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


def import_raw(document: dict[str, Any], workbench_root: Path) -> dict[str, str]:
    validate(document)
    payload = canonical_bytes(document)
    digest = hashlib.sha256(payload).hexdigest()
    raw_directory = workbench_root.resolve() / "raw" / "conversations"
    raw_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = raw_directory / f"{document['conversation_id']}.json"
    if target.exists():
        if target.read_bytes() != payload:
            raise ValueError("conversation_id already exists with different content")
        return {"state": "already_imported", "conversation_id": document["conversation_id"], "sha256": digest}
    temporary = target.with_suffix(".json.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, target)
    return {"state": "raw_imported", "conversation_id": document["conversation_id"], "sha256": digest}


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
