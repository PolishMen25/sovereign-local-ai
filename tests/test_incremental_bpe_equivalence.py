import unittest

from services.inference.tokenizer import (
    MAXIMUM_TOKEN_BYTES,
    SPECIAL_TOKENS,
    BpeTrainingResult,
    canonical_byte_tokens,
    merge_sequence,
    normalize_text,
    train_byte_bpe,
)


def reference_train_byte_bpe(
    texts: list[str], vocabulary_size: int, minimum_frequency: int
) -> BpeTrainingResult:
    """Small, intentionally direct reference for the incremental trainer tests."""
    sequences = [
        [f"{byte:02x}" for byte in normalize_text(text).encode("utf-8")]
        for text in texts
    ]
    tokens = list(canonical_byte_tokens())
    vocabulary = set(tokens)
    merges: list[tuple[str, str]] = []

    while len(SPECIAL_TOKENS) + len(tokens) < vocabulary_size:
        frequencies: dict[tuple[str, str], int] = {}
        for sequence in sequences:
            for pair in zip(sequence, sequence[1:]):
                frequencies[pair] = frequencies.get(pair, 0) + 1

        eligible = [
            (count, left, right)
            for (left, right), count in frequencies.items()
            if count >= minimum_frequency
            and left + right not in vocabulary
            and len(left + right) // 2 <= MAXIMUM_TOKEN_BYTES
        ]
        if not eligible:
            break

        _, left, right = min(eligible, key=lambda candidate: (-candidate[0], candidate[1], candidate[2]))
        merged = left + right
        merges.append((left, right))
        tokens.append(merged)
        vocabulary.add(merged)
        sequences = [merge_sequence(sequence, (left, right), merged) for sequence in sequences]

    return BpeTrainingResult(tokens_hex=tuple(tokens), merges=tuple(merges))


class IncrementalBpeEquivalenceTests(unittest.TestCase):
    def test_incremental_training_matches_reference_on_adversarial_inputs(self) -> None:
        cases = [
            ["aaa"],
            ["aaaa"],
            ["aaaaaaaaa"],
            ["abab abab", "baba abab"],
            ["ééé café", "cafe\u0301 café"],
            ["function test() { return 1; }", "def test():\n    return 1\n"],
        ]

        for texts in cases:
            for minimum_frequency in (1, 2, 3):
                with self.subTest(texts=texts, minimum_frequency=minimum_frequency):
                    expected = reference_train_byte_bpe(texts, 290, minimum_frequency)
                    actual = train_byte_bpe(
                        texts, 290, minimum_frequency=minimum_frequency
                    )
                    self.assertEqual(actual, expected)
