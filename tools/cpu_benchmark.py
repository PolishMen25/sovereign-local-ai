"""Small, reproducible CPU/NUMA host benchmark.

This is a measurement harness, not a model-training estimate. It records the
host metadata available to the current process and times a deterministic,
CPU-only hashing workload. A future mini-model benchmark can reuse the same
result envelope without changing the provenance fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import time
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20_000)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def metadata() -> dict[str, Any]:
    return {
        "hostname": platform.node(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "process_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
    }


def run_round(iterations: int) -> float:
    payload = b"sovereign-local-ai-cpu-benchmark-v1"
    start = time.perf_counter()
    digest = payload
    for _ in range(iterations):
        digest = hashlib.sha256(digest + payload).digest()
    elapsed = time.perf_counter() - start
    if len(digest) != 32:  # pragma: no cover - defensive invariant
        raise RuntimeError("benchmark digest invariant failed")
    return elapsed


def main() -> int:
    args = parse_args()
    if not 1 <= args.rounds <= 30 or not 1_000 <= args.iterations <= 5_000_000:
        raise SystemExit("rounds must be 1..30 and iterations must be 1000..5000000")
    samples = [run_round(args.iterations) for _ in range(args.rounds)]
    result: dict[str, Any] = {
        "schema_version": "cpu-benchmark-result.v1",
        "workload": {"name": "sha256_chain", "iterations": args.iterations},
        "metadata": metadata(),
        "timing_seconds": {
            "samples": samples,
            "median": statistics.median(samples),
            "minimum": min(samples),
            "maximum": max(samples),
        },
        "interpretation": "host proxy only; not a model tokens-per-second result",
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
