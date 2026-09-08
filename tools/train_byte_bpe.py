"""Build a deterministic byte-level BPE tokenizer only from an approved corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.tokenizer import (
    BpeTrainingResult,
    INPUT_ENCODING,
    MAXIMUM_VOCABULARY_SIZE,
    NORMALIZATION_POLICY_ID,
    SPECIAL_TOKENS,
    experimental_tokenizer_document,
    merge_sequence,
    train_byte_bpe,
)
from tools.validate_training_corpus_manifest import validate


MAXIMUM_CORPUS_BYTES = 512 * 1024 * 1024
MAXIMUM_RECORD_BYTES = 1024 * 1024
MAXIMUM_RECORDS = 1_000_000


def fail(message: str) -> None:
    raise ValueError(message)


def canonical_byte_token(value: bytes) -> str:
    return value.hex()


def collect_texts(raw: bytes, expected_records: int) -> list[str]:
    if type(expected_records) is not int or not 1 <= expected_records <= MAXIMUM_RECORDS:
        fail(f"expected_records must be between 1 and {MAXIMUM_RECORDS}")
    if not 1 <= len(raw) <= MAXIMUM_CORPUS_BYTES:
        fail("corpus size is outside the bounded tokenizer range")
    try:
        decoded = raw.decode(INPUT_ENCODING)
    except UnicodeDecodeError as error:
        fail(f"corpus must be valid UTF-8: {error}")
    lines = decoded.split("\n")
    if lines[-1] == "":
        lines.pop()
    if len(lines) != expected_records:
        fail("corpus record count does not match its manifest")

    texts: list[str] = []
    record_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if len(line.encode(INPUT_ENCODING)) > MAXIMUM_RECORD_BYTES:
            fail(f"record {line_number} exceeds the tokenizer record limit")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            fail(f"invalid JSONL record at line {line_number}: {error.msg}")
        if not isinstance(record, dict) or set(record) != {"record_id", "text"}:
            fail(f"record {line_number} must contain only record_id and text")
        record_id = record["record_id"]
        if (
            not isinstance(record_id, str)
            or not record_id
            or len(record_id) > 128
        ):
            fail(f"record {line_number} has an invalid record_id")
        if record_id in record_ids:
            fail(f"record {line_number} repeats a record_id")
        record_ids.add(record_id)
        if not isinstance(record["text"], str) or not record["text"]:
            fail(f"record {line_number} has an invalid text")
        texts.append(record["text"])
    return texts


def train(
    texts: list[str], vocabulary_size: int, *, min_frequency: int = 2
) -> BpeTrainingResult:
    """Compatibility entry point backed by the shared ordered-BPE engine."""
    return train_byte_bpe(
        texts, vocabulary_size, minimum_frequency=min_frequency
    )


def tokenizer_document(
    manifest: dict[str, Any],
    result: BpeTrainingResult,
    *,
    min_frequency: int = 2,
) -> dict[str, Any]:
    tokenizer_contract = manifest["tokenizer_contract"]
    if tokenizer_contract["input_encoding"] != INPUT_ENCODING:
        fail("manifest tokenizer encoding is unsupported")
    if tokenizer_contract["normalization_policy_id"] != NORMALIZATION_POLICY_ID:
        fail("manifest tokenizer normalization policy is unsupported")
    if tokenizer_contract["candidate_vocabulary_size"] > MAXIMUM_VOCABULARY_SIZE:
        fail("manifest tokenizer vocabulary exceeds the bounded implementation")
    if result.vocabulary_size != tokenizer_contract["candidate_vocabulary_size"]:
        fail("tokenizer training did not reach the exact candidate vocabulary size")
    return experimental_tokenizer_document(
        training_corpus_id=manifest["corpus_id"],
        training_corpus_sha256=manifest["splits"]["train"]["content_sha256"],
        result=result,
        minimum_frequency=min_frequency,
    )


def read_bounded_corpus(path: Path) -> bytes:
    size = path.stat().st_size
    if not 1 <= size <= MAXIMUM_CORPUS_BYTES:
        fail("corpus size is outside the bounded tokenizer range")
    raw = path.read_bytes()
    if len(raw) != size:
        fail("corpus changed while it was being read")
    return raw


def write_json_atomically(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding=INPUT_ENCODING,
        )
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-frequency", type=int, default=2)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding=INPUT_ENCODING))
        validate(manifest, require_training_authorization=True)
        corpus_bytes = read_bounded_corpus(args.input_jsonl)
        training_split = manifest["splits"]["train"]
        if len(corpus_bytes) != training_split["byte_size"]:
            fail("training split byte size does not match its manifest")
        if hashlib.sha256(corpus_bytes).hexdigest() != training_split["content_sha256"]:
            fail("training split SHA-256 does not match its manifest")
        texts = collect_texts(corpus_bytes, training_split["record_count"])
        result = train(
            texts,
            manifest["tokenizer_contract"]["candidate_vocabulary_size"],
            min_frequency=args.min_frequency,
        )
        document = tokenizer_document(
            manifest, result, min_frequency=args.min_frequency
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomically(args.output, document)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"tokenizer training refused: {error}", file=sys.stderr)
        return 1
    print(
        "experimental tokenizer written with "
        f"{result.vocabulary_size} entries and {len(result.merges)} merges"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
