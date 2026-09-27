#!/usr/bin/env python3
"""Evaluate pinned Byte-BPE tokenizer artifacts on one held-out JSONL set.

The tool is offline and read-only on its inputs. It re-validates every
artifact with ``services/inference/tokenizer.py``, refuses an artifact whose
bytes differ from the SHA-256 pinned by the operator, and encodes each record
with the runtime tokenizer itself. It writes one deterministic, content-free
JSON report: input digests, descriptive metrics and integrity checks. It
never decides: no threshold, no ranking, no promotion.

Exit codes: 0 when every integrity check holds, 2 when the report was written
but a round trip or a special-token invariant failed, 1 when the inputs were
refused (nothing is written).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.tokenizer import (
    BOS_TOKEN_ID,
    EOS_TOKEN_ID,
    INPUT_ENCODING,
    MAXIMUM_ARTIFACT_BYTES,
    MAXIMUM_DECODE_TOKEN_IDS,
    MAXIMUM_RUNTIME_TEXT_BYTES,
    PAD_TOKEN_ID,
    SPECIAL_TOKENS,
    UNK_TOKEN_ID,
    ByteBpeTokenizer,
    normalize_text,
    validate_tokenizer_document,
)
from tools.validate_training_corpus_manifest import validate as validate_manifest


REPORT_SCHEMA_VERSION = "tokenizer-evaluation-report.v1"
THRESHOLDS = "none_decided"
INTERPRETATION = "descriptive_only"
WORD_DEFINITION_ID = "unicode-word-regex-v1"
BYTE_DEFINITION_ID = "utf-8-after-nfc"
TOKEN_DEFINITION_ID = "runtime-encode-without-bos-eos"

MAXIMUM_EVAL_BYTES = 64 * 1024 * 1024
MAXIMUM_EVAL_RECORDS = 1_000_000
MAXIMUM_RECORD_ID_LENGTH = 128
MAXIMUM_MANIFEST_BYTES = 4 * 1024 * 1024
MAXIMUM_TOKENIZERS = 8
MAXIMUM_LISTED_FAILURES = 20
FIRST_BYTE_TOKEN_ID = len(SPECIAL_TOKENS)
FIRST_LEARNED_TOKEN_ID = FIRST_BYTE_TOKEN_ID + 256

HELD_OUT_SPLITS = ("validation", "test")
PLAIN_KEYS = frozenset({"record_id", "text"})
LABELLED_KEYS = frozenset({"record_id", "text", "language", "content_type"})
LANGUAGES = frozenset({"fr", "en", "mul", "zxx", "und"})
CONTENT_TYPES = frozenset({"prose", "code", "shell", "config", "log"})
UNLABELLED_LANGUAGE = "und"
UNLABELLED_CONTENT_TYPE = "unlabelled"

LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
WORD = re.compile(r"\w+")

# Probes for the special-token invariants. They are fixed so that two runs
# on the same artifacts produce the same report.
SPECIAL_TOKEN_TEXT_PROBE = "".join(SPECIAL_TOKENS)
WRAP_PROBE = "Évaluation hors ligne, déterministe.\nprint('ok')  # fin"


class EvaluationRefused(ValueError):
    """A refusal whose message never embeds evaluated text."""


class _StrictJsonError(ValueError):
    pass


def _fail(message: str) -> None:
    raise EvaluationRefused(message)


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def read_bounded_file(path: Path, *, maximum_bytes: int, context: str) -> bytes:
    """Read one regular, non-symlink file within its size bound."""
    try:
        before = os.lstat(path)
    except OSError:
        raise EvaluationRefused(f"{context} is unreadable") from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        _fail(f"{context} must be a regular file")
    if not 1 <= before.st_size <= maximum_bytes:
        _fail(f"{context} size is outside the bounded range")
    try:
        with open(path, "rb") as handle:
            payload = handle.read(maximum_bytes + 1)
    except OSError:
        raise EvaluationRefused(f"{context} is unreadable") from None
    if len(payload) != before.st_size:
        _fail(f"{context} changed while it was being read")
    return payload


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise _StrictJsonError("non-finite number")


def strict_json(text: str, context: str) -> Any:
    """Parse JSON without duplicate keys, NaN or Infinity."""
    try:
        return json.loads(
            text, object_pairs_hook=_strict_object, parse_constant=_reject_constant
        )
    except (json.JSONDecodeError, RecursionError, _StrictJsonError):
        raise EvaluationRefused(f"{context} is not strict JSON") from None


def _decode_utf8(payload: bytes, context: str) -> str:
    if payload.startswith(b"\xef\xbb\xbf") or b"\x00" in payload:
        _fail(f"{context} contains a byte order mark or a NUL byte")
    try:
        return payload.decode(INPUT_ENCODING)
    except UnicodeDecodeError:
        raise EvaluationRefused(f"{context} is not valid UTF-8") from None


@dataclass(frozen=True)
class PinnedTokenizer:
    label: str
    sha256: str
    byte_size: int
    metadata: dict[str, Any]
    token_byte_lengths: tuple[int, ...] = field(repr=False)
    tokenizer: ByteBpeTokenizer = field(repr=False, compare=False)


def load_pinned_tokenizer(label: str, path: Path, expected_sha256: str) -> PinnedTokenizer:
    """Load one artifact only if its bytes match the pin and its graph is sound."""
    if not isinstance(label, str) or not LABEL.fullmatch(label):
        _fail("tokenizer label must match ^[a-z0-9][a-z0-9._-]{0,47}$")
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        _fail(f"tokenizer {label}: pinned SHA-256 must be 64 lowercase hexadecimal characters")
    payload = read_bounded_file(
        path, maximum_bytes=MAXIMUM_ARTIFACT_BYTES, context=f"tokenizer {label}"
    )
    digest = sha256_hex(payload)
    if digest != expected_sha256:
        _fail(f"tokenizer {label} does not match its pinned SHA-256")
    document = strict_json(_decode_utf8(payload, f"tokenizer {label}"), f"tokenizer {label}")
    try:
        validate_tokenizer_document(document)
        tokenizer = ByteBpeTokenizer.from_document(document)
    except (TypeError, ValueError) as error:
        raise EvaluationRefused(f"tokenizer {label} is invalid or tampered: {error}") from None
    metadata = {
        "schema_version": document["schema_version"],
        "status": document["status"],
        "algorithm": document["algorithm"],
        "normalization_policy_id": document["normalization_policy_id"],
        "vocabulary_size": document["vocabulary_size"],
        "learned_token_count": len(document["merges"]),
        "minimum_frequency": document["minimum_frequency"],
        "maximum_token_bytes": document["maximum_token_bytes"],
        "training_corpus_id": document["training_corpus_id"],
        "training_corpus_sha256": document["training_corpus_sha256"],
    }
    return PinnedTokenizer(
        label=label,
        sha256=digest,
        byte_size=len(payload),
        metadata=metadata,
        token_byte_lengths=tuple(len(token) // 2 for token in document["tokens_hex"]),
        tokenizer=tokenizer,
    )


@dataclass(frozen=True)
class EvaluationRecord:
    language: str
    content_type: str
    text: str = field(repr=False)

    @property
    def group(self) -> str:
        return f"{self.language}/{self.content_type}"


def parse_evaluation_jsonl(payload: bytes) -> tuple[str, tuple[EvaluationRecord, ...]]:
    """Parse strict JSONL, either all plain split records or all labelled ones."""
    if not 1 <= len(payload) <= MAXIMUM_EVAL_BYTES:
        _fail("evaluation file size is outside the bounded range")
    lines = _decode_utf8(payload, "evaluation file").split("\n")
    if lines[-1] == "":
        lines.pop()
    if not 1 <= len(lines) <= MAXIMUM_EVAL_RECORDS:
        _fail("evaluation record count is outside the bounded range")
    record_format: str | None = None
    record_ids: set[str] = set()
    records: list[EvaluationRecord] = []
    for line_number, line in enumerate(lines, start=1):
        context = f"evaluation record {line_number}"
        if len(line.encode(INPUT_ENCODING)) > MAXIMUM_RUNTIME_TEXT_BYTES:
            _fail(f"{context} exceeds the runtime tokenizer bound")
        record = strict_json(line, context)
        if not isinstance(record, dict):
            _fail(f"{context} must be a JSON object")
        keys = frozenset(record)
        if keys == PLAIN_KEYS:
            current = "plain"
        elif keys == LABELLED_KEYS:
            current = "labelled"
        else:
            _fail(f"{context} keys must be record_id and text, plus language and content_type if labelled")
        if record_format is None:
            record_format = current
        elif current != record_format:
            _fail("evaluation file mixes plain and labelled records")
        record_id = record["record_id"]
        if (
            not isinstance(record_id, str)
            or not 1 <= len(record_id) <= MAXIMUM_RECORD_ID_LENGTH
        ):
            _fail(f"{context} has an invalid record_id")
        if record_id in record_ids:
            _fail(f"{context} repeats a record_id")
        record_ids.add(record_id)
        if not isinstance(record["text"], str) or not record["text"]:
            _fail(f"{context} has an invalid text")
        if current == "labelled":
            if not isinstance(record["language"], str) or record["language"] not in LANGUAGES:
                _fail(f"{context} has an unknown language label")
            if (
                not isinstance(record["content_type"], str)
                or record["content_type"] not in CONTENT_TYPES
            ):
                _fail(f"{context} has an unknown content_type label")
            language, content_type = record["language"], record["content_type"]
        else:
            language, content_type = UNLABELLED_LANGUAGE, UNLABELLED_CONTENT_TYPE
        records.append(
            EvaluationRecord(language=language, content_type=content_type, text=record["text"])
        )
    assert record_format is not None
    return record_format, tuple(records)


def bind_to_manifest(
    manifest_path: Path, split: str, payload: bytes, record_count: int
) -> dict[str, Any]:
    """Prove that the evaluation bytes are exactly one held-out split."""
    if split not in HELD_OUT_SPLITS:
        _fail("only the validation or test split can be evaluated")
    manifest_bytes = read_bounded_file(
        manifest_path, maximum_bytes=MAXIMUM_MANIFEST_BYTES, context="manifest"
    )
    document = strict_json(_decode_utf8(manifest_bytes, "manifest"), "manifest")
    try:
        validate_manifest(document)
    except ValueError as error:
        raise EvaluationRefused(f"manifest is invalid: {error}") from None
    entry = document["splits"][split]
    if (
        len(payload) != entry["byte_size"]
        or sha256_hex(payload) != entry["content_sha256"]
        or record_count != entry["record_count"]
    ):
        _fail(f"evaluation file does not match the manifest {split} split")
    return {
        "manifest_sha256": sha256_hex(manifest_bytes),
        "corpus_id": document["corpus_id"],
        "split": split,
        "train_split_sha256": document["splits"]["train"]["content_sha256"],
        "held_out_split_sha256": sorted(
            document["splits"][name]["content_sha256"] for name in HELD_OUT_SPLITS
        ),
    }


class _Accumulator:
    __slots__ = ("records", "characters", "bytes", "words", "tokens", "single_byte_tokens", "token_ids")

    def __init__(self) -> None:
        self.records = 0
        self.characters = 0
        self.bytes = 0
        self.words = 0
        self.tokens = 0
        self.single_byte_tokens = 0
        self.token_ids: set[int] = set()

    def add(self, *, characters: int, byte_count: int, words: int, token_ids: list[int]) -> None:
        self.records += 1
        self.characters += characters
        self.bytes += byte_count
        self.words += words
        self.tokens += len(token_ids)
        self.single_byte_tokens += sum(
            1 for token_id in token_ids if FIRST_BYTE_TOKEN_ID <= token_id < FIRST_LEARNED_TOKEN_ID
        )
        self.token_ids.update(token_ids)

    def summary(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "characters": self.characters,
            "bytes": self.bytes,
            "words": self.words,
            "tokens": self.tokens,
            "bytes_per_token": _ratio(self.bytes, self.tokens),
            "characters_per_token": _ratio(self.characters, self.tokens),
            "tokens_per_word": _ratio(self.tokens, self.words),
            "single_byte_token_share": _ratio(self.single_byte_tokens, self.tokens),
            "distinct_tokens": len(self.token_ids),
        }


def _token_byte_length(pinned: PinnedTokenizer, token_id: int) -> int:
    index = token_id - FIRST_BYTE_TOKEN_ID
    if 0 <= index < len(pinned.token_byte_lengths):
        return pinned.token_byte_lengths[index]
    return 0


def decode_in_bounded_slices(
    pinned: PinnedTokenizer, token_ids: list[int], expected: bytes
) -> str:
    """Decode with the runtime decoder, slicing long sequences on UTF-8 boundaries.

    The runtime refuses more than ``MAXIMUM_DECODE_TOKEN_IDS`` ids per call.
    Slices end where the expected bytes start a new character, so a correct
    tokenizer round-trips and a faulty one still fails the comparison.
    """
    if len(token_ids) <= MAXIMUM_DECODE_TOKEN_IDS:
        return pinned.tokenizer.decode(token_ids)
    pieces: list[str] = []
    start = 0
    cut = 0
    offset = 0
    for index, token_id in enumerate(token_ids):
        offset += _token_byte_length(pinned, token_id)
        if offset >= len(expected) or (expected[offset] & 0xC0) != 0x80:
            cut = index + 1
        if index + 1 - start == MAXIMUM_DECODE_TOKEN_IDS:
            if cut <= start:
                return "�"
            pieces.append(pinned.tokenizer.decode(token_ids[start:cut]))
            start = cut
    pieces.append(pinned.tokenizer.decode(token_ids[start:]))
    return "".join(pieces)


def special_token_invariants(pinned: PinnedTokenizer) -> dict[str, bool]:
    """Check ids 0-3 and their behaviour on fixed probes."""
    tokenizer = pinned.tokenizer
    expected = normalize_text(WRAP_PROBE)
    checks: dict[str, bool] = {
        "special_token_ids_are_0_to_3": (
            tokenizer.document["special_tokens"] == ["<pad>", "<bos>", "<eos>", "<unk>"]
            and (PAD_TOKEN_ID, BOS_TOKEN_ID, EOS_TOKEN_ID, UNK_TOKEN_ID) == (0, 1, 2, 3)
        ),
    }

    def guarded(name: str, check: Any) -> None:
        try:
            checks[name] = bool(check())
        except ValueError:
            checks[name] = False

    def plain() -> list[int]:
        return tokenizer.encode(WRAP_PROBE)

    def injected() -> list[int]:
        return tokenizer.encode(SPECIAL_TOKEN_TEXT_PROBE)

    guarded(
        "bos_eos_wrap_the_plain_encoding",
        lambda: tokenizer.encode(WRAP_PROBE, bos=True, eos=True) == [BOS_TOKEN_ID, *plain(), EOS_TOKEN_ID],
    )
    guarded(
        "special_token_text_is_not_injectable",
        lambda: all(token_id >= FIRST_BYTE_TOKEN_ID for token_id in injected())
        and tokenizer.decode(injected()) == SPECIAL_TOKEN_TEXT_PROBE,
    )
    guarded(
        "decode_skips_pad_and_bos",
        lambda: tokenizer.decode([PAD_TOKEN_ID, BOS_TOKEN_ID, *plain()]) == expected,
    )
    guarded(
        "decode_stops_at_eos",
        lambda: tokenizer.decode([*plain(), EOS_TOKEN_ID, *injected()]) == expected,
    )
    guarded(
        "unk_decodes_to_the_replacement_character",
        lambda: tokenizer.decode([UNK_TOKEN_ID]) == "�",
    )
    return checks


def evaluate_one(pinned: PinnedTokenizer, records: Iterable[EvaluationRecord]) -> dict[str, Any]:
    overall = _Accumulator()
    by_language: dict[str, _Accumulator] = {}
    by_content_type: dict[str, _Accumulator] = {}
    by_group: dict[str, _Accumulator] = {}
    failed_lines: list[int] = []
    special_id_in_plain_encoding = False
    for line_number, record in enumerate(records, start=1):
        normalized = normalize_text(record.text)
        expected = normalized.encode(INPUT_ENCODING)
        try:
            token_ids = pinned.tokenizer.encode(record.text)
        except ValueError:
            _fail(f"evaluation record {line_number} exceeds the runtime tokenizer bound after NFC")
        if any(token_id < FIRST_BYTE_TOKEN_ID for token_id in token_ids):
            special_id_in_plain_encoding = True
        try:
            round_trip = decode_in_bounded_slices(pinned, token_ids, expected) == normalized
        except ValueError:
            round_trip = False
        if not round_trip:
            failed_lines.append(line_number)
        measures = {
            "characters": len(normalized),
            "byte_count": len(expected),
            "words": len(WORD.findall(normalized)),
            "token_ids": token_ids,
        }
        overall.add(**measures)
        for table, key in (
            (by_language, record.language),
            (by_content_type, record.content_type),
            (by_group, record.group),
        ):
            table.setdefault(key, _Accumulator()).add(**measures)

    invariants = special_token_invariants(pinned)
    invariants["plain_encoding_emits_no_special_id"] = not special_id_in_plain_encoding
    vocabulary_size = pinned.metadata["vocabulary_size"]
    learned_count = pinned.metadata["learned_token_count"]
    used = overall.token_ids
    learned_used = sum(1 for token_id in used if token_id >= FIRST_LEARNED_TOKEN_ID)
    round_trip_report = {
        "records_exact": overall.records - len(failed_lines),
        "records_failed": len(failed_lines),
        "failed_line_numbers": failed_lines[:MAXIMUM_LISTED_FAILURES],
    }
    return {
        "label": pinned.label,
        "artifact": {"sha256": pinned.sha256, "byte_size": pinned.byte_size, **pinned.metadata},
        "special_token_invariants": dict(sorted(invariants.items())),
        "round_trip": round_trip_report,
        "integrity_ok": all(invariants.values()) and not failed_lines,
        "overall": overall.summary(),
        "by_language": {key: value.summary() for key, value in sorted(by_language.items())},
        "by_content_type": {key: value.summary() for key, value in sorted(by_content_type.items())},
        "by_group": {key: value.summary() for key, value in sorted(by_group.items())},
        "vocabulary": {
            "vocabulary_size": vocabulary_size,
            "usable_token_count": vocabulary_size - len(SPECIAL_TOKENS),
            "distinct_tokens_used": len(used),
            "vocabulary_utilisation": _ratio(len(used), vocabulary_size - len(SPECIAL_TOKENS)),
            "learned_token_count": learned_count,
            "distinct_learned_tokens_used": learned_used,
            "learned_token_utilisation": _ratio(learned_used, learned_count),
        },
    }


def compare(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Side-by-side token counts against the first artifact; no ranking."""
    if len(results) < 2:
        return None
    reference = results[0]
    groups = ["overall", *reference["by_group"]]
    by_group: dict[str, Any] = {}
    for group in groups:
        reference_tokens = (
            reference["overall"] if group == "overall" else reference["by_group"][group]
        )["tokens"]
        entry: dict[str, Any] = {}
        for result in results:
            metrics = result["overall"] if group == "overall" else result["by_group"][group]
            entry[result["label"]] = {
                "tokens": metrics["tokens"],
                "bytes_per_token": metrics["bytes_per_token"],
                "tokens_per_word": metrics["tokens_per_word"],
                "token_ratio_vs_reference": _ratio(metrics["tokens"], reference_tokens),
            }
        by_group[group] = entry
    return {
        "reference_label": reference["label"],
        "interpretation": INTERPRETATION,
        "by_group": by_group,
    }


