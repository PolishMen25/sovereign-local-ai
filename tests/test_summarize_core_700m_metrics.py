import unittest

from tools.summarize_core_700m_metrics import summarize


class Core700MetricsSummaryTests(unittest.TestCase):
    def test_timed_records_produce_throughput(self) -> None:
        result = summarize([
            {"schema_version": "core-700m-metric.v1", "step": 1, "loss": 3.0, "tokens": 64, "elapsed_seconds": 2.0},
            {"schema_version": "core-700m-metric.v1", "step": 2, "loss": 2.0, "tokens": 64, "elapsed_seconds": 4.0},
        ])
        self.assertEqual(2, result["steps"])
        self.assertEqual(32.0, result["measured_tokens_per_second"])

    def test_untimed_history_is_explicitly_not_a_benchmark(self) -> None:
        result = summarize([{"schema_version": "core-700m-metric.v1", "step": 1, "loss": 3.0, "tokens": 64}])
        self.assertEqual(0, result["timed_steps"])
        self.assertNotIn("measured_tokens_per_second", result)
