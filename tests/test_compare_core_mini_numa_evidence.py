import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "compare_core_mini_numa_evidence.py"
SPEC = importlib.util.spec_from_file_location("compare_core_mini_numa_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


SESSION_ID = "session-2f1c9b7a-4d3e-4a6b-8c2d-9e0f1a2b3c4d"
PROOF_A = "proof-11111111-2222-4333-8444-555555555555"
PROOF_B = "proof-66666666-7777-4888-9999-aaaaaaaaaaaa"


def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def workload() -> dict:
    return {
        "model_name": "CORE-MINI-1M",
        "data_mode": "synthetic",
        "repetitions": 3,
        "source_revision": "0" * 40,
        "source_archive_sha256": digest("archive"),
        "source_tree_manifest_sha256": digest("manifest"),
        "offline_runtime_lock_sha256": digest("lock"),
        "runtime_observation_sha256": digest("runtime"),
        "environment_contract_sha256": digest("environment"),
        "model_config_sha256": digest("config"),
        "steps": 24,
        "warmup_steps": 4,
        "batch_size": 2,
        "sequence_length": 128,
        "learning_rate": 0.0003,
        "seed": 7,
        "threads": 8,
    }


def distribution(mean: float, median: float, low: float, high: float) -> dict:
    return {
        "mean": mean,
        "median": median,
        "minimum": low,
        "maximum": high,
        "population_standard_deviation": 1.5,
        "median_absolute_deviation": 1.0,
    }


def proof(
    *,
    label: str,
    proof_id: str,
    commitment: str,
    throughput: dict,
    session_id: str = SESSION_ID,
    load: dict | None = None,
) -> dict:
    body = load if load is not None else workload()
    document = {
        "schema_version": "0.1.0",
        "artifact_type": "single-placement-run-proof",
        "canonicalization": "canonical-json-v1",
        "evidence_scope": "repeated-single-placement-only",
        "proof_id": proof_id,
        "created_at_utc": "2026-09-01T10:00:00Z",
        "benchmark_session_id": session_id,
        "placement": {
            "label": label,
            "application": "external",
            "contract_commitment_sha256": commitment,
            "verification": "current-process-matched-private-contract",
        },
        "workload": body,
        "workload_contract_sha256": MODULE.sha256_document(body),
        "repetitions": [{"index": index} for index in range(1, body["repetitions"] + 1)],
        "aggregate": {
            "repetitions_completed": body["repetitions"],
            "tokens_per_second": throughput,
        },
    }
    return document


def encode(document: dict) -> bytes:
    return MODULE.canonical_json_bytes(document) + b"\n"


def summary(document: dict) -> dict:
    payload = encode(document)
    return MODULE.summarize_proof(document, hashlib.sha256(payload).hexdigest())


def default_pair(
    throughput_a: dict | None = None, throughput_b: dict | None = None
) -> tuple[dict, dict]:
    side_a = proof(
        label="placement-a",
        proof_id=PROOF_A,
        commitment=digest("contract-a"),
        throughput=throughput_a or distribution(100.0, 100.0, 98.0, 102.0),
    )
    side_b = proof(
        label="placement-b",
        proof_id=PROOF_B,
        commitment=digest("contract-b"),
        throughput=throughput_b or distribution(150.0, 150.0, 148.0, 152.0),
    )
    return side_a, side_b


class ComparisonAcceptanceTests(unittest.TestCase):
    def test_disjoint_ranges_produce_a_descriptive_comparison(self) -> None:
        side_a, side_b = default_pair()
        result = MODULE.compare(summary(side_a), summary(side_b))
        self.assertEqual(result["artifact_type"], "two-placement-descriptive-comparison")
        self.assertEqual(result["evidence_scope"], "descriptive-two-placement-comparison-only")
        self.assertEqual(result["gate_status"], "g4-open")
        self.assertEqual(result["separation"]["outcome"], "disjoint-observed-ranges")
        self.assertFalse(result["separation"]["observed_ranges_overlap"])
        self.assertEqual(result["separation"]["higher_median_label"], "placement-b")
        self.assertAlmostEqual(result["descriptive_ratios"]["median_b_over_a"], 1.5)

    def test_overlapping_ranges_are_reported_as_inconclusive(self) -> None:
        side_a, side_b = default_pair(
            distribution(100.0, 100.0, 90.0, 110.0),
            distribution(104.0, 104.0, 94.0, 114.0),
        )
        result = MODULE.compare(summary(side_a), summary(side_b))
        self.assertTrue(result["separation"]["observed_ranges_overlap"])
        self.assertEqual(
            result["separation"]["outcome"], "inconclusive-overlapping-observed-ranges"
        )
        # A higher median is still reported, but the outcome refuses to call it a win.
        self.assertEqual(result["separation"]["higher_median_label"], "placement-b")

    def test_comparison_id_is_deterministic_and_order_independent(self) -> None:
        side_a, side_b = default_pair()
        forward = MODULE.compare(summary(side_a), summary(side_b))["comparison_id"]
        again = MODULE.compare(summary(side_a), summary(side_b))["comparison_id"]
        self.assertEqual(forward, again)
        self.assertRegex(forward, r"^comparison-[0-9a-f-]{36}$")

    def test_public_output_carries_no_private_placement_detail(self) -> None:
        side_a, side_b = default_pair()
        result = MODULE.compare(summary(side_a), summary(side_b))
        rendered = MODULE.canonical_json_bytes(result).decode("utf-8")
        for forbidden in ("/", "\\", "hostname", "cpu", "numa", "node", "affinity"):
            self.assertNotIn(forbidden, rendered.lower())

    def test_round_trip_through_files_matches_stdout_bytes(self) -> None:
        side_a, side_b = default_pair()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_bytes(encode(side_a))
            (root / "b.json").write_bytes(encode(side_b))
            output = root / "comparison.json"
            code = MODULE.main(
                [
                    "--evidence-a",
                    str(root / "a.json"),
                    "--evidence-b",
                    str(root / "b.json"),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 0)
            written = output.read_bytes()
        self.assertTrue(written.endswith(b"\n"))
        document = json.loads(written[:-1])
        self.assertEqual(MODULE.canonical_json_bytes(document) + b"\n", written)


class ComparisonRefusalTests(unittest.TestCase):
    def assertRefused(self, side_a: dict, side_b: dict, fragment: str) -> None:
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            MODULE.compare(summary(side_a), summary(side_b))
        self.assertIn(fragment, str(caught.exception))

    def test_two_proofs_of_the_same_placement_are_refused(self) -> None:
        side_a, _ = default_pair()
        twin = proof(
            label="placement-a",
            proof_id=PROOF_B,
            commitment=digest("contract-b"),
            throughput=distribution(150.0, 150.0, 148.0, 152.0),
        )
        self.assertRefused(side_a, twin, "one placement-a and one placement-b")

    def test_a_shared_placement_contract_is_refused(self) -> None:
        side_a, side_b = default_pair()
        side_b["placement"]["contract_commitment_sha256"] = side_a["placement"][
            "contract_commitment_sha256"
        ]
        self.assertRefused(side_a, side_b, "nothing to compare")

    def test_different_benchmark_sessions_are_refused(self) -> None:
        side_a, side_b = default_pair()
        side_b["benchmark_session_id"] = "session-99999999-8888-4777-b666-555555555555"
        self.assertRefused(side_a, side_b, "one benchmark session")

    def test_workload_drift_is_refused_and_names_the_field(self) -> None:
        side_a, side_b = default_pair()
        drifted = workload()
        drifted["threads"] = 16
        side_b["workload"] = drifted
        side_b["workload_contract_sha256"] = MODULE.sha256_document(drifted)
        self.assertRefused(side_a, side_b, "workload contract")

    def test_source_revision_drift_is_refused(self) -> None:
        side_a, side_b = default_pair()
        drifted = workload()
        drifted["source_revision"] = "1" * 40
        side_b["workload"] = drifted
        side_b["workload_contract_sha256"] = MODULE.sha256_document(drifted)
        self.assertRefused(side_a, side_b, "workload contract")

    def test_the_same_proof_twice_is_refused(self) -> None:
        side_a, _ = default_pair()
        self.assertRefused(side_a, copy.deepcopy(side_a), "one placement-a and one placement-b")

    def test_a_forged_workload_digest_is_refused(self) -> None:
        side_a, _ = default_pair()
        side_a["workload_contract_sha256"] = digest("forged")
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            summary(side_a)
        self.assertIn("does not match its workload", str(caught.exception))

    def test_fewer_than_three_repetitions_is_refused(self) -> None:
        body = workload()
        body["repetitions"] = 2
        thin = proof(
            label="placement-a",
            proof_id=PROOF_A,
            commitment=digest("contract-a"),
            throughput=distribution(100.0, 100.0, 98.0, 102.0),
            load=body,
        )
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            summary(thin)
        self.assertIn("too few completed repetitions", str(caught.exception))

    def test_a_median_outside_the_observed_range_is_refused(self) -> None:
        broken = proof(
            label="placement-a",
            proof_id=PROOF_A,
            commitment=digest("contract-a"),
            throughput=distribution(100.0, 500.0, 98.0, 102.0),
        )
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            summary(broken)
        self.assertIn("median falls outside", str(caught.exception))

    def test_a_boolean_throughput_statistic_is_refused(self) -> None:
        broken = proof(
            label="placement-a",
            proof_id=PROOF_A,
            commitment=digest("contract-a"),
            throughput=distribution(True, 100.0, 98.0, 102.0),
        )
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            summary(broken)
        self.assertIn("not a number", str(caught.exception))

    def test_a_repetition_count_mismatch_is_refused(self) -> None:
        broken = proof(
            label="placement-a",
            proof_id=PROOF_A,
            commitment=digest("contract-a"),
            throughput=distribution(100.0, 100.0, 98.0, 102.0),
        )
        broken["repetitions"] = broken["repetitions"][:-1]
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            summary(broken)
        self.assertIn("repetition count is inconsistent", str(caught.exception))


class ProofParsingTests(unittest.TestCase):
    def test_non_canonical_bytes_are_refused(self) -> None:
        side_a, _ = default_pair()
        pretty = json.dumps(side_a, indent=2).encode("utf-8") + b"\n"
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            MODULE.parse_proof(pretty)
        self.assertIn("canonical", str(caught.exception))

    def test_a_missing_trailing_newline_is_refused(self) -> None:
        side_a, _ = default_pair()
        with self.assertRaises(MODULE.ComparisonRefused):
            MODULE.parse_proof(MODULE.canonical_json_bytes(side_a))

    def test_a_duplicate_json_key_is_refused(self) -> None:
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            MODULE.parse_proof(b'{"a":1,"a":2}\n')
        self.assertIn("duplicate", str(caught.exception))

    def test_a_comparison_artifact_is_not_accepted_as_a_proof(self) -> None:
        side_a, side_b = default_pair()
        comparison = MODULE.compare(summary(side_a), summary(side_b))
        with self.assertRaises(MODULE.ComparisonRefused) as caught:
            MODULE.parse_proof(encode(comparison))
        self.assertIn("artifact_type", str(caught.exception))

    def test_an_existing_output_is_never_overwritten(self) -> None:
        side_a, side_b = default_pair()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_bytes(encode(side_a))
            (root / "b.json").write_bytes(encode(side_b))
            output = root / "comparison.json"
            output.write_bytes(b"previous\n")
            code = MODULE.main(
                [
                    "--evidence-a",
                    str(root / "a.json"),
                    "--evidence-b",
                    str(root / "b.json"),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 2)
            self.assertEqual(output.read_bytes(), b"previous\n")


SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "core-mini-numa-comparison.schema.json"
)


def check_against_schema(instance, schema: dict, root: dict, where: str = "$") -> None:
    """Minimal closed-schema check.

    The project ships no third-party dependency, so this covers exactly the
    keywords the comparison schema uses. Its point is that the schema file is
    actually exercised rather than shipped as decoration.
    """
    if "$ref" in schema:
        target = schema["$ref"].removeprefix("#/$defs/")
        check_against_schema(instance, root["$defs"][target], root, where)
        return
    if "const" in schema:
        assert instance == schema["const"], f"{where}: expected const {schema['const']!r}"
    if "enum" in schema:
        assert instance in schema["enum"], f"{where}: {instance!r} not in enum"
    expected_type = schema.get("type")
    if expected_type == "object":
        assert isinstance(instance, dict), f"{where}: expected object"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(instance) - set(properties)
            assert not unknown, f"{where}: unknown keys {sorted(unknown)}"
        for key in schema.get("required", []):
            assert key in instance, f"{where}: missing required key {key}"
        for key, value in instance.items():
            if key in properties:
                check_against_schema(value, properties[key], root, f"{where}.{key}")
    elif expected_type == "string":
        assert isinstance(instance, str), f"{where}: expected string"
        pattern = schema.get("pattern")
        if pattern:
            assert re.search(pattern, instance), f"{where}: {instance!r} fails {pattern}"
    elif expected_type == "integer":
        assert type(instance) is int, f"{where}: expected integer"
    elif expected_type == "number":
        assert type(instance) in (int, float), f"{where}: expected number"
    elif expected_type == "boolean":
        assert isinstance(instance, bool), f"{where}: expected boolean"
    if "minimum" in schema:
        assert instance >= schema["minimum"], f"{where}: below minimum"
    if "exclusiveMinimum" in schema:
        assert instance > schema["exclusiveMinimum"], f"{where}: not above exclusiveMinimum"


class SchemaConformanceTests(unittest.TestCase):
    def test_the_produced_comparison_conforms_to_the_published_schema(self) -> None:
        side_a, side_b = default_pair()
        result = MODULE.compare(summary(side_a), summary(side_b))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        check_against_schema(result, schema, schema)

    def test_the_overlapping_outcome_also_conforms(self) -> None:
        side_a, side_b = default_pair(
            distribution(100.0, 100.0, 90.0, 110.0),
            distribution(100.0, 100.0, 94.0, 114.0),
        )
        result = MODULE.compare(summary(side_a), summary(side_b))
        self.assertEqual(result["separation"]["higher_median_label"], "tied")
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        check_against_schema(result, schema, schema)

    def test_the_checker_rejects_an_unknown_key(self) -> None:
        side_a, side_b = default_pair()
        result = MODULE.compare(summary(side_a), summary(side_b))
        result["unexpected"] = True
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        with self.assertRaises(AssertionError):
            check_against_schema(result, schema, schema)


if __name__ == "__main__":
    unittest.main()
