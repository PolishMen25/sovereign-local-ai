"""Golden tests for the byte-BPE tokenizer.

They freeze the current observable behaviour (training output, encodings,
validation messages) so that any refactoring of services/inference/tokenizer.py
has to prove it is output-identical before it can be merged.  A digest change
here is a tokenizer contract change, never a test to "update".
"""

import copy
import hashlib
import json
import random
import unittest
import unicodedata

from services.inference.tokenizer import (
    ByteBpeTokenizer,
    experimental_tokenizer_document,
    merge_sequence,
    train_byte_bpe,
    validate_tokenizer_document,
)
from tests.test_incremental_bpe_equivalence import reference_train_byte_bpe

CORPUS = [
    "Bonjour à Lyon. Le serveur ML350 entraîne CORE sur CPU, sans réseau.",
    "def encode(text):\n    return [ord(c) for c in text]\n",
    "Café, café, CAFÉ ; œuvre, naïve, Noël — « guillemets » et 1 234,56 €.",
    "for i in range(10):\n    print(i * i)  # carré\n",
    "Les données restent dans RAW, puis quarantaine, puis validated.",
    "emoji 🙂🙂 et kanji 漢字漢字, tabulation\tet retour\r\n",
]
SAMPLES = ["Bonjour à Lyon.", "Café crème", "print('🙂')", "", "漢字", "a" * 24, "\t\r\n", "Noël 2026 : 1 234,56 €"]

# (vocabulary_size, minimum_frequency) -> (merge count, training digest, encodings digest)
GOLDEN = {
    (300, 2): (40, "7ff055e73b8606048939588f938ad82dce2a8d8aebdf3dbf3c019e4041d46cb1", "f27fdef76c3743c971066143307c7fd3b58c47216cd16d6222fbb9d51b77102e"),
    (420, 2): (54, "3fbe0464f879863575b2142688bbaad326b7616d22ad7bbf47479a50f4555666", "c1fcaf9809e9551479efd72e799c489efb44df30615b302bcaabd8045b7c6791"),
    (420, 1): (160, "649ebd4cb6852a5f8598da1046597960fce8d106c90f9c92480622ef0ed49e40", "0559e4212b4e20f219e0eef41c914e6aa432aea9c04e02a92e2910bbed919727"),
}

KEYS_MESSAGE = "tokenizer artifact keys must be exactly ['algorithm', 'input_encoding', 'maximum_token_bytes', 'merges', 'minimum_frequency', 'normalization_policy_id', 'schema_version', 'special_tokens', 'status', 'tokens_hex', 'training_corpus_id', 'training_corpus_sha256', 'vocabulary_size']"

# (label, mutation of a valid document, exact refusal message)
MUTATIONS = [
    ('clé en trop', lambda d: {**d, "extra": 1}, KEYS_MESSAGE),
    ('clé manquante', lambda d: {k: v for k, v in d.items() if k != "status"}, KEYS_MESSAGE),
    ('pas un dict', lambda d: [], KEYS_MESSAGE),
    ('schema', lambda d: {**d, "schema_version": "0.1.0"}, 'unsupported tokenizer schema_version'),
    ('status', lambda d: {**d, "status": "approved"}, 'unsupported tokenizer artifact status'),
    ('algorithme', lambda d: {**d, "algorithm": "bpe"}, 'unsupported tokenizer algorithm'),
    ('encodage', lambda d: {**d, "input_encoding": "latin-1"}, 'unsupported tokenizer input encoding'),
    ('normalisation', lambda d: {**d, "normalization_policy_id": "nfkc"}, 'unsupported tokenizer normalization policy'),
    ('tokens spéciaux', lambda d: {**d, "special_tokens": ["<pad>", "<eos>", "<bos>", "<unk>"]}, 'special tokens and their stable ids 0-3 do not match'),
    ('corpus id', lambda d: {**d, "training_corpus_id": "Corpus-X"}, 'invalid tokenizer training_corpus_id'),
    ('corpus sha', lambda d: {**d, "training_corpus_sha256": "A" * 64}, 'invalid tokenizer training_corpus_sha256'),
    ('fréquence booléenne', lambda d: {**d, "minimum_frequency": True}, 'invalid tokenizer minimum_frequency'),
    ('fréquence nulle', lambda d: {**d, "minimum_frequency": 0}, 'invalid tokenizer minimum_frequency'),
    ('taille max token', lambda d: {**d, "maximum_token_bytes": 32}, 'invalid tokenizer maximum_token_bytes'),
    ('tokens pas une liste', lambda d: {**d, "tokens_hex": tuple(d["tokens_hex"])}, 'tokenizer tokens_hex must be a list'),
    ('trop peu de tokens', lambda d: {**d, "tokens_hex": d["tokens_hex"][:255]}, 'tokenizer token count is outside the bounded range'),
    ('token non canonique', lambda d: {**d, "tokens_hex": replaced(d["tokens_hex"], 10, "0A")}, 'tokens_hex[10] must be canonical lowercase hexadecimal bytes'),
    ('token dupliqué', lambda d: {**d, "tokens_hex": replaced(d["tokens_hex"], -1, d["tokens_hex"][0])}, 'tokenizer tokens_hex contains a duplicate token'),
    ('octets dans le désordre', lambda d: {**d, "tokens_hex": replaced(replaced(d["tokens_hex"], 0, d["tokens_hex"][1]), 1, d["tokens_hex"][0])}, 'tokenizer must contain exactly one canonical token for each byte'),
    ('nombre de fusions', lambda d: {**d, "merges": d["merges"][:-1]}, 'tokenizer merge count must match its learned tokens'),
    ('fusion à 3 éléments', lambda d: {**d, "merges": replaced(d["merges"], 0, d["merges"][0] + ["61"])}, 'merges[0] must contain exactly two tokens'),
    ('fusion token indisponible', lambda d: {**d, "merges": replaced(d["merges"], 0, [d["tokens_hex"][-1], "61"])}, 'merges[0] references a token unavailable at that rank'),
    ('fusion recrée un token', lambda d: {**d, "merges": replaced(d["merges"], 1, ["61", "62"])}, 'merges[1] recreates an existing token'),
    ('fusion ne produit pas son rang', lambda d: {**d, "merges": replaced(d["merges"], 0, ["63", "64"])}, 'merges[0] does not produce the token assigned to its rank'),
    ('vocabulary_size faux', lambda d: {**d, "vocabulary_size": d["vocabulary_size"] + 1}, 'tokenizer vocabulary_size does not match its token ids'),
    ('vocabulary_size booléen', lambda d: {**d, "vocabulary_size": True}, 'tokenizer vocabulary_size does not match its token ids'),
]


