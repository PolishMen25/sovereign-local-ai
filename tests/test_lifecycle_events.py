"""Tests for the candidate lifecycle-event 0.1.0 schema and its replay.

Every event is synthetic: identifiers are counters, actors are technical
role names and subject digests are hashes of fixed labels.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any
import unittest
from unittest import mock

from tests._temp_support import sovereign_temporary_directory


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "services" / "quarantine" / "lifecycle.py"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "lifecycle-event.schema.json"
DOC_PATH = PROJECT_ROOT / "docs" / "data" / "lifecycle-events.md"
SPEC = importlib.util.spec_from_file_location("lifecycle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

L = MODULE
S = sys.modules["sovereign_quarantine_closed_schema"]
C = sys.modules["sovereign_quarantine_canonical_json"]

COLLECTOR = ("collector", "collector-ingress")
VALIDATOR = ("internal_service", "quarantine-validator")
OPERATOR = ("operator", "owner-review")
PROPOSAL = "0f" * 16


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class Journal:
    """Builds a consistent synthetic journal: counters, chain and timestamps."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.heads: dict[tuple[str, str, str], tuple[int, str, str]] = {}
        self.counter = 0

    def _base(self, event_type: str, subject: tuple[str, str, str], actor: tuple[str, str], reason_codes: tuple[str, ...], policy: str) -> dict[str, Any]:
        self.counter += 1
        moment = f"2026-09-01T10:{self.counter // 60:02d}:{self.counter % 60:02d}Z"
        return {
            "schema_version": "0.1.0",
            "event_id": f"00000000-0000-4000-8000-{self.counter:012d}",
            "event_type": event_type,
            "subject": {"artifact_kind": subject[0], "artifact_id": subject[1], "subject_sha256": subject[2]},
            "actor": {"kind": actor[0], "id": actor[1]},
            "decision": {"policy_id": policy, "policy_version": "1", "reason_codes": list(reason_codes)},
            "occurred_at": moment,
            "recorded_at": moment,
        }

    def register(
        self,
        event_type: str,
        subject: tuple[str, str, str],
        *,
        actor: tuple[str, str] = COLLECTOR,
        reason_codes: tuple[str, ...] = (),
        revision_of: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        event = self._base(event_type, subject, actor, reason_codes, "collector-ingress-v1")
        to_state = L.REJECTED_AT_INGRESS if event_type == L.INGRESS_REJECTED else L.RAW
        event.update(sequence=0, previous_event_sha256=None, from_state=None, to_state=to_state)
        if revision_of is not None:
            event["revision_of"] = {"artifact_kind": revision_of[0], "artifact_id": revision_of[1], "subject_sha256": revision_of[2]}
        self.events.append(event)
        self.heads[subject] = (0, L.event_sha256(event), to_state)
        return event

    def move(
        self,
        subject: tuple[str, str, str],
        to_state: str,
        *,
        actor: tuple[str, str] = VALIDATOR,
        reason_codes: tuple[str, ...] = (),
        superseded_by: tuple[str, str, str] | None = None,
        confirmation: bool = False,
    ) -> dict[str, Any]:
        sequence, head, state = self.heads[subject]
        event = self._base(L.STATE_TRANSITION, subject, actor, reason_codes, "quarantine-promotion-v1")
        event.update(sequence=sequence + 1, previous_event_sha256=head, from_state=state, to_state=to_state)
        if superseded_by is not None:
            event["superseded_by"] = {"artifact_kind": superseded_by[0], "artifact_id": superseded_by[1], "subject_sha256": superseded_by[2]}
        if confirmation:
            event["decision"]["confirmation_ref"] = {"capability": "knowledge.promote_approved", "proposal_id": PROPOSAL}
        self.events.append(event)
        self.heads[subject] = (sequence + 1, L.event_sha256(event), to_state)
        return event


PACKAGE_A = ("research_package", "3f1c2a9e-6b1d-4c1e-9a52-0d4b8e7f1a20", sha("raw-package-a"))
PACKAGE_B = ("research_package", "0b7c6f2e-4d1a-4f3b-9c2d-7e8f9a0b1c2d", sha("raw-package-b"))
PACKAGE_C = ("research_package", "5d2e8c1a-3b4f-4a6d-8e9c-1f2a3b4c5d6e", sha("raw-package-c"))
SUBMISSION = ("research_package", "7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d", sha("ingress-bytes-rejected"))
CONVERSATION = ("conversation", "9e8d7c6b-5a4f-4e3d-9c2b-1a0f9e8d7c6b", sha("conversation-original"))
REVISION_1 = ("conversation_revision", CONVERSATION[1], sha("conversation-revision-1"))
REVISION_2 = ("conversation_revision", CONVERSATION[1], sha("conversation-revision-2"))
DERIVED = ("derived_artifact", "drv-summary-0001", sha("derived-summary"))


def full_journal() -> Journal:
    journal = Journal()
    journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
    journal.move(PACKAGE_A, L.PENDING)
    journal.move(PACKAGE_A, L.VALIDATED, actor=OPERATOR, confirmation=True)
    journal.register(L.INGRESS_ACCEPTED, PACKAGE_B)
    journal.move(PACKAGE_B, L.PENDING)
    journal.move(PACKAGE_B, L.VALIDATED)
    journal.move(PACKAGE_A, L.SUPERSEDED, superseded_by=PACKAGE_B)
    journal.move(PACKAGE_A, L.ARCHIVED)
    journal.register(L.INGRESS_ACCEPTED, PACKAGE_C)
    journal.move(PACKAGE_C, L.PENDING)
    journal.move(PACKAGE_C, L.REJECTED, reason_codes=("PKG_INTEGRITY_MISMATCH",))
    journal.register(L.INGRESS_REJECTED, SUBMISSION, reason_codes=("SECRET_KNOWN_PREFIX",))
    journal.register(L.INGRESS_ACCEPTED, CONVERSATION)
    journal.register(L.INGRESS_ACCEPTED, REVISION_1, revision_of=CONVERSATION)
    journal.register(L.INGRESS_ACCEPTED, REVISION_2, revision_of=CONVERSATION)
    journal.register(L.DERIVED_RECORDED, DERIVED, actor=VALIDATOR)
    journal.move(DERIVED, L.PENDING)
    return journal


def refusal(events: list[dict[str, Any]], **kwargs: Any) -> tuple[tuple[str, ...], int]:
    try:
        L.replay(events, **kwargs)
    except L.LifecycleError as error:
        return error.reasons, error.event_index
    raise AssertionError("the journal was accepted")


def codes_of(event: dict[str, Any]) -> set[tuple[str, str]]:
    return {(finding.pointer, finding.code) for finding in L.evaluate_event(event)}


class SchemaParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_mirror_equals_the_schema_without_annotations(self) -> None:
        self.assertEqual(
            C.canonicalize(S.strip_annotations(self.schema)).decode("utf-8"),
            C.canonicalize(L.SCHEMA_MIRROR).decode("utf-8"),
        )

    def test_schema_is_draft_2020_12_and_closed_everywhere(self) -> None:
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", self.schema["$schema"])

        def walk(node: Any) -> int:
            if type(node) is not dict:
                return 0
            count = 0
            if node.get("type") == "object":
                self.assertIs(False, node.get("additionalProperties"))
                count += 1
            for child in list(node.get("properties", {}).values()) + list(node.get("$defs", {}).values()):
                count += walk(child)
            return count

        self.assertEqual(6, walk(self.schema))

    def test_the_transition_table_matches_the_documented_diagram(self) -> None:
        pairs = {(source, target) for source, targets in L.TRANSITIONS.items() for target in targets}
        self.assertEqual(
            {
                ("RAW", "PENDING"),
                ("PENDING", "VALIDATED"),
                ("PENDING", "REJECTED"),
                ("VALIDATED", "SUPERSEDED"),
                ("VALIDATED", "ARCHIVED"),
                ("SUPERSEDED", "ARCHIVED"),
                ("REJECTED", "ARCHIVED"),
            },
            pairs,
        )
        for terminal in L.TERMINAL_STATES:
            self.assertNotIn(terminal, L.TRANSITIONS)

    def test_no_content_field_exists(self) -> None:
        names = set(self.schema["properties"])
        for definition in self.schema["$defs"].values():
            names |= set(definition.get("properties", {}))
        for forbidden in ("text", "content", "body", "question", "response", "excerpt", "url", "path", "hostname"):
            self.assertNotIn(forbidden, names)


class EventRuleTests(unittest.TestCase):
    def test_every_event_of_the_reference_journal_is_valid(self) -> None:
        for index, event in enumerate(full_journal().events):
            with self.subTest(index=index):
                self.assertEqual(set(), codes_of(event))

    def test_collector_or_producer_can_never_emit_pending_or_validated(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        pending = journal.move(PACKAGE_A, L.PENDING, actor=COLLECTOR)
        self.assertIn(("/actor/kind", L.ACTOR_NOT_ALLOWED), codes_of(pending))
        validated = journal.move(PACKAGE_A, L.VALIDATED, actor=COLLECTOR)
        self.assertIn(("/actor/kind", L.ACTOR_NOT_ALLOWED), codes_of(validated))
        producer = copy.deepcopy(validated)
        producer["actor"]["kind"] = "producer"
        self.assertIn(("/actor/kind", "EVENT_ENUM_MISMATCH"), codes_of(producer))
        self.assertIn(("/actor/kind", L.ACTOR_NOT_ALLOWED), codes_of(producer))
        operator_ingress = Journal().register(L.INGRESS_ACCEPTED, PACKAGE_A, actor=OPERATOR)
        self.assertIn(("/actor/kind", L.ACTOR_NOT_ALLOWED), codes_of(operator_ingress))

    def test_illegal_transitions(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        skip = journal.move(PACKAGE_A, L.VALIDATED)
        self.assertIn(("/to_state", L.TRANSITION_NOT_ALLOWED), codes_of(skip))
        self.assertIn(("/to_state", "EVENT_CONST_MISMATCH"), codes_of(skip))
        for source in (L.ARCHIVED, L.REJECTED_AT_INGRESS):
            with self.subTest(source=source):
                event = copy.deepcopy(skip)
                event.update(from_state=source, to_state=L.PENDING)
                self.assertIn(("/to_state", L.TRANSITION_NOT_ALLOWED), codes_of(event))
                self.assertIn(("/from_state", "EVENT_ENUM_MISMATCH"), codes_of(event))
        back = copy.deepcopy(skip)
        back.update(from_state=L.VALIDATED, to_state=L.PENDING)
        self.assertIn(("/to_state", L.TRANSITION_NOT_ALLOWED), codes_of(back))

    def test_registration_shape(self) -> None:
        event = Journal().register(L.INGRESS_ACCEPTED, PACKAGE_A)
        cases = (
            ({"sequence": 1}, ("/sequence", "EVENT_CONST_MISMATCH")),
            ({"previous_event_sha256": sha("x")}, ("/previous_event_sha256", "EVENT_CONST_MISMATCH")),
            ({"from_state": L.RAW}, ("/from_state", "EVENT_CONST_MISMATCH")),
            ({"to_state": L.PENDING}, ("/to_state", L.TRANSITION_NOT_ALLOWED)),
        )
        for update, expected in cases:
            with self.subTest(update=update):
                changed = dict(event, **update)
                self.assertIn(expected, codes_of(changed))
        derived = Journal().register(L.INGRESS_ACCEPTED, DERIVED)
        self.assertIn(("/subject/artifact_kind", L.SUBJECT_KIND_NOT_ALLOWED), codes_of(derived))
        derived_by_collector = Journal().register(L.DERIVED_RECORDED, DERIVED)
        self.assertIn(("/actor/kind", L.ACTOR_NOT_ALLOWED), codes_of(derived_by_collector))

    def test_transition_shape(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        event = journal.move(PACKAGE_A, L.PENDING)
        self.assertIn(("/sequence", "EVENT_NUMBER_BELOW_MINIMUM"), codes_of(dict(event, sequence=0)))
        self.assertIn(("/previous_event_sha256", "EVENT_TYPE_MISMATCH"), codes_of(dict(event, previous_event_sha256=None)))
        self.assertIn(("/previous_event_sha256", "EVENT_PATTERN_MISMATCH"), codes_of(dict(event, previous_event_sha256=sha("x").upper())))

    def test_superseded_by_iff_superseded(self) -> None:
        journal = full_journal()
        superseded = next(event for event in journal.events if event["to_state"] == L.SUPERSEDED)
        missing = copy.deepcopy(superseded)
        del missing["superseded_by"]
        self.assertEqual({("/superseded_by", "EVENT_FIELD_MISSING")}, codes_of(missing))
        archived = next(event for event in journal.events if event["to_state"] == L.ARCHIVED)
        extra = dict(archived, superseded_by=superseded["superseded_by"])
        self.assertEqual({("/superseded_by", "EVENT_FIELD_FORBIDDEN")}, codes_of(extra))

    def test_rejections_carry_reason_codes(self) -> None:
        journal = full_journal()
        for state in (L.REJECTED, L.REJECTED_AT_INGRESS):
            with self.subTest(state=state):
                event = copy.deepcopy(next(event for event in journal.events if event["to_state"] == state))
                event["decision"]["reason_codes"] = []
                self.assertEqual({("/decision/reason_codes", "EVENT_ARRAY_TOO_SHORT")}, codes_of(event))
        event = copy.deepcopy(journal.events[0])
        for bad in (["lower_case"], ["A" * 65], ["SAME", "SAME"], ["X"] * 33):
            with self.subTest(bad=bad[:2]):
                event["decision"]["reason_codes"] = bad
                self.assertTrue(codes_of(event))

    def test_confirmation_ref_only_towards_validated(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        pending = journal.move(PACKAGE_A, L.PENDING, confirmation=True)
        self.assertEqual({("/decision/confirmation_ref", "EVENT_FIELD_FORBIDDEN")}, codes_of(pending))
        validated = journal.move(PACKAGE_A, L.VALIDATED, confirmation=True)
        self.assertEqual(set(), codes_of(validated))
        wrong = copy.deepcopy(validated)
        wrong["decision"]["confirmation_ref"]["capability"] = "knowledge.promote"
        self.assertEqual({("/decision/confirmation_ref/capability", "EVENT_CONST_MISMATCH")}, codes_of(wrong))

    def test_revision_link_shape(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, CONVERSATION)
        revision = journal.register(L.INGRESS_ACCEPTED, REVISION_1, revision_of=CONVERSATION)
        missing = copy.deepcopy(revision)
        del missing["revision_of"]
        self.assertEqual({("/revision_of", "EVENT_FIELD_MISSING")}, codes_of(missing))
        wrong_kind = copy.deepcopy(revision)
        wrong_kind["revision_of"]["artifact_kind"] = "research_package"
        self.assertEqual({("/revision_of/artifact_kind", "EVENT_CONST_MISMATCH")}, codes_of(wrong_kind))
        on_package = dict(journal.events[0], revision_of=revision["revision_of"])
        self.assertEqual({("/revision_of", "EVENT_FIELD_FORBIDDEN")}, codes_of(on_package))

    def test_time_order_and_formats(self) -> None:
        event = Journal().register(L.INGRESS_ACCEPTED, PACKAGE_A)
        self.assertEqual({("/recorded_at", L.TIME_ORDER)}, codes_of(dict(event, occurred_at="2026-09-01T10:00:02Z")))
        self.assertEqual({("/event_id", "EVENT_UUID_INVALID")}, codes_of(dict(event, event_id="event-1")))
        self.assertEqual({("/recorded_at", "EVENT_TIMESTAMP_INVALID")}, codes_of(dict(event, recorded_at="2026-09-01")))

    def test_unknown_members_and_auth_tag_placeholder(self) -> None:
        event = Journal().register(L.INGRESS_ACCEPTED, PACKAGE_A)
        self.assertEqual({("", "EVENT_FIELD_UNKNOWN")}, codes_of(dict(event, text="contenu")))
        tagged = dict(event, auth_tag={"scheme": "placeholder", "key_id": "key-0001", "value": sha("tag")})
        self.assertEqual(set(), codes_of(tagged))
        self.assertEqual(L.event_sha256(event), L.event_sha256(tagged))
        self.assertEqual({("/auth_tag/value", "EVENT_PATTERN_MISMATCH")}, codes_of(dict(event, auth_tag={"scheme": "x", "key_id": "k", "value": "short"})))
        self.assertEqual({("/subject", "EVENT_FIELD_UNKNOWN")}, codes_of(dict(event, subject=dict(event["subject"], path="raw/x"))))


class ReplayTests(unittest.TestCase):
    def test_replay_rebuilds_the_state_from_events_alone(self) -> None:
        journal = full_journal()
        result = L.replay(journal.events)
        self.assertEqual(len(journal.events), result.events_applied)
        self.assertEqual(0, result.duplicates_ignored)
        expected = {
            PACKAGE_A: L.ARCHIVED,
            PACKAGE_B: L.VALIDATED,
            PACKAGE_C: L.REJECTED,
            SUBMISSION: L.REJECTED_AT_INGRESS,
            CONVERSATION: L.RAW,
            REVISION_1: L.RAW,
            REVISION_2: L.RAW,
            DERIVED: L.PENDING,
        }
        self.assertEqual(expected, {key: subject.state for key, subject in result.subjects.items()})
        self.assertEqual(PACKAGE_B, result.subjects[PACKAGE_A].superseded_by)
        self.assertEqual(CONVERSATION, result.subjects[REVISION_2].revision_of)
        self.assertEqual(4, result.subjects[PACKAGE_A].sequence)
        self.assertEqual(L.event_sha256(journal.events[7]), result.subjects[PACKAGE_A].head_event_sha256)
        # A prefix of the journal gives the state at that point.
        self.assertEqual(L.VALIDATED, L.replay(journal.events[:3]).state_of(*PACKAGE_A))
        self.assertIsNone(L.replay(journal.events[:3]).state_of(*PACKAGE_B))
        # Replay is deterministic.
        self.assertEqual(L.replay(journal.events).as_dict(), result.as_dict())

    def test_identical_duplicates_are_idempotent(self) -> None:
        journal = full_journal()
        events = journal.events + [copy.deepcopy(journal.events[1]), copy.deepcopy(journal.events[-1])]
        result = L.replay(events)
        self.assertEqual(2, result.duplicates_ignored)
        self.assertEqual(L.replay(journal.events).as_dict()["subjects"], result.as_dict()["subjects"])

    def test_conflicting_duplicates_are_rejected(self) -> None:
        journal = full_journal()
        conflicting = copy.deepcopy(journal.events[1])
        conflicting["decision"]["reason_codes"] = ["OTHER_REASON"]
        self.assertEqual(((L.ID_CONFLICT,), len(journal.events)), refusal(journal.events + [conflicting]))
        retagged = dict(journal.events[1], auth_tag={"scheme": "placeholder", "key_id": "key-0001", "value": sha("tag")})
        self.assertEqual(((L.ID_CONFLICT,), len(journal.events)), refusal(journal.events + [retagged]))

    def test_illegal_transition_is_rejected_at_its_index(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        journal.move(PACKAGE_A, L.VALIDATED)
        reasons, index = refusal(journal.events)
        self.assertEqual(1, index)
        self.assertIn(L.TRANSITION_NOT_ALLOWED, reasons)

    def test_sequence_gaps_and_forks(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        pending = journal.move(PACKAGE_A, L.PENDING)
        gap = dict(pending, event_id="00000000-0000-4000-8000-000000000999", sequence=2)
        self.assertEqual(((L.SEQUENCE_GAP,), 1), refusal([journal.events[0], gap]))
        fork = dict(pending, event_id="00000000-0000-4000-8000-000000000998", actor={"kind": "operator", "id": "owner-review"})
        self.assertEqual(((L.FORK,), 2), refusal(journal.events + [fork]))
        second_registration = dict(journal.events[0], event_id="00000000-0000-4000-8000-000000000997")
        self.assertEqual(((L.FORK,), 1), refusal([journal.events[0], second_registration]))

    def test_chain_mismatches(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        journal.move(PACKAGE_A, L.PENDING)
        journal.move(PACKAGE_A, L.VALIDATED)
        wrong = copy.deepcopy(journal.events)
        wrong[2]["previous_event_sha256"] = sha("not-the-head")
        self.assertEqual(((L.CHAIN_MISMATCH,), 2), refusal(wrong))
        tampered = copy.deepcopy(journal.events)
        tampered[1]["decision"]["reason_codes"] = ["REWRITTEN"]
        self.assertEqual(((L.CHAIN_MISMATCH,), 2), refusal(tampered))
        # The placeholder tag is outside the chain: adding one breaks nothing.
        tagged = copy.deepcopy(journal.events)
        tagged[1]["auth_tag"] = {"scheme": "placeholder", "key_id": "key-0001", "value": sha("tag")}
        self.assertEqual(L.VALIDATED, L.replay(tagged).state_of(*PACKAGE_A))

    def test_state_and_subject_mismatches(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        claim = journal.move(PACKAGE_A, L.PENDING)
        claim.update(from_state=L.PENDING, to_state=L.VALIDATED)
        self.assertEqual(((L.STATE_MISMATCH,), 1), refusal(journal.events))
        orphan = Journal()
        orphan.heads[PACKAGE_B] = (0, sha("unknown-head"), L.RAW)
        orphan.move(PACKAGE_B, L.PENDING)
        self.assertEqual(((L.SUBJECT_UNKNOWN,), 0), refusal(orphan.events))

    def test_recorded_at_never_goes_back_for_a_subject(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        event = journal.move(PACKAGE_A, L.PENDING)
        event.update(occurred_at="2026-09-01T09:00:00Z", recorded_at="2026-09-01T09:00:00Z")
        self.assertEqual(((L.RECORDED_AT_REGRESSION,), 1), refusal(journal.events))

    def test_artifact_id_conflicts(self) -> None:
        journal = Journal()
        journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
        journal.register(L.INGRESS_ACCEPTED, (PACKAGE_A[0], PACKAGE_A[1], sha("different-bytes")))
        self.assertEqual(((L.ARTIFACT_ID_CONFLICT,), 1), refusal(journal.events))
        rejected = Journal()
        rejected.register(L.INGRESS_REJECTED, SUBMISSION, reason_codes=("JSON_DUPLICATE_KEY",))
        rejected.register(L.INGRESS_REJECTED, (SUBMISSION[0], SUBMISSION[1], sha("other")), reason_codes=("JSON_DUPLICATE_KEY",))
        self.assertEqual(((L.ARTIFACT_ID_CONFLICT,), 1), refusal(rejected.events))

    def test_revision_links_to_an_accepted_original(self) -> None:
        unknown = Journal()
        unknown.register(L.INGRESS_ACCEPTED, REVISION_1, revision_of=CONVERSATION)
        self.assertEqual(((L.REVISION_ORIGINAL_UNKNOWN,), 0), refusal(unknown.events))
        other_id = Journal()
        other_id.register(L.INGRESS_ACCEPTED, CONVERSATION)
        other_id.register(L.INGRESS_ACCEPTED, ("conversation_revision", "conv-other", sha("r")), revision_of=CONVERSATION)
        self.assertEqual(((L.REVISION_LINK_INVALID,), 1), refusal(other_id.events))
        same_bytes = Journal()
        same_bytes.register(L.INGRESS_ACCEPTED, CONVERSATION)
        same_bytes.register(L.INGRESS_ACCEPTED, ("conversation_revision", CONVERSATION[1], CONVERSATION[2]), revision_of=CONVERSATION)
        self.assertEqual(((L.REVISION_LINK_INVALID,), 1), refusal(same_bytes.events))
        refused_original = Journal()
        refused_original.register(L.INGRESS_REJECTED, ("conversation", CONVERSATION[1], CONVERSATION[2]), reason_codes=("SECRET_BEARER_TOKEN",))
        refused_original.register(L.INGRESS_ACCEPTED, REVISION_1, revision_of=CONVERSATION)
        self.assertEqual(((L.REVISION_ORIGINAL_UNKNOWN,), 1), refusal(refused_original.events))

    def test_superseded_by_must_be_a_validated_other_subject(self) -> None:
        def prepared() -> Journal:
            journal = Journal()
            journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
            journal.move(PACKAGE_A, L.PENDING)
            journal.move(PACKAGE_A, L.VALIDATED)
            journal.register(L.INGRESS_ACCEPTED, PACKAGE_B)
            return journal

        not_validated = prepared()
        not_validated.move(PACKAGE_A, L.SUPERSEDED, superseded_by=PACKAGE_B)
        self.assertEqual(((L.SUPERSEDED_BY_NOT_VALIDATED,), 4), refusal(not_validated.events))
        unknown = prepared()
        unknown.move(PACKAGE_A, L.SUPERSEDED, superseded_by=PACKAGE_C)
        self.assertEqual(((L.SUPERSEDED_BY_UNKNOWN,), 4), refusal(unknown.events))
        itself = prepared()
        itself.move(PACKAGE_A, L.SUPERSEDED, superseded_by=PACKAGE_A)
        self.assertEqual(((L.SUPERSEDED_BY_SELF,), 4), refusal(itself.events))

    def test_terminal_states_accept_no_transition(self) -> None:
        journal = full_journal()
        archived_head = journal.heads[PACKAGE_A]
        self.assertEqual(L.ARCHIVED, archived_head[2])
        journal.move(PACKAGE_A, L.PENDING)
        reasons, index = refusal(journal.events)
        self.assertEqual(len(journal.events) - 1, index)
        self.assertIn(L.TRANSITION_NOT_ALLOWED, reasons)

    def test_limits(self) -> None:
        self.assertEqual(((L.LIMIT_EXCEEDED,), 2), refusal(full_journal().events, max_events=2))
        reasons, index = refusal([["not", "an", "event"]])
        self.assertEqual(("EVENT_TYPE_MISMATCH",), reasons)
        self.assertEqual(0, index)


class RawAndSafetyTests(unittest.TestCase):
    def test_raw_bytes_and_digest_are_untouched_by_replay(self) -> None:
        with sovereign_temporary_directory() as directory:
            raw = Path(directory) / "raw" / "research-package.json"
            raw.parent.mkdir()
            raw.write_bytes(b'{"synthetic": "raw package bytes"}')
            before = (raw.read_bytes(), os.stat(raw).st_mtime_ns)
            digest = hashlib.sha256(before[0]).hexdigest()
            subject = ("research_package", "3f1c2a9e-6b1d-4c1e-9a52-0d4b8e7f1a20", digest)
            journal = Journal()
            journal.register(L.INGRESS_ACCEPTED, subject)
            journal.move(subject, L.PENDING)
            journal.move(subject, L.REJECTED, reason_codes=("PKG_TIMESTAMP_ORDER",))
            journal.move(subject, L.ARCHIVED)
            result = L.replay(journal.events)
            after = (raw.read_bytes(), os.stat(raw).st_mtime_ns)
            listing = sorted(path.name for path in Path(directory).rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(["raw", "research-package.json"], listing)
        self.assertEqual(L.ARCHIVED, result.state_of(*subject))
        self.assertEqual(digest, result.subjects[subject].subject_sha256)

    def test_module_never_writes_or_uses_the_network(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("write_bytes", "write_text", "os.replace", "os.remove", "unlink", "shutil", '"w', "'w", "import socket", "urllib", "http.client", "subprocess"):
            self.assertNotIn(forbidden, source)
        names = ("getaddrinfo", "create_connection", "socket")
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(mock.patch.object(socket, name, side_effect=AssertionError(name))) for name in names]
            L.replay(full_journal().events)
        for patched in mocks:
            patched.assert_not_called()

    def test_refusals_never_echo_content(self) -> None:
        marker = "synthetic-marker-3b9d"
        event = Journal().register(L.INGRESS_ACCEPTED, PACKAGE_A)
        event[marker] = marker
        event["actor"]["id"] = marker.upper()
        findings = L.evaluate_event(event)
        self.assertNotIn(marker, repr(findings))
        self.assertNotIn(marker.upper(), repr(findings))
        with self.assertRaises(L.LifecycleError) as caught:
            L.replay([event])
        self.assertNotIn(marker, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_every_code_is_documented(self) -> None:
        text = DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("PROVISOIRE", text)
        self.assertIn(L.POLICY_ID, text)
        self.assertIn("PR #17", text)
        for code in sorted(L.EVENT_RULE_CODES | L.REPLAY_CODES):
            self.assertIn(f"`{code}`", text)
        for state in L.STATES:
            self.assertIn(f"`{state}`", text)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, path: Path) -> tuple[int, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = L.main([str(path)])
        return code, stdout.getvalue() + stderr.getvalue()

    def test_cli_replays_a_jsonl_journal(self) -> None:
        journal = full_journal()
        with sovereign_temporary_directory() as directory:
            good = Path(directory) / "journal.jsonl"
            good.write_text("".join(json.dumps(event) + "\n" for event in journal.events), encoding="utf-8")
            bad = Path(directory) / "tampered.jsonl"
            events = copy.deepcopy(journal.events)
            events[2]["previous_event_sha256"] = sha("x")
            bad.write_text("\r\n".join(json.dumps(event) for event in events), encoding="utf-8")
            broken = Path(directory) / "broken.jsonl"
            broken.write_text(json.dumps(journal.events[0]) + '\n{"a": 1, "a": 2}\n', encoding="utf-8")
            results = [self.run_cli(path) for path in (good, bad, broken, Path(directory) / "missing.jsonl")]
        self.assertEqual([0, 1, 1, 2], [code for code, _ in results])
        report = json.loads(results[0][1])
        self.assertEqual(len(journal.events), report["events_applied"])
        self.assertEqual(8, len(report["subjects"]))
        self.assertEqual({"event_index": 2, "reasons": [L.CHAIN_MISMATCH]}, {k: v for k, v in json.loads(results[1][1]).items() if k in ("event_index", "reasons")})
        self.assertEqual(["JSON_DUPLICATE_KEY"], json.loads(results[2][1])["reasons"])
        self.assertEqual(1, json.loads(results[2][1])["event_index"])


if __name__ == "__main__":
    unittest.main()
