"""Strict, CPU-only CORE checkpoint state loading primitives.

The functions in this module validate the complete model and AdamW state both
before and after PyTorch mutates the runtime objects.  They deliberately expose
no filesystem or network capability; bounded, safe deserialization remains the
caller's responsibility.
"""

from __future__ import annotations

import math
from typing import Any


MAXIMUM_TOTAL_STEPS = 10_000


class CompatibilityError(RuntimeError):
    """A path-free checkpoint compatibility refusal safe for public output."""


def _plain_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CompatibilityError(f"{label} is invalid")
    return value


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
    try:
        finite = torch.isfinite(received).all().item()
    except Exception as error:
        raise CompatibilityError(f"{label} finiteness is unverifiable") from error
    if type(finite) is not bool or not finite:
        raise CompatibilityError(f"{label} contains non-finite values")


def _validate_optimizer_step_tensor(
    torch: Any, step_tensor: Any, *, checkpoint_step: int
) -> None:
    checkpoint_step = _plain_positive_int(checkpoint_step, "checkpoint step")
    expected_layout = getattr(torch, "strided", "strided")
    if not torch.is_tensor(step_tensor) or step_tensor.numel() != 1:
        raise CompatibilityError("checkpoint optimizer step state is incompatible")
    if tuple(step_tensor.shape) != ():
        raise CompatibilityError("checkpoint optimizer step shape is incompatible")
    if step_tensor.device.type != "cpu" or step_tensor.dtype != torch.float32:
        raise CompatibilityError("checkpoint optimizer step metadata is incompatible")
    if getattr(step_tensor, "layout", None) != expected_layout:
        raise CompatibilityError("checkpoint optimizer step layout is incompatible")
    try:
        step_value = step_tensor.item()
    except Exception as error:
        raise CompatibilityError(
            "checkpoint optimizer step state is incompatible"
        ) from error
    if (
        isinstance(step_value, bool)
        or not isinstance(step_value, (int, float))
        or not math.isfinite(float(step_value))
        or float(step_value) != float(checkpoint_step)
    ):
        raise CompatibilityError("checkpoint optimizer step does not match checkpoint")


def strict_recursive_equal(received: Any, expected: Any) -> bool:
    """Compare nested contracts without Python's bool/int coercion."""

    if type(received) is not type(expected):
        return False
    if isinstance(expected, dict):
        if len(received) != len(expected):
            return False
        unmatched_received_keys = list(received)
        for expected_key, expected_value in expected.items():
            matching_keys = [
                received_key
                for received_key in unmatched_received_keys
                if strict_recursive_equal(received_key, expected_key)
            ]
            if len(matching_keys) != 1:
                return False
            received_key = matching_keys[0]
            unmatched_received_keys.remove(received_key)
            if not strict_recursive_equal(received[received_key], expected_value):
                return False
        return not unmatched_received_keys
    if isinstance(expected, (list, tuple)):
        return len(received) == len(expected) and all(
            strict_recursive_equal(left, right)
            for left, right in zip(received, expected)
        )
    try:
        return bool(received == expected)
    except Exception:
        return False


def _tensor_storage_identity(tensor: Any, *, label: str) -> tuple[str, int, int]:
    try:
        if tensor.storage_offset() != 0:
            raise CompatibilityError(f"{label} storage offset is incompatible")
        storage = tensor.untyped_storage()
        storage_bytes = storage.nbytes()
        element_count = tensor.numel()
        element_size = tensor.element_size()
        pointer = storage.data_ptr()
        device_type = tensor.device.type
    except CompatibilityError:
        raise
    except Exception as error:
        raise CompatibilityError(f"{label} storage is unverifiable") from error
    if (
        isinstance(element_count, bool)
        or not isinstance(element_count, int)
        or element_count < 1
        or isinstance(element_size, bool)
        or not isinstance(element_size, int)
        or element_size < 1
    ):
        raise CompatibilityError(f"{label} storage size is incompatible")
    exact_bytes = element_count * element_size
    if (
        isinstance(storage_bytes, bool)
        or not isinstance(storage_bytes, int)
        or storage_bytes != exact_bytes
        or isinstance(pointer, bool)
        or not isinstance(pointer, int)
        or pointer <= 0
    ):
        raise CompatibilityError(f"{label} storage size is incompatible")
    return device_type, pointer, storage_bytes


