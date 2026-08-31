#!/usr/bin/env python3
"""Summarize one uninterrupted CORE-MINI metrics file reproducibly."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number} is not valid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"line {line_number} must be an object")
        records.append(record)
    if not records:
        raise ValueError("metrics file is empty")
    return records


def summarize(records: list[dict[str, Any]], *, warmup_steps: int) -> dict[str, Any]:
    if not 0 <= warmup_steps < len(records):
        raise ValueError("warmup_steps must leave at least one measured step")

    durations: list[float] = []
    tokens: list[int] = []
    previous_elapsed = 0.0
    previous_step: int | None = None
    for index, record in enumerate(records):
        step = record.get("step")
        loss = record.get("loss")
        elapsed = record.get("elapsed_seconds")
        token_count = record.get("tokens")
        if not isinstance(step, int) or step < 1:
            raise ValueError(f"record {index + 1} has an invalid step")
        if previous_step is not None and step != previous_step + 1:
            raise ValueError("steps must be contiguous")
        if not isinstance(loss, (int, float)) or not math.isfinite(loss):
            raise ValueError(f"step {step} has a non-finite loss")
        if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed):
            raise ValueError(f"step {step} has invalid elapsed_seconds")
        duration = float(elapsed) - previous_elapsed
        if duration <= 0.0:
            raise ValueError("elapsed_seconds must increase within one run")
        if not isinstance(token_count, int) or token_count < 1:
            raise ValueError(f"step {step} has an invalid token count")
        durations.append(duration)
        tokens.append(token_count)
        previous_elapsed = float(elapsed)
        previous_step = step

    measured_durations = durations[warmup_steps:]
    measured_tokens = tokens[warmup_steps:]
    measured_seconds = sum(measured_durations)
    return {
        "schema_version": "core-mini-metrics-summary.v1",
        "steps_total": len(records),
        "warmup_steps": warmup_steps,
        "steps_measured": len(measured_durations),
        "tokens_measured": sum(measured_tokens),
        "timing_seconds": {
            "total": measured_seconds,
            "median_step": statistics.median(measured_durations),
            "minimum_step": min(measured_durations),
            "maximum_step": max(measured_durations),
        },
        "tokens_per_second": sum(measured_tokens) / measured_seconds,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", type=Path)
    parser.add_argument("--warmup-steps", type=int, default=5)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = load_records(args.metrics)
    result = summarize(records, warmup_steps=args.warmup_steps)
    result["metrics_sha256"] = hashlib.sha256(args.metrics.read_bytes()).hexdigest()
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
