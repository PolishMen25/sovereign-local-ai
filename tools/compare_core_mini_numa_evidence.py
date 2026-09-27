#!/usr/bin/env python3
"""Compare two closed CORE-MINI NUMA proofs without exposing host details.

The output follows schemas/core-mini-numa-comparison.schema.json
(core-mini-numa-comparison.v2). It is descriptive only: it never names a
winning placement and always carries gate_status "g4-open".
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
from pathlib import Path
import re
import stat
import statistics
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.cli import PathFreeArgumentParser
from tools import core_mini_numa_benchmark as benchmark


EVIDENCE_ROOT_KEYS = {
    "schema_version", "artifact_type", "proof_id", "created_at_utc",
    "benchmark_session_id", "canonicalization", "placement", "workload",
    "workload_contract_sha256", "repetitions", "aggregate", "evidence_scope",
}
WORKLOAD_KEYS = {
    "model_name", "data_mode", "repetitions", "source_revision",
    "source_archive_sha256", "source_tree_manifest_sha256",
    "offline_runtime_lock_sha256", "numpy_runtime_lock_sha256",
    "runtime_observation_sha256", "environment_contract_sha256",
    "model_config_sha256", "steps", "warmup_steps", "batch_size",
    "sequence_length", "learning_rate", "seed", "threads",
}
DISTRIBUTION_KEYS = {
    "mean", "median", "minimum", "maximum",
    "population_standard_deviation", "median_absolute_deviation",
}
REPETITION_KEYS = {
    "repetition_id", "status", "metrics_sha256", "summary_sha256",
    "verification_sha256", "checkpoint_sha256", "steps_total", "steps_measured",
    "tokens_measured", "timing_seconds", "tokens_per_second",
}
REPETITION_DIGEST_KEYS = (
    "metrics_sha256", "summary_sha256", "verification_sha256", "checkpoint_sha256",
)
# Same timing contract as the runner's metrics summary: five positive values
# and two non-negative dispersion values, all finite floats.
TIMING_POSITIVE_KEYS = (
    "total", "mean_step", "median_step", "minimum_step", "maximum_step",
)
TIMING_DISPERSION_KEYS = (
    "population_standard_deviation", "median_absolute_deviation",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
PROOF_ID_PATTERN = re.compile(
    r"proof-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
CREATED_AT_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
)
# Every workload field is held to the evidence 0.2.0 contract (and the
# runner's own bounds) before use, so no proof outside that contract is ever
# compared. Only the digests below are echoed in shared_contract: threads and
# the other workload parameters stay bound through workload_contract_sha256
# and each proof file SHA-256, pending the owner's D-025 ruling on publishing
# a thread level equal to the affinity size (protocol, owner point 7).
WORKLOAD_DIGEST_KEYS = (
    "source_archive_sha256", "source_tree_manifest_sha256",
    "offline_runtime_lock_sha256", "numpy_runtime_lock_sha256",
    "runtime_observation_sha256", "environment_contract_sha256",
    "model_config_sha256",
)
WORKLOAD_INTEGER_BOUNDS = {
    "repetitions": (benchmark.MINIMUM_REPETITIONS, benchmark.MAXIMUM_REPETITIONS),
    "steps": (benchmark.MINIMUM_STEPS, benchmark.MAXIMUM_STEPS),
    "batch_size": (1, 64),
    "sequence_length": (2, 512),
    "seed": (-(2**63), (2**63) - 1),
    "threads": (1, 256),
}
EVIDENCE_SCHEMA_VERSION = "0.2.0"
COMPARISON_SCHEMA_VERSION = "core-mini-numa-comparison.v2"
LABEL_A, LABEL_B = benchmark.PLACEMENT_IDS


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _require_regular_non_link(path: Path, subject: str) -> None:
    # The bounded read also uses O_NOFOLLOW where the platform offers it; this
    # explicit check keeps the refusal on platforms without that flag. Like
    # O_NOFOLLOW, it inspects the final path component only: symbolic links in
    # parent directories are followed. The placement verifier reuses it.
    try:
        metadata = os.lstat(path)
    except (OSError, ValueError):
        raise benchmark.BenchmarkRefused(f"{subject} is unavailable") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise benchmark.BenchmarkRefused(
            f"{subject} must be a regular file, not a link"
        )


def _is_finite_float(value: Any) -> bool:
    return type(value) is float and math.isfinite(value)


def _validate_repetition(run: Any, workload: dict[str, Any]) -> float:
    # Repetition fields are not echoed in the comparison, but the comparator
    # refuses any proof outside the 0.2.0 contract, with the runner's bounds.
    if (
        not isinstance(run, dict)
        or set(run) != REPETITION_KEYS
        or run["status"] != "completed"
        or any(not _is_sha256(run[key]) for key in REPETITION_DIGEST_KEYS)
    ):
        raise benchmark.BenchmarkRefused("NUMA repetition is incompatible")
    steps = workload["steps"]
    measured_steps = steps - workload["warmup_steps"]
    tokens_per_step = workload["batch_size"] * workload["sequence_length"]
    expected_counts = {
        "steps_total": steps,
        "steps_measured": measured_steps,
        "tokens_measured": tokens_per_step * measured_steps,
    }
    if any(
        type(run[key]) is not int or run[key] != value
        for key, value in expected_counts.items()
    ):
        raise benchmark.BenchmarkRefused("NUMA repetition counts are incompatible")
    timing = run["timing_seconds"]
    if (
        not isinstance(timing, dict)
        or set(timing) != set(TIMING_POSITIVE_KEYS) | set(TIMING_DISPERSION_KEYS)
        or any(
            not _is_finite_float(timing[key]) or timing[key] <= 0.0
            for key in TIMING_POSITIVE_KEYS
        )
        or any(
            not _is_finite_float(timing[key]) or timing[key] < 0.0
            for key in TIMING_DISPERSION_KEYS
        )
    ):
        raise benchmark.BenchmarkRefused("NUMA repetition timing is incompatible")
    throughput = run["tokens_per_second"]
    if not _is_finite_float(throughput) or throughput <= 0.0:
        raise benchmark.BenchmarkRefused("NUMA throughput is incompatible")
    return throughput


def _validate_workload(workload: dict[str, Any]) -> None:
    def refuse(key: str) -> None:
        raise benchmark.BenchmarkRefused(f"NUMA workload field is incompatible: {key}")

    if workload["model_name"] != "CORE-MINI-1M":
        refuse("model_name")
    if workload["data_mode"] != "synthetic":
        refuse("data_mode")
    revision = workload["source_revision"]
    if (
        not isinstance(revision, str)
        or benchmark.SOURCE_COMMIT_PATTERN.fullmatch(revision) is None
    ):
        refuse("source_revision")
    for key in WORKLOAD_DIGEST_KEYS:
        if not _is_sha256(workload[key]):
            refuse(key)
    for key, (minimum, maximum) in WORKLOAD_INTEGER_BOUNDS.items():
        value = workload[key]
        if type(value) is not int or not minimum <= value <= maximum:
            refuse(key)
    warmup = workload["warmup_steps"]
    if type(warmup) is not int or not 1 <= warmup <= workload["steps"] - 3:
        refuse("warmup_steps")
    rate = workload["learning_rate"]
    if type(rate) is not float or not math.isfinite(rate) or not 0.0 < rate <= 1.0:
        refuse("learning_rate")


def _read_evidence(path: Path) -> tuple[dict[str, Any], str]:
    _require_regular_non_link(path, "NUMA evidence")
    payload = benchmark._read_regular_bytes(
        path, maximum_bytes=benchmark.MAXIMUM_CHILD_OUTPUT_BYTES
    )
    try:
        document = benchmark._parse_json_object(
            payload, expected_keys=EVIDENCE_ROOT_KEYS
        )
    except (ValueError, RecursionError):
        # Oversized integers and deep nesting escape json.JSONDecodeError.
        raise benchmark.BenchmarkRefused("NUMA evidence JSON is invalid") from None
    # The runner writes canonical-json-v1 followed by exactly one LF. Any other
    # byte form (indentation, CRLF, missing or doubled LF, escaped variants)
    # would make the file SHA-256 ambiguous, so it is refused.
    if benchmark._canonical_json_bytes(document) + b"\n" != payload:
        raise benchmark.BenchmarkRefused("NUMA evidence bytes are not canonical")
    if (
        document["schema_version"] != EVIDENCE_SCHEMA_VERSION
        or document["artifact_type"] != benchmark.EVIDENCE_TYPE
        or document["canonicalization"] != "canonical-json-v1"
        or document["evidence_scope"] != "repeated-single-placement-only"
        or not isinstance(document["proof_id"], str)
        or PROOF_ID_PATTERN.fullmatch(document["proof_id"]) is None
        or not isinstance(document["benchmark_session_id"], str)
        or benchmark.SESSION_ID_PATTERN.fullmatch(document["benchmark_session_id"])
        is None
        or not isinstance(document["created_at_utc"], str)
        or CREATED_AT_PATTERN.fullmatch(document["created_at_utc"]) is None
        or not _is_sha256(document["workload_contract_sha256"])
        or not isinstance(document["placement"], dict)
        or set(document["placement"])
        != {"label", "application", "contract_commitment_sha256", "verification"}
        or document["placement"]["application"] != "external"
        or document["placement"]["verification"]
        != "current-process-matched-private-contract"
        or document["placement"]["label"] not in benchmark.PLACEMENT_IDS
        or not _is_sha256(document["placement"]["contract_commitment_sha256"])
        or not isinstance(document["workload"], dict)
        or set(document["workload"]) != WORKLOAD_KEYS
        or not isinstance(document["aggregate"], dict)
        or set(document["aggregate"]) != {"repetitions_completed", "tokens_per_second"}
        or type(document["aggregate"]["repetitions_completed"]) is not int
        or document["aggregate"]["repetitions_completed"] != document["workload"]["repetitions"]
        or not isinstance(document["aggregate"]["tokens_per_second"], dict)
        or set(document["aggregate"]["tokens_per_second"]) != DISTRIBUTION_KEYS
    ):
        raise benchmark.BenchmarkRefused("NUMA evidence is incompatible")
    _validate_workload(document["workload"])
    if hashlib.sha256(benchmark._canonical_json_bytes(document["workload"])).hexdigest() != document["workload_contract_sha256"]:
        raise benchmark.BenchmarkRefused("NUMA workload digest is incompatible")
    repetitions = document["repetitions"]
    expected_count = document["workload"]["repetitions"]
    if (
        type(expected_count) is not int
        or not benchmark.MINIMUM_REPETITIONS
        <= expected_count
        <= benchmark.MAXIMUM_REPETITIONS
        or not isinstance(repetitions, list)
        or len(repetitions) != expected_count
        # type() rather than ==, so that True never stands for repetition 1.
        or [
            run.get("repetition_id")
            if isinstance(run, dict) and type(run.get("repetition_id")) is int
            else None
            for run in repetitions
        ]
        != list(range(1, expected_count + 1))
    ):
        raise benchmark.BenchmarkRefused("NUMA repetitions are incompatible")
    samples = [
        _validate_repetition(run, document["workload"]) for run in repetitions
    ]
    distribution = document["aggregate"]["tokens_per_second"]
    try:
        expected_distribution = {
            "mean": statistics.fmean(samples),
            "median": statistics.median(samples),
            "minimum": min(samples),
            "maximum": max(samples),
            "population_standard_deviation": statistics.pstdev(samples),
            "median_absolute_deviation": statistics.median(
                abs(value - statistics.median(samples)) for value in samples
            ),
        }
    except (OverflowError, ValueError, statistics.StatisticsError):
        # Finite samples near the float maximum overflow fmean's exact sum;
        # library callers expect BenchmarkRefused, never a raw exception.
        raise benchmark.BenchmarkRefused("NUMA aggregate is incompatible") from None
    if any(
        type(distribution[key]) is not float
        or not math.isfinite(distribution[key])
        or distribution[key] != value
        for key, value in expected_distribution.items()
    ):
        raise benchmark.BenchmarkRefused("NUMA aggregate is incompatible")
    return document, hashlib.sha256(payload).hexdigest()


def _require_comparable(
    a: dict[str, Any], a_sha256: str, b: dict[str, Any], b_sha256: str
) -> None:
    # Refusal messages name fixed fields only, never a path or a value.
    if a_sha256 == b_sha256:
        raise benchmark.BenchmarkRefused("NUMA comparison needs two distinct proof files")
    if a["placement"]["label"] != LABEL_A or b["placement"]["label"] != LABEL_B:
        raise benchmark.BenchmarkRefused("NUMA comparison needs placement-a then placement-b")
    if a["proof_id"] == b["proof_id"]:
        raise benchmark.BenchmarkRefused("NUMA comparison needs two distinct proof_id values")
    if a["benchmark_session_id"] != b["benchmark_session_id"]:
        raise benchmark.BenchmarkRefused("NUMA proofs differ on benchmark_session_id")
    for key in sorted(WORKLOAD_KEYS):
        if a["workload"][key] != b["workload"][key]:
            raise benchmark.BenchmarkRefused(f"NUMA proofs differ on workload field: {key}")
    if a["workload_contract_sha256"] != b["workload_contract_sha256"]:
        raise benchmark.BenchmarkRefused("NUMA proofs differ on workload_contract_sha256")
    # The protocol requires two distinct private placement contracts. Salted
    # commitments differ between runs, so equality means the same run (or a
    # copied commitment) is presented twice. Inequality alone does not prove
    # that the two private contracts differ.
    if (
        a["placement"]["contract_commitment_sha256"]
        == b["placement"]["contract_commitment_sha256"]
    ):
        raise benchmark.BenchmarkRefused("NUMA proofs share one placement contract")


def _ratio(numerator: float, denominator: float) -> float:
    value = numerator / denominator
    if not math.isfinite(value) or value <= 0.0:
        raise benchmark.BenchmarkRefused("NUMA descriptive ratio is not finite")
    return value


def _placement_summary(document: dict[str, Any], proof_file_sha256: str) -> dict[str, Any]:
    return {
        "proof_id": document["proof_id"],
        "proof_file_sha256": proof_file_sha256,
        "contract_commitment_sha256": document["placement"]["contract_commitment_sha256"],
        "repetitions_completed": document["aggregate"]["repetitions_completed"],
        "tokens_per_second": dict(document["aggregate"]["tokens_per_second"]),
    }


def compare(placement_a: Path, placement_b: Path) -> dict[str, Any]:
    a, a_sha256 = _read_evidence(placement_a)
    b, b_sha256 = _read_evidence(placement_b)
    _require_comparable(a, a_sha256, b, b_sha256)
    first = a["aggregate"]["tokens_per_second"]
    second = b["aggregate"]["tokens_per_second"]
    # Three to ten repetitions cannot support a significance claim. The
    # artifact reports whether the observed [minimum, maximum] ranges overlap
    # and stops there; a higher median is described, never declared a winner.
    overlap = (
        first["minimum"] <= second["maximum"]
        and second["minimum"] <= first["maximum"]
    )
    if first["median"] > second["median"]:
        higher_median_label = LABEL_A
    elif second["median"] > first["median"]:
        higher_median_label = LABEL_B
    else:
        higher_median_label = "tied"
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "artifact_type": "descriptive-two-placement-comparison",
        "canonicalization": "canonical-json-v1",
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "benchmark_session_id": a["benchmark_session_id"],
        "shared_contract": {
            "workload_contract_sha256": a["workload_contract_sha256"],
            **{key: a["workload"][key] for key in WORKLOAD_DIGEST_KEYS},
        },
        "placements": {
            LABEL_A: _placement_summary(a, a_sha256),
            LABEL_B: _placement_summary(b, b_sha256),
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
            "higher_median_label": higher_median_label,
        },
        "interpretation": "descriptive-only-not-a-core-placement-decision",
        "gate_status": "g4-open",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = PathFreeArgumentParser(description=__doc__)
    parser.add_argument("--placement-a", type=Path, required=True)
    parser.add_argument("--placement-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        document = compare(args.placement_a, args.placement_b)
        encoded = benchmark._canonical_json_bytes(document) + b"\n"
        benchmark._write_atomic_exclusive(args.output, encoded)
        sys.stdout.buffer.write(encoded)
        return 0
    except Exception:
        # Fail closed: CliArgumentError, BenchmarkRefused, OSError and any
        # unexpected parsing error become the same path-free refusal.
        print("CORE-MINI NUMA comparison refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
