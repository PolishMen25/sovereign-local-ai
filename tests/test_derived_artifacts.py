"""Tests for the candidate derived-artifact 0.1.0 schema and its lineage check.

Every record is synthetic: identifiers are counters, actors are technical
role names and every digest is the hash of a fixed label.  Secret-shaped
parameter values are assembled at run time, so no such literal is committed.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import random
import socket
import sys
from typing import Any
import unittest
from unittest import mock

from tests._temp_support import sovereign_temporary_directory


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "services" / "quarantine" / "lineage.py"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "derived-artifact.schema.json"
DOC_PATH = PROJECT_ROOT / "docs" / "data" / "derived-artifacts.md"
SPEC = importlib.util.spec_from_file_location("lineage", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

G = MODULE
S = sys.modules["sovereign_quarantine_closed_schema"]
C = sys.modules["sovereign_quarantine_canonical_json"]
L = sys.modules["sovereign_quarantine_lifecycle"]
SCAN = sys.modules["sovereign_quarantine_secret_scan"]


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


PACKAGE_A = ("research_package", "3f1c2a9e-6b1d-4c1e-9a52-0d4b8e7f1a20", sha("raw-package-a"))
PACKAGE_B = ("research_package", "0b7c6f2e-4d1a-4f3b-9c2d-7e8f9a0b1c2d", sha("raw-package-b"))
CONVERSATION = ("conversation", "9e8d7c6b-5a4f-4e3d-9c2b-1a0f9e8d7c6b", sha("conversation-original"))
REVISION = ("conversation_revision", CONVERSATION[1], sha("conversation-revision-1"))
ROOTS = frozenset({PACKAGE_A, PACKAGE_B, CONVERSATION, REVISION})


def ref(key: tuple[str, str, str], role: str = "primary") -> dict[str, str]:
    return {"artifact_kind": key[0], "artifact_id": key[1], "sha256": key[2], "role": role}


def derived(artifact_id: str) -> tuple[str, str, str]:
    return ("derived_artifact", artifact_id, sha("result-" + artifact_id))


def record(
    artifact_id: str,
    transformation: str,
    parents: list[dict[str, str]],
    *,
    parameters: tuple[tuple[str, Any], ...] = (),
    replaces: tuple[str, str, str] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "0.1.0",
        "artifact_id": artifact_id,
        "parents": parents,
        "transformation": {
            "type": transformation,
            "version": "1.0.0",
            "parameters": [{"name": name, "value": value} for name, value in parameters],
        },
        "actor": {"kind": "internal_service", "id": "quarantine-deriver"},
        "started_at": "2026-09-02T10:00:00Z",
        "completed_at": "2026-09-02T10:00:05Z",
        "result": {"content_sha256": sha("result-" + artifact_id), "byte_size": 4096, "media_type": "application/jsonl"},
    }
    if replaces is not None:
        document["replaces"] = {"artifact_kind": replaces[0], "artifact_id": replaces[1], "sha256": replaces[2]}
    return document


def reference_records() -> list[dict[str, Any]]:
    """RAW package -> redact -> clean -> chunk -> embed -> index, plus a summary and a translation."""

    return [
        record("drv-redact-0001", "redact", [ref(PACKAGE_A)], parameters=(("policy", "producer-redaction-v1"),)),
        record("drv-clean-0001", "clean", [ref(derived("drv-redact-0001"))], parameters=(("normalization", "unicode-nfc-v1"),)),
        record("drv-chunk-0001", "chunk", [ref(derived("drv-clean-0001"))], parameters=(("chunk_size", 512), ("overlap", 64))),
        record(
            "drv-embed-0001",
            "embed",
            [ref(derived("drv-chunk-0001"))],
            parameters=(("model", "synthetic-embedder-0.6b"), ("dimensions", 1024), ("normalize", True)),
        ),
        record("drv-index-0001", "index", [ref(derived("drv-embed-0001")), ref(derived("drv-chunk-0001"), "supporting")]),
        record("drv-summary-0001", "summarize", [ref(derived("drv-clean-0001")), ref(PACKAGE_B)], parameters=(("max_words", 200),)),
        record(
            "drv-translate-0001",
            "translate",
            [ref(derived("drv-summary-0001")), ref(REVISION, "supporting")],
            parameters=(("target_language", "fr"), ("seed", None)),
        ),
    ]


def codes_of(document: Any) -> set[tuple[str, str]]:
    return {(finding.pointer, finding.code) for finding in G.evaluate_record(document)}


def lineage_codes(records: list[Any], roots: frozenset[tuple[str, str, str]] = ROOTS) -> set[tuple[str, str]]:
    return {(finding.pointer, finding.code) for finding in G.check_lineage(records, roots).findings}


def with_parameter(name: str, value: Any) -> dict[str, Any]:
    document = reference_records()[0]
    document["transformation"]["parameters"].append({"name": name, "value": value})
    return document


class Journal:
    """Minimal synthetic lifecycle journal (registrations and transitions)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.heads: dict[tuple[str, str, str], tuple[int, str, str]] = {}

    def _event(self, event_type: str, subject: tuple[str, str, str], actor: tuple[str, str], reason_codes: tuple[str, ...]) -> dict[str, Any]:
        counter = len(self.events) + 1
        moment = f"2026-09-02T09:{counter // 60:02d}:{counter % 60:02d}Z"
        return {
            "schema_version": "0.1.0",
            "event_id": f"00000000-0000-4000-8000-{counter:012d}",
            "event_type": event_type,
            "subject": {"artifact_kind": subject[0], "artifact_id": subject[1], "subject_sha256": subject[2]},
            "actor": {"kind": actor[0], "id": actor[1]},
            "decision": {"policy_id": "quarantine-promotion-v1", "policy_version": "1", "reason_codes": list(reason_codes)},
            "occurred_at": moment,
            "recorded_at": moment,
        }

    def register(self, event_type: str, subject: tuple[str, str, str], *, reason_codes: tuple[str, ...] = (), revision_of: tuple[str, str, str] | None = None) -> None:
        actor = ("internal_service", "quarantine-deriver") if event_type == L.DERIVED_RECORDED else ("collector", "collector-ingress")
        event = self._event(event_type, subject, actor, reason_codes)
        to_state = L.REJECTED_AT_INGRESS if event_type == L.INGRESS_REJECTED else L.RAW
        event.update(sequence=0, previous_event_sha256=None, from_state=None, to_state=to_state)
        if revision_of is not None:
            event["revision_of"] = {"artifact_kind": revision_of[0], "artifact_id": revision_of[1], "subject_sha256": revision_of[2]}
        self.events.append(event)
        self.heads[subject] = (0, L.event_sha256(event), to_state)

    def move(self, subject: tuple[str, str, str], to_state: str, *, reason_codes: tuple[str, ...] = ()) -> None:
        sequence, head, state = self.heads[subject]
        event = self._event(L.STATE_TRANSITION, subject, ("internal_service", "quarantine-validator"), reason_codes)
        event.update(sequence=sequence + 1, previous_event_sha256=head, from_state=state, to_state=to_state)
        self.events.append(event)
        self.heads[subject] = (sequence + 1, L.event_sha256(event), to_state)


