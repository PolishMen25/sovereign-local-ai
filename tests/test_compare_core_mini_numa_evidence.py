import json
from pathlib import Path
import unittest

from tests._temp_support import sovereign_temporary_directory
from tools import compare_core_mini_numa_evidence as comparison
from tools import core_mini_numa_benchmark as benchmark


def evidence(label: str, proof_id: str, median: float) -> dict:
    workload = {
        "model_name": "CORE-MINI-1M", "data_mode": "synthetic", "repetitions": 3,
        "source_revision": "a" * 40, "source_archive_sha256": "1" * 64,
        "source_tree_manifest_sha256": "2" * 64, "offline_runtime_lock_sha256": "3" * 64,
        "numpy_runtime_lock_sha256": "4" * 64, "runtime_observation_sha256": "5" * 64,
        "environment_contract_sha256": "6" * 64, "model_config_sha256": "7" * 64,
        "steps": 8, "warmup_steps": 2, "batch_size": 2, "sequence_length": 32,
        "learning_rate": 0.0003, "seed": 20260831, "threads": 12,
    }
    return {
        "schema_version": "0.2.0", "artifact_type": "single-placement-run-proof",
        "proof_id": proof_id, "created_at_utc": "2026-09-06T18:00:00Z",
        "benchmark_session_id": "session-12345678-1234-4234-8234-123456789abc",
        "canonicalization": "canonical-json-v1",
        "placement": {"label": label, "application": "external", "contract_commitment_sha256": "8" * 64, "verification": "current-process-matched-private-contract"},
        "workload": workload,
        "workload_contract_sha256": __import__("hashlib").sha256(benchmark._canonical_json_bytes(workload)).hexdigest(),
        "repetitions": [
            {
                "repetition_id": index, "status": "completed",
                "metrics_sha256": str(index) * 64,
                "summary_sha256": str(index + 3) * 64,
                "verification_sha256": str(index + 4) * 64,
                "checkpoint_sha256": str(index + 6) * 64,
                "steps_total": 8, "steps_measured": 6, "tokens_measured": 384,
                "timing_seconds": {}, "tokens_per_second": median,
            }
            for index in range(1, 4)
        ],
        "aggregate": {"repetitions_completed": 3, "tokens_per_second": {"mean": median, "median": median, "minimum": median, "maximum": median, "population_standard_deviation": 0.0, "median_absolute_deviation": 0.0}},
        "evidence_scope": "repeated-single-placement-only",
    }


class ComparisonTests(unittest.TestCase):
    def _write(self, path: Path, document: dict) -> None:
        path.write_bytes(benchmark._canonical_json_bytes(document) + b"\n")

    def test_compares_closed_same_workload_proofs(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            a, b = root / "a.json", root / "b.json"
            self._write(a, evidence("placement-a", "proof-12345678-1234-4234-8234-123456789abc", 2000.0))
            self._write(b, evidence("placement-b", "proof-87654321-4321-4321-8321-cba987654321", 1900.0))
            result = comparison.compare(a, b)
            self.assertEqual(result["interpretation"], "descriptive-only-not-a-core-placement-decision")
            self.assertAlmostEqual(result["median_tokens_per_second_ratio_a_over_b"], 2000.0 / 1900.0)

    def test_refuses_session_or_workload_drift(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            a, b = root / "a.json", root / "b.json"
            self._write(a, evidence("placement-a", "proof-12345678-1234-4234-8234-123456789abc", 2000.0))
            changed = evidence("placement-b", "proof-87654321-4321-4321-8321-cba987654321", 1900.0)
            changed["workload"]["threads"] = 11
            self._write(b, changed)
            with self.assertRaises(benchmark.BenchmarkRefused):
                comparison.compare(a, b)

    def test_cli_refuses_without_echoing_private_path(self) -> None:
        self.assertEqual(comparison.main(["--placement-a", "private-marker"]), 1)


if __name__ == "__main__":
    unittest.main()
