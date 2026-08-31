from pathlib import Path
from types import SimpleNamespace
import unittest

from tools.train_core_mini import (
    load_and_validate_document,
    synthetic_token_rows,
    training_contract,
    validate_run_limits,
)


class CoreMiniHarnessTests(unittest.TestCase):
    CONFIG = (
        Path(__file__).parents[1]
        / "configs"
        / "models"
        / "core-mini.candidate.json"
    )

    def test_candidate_has_exact_parameter_count(self) -> None:
        document, _ = load_and_validate_document(self.CONFIG)
        self.assertEqual(document["parameter_count"]["total_trainable"], 1_328_256)

    def test_synthetic_rows_are_deterministic_and_bounded(self) -> None:
        first = synthetic_token_rows(
            step=3,
            batch_size=2,
            sequence_length=8,
            vocabulary_size=32,
            seed=7,
        )
        second = synthetic_token_rows(
            step=3,
            batch_size=2,
            sequence_length=8,
            vocabulary_size=32,
            seed=7,
        )
        self.assertEqual(first, second)
        self.assertEqual([len(row) for row in first], [9, 9])
        self.assertTrue(all(0 <= token < 32 for row in first for token in row))

    def test_run_limits_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "steps"):
            validate_run_limits(steps=0, batch_size=1, sequence_length=2)
        with self.assertRaisesRegex(ValueError, "batch_size"):
            validate_run_limits(steps=1, batch_size=0, sequence_length=2)
        with self.assertRaisesRegex(ValueError, "sequence_length"):
            validate_run_limits(steps=1, batch_size=1, sequence_length=1)

    def test_training_contract_normalizes_torch_version_to_plain_string(self) -> None:
        class TorchVersion(str):
            pass

        args = SimpleNamespace(
            learning_rate=3e-4,
            batch_size=2,
            sequence_length=32,
            seed=7,
            threads=1,
        )
        torch = SimpleNamespace(__version__=TorchVersion("2.13.0+cpu"))

        contract = training_contract(args, "a" * 64, torch)

        self.assertIs(type(contract["torch"]), str)
        self.assertEqual(contract["torch"], "2.13.0+cpu")


if __name__ == "__main__":
    unittest.main()
