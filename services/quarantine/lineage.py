"""Derived-artifact records and their lineage check (derived-artifact 0.1.0).

PROVISOIRE: candidate contract ``derived-artifact-lineage-v1`` for issue #6,
specified in docs/data/derived-artifacts.md.  This module is a pure library.
It is not wired into any route, service or port.  It never touches the
network, never writes a file and never reads the bytes of an artifact: it
checks declared identifiers and digests only.

A derived-artifact record says which parents (RAW ingress artifacts or other
derived artifacts, each named by kind, id and SHA-256) a transformation used,
which transformation and version ran with which non-secret parameters, who
ran it, when, and the digest of the result.  Two layers run:

1. each record on its own: a mirror of ``schemas/derived-artifact.schema.json``
   (a test proves the mirror equals the schema file) plus rules the schema
   cannot express: time order, self-parenting, duplicate parents, at least one
   primary parent, secret-like parameter names or values;
2. a set of records against the known RAW roots (usually rebuilt from the
   lifecycle journal): identifier conflicts, unknown parents, parent digest
   mismatches, ``replaces`` targets and cycles.

A consistent set can then be walked from any derived artifact back to the RAW
digests it comes from.  Refusals carry reason codes and JSON Pointers made of
schema names and record indexes only; they never echo a value.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any, Iterable


POLICY_ID = "derived-artifact-lineage-v1"
SCHEMA_VERSION = "0.1.0"
CODE_PREFIX = "LINEAGE_"
JSON_PREFIX = "JSON_"
MAX_RECORDS = 1_000_000
MAX_PARENT_REFERENCES = 4_000_000


def _load_sibling(name: str, filename: str) -> ModuleType:
    """Load a sibling module by path, without touching sys.path."""

    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        if spec is None or spec.loader is None:
            raise ImportError(f"{filename} is missing next to lineage.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


_CANONICAL = _load_sibling("sovereign_quarantine_canonical_json", "canonical_json.py")
_SCHEMA = _load_sibling("sovereign_quarantine_closed_schema", "closed_schema.py")
_SECRET_SCAN = _load_sibling("sovereign_quarantine_secret_scan", "secret_scan.py")
_LIFECYCLE = _load_sibling("sovereign_quarantine_lifecycle", "lifecycle.py")

Finding = _SCHEMA.Finding

DERIVED_KIND = "derived_artifact"
ARTIFACT_KINDS: tuple[str, ...] = tuple(_LIFECYCLE.ARTIFACT_KINDS)
ROOT_KINDS = tuple(kind for kind in ARTIFACT_KINDS if kind != DERIVED_KIND)
ACTOR_KINDS: tuple[str, ...] = tuple(_LIFECYCLE.INTERNAL_ACTORS)
TRANSFORMATION_TYPES = ("redact", "clean", "summarize", "translate", "chunk", "embed", "index")
PRIMARY = "primary"
SUPPORTING = "supporting"
PARENT_ROLES = (PRIMARY, SUPPORTING)

# Same secret-like name fragments as generationParameter in
# schemas/research-package.schema.json (a test keeps both patterns equal).
SECRET_NAME_FRAGMENT = (
    "api[_-]?key|access[_-]?token|refresh[_-]?token|auth(?:orization)?|password|passwd|secret|credential"
    "|cookie|private[_-]?key"
)
PARAMETER_NAME_PATTERN = "^(?!.*(?:" + SECRET_NAME_FRAGMENT + "))[a-z][a-z0-9_.-]{0,63}$"
_SECRET_NAME = re.compile("(?i)(?:" + SECRET_NAME_FRAGMENT + ")")
# The mixed-token heuristic also fires on ordinary model or file names; its
# outcome is an owner decision, so it does not refuse a lineage record.
IGNORED_SECRET_CATEGORIES = frozenset({_SECRET_SCAN.MIXED_TOKEN})

# -- reason codes -------------------------------------------------------------

TIME_ORDER = "LINEAGE_TIME_ORDER"
SELF_PARENT = "LINEAGE_SELF_PARENT"
DUPLICATE_PARENT = "LINEAGE_DUPLICATE_PARENT"
NO_PRIMARY_PARENT = "LINEAGE_NO_PRIMARY_PARENT"
PARAMETER_NAME_SECRET = "LINEAGE_PARAMETER_NAME_SECRET"
PARAMETER_VALUE_SECRET = "LINEAGE_PARAMETER_VALUE_SECRET"
DUPLICATE_PARAMETER = "LINEAGE_DUPLICATE_PARAMETER"
REPLACES_SELF = "LINEAGE_REPLACES_SELF"

ARTIFACT_ID_CONFLICT = "LINEAGE_ARTIFACT_ID_CONFLICT"
PARENT_UNKNOWN = "LINEAGE_PARENT_UNKNOWN"
PARENT_HASH_MISMATCH = "LINEAGE_PARENT_HASH_MISMATCH"
REPLACES_UNKNOWN = "LINEAGE_REPLACES_UNKNOWN"
REPLACES_HASH_MISMATCH = "LINEAGE_REPLACES_HASH_MISMATCH"
CYCLE = "LINEAGE_CYCLE"
ARTIFACT_UNKNOWN = "LINEAGE_ARTIFACT_UNKNOWN"
LIMIT_EXCEEDED = "LINEAGE_LIMIT_EXCEEDED"

RECORD_RULE_CODES = frozenset(
    {
        TIME_ORDER,
        SELF_PARENT,
        DUPLICATE_PARENT,
        NO_PRIMARY_PARENT,
        PARAMETER_NAME_SECRET,
        PARAMETER_VALUE_SECRET,
        DUPLICATE_PARAMETER,
        REPLACES_SELF,
    }
)
GRAPH_CODES = frozenset(
    {
        ARTIFACT_ID_CONFLICT,
        PARENT_UNKNOWN,
        PARENT_HASH_MISMATCH,
        REPLACES_UNKNOWN,
        REPLACES_HASH_MISMATCH,
        CYCLE,
        ARTIFACT_UNKNOWN,
        LIMIT_EXCEEDED,
    }
)
STRUCTURAL_CODES = frozenset(CODE_PREFIX + code for code in _SCHEMA.GENERIC_CODES)

# -- mirror of schemas/derived-artifact.schema.json ---------------------------

_ARTIFACT_KIND = {"enum": list(ARTIFACT_KINDS)}

SCHEMA_MIRROR: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "artifact_id", "parents", "transformation", "actor", "started_at", "completed_at", "result"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "artifact_id": {"$ref": "#/$defs/identifier"},
        "parents": {"type": "array", "minItems": 1, "maxItems": 4096, "items": {"$ref": "#/$defs/parentRef"}},
        "transformation": {"$ref": "#/$defs/transformation"},
        "actor": {"$ref": "#/$defs/actor"},
        "started_at": {"$ref": "#/$defs/dateTime"},
        "completed_at": {"$ref": "#/$defs/dateTime"},
        "result": {"$ref": "#/$defs/result"},
        "replaces": {"$ref": "#/$defs/artifactRef"},
    },
    "$defs": {
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "dateTime": {"type": "string", "format": "date-time"},
        "identifier": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"},
        "artifactKind": _ARTIFACT_KIND,
        "artifactRef": {
            "type": "object",
            "additionalProperties": False,
            "required": ["artifact_kind", "artifact_id", "sha256"],
            "properties": {
                "artifact_kind": {"$ref": "#/$defs/artifactKind"},
                "artifact_id": {"$ref": "#/$defs/identifier"},
                "sha256": {"$ref": "#/$defs/sha256"},
            },
        },
        "parentRef": {
            "type": "object",
            "additionalProperties": False,
            "required": ["artifact_kind", "artifact_id", "sha256", "role"],
            "properties": {
                "artifact_kind": {"$ref": "#/$defs/artifactKind"},
                "artifact_id": {"$ref": "#/$defs/identifier"},
                "sha256": {"$ref": "#/$defs/sha256"},
                "role": {"enum": list(PARENT_ROLES)},
            },
        },
        "transformation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "version", "parameters"],
            "properties": {
                "type": {"enum": list(TRANSFORMATION_TYPES)},
                "version": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"},
                "parameters": {"type": "array", "maxItems": 64, "items": {"$ref": "#/$defs/parameter"}},
            },
        },
        "parameter": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "value"],
            "properties": {
                "name": {"type": "string", "pattern": PARAMETER_NAME_PATTERN},
                "value": {
                    "oneOf": [
                        {"type": "string", "maxLength": 1024},
                        {"type": "number"},
                        {"type": "boolean"},
                        {"type": "null"},
                    ]
                },
            },
        },
        "actor": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "id"],
            "properties": {
                "kind": {"enum": list(ACTOR_KINDS)},
                "id": {"type": "string", "pattern": "^[a-z][a-z0-9._-]{0,63}$"},
            },
        },
        "result": {
            "type": "object",
            "additionalProperties": False,
            "required": ["content_sha256", "byte_size", "media_type"],
            "properties": {
                "content_sha256": {"$ref": "#/$defs/sha256"},
                "byte_size": {"type": "integer", "minimum": 1, "maximum": 1099511627776},
                "media_type": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$",
                    "maxLength": 255,
                },
            },
        },
    },
}

_VALIDATOR = _SCHEMA.ClosedSchema(SCHEMA_MIRROR, code_prefix=CODE_PREFIX)
MAX_PARENTS = SCHEMA_MIRROR["properties"]["parents"]["maxItems"]
MAX_PARAMETERS = _VALIDATOR.definition("transformation")["properties"]["parameters"]["maxItems"]

ArtifactKey = tuple[str, str, str]


class LineageError(ValueError):
    """Lineage refusal: reason codes only, never content."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__(f"{POLICY_ID} refused: {', '.join(reasons)}")


