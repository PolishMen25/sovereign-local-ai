import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "validate_training_corpus_manifest.py"
SPEC = importlib.util.spec_from_file_location("validate_training_corpus_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def digest(value: str) -> str:
    return value * 64


def valid_manifest() -> dict:
    return {
        "schema_version": "0.2.0",
        "corpus_id": "corpus-synthetic-gate",
        "lifecycle_state": "VALIDATED",
        "classification": "synthetic",
        "materialization": {"format": "jsonl-utf8", "content_sha256": digest("a"), "byte_size": 100, "record_count": 3},
        "source_packages": [
            {"package_id": "package-train", "provenance_id": "provenance-train", "content_sha256": digest("b"), "license": "LicenseRef-Synthetic", "languages": ["fr"], "review_state": "approved"},
            {"package_id": "package-validation", "provenance_id": "provenance-validation", "content_sha256": digest("c"), "license": "LicenseRef-Synthetic", "languages": ["fr"], "review_state": "approved"},
            {"package_id": "package-test", "provenance_id": "provenance-test", "content_sha256": digest("d"), "license": "LicenseRef-Synthetic", "languages": ["fr"], "review_state": "approved"},
        ],
        "splits": {
            "train": {"package_ids": ["package-train"], "content_sha256": digest("e"), "byte_size": 30, "record_count": 1},
            "validation": {"package_ids": ["package-validation"], "content_sha256": digest("f"), "byte_size": 30, "record_count": 1},
            "test": {"package_ids": ["package-test"], "content_sha256": digest("0"), "byte_size": 40, "record_count": 1},
        },
        "tokenizer_contract": {"input_encoding": "utf-8", "normalization_policy_id": "unicode-nfc-v1", "candidate_vocabulary_size": 32000, "review_state": "pending"},
        "approvals": {"data_governance": "pending", "training_authorization": "not_approved"},
    }


class TrainingCorpusManifestTests(unittest.TestCase):
    def test_synthetic_gate_manifest_is_structurally_accepted(self) -> None:
        MODULE.validate(valid_manifest())

    def test_synthetic_manifest_never_passes_linguistic_training_gate(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate(valid_manifest(), require_training_authorization=True)

    def test_raw_source_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["lifecycle_state"] = "RAW"
        with self.assertRaises(ValueError):
            MODULE.validate(manifest)

    def test_source_split_leakage_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["splits"]["test"]["package_ids"] = ["package-train"]
        with self.assertRaises(ValueError):
            MODULE.validate(manifest)

    def test_each_split_requires_a_byte_size(self) -> None:
        manifest = valid_manifest()
        del manifest["splits"]["train"]["byte_size"]
        with self.assertRaisesRegex(ValueError, "keys"):
            MODULE.validate(manifest)

    def test_split_hashes_must_be_distinct_from_each_other_and_global(self) -> None:
        duplicate_split = valid_manifest()
        duplicate_split["splits"]["test"]["content_sha256"] = duplicate_split["splits"]["train"]["content_sha256"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            MODULE.validate(duplicate_split)

        duplicate_global = valid_manifest()
        duplicate_global["materialization"]["content_sha256"] = duplicate_global["splits"]["train"]["content_sha256"]
        with self.assertRaisesRegex(ValueError, "global"):
            MODULE.validate(duplicate_global)

    def test_boolean_sizes_counts_and_vocabulary_are_rejected(self) -> None:
        for mutate in (
            lambda doc: doc["materialization"].__setitem__("byte_size", True),
            lambda doc: doc["splits"]["train"].__setitem__("byte_size", True),
            lambda doc: doc["splits"]["train"].__setitem__("record_count", True),
            lambda doc: doc["tokenizer_contract"].__setitem__("candidate_vocabulary_size", True),
        ):
            manifest = valid_manifest()
            mutate(manifest)
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                MODULE.validate(manifest)

    def test_global_record_count_must_equal_split_total(self) -> None:
        manifest = valid_manifest()
        manifest["materialization"]["record_count"] = 4
        with self.assertRaisesRegex(ValueError, "split total"):
            MODULE.validate(manifest)

    def test_sensitive_location_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["materialization"]["path"] = "/internal/corpus.jsonl"
        with self.assertRaises(ValueError):
            MODULE.validate(manifest)

    def test_approved_linguistic_manifest_can_pass_explicit_gate(self) -> None:
        manifest = valid_manifest()
        manifest["classification"] = "approved_training"
        manifest["tokenizer_contract"]["review_state"] = "approved"
        manifest["approvals"] = {"data_governance": "approved", "training_authorization": "approved"}
        MODULE.validate(manifest, require_training_authorization=True)


if __name__ == "__main__":
    unittest.main()
