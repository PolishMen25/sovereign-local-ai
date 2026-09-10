from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "tools" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load("run_code_agent_loop")
RUNNER = _load("run_code_evaluation")
SUITE_PATH = PROJECT_ROOT / "configs" / "evaluation" / "core-python-e2.candidate.json"
DIGEST = "7" * 64


def candidates_file(directory: Path) -> Path:
    tasks = json.loads(SUITE_PATH.read_text(encoding="utf-8"))["tasks"]
    document = {"schema_version": "core-code-evaluation-candidates.v1",
                "model_name": "fixture", "checkpoint_sha256": DIGEST,
                "candidates": [{"task_id": t["id"], "source": "def broken():\n    return 0\n"}
                               for t in tasks]}
    path = directory / "candidates.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def failing(*_args, **_kwargs) -> dict:
    return {"passed": False, "returncode": 1, "timed_out": False,
            "failure": "Traceback (most recent call last):\nAssertionError"}


def passing(*_args, **_kwargs) -> dict:
    return {"passed": True, "returncode": 0, "timed_out": False, "failure": ""}


class AgentLoopTests(unittest.TestCase):
    def _run(self, directory: Path, execute, repairs: int = 1, **overrides):
        options = dict(suite_path=SUITE_PATH, candidates_path=candidates_file(directory),
                       output_dir=directory / "out",
                       endpoint="http://127.0.0.1:8790/v1/chat/completions",
                       api_key=None, max_repairs=repairs, max_tokens=64,
                       temperature=0.0, seed=1, timeout=5)
        options.update(overrides)
        with (patch.object(MODULE.evaluation, "require_sandbox", return_value="/usr/bin/bwrap"),
              patch.object(MODULE.evaluation, "process_limit", return_value=999),
              patch.object(MODULE, "execute", side_effect=execute),
              patch.object(MODULE, "repair", return_value=("def fixed():\n    return 1\n", 0.4))):
            return MODULE.run_loop(**options)

    def test_first_pass_and_final_pass_are_reported_separately(self) -> None:
        calls = {"n": 0}

        def once_then_fixed(*args, **kwargs):
            calls["n"] += 1
            return failing() if calls["n"] % 2 == 1 else passing()

        with tempfile.TemporaryDirectory() as directory:
            report = self._run(Path(directory), once_then_fixed)
        totals = report["totals"]
        self.assertEqual(0, totals["first_pass"])
        self.assertEqual(totals["tasks"], totals["final_pass"])
        self.assertIn("first_pass measures the model", report["caveat"])

    def test_a_zero_repair_budget_never_calls_the_engine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MODULE, "repair") as repair:
                report = self._run(Path(directory), failing, repairs=0)
            repair.assert_not_called()
        self.assertEqual(0, report["totals"]["final_pass"])
        self.assertEqual(0, report["repair_budget"])

    def test_a_passing_candidate_is_never_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MODULE, "repair") as repair:
                report = self._run(Path(directory), passing)
            repair.assert_not_called()
        self.assertEqual(report["totals"]["tasks"], report["totals"]["first_pass"])

    def test_final_candidates_satisfy_the_official_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._run(Path(directory), passing)
            document = json.loads((Path(directory) / "out" / "candidates.json").read_text(encoding="utf-8"))
        task_ids = {t["id"] for t in RUNNER.validate_suite(
            json.loads(SUITE_PATH.read_text(encoding="utf-8")))}
        _name, digest, sources = RUNNER.validate_candidates(document, task_ids)
        self.assertEqual(DIGEST, digest)
        self.assertEqual(task_ids, set(sources))

    def test_negative_budget_and_existing_destination_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MODULE.LoopRefused, "budget"):
                self._run(Path(directory), passing, repairs=-1)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            out.mkdir()
            (out / "agent-loop-report.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.LoopRefused, "already exists"):
                self._run(Path(directory), passing)


if __name__ == "__main__":
    unittest.main()
