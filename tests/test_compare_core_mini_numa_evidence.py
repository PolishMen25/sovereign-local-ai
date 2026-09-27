import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import statistics
import unittest
from unittest.mock import patch

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
        self.assertEqual(result["schema_version"], "core-mini-numa-comparison.v2")
        self.assertEqual(result["evidence_schema_version"], "0.2.0")
        self.assertEqual(result["interpretation"], "descriptive-only-not-a-core-placement-decision")
        self.assertEqual(result["gate_status"], "g4-open")
        placement_a = result["placements"]["placement-a"]
        self.assertEqual(placement_a["proof_id"], PROOF_A)
        self.assertEqual(placement_a["contract_commitment_sha256"], COMMITMENT_A)
        self.assertEqual(
            placement_a["proof_file_sha256"],
            hashlib.sha256(encode(evidence_a())).hexdigest(),
        )
        self.assertEqual(placement_a["tokens_per_second"], distribution(SAMPLES_A))
        self.assertEqual(
            result["placements"]["placement-b"]["tokens_per_second"],
            distribution(SAMPLES_B),
        )
        # Hashes only: threads and the other workload parameters stay bound
        # through workload_contract_sha256 and are never echoed (D-025).
        self.assertEqual(
            result["shared_contract"],
            {"workload_contract_sha256": evidence_a()["workload_contract_sha256"]}
            | {key: workload()[key] for key in comparison.WORKLOAD_DIGEST_KEYS},
        )
        self.assertTrue(all(key.endswith("_sha256") for key in result["shared_contract"]))
        ratios = result["descriptive_ratios"]
        self.assertEqual(ratios["median_b_over_a"], 1850.0 / 2000.0)
        self.assertEqual(ratios["mean_b_over_a"], statistics.fmean(SAMPLES_B) / statistics.fmean(SAMPLES_A))
        self.assertEqual(ratios["minimum_b_over_a"], 1800.0 / 1900.0)
        self.assertEqual(ratios["maximum_b_over_a"], 1950.0 / 2100.0)

    def test_refuses_session_or_workload_drift_and_names_the_field(self) -> None:
        session = evidence_b()
        session["benchmark_session_id"] = "session-99999999-8888-4777-b666-555555555555"
        threads = evidence_b()
        threads["workload"]["threads"] = 11
        rehash_workload(threads)
        numpy_lock = evidence_b()
        numpy_lock["workload"]["numpy_runtime_lock_sha256"] = "e" * 64
        rehash_workload(numpy_lock)
        cases = (
            ("benchmark_session_id", session),
            ("workload field: threads", threads),
            ("workload field: numpy_runtime_lock_sha256", numpy_lock),
        )
        for fragment, drifted in cases:
            with self.subTest(drift=fragment):
                self.assertRefused(evidence_a(), drifted, fragment)

    def test_refuses_labels_out_of_order(self) -> None:
        swapped_a = evidence("placement-b", PROOF_A, SAMPLES_A, commitment=COMMITMENT_A)
        swapped_b = evidence("placement-a", PROOF_B, SAMPLES_B, commitment=COMMITMENT_B)
        self.assertRefused(swapped_a, swapped_b, "placement-a then placement-b")
        self.assertRefused(evidence_a(), evidence_a() | {"proof_id": PROOF_B}, "placement-a then placement-b")

    def test_refuses_workload_values_outside_the_evidence_contract(self) -> None:
        cases = {
            "model_name": "/private/model",
            "data_mode": "pilote",
            "source_revision": "A" * 40,
            "numpy_runtime_lock_sha256": "not-a-digest",
            "threads": True,
            "batch_size": 65,
            "warmup_steps": 6,
            "learning_rate": 3,
            "seed": 2**63,
        }
        for key, value in cases.items():
            with self.subTest(field=key):
                # Both sides carry the same malformed value, so this is not drift:
                # the value itself must never reach the public artifact.
                pair = []
                for document in (evidence_a(), evidence_b()):
                    document["workload"][key] = value
                    rehash_workload(document)
                    pair.append(document)
                self.assertRefused(pair[0], pair[1], f"workload field is incompatible: {key}")

    def test_refuses_a_non_integer_repetition_count(self) -> None:
        document = evidence_a()
        document["aggregate"]["repetitions_completed"] = 3.0
        self.assertRefused(document, evidence_b(), "incompatible")

    def test_refuses_a_non_finite_descriptive_ratio(self) -> None:
        self.assertRefused(
            evidence_a([1e-300, 1e-300, 1e-300]),
            evidence_b([1e300, 1e300, 1e300]),
            "ratio",
        )

    def test_samples_near_the_float_maximum_are_refused_not_raised(self) -> None:
        # Finite samples near the float maximum overflow fmean's exact sum.
        # The placement verifier calls the comparator as a library and must
        # receive a refusal, never an OverflowError.
        document = evidence_a()
        for run in document["repetitions"]:
            run["tokens_per_second"] = 1.7e308
        document["aggregate"]["tokens_per_second"] = {
            "mean": 1.7e308, "median": 1.7e308, "minimum": 1.7e308,
            "maximum": 1.7e308, "population_standard_deviation": 0.0,
            "median_absolute_deviation": 0.0,
        }
        self.assertRefused(document, evidence_b(), "NUMA aggregate is incompatible")

    def test_refuses_repetition_fields_outside_the_evidence_contract(self) -> None:
        def timing(**changes) -> dict:
            return repetition(1, 1800.0)["timing_seconds"] | changes

        cases = {
            "boolean repetition id": ({"repetition_id": True}, "repetitions are incompatible"),
            "path as metrics digest": ({"metrics_sha256": "/private/path"}, "repetition is incompatible"),
            "uppercase checkpoint digest": ({"checkpoint_sha256": "A" * 64}, "repetition is incompatible"),
            "steps_total off the workload": ({"steps_total": 9}, "counts"),
            "float steps_measured": ({"steps_measured": 6.0}, "counts"),
            "boolean steps_measured": ({"steps_measured": True}, "counts"),
            "tokens_measured off the workload": ({"tokens_measured": 385}, "counts"),
            "free-form timing": ({"timing_seconds": {"note": "/private/path"}}, "timing"),
            "negative timing": ({"timing_seconds": timing(total=-1.0)}, "timing"),
            "integer timing": ({"timing_seconds": timing(total=2)}, "timing"),
            "negative dispersion": (
                {"timing_seconds": timing(median_absolute_deviation=-0.01)}, "timing",
            ),
        }
        for name, (changes, fragment) in cases.items():
            with self.subTest(case=name):
                document = evidence_b()
                document["repetitions"][0].update(changes)
                self.assertRefused(evidence_a(), document, fragment)

    def test_refuses_a_directory_or_a_symbolic_link_as_proof(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            path_a, path_b = self._pair(root, evidence_a(), evidence_b())
            with self.assertRaises(benchmark.BenchmarkRefused) as caught:
                comparison.compare(root, path_b)
            self.assertIn("not a link", str(caught.exception))
            link = root / "link.json"
            try:
                os.symlink(path_a, link)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable on this platform")
            with self.assertRaises(benchmark.BenchmarkRefused) as caught:
                comparison.compare(link, path_b)
        self.assertIn("not a link", str(caught.exception))

    def test_refuses_a_link_where_links_cannot_be_created(self) -> None:
        # Windows has no O_NOFOLLOW and test hosts often lack the symlink
        # privilege: simulate what lstat reports for a link on each side.
        real_lstat = os.lstat
        for side in (0, 1):
            with self.subTest(side=side), sovereign_temporary_directory() as directory:
                paths = self._pair(Path(directory), evidence_a(), evidence_b())
                target = paths[side]

                def fake_lstat(path, *args, **kwargs):
                    result = real_lstat(path, *args, **kwargs)
                    if Path(path) == target:
                        fields = list(result)
                        fields[stat.ST_MODE] = stat.S_IFLNK | 0o777
                        return os.stat_result(fields)
                    return result

                with patch.object(comparison.os, "lstat", fake_lstat):
                    with self.assertRaises(benchmark.BenchmarkRefused) as caught:
                        comparison.compare(*paths)
                self.assertIn("not a link", str(caught.exception))

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
            check_against_schema(json.loads(written), load_comparison_schema())
            again = run_cli(argv)
            self.assertEqual(again, (1, b"", REFUSAL_LINE))
            self.assertEqual(output.read_bytes(), written)


def compare_documents(a: dict, b: dict) -> dict:
    with sovereign_temporary_directory() as directory:
        root = Path(directory)
        path_a, path_b = root / "a.json", root / "b.json"
        path_a.write_bytes(encode(a))
        path_b.write_bytes(encode(b))
        return comparison.compare(path_a, path_b)


class SeparationTests(unittest.TestCase):
    def test_overlapping_observed_ranges_are_inconclusive(self) -> None:
        result = compare_documents(evidence_a(), evidence_b())
        self.assertEqual(
            result["separation"],
            {
                "observed_ranges_overlap": True,
                "outcome": "inconclusive-overlapping-observed-ranges",
                "higher_median_label": "placement-a",
            },
        )

    def test_touching_observed_ranges_still_overlap(self) -> None:
        # The observed ranges are closed intervals: a shared endpoint overlaps.
        for samples_b in ([2100.0, 2200.0, 2300.0], [1700.0, 1800.0, 1900.0]):
            with self.subTest(samples_b=samples_b):
                result = compare_documents(evidence_a(), evidence_b(samples_b))
                self.assertTrue(result["separation"]["observed_ranges_overlap"])
                self.assertEqual(
                    result["separation"]["outcome"],
                    "inconclusive-overlapping-observed-ranges",
                )

    def test_disjoint_observed_ranges_are_described_without_a_winner(self) -> None:
        for samples_b, higher in (
            ([1500.0, 1550.0, 1600.0], "placement-a"),
            ([2500.0, 2600.0, 2700.0], "placement-b"),
        ):
            with self.subTest(higher=higher):
                result = compare_documents(evidence_a(), evidence_b(samples_b))
                self.assertEqual(
                    result["separation"],
                    {
                        "observed_ranges_overlap": False,
                        "outcome": "disjoint-observed-ranges",
                        "higher_median_label": higher,
                    },
                )
                self.assertEqual(result["gate_status"], "g4-open")

    def test_equal_medians_are_tied(self) -> None:
        result = compare_documents(evidence_a(), evidence_b([1950.0, 2000.0, 2050.0]))
        self.assertEqual(result["separation"]["higher_median_label"], "tied")
        self.assertEqual(result["descriptive_ratios"]["median_b_over_a"], 1.0)

    def test_v2_median_ratio_is_the_inverse_of_the_v1_orientation(self) -> None:
        result = compare_documents(evidence_a(), evidence_b())
        medians = {
            label: summary["tokens_per_second"]["median"]
            for label, summary in result["placements"].items()
        }
        v1_ratio_a_over_b = medians["placement-a"] / medians["placement-b"]
        self.assertAlmostEqual(
            result["descriptive_ratios"]["median_b_over_a"], 1.0 / v1_ratio_a_over_b
        )

    def test_output_is_deterministic_and_carries_no_path_host_or_socket_claim(self) -> None:
        first = benchmark._canonical_json_bytes(compare_documents(evidence_a(), evidence_b()))
        second = benchmark._canonical_json_bytes(compare_documents(evidence_a(), evidence_b()))
        self.assertEqual(first, second)
        rendered = first.decode("utf-8").lower()
        for forbidden in (
            "/", "\\", "host", "socket", "cpu", "node", "affinity", "winner",
            "faster", "recommend", "created_at", "threads",
        ):
            self.assertNotIn(forbidden, rendered)


SCHEMA_ROOT = Path(__file__).parents[1] / "schemas"
ANNOTATION_KEYWORDS = {"$schema", "$id", "title", "description", "$defs"}
SUPPORTED_KEYWORDS = ANNOTATION_KEYWORDS | {
    "$ref", "type", "const", "enum", "pattern", "minimum", "maximum",
    "exclusiveMinimum", "properties", "required", "additionalProperties",
}


def load_comparison_schema() -> dict:
    return json.loads(
        (SCHEMA_ROOT / "core-mini-numa-comparison.schema.json").read_text(encoding="utf-8")
    )


def _same_json_value(left, right) -> bool:
    # const/enum equality, type-strict at every depth: True never matches 1,
    # even inside an object or array enum. Stricter than JSON Schema, which
    # holds 1 and 1.0 equal: this closed contract never needs that leniency.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_json_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json_value(item, other) for item, other in zip(left, right)
        )
    return left == right


