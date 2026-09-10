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


MODULE = _load("run_project_repair")


def make_project(root: Path) -> Path:
    project = root / "copy"
    (project / "pkg").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "pkg" / "money.py").write_text("def total(x):\n    return x\n", encoding="utf-8")
    (project / "tests" / "test_money.py").write_text("assert True\n", encoding="utf-8")
    return project


class GuardTests(unittest.TestCase):
    def _repair(self, project: Path, out: Path, **overrides):
        options = dict(project=project, command="true", output_dir=out,
                       endpoint="http://127.0.0.1:8790/v1/chat/completions",
                       api_key=None, max_repairs=1, max_tokens=64, temperature=0.0,
                       seed=1, timeout=5, test_seconds=5)
        options.update(overrides)
        return MODULE.repair_project(**options)

    def test_a_checkout_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            (project / ".git").mkdir()
            with self.assertRaisesRegex(MODULE.ProjectRepairRefused, "exported copy"):
                self._repair(project, Path(directory) / "out")

    def test_a_test_file_can_never_be_made_editable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            with self.assertRaisesRegex(MODULE.ProjectRepairRefused, "never edit a test file"):
                self._repair(project, Path(directory) / "out",
                             focus=[Path("tests/test_money.py")])

    def test_a_focus_file_outside_the_project_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            with self.assertRaisesRegex(MODULE.ProjectRepairRefused, "outside the project"):
                self._repair(project, Path(directory) / "out", focus=[Path("/etc/passwd")])

    def test_a_budget_below_one_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            with self.assertRaisesRegex(MODULE.ProjectRepairRefused, "at least one"):
                self._repair(project, Path(directory) / "out", max_repairs=0)


class TargetSelectionTests(unittest.TestCase):
    def test_the_failing_source_file_is_preferred_over_the_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            failure = ('Traceback (most recent call last):\n'
                       '  File "/work/tests/test_money.py", line 3, in test\n'
                       '  File "/work/pkg/money.py", line 2, in total\n'
                       'TypeError\n')
            chosen = MODULE.choose_target(failure, project.resolve(), [], set())
            self.assertEqual("money.py", chosen.name)

    def test_an_assertion_failure_falls_back_to_the_allowed_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            failure = ('  File "/work/tests/test_money.py", line 3, in test\n'
                       'AssertionError: 12 != 10\n')
            allowed = [(project / "pkg" / "money.py").resolve()]
            chosen = MODULE.choose_target(failure, project.resolve(), allowed, set())
            self.assertEqual(allowed[0], chosen)

    def test_an_already_attempted_file_is_not_retried_forever(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            allowed = [(project / "pkg" / "money.py").resolve()]
            chosen = MODULE.choose_target("AssertionError\n", project.resolve(),
                                          allowed, set(allowed))
            self.assertIsNone(chosen)


class CollectionErrorTests(unittest.TestCase):
    def test_a_failure_naming_no_project_file_stops_the_run(self) -> None:
        collection_error = {
            "passed": False, "returncode": 1, "timed_out": False,
            "output": ('Traceback (most recent call last):\n'
                       '  File "/usr/lib/python3.11/unittest/loader.py", line 320, in discover\n'
                       "ImportError: Start directory is not importable: '/work/tests'\n")}
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            with (patch.object(MODULE.evaluation, "require_sandbox", return_value="/usr/bin/bwrap"),
                  patch.object(MODULE.evaluation, "process_limit", return_value=999),
                  patch.object(MODULE, "run_tests", return_value=collection_error),
                  patch.object(MODULE, "repair_file") as repair):
                with self.assertRaisesRegex(MODULE.ProjectRepairRefused, "collection or import error"):
                    MODULE.repair_project(
                        project=project, command="true", output_dir=Path(directory) / "out",
                        endpoint="http://127.0.0.1:8790/v1/chat/completions", api_key=None,
                        max_repairs=2, max_tokens=64, temperature=0.0, seed=1, timeout=5,
                        test_seconds=5, focus=[Path("pkg/money.py")])
            repair.assert_not_called()

    def test_a_real_test_failure_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            failure = ('  File "/work/tests/test_money.py", line 3, in test\n'
                       'AssertionError: 12 != 10\n')
            self.assertTrue(MODULE.failure_touches_project(failure, project.resolve()))


class RepairFlowTests(unittest.TestCase):
    def test_a_successful_repair_produces_an_exact_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            out = Path(directory) / "out"
            target = project / "pkg" / "money.py"
            outcomes = [
                {"passed": False, "returncode": 1, "timed_out": False,
                 "output": 'File "/work/tests/test_money.py", line 3\nAssertionError'},
                {"passed": True, "returncode": 0, "timed_out": False, "output": ""},
            ]
            with (patch.object(MODULE.evaluation, "require_sandbox", return_value="/usr/bin/bwrap"),
                  patch.object(MODULE.evaluation, "process_limit", return_value=999),
                  patch.object(MODULE, "run_tests", side_effect=outcomes),
                  patch.object(MODULE, "repair_file",
                               return_value=("def total(x):\n    return x * 2\n", 1.0))):
                report = MODULE.repair_project(
                    project=project, command="true", output_dir=out,
                    endpoint="http://127.0.0.1:8790/v1/chat/completions", api_key=None,
                    max_repairs=1, max_tokens=64, temperature=0.0, seed=1, timeout=5,
                    test_seconds=5, focus=[Path("pkg/money.py")])
            self.assertFalse(report["initial_pass"])
            self.assertTrue(report["final_pass"])
            self.assertEqual(["pkg/money.py"], report["files_changed"])
            self.assertEqual("def total(x):\n    return x * 2\n",
                             target.read_text(encoding="utf-8"))
            diff = (out / "proposed.diff").read_text(encoding="utf-8")
            self.assertIn("-    return x", diff)
            self.assertIn("+    return x * 2", diff)

    def test_a_passing_suite_is_never_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = make_project(Path(directory))
            passing = {"passed": True, "returncode": 0, "timed_out": False, "output": ""}
            with (patch.object(MODULE.evaluation, "require_sandbox", return_value="/usr/bin/bwrap"),
                  patch.object(MODULE.evaluation, "process_limit", return_value=999),
                  patch.object(MODULE, "run_tests", return_value=passing),
                  patch.object(MODULE, "repair_file") as repair):
                report = MODULE.repair_project(
                    project=project, command="true", output_dir=Path(directory) / "out",
                    endpoint="http://127.0.0.1:8790/v1/chat/completions", api_key=None,
                    max_repairs=3, max_tokens=64, temperature=0.0, seed=1, timeout=5,
                    test_seconds=5)
            repair.assert_not_called()
            self.assertEqual([], report["files_changed"])


if __name__ == "__main__":
    unittest.main()
