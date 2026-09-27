import contextlib
import hashlib
import io
import json
from pathlib import Path
import statistics
import unittest

from tests._temp_support import sovereign_temporary_directory
from tools import compare_core_mini_numa_evidence as comparison
from tools import core_mini_numa_benchmark as benchmark


SESSION_ID = "session-12345678-1234-4234-8234-123456789abc"
PROOF_A = "proof-12345678-1234-4234-8234-123456789abc"
PROOF_B = "proof-87654321-4321-4321-8321-cba987654321"
# Salted commitments differ between runs, so each placement gets its own.
COMMITMENT_A = hashlib.sha256(b"synthetic-contract-a").hexdigest()
COMMITMENT_B = hashlib.sha256(b"synthetic-contract-b").hexdigest()
SAMPLES_A = [1900.0, 2000.0, 2100.0]
SAMPLES_B = [1800.0, 1850.0, 1950.0]
REFUSAL_LINE = "CORE-MINI NUMA comparison refused\n"


def workload(repetitions: int = 3) -> dict:
    return {
        "model_name": "CORE-MINI-1M", "data_mode": "synthetic", "repetitions": repetitions,
        "source_revision": "a" * 40, "source_archive_sha256": "1" * 64,
        "source_tree_manifest_sha256": "2" * 64, "offline_runtime_lock_sha256": "3" * 64,
        "numpy_runtime_lock_sha256": "4" * 64, "runtime_observation_sha256": "5" * 64,
        "environment_contract_sha256": "6" * 64, "model_config_sha256": "7" * 64,
        "steps": 8, "warmup_steps": 2, "batch_size": 2, "sequence_length": 32,
        "learning_rate": 0.0003, "seed": 20260831, "threads": 12,
    }


def distribution(samples: list[float]) -> dict:
    if not samples:
        return {
            "mean": 1.0, "median": 1.0, "minimum": 1.0, "maximum": 1.0,
            "population_standard_deviation": 0.0, "median_absolute_deviation": 0.0,
        }
    median = statistics.median(samples)
    return {
        "mean": statistics.fmean(samples),
        "median": median,
        "minimum": min(samples),
        "maximum": max(samples),
        "population_standard_deviation": statistics.pstdev(samples),
        "median_absolute_deviation": statistics.median(
            abs(value - median) for value in samples
        ),
    }


def repetition(index: int, throughput: float) -> dict:
    def digest(kind: str) -> str:
        return hashlib.sha256(f"{kind}-{index}".encode("ascii")).hexdigest()

    return {
        "repetition_id": index, "status": "completed",
        "metrics_sha256": digest("metrics"), "summary_sha256": digest("summary"),
        "verification_sha256": digest("verification"),
        "checkpoint_sha256": digest("checkpoint"),
        "steps_total": 8, "steps_measured": 6, "tokens_measured": 384,
        "timing_seconds": {
            "total": 2.0, "mean_step": 0.2, "median_step": 0.2, "minimum_step": 0.19,
            "maximum_step": 0.21, "population_standard_deviation": 0.01,
            "median_absolute_deviation": 0.01,
        },
        "tokens_per_second": throughput,
    }


def evidence(
    label: str, proof_id: str, samples: list[float], *, commitment: str
) -> dict:
    load = workload(len(samples))
    return {
        "schema_version": "0.2.0", "artifact_type": "single-placement-run-proof",
        "proof_id": proof_id, "created_at_utc": "2026-09-06T18:00:00Z",
        "benchmark_session_id": SESSION_ID,
        "canonicalization": "canonical-json-v1",
        "placement": {
            "label": label, "application": "external",
            "contract_commitment_sha256": commitment,
            "verification": "current-process-matched-private-contract",
        },
        "workload": load,
        "workload_contract_sha256": hashlib.sha256(
            benchmark._canonical_json_bytes(load)
        ).hexdigest(),
        "repetitions": [
            repetition(index, value) for index, value in enumerate(samples, 1)
        ],
        "aggregate": {
            "repetitions_completed": len(samples),
            "tokens_per_second": distribution(samples),
        },
        "evidence_scope": "repeated-single-placement-only",
    }


def evidence_a(samples: list[float] = SAMPLES_A) -> dict:
    return evidence("placement-a", PROOF_A, samples, commitment=COMMITMENT_A)


