#!/usr/bin/env python3
"""Run the bounded, CPU-only CORE-MINI training and checkpoint harness."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import stat
import sys
import tempfile
import time
from typing import Any, BinaryIO, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.checkpoint import (
    MAXIMUM_TOTAL_STEPS,
    load_model_state_strict,
    load_optimizer_state_strict,
    strict_recursive_equal,
    validate_model_gradients_finite,
)
from services.inference.cli import PathFreeArgumentParser
from services.inference.configuration import load_core_mini_configuration
from services.inference.model import build_model, require_cpu_torch
from tools.authorized_text_bundle import (
    AuthorizedTextBundle,
    load_authorized_text_bundle,
)
from tools.count_core_parameters import CoreConfig


DEFAULT_CONFIG = (
    Path(__file__).parents[1] / "configs" / "models" / "core-mini.candidate.json"
)
DATA_MODE_SYNTHETIC = "synthetic"
DATA_MODE_AUTHORIZED_TEXT = "authorized-text"
MAXIMUM_RESUME_CHECKPOINT_BYTES = 256 * 1024 * 1024
MAXIMUM_METRICS_BYTES = 64 * 1024 * 1024
MAXIMUM_METRIC_LINE_BYTES = 1024 * 1024
CHECKPOINT_SCHEMA_VERSION = "0.1.0"
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
AUTHORIZED_METRIC_KEYS = {
    "step",
    "loss",
    "elapsed_seconds",
    "tokens",
    "data_mode",
    "data_lineage",
    "training_contract_sha256",
}


def load_and_validate_document(path: Path) -> tuple[dict[str, Any], CoreConfig]:
    """Backward-compatible two-value view of the common strict loader."""

    document, config, _ = load_core_mini_configuration(path)
    return document, config


def validate_run_limits(*, steps: int, batch_size: int, sequence_length: int) -> None:
    if type(steps) is not int:
        raise ValueError("steps must be an integer")
    if type(batch_size) is not int:
        raise ValueError("batch_size must be an integer")
    if type(sequence_length) is not int:
        raise ValueError("sequence_length must be an integer")
    if not 1 <= steps <= MAXIMUM_TOTAL_STEPS:
        raise ValueError("steps must be between 1 and 10000")
    if not 1 <= batch_size <= 64:
        raise ValueError("batch_size must be between 1 and 64")
    if not 2 <= sequence_length <= 512:
        raise ValueError("sequence_length must be between 2 and 512")


def calculate_final_step(*, start_step: int, steps: int) -> int:
    """Return a total step count bounded across fresh and resumed runs."""

    if type(start_step) is not int or not 0 <= start_step <= MAXIMUM_TOTAL_STEPS:
        raise RuntimeError("Checkpoint step is invalid")
    if type(steps) is not int or not 1 <= steps <= MAXIMUM_TOTAL_STEPS:
        raise ValueError("steps must be between 1 and 10000")
    if start_step > MAXIMUM_TOTAL_STEPS - steps:
        raise RuntimeError("Final checkpoint step exceeds the bounded range")
    return start_step + steps


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


def authorized_text_token_rows(
    bundle: AuthorizedTextBundle,
    *,
    step: int,
    batch_size: int,
    sequence_length: int,
    seed: int,
) -> list[list[int]]:
    """Return deterministic next-token rows from the authorized train split.

    A row starts in one deterministic record.  Long records provide a bounded
    contiguous window; short records are joined only through explicit EOS/BOS
    boundaries.  Validation and test materializations are unavailable here
    because ``AuthorizedTextBundle`` contains the validated train split only.
    """

    if not isinstance(bundle, AuthorizedTextBundle):
        raise ValueError("authorized-text requires a validated training bundle")
    validate_run_limits(
        steps=1, batch_size=batch_size, sequence_length=sequence_length
    )
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise ValueError("step must be a non-negative integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not bundle.records:
        raise ValueError("authorized-text train split must not be empty")

    required = sequence_length + 1
    rows: list[list[int]] = []
    for row_index in range(batch_size):
        record_index = (seed + step * 131 + row_index * 977) % len(bundle.records)
        token_ids = bundle.tokenizer.encode(
            bundle.records[record_index].text, bos=True, eos=True
        )
        if len(token_ids) >= required:
            maximum_start = len(token_ids) - required
            start = (
                seed * 17 + step * 104_729 + row_index * 1_009
            ) % (maximum_start + 1)
            rows.append(token_ids[start : start + required])
            continue

        row = list(token_ids)
        # Every non-empty UTF-8 record contributes at least BOS, one byte token
        # and EOS, so this loop is strictly bounded by ``required`` iterations.
        while len(row) < required:
            record_index = (record_index + 1) % len(bundle.records)
            following = bundle.tokenizer.encode(
                bundle.records[record_index].text, bos=True, eos=True
            )
            row.extend(following[: required - len(row)])
        rows.append(row)

    return rows


def training_contract(
    args: argparse.Namespace,
    config_hash: str,
    torch: Any,
    *,
    authorized_bundle: AuthorizedTextBundle | None = None,
) -> dict[str, Any]:
    contract = {
        "schema_version": "0.1.0",
        "config_sha256": config_hash,
        # TorchVersion is a str subclass in recent PyTorch releases.  Persist a
        # plain str so checkpoints remain loadable with weights_only=True.
        "torch": str(torch.__version__),
        "device": "cpu",
        "dtype": "float32",
        "optimizer": "AdamW",
        "learning_rate": args.learning_rate,
        "batch_size": args.batch_size,
        "sequence_length": args.sequence_length,
        "seed": args.seed,
        "threads": args.threads,
    }
    data_mode = getattr(args, "data_mode", DATA_MODE_SYNTHETIC)
    if data_mode == DATA_MODE_SYNTHETIC:
        if authorized_bundle is not None:
            raise ValueError("synthetic mode does not accept an authorized bundle")
        # Keep the historical synthetic contract byte-for-byte compatible.
        contract["synthetic_generator"] = "arithmetic-v1"
    elif data_mode == DATA_MODE_AUTHORIZED_TEXT:
        if not isinstance(authorized_bundle, AuthorizedTextBundle):
            raise ValueError("authorized-text requires a validated training bundle")
        contract["schema_version"] = "0.2.0"
        contract["data_mode"] = DATA_MODE_AUTHORIZED_TEXT
        contract["data_lineage"] = authorized_bundle.lineage_contract()
    else:
        raise ValueError("unsupported training data mode")
    return contract


def load_training_bundle(
    args: argparse.Namespace, *, model_vocabulary_size: int
) -> AuthorizedTextBundle | None:
    """Validate data-mode arguments and load authorized text without fallback."""

    data_mode = getattr(args, "data_mode", DATA_MODE_SYNTHETIC)
    paths = (
        getattr(args, "authorized_manifest", None),
        getattr(args, "authorized_train_jsonl", None),
        getattr(args, "authorized_tokenizer", None),
    )
    if data_mode == DATA_MODE_SYNTHETIC:
        if any(path is not None for path in paths):
            raise ValueError(
                "authorized-text paths are forbidden unless --data-mode authorized-text is selected"
            )
        return None
    if data_mode != DATA_MODE_AUTHORIZED_TEXT:
        raise ValueError("unsupported training data mode")
    if any(path is None for path in paths):
        raise ValueError(
            "authorized-text requires manifest, train JSONL and tokenizer paths"
        )
    if any(not isinstance(path, Path) for path in paths):
        raise ValueError("authorized-text inputs must be filesystem paths")
    manifest_path, train_jsonl_path, tokenizer_path = paths

    # This is deliberately the only authorized-text loading path.  The loader
    # verifies approval, split identity, bytes, hashes, record count and the
    # tokenizer lineage before any PyTorch runtime is initialized.
    try:
        bundle = load_authorized_text_bundle(
            manifest_path=manifest_path,
            train_jsonl_path=train_jsonl_path,
            tokenizer_path=tokenizer_path,
        )
    except OSError:
        # Do not echo an operator-supplied private path into public logs.
        raise ValueError("authorized-text input is unavailable") from None
    if bundle.tokenizer_vocabulary_size != model_vocabulary_size:
        raise ValueError(
            "authorized tokenizer vocabulary does not match the model configuration"
        )
    return bundle


def load_resume_checkpoint_with_digest(
    torch: Any, checkpoint_path: Path
) -> tuple[dict[str, Any], str]:
    """Load and hash one immutable, bounded byte copy on the CPU."""

    try:
        with checkpoint_path.open("rb") as checkpoint_file:
            metadata_before = os.fstat(checkpoint_file.fileno())
            if not stat.S_ISREG(metadata_before.st_mode):
                raise RuntimeError("Checkpoint must be a regular file")
            if not 1 <= metadata_before.st_size <= MAXIMUM_RESUME_CHECKPOINT_BYTES:
                raise RuntimeError("Checkpoint size is outside the bounded range")
            checkpoint_bytes = checkpoint_file.read(metadata_before.st_size + 1)
            metadata_after = os.fstat(checkpoint_file.fileno())
    except RuntimeError:
        raise
    except OSError:
        raise RuntimeError("Checkpoint is unavailable") from None
    if (
        len(checkpoint_bytes) != metadata_before.st_size
        or metadata_after.st_size != metadata_before.st_size
    ):
        raise RuntimeError("Checkpoint changed while being read")
    checkpoint_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
    try:
        checkpoint = torch.load(
            io.BytesIO(checkpoint_bytes), map_location="cpu", weights_only=True
        )
    except Exception:
        raise RuntimeError("Checkpoint could not be loaded safely") from None
    finally:
        checkpoint_bytes = b""
    if not isinstance(checkpoint, dict):
        raise RuntimeError("Checkpoint must be a mapping")
    return checkpoint, checkpoint_sha256


def load_resume_checkpoint(torch: Any, checkpoint_path: Path) -> dict[str, Any]:
    """Backward-compatible checkpoint-only view of the strict loader."""

    checkpoint, _ = load_resume_checkpoint_with_digest(torch, checkpoint_path)
    return checkpoint


def validate_resume_checkpoint_document(
    checkpoint: dict[str, Any],
    *,
    model_name: str,
    config_sha256: str,
    contract: dict[str, Any],
) -> int:
    """Validate the bounded checkpoint envelope before loading tensor state."""

    if set(checkpoint) != CHECKPOINT_KEYS:
        raise RuntimeError("Checkpoint keys are incompatible")
    if checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
        raise RuntimeError("Unsupported checkpoint schema_version")
    if checkpoint["model_name"] != model_name:
        raise RuntimeError("Checkpoint model name does not match")
    if checkpoint["config_sha256"] != config_sha256:
        raise RuntimeError("Checkpoint configuration does not match")
    if not strict_recursive_equal(checkpoint["training_contract"], contract):
        raise RuntimeError("Checkpoint training contract does not match")
    if (
        type(checkpoint["step"]) is not int
        or not 1 <= checkpoint["step"] <= MAXIMUM_TOTAL_STEPS
    ):
        raise RuntimeError("Checkpoint step is invalid")
    if not isinstance(checkpoint["model"], dict) or not isinstance(
        checkpoint["optimizer"], dict
    ):
        raise RuntimeError("Checkpoint state is incomplete")
    if not isinstance(checkpoint["run"], dict):
        raise RuntimeError("Checkpoint run metadata is invalid")
    return checkpoint["step"]


def load_resume_state_strict(
    torch: Any,
    model: Any,
    optimizer: Any,
    checkpoint: dict[str, Any],
) -> tuple[int, int]:
    """Load an exact model and AdamW state after full pre/post validation."""

    checkpoint_step = checkpoint.get("step")
    if (
        type(checkpoint_step) is not int
        or not 1 <= checkpoint_step <= MAXIMUM_TOTAL_STEPS
    ):
        raise RuntimeError("Checkpoint step is invalid")
    model_key_count = load_model_state_strict(torch, model, checkpoint.get("model"))
    optimizer_parameter_count = load_optimizer_state_strict(
        torch,
        optimizer,
        model,
        checkpoint.get("optimizer"),
        checkpoint_step=checkpoint_step,
    )
    return model_key_count, optimizer_parameter_count


def training_metric_record(
    *,
    step: int,
    loss: float,
    elapsed_seconds: float,
    tokens: int,
    authorized_bundle: AuthorizedTextBundle | None,
    training_contract_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one content-free metric record with required data lineage."""

    if type(step) is not int or step < 1:
        raise ValueError("metric step must be a positive integer")
    if type(loss) is not float or not math.isfinite(loss) or loss < 0:
        raise ValueError("metric loss must be a finite non-negative float")
    if (
        type(elapsed_seconds) is not float
        or not math.isfinite(elapsed_seconds)
        or elapsed_seconds < 0
    ):
        raise ValueError(
            "metric elapsed_seconds must be a finite non-negative float"
        )
    if type(tokens) is not int or tokens < 1:
        raise ValueError("metric tokens must be a positive integer")
    record: dict[str, Any] = {
        "step": step,
        "loss": loss,
        "elapsed_seconds": elapsed_seconds,
        "tokens": tokens,
    }
    if authorized_bundle is not None:
        if not isinstance(authorized_bundle, AuthorizedTextBundle):
            raise ValueError("authorized metrics require a validated training bundle")
        if not isinstance(training_contract_document, dict):
            raise ValueError("authorized metrics require the complete training contract")
        record["data_mode"] = DATA_MODE_AUTHORIZED_TEXT
        record["data_lineage"] = authorized_bundle.lineage_contract()
        record["training_contract_sha256"] = training_contract_sha256(
            training_contract_document
        )
    elif training_contract_document is not None:
        raise ValueError("synthetic metrics do not accept an authorized contract")
    return record


