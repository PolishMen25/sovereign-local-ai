#!/usr/bin/env python3
"""Count parameters for the provisional, bias-free CORE decoder architecture."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = (
    Path(__file__).parents[1] / "configs" / "models" / "core-80m.candidate.json"
)


@dataclass(frozen=True)
class CoreConfig:
    vocabulary_size: int
    hidden_size: int
    num_hidden_layers: int
    num_attention_heads: int
    head_dimension: int
    intermediate_size: int
    tie_word_embeddings: bool

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "CoreConfig":
        architecture = document["architecture"]
        if architecture.get("attention_variant") != "standard_mha":
            raise ValueError("The counter currently supports standard_mha only")
        if architecture.get("activation") != "swiglu":
            raise ValueError("The counter currently supports swiglu only")
        if architecture.get("normalization") != "rmsnorm":
            raise ValueError("The counter currently supports rmsnorm only")
        if architecture.get("position_encoding") != "rope":
            raise ValueError("The counter assumes parameter-free rope positions")
        if architecture.get("use_bias") is not False:
            raise ValueError("The counter assumes a bias-free architecture")
        return cls(
            vocabulary_size=architecture["vocabulary_size"],
            hidden_size=architecture["hidden_size"],
            num_hidden_layers=architecture["num_hidden_layers"],
            num_attention_heads=architecture["num_attention_heads"],
            head_dimension=architecture["head_dimension"],
            intermediate_size=architecture["intermediate_size"],
            tie_word_embeddings=architecture["tie_word_embeddings"],
        )

    def validate(self) -> None:
        values = (
            self.vocabulary_size,
            self.hidden_size,
            self.num_hidden_layers,
            self.num_attention_heads,
            self.head_dimension,
            self.intermediate_size,
        )
        if any(value <= 0 for value in values):
            raise ValueError("All dimensions must be strictly positive")
        if self.hidden_size % self.num_attention_heads != 0:
            raise ValueError("hidden_size must be divisible by num_attention_heads")
        if self.hidden_size != self.num_attention_heads * self.head_dimension:
            raise ValueError("hidden_size must equal heads multiplied by head_dimension")
        if self.head_dimension % 2 != 0:
            raise ValueError("head_dimension must be even for rotary positions")


def load_candidate_document(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as config_file:
        document = json.load(config_file)
    if document.get("status") != "candidate":
        raise ValueError("Expected a candidate configuration")
    return document


def count_parameters(config: CoreConfig) -> dict[str, int]:
    """Return an exact breakdown for tied embeddings, SwiGLU and two RMSNorms/block."""
    config.validate()
    d_model = config.hidden_size

    token_embeddings = config.vocabulary_size * d_model
    attention_per_layer = 4 * d_model * d_model  # Q, K, V and output
    mlp_per_layer = 3 * d_model * config.intermediate_size  # gate, up, down
    norms_per_layer = 2 * d_model
    transformer_blocks = config.num_hidden_layers * (
        attention_per_layer + mlp_per_layer + norms_per_layer
    )
    final_norm = d_model
    output_head = 0 if config.tie_word_embeddings else config.vocabulary_size * d_model
    total = token_embeddings + transformer_blocks + final_norm + output_head

    return {
        "token_embeddings": token_embeddings,
        "attention_per_layer": attention_per_layer,
        "mlp_per_layer": mlp_per_layer,
        "norms_per_layer": norms_per_layer,
        "transformer_blocks": transformer_blocks,
        "final_norm": final_norm,
        "output_head": output_head,
        "total_trainable": total,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    document = load_candidate_document(args.config)
    config = CoreConfig.from_document(document)
    breakdown = count_parameters(config)
    declared = document.get("parameter_count")
    if declared != breakdown:
        raise ValueError(
            "Declared parameter_count does not match the architecture: "
            f"declared={declared!r}, calculated={breakdown!r}"
        )
    for name, value in breakdown.items():
        print(f"{name:24} {value:>12,}")


if __name__ == "__main__":
    main()

