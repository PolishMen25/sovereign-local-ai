"""Local owner authentication with Argon2id and hashed sessions."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any


USERNAME = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")
MAX_PASSWORD_CHARS = 256


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def default_password_hasher() -> Any:
    try:
        from argon2 import PasswordHasher
        from argon2.low_level import Type
    except ImportError as error:
        raise RuntimeError("Argon2id support is not installed") from error
    return PasswordHasher(
        time_cost=3,
        memory_cost=65_536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


class AuthenticationStore:
    def __init__(self, database: Path, *, hasher: Any | None = None) -> None:
        self.database = database
        self.hasher = hasher

    def _hasher(self) -> Any:
        if self.hasher is None:
            self.hasher = default_password_hasher()
        return self.hasher

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
                CREATE TABLE IF NOT EXISTS local_owner (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_sha256 TEXT PRIMARY KEY,
                    username TEXT NOT NULL REFERENCES local_owner(username) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                """
            )

    def setup_required(self) -> bool:
        with closing(self._connect()) as connection:
            count = connection.execute("SELECT COUNT(*) FROM local_owner").fetchone()[0]
        return count == 0

    def initialize_owner(self, username: str, password: str) -> None:
        if not isinstance(username, str) or USERNAME.fullmatch(username) is None:
            raise ValueError("username is invalid")
        if not isinstance(password, str) or not 12 <= len(password) <= MAX_PASSWORD_CHARS:
            raise ValueError("password length is invalid")
        if len(set(password)) < 8:
            raise ValueError("password diversity is insufficient")
        password_hash = self._hasher().hash(password)
        if not isinstance(password_hash, str) or not password_hash.startswith("$argon2id$"):
            raise RuntimeError("password hasher did not produce Argon2id")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM local_owner LIMIT 1").fetchone() is not None:
                raise RuntimeError("local owner is already initialized")
            connection.execute(
                "INSERT INTO local_owner(username,password_hash,created_at) VALUES(?,?,?)",
                (username, password_hash, _timestamp(_now())),
            )

    def authenticate(self, username: str, password: str, *, lifetime_hours: int = 12) -> dict[str, str]:
        if not isinstance(username, str) or USERNAME.fullmatch(username) is None:
            raise PermissionError("authentication failed")
        if not isinstance(password, str) or not 1 <= len(password) <= MAX_PASSWORD_CHARS:
            raise PermissionError("authentication failed")
        if not isinstance(lifetime_hours, int) or not 1 <= lifetime_hours <= 24:
            raise ValueError("session lifetime is invalid")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT password_hash FROM local_owner WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            raise PermissionError("authentication failed")
        try:
            verified = self._hasher().verify(row["password_hash"], password)
        except Exception:
            verified = False
        if verified is not True:
            raise PermissionError("authentication failed")
        token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        created = _now()
        expires = created + timedelta(hours=lifetime_hours)
        token_sha256 = hashlib.sha256(token.encode("ascii")).hexdigest()
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (_timestamp(created),))
            connection.execute(
                "INSERT INTO sessions(token_sha256,username,csrf_token,created_at,expires_at) VALUES(?,?,?,?,?)",
                (token_sha256, username, csrf_token, _timestamp(created), _timestamp(expires)),
            )
        return {
            "session_token": token,
            "csrf_token": csrf_token,
            "expires_at": _timestamp(expires),
            "username": username,
        }

    def validate_session(self, token: str, *, csrf_token: str | None = None, require_csrf: bool = False) -> str:
        if not isinstance(token, str) or not 32 <= len(token) <= 256:
            raise PermissionError("session is invalid")
        token_sha256 = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT username,csrf_token,expires_at FROM sessions WHERE token_sha256 = ?",
                (token_sha256,),
            ).fetchone()
        if row is None or row["expires_at"] <= _timestamp(_now()):
            raise PermissionError("session is invalid")
        if require_csrf and (not isinstance(csrf_token, str) or not secrets.compare_digest(row["csrf_token"], csrf_token)):
            raise PermissionError("csrf token is invalid")
        return str(row["username"])

    def logout(self, token: str) -> None:
        if not isinstance(token, str) or not 32 <= len(token) <= 256:
            return
        token_sha256 = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM sessions WHERE token_sha256 = ?", (token_sha256,))

