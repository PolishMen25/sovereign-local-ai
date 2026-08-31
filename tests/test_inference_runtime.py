from pathlib import Path
import unittest

from services.inference.runtime import InferenceUnavailable, LocalInferenceRuntime


class InferenceRuntimeTests(unittest.TestCase):
    def test_missing_weights_fail_closed_and_report_cpu_only(self) -> None:
        runtime = LocalInferenceRuntime("CORE-80M", Path("does-not-exist.weights"))
        self.assertEqual(runtime.status().state, "awaiting_local_weights")
        self.assertEqual(runtime.status().backend, "cpu_only")
        self.assertFalse(runtime.status().generation_available)
        with self.assertRaises(InferenceUnavailable):
            runtime.generate("bonjour")

    def test_existing_placeholder_still_requires_phase_gate(self) -> None:
        weights = Path(__file__).parent / "placeholder.weights"
        try:
            weights.write_bytes(b"fixture")
            runtime = LocalInferenceRuntime("CORE-80M", weights)
            self.assertTrue(runtime.status().weights_present)
            self.assertEqual(
                runtime.status().state, "weights_detected_runtime_disabled"
            )
            self.assertFalse(runtime.status().generation_available)
            with self.assertRaises(InferenceUnavailable):
                runtime.generate("test", max_new_tokens=4)
        finally:
            weights.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
