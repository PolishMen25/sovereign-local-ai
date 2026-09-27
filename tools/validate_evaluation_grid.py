#!/usr/bin/env python3
"""Validate the machine-readable V1 evaluation grid, fail-closed.

The grid (``configs/evaluation/v1-grid.candidate.json``) is the
machine-readable form of ``docs/model/v1-evaluation-grid.md``.  Every metric
must declare a fixture, a procedure, a threshold, a responsible role and at
least one G gate and one A gate.  The validator refuses:

- a missing, extra or malformed field;
- an unknown axis, gate id or threshold status;
- a fixture or procedure path that does not exist in the repository (a fixture
  that does not exist yet must be declared ``missing``, never pointed at);
- a cited decision absent from, or superseded in, the decision register;
- an ``approved`` threshold without a decision id, an approval date and the
  grid SHA-256, or whose SHA-256 does not match the grid content.

The grid SHA-256 covers the canonical JSON of the grid with every threshold's
``status`` and ``approval`` removed.  Approving a threshold therefore leaves
the digest unchanged, while editing any threshold, fixture, procedure or gate
after approval breaks it: a threshold cannot be tuned after the fact without a
new decision.  ``--print-digest`` prints that digest for the owner to pin in a
decision entry.

The validator reads the grid, the decision register and path metadata only.
It writes nothing and makes no network call.

Exit codes: 0 valid, 1 invalid grid, 2 usage error.
"""

from __future__ import annotations

import argparse
import copy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRID = PROJECT_ROOT / "configs" / "evaluation" / "v1-grid.candidate.json"
DECISIONS_RELATIVE = PurePosixPath("docs/project/decisions.md")

SCHEMA_VERSION = "evaluation-grid.v1"
GRID_STATUS = "candidate_owner_review_required"
TOP_LEVEL_KEYS = frozenset({"schema_version", "grid_id", "status", "source_document", "axes", "metrics", "gate_links"})
AXIS_KEYS = frozenset({"id", "title"})
METRIC_KEYS = frozenset({"id", "axis", "title", "fixture", "procedure", "threshold", "responsible", "g_gates", "a_gates"})
FIXTURE_KEYS = frozenset({"status", "paths", "description"})
PROCEDURE_KEYS = frozenset({"description", "paths"})
THRESHOLD_KEYS = frozenset({"status", "statement", "decisions"})
APPROVAL_KEYS = frozenset({"decision_id", "approved_on", "grid_sha256"})

AXIS_IDS = tuple(range(1, 9))
G_GATES = tuple(f"G{index}" for index in range(9))
A_GATES = tuple(f"A{index}" for index in range(9))
FIXTURE_STATUSES = ("present", "partial", "missing", "runtime_artifact")
THRESHOLD_STATUSES = ("proposed", "pending_measurement", "confirmed", "approved")
LINK_LEVELS = ("required", "partial", "none")
RESPONSIBLE_ROLES = ("project_owner",)

