import copy
import itertools
import unittest

from services.inference.tokenizer import (
    BOS_TOKEN_ID,
    EOS_TOKEN_ID,
    MAXIMUM_DECODE_TOKEN_IDS,
    MAXIMUM_RUNTIME_TEXT_BYTES,
    ByteBpeTokenizer,
    canonical_byte_tokens,
    experimental_tokenizer_document,
    promote_to_candidate_core,
    train_byte_bpe,
    validate_tokenizer_document,
)


def artifact() -> dict:
    result = train_byte_bpe(
        ["Bonjour à Lyon. Bonjour à Lyon.", "Un vrai tokenizer local."],
        280,
    )
    return experimental_tokenizer_document(
        training_corpus_id="corpus-approved-tokenizer",
        training_corpus_sha256="a" * 64,
        result=result,
        minimum_frequency=2,
    )


class InferenceTokenizerTests(unittest.TestCase):
    def test_encode_decode_round_trip_is_deterministic(self) -> None:
        tokenizer = ByteBpeTokenizer.from_document(artifact())
        first = tokenizer.encode("Bonjour à Lyon.", bos=True, eos=True)
        second = tokenizer.encode("Bonjour à Lyon.", bos=True, eos=True)

        self.assertEqual(first, second)
        self.assertEqual(first[0], BOS_TOKEN_ID)
        self.assertEqual(first[-1], EOS_TOKEN_ID)
        self.assertEqual(tokenizer.decode(first), "Bonjour à Lyon.")

    def test_nfc_equivalents_have_identical_token_ids(self) -> None:
        tokenizer = ByteBpeTokenizer.from_document(artifact())
        self.assertEqual(tokenizer.encode("Cafe\u0301"), tokenizer.encode("Café"))

    def test_minimum_frequency_one_is_a_valid_deterministic_contract(self) -> None:
        result = train_byte_bpe(["rare merge sequence"], 270, minimum_frequency=1)
        document = experimental_tokenizer_document(
            training_corpus_id="corpus-approved-tokenizer",
            training_corpus_sha256="a" * 64,
            result=result,
            minimum_frequency=1,
        )
        self.assertEqual(document["minimum_frequency"], 1)

    def test_encoder_replays_merge_rank_instead_of_greedy_matching(self) -> None:
        tokens = list(canonical_byte_tokens()) + ["6162", "616263"]
        document = {
            "schema_version": "0.2.0",
            "status": "experimental",
            "algorithm": "byte_bpe",
            "training_corpus_id": "corpus-approved-ranked",
            "training_corpus_sha256": "b" * 64,
            "input_encoding": "utf-8",
            "normalization_policy_id": "unicode-nfc-v1",
            "special_tokens": ["<pad>", "<bos>", "<eos>", "<unk>"],
            "tokens_hex": tokens,
            "merges": [["61", "62"], ["6162", "63"]],
            "vocabulary_size": 4 + len(tokens),
            "minimum_frequency": 2,
            "maximum_token_bytes": 64,
        }
        tokenizer = ByteBpeTokenizer.from_document(document)
        self.assertEqual(tokenizer.encode("abc"), [4 + 257])
        self.assertEqual(tokenizer.decode([4 + 257]), "abc")

    def test_encoder_skips_absent_merges_without_changing_output(self) -> None:
        tokens = list(canonical_byte_tokens()) + ["6162", "fffe", "616263"]
        document = {
            "schema_version": "0.2.0",
            "status": "experimental",
            "algorithm": "byte_bpe",
            "training_corpus_id": "corpus-absent-merge",
            "training_corpus_sha256": "c" * 64,
            "input_encoding": "utf-8",
            "normalization_policy_id": "unicode-nfc-v1",
            "special_tokens": ["<pad>", "<bos>", "<eos>", "<unk>"],
            "tokens_hex": tokens,
            "merges": [["61", "62"], ["ff", "fe"], ["6162", "63"]],
            "vocabulary_size": 4 + len(tokens),
            "minimum_frequency": 2,
            "maximum_token_bytes": 64,
        }
        tokenizer = ByteBpeTokenizer.from_document(document)
        self.assertEqual(tokenizer.encode("abc"), [4 + 258])

    def test_mutating_source_document_does_not_mutate_runtime(self) -> None:
        document = artifact()
        tokenizer = ByteBpeTokenizer.from_document(document)
        expected = tokenizer.encode("Bonjour")
        document["tokens_hex"][0] = "ffff"
        self.assertEqual(tokenizer.encode("Bonjour"), expected)

    def test_mutating_returned_document_does_not_mutate_runtime(self) -> None:
        tokenizer = ByteBpeTokenizer.from_document(artifact())
        expected = tokenizer.encode("Bonjour")
        returned = tokenizer.document
        returned["tokens_hex"][0] = "ffff"
        returned["merges"].clear()
        self.assertEqual(tokenizer.encode("Bonjour"), expected)

    def test_runtime_text_and_decode_length_are_bounded(self) -> None:
        tokenizer = ByteBpeTokenizer.from_document(artifact())
        with self.assertRaisesRegex(ValueError, "runtime tokenizer size"):
            tokenizer.encode("a" * (MAXIMUM_RUNTIME_TEXT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "bounded decode length"):
            tokenizer.decode(itertools.repeat(4, MAXIMUM_DECODE_TOKEN_IDS + 1))

    def test_candidate_core_is_valid_but_unknown_status_is_refused(self) -> None:
        document = artifact()
        candidate = promote_to_candidate_core(document)
        self.assertEqual(candidate["status"], "candidate_core")
        self.assertEqual(ByteBpeTokenizer.from_document(candidate).encode("Bonjour"), ByteBpeTokenizer.from_document(document).encode("Bonjour"))

        document["status"] = "approved"
        with self.assertRaisesRegex(ValueError, "unsupported tokenizer artifact status"):
            validate_tokenizer_document(document)

    def test_promotion_refuses_a_nonexperimental_source(self) -> None:
        candidate = promote_to_candidate_core(artifact())
        with self.assertRaisesRegex(ValueError, "only an experimental"):
            promote_to_candidate_core(candidate)

    def test_noncanonical_or_incomplete_byte_coverage_is_refused(self) -> None:
        noncanonical = artifact()
        noncanonical["tokens_hex"][0] = "0 0"
        with self.assertRaisesRegex(ValueError, "canonical"):
            validate_tokenizer_document(noncanonical)

        incomplete = artifact()
        incomplete["tokens_hex"][0], incomplete["tokens_hex"][1] = (
            incomplete["tokens_hex"][1],
            incomplete["tokens_hex"][0],
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_tokenizer_document(incomplete)

    def test_tampered_merge_order_or_output_is_refused(self) -> None:
        document = artifact()
        self.assertTrue(document["merges"])

        unavailable = copy.deepcopy(document)
        unavailable["merges"][0][0] = "6162"
        with self.assertRaisesRegex(ValueError, "unavailable"):
            validate_tokenizer_document(unavailable)

        wrong_output = copy.deepcopy(document)
        wrong_output["tokens_hex"][256] = "ffff"
        with self.assertRaisesRegex(ValueError, "does not produce"):
            validate_tokenizer_document(wrong_output)

    def test_out_of_range_or_boolean_token_id_is_refused(self) -> None:
        tokenizer = ByteBpeTokenizer.from_document(artifact())
        with self.assertRaisesRegex(ValueError, "outside"):
            tokenizer.decode([tokenizer.vocabulary_size])
        with self.assertRaisesRegex(ValueError, "integer"):
            tokenizer.decode([True])


if __name__ == "__main__":
    unittest.main()
