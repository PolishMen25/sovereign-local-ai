"""Synthetic fixtures for the candidate research-package and lifecycle contracts.

Each fixture file under tests/fixtures/research-package/ and
tests/fixtures/lifecycle-events/ is listed in the directory's expected.json
with the exact refusals it must produce.  Template fixtures carry
placeholders instead of secret-shaped fragments; the fragments are assembled
here at run time, so no such literal is committed to the public repository.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any
import unittest


PROJECT_ROOT = Path(__file__).parents[1]
QUARANTINE = PROJECT_ROOT / "services" / "quarantine"
PACKAGE_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "research-package"
JOURNAL_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "lifecycle-events"
NOT_FIXTURES = {"expected.json", "README.md"}


def _load(name: str, filename: str) -> ModuleType:
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, QUARANTINE / filename)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


R = _load("research_package", "research_package.py")
L = _load("lifecycle", "lifecycle.py")
C = sys.modules["sovereign_quarantine_canonical_json"]
S = sys.modules["sovereign_quarantine_closed_schema"]
SCAN = _load("sovereign_quarantine_secret_scan", "secret_scan.py")

# Assembled at run time: the committed files only hold the placeholders.
RUNTIME_FRAGMENTS = {
    "{{signed_param}}": "X-Amz-" + "Signature",
    "{{credential_param}}": "access_" + "token",
    "{{bearer_value}}": hashlib.sha256(b"synthetic-bearer-value").hexdigest()[:24],
}

# Structural codes that no byte string can produce against research-package
# 0.1.0; each exclusion is re-proved in test_every_rule_has_an_invalid_fixture.
UNREACHABLE_PACKAGE_CODES = {
    "PKG_FIELD_FORBIDDEN",  # the schema has no false subschema
    "PKG_ARRAY_TOO_SHORT",  # the schema has no minItems
    "PKG_NUMBER_NOT_FINITE",  # the strict parser refuses NaN and infinities first
    "PKG_TOO_MANY_FINDINGS",  # a cap, not a rule (unit-tested)
}


def expected_cases(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "expected.json").read_text(encoding="utf-8"))


def fixture_files(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir() if path.is_file() and path.name not in NOT_FIXTURES}


def package_bytes(filename: str) -> bytes:
    text = (PACKAGE_FIXTURES / filename).read_text(encoding="utf-8")
    if filename.endswith(".template.json"):
        for placeholder, fragment in RUNTIME_FRAGMENTS.items():
            text = text.replace(placeholder, fragment)
    return text.encode("utf-8")


def read_journal(filename: str) -> tuple[list[Any], tuple[str, ...], int]:
    """Strict JSONL reading: events, or the refusal codes and the line index."""

    events: list[Any] = []
    lines = [line for line in (JOURNAL_FIXTURES / filename).read_bytes().split(b"\n") if line.strip()]
    for index, line in enumerate(lines):
        refusal: str | None = None
        try:
            events.append(C.loads_strict(line.rstrip(b"\r")))
        except C.CanonicalJSONError as error:
            refusal = error.code
        if refusal is not None:
            return events, ("JSON_" + refusal,), index
    return events, (), -1


def subschemas(node: Any) -> list[Any]:
    """Every schema node of a mirror, boolean subschemas included."""

    found = [node]
    if type(node) is dict:
        for keyword in ("items", "if", "then", "else"):
            if keyword in node:
                found += subschemas(node[keyword])
        for keyword in ("oneOf", "allOf"):
            for child in node.get(keyword, ()):
                found += subschemas(child)
        for keyword in ("properties", "$defs"):
            for child in node.get(keyword, {}).values():
                found += subschemas(child)
    return found


class ResearchPackageFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = expected_cases(PACKAGE_FIXTURES)
        self.cases = self.manifest["cases"]

    def test_manifest_lists_every_fixture_file(self) -> None:
        self.assertEqual(R.POLICY_ID, self.manifest["policy_id"])
        self.assertEqual(fixture_files(PACKAGE_FIXTURES), {case["file"] for case in self.cases})
        self.assertEqual(sorted(RUNTIME_FRAGMENTS), self.manifest["placeholders"])
        for name in fixture_files(PACKAGE_FIXTURES):
            text = (PACKAGE_FIXTURES / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertEqual(name.endswith(".template.json"), "{{" in text)

    def test_every_case_gives_exactly_the_expected_findings(self) -> None:
        for case in self.cases:
            with self.subTest(file=case["file"], max_bytes=case.get("max_bytes")):
                limit = case.get("max_bytes", C.MAX_DOCUMENT_BYTES)
                result = R.evaluate_bytes(package_bytes(case["file"]), max_bytes=limit)
                self.assertEqual(case["findings"], result.as_dict()["findings"])
                self.assertEqual(not case["findings"], result.valid)
                self.assertEqual(case["file"].startswith(("valid-", "flagged-")) and "max_bytes" not in case, result.valid)
                if "secret_scan" in case:
                    text = package_bytes(case["file"]).decode("utf-8")
                    self.assertEqual(tuple(case["secret_scan"]), SCAN.scan_text(text).categories)

    def test_at_least_two_valid_packages(self) -> None:
        valid = {case["file"] for case in self.cases if not case["findings"] and case["file"].startswith("valid-")}
        self.assertGreaterEqual(len(valid), 2)

    def test_every_rule_has_an_invalid_fixture(self) -> None:
        covered = {finding["code"] for case in self.cases for finding in case["findings"]}
        self.assertEqual(set(), R.SEMANTIC_CODES - covered)
        self.assertEqual(set(), R.STRUCTURAL_CODES - UNREACHABLE_PACKAGE_CODES - covered)
        # Re-prove the exclusions instead of trusting the comment.
        nodes = subschemas(R.SCHEMA_MIRROR)
        self.assertGreater(len(nodes), 100)
        self.assertFalse(any(node is False for node in nodes))
        self.assertFalse(any(type(node) is dict and "minItems" in node for node in nodes))
        with self.assertRaises(C.CanonicalJSONError):
            C.loads_strict(b'{"amount": NaN}')
        # The static URL policy and the strict JSON profile are applied too.
        self.assertTrue({code for code in covered if code.startswith("URL_")} >= {"URL_SCHEME_NOT_HTTPS", "URL_USERINFO", "URL_IP_RESERVED", "URL_PARAM_SIGNED", "URL_PARAM_CREDENTIAL"})
        self.assertTrue({code for code in covered if code.startswith("JSON_")} >= {"JSON_DUPLICATE_KEY", "JSON_NON_FINITE_NUMBER", "JSON_SIZE_EXCEEDED"})
        # A producer can never declare VALIDATED.
        self.assertIn(R.LIFECYCLE_STATE_NOT_RAW, covered)

    def test_secret_in_text_is_left_to_the_scanner(self) -> None:
        flagged = [case for case in self.cases if "secret_scan" in case]
        self.assertTrue(flagged)
        for case in flagged:
            self.assertEqual([], case["findings"])
            self.assertTrue(case["secret_scan"])
            # Without the runtime fragment, the committed file is clean.
            committed = (PACKAGE_FIXTURES / case["file"]).read_text(encoding="utf-8")
            self.assertEqual((), SCAN.scan_text(committed).categories)


class LifecycleFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = expected_cases(JOURNAL_FIXTURES)
        self.cases = self.manifest["cases"]

    def test_manifest_lists_every_fixture_file(self) -> None:
        self.assertEqual(L.POLICY_ID, self.manifest["policy_id"])
        self.assertEqual(fixture_files(JOURNAL_FIXTURES), {case["file"] for case in self.cases})

    def test_every_journal_replays_as_expected(self) -> None:
        for case in self.cases:
            with self.subTest(file=case["file"], max_events=case.get("max_events")):
                events, reasons, index = read_journal(case["file"])
                if not reasons:
                    try:
                        result = L.replay(events, max_events=case.get("max_events", L.MAX_EVENTS))
                    except L.LifecycleError as error:
                        reasons, index = error.reasons, error.event_index
                if "reasons" in case:
                    self.assertEqual((case["reasons"], case["event_index"]), (list(reasons), index))
                    continue
                self.assertEqual((), reasons)
                self.assertEqual(case["events_applied"], result.events_applied)
                self.assertEqual(case["duplicates_ignored"], result.duplicates_ignored)
                states = [[item["artifact_kind"], item["artifact_id"], item["state"]] for item in result.as_dict()["subjects"]]
                self.assertEqual(case["states"], states)

    def test_at_least_two_valid_journals(self) -> None:
        valid = {case["file"] for case in self.cases if "states" in case}
        self.assertGreaterEqual(len(valid), 2)
        self.assertTrue(all(name.startswith("valid-") for name in valid))

    def test_every_rule_has_an_invalid_fixture(self) -> None:
        covered = {reason for case in self.cases for reason in case.get("reasons", ())}
        self.assertEqual(set(), (L.EVENT_RULE_CODES | L.REPLAY_CODES) - covered)
        self.assertIn("JSON_DUPLICATE_KEY", covered)
        for name in {case["file"] for case in self.cases if "reasons" in case and "max_events" not in case}:
            self.assertTrue(name.startswith("invalid-"), name)


if __name__ == "__main__":
    unittest.main()