def _key(reference: dict[str, Any]) -> ArtifactKey:
    return (reference["artifact_kind"], reference["artifact_id"], reference["sha256"])


def subject_key(record: dict[str, Any]) -> ArtifactKey:
    """Lifecycle subject of a valid record: its DERIVED_RECORDED event names this key."""

    return (DERIVED_KIND, record["artifact_id"], record["result"]["content_sha256"])


# -- one record ---------------------------------------------------------------


def _check_parents(record: dict[str, Any], add: Any) -> None:
    parents = _SCHEMA.bounded_list(record.get("parents"), MAX_PARENTS)
    artifact_id = record.get("artifact_id")
    seen: set[tuple[Any, Any, Any]] = set()
    primary = False
    for index, parent in enumerate(parents):
        if type(parent) is not dict:
            continue
        kind, parent_id = parent.get("artifact_kind"), parent.get("artifact_id")
        if kind == DERIVED_KIND and type(parent_id) is str and parent_id == artifact_id:
            add(SELF_PARENT, f"/parents/{index}")
        reference = (kind, parent_id, parent.get("sha256"))
        if all(type(part) is str for part in reference):
            if reference in seen:
                add(DUPLICATE_PARENT, f"/parents/{index}")
            seen.add(reference)
        primary = primary or parent.get("role") == PRIMARY
    if parents and not primary:
        add(NO_PRIMARY_PARENT, "/parents")


