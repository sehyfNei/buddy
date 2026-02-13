# Buddy v1.5 — Memory Map / Knowledge Graph

> Status: **PLANNING** — not yet implemented
> Created: 2026-02-13
> Depends on: v1 (complete)

---

## Why This Exists

v1 Buddy can detect struggle and respond in the moment. But it forgets everything between sessions, doesn't understand *what* the reader is struggling with (only *that* they're struggling), and can't connect ideas across pages.

The Knowledge Graph gives Buddy **understanding of the document** — not just the text on the current page, but the concepts, their relationships, and the reader's personal history with them.

**Current gap:** memory is short chat history + basic highlights. No concept awareness, no cross-session continuity, no "what depends on what."

---

## Guardrails (Buddy Keeps Its Soul)

These are non-negotiable:

1. **Local-first, on-device only** — no cloud, no external APIs for graph storage
2. **State-aware first, graph second** — graph supports clarity, never creates noise
3. **Start lightweight, evolve later** — no Neo4j, no complex infra in v1.5
4. **FOCUSED = SILENT still applies** — graph doesn't change the core rule

---

## What The Graph Enables (v1.5 Scope)

| Capability | Current (v1) | With Graph (v1.5) |
|---|---|---|
| "Where am I?" | Page number only | Section summary + concept context |
| "What depends on this?" | Nothing | Prerequisite/concept links |
| "I'm stuck" rescue | Generic passage simplification | Targeted simplification from adjacent concepts |
| Cross-session memory | None (reset on restart) | Knows what user struggled with before |
| Chat context | Current page + 10 recent messages | Current page + related concepts + prereq chain + confusion history |

---

## Data Model

### Entities (Nodes)

| Entity | Description | Source |
|--------|-------------|--------|
| **Document** | The uploaded PDF | Upload event |
| **PageChunk** | Page range + extracted text span | PDF ingestion |
| **Concept** | A term, topic, or idea | LLM extraction at upload |
| **UserSignal** | A stuck/tired/idle episode | State detector |
| **UserAnnotation** | A highlight or note | User action |

> **Phase 2 addition:** `Claim` / `Idea` nodes (specific arguments or assertions within text)

### Relationships (Edges)

| Edge | From → To | Meaning |
|------|-----------|---------|
| `mentions` | PageChunk → Concept | This chunk discusses this concept |
| `depends_on` | Concept → Concept | Understanding A requires understanding B |
| `explains` | Concept → Concept | A helps clarify B (lighter than depends_on) |
| `confused_at` | UserSignal → Concept or PageChunk | User was struggling here |
| `annotated` | UserAnnotation → PageChunk | User highlighted/noted this section |

### Storage: Single SQLite File

```
bUDDY/data/graph.db
```

Schema (node/edge style — no graph DB needed):

```sql
-- Nodes
CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,  -- 'document', 'page_chunk', 'concept', 'signal', 'annotation'
    label       TEXT NOT NULL,  -- human-readable name
    data        TEXT,           -- JSON blob for type-specific fields
    doc_id      TEXT,           -- which document this belongs to
    confidence  REAL DEFAULT 1.0,
    created_at  REAL NOT NULL
);

-- Edges
CREATE TABLE edges (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES nodes(id),
    target_id   TEXT NOT NULL REFERENCES nodes(id),
    rel_type    TEXT NOT NULL,  -- 'mentions', 'depends_on', 'explains', 'confused_at', 'annotated'
    weight      REAL DEFAULT 1.0,
    data        TEXT,           -- JSON blob for edge metadata
    created_at  REAL NOT NULL
);

CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_rel ON edges(rel_type);
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_doc ON nodes(doc_id);
```

**Why SQLite:**
- Already local-first (single file, no server)
- Matches v1 philosophy of zero infra
- Node/edge tables give graph-like queries without graph DB complexity
- Easy to migrate later if needed

---

## Ingestion Pipeline

### On PDF Upload (bulk extraction)

```
Upload PDF
    │
    ├── 1. Split pages into chunks (existing pdf_handler.py)
    │
    ├── 2. For each chunk:
    │      ├── Extract concepts (LLM prompt + heuristic fallback)
    │      ├── Create PageChunk node
    │      └── Create Concept nodes + 'mentions' edges
    │
    ├── 3. Cross-chunk concept linking:
    │      ├── Identify shared concepts across chunks
    │      └── Infer 'depends_on' / 'explains' edges (LLM prompt)
    │
    └── 4. Cache compact section summaries
           └── Store as data blob on PageChunk nodes
```

**Concept extraction prompt (for LLM):**
```
Given this passage from a document, extract the key concepts (terms, topics, ideas).
For each concept, note:
- The concept name (short, 1-4 words)
- A one-sentence definition in simple language
- Any prerequisite concepts needed to understand it

Passage:
---
{chunk_text}
---

Return as JSON array.
```