REFUSED_AT_INGRESS = ("research_package", "7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d", sha("ingress-bytes-rejected"))


def reference_journal() -> Journal:
    journal = Journal()
    journal.register(L.INGRESS_ACCEPTED, PACKAGE_A)
    journal.move(PACKAGE_A, L.PENDING)
    journal.register(L.INGRESS_ACCEPTED, PACKAGE_B)
    journal.move(PACKAGE_B, L.PENDING)
    # A rejected package keeps its RAW bytes: it stays a possible root.
    journal.move(PACKAGE_B, L.REJECTED, reason_codes=("PKG_TIMESTAMP_ORDER",))
    journal.register(L.INGRESS_ACCEPTED, CONVERSATION)
    journal.register(L.INGRESS_ACCEPTED, REVISION, revision_of=CONVERSATION)
    journal.register(L.INGRESS_REJECTED, REFUSED_AT_INGRESS, reason_codes=("SECRET_KNOWN_PREFIX",))
    for document in reference_records():
        journal.register(L.DERIVED_RECORDED, G.subject_key(document))
    return journal


class SchemaParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_mirror_equals_the_schema_without_annotations(self) -> None:
        self.assertEqual(
            C.canonicalize(S.strip_annotations(self.schema)).decode("utf-8"),
            C.canonicalize(G.SCHEMA_MIRROR).decode("utf-8"),
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

        self.assertEqual(7, walk(self.schema))

    def test_parameter_names_follow_the_generation_parameter_rule(self) -> None:
        package_schema = json.loads((PROJECT_ROOT / "schemas" / "research-package.schema.json").read_text(encoding="utf-8"))
        expected = package_schema["$defs"]["generationParameter"]["properties"]["name"]["pattern"]
        self.assertEqual(expected, G.PARAMETER_NAME_PATTERN)
        self.assertEqual(expected, self.schema["$defs"]["parameter"]["properties"]["name"]["pattern"])

    def test_identifiers_match_the_journal_and_the_corpus_manifest(self) -> None:
        identifier = self.schema["$defs"]["identifier"]["pattern"]
        manifest = json.loads((PROJECT_ROOT / "schemas" / "training-corpus-manifest.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(identifier, manifest["$defs"]["sourcePackage"]["properties"]["provenance_id"]["pattern"])
        self.assertEqual(identifier, L.SCHEMA_MIRROR["$defs"]["identifier"]["pattern"])
        self.assertEqual(list(L.ARTIFACT_KINDS), self.schema["$defs"]["artifactKind"]["enum"])
        self.assertEqual(["internal_service", "operator"], self.schema["$defs"]["actor"]["properties"]["kind"]["enum"])
        self.assertEqual(L.SCHEMA_MIRROR["$defs"]["actor"]["properties"]["id"], G.SCHEMA_MIRROR["$defs"]["actor"]["properties"]["id"])

    def test_transformation_types_are_the_documented_list(self) -> None:
        self.assertEqual(
            ["redact", "clean", "summarize", "translate", "chunk", "embed", "index"],
            self.schema["$defs"]["transformation"]["properties"]["type"]["enum"],
        )

    def test_no_content_field_exists(self) -> None:
        names = set(self.schema["properties"])
        for definition in self.schema["$defs"].values():
            names |= set(definition.get("properties", {}))
        for forbidden in ("text", "content", "body", "excerpt", "url", "path", "hostname", "secret", "token"):
            self.assertNotIn(forbidden, names)


class RecordRuleTests(unittest.TestCase):
    def test_reference_records_are_valid(self) -> None:
        for document in reference_records():
            with self.subTest(artifact_id=document["artifact_id"]):
                self.assertEqual(set(), codes_of(document))

    def test_time_order(self) -> None:
        document = reference_records()[0]
        document["completed_at"] = "2026-09-02T09:59:59Z"
        self.assertEqual({("/completed_at", G.TIME_ORDER)}, codes_of(document))
        # Offsets are compared in UTC; equal instants are allowed.
        document["completed_at"] = "2026-09-02T12:00:00+02:00"
        self.assertEqual(set(), codes_of(document))
        document["completed_at"] = "2026-09-02T11:59:59+02:00"
        self.assertEqual({("/completed_at", G.TIME_ORDER)}, codes_of(document))

    def test_self_parenting(self) -> None:
        document = reference_records()[1]
        document["parents"].append(ref(derived("drv-clean-0001"), "supporting"))
        self.assertEqual({("/parents/1", G.SELF_PARENT)}, codes_of(document))
        # A RAW artifact with the same identifier is another artifact, not the record itself.
        document = record("3f1c2a9e-6b1d-4c1e-9a52-0d4b8e7f1a20", "clean", [ref(PACKAGE_A)])
        self.assertEqual(set(), codes_of(document))

    def test_duplicate_parents(self) -> None:
        document = reference_records()[0]
        document["parents"].append(ref(PACKAGE_A, "supporting"))
        self.assertEqual({("/parents/1", G.DUPLICATE_PARENT)}, codes_of(document))
        # Two revisions of one conversation share an id, not a digest.
        document = record("drv-summary-0002", "summarize", [ref(CONVERSATION), ref(REVISION)])
        self.assertEqual(set(), codes_of(document))

    def test_at_least_one_primary_parent(self) -> None:
        document = reference_records()[0]
        document["parents"][0]["role"] = "supporting"
        self.assertEqual({("/parents", G.NO_PRIMARY_PARENT)}, codes_of(document))

    def test_secret_like_parameter_names(self) -> None:
        for name in ("api_key", "x.access-token", "authorization", "client_secret", "session_cookie", "db_password", "signing.private-key"):
            with self.subTest(name=name):
                self.assertEqual(
                    {
                        ("/transformation/parameters/1/name", "LINEAGE_PATTERN_MISMATCH"),
                        ("/transformation/parameters/1/name", G.PARAMETER_NAME_SECRET),
                    },
                    codes_of(with_parameter(name, "x")),
                )
        # Upper case breaks the pattern too; the dedicated code still names the reason.
        self.assertIn(("/transformation/parameters/1/name", G.PARAMETER_NAME_SECRET), codes_of(with_parameter("API_KEY", 1)))
        for name in ("max_tokens", "chunk_size", "target_language", "tokenizer.version"):
            with self.subTest(name=name):
                self.assertEqual(set(), codes_of(with_parameter(name, 1)))

    def test_secret_shaped_parameter_values(self) -> None:
        values = (
            "ghp_" + "a1B2" * 6,
            "Bearer " + sha("bearer")[:24],
            "-----BEGIN " + "PRIVATE KEY-----",
            "https://example.com/o?" + "X-Amz-" + "Signature=" + sha("signature"),
            "password" + "=" + "x",
        )
        for value in values:
            with self.subTest(value=value[:8]):
                self.assertEqual({("/transformation/parameters/1/value", G.PARAMETER_VALUE_SECRET)}, codes_of(with_parameter("note", value)))
        # The low-precision mixed-token heuristic alone does not refuse a record.
        name = "Model3-Embedding-0.6B"
        self.assertEqual(("SECRET_MIXED_TOKEN",), SCAN.scan_text(name).categories)
        self.assertEqual(set(), codes_of(with_parameter("model", name)))
        self.assertEqual(set(), codes_of(with_parameter("digest", sha("not-a-secret"))))

    def test_duplicate_parameter_names(self) -> None:
        self.assertEqual({("/transformation/parameters/1/name", G.DUPLICATE_PARAMETER)}, codes_of(with_parameter("policy", "other")))

    def test_replaces_itself(self) -> None:
        document = record("drv-clean-0002", "clean", [ref(PACKAGE_A)], replaces=derived("drv-clean-0002"))
        self.assertEqual({("/replaces", G.REPLACES_SELF)}, codes_of(document))

    def test_structural_refusals(self) -> None:
        def changed(change: Any) -> set[tuple[str, str]]:
            document = reference_records()[2]
            change(document)
            return codes_of(document)

        cases = (
            (lambda d: d.__setitem__("text", "contenu"), {("", "LINEAGE_FIELD_UNKNOWN")}),
            (lambda d: d["parents"][0].__setitem__("path", "raw/x"), {("/parents/0", "LINEAGE_FIELD_UNKNOWN")}),
            (lambda d: d.pop("result"), {("/result", "LINEAGE_FIELD_MISSING")}),
            (lambda d: d.__setitem__("schema_version", "0.2.0"), {("/schema_version", "LINEAGE_CONST_MISMATCH")}),
            (lambda d: d["actor"].__setitem__("kind", "collector"), {("/actor/kind", "LINEAGE_ENUM_MISMATCH")}),
            (lambda d: d["actor"].__setitem__("kind", "producer"), {("/actor/kind", "LINEAGE_ENUM_MISMATCH")}),
            (lambda d: d["transformation"].__setitem__("type", "extract"), {("/transformation/type", "LINEAGE_ENUM_MISMATCH")}),
            (lambda d: d["parents"][0].__setitem__("role", "input"), {("/parents/0/role", "LINEAGE_ENUM_MISMATCH"), ("/parents", G.NO_PRIMARY_PARENT)}),
            (lambda d: d.__setitem__("parents", []), {("/parents", "LINEAGE_ARRAY_TOO_SHORT")}),
            (lambda d: d["parents"][0].__setitem__("sha256", sha("x").upper()), {("/parents/0/sha256", "LINEAGE_PATTERN_MISMATCH")}),
            (lambda d: d["result"].__setitem__("byte_size", 0), {("/result/byte_size", "LINEAGE_NUMBER_BELOW_MINIMUM")}),
            (lambda d: d["result"].__setitem__("byte_size", 4096.0), {("/result/byte_size", "LINEAGE_TYPE_MISMATCH")}),
            (lambda d: d["result"].__setitem__("media_type", "jsonl"), {("/result/media_type", "LINEAGE_PATTERN_MISMATCH")}),
            (lambda d: d.__setitem__("started_at", "2026-09-02"), {("/started_at", "LINEAGE_TIMESTAMP_INVALID")}),
            (lambda d: d.__setitem__("artifact_id", "drv/../x"), {("/artifact_id", "LINEAGE_PATTERN_MISMATCH")}),
            (lambda d: d["transformation"]["parameters"][0].__setitem__("value", {"nested": 1}), {("/transformation/parameters/0/value", "LINEAGE_ONE_OF_MISMATCH")}),
            (lambda d: d["transformation"]["parameters"][0].__setitem__("value", "v" * 1025), {("/transformation/parameters/0/value", "LINEAGE_ONE_OF_MISMATCH")}),
        )
        for change, expected in cases:
            with self.subTest(expected=sorted(expected)):
                self.assertEqual(expected, changed(change))
        self.assertEqual({("", "LINEAGE_TYPE_MISMATCH")}, codes_of(["not", "a", "record"]))

    def test_oversized_arrays_are_not_walked(self) -> None:
        document = reference_records()[0]
        document["parents"] = [ref(PACKAGE_A, "supporting")] * 4097
        self.assertEqual({("/parents", "LINEAGE_ARRAY_TOO_LONG")}, codes_of(document))
        document = reference_records()[0]
        document["transformation"]["parameters"] = [{"name": "api_key", "value": "x"}] * 65
        self.assertEqual({("/transformation/parameters", "LINEAGE_ARRAY_TOO_LONG")}, codes_of(document))

    def test_values_outside_i_json_are_refused(self) -> None:
        self.assertEqual({("", "JSON_INTEGER_OUT_OF_RANGE")}, codes_of(with_parameter("seed", 2**60)))
        self.assertIn(("/transformation/parameters/1/value", "LINEAGE_NUMBER_NOT_FINITE"), codes_of(with_parameter("seed", float("nan"))))


class LineageTests(unittest.TestCase):
    def test_lineage_walks_back_to_the_raw_package_hash(self) -> None:
        result = G.check_lineage(reference_records(), ROOTS)
        self.assertTrue(result.valid, result.findings)
        self.assertEqual(7, result.records_checked)
        graph = result.graph
        self.assertEqual((PACKAGE_A,), graph.raw_roots("drv-index-0001"))
        self.assertEqual(PACKAGE_A[2], graph.raw_roots("drv-index-0001")[0][2])
        self.assertEqual(
            (derived("drv-chunk-0001"), derived("drv-clean-0001"), derived("drv-embed-0001"), derived("drv-redact-0001")),
            graph.derived_ancestors("drv-index-0001"),
        )
        self.assertEqual(tuple(sorted((PACKAGE_A, PACKAGE_B, REVISION))), graph.raw_roots("drv-translate-0001"))
        self.assertEqual((), graph.derived_ancestors("drv-redact-0001"))
        with self.assertRaises(G.LineageError) as caught:
            graph.raw_roots("drv-missing")
        self.assertEqual((G.ARTIFACT_UNKNOWN,), caught.exception.reasons)

    def test_the_check_does_not_depend_on_record_order(self) -> None:
        records = reference_records()
        random.Random(7).shuffle(records)
        graph = G.build_graph(records, iter(ROOTS))
        self.assertEqual((PACKAGE_A,), graph.raw_roots("drv-index-0001"))
        self.assertEqual(ROOTS, graph.roots)

    def test_roots_come_from_the_lifecycle_journal(self) -> None:
        replayed = L.replay(reference_journal().events)
        roots = G.roots_from_replay(replayed)
        self.assertEqual(ROOTS, roots)
        self.assertNotIn(REFUSED_AT_INGRESS, roots)
        # Each record's lifecycle subject is (derived_artifact, artifact_id, result digest).
        for document in reference_records():
            self.assertEqual(L.RAW, replayed.state_of(*G.subject_key(document)))
        self.assertTrue(G.check_lineage(reference_records(), roots).valid)
        # A parent refused at ingress was never stored: it is unknown.
        orphan = record("drv-clean-0009", "clean", [ref(REFUSED_AT_INGRESS)])
        self.assertEqual({("/0/parents/0", G.PARENT_UNKNOWN)}, lineage_codes([orphan], roots))

    def test_unknown_parents(self) -> None:
        records = reference_records()
        records[1]["parents"] = [ref(derived("drv-missing-0001"))]
        records[5]["parents"][1] = ref(("research_package", "5d2e8c1a-3b4f-4a6d-8e9c-1f2a3b4c5d6e", sha("raw-package-c")))
        self.assertEqual({("/1/parents/0", G.PARENT_UNKNOWN), ("/5/parents/1", G.PARENT_UNKNOWN)}, lineage_codes(records))
        # Same identifier under another kind is another artifact.
        records = reference_records()
        records[0]["parents"] = [ref(("conversation", PACKAGE_A[1], PACKAGE_A[2]))]
        self.assertEqual({("/0/parents/0", G.PARENT_UNKNOWN)}, lineage_codes(records))

    def test_parent_hash_mismatches(self) -> None:
        records = reference_records()
        records[0]["parents"][0]["sha256"] = sha("raw-package-a-altered")
        records[2]["parents"][0]["sha256"] = sha("result-drv-redact-0001")
        self.assertEqual(
            {("/0/parents/0/sha256", G.PARENT_HASH_MISMATCH), ("/2/parents/0/sha256", G.PARENT_HASH_MISMATCH)},
            lineage_codes(records),
        )
        # A revision digest does not stand for the original conversation.
        records = reference_records()
        records[6]["parents"][1] = ref(("conversation", CONVERSATION[1], REVISION[2]), "supporting")
        self.assertEqual({("/6/parents/1/sha256", G.PARENT_HASH_MISMATCH)}, lineage_codes(records))

    def test_cycles_are_refused(self) -> None:
        two = [
            record("drv-a", "clean", [ref(PACKAGE_A), ref(derived("drv-b"), "supporting")]),
            record("drv-b", "clean", [ref(derived("drv-a"))]),
            record("drv-c", "chunk", [ref(derived("drv-b"))]),
        ]
        self.assertEqual({("/0", G.CYCLE), ("/1", G.CYCLE)}, lineage_codes(two))
        three = [
            record("drv-x", "clean", [ref(derived("drv-z"))]),
            record("drv-y", "clean", [ref(derived("drv-x"))]),
            record("drv-z", "clean", [ref(derived("drv-y"))]),
        ]
        self.assertEqual({("/0", G.CYCLE), ("/1", G.CYCLE), ("/2", G.CYCLE)}, lineage_codes(three))
        # A replacement is newer than what it replaces: a replaces loop is a cycle too.
        loop = [
            record("drv-p", "clean", [ref(PACKAGE_A)], replaces=derived("drv-q")),
            record("drv-q", "clean", [ref(PACKAGE_A)], replaces=derived("drv-p")),
        ]
        self.assertEqual({("/0", G.CYCLE), ("/1", G.CYCLE)}, lineage_codes(loop))
        with self.assertRaises(G.LineageError) as caught:
            G.build_graph(two, ROOTS)
        self.assertEqual((G.CYCLE,), caught.exception.reasons)

    def test_self_parenting_in_a_set(self) -> None:
        records = reference_records()
        records[1]["parents"].append(ref(derived("drv-clean-0001"), "supporting"))
        # The refused record leaves the graph, so its children lose their parent.
        self.assertEqual(
            {("/1/parents/1", G.SELF_PARENT), ("/2/parents/0", G.PARENT_UNKNOWN), ("/5/parents/0", G.PARENT_UNKNOWN)},
            lineage_codes(records),
        )

    def test_identifier_conflicts_and_idempotent_duplicates(self) -> None:
        records = reference_records()
        result = G.check_lineage(records + [copy.deepcopy(records[0]), copy.deepcopy(records[4])], ROOTS)
        self.assertTrue(result.valid, result.findings)
        self.assertEqual(2, result.duplicates_ignored)
        conflicting = copy.deepcopy(records[0])
        conflicting["result"]["byte_size"] = 1
        self.assertEqual({("/7/artifact_id", G.ARTIFACT_ID_CONFLICT)}, lineage_codes(records + [conflicting]))

    def test_replaces_links(self) -> None:
        records = reference_records()
        corrected = record("drv-summary-0002", "summarize", [ref(derived("drv-clean-0001")), ref(PACKAGE_B)], replaces=derived("drv-summary-0001"))
        self.assertTrue(G.check_lineage(records + [corrected], ROOTS).valid)
        # A corrected derivative may replace the RAW package it comes from.
        package_fix = record("drv-clean-0002", "clean", [ref(PACKAGE_A)], replaces=PACKAGE_A)
        self.assertTrue(G.check_lineage(records + [package_fix], ROOTS).valid)
        unknown = record("drv-summary-0003", "summarize", [ref(PACKAGE_B)], replaces=derived("drv-missing-0001"))
        mismatch = record("drv-summary-0004", "summarize", [ref(PACKAGE_B)], replaces=("derived_artifact", "drv-summary-0001", sha("other")))
        self.assertEqual(
            {("/7/replaces", G.REPLACES_UNKNOWN), ("/8/replaces/sha256", G.REPLACES_HASH_MISMATCH)},
            lineage_codes(records + [unknown, mismatch]),
        )
        # Replacing is not deriving: the walk follows parents only.
        graph = G.build_graph(records + [corrected], ROOTS)
        self.assertEqual(tuple(sorted((PACKAGE_A, PACKAGE_B))), graph.raw_roots("drv-summary-0002"))

    def test_limits(self) -> None:
        result = G.check_lineage(reference_records(), ROOTS, max_records=2)
        self.assertEqual(("LINEAGE_LIMIT_EXCEEDED",), result.reason_codes)
        self.assertIsNone(result.graph)
        with mock.patch.object(G, "MAX_PARENT_REFERENCES", 3):
            self.assertEqual(("LINEAGE_LIMIT_EXCEEDED",), G.check_lineage(reference_records(), ROOTS).reason_codes)
        many = [record(f"drv-{index:04d}", "clean", [ref(PACKAGE_A), ref(derived("drv-missing"), "supporting")]) for index in range(150)]
        capped = G.check_lineage(many, ROOTS)
        self.assertEqual(S.MAX_FINDINGS, len(capped.findings))
        self.assertIn("LINEAGE_TOO_MANY_FINDINGS", capped.reason_codes)


class SafetyTests(unittest.TestCase):
    def test_refusals_never_echo_content(self) -> None:
        marker = "synthetic-marker-4d2e"
        document = reference_records()[0]
        document[marker] = marker
        document["actor"]["id"] = marker.upper()
        document["transformation"]["parameters"].append({"name": marker, "value": marker + " Bearer " + sha(marker)[:20]})
        document["artifact_id"] = marker
        findings = G.evaluate_record(document)
        self.assertTrue(findings)
        self.assertNotIn(marker, repr(findings))
        result = G.check_lineage([document, record("drv-z", "clean", [ref(derived(marker))])], ROOTS)
        self.assertNotIn(marker, repr(result))
        self.assertNotIn(marker, json.dumps(result.as_dict()))
        with self.assertRaises(G.LineageError) as caught:
            G.build_graph([document], ROOTS)
        self.assertNotIn(marker, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_module_never_writes_or_uses_the_network(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        # The module opens no file itself: JSONL reading is delegated to the lifecycle reader.
        for forbidden in ("open(", "write_bytes", "write_text", "os.replace", "os.remove", "unlink", "shutil", "import socket", "urllib", "http.client", "subprocess"):
            self.assertNotIn(forbidden, source)
        names = ("getaddrinfo", "gethostbyname", "create_connection", "socket")
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(mock.patch.object(socket, name, side_effect=AssertionError(name))) for name in names]
            G.build_graph(reference_records(), ROOTS).raw_roots("drv-index-0001")
            G.check_lineage([with_parameter("note", "https://example.com/a?b=c")], ROOTS)
        for patched in mocks:
            patched.assert_not_called()

    def test_runtime_uses_the_standard_library_only(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            else:
                continue
            for name in modules:
                self.assertIn(name.split(".")[0], sys.stdlib_module_names | {"__future__"})

    def test_no_service_imports_the_checker(self) -> None:
        for path in (PROJECT_ROOT / "services").rglob("*.py"):
            if path == MODULE_PATH:
                continue
            with self.subTest(path=path.relative_to(PROJECT_ROOT).as_posix()):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("lineage.py", source)
                self.assertNotIn("import lineage", source)
                self.assertNotIn("derived-artifact", source)

    def test_every_code_is_documented(self) -> None:
        text = DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("PROVISOIRE", text)
        self.assertIn(G.POLICY_ID, text)
        self.assertIn("provenance_id", text)
        for code in sorted(G.RECORD_RULE_CODES | G.GRAPH_CODES):
            self.assertIn(f"`{code}`", text)
        for transformation in G.TRANSFORMATION_TYPES:
            self.assertIn(f"`{transformation}`", text)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> tuple[int, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = G.main(list(arguments))
        return code, stdout.getvalue() + stderr.getvalue()

    def test_cli_checks_and_walks_a_lineage(self) -> None:
        marker = "synthetic-marker-8f1a"
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            journal = root / "journal.jsonl"
            journal.write_text("".join(json.dumps(event) + "\n" for event in reference_journal().events), encoding="utf-8")
            good = root / "derived.jsonl"
            good.write_text("\r\n".join(json.dumps(document) for document in reference_records()), encoding="utf-8")
            records = reference_records()
            records[3]["parents"][0]["sha256"] = sha(marker)
            records[0]["transformation"]["parameters"].append({"name": "note", "value": marker})
            bad = root / "tampered.jsonl"
            bad.write_text("".join(json.dumps(document) + "\n" for document in records), encoding="utf-8")
            broken = root / "broken.jsonl"
            broken.write_text(json.dumps(reference_records()[0]) + '\n{"a": 1, "a": 2}\n', encoding="utf-8")
            events = reference_journal().events
            events[1]["previous_event_sha256"] = sha("x")
            bad_journal = root / "bad-journal.jsonl"
            bad_journal.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
            runs = [
                self.run_cli(str(good), "--journal", str(journal)),
                self.run_cli(str(good), "--journal", str(journal), "--walk", "drv-translate-0001"),
                self.run_cli(str(bad), "--journal", str(journal)),
                self.run_cli(str(broken), "--journal", str(journal)),
                self.run_cli(str(good), "--journal", str(bad_journal)),
                self.run_cli(str(good), "--journal", str(journal), "--walk", "drv-missing"),
                self.run_cli(str(root / "missing.jsonl"), "--journal", str(journal)),
            ]
        self.assertEqual([0, 0, 1, 1, 1, 1, 2], [code for code, _ in runs])
        report = json.loads(runs[0][1])
        self.assertTrue(report["valid"])
        self.assertEqual(7, report["records_checked"])
        walk = json.loads(runs[1][1])
        self.assertEqual(
            sorted([PACKAGE_A, PACKAGE_B, REVISION]),
            [(item["artifact_kind"], item["artifact_id"], item["sha256"]) for item in walk["raw_roots"]],
        )
        self.assertEqual([{"code": G.PARENT_HASH_MISMATCH, "pointer": "/3/parents/0/sha256"}], json.loads(runs[2][1])["findings"])
        self.assertEqual({"reasons": ["JSON_DUPLICATE_KEY"], "record_index": 1}, {k: v for k, v in json.loads(runs[3][1]).items() if k in ("reasons", "record_index")})
        self.assertEqual({"reasons": [L.CHAIN_MISMATCH], "event_index": 1}, {k: v for k, v in json.loads(runs[4][1]).items() if k in ("reasons", "event_index")})
        self.assertEqual([G.ARTIFACT_UNKNOWN], json.loads(runs[5][1])["reasons"])
        for _code, output in runs:
            self.assertNotIn(marker, output)
            self.assertNotIn(sha(marker), output)


if __name__ == "__main__":
    unittest.main()
