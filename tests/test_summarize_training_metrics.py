import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from tests._temp_support import sovereign_temporary_directory
from tools.summarize_training_metrics import (
    _atomic_write,
    _paths_alias,
    parse_records,
    summarize,
)


PROJECT_ROOT = Path(__file__).parents[1]


def synthetic_record(step: int, elapsed: float, *, tokens: int = 10) -> dict:
    return {
        "step": step,
        "loss": float(5 - step),
        "elapsed_seconds": elapsed,
        "tokens": tokens,
    }


def authorized_record(step: int, elapsed: float) -> dict:
    record = synthetic_record(step, elapsed)
    record.update(
        {
            "data_mode": "authorized-text",
            "data_lineage": {
                "schema_version": "0.1.0",
                "mode": "authorized-text",
                "corpus": {
                    "corpus_id": "corpus-demo",
                    "manifest_schema_version": "0.2.0",
                    "manifest_sha256": "b" * 64,
                    "split": "train",
                    "content_sha256": "c" * 64,
                    "byte_size": 128,
                    "record_count": 3,
                },
                "tokenizer": {
                    "schema_version": "0.2.0",
                    "status": "experimental",
                    "content_sha256": "d" * 64,
                    "vocabulary_size": 4096,
                    "normalization_policy_id": "unicode-nfc-v1",
                },
            },
            "training_contract_sha256": "a" * 64,
        }
    )
    return record