def training_contract_sha256(contract: dict[str, Any]) -> str:
    """Hash the complete contract using canonical UTF-8 JSON."""

    if not isinstance(contract, dict):
        raise ValueError("training contract must be a mapping")
    try:
        canonical = json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ValueError("training contract is not canonical JSON") from None
    return hashlib.sha256(canonical).hexdigest()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object key")
        document[key] = value
    return document


def validate_authorized_metrics_payload(
    payload: bytes,
    *,
    authorized_bundle: AuthorizedTextBundle,
    training_contract_document: dict[str, Any],
    expected_tokens: int,
    checkpoint_step: int,
) -> tuple[int, int]:
    """Return the validated last step and byte offset of the checkpoint prefix."""

    if not isinstance(authorized_bundle, AuthorizedTextBundle):
        raise ValueError("authorized metrics require a validated training bundle")
    if not isinstance(training_contract_document, dict):
        raise ValueError("authorized metrics require the complete training contract")
    if type(expected_tokens) is not int or expected_tokens < 1:
        raise ValueError("expected metric token count is invalid")
    if type(checkpoint_step) is not int or checkpoint_step < 0:
        raise ValueError("checkpoint metrics step is invalid")
    if not isinstance(payload, bytes) or len(payload) > MAXIMUM_METRICS_BYTES:
        raise RuntimeError("Existing metrics size is outside the bounded range")
    if not payload:
        if checkpoint_step != 0:
            raise RuntimeError("Existing metrics are behind the checkpoint step")
        return 0, 0
    if not payload.endswith(b"\n"):
        raise RuntimeError("Existing metrics contain an incomplete record")

    expected_lineage = authorized_bundle.lineage_contract()
    expected_contract_sha256 = training_contract_sha256(training_contract_document)
    previous_step = 0
    prefix_offset = 0
    current_offset = 0
    raw_lines = payload.split(b"\n")
    raw_lines.pop()
    for raw_line_with_optional_cr in raw_lines:
        consumed_bytes = len(raw_line_with_optional_cr) + 1
        raw_line = (
            raw_line_with_optional_cr[:-1]
            if raw_line_with_optional_cr.endswith(b"\r")
            else raw_line_with_optional_cr
        )
        if not raw_line or len(raw_line) > MAXIMUM_METRIC_LINE_BYTES:
            raise RuntimeError("Existing metrics record is outside the bounded range")
        try:
            record = json.loads(
                raw_line.decode("utf-8"), object_pairs_hook=_unique_json_object
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise RuntimeError("Existing metrics contain invalid strict JSON") from None
        if not isinstance(record, dict):
            raise RuntimeError("Existing metrics record must be a mapping")
        if set(record) != AUTHORIZED_METRIC_KEYS:
            raise RuntimeError("Existing metrics keys are incompatible")
        if record["data_mode"] != DATA_MODE_AUTHORIZED_TEXT:
            raise RuntimeError("Existing metrics data mode does not match")
        if not strict_recursive_equal(record["data_lineage"], expected_lineage):
            raise RuntimeError("Existing metrics data lineage does not match")
        if record["training_contract_sha256"] != expected_contract_sha256:
            raise RuntimeError("Existing metrics training contract does not match")
        step = record["step"]
        if type(step) is not int or step < 1:
            raise RuntimeError("Existing metrics step is invalid")
        if step != previous_step + 1:
            raise RuntimeError("Existing metrics steps are not contiguous")
        loss = record["loss"]
        if type(loss) is not float or not math.isfinite(loss) or loss < 0:
            raise RuntimeError("Existing metrics loss is invalid")
        elapsed_seconds = record["elapsed_seconds"]
        if (
            type(elapsed_seconds) is not float
            or not math.isfinite(elapsed_seconds)
            or elapsed_seconds < 0
        ):
            raise RuntimeError("Existing metrics elapsed_seconds is invalid")
        if type(record["tokens"]) is not int or record["tokens"] != expected_tokens:
            raise RuntimeError("Existing metrics token count does not match")
        previous_step = step
        current_offset += consumed_bytes
        if step == checkpoint_step:
            prefix_offset = current_offset

    if previous_step < checkpoint_step:
        raise RuntimeError("Existing metrics are behind the checkpoint step")
    return previous_step, prefix_offset


def _validate_sha256(value: Any, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeError(f"{label} is invalid")
    return value


def authorized_metrics_binding_from_checkpoint(
    checkpoint: dict[str, Any], *, checkpoint_step: int
) -> str:
    """Return the content-free journal prefix binding from an authorized checkpoint."""

    if type(checkpoint_step) is not int or checkpoint_step < 1:
        raise RuntimeError("Authorized metrics checkpoint step is invalid")
    run = checkpoint.get("run")
    if not isinstance(run, dict) or run.get("data_mode") != DATA_MODE_AUTHORIZED_TEXT:
        raise RuntimeError("Authorized checkpoint run metadata is incompatible")
    binding = run.get("authorized_metrics")
    if not isinstance(binding, dict) or set(binding) != {"prefix_sha256", "step"}:
        raise RuntimeError("Authorized metrics checkpoint binding is incomplete")
    if type(binding["step"]) is not int or binding["step"] != checkpoint_step:
        raise RuntimeError("Authorized metrics checkpoint binding step does not match")
    return _validate_sha256(
        binding["prefix_sha256"], label="Authorized metrics prefix digest"
    )


@contextmanager
def open_authorized_metrics_journal(
    metrics_path: Path,
    *,
    authorized_bundle: AuthorizedTextBundle,
    training_contract_document: dict[str, Any],
    expected_tokens: int,
    checkpoint_step: int,
    require_existing: bool,
    recover_ahead: bool,
    expected_prefix_sha256: str | None = None,
) -> Iterator[BinaryIO]:
    """Validate, reconcile and append one journal through one file handle."""

    flags = (
        os.O_RDWR
        | os.O_APPEND
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if not require_existing:
        flags |= os.O_CREAT
    file_descriptor: int | None = None
    journal: BinaryIO | None = None
    try:
        file_descriptor = os.open(metrics_path, flags, 0o600)
        journal = os.fdopen(file_descriptor, "r+b", buffering=0)
        file_descriptor = None
        metadata = os.fstat(journal.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("Authorized metrics must be a regular file")
        if not 0 <= metadata.st_size <= MAXIMUM_METRICS_BYTES:
            raise RuntimeError("Existing metrics size is outside the bounded range")
        journal.seek(0)
        payload = journal.read(MAXIMUM_METRICS_BYTES + 1)
        metadata_after_read = os.fstat(journal.fileno())
        if (
            len(payload) != metadata.st_size
            or metadata_after_read.st_size != metadata.st_size
        ):
            raise RuntimeError("Existing metrics changed while being read")
        last_step, checkpoint_offset = validate_authorized_metrics_payload(
            payload,
            authorized_bundle=authorized_bundle,
            training_contract_document=training_contract_document,
            expected_tokens=expected_tokens,
            checkpoint_step=checkpoint_step,
        )
        if checkpoint_step > 0:
            if expected_prefix_sha256 is None:
                raise RuntimeError("Authorized metrics checkpoint binding is required")
            expected_prefix_sha256 = _validate_sha256(
                expected_prefix_sha256,
                label="Authorized metrics checkpoint prefix digest",
            )
            prefix_sha256 = hashlib.sha256(payload[:checkpoint_offset]).hexdigest()
            if prefix_sha256 != expected_prefix_sha256:
                raise RuntimeError("Authorized metrics checkpoint prefix does not match")
        if last_step > checkpoint_step:
            if not recover_ahead:
                raise RuntimeError("Existing metrics are ahead without a checkpoint")
            os.ftruncate(journal.fileno(), checkpoint_offset)
            os.fsync(journal.fileno())
            journal.seek(0)
            recovered_prefix = journal.read(checkpoint_offset + 1)
            recovered_metadata = os.fstat(journal.fileno())
            if (
                recovered_metadata.st_size != checkpoint_offset
                or len(recovered_prefix) != checkpoint_offset
                or hashlib.sha256(recovered_prefix).hexdigest()
                != expected_prefix_sha256
            ):
                raise RuntimeError("Authorized metrics recovery could not be verified")
        journal.seek(0, os.SEEK_END)
    except RuntimeError:
        if journal is not None:
            journal.close()
        elif file_descriptor is not None:
            os.close(file_descriptor)
        raise
    except OSError:
        if journal is not None:
            journal.close()
        elif file_descriptor is not None:
            os.close(file_descriptor)
        raise RuntimeError("Authorized metrics journal is unavailable") from None

    if journal is None:
        raise RuntimeError("Authorized metrics journal is unavailable")
    try:
        yield journal
    finally:
        journal.close()


def hash_authorized_metrics_journal(
    journal: BinaryIO,
    *,
    authorized_bundle: AuthorizedTextBundle,
    training_contract_document: dict[str, Any],
    expected_tokens: int,
    checkpoint_step: int,
) -> str:
    """Validate and hash the exact authorized journal prefix held by one handle."""

    try:
        metadata = os.fstat(journal.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 0 <= metadata.st_size <= MAXIMUM_METRICS_BYTES
        ):
            raise RuntimeError("Authorized metrics size is outside the bounded range")
        journal.seek(0)
        payload = journal.read(metadata.st_size + 1)
        metadata_after = os.fstat(journal.fileno())
        if (
            len(payload) != metadata.st_size
            or metadata_after.st_size != metadata.st_size
        ):
            raise RuntimeError("Authorized metrics changed while being hashed")
        last_step, checkpoint_offset = validate_authorized_metrics_payload(
            payload,
            authorized_bundle=authorized_bundle,
            training_contract_document=training_contract_document,
            expected_tokens=expected_tokens,
            checkpoint_step=checkpoint_step,
        )
        if last_step != checkpoint_step or checkpoint_offset != len(payload):
            raise RuntimeError("Authorized metrics do not match the final checkpoint")
        return hashlib.sha256(payload).hexdigest()
    except RuntimeError:
        raise
    except OSError:
        raise RuntimeError("Authorized metrics journal is unavailable") from None
    finally:
        try:
            journal.seek(0, os.SEEK_END)
        except OSError:
            pass


def append_authorized_metric(journal: BinaryIO, record: dict[str, Any]) -> None:
    """Durably append one validated, content-free metric record."""

    if not isinstance(record, dict) or set(record) != AUTHORIZED_METRIC_KEYS:
        raise RuntimeError("Authorized metric record keys are incompatible")
    try:
        encoded = (
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        if len(encoded) > MAXIMUM_METRIC_LINE_BYTES + 1:
            raise RuntimeError("Authorized metric record exceeds the bounded range")
        metadata = os.fstat(journal.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size + len(encoded) > MAXIMUM_METRICS_BYTES
        ):
            raise RuntimeError("Authorized metrics journal exceeds the bounded range")
        written = journal.write(encoded)
        if written != len(encoded):
            raise OSError("short journal write")
        journal.flush()
        os.fsync(journal.fileno())
        if os.fstat(journal.fileno()).st_size != metadata.st_size + len(encoded):
            raise RuntimeError("Authorized metrics journal changed during append")
    except RuntimeError:
        raise
    except (OSError, TypeError, ValueError):
        raise RuntimeError("Authorized metrics journal write failed") from None


def training_run_metadata(
    args: argparse.Namespace,
    contract: dict[str, Any],
    *,
    authorized_bundle: AuthorizedTextBundle | None,
    parent_checkpoint_sha256: str | None,
    parent_step: int | None,
    authorized_metrics_prefix_sha256: str | None = None,
    authorized_metrics_step: int | None = None,
) -> dict[str, Any]:
    """Build content-free runtime metadata with an optional parent lineage."""

    if (parent_checkpoint_sha256 is None) != (parent_step is None):
        raise RuntimeError("Parent checkpoint lineage is incomplete")
    run: dict[str, Any] = {
        "device": "cpu",
        "torch": contract["torch"],
        "python": platform.python_version(),
        "platform": platform.platform(),
        "threads": args.threads,
        "batch_size": args.batch_size,
        "sequence_length": args.sequence_length,
        "seed": args.seed,
        "learning_rate": args.learning_rate,
        **(
            {"data_mode": DATA_MODE_AUTHORIZED_TEXT}
            if authorized_bundle is not None
            else {}
        ),
    }
    if parent_checkpoint_sha256 is not None:
        if (
            len(parent_checkpoint_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in parent_checkpoint_sha256
            )
            or type(parent_step) is not int
            or not 1 <= parent_step <= MAXIMUM_TOTAL_STEPS
        ):
            raise RuntimeError("Parent checkpoint lineage is invalid")
        run["lineage"] = {
            "parent_checkpoint_sha256": parent_checkpoint_sha256,
            "parent_step": parent_step,
        }
    if authorized_bundle is not None:
        prefix_sha256 = _validate_sha256(
            authorized_metrics_prefix_sha256,
            label="Authorized metrics prefix digest",
        )
        if (
            type(authorized_metrics_step) is not int
            or not 1 <= authorized_metrics_step <= MAXIMUM_TOTAL_STEPS
        ):
            raise RuntimeError("Authorized metrics step is invalid")
        run["authorized_metrics"] = {
            "prefix_sha256": prefix_sha256,
            "step": authorized_metrics_step,
        }
    elif (
        authorized_metrics_prefix_sha256 is not None
        or authorized_metrics_step is not None
    ):
        raise RuntimeError("Synthetic runs cannot bind authorized metrics")
    return run


def _hash_open_checkpoint(checkpoint_file: BinaryIO) -> str:
    checkpoint_file.seek(0)
    digest = hashlib.sha256()
    while chunk := checkpoint_file.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def save_checkpoint(
    torch: Any, checkpoint_path: Path, payload: dict[str, Any]
) -> str:
    """Atomically save through one exclusive same-directory file and return its hash."""

    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{checkpoint_path.name}.",
            suffix=".tmp",
            dir=str(checkpoint_path.parent),
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w+b") as checkpoint_file:
            descriptor = None
            torch.save(payload, checkpoint_file)
            checkpoint_file.flush()
            os.fsync(checkpoint_file.fileno())
            checkpoint_sha256 = _hash_open_checkpoint(checkpoint_file)
        os.replace(temporary_path, checkpoint_path)
        temporary_path = None
        if os.name != "nt":
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_descriptor = os.open(checkpoint_path.parent, directory_flags)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        return checkpoint_sha256
    except Exception:
        raise RuntimeError("Checkpoint could not be saved safely") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def checkpoint_public_result(
    checkpoint_path: Path, checkpoint_sha256: str
) -> dict[str, str]:
    """Return a success payload that cannot expose the parent directory."""

    if (
        len(checkpoint_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in checkpoint_sha256
        )
    ):
        raise RuntimeError("Checkpoint digest is invalid")
    return {
        "checkpoint_name": checkpoint_path.name,
        "checkpoint_sha256": checkpoint_sha256,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = PathFreeArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sequence-length", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--resume", type=Path)
    parser.add_argument(
        "--data-mode",
        choices=(DATA_MODE_SYNTHETIC, DATA_MODE_AUTHORIZED_TEXT),
        default=DATA_MODE_SYNTHETIC,
    )
    parser.add_argument("--authorized-manifest", type=Path)
    parser.add_argument("--authorized-train-jsonl", type=Path)
    parser.add_argument("--authorized-tokenizer", type=Path)
    return parser.parse_args(argv)


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    validate_run_limits(
        steps=args.steps,
        batch_size=args.batch_size,
        sequence_length=args.sequence_length,
    )
    if type(args.threads) is not int or not 1 <= args.threads <= 256:
        raise ValueError("threads must be between 1 and 256")
    if type(args.seed) is not int or not -(2**63) <= args.seed < 2**63:
        raise ValueError("seed must fit a signed 64-bit integer")
    if (
        isinstance(args.learning_rate, bool)
        or not math.isfinite(args.learning_rate)
        or not 0.0 < args.learning_rate <= 1.0
    ):
        raise ValueError("learning_rate must be between 0 and 1")
    document, config, config_hash = load_core_mini_configuration(args.config)
    authorized_bundle = load_training_bundle(
        args, model_vocabulary_size=config.vocabulary_size
    )
    torch = require_cpu_torch()
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)

    model = build_model(torch, config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    start_step = 0
    parent_checkpoint_sha256: str | None = None
    parent_step: int | None = None
    expected_authorized_metrics_sha256: str | None = None
    contract = training_contract(
        args, config_hash, torch, authorized_bundle=authorized_bundle
    )
    if args.resume is not None:
        checkpoint, parent_checkpoint_sha256 = load_resume_checkpoint_with_digest(
            torch, args.resume
        )
        start_step = validate_resume_checkpoint_document(
            checkpoint,
            model_name=document["name"],
            config_sha256=config_hash,
            contract=contract,
        )
        if authorized_bundle is not None:
            expected_authorized_metrics_sha256 = (
                authorized_metrics_binding_from_checkpoint(
                    checkpoint, checkpoint_step=start_step
                )
            )
        load_resume_state_strict(torch, model, optimizer, checkpoint)
        parent_step = start_step

    final_step = calculate_final_step(start_step=start_step, steps=args.steps)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "metrics.jsonl"
    expected_metric_tokens = args.batch_size * args.sequence_length
    if authorized_bundle is not None:
        metrics_context = open_authorized_metrics_journal(
            metrics_path,
            authorized_bundle=authorized_bundle,
            training_contract_document=contract,
            expected_tokens=expected_metric_tokens,
            checkpoint_step=start_step,
            require_existing=args.resume is not None and start_step > 0,
            recover_ahead=args.resume is not None,
            expected_prefix_sha256=expected_authorized_metrics_sha256,
        )
    else:
        metrics_context = metrics_path.open("a", encoding="utf-8")
    started = time.perf_counter()
    authorized_metrics_prefix_sha256: str | None = None
    with metrics_context as metrics_file:
        for step in range(start_step, final_step):
            if args.data_mode == DATA_MODE_SYNTHETIC:
                rows = synthetic_token_rows(
                    step=step,
                    batch_size=args.batch_size,
                    sequence_length=args.sequence_length,
                    vocabulary_size=config.vocabulary_size,
                    seed=args.seed,
                )
            else:
                if authorized_bundle is None:  # defensive: no implicit fallback
                    raise RuntimeError("authorized-text bundle is unavailable")
                rows = authorized_text_token_rows(
                    authorized_bundle,
                    step=step,
                    batch_size=args.batch_size,
                    sequence_length=args.sequence_length,
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
            validate_model_gradients_finite(torch, model)
            optimizer.step()
            record = training_metric_record(
                step=step + 1,
                loss=float(loss.detach()),
                elapsed_seconds=time.perf_counter() - started,
                tokens=expected_metric_tokens,
                authorized_bundle=authorized_bundle,
                training_contract_document=(
                    contract if authorized_bundle is not None else None
                ),
            )
            if authorized_bundle is not None:
                append_authorized_metric(metrics_file, record)
            else:
                metrics_file.write(json.dumps(record, sort_keys=True) + "\n")
                metrics_file.flush()
        if authorized_bundle is not None:
            authorized_metrics_prefix_sha256 = hash_authorized_metrics_journal(
                metrics_file,
                authorized_bundle=authorized_bundle,
                training_contract_document=contract,
                expected_tokens=expected_metric_tokens,
                checkpoint_step=final_step,
            )

    final_model_state = model.state_dict()
    final_optimizer_state = optimizer.state_dict()
    load_model_state_strict(torch, model, final_model_state)
    load_optimizer_state_strict(
        torch,
        optimizer,
        model,
        final_optimizer_state,
        checkpoint_step=final_step,
    )
    checkpoint_path = args.output_dir / f"core-mini-step-{final_step:06d}.pt"
    checkpoint_sha256 = save_checkpoint(
        torch,
        checkpoint_path,
        {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "model_name": document["name"],
            "step": final_step,
            "config_sha256": config_hash,
            "training_contract": contract,
            "model": final_model_state,
            "optimizer": final_optimizer_state,
            "run": training_run_metadata(
                args,
                contract,
                authorized_bundle=authorized_bundle,
                parent_checkpoint_sha256=parent_checkpoint_sha256,
                parent_step=parent_step,
                authorized_metrics_prefix_sha256=authorized_metrics_prefix_sha256,
                authorized_metrics_step=(
                    final_step if authorized_bundle is not None else None
                ),
            ),
        },
    )
    print(
        json.dumps(
            checkpoint_public_result(checkpoint_path, checkpoint_sha256),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the public CLI without ever echoing operator-supplied paths."""

    try:
        return _main(argv)
    except Exception:
        print("CORE-MINI training refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