def evidence_b(samples: list[float] = SAMPLES_B) -> dict:
    return evidence("placement-b", PROOF_B, samples, commitment=COMMITMENT_B)


def rehash_workload(document: dict) -> None:
    document["workload_contract_sha256"] = hashlib.sha256(
        benchmark._canonical_json_bytes(document["workload"])
    ).hexdigest()


def encode(document: dict) -> bytes:
    return benchmark._canonical_json_bytes(document) + b"\n"


def run_cli(argv: list[str]) -> tuple[int, bytes, str]:
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = comparison.main(argv)
    stdout.flush()
    return code, stdout.buffer.getvalue(), stderr.getvalue()


class ComparisonTests(unittest.TestCase):
    def _pair(self, root: Path, a: dict, b: dict) -> tuple[Path, Path]:
        path_a, path_b = root / "a.json", root / "b.json"
        path_a.write_bytes(encode(a))
        path_b.write_bytes(encode(b))
        return path_a, path_b

    def assertRefused(self, a: dict, b: dict, fragment: str = "") -> None:
        with sovereign_temporary_directory() as directory:
            path_a, path_b = self._pair(Path(directory), a, b)
            with self.assertRaises(benchmark.BenchmarkRefused) as caught:
                comparison.compare(path_a, path_b)
        self.assertIn(fragment, str(caught.exception))

    def test_compares_closed_same_workload_proofs(self) -> None:
        with sovereign_temporary_directory() as directory:
            path_a, path_b = self._pair(Path(directory), evidence_a(), evidence_b())
            result = comparison.compare(path_a, path_b)
        self.assertEqual(result["schema_version"], "core-mini-numa-comparison.v1")
        self.assertEqual(result["interpretation"], "descriptive-only-not-a-core-placement-decision")
        self.assertEqual(
            result["evidence"]["placement_a"]["sha256"],
            hashlib.sha256(encode(evidence_a())).hexdigest(),
        )
        self.assertAlmostEqual(result["median_tokens_per_second_ratio_a_over_b"], 2000.0 / 1850.0)

    def test_refuses_session_or_workload_drift(self) -> None:
        session = evidence_b()
        session["benchmark_session_id"] = "session-99999999-8888-4777-b666-555555555555"
        threads = evidence_b()
        threads["workload"]["threads"] = 11
        rehash_workload(threads)
        for name, drifted in (("session", session), ("threads", threads)):
            with self.subTest(drift=name):
                self.assertRefused(evidence_a(), drifted, "not comparable")

    def test_refuses_a_forged_workload_digest(self) -> None:
        forged = evidence_b()
        forged["workload"]["threads"] = 11
        self.assertRefused(evidence_a(), forged, "workload digest")

    def test_refuses_a_shared_placement_commitment(self) -> None:
        shared = evidence_b()
        shared["placement"]["contract_commitment_sha256"] = COMMITMENT_A
        self.assertRefused(evidence_a(), shared, "share one placement contract")

    def test_refuses_repetition_counts_outside_the_protocol_bounds(self) -> None:
        for count in (0, 1, 2, 11):
            with self.subTest(repetitions=count):
                samples = [2000.0 + index for index in range(count)]
                self.assertRefused(evidence_a(samples), evidence_b(), "repetitions")

    def test_zero_repetitions_is_a_controlled_cli_refusal(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            path_a, path_b = self._pair(root, evidence_a([]), evidence_b())
            output = root / "comparison.json"
            code, stdout, stderr = run_cli([
                "--placement-a", str(path_a), "--placement-b", str(path_b),
                "--output", str(output),
            ])
            self.assertFalse(output.exists())
        self.assertEqual(code, 1)
        self.assertEqual(stdout, b"")
        self.assertEqual(stderr, REFUSAL_LINE)

    def test_refuses_non_canonical_bytes_and_line_endings(self) -> None:
        canonical = encode(evidence_a())
        variants = {
            "indented": json.dumps(evidence_a(), indent=2, sort_keys=True).encode("utf-8") + b"\n",
            "unsorted": json.dumps(evidence_a(), separators=(",", ":")).encode("utf-8") + b"\n",
            "missing-lf": canonical[:-1],
            "double-lf": canonical + b"\n",
            "crlf": canonical[:-1] + b"\r\n",
            "leading-space": b" " + canonical,
            "escaped-ascii": json.dumps(
                evidence_a(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).replace("CORE", "\\u0043ORE").encode("ascii") + b"\n",
        }
        for name, payload in variants.items():
            with self.subTest(variant=name):
                self.assertNotEqual(payload, canonical)
                with sovereign_temporary_directory() as directory:
                    root = Path(directory)
                    path_a, path_b = self._pair(root, evidence_a(), evidence_b())
                    path_a.write_bytes(payload)
                    with self.assertRaises(benchmark.BenchmarkRefused):
                        comparison.compare(path_a, path_b)

    def test_refuses_the_same_file_used_twice(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            path_a, _ = self._pair(root, evidence_a(), evidence_b())
            copy_a = root / "copy.json"
            copy_a.write_bytes(path_a.read_bytes())
            for second in (path_a, copy_a):
                with self.subTest(second=second.name):
                    with self.assertRaises(benchmark.BenchmarkRefused) as caught:
                        comparison.compare(path_a, second)
                    self.assertIn("two distinct proof files", str(caught.exception))

    def test_refuses_malformed_public_identifiers(self) -> None:
        def mutate(field: str, value: str) -> dict:
            document = evidence_b()
            if field == "contract_commitment_sha256":
                document["placement"][field] = value
            else:
                document[field] = value
            return document

        cases = {
            "path-like proof id": mutate("proof_id", "proof-../private/marker"),
            "uppercase session": mutate("benchmark_session_id", SESSION_ID.upper()),
            "short commitment": mutate("contract_commitment_sha256", "9" * 63),
            "uppercase commitment": mutate("contract_commitment_sha256", "A" * 64),
            "short workload digest": mutate("workload_contract_sha256", "0" * 32),
            "local timestamp": mutate("created_at_utc", "2026-09-06T18:00:00+02:00"),
        }
        for name, document in cases.items():
            with self.subTest(case=name):
                self.assertRefused(evidence_a(), document, "incompatible")

    def test_oversized_integer_or_deep_nesting_is_refused_without_traceback(self) -> None:
        payloads = {
            "oversized-integer": b'{"seed":' + b"7" * 5000 + b"}\n",
            "deep-nesting": b"[" * 100_000 + b"]" * 100_000 + b"\n",
        }
        for name, payload in payloads.items():
            with self.subTest(payload=name):
                with sovereign_temporary_directory() as directory:
                    root = Path(directory)
                    path_a, path_b = self._pair(root, evidence_a(), evidence_b())
                    path_a.write_bytes(payload)
                    with self.assertRaises(benchmark.BenchmarkRefused):
                        comparison.compare(path_a, path_b)
                    code, stdout, stderr = run_cli([
                        "--placement-a", str(path_a), "--placement-b", str(path_b),
                        "--output", str(root / "comparison.json"),
                    ])
                self.assertEqual((code, stdout, stderr), (1, b"", REFUSAL_LINE))

    def test_cli_refuses_without_echoing_private_path(self) -> None:
        marker = "private-marker-7f3a"
        code, stdout, stderr = run_cli(["--placement-a", marker])
        self.assertEqual((code, stdout), (1, b""))
        self.assertNotIn(marker, stderr)
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            _, path_b = self._pair(root, evidence_a(), evidence_b())
            code, stdout, stderr = run_cli([
                "--placement-a", str(root / marker), "--placement-b", str(path_b),
                "--output", str(root / "comparison.json"),
            ])
        self.assertEqual((code, stdout, stderr), (1, b"", REFUSAL_LINE))

    def test_cli_writes_the_stdout_bytes_once_and_never_overwrites(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            path_a, path_b = self._pair(root, evidence_a(), evidence_b())
            output = root / "comparison.json"
            argv = [
                "--placement-a", str(path_a), "--placement-b", str(path_b),
                "--output", str(output),
            ]
            code, stdout, stderr = run_cli(argv)
            self.assertEqual((code, stderr), (0, ""))
            written = output.read_bytes()
            self.assertEqual(written, stdout)
            self.assertEqual(
                benchmark._canonical_json_bytes(json.loads(written)) + b"\n", written
            )
            again = run_cli(argv)
            self.assertEqual(again, (1, b"", REFUSAL_LINE))
            self.assertEqual(output.read_bytes(), written)


if __name__ == "__main__":
    unittest.main()
