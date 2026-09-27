"""Append-only lifecycle events and their replay (lifecycle-event 0.1.0).

PROVISOIRE: candidate contract ``lifecycle-event-replay-v1`` for issue #6,
specified in docs/data/lifecycle-events.md.  This module is a pure library.
It is not wired into any route, service or port.  It never touches the
network, never writes a file and never reads RAW bytes: the current state of
an artifact is rebuilt from the events alone, and RAW stays untouched.

Each event is checked against a mirror of
``schemas/lifecycle-event.schema.json`` (the transition table below is its
single source: the mirror's conditional rules are generated from it, and a
test proves the mirror equals the schema file).  Replay then checks what one
event cannot show on its own: per-subject sequence numbers without gaps or
forks, the RFC 8785 hash chain, the current state, idempotent duplicates,
identifier conflicts, the RAW revision to original link and the
``superseded_by`` target.

Refusals carry reason codes and the index of the offending event only.  The
authentication tag is a placeholder: its scheme, keys and verification are an
owner decision, so replay neither verifies it nor includes it in the chain.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Iterable


POLICY_ID = "lifecycle-event-replay-v1"
SCHEMA_VERSION = "0.1.0"
CODE_PREFIX = "EVENT_"
JSON_PREFIX = "JSON_"
AUTH_TAG_MEMBER = "auth_tag"
MAX_EVENTS = 1_000_000
MAX_JOURNAL_BYTES = 64 * 1024 * 1024


def _load_sibling(name: str, filename: str) -> ModuleType:
    """Load a sibling module by path, without touching sys.path."""

    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        if spec is None or spec.loader is None:
            raise ImportError(f"{filename} is missing next to lifecycle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


_CANONICAL = _load_sibling("sovereign_quarantine_canonical_json", "canonical_json.py")
_SCHEMA = _load_sibling("sovereign_quarantine_closed_schema", "closed_schema.py")

Finding = _SCHEMA.Finding

# -- states, event types and transitions ------------------------------------

RAW = "RAW"
PENDING = "PENDING"
VALIDATED = "VALIDATED"
REJECTED = "REJECTED"
SUPERSEDED = "SUPERSEDED"
ARCHIVED = "ARCHIVED"
REJECTED_AT_INGRESS = "REJECTED_AT_INGRESS"
STATES = (RAW, PENDING, VALIDATED, REJECTED, SUPERSEDED, ARCHIVED, REJECTED_AT_INGRESS)

INGRESS_ACCEPTED = "INGRESS_ACCEPTED"
INGRESS_REJECTED = "INGRESS_REJECTED"
DERIVED_RECORDED = "DERIVED_RECORDED"
STATE_TRANSITION = "STATE_TRANSITION"
EVENT_TYPES = (INGRESS_ACCEPTED, INGRESS_REJECTED, DERIVED_RECORDED, STATE_TRANSITION)
REGISTRATION_TYPES = (INGRESS_ACCEPTED, INGRESS_REJECTED, DERIVED_RECORDED)

ARTIFACT_KINDS = ("research_package", "conversation", "conversation_revision", "derived_artifact")
ACTOR_KINDS = ("collector", "internal_service", "operator")
INTERNAL_ACTORS = ("internal_service", "operator")

# The documented ordinary transitions (provenance-and-lifecycle.md).  This
# table is the single source of the schema's transition rules.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    RAW: (PENDING,),
    PENDING: (VALIDATED, REJECTED),
    VALIDATED: (SUPERSEDED, ARCHIVED),
    SUPERSEDED: (ARCHIVED,),
    REJECTED: (ARCHIVED,),
}
TERMINAL_STATES = (ARCHIVED, REJECTED_AT_INGRESS)

# event type -> (to_state options, actor kinds, subject kinds or None for any)
REGISTRATIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...] | None]] = {
    INGRESS_ACCEPTED: ((RAW,), ("collector",), ("research_package", "conversation", "conversation_revision")),
    INGRESS_REJECTED: ((REJECTED_AT_INGRESS,), ("collector",), ("research_package", "conversation")),
    DERIVED_RECORDED: ((RAW,), INTERNAL_ACTORS, ("derived_artifact",)),
    STATE_TRANSITION: ((PENDING, VALIDATED, REJECTED, SUPERSEDED, ARCHIVED), INTERNAL_ACTORS, None),
}

# -- reason codes -------------------------------------------------------------

TRANSITION_NOT_ALLOWED = "EVENT_TRANSITION_NOT_ALLOWED"
ACTOR_NOT_ALLOWED = "EVENT_ACTOR_NOT_ALLOWED"
SUBJECT_KIND_NOT_ALLOWED = "EVENT_SUBJECT_KIND_NOT_ALLOWED"
TIME_ORDER = "EVENT_TIME_ORDER"
ID_CONFLICT = "EVENT_ID_CONFLICT"
FORK = "EVENT_FORK"
SEQUENCE_GAP = "EVENT_SEQUENCE_GAP"
SUBJECT_UNKNOWN = "EVENT_SUBJECT_UNKNOWN"
CHAIN_MISMATCH = "EVENT_CHAIN_MISMATCH"
STATE_MISMATCH = "EVENT_STATE_MISMATCH"
RECORDED_AT_REGRESSION = "EVENT_RECORDED_AT_REGRESSION"
ARTIFACT_ID_CONFLICT = "EVENT_ARTIFACT_ID_CONFLICT"
REVISION_ORIGINAL_UNKNOWN = "EVENT_REVISION_ORIGINAL_UNKNOWN"
REVISION_LINK_INVALID = "EVENT_REVISION_LINK_INVALID"
SUPERSEDED_BY_UNKNOWN = "EVENT_SUPERSEDED_BY_UNKNOWN"
SUPERSEDED_BY_SELF = "EVENT_SUPERSEDED_BY_SELF"
SUPERSEDED_BY_NOT_VALIDATED = "EVENT_SUPERSEDED_BY_NOT_VALIDATED"
LIMIT_EXCEEDED = "EVENT_LIMIT_EXCEEDED"

EVENT_RULE_CODES = frozenset({TRANSITION_NOT_ALLOWED, ACTOR_NOT_ALLOWED, SUBJECT_KIND_NOT_ALLOWED, TIME_ORDER})
REPLAY_CODES = frozenset(
    {
        ID_CONFLICT,
        FORK,
        SEQUENCE_GAP,
        SUBJECT_UNKNOWN,
        CHAIN_MISMATCH,
        STATE_MISMATCH,
        RECORDED_AT_REGRESSION,
        ARTIFACT_ID_CONFLICT,
        REVISION_ORIGINAL_UNKNOWN,
        REVISION_LINK_INVALID,
        SUPERSEDED_BY_UNKNOWN,
        SUPERSEDED_BY_SELF,
        SUPERSEDED_BY_NOT_VALIDATED,
        LIMIT_EXCEEDED,
    }
)
STRUCTURAL_CODES = frozenset(CODE_PREFIX + code for code in _SCHEMA.GENERIC_CODES)

# -- mirror of schemas/lifecycle-event.schema.json ----------------------------


def _when(member: str, value: Any) -> dict[str, Any]:
    keyword = "enum" if type(value) is list else "const"
    return {"properties": {member: {keyword: value}}, "required": [member]}


def _one_or_many(values: tuple[str, ...]) -> dict[str, Any]:
    return {"const": values[0]} if len(values) == 1 else {"enum": list(values)}


def _event_type_rule(event_type: str) -> dict[str, Any]:
    to_states, actors, kinds = REGISTRATIONS[event_type]
    then: dict[str, Any] = {
        "to_state": _one_or_many(to_states),
        "actor": {"properties": {"kind": _one_or_many(actors)}},
    }
    if kinds is not None:
        then["subject"] = {"properties": {"artifact_kind": _one_or_many(kinds)}}
    return {"if": _when("event_type", event_type), "then": {"properties": then}}


def _transition_rules() -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[str]] = {}
    for source, targets in TRANSITIONS.items():
        groups.setdefault(targets, []).append(source)
    rules = []
    for targets, sources in groups.items():
        condition = _when("from_state", sources[0] if len(sources) == 1 else sources)
        rules.append({"if": condition, "then": {"properties": {"to_state": _one_or_many(targets)}}})
    return rules


SCHEMA_MIRROR: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "event_id",
        "event_type",
        "subject",
        "sequence",
        "previous_event_sha256",
        "from_state",
        "to_state",
        "actor",
        "decision",
        "occurred_at",
        "recorded_at",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "event_id": {"type": "string", "format": "uuid"},
        "event_type": {"enum": list(EVENT_TYPES)},
        "subject": {"$ref": "#/$defs/subjectRef"},
        "sequence": {"type": "integer", "minimum": 0, "maximum": MAX_EVENTS},
        "previous_event_sha256": {"type": ["string", "null"], "pattern": "^[a-f0-9]{64}$"},
        "from_state": {"enum": [None, *TRANSITIONS]},
        "to_state": {"enum": list(STATES)},
        "actor": {"$ref": "#/$defs/actor"},
        "decision": {"$ref": "#/$defs/decision"},
        "superseded_by": {"$ref": "#/$defs/subjectRef"},
        "revision_of": {"$ref": "#/$defs/subjectRef"},
        "occurred_at": {"$ref": "#/$defs/dateTime"},
        "recorded_at": {"$ref": "#/$defs/dateTime"},
        "auth_tag": {"$ref": "#/$defs/authTag"},
    },
    "allOf": [
        {
            "if": _when("event_type", list(REGISTRATION_TYPES)),
            "then": {
                "properties": {
                    "sequence": {"const": 0},
                    "previous_event_sha256": {"const": None},
                    "from_state": {"const": None},
                }
            },
            "else": {
                "properties": {
                    "sequence": {"minimum": 1},
                    "previous_event_sha256": {"type": "string"},
                    "from_state": {"type": "string"},
                }
            },
        },
        *(_event_type_rule(event_type) for event_type in EVENT_TYPES),
        *_transition_rules(),
        {
            "if": _when("to_state", SUPERSEDED),
            "then": {"required": ["superseded_by"]},
            "else": {"properties": {"superseded_by": False}},
        },
        {
            "if": _when("to_state", [REJECTED, REJECTED_AT_INGRESS]),
            "then": {"properties": {"decision": {"properties": {"reason_codes": {"minItems": 1}}}}},
        },
        {
            "if": {
                "properties": {
                    "event_type": {"const": INGRESS_ACCEPTED},
                    "subject": _when("artifact_kind", "conversation_revision"),
                },
                "required": ["event_type", "subject"],
            },
            "then": {
                "required": ["revision_of"],
                "properties": {"revision_of": {"properties": {"artifact_kind": {"const": "conversation"}}}},
            },
            "else": {"properties": {"revision_of": False}},
        },
        {
            "if": _when("to_state", VALIDATED),
            "else": {"properties": {"decision": {"properties": {"confirmation_ref": False}}}},
        },
    ],
    "$defs": {
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "dateTime": {"type": "string", "format": "date-time"},
        "identifier": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"},
        "subjectRef": {
            "type": "object",
            "additionalProperties": False,
            "required": ["artifact_kind", "artifact_id", "subject_sha256"],
            "properties": {
                "artifact_kind": {"enum": list(ARTIFACT_KINDS)},
                "artifact_id": {"$ref": "#/$defs/identifier"},
                "subject_sha256": {"$ref": "#/$defs/sha256"},
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
        "decision": {
            "type": "object",
            "additionalProperties": False,
            "required": ["policy_id", "policy_version", "reason_codes"],
            "properties": {
                "policy_id": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{2,127}$"},
                "policy_version": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"},
                "reason_codes": {
                    "type": "array",
                    "maxItems": 32,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,63}$"},
                },
                "confirmation_ref": {"$ref": "#/$defs/confirmationRef"},
            },
        },
        "confirmationRef": {
            "type": "object",
            "additionalProperties": False,
            "required": ["capability", "proposal_id"],
            "properties": {
                "capability": {"const": "knowledge.promote_approved"},
                "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
            },
        },
        "authTag": {
            "type": "object",
            "additionalProperties": False,
            "required": ["scheme", "key_id", "value"],
            "properties": {
                "scheme": {"type": "string", "pattern": "^[a-z0-9][a-z0-9.-]{0,63}$"},
                "key_id": {"$ref": "#/$defs/identifier"},
                "value": {"type": "string", "pattern": "^[A-Za-z0-9_-]{16,2048}$"},
            },
        },
    },
}

_VALIDATOR = _SCHEMA.ClosedSchema(SCHEMA_MIRROR, code_prefix=CODE_PREFIX)

SubjectKey = tuple[str, str, str]


class LifecycleError(ValueError):
    """Replay refusal: reason codes and the event index, never content."""

    def __init__(self, reasons: tuple[str, ...], event_index: int) -> None:
        self.reasons = reasons
        self.event_index = event_index
        super().__init__(f"{POLICY_ID} refused event {event_index}: {', '.join(reasons)}")


@dataclass(frozen=True)
class SubjectState:
    artifact_kind: str
    artifact_id: str
    subject_sha256: str
    state: str
    sequence: int
    head_event_sha256: str
    recorded_at: str
    superseded_by: SubjectKey | None = None
    revision_of: SubjectKey | None = None

    @property
    def key(self) -> SubjectKey:
        return (self.artifact_kind, self.artifact_id, self.subject_sha256)


@dataclass(frozen=True)
class ReplayResult:
    subjects: dict[SubjectKey, SubjectState]
    events_applied: int
    duplicates_ignored: int

    def state_of(self, artifact_kind: str, artifact_id: str, subject_sha256: str) -> str | None:
        subject = self.subjects.get((artifact_kind, artifact_id, subject_sha256))
        return None if subject is None else subject.state

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": POLICY_ID,
            "events_applied": self.events_applied,
            "duplicates_ignored": self.duplicates_ignored,
            "subjects": [
                {
                    "artifact_kind": subject.artifact_kind,
                    "artifact_id": subject.artifact_id,
                    "subject_sha256": subject.subject_sha256,
                    "state": subject.state,
                    "sequence": subject.sequence,
                }
                for _key, subject in sorted(self.subjects.items())
            ],
        }


def event_sha256(event: dict[str, Any]) -> str:
    """Chain digest: RFC 8785 SHA-256 of the event without its ``auth_tag``."""

    return _CANONICAL.canonical_sha256({key: value for key, value in event.items() if key != AUTH_TAG_MEMBER})


def _key(reference: dict[str, Any]) -> SubjectKey:
    return (reference["artifact_kind"], reference["artifact_id"], reference["subject_sha256"])


def evaluate_event(event: Any) -> tuple[Any, ...]:
    """Findings for one event on its own: schema mirror plus explicit rule codes."""

    if type(event) is not dict:
        return (Finding("", CODE_PREFIX + _SCHEMA.TYPE_MISMATCH),)
    found: set[Any] = set(_VALIDATOR.evaluate(event))
    event_type = event.get("event_type")
    if event_type in REGISTRATIONS:
        to_states, actors, kinds = REGISTRATIONS[event_type]
        from_state, to_state = event.get("from_state"), event.get("to_state")
        if event_type == STATE_TRANSITION:
            allowed = type(from_state) is str and to_state in TRANSITIONS.get(from_state, ())
        else:
            allowed = from_state is None and to_state in to_states
        if not allowed:
            found.add(Finding("/to_state", TRANSITION_NOT_ALLOWED))
        actor = event.get("actor")
        if type(actor) is dict and actor.get("kind") not in actors:
            found.add(Finding("/actor/kind", ACTOR_NOT_ALLOWED))
        subject = event.get("subject")
        if kinds is not None and type(subject) is dict and subject.get("artifact_kind") not in kinds:
            found.add(Finding("/subject/artifact_kind", SUBJECT_KIND_NOT_ALLOWED))
    occurred = _SCHEMA.parse_rfc3339(event.get("occurred_at"))
    recorded = _SCHEMA.parse_rfc3339(event.get("recorded_at"))
    if occurred is not None and recorded is not None and occurred > recorded:
        found.add(Finding("/recorded_at", TIME_ORDER))
    if not found:
        refusal: str | None = None
        try:
            _CANONICAL.canonicalize(event)
        except _CANONICAL.CanonicalJSONError as error:
            refusal = error.code
        if refusal is not None:
            found.add(Finding("", JSON_PREFIX + refusal))
    return _SCHEMA.finalize(found, CODE_PREFIX)


def replay(events: Iterable[Any], *, max_events: int = MAX_EVENTS) -> ReplayResult:
    """Rebuild every subject's state from the journal, in journal order.

    The first refusal stops the replay: a journal is either fully consistent
    or rejected, never partially applied.
    """

    subjects: dict[SubjectKey, SubjectState] = {}
    registered: dict[tuple[str, str], SubjectKey] = {}
    seen: dict[str, bytes] = {}
    applied = duplicates = 0
    for index, event in enumerate(events):
        if index >= max_events:
            raise LifecycleError((LIMIT_EXCEEDED,), index)
        findings = evaluate_event(event)
        if findings:
            raise LifecycleError(_SCHEMA.codes(findings), index)
        canonical = _CANONICAL.canonicalize(event)
        event_id = event["event_id"].lower()
        if event_id in seen:
            if seen[event_id] == canonical:
                duplicates += 1
                continue
            raise LifecycleError((ID_CONFLICT,), index)
        key = _key(event["subject"])
        current = subjects.get(key)
        recorded_at = event["recorded_at"]
        if event["event_type"] in REGISTRATION_TYPES:
            if current is not None:
                raise LifecycleError((FORK,), index)
            kind, artifact_id, sha256 = key
            if kind != "conversation_revision" and (kind, artifact_id) in registered:
                raise LifecycleError((ARTIFACT_ID_CONFLICT,), index)
            revision_of = None
            if "revision_of" in event:
                revision_of = _key(event["revision_of"])
                if revision_of[1] != artifact_id or revision_of[2] == sha256:
                    raise LifecycleError((REVISION_LINK_INVALID,), index)
                original = subjects.get(revision_of)
                if original is None or original.state == REJECTED_AT_INGRESS:
                    raise LifecycleError((REVISION_ORIGINAL_UNKNOWN,), index)
            registered.setdefault((kind, artifact_id), key)
            subjects[key] = SubjectState(kind, artifact_id, sha256, event["to_state"], 0, event_sha256(event), recorded_at, None, revision_of)
        else:
            if current is None:
                raise LifecycleError((SUBJECT_UNKNOWN,), index)
            if event["sequence"] <= current.sequence:
                raise LifecycleError((FORK,), index)
            if event["sequence"] > current.sequence + 1:
                raise LifecycleError((SEQUENCE_GAP,), index)
            if event["previous_event_sha256"] != current.head_event_sha256:
                raise LifecycleError((CHAIN_MISMATCH,), index)
            if event["from_state"] != current.state:
                raise LifecycleError((STATE_MISMATCH,), index)
            if _SCHEMA.parse_rfc3339(recorded_at) < _SCHEMA.parse_rfc3339(current.recorded_at):
                raise LifecycleError((RECORDED_AT_REGRESSION,), index)
            superseded_by = None
            if event["to_state"] == SUPERSEDED:
                superseded_by = _key(event["superseded_by"])
                if superseded_by == key:
                    raise LifecycleError((SUPERSEDED_BY_SELF,), index)
                replacement = subjects.get(superseded_by)
                if replacement is None:
                    raise LifecycleError((SUPERSEDED_BY_UNKNOWN,), index)
                if replacement.state != VALIDATED:
                    raise LifecycleError((SUPERSEDED_BY_NOT_VALIDATED,), index)
            subjects[key] = SubjectState(
                current.artifact_kind,
                current.artifact_id,
                current.subject_sha256,
                event["to_state"],
                event["sequence"],
                event_sha256(event),
                recorded_at,
                superseded_by or current.superseded_by,
                current.revision_of,
            )
        seen[event_id] = canonical
        applied += 1
    return ReplayResult(subjects, applied, duplicates)


def _read_journal(path: Path) -> tuple[list[Any] | None, tuple[str, ...], int]:
    """Parse a JSONL journal strictly; returns events or refusal codes and line index."""

    with path.open("rb") as handle:
        data = handle.read(MAX_JOURNAL_BYTES + 1)
    if len(data) > MAX_JOURNAL_BYTES:
        return None, (JSON_PREFIX + "SIZE_EXCEEDED",), -1
    events: list[Any] = []
    for index, line in enumerate(line for line in data.split(b"\n") if line.strip()):
        refusal: str | None = None
        try:
            events.append(_CANONICAL.loads_strict(line.rstrip(b"\r")))
        except _CANONICAL.CanonicalJSONError as error:
            refusal = error.code
        if refusal is not None:
            return None, (JSON_PREFIX + refusal,), index
    return events, (), -1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rejoue hors ligne un journal JSONL d'événements de cycle de vie (PROVISOIRE). "
        "La sortie ne contient que des états, des identifiants et des codes de motif."
    )
    parser.add_argument("path", type=Path, help="journal JSONL, un événement par ligne, dans l'ordre d'ajout")
    arguments = parser.parse_args(argv)
    try:
        events, reasons, index = _read_journal(arguments.path)
    except OSError:
        print("replay refused: the journal cannot be read", file=sys.stderr)
        return 2
    if events is not None:
        try:
            result = replay(events)
        except LifecycleError as error:
            reasons, index = error.reasons, error.event_index
        else:
            print(_CANONICAL.canonicalize(result.as_dict()).decode("utf-8"))
            return 0
    report = {"policy_id": POLICY_ID, "refused": True, "reasons": list(reasons), "event_index": index}
    print(_CANONICAL.canonicalize(report).decode("utf-8"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
