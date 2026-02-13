"""SQLite-backed knowledge graph with node/edge tables."""

import json
import sqlite3
import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Node / Edge Types ────────────────────────────────────────────────────────

class NodeType(str, Enum):
    DOCUMENT = "document"
    PAGE_CHUNK = "page_chunk"
    CONCEPT = "concept"
    CLAIM = "claim"
    SIGNAL = "signal"
    ANNOTATION = "annotation"


class EdgeType(str, Enum):
    MENTIONS = "mentions"          # PageChunk → Concept/Claim
    DEPENDS_ON = "depends_on"      # Concept → Concept (prerequisite)
    EXPLAINS = "explains"          # Concept → Concept (clarifies)
    SUPPORTS = "supports"          # Claim → Concept or Claim → Claim
    CONFUSED_AT = "confused_at"    # Signal → Concept/PageChunk
    ANNOTATED = "annotated"        # Annotation → PageChunk


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class Node:
    id: str
    type: str
    label: str
    data: dict = field(default_factory=dict)
    doc_id: str = ""
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)


@dataclass
class Edge:
    id: str
    source_id: str
    target_id: str
    rel_type: str
    weight: float = 1.0
    data: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


# ── Graph Database ───────────────────────────────────────────────────────────

class KnowledgeGraph:
    """SQLite-backed knowledge graph for concept/claim storage and retrieval."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS nodes (
        id          TEXT PRIMARY KEY,
        type        TEXT NOT NULL,
        label       TEXT NOT NULL,
        data        TEXT DEFAULT '{}',
        doc_id      TEXT DEFAULT '',
        confidence  REAL DEFAULT 1.0,
        created_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS edges (
        id          TEXT PRIMARY KEY,
        source_id   TEXT NOT NULL REFERENCES nodes(id),
        target_id   TEXT NOT NULL REFERENCES nodes(id),
        rel_type    TEXT NOT NULL,
        weight      REAL DEFAULT 1.0,
        data        TEXT DEFAULT '{}',
        created_at  REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
    CREATE INDEX IF NOT EXISTS idx_nodes_doc ON nodes(doc_id);
    CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);
    CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
    CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
    CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(rel_type);
    CREATE INDEX IF NOT EXISTS idx_edges_source_rel ON edges(source_id, rel_type);
    CREATE INDEX IF NOT EXISTS idx_edges_target_rel ON edges(target_id, rel_type);
    """

    def __init__(self, db_path: str | Path = "data/graph.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        logger.info("Knowledge graph opened: %s", self.db_path)

    def _init_schema(self) -> None:
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── Node CRUD ────────────────────────────────────────────────────────

    def add_node(self, node: Node) -> Node:
        self._conn.execute(
            "INSERT OR REPLACE INTO nodes (id, type, label, data, doc_id, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node.id, node.type, node.label, json.dumps(node.data),
             node.doc_id, node.confidence, node.created_at),
        )
        self._conn.commit()
        return node

    def get_node(self, node_id: str) -> Node | None:
        row = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return None
        return self._row_to_node(row)

    def find_nodes(self, node_type: str | None = None, doc_id: str | None = None,
                   label_contains: str | None = None, limit: int = 100) -> list[Node]:
        query = "SELECT * FROM nodes WHERE 1=1"
        params: list[Any] = []

        if node_type:
            query += " AND type = ?"
            params.append(node_type)
        if doc_id:
            query += " AND doc_id = ?"
            params.append(doc_id)
        if label_contains:
            query += " AND label LIKE ?"
            params.append(f"%{label_contains}%")

        query += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_node(r) for r in rows]

    def delete_node(self, node_id: str) -> None:
        self._conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
        self._conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        self._conn.commit()

    def update_node_confidence(self, node_id: str, delta: float) -> None:
        self._conn.execute(
            "UPDATE nodes SET confidence = MIN(1.0, MAX(0.0, confidence + ?)) WHERE id = ?",
            (delta, node_id),
        )
        self._conn.commit()

    # ── Edge CRUD ────────────────────────────────────────────────────────

    def add_edge(self, edge: Edge) -> Edge:
        self._conn.execute(
            "INSERT OR REPLACE INTO edges (id, source_id, target_id, rel_type, weight, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (edge.id, edge.source_id, edge.target_id, edge.rel_type,
             edge.weight, json.dumps(edge.data), edge.created_at),
        )
        self._conn.commit()
        return edge

    def get_edges_from(self, node_id: str, rel_type: str | None = None) -> list[Edge]:
        if rel_type:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE source_id = ? AND rel_type = ?", (node_id, rel_type)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE source_id = ?", (node_id,)
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_to(self, node_id: str, rel_type: str | None = None) -> list[Edge]:
        if rel_type:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE target_id = ? AND rel_type = ?", (node_id, rel_type)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE target_id = ?", (node_id,)
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def update_edge_weight(self, edge_id: str, delta: float) -> None:
        self._conn.execute(
            "UPDATE edges SET weight = MAX(0.0, weight + ?) WHERE id = ?",
            (delta, edge_id),
        )
        self._conn.commit()

    def delete_edge(self, edge_id: str) -> None:
        self._conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
        self._conn.commit()

    # ── Query Helpers ────────────────────────────────────────────────────

    def get_concepts_for_page(self, doc_id: str, page: int) -> list[Node]:
        """Get all concepts mentioned on a specific page."""
        rows = self._conn.execute("""
            SELECT c.* FROM nodes c
            JOIN edges e ON e.target_id = c.id
            JOIN nodes p ON p.id = e.source_id
            WHERE p.type = 'page_chunk'
              AND p.doc_id = ?
              AND json_extract(p.data, '$.page') = ?
              AND e.rel_type = 'mentions'
              AND c.type IN ('concept', 'claim')
            ORDER BY e.weight DESC
        """, (doc_id, page)).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_prerequisites(self, concept_id: str, depth: int = 2) -> list[Node]:
        """Walk the depends_on chain up to `depth` levels."""
        visited: set[str] = set()
        result: list[Node] = []
        queue = [concept_id]

        for _ in range(depth):
            next_queue = []
            for nid in queue:
                if nid in visited:
                    continue
                visited.add(nid)
                edges = self.get_edges_from(nid, rel_type=EdgeType.DEPENDS_ON)
                for edge in edges:
                    if edge.target_id not in visited:
                        node = self.get_node(edge.target_id)
                        if node:
                            result.append(node)
                            next_queue.append(edge.target_id)
            queue = next_queue

        return result

    def get_confusion_history(self, doc_id: str, concept_ids: list[str], limit: int = 5) -> list[Node]:
        """Get past STUCK/confused signals related to given concepts."""
        if not concept_ids:
            return []
        placeholders = ",".join("?" for _ in concept_ids)
        rows = self._conn.execute(f"""
            SELECT s.* FROM nodes s
            JOIN edges e ON e.source_id = s.id
            WHERE e.target_id IN ({placeholders})
              AND e.rel_type = 'confused_at'
              AND s.type = 'signal'
            ORDER BY s.created_at DESC
            LIMIT ?
        """, (*concept_ids, limit)).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_page_chunk(self, doc_id: str, page: int) -> Node | None:
        """Get the page chunk node for a specific page."""
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE type = 'page_chunk' AND doc_id = ? AND json_extract(data, '$.page') = ?",
            (doc_id, page),
        ).fetchone()
        return self._row_to_node(row) if row else None

    def get_doc_stats(self, doc_id: str) -> dict:
        """Get summary stats for a document's graph."""
        concepts = self._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE doc_id = ? AND type = 'concept'", (doc_id,)
        ).fetchone()[0]
        claims = self._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE doc_id = ? AND type = 'claim'", (doc_id,)
        ).fetchone()[0]
        chunks = self._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE doc_id = ? AND type = 'page_chunk'", (doc_id,)
        ).fetchone()[0]
        edges = self._conn.execute("""
            SELECT COUNT(*) FROM edges e
            JOIN nodes n ON n.id = e.source_id
            WHERE n.doc_id = ?
        """, (doc_id,)).fetchone()[0]
        return {"concepts": concepts, "claims": claims, "chunks": chunks, "edges": edges}

    # ── Internal ─────────────────────────────────────────────────────────

    def _row_to_node(self, row: sqlite3.Row) -> Node:
        return Node(
            id=row["id"],
            type=row["type"],
            label=row["label"],
            data=json.loads(row["data"]) if row["data"] else {},
            doc_id=row["doc_id"],
            confidence=row["confidence"],
            created_at=row["created_at"],
        )

    def _row_to_edge(self, row: sqlite3.Row) -> Edge:
        return Edge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            rel_type=row["rel_type"],
            weight=row["weight"],
            data=json.loads(row["data"]) if row["data"] else {},
            created_at=row["created_at"],
        )


# ── Helper ───────────────────────────────────────────────────────────────────

def make_id() -> str:
    return str(uuid.uuid4())