def _check_parameters(record: dict[str, Any], add: Any) -> None:
    transformation = record.get("transformation")
    if type(transformation) is not dict:
        return
    seen: set[str] = set()
    for index, parameter in enumerate(_SCHEMA.bounded_list(transformation.get("parameters"), MAX_PARAMETERS)):
        if type(parameter) is not dict:
            continue
        name, value = parameter.get("name"), parameter.get("value")
        pointer = f"/transformation/parameters/{index}"
        if type(name) is str:
            if _SECRET_NAME.search(name):
                add(PARAMETER_NAME_SECRET, pointer + "/name")
            if name in seen:
                add(DUPLICATE_PARAMETER, pointer + "/name")
            seen.add(name)
        if type(value) is str and len(value) <= 1024:
            categories = set(_SECRET_SCAN.scan_text(value).categories) - IGNORED_SECRET_CATEGORIES
            if categories:
                add(PARAMETER_VALUE_SECRET, pointer + "/value")


def _check_times(record: dict[str, Any], add: Any) -> None:
    started = _SCHEMA.parse_rfc3339(record.get("started_at"))
    completed = _SCHEMA.parse_rfc3339(record.get("completed_at"))
    if started is not None and completed is not None and completed < started:
        add(TIME_ORDER, "/completed_at")


