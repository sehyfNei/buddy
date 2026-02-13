# Buddy Reader — Work In Progress

> Last updated: 2026-02-13

---

## What Is Buddy?

Buddy is a **cognitive companion** (not a chatbot) that detects when a reader is struggling and responds appropriately. The **Reader** is the first surface — because reading is where struggle is most visible (re-reading, long pauses, confusion, skipping sections).

**Reader = Body. Buddy = Soul.**

Stack: **Python (FastAPI) + HTML/CSS/JS + PDF.js** — no Node, no npm, no build step.

---

## Project Structure (Complete)

```
bUDDY/
├── soul.md                     # Project philosophy
├── app.py                      # Main entry point — starts FastAPI server
├── requirements.txt            # 6 Python dependencies
├── config.yaml                 # Model config (provider, model, endpoint, params)
├── WIP.md                      # This file
│
├── buddy/
│   ├── core/
│   │   ├── state_detector.py   # FOCUSED / STUCK / TIRED / IDLE detection
│   │   ├── mode_router.py      # Routes state → response strategy
│   │   └── tone_controller.py  # Wraps LLM prompts with tone per mode
│   │
│   ├── llm/
│   │   ├── base.py             # Abstract LLMProvider interface
│   │   ├── ollama_provider.py  # Ollama integration
│   │   ├── vllm_provider.py    # vLLM integration
│   │   └── openai_compat.py    # Any OpenAI-compatible API
│   │
│   ├── reader/
│   │   ├── pdf_handler.py      # PDF text extraction via PyMuPDF
│   │   ├── signals.py          # Reading behavior signal collector
│   │   └── session.py          # Reading session state (page, highlights)
│   │
│   ├── memory/
│   │   └── session_memory.py   # In-memory chat history (not persistent)
│   │
│   └── api/
│       └── routes.py           # All FastAPI endpoints
│
├── frontend/
│   ├── index.html              # Main reader UI
│   ├── style.css               # Dark theme styling
│   └── app.js                  # PDF rendering, signal capture, chat, state polling
│
└── tests/
    └── test_state_detector.py  # 10 tests — all passing
```

---

## What's Done (v1 Implementation)

### Step 1: Project Skeleton + Config — DONE
- [x] All folders and `__init__.py` files created
- [x] `requirements.txt` with 6 dependencies (fastapi, uvicorn, python-multipart, pymupdf, pyyaml, httpx)
- [x] `config.yaml` with LLM provider/model/endpoint settings + reader + buddy config
- [x] Dependencies installed and verified

### Step 2: PDF Reader (Body) — DONE
- [x] `pdf_handler.py` — extracts text from PDF using PyMuPDF (from file path or bytes)
- [x] `session.py` — tracks reading session state (current page, highlights, document)
- [x] Frontend renders PDFs using PDF.js (loaded from CDN)
- [x] Upload PDF via file picker → rendered in canvas
- [x] Page navigation (prev/next buttons + arrow keys)

### Step 3: LLM Module (Modular Engine) — DONE
- [x] `base.py` — abstract `LLMProvider` with `generate()` and `health_check()`
- [x] `ollama_provider.py` — calls Ollama `/api/chat` endpoint
- [x] `vllm_provider.py` — calls vLLM OpenAI-compatible endpoint
- [x] `openai_compat.py` — generic OpenAI-compatible provider (LM Studio, LocalAI, etc.)
- [x] Provider selection driven by `config.yaml` — swap models without touching code

### Step 4: Reading Signals + State Detection — DONE
- [x] `signals.py` — collects events: page_view, scroll_back, selection, idle, page_skip
- [x] `state_detector.py` — rule-based heuristics classify user state:
  - Re-read same page 2+ times → **STUCK**
  - Long idle (>90s) → **TIRED**
  - Medium idle (>30s) → **IDLE**
  - Fast page skipping (3+ pages) → **STUCK**
  - Long time on page + scroll backs → **STUCK**
  - Normal reading → **FOCUSED** (Buddy stays quiet)
- [x] Frontend sends signals to `/api/signal` endpoint
- [x] 10 unit tests — all passing

