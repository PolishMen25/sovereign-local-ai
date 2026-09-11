#!/usr/bin/env python3
"""Turn an owner-approved arena packet into a CORE corpus increment (RAW only).

The arena writes packets of test-passing solutions under
/var/lib/sovereign-arena/packets/<id>/ and marks one approved when the owner
clicks in the gateway.  This tool reads such an APPROVED packet and emits a
deterministic ``{record_id, text}`` JSONL increment plus a provenance manifest,
into RAW.  It never writes to a validated corpus and never trains anything:
promotion RAW -> validated stays the owner's manual, gated step.

Each record teaches CORE one instruction->code example:

    ### Instruction
    <task prompt>

    ### Réponse
    ```python
    <solution the arena proved against the task's tests>
    ```

Only the task's own tests decided that a solution belongs here, so the increment
is classified synthetic and is capped downstream at 20 % of any corpus it feeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

INCREMENT_SCHEMA = "arena-corpus-increment.v1"
APPROVAL_SCHEMA = "arena-approval.v1"
RECORD_TEMPLATE = "### Instruction\n{prompt}\n\n### Réponse\n```python\n{source}\n```\n"
MAX_RECORD_BYTES = 200_000


class IncrementRefused(ValueError):
    """Raised when the packet is not a safe, approved source for CORE."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_task_prompts(suite_path: Path) -> dict[str, str]:
    document = json.loads(suite_path.read_text(encoding="utf-8"))
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise IncrementRefused("task suite is empty or malformed")
    return {task["id"]: task["prompt"] for task in tasks}


def read_approved_packet(packet_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (manifest, solutions) for a packet the owner has approved.

    Refuses unless: the arena manifest is present, an approval.json for this
    exact packet exists, and the solutions file hashes to the approved digest.
    """

    manifest_path = packet_dir / "manifest.json"
    solutions_path = packet_dir / "solutions.jsonl"
    approval_path = packet_dir / "approval.json"
    for required in (manifest_path, solutions_path, approval_path):
        if not required.is_file():
            raise IncrementRefused(f"packet is missing {required.name} (approved in the gateway?)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if approval.get("schema_version") != APPROVAL_SCHEMA or approval.get("kind") != "packet":
        raise IncrementRefused("approval.json is not a packet approval")
    if approval.get("target_id") != manifest.get("packet_id"):
        raise IncrementRefused("approval does not match this packet")
    body = solutions_path.read_bytes()
    if sha256_bytes(body) != manifest.get("solutions_sha256"):
        raise IncrementRefused("solutions.jsonl does not match the approved digest")
    if approval.get("target_sha256") != manifest.get("solutions_sha256"):
        raise IncrementRefused("approval digest does not match the solutions")
    solutions = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    if not solutions:
        raise IncrementRefused("packet has no solutions")
    return manifest, solutions


def build_records(solutions: list[dict[str, Any]], prompts: dict[str, str], packet_id: str) -> list[dict[str, str]]:
    """One deduplicated record per (task, normalized solution), in stable order."""

    seen: set[tuple[str, str]] = set()
    records: list[dict[str, str]] = []
    for solution in solutions:
        task_id, source = solution.get("task_id"), solution.get("source")
        prompt = prompts.get(task_id)
        if prompt is None:
            raise IncrementRefused(f"task {task_id} is not in the suite; refusing to guess its prompt")
        if not isinstance(source, str) or not source.strip():
            continue
        key = (task_id, solution.get("source_sha256", sha256_bytes(source.encode("utf-8"))))
        if key in seen:
            continue
        seen.add(key)
        text = RECORD_TEMPLATE.format(prompt=prompt.strip(), source=source.strip())
        if len(text.encode("utf-8")) > MAX_RECORD_BYTES:
            continue
        records.append({"record_id": f"{packet_id}-{len(records):04d}", "text": text})
    if not records:
        raise IncrementRefused("no usable record after deduplication")
    return records


def write_increment(records: list[dict[str, str]], manifest: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=False)
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for r in records)
    records_path = out_dir / "records.jsonl"
    records_path.write_text(body, encoding="utf-8")
    increment = {
        "schema_version": INCREMENT_SCHEMA,
        "increment_id": f"corpus-arena-{manifest['packet_id']}".lower().replace("_", "-")[:63],
        "lifecycle_state": "RAW",
        "classification": "synthetic",
        "source": "sovereign agent arena",
        "referee": "task tests in the offline bwrap sandbox",
        "arena_packet_id": manifest["packet_id"],
        "arena_solutions_sha256": manifest["solutions_sha256"],
        "record_count": len(records),
        "content_sha256": sha256_bytes(body.encode("utf-8")),
        "byte_size": len(body.encode("utf-8")),
        "languages": ["en"],
        "max_share_in_corpus_increment": 0.20,
        "promotion": "RAW only; owner must validate before any training",
        "training_authorization": "not_approved",
    }
    (out_dir / "manifest.json").write_text(json.dumps(increment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return increment


def build(packet_dir: Path, suite_path: Path, raw_root: Path) -> dict[str, Any]:
    prompts = load_task_prompts(suite_path)
    manifest, solutions = read_approved_packet(packet_dir)
    records = build_records(solutions, prompts, manifest["packet_id"])
    out_dir = raw_root / f"arena-{manifest['packet_id']}"
    return write_increment(records, manifest, out_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet_dir", type=Path, help="approved arena packet directory")
    parser.add_argument("--suite", type=Path, default=Path("configs/evaluation/core-python-e2.candidate.json"))
    parser.add_argument("--raw-root", type=Path, default=Path("/mnt/sovereign-ai/raw/corpus/arena"),
                        help="RAW destination root (never a validated path)")
    args = parser.parse_args(argv)
    try:
        increment = build(args.packet_dir, args.suite, args.raw_root)
    except IncrementRefused as error:
        print(f"refused: {error}")
        return 1
    print(json.dumps({k: increment[k] for k in ("increment_id", "record_count", "content_sha256", "lifecycle_state")}, indent=2))
    print(f"written under {args.raw_root}/arena-{increment['arena_packet_id']} (RAW; validate before training)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
