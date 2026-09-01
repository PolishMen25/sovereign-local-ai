#!/usr/bin/env python3
"""Verify and resume one historical CORE-MINI checkpoint entirely offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, BinaryIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.model import build_model, require_cpu_torch
from tools.train_core_mini import (
    DEFAULT_CONFIG,
    load_and_validate_document,
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


class CompatibilityError(RuntimeError):
    """A safe, path-free compatibility refusal suitable for public output."""


def _plain_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CompatibilityError(f"{name} is invalid")
    return value


def _config_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise CompatibilityError("model configuration is unavailable") from error


def _hash_open_file(checkpoint_file: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := checkpoint_file.read(1024 * 1024):
        digest.update(chunk)
    checkpoint_file.seek(0)
    return digest.hexdigest()


def load_checkpoint_safely(
    torch: Any, checkpoint_path: Path, *, maximum_bytes: int = MAX_CHECKPOINT_BYTES
) -> tuple[dict[str, Any], str, int]:
    """Load one bounded regular file with the safe PyTorch deserializer."""

    if not isinstance(maximum_bytes, int) or isinstance(maximum_bytes, bool) or maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be a positive integer")
    try:
        with checkpoint_path.open("rb") as checkpoint_file:
            metadata = os.fstat(checkpoint_file.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise CompatibilityError("checkpoint must be a regular file")
            if not 1 <= metadata.st_size <= maximum_bytes:
                raise CompatibilityError("checkpoint size is outside the allowed range")
            checkpoint_sha256 = _hash_open_file(checkpoint_file)
            try:
                checkpoint = torch.load(
                    checkpoint_file, map_location="cpu", weights_only=True
                )
            except Exception as error:
                raise CompatibilityError("checkpoint could not be loaded safely") from error
    except CompatibilityError:
        raise
    except OSError as error:
        raise CompatibilityError("checkpoint is unavailable") from error
    if not isinstance(checkpoint, dict):
        raise CompatibilityError("checkpoint must be a mapping")
    return checkpoint, checkpoint_sha256, metadata.st_size


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
    if any(contract[name] != expected for name, expected in expected_literals.items()):
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
    if isinstance(learning_rate, bool) or not isinstance(learning_rate, (int, float)):
        raise CompatibilityError("training contract learning_rate is invalid")
    if not math.isfinite(float(learning_rate)) or not 0.0 < float(learning_rate) <= 1.0:
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
) -> tuple[int, dict[str, Any]]:
    if set(checkpoint) != CHECKPOINT_KEYS:
        raise CompatibilityError("checkpoint keys are incompatible")
    if checkpoint["schema_version"] != "0.1.0":
        raise CompatibilityError("checkpoint schema is incompatible")
    if checkpoint["model_name"] != model_name:
        raise CompatibilityError("checkpoint model name does not match")
    if checkpoint["config_sha256"] != config_sha256:
        raise CompatibilityError("checkpoint configuration does not match")
    step = _plain_int(checkpoint["step"], "checkpoint step")
    if step < 1:
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


def _validate_tensor_metadata(
    torch: Any, received: Any, expected: Any, *, label: str
) -> None:
    if not torch.is_tensor(received):
        raise CompatibilityError(f"{label} is not a tensor")
    if received.shape != expected.shape:
        raise CompatibilityError(f"{label} shape is incompatible")
    if received.dtype != expected.dtype:
        raise CompatibilityError(f"{label} dtype is incompatible")
    if received.device.type != "cpu" or expected.device.type != "cpu":
        raise CompatibilityError(f"{label} is outside the CPU")
    if getattr(received, "layout", None) != getattr(expected, "layout", None):
        raise CompatibilityError(f"{label} layout is incompatible")


def _validate_optimizer_step_tensor(
    torch: Any, step_tensor: Any, *, checkpoint_step: int
) -> None:
    if not torch.is_tensor(step_tensor) or step_tensor.numel() != 1:
        raise CompatibilityError("checkpoint optimizer step state is incompatible")
    if step_tensor.device.type != "cpu" or step_tensor.dtype != torch.float32:
        raise CompatibilityError("checkpoint optimizer step metadata is incompatible")
    try:
        step_value = step_tensor.item()
    except Exception as error:
        raise CompatibilityError("checkpoint optimizer step state is incompatible") from error
    if (
        isinstance(step_value, bool)
        or not isinstance(step_value, (int, float))
        or not math.isfinite(float(step_value))
        or float(step_value) != float(checkpoint_step)
    ):
        raise CompatibilityError("checkpoint optimizer step does not match checkpoint")


def load_model_state_strict(torch: Any, model: Any, state: dict[str, Any]) -> int:
    expected_state = model.state_dict()
    expected_keys = tuple(expected_state.keys())
    received_keys = tuple(state.keys())
    if len(received_keys) != len(set(received_keys)) or set(received_keys) != set(expected_keys):
        raise CompatibilityError("checkpoint model keys do not match")
    for name, expected_tensor in expected_state.items():
        if not torch.is_tensor(expected_tensor):
            raise CompatibilityError("runtime model state is not tensor-only")
        _validate_tensor_metadata(
            torch,
            state[name],
            expected_tensor,
            label=f"checkpoint model tensor {name}",
        )
    try:
        incompatible = model.load_state_dict(state, strict=True)
    except Exception as error:
        raise CompatibilityError("checkpoint model tensors are incompatible") from error
    if incompatible.missing_keys or incompatible.unexpected_keys:
        raise CompatibilityError("checkpoint model keys do not match")
    return len(expected_keys)


def load_optimizer_state_strict(
    torch: Any,
    optimizer: Any,
    model: Any,
    state: dict[str, Any],
    *,
    checkpoint_step: int,
) -> int:
    if set(state) != {"state", "param_groups"}:
        raise CompatibilityError("checkpoint optimizer keys do not match")
    if not isinstance(state["state"], dict) or not isinstance(state["param_groups"], list):
        raise CompatibilityError("checkpoint optimizer structure is invalid")

    expected = optimizer.state_dict()
    if len(state["param_groups"]) != len(expected["param_groups"]):
        raise CompatibilityError("checkpoint optimizer parameter groups do not match")
    checkpoint_parameter_ids: list[int] = []
    for received_group, expected_group in zip(
        state["param_groups"], expected["param_groups"]
    ):
        if not isinstance(received_group, dict) or set(received_group) != set(expected_group):
            raise CompatibilityError("checkpoint optimizer group keys do not match")
        if received_group["params"] != expected_group["params"]:
            raise CompatibilityError("checkpoint optimizer parameter order does not match")
        for name, expected_value in expected_group.items():
            if name != "params" and received_group[name] != expected_value:
                raise CompatibilityError("checkpoint optimizer settings do not match")
        checkpoint_parameter_ids.extend(received_group["params"])

    if len(checkpoint_parameter_ids) != len(set(checkpoint_parameter_ids)):
        raise CompatibilityError("checkpoint optimizer parameter identifiers are invalid")
    if set(state["state"]) != set(checkpoint_parameter_ids):
        raise CompatibilityError("checkpoint optimizer parameter states are incomplete")

    parameters = list(model.parameters())
    if len(parameters) != len(checkpoint_parameter_ids):
        raise CompatibilityError("checkpoint optimizer parameter states are incomplete")
    for parameter_id, parameter in zip(checkpoint_parameter_ids, parameters):
        parameter_state = state["state"][parameter_id]
        expected_state_keys = {"step", "exp_avg", "exp_avg_sq"}
        if not isinstance(parameter_state, dict) or set(parameter_state) != expected_state_keys:
            raise CompatibilityError("checkpoint optimizer state keys are incompatible")
        _validate_optimizer_step_tensor(
            torch, parameter_state["step"], checkpoint_step=checkpoint_step
        )
        for name in ("exp_avg", "exp_avg_sq"):
            _validate_tensor_metadata(
                torch,
                parameter_state[name],
                parameter,
                label=f"checkpoint optimizer tensor {name}",
            )
    try:
        optimizer.load_state_dict(state)
    except Exception as error:
        raise CompatibilityError("checkpoint optimizer tensors are incompatible") from error

    if len(parameters) != len(checkpoint_parameter_ids) or set(optimizer.state) != set(parameters):
        raise CompatibilityError("loaded optimizer parameter states are incomplete")
    for parameter in parameters:
        parameter_state = optimizer.state[parameter]
        expected_state_keys = {"step", "exp_avg", "exp_avg_sq"}
        if parameter_state.keys() != expected_state_keys:
            raise CompatibilityError("loaded optimizer state keys are incompatible")
        _validate_optimizer_step_tensor(
            torch, parameter_state["step"], checkpoint_step=checkpoint_step
        )
        for name in ("exp_avg", "exp_avg_sq"):
            _validate_tensor_metadata(
                torch,
                parameter_state[name],
                parameter,
                label=f"loaded optimizer tensor {name}",
            )
    return len(parameters)


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
    document, config = load_and_validate_document(config_path)
    config_sha256 = _config_sha256(config_path)
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

    with tempfile.TemporaryDirectory(prefix="core-checkpoint-compat-") as directory:
        temporary_checkpoint = Path(directory) / "resumed.pt"
        resumed = dict(checkpoint)
        resumed["step"] = step + 1
        resumed["model"] = model.state_dict()
        resumed["optimizer"] = optimizer.state_dict()
        save_checkpoint(torch, temporary_checkpoint, resumed)
        reloaded, _, _ = load_checkpoint_safely(torch, temporary_checkpoint)
        if reloaded.get("step") != step + 1:
            raise CompatibilityError("temporary resumed checkpoint is incompatible")

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
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
