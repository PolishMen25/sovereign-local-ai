#!/usr/bin/env python3
"""Validate and summarize one uninterrupted CORE-MINI metrics journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import statistics
import sys
import tempfile
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.checkpoint import (
    MAXIMUM_TOTAL_STEPS,
    strict_recursive_equal,
)
from services.inference.cli import PathFreeArgumentParser
from services.inference.tokenizer import (
    ARTIFACT_STATUS,
    MAXIMUM_VOCABULARY_SIZE,
    NORMALIZATION_POLICY_ID,
    SCHEMA_VERSION as TOKENIZER_SCHEMA_VERSION,
)
from tools.authorized_text_bundle import (
    BUNDLE_SCHEMA_VERSION,
    MAXIMUM_TRAIN_BYTES,
    MAXIMUM_TRAIN_RECORDS,
)
from tools.validate_training_corpus_manifest import CORPUS_ID


MAXIMUM_METRICS_BYTES = 64 * 1024 * 1024
MAXIMUM_METRIC_RECORD_BYTES = 64 * 1024
MAXIMUM_JSON_INTEGER = 2**63 - 1
MAXIMUM_JSON_NUMBER_CHARACTERS = 64
MINIMUM_TOKENS_PER_STEP = 2
MAXIMUM_TOKENS_PER_STEP = 64 * 512
SYNTHETIC_KEYS = {"step", "loss", "elapsed_seconds", "tokens"}
AUTHORIZED_KEYS = SYNTHETIC_KEYS | {
    "data_mode",
    "data_lineage",
    "training_contract_sha256",
}
AUTHORIZED_LINEAGE_KEYS = {"schema_version", "mode", "corpus", "tokenizer"}
AUTHORIZED_CORPUS_KEYS = {
    "corpus_id",
    "manifest_schema_version",
    "manifest_sha256",
    "split",
    "content_sha256",
    "byte_size",
    "record_count",
}
AUTHORIZED_TOKENIZER_KEYS = {
    "schema_version",
    "status",
    "content_sha256",
    "vocabulary_size",
    "normalization_policy_id",
}
TRAINING_CORPUS_MANIFEST_SCHEMA_VERSION = "0.2.0"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("metrics contain a duplicate JSON object key")
        document[key] = value
    return document


def _reject_json_constant(value: str) -> None:
    del value
    raise ValueError("metrics contain a non-finite JSON number")


def _parse_json_integer(value: str) -> int:
    if len(value) > MAXIMUM_JSON_NUMBER_CHARACTERS:
        raise ValueError("metrics contain an oversized JSON integer")
    parsed = int(value)
    if not -MAXIMUM_JSON_INTEGER <= parsed <= MAXIMUM_JSON_INTEGER:
        raise ValueError("metrics contain an out-of-range JSON integer")
    return parsed


def _parse_json_float(value: str) -> float:
    if len(value) > MAXIMUM_JSON_NUMBER_CHARACTERS:
        raise ValueError("metrics contain an oversized JSON number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("metrics contain a non-finite JSON number")
    return parsed


def _read_regular_file(path: Path) -> bytes:
    """Read one bounded regular file from stable metadata."""

    try:
        with path.open("rb") as metrics_file:
            metadata_before = os.fstat(metrics_file.fileno())
            if not stat.S_ISREG(metadata_before.st_mode):
                raise ValueError("metrics must be a regular file")
            if not 1 <= metadata_before.st_size <= MAXIMUM_METRICS_BYTES:
                raise ValueError("metrics size is outside the allowed range")
            payload = metrics_file.read(metadata_before.st_size + 1)
            metadata_after = os.fstat(metrics_file.fileno())
    except ValueError:
        raise
    except OSError:
        raise ValueError("metrics are unavailable") from None
    if (
        len(payload) != metadata_before.st_size
        or metadata_after.st_dev != metadata_before.st_dev
        or metadata_after.st_ino != metadata_before.st_ino
        or metadata_after.st_mode != metadata_before.st_mode
        or metadata_after.st_size != metadata_before.st_size
        or metadata_after.st_mtime_ns != metadata_before.st_mtime_ns
        or metadata_after.st_ctime_ns != metadata_before.st_ctime_ns
    ):
        raise ValueError("metrics changed while being read")
    return payload


def parse_records(payload: bytes) -> list[dict[str, Any]]:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAXIMUM_METRICS_BYTES:
        raise ValueError("metrics size is outside the allowed range")
    if not payload.endswith(b"\n"):
        raise ValueError("metrics end with an incomplete record")

    lines = payload.split(b"\n")[:-1]
    if not 1 <= len(lines) <= MAXIMUM_TOTAL_STEPS:
        raise ValueError("metrics record count is outside the allowed range")

    records: list[dict[str, Any]] = []
    for line in lines:
        if line.endswith(b"\r"):
            line = line[:-1]
        if not 1 <= len(line) <= MAXIMUM_METRIC_RECORD_BYTES:
            raise ValueError("metrics record size is outside the allowed range")
        try:
            decoded = line.decode("utf-8", errors="strict")
            record = json.loads(
                decoded,
                object_pairs_hook=_unique_json_object,
                parse_int=_parse_json_integer,
                parse_float=_parse_json_float,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("metrics contain invalid strict JSON") from None
        if not isinstance(record, dict):
            raise ValueError("metrics record must be an object")
        records.append(record)
    return records


def load_records(path: Path) -> tuple[list[dict[str, Any]], str]:
    payload = _read_regular_file(path)
    return parse_records(payload), hashlib.sha256(payload).hexdigest()


def _validate_digest(value: Any) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("metrics training contract digest is invalid")
    return value


def _validate_authorized_lineage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != AUTHORIZED_LINEAGE_KEYS:
        raise ValueError("metrics data lineage keys are incompatible")
    if value["schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise ValueError("metrics data lineage schema is incompatible")
    if value["mode"] != "authorized-text":
        raise ValueError("metrics data lineage mode is incompatible")

    corpus = value["corpus"]
    if not isinstance(corpus, dict) or set(corpus) != AUTHORIZED_CORPUS_KEYS:
        raise ValueError("metrics corpus lineage keys are incompatible")
    if (
        type(corpus["corpus_id"]) is not str
        or CORPUS_ID.fullmatch(corpus["corpus_id"]) is None
    ):
        raise ValueError("metrics corpus lineage identifier is invalid")
    if corpus["manifest_schema_version"] != TRAINING_CORPUS_MANIFEST_SCHEMA_VERSION:
        raise ValueError("metrics corpus manifest schema is incompatible")
    _validate_digest(corpus["manifest_sha256"])
    if corpus["split"] != "train":
        raise ValueError("metrics corpus split is incompatible")
    _validate_digest(corpus["content_sha256"])
    if (
        type(corpus["byte_size"]) is not int
        or not 1 <= corpus["byte_size"] <= MAXIMUM_TRAIN_BYTES
    ):
        raise ValueError("metrics corpus byte size is invalid")
    if (
        type(corpus["record_count"]) is not int
        or not 1 <= corpus["record_count"] <= MAXIMUM_TRAIN_RECORDS
    ):
        raise ValueError("metrics corpus record count is invalid")

    tokenizer = value["tokenizer"]
    if not isinstance(tokenizer, dict) or set(tokenizer) != AUTHORIZED_TOKENIZER_KEYS:
        raise ValueError("metrics tokenizer lineage keys are incompatible")
    if tokenizer["schema_version"] != TOKENIZER_SCHEMA_VERSION:
        raise ValueError("metrics tokenizer schema is incompatible")
    if tokenizer["status"] != ARTIFACT_STATUS:
        raise ValueError("metrics tokenizer status is incompatible")
    _validate_digest(tokenizer["content_sha256"])
    if (
        type(tokenizer["vocabulary_size"]) is not int
        or not 260 <= tokenizer["vocabulary_size"] <= MAXIMUM_VOCABULARY_SIZE
    ):
        raise ValueError("metrics tokenizer vocabulary size is invalid")
    if tokenizer["normalization_policy_id"] != NORMALIZATION_POLICY_ID:
        raise ValueError("metrics tokenizer normalization policy is incompatible")
    return value


def _paths_alias(source: Path, target: Path) -> bool:
    try:
        source_absolute = os.path.normcase(os.path.abspath(os.fspath(source)))
        target_absolute = os.path.normcase(os.path.abspath(os.fspath(target)))
        if source_absolute == target_absolute:
            return True
        source_real = os.path.normcase(os.path.realpath(source_absolute))
        target_real = os.path.normcase(os.path.realpath(target_absolute))
        if source_real == target_real:
            return True
        try:
            return os.path.samefile(source_absolute, target_absolute)
        except FileNotFoundError:
            return False
    except OSError:
        raise ValueError("metrics paths are unavailable") from None


def _require_distinct_output(source: Path, target: Path) -> None:
    if _paths_alias(source, target):
        raise ValueError("metrics output must not replace its source")


def summarize(records: list[dict[str, Any]], *, warmup_steps: int) -> dict[str, Any]:
    if type(warmup_steps) is not int or not 0 <= warmup_steps < len(records):
        raise ValueError("warmup_steps must leave at least one measured step")
    if not 1 <= len(records) <= MAXIMUM_TOTAL_STEPS:
        raise ValueError("metrics record count is outside the allowed range")

    first_keys = set(records[0]) if isinstance(records[0], dict) else set()
    if first_keys == SYNTHETIC_KEYS:
        data_mode = "synthetic"
        expected_lineage: Any = None
        expected_contract_sha256: str | None = None
    elif first_keys == AUTHORIZED_KEYS:
        data_mode = "authorized-text"
        expected_lineage = _validate_authorized_lineage(
            records[0].get("data_lineage")
        )
        expected_contract_sha256 = _validate_digest(
            records[0].get("training_contract_sha256")
        )
    else:
        raise ValueError("metrics record keys are incompatible")

    durations: list[float] = []
    tokens: list[int] = []
    previous_elapsed = 0.0
    previous_step: int | None = None
    expected_tokens: int | None = None
    for expected_step, record in enumerate(records, 1):
        if not isinstance(record, dict) or set(record) != first_keys:
            raise ValueError("metrics record keys are incompatible")
        step = record.get("step")
        loss = record.get("loss")
        elapsed = record.get("elapsed_seconds")
        token_count = record.get("tokens")
        if type(step) is not int or step != expected_step:
            raise ValueError("metrics step is invalid")
        if previous_step is not None and step != previous_step + 1:
            raise ValueError("metrics steps are not contiguous")
        if type(loss) is not float or not math.isfinite(loss) or loss < 0.0:
            raise ValueError("metrics loss is invalid")
        if type(elapsed) is not float or not math.isfinite(elapsed):
            raise ValueError("metrics elapsed time is invalid")
        duration = elapsed - previous_elapsed
        if duration <= 0.0:
            raise ValueError("metrics elapsed time must increase")
        if (
            type(token_count) is not int
            or not MINIMUM_TOKENS_PER_STEP
            <= token_count
            <= MAXIMUM_TOKENS_PER_STEP
        ):
            raise ValueError("metrics token count is invalid")
        if expected_tokens is None:
            expected_tokens = token_count
        elif token_count != expected_tokens:
            raise ValueError("metrics token count changed within the run")

        if data_mode == "authorized-text":
            if record.get("data_mode") != data_mode:
                raise ValueError("metrics data mode is invalid")
            received_lineage = _validate_authorized_lineage(
                record.get("data_lineage")
            )
            if not strict_recursive_equal(received_lineage, expected_lineage):
                raise ValueError("metrics data lineage changed within the run")
            if _validate_digest(record.get("training_contract_sha256")) != expected_contract_sha256:
                raise ValueError("metrics training contract changed within the run")

        durations.append(duration)
        tokens.append(token_count)
        previous_elapsed = elapsed
        previous_step = step

    measured_durations = durations[warmup_steps:]
    measured_tokens = tokens[warmup_steps:]
    try:
        measured_seconds = math.fsum(measured_durations)
        mean_step = statistics.fmean(measured_durations)
        median_step = statistics.median(measured_durations)
        standard_deviation = statistics.pstdev(measured_durations)
        median_absolute_deviation = statistics.median(
            abs(duration - median_step) for duration in measured_durations
        )
        tokens_per_second = sum(measured_tokens) / measured_seconds
    except (OverflowError, statistics.StatisticsError, ZeroDivisionError):
        raise ValueError("metrics timing statistics are invalid") from None
    if not all(
        math.isfinite(value)
        for value in (
            measured_seconds,
            mean_step,
            median_step,
            standard_deviation,
            median_absolute_deviation,
            tokens_per_second,
        )
    ):
        raise ValueError("metrics timing statistics are invalid")
    return {
        "schema_version": "core-mini-metrics-summary.v2",
        "data_mode": data_mode,
        "steps_total": len(records),
        "warmup_steps": warmup_steps,
        "steps_measured": len(measured_durations),
        "tokens_per_step": expected_tokens,
        "tokens_measured": sum(measured_tokens),
        "timing_seconds": {
            "total": measured_seconds,
            "mean_step": mean_step,
            "median_step": median_step,
            "minimum_step": min(measured_durations),
            "maximum_step": max(measured_durations),
            "population_standard_deviation": standard_deviation,
            "median_absolute_deviation": median_absolute_deviation,
        },
        "tokens_per_second": tokens_per_second,
    }


def _atomic_write(path: Path, payload: bytes, *, source_path: Path) -> None:
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        _require_distinct_output(source_path, path)
        if os.path.lexists(path):
            raise ValueError("metrics summary output already exists")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output_file:
            descriptor = None
            output_file.write(payload)
            output_file.flush()
            os.fsync(output_file.fileno())
        _require_distinct_output(source_path, path)
        os.link(temporary_path, path, follow_symlinks=False)
        temporary_path.unlink()
        temporary_path = None
        if os.name != "nt":
            directory_descriptor = os.open(
                path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    except OSError:
        raise ValueError("metrics summary output is unavailable") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = PathFreeArgumentParser(description=__doc__)
    parser.add_argument("metrics", type=Path)
    parser.add_argument("--warmup-steps", type=int, default=5)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output is not None:
        _require_distinct_output(args.metrics, args.output)
    records, metrics_sha256 = load_records(args.metrics)
    result = summarize(records, warmup_steps=args.warmup_steps)
    result["metrics_sha256"] = metrics_sha256
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    if args.output is not None:
        _atomic_write(args.output, encoded, source_path=args.metrics)
    sys.stdout.buffer.write(encoded)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception:
        print("CORE-MINI metrics summary refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