### Step 5: Mode Router + Tone Controller — DONE
- [x] `mode_router.py` — maps states to response modes:
  - STUCK → EXPLAIN (simplify, break down, analogies)
  - TIRED → NUDGE (short, warm, suggest break)
  - IDLE → CHECK_IN (gentle "still there?")
  - FOCUSED → SILENT (don't interrupt)
- [x] `tone_controller.py` — builds system/user prompts per mode with appropriate tone

### Step 6: Buddy Panel Integration (Body + Soul) — DONE
- [x] `/api/state` endpoint — aggregates signals → detects state → generates intervention
- [x] `/api/chat` endpoint — direct conversation with Buddy about the document
- [x] `/api/health` endpoint — checks if LLM is reachable
- [x] Frontend polls `/api/state` every 5 seconds
- [x] Buddy panel shows proactive messages when struggle detected
- [x] Buddy stays quiet when user is FOCUSED
- [x] Intervention cooldown (60s default) prevents spamming
- [x] Chat input for direct questions about the reading material
- [x] Health indicator dot (green = LLM connected, red = disconnected)

---

## API Endpoints

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/api/upload` | Upload a PDF file, start new session |
| GET | `/api/page/{n}` | Get extracted text for page n |
| POST | `/api/signal` | Receive a reading behavior event |
| GET | `/api/state` | Get current detected state + optional intervention |
| POST | `/api/chat` | Send a message to Buddy, get response |
| GET | `/api/health` | Check server + LLM connectivity |
| POST | `/api/highlight` | Save a text highlight |

---

## How to Run

```bash
# 1. Start your local model
ollama pull llama3.2:3b
ollama serve

# 2. Start Buddy
pip install -r requirements.txt
python app.py

# 3. Open browser → http://localhost:8000
```

---

## What's NOT Done Yet (Future Work)

### High Priority — Next Steps
- [ ] **Test end-to-end with a real PDF + running Ollama** — verify the full loop works
- [ ] **PDF.js vendored locally** — currently loaded from CDN, plan says vendor it in `frontend/lib/pdfjs/`
- [ ] **Text selection highlighting** — frontend captures selections but no visual persistence
- [ ] **Highlights panel** — UI to view saved highlights
- [ ] **Notes panel** — save and view notes alongside reading
- [ ] **Better page skip detection** — track when user jumps multiple pages at once
- [ ] **Reading speed calculation** — `reading_speed_wpm` field exists but isn't populated

### Medium Priority — Enhancements
- [ ] **Persistent memory** — save session/conversation to disk (currently in-memory only, lost on restart)
- [ ] **Multiple sessions** — support switching between documents
- [ ] **File browser** — select PDFs from local filesystem instead of upload-only
- [ ] **Terminal/file access** — subprocess execution for deeper OS integration (like OpenClaw)
- [ ] **Streaming responses** — stream LLM output to UI instead of waiting for full response
- [ ] **Better signal aggregation** — time-windowed analysis instead of cumulative
- [ ] **Configurable thresholds** — expose state detection thresholds in config.yaml

### Low Priority — Polish
- [ ] **Responsive design** — mobile/tablet layout
- [ ] **Dark/light theme toggle**
- [ ] **PDF search** — find text within the document
- [ ] **PDF zoom controls**
- [ ] **Export highlights/notes** to file
- [ ] **ML-based state detection** — replace rule-based heuristics with a trained model
- [ ] **Multi-user support** — session management for multiple concurrent users

---

## Key Design Decisions Made

1. **Single-user v1** — no auth, no multi-session. One user, one document at a time.
2. **Rule-based detection** — no ML for state detection in v1. Simple thresholds that are easy to tune.
3. **PDF.js from CDN** — faster to get running; should be vendored for offline use later.
4. **In-memory everything** — no database, no file persistence. Restart = clean slate.
5. **Cooldown on interventions** — Buddy won't spam. 60-second minimum between proactive messages.
6. **FOCUSED = SILENT** — the most important rule. Buddy never interrupts flow state.
7. **Config-driven LLM** — change provider/model in `config.yaml`, no code changes needed.

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | >=0.104.0 | Web framework |
| uvicorn | >=0.24.0 | ASGI server |
| python-multipart | >=0.0.6 | File upload support |
| pymupdf | >=1.23.0 | PDF text extraction |
| pyyaml | >=6.0 | Config file loading |
| httpx | >=0.25.0 | Async HTTP client for LLM APIs |

All free. All open source. No API keys needed.

---

## Test Status

```
tests/test_state_detector.py — 10/10 PASSED
```

Tests cover: focused reading, re-read detection, scroll-back + re-read combo, long page time, page skipping, long idle (tired), medium idle, short idle, empty signals, priority ordering (stuck > idle).
