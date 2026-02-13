import uuid
import time
import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
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
from ..memory.session_store import SessionStore
from ..knowledge.graph import KnowledgeGraph
from ..knowledge.extractor import ConceptExtractor
from ..knowledge.retriever import GraphRetriever
from ..knowledge.updater import GraphUpdater

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

# ── Knowledge graph (v1.5) ─────────────────────────────────────────────────

_graph: KnowledgeGraph | None = None
_extractor: ConceptExtractor | None = None
_retriever: GraphRetriever | None = None
_updater: GraphUpdater | None = None
_session_store: SessionStore | None = None
_doc_id: str = ""  # current document ID in graph
_extraction_in_progress: bool = False


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


def init_knowledge(config: dict) -> None:
    """Initialize knowledge graph, session store, and related components."""
    global _graph, _extractor, _retriever, _updater, _session_store

    data_dir = config.get("knowledge", {}).get("data_dir", "data")

    _graph = KnowledgeGraph(db_path=f"{data_dir}/graph.db")
    _session_store = SessionStore(db_path=f"{data_dir}/sessions.db")

    if _llm:
        _extractor = ConceptExtractor(llm=_llm, graph=_graph)
    _retriever = GraphRetriever(graph=_graph)
    _updater = GraphUpdater(graph=_graph)

    logger.info("Knowledge graph and session store initialized")


# ── Request/Response models ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    page: int | None = None

class ChatResponse(BaseModel):
    reply: str
    state: str
    mode: str
    concepts: list[dict] = []

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
    extracting: bool = False


# ── Background extraction ──────────────────────────────────────────────────

async def _run_extraction(doc_id: str, pages: list[dict]) -> None:
    """Run concept extraction in background after upload."""
    global _extraction_in_progress
    _extraction_in_progress = True
    try:
        if _extractor:
            result = await _extractor.extract_from_document(doc_id, pages)
            logger.info(
                "Background extraction done: %d concepts, %d claims, %d edges",
                result.concepts_added, result.claims_added, result.edges_added,
            )
    except Exception as e:
        logger.error("Background extraction failed: %s", e)
    finally:
        _extraction_in_progress = False


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...), background_tasks: BackgroundTasks = None) -> SessionInfo:
    global _session, _signals, _memory, _doc_id

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    max_mb = _config.get("reader", {}).get("max_upload_mb", 50)
    data = await file.read()
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {max_mb}MB).")

    handler = PDFHandler()
    doc = handler.extract_from_bytes(data, filename=file.filename)

    session_id = str(uuid.uuid4())
    _doc_id = str(uuid.uuid4())
    _session = ReadingSession(session_id=session_id, document=doc)
    _signals = SignalCollector()
    _memory = SessionMemory()

    # Persist session
    if _session_store:
        _session_store.create_session(session_id, doc_id=_doc_id, doc_name=file.filename)

    logger.info("New session %s: %s (%d pages)", session_id, doc.filename, doc.total_pages)

    # Start background concept extraction
    extracting = False
    if _extractor and background_tasks:
        pages = [{"page": p.page_num, "text": p.text} for p in doc.pages]
        background_tasks.add_task(_run_extraction, _doc_id, pages)
        extracting = True
        logger.info("Started background concept extraction for %s", doc.filename)

    return SessionInfo(
        session_id=session_id,
        filename=doc.filename,
        total_pages=doc.total_pages,
        current_page=1,
        extracting=extracting,
    )


@router.get("/page/{page_num}")
async def get_page_text(page_num: int) -> dict:
    if not _session or not _session.has_document:
        raise HTTPException(400, "No document loaded.")
    if page_num < 1 or page_num > _session.total_pages:
        raise HTTPException(404, "Page not found.")

    _session.current_page = page_num

    # Get concepts for this page from graph
    concepts = []
    if _retriever and _doc_id:
        page_concepts = _graph.get_concepts_for_page(_doc_id, page_num) if _graph else []
        concepts = [{"name": c.label, "definition": c.data.get("definition", "")} for c in page_concepts[:5]]

    return {
        "page": page_num,
        "text": _session.document.get_page_text(page_num),
        "total_pages": _session.total_pages,
        "concepts": concepts,
    }


@router.post("/signal")
async def receive_signal(req: SignalRequest) -> dict:
    event = SignalEvent(
        event_type=req.event_type,
        page=req.page,
        data=req.data,
    )
    _signals.record(event)

    # Update graph with re-read signals
    if _updater and _doc_id and req.event_type == "page_view":
        _updater.record_reread(_doc_id, req.page)

    return {"status": "ok"}


