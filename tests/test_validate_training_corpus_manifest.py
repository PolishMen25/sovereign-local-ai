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
        "schema_version": "0.1.0",
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
            "train": {"package_ids": ["package-train"], "content_sha256": digest("e"), "record_count": 1},
            "validation": {"package_ids": ["package-validation"], "content_sha256": digest("f"), "record_count": 1},
            "test": {"package_ids": ["package-test"], "content_sha256": digest("0"), "record_count": 1},
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