def _check_replaces(record: dict[str, Any], add: Any) -> None:
    replaces = record.get("replaces")
    if type(replaces) is dict and replaces.get("artifact_kind") == DERIVED_KIND:
        if type(replaces.get("artifact_id")) is str and replaces.get("artifact_id") == record.get("artifact_id"):
            add(REPLACES_SELF, "/replaces")


def evaluate_record(record: Any) -> tuple[Any, ...]:
    """Findings for one record on its own: schema mirror plus record rules."""

    if type(record) is not dict:
        return (Finding("", CODE_PREFIX + _SCHEMA.TYPE_MISMATCH),)
    found: set[Any] = set(_VALIDATOR.evaluate(record))

    def add(code: str, pointer: str) -> None:
        found.add(Finding(pointer, code))

    _check_parents(record, add)
    _check_parameters(record, add)
    _check_times(record, add)
    _check_replaces(record, add)
    if not found:
        refusal: str | None = None
        try:
            _CANONICAL.canonicalize(record)
        except _CANONICAL.CanonicalJSONError as error:
            refusal = error.code
        if refusal is not None:
            found.add(Finding("", JSON_PREFIX + refusal))
    return _SCHEMA.finalize(found, CODE_PREFIX)


# -- a set of records -----------------------------------------------------------


@dataclass(frozen=True)
class LineageGraph:
    """A consistent lineage: every parent resolved, no conflict, no cycle."""

    records: dict[str, dict[str, Any]]
    roots: frozenset[ArtifactKey]

    def raw_roots(self, artifact_id: str) -> tuple[ArtifactKey, ...]:
        """RAW artifacts (kind, id, SHA-256) a derived artifact comes from, through parents only."""

        if artifact_id not in self.records:
            raise LineageError((ARTIFACT_UNKNOWN,))
        found: set[ArtifactKey] = set()
        visited: set[str] = set()
        stack = [artifact_id]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for parent in self.records[current]["parents"]:
                if parent["artifact_kind"] == DERIVED_KIND:
                    stack.append(parent["artifact_id"])
                else:
                    found.add(_key(parent))
        return tuple(sorted(found))

    def derived_ancestors(self, artifact_id: str) -> tuple[ArtifactKey, ...]:
        """Every derived artifact on the way from ``artifact_id`` to its RAW roots."""

        if artifact_id not in self.records:
            raise LineageError((ARTIFACT_UNKNOWN,))
        found: set[ArtifactKey] = set()
        stack = [artifact_id]
        while stack:
            for parent in self.records[stack.pop()]["parents"]:
                if parent["artifact_kind"] == DERIVED_KIND and _key(parent) not in found:
                    found.add(_key(parent))
                    stack.append(parent["artifact_id"])
        return tuple(sorted(found))


@dataclass(frozen=True)
class LineageResult:
    findings: tuple[Any, ...]
    records_checked: int
    duplicates_ignored: int
    graph: LineageGraph | None

    @property
    def valid(self) -> bool:
        return not self.findings

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return _SCHEMA.codes(self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": POLICY_ID,
            "schema_version": SCHEMA_VERSION,
            "valid": self.valid,
            "records_checked": self.records_checked,
            "duplicates_ignored": self.duplicates_ignored,
            "findings": [{"code": finding.code, "pointer": finding.pointer} for finding in self.findings],
        }


