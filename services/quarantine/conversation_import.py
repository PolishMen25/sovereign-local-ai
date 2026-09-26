"""Import a sanitized conversation into immutable-like RAW storage.

This CLI is operator-run only. It never promotes a conversation into the MCP
catalogue and rejects likely secrets before any durable write.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
from uuid import UUID


MAX_MESSAGES = 10_000
MAX_MESSAGE_CHARS = 50_000
SECRET_PATTERN = re.compile(r"(?:password|passwd|mot\s+de\s+passe|api[_ -]?key|access[_ -]?token|private[_ -]?key)\s*[:=]", re.IGNORECASE)


def validate(document: Any) -> None:
    if not isinstance(document, dict) or set(document) != {"schema_version", "conversation_id", "captured_at", "messages"}:
        raise ValueError("conversation must contain only schema_version, conversation_id, captured_at and messages")
    if document["schema_version"] != "0.1.0":
        raise ValueError("unsupported schema_version")
    try:
        UUID(document["conversation_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("conversation_id must be a UUID") from error
    if not isinstance(document["captured_at"], str) or "T" not in document["captured_at"]:
        raise ValueError("captured_at must be an ISO-8601 timestamp")
    messages = document["messages"]
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise ValueError("messages count is out of range")
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise ValueError("each message must contain only role and content")
        if message["role"] not in {"user", "assistant", "system", "tool"}:
            raise ValueError("unsupported message role")
        content = message["content"]
        if not isinstance(content, str) or not 1 <= len(content) <= MAX_MESSAGE_CHARS:
            raise ValueError("message content is out of range")
        if SECRET_PATTERN.search(content):
            raise ValueError("conversation contains a likely secret and must be redacted before import")


def canonical_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _store_once(target: Path, payload: bytes) -> bool:
    """Publish one complete snapshot without replacing an existing RAW file."""
    if target.is_symlink():
        raise ValueError("conversation storage target is a symlink")
    if target.exists():
        if not target.is_file() or target.read_bytes() != payload:
            raise ValueError("conversation snapshot already exists with different content")
        return False
    with tempfile.NamedTemporaryFile(mode="wb", prefix=".incoming-", dir=target.parent, delete=False) as staged:
        staged_path = Path(staged.name)
        staged.write(payload)
        staged.flush()
        os.fsync(staged.fileno())
    try:
        try:
            os.link(staged_path, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != payload:
                raise ValueError("conversation snapshot already exists with different content")
            return False
    finally:
        staged_path.unlink()
    return True


def import_raw(document: dict[str, Any], workbench_root: Path) -> dict[str, str]:
    validate(document)
    payload = canonical_bytes(document)
    digest = hashlib.sha256(payload).hexdigest()
    raw_directory = workbench_root.resolve() / "raw" / "conversations"
    directory_mode = 0o755 if os.name == "nt" else 0o700
    raw_directory.mkdir(mode=directory_mode, parents=True, exist_ok=True)
    target = raw_directory / f"{document['conversation_id']}.json"
    if target.is_symlink():
        raise ValueError("conversation storage target is a symlink")
    if target.exists() and target.read_bytes() != payload:
        # A later SessionEnd can carry more messages under the same stable ID.
        # Preserve the first snapshot and retain each distinct revision in RAW.
        version_directory = raw_directory / "versions" / document["conversation_id"]
        version_directory.mkdir(mode=directory_mode, parents=True, exist_ok=True)
        target = version_directory / f"{digest}.json"
    state = "raw_imported" if _store_once(target, payload) else "already_imported"
    return {"state": state, "conversation_id": document["conversation_id"], "sha256": digest}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: conversation_import.py REDACTED_CONVERSATION.json", file=sys.stderr)
        return 2
    try:
        document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        root = Path(os.environ.get("SOVEREIGN_WORKBENCH_ROOT", "workbench"))
        receipt = import_raw(document, root)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"conversation import rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