class TrainingMetricsSummaryTests(unittest.TestCase):
    def test_summarizes_post_warmup_steps_with_dispersion(self) -> None:
        records = [
            synthetic_record(1, 0.5),
            synthetic_record(2, 0.8),
            synthetic_record(3, 1.0),
        ]

        result = summarize(records, warmup_steps=1)

        self.assertEqual(result["schema_version"], "core-mini-metrics-summary.v2")
        self.assertEqual(result["data_mode"], "synthetic")
        self.assertEqual(result["steps_measured"], 2)
        self.assertEqual(result["tokens_per_step"], 10)
        self.assertEqual(result["tokens_measured"], 20)
        self.assertAlmostEqual(result["timing_seconds"]["median_step"], 0.25)
        self.assertAlmostEqual(
            result["timing_seconds"]["population_standard_deviation"], 0.05
        )
        self.assertAlmostEqual(
            result["timing_seconds"]["median_absolute_deviation"], 0.05
        )
        self.assertAlmostEqual(result["tokens_per_second"], 40.0)

    def test_rejects_elapsed_reset_from_concatenated_runs(self) -> None:
        records = [synthetic_record(1, 0.5), synthetic_record(2, 0.1)]

        with self.assertRaisesRegex(ValueError, "increase"):
            summarize(records, warmup_steps=0)

    def test_rejects_journal_that_does_not_start_at_step_one(self) -> None:
        record = synthetic_record(5, 0.5)

        with self.assertRaisesRegex(ValueError, "step"):
            summarize([record], warmup_steps=0)

    def test_rejects_non_finite_derived_statistics(self) -> None:
        record = synthetic_record(1, float.fromhex("0x0.0000000000001p-1022"))

        with self.assertRaisesRegex(ValueError, "statistics"):
            summarize([record], warmup_steps=0)

    def test_rejects_non_finite_or_non_float_loss(self) -> None:
        for loss in (float("nan"), 1, True):
            with self.subTest(loss=loss):
                record = synthetic_record(1, 0.5)
                record["loss"] = loss
                with self.assertRaisesRegex(ValueError, "loss"):
                    summarize([record], warmup_steps=0)

    def test_rejects_bool_integer_fields_and_token_drift(self) -> None:
        invalid_step = synthetic_record(1, 0.5)
        invalid_step["step"] = True
        with self.assertRaisesRegex(ValueError, "step"):
            summarize([invalid_step], warmup_steps=0)

        invalid_tokens = synthetic_record(1, 0.5)
        invalid_tokens["tokens"] = True
        with self.assertRaisesRegex(ValueError, "token"):
            summarize([invalid_tokens], warmup_steps=0)

        with self.assertRaisesRegex(ValueError, "warmup"):
            summarize([synthetic_record(1, 0.5)], warmup_steps=False)

        with self.assertRaisesRegex(ValueError, "token count changed"):
            summarize(
                [synthetic_record(1, 0.5), synthetic_record(2, 1.0, tokens=11)],
                warmup_steps=0,
            )

        for token_count in (1, (64 * 512) + 1):
            with self.subTest(token_count=token_count):
                with self.assertRaisesRegex(ValueError, "token count"):
                    summarize(
                        [synthetic_record(1, 0.5, tokens=token_count)],
                        warmup_steps=0,
                    )

    def test_rejects_mixed_or_changed_authorized_lineage(self) -> None:
        first = authorized_record(1, 0.5)
        mixed = synthetic_record(2, 1.0)
        with self.assertRaisesRegex(ValueError, "keys"):
            summarize([first, mixed], warmup_steps=0)

        changed = authorized_record(2, 1.0)
        changed["data_lineage"]["corpus"]["record_count"] = True
        with self.assertRaisesRegex(ValueError, "record count"):
            summarize([first, changed], warmup_steps=0)

        unexpected = authorized_record(1, 0.5)
        unexpected["data_lineage"]["raw_private_content"] = "forbidden"
        with self.assertRaisesRegex(ValueError, "lineage keys"):
            summarize([unexpected], warmup_steps=0)

    def test_strict_parser_rejects_duplicates_constants_and_partial_record(self) -> None:
        duplicate = (
            b'{"step":1,"step":2,"loss":1.0,'
            b'"elapsed_seconds":0.5,"tokens":10}\n'
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_records(duplicate)

        constant = (
            b'{"step":1,"loss":NaN,"elapsed_seconds":0.5,"tokens":10}\n'
        )
        with self.assertRaisesRegex(ValueError, "non-finite"):
            parse_records(constant)

        overflow = (
            b'{"step":1,"loss":1e9999,"elapsed_seconds":0.5,"tokens":10}\n'
        )
        with self.assertRaisesRegex(ValueError, "non-finite"):
            parse_records(overflow)

        first = json.dumps(synthetic_record(1, 0.5)).encode("utf-8")
        second = json.dumps(synthetic_record(2, 1.0)).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "invalid strict JSON"):
            parse_records(first + b"\r" + second + b"\n")

        crlf_records = parse_records(first + b"\r\n" + second + b"\r\n")
        self.assertEqual([record["step"] for record in crlf_records], [1, 2])

        complete = json.dumps(synthetic_record(1, 0.5)).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            parse_records(complete)

    def test_cli_hashes_exact_bytes_and_writes_atomically(self) -> None:
        payload = b"".join(
            json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
            + b"\n"
            for record in (synthetic_record(1, 0.5), synthetic_record(2, 0.8))
        )
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            metrics = root / "metrics.jsonl"
            output = root / "summary.json"
            metrics.write_bytes(payload)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "tools/summarize_training_metrics.py",
                    str(metrics),
                    "--warmup-steps",
                    "1",
                    "--output",
                    str(output),
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            self.assertEqual(output.read_bytes(), completed.stdout)
            document = json.loads(completed.stdout)
            self.assertEqual(
                document["metrics_sha256"], hashlib.sha256(payload).hexdigest()
            )
            self.assertEqual(list(root.glob(".summary.json.*.tmp")), [])

    def test_cli_refusal_does_not_echo_private_path(self) -> None:
        marker = "private-metrics-path-marker"
        arguments = (
            [marker, "--warmup-steps", "0"],
            ["metrics.jsonl", "--warmup-steps", marker],
            ["metrics.jsonl", "--unknown-option", marker],
        )
        for case in arguments:
            with self.subTest(arguments=case):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        "tools/summarize_training_metrics.py",
                        *case,
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertNotIn(marker, completed.stdout + completed.stderr)
                self.assertEqual(
                    completed.stderr.strip(), "CORE-MINI metrics summary refused"
                )

    def test_cli_refuses_output_alias_and_preserves_source(self) -> None:
        payload = (
            json.dumps(synthetic_record(1, 0.5), sort_keys=True).encode("utf-8")
            + b"\n"
        )
        with sovereign_temporary_directory() as directory:
            metrics = Path(directory) / "metrics.jsonl"
            metrics.write_bytes(payload)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "tools/summarize_training_metrics.py",
                    str(metrics),
                    "--warmup-steps",
                    "0",
                    "--output",
                    str(metrics),
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(metrics.read_bytes(), payload)
            self.assertEqual(
                completed.stderr.strip(), "CORE-MINI metrics summary refused"
            )

    def test_alias_detection_recognizes_hard_link(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            metrics = root / "metrics.jsonl"
            alias = root / "metrics-hard-link.jsonl"
            metrics.write_bytes(b"{}\n")
            try:
                os.link(metrics, alias)
            except OSError as error:
                self.skipTest(f"hard links unavailable: {type(error).__name__}")
            self.assertTrue(_paths_alias(metrics, alias))

    def test_atomic_output_never_replaces_existing_or_renamed_source(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            metrics = root / "metrics.jsonl"
            output = root / "summary.json"
            original = b"original metrics\n"
            existing = b"existing summary\n"
            metrics.write_bytes(original)
            output.write_bytes(existing)

            with self.assertRaisesRegex(ValueError, "already exists"):
                _atomic_write(output, b"new summary\n", source_path=metrics)
            self.assertEqual(metrics.read_bytes(), original)
            self.assertEqual(output.read_bytes(), existing)

            output.unlink()
            metrics.replace(output)
            with self.assertRaisesRegex(ValueError, "already exists"):
                _atomic_write(output, b"new summary\n", source_path=metrics)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
