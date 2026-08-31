#!/usr/bin/env python3
"""Run the bounded, CPU-only CORE-MINI training and checkpoint harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import time
from typing import Any

from tools.count_core_parameters import CoreConfig, count_parameters


DEFAULT_CONFIG = (
    Path(__file__).parents[1] / "configs" / "models" / "core-mini.candidate.json"
)


def load_and_validate_document(path: Path) -> tuple[dict[str, Any], CoreConfig]:
    with path.open(encoding="utf-8") as config_file:
        document = json.load(config_file)
    if document.get("name") != "CORE-MINI-1M":
        raise ValueError("The training harness accepts CORE-MINI-1M only")
    if document.get("status") != "candidate":
        raise ValueError("Expected a candidate mini-model configuration")
    config = CoreConfig.from_document(document)
    calculated = count_parameters(config)
    if document.get("parameter_count") != calculated:
        raise ValueError("Declared parameter count does not match the architecture")
    return document, config


def validate_run_limits(*, steps: int, batch_size: int, sequence_length: int) -> None:
    if not 1 <= steps <= 10_000:
        raise ValueError("steps must be between 1 and 10000")
    if not 1 <= batch_size <= 64:
        raise ValueError("batch_size must be between 1 and 64")
    if not 2 <= sequence_length <= 512:
        raise ValueError("sequence_length must be between 2 and 512")


def synthetic_token_rows(
    *, step: int, batch_size: int, sequence_length: int, vocabulary_size: int, seed: int
) -> list[list[int]]:
    """Return deterministic next-token sequences without external or personal data."""
    rows: list[list[int]] = []
    for row_index in range(batch_size):
        start = (seed + step * 131 + row_index * 977) % vocabulary_size
        stride = 1 + ((step + row_index) % 17)
        rows.append(
            [
                (start + token_index * stride) % vocabulary_size
                for token_index in range(sequence_length + 1)
            ]
        )
    return rows


def require_cpu_torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is absent; install only from the verified offline CPU bundle"
        ) from exc
    if torch.version.cuda is not None or getattr(torch.version, "hip", None) is not None:
        raise RuntimeError("CUDA/ROCm builds are forbidden for this CPU-only harness")
    return torch


def build_model(torch: Any, config: CoreConfig) -> Any:
    nn = torch.nn
    functional = torch.nn.functional
    head_dim = config.head_dimension

    class RMSNorm(nn.Module):
        def __init__(self, dimension: int) -> None:
            super().__init__()
            self.weight = nn.Parameter(torch.ones(dimension, device="cpu"))

        def forward(self, values: Any) -> Any:
            scale = values.pow(2).mean(dim=-1, keepdim=True).add(1e-6).rsqrt()
            return values * scale * self.weight

    def apply_rope(values: Any) -> Any:
        sequence_length = values.shape[-2]
        positions = torch.arange(sequence_length, device="cpu", dtype=torch.float32)
        inv_frequency = 1.0 / (
            10000
            ** (
                torch.arange(0, head_dim, 2, device="cpu", dtype=torch.float32)
                / head_dim
            )
        )
        angles = torch.outer(positions, inv_frequency)
        cosine = angles.cos().to(dtype=values.dtype)[None, None, :, :]
        sine = angles.sin().to(dtype=values.dtype)[None, None, :, :]
        even = values[..., 0::2]
        odd = values[..., 1::2]
        return torch.stack(
            (even * cosine - odd * sine, even * sine + odd * cosine), dim=-1
        ).flatten(-2)

    class CausalSelfAttention(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            dimension = config.hidden_size
            self.q = nn.Linear(dimension, dimension, bias=False, device="cpu")
            self.k = nn.Linear(dimension, dimension, bias=False, device="cpu")
            self.v = nn.Linear(dimension, dimension, bias=False, device="cpu")
            self.output = nn.Linear(dimension, dimension, bias=False, device="cpu")

        def forward(self, values: Any) -> Any:
            batch, sequence, dimension = values.shape

            def split_heads(projected: Any) -> Any:
                return projected.view(
                    batch, sequence, config.num_attention_heads, head_dim
                ).transpose(1, 2)

            query = apply_rope(split_heads(self.q(values)))
            key = apply_rope(split_heads(self.k(values)))
            value = split_heads(self.v(values))
            attended = functional.scaled_dot_product_attention(
                query, key, value, is_causal=True
            )
            merged = attended.transpose(1, 2).contiguous().view(
                batch, sequence, dimension
            )
            return self.output(merged)

    class SwiGLU(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            dimension = config.hidden_size
            intermediate = config.intermediate_size
            self.gate = nn.Linear(dimension, intermediate, bias=False, device="cpu")
            self.up = nn.Linear(dimension, intermediate, bias=False, device="cpu")
            self.down = nn.Linear(intermediate, dimension, bias=False, device="cpu")

        def forward(self, values: Any) -> Any:
            return self.down(functional.silu(self.gate(values)) * self.up(values))

    class DecoderBlock(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.attention_norm = RMSNorm(config.hidden_size)
            self.attention = CausalSelfAttention()
            self.mlp_norm = RMSNorm(config.hidden_size)
            self.mlp = SwiGLU()

        def forward(self, values: Any) -> Any:
            values = values + self.attention(self.attention_norm(values))
            return values + self.mlp(self.mlp_norm(values))

    class CoreMini(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.token_embeddings = nn.Embedding(
                config.vocabulary_size, config.hidden_size, device="cpu"
            )
            self.blocks = nn.ModuleList(
                DecoderBlock() for _ in range(config.num_hidden_layers)
            )
            self.final_norm = RMSNorm(config.hidden_size)

        def forward(self, token_ids: Any) -> Any:
            if token_ids.device.type != "cpu":
                raise RuntimeError("CORE-MINI accepts CPU tensors only")
            hidden = self.token_embeddings(token_ids)
            for block in self.blocks:
                hidden = block(hidden)
            hidden = self.final_norm(hidden)
            return functional.linear(hidden, self.token_embeddings.weight)

    model = CoreMini()
    expected = count_parameters(config)["total_trainable"]
    observed = sum(parameter.numel() for parameter in model.parameters())
    if observed != expected:
        raise RuntimeError(f"Parameter mismatch: expected {expected}, observed {observed}")
    if any(parameter.device.type != "cpu" for parameter in model.parameters()):
        raise RuntimeError("A model parameter was created outside the CPU")
    return model


def _config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def training_contract(args: argparse.Namespace, config_hash: str, torch: Any) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "config_sha256": config_hash,
        "torch": torch.__version__,
        "device": "cpu",
        "dtype": "float32",
        "optimizer": "AdamW",
        "learning_rate": args.learning_rate,
        "batch_size": args.batch_size,
        "sequence_length": args.sequence_length,
        "seed": args.seed,
        "threads": args.threads,
        "synthetic_generator": "arithmetic-v1",
    }


def save_checkpoint(torch: Any, checkpoint_path: Path, payload: dict[str, Any]) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, checkpoint_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sequence-length", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--resume", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validate_run_limits(
        steps=args.steps,
        batch_size=args.batch_size,
        sequence_length=args.sequence_length,
    )
    if not 1 <= args.threads <= 256:
        raise ValueError("threads must be between 1 and 256")
    if not 0.0 < args.learning_rate <= 1.0:
        raise ValueError("learning_rate must be between 0 and 1")
    document, config = load_and_validate_document(args.config)
    torch = require_cpu_torch()
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)

    model = build_model(torch, config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    start_step = 0
    config_hash = _config_sha256(args.config)
    contract = training_contract(args, config_hash, torch)
    if args.resume is not None:
        checkpoint = torch.load(args.resume, map_location="cpu", weights_only=True)
        if not isinstance(checkpoint, dict):
            raise RuntimeError("Checkpoint must be a mapping")
        if checkpoint.get("schema_version") != "0.1.0":
            raise RuntimeError("Unsupported checkpoint schema_version")
        if checkpoint.get("model_name") != document["name"]:
            raise RuntimeError("Checkpoint model name does not match")
        if checkpoint.get("training_contract") != contract:
            raise RuntimeError("Checkpoint training contract does not match")
        if not isinstance(checkpoint.get("step"), int) or checkpoint["step"] < 0:
            raise RuntimeError("Checkpoint step is invalid")
        if not isinstance(checkpoint.get("model"), dict) or not isinstance(
            checkpoint.get("optimizer"), dict
        ):
            raise RuntimeError("Checkpoint state is incomplete")
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        start_step = int(checkpoint["step"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "metrics.jsonl"
    started = time.perf_counter()
    with metrics_path.open("a", encoding="utf-8") as metrics_file:
        for step in range(start_step, start_step + args.steps):
            rows = synthetic_token_rows(
                step=step,
                batch_size=args.batch_size,
                sequence_length=args.sequence_length,
                vocabulary_size=config.vocabulary_size,
                seed=args.seed,
            )
            tokens = torch.tensor(rows, dtype=torch.long, device="cpu")
            inputs, targets = tokens[:, :-1], tokens[:, 1:]
            optimizer.zero_grad(set_to_none=True)
            logits = model(inputs)
            loss = torch.nn.functional.cross_entropy(
                logits.reshape(-1, config.vocabulary_size), targets.reshape(-1)
            )
            loss.backward()
            optimizer.step()
            record = {
                "step": step + 1,
                "loss": float(loss.detach()),
                "elapsed_seconds": time.perf_counter() - started,
                "tokens": args.batch_size * args.sequence_length,
            }
            metrics_file.write(json.dumps(record, sort_keys=True) + "\n")
            metrics_file.flush()

    final_step = start_step + args.steps
    checkpoint_path = args.output_dir / f"core-mini-step-{final_step:06d}.pt"
    save_checkpoint(
        torch,
        checkpoint_path,
        {
            "schema_version": "0.1.0",
            "model_name": document["name"],
            "step": final_step,
            "config_sha256": config_hash,
            "training_contract": contract,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "run": {
                "device": "cpu",
                "torch": torch.__version__,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "threads": args.threads,
                "batch_size": args.batch_size,
                "sequence_length": args.sequence_length,
                "seed": args.seed,
                "learning_rate": args.learning_rate,
            },
        },
    )
    print(json.dumps({"checkpoint": str(checkpoint_path), "step": final_step}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
