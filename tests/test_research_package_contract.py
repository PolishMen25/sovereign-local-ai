"""Contract tests for the candidate research-package 0.1.0 validator.

Every package here is synthetic.  URLs use RFC 2606 names (example.com,
example.org) or RFC 5737/3849 documentation addresses, and no secret-shaped
literal appears in the source: signed parameter names are assembled at run
time.
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
import socket
import sys
from typing import Any, Callable
import unittest
from unittest import mock

from tests._temp_support import sovereign_temporary_directory


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "services" / "quarantine" / "research_package.py"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "research-package.schema.json"
DOC_PATH = PROJECT_ROOT / "docs" / "data" / "research-package-validation.md"
SPEC = importlib.util.spec_from_file_location("research_package", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

R = MODULE
S = sys.modules["sovereign_quarantine_closed_schema"]
C = sys.modules["sovereign_quarantine_canonical_json"]
U = sys.modules["sovereign_quarantine_url_policy"]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


RESPONSE_TEXT = "Réponse synthétique : deux sources publiques d'exemple sont citées. \U0001f600 Fin."
SYSTEM_PROMPT = "Réponds en français et cite tes sources."


def seal(package: dict[str, Any]) -> dict[str, Any]:
    package["integrity"]["package_sha256"] = C.package_sha256(package)
    return package


def minimal_package() -> dict[str, Any]:
    return seal(
        {
            "schema_version": "0.1.0",
            "package_id": "0b7c6f2e-4d1a-4f3b-9c2d-7e8f9a0b1c2d",
            "lifecycle_state": "RAW",
            "producer": {"provider": "synthetic-provider", "model": "synthetic-model"},
            "timestamps": {
                "request_started_at": "2026-09-01T10:00:00Z",
                "response_completed_at": "2026-09-01T10:00:04Z",
                "collected_at": "2026-09-01T10:00:05Z",
                "created_at": "2026-09-01T10:00:06Z",
            },
            "request": {"question": "Quelle est la frontière de confiance du Collector ?"},
            "response": {"text": "Le Collector est en écriture seule."},
            "sources": [],
            "citations": [],
            "attachments": [],
            "usage": {},
            "cost": {},
            "generation_parameters": [],
            "errors": [],
            "security": {
                "producer_secret_scan_status": "passed",
                "redaction_policy_version": "producer-redaction-v1",
                "scanned_at": "2026-09-01T10:00:05Z",
                "redactions_count": 0,
            },
            "integrity": {
                "algorithm": "SHA-256",
                "canonicalization": "RFC8785",
                "hash_scope": "canonical-package-excluding-integrity",
                "package_sha256": "0" * 64,
            },
        }
    )


def full_package() -> dict[str, Any]:
    return seal(
        {
            "schema_version": "0.1.0",
            "package_id": "3f1c2a9e-6b1d-4c1e-9a52-0d4b8e7f1a20",
            "lifecycle_state": "RAW",
            "producer": {
                "provider": "synthetic-provider",
                "model": "synthetic-model-large",
                "provider_request_id": "req-0001",
                "gateway_version": "0.1.0",
            },
            "timestamps": {
                "request_started_at": "2026-09-01T10:00:00Z",
                "response_completed_at": "2026-09-01T10:00:05.250Z",
                # 10:00:06 UTC written with an offset: order is computed in UTC.
                "collected_at": "2026-09-01T12:00:06+02:00",
                "created_at": "2026-09-01T10:00:07.000000001Z",
            },
            "request": {
                "question": "Quelles sources publiques décrivent un sas de quarantaine ?",
                "controlled_system_prompt": {
                    "text": SYSTEM_PROMPT,
                    "controlled_by": "local_operator",
                    "template_id": "template-fr-1",
                    "sha256": sha(SYSTEM_PROMPT),
                },
                "conversation_id": "conv-0001",
            },
            "response": {
                "text": RESPONSE_TEXT,
                "language": "fr-FR",
                "finish_reason": "stop",
                "provider_status": "completed",
            },
            "sources": [
                {
                    "source_id": "src-1",
                    "kind": "web",
                    "url": "https://example.com/articles/quarantaine",
                    "title": "Article d'exemple",
                    "publisher": "Éditeur d'exemple",
                    "authors": ["Autrice Synthétique"],
                    "published_at": "2026-08-01T00:00:00Z",
                    "retrieved_at": "2026-09-01T10:00:02Z",
                    "content_sha256": sha("source-1"),
                    "media_type": "text/html",
                },
                {
                    "source_id": "src-2",
                    "kind": "document",
                    "url": "https://www.example.org/rapport.pdf",
                    "retrieved_at": "2026-09-01T10:00:03Z",
                    "media_type": "application/pdf",
                },
            ],
            "citations": [
                {
                    "citation_id": "cit-1",
                    "source_id": "src-1",
                    "response_start": 0,
                    "response_end": 10,
                    "locator": "section 2",
                    "quoted_text_sha256": sha("extrait-1"),
                },
                # The range ends exactly at the end of the text, counted in code points.
                {"citation_id": "cit-2", "source_id": "src-2", "response_start": 10, "response_end": len(RESPONSE_TEXT)},
                {"citation_id": "cit-3", "source_id": "src-1"},
            ],
            "attachments": [
                {
                    "attachment_id": "att-1",
                    "filename": "rapport.pdf",
                    "media_type": "application/pdf",
                    "byte_size": 2048,
                    "content_sha256": sha("attachment-1"),
                    "source_url": "https://www.example.org/rapport.pdf",
                    "created_at": "2026-09-01T10:00:03Z",
                }
            ],
            "usage": {
                "input_tokens": 120,
                "output_tokens": 80,
                "total_tokens": 200,
                "cached_input_tokens": 20,
                "reasoning_tokens": 30,
            },
            "cost": {"amount": 0.0125, "currency": "EUR", "estimated": True},
            "generation_parameters": [
                {"name": "temperature", "value": 0.2},
                {"name": "max_output_tokens", "value": 1024},
                {"name": "stop", "value": ["###", None, 1, True]},
                {"name": "seed", "value": None},
                {"name": "stream", "value": False},
                {"name": "reasoning.effort", "value": "medium"},
            ],
            "errors": [
                {
                    "code": "PROVIDER_RETRY",
                    "phase": "provider",
                    "message": "Nouvelle tentative après délai.",
                    "retryable": True,
                    "occurred_at": "2026-09-01T10:00:01Z",
                    "provider_http_status": 429,
                    "provider_error_type": "rate_limit",
                }
            ],
            "security": {
                "producer_secret_scan_status": "passed",
                "redaction_policy_version": "producer-redaction-v1",
                "scanned_at": "2026-09-01T10:00:06Z",
                "redactions_count": 1,
                "redacted_categories": ["personal_data"],
            },
            "integrity": {
                "algorithm": "SHA-256",
                "canonicalization": "RFC8785",
                "hash_scope": "canonical-package-excluding-integrity",
                "package_sha256": "0" * 64,
                "provider_raw_response_sha256": sha("provider-raw-response"),
            },
        }
    )


def findings_after(change: Callable[[dict[str, Any]], Any], *, base: Callable[[], dict[str, Any]] = full_package, reseal: bool = True) -> set[tuple[str, str]]:
    package = base()
    change(package)
    if reseal and type(package.get("integrity")) is dict:
        try:
            seal(package)
        except C.CanonicalJSONError:
            pass
    return {(finding.pointer, finding.code) for finding in R.evaluate(package).findings}


def signed_parameter() -> str:
    return "X-Amz-" + "Signature"


class SchemaParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_mirror_equals_the_schema_without_annotations(self) -> None:
        self.assertEqual(
            C.canonicalize(S.strip_annotations(self.schema)).decode("utf-8"),
            C.canonicalize(R.SCHEMA_MIRROR).decode("utf-8"),
        )

    def test_required_const_enum_and_max_items_match_the_schema(self) -> None:
        def collect(node: Any, path: str, found: dict[tuple[str, str], Any]) -> None:
            if type(node) is not dict:
                return
            for keyword in ("required", "const", "enum", "maxItems"):
                if keyword in node:
                    found[(path, keyword)] = node[keyword]
            for name, child in node.get("properties", {}).items():
                collect(child, f"{path}/properties/{name}", found)
            for name, child in node.get("$defs", {}).items():
                collect(child, f"/$defs/{name}", found)
            for keyword in ("items",):
                if keyword in node:
                    collect(node[keyword], f"{path}/{keyword}", found)
            for index, child in enumerate(node.get("oneOf", ())):
                collect(child, f"{path}/oneOf/{index}", found)

        schema_view: dict[tuple[str, str], Any] = {}
        mirror_view: dict[tuple[str, str], Any] = {}
        collect(self.schema, "", schema_view)
        collect(R.SCHEMA_MIRROR, "", mirror_view)
        self.assertGreaterEqual(len(schema_view), 30)
        self.assertEqual(json.dumps(schema_view.get(("", "required"))), json.dumps(mirror_view.get(("", "required"))))
        self.assertEqual(
            {key: json.dumps(value) for key, value in schema_view.items()},
            {key: json.dumps(value) for key, value in mirror_view.items()},
        )
        self.assertEqual("RAW", schema_view[("/properties/lifecycle_state", "const")])

    def test_every_object_is_closed(self) -> None:
        def walk(node: Any) -> None:
            if type(node) is not dict:
                return
            if node.get("type") == "object":
                self.assertIs(False, node.get("additionalProperties"))
            for child in list(node.get("properties", {}).values()) + list(node.get("$defs", {}).values()):
                walk(child)
            if "items" in node:
                walk(node["items"])

        walk(self.schema)

    def test_the_interpreter_refuses_an_unvetted_mirror(self) -> None:
        refused = (
            {"type": "object", "properties": {}},
            {"type": "object", "additionalProperties": True},
            {"type": "string", "format": "email"},
            {"type": "string", "pattern": "^\\d+$"},
            {"$ref": "#/$defs/missing"},
            {"type": "string", "unevaluatedProperties": False},
            {"type": "decimal"},
        )
        for mirror in refused:
            with self.subTest(mirror=mirror), self.assertRaises(S.SchemaMirrorError):
                S.ClosedSchema(mirror, code_prefix="T_")


class StructuralRuleTests(unittest.TestCase):
    def test_minimal_and_full_packages_are_valid(self) -> None:
        for build in (minimal_package, full_package):
            with self.subTest(build=build.__name__):
                result = R.evaluate(build())
                self.assertTrue(result.valid, result.findings)
                self.assertEqual(R.POLICY_ID, result.policy_id)
                R.check(build())

    def test_unknown_member_is_refused_without_naming_it(self) -> None:
        marker = "synthetic_marker_5e1f"
        self.assertEqual({("", "PKG_FIELD_UNKNOWN")}, findings_after(lambda p: p.__setitem__(marker, 1)))
        self.assertEqual({("/producer", "PKG_FIELD_UNKNOWN")}, findings_after(lambda p: p["producer"].__setitem__(marker, "x")))

    def test_missing_member_is_refused(self) -> None:
        self.assertEqual({("/security", "PKG_FIELD_MISSING")}, findings_after(lambda p: p.pop("security")))
        self.assertIn(("/sources/0/kind", "PKG_FIELD_MISSING"), findings_after(lambda p: p["sources"][0].pop("kind")))

    def test_types_are_exact(self) -> None:
        cases = (
            (lambda p: p["usage"].__setitem__("input_tokens", True), "/usage/input_tokens"),
            (lambda p: p["usage"].__setitem__("input_tokens", 120.0), "/usage/input_tokens"),
            (lambda p: p["cost"].__setitem__("estimated", 1), "/cost/estimated"),
            (lambda p: p.__setitem__("sources", {}), "/sources"),
            (lambda p: p["response"].__setitem__("text", None), "/response/text"),
        )
        for change, pointer in cases:
            with self.subTest(pointer=pointer):
                self.assertIn((pointer, "PKG_TYPE_MISMATCH"), findings_after(change))
        self.assertEqual(("PKG_TYPE_MISMATCH",), R.evaluate([]).reason_codes)

    def test_const_and_enum(self) -> None:
        self.assertEqual({("/schema_version", "PKG_CONST_MISMATCH")}, findings_after(lambda p: p.__setitem__("schema_version", "0.2.0")))
        self.assertEqual(
            {("/integrity/canonicalization", "PKG_CONST_MISMATCH")},
            findings_after(lambda p: p["integrity"].__setitem__("canonicalization", "sort_keys")),
        )
        self.assertEqual({("/sources/0/kind", "PKG_ENUM_MISMATCH")}, findings_after(lambda p: p["sources"][0].__setitem__("kind", "rumour")))
        self.assertEqual(
            {("/security/redacted_categories/0", "PKG_ENUM_MISMATCH")},
            findings_after(lambda p: p["security"]["redacted_categories"].__setitem__(0, "unknown")),
        )

    def test_string_bounds(self) -> None:
        self.assertEqual({("/producer/provider", "PKG_STRING_TOO_SHORT")}, findings_after(lambda p: p["producer"].__setitem__("provider", "")))
        self.assertEqual({("/producer/provider", "PKG_STRING_TOO_LONG")}, findings_after(lambda p: p["producer"].__setitem__("provider", "p" * 101)))
        self.assertEqual(set(), findings_after(lambda p: p["producer"].__setitem__("provider", "p" * 100)))
        # maxLength counts code points, not UTF-16 units: 100 emoji fit.
        self.assertEqual(set(), findings_after(lambda p: p["producer"].__setitem__("provider", "\U0001f600" * 100)))

    def test_patterns_are_anchored_like_ecma_262(self) -> None:
        upper = sha("x").upper()
        self.assertEqual({("/sources/0/content_sha256", "PKG_PATTERN_MISMATCH")}, findings_after(lambda p: p["sources"][0].__setitem__("content_sha256", upper)))
        # Python's "$" would accept a trailing newline; the ECMA-262 reading must not.
        trailing = sha("x") + "\n"
        self.assertEqual({("/sources/0/content_sha256", "PKG_PATTERN_MISMATCH")}, findings_after(lambda p: p["sources"][0].__setitem__("content_sha256", trailing)))
        self.assertEqual({("/response/language", "PKG_PATTERN_MISMATCH")}, findings_after(lambda p: p["response"].__setitem__("language", "fr\n")))
        self.assertEqual({("/attachments/0/filename", "PKG_PATTERN_MISMATCH")}, findings_after(lambda p: p["attachments"][0].__setitem__("filename", "../x.pdf")))
        self.assertEqual(set(), findings_after(lambda p: p["attachments"][0].__setitem__("filename", "rapport final.pdf")))

    def test_secret_like_parameter_names_are_refused(self) -> None:
        for name in ("api_key", "x.access-token", "authorization", "client_secret", "session_cookie", "db_password"):
            with self.subTest(name=name):
                self.assertEqual(
                    {("/generation_parameters/0/name", "PKG_PATTERN_MISMATCH")},
                    findings_after(lambda p, n=name: p["generation_parameters"][0].__setitem__("name", n)),
                )

    def test_uuid_format(self) -> None:
        self.assertEqual({("/package_id", "PKG_UUID_INVALID")}, findings_after(lambda p: p.__setitem__("package_id", "not-a-uuid")))
        self.assertEqual(
            {("/package_id", "PKG_UUID_INVALID")},
            findings_after(lambda p: p.__setitem__("package_id", "3f1c2a9e6b1d4c1e9a520d4b8e7f1a20")),
        )
        self.assertEqual(set(), findings_after(lambda p: p.__setitem__("package_id", "3F1C2A9E-6B1D-4C1E-9A52-0D4B8E7F1A20")))

    def test_timestamp_format(self) -> None:
        refused = (
            "2026-09-01T10:00:00",
            "2026-09-01 10:00:00Z",
            "2026-09-01t10:00:00Z",
            "2026-09-01T10:00:00z",
            "2026-09-01T23:59:60Z",
            "2026-02-30T10:00:00Z",
            "2026-09-01T10:00:00.1234567890Z",
            "2026-09-01T10:00:00+24:00",
            "2026-09-01T10:00:00Z\n",
        )
        for value in refused:
            with self.subTest(value=value):
                self.assertEqual(
                    {("/security/scanned_at", "PKG_TIMESTAMP_INVALID")},
                    findings_after(lambda p, v=value: p["security"].__setitem__("scanned_at", v)),
                )
        for value in ("2026-09-01T10:00:05.123456789Z", "2026-09-01T11:00:05+01:00", "2026-09-01T10:00:05-00:00"):
            with self.subTest(value=value):
                self.assertEqual(set(), findings_after(lambda p, v=value: p["security"].__setitem__("scanned_at", v)))

    def test_number_bounds_and_finiteness(self) -> None:
        self.assertEqual({("/usage/input_tokens", "PKG_NUMBER_BELOW_MINIMUM")}, findings_after(lambda p: p["usage"].__setitem__("input_tokens", -1)))
        self.assertEqual({("/attachments/0/byte_size", "PKG_NUMBER_ABOVE_MAXIMUM")}, findings_after(lambda p: p["attachments"][0].__setitem__("byte_size", 2**30 + 1)))
        self.assertEqual({("/errors/0/provider_http_status", "PKG_NUMBER_BELOW_MINIMUM")}, findings_after(lambda p: p["errors"][0].__setitem__("provider_http_status", 99)))
        for value in (float("inf"), float("nan")):
            with self.subTest(value=value):
                found = findings_after(lambda p, v=value: p["cost"].__setitem__("amount", v))
                self.assertIn(("/cost/amount", "PKG_NUMBER_NOT_FINITE"), found)
                self.assertIn(("", "JSON_NON_FINITE_NUMBER"), found)
        self.assertEqual(set(), findings_after(lambda p: p["cost"].__setitem__("amount", 0)))

    def test_array_bounds_and_uniqueness(self) -> None:
        self.assertEqual({("/sources/0/authors", "PKG_ARRAY_TOO_LONG")}, findings_after(lambda p: p["sources"][0].__setitem__("authors", ["a"] * 101)))
        self.assertEqual(set(), findings_after(lambda p: p["sources"][0].__setitem__("authors", ["a"] * 100)))
        self.assertEqual(
            {("/security/redacted_categories/1", "PKG_ARRAY_DUPLICATE_ITEM")},
            findings_after(lambda p: p["security"].__setitem__("redacted_categories", ["password", "password"])),
        )

    def test_oversized_arrays_are_not_walked(self) -> None:
        package = full_package()
        package["citations"] = [{"citation_id": "c", "source_id": "missing"}] * 5001
        seal(package)
        self.assertEqual({("/citations", "PKG_ARRAY_TOO_LONG")}, {(f.pointer, f.code) for f in R.evaluate(package).findings})

    def test_generation_value_is_one_scalar_or_a_scalar_list(self) -> None:
        for value in ({"nested": 1}, [["nested"]], "v" * 10001):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(
                    {("/generation_parameters/0/value", "PKG_ONE_OF_MISMATCH")},
                    findings_after(lambda p, v=value: p["generation_parameters"][0].__setitem__("value", v)),
                )

    def test_dependent_members(self) -> None:
        self.assertEqual(
            {("/cost/currency", "PKG_FIELD_DEPENDENCY_MISSING")},
            findings_after(lambda p: p["cost"].pop("currency")),
        )
        self.assertEqual(
            {("/citations/0/response_end", "PKG_FIELD_DEPENDENCY_MISSING")},
            findings_after(lambda p: p["citations"][0].pop("response_end")),
        )
        self.assertEqual(set(), findings_after(lambda p: p.__setitem__("cost", {})))

    def test_findings_are_capped(self) -> None:
        package = full_package()
        package["sources"] = [{"source_id": "s", "extra": 1}] * 1000
        result = R.evaluate(package)
        self.assertEqual(S.MAX_FINDINGS, len(result.findings))
        self.assertIn("PKG_TOO_MANY_FINDINGS", result.reason_codes)


class SemanticRuleTests(unittest.TestCase):
    def test_lifecycle_state_must_be_raw(self) -> None:
        for state in ("VALIDATED", "PENDING", "raw", None):
            with self.subTest(state=state):
                found = findings_after(lambda p, s=state: p.__setitem__("lifecycle_state", s))
                self.assertIn(("/lifecycle_state", R.LIFECYCLE_STATE_NOT_RAW), found)
        self.assertTrue(R.evaluate(full_package()).valid)
        with self.assertRaises(R.ResearchPackageError) as caught:
            package = full_package()
            package["lifecycle_state"] = "VALIDATED"
            R.check(seal(package))
        self.assertIn(R.LIFECYCLE_STATE_NOT_RAW, caught.exception.reasons)

    def test_timestamp_order(self) -> None:
        pairs = (
            ("response_completed_at", "2026-09-01T09:59:59Z"),
            ("collected_at", "2026-09-01T10:00:05Z"),
            ("created_at", "2026-09-01T10:00:05.9Z"),
        )
        for name, value in pairs:
            with self.subTest(name=name):
                found = findings_after(lambda p, n=name, v=value: p["timestamps"].__setitem__(n, v))
                self.assertIn((f"/timestamps/{name}", R.TIMESTAMP_ORDER), found)
        # 12:00:06+02:00 is 10:00:06Z; 10:00:06.5+00:00 is later, so created_at stays valid.
        self.assertEqual(set(), findings_after(lambda p: p["timestamps"].__setitem__("created_at", "2026-09-01T10:00:06.5+00:00")))
        # Equal instants are allowed.
        self.assertEqual(set(), findings_after(lambda p: p["timestamps"].__setitem__("created_at", "2026-09-01T10:00:06Z")))
        # 11:00:06+02:00 is 09:00:06Z, before the response completed.
        self.assertIn(("/timestamps/collected_at", R.TIMESTAMP_ORDER), findings_after(lambda p: p["timestamps"].__setitem__("collected_at", "2026-09-01T11:00:06+02:00")))

    def test_ids_are_unique(self) -> None:
        cases = (
            (lambda p: p["sources"][1].__setitem__("source_id", "src-1"), "/sources/1/source_id"),
            (lambda p: p["citations"][1].__setitem__("citation_id", "cit-1"), "/citations/1/citation_id"),
            (lambda p: p["attachments"].append(copy.deepcopy(p["attachments"][0])), "/attachments/1/attachment_id"),
            (lambda p: p["generation_parameters"][1].__setitem__("name", "temperature"), "/generation_parameters/1/name"),
        )
        for change, pointer in cases:
            with self.subTest(pointer=pointer):
                self.assertIn((pointer, R.DUPLICATE_ID), findings_after(change))
        self.assertEqual(
            {("/sources/1/source_id", R.DUPLICATE_ID)},
            findings_after(lambda p: (p["sources"][1].__setitem__("source_id", "src-1"), p["citations"][1].__setitem__("source_id", "src-1"))),
        )

    def test_citations_reference_declared_sources(self) -> None:
        self.assertEqual(
            {("/citations/2/source_id", R.CITATION_SOURCE_UNKNOWN)},
            findings_after(lambda p: p["citations"][2].__setitem__("source_id", "src-9")),
        )
        self.assertEqual(
            {(f"/citations/{index}/source_id", R.CITATION_SOURCE_UNKNOWN) for index in range(3)},
            findings_after(lambda p: p.__setitem__("sources", [])),
        )

    def test_citation_offsets_count_code_points(self) -> None:
        self.assertEqual(
            {("/citations/0/response_start", R.CITATION_OFFSET_ORDER)},
            findings_after(lambda p: p["citations"][0].update(response_start=11, response_end=10)),
        )
        self.assertEqual(
            {("/citations/1/response_end", R.CITATION_OFFSET_RANGE)},
            findings_after(lambda p: p["citations"][1].__setitem__("response_end", len(RESPONSE_TEXT) + 1)),
        )
        # The emoji is one code point but two UTF-16 units: the end offset
        # len(text) is valid, len(text) + 1 is not.
        self.assertGreater(len(RESPONSE_TEXT.encode("utf-16-le")) // 2, len(RESPONSE_TEXT))
        self.assertEqual(set(), findings_after(lambda p: p["citations"][0].update(response_start=5, response_end=5)))

    def test_usage_consistency(self) -> None:
        cases = (
            ({"cached_input_tokens": 121}, "/usage/cached_input_tokens", R.USAGE_CACHED_EXCEEDS_INPUT),
            ({"reasoning_tokens": 81}, "/usage/reasoning_tokens", R.USAGE_REASONING_EXCEEDS_OUTPUT),
            ({"total_tokens": 199}, "/usage/total_tokens", R.USAGE_TOTAL_BELOW_SUM),
        )
        for update, pointer, code in cases:
            with self.subTest(code=code):
                self.assertEqual({(pointer, code)}, findings_after(lambda p, u=update: p["usage"].update(u)))
        self.assertEqual(set(), findings_after(lambda p: p["usage"].update(cached_input_tokens=120, reasoning_tokens=80, total_tokens=250)))
        # Rules only compare counters that are present.
        self.assertEqual(set(), findings_after(lambda p: p.__setitem__("usage", {"cached_input_tokens": 500, "total_tokens": 1})))

    def test_controlled_system_prompt_digest(self) -> None:
        self.assertEqual(
            {("/request/controlled_system_prompt/sha256", R.SYSTEM_PROMPT_SHA256_MISMATCH)},
            findings_after(lambda p: p["request"]["controlled_system_prompt"].__setitem__("text", SYSTEM_PROMPT + " ")),
        )

    def test_integrity_digest(self) -> None:
        self.assertEqual(
            {("/integrity/package_sha256", R.INTEGRITY_MISMATCH)},
            findings_after(lambda p: p["response"].__setitem__("text", RESPONSE_TEXT + "!"), reseal=False),
        )
        # The integrity member is outside the digest: changing it keeps the package valid.
        package = full_package()
        package["integrity"]["provider_raw_response_sha256"] = sha("other")
        self.assertTrue(R.evaluate(package).valid)
        # Member order and whitespace do not matter: the digest is RFC 8785.
        shuffled = dict(reversed(list(full_package().items())))
        self.assertTrue(R.evaluate_bytes(json.dumps(shuffled, indent=3, ensure_ascii=True).encode("utf-8")).valid)

    def test_values_outside_i_json_are_refused(self) -> None:
        self.assertIn(("", "JSON_INTEGER_OUT_OF_RANGE"), findings_after(lambda p: p["usage"].__setitem__("total_tokens", 2**60)))
        self.assertIn(("", "JSON_LONE_SURROGATE"), findings_after(lambda p: p["response"].__setitem__("text", "a\ud800b")))

    def test_declared_urls_follow_the_static_ssrf_policy(self) -> None:
        cases = (
            ("http://example.com/", {"PKG_PATTERN_MISMATCH", U.SCHEME_NOT_HTTPS}),
            ("https://reader@example.com/", {U.USERINFO}),
            ("https://192.0.2.10/page", {U.IP_RESERVED}),
            ("https://[2001:db8::1]/page", {U.IP_RESERVED}),
            ("https://intranet.example/page", {U.HOST_SPECIAL_USE}),
            ("https://example.com:8443/", {U.PORT_NOT_DEFAULT}),
            ("https://example.com/o?" + signed_parameter() + "=" + sha("s"), {U.PARAM_SIGNED}),
            ("https://example.com/o?access_" + "token=" + sha("t")[:20], {U.PARAM_CREDENTIAL}),
        )
        for url, expected in cases:
            with self.subTest(url=url[:40]):
                found = findings_after(lambda p, u=url: p["sources"][0].__setitem__("url", u))
                self.assertEqual({("/sources/0/url", code) for code in expected}, found)
                found = findings_after(lambda p, u=url: p["attachments"][0].__setitem__("source_url", u))
                self.assertEqual({("/attachments/0/source_url", code) for code in expected}, found)

    def test_every_reason_code_is_namespaced_and_event_compatible(self) -> None:
        import re

        pattern = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
        for code in R.REASON_CODES:
            self.assertRegex(code, pattern)
            self.assertTrue(code.startswith(("PKG_", "URL_", "JSON_")), code)


class BytesTests(unittest.TestCase):
    def encode(self, package: dict[str, Any]) -> bytes:
        return json.dumps(package, ensure_ascii=False).encode("utf-8")

    def test_strict_parsing_codes(self) -> None:
        body = self.encode(full_package())
        duplicate = body.replace(b'"lifecycle_state": "RAW"', b'"lifecycle_state": "VALIDATED", "lifecycle_state": "RAW"', 1)
        self.assertEqual(("JSON_DUPLICATE_KEY",), R.evaluate_bytes(duplicate).reason_codes)
        not_finite = body.replace(b'"amount": 0.0125', b'"amount": NaN', 1)
        self.assertEqual(("JSON_NON_FINITE_NUMBER",), R.evaluate_bytes(not_finite).reason_codes)
        self.assertEqual(("JSON_BOM_REFUSED",), R.evaluate_bytes(b"\xef\xbb\xbf" + body).reason_codes)
        self.assertEqual(("JSON_SIZE_EXCEEDED",), R.evaluate_bytes(body, max_bytes=100).reason_codes)
        self.assertTrue(R.evaluate_bytes(body).valid)


class SafetyTests(unittest.TestCase):
    def test_findings_and_errors_never_echo_content(self) -> None:
        marker = "synthetic-marker-7c3a"
        package = full_package()
        package[marker] = marker
        package["producer"]["provider"] = marker * 20
        package["sources"][0]["url"] = f"https://{marker}.internal/?token={marker}"
        package["response"]["text"] = marker
        package["citations"][0]["source_id"] = marker
        result = R.evaluate(package)
        self.assertFalse(result.valid)
        self.assertNotIn(marker, repr(result))
        self.assertNotIn(marker, json.dumps(result.as_dict()))
        with self.assertRaises(R.ResearchPackageError) as caught:
            R.check(package)
        self.assertNotIn(marker, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        body = ('{"%s": 1, "%s": 2}' % (marker, marker)).encode("utf-8")
        duplicate = R.evaluate_bytes(body)
        self.assertEqual(("JSON_DUPLICATE_KEY",), duplicate.reason_codes)
        self.assertNotIn(marker, repr(duplicate))

    def test_no_network_is_ever_used(self) -> None:
        names = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "create_connection", "socket")
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(mock.patch.object(socket, name, side_effect=AssertionError(name))) for name in names]
            R.evaluate(full_package())
            R.evaluate(minimal_package())
            R.evaluate_bytes(json.dumps(full_package()).encode())
        for patched in mocks:
            patched.assert_not_called()
        for path in (MODULE_PATH, MODULE_PATH.with_name("closed_schema.py")):
            source = path.read_text(encoding="utf-8")
            for forbidden in ("import socket", "urllib.request", "http.client", "import ssl", "subprocess"):
                self.assertNotIn(forbidden, source)

    def test_runtime_uses_the_standard_library_only(self) -> None:
        for path in (MODULE_PATH, MODULE_PATH.with_name("closed_schema.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [node.module or ""]
                else:
                    continue
                for name in modules:
                    self.assertIn(name.split(".")[0], sys.stdlib_module_names | {"__future__"}, path.name)

    def test_no_http_handler_or_service_imports_the_validator(self) -> None:
        own = {"research_package.py", "closed_schema.py", "lifecycle.py", "lineage.py"}
        for path in (PROJECT_ROOT / "services").rglob("*.py"):
            if path.parent.name == "quarantine" and path.name in own:
                continue
            with self.subTest(path=path.relative_to(PROJECT_ROOT).as_posix()):
                self.assertNotIn("research_package", path.read_text(encoding="utf-8"))

    def test_specification_documents_every_semantic_code(self) -> None:
        text = DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("PROVISOIRE", text)
        self.assertIn(R.POLICY_ID, text)
        for code in sorted(R.SEMANTIC_CODES | R.STRUCTURAL_CODES):
            self.assertIn(f"`{code}`", text)


class CommandLineTests(unittest.TestCase):
    def test_cli_reports_codes_only(self) -> None:
        marker = "synthetic-marker-7c3a"
        with sovereign_temporary_directory() as directory:
            valid = Path(directory) / "valid.json"
            valid.write_text(json.dumps(full_package(), ensure_ascii=False), encoding="utf-8")
            invalid_package = full_package()
            invalid_package["response"]["text"] = marker + RESPONSE_TEXT
            invalid = Path(directory) / "invalid.json"
            invalid.write_text(json.dumps(invalid_package), encoding="utf-8")
            outputs = []
            codes = []
            for path in (valid, invalid, Path(directory) / "missing.json"):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    codes.append(R.main([str(path)]))
                outputs.append(stdout.getvalue() + stderr.getvalue())
        self.assertEqual([0, 1, 2], codes)
        self.assertTrue(json.loads(outputs[0])["valid"])
        report = json.loads(outputs[1])
        self.assertEqual([{"code": R.INTEGRITY_MISMATCH, "pointer": "/integrity/package_sha256"}], report["findings"])
        for output in outputs:
            self.assertNotIn(marker, output)


if __name__ == "__main__":
    unittest.main()
