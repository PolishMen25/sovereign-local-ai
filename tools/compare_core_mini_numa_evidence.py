#!/usr/bin/env python3
"""Compare two closed CORE-MINI NUMA proofs without exposing host details."""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
import statistics
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.cli import CliArgumentError, PathFreeArgumentParser
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


def _read_evidence(path: Path) -> tuple[dict[str, Any], str]:
    payload = benchmark._read_regular_bytes(
        path, maximum_bytes=benchmark.MAXIMUM_CHILD_OUTPUT_BYTES
    )
    document = benchmark._parse_json_object(payload, expected_keys=EVIDENCE_ROOT_KEYS)
    if (
        document["schema_version"] != "0.2.0"
        or document["artifact_type"] != benchmark.EVIDENCE_TYPE
        or document["canonicalization"] != "canonical-json-v1"
        or document["evidence_scope"] != "repeated-single-placement-only"
        or not isinstance(document["proof_id"], str)
        or not isinstance(document["benchmark_session_id"], str)
        or not isinstance(document["placement"], dict)
        or set(document["placement"])
        != {"label", "application", "contract_commitment_sha256", "verification"}
        or document["placement"]["application"] != "external"
        or document["placement"]["verification"]
        != "current-process-matched-private-contract"
        or document["placement"]["label"] not in benchmark.PLACEMENT_IDS
        or not isinstance(document["workload"], dict)
        or set(document["workload"]) != WORKLOAD_KEYS
        or not isinstance(document["aggregate"], dict)
        or set(document["aggregate"]) != {"repetitions_completed", "tokens_per_second"}
        or document["aggregate"]["repetitions_completed"] != document["workload"]["repetitions"]
        or not isinstance(document["aggregate"]["tokens_per_second"], dict)
        or set(document["aggregate"]["tokens_per_second"]) != DISTRIBUTION_KEYS
    ):
        raise benchmark.BenchmarkRefused("NUMA evidence is incompatible")
    if hashlib.sha256(benchmark._canonical_json_bytes(document["workload"])).hexdigest() != document["workload_contract_sha256"]:
        raise benchmark.BenchmarkRefused("NUMA workload digest is incompatible")
    repetitions = document["repetitions"]
    expected_count = document["workload"]["repetitions"]
    if (
        type(expected_count) is not int
        or not isinstance(repetitions, list)
        or len(repetitions) != expected_count
        or [run.get("repetition_id") if isinstance(run, dict) else None for run in repetitions]
        != list(range(1, expected_count + 1))
    ):
        raise benchmark.BenchmarkRefused("NUMA repetitions are incompatible")
    samples: list[float] = []
    for run in repetitions:
        if set(run) != REPETITION_KEYS or run["status"] != "completed":
            raise benchmark.BenchmarkRefused("NUMA repetition is incompatible")
        throughput = run["tokens_per_second"]
        if type(throughput) is not float or not math.isfinite(throughput) or throughput <= 0.0:
            raise benchmark.BenchmarkRefused("NUMA throughput is incompatible")
        samples.append(throughput)
    distribution = document["aggregate"]["tokens_per_second"]
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
    if any(
        type(distribution[key]) is not float
        or not math.isfinite(distribution[key])
        or distribution[key] != value
        for key, value in expected_distribution.items()
    ):
        raise benchmark.BenchmarkRefused("NUMA aggregate is incompatible")
    return document, hashlib.sha256(payload).hexdigest()


def compare(placement_a: Path, placement_b: Path) -> dict[str, Any]:
    a, a_sha256 = _read_evidence(placement_a)
    b, b_sha256 = _read_evidence(placement_b)
    if (
        a["placement"]["label"] != "placement-a"
        or b["placement"]["label"] != "placement-b"
        or a["proof_id"] == b["proof_id"]
        or a["benchmark_session_id"] != b["benchmark_session_id"]
        or a["workload"] != b["workload"]
        or a["workload_contract_sha256"] != b["workload_contract_sha256"]
    ):
        raise benchmark.BenchmarkRefused("NUMA proofs are not comparable")
    a_median = a["aggregate"]["tokens_per_second"]["median"]
    b_median = b["aggregate"]["tokens_per_second"]["median"]
    return {
        "schema_version": "core-mini-numa-comparison.v1",
        "artifact_type": "descriptive-two-placement-comparison",
        "benchmark_session_id": a["benchmark_session_id"],
        "workload_contract_sha256": a["workload_contract_sha256"],
        "evidence": {
            "placement_a": {"proof_id": a["proof_id"], "sha256": a_sha256, "median_tokens_per_second": a_median},
            "placement_b": {"proof_id": b["proof_id"], "sha256": b_sha256, "median_tokens_per_second": b_median},
        },
        "median_tokens_per_second_ratio_a_over_b": a_median / b_median,
        "interpretation": "descriptive-only-not-a-core-placement-decision",
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
    except (CliArgumentError, benchmark.BenchmarkRefused, OSError):
        print("CORE-MINI NUMA comparison refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