def check_against_schema(instance, schema: dict, root: dict | None = None, where: str = "$") -> None:
    """Validate ``instance`` against the closed subset of Draft 2020-12 used here.

    The project ships no third-party dependency, so this stdlib checker covers
    exactly the keywords of the comparison schema. It refuses any other keyword
    rather than silently ignoring it, so the schema file is really exercised.
    """

    def fail(message: str) -> None:
        raise AssertionError(f"{where}: {message}")

    root = schema if root is None else root
    unsupported = set(schema) - SUPPORTED_KEYWORDS
    if unsupported:
        fail(f"unsupported schema keywords {sorted(unsupported)}")
    if "$ref" in schema:
        reference = schema["$ref"]
        if set(schema) != {"$ref"} or not reference.startswith("#/$defs/"):
            fail("only bare local $ref values are supported")
        check_against_schema(instance, root["$defs"][reference[len("#/$defs/"):]], root, where)
        return
    if "const" in schema and not _same_json_value(instance, schema["const"]):
        fail(f"expected const {schema['const']!r}")
    if "enum" in schema and not any(_same_json_value(instance, item) for item in schema["enum"]):
        fail(f"{instance!r} is not in enum")
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(instance, dict):
            fail("expected object")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            fail("every object in this contract must be closed")
        unknown = set(instance) - set(properties)
        if unknown:
            fail(f"unknown keys {sorted(unknown)}")
        missing = set(schema.get("required", [])) - set(instance)
        if missing:
            fail(f"missing required keys {sorted(missing)}")
        for key, value in instance.items():
            check_against_schema(value, properties[key], root, f"{where}.{key}")
    elif expected == "string":
        if not isinstance(instance, str):
            fail("expected string")
        pattern = schema.get("pattern")
        if pattern is not None:
            if not (pattern.startswith("^") and pattern.endswith("$")):
                fail("patterns must be anchored")
            # ECMA-262 '$' never matches before a trailing newline; fullmatch
            # on the unanchored body keeps that meaning in Python.
            if re.fullmatch(pattern[1:-1], instance) is None:
                fail(f"{instance!r} does not match {pattern}")
    elif expected == "integer":
        if type(instance) is not int:
            fail("expected integer")
    elif expected == "number":
        if type(instance) not in (int, float) or not math.isfinite(instance):
            fail("expected finite number")
    elif expected == "boolean":
        if type(instance) is not bool:
            fail("expected boolean")
    elif expected is not None:
        fail(f"unsupported type {expected!r}")
    numeric = type(instance) in (int, float)
    if "minimum" in schema and (not numeric or instance < schema["minimum"]):
        fail("below minimum")
    if "maximum" in schema and (not numeric or instance > schema["maximum"]):
        fail("above maximum")
    if "exclusiveMinimum" in schema and (not numeric or instance <= schema["exclusiveMinimum"]):
        fail("not above exclusiveMinimum")


