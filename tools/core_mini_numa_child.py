#!/usr/bin/env python3
"""Attest one inherited placement, then exec one fixed CORE-MINI phase."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.cli import PathFreeArgumentParser
from tools.core_mini_numa_benchmark import (
    MEMORY_POLICY_MODES,
    BenchmarkRefused,
    _canonical_json_bytes,
    _require_outside_project,
    _write_atomic_exclusive,
    capture_placement,
    require_inet_sockets_denied,
)


TRAINER = PROJECT_ROOT / "tools" / "train_core_mini.py"
SUMMARIZER = PROJECT_ROOT / "tools" / "summarize_training_metrics.py"
VERIFIER = PROJECT_ROOT / "tools" / "verify_core_checkpoint_compatibility.py"
PHASES = ("runtime", "train", "summarize", "verify")
OPTION_NAMES = {
    "config",
    "output_dir",
    "steps",
    "batch_size",
    "sequence_length",
    "seed",
    "threads",
    "metrics",
    "warmup_steps",
    "output",
    "checkpoint",
}
EXPECTED_OPTIONS = {
    "runtime": set(),
    "train": {
        "config",
        "output_dir",
        "steps",
        "batch_size",
        "sequence_length",
        "seed",
        "threads",
    },
    "summarize": {"metrics", "warmup_steps", "output"},
    "verify": {"checkpoint", "config"},
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = PathFreeArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument(
        "--required-memory-policy",
        choices=tuple(sorted(set(MEMORY_POLICY_MODES.values()))),
        required=True,
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--sequence-length", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--warmup-steps", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    return parser.parse_args(argv)


def _present_options(args: argparse.Namespace) -> set[str]:
    return {name for name in OPTION_NAMES if getattr(args, name) is not None}


def build_phase_command(args: argparse.Namespace) -> list[str]:
    if _present_options(args) != EXPECTED_OPTIONS[args.phase]:
        raise BenchmarkRefused("child phase options are incompatible")
    base = [sys.executable, "-I", "-B"]
    if args.phase == "runtime":
        from tools.core_mini_numa_benchmark import RUNTIME_PROBE

        return [*base, "-c", RUNTIME_PROBE]
    if args.phase == "train":
        return [
            *base,
            str(TRAINER),
            "--config",
            str(args.config),
            "--output-dir",
            str(args.output_dir),
            "--steps",
            str(args.steps),
            "--batch-size",
            str(args.batch_size),
            "--sequence-length",
            str(args.sequence_length),
            "--learning-rate",
            "0.0003",
            "--seed",
            str(args.seed),
            "--threads",
            str(args.threads),
            "--data-mode",
            "synthetic",
        ]
    if args.phase == "summarize":
        return [
            *base,
            str(SUMMARIZER),
            str(args.metrics),
            "--warmup-steps",
            str(args.warmup_steps),
            "--output",
            str(args.output),
        ]
    if args.phase == "verify":
        return [
            *base,
            str(VERIFIER),
            "--checkpoint",
            str(args.checkpoint),
            "--config",
            str(args.config),
        ]
    raise BenchmarkRefused("child phase is incompatible")


def _attestation_document(args: argparse.Namespace) -> dict[str, Any]:
    require_inet_sockets_denied()
    placement = capture_placement(args.required_memory_policy)
    return {
        "schema_version": "core-mini-child-placement.v1",
        "phase": args.phase,
        "cpu_ids": list(placement.cpu_ids),
        "allowed_memory_nodes": list(placement.allowed_memory_nodes),
        "memory_policy": placement.memory_policy,
        "policy_memory_nodes": list(placement.policy_memory_nodes),
        "inet_socket_policy": "stream-and-dgram-denied",
    }


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    command = build_phase_command(args)
    if not Path(sys.executable).is_absolute():
        raise BenchmarkRefused("Python interpreter path is incompatible")
    attestation_path = _require_outside_project(args.attestation, must_exist=False)
    if attestation_path != args.attestation or not attestation_path.parent.is_dir():
        raise BenchmarkRefused("child attestation path is incompatible")
    encoded = _canonical_json_bytes(_attestation_document(args)) + b"\n"
    _write_atomic_exclusive(attestation_path, encoded)
    os.execv(sys.executable, command)
    raise BenchmarkRefused("child exec returned unexpectedly")


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception:
        print("CORE-MINI NUMA child refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