@router.get("/state")
async def get_state() -> StateResponse:
    global _last_intervention_time

    signals = _signals.aggregate()
    state = _detector.detect(signals)
    decision = _mode_router.route(state)

    # Record state episode
    if _session_store and _session and state != UserState.FOCUSED:
        _session_store.add_episode(
            _session.session_id, state.value,
            _session.current_page if _session else 0,
        )

    # Record stuck/tired in graph
    if _updater and _doc_id and state in (UserState.STUCK, UserState.TIRED):
        page = _session.current_page if _session else 0
        _updater.record_stuck(_doc_id, page, state)

    message = None
    cooldown = _config.get("buddy", {}).get("intervention_cooldown_s", 60)
    quiet_when_focused = _config.get("buddy", {}).get("quiet_when_focused", True)

    if decision.should_intervene:
        now = time.time()
        if now - _last_intervention_time >= cooldown:
            if not (quiet_when_focused and state == UserState.FOCUSED):
                # Build graph-enriched context
                passage = _session.get_context_text() if _session else ""
                context = passage

                if _retriever and _doc_id and _session:
                    bundle = _retriever.get_context_bundle(
                        _doc_id, _session.current_page, passage
                    )
                    if not bundle.is_empty:
                        context = bundle.to_context_string()

                message = _tone.build_user_prompt(decision.mode)

                if _llm and decision.mode != ResponseMode.SILENT:
                    try:
                        system_prompt = _tone.build_system_prompt(decision.mode, context)
                        user_prompt = _tone.build_user_prompt(decision.mode)
                        resp = await _llm.generate(user_prompt, context=system_prompt)
                        message = resp.text
                        _memory.add("buddy", message)
                        if _session_store and _session:
                            _session_store.add_message(_session.session_id, "buddy", message)
                    except Exception as e:
                        logger.error("LLM call failed during intervention: %s", e)
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
    if _session_store and _session:
        _session_store.add_message(_session.session_id, "user", req.message)

    # Build graph-enriched context
    passage = ""
    if _session and _session.has_document:
        passage = _session.get_context_text()

    context = passage
    response_concepts = []

    if _retriever and _doc_id and _session:
        bundle = _retriever.get_context_bundle(
            _doc_id, _session.current_page, passage
        )
        if not bundle.is_empty:
            context = bundle.to_context_string()
            response_concepts = bundle.concepts

    # Detect state for tone
    signals = _signals.aggregate()
    state = _detector.detect(signals)

    # For direct chat, always use EXPLAIN mode (user is asking)
    mode = ResponseMode.EXPLAIN
    system_prompt = _tone.build_system_prompt(mode, context)

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
    if _session_store and _session:
        _session_store.add_message(_session.session_id, "buddy", reply)

    return ChatResponse(
        reply=reply,
        state=state.value,
        mode=mode.value,
        concepts=response_concepts,
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
        "graph_ready": _graph is not None,
        "extraction_in_progress": _extraction_in_progress,
    }


@router.post("/highlight")
async def add_highlight(page: int, text: str) -> dict:
    if _session:
        _session.add_highlight(page, text)
    if _updater and _doc_id:
        _updater.record_highlight(_doc_id, page, text)
    return {"status": "ok"}


@router.get("/concepts")
async def get_concepts() -> dict:
    """Get all concepts for the current document (for concept map UI)."""
    if not _retriever or not _doc_id:
        return {"concepts": [], "stats": {}}

    concepts = _retriever.get_concept_summary(_doc_id)
    stats = _graph.get_doc_stats(_doc_id) if _graph else {}
    return {"concepts": concepts, "stats": stats}


@router.get("/concepts/page/{page_num}")
async def get_page_concepts(page_num: int) -> dict:
    """Get concepts for a specific page."""
    if not _retriever or not _doc_id:
        return {"concepts": [], "prerequisites": []}

    bundle = _retriever.get_context_bundle(_doc_id, page_num)
    return {
        "concepts": bundle.concepts,
        "prerequisites": bundle.prerequisites,
        "claims": bundle.claims,
        "confusion_history": bundle.confusion_history,
    }


@router.get("/sessions")
async def get_sessions() -> dict:
    """Get past sessions for the current document."""
    if not _session_store or not _doc_id:
        return {"sessions": []}
    sessions = _session_store.get_sessions_for_doc(_doc_id)
    struggle = _session_store.get_doc_struggle_summary(_doc_id)
    return {"sessions": sessions, **struggle}
