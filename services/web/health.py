"""A single, cheap health snapshot of the local stack.

Everything here is read-only and costs no generation: engine reachability comes
from each client's own ``status()``, the rest is counted from what the gateway
already holds (knowledge index, arena, corpus, workspace) plus container-level
resource files.  Nothing shells out and nothing benchmarks a model, so the page
can be refreshed freely.

Note on scope: the gateway lives inside the CT 101 container, so the resource
figures describe that container (via lxcfs), not the whole Proxmox host.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

MEMINFO = Path("/proc/meminfo")
LOADAVG = Path("/proc/loadavg")


def _meminfo(path: Path = MEMINFO) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                parts = rest.split()
                if parts and parts[0].isdigit():
                    values[key] = int(parts[0]) * 1024
    except (OSError, ValueError):
        return {}
    return values


def _loadavg(path: Path = LOADAVG) -> list[float]:
    try:
        parts = path.read_text(encoding="utf-8").split()[:3]
        return [float(value) for value in parts]
    except (OSError, ValueError, IndexError):
        return []


def resources(state_root: Path | None = None, *, meminfo: Path = MEMINFO, loadavg: Path = LOADAVG) -> dict[str, Any]:
    memory = _meminfo(meminfo)
    snapshot: dict[str, Any] = {"load": _loadavg(loadavg)}
    total, available = memory.get("MemTotal"), memory.get("MemAvailable")
    if total:
        snapshot["memory"] = {
            "total_bytes": total,
            "available_bytes": available,
            "used_percent": round((total - available) * 100 / total, 1) if available is not None else None,
        }
    if state_root is not None:
        try:
            usage = shutil.disk_usage(state_root)
            snapshot["disk"] = {
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "used_percent": round((usage.total - usage.free) * 100 / usage.total, 1) if usage.total else None,
            }
        except OSError:
            pass
    return snapshot


def _engine_row(name: str, label: str, runtime: Any) -> dict[str, Any]:
    if runtime is None:
        return {"engine": name, "label": label, "available": False, "state": "non configuré"}
    try:
        status = runtime.status()
    except Exception:  # noqa: BLE001 — a health page must never fail on a probe
        return {"engine": name, "label": label, "available": False, "state": "injoignable"}
    return {
        "engine": name,
        "label": label,
        "available": bool(status.get("available")),
        "state": str(status.get("state", "inconnu")),
    }


def snapshot(state: Any, *, state_root: Path | None = None, sandbox_available: bool | None = None) -> dict[str, Any]:
    """Collect the whole picture in one pass; never raises."""
    runtimes = [
        _engine_row("CHAT-14B", "Conversation (Qwen2.5-14B)", getattr(state, "runtime", None)),
        _engine_row("QWEN-CODER", "Programmation (Qwen2.5-Coder-7B)", getattr(state, "qwen_runtime", None)),
        _engine_row("EMBED", "Embeddings (Qwen3-Embedding-0.6B)", getattr(state, "embed_runtime", None)),
        _engine_row("CORE-700M", "CORE (expérimental)", getattr(state, "core_runtime", None)),
    ]

    knowledge: dict[str, Any] = {"ready": False}
    try:
        knowledge = state.knowledge.status()
    except Exception:  # noqa: BLE001
        pass

    arena: dict[str, Any] = {"available": False}
    try:
        arena = state.arena_overview()
    except Exception:  # noqa: BLE001
        pass

    corpus: dict[str, Any] = {"available": False, "increments": []}
    try:
        corpus = state.corpus_increments()
    except Exception:  # noqa: BLE001
        pass
    increments = corpus.get("increments", []) or []

    workspace_files = 0
    workspace_dir = getattr(state, "workspace_dir", None)
    if workspace_dir is not None:
        try:
            from services.web import workspace as workspace_module
            workspace_files = len(workspace_module.list_files(workspace_dir))
        except Exception:  # noqa: BLE001
            workspace_files = 0

    return {
        "engines": runtimes,
        "knowledge": {"ready": bool(knowledge.get("ready")), "documents": knowledge.get("documents", 0),
                      "mode": knowledge.get("mode", "lexical")},
        "arena": {"available": bool(arena.get("available")), "matches": arena.get("matches"),
                  "accepted": arena.get("accepted_solutions") or arena.get("accepted")},
        "corpus": {"available": bool(corpus.get("available")), "total": len(increments),
                   "validated": sum(1 for item in increments if item.get("status") == "validated")},
        "workspace": {"configured": workspace_dir is not None, "files": workspace_files},
        "actions": {"sandbox": bool(sandbox_available), "tools_enabled": bool(getattr(state, "tools_enabled", False))},
        "resources": resources(state_root),
    }
