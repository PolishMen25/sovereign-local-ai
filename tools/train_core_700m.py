#!/usr/bin/env python3
"""Run a bounded CPU-only candidate CORE stage from candidate-core text artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.configuration import load_core_candidate_configuration
from services.inference.model import build_model, require_cpu_torch
from tools.authorized_text_bundle import load_authorized_text_bundle
from tools.pretokenized_authorized_text import (
    PretokenizedAuthorizedText,
    load_pretokenized_authorized_text,
    pretokenized_text_token_rows,
)
from tools.train_core_mini import authorized_text_token_rows

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "models" / "core-700m.candidate.json"
MAXIMUM_TOTAL_STEPS = 20_000


def calculate_final_step(*, start_step: int, steps: int) -> int:
    """Return the bounded final step for a resumable candidate CORE run."""

    if type(start_step) is not int or start_step < 0:
        raise ValueError("CORE start step is invalid")
    if type(steps) is not int or not 1 <= steps <= MAXIMUM_TOTAL_STEPS:
        raise ValueError("CORE run limits are invalid")
    final_step = start_step + steps
    if final_step > MAXIMUM_TOTAL_STEPS:
        raise ValueError("CORE total step limit is exceeded")
    return final_step


def load_preflight(
    path: Path, *, model_name: str, config_sha256: str, bundle: Any
) -> dict[str, Any]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("CORE preflight receipt is unavailable") from error
    expected = {"schema_version": f"{model_name.lower()}-tokenizer-preflight.v1", "model_name": model_name, "model_config_sha256": config_sha256, "tokenizer_status": "candidate_core", "tokenizer_sha256": bundle.tokenizer_sha256, "tokenizer_vocabulary_size": bundle.tokenizer_vocabulary_size, "corpus_id": bundle.corpus_id, "manifest_sha256": bundle.manifest_sha256, "train_split_sha256": bundle.train_sha256}
    if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("CORE preflight receipt does not match the authorized inputs")
    return receipt


def atomic_save(torch: Any, path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def metric_record(
    *, model_name: str = "CORE-700M", step: int, loss: float, tokens: int,
    elapsed_seconds: float, cpu_seconds: float,
) -> dict[str, Any]:
    """Return a content-free, measurable CPU training metric."""
    if type(step) is not int or step < 1 or type(tokens) is not int or tokens < 1:
        raise ValueError("CORE metric fields are invalid")
    if not all(isinstance(value, float) and value >= 0.0 for value in (loss, elapsed_seconds, cpu_seconds)):
        raise ValueError("CORE metric values are invalid")
    return {
        "schema_version": f"{model_name.lower()}-metric.v1",
        "step": step,
        "loss": loss,
        "tokens": tokens,
        "elapsed_seconds": elapsed_seconds,
        "cpu_seconds": cpu_seconds,
    }


def load_resume(
    torch: Any, path: Path, *, model_name: str, contract: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    """Load only an exact, CPU checkpoint belonging to this run contract."""
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as error:
        raise RuntimeError("CORE checkpoint cannot be loaded safely") from error
    if not isinstance(checkpoint, dict) or set(checkpoint) != {
        "schema_version", "model_name", "step", "contract", "model", "optimizer"
    }:
        raise RuntimeError("CORE checkpoint envelope is incompatible")
    if (
        checkpoint["schema_version"] != f"{model_name.lower()}-checkpoint.v1"
        or checkpoint["model_name"] != model_name
        or checkpoint["contract"] != contract
        or type(checkpoint["step"]) is not int
        or not 1 <= checkpoint["step"] <= MAXIMUM_TOTAL_STEPS
    ):
        raise RuntimeError("CORE checkpoint contract is incompatible")
    if not isinstance(checkpoint["model"], dict) or not isinstance(checkpoint["optimizer"], dict):
        raise RuntimeError("CORE checkpoint state is incomplete")
    return checkpoint, checkpoint["step"]


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.batch_size <= 8 or not 2 <= args.sequence_length <= 512:
        raise ValueError("CORE run limits are invalid")
    document, config, config_sha256 = load_core_candidate_configuration(args.config)
    if document["name"] != args.model_name:
        raise ValueError("CORE runner model name does not match the configuration")
    bundle = load_authorized_text_bundle(manifest_path=args.manifest, train_jsonl_path=args.train_jsonl, tokenizer_path=args.tokenizer)
    if bundle.tokenizer_status != "candidate_core" or bundle.tokenizer_vocabulary_size != config.vocabulary_size:
        raise ValueError("CORE requires its exact candidate_core tokenizer")
    load_preflight(
        args.preflight_json,
        model_name=args.model_name,
        config_sha256=config_sha256,
        bundle=bundle,
    )
    pretokenized: PretokenizedAuthorizedText | None = None
    if args.pretokenized_dir is not None:
        pretokenized = load_pretokenized_authorized_text(
            args.pretokenized_dir, bundle=bundle
        )
    torch = require_cpu_torch()
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)
    model = build_model(torch, config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    contract = {"config_sha256": config_sha256, "manifest_sha256": bundle.manifest_sha256, "train_split_sha256": bundle.train_sha256, "tokenizer_sha256": bundle.tokenizer_sha256, "preflight_sha256": hashlib.sha256(args.preflight_json.read_bytes()).hexdigest(), "batch_size": args.batch_size, "sequence_length": args.sequence_length, "threads": args.threads, "seed": args.seed}
    start_step = 0
    if args.resume is not None:
        checkpoint, start_step = load_resume(
            torch, args.resume, model_name=args.model_name, contract=contract
        )
        model.load_state_dict(checkpoint["model"], strict=True)
        optimizer.load_state_dict(checkpoint["optimizer"])
    final_step = calculate_final_step(start_step=start_step, steps=args.steps)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "metrics.jsonl"
    if args.resume is None and metrics_path.exists():
        raise ValueError("CORE metrics already exist; use --resume")
    stage_started = time.perf_counter()
    stage_cpu_started = time.process_time()
    with metrics_path.open("a", encoding="utf-8") as metrics:
        for step in range(start_step, start_step + args.steps):
            rows = (
                pretokenized_text_token_rows(
                    pretokenized,
                    step=step,
                    batch_size=args.batch_size,
                    sequence_length=args.sequence_length,
                    seed=args.seed,
                )
                if pretokenized is not None
                else authorized_text_token_rows(
                    bundle,
                    step=step,
                    batch_size=args.batch_size,
                    sequence_length=args.sequence_length,
                    seed=args.seed,
                )
            )
            tokens = torch.tensor(rows, dtype=torch.long)
            logits = model(tokens[:, :-1])
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, config.vocabulary_size), tokens[:, 1:].reshape(-1))
            if not torch.isfinite(loss):
                raise RuntimeError("CORE-700M loss is not finite")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            metrics.write(json.dumps(metric_record(
                model_name=args.model_name,
                step=step + 1,
                loss=float(loss.detach()),
                tokens=args.batch_size * args.sequence_length,
                elapsed_seconds=time.perf_counter() - stage_started,
                cpu_seconds=time.process_time() - stage_cpu_started,
            ), sort_keys=True) + "\n")
            metrics.flush()
    checkpoint = args.output_dir / f"{args.model_name.lower()}-step-{final_step:06d}.pt"
    atomic_save(torch, checkpoint, {"schema_version": f"{args.model_name.lower()}-checkpoint.v1", "model_name": document["name"], "step": final_step, "contract": contract, "model": model.state_dict(), "optimizer": optimizer.state_dict()})
    return {"checkpoint": str(checkpoint), "metrics": str(metrics_path), "steps": final_step}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model-name", default="CORE-700M")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--pretokenized-dir", type=Path)
    parser.add_argument("--preflight-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--sequence-length", type=int, default=64)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=20260907)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args), sort_keys=True))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"CORE training refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
