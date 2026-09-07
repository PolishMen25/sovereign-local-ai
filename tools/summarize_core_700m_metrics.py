#!/usr/bin/env python3
"""Validate and summarize content-free CORE-700M metrics offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def load_metrics(path: Path) -> list[dict[str, Any]]:
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError("CORE-700M metrics are unavailable") from error
    if not payload or not payload.endswith("\n"):
        raise ValueError("CORE-700M metrics are incomplete")
    records: list[dict[str, Any]] = []
    for expected_step, line in enumerate(payload.splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("CORE-700M metric is not JSON") from error
        if not isinstance(record, dict) or record.get("schema_version") != "core-700m-metric.v1":
            raise ValueError("CORE-700M metric schema is invalid")
        if record.get("step") != expected_step or type(record.get("tokens")) is not int or record["tokens"] < 1:
            raise ValueError("CORE-700M metrics are not contiguous")
        if not isinstance(record.get("loss"), (int, float)) or isinstance(record["loss"], bool):
            raise ValueError("CORE-700M loss is invalid")
        records.append(record)
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ValueError("CORE-700M metrics are empty")
    timed = [record for record in records if isinstance(record.get("elapsed_seconds"), (int, float)) and not isinstance(record.get("elapsed_seconds"), bool) and record["elapsed_seconds"] > 0]
    result: dict[str, Any] = {
        "schema_version": "core-700m-metrics-summary.v1",
        "steps": len(records),
        "last_loss": float(records[-1]["loss"]),
        "timed_steps": len(timed),
    }
    if timed:
        first_elapsed = float(timed[0]["elapsed_seconds"])
        last_elapsed = float(timed[-1]["elapsed_seconds"])
        elapsed = last_elapsed - first_elapsed
        if elapsed > 0:
            result["measured_tokens_per_second"] = sum(record["tokens"] for record in timed[1:]) / elapsed
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(summarize(load_metrics(args.metrics)), sort_keys=True))
    except ValueError as error:
        print(f"CORE-700M metrics refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
