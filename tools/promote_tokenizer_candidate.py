#!/usr/bin/env python3
"""Promote one verified experimental Byte-BPE artifact to ``candidate_core``.

The command is deliberately offline and refuses overwrite.  It creates a
separate receipt that binds the approved corpus manifest, exact train split,
source tokenizer and promoted tokenizer through SHA-256 digests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.tokenizer import (
    EXPERIMENTAL_STATUS,
    MAXIMUM_ARTIFACT_BYTES,
    promote_to_candidate_core,
    validate_tokenizer_document,
)
from tools.authorized_text_bundle import load_authorized_text_bundle


RECEIPT_SCHEMA_VERSION = "0.1.0"
MAXIMUM_APPROVAL_REFERENCE_LENGTH = 160
DATE = re.compile(r"^20[0-9]{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
SAFE_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,159}$")


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_json_object(path: Path, *, maximum_bytes: int, context: str) -> tuple[bytes, dict[str, Any]]:
    size = path.stat().st_size
    if not 1 <= size <= maximum_bytes:
        raise ValueError(f"{context} size is outside the bounded range")
    payload = path.read_bytes()
    if len(payload) != size:
        raise ValueError(f"{context} changed while it was being read")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{context} must be valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{context} must be a JSON object")
    return payload, document


def build_receipt(
    *,
    approval_reference: str,
    approved_at: str,
    bundle: Any,
    source_tokenizer_sha256: str,
    candidate_tokenizer_sha256: str,
) -> dict[str, Any]:
    if not SAFE_REFERENCE.fullmatch(approval_reference):
        raise ValueError("approval_reference has an invalid format")
    if len(approval_reference) > MAXIMUM_APPROVAL_REFERENCE_LENGTH:
        raise ValueError("approval_reference is too long")
    if not DATE.fullmatch(approved_at):
        raise ValueError("approved_at must use YYYY-MM-DD")
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "promotion": "experimental_to_candidate_core",
        "approval_reference": approval_reference,
        "approved_at": approved_at,
        "corpus_id": bundle.corpus_id,
        "manifest_sha256": bundle.manifest_sha256,
        "train_split_sha256": bundle.train_sha256,
        "source_tokenizer_sha256": source_tokenizer_sha256,
        "candidate_tokenizer_sha256": candidate_tokenizer_sha256,
        "candidate_vocabulary_size": bundle.tokenizer_vocabulary_size,
        "candidate_tokenizer_status": "candidate_core",
    }


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
        output.flush()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--input-tokenizer", type=Path, required=True)
    parser.add_argument("--output-tokenizer", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--approved-at", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output_tokenizer.exists() or args.receipt.exists():
        raise ValueError("candidate tokenizer output or receipt already exists")
    source_bytes, source_document = read_json_object(
        args.input_tokenizer,
        maximum_bytes=MAXIMUM_ARTIFACT_BYTES,
        context="source tokenizer",
    )
    validate_tokenizer_document(source_document)
    if source_document["status"] != EXPERIMENTAL_STATUS:
        raise ValueError("source tokenizer must be experimental")
    bundle = load_authorized_text_bundle(
        manifest_path=args.manifest,
        train_jsonl_path=args.train_jsonl,
        tokenizer_path=args.input_tokenizer,
    )
    promoted = promote_to_candidate_core(source_document)
    promoted_bytes = canonical_json_bytes(promoted)
    receipt = build_receipt(
        approval_reference=args.approval_reference,
        approved_at=args.approved_at,
        bundle=bundle,
        source_tokenizer_sha256=sha256(source_bytes),
        candidate_tokenizer_sha256=sha256(promoted_bytes),
    )
    write_new(args.output_tokenizer, promoted_bytes)
    try:
        write_new(args.receipt, canonical_json_bytes(receipt))
    except Exception:
        # Do not silently claim a promotion if its receipt could not be saved.
        raise RuntimeError("candidate tokenizer was written but receipt creation failed") from None
    print(json.dumps({"tokenizer": str(args.output_tokenizer), "receipt": str(args.receipt)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
