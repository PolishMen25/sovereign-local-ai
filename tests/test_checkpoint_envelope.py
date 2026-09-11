import unittest

from services.inference.checkpoint_envelope import (
    INFERENCE_ENVELOPE_KEYS,
    TRAINING_ENVELOPE_KEYS,
    allowed_checkpoint_schemas,
    build_training_envelope,
    checkpoint_schema,
)
from services.inference.runtime import (
    InferenceUnavailable,
    is_collapsed_output,
    runtime_state,
    validate_inference_checkpoint,
)

EXPECTED = {
    "config_sha256": "c" * 64,
    "manifest_sha256": "m" * 64,
    "tokenizer_sha256": "t" * 64,
    "preflight_sha256": "p" * 64,
}
TRAINING_CONTRACT = {**EXPECTED, "train_split_sha256": "s" * 64, "batch_size": 1}


def training_envelope(model_name: str = "CORE-30M") -> dict:
    return build_training_envelope(
        model_name=model_name,
        step=10,
        contract=dict(TRAINING_CONTRACT),
        model_state={"w": 1},
        optimizer_state={"state": {}},
    )


class CheckpointEnvelopeTests(unittest.TestCase):
    def test_training_envelope_is_the_one_inference_accepts(self) -> None:
        envelope = training_envelope()
        self.assertEqual(set(envelope), TRAINING_ENVELOPE_KEYS)
        self.assertEqual(envelope["schema_version"], checkpoint_schema("CORE-30M"))
        self.assertIn(envelope["schema_version"], allowed_checkpoint_schemas("CORE-30M"))
        state = validate_inference_checkpoint(
            envelope, model_name="CORE-30M", expected_contract=EXPECTED
        )
        self.assertIs(state, envelope["model"])

    def test_inference_only_envelope_is_accepted(self) -> None:
        envelope = training_envelope()
        del envelope["optimizer"]
        self.assertEqual(set(envelope), INFERENCE_ENVELOPE_KEYS)
        validate_inference_checkpoint(envelope, model_name="CORE-30M", expected_contract=EXPECTED)

    def test_historical_700m_schema_only_for_700m(self) -> None:
        envelope = training_envelope("CORE-700M")
        envelope["schema_version"] = "core-700m-inference-checkpoint.v1"
        validate_inference_checkpoint(envelope, model_name="CORE-700M", expected_contract=EXPECTED)
        envelope["model_name"] = "CORE-30M"
        with self.assertRaisesRegex(InferenceUnavailable, "provenance"):
            validate_inference_checkpoint(envelope, model_name="CORE-30M", expected_contract=EXPECTED)

    def test_envelope_refusals(self) -> None:
        for broken in ("not a dict", {**training_envelope(), "extra": 1}, {"model": {}}):
            with self.assertRaisesRegex(InferenceUnavailable, "envelope is incompatible"):
                validate_inference_checkpoint(broken, model_name="CORE-30M", expected_contract=EXPECTED)

    def test_provenance_refusals(self) -> None:
        cases = {
            "schema of another candidate": ("schema_version", "core-700m-checkpoint.v1"),
            "other model name": ("model_name", "CORE-700M"),
            "contract not a dict": ("contract", ["c"]),
            "model not a dict": ("model", None),
        }
        for label, (key, value) in cases.items():
            envelope = training_envelope()
            envelope[key] = value
            with self.subTest(label), self.assertRaisesRegex(InferenceUnavailable, "provenance"):
                validate_inference_checkpoint(envelope, model_name="CORE-30M", expected_contract=EXPECTED)
        for key in EXPECTED:
            envelope = training_envelope()
            envelope["contract"][key] = "0" * 64
            with self.subTest(key), self.assertRaisesRegex(InferenceUnavailable, "provenance"):
                validate_inference_checkpoint(envelope, model_name="CORE-30M", expected_contract=EXPECTED)


class RuntimeHelpersTests(unittest.TestCase):
    def test_state_labels(self) -> None:
        self.assertEqual(runtime_state(ready=True, loaded=True, weights_present=True), "ready_experimental")
        self.assertEqual(runtime_state(ready=True, loaded=False, weights_present=True), "checkpoint_pending_validation")
        self.assertEqual(runtime_state(ready=False, loaded=False, weights_present=True), "weights_detected_runtime_disabled")
        self.assertEqual(runtime_state(ready=False, loaded=False, weights_present=False), "awaiting_local_weights")

    def test_quality_gate(self) -> None:
        self.assertTrue(is_collapsed_output("a" * 16))
        self.assertTrue(is_collapsed_output("ab" * 8))
        self.assertTrue(is_collapsed_output("abc" * 5 + "a"))
        self.assertTrue(is_collapsed_output("abcdefgh" * 4))
        self.assertFalse(is_collapsed_output("a" * 15))
        self.assertFalse(is_collapsed_output("abcdefg" * 4))  # period 7 is not checked
        self.assertFalse(is_collapsed_output("Bonjour, voici une vraie réponse."))


if __name__ == "__main__":
    unittest.main()
