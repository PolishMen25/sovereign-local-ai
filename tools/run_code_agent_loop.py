#!/usr/bin/env python3
"""Write code, run its tests, read the failure, fix it once.

This is the agent loop, and it is deliberately NOT the scorer. The scorer in
tools/run_code_evaluation.py asks each task once and never retries, because that
is what measures a model. This loop retries, because that is what an engineer
does. Its report labels both numbers separately so they can never be confused:
`first_pass` is what the model knew, `final_pass` is what the loop achieved.

The loop sees the failing traceback, exactly as an agent running a project's
tests would. That is the point, and it is also the caveat.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import generate_code_candidates as generation  # noqa: E402
from tools import run_code_evaluation as evaluation  # noqa: E402

LOOP_SCHEMA = "core-code-agent-loop-report.v1"
FEEDBACK_BYTES = 4000
RUNNER_SOURCE = (
    "import runpy\nfrom pathlib import Path\n"
    "module = runpy.run_path('candidate.py')\n"
    "source = Path('tests.py').read_text(encoding='utf-8')\n"
    "exec(compile(source, 'tests.py', 'exec'), {'module': module})\n"
)
REPAIR = (
    "You are a Python programmer. Your previous answer failed its tests.\n"
    "Fix the function. Answer with a single Python code block and nothing else.\n"
    "No tests, no explanation.\n\n"
    "Task: {prompt}\n\n"
    "Your previous answer:\n```python\n{source}\n```\n\n"
    "Running the tests produced:\n```\n{failure}\n```\n"
)


class LoopRefused(ValueError):
    """Raised when the loop cannot meet its contract."""


def execute(binary: str, *, task: dict[str, str], source: str, workspace: Path,
            process_budget: int) -> dict[str, Any]:
    """Run one candidate against its tests and keep what the sandbox printed."""
    with tempfile.TemporaryDirectory(prefix="loop-", dir=workspace) as temporary:
        workdir = Path(temporary)
        (workdir / "candidate.py").write_text(source, encoding="utf-8")
        (workdir / "tests.py").write_text(task["test_source"], encoding="utf-8")
        (workdir / "runner.py").write_text(RUNNER_SOURCE, encoding="utf-8")
        output_path = workdir / "output.log"
        timed_out = False
        with output_path.open("wb") as output:
            process = subprocess.Popen(
                evaluation.sandbox_command(binary, workdir), stdout=output,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                preexec_fn=lambda: evaluation.limit_resources(process_budget))
            try:
                returncode = process.wait(timeout=evaluation.WALL_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                returncode = process.wait()
        failure = output_path.read_text(encoding="utf-8", errors="replace")
    return {"passed": returncode == 0 and not timed_out, "returncode": returncode,
            "timed_out": timed_out, "failure": failure.strip()}


def repair(task: dict[str, str], source: str, failure: str, *, endpoint: str,
           api_key: str | None, max_tokens: int, temperature: float, seed: int,
           timeout: int) -> tuple[str, float]:
    prompt = REPAIR.format(prompt=task["prompt"], source=source,
                           failure=failure[-FEEDBACK_BYTES:] or "(no output)")
    document, duration = generation.request_completion(
        endpoint=endpoint, api_key=api_key, prompt=prompt, max_tokens=max_tokens,
        temperature=temperature, seed=seed, timeout=timeout)
    try:
        answer = document["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise LoopRefused("engine returned an invalid response") from error
    fixed, _ = generation.extract_source(answer)
    return fixed or source, duration


def run_loop(*, suite_path: Path, candidates_path: Path, output_dir: Path,
             endpoint: str, api_key: str | None, max_repairs: int,
             max_tokens: int, temperature: float, seed: int,
             timeout: int) -> dict[str, Any]:
    if max_repairs < 0:
        raise LoopRefused("repair budget cannot be negative")
    suite = evaluation.read_json(suite_path)
    tasks = evaluation.validate_suite(suite)
    document = evaluation.read_json(candidates_path)
    model_name, weights_sha256, sources = evaluation.validate_candidates(
        document, {task["id"] for task in tasks})

    binary = evaluation.require_sandbox()
    budget = evaluation.process_limit()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "agent-loop-report.json"
    final_path = output_dir / "candidates.json"
    for path in (report_path, final_path):
        if path.exists():
            raise LoopRefused(f"destination already exists: {path}")

    results: list[dict[str, Any]] = []
    final: dict[str, str] = {}
    spent = 0.0
    with tempfile.TemporaryDirectory(prefix="agent-loop-") as workspace:
        for task in tasks:
            source = sources[task["id"]]
            attempts: list[dict[str, Any]] = []
            outcome = execute(binary, task=task, source=source,
                              workspace=Path(workspace), process_budget=budget)
            attempts.append({"attempt": 1, "repaired": False,
                             "passed": outcome["passed"],
                             "returncode": outcome["returncode"],
                             "timed_out": outcome["timed_out"],
                             "failure_head": outcome["failure"].splitlines()[-1][:200]
                             if outcome["failure"] else ""})
            for round_index in range(max_repairs):
                if outcome["passed"]:
                    break
                source, duration = repair(
                    task, source, outcome["failure"], endpoint=endpoint,
                    api_key=api_key, max_tokens=max_tokens,
                    temperature=temperature, seed=seed, timeout=timeout)
                spent += duration
                outcome = execute(binary, task=task, source=source,
                                  workspace=Path(workspace), process_budget=budget)
                attempts.append({"attempt": round_index + 2, "repaired": True,
                                 "passed": outcome["passed"],
                                 "returncode": outcome["returncode"],
                                 "timed_out": outcome["timed_out"],
                                 "repair_seconds": round(duration, 2),
                                 "failure_head": outcome["failure"].splitlines()[-1][:200]
                                 if outcome["failure"] else ""})
            final[task["id"]] = source
            results.append({"task_id": task["id"],
                            "first_pass": attempts[0]["passed"],
                            "final_pass": outcome["passed"],
                            "attempts": attempts})

    report = {
        "schema_version": LOOP_SCHEMA,
        "suite_sha256": evaluation.sha256_file(suite_path),
        "input_candidates_sha256": evaluation.sha256_file(candidates_path),
        "model_name": model_name, "checkpoint_sha256": weights_sha256,
        "repair_budget": max_repairs,
        "caveat": ("the loop is shown the failing traceback, which includes the failing "
                   "assertion; first_pass measures the model, final_pass measures the loop"),
        "totals": {"tasks": len(tasks),
                   "first_pass": sum(r["first_pass"] for r in results),
                   "final_pass": sum(r["final_pass"] for r in results),
                   "repair_seconds": round(spent, 1)},
        "results": results,
    }
    final_document = {"schema_version": generation.CANDIDATES_SCHEMA,
                      "model_name": model_name + f"-loop{max_repairs}",
                      "checkpoint_sha256": weights_sha256,
                      "candidates": [{"task_id": k, "source": v} for k, v in sorted(final.items())]}
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    final_path.write_text(json.dumps(final_document, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--max-repairs", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        report = run_loop(
            suite_path=args.suite, candidates_path=args.candidates,
            output_dir=args.output_dir, endpoint=args.endpoint,
            api_key=generation.read_api_key(args.api_key_file),
            max_repairs=args.max_repairs, max_tokens=args.max_tokens,
            temperature=args.temperature, seed=args.seed, timeout=args.timeout)
    except (OSError, LoopRefused, evaluation.EvaluationRefused,
            generation.GenerationRefused) as error:
        print(f"agent loop refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report["totals"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
