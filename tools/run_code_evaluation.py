#!/usr/bin/env python3
"""Evaluate supplied Python candidates in a fail-closed offline sandbox."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

try:  # The runner is Linux-only; keeping importable supports static tests elsewhere.
    import resource
except ImportError:  # pragma: no cover - Windows cannot run the sandbox.
    resource = None  # type: ignore[assignment]


SUITE_SCHEMA = "core-code-evaluation-suite.v1"
CANDIDATES_SCHEMA = "core-code-evaluation-candidates.v1"
REPORT_SCHEMA = "core-code-evaluation-report.v1"
SUITE_STATUS = "candidate_owner_review_required"
TASK_ID = re.compile(r"^python-(?:0[1-9]|10)-[a-z-]+$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
TASK_COUNT = 10
CPU_SECONDS = 10
MEMORY_BYTES = 512 * 1024 * 1024
OUTPUT_BYTES = 64 * 1024 * 1024
WALL_SECONDS = 12


class EvaluationRefused(ValueError):
    """Raised when an evaluation cannot meet its fixed safety contract."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationRefused("evaluation JSON is unavailable or invalid") from error
    if not isinstance(value, dict):
        raise EvaluationRefused("evaluation JSON must contain an object")
    return value


def validate_suite(document: Any) -> list[dict[str, str]]:
    if not isinstance(document, dict) or set(document) != {
        "schema_version", "status", "language", "execution", "tasks"
    }:
        raise EvaluationRefused("evaluation suite keys are invalid")
    if (
        document["schema_version"] != SUITE_SCHEMA
        or document["status"] != SUITE_STATUS
        or document["language"] != "python"
        or document["execution"] != "isolated_external_tests"
    ):
        raise EvaluationRefused("evaluation suite contract is invalid")
    tasks = document["tasks"]
    if not isinstance(tasks, list) or len(tasks) != TASK_COUNT:
        raise EvaluationRefused("evaluation suite must contain exactly ten tasks")
    identifiers: set[str] = set()
    validated: list[dict[str, str]] = []
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {
            "id", "function_name", "prompt", "test_source"
        }:
            raise EvaluationRefused("evaluation task shape is invalid")
        identifier = task["id"]
        if not isinstance(identifier, str) or TASK_ID.fullmatch(identifier) is None or identifier in identifiers:
            raise EvaluationRefused("evaluation task id is invalid")
        if not all(isinstance(task[key], str) for key in ("function_name", "prompt", "test_source")):
            raise EvaluationRefused("evaluation task fields are invalid")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", task["function_name"]):
            raise EvaluationRefused("evaluation function name is invalid")
        if not 12 <= len(task["prompt"]) <= 800 or task["prompt"] != task["prompt"].strip():
            raise EvaluationRefused("evaluation prompt is invalid")
        if not 1 <= len(task["test_source"]) <= 16_384:
            raise EvaluationRefused("evaluation test source is invalid")
        identifiers.add(identifier)
        validated.append(task)
    return validated


def validate_candidates(document: Any, task_ids: set[str]) -> tuple[str, str, dict[str, str]]:
    if not isinstance(document, dict) or set(document) != {
        "schema_version", "model_name", "checkpoint_sha256", "candidates"
    }:
        raise EvaluationRefused("candidate input keys are invalid")
    if document["schema_version"] != CANDIDATES_SCHEMA:
        raise EvaluationRefused("candidate input schema is invalid")
    model_name, checkpoint_sha256 = document["model_name"], document["checkpoint_sha256"]
    if not isinstance(model_name, str) or not 1 <= len(model_name) <= 128:
        raise EvaluationRefused("candidate model name is invalid")
    if not isinstance(checkpoint_sha256, str) or HEX_SHA256.fullmatch(checkpoint_sha256) is None:
        raise EvaluationRefused("candidate checkpoint digest is invalid")
    candidates = document["candidates"]
    if not isinstance(candidates, list) or len(candidates) != len(task_ids):
        raise EvaluationRefused("candidate count does not match the suite")
    result: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {"task_id", "source"}:
            raise EvaluationRefused("candidate shape is invalid")
        task_id, source = candidate["task_id"], candidate["source"]
        if not isinstance(task_id, str) or task_id not in task_ids or task_id in result:
            raise EvaluationRefused("candidate task id is invalid")
        if not isinstance(source, str) or not 1 <= len(source.encode("utf-8")) <= 262_144:
            raise EvaluationRefused("candidate source is invalid")
        result[task_id] = source
    return model_name, checkpoint_sha256, result


