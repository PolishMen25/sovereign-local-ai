import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import unittest
import uuid

from services.inference.tokenizer import experimental_tokenizer_document, train_byte_bpe


MODULE_PATH = Path(__file__).parents[1] / "tools" / "promote_tokenizer_candidate.py"
SPEC = importlib.util.spec_from_file_location("promote_tokenizer_candidate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def record(record_id: str, text: str) -> bytes:
    return (json.dumps({"record_id": record_id, "text": text}, separators=(",", ":")) + "\n").encode()


class TokenizerCandidatePromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(__file__).parents[1] / f".tokenizer-promotion-{uuid.uuid4().hex}"
        self.directory.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.directory)

    def write_inputs(self) -> tuple[Path, Path, Path]:
        train = record("train-1", "Approved tokenizer source.")
        validation = record("validation-1", "Validation only.")
        test = record("test-1", "Test only.")
        result = train_byte_bpe(["Approved tokenizer source."], 264)
        tokenizer = experimental_tokenizer_document(
            training_corpus_id="corpus-approved-promotion",
            training_corpus_sha256=digest(train),
            result=result,
            minimum_frequency=2,
        )
        manifest = {
            "schema_version": "0.2.0", "corpus_id": "corpus-approved-promotion",
            "lifecycle_state": "VALIDATED", "classification": "approved_training",
            "materialization": {"format": "jsonl-utf8", "content_sha256": digest(train + validation + test), "byte_size": len(train + validation + test), "record_count": 3},
            "source_packages": [
                {"package_id": "package-train", "provenance_id": "provenance-train", "content_sha256": digest(train), "license": "MIT", "languages": ["en"], "review_state": "approved"},
                {"package_id": "package-validation", "provenance_id": "provenance-validation", "content_sha256": digest(validation), "license": "MIT", "languages": ["en"], "review_state": "approved"},
                {"package_id": "package-test", "provenance_id": "provenance-test", "content_sha256": digest(test), "license": "MIT", "languages": ["en"], "review_state": "approved"},
            ],
            "splits": {
                "train": {"package_ids": ["package-train"], "content_sha256": digest(train), "byte_size": len(train), "record_count": 1},
                "validation": {"package_ids": ["package-validation"], "content_sha256": digest(validation), "byte_size": len(validation), "record_count": 1},
                "test": {"package_ids": ["package-test"], "content_sha256": digest(test), "byte_size": len(test), "record_count": 1},
            },
            "tokenizer_contract": {"input_encoding": "utf-8", "normalization_policy_id": "unicode-nfc-v1", "candidate_vocabulary_size": result.vocabulary_size, "review_state": "approved"},
            "approvals": {"data_governance": "approved", "training_authorization": "approved"},
        }
        manifest_path, train_path, tokenizer_path = (self.directory / "manifest.json", self.directory / "train.jsonl", self.directory / "experimental.json")
        manifest_path.write_bytes(MODULE.canonical_json_bytes(manifest))
        train_path.write_bytes(train)
        tokenizer_path.write_bytes(MODULE.canonical_json_bytes(tokenizer))
        return manifest_path, train_path, tokenizer_path

    def test_promotion_writes_bound_candidate_and_receipt(self) -> None:
        manifest, train, source = self.write_inputs()
        candidate, receipt = self.directory / "candidate.json", self.directory / "receipt.json"
        result = MODULE.main(["--manifest", str(manifest), "--train-jsonl", str(train), "--input-tokenizer", str(source), "--output-tokenizer", str(candidate), "--receipt", str(receipt), "--approval-reference", "owner-approval-2026-09-07", "--approved-at", "2026-09-07"])
        self.assertEqual(result, 0)
        candidate_document = json.loads(candidate.read_text())
        receipt_document = json.loads(receipt.read_text())
        self.assertEqual(candidate_document["status"], "candidate_core")
        self.assertEqual(receipt_document["source_tokenizer_sha256"], digest(source.read_bytes()))
        self.assertEqual(receipt_document["candidate_tokenizer_sha256"], digest(candidate.read_bytes()))
        self.assertEqual(receipt_document["train_split_sha256"], digest(train.read_bytes()))

    def test_promotion_refuses_overwrite_and_bad_approval_reference(self) -> None:
        manifest, train, source = self.write_inputs()
        candidate, receipt = self.directory / "candidate.json", self.directory / "receipt.json"
        candidate.write_text("existing")
        with self.assertRaisesRegex(ValueError, "already exists"):
            MODULE.main(["--manifest", str(manifest), "--train-jsonl", str(train), "--input-tokenizer", str(source), "--output-tokenizer", str(candidate), "--receipt", str(receipt), "--approval-reference", "owner-approval", "--approved-at", "2026-09-07"])
