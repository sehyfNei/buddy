# Buddy Reader — Work In Progress

> Last updated: 2026-02-13 (end of session 2)

---

## What Is Buddy?

Buddy is a **cognitive companion** (not a chatbot) that detects when a reader is struggling and responds appropriately. The **Reader** is the first surface — because reading is where struggle is most visible (re-reading, long pauses, confusion, skipping sections).

**Reader = Body. Buddy = Soul.**

Stack: **Python (FastAPI) + HTML/CSS/JS + PDF.js** — no Node, no npm, no build step.

---

## Project Structure

```
bUDDY/
├── soul.md                     # Project philosophy
├── app.py                      # Main entry — FastAPI server + startup/shutdown hooks
├── requirements.txt            # 6 Python dependencies (no new ones since v1)
├── config.yaml                 # Model + reader + buddy + knowledge config
├── WIP.md                      # This file — session continuity
├── ARCHITECTURE-v1.5-knowledge-graph.md  # Full v1.5 design doc
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
│   │   ├── session_memory.py   # In-memory chat history (v1 compat, still used for fast access)
│   │   └── session_store.py    # SQLite-backed persistent sessions (v1.5)
│   │
│   ├── knowledge/              # v1.5 Knowledge Graph
│   │   ├── graph.py            # SQLite node/edge graph — thread-safe with Lock
│   │   ├── extractor.py        # LLM-powered concept + claim extraction
│   │   ├── retriever.py        # Context bundle assembly from graph
│   │   └── updater.py          # Incremental graph updates from signals
│   │
│   └── api/
│       └── routes.py           # All endpoints (v1 + v1.5 graph-enriched)
│
├── frontend/
│   ├── index.html              # Main reader UI (with concepts bar)
│   ├── style.css               # Dark theme + concept chips styling
│   └── app.js                  # PDF rendering, signal capture, chat, concepts, state polling
│
├── data/                       # Persistent storage (gitignored, created at runtime)
│   ├── graph.db                # Knowledge graph (concepts, claims, edges)
│   └── sessions.db             # Chat history, state episodes
│
└── tests/
    ├── test_state_detector.py  # 10 tests
    └── test_knowledge_graph.py # 21 tests
```

---

## What's Complete

### v1 — Core Reader + Buddy (all 6 steps done)
- PDF upload + rendering via PDF.js
- Reading signal capture (page views, scroll-backs, selections, idle)
- Rule-based state detection (FOCUSED/STUCK/TIRED/IDLE)
- Mode routing + tone-controlled LLM prompts
- Modular LLM (Ollama/vLLM/OpenAI-compat, config-driven)
- Buddy chat panel with proactive interventions
- 10 state detector tests passing

### v1.5 M1 — Schema + Ingestion + Persistence (done)
- SQLite knowledge graph (nodes: document, page_chunk, concept, claim, signal, annotation)
- Edges: mentions, depends_on, explains, supports, confused_at, annotated
- LLM-powered concept + claim extraction on PDF upload (background task)
- Persistent sessions, chat messages, state episodes in sessions.db
- Thread-safe SQLite with `threading.Lock` on all operations
- 21 graph tests passing

### v1.5 M2 — Retrieval-in-Chat Integration (done)
- `/api/chat` and `/api/state` use graph-enriched context bundles
- Context bundle: passage + concepts + prerequisites + claims + confusion history
- 3 new endpoints: `/api/concepts`, `/api/concepts/page/{n}`, `/api/sessions`
- Chat responses include related concepts

### Bug fixes applied (session 2)
- Architecture doc updated from "PLANNING" to reflect actual implementation status
- Config knobs `extract_on_upload` and `max_concepts_per_page` wired into runtime
- Frontend concepts bar fetches + displays page concepts with prereq indicators
- `threading.Lock` on all SQLite ops in graph.py and session_store.py
- State episode logging deduplicated (only on state change or 30s gap)
- Graceful `shutdown` event closes all DB connections

---

