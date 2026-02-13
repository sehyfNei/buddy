"""SQLite-backed session persistence — chat messages, state episodes, session metadata."""

import json
import sqlite3
import threading
import time
import uuid
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class StateEpisode:
    state: str
    page: int
    duration_s: float = 0.0
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


class SessionStore:
    """Persistent session storage backed by SQLite."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS sessions (
        id          TEXT PRIMARY KEY,
        doc_id      TEXT,
        doc_name    TEXT DEFAULT '',
        started_at  REAL NOT NULL,
        ended_at    REAL,
        summary     TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        timestamp   REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS state_episodes (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        state       TEXT NOT NULL,
        page        INTEGER,
        duration_s  REAL DEFAULT 0.0,
        timestamp   REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id);
    CREATE INDEX IF NOT EXISTS idx_chat_time ON chat_messages(timestamp);
    CREATE INDEX IF NOT EXISTS idx_episodes_session ON state_episodes(session_id);
    CREATE INDEX IF NOT EXISTS idx_sessions_doc ON sessions(doc_id);
    """

    def __init__(self, db_path: str | Path = "data/sessions.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()
        logger.info("Session store opened: %s", self.db_path)

    def close(self) -> None:
        self._conn.close()

    # ── Sessions ─────────────────────────────────────────────────────────

    def create_session(self, session_id: str, doc_id: str = "", doc_name: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions (id, doc_id, doc_name, started_at) VALUES (?, ?, ?, ?)",
                (session_id, doc_id, doc_name, time.time()),
            )
            self._conn.commit()

    def end_session(self, session_id: str, summary: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ?, summary = ? WHERE id = ?",
                (time.time(), summary, session_id),
            )
            self._conn.commit()

    def get_sessions_for_doc(self, doc_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE doc_id = ? ORDER BY started_at DESC", (doc_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Chat Messages ────────────────────────────────────────────────────

    def add_message(self, session_id: str, role: str, content: str) -> ChatMessage:
        msg = ChatMessage(role=role, content=content)
        with self._lock:
            self._conn.execute(
                "INSERT INTO chat_messages (id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (msg.id, session_id, msg.role, msg.content, msg.timestamp),
            )
            self._conn.commit()
        return msg

    def get_messages(self, session_id: str, limit: int = 50) -> list[ChatMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [ChatMessage(id=r["id"], role=r["role"], content=r["content"], timestamp=r["timestamp"])
                for r in reversed(rows)]

    def get_recent_context(self, session_id: str, limit: int = 10) -> str:
        """Format recent messages as context string for LLM."""
        msgs = self.get_messages(session_id, limit=limit)
        if not msgs:
            return ""
        lines = []
        for msg in msgs:
            prefix = "Reader" if msg.role == "user" else "Buddy"
            lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)

    # ── State Episodes ───────────────────────────────────────────────────

    def add_episode(self, session_id: str, state: str, page: int, duration_s: float = 0.0) -> StateEpisode:
        ep = StateEpisode(state=state, page=page, duration_s=duration_s)
        with self._lock:
            self._conn.execute(
                "INSERT INTO state_episodes (id, session_id, state, page, duration_s, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (ep.id, session_id, ep.state, ep.page, ep.duration_s, ep.timestamp),
            )
            self._conn.commit()
        return ep

    def get_episodes(self, session_id: str, limit: int = 50) -> list[StateEpisode]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM state_episodes WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [StateEpisode(id=r["id"], state=r["state"], page=r["page"],
                             duration_s=r["duration_s"], timestamp=r["timestamp"])
                for r in reversed(rows)]

    def get_stuck_pages(self, session_id: str) -> list[int]:
        """Get pages where user was stuck in this session."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT page FROM state_episodes WHERE session_id = ? AND state = 'stuck'",
                (session_id,),
            ).fetchall()
        return [r["page"] for r in rows]

    def get_doc_struggle_summary(self, doc_id: str) -> dict:
        """Cross-session summary of struggle points for a document."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT e.state, e.page, COUNT(*) as count
                FROM state_episodes e
                JOIN sessions s ON s.id = e.session_id
                WHERE s.doc_id = ?
                  AND e.state IN ('stuck', 'tired')
                GROUP BY e.state, e.page
                ORDER BY count DESC
            """, (doc_id,)).fetchall()
        return {
            "struggle_points": [
                {"state": r["state"], "page": r["page"], "occurrences": r["count"]}
                for r in rows
            ]
        }
