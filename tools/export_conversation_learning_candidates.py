#!/usr/bin/env python3
"""Export redacted conversation turns as an unapproved training candidate.

The command reads the private memory database and creates a new, immutable
candidate directory.  It never writes into RAW, VALIDATED, or model weights.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.memory.store import MemoryStore


DATA_FILE = "learning-candidates.jsonl"
MANIFEST_FILE = "manifest.candidate.json"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def build_candidate_records(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Pair each assistant answer with the immediately preceding user turn."""
    records: list[dict[str, Any]] = []
    excluded = {"orphan_assistant": 0, "unanswered_user": 0, "superseded_user": 0}
    pending_user: dict[str, Any] | None = None
    previous_conversation: str | None = None

    for message in messages:
        conversation_id = str(message["conversation_id"])
        if conversation_id != previous_conversation:
            if pending_user is not None:
                excluded["unanswered_user"] += 1
            pending_user = None
            previous_conversation = conversation_id
        if message["role"] == "user":
            if pending_user is not None:
                excluded["superseded_user"] += 1
            pending_user = message
            continue
        if pending_user is None:
            excluded["orphan_assistant"] += 1
            continue

        user_content = str(pending_user["content"])
        assistant_content = str(message["content"])
        source_digests = [str(pending_user["content_sha256"]), str(message["content_sha256"])]
        record_material = "\n".join((conversation_id, *source_digests)).encode("utf-8")
        records.append(
            {
                "conversation_sha256": hashlib.sha256(conversation_id.encode("utf-8")).hexdigest(),
                "record_id": hashlib.sha256(record_material).hexdigest(),
                "schema_version": "conversation-learning-record.v1",
                "source_message_sha256": source_digests,
                "text": f"<|user|>\n{user_content}\n<|assistant|>\n{assistant_content}",
            }
        )
        pending_user = None

    if pending_user is not None:
        excluded["unanswered_user"] += 1
    return records, excluded


def export_learning_candidates(
    *, database: Path, output_dir: Path, backfill_existing: bool = False
) -> dict[str, Any]:
    if not database.is_file() or database.is_symlink():
        raise ValueError("memory database must be an existing regular file")
    if output_dir.exists():
        raise FileExistsError("candidate destination already exists")
    store = MemoryStore(database)
    backfill = store.backfill_learning_queue() if backfill_existing else {"queued": 0}
    messages = store.learning_candidates()
    records, excluded = build_candidate_records(messages)
    if not records:
        raise ValueError("learning queue contains no complete user/assistant pair")
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)

    data = b"".join(_canonical_json(record) + b"\n" for record in records)
    data_sha256 = hashlib.sha256(data).hexdigest()
    data_path = output_dir / DATA_FILE
    data_path.write_bytes(data)
    if hashlib.sha256(data_path.read_bytes()).hexdigest() != data_sha256:
        raise RuntimeError("candidate data verification failed after write")

    manifest = {
        "approval_status": "pending_owner_approval",
        "automatic_promotion": False,
        "backfilled_message_count": backfill["queued"],
        "conversation_count": len({record["conversation_sha256"] for record in records}),
        "data_file": DATA_FILE,
        "data_sha256": data_sha256,
        "excluded_messages": excluded,
        "message_count": len(records) * 2,
        "record_count": len(records),
        "sanitizer": "tools.codex_conversation_sync.sanitize_text",
        "schema_version": "conversation-learning-candidate-manifest.v1",
        "source": "private-redacted-memory-learning-queue",
    }
    manifest_path = output_dir / MANIFEST_FILE
    manifest_path.write_bytes(_canonical_json(manifest) + b"\n")
    reread = json.loads(manifest_path.read_text(encoding="utf-8"))
    if reread != manifest:
        raise RuntimeError("candidate manifest verification failed after write")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--backfill-existing",
        action="store_true",
        help="queue older user/assistant messages only after digest and sanitization checks",
    )
    args = parser.parse_args()
    try:
        manifest = export_learning_candidates(
            database=args.database,
            output_dir=args.output_dir,
            backfill_existing=args.backfill_existing,
        )
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"conversation learning export refused: {error}\n")
    print(json.dumps(manifest, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
