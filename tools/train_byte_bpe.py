"""Build a deterministic byte-level BPE tokenizer only from an approved corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from tools.validate_training_corpus_manifest import validate


SPECIAL_TOKENS = ["<pad>", "<bos>", "<eos>", "<unk>"]


def fail(message: str) -> None:
    raise ValueError(message)


def canonical_byte_token(value: bytes) -> str:
    return value.hex()


def collect_texts(raw: bytes, expected_records: int) -> list[str]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        fail(f"corpus must be valid UTF-8: {error}")
    if len(lines) != expected_records:
        fail("corpus record count does not match its manifest")
    texts: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            fail(f"invalid JSONL record at line {line_number}: {error.msg}")
        if not isinstance(record, dict) or set(record) != {"record_id", "text"}:
            fail(f"record {line_number} must contain only record_id and text")
        if not isinstance(record["record_id"], str) or not record["record_id"]:
            fail(f"record {line_number} has an invalid record_id")
        if not isinstance(record["text"], str) or not record["text"]:
            fail(f"record {line_number} has an invalid text")
        texts.append(record["text"])
    return texts


def train(texts: list[str], vocabulary_size: int, *, min_frequency: int = 2) -> list[str]:
    """Return stable hexadecimal byte tokens, with deterministic BPE merges."""
    if not 260 <= vocabulary_size <= 262144:
        fail("vocabulary_size must be between 260 and 262144")
    if not texts or any(not isinstance(text, str) or not text for text in texts):
        fail("texts must be a non-empty list of non-empty strings")
    if min_frequency < 2:
        fail("min_frequency must be at least 2")

    sequences = [[canonical_byte_token(bytes([byte])) for byte in text.encode("utf-8")] for text in texts]
    vocabulary = {canonical_byte_token(bytes([byte])) for byte in range(256)}
    while len(SPECIAL_TOKENS) + len(vocabulary) < vocabulary_size:
        frequencies: dict[tuple[str, str], int] = {}
        for sequence in sequences:
            for left, right in zip(sequence, sequence[1:]):
                frequencies[(left, right)] = frequencies.get((left, right), 0) + 1
        eligible = [(count, pair) for pair, count in frequencies.items() if count >= min_frequency]
        if not eligible:
            break
        _, pair = min(eligible, key=lambda item: (-item[0], item[1][0], item[1][1]))
        merged = pair[0] + pair[1]
        if len(bytes.fromhex(merged)) > 64:
            break
        vocabulary.add(merged)
        sequences = [merge_sequence(sequence, pair, merged) for sequence in sequences]
    return SPECIAL_TOKENS + sorted(vocabulary, key=lambda token: (len(token), token))


def merge_sequence(sequence: list[str], pair: tuple[str, str], merged: str) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(sequence):
        if index + 1 < len(sequence) and (sequence[index], sequence[index + 1]) == pair:
            output.append(merged)
            index += 2
        else:
            output.append(sequence[index])
            index += 1
    return output


def tokenizer_document(manifest: dict[str, Any], vocabulary: list[str]) -> dict[str, Any]:
    materialization = manifest["materialization"]
    return {
        "schema_version": "0.1.0",
        "status": "experimental",
        "algorithm": "byte_bpe",
        "training_corpus_id": manifest["corpus_id"],
        "training_corpus_sha256": materialization["content_sha256"],
        "input_encoding": manifest["tokenizer_contract"]["input_encoding"],
        "normalization_policy_id": manifest["tokenizer_contract"]["normalization_policy_id"],
        "special_tokens": SPECIAL_TOKENS,
        "tokens_hex": vocabulary[len(SPECIAL_TOKENS):],
        "vocabulary_size": len(vocabulary),
    }


def write_json_atomically(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-frequency", type=int, default=2)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate(manifest, require_training_authorization=True)
        corpus_bytes = args.input_jsonl.read_bytes()
        if hashlib.sha256(corpus_bytes).hexdigest() != manifest["materialization"]["content_sha256"]:
            fail("corpus SHA-256 does not match its manifest")
        texts = collect_texts(corpus_bytes, manifest["materialization"]["record_count"])
        vocabulary = train(texts, manifest["tokenizer_contract"]["candidate_vocabulary_size"], min_frequency=args.min_frequency)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomically(args.output, tokenizer_document(manifest, vocabulary))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"tokenizer training refused: {error}", file=sys.stderr)
        return 1
    print(f"experimental tokenizer written with {len(vocabulary)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