def run_evaluation(
    *,
    tokenizers: list[tuple[str, Path, str]],
    eval_path: Path,
    eval_sha256: str | None = None,
    manifest_path: Path | None = None,
    split: str | None = None,
) -> dict[str, Any]:
    if not 1 <= len(tokenizers) <= MAXIMUM_TOKENIZERS:
        _fail(f"between 1 and {MAXIMUM_TOKENIZERS} tokenizers are required")
    if (manifest_path is None) != (split is None):
        _fail("--manifest and --split must be given together")
    if eval_sha256 is not None and not SHA256.fullmatch(eval_sha256):
        _fail("pinned evaluation SHA-256 must be 64 lowercase hexadecimal characters")
    labels = [label for label, _path, _digest in tokenizers]
    if len(labels) != len(set(labels)):
        _fail("tokenizer labels must be unique")
    pinned = [load_pinned_tokenizer(label, path, digest) for label, path, digest in tokenizers]
    if len({item.sha256 for item in pinned}) != len(pinned):
        _fail("tokenizer artifacts must be distinct")

    payload = read_bounded_file(eval_path, maximum_bytes=MAXIMUM_EVAL_BYTES, context="evaluation file")
    eval_digest = sha256_hex(payload)
    if eval_sha256 is not None and eval_digest != eval_sha256:
        _fail("evaluation file does not match its pinned SHA-256")
    record_format, records = parse_evaluation_jsonl(payload)
    binding = None
    if manifest_path is not None and split is not None:
        binding = bind_to_manifest(manifest_path, split, payload, len(records))
    for item in pinned:
        trained_on = item.metadata["training_corpus_sha256"]
        if trained_on == eval_digest:
            _fail(f"evaluation file is the training split of tokenizer {item.label}")
        if binding is not None and trained_on in binding["held_out_split_sha256"]:
            _fail(f"tokenizer {item.label} was trained on a held-out split")

    results = [evaluate_one(item, records) for item in pinned]
    for result, item in zip(results, pinned):
        result["artifact"]["trained_on_manifest_train_split"] = (
            None if binding is None
            else item.metadata["training_corpus_sha256"] == binding["train_split_sha256"]
        )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "thresholds": THRESHOLDS,
        "interpretation": INTERPRETATION,
        "definitions": {
            "bytes": BYTE_DEFINITION_ID,
            "words": WORD_DEFINITION_ID,
            "tokens": TOKEN_DEFINITION_ID,
        },
        "evaluation_input": {
            "sha256": eval_digest,
            "byte_size": len(payload),
            "record_count": len(records),
            "record_format": record_format,
            "records_changed_by_nfc": sum(
                1 for record in records if normalize_text(record.text) != record.text
            ),
            "manifest_binding": None if binding is None else {
                "manifest_sha256": binding["manifest_sha256"],
                "corpus_id": binding["corpus_id"],
                "split": binding["split"],
            },
        },
        "tokenizers": results,
        "comparison": compare(results),
        "integrity_ok": all(result["integrity_ok"] for result in results),
    }


