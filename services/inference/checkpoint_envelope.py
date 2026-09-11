"""Single definition of the CORE checkpoint envelope.

Training writes this envelope and inference reads it.  Both sides import the
names below so that a schema change is made in one place instead of being
re-typed in ``tools/train_core_700m.py`` and ``services/inference/runtime.py``.
"""

from __future__ import annotations

from typing import Any

TRAINING_ENVELOPE_KEYS = frozenset(
    {"schema_version", "model_name", "step", "contract", "model", "optimizer"}
)
INFERENCE_ENVELOPE_KEYS = TRAINING_ENVELOPE_KEYS - {"optimizer"}
ACCEPTED_ENVELOPE_KEY_SETS = (INFERENCE_ENVELOPE_KEYS, TRAINING_ENVELOPE_KEYS)
HISTORICAL_CORE_700M_INFERENCE_SCHEMA = "core-700m-inference-checkpoint.v1"


def checkpoint_schema(model_name: str) -> str:
    """Return the schema identifier written by training for one candidate."""

    return f"{model_name.lower()}-checkpoint.v1"


def allowed_checkpoint_schemas(model_name: str) -> frozenset[str]:
    """Return the exact checkpoint envelopes accepted for one CORE candidate.

    Checkpoint provenance is model-specific: accepting a generic ``core-*``
    schema would make it possible to load weights produced for a different
    candidate.  The historical inference envelope is a CORE-700M-only format.
    """

    schemas = {checkpoint_schema(model_name)}
    if model_name == "CORE-700M":
        schemas.add(HISTORICAL_CORE_700M_INFERENCE_SCHEMA)
    return frozenset(schemas)


def build_training_envelope(
    *,
    model_name: str,
    step: int,
    contract: dict[str, Any],
    model_state: dict[str, Any],
    optimizer_state: dict[str, Any],
) -> dict[str, Any]:
    """Return the envelope that training saves and inference accepts."""

    return {
        "schema_version": checkpoint_schema(model_name),
        "model_name": model_name,
        "step": step,
        "contract": contract,
        "model": model_state,
        "optimizer": optimizer_state,
    }
