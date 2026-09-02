"""Two-step, one-time owner confirmation ledger for narrow actions.

This module authorizes a pre-hashed proposal. It never executes the action and
is deliberately not exposed as a model or MCP tool.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any
from uuid import uuid4


ALLOWED_CAPABILITIES = frozenset(
    {
        "conversation.export",
        "conversation.delete",
        "knowledge.promote_approved",
        "proxmox.status",
        "service.restart_approved",
        "synology.status",
    }
)
TARGET = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("proposal payload must be a non-empty object")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    if len(raw) > 65_536:
        raise ValueError("proposal payload exceeds its size limit")
    return hashlib.sha256(raw).hexdigest()


class ConfirmationLedger:
    def __init__(self, database: Path) -> None:
        self.database = database

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    target TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','consumed','expired')),
                    confirmed_by TEXT,
                    authorization_sha256 TEXT
                );
                """
            )

    def propose(self, *, capability: str, target: str, summary: str, payload_sha256: str, lifetime_minutes: int = 30) -> dict[str, str]:
        if capability not in ALLOWED_CAPABILITIES:
            raise ValueError("capability is not allowlisted")
        if not isinstance(target, str) or TARGET.fullmatch(target) is None:
            raise ValueError("target is invalid")
        if not isinstance(summary, str) or not 1 <= len(summary) <= 1_000:
            raise ValueError("summary is invalid")
        if not isinstance(payload_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", payload_sha256) is None:
            raise ValueError("payload digest is invalid")
        if not isinstance(lifetime_minutes, int) or not 1 <= lifetime_minutes <= 60:
            raise ValueError("proposal lifetime is invalid")
        created = _now()
        expires = created + timedelta(minutes=lifetime_minutes)
        proposal_id = uuid4().hex
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO proposals(proposal_id,capability,target,summary,payload_sha256,created_at,expires_at,status) "
                "VALUES(?,?,?,?,?,?,?,'pending')",
                (proposal_id, capability, target, summary, payload_sha256, _stamp(created), _stamp(expires)),
            )
        return {
            "proposal_id": proposal_id,
            "capability": capability,
            "target": target,
            "summary": summary,
            "payload_sha256": payload_sha256,
            "expires_at": _stamp(expires),
            "requires_confirmation": "true",
        }

    def confirm(self, proposal_id: str, *, owner: str, expected_payload_sha256: str) -> dict[str, str]:
        if not isinstance(owner, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{2,31}", owner):
            raise PermissionError("owner identity is invalid")
        authorization = secrets.token_urlsafe(48)
        authorization_sha256 = hashlib.sha256(authorization.encode("ascii")).hexdigest()
        now = _stamp(_now())
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
            if row is None or row["status"] != "pending":
                raise PermissionError("proposal is unavailable")
            if row["expires_at"] <= now:
                connection.execute("UPDATE proposals SET status='expired' WHERE proposal_id = ?", (proposal_id,))
                raise PermissionError("proposal expired")
            if not secrets.compare_digest(row["payload_sha256"], expected_payload_sha256):
                raise PermissionError("proposal digest changed")
            connection.execute(
                "UPDATE proposals SET status='confirmed',confirmed_by=?,authorization_sha256=? WHERE proposal_id=?",
                (owner, authorization_sha256, proposal_id),
            )
        return {"proposal_id": proposal_id, "authorization": authorization, "expires_at": row["expires_at"]}

    def consume(self, proposal_id: str, *, authorization: str, capability: str, target: str, payload_sha256: str) -> None:
        if not isinstance(authorization, str) or len(authorization) < 32:
            raise PermissionError("authorization is invalid")
        authorization_sha256 = hashlib.sha256(authorization.encode("ascii", errors="ignore")).hexdigest()
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
            if row is None or row["status"] != "confirmed":
                raise PermissionError("authorization is unavailable")
            expected = (row["authorization_sha256"], row["capability"], row["target"], row["payload_sha256"])
            supplied = (authorization_sha256, capability, target, payload_sha256)
            if any(not secrets.compare_digest(str(left), str(right)) for left, right in zip(expected, supplied, strict=True)):
                raise PermissionError("authorization binding is invalid")
            connection.execute("UPDATE proposals SET status='consumed' WHERE proposal_id = ?", (proposal_id,))

