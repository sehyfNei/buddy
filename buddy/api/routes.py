import uuid
import time
import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from ..llm.base import LLMProvider
from ..llm.ollama_provider import OllamaProvider
from ..llm.vllm_provider import VLLMProvider
from ..llm.openai_compat import OpenAICompatProvider
from ..core.state_detector import StateDetector, UserState
from ..core.mode_router import ModeRouter, ResponseMode
from ..core.tone_controller import ToneController
from ..reader.pdf_handler import PDFHandler
from ..reader.signals import SignalCollector, SignalEvent
from ..reader.session import ReadingSession
from ..memory.session_memory import SessionMemory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ── Global state (single-user v1) ──────────────────────────────────────────

_session: ReadingSession | None = None
_signals = SignalCollector()
_memory = SessionMemory()
_detector = StateDetector()
_mode_router = ModeRouter()
_tone = ToneController()
_llm: LLMProvider | None = None
_last_intervention_time: float = 0.0
_config: dict = {}


def load_config(config_path: str = "config.yaml") -> dict:
    global _config
    path = Path(config_path)
    if path.exists():
        with open(path, "r") as f:
            _config = yaml.safe_load(f) or {}
    else:
        _config = {}
    return _config


def init_llm(config: dict) -> LLMProvider:
    global _llm
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "ollama")
    model = llm_cfg.get("model", "llama3.2:3b")
    endpoint = llm_cfg.get("endpoint", "http://localhost:11434")
    temperature = llm_cfg.get("temperature", 0.7)
    max_tokens = llm_cfg.get("max_tokens", 512)

    providers = {
        "ollama": OllamaProvider,
        "vllm": VLLMProvider,
        "openai_compat": OpenAICompatProvider,
    }

    cls = providers.get(provider, OllamaProvider)
    _llm = cls(model=model, endpoint=endpoint, temperature=temperature, max_tokens=max_tokens)
    logger.info("LLM initialized: provider=%s model=%s endpoint=%s", provider, model, endpoint)
    return _llm


# ── Request/Response models ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    page: int | None = None

class ChatResponse(BaseModel):
    reply: str
    state: str
    mode: str

class SignalRequest(BaseModel):
    event_type: str
    page: int = 0
    data: dict = {}

class StateResponse(BaseModel):
    state: str
    should_intervene: bool
    mode: str
    reason: str
    message: str | None = None

class SessionInfo(BaseModel):
    session_id: str
    filename: str
    total_pages: int
    current_page: int


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)) -> SessionInfo:
    global _session, _signals, _memory

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    max_mb = _config.get("reader", {}).get("max_upload_mb", 50)
    data = await file.read()
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {max_mb}MB).")

    handler = PDFHandler()
    doc = handler.extract_from_bytes(data, filename=file.filename)

    _session = ReadingSession(session_id=str(uuid.uuid4()), document=doc)
    _signals = SignalCollector()
    _memory = SessionMemory()

    logger.info("New session %s: %s (%d pages)", _session.session_id, doc.filename, doc.total_pages)

    return SessionInfo(
        session_id=_session.session_id,
        filename=doc.filename,
        total_pages=doc.total_pages,
        current_page=1,
    )


@router.get("/page/{page_num}")
async def get_page_text(page_num: int) -> dict:
    if not _session or not _session.has_document:
        raise HTTPException(400, "No document loaded.")
    if page_num < 1 or page_num > _session.total_pages:
        raise HTTPException(404, "Page not found.")

    _session.current_page = page_num
    return {
        "page": page_num,
        "text": _session.document.get_page_text(page_num),
        "total_pages": _session.total_pages,
    }


@router.post("/signal")
async def receive_signal(req: SignalRequest) -> dict:
    event = SignalEvent(
        event_type=req.event_type,
        page=req.page,
        data=req.data,
    )
    _signals.record(event)
    return {"status": "ok"}


@router.get("/state")
async def get_state() -> StateResponse:
    global _last_intervention_time

    signals = _signals.aggregate()
    state = _detector.detect(signals)
    decision = _mode_router.route(state)

    message = None
    cooldown = _config.get("buddy", {}).get("intervention_cooldown_s", 60)
    quiet_when_focused = _config.get("buddy", {}).get("quiet_when_focused", True)

    if decision.should_intervene:
        now = time.time()
        if now - _last_intervention_time >= cooldown:
            if not (quiet_when_focused and state == UserState.FOCUSED):
                passage = _session.get_context_text() if _session else ""
                message = _tone.build_user_prompt(decision.mode)

                if _llm and decision.mode != ResponseMode.SILENT:
                    try:
                        system_prompt = _tone.build_system_prompt(decision.mode, passage)
                        user_prompt = _tone.build_user_prompt(decision.mode)
                        resp = await _llm.generate(user_prompt, context=system_prompt)
                        message = resp.text
                        _memory.add("buddy", message)
                    except Exception as e:
                        logger.error("LLM call failed during intervention: %s", e)
                        # Fall back to static message
                        message = _tone.build_user_prompt(decision.mode)

                _last_intervention_time = now

    return StateResponse(
        state=state.value,
        should_intervene=decision.should_intervene,
        mode=decision.mode.value,
        reason=decision.reason,
        message=message,
    )


@router.post("/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    if not _llm:
        raise HTTPException(503, "LLM not configured. Check config.yaml and ensure your model server is running.")

    if req.page and _session:
        _session.current_page = req.page

    _memory.add("user", req.message)

    # Get current reading context
    passage = ""
    if _session and _session.has_document:
        passage = _session.get_context_text()

    # Detect state for tone
    signals = _signals.aggregate()
    state = _detector.detect(signals)
    decision = _mode_router.route(state)

    # For direct chat, always use EXPLAIN mode (user is asking)
    mode = ResponseMode.EXPLAIN
    system_prompt = _tone.build_system_prompt(mode, passage)

    # Add conversation history to context
    history = _memory.get_context_string()
    if history:
        system_prompt += f"\n\nRecent conversation:\n{history}"

    try:
        resp = await _llm.generate(req.message, context=system_prompt)
        reply = resp.text
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        raise HTTPException(502, f"Model server error: {e}")

    _memory.add("buddy", reply)

    return ChatResponse(
        reply=reply,
        state=state.value,
        mode=mode.value,
    )


@router.get("/health")
async def health() -> dict:
    llm_ok = False
    if _llm:
        llm_ok = await _llm.health_check()
    return {
        "status": "ok",
        "llm_connected": llm_ok,
        "session_active": _session is not None and _session.has_document,
    }


@router.post("/highlight")
async def add_highlight(page: int, text: str) -> dict:
    if _session:
        _session.add_highlight(page, text)
    return {"status": "ok"}