def _validate_optimizer_tensor_storage(
    received: Any, expected_parameter: Any, *, label: str
) -> tuple[str, int, int]:
    try:
        received_stride = tuple(received.stride())
        expected_stride = tuple(expected_parameter.stride())
    except Exception as error:
        raise CompatibilityError(f"{label} stride is unverifiable") from error
    if received_stride != expected_stride:
        raise CompatibilityError(f"{label} stride is incompatible")
    return _tensor_storage_identity(received, label=label)


def _plain_parameter_ids(value: Any) -> list[int]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in value
    ):
        raise CompatibilityError(
            "checkpoint optimizer parameter identifiers are invalid"
        )
    return value


def load_model_state_strict(torch: Any, model: Any, state: dict[str, Any]) -> int:
    """Validate and load an exact CPU model state, then validate it again."""

    if not isinstance(state, dict):
        raise CompatibilityError("checkpoint model state is invalid")
    expected_state = model.state_dict()
    if not isinstance(expected_state, dict):
        raise CompatibilityError("runtime model state is invalid")
    expected_keys = tuple(expected_state.keys())
    received_keys = tuple(state.keys())
    if set(received_keys) != set(expected_keys):
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

    loaded_state = model.state_dict()
    if not isinstance(loaded_state, dict) or set(loaded_state) != set(expected_keys):
        raise CompatibilityError("loaded model keys do not match")
    for name, received_tensor in state.items():
        _validate_tensor_metadata(
            torch,
            loaded_state[name],
            received_tensor,
            label=f"loaded model tensor {name}",
        )
    return len(expected_keys)


def validate_model_gradients_finite(torch: Any, model: Any) -> int:
    """Require one finite, complete CPU gradient for every model parameter."""

    parameters = list(model.parameters())
    if not parameters:
        raise CompatibilityError("runtime model has no trainable parameters")
    for parameter in parameters:
        gradient = getattr(parameter, "grad", None)
        if gradient is None:
            raise CompatibilityError("runtime model gradients are incomplete")
        _validate_tensor_metadata(
            torch,
            gradient,
            parameter,
            label="runtime model gradient",
        )
    return len(parameters)


def _validate_optimizer_groups(
    received_groups: Any, expected_groups: Any
) -> list[int]:
    if not isinstance(received_groups, list) or not isinstance(expected_groups, list):
        raise CompatibilityError("checkpoint optimizer parameter groups are invalid")
    if len(received_groups) != len(expected_groups):
        raise CompatibilityError("checkpoint optimizer parameter groups do not match")

    parameter_ids: list[int] = []
    for received_group, expected_group in zip(received_groups, expected_groups):
        if not isinstance(received_group, dict) or not isinstance(expected_group, dict):
            raise CompatibilityError("checkpoint optimizer parameter group is invalid")
        if set(received_group) != set(expected_group) or "params" not in received_group:
            raise CompatibilityError("checkpoint optimizer group keys do not match")
        received_ids = _plain_parameter_ids(received_group["params"])
        expected_ids = _plain_parameter_ids(expected_group["params"])
        if received_ids != expected_ids:
            raise CompatibilityError(
                "checkpoint optimizer parameter order does not match"
            )
        for name, expected_value in expected_group.items():
            if name != "params" and not strict_recursive_equal(
                received_group[name], expected_value
            ):
                raise CompatibilityError("checkpoint optimizer settings do not match")
        parameter_ids.extend(received_ids)

    if len(parameter_ids) != len(set(parameter_ids)):
        raise CompatibilityError(
            "checkpoint optimizer parameter identifiers are invalid"
        )
    return parameter_ids


