import json
import unittest
from unittest.mock import patch

from tools import cpu_benchmark


class CpuBenchmarkTests(unittest.TestCase):
    def test_round_is_deterministic_and_bounded(self) -> None:
        with patch.object(cpu_benchmark.time, "perf_counter", side_effect=[1.0, 1.25]):
            elapsed = cpu_benchmark.run_round(1000)
        self.assertEqual(elapsed, 0.25)

    def test_result_envelope_is_json_serializable(self) -> None:
        result = {
            "schema_version": "cpu-benchmark-result.v1",
            "workload": {"name": "sha256_chain", "iterations": 1000},
            "metadata": cpu_benchmark.metadata(),
            "timing_seconds": {"samples": [0.1], "median": 0.1},
        }
        self.assertEqual(json.loads(json.dumps(result))["schema_version"], "cpu-benchmark-result.v1")


if __name__ == "__main__":
    unittest.main()