## API Endpoints

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/api/upload` | Upload PDF, start session, trigger background extraction |
| GET | `/api/page/{n}` | Get page text + concepts from graph |
| POST | `/api/signal` | Receive reading behavior event |
| GET | `/api/state` | Detected state + optional intervention (deduped logging) |
| POST | `/api/chat` | Chat with Buddy (graph-enriched context) |
| GET | `/api/health` | Server + LLM + graph status |
| POST | `/api/highlight` | Save highlight + boost graph concept weights |
| GET | `/api/concepts` | All concepts for current document |
| GET | `/api/concepts/page/{n}` | Concepts + prereqs + claims + confusion for page |
| GET | `/api/sessions` | Past sessions + struggle summary for document |

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

## Where to Pick Up Next (Prioritized)

### 1. End-to-end test with real PDF + Ollama (HIGH — never verified)
The full loop has never been tested live. Upload a PDF, read a few pages, trigger STUCK detection, verify Buddy responds with graph-enriched context. This should happen before adding more features.

### 2. M3 remainder: Stuck Assist + Summaries
- [ ] **"Stuck Assist" flow** — when STUCK detected, look up prereq chain for current page concepts, generate targeted help that addresses the root confusion (not just the current passage)
- [ ] **Precomputed section summaries** — at upload time, generate short summaries per section/chapter for "where am I?" context
- [ ] **"Where am I?" endpoint** — `/api/summary/page/{n}` returning section context + progress

### 3. M4: UI panels
- [ ] **Concept sidebar** (collapsed by default) — full concept map for document
- [ ] **"Stuck Assist" button** — manual trigger in Buddy panel
- [ ] **Memory timeline** — visual history of struggle points + resolved concepts

### 4. Remaining v1 polish
- [ ] **Vendor PDF.js locally** — currently CDN-loaded, not fully offline/local-first
- [ ] **Text selection highlighting** — visual persistence of selections
- [ ] **Highlights/Notes panels** — view and manage saved annotations
- [ ] **Page skip detection** — track multi-page jumps as signals
- [ ] **Reading speed calculation** — populate `reading_speed_wpm` field
- [ ] **Streaming LLM responses** — stream to UI instead of waiting for full response

### 5. Longer-term
- [ ] Multiple sessions / document switching
- [ ] File browser for local PDF selection
- [ ] Configurable detection thresholds in config.yaml
- [ ] Eval scripts for retrieval quality + noise rate
- [ ] ML-based state detection (replace heuristics)
- [ ] Multi-user support

---

## Design Decisions (Resolved)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Single-user | Yes (v1) | Simplicity. Globals + single session. |
| State detection | Rule-based heuristics | No ML needed yet. Easy to tune thresholds. |
| PDF.js | CDN (not vendored) | Faster setup. Should vendor for offline. |
| Graph granularity | Concepts + Claims | Both extracted by LLM at upload time. |
| Edge generation | Pure LLM | All relationships inferred by model, no heuristic fallback. |
| Storage | Split (graph.db + sessions.db) | Different lifecycles — graph persists, sessions can be pruned. |
| Threading | Lock per DB instance | Protects against background extraction + request handler overlap. |
| Episode dedup | 30s min gap + state change | Prevents poll-inflated struggle counts. |
| Intervention cooldown | 60s configurable | Buddy doesn't spam. |
| FOCUSED = SILENT | Always | The most important rule. |

---

## Config Reference

```yaml
llm:
  provider: ollama              # ollama | vllm | openai_compat
  model: llama3.2:3b
  endpoint: http://localhost:11434
  temperature: 0.7
  max_tokens: 512

reader:
  max_upload_mb: 50
  signals_interval_ms: 5000

buddy:
  quiet_when_focused: true
  intervention_cooldown_s: 60

knowledge:
  data_dir: data
  extract_on_upload: true       # gates background concept extraction
  max_concepts_per_page: 10     # caps extractor output per page
```

---

## Test Status

```
tests/test_state_detector.py  — 10/10 PASSED  (state detection heuristics)
tests/test_knowledge_graph.py — 21/21 PASSED  (graph CRUD, queries, retriever, updater)
Total: 31/31 PASSED
```

---

## Git History

| Commit | What |
|--------|------|
| `4ba5878` | Initial commit: full v1 implementation (27 files) |
| `c6a76f9` | v1.5 architecture plan document |
| `c24be44` | v1.5 M1/M2: knowledge graph, extraction, retrieval, persistence |
| `39b024e` | Fix 6 critical gaps: docs, config, frontend, threading, dedup, shutdown |

Remote: `https://github.com/sehyfNei/buddy.git` (branch: `main`)
