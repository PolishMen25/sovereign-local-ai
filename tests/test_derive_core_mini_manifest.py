import copy
import unittest

from tools.derive_core_mini_manifest import CORE_MINI_VOCABULARY_SIZE, derive


def manifest() -> dict:
    return {
        "schema_version": "0.2.0", "corpus_id": "corpus-core-source", "lifecycle_state": "VALIDATED", "classification": "approved_training",
        "materialization": {"format": "jsonl-utf8", "content_sha256": "a" * 64, "byte_size": 3, "record_count": 3},
        "source_packages": [
            {"package_id": "package-train", "provenance_id": "provenance-train", "content_sha256": "b" * 64, "license": "MIT", "languages": ["en"], "review_state": "approved"},
            {"package_id": "package-validation", "provenance_id": "provenance-validation", "content_sha256": "c" * 64, "license": "MIT", "languages": ["en"], "review_state": "approved"},
            {"package_id": "package-test", "provenance_id": "provenance-test", "content_sha256": "d" * 64, "license": "MIT", "languages": ["en"], "review_state": "approved"},
        ],
        "splits": {
            "train": {"package_ids": ["package-train"], "content_sha256": "e" * 64, "byte_size": 1, "record_count": 1},
            "validation": {"package_ids": ["package-validation"], "content_sha256": "f" * 64, "byte_size": 1, "record_count": 1},
            "test": {"package_ids": ["package-test"], "content_sha256": "0" * 64, "byte_size": 1, "record_count": 1},
        },
        "tokenizer_contract": {"input_encoding": "utf-8", "normalization_policy_id": "unicode-nfc-v1", "candidate_vocabulary_size": 32000, "review_state": "approved"},
        "approvals": {"data_governance": "approved", "training_authorization": "approved"},
    }


class DeriveCoreMiniManifestTests(unittest.TestCase):
    def test_derives_distinct_id_and_mini_vocabulary_without_mutating_source(self) -> None:
        source = manifest()
        original = copy.deepcopy(source)
        result = derive(source, corpus_id="corpus-core-source-mini")
        self.assertEqual(result["corpus_id"], "corpus-core-source-mini")
        self.assertEqual(result["tokenizer_contract"]["candidate_vocabulary_size"], CORE_MINI_VOCABULARY_SIZE)
        self.assertEqual(source, original)
