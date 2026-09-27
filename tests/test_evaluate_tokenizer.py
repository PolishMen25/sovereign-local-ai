"""Tests for the offline tokenizer evaluation tool.

Every tokenizer here is trained in the test from the synthetic fixture; no
corpus, artifact or digest from the real project is read.
"""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import unicodedata
import unittest
from unittest import mock

from services.inference.tokenizer import (
    ByteBpeTokenizer,
    experimental_tokenizer_document,
    train_byte_bpe,
)
from tests._temp_support import sovereign_temporary_directory
from tools import evaluate_tokenizer as tool


PROJECT_ROOT = Path(__file__).parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "tokenizer_eval_synthetic.jsonl"
TOOL_PATH = PROJECT_ROOT / "tools" / "evaluate_tokenizer.py"
PROTOCOL_PATH = PROJECT_ROOT / "docs" / "model" / "tokenizer-experiments-protocol.md"


def fixture_records() -> list[dict]:
    return [json.loads(line) for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()]


def canonical(document: dict) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def tokenizer_document(vocabulary_size: int, *, minimum_frequency: int = 2,
                       training_corpus_sha256: str = "a" * 64) -> dict:
    texts = [record["text"] for record in fixture_records()]
    return experimental_tokenizer_document(
        training_corpus_id="corpus-synthetic-eval",
        training_corpus_sha256=training_corpus_sha256,
        result=train_byte_bpe(texts, vocabulary_size, minimum_frequency=minimum_frequency),
        minimum_frequency=minimum_frequency,
    )


def jsonl(records: list[dict]) -> bytes:
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records).encode("utf-8")


class EvaluationCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = sovereign_temporary_directory()
        self.root = Path(self._temporary.__enter__())

    def tearDown(self) -> None:
        self._temporary.__exit__(None, None, None)

    def write_tokenizer(self, name: str, document: dict) -> tuple[Path, str]:
        payload = canonical(document)
        path = self.root / f"{name}.json"
        path.write_bytes(payload)
        return path, hashlib.sha256(payload).hexdigest()

    def write_file(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        return path

    def standard_tokenizers(self) -> list[tuple[str, Path, str]]:
        entries = []
        for label, size, frequency in (("bytes", 260, 2), ("bpe-320", 320, 2), ("bpe-420", 420, 1)):
            path, digest = self.write_tokenizer(label, tokenizer_document(size, minimum_frequency=frequency))
            entries.append((label, path, digest))
        return entries

    def cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = tool.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def tokenizer_arguments(entries: list[tuple[str, Path, str]]) -> list[str]:
        arguments: list[str] = []
        for label, path, digest in entries:
            arguments += ["--tokenizer", label, str(path), digest]
        return arguments


class FixtureTests(unittest.TestCase):
    def test_fixture_is_labelled_bilingual_and_covers_code(self) -> None:
        records = fixture_records()
        self.assertTrue(all(set(record) == tool.LABELLED_KEYS for record in records))
        groups = {(record["language"], record["content_type"]) for record in records}
        for group in (("fr", "prose"), ("en", "prose"), ("fr", "code"), ("en", "code"), ("zxx", "shell")):
            self.assertIn(group, groups)
        self.assertEqual(len(records), len({record["record_id"] for record in records}))

    def test_protocol_presents_no_decided_threshold(self) -> None:
        text = PROTOCOL_PATH.read_text(encoding="utf-8")
        self.assertIn("PROPOSÉ", text)
        self.assertIn("Aucun seuil", text)
        self.assertIn("tools/evaluate_tokenizer.py", text)


class NominalEvaluationTests(EvaluationCase):
    def test_report_is_deterministic_hashed_and_binds_every_input(self) -> None:
        entries = self.standard_tokenizers()
        outputs = []
        for name in ("first.json", "second.json"):
            code, stdout, stderr = self.cli(
                self.tokenizer_arguments(entries)
                + ["--eval-jsonl", str(FIXTURE_PATH), "--output", str(self.root / name)]
            )
            self.assertEqual(0, code, stderr)
            payload = (self.root / name).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), json.loads(stdout)["report_sha256"])
            outputs.append(payload)
        self.assertEqual(outputs[0], outputs[1])
        report = json.loads(outputs[0])
        self.assertEqual(tool.REPORT_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual("none_decided", report["thresholds"])
        self.assertEqual(
            hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(), report["evaluation_input"]["sha256"]
        )
        self.assertEqual(
            [digest for _label, _path, digest in entries],
            [item["artifact"]["sha256"] for item in report["tokenizers"]],
        )
        self.assertTrue(report["integrity_ok"])

    def test_metrics_are_grouped_by_language_and_content_type(self) -> None:
        report = tool.run_evaluation(tokenizers=self.standard_tokenizers(), eval_path=FIXTURE_PATH)
        records = fixture_records()
        for result in report["tokenizers"]:
            self.assertEqual(len(records), result["overall"]["records"])
            self.assertEqual({"en", "fr", "mul", "und", "zxx"}, set(result["by_language"]))
            self.assertIn("fr/prose", result["by_group"])
            self.assertIn("en/code", result["by_group"])
            for table in ("by_language", "by_content_type", "by_group"):
                self.assertEqual(
                    result["overall"]["tokens"],
                    sum(entry["tokens"] for entry in result[table].values()),
                )
            self.assertEqual(
                sum(len(unicodedata.normalize("NFC", record["text"]).encode("utf-8")) for record in records),
                result["overall"]["bytes"],
            )
            self.assertLess(
                result["overall"]["bytes"], sum(len(record["text"].encode("utf-8")) for record in records)
            )

    def test_byte_only_artifact_fixes_the_metric_definitions(self) -> None:
        report = tool.run_evaluation(tokenizers=self.standard_tokenizers()[:1], eval_path=FIXTURE_PATH)
        result = report["tokenizers"][0]
        self.assertEqual(1.0, result["overall"]["bytes_per_token"])
        self.assertEqual(1.0, result["overall"]["single_byte_token_share"])
        self.assertEqual(result["overall"]["bytes"], result["overall"]["tokens"])
        self.assertEqual(0, result["vocabulary"]["learned_token_count"])
        self.assertIsNone(result["vocabulary"]["learned_token_utilisation"])
        self.assertIsNone(report["comparison"])

    def test_comparison_is_descriptive_against_the_first_artifact(self) -> None:
        report = tool.run_evaluation(tokenizers=self.standard_tokenizers(), eval_path=FIXTURE_PATH)
        comparison = report["comparison"]
        self.assertEqual("bytes", comparison["reference_label"])
        self.assertEqual("descriptive_only", comparison["interpretation"])
        overall = comparison["by_group"]["overall"]
        self.assertEqual(1.0, overall["bytes"]["token_ratio_vs_reference"])
        self.assertLess(overall["bpe-420"]["tokens"], overall["bpe-320"]["tokens"])
        self.assertLess(overall["bpe-320"]["token_ratio_vs_reference"], 1.0)
        self.assertNotIn("winner", json.dumps(report))
        self.assertNotIn("rank", json.dumps(comparison))

    def test_round_trip_and_special_token_invariants_hold(self) -> None:
        report = tool.run_evaluation(tokenizers=self.standard_tokenizers(), eval_path=FIXTURE_PATH)
        self.assertEqual(1, report["evaluation_input"]["records_changed_by_nfc"])
        for result in report["tokenizers"]:
            self.assertEqual(0, result["round_trip"]["records_failed"])
            self.assertTrue(all(result["special_token_invariants"].values()), result["label"])
            self.assertEqual(
                {
                    "bos_eos_wrap_the_plain_encoding", "decode_skips_pad_and_bos",
                    "decode_stops_at_eos", "plain_encoding_emits_no_special_id",
                    "special_token_ids_are_0_to_3", "special_token_text_is_not_injectable",
                    "unk_decodes_to_the_replacement_character",
                },
                set(result["special_token_invariants"]),
            )

    def test_long_record_is_decoded_in_slices_on_character_boundaries(self) -> None:
        path, digest = self.write_tokenizer("bytes", tokenizer_document(260))
        long_text = "a" + "é" * 40_000
        eval_path = self.write_file("long.jsonl", jsonl([{"record_id": "long-001", "text": long_text}]))
        report = tool.run_evaluation(tokenizers=[("bytes", path, digest)], eval_path=eval_path)
        result = report["tokenizers"][0]
        self.assertGreater(result["overall"]["tokens"], tool.MAXIMUM_DECODE_TOKEN_IDS)
        self.assertEqual(0, result["round_trip"]["records_failed"])
        self.assertEqual("plain", report["evaluation_input"]["record_format"])
        self.assertEqual({"und/unlabelled"}, set(result["by_group"]))

    def test_report_carries_no_evaluated_text_or_input_path(self) -> None:
        entries = self.standard_tokenizers()
        output = self.root / "report.json"
        code, _stdout, stderr = self.cli(
            self.tokenizer_arguments(entries) + ["--eval-jsonl", str(FIXTURE_PATH), "--output", str(output)]
        )
        self.assertEqual(0, code, stderr)
        payload = output.read_text(encoding="utf-8")
        for fragment in ("quarantaine", "moyenne", "Counter", "unittest", "fr-prose-001", str(self.root)):
            self.assertNotIn(fragment, payload)

    def test_command_line_script_runs_offline(self) -> None:
        entries = self.standard_tokenizers()[:2]
        output = self.root / "script.json"
        completed = subprocess.run(
            [sys.executable, "-B", str(TOOL_PATH), *self.tokenizer_arguments(entries),
             "--eval-jsonl", str(FIXTURE_PATH), "--output", str(output)],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["integrity_ok"])


class ManifestBindingTests(EvaluationCase):
    def manifest(self, payload: bytes, record_count: int) -> dict:
        def digest(value: str) -> str:
            return value * 64

        return {
            "schema_version": "0.2.0",
            "corpus_id": "corpus-synthetic-evaluation",
            "lifecycle_state": "VALIDATED",
            "classification": "synthetic",
            "materialization": {"format": "jsonl-utf8", "content_sha256": digest("c"),
                                "byte_size": 100 + len(payload), "record_count": 2 + record_count},
            "source_packages": [
                {"package_id": f"package-{name}", "provenance_id": f"provenance-{name}",
                 "content_sha256": digest(letter), "license": "CC0-1.0", "languages": ["fr", "en"],
                 "review_state": "approved"}
                for name, letter in (("train", "1"), ("validation", "2"), ("test", "3"))
            ],
            "splits": {
                "train": {"package_ids": ["package-train"], "content_sha256": digest("e"),
                          "byte_size": 50, "record_count": 1},
                "validation": {"package_ids": ["package-validation"],
                               "content_sha256": hashlib.sha256(payload).hexdigest(),
                               "byte_size": len(payload), "record_count": record_count},
                "test": {"package_ids": ["package-test"], "content_sha256": digest("0"),
                         "byte_size": 50, "record_count": 1},
            },
            "tokenizer_contract": {"input_encoding": "utf-8", "normalization_policy_id": "unicode-nfc-v1",
                                   "candidate_vocabulary_size": 32000, "review_state": "pending"},
            "approvals": {"data_governance": "pending", "training_authorization": "not_approved"},
        }

    def held_out(self) -> tuple[Path, bytes, int]:
        records = [{"record_id": record["record_id"], "text": record["text"]} for record in fixture_records()]
        payload = jsonl(records)
        return self.write_file("validation.jsonl", payload), payload, len(records)

    def test_validation_split_bound_by_the_manifest_is_accepted(self) -> None:
        eval_path, payload, count = self.held_out()
        manifest_path = self.write_file("manifest.json", canonical(self.manifest(payload, count)))
        trained_path, trained_digest = self.write_tokenizer(
            "trained", tokenizer_document(320, training_corpus_sha256="e" * 64)
        )
        other_path, other_digest = self.write_tokenizer("other", tokenizer_document(300))
        report = tool.run_evaluation(
            tokenizers=[("trained", trained_path, trained_digest), ("other", other_path, other_digest)],
            eval_path=eval_path, manifest_path=manifest_path, split="validation",
        )
        binding = report["evaluation_input"]["manifest_binding"]
        self.assertEqual("validation", binding["split"])
        self.assertEqual(hashlib.sha256(manifest_path.read_bytes()).hexdigest(), binding["manifest_sha256"])
        self.assertEqual(
            [True, False],
            [item["artifact"]["trained_on_manifest_train_split"] for item in report["tokenizers"]],
        )

    def test_bytes_that_differ_from_the_manifest_split_are_refused(self) -> None:
        eval_path, payload, count = self.held_out()
        manifest = self.manifest(payload, count)
        manifest["splits"]["validation"]["byte_size"] += 1
        manifest["materialization"]["byte_size"] += 1
        manifest_path = self.write_file("manifest.json", canonical(manifest))
        path, digest = self.write_tokenizer("bpe", tokenizer_document(300))
        with self.assertRaisesRegex(tool.EvaluationRefused, "does not match the manifest validation split"):
            tool.run_evaluation(tokenizers=[("bpe", path, digest)], eval_path=eval_path,
                                manifest_path=manifest_path, split="validation")

    def test_tokenizer_trained_on_a_held_out_split_is_refused(self) -> None:
        eval_path, payload, count = self.held_out()
        manifest_path = self.write_file("manifest.json", canonical(self.manifest(payload, count)))
        path, digest = self.write_tokenizer("leaky", tokenizer_document(300, training_corpus_sha256="0" * 64))
        with self.assertRaisesRegex(tool.EvaluationRefused, "trained on a held-out split"):
            tool.run_evaluation(tokenizers=[("leaky", path, digest)], eval_path=eval_path,
                                manifest_path=manifest_path, split="validation")

    def test_train_split_and_unpaired_arguments_are_refused(self) -> None:
        eval_path, payload, count = self.held_out()
        manifest_path = self.write_file("manifest.json", canonical(self.manifest(payload, count)))
        path, digest = self.write_tokenizer("bpe", tokenizer_document(300))
        with self.assertRaisesRegex(tool.EvaluationRefused, "only the validation or test split"):
            tool.run_evaluation(tokenizers=[("bpe", path, digest)], eval_path=eval_path,
                                manifest_path=manifest_path, split="train")
        with self.assertRaisesRegex(tool.EvaluationRefused, "together"):
            tool.run_evaluation(tokenizers=[("bpe", path, digest)], eval_path=eval_path, split="validation")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tool.parse_args(["--tokenizer", "bpe", str(path), digest, "--eval-jsonl", str(eval_path),
                             "--manifest", str(manifest_path), "--split", "train", "--output", "x.json"])


class TamperAndLeakTests(EvaluationCase):
    def assertRefusedWithoutReport(self, entries: list[tuple[str, Path, str]], message: str,
                                   eval_path: Path = FIXTURE_PATH) -> None:
        output = self.root / "refused.json"
        code, stdout, stderr = self.cli(
            self.tokenizer_arguments(entries) + ["--eval-jsonl", str(eval_path), "--output", str(output)]
        )
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn(message, stderr)
        self.assertFalse(output.exists())

    def test_structurally_tampered_artifact_is_refused_even_with_a_matching_pin(self) -> None:
        document = tokenizer_document(320)
        document["tokens_hex"][300], document["tokens_hex"][301] = (
            document["tokens_hex"][301], document["tokens_hex"][300]
        )
        path, digest = self.write_tokenizer("tampered", document)
        self.assertRefusedWithoutReport([("tampered", path, digest)], "invalid or tampered")

    def test_altered_special_tokens_are_refused(self) -> None:
        document = tokenizer_document(300)
        document["special_tokens"] = ["<pad>", "<bos>", "<unk>", "<eos>"]
        path, digest = self.write_tokenizer("special", document)
        self.assertRefusedWithoutReport([("special", path, digest)], "invalid or tampered")

    def test_artifact_that_differs_from_its_pin_is_refused(self) -> None:
        document = tokenizer_document(300)
        path, pinned = self.write_tokenizer("pinned", document)
        document["training_corpus_sha256"] = "b" * 64
        path.write_bytes(canonical(document))
        self.assertRefusedWithoutReport([("pinned", path, pinned)], "does not match its pinned SHA-256")

    def test_evaluating_on_the_tokenizer_training_split_is_refused(self) -> None:
        fixture_digest = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
        path, digest = self.write_tokenizer("self", tokenizer_document(300, training_corpus_sha256=fixture_digest))
        self.assertRefusedWithoutReport([("self", path, digest)], "training split of tokenizer self")

    def test_pinned_evaluation_digest_is_enforced(self) -> None:
        path, digest = self.write_tokenizer("bpe", tokenizer_document(300))
        with self.assertRaisesRegex(tool.EvaluationRefused, "evaluation file does not match"):
            tool.run_evaluation(tokenizers=[("bpe", path, digest)], eval_path=FIXTURE_PATH,
                                eval_sha256="f" * 64)

    def test_labels_pins_and_artifact_set_are_validated(self) -> None:
        path, digest = self.write_tokenizer("bpe", tokenizer_document(300))
        cases = (
            ([("Bad Label", path, digest)], "tokenizer label"),
            ([("bpe", path, digest.upper())], "pinned SHA-256 must be"),
            ([("bpe", path, digest), ("bpe", path, digest)], "labels must be unique"),
            ([("one", path, digest), ("two", path, digest)], "must be distinct"),
            ([(f"t{index}", path, digest) for index in range(9)], "between 1 and 8"),
            ([("missing", self.root / "absent.json", digest)], "unreadable"),
        )
        for entries, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(tool.EvaluationRefused, message):
                tool.run_evaluation(tokenizers=entries, eval_path=FIXTURE_PATH)

    def test_existing_report_is_never_overwritten(self) -> None:
        path, digest = self.write_tokenizer("bpe", tokenizer_document(300))
        output = self.write_file("existing.json", b"keep\n")
        code, _stdout, stderr = self.cli(
            ["--tokenizer", "bpe", str(path), digest, "--eval-jsonl", str(FIXTURE_PATH), "--output", str(output)]
        )
        self.assertEqual(1, code)
        self.assertIn("already exists", stderr)
        self.assertEqual(b"keep\n", output.read_bytes())

    def test_integrity_failure_writes_the_report_and_exits_two(self) -> None:
        path, digest = self.write_tokenizer("bpe", tokenizer_document(300))
        output = self.root / "broken.json"
        with mock.patch.object(ByteBpeTokenizer, "decode", lambda self, token_ids: "altéré"):
            code, stdout, _stderr = self.cli(
                ["--tokenizer", "bpe", str(path), digest, "--eval-jsonl", str(FIXTURE_PATH),
                 "--output", str(output)]
            )
        self.assertEqual(2, code)
        self.assertFalse(json.loads(stdout)["integrity_ok"])
        report = json.loads(output.read_text(encoding="utf-8"))
        result = report["tokenizers"][0]
        self.assertFalse(report["integrity_ok"])
        self.assertEqual(len(fixture_records()), result["round_trip"]["records_failed"])
        self.assertEqual(tool.MAXIMUM_LISTED_FAILURES, len(result["round_trip"]["failed_line_numbers"]))
        self.assertFalse(result["special_token_invariants"]["decode_stops_at_eos"])


class MalformedEvaluationInputTests(EvaluationCase):
    def test_malformed_evaluation_files_are_refused(self) -> None:
        good = {"record_id": "r1", "language": "fr", "content_type": "prose", "text": "Bonjour."}
        cases = {
            "repeats a record_id": jsonl([good, good]),
            "mixes plain and labelled": jsonl([good, {"record_id": "r2", "text": "x"}]),
            "unknown language": jsonl([dict(good, language="de")]),
            "unknown content_type": jsonl([dict(good, content_type="poem")]),
            "keys must be": jsonl([dict(good, source="web")]),
            "not strict JSON": b'{"record_id":"r1","record_id":"r2","text":"x"}\n',
            "non-finite": b'{"record_id":"r1","text":NaN}\n',
            "byte order mark": b"\xef\xbb\xbf" + jsonl([good]),
            "not valid UTF-8": b'{"record_id":"r1","text":"\xff"}\n',
            "size is outside": b"",
            "invalid text": jsonl([dict(good, text="")]),
            "must be a JSON object": b'["r1","x"]\n',
            "exceeds the runtime tokenizer bound": jsonl(
                [{"record_id": "big", "text": "x" * (tool.MAXIMUM_RUNTIME_TEXT_BYTES + 1)}]
            ),
        }
        path, digest = self.write_tokenizer("bpe", tokenizer_document(300))
        for message, payload in cases.items():
            eval_path = self.write_file("case.jsonl", payload)
            expected = "not strict JSON" if message == "non-finite" else message
            with self.subTest(case=message), self.assertRaisesRegex(tool.EvaluationRefused, expected):
                tool.run_evaluation(tokenizers=[("bpe", path, digest)], eval_path=eval_path)


class OfflineTests(EvaluationCase):
    def test_tool_imports_no_network_module(self) -> None:
        source = TOOL_PATH.read_text(encoding="utf-8")
        for module in ("socket", "urllib", "http.client", "ssl", "subprocess"):
            self.assertNotIn(f"import {module}", source)

    def test_evaluation_opens_no_socket(self) -> None:
        entries = self.standard_tokenizers()
        refused = AssertionError("network access attempted")
        with mock.patch.object(socket, "socket", side_effect=refused), \
                mock.patch.object(socket, "create_connection", side_effect=refused), \
                mock.patch.object(socket, "getaddrinfo", side_effect=refused):
            report = tool.run_evaluation(tokenizers=entries, eval_path=FIXTURE_PATH)
        self.assertTrue(report["integrity_ok"])


if __name__ == "__main__":
    unittest.main()