**Heuristic fallback (when LLM is unavailable):**
- Extract capitalized multi-word phrases
- Extract terms that appear in bold/italic (from PDF formatting)
- Extract terms that repeat across multiple pages
- No relationship inference without LLM

**Confidence scoring:**
- LLM-extracted concepts: confidence 0.8
- Heuristic-extracted: confidence 0.5
- User-confirmed (via highlight/question): confidence 1.0
- Edges get confidence from source concept scores

### Incremental Updates (During Reading)

| Event | Graph Update |
|-------|-------------|
| User highlights text | Strengthen related concept weights (+0.1) |
| User asks about concept X | Mark X as "active interest", boost retrieval priority |
| STUCK detected on page N | Add `confused_at` edge from signal → page chunk + concepts |
| User re-reads page | Increase weight on that page's concept edges |
| User asks "what is X?" | If X not in graph, create new concept node (confidence 0.6) |

---

## Retrieval Strategy

### Current (v1) Context Assembly

```
context = current_passage + recent_chat_history
```

### Upgraded (v1.5) Context Bundle

```
context = {
    passage_window:     current page ± 1 page text,
    related_concepts:   top 5 concepts mentioned on current page,
    prereq_chain:       concepts that current concepts depend on,
    confusion_history:  past confused_at signals for these concepts,
    chat_history:       last 10 messages (unchanged),
}
```

**Retrieval query (pseudo-SQL):**
```sql
-- Get concepts for current page
SELECT c.* FROM nodes c
JOIN edges e ON e.target_id = c.id
JOIN nodes p ON p.id = e.source_id
WHERE p.type = 'page_chunk'
  AND p.data LIKE '%"page": {current_page}%'
  AND e.rel_type = 'mentions'
ORDER BY e.weight DESC
LIMIT 5;

-- Get prerequisites for those concepts
SELECT prereq.* FROM nodes prereq
JOIN edges e ON e.target_id = prereq.id
WHERE e.source_id IN ({concept_ids})
  AND e.rel_type = 'depends_on';

-- Get confusion history
SELECT s.* FROM nodes s
JOIN edges e ON e.source_id = s.id
WHERE e.target_id IN ({concept_ids})
  AND e.rel_type = 'confused_at'
ORDER BY s.created_at DESC
LIMIT 5;
```

**Latency budget:** graph retrieval must complete in <150ms locally.

---

## Personalization Loop

Uses existing state detector outputs as feedback:

| Pattern | Graph Response |
|---------|---------------|
| Repeatedly stuck on concept X | Increase simplification depth for X in prompts |
| Asks "what is Y?" across sessions | Precompute quick primer for Y, serve immediately |
| TIRED state detected | Switch retrieval to "next step only" (shorter context) |
| FOCUSED for extended period | Reduce graph context to minimum (don't slow things down) |
| Concept X was confusing, then resolved | Mark X as "understood" — reduce future intervention weight |

---

## Persistence + Lifecycle

### New Files

```
bUDDY/
├── data/
│   ├── graph.db          # Knowledge graph (nodes + edges)
│   └── sessions.db       # Chat summaries, state episodes, session metadata
```

### New Module

```
buddy/
├── knowledge/
│   ├── __init__.py
│   ├── graph.py          # Graph CRUD operations (SQLite)
│   ├── extractor.py      # Concept extraction (LLM + heuristic)
│   ├── retriever.py      # Context bundle assembly from graph
│   └── updater.py        # Incremental graph updates from signals
```

### Session Persistence

```sql
-- sessions.db
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    doc_id      TEXT,
    started_at  REAL,
    ended_at    REAL,
    summary     TEXT  -- LLM-generated session summary
);

CREATE TABLE chat_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(id),
    role        TEXT,
    content     TEXT,
    timestamp   REAL
);

CREATE TABLE state_episodes (
    id          TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(id),
    state       TEXT,  -- 'stuck', 'tired', 'idle', 'focused'
    page        INTEGER,
    duration_s  REAL,
    timestamp   REAL
);
```

---

## UX Plan (Progressive, Non-Intrusive)

### New UI Elements (all collapsed/hidden by default)

| Element | Where | When Visible |
|---------|-------|-------------|
| **Concept sidebar** | Below Buddy chat | User clicks "Concepts" toggle |
| **"Why this matters"** | Tooltip on concepts | Hover/tap on concept name |
| **"Stuck Assist"** | Button in Buddy panel | When state = STUCK |
| **Memory timeline** | Separate panel | User clicks "My Progress" |

### Stuck Assist Flow

```
User is STUCK on page 12
    │
    ├── Graph lookup: page 12 mentions concepts [A, B, C]
    ├── Concept B depends_on [X, Y]
    ├── User was confused_at [X] in previous session
    │
    └── Buddy says: "This section builds on [X], which tripped you up
                     last time too. Want me to start with a quick
                     refresher on [X] before we tackle this?"
```

This is the core value proposition — Buddy doesn't just simplify, it knows *where* the confusion originates.

---

## Evaluation Plan

### Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Retrieval relevance | >80% of returned concepts match page topic | Manual review on 5 test PDFs |
| Intervention usefulness | Stuck→Focused transitions improve vs v1 | Compare state logs with/without graph |
| Noise rate | <10% irrelevant concepts in context | Count unrelated concepts in bundles |
| Extraction accuracy | >70% valid concepts per chunk | Manual spot-check |
| Graph retrieval latency | <150ms | Timed queries on graph.db |

### Evaluation Method

1. Offline eval scripts (automated concept extraction + retrieval checks)
2. Manual reading sessions (team reads PDFs, reviews Buddy responses)
3. A/B comparison: v1 context vs v1.5 context on same passages

---

## Open Design Decisions

| Decision | Options | Current Lean |
|----------|---------|-------------|
| **Graph granularity** | Concept-only first vs include Claims/Arguments | **Concept-only first** — add Claims in phase 2 |
| **Edge generation** | Pure LLM vs hybrid heuristic+LLM | **Hybrid** — heuristics for mentions, LLM for depends_on/explains |
| **Precompute timing** | Upload-only vs background while reading | **Upload-time bulk + lightweight incremental** during reading |
| **Storage** | Single SQLite vs split DBs | **Split** — graph.db + sessions.db (different lifecycles) |
| **Explainability** | Show "why this concept suggested" or keep hidden | **Hidden by default**, show on hover/request |
| **Chunk size** | Per-page vs multi-page vs paragraph | **Per-page** to start (matches existing page model) |

---

## Milestone Roadmap

### M1 — Schema + Ingestion + Persistence (Week 1)

- [ ] Create `buddy/knowledge/` module with `graph.py`
- [ ] Implement SQLite schema (nodes + edges tables)
- [ ] Build concept extractor (LLM prompt + heuristic fallback)
- [ ] Wire into upload flow: PDF upload → chunk → extract → store
- [ ] Add `data/` directory with `graph.db` + `sessions.db`
- [ ] Persist chat messages and state episodes to `sessions.db`
- [ ] Migrate `session_memory.py` from in-memory to SQLite-backed

### M2 — Retrieval-in-Chat Integration (Week 2)

- [ ] Build `retriever.py` — context bundle assembly from graph
- [ ] Update `/api/chat` to use graph-enriched context
- [ ] Update `/api/state` interventions to reference concepts
- [ ] Add concept-aware system prompts to `tone_controller.py`
- [ ] Verify latency stays under 150ms for graph queries

### M3 — Proactive Summaries + Stuck Assist (Week 3)

- [ ] Build `updater.py` — incremental graph updates from signals
- [ ] Add `confused_at` edge creation on STUCK detection
- [ ] Implement "Stuck Assist" flow (prereq chain lookup → targeted help)
- [ ] Precompute section summaries at upload time
- [ ] Add "where am I?" summary to state response

### M4 — UI + Tuning + Metrics (Week 4)

- [ ] Add concept sidebar to frontend (collapsed by default)
- [ ] Add "Stuck Assist" button in Buddy panel
- [ ] Add memory timeline panel
- [ ] Build eval scripts for retrieval relevance + noise rate
- [ ] Tune extraction prompts and confidence thresholds
- [ ] Performance profiling and optimization

---

## Impact on Existing Code

| File | Change Type | What Changes |
|------|------------|-------------|
| `buddy/api/routes.py` | Modify | Wire graph into `/api/chat`, `/api/state`, `/api/upload` |
| `buddy/core/tone_controller.py` | Modify | Add concept-aware prompt templates |
| `buddy/reader/pdf_handler.py` | Minor | Expose chunk boundaries for graph ingestion |
| `buddy/memory/session_memory.py` | Replace/extend | SQLite-backed instead of in-memory |
| `config.yaml` | Extend | Add `knowledge:` section for graph settings |
| `requirements.txt` | No change | SQLite is in Python stdlib |
| `frontend/app.js` | Extend | New UI panels, concept display |
| `frontend/style.css` | Extend | Styles for new panels |
| `frontend/index.html` | Extend | New panel containers |

**No new dependencies needed** — SQLite is built into Python.

---

## Recommendation: Start Here

**"Concept Graph Lite"** — the minimum viable graph:

1. SQLite-backed concept nodes + simple edges
2. Upload-time extraction + lightweight incremental updates
3. Retrieval plugged into existing `/api/chat` + `/api/state`
4. No graph UI until quality stabilizes

This gives immediate value (better context → better responses) without violating "start small, local-first."