def _runtime_parameters_in_optimizer_order(
    optimizer: Any, model: Any, expected_groups: list[dict[str, Any]]
) -> list[Any]:
    model_parameters = list(model.parameters())
    runtime_groups = getattr(optimizer, "param_groups", None)
    if runtime_groups is None:
        runtime_parameters = model_parameters
    else:
        if not isinstance(runtime_groups, list) or len(runtime_groups) != len(
            expected_groups
        ):
            raise CompatibilityError(
                "runtime optimizer parameter groups do not match"
            )
        runtime_parameters = []
        for runtime_group, expected_group in zip(runtime_groups, expected_groups):
            if not isinstance(runtime_group, dict) or not isinstance(
                runtime_group.get("params"), list
            ):
                raise CompatibilityError("runtime optimizer parameter group is invalid")
            if len(runtime_group["params"]) != len(expected_group["params"]):
                raise CompatibilityError(
                    "runtime optimizer parameter order does not match"
                )
            runtime_parameters.extend(runtime_group["params"])
    if (
        len(runtime_parameters) != len(model_parameters)
        or len({id(parameter) for parameter in runtime_parameters})
        != len(runtime_parameters)
        or {id(parameter) for parameter in runtime_parameters}
        != {id(parameter) for parameter in model_parameters}
    ):
        raise CompatibilityError("checkpoint optimizer parameter states are incomplete")
    return runtime_parameters


def _validate_parameter_state(
    torch: Any,
    parameter_state: Any,
    parameter: Any,
    *,
    checkpoint_step: int,
    label_prefix: str,
) -> tuple[Any, Any, Any]:
    expected_state_keys = {"step", "exp_avg", "exp_avg_sq"}
    if not isinstance(parameter_state, dict) or set(parameter_state) != expected_state_keys:
        raise CompatibilityError(f"{label_prefix} state keys are incompatible")
    _validate_optimizer_step_tensor(
        torch, parameter_state["step"], checkpoint_step=checkpoint_step
    )
    try:
        step_stride = tuple(parameter_state["step"].stride())
    except Exception as error:
        raise CompatibilityError(
            f"{label_prefix} tensor step stride is unverifiable"
        ) from error
    if step_stride != ():
        raise CompatibilityError(f"{label_prefix} tensor step stride is incompatible")
    _tensor_storage_identity(
        parameter_state["step"], label=f"{label_prefix} tensor step"
    )
    for name in ("exp_avg", "exp_avg_sq"):
        _validate_tensor_metadata(
            torch,
            parameter_state[name],
            parameter,
            label=f"{label_prefix} tensor {name}",
        )
        _validate_optimizer_tensor_storage(
            parameter_state[name],
            parameter,
            label=f"{label_prefix} tensor {name}",
        )
    return (
        parameter_state["step"],
        parameter_state["exp_avg"],
        parameter_state["exp_avg_sq"],
    )


def _validate_optimizer_tensor_independence(
    tensors: list[Any], parameters: list[Any], *, label: str
) -> None:
    tensor_ids = [id(tensor) for tensor in tensors]
    if len(tensor_ids) != len(set(tensor_ids)):
        raise CompatibilityError(f"{label} tensor identities are not distinct")
    tensor_storages = [
        _tensor_storage_identity(tensor, label=f"{label} tensor")
        for tensor in tensors
    ]
    if len(tensor_storages) != len(set(tensor_storages)):
        raise CompatibilityError(f"{label} tensor storages are aliased")
    parameter_ids = {id(parameter) for parameter in parameters}
    if parameter_ids.intersection(tensor_ids):
        raise CompatibilityError(f"{label} tensors alias model parameters")
    parameter_storages = {
        _tensor_storage_identity(parameter, label="runtime model parameter")
        for parameter in parameters
    }
    if parameter_storages.intersection(tensor_storages):
        raise CompatibilityError(f"{label} tensors alias model parameter storage")


