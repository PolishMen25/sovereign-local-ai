from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parents[1]


def _load(name: str):
    path = PROJECT_ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load("generate_code_candidates")
RUNNER = _load("run_code_evaluation")
SUITE_PATH = PROJECT_ROOT / "configs" / "evaluation" / "core-python-e2.candidate.json"
DIGEST = "5" * 64


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self, *_args) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args) -> bool:
        return False


def answer(text: str, finish: str = "stop") -> dict:
    return {"choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 12}}


class ExtractionTests(unittest.TestCase):
    def test_fenced_python_block_is_extracted(self) -> None:
        source, unfenced = MODULE.extract_source("Sure!\n```python\ndef f():\n    return 1\n```\nDone.")
        self.assertEqual("def f():\n    return 1", source)
        self.assertFalse(unfenced)

    def test_unfenced_answer_is_kept_and_flagged(self) -> None:
        source, unfenced = MODULE.extract_source("def f():\n    return 1\n")
        self.assertEqual("def f():\n    return 1", source)
        self.assertTrue(unfenced)


class GenerationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reply = FakeResponse(answer("```python\ndef solution():\n    return 1\n```"))

    def _generate(self, directory: Path, **overrides):
        options = dict(suite_path=SUITE_PATH, output_dir=directory / "out",
                       endpoint="http://127.0.0.1:8790/v1/chat/completions",
                       api_key=None, model_name="fixture", weights_sha256=DIGEST,
                       max_tokens=64, temperature=0.0, seed=1, timeout=5)
        options.update(overrides)
        return MODULE.generate(**options)

    def test_each_task_is_asked_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MODULE.urllib.request, "urlopen", return_value=self.reply) as call:
                result = self._generate(Path(directory))
            tasks = json.loads(SUITE_PATH.read_text(encoding="utf-8"))["tasks"]
            self.assertEqual(len(tasks), call.call_count)
            self.assertEqual(len(tasks), result["totals"]["tasks"])

    def test_output_satisfies_the_evaluation_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MODULE.urllib.request, "urlopen", return_value=self.reply):
                result = self._generate(Path(directory))
            document = json.loads(Path(result["candidates_path"]).read_text(encoding="utf-8"))
            task_ids = {task["id"] for task in RUNNER.validate_suite(
                json.loads(SUITE_PATH.read_text(encoding="utf-8")))}
            name, digest, candidates = RUNNER.validate_candidates(document, task_ids)
            self.assertEqual("fixture", name)
            self.assertEqual(DIGEST, digest)
            self.assertEqual(task_ids, set(candidates))

    def test_engine_failure_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            with patch.object(MODULE.urllib.request, "urlopen", side_effect=OSError("boom")):
                with self.assertRaisesRegex(MODULE.GenerationRefused, "unavailable"):
                    self._generate(Path(directory))
            self.assertFalse(out.exists())

    def test_existing_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            out.mkdir()
            (out / "candidates.json").write_text("{}", encoding="utf-8")
            with patch.object(MODULE.urllib.request, "urlopen", return_value=self.reply):
                with self.assertRaisesRegex(MODULE.GenerationRefused, "already exists"):
                    self._generate(Path(directory))

    def test_metadata_never_contains_the_api_key(self) -> None:
        secret = "k" * 64
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MODULE.urllib.request, "urlopen", return_value=self.reply):
                result = self._generate(Path(directory), api_key=secret)
            for path in (result["candidates_path"], result["metadata_path"]):
                self.assertNotIn(secret, Path(path).read_text(encoding="utf-8"))

    def test_invalid_weights_digest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MODULE.GenerationRefused, "weights digest"):
                self._generate(Path(directory), weights_sha256="not-a-digest")

    def test_truncated_and_unfenced_answers_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = FakeResponse(answer("def solution():\n    return 1\n", finish="length"))
            with patch.object(MODULE.urllib.request, "urlopen", return_value=raw):
                result = self._generate(Path(directory))
            totals = result["totals"]
            self.assertEqual(totals["tasks"], totals["unfenced"])
            self.assertEqual(totals["tasks"], totals["truncated"])


class ApiKeyFileTests(unittest.TestCase):
    def test_missing_or_empty_key_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent"
            with self.assertRaisesRegex(MODULE.GenerationRefused, "api key file"):
                MODULE.read_api_key(missing)
            empty = Path(directory) / "empty"
            empty.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.GenerationRefused, "api key file"):
                MODULE.read_api_key(empty)

    def test_no_key_file_means_no_authorisation_header(self) -> None:
        self.assertIsNone(MODULE.read_api_key(None))


if __name__ == "__main__":
    unittest.main()
