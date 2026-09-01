#!/usr/bin/env python3
"""Verify and resume one historical CORE-MINI checkpoint entirely offline."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.checkpoint import (
    CompatibilityError,
    MAXIMUM_TOTAL_STEPS,
    load_model_state_strict,
    load_optimizer_state_strict,
    strict_recursive_equal,
    validate_model_gradients_finite,
)
from services.inference.cli import PathFreeArgumentParser
from services.inference.configuration import load_core_mini_configuration
from services.inference.model import build_model, require_cpu_torch
from tools.train_core_mini import (
    DEFAULT_CONFIG,
    save_checkpoint,
    synthetic_token_rows,
    validate_run_limits,
)


MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024
CHECKPOINT_KEYS = {
    "schema_version",
    "model_name",
    "step",
    "config_sha256",
    "training_contract",
    "model",
    "optimizer",
    "run",
}
TRAINING_CONTRACT_KEYS = {
    "schema_version",
    "config_sha256",
    "torch",
    "device",
    "dtype",
    "optimizer",
    "learning_rate",
    "batch_size",
    "sequence_length",
    "seed",
    "threads",
    "synthetic_generator",
}


def _plain_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CompatibilityError(f"{name} is invalid")
    return value


def load_checkpoint_safely(
    torch: Any, checkpoint_path: Path, *, maximum_bytes: int = MAX_CHECKPOINT_BYTES
) -> tuple[dict[str, Any], str, int]:
    """Load one bounded regular file with the safe PyTorch deserializer."""

    if not isinstance(maximum_bytes, int) or isinstance(maximum_bytes, bool) or maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be a positive integer")
    try:
        with checkpoint_path.open("rb") as checkpoint_file:
            metadata_before = os.fstat(checkpoint_file.fileno())
            if not stat.S_ISREG(metadata_before.st_mode):
                raise CompatibilityError("checkpoint must be a regular file")
            if not 1 <= metadata_before.st_size <= maximum_bytes:
                raise CompatibilityError("checkpoint size is outside the allowed range")
            checkpoint_bytes = checkpoint_file.read(metadata_before.st_size + 1)
            metadata_after = os.fstat(checkpoint_file.fileno())
    except CompatibilityError:
        raise
    except OSError:
        raise CompatibilityError("checkpoint is unavailable") from None
    if (
        len(checkpoint_bytes) != metadata_before.st_size
        or metadata_after.st_size != metadata_before.st_size
    ):
        raise CompatibilityError("checkpoint changed while being read")
    checkpoint_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
    try:
        checkpoint = torch.load(
            io.BytesIO(checkpoint_bytes), map_location="cpu", weights_only=True
        )
    except Exception:
        raise CompatibilityError("checkpoint could not be loaded safely") from None
    finally:
        checkpoint_bytes = b""
    if not isinstance(checkpoint, dict):
        raise CompatibilityError("checkpoint must be a mapping")
    return checkpoint, checkpoint_sha256, metadata_before.st_size


def validate_training_contract(
    contract: Any, *, config_sha256: str, torch: Any
) -> dict[str, Any]:
    if not isinstance(contract, dict) or set(contract) != TRAINING_CONTRACT_KEYS:
        raise CompatibilityError("training contract keys are incompatible")
    if contract["schema_version"] != "0.1.0":
        raise CompatibilityError("training contract schema is incompatible")
    if contract["config_sha256"] != config_sha256:
        raise CompatibilityError("training contract configuration does not match")
    if type(contract["torch"]) is not str or contract["torch"] != str(torch.__version__):
        raise CompatibilityError("training contract PyTorch version does not match")
    expected_literals = {
        "device": "cpu",
        "dtype": "float32",
        "optimizer": "AdamW",
        "synthetic_generator": "arithmetic-v1",
    }
    if any(
        not strict_recursive_equal(contract[name], expected)
        for name, expected in expected_literals.items()
    ):
        raise CompatibilityError("training contract execution mode is incompatible")

    batch_size = _plain_int(contract["batch_size"], "training contract batch_size")
    sequence_length = _plain_int(
        contract["sequence_length"], "training contract sequence_length"
    )
    seed = _plain_int(contract["seed"], "training contract seed")
    threads = _plain_int(contract["threads"], "training contract threads")
    validate_run_limits(steps=1, batch_size=batch_size, sequence_length=sequence_length)
    if not 1 <= threads <= 256:
        raise CompatibilityError("training contract threads is invalid")
    learning_rate = contract["learning_rate"]
    if (
        type(learning_rate) is not float
        or not math.isfinite(learning_rate)
        or not 0.0 < learning_rate <= 1.0
    ):
        raise CompatibilityError("training contract learning_rate is invalid")
    if not -(2**63) <= seed < 2**63:
        raise CompatibilityError("training contract seed is invalid")
    return contract


def validate_checkpoint_document(
    checkpoint: dict[str, Any],
    *,
    model_name: str,
    config_sha256: str,
    torch: Any,
    require_resume_room: bool = True,
) -> tuple[int, dict[str, Any]]:
    if set(checkpoint) != CHECKPOINT_KEYS:
        raise CompatibilityError("checkpoint keys are incompatible")
    if checkpoint["schema_version"] != "0.1.0":
        raise CompatibilityError("checkpoint schema is incompatible")
    if checkpoint["model_name"] != model_name:
        raise CompatibilityError("checkpoint model name does not match")
    if checkpoint["config_sha256"] != config_sha256:
        raise CompatibilityError("checkpoint configuration does not match")
    if type(require_resume_room) is not bool:
        raise CompatibilityError("checkpoint step policy is invalid")
    step = _plain_int(checkpoint["step"], "checkpoint step")
    maximum_step = (
        MAXIMUM_TOTAL_STEPS - 1 if require_resume_room else MAXIMUM_TOTAL_STEPS
    )
    if not 1 <= step <= maximum_step:
        raise CompatibilityError("checkpoint step is invalid")
    contract = validate_training_contract(
        checkpoint["training_contract"], config_sha256=config_sha256, torch=torch
    )
    if not isinstance(checkpoint["model"], dict):
        raise CompatibilityError("checkpoint model state is invalid")
    if not isinstance(checkpoint["optimizer"], dict):
        raise CompatibilityError("checkpoint optimizer state is invalid")
    if not isinstance(checkpoint["run"], dict):
        raise CompatibilityError("checkpoint run metadata is invalid")
    return step, contract


def resume_one_synthetic_step(
    torch: Any,
    model: Any,
    optimizer: Any,
    config: Any,
    contract: dict[str, Any],
    *,
    step: int,
) -> float:
    """Execute exactly the next historical arithmetic-v1 training step."""

    rows = synthetic_token_rows(
        step=step,
        batch_size=contract["batch_size"],
        sequence_length=contract["sequence_length"],
        vocabulary_size=config.vocabulary_size,
        seed=contract["seed"],
    )
    tokens = torch.tensor(rows, dtype=torch.long, device="cpu")
    inputs, targets = tokens[:, :-1], tokens[:, 1:]
    optimizer.zero_grad(set_to_none=True)
    logits = model(inputs)
    loss = torch.nn.functional.cross_entropy(
        logits.reshape(-1, config.vocabulary_size), targets.reshape(-1)
    )
    loss.backward()
    validate_model_gradients_finite(torch, model)
    optimizer.step()
    value = float(loss.detach())
    if not math.isfinite(value):
        raise CompatibilityError("resumed loss is not finite")
    return value


def verify_checkpoint(
    checkpoint_path: Path,
    config_path: Path = DEFAULT_CONFIG,
    *,
    torch_module: Any | None = None,
) -> dict[str, Any]:
    document, config, config_sha256 = load_core_mini_configuration(config_path)
    torch = require_cpu_torch() if torch_module is None else torch_module
    # build_model validates the injected module too, before allocating tensors.
    model = build_model(torch, config)
    checkpoint, checkpoint_sha256, checkpoint_size = load_checkpoint_safely(
        torch, checkpoint_path
    )
    step, contract = validate_checkpoint_document(
        checkpoint,
        model_name=document["name"],
        config_sha256=config_sha256,
        torch=torch,
    )

    torch.set_num_threads(contract["threads"])
    torch.manual_seed(contract["seed"])
    torch.use_deterministic_algorithms(True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=contract["learning_rate"])
    model_key_count = load_model_state_strict(torch, model, checkpoint["model"])
    optimizer_parameter_count = load_optimizer_state_strict(
        torch,
        optimizer,
        model,
        checkpoint["optimizer"],
        checkpoint_step=step,
    )
    loss = resume_one_synthetic_step(
        torch, model, optimizer, config, contract, step=step
    )
    resumed_model_state = model.state_dict()
    resumed_optimizer_state = optimizer.state_dict()
    load_model_state_strict(torch, model, resumed_model_state)
    load_optimizer_state_strict(
        torch,
        optimizer,
        model,
        resumed_optimizer_state,
        checkpoint_step=step + 1,
    )

    with tempfile.TemporaryDirectory(prefix="core-checkpoint-compat-") as directory:
        temporary_checkpoint = Path(directory) / "resumed.pt"
        resumed = dict(checkpoint)
        resumed["step"] = step + 1
        resumed["model"] = resumed_model_state
        resumed["optimizer"] = resumed_optimizer_state
        save_checkpoint(torch, temporary_checkpoint, resumed)
        reloaded, _, _ = load_checkpoint_safely(torch, temporary_checkpoint)
        reloaded_step, _ = validate_checkpoint_document(
            reloaded,
            model_name=document["name"],
            config_sha256=config_sha256,
            torch=torch,
            require_resume_room=False,
        )
        if reloaded_step != step + 1:
            raise CompatibilityError("temporary resumed checkpoint is incompatible")
        load_model_state_strict(torch, model, reloaded["model"])
        load_optimizer_state_strict(
            torch,
            optimizer,
            model,
            reloaded["optimizer"],
            checkpoint_step=reloaded_step,
        )

    return {
        "status": "compatible",
        "backend": "cpu_only",
        "network": "disabled",
        "model_name": document["name"],
        "checkpoint_schema_version": checkpoint["schema_version"],
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_bytes": checkpoint_size,
        "step_before": step,
        "step_after": step + 1,
        "resumed_steps": 1,
        "resumed_loss": loss,
        "model_state_keys": model_key_count,
        "optimizer_parameter_states": optimizer_parameter_count,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = PathFreeArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        report = verify_checkpoint(args.checkpoint, args.config)
    except CompatibilityError as error:
        print(f"checkpoint compatibility refused: {error}", file=sys.stderr)
        return 1
    except Exception:
        # Unexpected library errors can contain local paths or implementation
        # details, so the public CLI report deliberately remains generic.
        print("checkpoint compatibility refused: verification failed", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
