import unittest

from tools.summarize_training_metrics import summarize


class TrainingMetricsSummaryTests(unittest.TestCase):
    def test_summarizes_post_warmup_steps(self) -> None:
        records = [
            {"step": 1, "loss": 4.0, "elapsed_seconds": 0.5, "tokens": 10},
            {"step": 2, "loss": 3.0, "elapsed_seconds": 0.8, "tokens": 10},
            {"step": 3, "loss": 2.0, "elapsed_seconds": 1.0, "tokens": 10},
        ]

        result = summarize(records, warmup_steps=1)

        self.assertEqual(result["steps_measured"], 2)
        self.assertEqual(result["tokens_measured"], 20)
        self.assertAlmostEqual(result["timing_seconds"]["median_step"], 0.25)
        self.assertAlmostEqual(result["tokens_per_second"], 40.0)

    def test_rejects_elapsed_reset_from_concatenated_runs(self) -> None:
        records = [
            {"step": 1, "loss": 4.0, "elapsed_seconds": 0.5, "tokens": 10},
            {"step": 2, "loss": 3.0, "elapsed_seconds": 0.1, "tokens": 10},
        ]

        with self.assertRaisesRegex(ValueError, "increase"):
            summarize(records, warmup_steps=0)

    def test_rejects_non_finite_loss(self) -> None:
        records = [
            {"step": 1, "loss": float("nan"), "elapsed_seconds": 0.5, "tokens": 10}
        ]

        with self.assertRaisesRegex(ValueError, "non-finite"):
            summarize(records, warmup_steps=0)


if __name__ == "__main__":
    unittest.main()
