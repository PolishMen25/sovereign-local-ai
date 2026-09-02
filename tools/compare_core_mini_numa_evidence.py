#!/usr/bin/env python3
"""Compare exactly two CORE-MINI placement proofs without concluding a gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any
from uuid import UUID, uuid5


SCHEMA_VERSION = "0.1.0"
ARTIFACT_TYPE = "two-placement-descriptive-comparison"
CANONICALIZATION = "canonical-json-v1"
EVIDENCE_SCOPE = "descriptive-two-placement-comparison-only"
GATE_STATUS = "g4-open"

EVIDENCE_ARTIFACT_TYPE = "single-placement-run-proof"
EVIDENCE_SCHEMA_VERSION = "0.1.0"
EVIDENCE_SCOPE_EXPECTED = "repeated-single-placement-only"

LABEL_A = "placement-a"
LABEL_B = "placement-b"

MAXIMUM_EVIDENCE_BYTES = 1_048_576
MINIMUM_REPETITIONS = 3

COMPARISON_NAMESPACE = UUID("8f1d6f6c-0b2a-4a3e-9d5f-6c7b8a9e0d13")

# Workload fields that must be byte-identical across both proofs. The runner
# already binds them into workload_contract_sha256; they are re-checked here so
# a refusal names the drifting field instead of an opaque digest mismatch.
SHARED_WORKLOAD_FIELDS = (
    "model_name",
    "data_mode",
    "source_revision",
    "source_archive_sha256",
    "source_tree_manifest_sha256",
    "offline_runtime_lock_sha256",
    "runtime_observation_sha256",
    "environment_contract_sha256",
    "model_config_sha256",
    "steps",
    "warmup_steps",
    "batch_size",
    "sequence_length",
    "learning_rate",
    "seed",
    "threads",
)

DISTRIBUTION_FIELDS = (
    "mean",
    "median",
    "minimum",
    "maximum",
    "population_standard_deviation",
    "median_absolute_deviation",
)


class ComparisonRefused(Exception):
    """Refusal carrying no path, host detail or private contract content."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ComparisonRefused("proof contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ComparisonRefused("proof contains a non-finite JSON value")


def _read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise ComparisonRefused("proof is not a regular file")
        if not 1 <= status.st_size <= MAXIMUM_EVIDENCE_BYTES:
            raise ComparisonRefused("proof size is outside the allowed range")
        payload = os.read(descriptor, status.st_size + 1)
    except ComparisonRefused:
        raise
    except OSError:
        raise ComparisonRefused("proof cannot be read safely") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(payload) != status.st_size:
        raise ComparisonRefused("proof changed while being read")
    return payload


def canonical_json_bytes(document: Any) -> bytes:
    try:
        return json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise ComparisonRefused("canonical JSON creation failed") from None