def roots_from_replay(replay_result: Any) -> frozenset[ArtifactKey]:
    """RAW roots known to a replayed lifecycle journal.

    Every ingress-accepted subject counts, whatever its later state:
    ``REJECTED``, ``SUPERSEDED`` and ``ARCHIVED`` never delete the RAW bytes.
    ``REJECTED_AT_INGRESS`` subjects were never stored, so they are excluded.
    """

    return frozenset(
        key
        for key, subject in replay_result.subjects.items()
        if subject.artifact_kind in ROOT_KINDS and subject.state != _LIFECYCLE.REJECTED_AT_INGRESS
    )


def _strongly_connected(nodes: list[str], edges: dict[str, list[str]]) -> list[list[str]]:
    """Iterative Tarjan: components of more than one node (self-loops are refused earlier)."""

    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0
    for start in nodes:
        if start in index_of:
            continue
        work = [(start, 0)]
        while work:
            node, position = work.pop()
            if position == 0:
                index_of[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            targets = edges.get(node, [])
            if position < len(targets):
                work.append((node, position + 1))
                target = targets[position]
                if target not in index_of:
                    work.append((target, 0))
                elif target in on_stack:
                    low[node] = min(low[node], index_of[target])
                continue
            if low[node] == index_of[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    components.append(component)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return components


def check_lineage(
    records: Iterable[Any],
    roots: Iterable[ArtifactKey],
    *,
    max_records: int = MAX_RECORDS,
) -> LineageResult:
    """Check a set of records against the known RAW roots; codes and pointers only.

    Pointers start with the record index (``/3/parents/0/sha256``).  A record
    that fails its own checks is left out of the graph, so its children report
    ``LINEAGE_PARENT_UNKNOWN``.
    """

    root_set = frozenset(roots)
    batch: list[Any] = []
    for record in records:
        if len(batch) >= max_records:
            return LineageResult((Finding("", LIMIT_EXCEEDED),), len(batch), 0, None)
        batch.append(record)
    found: set[Any] = set()

    def add(code: str, pointer: str) -> None:
        found.add(Finding(pointer, code))

    valid: dict[str, tuple[int, dict[str, Any]]] = {}
    canonical_of: dict[str, bytes] = {}
    duplicates = references = 0
    for index, record in enumerate(batch):
        record_findings = evaluate_record(record)
        for finding in record_findings:
            add(finding.code, f"/{index}{finding.pointer}")
        if record_findings:
            continue
        canonical = _CANONICAL.canonicalize(record)
        artifact_id = record["artifact_id"]
        if artifact_id in canonical_of:
            if canonical_of[artifact_id] == canonical:
                duplicates += 1
            else:
                add(ARTIFACT_ID_CONFLICT, f"/{index}/artifact_id")
            continue
        canonical_of[artifact_id] = canonical
        valid[artifact_id] = (index, record)
        references += len(record["parents"])
    if references > MAX_PARENT_REFERENCES:
        return LineageResult((Finding("", LIMIT_EXCEEDED),), len(batch), duplicates, None)

    root_digests: dict[tuple[str, str], set[str]] = {}
    for kind, artifact_id, digest in root_set:
        root_digests.setdefault((kind, artifact_id), set()).add(digest)

    def resolve(reference: dict[str, Any]) -> tuple[bool, bool]:
        """(known, digest matches) for a parent or ``replaces`` reference."""

        kind, artifact_id, digest = _key(reference)
        if kind == DERIVED_KIND:
            target = valid.get(artifact_id)
            if target is None:
                return False, False
            return True, target[1]["result"]["content_sha256"] == digest
        digests = root_digests.get((kind, artifact_id))
        if digests is None:
            return False, False
        return True, digest in digests

    edges: dict[str, list[str]] = {}
    for artifact_id, (index, record) in valid.items():
        targets: list[str] = []
        for position, parent in enumerate(record["parents"]):
            known, matches = resolve(parent)
            if not known:
                add(PARENT_UNKNOWN, f"/{index}/parents/{position}")
            elif not matches:
                add(PARENT_HASH_MISMATCH, f"/{index}/parents/{position}/sha256")
            elif parent["artifact_kind"] == DERIVED_KIND:
                targets.append(parent["artifact_id"])
        if "replaces" in record:
            known, matches = resolve(record["replaces"])
            if not known:
                add(REPLACES_UNKNOWN, f"/{index}/replaces")
            elif not matches:
                add(REPLACES_HASH_MISMATCH, f"/{index}/replaces/sha256")
            elif record["replaces"]["artifact_kind"] == DERIVED_KIND:
                # Whatever a record replaces is older than it, like its parents.
                targets.append(record["replaces"]["artifact_id"])
        edges[artifact_id] = targets
    for component in _strongly_connected(list(valid), edges):
        for artifact_id in component:
            add(CYCLE, f"/{valid[artifact_id][0]}")

    findings = _SCHEMA.finalize(found, CODE_PREFIX)
    graph = None
    if not findings:
        graph = LineageGraph({artifact_id: record for artifact_id, (_index, record) in valid.items()}, root_set)
    return LineageResult(findings, len(batch), duplicates, graph)


def build_graph(records: Iterable[Any], roots: Iterable[ArtifactKey]) -> LineageGraph:
    """The lineage graph of a consistent set, or ``LineageError`` with its codes."""

    result = check_lineage(records, roots)
    if result.graph is None:
        raise LineageError(result.reason_codes)
    return result.graph


# -- command line -----------------------------------------------------------------


def _read_jsonl(path: Path) -> tuple[list[Any] | None, tuple[str, ...], int]:
    """Strict JSONL reading, shared with the lifecycle replay (same bounds and codes)."""

    return _LIFECYCLE._read_journal(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Vérifie hors ligne la lignée d'artefacts dérivés contre un journal de cycle de vie "
        "(PROVISOIRE). La sortie ne contient que des identifiants, des empreintes et des codes de motif."
    )
    parser.add_argument("records", type=Path, help="enregistrements derived-artifact en JSONL, un par ligne")
    parser.add_argument("--journal", type=Path, required=True, help="journal JSONL d'événements de cycle de vie")
    parser.add_argument("--walk", metavar="ARTIFACT_ID", help="remonter ce dérivé jusqu'à ses racines RAW")
    arguments = parser.parse_args(argv)
    try:
        events, journal_reasons, journal_index = _read_jsonl(arguments.journal)
        records, record_reasons, record_index = _read_jsonl(arguments.records)
    except OSError:
        print("lineage check refused: an input file cannot be read", file=sys.stderr)
        return 2
    report: dict[str, Any]
    if events is not None:
        try:
            replay_result = _LIFECYCLE.replay(events)
        except _LIFECYCLE.LifecycleError as error:
            events, journal_reasons, journal_index = None, error.reasons, error.event_index
    if events is None:
        report = {"policy_id": POLICY_ID, "refused": "journal", "reasons": list(journal_reasons), "event_index": journal_index}
        print(_CANONICAL.canonicalize(report).decode("utf-8"))
        return 1
    if records is None:
        report = {"policy_id": POLICY_ID, "refused": "records", "reasons": list(record_reasons), "record_index": record_index}
        print(_CANONICAL.canonicalize(report).decode("utf-8"))
        return 1
    result = check_lineage(records, roots_from_replay(replay_result))
    if arguments.walk is None or result.graph is None:
        print(_CANONICAL.canonicalize(result.as_dict()).decode("utf-8"))
        return 0 if result.valid else 1
    try:
        roots = result.graph.raw_roots(arguments.walk)
    except LineageError as error:
        report = {"policy_id": POLICY_ID, "refused": "walk", "reasons": list(error.reasons)}
        print(_CANONICAL.canonicalize(report).decode("utf-8"))
        return 1
    report = {
        "policy_id": POLICY_ID,
        "artifact_id": arguments.walk,
        "raw_roots": [{"artifact_kind": kind, "artifact_id": artifact_id, "sha256": digest} for kind, artifact_id, digest in roots],
    }
    print(_CANONICAL.canonicalize(report).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
