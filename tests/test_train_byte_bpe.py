import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "train_byte_bpe.py"
SPEC = importlib.util.spec_from_file_location("train_byte_bpe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def manifest(*, candidate_vocabulary_size: int = 270) -> dict:
    return {
        "corpus_id": "corpus-approved-example",
        "materialization": {"content_sha256": "a" * 64},
        "splits": {
            "train": {
                "content_sha256": "b" * 64,
                "byte_size": 123,
                "record_count": 2,
            }
        },
        "tokenizer_contract": {
            "input_encoding": "utf-8",
            "normalization_policy_id": "unicode-nfc-v1",
            "candidate_vocabulary_size": candidate_vocabulary_size,
        },
    }


class ByteBpeTrainingTests(unittest.TestCase):
    def test_corpus_limit_supports_the_verified_pilot_split_size(self) -> None:
        self.assertEqual(MODULE.MAXIMUM_CORPUS_BYTES, 512 * 1024 * 1024)

    def test_training_is_deterministic_and_keeps_exact_byte_coverage(self) -> None:
        first = MODULE.train(["bonjour bonjour", "bonjour monde"], 270)
        second = MODULE.train(["bonjour bonjour", "bonjour monde"], 270)

        self.assertEqual(first, second)
        self.assertEqual(first.tokens_hex[:256], tuple(f"{value:02x}" for value in range(256)))
        self.assertEqual(len(first.tokens_hex), len(set(first.tokens_hex)))
        self.assertEqual(len(first.merges), len(first.tokens_hex) - 256)
        self.assertGreater(first.vocabulary_size, 260)
        self.assertLessEqual(first.vocabulary_size, 270)

    def test_training_normalizes_nfc_before_learning_merges(self) -> None:
        decomposed = MODULE.train(["Cafe\u0301 Cafe\u0301"], 270)
        composed = MODULE.train(["Café Café"], 270)
        self.assertEqual(decomposed, composed)

    def test_too_small_or_boolean_vocabulary_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.train(["synthetic"], 259)
        with self.assertRaises(ValueError):
            MODULE.train(["synthetic"], True)
        with self.assertRaisesRegex(ValueError, "single string"):
            MODULE.train("synthetic", 270)

    def test_record_contract_rejects_extra_fields_and_duplicate_ids(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.collect_texts(
                b'{"record_id":"x","text":"a","source":"no"}\n', 1
            )
        with self.assertRaisesRegex(ValueError, "repeats"):
            MODULE.collect_texts(
                b'{"record_id":"x","text":"a"}\n'
                b'{"record_id":"x","text":"b"}\n',
                2,
            )

    def test_tokenizer_document_has_schema_02_lineage_and_no_text(self) -> None:
        result = MODULE.train(["Bonjour Bonjour"], 270)
        document = MODULE.tokenizer_document(
            manifest(candidate_vocabulary_size=result.vocabulary_size), result
        )

        self.assertEqual(document["schema_version"], "0.2.0")
        self.assertEqual(document["status"], "experimental")
        self.assertEqual(document["training_corpus_id"], "corpus-approved-example")
        self.assertEqual(document["training_corpus_sha256"], "b" * 64)
        self.assertEqual(document["special_tokens"], ["<pad>", "<bos>", "<eos>", "<unk>"])
        self.assertNotIn("text", document)

    def test_unsupported_manifest_normalization_is_refused(self) -> None:
        candidate = manifest()
        candidate["tokenizer_contract"]["normalization_policy_id"] = "identity-v1"
        result = MODULE.train(["Bonjour Bonjour"], 270)
        with self.assertRaisesRegex(ValueError, "normalization"):
            MODULE.tokenizer_document(candidate, result)

    def test_document_refuses_when_training_cannot_reach_exact_candidate_size(self) -> None:
        result = MODULE.train(["abcdefghijk"], 280)
        self.assertLess(result.vocabulary_size, 280)
        with self.assertRaisesRegex(ValueError, "exact candidate vocabulary"):
            MODULE.tokenizer_document(
                manifest(candidate_vocabulary_size=280), result
            )


if __name__ == "__main__":
    unittest.main()