GRID_ID = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
METRIC_ID = re.compile(r"^M([1-8])\.([1-9][0-9]?)$")
DECISION_ID = re.compile(r"^D-[0-9]{3}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
REGISTER_ROW = re.compile(r"^\|\s*(D-[0-9]{3})\s*\|\s*(.*)$")

MAX_GRID_BYTES = 1024 * 1024
MAX_REGISTER_BYTES = 1024 * 1024
MAX_METRICS = 200
MAX_PATHS = 16
MAX_DECISIONS = 8
TITLE_RANGE = (3, 160)
TEXT_RANGE = (3, 1500)


class GridInvalid(ValueError):
    """The grid breaks its contract; nothing derived from it may be trusted."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GridInvalid(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise GridInvalid(f"non-finite JSON number: {value}")


def load_grid(path: Path) -> dict[str, Any]:
    """Read one grid file as strict JSON: bounded, UTF-8, no duplicate key, no NaN."""

    if path.is_symlink() or not path.is_file():
        raise GridInvalid("grid must be a regular file")
    payload = path.read_bytes()
    if not 1 <= len(payload) <= MAX_GRID_BYTES:
        raise GridInvalid("grid size is outside the bounded range")
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except UnicodeDecodeError as error:
        raise GridInvalid("grid must be UTF-8") from error
    except json.JSONDecodeError as error:
        raise GridInvalid(f"grid is not valid JSON (line {error.lineno})") from error
    if not isinstance(document, dict):
        raise GridInvalid("grid must be a JSON object")
    return document


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def grid_sha256(document: dict[str, Any]) -> str:
    """Digest of the grid content, independent of threshold approval state."""

    content = copy.deepcopy(document)
    metrics = content.get("metrics")
    if isinstance(metrics, list):
        for metric in metrics:
            threshold = metric.get("threshold") if isinstance(metric, dict) else None
            if isinstance(threshold, dict):
                threshold.pop("status", None)
                threshold.pop("approval", None)
    return hashlib.sha256(canonical_json(content)).hexdigest()


def load_decision_register(path: Path) -> dict[str, bool]:
    """Map every ``D-xxx`` row of the register to whether it is superseded."""

    if path.is_symlink() or not path.is_file():
        raise GridInvalid("decision register is unavailable")
    payload = path.read_bytes()
    if not 1 <= len(payload) <= MAX_REGISTER_BYTES:
        raise GridInvalid("decision register size is outside the bounded range")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GridInvalid("decision register must be UTF-8") from error
    register: dict[str, bool] = {}
    for line in text.splitlines():
        match = REGISTER_ROW.match(line.strip())
        if match is not None:
            register[match.group(1)] = match.group(2).lstrip().startswith("**SUPERSEDED")
    if not register:
        raise GridInvalid("decision register contains no decision")
    return register


def _require_text(value: Any, context: str, bounds: tuple[int, int] = TEXT_RANGE) -> str:
    if not isinstance(value, str) or value != value.strip() or not bounds[0] <= len(value) <= bounds[1]:
        raise GridInvalid(f"{context} must be a trimmed string of {bounds[0]}-{bounds[1]} characters")
    return value


def _require_keys(value: Any, expected: frozenset[str], context: str, optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GridInvalid(f"{context} must be an object")
    keys = set(value)
    missing = sorted(expected - keys)
    if missing:
        raise GridInvalid(f"{context} is missing field(s): {', '.join(missing)}")
    extra = sorted(keys - expected - optional)
    if extra:
        raise GridInvalid(f"{context} has unknown field(s): {', '.join(extra)}")
    return value


def _require_repository_path(value: Any, root: Path, context: str) -> str:
    if not isinstance(value, str) or SAFE_PATH.fullmatch(value) is None:
        raise GridInvalid(f"{context} is not a safe relative path")
    posix = PurePosixPath(value)
    if posix.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise GridInvalid(f"{context} must stay inside the repository")
    target = root.joinpath(*posix.parts)
    if target.is_symlink() or not (target.is_file() or target.is_dir()):
        raise GridInvalid(f"{context} does not exist: {value}")
    return value


def _require_paths(value: Any, root: Path, context: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_PATHS or len(value) != len(set(map(str, value))):
        raise GridInvalid(f"{context} must be a unique list of at most {MAX_PATHS} paths")
    return [_require_repository_path(item, root, f"{context} entry") for item in value]


def _require_gates(value: Any, known: tuple[str, ...], context: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) != len(set(map(str, value))):
        raise GridInvalid(f"{context} must be a non-empty unique list")
    for gate in value:
        if not isinstance(gate, str) or gate not in known:
            raise GridInvalid(f"{context} contains an unknown gate id: {gate!r}")
    return value


def _require_decision(value: Any, register: dict[str, bool], context: str) -> str:
    if not isinstance(value, str) or DECISION_ID.fullmatch(value) is None:
        raise GridInvalid(f"{context} must be a decision id D-xxx")
    if value not in register:
        raise GridInvalid(f"{context} {value} is not in the decision register")
    if register[value]:
        raise GridInvalid(f"{context} {value} is superseded in the decision register")
    return value


def _validate_fixture(value: Any, root: Path, context: str) -> str:
    fixture = _require_keys(value, FIXTURE_KEYS, context)
    status = fixture["status"]
    if status not in FIXTURE_STATUSES:
        raise GridInvalid(f"{context} status is unknown")
    paths = _require_paths(fixture["paths"], root, f"{context} paths")
    _require_text(fixture["description"], f"{context} description")
    if status in {"present", "partial"} and not paths:
        raise GridInvalid(f"{context} is {status} but lists no path")
    if status in {"missing", "runtime_artifact"} and paths:
        raise GridInvalid(f"{context} is {status} and must not point at a path")
    return status


def _validate_threshold(value: Any, register: dict[str, bool], digest: str, today: date, context: str) -> str:
    threshold = _require_keys(value, THRESHOLD_KEYS, context, optional=frozenset({"approval"}))
    status = threshold["status"]
    if status not in THRESHOLD_STATUSES:
        raise GridInvalid(f"{context} status is unknown")
    _require_text(threshold["statement"], f"{context} statement")
    decisions = threshold["decisions"]
    if not isinstance(decisions, list) or len(decisions) > MAX_DECISIONS or len(decisions) != len(set(map(str, decisions))):
        raise GridInvalid(f"{context} decisions must be a unique list of at most {MAX_DECISIONS} ids")
    for decision in decisions:
        _require_decision(decision, register, f"{context} decision")
    if status == "confirmed" and not decisions:
        raise GridInvalid(f"{context} is confirmed but cites no decision")
    if status != "approved":
        if "approval" in threshold:
            raise GridInvalid(f"{context} carries an approval but is not approved")
        return status
    if "approval" not in threshold:
        raise GridInvalid(f"{context} is approved without an approval record")
    approval = _require_keys(threshold["approval"], APPROVAL_KEYS, f"{context} approval")
    _require_decision(approval["decision_id"], register, f"{context} approval decision")
    approved_on = approval["approved_on"]
    if not isinstance(approved_on, str) or ISO_DATE.fullmatch(approved_on) is None:
        raise GridInvalid(f"{context} approval date must be YYYY-MM-DD")
    try:
        approved_date = date.fromisoformat(approved_on)
    except ValueError as error:
        raise GridInvalid(f"{context} approval date is not a calendar date") from error
    if approved_date > today:
        raise GridInvalid(f"{context} approval date is in the future")
    pinned = approval["grid_sha256"]
    if not isinstance(pinned, str) or SHA256.fullmatch(pinned) is None:
        raise GridInvalid(f"{context} approval grid_sha256 must be a lowercase SHA-256")
    if pinned != digest:
        raise GridInvalid(f"{context} approval grid_sha256 does not match the grid content")
    return status


def _validate_gate_links(value: Any) -> dict[str, dict[str, str]]:
    links = _require_keys(value, frozenset(G_GATES), "gate_links")
    for g_gate in G_GATES:
        row = _require_keys(links[g_gate], frozenset(A_GATES), f"gate_links {g_gate}")
        for a_gate in A_GATES:
            if row[a_gate] not in LINK_LEVELS:
                raise GridInvalid(f"gate_links {g_gate}/{a_gate} level is unknown")
    return links


def validate(document: Any, *, root: Path = PROJECT_ROOT, decisions_path: Path | None = None,
             today: date | None = None) -> dict[str, Any]:
    """Validate one grid document; return a content-free summary or raise GridInvalid."""

    grid = _require_keys(document, TOP_LEVEL_KEYS, "grid")
    if grid["schema_version"] != SCHEMA_VERSION:
        raise GridInvalid("grid schema_version is unsupported")
    if not isinstance(grid["grid_id"], str) or GRID_ID.fullmatch(grid["grid_id"]) is None:
        raise GridInvalid("grid_id is invalid")
    if grid["status"] != GRID_STATUS:
        raise GridInvalid(f"grid status must remain {GRID_STATUS}")
    _require_repository_path(grid["source_document"], root, "source_document")
    register = load_decision_register(decisions_path or root.joinpath(*DECISIONS_RELATIVE.parts))
    today = today or datetime.now(timezone.utc).date()
    digest = grid_sha256(grid)

    axes = grid["axes"]
    if not isinstance(axes, list) or len(axes) != len(AXIS_IDS):
        raise GridInvalid(f"grid must declare exactly {len(AXIS_IDS)} axes")
    for expected, axis in zip(AXIS_IDS, axes):
        _require_keys(axis, AXIS_KEYS, f"axis {expected}")
        if type(axis["id"]) is not int or axis["id"] != expected:
            raise GridInvalid(f"axis ids must be 1-{len(AXIS_IDS)} in order")
        _require_text(axis["title"], f"axis {expected} title", TITLE_RANGE)

    links = _validate_gate_links(grid["gate_links"])

    metrics = grid["metrics"]
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= MAX_METRICS:
        raise GridInvalid(f"grid metrics must be a list of 1-{MAX_METRICS} entries")
    seen: set[str] = set()
    covered_axes: set[int] = set()
    fixtures: dict[str, int] = {status: 0 for status in FIXTURE_STATUSES}
    thresholds: dict[str, int] = {status: 0 for status in THRESHOLD_STATUSES}
    for position, metric in enumerate(metrics):
        label = metric.get("id") if isinstance(metric, dict) and isinstance(metric.get("id"), str) else f"#{position}"
        context = f"metric {label}"
        _require_keys(metric, METRIC_KEYS, context)
        match = METRIC_ID.fullmatch(metric["id"]) if isinstance(metric["id"], str) else None
        if match is None or metric["id"] in seen:
            raise GridInvalid(f"{context} id must be unique and look like M<axis>.<n>")
        seen.add(metric["id"])
        if type(metric["axis"]) is not int or metric["axis"] not in AXIS_IDS or int(match.group(1)) != metric["axis"]:
            raise GridInvalid(f"{context} axis is unknown or does not match its id")
        covered_axes.add(metric["axis"])
        _require_text(metric["title"], f"{context} title", TITLE_RANGE)
        fixtures[_validate_fixture(metric["fixture"], root, f"{context} fixture")] += 1
        procedure = _require_keys(metric["procedure"], PROCEDURE_KEYS, f"{context} procedure")
        _require_text(procedure["description"], f"{context} procedure description")
        _require_paths(procedure["paths"], root, f"{context} procedure paths")
        thresholds[_validate_threshold(metric["threshold"], register, digest, today, f"{context} threshold")] += 1
        if metric["responsible"] not in RESPONSIBLE_ROLES:
            raise GridInvalid(f"{context} responsible role is unknown")
        g_gates = _require_gates(metric["g_gates"], G_GATES, f"{context} g_gates")
        a_gates = _require_gates(metric["a_gates"], A_GATES, f"{context} a_gates")
        for a_gate in a_gates:
            if all(links[g_gate][a_gate] == "none" for g_gate in g_gates):
                raise GridInvalid(f"{context} gate {a_gate} is linked to none of its G gates in gate_links")
    missing_axes = sorted(set(AXIS_IDS) - covered_axes)
    if missing_axes:
        raise GridInvalid(f"grid axes without metric: {', '.join(map(str, missing_axes))}")
    return {
        "schema_version": SCHEMA_VERSION,
        "grid_id": grid["grid_id"],
        "status": grid["status"],
        "grid_sha256": digest,
        "metric_count": len(metrics),
        "fixtures_by_status": fixtures,
        "thresholds_by_status": thresholds,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("grid", nargs="?", type=Path, default=DEFAULT_GRID,
                        help="grid JSON (default: the versioned candidate grid)")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT,
                        help="repository root used to resolve fixture, procedure and register paths")
    parser.add_argument("--print-digest", action="store_true",
                        help="print only the grid SHA-256 to pin in a decision entry (the grid must be valid)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = validate(load_grid(args.grid), root=args.root)
    except (GridInvalid, OSError) as error:
        print(f"invalid evaluation grid: {error}", file=sys.stderr)
        return 1
    if args.print_digest:
        print(summary["grid_sha256"])
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
