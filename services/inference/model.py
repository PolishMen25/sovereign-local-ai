"""Shared, CPU-only implementation of the CORE decoder model.

This module deliberately performs no network access, dependency installation,
checkpoint loading, or backend fallback.  Both training and future inference
must build the model through :func:`build_model` so their parameter names and
tensor shapes remain identical.
"""

from __future__ import annotations

from typing import Any

from tools.count_core_parameters import CoreConfig, count_parameters


def validate_cpu_torch(torch: Any) -> Any:
    """Return *torch* only when it is an explicitly CPU-only build.

    Checking both the build metadata and the runtime availability prevents a
    partially mocked or unusual installation from silently selecting a GPU.
    """

    version = getattr(torch, "version", None)
    if version is None:
        raise RuntimeError("PyTorch version metadata is unavailable")
    if getattr(version, "cuda", None) is not None or getattr(version, "hip", None) is not None:
        raise RuntimeError("CUDA/ROCm builds are forbidden for this CPU-only runtime")

    cuda = getattr(torch, "cuda", None)
    if cuda is not None:
        is_available = getattr(cuda, "is_available", None)
        if not callable(is_available):
            raise RuntimeError("PyTorch CUDA runtime metadata is invalid")
        if is_available():
            raise RuntimeError("A CUDA runtime is forbidden for this CPU-only runtime")
    return torch


def require_cpu_torch() -> Any:
    """Import the locally installed PyTorch package and enforce CPU-only use."""

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is absent; install only from the verified offline CPU bundle"
        ) from exc
    return validate_cpu_torch(torch)


def build_model(torch: Any, config: CoreConfig) -> Any:
    """Build the strict CORE decoder on CPU with stable state-dict names."""

    validate_cpu_torch(torch)
    config.validate()
    if not config.tie_word_embeddings:
        raise ValueError("The shared CORE implementation requires tied embeddings")

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

    class CoreModel(nn.Module):
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
                raise RuntimeError("CORE accepts CPU tensors only")
            hidden = self.token_embeddings(token_ids)
            for block in self.blocks:
                hidden = block(hidden)
            hidden = self.final_norm(hidden)
            return functional.linear(hidden, self.token_embeddings.weight)

    model = CoreModel()
    expected = count_parameters(config)["total_trainable"]
    observed = sum(parameter.numel() for parameter in model.parameters())
    if observed != expected:
        raise RuntimeError(f"Parameter mismatch: expected {expected}, observed {observed}")
    if any(parameter.device.type != "cpu" for parameter in model.parameters()):
        raise RuntimeError("A model parameter was created outside the CPU")
    return model
