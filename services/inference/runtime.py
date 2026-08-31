"""CPU-only inference boundary for the future CORE runtime.

The candidate model has no weights yet. This boundary therefore fails closed
with a structured status instead of silently substituting a remote or GPU
backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeStatus:
    state: str
    backend: str
    model_name: str
    weights_present: bool
    generation_available: bool
    network: str = "disabled"


class InferenceUnavailable(RuntimeError):
    """Raised when inference is requested before local weights are installed."""


class LocalInferenceRuntime:
    def __init__(self, model_name: str, weights_path: Path) -> None:
        if not model_name or not model_name.isascii():
            raise ValueError("model_name must be a non-empty ASCII identifier")
        self.model_name = model_name
        self.weights_path = weights_path

    def status(self) -> RuntimeStatus:
        present = self.weights_path.is_file()
        return RuntimeStatus(
            state=(
                "weights_detected_runtime_disabled"
                if present
                else "awaiting_local_weights"
            ),
            backend="cpu_only",
            model_name=self.model_name,
            weights_present=present,
            generation_available=False,
        )

    def generate(self, prompt: str, *, max_new_tokens: int = 128) -> dict[str, Any]:
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 12_000:
            raise ValueError("prompt must contain between 1 and 12000 characters")
        if not 1 <= max_new_tokens <= 2048:
            raise ValueError("max_new_tokens must be between 1 and 2048")
        if not self.weights_path.is_file():
            raise InferenceUnavailable("local model weights are not installed")
        raise InferenceUnavailable("CORE runtime implementation is not enabled in phase 0")
