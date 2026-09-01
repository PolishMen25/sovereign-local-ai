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


class ByteBpeTests(unittest.TestCase):
    def test_training_is_deterministic_and_keeps_byte_coverage(self) -> None:
        first = MODULE.train(["bonjour bonjour", "bonjour monde"], 270)
        second = MODULE.train(["bonjour bonjour", "bonjour monde"], 270)
        self.assertEqual(first, second)
        self.assertEqual(first[:4], MODULE.SPECIAL_TOKENS)
        self.assertGreater(len(first), 260)
        self.assertLessEqual(len(first), 270)
        self.assertIn("62", first)

    def test_too_small_vocabulary_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.train(["synthetic"], 259)

    def test_record_contract_rejects_extra_fields(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.collect_texts(b'{"record_id":"x","text":"a","source":"no"}\n', 1)

    def test_tokenizer_document_carries_only_lineage_not_text(self) -> None:
        manifest = {
            "corpus_id": "corpus-approved-example",
            "materialization": {"content_sha256": "a" * 64},
            "tokenizer_contract": {"input_encoding": "utf-8", "normalization_policy_id": "unicode-nfc-v1"},
        }
        document = MODULE.tokenizer_document(manifest, MODULE.SPECIAL_TOKENS + ["61"])
        self.assertEqual(document["training_corpus_id"], "corpus-approved-example")
        self.assertNotIn("text", document)


if __name__ == "__main__":
    unittest.main()
