"""Strict CPU-only experimental inference for a local CORE checkpoint."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from services.inference.checkpoint_envelope import (
    ACCEPTED_ENVELOPE_KEY_SETS,
    allowed_checkpoint_schemas,
)
from services.inference.configuration import load_core_candidate_configuration
from services.inference.model import build_model, require_cpu_torch
from services.inference.tokenizer import EOS_TOKEN_ID, load_tokenizer


@dataclass(frozen=True)
class RuntimeStatus:
    state: str
    backend: str
    model_name: str
    weights_present: bool
    generation_available: bool
    network: str = "disabled"


class InferenceUnavailable(RuntimeError):
    """Raised when local inference cannot prove its complete contract."""


__all__ = [
    "InferenceUnavailable",
    "LocalInferenceRuntime",
    "RuntimeStatus",
    "allowed_checkpoint_schemas",
    "is_collapsed_output",
    "runtime_state",
    "validate_inference_checkpoint",
]

# Periods checked by the quality gate.  Width 7 is not in the list: keep it
# that way unless the gate itself is deliberately changed.
_COLLAPSE_PERIODS = (1, 2, 3, 4, 5, 6, 8)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise InferenceUnavailable("CORE contract artifact is unavailable") from error


def runtime_state(*, ready: bool, loaded: bool, weights_present: bool) -> str:
    """Return the public runtime state label for one combination of facts."""

    if ready and loaded:
        return "ready_experimental"
    if ready:
        return "checkpoint_pending_validation"
    if weights_present:
        return "weights_detected_runtime_disabled"
    return "awaiting_local_weights"


def validate_inference_checkpoint(
    checkpoint: Any, *, model_name: str, expected_contract: dict[str, str]
) -> dict[str, Any]:
    """Return the model state of an envelope that belongs to this candidate.

    Pure function: no torch, no file access, so every refusal is unit-testable.
    """

    if not isinstance(checkpoint, dict) or set(checkpoint) not in ACCEPTED_ENVELOPE_KEY_SETS:
        raise InferenceUnavailable("CORE checkpoint envelope is incompatible")
    contract = checkpoint.get("contract")
    if (
        checkpoint.get("schema_version") not in allowed_checkpoint_schemas(model_name)
        or checkpoint.get("model_name") != model_name
        or not isinstance(contract, dict)
        or any(contract.get(key) != value for key, value in expected_contract.items())
        or not isinstance(checkpoint.get("model"), dict)
    ):
        raise InferenceUnavailable("CORE checkpoint provenance is incompatible")
    return checkpoint["model"]


def is_collapsed_output(answer: str) -> bool:
    """Return True when an answer is one short pattern repeated.

    A 20-step checkpoint can be mechanically loadable yet collapse into one
    repeated token.  Such output is refused instead of shown as an answer.
    """

    if len(answer) < 16:
        return False
    for width in _COLLAPSE_PERIODS:
        if len(answer) >= width * 4 and answer == answer[:width] * (len(answer) // width) + answer[: len(answer) % width]:
            return True
    return False


class LocalInferenceRuntime:
    """Reference greedy decoder; deliberately small and deterministic."""

    def __init__(self, model_name: str, weights_path: Path, *, config_path: Path | None = None, tokenizer_path: Path | None = None, manifest_path: Path | None = None, preflight_path: Path | None = None, max_context_tokens: int = 256) -> None:
        if not model_name or not model_name.isascii():
            raise ValueError("model_name must be a non-empty ASCII identifier")
        if not 8 <= max_context_tokens <= 2048:
            raise ValueError("max_context_tokens must be between 8 and 2048")
        self.model_name, self.weights_path = model_name, weights_path
        self.config_path, self.tokenizer_path = config_path, tokenizer_path
        self.manifest_path, self.preflight_path = manifest_path, preflight_path
        self.max_context_tokens = max_context_tokens
        self._model: Any | None = None
        self._tokenizer: Any | None = None

    def _inputs_ready(self) -> bool:
        return all(path is not None and path.is_file() for path in (self.weights_path, self.config_path, self.tokenizer_path, self.manifest_path, self.preflight_path))

    def status(self) -> RuntimeStatus:
        weights_present = self.weights_path.is_file()
        ready = self._inputs_ready()
        if ready and self._model is None:
            try:
                self._load()
            except InferenceUnavailable:
                return RuntimeStatus(state="checkpoint_refused", backend="cpu_only", model_name=self.model_name, weights_present=weights_present, generation_available=False)
        loaded = self._model is not None
        return RuntimeStatus(
            state=runtime_state(ready=ready, loaded=loaded, weights_present=weights_present),
            backend="cpu_only", model_name=self.model_name, weights_present=weights_present,
            generation_available=ready and loaded,
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self._inputs_ready() or None in (self.config_path, self.tokenizer_path, self.manifest_path, self.preflight_path):
            raise InferenceUnavailable("CORE checkpoint contract is incomplete")
        assert self.config_path and self.tokenizer_path and self.manifest_path and self.preflight_path
        document, config, config_sha = load_core_candidate_configuration(self.config_path)
        tokenizer = load_tokenizer(self.tokenizer_path)
        manifest, preflight = self._read_lineage_receipts()
        if document.get("name") != self.model_name or tokenizer.vocabulary_size != config.vocabulary_size or not isinstance(manifest, dict) or not isinstance(preflight, dict):
            raise InferenceUnavailable("CORE lineage is incompatible")
        expected = self._expected_contract(config_sha)
        torch = require_cpu_torch()
        try:
            checkpoint = torch.load(self.weights_path, map_location="cpu", weights_only=True)
        except Exception as error:
            raise InferenceUnavailable("CORE checkpoint cannot be loaded safely") from error
        model_state = validate_inference_checkpoint(checkpoint, model_name=self.model_name, expected_contract=expected)
        model = build_model(torch, config)
        try:
            model.load_state_dict(model_state, strict=True)
        except Exception as error:
            raise InferenceUnavailable("CORE checkpoint tensors are incompatible") from error
        model.eval()
        self._model, self._tokenizer = model, tokenizer

    def _read_lineage_receipts(self) -> tuple[Any, Any]:
        assert self.manifest_path and self.preflight_path
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            preflight = json.loads(self.preflight_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InferenceUnavailable("CORE lineage receipt is invalid") from error
        return manifest, preflight

    def _expected_contract(self, config_sha: str) -> dict[str, str]:
        assert self.manifest_path and self.tokenizer_path and self.preflight_path
        return {"config_sha256": config_sha, "manifest_sha256": _sha256(self.manifest_path), "tokenizer_sha256": _sha256(self.tokenizer_path), "preflight_sha256": _sha256(self.preflight_path)}

    def generate(self, prompt: str, *, max_new_tokens: int = 64, seed: int = 20260907) -> dict[str, Any]:
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 12_000:
            raise ValueError("prompt must contain between 1 and 12000 characters")
        if not 1 <= max_new_tokens <= 64 or type(seed) is not int:
            raise ValueError("CORE generation limits are invalid")
        self._load()
        assert self._model is not None and self._tokenizer is not None
        torch = require_cpu_torch()
        torch.manual_seed(seed)
        ids = self._tokenizer.encode(prompt, bos=True)[-self.max_context_tokens:]
        output: list[int] = []
        with torch.inference_mode():
            for _ in range(max_new_tokens):
                token_id = int(self._model(torch.tensor([ids[-self.max_context_tokens:]], dtype=torch.long))[0, -1].argmax().item())
                if token_id == EOS_TOKEN_ID:
                    break
                ids.append(token_id)
                output.append(token_id)
        answer = self._tokenizer.decode(output)
        if is_collapsed_output(answer):
            raise InferenceUnavailable("CORE quality gate refused repetitive output")
        return {"engine": self.model_name, "experimental": True, "answer": answer, "seed": seed}
