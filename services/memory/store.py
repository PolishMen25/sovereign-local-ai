"""Bounded SQLite store for private, redacted conversation memory.

The database path is operator supplied. Client requests never select a path.
Deletion removes message content and retains only a content-free audit receipt.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from uuid import uuid4

from tools.codex_conversation_sync import sanitize_text


CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
ROLES = frozenset({"user", "assistant", "system", "tool"})
MAX_CONTENT_CHARS = 45_000
MAX_TITLE_CHARS = 160


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class MemoryStore:
    def __init__(self, database: Path) -> None:
        self.database = database

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
                    role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
                    content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (conversation_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS audit_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_conversation_order
                    ON messages(conversation_id, ordinal);
                """
            )

    @staticmethod
    def _validate_conversation_id(conversation_id: str) -> None:
        if not isinstance(conversation_id, str) or CONVERSATION_ID.fullmatch(conversation_id) is None:
            raise ValueError("conversation_id is invalid")

    def create_conversation(self, *, title: str = "Nouvelle conversation", conversation_id: str | None = None) -> str:
        if conversation_id is None:
            conversation_id = uuid4().hex
        self._validate_conversation_id(conversation_id)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= MAX_TITLE_CHARS:
            raise ValueError("conversation title is invalid")
        now = utc_now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO conversations(conversation_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                (conversation_id, sanitize_text(title)[:MAX_TITLE_CHARS], now, now),
            )
        return conversation_id

    def append_message(self, conversation_id: str, *, role: str, content: str) -> dict[str, Any]:
        self._validate_conversation_id(conversation_id)
        if role not in ROLES:
            raise ValueError("message role is invalid")
        if not isinstance(content, str) or not 1 <= len(content) <= MAX_CONTENT_CHARS:
            raise ValueError("message content size is invalid")
        redacted = sanitize_text(content)
        digest = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        message_id = uuid4().hex
        now = utc_now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            present = connection.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
            if present is None:
                raise KeyError("conversation does not exist")
            ordinal = connection.execute(
                "SELECT COALESCE(MAX(ordinal),0)+1 FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO messages(message_id,conversation_id,ordinal,role,content,content_sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (message_id, conversation_id, ordinal, role, redacted, digest, now),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (now, conversation_id),
            )
        return {
            "message_id": message_id,
            "ordinal": ordinal,
            "role": role,
            "content": redacted,
            "content_sha256": digest,
            "created_at": now,
        }

    def list_conversations(self, *, limit: int = 100) -> list[dict[str, str]]:
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("conversation limit is invalid")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT conversation_id,title,created_at,updated_at FROM conversations "
                "ORDER BY updated_at DESC, conversation_id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def export_conversation(self, conversation_id: str) -> dict[str, Any]:
        self._validate_conversation_id(conversation_id)
        with closing(self._connect()) as connection:
            conversation = connection.execute(
                "SELECT conversation_id,title,created_at,updated_at FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise KeyError("conversation does not exist")
            messages = connection.execute(
                "SELECT message_id,ordinal,role,content,content_sha256,created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY ordinal",
                (conversation_id,),
            ).fetchall()
        return {
            "schema_version": "private-conversation-export.v1",
            **dict(conversation),
            "messages": [dict(row) for row in messages],
        }

    def delete_conversation(self, conversation_id: str) -> dict[str, str]:
        self._validate_conversation_id(conversation_id)
        occurred_at = utc_now()
        event = {
            "event_type": "conversation_deleted",
            "conversation_id": conversation_id,
            "occurred_at": occurred_at,
        }
        event_sha256 = hashlib.sha256(
            json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        receipt_id = uuid4().hex
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            deleted = connection.execute(
                "DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).rowcount
            if deleted != 1:
                raise KeyError("conversation does not exist")
            connection.execute(
                "INSERT INTO audit_receipts(receipt_id,event_type,conversation_id,occurred_at,event_sha256) "
                "VALUES(?,?,?,?,?)",
                (receipt_id, event["event_type"], conversation_id, occurred_at, event_sha256),
            )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"receipt_id": receipt_id, **event, "event_sha256": event_sha256}