def sha256_document(document: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def parse_proof(payload: bytes) -> dict[str, Any]:
    """Parse one proof file, rejecting anything the runner would not have emitted."""
    if b"\x00" in payload:
        raise ComparisonRefused("proof contains a NUL byte")
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        raise ComparisonRefused("proof is not canonical bytes plus one LF")
    try:
        document = json.loads(
            payload[:-1].decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except ComparisonRefused:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ComparisonRefused("proof is not strict UTF-8 JSON") from None
    if not isinstance(document, dict):
        raise ComparisonRefused("proof is not a JSON object")
    if canonical_json_bytes(document) != payload[:-1]:
        raise ComparisonRefused("proof is not in canonical form")
    for key, expected in (
        ("schema_version", EVIDENCE_SCHEMA_VERSION),
        ("artifact_type", EVIDENCE_ARTIFACT_TYPE),
        ("canonicalization", CANONICALIZATION),
        ("evidence_scope", EVIDENCE_SCOPE_EXPECTED),
    ):
        if document.get(key) != expected:
            raise ComparisonRefused(f"proof {key} is not supported")
    return document


def _require_mapping(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise ComparisonRefused(f"proof {key} is missing or malformed")
    return value


def _require_distribution(aggregate: dict[str, Any]) -> dict[str, float]:
    distribution = aggregate.get("tokens_per_second")
    if not isinstance(distribution, dict) or set(distribution) != set(DISTRIBUTION_FIELDS):
        raise ComparisonRefused("proof throughput distribution is malformed")
    values: dict[str, float] = {}
    for field in DISTRIBUTION_FIELDS:
        raw = distribution[field]
        # bool is an int subclass; a boolean here would silently become 0.0/1.0.
        if type(raw) not in (int, float):
            raise ComparisonRefused("proof throughput statistic is not a number")
        number = float(raw)
        if number != number or number in (float("inf"), float("-inf")):
            raise ComparisonRefused("proof throughput statistic is not finite")
        if field.endswith("deviation"):
            if number < 0:
                raise ComparisonRefused("proof throughput deviation is negative")
        elif number <= 0:
            raise ComparisonRefused("proof throughput statistic is not positive")
        values[field] = number
    if not values["minimum"] <= values["median"] <= values["maximum"]:
        raise ComparisonRefused("proof median falls outside its observed range")
    if not values["minimum"] <= values["mean"] <= values["maximum"]:
        raise ComparisonRefused("proof mean falls outside its observed range")
    return values


def summarize_proof(document: dict[str, Any], proof_file_sha256: str) -> dict[str, Any]:
    """Reduce one verified proof to the fields the public comparison may carry."""
    placement = _require_mapping(document, "placement")
    workload = _require_mapping(document, "workload")
    aggregate = _require_mapping(document, "aggregate")

    label = placement.get("label")
    if label not in (LABEL_A, LABEL_B):
        raise ComparisonRefused("proof placement label is not recognised")

    declared = document.get("workload_contract_sha256")
    recomputed = sha256_document(workload)
    if declared != recomputed:
        raise ComparisonRefused("proof workload contract digest does not match its workload")

    completed = aggregate.get("repetitions_completed")
    if type(completed) is not int or completed < MINIMUM_REPETITIONS:
        raise ComparisonRefused("proof reports too few completed repetitions")
    repetitions = document.get("repetitions")
    if not isinstance(repetitions, list) or len(repetitions) != completed:
        raise ComparisonRefused("proof repetition count is inconsistent")
    if workload.get("repetitions") != completed:
        raise ComparisonRefused("proof workload repetition count is inconsistent")

    commitment = placement.get("contract_commitment_sha256")
    if not isinstance(commitment, str):
        raise ComparisonRefused("proof placement commitment is malformed")

    return {
        "label": label,
        "proof_id": document.get("proof_id"),
        "proof_file_sha256": proof_file_sha256,
        "contract_commitment_sha256": commitment,
        "repetitions_completed": completed,
        "tokens_per_second": _require_distribution(aggregate),
        "benchmark_session_id": document.get("benchmark_session_id"),
        "workload_contract_sha256": recomputed,
        "workload": workload,
    }


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        raise ComparisonRefused("proof throughput denominator is not positive")
    value = numerator / denominator
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        raise ComparisonRefused("descriptive ratio is not a positive finite number")
    return value


def compare(side_a: dict[str, Any], side_b: dict[str, Any]) -> dict[str, Any]:
    """Build the comparison artifact from two already-verified proof summaries."""
    if side_a["label"] != LABEL_A or side_b["label"] != LABEL_B:
        raise ComparisonRefused("comparison requires one placement-a and one placement-b proof")
    if side_a["proof_id"] == side_b["proof_id"]:
        raise ComparisonRefused("comparison requires two distinct proofs")
    if side_a["proof_file_sha256"] == side_b["proof_file_sha256"]:
        raise ComparisonRefused("comparison requires two distinct proof files")
    if side_a["benchmark_session_id"] != side_b["benchmark_session_id"]:
        raise ComparisonRefused("proofs do not share one benchmark session")
    if side_a["workload_contract_sha256"] != side_b["workload_contract_sha256"]:
        raise ComparisonRefused("proofs do not share one workload contract")
    for field in SHARED_WORKLOAD_FIELDS:
        if side_a["workload"].get(field) != side_b["workload"].get(field):
            raise ComparisonRefused(f"proofs disagree on workload field {field}")
    if side_a["contract_commitment_sha256"] == side_b["contract_commitment_sha256"]:
        raise ComparisonRefused("proofs share one placement contract, so there is nothing to compare")

    first = side_a["tokens_per_second"]
    second = side_b["tokens_per_second"]

    # Overlap is judged on observed minima and maxima only. Three to ten
    # repetitions cannot support a significance claim, so the artifact reports
    # what was observed and stops there.
    overlap = first["minimum"] <= second["maximum"] and second["minimum"] <= first["maximum"]
    if first["median"] > second["median"]:
        higher = LABEL_A
    elif second["median"] > first["median"]:
        higher = LABEL_B
    else:
        higher = "tied"

    workload = side_a["workload"]
    comparison_id = uuid5(
        COMPARISON_NAMESPACE,
        "\n".join(sorted((side_a["proof_file_sha256"], side_b["proof_file_sha256"]))),
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "canonicalization": CANONICALIZATION,
        "comparison_id": f"comparison-{comparison_id}",
        "created_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "benchmark_session_id": side_a["benchmark_session_id"],
        "shared_contract": {
            "workload_contract_sha256": side_a["workload_contract_sha256"],
            "source_revision": workload["source_revision"],
            "source_archive_sha256": workload["source_archive_sha256"],
            "source_tree_manifest_sha256": workload["source_tree_manifest_sha256"],
            "offline_runtime_lock_sha256": workload["offline_runtime_lock_sha256"],
            "runtime_observation_sha256": workload["runtime_observation_sha256"],
            "environment_contract_sha256": workload["environment_contract_sha256"],
            "model_config_sha256": workload["model_config_sha256"],
            "steps": workload["steps"],
            "warmup_steps": workload["warmup_steps"],
            "batch_size": workload["batch_size"],
            "sequence_length": workload["sequence_length"],
            "seed": workload["seed"],
            "threads": workload["threads"],
        },
        "placements": {
            LABEL_A: {
                "proof_id": side_a["proof_id"],
                "proof_file_sha256": side_a["proof_file_sha256"],
                "contract_commitment_sha256": side_a["contract_commitment_sha256"],
                "repetitions_completed": side_a["repetitions_completed"],
                "tokens_per_second": first,
            },
            LABEL_B: {
                "proof_id": side_b["proof_id"],
                "proof_file_sha256": side_b["proof_file_sha256"],
                "contract_commitment_sha256": side_b["contract_commitment_sha256"],
                "repetitions_completed": side_b["repetitions_completed"],
                "tokens_per_second": second,
            },
        },
        "descriptive_ratios": {
            "mean_b_over_a": _ratio(second["mean"], first["mean"]),
            "median_b_over_a": _ratio(second["median"], first["median"]),
            "minimum_b_over_a": _ratio(second["minimum"], first["minimum"]),
            "maximum_b_over_a": _ratio(second["maximum"], first["maximum"]),
        },
        "separation": {
            "observed_ranges_overlap": overlap,
            "outcome": "inconclusive-overlapping-observed-ranges"
            if overlap
            else "disjoint-observed-ranges",
            "higher_median_label": higher,
        },
        "evidence_scope": EVIDENCE_SCOPE,
        "gate_status": GATE_STATUS,
    }


def load_proof(path: Path) -> dict[str, Any]:
    payload = _read_regular_bytes(path)
    document = parse_proof(payload)
    return summarize_proof(document, hashlib.sha256(payload).hexdigest())


def _write_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise ComparisonRefused("comparison was not written completely")
        os.fsync(descriptor)
    except FileExistsError:
        raise ComparisonRefused("comparison output already exists") from None
    except ComparisonRefused:
        raise
    except OSError:
        raise ComparisonRefused("comparison output cannot be written") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-a", type=Path, required=True)
    parser.add_argument("--evidence-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        side_a = load_proof(arguments.evidence_a)
        side_b = load_proof(arguments.evidence_b)
        comparison = compare(side_a, side_b)
        payload = canonical_json_bytes(comparison) + b"\n"
        _write_exclusive(arguments.output, payload)
    except ComparisonRefused as refusal:
        # Refusals never echo an operand, so no path reaches the public output.
        print(f"comparison refused: {refusal}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
