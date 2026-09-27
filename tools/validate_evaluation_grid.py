#!/usr/bin/env python3
"""Validate the machine-readable V1 evaluation grid, fail-closed.

The grid (``configs/evaluation/v1-grid.candidate.json``) is the
machine-readable form of ``docs/model/v1-evaluation-grid.md``.  Every metric
must declare a fixture, a procedure, a threshold, a responsible role and at
least one G gate and one A gate.  The validator refuses:

- a missing, extra or malformed field;
- an unknown axis, gate id or threshold status;
- a fixture or procedure path that does not exist in the repository (a fixture
  that does not exist yet must be declared ``missing``, never pointed at), and
  a fixture path that is not a regular file;
- a cited decision absent from, or superseded in, the decision register;
- an ``approved`` threshold without a decision id, an approval date, its
  pre-approval status and the grid SHA-256; whose SHA-256 does not match the
  grid content; or whose decision row in the register does not record that
  SHA-256.

The grid SHA-256 covers the canonical JSON of the grid entries (every
threshold with its status, an approved one counted with the status recorded in
``approval.previous_status``, and without its ``approval`` object) together
with the SHA-256 of the bytes of every fixture file the grid points at.
Approving a threshold therefore leaves the digest unchanged, while editing any
threshold, status, fixture entry, fixture file, procedure entry or gate after
approval breaks it: a threshold or an evaluation set cannot be tuned after the
fact without a new decision.  The files listed as procedure paths (tools,
documents) are not hashed: their changes go through review, not through this
pin.  ``--print-digest`` prints that digest for the owner to record in the
decision entry that approves the thresholds.

The validator reads the grid, the decision register, the fixture files and
path metadata only.  It writes nothing and makes no network call.

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
APPROVAL_KEYS = frozenset({"decision_id", "approved_on", "grid_sha256", "previous_status"})

AXIS_IDS = tuple(range(1, 9))
G_GATES = tuple(f"G{index}" for index in range(9))
A_GATES = tuple(f"A{index}" for index in range(9))
FIXTURE_STATUSES = ("present", "partial", "missing", "runtime_artifact")
THRESHOLD_STATUSES = ("proposed", "pending_measurement", "confirmed", "approved")
PRE_APPROVAL_STATUSES = ("proposed", "pending_measurement", "confirmed")
LINK_LEVELS = ("required", "partial", "none")
RESPONSIBLE_ROLES = ("project_owner",)

GRID_ID = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
METRIC_ID = re.compile(r"^M([1-8])\.([1-9][0-9]?)$")
DECISION_ID = re.compile(r"^D-[0-9]{3}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
REGISTER_ROW = re.compile(r"^\|\s*(D-[0-9]{3})\s*\|\s*(.*)$")
SAFE_JSON_KEY = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")

MAX_GRID_BYTES = 1024 * 1024
MAX_REGISTER_BYTES = 1024 * 1024
MAX_FIXTURE_BYTES = 16 * 1024 * 1024
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
            # Echo a key only when it looks like a schema field, never raw input.
            raise GridInvalid(f"duplicate JSON key: {key}" if SAFE_JSON_KEY.fullmatch(key) else "duplicate JSON key")
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
    except RecursionError as error:
        raise GridInvalid("grid nesting is too deep") from error
    if not isinstance(document, dict):
        raise GridInvalid("grid must be a JSON object")
    return document


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _fixture_file_sha256(root: Path, value: Any, context: str) -> str:
    _require_repository_path(value, root, context)
    target = root.joinpath(*PurePosixPath(value).parts)
    if not target.is_file():
        raise GridInvalid(f"{context} must be a regular file: {value}")
    payload = target.read_bytes()
    if len(payload) > MAX_FIXTURE_BYTES:
        raise GridInvalid(f"{context} is larger than the bounded fixture size: {value}")
    # Canonical bytes: CRLF read as LF, so a Windows checkout (autocrlf) and a
    # Linux one pin the same digest.
    return hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()


def fixture_digests(document: dict[str, Any], root: Path = PROJECT_ROOT) -> dict[str, str]:
    """SHA-256 of the bytes of every fixture file the grid points at, by repository path."""

    digests: dict[str, str] = {}
    metrics = document.get("metrics") if isinstance(document, dict) else None
    for metric in metrics if isinstance(metrics, list) else []:
        fixture = metric.get("fixture") if isinstance(metric, dict) else None
        paths = fixture.get("paths") if isinstance(fixture, dict) else None
        for value in paths if isinstance(paths, list) else []:
            if isinstance(value, str) and value not in digests:
                digests[value] = _fixture_file_sha256(root, value, "fixture path")
            elif not isinstance(value, str):
                raise GridInvalid("fixture path is not a safe relative path")
    return dict(sorted(digests.items()))


def grid_sha256(document: dict[str, Any], root: Path = PROJECT_ROOT) -> str:
    """Digest of the grid entries and fixture files, independent of approvals.

    An approved threshold counts with the status recorded in
    ``approval.previous_status``: approving leaves the digest unchanged, any
    other status change (``proposed`` to ``confirmed``, say) breaks it.
    """

    content = copy.deepcopy(document)
    metrics = content.get("metrics")
    if isinstance(metrics, list):
        for metric in metrics:
            threshold = metric.get("threshold") if isinstance(metric, dict) else None
            if isinstance(threshold, dict):
                approval = threshold.pop("approval", None)
                if threshold.get("status") == "approved":
                    threshold["status"] = approval.get("previous_status") if isinstance(approval, dict) else None
    payload = {"grid": content, "fixture_sha256": fixture_digests(document, root)}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def load_decision_register(path: Path) -> dict[str, str]:
    """Map every ``D-xxx`` row of the register to the rest of its row text."""

    if path.is_symlink() or not path.is_file():
        raise GridInvalid("decision register is unavailable")
    payload = path.read_bytes()
    if not 1 <= len(payload) <= MAX_REGISTER_BYTES:
        raise GridInvalid("decision register size is outside the bounded range")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GridInvalid("decision register must be UTF-8") from error
    register: dict[str, str] = {}
    for line in text.splitlines():
        match = REGISTER_ROW.match(line.strip())
        if match is not None:
            register[match.group(1)] = match.group(2).strip()
    if not register:
        raise GridInvalid("decision register contains no decision")
    return register


def is_superseded(row: str) -> bool:
    return row.startswith("**SUPERSEDED")


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


def _require_decision(value: Any, register: dict[str, str], context: str) -> str:
    if not isinstance(value, str) or DECISION_ID.fullmatch(value) is None:
        raise GridInvalid(f"{context} must be a decision id D-xxx")
    if value not in register:
        raise GridInvalid(f"{context} {value} is not in the decision register")
    if is_superseded(register[value]):
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
    for value in paths:  # fixture bytes enter the grid digest: files only
        if not root.joinpath(*PurePosixPath(value).parts).is_file():
            raise GridInvalid(f"{context} path must be a regular file: {value}")
    return status


def _validate_threshold(value: Any, register: dict[str, str], today: date,
                        context: str) -> tuple[str, dict[str, Any] | None]:
    """Validate one threshold; return its status and, when approved, its approval to pin."""

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
        return status, None
    if "approval" not in threshold:
        raise GridInvalid(f"{context} is approved without an approval record")
    approval = _require_keys(threshold["approval"], APPROVAL_KEYS, f"{context} approval")
    _require_decision(approval["decision_id"], register, f"{context} approval decision")
    if approval["previous_status"] not in PRE_APPROVAL_STATUSES:
        raise GridInvalid(f"{context} approval previous_status must be one of {', '.join(PRE_APPROVAL_STATUSES)}")
    if approval["previous_status"] == "confirmed" and not decisions:
        raise GridInvalid(f"{context} was confirmed but cites no decision")
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
    return status, approval


def _check_pin(approval: dict[str, Any], register: dict[str, str], digest: str, context: str) -> None:
    """The pinned digest must be the grid's and be recorded in the approving decision row."""

    if approval["grid_sha256"] != digest:
        raise GridInvalid(f"{context} approval grid_sha256 does not match the grid content")
    if digest not in register[approval["decision_id"]]:
        raise GridInvalid(f"{context} approval decision {approval['decision_id']} does not record the pinned grid_sha256")


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
    approvals: list[tuple[str, dict[str, Any]]] = []
    for position, metric in enumerate(metrics):
        identifier = metric.get("id") if isinstance(metric, dict) else None
        label = identifier if isinstance(identifier, str) and METRIC_ID.fullmatch(identifier) else f"#{position}"
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
        status, approval = _validate_threshold(metric["threshold"], register, today, f"{context} threshold")
        thresholds[status] += 1
        if approval is not None:
            approvals.append((f"{context} threshold", approval))
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
    digest = grid_sha256(grid, root)
    for context, approval in approvals:
        _check_pin(approval, register, digest, context)
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
                        help="print only the grid SHA-256 (grid entries and fixture files) to record in the "
                             "approving decision entry (the grid must be valid)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = validate(load_grid(args.grid), root=args.root)
    except GridInvalid as error:
        print(f"invalid evaluation grid: {error}", file=sys.stderr)
        return 1
    except OSError as error:  # never echo the path: it may name internal storage
        print(f"invalid evaluation grid: input unreadable: {error.strerror or 'I/O error'}", file=sys.stderr)
        return 1
    if args.print_digest:
        print(summary["grid_sha256"])
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
