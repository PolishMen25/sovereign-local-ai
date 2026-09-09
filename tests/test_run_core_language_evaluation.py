import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.inference.runtime import InferenceUnavailable
from tools.run_core_language_evaluation import (
    RECEIPT_NAME,
    RESULTS_NAME,
    REVIEW_NAME,
    run_evaluation,
)


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "configs" / "evaluation" / "core-30m-e1.candidate.json"


class ReadyRuntime:
    def __init__(self, *args, **kwargs):
        self.calls = []

    class Status:
        generation_available = True

    def status(self):
        return self.Status()

    def generate(self, prompt, *, max_new_tokens, seed):
        self.calls.append((prompt, max_new_tokens, seed))
        return {"engine": "CORE-30M", "experimental": True, "answer": "bounded response"}


class CoreLanguageEvaluationTests(unittest.TestCase):
    def inputs(self, directory: Path) -> dict[str, Path]:
        paths = {name: directory / f"{name}.bin" for name in ("checkpoint", "config", "tokenizer", "manifest", "preflight")}
        for name, path in paths.items():
            path.write_bytes(name.encode("ascii"))
        paths["suite"] = SUITE
        paths["output"] = directory / "result"
        return paths

    def test_writes_complete_immutable_owner_review_package(self):
        with tempfile.TemporaryDirectory() as directory, patch("tools.run_core_language_evaluation.LocalInferenceRuntime", ReadyRuntime):
            paths = self.inputs(Path(directory))
            receipt = run_evaluation(
                suite_path=paths["suite"], checkpoint_path=paths["checkpoint"], config_path=paths["config"],
                tokenizer_path=paths["tokenizer"], manifest_path=paths["manifest"], preflight_path=paths["preflight"],
                output_dir=paths["output"], seed=7, max_new_tokens=12,
            )
            self.assertEqual(receipt["response_count"], 50)
            rows = [json.loads(line) for line in (paths["output"] / RESULTS_NAME).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 50)
            self.assertEqual({row["seed"] for row in rows}, {7})
            review = json.loads((paths["output"] / REVIEW_NAME).read_text(encoding="utf-8"))
            self.assertTrue(all(item["decision"] is None for item in review["decisions"]))
            written = json.loads((paths["output"] / RECEIPT_NAME).read_text(encoding="utf-8"))
            self.assertEqual(written["responses_sha256"], receipt["responses_sha256"])

    def test_refuses_preexisting_destination_before_runtime(self):
        with tempfile.TemporaryDirectory() as directory, patch("tools.run_core_language_evaluation.LocalInferenceRuntime") as runtime:
            paths = self.inputs(Path(directory))
            paths["output"].mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                run_evaluation(
                    suite_path=paths["suite"], checkpoint_path=paths["checkpoint"], config_path=paths["config"],
                    tokenizer_path=paths["tokenizer"], manifest_path=paths["manifest"], preflight_path=paths["preflight"],
                    output_dir=paths["output"], seed=7, max_new_tokens=12,
                )
            runtime.assert_not_called()

    def test_refuses_non_ready_checkpoint_without_output(self):
        class NotReadyRuntime(ReadyRuntime):
            class Status:
                generation_available = False

        with tempfile.TemporaryDirectory() as directory, patch("tools.run_core_language_evaluation.LocalInferenceRuntime", NotReadyRuntime):
            paths = self.inputs(Path(directory))
            with self.assertRaisesRegex(InferenceUnavailable, "checkpoint contract"):
                run_evaluation(
                    suite_path=paths["suite"], checkpoint_path=paths["checkpoint"], config_path=paths["config"],
                    tokenizer_path=paths["tokenizer"], manifest_path=paths["manifest"], preflight_path=paths["preflight"],
                    output_dir=paths["output"], seed=7, max_new_tokens=12,
                )
            self.assertFalse(paths["output"].exists())


if __name__ == "__main__":
    unittest.main()
