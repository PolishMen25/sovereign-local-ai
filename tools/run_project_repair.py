#!/usr/bin/env python3
"""Run a project's tests, read the failure, repair one file, run them again.

The agent never touches the original project. It works on a copy, and the only
thing it hands back is a diff for a human to approve. It refuses to run on a
directory that contains a .git, because that is almost certainly a live
checkout rather than the copy it was meant to receive.

It asks the model for the complete corrected file rather than a patch. Small
models are reliable at rewriting a file and unreliable at producing a unified
diff that applies; the diff you review is computed here, from the two versions,
so it is always exact.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import generate_code_candidates as generation  # noqa: E402
from tools import run_code_evaluation as evaluation  # noqa: E402

REPORT_SCHEMA = "project-repair-report.v1"
FAILURE_BYTES = 6000
SOURCE_BYTES = 60_000
FILE_IN_TRACEBACK = re.compile(r'File "([^"]+\.py)"')
REPAIR = (
    "You are fixing a bug in an existing Python project.\n\n"
    "Running the test suite produced:\n```\n{failure}\n```\n\n"
    "Here is the complete current content of {path}:\n```python\n{source}\n```\n\n"
    "Rewrite the complete file with the bug fixed. Answer with a single Python code "
    "block containing the entire file and nothing else. Change as little as possible, "
    "keep every behaviour the tests do not exercise, and do not add or modify tests.\n"
)


class ProjectRepairRefused(ValueError):
    """Raised when a repair run cannot meet its contract."""


def sandbox_command(binary: str, workdir: Path, command: str) -> list[str]:
    return [
        binary, "--unshare-all", "--unshare-net", "--die-with-parent", "--new-session",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
        "--bind", str(workdir), "/work", "--chdir", "/work", "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "HOME", "/tmp",
        "--", "/bin/sh", "-c", command,
    ]


def run_tests(binary: str, *, project: Path, command: str, budget: int,
              seconds: int) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".log") as output:
        timed_out = False
        process = subprocess.Popen(
            sandbox_command(binary, project, command), stdout=output,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            preexec_fn=lambda: evaluation.limit_resources(budget))
        try:
            returncode = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            returncode = process.wait()
        text = Path(output.name).read_text(encoding="utf-8", errors="replace")
    return {"passed": returncode == 0 and not timed_out, "returncode": returncode,
            "timed_out": timed_out, "output": text.strip()}


def candidate_file(failure: str, project: Path) -> Path | None:
    """The deepest project file named in the traceback, tests excluded."""
    seen: list[Path] = []
    for raw in FILE_IN_TRACEBACK.findall(failure):
        name = raw.replace("/work/", "", 1).lstrip("/")
        path = (project / name).resolve()
        try:
            path.relative_to(project.resolve())
        except ValueError:
            continue
        if not path.is_file() or "test" in path.name:
            continue
        if path not in seen:
            seen.append(path)
    return seen[-1] if seen else None


def failure_touches_project(failure: str, project: Path) -> bool:
    """True when the traceback names any file of the project, tests included.

    A failure that names only the standard library is a collection or import
    error, not a test result. Repairing a project file in answer to it would be
    guesswork, so the run stops instead.
    """
    for raw in FILE_IN_TRACEBACK.findall(failure):
        name = raw.replace("/work/", "", 1).lstrip("/")
        candidate = (project / name).resolve()
        try:
            candidate.relative_to(project.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return True
    return False


def choose_target(failure: str, project: Path, focus: list[Path],
                  attempted: set[Path]) -> Path | None:
    """Prefer the file the failure names; otherwise the next file the human allowed."""
    named = candidate_file(failure, project)
    if named is not None and (not focus or named in focus):
        return named
    for path in focus:
        if path not in attempted:
            return path
    return None


def repair_file(path: Path, failure: str, *, project: Path, endpoint: str,
                api_key: str | None, max_tokens: int, temperature: float,
                seed: int, timeout: int) -> tuple[str, float]:
    source = path.read_text(encoding="utf-8")
    if len(source.encode("utf-8")) > SOURCE_BYTES:
        raise ProjectRepairRefused(f"{path} is too large to repair in one pass")
    prompt = REPAIR.format(failure=failure[-FAILURE_BYTES:] or "(no output)",
                           path=path.relative_to(project), source=source)
    document, duration = generation.request_completion(
        endpoint=endpoint, api_key=api_key, prompt=prompt, max_tokens=max_tokens,
        temperature=temperature, seed=seed, timeout=timeout)
    try:
        answer = document["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ProjectRepairRefused("engine returned an invalid response") from error
    fixed, unfenced = generation.extract_source(answer)
    if unfenced or not fixed.strip():
        raise ProjectRepairRefused("engine did not return a fenced file")
    return fixed.rstrip() + "\n", duration


def repair_project(*, project: Path, command: str, output_dir: Path, endpoint: str,
                   api_key: str | None, max_repairs: int, max_tokens: int,
                   temperature: float, seed: int, timeout: int,
                   test_seconds: int, focus: list[Path] | None = None) -> dict[str, Any]:
    project = project.resolve()
    if not project.is_dir():
        raise ProjectRepairRefused("project directory does not exist")
    if (project / ".git").exists():
        raise ProjectRepairRefused(
            "project contains a .git: point this tool at an exported copy, not a checkout")
    if max_repairs < 1:
        raise ProjectRepairRefused("repair budget must be at least one")
    allowed: list[Path] = []
    for entry in focus or []:
        path = (project / entry).resolve() if not entry.is_absolute() else entry.resolve()
        try:
            path.relative_to(project)
        except ValueError as error:
            raise ProjectRepairRefused(f"focus file is outside the project: {entry}") from error
        if not path.is_file():
            raise ProjectRepairRefused(f"focus file does not exist: {entry}")
        if "test" in path.name:
            raise ProjectRepairRefused(f"the agent may never edit a test file: {entry}")
        allowed.append(path)

    binary = evaluation.require_sandbox()
    budget = evaluation.process_limit()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "project-repair-report.json"
    diff_path = output_dir / "proposed.diff"
    for path in (report_path, diff_path):
        if path.exists():
            raise ProjectRepairRefused(f"destination already exists: {path}")

    originals: dict[Path, str] = {}
    attempted: set[Path] = set()
    rounds: list[dict[str, Any]] = []
    spent = 0.0
    outcome = run_tests(binary, project=project, command=command, budget=budget,
                        seconds=test_seconds)
    rounds.append({"round": 0, "repaired": None, "passed": outcome["passed"],
                   "returncode": outcome["returncode"], "timed_out": outcome["timed_out"],
                   "last_line": outcome["output"].splitlines()[-1][:200] if outcome["output"] else ""})

    if not outcome["passed"] and not failure_touches_project(outcome["output"], project):
        raise ProjectRepairRefused(
            "the failure names no file of the project: this looks like a collection or "
            "import error, not a test result. Fix the test command first.")

    for index in range(max_repairs):
        if outcome["passed"]:
            break
        target = choose_target(outcome["output"], project, allowed, attempted)
        if target is None:
            rounds.append({"round": index + 1, "repaired": None,
                           "refused": "no editable file identified; pass --focus to name one"})
            break
        attempted.add(target)
        originals.setdefault(target, target.read_text(encoding="utf-8"))
        fixed, duration = repair_file(
            target, outcome["output"], project=project, endpoint=endpoint,
            api_key=api_key, max_tokens=max_tokens, temperature=temperature,
            seed=seed, timeout=timeout)
        spent += duration
        target.write_text(fixed, encoding="utf-8")
        outcome = run_tests(binary, project=project, command=command, budget=budget,
                            seconds=test_seconds)
        rounds.append({"round": index + 1, "repaired": str(target.relative_to(project)),
                       "repair_seconds": round(duration, 2), "passed": outcome["passed"],
                       "returncode": outcome["returncode"], "timed_out": outcome["timed_out"],
                       "last_line": outcome["output"].splitlines()[-1][:200] if outcome["output"] else ""})

    diff_lines: list[str] = []
    for path, before in sorted(originals.items()):
        after = path.read_text(encoding="utf-8")
        name = str(path.relative_to(project))
        diff_lines.extend(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{name}", tofile=f"b/{name}"))
    diff_path.write_text("".join(diff_lines), encoding="utf-8")

    report = {"schema_version": REPORT_SCHEMA,
              "project": str(project), "test_command": command,
              "repair_budget": max_repairs,
              "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "files_changed": sorted(str(p.relative_to(project)) for p in originals),
              "editable_files": sorted(str(p.relative_to(project)) for p in allowed) or None,
              "repair_seconds": round(spent, 1),
              "initial_pass": rounds[0]["passed"], "final_pass": outcome["passed"],
              "rounds": rounds,
              "note": ("the diff is computed from the two file versions, not produced by "
                       "the model; nothing outside the project copy was touched")}
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--max-repairs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--test-seconds", type=int, default=180)
    parser.add_argument("--focus", type=Path, action="append", default=[],
                        help="file the agent may modify; repeatable, never a test file")
    args = parser.parse_args(argv)
    try:
        report = repair_project(
            project=args.project, command=args.test_command, output_dir=args.output_dir,
            endpoint=args.endpoint, api_key=generation.read_api_key(args.api_key_file),
            max_repairs=args.max_repairs, max_tokens=args.max_tokens,
            temperature=args.temperature, seed=args.seed, timeout=args.timeout,
            test_seconds=args.test_seconds, focus=args.focus)
    except (OSError, ProjectRepairRefused, evaluation.EvaluationRefused,
            generation.GenerationRefused) as error:
        print(f"project repair refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"initial_pass": report["initial_pass"],
                      "final_pass": report["final_pass"],
                      "files_changed": report["files_changed"],
                      "repair_seconds": report["repair_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
