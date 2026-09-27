import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.test_arena_practice_suite import KNOWN_OVERLAPS_PENDING_OWNER_DECISION
from tools import check_evaluation_contamination as checker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRACTICE_SUITE = PROJECT_ROOT / "configs" / "arena" / "practice-suite.v1.json"
RECORD_TEMPLATE = "### Instruction\n{prompt}\n\n### Réponse\n```python\n{source}\n```\n"

E1_PROMPT_FR = "Explique en deux phrases pourquoi une sauvegarde doit être restaurée pour être considérée comme prouvée."
E1_PROMPT_EN = "Summarize in one sentence why a synthetic fixture must never contain a real secret or address."
E2_PROMPT_MERGE = ("Write zigzag_merge(left, right) that interleaves two lists element by element "
                   "and appends the remaining tail of the longer list.")
E2_PROMPT_VOWELS = "Write count_vowels(text) that returns how many ASCII vowels appear in text, ignoring case entirely."

SYNTHETIC_E1 = {
    "schema_version": "core-language-evaluation-suite.v1",
    "prompts": [
        {"id": "fr-general-01", "language": "fr", "category": "general", "prompt": E1_PROMPT_FR},
        {"id": "en-general-01", "language": "en", "category": "general", "prompt": E1_PROMPT_EN},
    ],
}
SYNTHETIC_E2 = {
    "schema_version": "core-code-evaluation-suite.v1",
    "tasks": [
        {"id": "python-01-zigzag-merge", "function_name": "zigzag_merge", "prompt": E2_PROMPT_MERGE,
         "test_source": "assert True\n"},
        {"id": "python-02-count-vowels", "function_name": "count_vowels", "prompt": E2_PROMPT_VOWELS,
         "test_source": "assert True\n"},
    ],
}
CLEAN_TEXTS = (
    RECORD_TEMPLATE.format(prompt="Write reverse_words(s) that returns the words of s in reverse order.",
                           source="def reverse_words(s):\n    return ' '.join(reversed(s.split()))"),
    RECORD_TEMPLATE.format(prompt="Write double(x) that returns twice x.", source="def double(x):\n    return 2 * x"),
)
HEX = re.compile(r"^[0-9a-f]{64}$")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def jsonl(records: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for r in records).encode("utf-8")


class ContaminationCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.e1 = self.root / "e1.json"
        self.e2 = self.root / "e2.json"
        self.e1.write_bytes(json.dumps(SYNTHETIC_E1).encode("utf-8"))
        self.e2.write_bytes(json.dumps(SYNTHETIC_E2).encode("utf-8"))

    # -- fixtures -----------------------------------------------------------------

    def arena_increment(self, texts: tuple[str, ...] | list[str], *, name: str = "increment",
                        schema: str = "arena-corpus-increment.v1", body: bytes | None = None,
                        declared_sha: str | None = None, ids: list[str] | None = None) -> Path:
        directory = self.root / name
        directory.mkdir()
        ids = ids or [f"corpus-arena-test-{index:04d}" for index in range(len(texts))]
        body = jsonl([{"record_id": i, "text": t} for i, t in zip(ids, texts)]) if body is None else body
        (directory / "records.jsonl").write_bytes(body)
        manifest = {"schema_version": schema, "increment_id": f"corpus-arena-{name}",
                    "content_sha256": declared_sha or sha(body), "record_count": max(1, len(texts))}
        (directory / "manifest.json").write_bytes(json.dumps(manifest).encode("utf-8"))
        return directory

    def conversation_candidates(self, texts: list[str], *, data_file: str = "learning-candidates.jsonl") -> Path:
        directory = self.root / "candidates"
        directory.mkdir()
        records = []
        for index, text in enumerate(texts):
            digests = [sha(f"user-{index}".encode()), sha(f"assistant-{index}".encode())]
            records.append({"conversation_sha256": sha(b"conversation"), "record_id": sha(f"record-{index}".encode()),
                            "schema_version": "conversation-learning-record.v1",
                            "source_message_sha256": digests, "text": text})
        body = jsonl(records)
        (directory / "learning-candidates.jsonl").write_bytes(body)
        manifest = {"approval_status": "pending_owner_approval", "automatic_promotion": False,
                    "data_file": data_file, "data_sha256": sha(body), "record_count": len(records),
                    "schema_version": "conversation-learning-candidate-manifest.v1"}
        (directory / "manifest.candidate.json").write_bytes(json.dumps(manifest).encode("utf-8"))
        return directory

    def authorized_text(self, splits: dict[str, list[str]]) -> tuple[Path, dict[str, Path]]:
        bodies = {name: jsonl([{"record_id": f"{name}-{i:04d}", "text": t} for i, t in enumerate(texts)])
                  for name, texts in splits.items()}
        paths = {}
        for name, body in bodies.items():
            paths[name] = self.root / f"{name}.jsonl"
            paths[name].write_bytes(body)
        everything = b"".join(bodies.values())
        manifest = {
            "schema_version": "0.2.0",
            "corpus_id": "corpus-synthetic-contamination-check",
            "lifecycle_state": "VALIDATED",
            "classification": "approved_training",
            "materialization": {"format": "jsonl-utf8", "content_sha256": sha(everything),
                                "byte_size": len(everything), "record_count": sum(len(t) for t in splits.values())},
            "source_packages": [
                {"package_id": f"pkg-{name}", "provenance_id": f"prov-{name}", "content_sha256": sha(body),
                 "license": "CC0-1.0", "languages": ["en"], "review_state": "approved"}
                for name, body in bodies.items()
            ],
            "splits": {name: {"package_ids": [f"pkg-{name}"], "content_sha256": sha(body), "byte_size": len(body),
                              "record_count": len(splits[name])} for name, body in bodies.items()},
            "tokenizer_contract": {"input_encoding": "utf-8", "normalization_policy_id": "nfc-v1",
                                   "candidate_vocabulary_size": 32000, "review_state": "pending"},
            "approvals": {"data_governance": "pending", "training_authorization": "not_approved"},
        }
        manifest_path = self.root / "corpus-manifest.json"
        manifest_path.write_bytes(json.dumps(manifest).encode("utf-8"))
        return manifest_path, paths

    def run_cli(self, *argv: str, synthetic: bool = True) -> tuple[int, str, str]:
        suites = ["--e1", str(self.e1), "--e2", str(self.e2)] if synthetic else []
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = checker.main([*suites, *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def check(self, kind: str, *paths: Path, **options) -> dict:
        return checker.check(kind, tuple(paths), e1_path=self.e1, e2_path=self.e2, **options)

    # -- nominal paths ------------------------------------------------------------

    def test_clean_arena_increments_pass(self) -> None:
        for schema in ("arena-corpus-increment.v1", "arena-corpus-increment.validated.v1"):
            with self.subTest(schema=schema):
                directory = self.arena_increment(CLEAN_TEXTS, name=schema.replace(".", "-"), schema=schema)
                code, out, err = self.run_cli("arena-increment", str(directory))
                # stderr may carry unrelated interpreter warnings; only a refusal matters here.
                self.assertEqual(code, checker.EXIT_CLEAN, err)
                self.assertNotIn("refused", err)
                report = json.loads(out)
                self.assertFalse(report["summary"]["contaminated"])
                self.assertEqual(report["findings"], [])
                self.assertEqual(report["source"]["content_sha256"], sha((directory / "records.jsonl").read_bytes()))
                self.assertEqual(report["source"]["record_count"], 2)
                self.assertEqual([s["name"] for s in report["evaluation_sets"]], ["E1", "E2"])

    def test_planted_verbatim_prompt_is_detected(self) -> None:
        leak = RECORD_TEMPLATE.format(prompt=E2_PROMPT_VOWELS, source="def vowels(t):\n    return 0")
        directory = self.arena_increment([CLEAN_TEXTS[0], leak])
        code, out, _ = self.run_cli("arena-increment", str(directory))
        self.assertEqual(code, checker.EXIT_OVERLAP)
        report = json.loads(out)
        self.assertTrue(report["summary"]["contaminated"])
        [finding] = report["findings"]
        self.assertEqual((finding["eval_set"], finding["eval_id"], finding["field"], finding["level"]),
                         ("E2", "python-02-count-vowels", "prompt", "exact_prompt"))
        self.assertEqual(finding["eval_sha256"], sha(E2_PROMPT_VOWELS.encode("utf-8")))
        self.assertEqual(finding["records"], [{"record_index": 2, "record_id": "corpus-arena-test-0001",
                                               "record_sha256": sha(leak.encode("utf-8")), "ngram_ratio": 1.0}])

    def test_normalized_copy_is_detected(self) -> None:
        variant = "WRITE  count_vowels( text ) -- that returns how many ascii VOWELS appear in text; ignoring case entirely!"
        directory = self.arena_increment([RECORD_TEMPLATE.format(prompt=variant, source="pass")])
        [finding] = self.check("arena-increment", directory)["findings"]
        self.assertEqual((finding["eval_id"], finding["level"]), ("python-02-count-vowels", "normalized_prompt"))

    def test_partial_copy_is_detected_by_ngrams(self) -> None:
        words = E2_PROMPT_MERGE.split()
        partial = " ".join(words[: int(len(words) * 0.75)]) + " then sorts everything in place."
        directory = self.arena_increment([RECORD_TEMPLATE.format(prompt=partial, source="pass")])
        [finding] = self.check("arena-increment", directory)["findings"]
        self.assertEqual((finding["eval_id"], finding["level"]), ("python-01-zigzag-merge", "ngram_prompt"))
        self.assertGreaterEqual(finding["records"][0]["ngram_ratio"], 0.5)
        self.assertLess(finding["records"][0]["ngram_ratio"], 1.0)

    def test_function_definition_is_detected(self) -> None:
        text = RECORD_TEMPLATE.format(prompt="Write an interleaving helper.",
                                      source="def zigzag_merge (a, b):\n    return a + b")
        directory = self.arena_increment([text])
        [finding] = self.check("arena-increment", directory)["findings"]
        self.assertEqual((finding["eval_id"], finding["field"], finding["level"]),
                         ("python-01-zigzag-merge", "function_name", "function_definition"))
        self.assertEqual(finding["eval_sha256"], sha(b"zigzag_merge"))
        self.assertNotIn("ngram_ratio", finding["records"][0])

    def test_a_mention_without_definition_is_not_a_function_finding(self) -> None:
        text = RECORD_TEMPLATE.format(prompt="Explain what a zigzag_merge helper could do.", source="pass")
        directory = self.arena_increment([text])
        self.assertEqual(self.check("arena-increment", directory)["findings"], [])

    def test_conversation_candidates_detect_an_e1_prompt_typed_in_chat(self) -> None:
        texts = [f"<|user|>\n{E1_PROMPT_FR}\n<|assistant|>\nParce que seule une restauration vérifiée le montre.",
                 "<|user|>\nBonjour\n<|assistant|>\nBonjour, que puis-je faire ?"]
        directory = self.conversation_candidates(texts)
        code, out, _ = self.run_cli("conversation-candidates", str(directory))
        self.assertEqual(code, checker.EXIT_OVERLAP)
        report = json.loads(out)
        self.assertEqual(report["source"]["kind"], "conversation-candidates")
        [finding] = report["findings"]
        self.assertEqual((finding["eval_set"], finding["eval_id"], finding["level"]), ("E1", "fr-general-01", "exact_prompt"))
        self.assertRegex(finding["records"][0]["record_id"], HEX)

    def test_authorized_text_split_is_identified_and_checked(self) -> None:
        leak = f"Notes. {E1_PROMPT_EN} End of notes."
        manifest, paths = self.authorized_text({"train": [CLEAN_TEXTS[0], leak], "validation": [CLEAN_TEXTS[1]],
                                                "test": ["A neutral synthetic sentence for the test split."]})
        code, out, _ = self.run_cli("authorized-text", str(manifest), str(paths["train"]))
        self.assertEqual(code, checker.EXIT_OVERLAP)
        report = json.loads(out)
        self.assertEqual((report["source"]["split"], report["source"]["corpus_id"]),
                         ("train", "corpus-synthetic-contamination-check"))
        self.assertEqual([f["eval_id"] for f in report["findings"]], ["en-general-01"])
        code, out, _ = self.run_cli("authorized-text", str(manifest), str(paths["validation"]))
        self.assertEqual(code, checker.EXIT_CLEAN)
        self.assertEqual(json.loads(out)["source"]["split"], "validation")

    def test_findings_list_is_bounded_but_counted(self) -> None:
        leak = RECORD_TEMPLATE.format(prompt=E2_PROMPT_MERGE, source="pass")
        directory = self.arena_increment([leak, leak + "\n# copy"])
        [finding] = self.check("arena-increment", directory, max_records_per_finding=1)["findings"]
        self.assertEqual((finding["record_count"], len(finding["records"]), finding["records_truncated"]), (2, 1, True))

    def test_unsafe_record_ids_are_not_echoed(self) -> None:
        leak = RECORD_TEMPLATE.format(prompt=E2_PROMPT_MERGE, source="pass")
        directory = self.arena_increment([leak], ids=["private note: the owner typed this"])
        [finding] = self.check("arena-increment", directory)["findings"]
        self.assertIsNone(finding["records"][0]["record_id"])
        self.assertEqual(finding["records"][0]["record_sha256"], sha(leak.encode("utf-8")))

    # -- content-free report and read-only behaviour --------------------------------

    def test_report_holds_no_prompt_record_or_solution_text(self) -> None:
        solution = "def count_vowels(text):\n    return sum(c in 'aeiou' for c in text.lower())"
        leaks = [RECORD_TEMPLATE.format(prompt=E2_PROMPT_VOWELS, source=solution),
                 f"Contexte : {E1_PROMPT_FR}",
                 RECORD_TEMPLATE.format(prompt=" ".join(E2_PROMPT_MERGE.split()[:14]) + " quickly.", source="pass")]
        directory = self.arena_increment(leaks)
        code, out, _ = self.run_cli("arena-increment", str(directory))
        self.assertEqual(code, checker.EXIT_OVERLAP)
        summary = json.loads(out)["summary"]
        self.assertEqual((summary["finding_count"], summary["items_with_findings"]), (4, 3))
        forbidden = [E1_PROMPT_FR, E1_PROMPT_EN, E2_PROMPT_MERGE, E2_PROMPT_VOWELS, solution, *leaks,
                     checker.normalize(E2_PROMPT_VOWELS), checker.normalize(E1_PROMPT_FR), "sum(c in", "Contexte"]
        for text in forbidden:
            self.assertNotIn(text, out)

        def strings(value):
            if isinstance(value, dict):
                for key, nested in value.items():
                    yield key
                    yield from strings(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from strings(nested)
            elif isinstance(value, str):
                yield value

        report = json.loads(out)
        allowed_long = {report["parameters"]["normalization"]}
        for value in strings(report):
            self.assertTrue(len(value) <= 64 or value in allowed_long, value)

    def test_never_writes_into_the_source_or_anywhere_else(self) -> None:
        leak = RECORD_TEMPLATE.format(prompt=E2_PROMPT_MERGE, source="def zigzag_merge(a, b):\n    return a")
        directory = self.arena_increment([leak])

        def snapshot() -> dict[str, str]:
            return {str(p.relative_to(self.root)): sha(p.read_bytes()) for p in sorted(self.root.rglob("*")) if p.is_file()}

        before = snapshot()
        code, _, _ = self.run_cli("arena-increment", str(directory))
        self.assertEqual(code, checker.EXIT_OVERLAP)
        self.assertEqual(snapshot(), before)

    # -- refusals -------------------------------------------------------------------

    def test_digest_mismatch_is_refused_without_a_partial_report(self) -> None:
        leak = RECORD_TEMPLATE.format(prompt=E2_PROMPT_MERGE, source="pass")
        directory = self.arena_increment([leak], declared_sha="0" * 64)
        code, out, err = self.run_cli("arena-increment", str(directory))
        self.assertEqual((code, out), (checker.EXIT_REFUSED, ""))
        self.assertIn("does not match the manifest content_sha256", err)

    def test_split_unknown_to_the_manifest_is_refused(self) -> None:
        manifest, _ = self.authorized_text({"train": [CLEAN_TEXTS[0]], "validation": [CLEAN_TEXTS[1]],
                                            "test": ["A neutral synthetic sentence."]})
        stray = self.root / "stray.jsonl"
        stray.write_bytes(jsonl([{"record_id": "stray-0000", "text": "Unlisted text."}]))
        code, out, err = self.run_cli("authorized-text", str(manifest), str(stray))
        self.assertEqual((code, out), (checker.EXIT_REFUSED, ""))
        self.assertIn("matches no digest", err)

    def test_invalid_corpus_manifest_is_refused(self) -> None:
        manifest, paths = self.authorized_text({"train": [CLEAN_TEXTS[0]], "validation": [CLEAN_TEXTS[1]],
                                                "test": ["A neutral synthetic sentence."]})
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["lifecycle_state"] = "RAW"
        manifest.write_bytes(json.dumps(document).encode("utf-8"))
        with self.assertRaisesRegex(checker.CheckRefused, "manifest is invalid"):
            self.check("authorized-text", manifest, paths["train"])

    def test_malformed_arena_records_are_refused(self) -> None:
        good = json.dumps({"record_id": "r-0000", "text": "x"}).encode("utf-8")
        cases = {
            "blank line": good + b"\n\n" + good.replace(b"r-0000", b"r-0001") + b"\n",
            "extra key": json.dumps({"record_id": "r-0000", "text": "x", "prompt": "y"}).encode("utf-8") + b"\n",
            "duplicate id": good + b"\n" + good + b"\n",
            "not an object": b"[1, 2]\n",
            "invalid utf-8": b"{\"record_id\": \"r-0000\", \"text\": \"\xff\"}\n",
            "empty text": json.dumps({"record_id": "r-0000", "text": ""}).encode("utf-8") + b"\n",
            "not json": b"record_id=r-0000\n",
        }
        for index, (label, body) in enumerate(cases.items()):
            with self.subTest(case=label):
                directory = self.arena_increment(["x"], name=f"bad-{index}", body=body)
                with self.assertRaises(checker.CheckRefused):
                    self.check("arena-increment", directory)

    def test_deeply_nested_input_is_a_refusal_never_an_overlap(self) -> None:
        nested = b"[" * 200_000 + b"\n"
        directory = self.arena_increment(["x"], name="nested-record", body=nested)
        with self.assertRaisesRegex(checker.CheckRefused, "not valid UTF-8 JSON"):
            self.check("arena-increment", directory)
        code, out, err = self.run_cli("arena-increment", str(directory))
        self.assertEqual((code, out), (checker.EXIT_REFUSED, ""))
        self.assertIn("refused", err)
        nested_e1 = self.root / "nested-e1.json"
        nested_e1.write_bytes(b"[" * 200_000)
        code, out, _ = self.run_cli("--e1", str(nested_e1), "arena-increment", str(directory), synthetic=False)
        self.assertEqual((code, out), (checker.EXIT_REFUSED, ""))

    def test_unreadable_or_unexpected_failures_are_refusals_without_a_path(self) -> None:
        directory = self.arena_increment(CLEAN_TEXTS)
        secret_path = "/srv/internal-share/corpus/records.jsonl"
        for failure, expected in ((PermissionError(13, "Permission denied", secret_path), "Permission denied"),
                                  (RuntimeError(f"boom at {secret_path}"), "unexpected failure")):
            with self.subTest(failure=type(failure).__name__), mock.patch.object(checker, "check", side_effect=failure):
                code, out, err = self.run_cli("arena-increment", str(directory))
                self.assertEqual((code, out), (checker.EXIT_REFUSED, ""))
                self.assertIn(expected, err)
                self.assertNotIn("internal-share", err)

    def test_empty_or_unknown_arena_sources_are_refused(self) -> None:
        directory = self.arena_increment(["x"], name="unknown-schema", schema="arena-packet.v1")
        with self.assertRaisesRegex(checker.CheckRefused, "unknown schema"):
            self.check("arena-increment", directory)
        empty = self.arena_increment(["x"], name="empty", body=b"")
        with self.assertRaisesRegex(checker.CheckRefused, "bounded range"):
            self.check("arena-increment", empty)
        with self.assertRaisesRegex(checker.CheckRefused, "must be a directory"):
            self.check("arena-increment", self.root / "missing")

    def test_oversized_line_is_refused(self) -> None:
        directory = self.arena_increment(["y" * 200])
        with mock.patch.object(checker, "MAX_LINE_BYTES", 64):
            with self.assertRaisesRegex(checker.CheckRefused, "line size limit"):
                self.check("arena-increment", directory)

    def test_conversation_candidate_contract_is_enforced(self) -> None:
        directory = self.conversation_candidates(["<|user|>\nBonjour\n<|assistant|>\nBonjour."],
                                                 data_file="../outside.jsonl")
        with self.assertRaisesRegex(checker.CheckRefused, "data_file must be"):
            self.check("conversation-candidates", directory)
        plain = self.arena_increment(CLEAN_TEXTS, name="plain")
        (plain / "learning-candidates.jsonl").write_bytes((plain / "records.jsonl").read_bytes())
        manifest = {"schema_version": "conversation-learning-candidate-manifest.v1",
                    "data_file": "learning-candidates.jsonl", "record_count": 2,
                    "data_sha256": sha((plain / "records.jsonl").read_bytes())}
        (plain / "manifest.candidate.json").write_bytes(json.dumps(manifest).encode("utf-8"))
        with self.assertRaisesRegex(checker.CheckRefused, "conversation-learning-record.v1"):
            self.check("conversation-candidates", plain)

    def test_invalid_evaluation_suites_are_refused(self) -> None:
        directory = self.arena_increment(CLEAN_TEXTS)
        practice_as_e2 = self.root / "practice-as-e2.json"
        practice_as_e2.write_bytes(PRACTICE_SUITE.read_bytes())
        duplicate_e1 = self.root / "duplicate-e1.json"
        duplicate_e1.write_bytes(json.dumps(dict(SYNTHETIC_E1, prompts=SYNTHETIC_E1["prompts"] * 2)).encode("utf-8"))
        bad_function = self.root / "bad-function.json"
        bad_function.write_bytes(json.dumps(dict(SYNTHETIC_E2, tasks=[dict(SYNTHETIC_E2["tasks"][0], function_name="x; import os")])).encode("utf-8"))
        for label, e1, e2, message in (
            ("practice suite given as E2", self.e1, practice_as_e2, "E2 suite schema"),
            ("duplicate E1 ids", duplicate_e1, self.e2, "unique and safe"),
            ("unsafe function name", self.e1, bad_function, "invalid function name"),
        ):
            with self.subTest(case=label):
                with self.assertRaisesRegex(checker.CheckRefused, message):
                    checker.check("arena-increment", (directory,), e1_path=e1, e2_path=e2)

    def test_parameters_are_bounded(self) -> None:
        directory = self.arena_increment(CLEAN_TEXTS)
        for options in ({"ngram_size": 2}, {"ngram_size": 33}, {"ngram_threshold": 0.0}, {"ngram_threshold": float("nan")},
                        {"ngram_threshold": 1.5}, {"max_records_per_finding": 0}):
            with self.subTest(options=options):
                with self.assertRaises(checker.CheckRefused):
                    self.check("arena-increment", directory, **options)
        code, out, _ = self.run_cli("--ngram-size", "1", "arena-increment", str(directory))
        self.assertEqual((code, out), (checker.EXIT_REFUSED, ""))

    # -- versioned evaluation sets ----------------------------------------------------

    def test_versioned_suites_flag_exactly_the_documented_arena_overlaps(self) -> None:
        tasks = json.loads(PRACTICE_SUITE.read_text(encoding="utf-8"))["tasks"]
        texts = [RECORD_TEMPLATE.format(prompt=t["prompt"], source=f"def {t['function_name']}(*args):\n    return None")
                 for t in tasks]
        directory = self.arena_increment(texts)
        code, out, _ = self.run_cli("arena-increment", str(directory), synthetic=False)
        self.assertEqual(code, checker.EXIT_OVERLAP)
        findings = json.loads(out)["findings"]
        known_e2_ids = {e2_id for e2_id, _ in KNOWN_OVERLAPS_PENDING_OWNER_DECISION.values()}
        self.assertEqual({f["eval_id"] for f in findings if f["level"] == "function_definition"}, known_e2_ids)
        self.assertEqual([f for f in findings if f["level"] in {"exact_prompt", "normalized_prompt"}], [])
        self.assertLessEqual({f["eval_id"] for f in findings}, known_e2_ids)

    def test_help_runs_as_a_file(self) -> None:
        completed = subprocess.run([sys.executable, "-B", "tools/check_evaluation_contamination.py", "--help"],
                                   cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