def load_optimizer_state_strict(
    torch: Any,
    optimizer: Any,
    model: Any,
    state: dict[str, Any],
    *,
    checkpoint_step: int,
) -> int:
    """Validate and load a complete AdamW CPU state, then validate it again."""

    checkpoint_step = _plain_positive_int(checkpoint_step, "checkpoint step")
    if not isinstance(state, dict) or set(state) != {"state", "param_groups"}:
        raise CompatibilityError("checkpoint optimizer keys do not match")
    if not isinstance(state["state"], dict):
        raise CompatibilityError("checkpoint optimizer structure is invalid")

    expected = optimizer.state_dict()
    if not isinstance(expected, dict) or set(expected) != {"state", "param_groups"}:
        raise CompatibilityError("runtime optimizer structure is invalid")
    parameter_ids = _validate_optimizer_groups(
        state["param_groups"], expected["param_groups"]
    )
    if any(
        isinstance(parameter_id, bool) or not isinstance(parameter_id, int)
        for parameter_id in state["state"]
    ):
        raise CompatibilityError(
            "checkpoint optimizer parameter identifiers are invalid"
        )
    if set(state["state"]) != set(parameter_ids):
        raise CompatibilityError("checkpoint optimizer parameter states are incomplete")

    parameters = _runtime_parameters_in_optimizer_order(
        optimizer, model, expected["param_groups"]
    )
    if len(parameters) != len(parameter_ids):
        raise CompatibilityError("checkpoint optimizer parameter states are incomplete")
    checkpoint_tensors: list[Any] = []
    for parameter_id, parameter in zip(parameter_ids, parameters):
        checkpoint_tensors.extend(
            _validate_parameter_state(
                torch,
                state["state"][parameter_id],
                parameter,
                checkpoint_step=checkpoint_step,
                label_prefix="checkpoint optimizer",
            )
        )
    _validate_optimizer_tensor_independence(
        checkpoint_tensors, parameters, label="checkpoint optimizer"
    )

    try:
        optimizer.load_state_dict(state)
    except Exception as error:
        raise CompatibilityError("checkpoint optimizer tensors are incompatible") from error

    if set(getattr(optimizer, "state", {})) != set(parameters):
        raise CompatibilityError("loaded optimizer parameter states are incomplete")
    loaded_tensors: list[Any] = []
    for parameter in parameters:
        loaded_tensors.extend(
            _validate_parameter_state(
                torch,
                optimizer.state[parameter],
                parameter,
                checkpoint_step=checkpoint_step,
                label_prefix="loaded optimizer",
            )
        )
    _validate_optimizer_tensor_independence(
        loaded_tensors, parameters, label="loaded optimizer"
    )

    # Real PyTorch optimizers expose ``param_groups``.  Re-serialize them after
    # loading so option coercion or group mutation cannot pass unnoticed.
    if hasattr(optimizer, "param_groups"):
        loaded = optimizer.state_dict()
        if not isinstance(loaded, dict) or set(loaded) != {"state", "param_groups"}:
            raise CompatibilityError("loaded optimizer structure is invalid")
        loaded_ids = _validate_optimizer_groups(
            loaded["param_groups"], state["param_groups"]
        )
        if loaded_ids != parameter_ids or set(loaded["state"]) != set(parameter_ids):
            raise CompatibilityError("loaded optimizer parameter states are incomplete")
        serialized_loaded_tensors: list[Any] = []
        for parameter_id, parameter in zip(parameter_ids, parameters):
            serialized_loaded_tensors.extend(
                _validate_parameter_state(
                    torch,
                    loaded["state"][parameter_id],
                    parameter,
                    checkpoint_step=checkpoint_step,
                    label_prefix="loaded optimizer",
                )
            )
        _validate_optimizer_tensor_independence(
            serialized_loaded_tensors, parameters, label="loaded optimizer"
        )
    return len(parameters)