def require_sandbox() -> str:
    binary = shutil.which("bwrap")
    if platform.system() != "Linux" or binary is None or resource is None:
        raise EvaluationRefused("offline sandbox is unavailable")
    required = (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"))
    if not all(path.is_dir() for path in required):
        raise EvaluationRefused("offline sandbox runtime is incomplete")
    return binary


def limit_resources() -> None:
    if resource is None:
        raise EvaluationRefused("offline sandbox is unavailable")
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_BYTES, OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))


def sandbox_command(binary: str, workdir: Path) -> list[str]:
    return [
        binary,
        "--unshare-all", "--unshare-net", "--die-with-parent", "--new-session", "--proc", "/proc",
        "--dev", "/dev", "--tmpfs", "/tmp", "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin", "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64", "--dir", "/work", "--bind",
        str(workdir), "/work", "--chdir", "/work", "--clearenv", "--setenv",
        "PATH", "/usr/bin:/bin", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--", "/usr/bin/python3", "/work/runner.py",
    ]


def run_task(binary: str, *, task: dict[str, str], source: str, output_dir: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="e2-", dir=output_dir) as temporary:
        workdir = Path(temporary)
        (workdir / "candidate.py").write_text(source, encoding="utf-8")
        (workdir / "tests.py").write_text(task["test_source"], encoding="utf-8")
        (workdir / "runner.py").write_text(
            "import runpy\nfrom pathlib import Path\nmodule = runpy.run_path('candidate.py')\n"
            "source = Path('tests.py').read_text(encoding='utf-8')\nexec(compile(source, 'tests.py', 'exec'), {'module': module})\n",
            encoding="utf-8",
        )
        output_path = workdir / "output.log"
        returncode: int | None = None
        timed_out = False
        with output_path.open("wb") as output:
            process = subprocess.Popen(
                sandbox_command(binary, workdir), stdout=output, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, preexec_fn=limit_resources,
            )
            try:
                returncode = process.wait(timeout=WALL_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait()
        output_size = output_path.stat().st_size
        output_digest = sha256_file(output_path)
    verdict = "accept" if not timed_out and returncode == 0 and output_size <= OUTPUT_BYTES else "reject"
    return {
        "task_id": task["id"],
        "prompt_sha256": sha256_bytes(task["prompt"].encode("utf-8")),
        "test_sha256": sha256_bytes(task["test_source"].encode("utf-8")),
        "candidate_sha256": sha256_bytes(source.encode("utf-8")),
        "output_sha256": output_digest,
        "output_bytes": output_size,
        "returncode": returncode,
        "timed_out": timed_out,
        "verdict": verdict,
    }


def evaluate(*, suite_path: Path, candidates_path: Path, output_dir: Path) -> dict[str, Any]:
    suite = read_json(suite_path)
    tasks = validate_suite(suite)
    task_ids = {task["id"] for task in tasks}
    candidates_document = read_json(candidates_path)
    model_name, checkpoint_sha256, candidates = validate_candidates(candidates_document, task_ids)
    binary = require_sandbox()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "code-evaluation-report.json"
    if report_path.exists():
        raise EvaluationRefused("evaluation report destination already exists")
    results = [run_task(binary, task=task, source=candidates[task["id"]], output_dir=output_dir) for task in tasks]
    report = {
        "schema_version": REPORT_SCHEMA,
        "suite_sha256": sha256_file(suite_path),
        "candidates_sha256": sha256_file(candidates_path),
        "model_name": model_name,
        "checkpoint_sha256": checkpoint_sha256,
        "limits": {"cpu_seconds": CPU_SECONDS, "memory_bytes": MEMORY_BYTES, "output_bytes": OUTPUT_BYTES, "wall_seconds": WALL_SECONDS},
        "accepted": sum(result["verdict"] == "accept" for result in results),
        "rejected": sum(result["verdict"] == "reject" for result in results),
        "results": results,
    }
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, report_path)
    if sha256_file(report_path) != sha256_bytes(report_path.read_bytes()):
        raise EvaluationRefused("evaluation report verification failed")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate(suite_path=args.suite, candidates_path=args.candidates, output_dir=args.output_dir)
    except (OSError, EvaluationRefused) as error:
        print(f"code evaluation refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"accepted": report["accepted"], "rejected": report["rejected"], "schema_version": REPORT_SCHEMA}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
