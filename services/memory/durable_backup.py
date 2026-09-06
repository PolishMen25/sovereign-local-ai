"""Atomic, content-free verified backups for private SQLite conversation memory."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


SCHEMA_VERSION = "private-memory-backup.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _require_database(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("database path is invalid")
    return resolved


def _check_sqlite(path: Path) -> None:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()
    if result != ("ok",):
        raise ValueError("sqlite integrity check failed")


def create_backup(source: Path, destination_directory: Path) -> dict[str, Any]:
    """Create an atomic SQLite backup and a content-free manifest."""
    source = _require_database(source)
    destination = destination_directory.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        destination.chmod(0o700)
    if not destination.is_dir():
        raise ValueError("backup destination is invalid")

    with tempfile.NamedTemporaryFile(prefix="memory-", suffix=".sqlite3", dir=destination, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(source)) as source_connection, closing(sqlite3.connect(temporary)) as target_connection:
            source_connection.backup(target_connection)
        _check_sqlite(temporary)
        digest = _sha256(temporary)
        filename = f"memory-{_utc_now()}-{digest[:16]}.sqlite3"
        artifact = destination / filename
        os.replace(temporary, artifact)
        manifest = artifact.with_suffix(".json")
        document = {
            "schema_version": SCHEMA_VERSION,
            "artifact": filename,
            "sha256": digest,
            "bytes": artifact.stat().st_size,
        }
        _atomic_json(manifest, document)
        return document
    finally:
        temporary.unlink(missing_ok=True)


def verify_backup(artifact: Path, manifest: Path) -> dict[str, Any]:
    artifact = _require_database(artifact)
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("backup manifest is invalid") from error
    if not isinstance(document, dict) or set(document) != {"schema_version", "artifact", "sha256", "bytes"}:
        raise ValueError("backup manifest fields are invalid")
    if document.get("schema_version") != SCHEMA_VERSION or document.get("artifact") != artifact.name:
        raise ValueError("backup manifest identity is invalid")
    if not isinstance(document.get("sha256"), str) or len(document["sha256"]) != 64:
        raise ValueError("backup manifest digest is invalid")
    if not isinstance(document.get("bytes"), int) or document["bytes"] != artifact.stat().st_size:
        raise ValueError("backup manifest size is invalid")
    if _sha256(artifact) != document["sha256"]:
        raise ValueError("backup digest does not match")
    _check_sqlite(artifact)
    return document


def restore_backup(artifact: Path, manifest: Path, destination: Path) -> dict[str, Any]:
    """Restore a verified artifact through SQLite's backup API, atomically."""
    document = verify_backup(artifact, manifest)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        destination.parent.chmod(0o700)
    with tempfile.NamedTemporaryFile(prefix="restore-", suffix=".sqlite3", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(artifact)) as source_connection, closing(sqlite3.connect(temporary)) as target_connection:
            source_connection.backup(target_connection)
        _check_sqlite(temporary)
        if _sha256(temporary) != document["sha256"]:
            raise ValueError("restored backup digest does not match")
        os.replace(temporary, destination)
        return {"schema_version": SCHEMA_VERSION, "restored_sha256": document["sha256"], "bytes": document["bytes"]}
    finally:
        temporary.unlink(missing_ok=True)
