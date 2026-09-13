"""A small scratch workspace the assistant may write into, after human approval.

Deliberately narrow: files live under one gateway-owned directory and nowhere
else.  Paths are validated segment by segment and re-checked after resolution,
so no traversal, absolute path or symlink can escape the root.  The assistant
never touches the user's real folders — retrieving a file is an explicit
download from this workspace.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 200
MAX_RELATIVE_CHARS = 200
MAX_READ_CHARS = 20_000


class WorkspaceError(ValueError):
    """The requested path or content is not acceptable."""


def resolve(root: Path, relative: str) -> Path:
    """Return the absolute target for ``relative`` inside ``root``, or refuse."""
    if not isinstance(relative, str) or not relative.strip() or len(relative) > MAX_RELATIVE_CHARS:
        raise WorkspaceError("chemin de fichier invalide")
    if relative.startswith("/") or "\\" in relative or "\x00" in relative:
        raise WorkspaceError("chemin absolu ou caractères interdits")
    parts = [part for part in relative.split("/") if part]
    if not 1 <= len(parts) <= 2:
        raise WorkspaceError("chemin limité à un fichier, éventuellement dans un sous-dossier")
    for part in parts:
        if part in {".", ".."} or SAFE_SEGMENT.fullmatch(part) is None:
            raise WorkspaceError(f"nom de segment refusé : {part[:40]}")
    root_resolved = root.resolve()
    target = (root_resolved / Path(*parts)).resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise WorkspaceError("le chemin sort du dossier de travail")
    return target


def write_file(root: Path, relative: str, content: str) -> dict[str, Any]:
    """Write one text file into the workspace. Returns {path, relative, bytes}."""
    if not isinstance(content, str):
        raise WorkspaceError("contenu invalide")
    payload = content.encode("utf-8")
    if len(payload) > MAX_FILE_BYTES:
        raise WorkspaceError(f"fichier trop volumineux (max {MAX_FILE_BYTES // 1024} Ko)")
    root.mkdir(parents=True, exist_ok=True)
    target = resolve(root, relative)
    if not target.exists() and sum(1 for _ in root.rglob("*") if _.is_file()) >= MAX_FILES:
        raise WorkspaceError(f"dossier de travail plein (max {MAX_FILES} fichiers)")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or (target.exists() and target.is_symlink()):
        raise WorkspaceError("lien symbolique refusé")
    target.write_bytes(payload)
    return {"path": str(target), "relative": str(target.relative_to(root.resolve())), "bytes": len(payload)}


def list_files(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append({
            "relative": str(path.relative_to(root.resolve() if root.is_absolute() else root)),
            "bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        })
        if len(entries) >= MAX_FILES:
            break
    return entries


def read_file(root: Path, relative: str, *, max_chars: int = MAX_READ_CHARS) -> str:
    target = resolve(root, relative)
    if not target.is_file() or target.is_symlink():
        raise WorkspaceError("fichier introuvable dans le dossier de travail")
    return target.read_text(encoding="utf-8", errors="replace")[:max_chars]


def read_bytes(root: Path, relative: str) -> bytes:
    target = resolve(root, relative)
    if not target.is_file() or target.is_symlink():
        raise WorkspaceError("fichier introuvable dans le dossier de travail")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise WorkspaceError("fichier trop volumineux")
    return target.read_bytes()
