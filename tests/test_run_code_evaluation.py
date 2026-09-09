from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "tools" / "run_code_evaluation.py"
SPEC = importlib.util.spec_from_file_location("run_code_evaluation", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SUITE_PATH = PROJECT_ROOT / "configs" / "evaluation" / "core-python-e2.candidate.json"


class CodeEvaluationSuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))

    def test_candidate_suite_has_fifty_distinct_python_tasks(self) -> None:
        tasks = MODULE.validate_suite(self.suite)
        self.assertEqual(50, len(tasks))
        self.assertEqual(50, len({task["id"] for task in tasks}))

    def test_suite_refuses_an_extra_task_or_wrong_status(self) -> None:
        changed = json.loads(json.dumps(self.suite))
        changed["tasks"].append(changed["tasks"][0])
        with self.assertRaisesRegex(MODULE.EvaluationRefused, "fifty tasks"):
            MODULE.validate_suite(changed)
        changed = json.loads(json.dumps(self.suite))
        changed["status"] = "approved"
        with self.assertRaisesRegex(MODULE.EvaluationRefused, "contract"):
            MODULE.validate_suite(changed)

    def test_candidates_must_cover_each_task_once_and_bind_a_checkpoint(self) -> None:
        task_ids = {task["id"] for task in self.suite["tasks"]}
        document = {
            "schema_version": MODULE.CANDIDATES_SCHEMA,
            "model_name": "fixture",
            "checkpoint_sha256": "a" * 64,
            "candidates": [{"task_id": task_id, "source": "def example():\n    return 1\n"} for task_id in sorted(task_ids)],
        }
        model_name, digest, candidates = MODULE.validate_candidates(document, task_ids)
        self.assertEqual("fixture", model_name)
        self.assertEqual("a" * 64, digest)
        self.assertEqual(task_ids, set(candidates))
        document["candidates"][1]["task_id"] = document["candidates"][0]["task_id"]
        with self.assertRaisesRegex(MODULE.EvaluationRefused, "task id"):
            MODULE.validate_candidates(document, task_ids)

    def test_sandbox_command_has_network_and_filesystem_isolation(self) -> None:
        command = MODULE.sandbox_command("/usr/bin/bwrap", Path("/safe/work"))
        self.assertIn("--unshare-all", command)
        self.assertIn("--unshare-net", command)
        self.assertIn("--ro-bind", command)
        self.assertIn("--bind", command)
        self.assertIn("--clearenv", command)
        self.assertIn("/work", command)

    def test_report_contains_hashes_and_verdicts_but_no_candidate_text(self) -> None:
        candidates = {
            "schema_version": MODULE.CANDIDATES_SCHEMA,
            "model_name": "fixture",
            "checkpoint_sha256": "b" * 64,
            "candidates": [{"task_id": task["id"], "source": "private candidate text"} for task in self.suite["tasks"]],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite_path, candidates_path, output_dir = root / "suite.json", root / "candidates.json", root / "out"
            suite_path.write_text(json.dumps(self.suite), encoding="utf-8")
            candidates_path.write_text(json.dumps(candidates), encoding="utf-8")
            result = {"task_id": self.suite["tasks"][0]["id"], "prompt_sha256": "1" * 64, "test_sha256": "2" * 64, "candidate_sha256": "3" * 64, "output_sha256": "4" * 64, "output_bytes": 0, "returncode": 0, "timed_out": False, "verdict": "accept"}
            with patch.object(MODULE, "require_sandbox", return_value="/usr/bin/bwrap"), patch.object(MODULE, "run_task", side_effect=[dict(result, task_id=task["id"]) for task in self.suite["tasks"]]):
                report = MODULE.evaluate(suite_path=suite_path, candidates_path=candidates_path, output_dir=output_dir)
            report_text = (output_dir / "code-evaluation-report.json").read_text(encoding="utf-8")
            self.assertEqual(50, report["accepted"])
            self.assertNotIn("private candidate text", report_text)
            self.assertNotIn(self.suite["tasks"][0]["prompt"], report_text)


if __name__ == "__main__":
    unittest.main()