def replaced(sequence: list, index: int, value: object) -> list:
    copy_ = list(sequence)
    copy_[index] = value
    return copy_


def digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def document(result, minimum_frequency: int) -> dict:
    return experimental_tokenizer_document(
        training_corpus_id="corpus-golden-tests",
        training_corpus_sha256="0" * 64,
        result=result,
        minimum_frequency=minimum_frequency,
    )


def reference_encode(doc: dict, text: str) -> list[int]:
    """Replay every merge in rank order, without the encoder's skip shortcut."""

    sequence = [f"{byte:02x}" for byte in unicodedata.normalize("NFC", text).encode("utf-8")]
    for left, right in doc["merges"]:
        sequence = merge_sequence(sequence, (left, right), left + right)
    ids = {token: index for index, token in enumerate(doc["tokens_hex"], start=4)}
    return [ids[token] for token in sequence]


def random_texts(rng: random.Random) -> list[str]:
    alphabet = rng.choice(["ab", "abc ", "aé🙂", "def (x):\n", "Lyon café "])
    return ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40))) for _ in range(rng.randint(1, 4))]


class TokenizerGoldenTests(unittest.TestCase):
    def test_training_and_encodings_match_frozen_digests(self) -> None:
        for (vocabulary_size, minimum_frequency), (merge_count, training, encodings) in GOLDEN.items():
            with self.subTest(vocabulary_size=vocabulary_size, minimum_frequency=minimum_frequency):
                result = train_byte_bpe(CORPUS, vocabulary_size, minimum_frequency=minimum_frequency)
                self.assertEqual(len(result.merges), merge_count)
                self.assertEqual(digest([list(result.tokens_hex), [list(m) for m in result.merges]]), training)
                tokenizer = ByteBpeTokenizer.from_document(document(result, minimum_frequency))
                self.assertEqual(digest([tokenizer.encode(s, bos=True, eos=True) for s in SAMPLES]), encodings)

    def test_incremental_training_matches_reference_on_random_corpora(self) -> None:
        rng = random.Random(20260911)
        for case in range(120):
            texts = random_texts(rng)
            vocabulary_size = rng.randint(260, 330)
            minimum_frequency = rng.choice((1, 1, 2, 3))
            with self.subTest(case=case):
                self.assertEqual(
                    train_byte_bpe(texts, vocabulary_size, minimum_frequency=minimum_frequency),
                    reference_train_byte_bpe(texts, vocabulary_size, minimum_frequency),
                )

    def test_encoder_matches_full_rank_replay_and_round_trips(self) -> None:
        rng = random.Random(7)
        doc = document(train_byte_bpe(CORPUS, 420, minimum_frequency=1), 1)
        tokenizer = ByteBpeTokenizer.from_document(doc)
        pool = "".join(CORPUS) + "é‍�"
        for case in range(300):
            text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 60)))
            with self.subTest(case=case):
                ids = tokenizer.encode(text)
                self.assertEqual(ids, reference_encode(doc, text))
                self.assertEqual(tokenizer.decode(ids), unicodedata.normalize("NFC", text))

    def test_validation_refusals_keep_their_exact_messages(self) -> None:
        base = document(train_byte_bpe(["abab abab cdcd", "abab cdcd"], 264, minimum_frequency=1), 1)
        self.assertIs(validate_tokenizer_document(base), base)
        for label, mutate, message in MUTATIONS:
            candidate = mutate(copy.deepcopy(base))
            with self.subTest(label), self.assertRaises(ValueError) as caught:
                validate_tokenizer_document(candidate)
            self.assertEqual(str(caught.exception), message)


if __name__ == "__main__":
    unittest.main()
