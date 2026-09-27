#!/usr/bin/env python3
"""Recompute, offline and read-only, the digests of the synthetic contract fixtures.

PROVISOIRE, like the research-package and lifecycle contracts it serves
(docs/data/research-package-validation.md, docs/data/lifecycle-events.md).

* A research-package fixture (``*.json``) is read; a ``*.template.json`` is
  first expanded in memory with ``RUNTIME_FRAGMENTS``, so the printed digest is
  the one ``integrity.package_sha256`` must carry.  The committed file keeps
  its placeholders: secret-shaped fragments are never written to the public
  repository.
* A lifecycle journal (``*.jsonl``) is read line by line; each event's chain
  digest (``lifecycle.event_sha256``) is printed next to its declared
  ``previous_event_sha256``, to re-chain the following events of a subject.

The tool never writes a file and never uses the network.  Its output holds
file names, line numbers, digests and reason codes only, never a value.
Exit codes: 0 every digest computed, 1 a document refused by the strict
profile, 2 an unreadable or oversized file.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUARANTINE = PROJECT_ROOT / "services" / "quarantine"
PACKAGE_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "research-package"
TEMPLATE_SUFFIX = ".template.json"
_DIGEST = re.compile("[0-9a-fA-F]{64}")

# Assembled at run time: the committed fixtures only hold the placeholders.
RUNTIME_FRAGMENTS = {
    "{{signed_param}}": "X-Amz-" + "Signature",
    "{{credential_param}}": "access_" + "token",
    "{{bearer_value}}": hashlib.sha256(b"synthetic-bearer-value").hexdigest()[:24],
}


def _load(name: str, filename: str) -> ModuleType:
    """Load a quarantine module by path, without touching sys.path."""

    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, QUARANTINE / filename)
        if spec is None or spec.loader is None:
            raise ImportError(f"{filename} is missing from services/quarantine")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


_CANONICAL = _load("sovereign_quarantine_canonical_json", "canonical_json.py")
_LIFECYCLE = _load("sovereign_quarantine_lifecycle", "lifecycle.py")


def expand(name: str, data: bytes) -> bytes:
    """The bytes a fixture stands for: templates get their runtime fragments."""

    if not name.endswith(TEMPLATE_SUFFIX):
        return data
    text = data.decode("utf-8")
    for placeholder, fragment in RUNTIME_FRAGMENTS.items():
        text = text.replace(placeholder, fragment)
    return text.encode("utf-8")


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise _CANONICAL.CanonicalJSONError("SIZE_EXCEEDED")
    return data


def package_row(name: str, data: bytes) -> dict[str, Any]:
    """Declared and recomputed ``integrity.package_sha256`` of one package."""

    refusal: str | None = None
    document: Any = None
    try:
        expanded = expand(name, data)
    except UnicodeDecodeError:
        refusal = "INVALID_UTF8"
    if refusal is None:
        try:
            document = _CANONICAL.loads_strict(expanded)
        except _CANONICAL.CanonicalJSONError as error:
            refusal = error.code
    if refusal is None and type(document) is not dict:
        refusal = "NOT_AN_OBJECT"
    if refusal is not None:
        return {"file": name, "refused": "JSON_" + refusal}
    integrity = document.get("integrity")
    declared = integrity.get("package_sha256") if type(integrity) is dict else None
    if type(declared) is not str or not _DIGEST.fullmatch(declared):
        declared = None  # only a digest is ever printed, never another value
    computed = _CANONICAL.package_sha256(document)
    return {"file": name, "declared": declared, "computed": computed, "match": declared == computed}


def journal_rows(name: str, data: bytes) -> list[dict[str, Any]]:
    """Chain digest of every event of a JSONL journal, in journal order."""

    rows: list[dict[str, Any]] = []
    lines = [line.rstrip(b"\r") for line in data.split(b"\n")]
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        refusal: str | None = None
        event: Any = None
        try:
            event = _CANONICAL.loads_strict(line)
        except _CANONICAL.CanonicalJSONError as error:
            refusal = error.code
        if refusal is not None:
            rows.append({"file": name, "line": number, "refused": "JSON_" + refusal})
            continue
        if type(event) is not dict:
            rows.append({"file": name, "line": number, "refused": "EVENT_TYPE_MISMATCH"})
            continue
        rows.append(
            {
                "file": name,
                "line": number,
                "event_sha256": _LIFECYCLE.event_sha256(event),
                "previous_event_sha256": event.get("previous_event_sha256"),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recalcule hors ligne, sans rien écrire, les empreintes des fixtures synthétiques "
        "research-package (gabarits développés en mémoire) et des journaux de cycle de vie (PROVISOIRE)."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="fixtures .json, .template.json ou .jsonl ; par défaut, tous les paquets de tests/fixtures/research-package",
    )
    arguments = parser.parse_args(argv)
    paths = arguments.paths or sorted(
        path for path in PACKAGE_FIXTURES.glob("*.json") if path.name != "expected.json"
    )
    refused = False
    for path in paths:
        unreadable: str | None = None
        data = b""
        try:
            data = _read(path, _CANONICAL.MAX_DOCUMENT_BYTES)
        except OSError:
            unreadable = "the input file cannot be read"
        except _CANONICAL.CanonicalJSONError as error:
            unreadable = error.code
        if unreadable is not None:
            print(f"fixture hash refused: {unreadable}", file=sys.stderr)
            return 2
        rows = journal_rows(path.name, data) if path.suffix == ".jsonl" else [package_row(path.name, data)]
        for row in rows:
            refused = refused or "refused" in row
            print(_CANONICAL.canonicalize(row).decode("utf-8"))
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
