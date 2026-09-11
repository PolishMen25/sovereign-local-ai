#!/usr/bin/env python3
"""Promote an owner-approved RAW arena increment into the validated corpus.

The arena bridge (``build_core_increment_from_arena.py``) writes RAW increments
under ``/mnt/sovereign-ai/raw/corpus/arena/<id>/`` (records.jsonl + manifest.json,
``lifecycle_state == "RAW"``, ``training_authorization == "not_approved"``).

This tool takes such a RAW increment plus an owner approval and writes a
VALIDATED copy under the validated corpus tree, refusing unless:

* the RAW manifest is well-formed and still ``RAW``;
* ``records.jsonl`` hashes to the manifest's ``content_sha256``;
* an approval for this exact increment id AND content digest is present.

Promotion never mutates an existing validated corpus and never trains anything:
it blesses one synthetic increment as owner-approved, carrying its ``≤ 20 %``
share cap forward.  Building a training corpus that includes it, and launching a
training run, stay separate, deliberate, owner-gated steps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

INCREMENT_SCHEMA = "arena-corpus-increment.v1"
APPROVAL_SCHEMA = "arena-increment-approval.v1"
VALIDATED_SCHEMA = "arena-corpus-increment.validated.v1"
SYNTHETIC_SHARE_CAP = 0.20


class PromotionRefused(ValueError):
    """Raised when the increment is not a safe, approved source to validate."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_raw_increment(increment_dir: Path) -> tuple[dict[str, Any], bytes]:
    """Return (manifest, records_bytes) for a well-formed RAW increment."""

    manifest_path = increment_dir / "manifest.json"
    records_path = increment_dir / "records.jsonl"
    for required in (manifest_path, records_path):
        if not required.is_file():
            raise PromotionRefused(f"increment is missing {required.name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != INCREMENT_SCHEMA:
        raise PromotionRefused("increment manifest is not an arena corpus increment")
    if manifest.get("lifecycle_state") != "RAW":
        raise PromotionRefused(f"increment is not RAW (state={manifest.get('lifecycle_state')!r})")
    body = records_path.read_bytes()
    if sha256_bytes(body) != manifest.get("content_sha256"):
        raise PromotionRefused("records.jsonl does not match the manifest content digest")
    records = [line for line in body.decode("utf-8").splitlines() if line.strip()]
    if not records:
        raise PromotionRefused("increment has no records")
    if len(records) != manifest.get("record_count"):
        raise PromotionRefused("record_count does not match records.jsonl")
    return manifest, body


def check_approval(approval: dict[str, Any], manifest: dict[str, Any]) -> None:
    if approval.get("schema_version") != APPROVAL_SCHEMA or approval.get("kind") != "increment":
        raise PromotionRefused("approval is not an increment approval")
    if approval.get("target_id") != manifest.get("increment_id"):
        raise PromotionRefused("approval does not match this increment id")
    if approval.get("target_sha256") != manifest.get("content_sha256"):
        raise PromotionRefused("approval digest does not match the increment content")
    if not str(approval.get("approved_by", "")).strip():
        raise PromotionRefused("approval has no approver")


def build_validated_manifest(manifest: dict[str, Any], approval: dict[str, Any], body: bytes) -> dict[str, Any]:
    validated = dict(manifest)
    validated.update({
        "schema_version": VALIDATED_SCHEMA,
        "lifecycle_state": "VALIDATED",
        "training_authorization": "approved",
        "promoted_at": utc_now(),
        "approved_by": str(approval["approved_by"]),
        "approval_sha256": sha256_bytes(json.dumps(approval, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "raw_increment_id": manifest["increment_id"],
        "raw_content_sha256": manifest["content_sha256"],
        "max_share_in_corpus_increment": float(manifest.get("max_share_in_corpus_increment", SYNTHETIC_SHARE_CAP)),
        "content_sha256": sha256_bytes(body),
        "promotion": "VALIDATED synthetic increment; capped at its max_share when a training corpus is built",
    })
    return validated


def promote(increment_dir: Path, approval_path: Path, validated_root: Path) -> dict[str, Any]:
    manifest, body = read_raw_increment(increment_dir)
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    check_approval(approval, manifest)
    out_dir = validated_root / manifest["increment_id"]
    if out_dir.exists():
        raise PromotionRefused(f"already promoted: {out_dir} exists")
    validated = build_validated_manifest(manifest, approval, body)
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "records.jsonl").write_bytes(body)
    (out_dir / "manifest.json").write_text(json.dumps(validated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "approval.json").write_text(json.dumps(approval, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return validated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("increment_dir", type=Path, help="RAW increment directory (records.jsonl + manifest.json)")
    parser.add_argument("--approval", type=Path, required=True, help="owner approval JSON for this increment")
    parser.add_argument("--validated-root", type=Path, default=Path("/mnt/sovereign-ai/validated/corpus/arena-increments"),
                        help="validated destination root")
    args = parser.parse_args(argv)
    try:
        validated = promote(args.increment_dir, args.approval, args.validated_root)
    except PromotionRefused as error:
        print(f"refused: {error}")
        return 1
    print(json.dumps({k: validated[k] for k in ("increment_id", "lifecycle_state", "record_count", "content_sha256", "approved_by")}, indent=2))
    print(f"promoted under {args.validated_root}/{validated['increment_id']} (VALIDATED; still capped at {validated['max_share_in_corpus_increment']:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
