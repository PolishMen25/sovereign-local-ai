"""Single-read, bounded and strict CORE-MINI configuration loading."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from services.inference.checkpoint import strict_recursive_equal
from tools.count_core_parameters import CoreConfig, count_parameters


MAXIMUM_MODEL_CONFIG_BYTES = 1024 * 1024
EXPECTED_CORE_MINI_ARCHITECTURE = {
    "family": "decoder_only_transformer",
    "attention_variant": "standard_mha",
    "vocabulary_size": 4096,
    "hidden_size": 128,
    "num_hidden_layers": 4,
    "num_attention_heads": 4,
    "head_dimension": 32,
    "intermediate_size": 352,
    "activation": "swiglu",
    "position_encoding": "rope",
    "normalization": "rmsnorm",
    "tie_word_embeddings": True,
    "use_bias": False,
}
EXPECTED_CORE_MINI_PARAMETER_COUNT = {
    "token_embeddings": 524_288,
    "attention_per_layer": 65_536,
    "mlp_per_layer": 135_168,
    "norms_per_layer": 256,
    "transformer_blocks": 803_840,
    "final_norm": 128,
    "output_head": 0,
    "total_trainable": 1_328_256,
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object key")
        document[key] = value
    return document


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def load_core_mini_configuration(
    path: Path,
) -> tuple[dict[str, Any], CoreConfig, str]:
    """Parse, validate and hash exactly one immutable bounded byte copy."""

    try:
        with path.open("rb") as config_file:
            metadata_before = os.fstat(config_file.fileno())
            if not stat.S_ISREG(metadata_before.st_mode):
                raise ValueError("Model configuration must be a regular file")
            if not 1 <= metadata_before.st_size <= MAXIMUM_MODEL_CONFIG_BYTES:
                raise ValueError("Model configuration size is outside the bounded range")
            payload = config_file.read(metadata_before.st_size + 1)
            metadata_after = os.fstat(config_file.fileno())
    except ValueError:
        raise
    except OSError:
        raise ValueError("Model configuration is unavailable") from None
    if (
        len(payload) != metadata_before.st_size
        or metadata_after.st_size != metadata_before.st_size
    ):
        raise ValueError("Model configuration changed while being read")
    config_sha256 = hashlib.sha256(payload).hexdigest()
    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("Model configuration is not strict JSON") from None
    finally:
        payload = b""
    if not isinstance(document, dict):
        raise ValueError("Model configuration must be a mapping")
    if document.get("name") != "CORE-MINI-1M":
        raise ValueError("The training harness accepts CORE-MINI-1M only")
    if document.get("status") != "candidate":
        raise ValueError("Expected a candidate mini-model configuration")
    if not strict_recursive_equal(
        document.get("architecture"), EXPECTED_CORE_MINI_ARCHITECTURE
    ):
        raise ValueError("Model configuration architecture is not CORE-MINI-1M")
    config = CoreConfig.from_document(document)
    calculated = count_parameters(config)
    if not strict_recursive_equal(calculated, EXPECTED_CORE_MINI_PARAMETER_COUNT):
        raise ValueError("Calculated model size is not CORE-MINI-1M")
    if not strict_recursive_equal(
        document.get("parameter_count"), EXPECTED_CORE_MINI_PARAMETER_COUNT
    ):
        raise ValueError("Declared parameter count does not match the architecture")
    return document, config, config_sha256