def write_report(path: Path, report: dict[str, Any]) -> str:
    """Write canonical JSON to a new file only; return its SHA-256."""
    payload = canonical_json_bytes(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "xb") as output:
            output.write(payload)
    except FileExistsError:
        raise EvaluationRefused("report output already exists") from None
    return sha256_hex(payload)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate pinned Byte-BPE tokenizers on a held-out JSONL set (offline)."
    )
    parser.add_argument(
        "--tokenizer",
        nargs=3,
        action="append",
        required=True,
        metavar=("LABEL", "PATH", "SHA256"),
        help="artifact label, path and pinned SHA-256; repeat to compare artifacts",
    )
    parser.add_argument("--eval-jsonl", type=Path, required=True)
    parser.add_argument("--eval-sha256", help="optional pinned SHA-256 of the evaluation file")
    parser.add_argument("--manifest", type=Path, help="corpus manifest binding a held-out split")
    parser.add_argument("--split", choices=HELD_OUT_SPLITS)
    parser.add_argument("--output", type=Path, required=True, help="new report file (never overwritten)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        if arguments.output.exists() or arguments.output.is_symlink():
            _fail("report output already exists")
        report = run_evaluation(
            tokenizers=[(label, Path(path), digest) for label, path, digest in arguments.tokenizer],
            eval_path=arguments.eval_jsonl,
            eval_sha256=arguments.eval_sha256,
            manifest_path=arguments.manifest,
            split=arguments.split,
        )
        report_sha256 = write_report(arguments.output, report)
    except (OSError, ValueError) as error:
        print(f"tokenizer evaluation refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(
        {
            "integrity_ok": report["integrity_ok"],
            "report_sha256": report_sha256,
            "tokenizers": len(report["tokenizers"]),
        },
        sort_keys=True,
    ))
    return 0 if report["integrity_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
