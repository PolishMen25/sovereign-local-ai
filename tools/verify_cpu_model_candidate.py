#!/usr/bin/env python3
"""Instantiate a candidate decoder on CPU and verify its exact parameter count."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from tools.count_core_parameters import CoreConfig, count_parameters
from tools.train_core_mini import build_model, require_cpu_torch


DEFAULT_CONFIG = Path(__file__).parents[1] / "configs" / "models" / "core-700m.candidate.json"


def load_candidate(path: Path) -> tuple[dict[str, Any], CoreConfig]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("status") != "candidate":
        raise ValueError("model configuration must have candidate status")
    if not isinstance(document.get("name"), str) or not document["name"].isascii():
        raise ValueError("model configuration must have an ASCII name")
    config = CoreConfig.from_document(document)
    expected = count_parameters(config)
    if document.get("parameter_count") != expected:
        raise ValueError("declared parameter count does not match the architecture")
    return document, config


def verify(path: Path) -> dict[str, Any]:
    document, config = load_candidate(path)
    torch = require_cpu_torch()
    model = build_model(torch, config)
    observed = sum(parameter.numel() for parameter in model.parameters())
    expected = count_parameters(config)["total_trainable"]
    if observed != expected:
        raise RuntimeError(f"parameter mismatch: expected {expected}, observed {observed}")
    if any(parameter.device.type != "cpu" for parameter in model.parameters()):
        raise RuntimeError("candidate allocated a non-CPU parameter")
    return {
        "schema_version": "cpu-model-instantiation.v1",
        "model_name": document["name"],
        "status": "instantiated_cpu_only",
        "parameters": observed,
        "cuda": torch.version.cuda is not None,
        "rocm": getattr(torch.version, "hip", None) is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.config), sort_keys=True))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"candidate verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
