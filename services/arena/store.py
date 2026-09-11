"""SQLite state of the arena: profiles, matches, attempts, events and packets.

The arena daemon is the only writer.  The gateway opens the same file with
``read_only=True`` (SQLite ``mode=ro``) and never writes to it.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

ROLES = ("author", "critic")
ENGINES = ("QWEN-CODER", "BOOTSTRAP")
PROFILE_STATUSES = ("active", "retired")
PACKET_STATUSES = ("awaiting_owner_approval", "flagged", "approved")
EVENT_PAYLOAD_BYTES = 8_192
RATING_HISTORY_POINTS = 40

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('author','critic')),
    engine TEXT NOT NULL CHECK (engine IN ('QWEN-CODER','BOOTSTRAP')),
    system_prompt TEXT NOT NULL,
    temperature REAL NOT NULL CHECK (temperature >= 0 AND temperature <= 1),
    parent_id TEXT REFERENCES profiles(profile_id),
    generation INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired')),
    chat_approved INTEGER NOT NULL DEFAULT 0 CHECK (chat_approved IN (0,1)),
    rating REAL NOT NULL DEFAULT 1000,
    matches INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    first_pass INTEGER NOT NULL DEFAULT 0,
    repaired INTEGER NOT NULL DEFAULT 0,
    advised INTEGER NOT NULL DEFAULT 0,
    advice_success INTEGER NOT NULL DEFAULT 0,
    last_played_at TEXT,
    created_at TEXT NOT NULL,
    retired_at TEXT
);
CREATE TABLE IF NOT EXISTS rating_history (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
    at TEXT NOT NULL,
    rating REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rating_history_profile ON rating_history(profile_id, at);
CREATE TABLE IF NOT EXISTS matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    author_a TEXT NOT NULL REFERENCES profiles(profile_id),
    author_b TEXT NOT NULL REFERENCES profiles(profile_id),
    critic_id TEXT REFERENCES profiles(profile_id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    score_a REAL,
    score_b REAL
);
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(match_id),
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt IN (1,2)),
    passed INTEGER NOT NULL CHECK (passed IN (0,1)),
    source TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    normalized_sha256 TEXT NOT NULL,
    failure_excerpt TEXT NOT NULL DEFAULT '',
    critique TEXT NOT NULL DEFAULT '',
    packet_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_accepted ON attempts(passed, packet_id);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS packets (
    packet_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    path TEXT NOT NULL,
    solutions_sha256 TEXT NOT NULL,
    solutions INTEGER NOT NULL,
    unique_ratio REAL NOT NULL,
    max_repetition REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('awaiting_owner_approval','flagged','approved')),
    approved_at TEXT,
    approved_by TEXT
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ArenaStore:
    def __init__(self, database: Path, *, read_only: bool = False) -> None:
        self.database = database
        self.read_only = read_only

    # --- connection -------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            if not self.database.is_file():
                raise FileNotFoundError("arena database is not available")
            connection = sqlite3.connect(f"file:{self.database}?mode=ro", uri=True, timeout=5)
        else:
            self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            connection = sqlite3.connect(self.database, timeout=10)
            # Rollback journal, not WAL: the gateway reads with a different Unix
            # user that cannot create the -shm/-wal files next to the database.
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(SCHEMA)

    # --- writes (daemon only) ---------------------------------------------

    def add_profile(self, profile: dict[str, Any]) -> None:
        if profile["role"] not in ROLES or profile["engine"] not in ENGINES:
            raise ValueError("arena profile role or engine is invalid")
        now = utc_now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO profiles(profile_id,display_name,role,engine,system_prompt,temperature,parent_id,generation,rating,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (profile["profile_id"], profile["display_name"], profile["role"], profile["engine"],
                 profile["system_prompt"], float(profile["temperature"]), profile.get("parent_id"),
                 int(profile.get("generation", 0)), float(profile.get("rating", 1000.0)), now),
            )
            connection.execute("INSERT INTO rating_history(profile_id,at,rating) VALUES(?,?,?)",
                               (profile["profile_id"], now, float(profile.get("rating", 1000.0))))

    def retire_profile(self, profile_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("UPDATE profiles SET status='retired', retired_at=? WHERE profile_id=? AND status='active'",
                               (utc_now(), profile_id))

    def approve_profile_for_chat(self, profile_id: str) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute("UPDATE profiles SET chat_approved=1 WHERE profile_id=?", (profile_id,))
            return cursor.rowcount == 1

    def start_match(self, task_id: str, author_a: str, author_b: str, critic_id: str | None) -> int:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO matches(task_id,author_a,author_b,critic_id,started_at) VALUES(?,?,?,?,?)",
                (task_id, author_a, author_b, critic_id, utc_now()))
            return int(cursor.lastrowid)

    def record_attempt(self, match_id: int, profile_id: str, task_id: str, attempt: int, *, passed: bool,
                       source: str, source_sha256: str, normalized_sha256: str,
                       failure_excerpt: str = "", critique: str = "") -> int:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO attempts(match_id,profile_id,task_id,attempt,passed,source,source_sha256,normalized_sha256,failure_excerpt,critique,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (match_id, profile_id, task_id, attempt, int(passed), source, source_sha256, normalized_sha256,
                 failure_excerpt, critique, utc_now()))
            return int(cursor.lastrowid)

    def finish_match(self, match_id: int, results: dict[str, dict[str, Any]], critic: dict[str, Any] | None) -> None:
        """Store scores and apply the new ratings and counters in one transaction."""

        now = utc_now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT author_a, author_b FROM matches WHERE match_id=?", (match_id,)).fetchone()
            connection.execute("UPDATE matches SET finished_at=?, score_a=?, score_b=? WHERE match_id=?",
                               (now, results[row["author_a"]]["score"], results[row["author_b"]]["score"], match_id))
            for profile_id, result in results.items():
                connection.execute(
                    "UPDATE profiles SET rating=?, matches=matches+1, wins=wins+?, first_pass=first_pass+?,"
                    " repaired=repaired+?, last_played_at=? WHERE profile_id=?",
                    (result["rating"], int(result["won"]), int(result["first_pass"]), int(result["repaired"]), now, profile_id))
                connection.execute("INSERT INTO rating_history(profile_id,at,rating) VALUES(?,?,?)",
                                   (profile_id, now, result["rating"]))
            if critic is not None:
                connection.execute(
                    "UPDATE profiles SET advised=advised+?, advice_success=advice_success+?, last_played_at=? WHERE profile_id=?",
                    (critic["advised"], critic["success"], now, critic["profile_id"]))

    def add_event(self, kind: str, payload: dict[str, Any]) -> int:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > EVENT_PAYLOAD_BYTES:
            encoded = json.dumps({"truncated": True, "kind": kind}, separators=(",", ":"))
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute("INSERT INTO events(at,kind,payload) VALUES(?,?,?)", (utc_now(), kind, encoded))
            return int(cursor.lastrowid)

    def set_state(self, **values: Any) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executemany("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                   [(key, json.dumps(value, ensure_ascii=False)) for key, value in values.items()])

    def unpacked_accepted(self) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT a.*, p.engine FROM attempts a JOIN profiles p ON p.profile_id=a.profile_id"
                " WHERE a.passed=1 AND a.packet_id IS NULL ORDER BY a.attempt_id").fetchall()

    def record_packet(self, packet: dict[str, Any], attempt_ids: Iterable[int]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO packets(packet_id,created_at,path,solutions_sha256,solutions,unique_ratio,max_repetition,status)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (packet["packet_id"], packet["created_at"], packet["path"], packet["solutions_sha256"],
                 packet["solutions"], packet["unique_ratio"], packet["max_repetition"], packet["status"]))
            connection.executemany("UPDATE attempts SET packet_id=? WHERE attempt_id=?",
                                   [(packet["packet_id"], attempt_id) for attempt_id in attempt_ids])

    def approve_packet(self, packet_id: str, solutions_sha256: str, approved_by: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT * FROM packets WHERE packet_id=?", (packet_id,)).fetchone()
            if row is None or row["status"] != "awaiting_owner_approval" or row["solutions_sha256"] != solutions_sha256:
                return None
            now = utc_now()
            connection.execute("UPDATE packets SET status='approved', approved_at=?, approved_by=? WHERE packet_id=?",
                               (now, approved_by, packet_id))
            return {**dict(row), "status": "approved", "approved_at": now, "approved_by": approved_by}

    # --- reads ------------------------------------------------------------

    def profiles(self, *, role: str | None = None, status: str | None = "active") -> list[dict[str, Any]]:
        query, parameters = "SELECT * FROM profiles WHERE 1=1", []
        if role is not None:
            query += " AND role=?"
            parameters.append(role)
        if status is not None:
            query += " AND status=?"
            parameters.append(status)
        with closing(self._connect()) as connection:
            return [dict(row) for row in connection.execute(query + " ORDER BY rating DESC, profile_id", parameters)]

    def recent_failures(self, profile_id: str, limit: int = 5) -> list[dict[str, str]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT task_id, failure_excerpt FROM attempts WHERE profile_id=? AND passed=0 AND failure_excerpt!=''"
                " ORDER BY attempt_id DESC LIMIT ?", (profile_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def task_solve_counts(self) -> dict[str, int]:
        with closing(self._connect()) as connection:
            return {row["task_id"]: row["n"] for row in connection.execute(
                "SELECT task_id, COUNT(*) AS n FROM attempts WHERE passed=1 GROUP BY task_id")}

    def recent_task_ids(self, limit: int = 10) -> list[str]:
        with closing(self._connect()) as connection:
            return [row["task_id"] for row in connection.execute(
                "SELECT task_id FROM matches ORDER BY match_id DESC LIMIT ?", (limit,))]

    def packet_count(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM packets").fetchone()[0])

    def match_count(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM matches WHERE finished_at IS NOT NULL").fetchone()[0])

    def events_after(self, event_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM events WHERE event_id>? ORDER BY event_id LIMIT ?",
                                      (event_id, limit)).fetchall()
        return [{"event_id": row["event_id"], "at": row["at"], "kind": row["kind"], "payload": json.loads(row["payload"])}
                for row in rows]

    def last_event_id(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COALESCE(MAX(event_id),0) FROM events").fetchone()[0])

    def overview(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            profiles = [dict(row) for row in connection.execute(
                "SELECT profile_id,display_name,role,engine,temperature,parent_id,generation,status,chat_approved,rating,"
                "matches,wins,first_pass,repaired,advised,advice_success,created_at,retired_at FROM profiles"
                " ORDER BY status, rating DESC")]
            for profile in profiles:
                profile["rating_history"] = [round(row["rating"], 1) for row in reversed(connection.execute(
                    "SELECT rating FROM rating_history WHERE profile_id=? ORDER BY rowid DESC LIMIT ?",
                    (profile["profile_id"], RATING_HISTORY_POINTS)).fetchall())]
            packets = [dict(row) for row in connection.execute(
                "SELECT packet_id,created_at,solutions_sha256,solutions,unique_ratio,max_repetition,status,approved_at,approved_by"
                " FROM packets ORDER BY created_at DESC, packet_id DESC LIMIT 20")]
            state = {row["key"]: json.loads(row["value"]) for row in connection.execute("SELECT key, value FROM state")}
            totals = dict(connection.execute(
                "SELECT (SELECT COUNT(*) FROM matches WHERE finished_at IS NOT NULL) AS matches,"
                " (SELECT COUNT(*) FROM attempts WHERE passed=1) AS accepted,"
                " (SELECT COUNT(DISTINCT task_id) FROM attempts WHERE passed=1) AS tasks_solved,"
                " (SELECT COUNT(*) FROM matches WHERE finished_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 hour')) AS matches_last_hour,"
                " (SELECT COUNT(*) FROM attempts WHERE passed=1 AND packet_id IS NULL) AS pending_solutions"
            ).fetchone())
            last_event_id = int(connection.execute("SELECT COALESCE(MAX(event_id),0) FROM events").fetchone()[0])
        return {"profiles": profiles, "packets": packets, "state": state, "totals": totals, "last_event_id": last_event_id}