class ComparisonSchemaTests(unittest.TestCase):
    def test_produced_artifacts_validate_against_the_schema_file(self) -> None:
        schema = load_comparison_schema()
        # Every admissible separation combination is produced once.
        for name, samples_b in (
            ("overlapping, higher a", SAMPLES_B),
            ("overlapping, higher b", [1950.0, 2050.0, 2150.0]),
            ("disjoint, higher a", [1500.0, 1550.0, 1600.0]),
            ("disjoint, higher b", [2500.0, 2600.0, 2700.0]),
            ("tied", [1950.0, 2000.0, 2050.0]),
        ):
            with self.subTest(fixture=name):
                result = compare_documents(evidence_a(), evidence_b(samples_b))
                check_against_schema(result, schema)
                self.assertEqual(set(result), set(schema["required"]))

    def test_schema_is_closed_and_every_property_is_required(self) -> None:
        schema = load_comparison_schema()

        def walk(node: dict, where: str) -> None:
            if node.get("type") == "object":
                self.assertIs(node.get("additionalProperties"), False, where)
                self.assertEqual(set(node["required"]), set(node["properties"]), where)
                for key, child in node["properties"].items():
                    walk(child, f"{where}.{key}")

        walk(schema, "$")
        for name, definition in schema["$defs"].items():
            walk(definition, f"$defs.{name}")

    def test_shared_definitions_track_the_evidence_contract(self) -> None:
        schema = load_comparison_schema()
        evidence_schema = json.loads(
            (SCHEMA_ROOT / "core-mini-numa-evidence.schema.json").read_text(encoding="utf-8")
        )
        for name in ("distribution", "sha256", "proofId", "sessionId"):
            with self.subTest(definition=name):
                self.assertEqual(schema["$defs"][name], evidence_schema["$defs"][name])
        # shared_contract echoes the workload digest plus the workload's own
        # digest fields, and nothing else from the workload.
        shared = schema["$defs"]["sharedContract"]
        self.assertEqual(
            set(shared["required"]),
            {"workload_contract_sha256", *comparison.WORKLOAD_DIGEST_KEYS},
        )
        evidence_workload = evidence_schema["$defs"]["workload"]["properties"]
        for key in comparison.WORKLOAD_DIGEST_KEYS:
            with self.subTest(digest=key):
                self.assertEqual(evidence_workload[key], {"$ref": "#/$defs/sha256"})
                self.assertEqual(shared["properties"][key], evidence_workload[key])
        self.assertEqual(
            {key for key, value in evidence_workload.items() if value == {"$ref": "#/$defs/sha256"}},
            set(comparison.WORKLOAD_DIGEST_KEYS),
        )
        self.assertNotIn("workload", schema["$defs"])
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            comparison.COMPARISON_SCHEMA_VERSION,
        )
        self.assertEqual(
            schema["properties"]["evidence_schema_version"]["const"],
            evidence_schema["properties"]["schema_version"]["const"],
        )

    def test_the_checker_rejects_contract_violations(self) -> None:
        schema = load_comparison_schema()
        valid = compare_documents(evidence_a(), evidence_b())
        check_against_schema(valid, schema)

        def mutated(change) -> dict:
            document = json.loads(json.dumps(valid))
            change(document)
            return document

        violations = {
            "unknown root key": lambda d: d.update(unexpected=True),
            "wrong version": lambda d: d.update(schema_version="core-mini-numa-comparison.v1"),
            "gate closed": lambda d: d.update(gate_status="g4-closed"),
            "missing ratio": lambda d: d["descriptive_ratios"].pop("median_b_over_a"),
            "winner label": lambda d: d["separation"].update(higher_median_label="winner"),
            "overlap claimed disjoint": lambda d: d["separation"].update(
                observed_ranges_overlap=True, outcome="disjoint-observed-ranges"
            ),
            "disjoint claimed inconclusive": lambda d: d["separation"].update(
                observed_ranges_overlap=False,
                outcome="inconclusive-overlapping-observed-ranges",
            ),
            "tied yet disjoint": lambda d: d["separation"].update(
                observed_ranges_overlap=False,
                outcome="disjoint-observed-ranges",
                higher_median_label="tied",
            ),
            "integer overlap flag": lambda d: d["separation"].update(observed_ranges_overlap=1),
            "path in proof id": lambda d: d["placements"]["placement-a"].update(proof_id="proof-/tmp/x"),
            "digest with newline": lambda d: d["shared_contract"].update(
                workload_contract_sha256="a" * 64 + "\n"
            ),
            "boolean repetitions": lambda d: d["placements"]["placement-b"].update(
                repetitions_completed=True
            ),
            "zero ratio": lambda d: d["descriptive_ratios"].update(mean_b_over_a=0.0),
            "socket claim": lambda d: d["placements"].update(socket_count=2),
            "echoed thread count": lambda d: d["shared_contract"].update(threads=12),
            "echoed workload object": lambda d: d["shared_contract"].update(workload={}),
            "missing numpy lock digest": lambda d: d["shared_contract"].pop(
                "numpy_runtime_lock_sha256"
            ),
        }
        for name, change in violations.items():
            with self.subTest(violation=name):
                with self.assertRaises(AssertionError):
                    check_against_schema(mutated(change), schema)
        with self.assertRaises(AssertionError):
            check_against_schema(valid, schema | {"minProperties": 1})

    def test_the_object_enum_alone_rejects_non_boolean_stand_ins(self) -> None:
        # Strip the per-property keywords so only the separation enum can
        # reject: an integer or float must never stand in for a boolean.
        separation = load_comparison_schema()["properties"]["separation"]
        enum_only = separation | {
            "properties": {key: {} for key in separation["properties"]}
        }
        valid = compare_documents(evidence_a(), evidence_b())["separation"]
        check_against_schema(valid, enum_only)
        for stand_in in (1, 1.0):
            with self.subTest(stand_in=stand_in):
                with self.assertRaises(AssertionError) as caught:
                    check_against_schema(valid | {"observed_ranges_overlap": stand_in}, enum_only)
                self.assertIn("not in enum", str(caught.exception))

    def test_json_value_equality_is_type_strict_at_every_depth(self) -> None:
        for left, right in (
            (True, 1), (1.0, 1), ({"x": True}, {"x": 1}), ({"x": 1.0}, {"x": 1}),
            ([True], [1]), ([True], [True, True]), ({"x": True}, {"x": True, "y": 1}),
            ({"x": {"y": False}}, {"x": {"y": 0}}),
        ):
            with self.subTest(left=left, right=right):
                self.assertFalse(_same_json_value(left, right))
                self.assertFalse(_same_json_value(right, left))
        for value in ("tied", True, {"x": [False, "a"]}, [{"x": 1}]):
            with self.subTest(value=value):
                self.assertTrue(_same_json_value(value, json.loads(json.dumps(value))))


if __name__ == "__main__":
    unittest.main()
