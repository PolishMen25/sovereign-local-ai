"""Run one snippet of user-approved Python in the project's offline bwrap sandbox.

This is the execution half of the action-tool V2: the 14B *proposes* code, the
human approves it in the UI, and only then does it run here — isolated, offline
(``--unshare-all --unshare-net``), read-only system, a bound scratch /work,
cleared env and CPU/memory/output/process rlimits.  It never touches the host
filesystem or the network.  Reuses the exact sandbox primitives the arena uses
to referee untrusted code.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from tools.run_code_evaluation import require_sandbox, limit_resources, EvaluationRefused

MAX_CODE_CHARS = 20_000
MAX_OUTPUT_CHARS = 8_000
WALL_TIMEOUT_SECONDS = 20


def _command(binary: str, workdir: Path) -> list[str]:
    return [
        binary,
        "--unshare-all", "--unshare-net", "--die-with-parent", "--new-session",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
        "--dir", "/work", "--bind", str(workdir), "/work", "--chdir", "/work",
        "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--", "/usr/bin/python3", "/work/main.py",
    ]


_WORKS: bool | None = None


def available() -> bool:
    """True only if the sandbox genuinely runs here (cached real self-test).

    A binary check is not enough: in an unprivileged container bwrap may exist
    but fail to set up user namespaces. We run trivial code once and cache the
    verdict, so run_python is offered only when it can actually execute.
    """
    global _WORKS
    if _WORKS is not None:
        return _WORKS
    try:
        outcome = run_python("pass")
        _WORKS = bool(outcome.get("ok")) and not outcome.get("timed_out")
    except (ValueError, RuntimeError):
        _WORKS = False
    return _WORKS


def run_python(code: str) -> dict[str, Any]:
    """Execute code in the sandbox. Returns {ok, timed_out, exit_code, output}.

    Raises ValueError on invalid input and RuntimeError if the sandbox is
    unavailable (so the caller can report it to the model/user cleanly).
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code vide")
    if len(code) > MAX_CODE_CHARS:
        raise ValueError(f"code trop long (max {MAX_CODE_CHARS} caractères)")
    try:
        binary = require_sandbox()
    except EvaluationRefused as failure:
        raise RuntimeError(f"sandbox indisponible : {failure}") from failure
    with tempfile.TemporaryDirectory(prefix="runpy-") as temporary:
        workdir = Path(temporary)
        (workdir / "main.py").write_text(code, encoding="utf-8")
        try:
            process = subprocess.run(
                _command(binary, workdir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=limit_resources,
                timeout=WALL_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "timed_out": True, "exit_code": None,
                    "output": f"(exécution interrompue après {WALL_TIMEOUT_SECONDS}s)"}
        output = process.stdout.decode("utf-8", "replace")[:MAX_OUTPUT_CHARS]
        return {"ok": process.returncode == 0, "timed_out": False,
                "exit_code": process.returncode, "output": output}
