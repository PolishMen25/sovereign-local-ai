"""Synthetic fixtures for the candidate research-package and lifecycle contracts.

Each fixture file under tests/fixtures/research-package/ and
tests/fixtures/lifecycle-events/ is listed in the directory's expected.json
with the exact refusals it must produce.  Template fixtures carry
placeholders instead of secret-shaped fragments; the fragments are assembled
at run time by tools/contract_fixture_hashes.py (the reseal helper), so no
such literal is committed to the public repository.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any
import unittest


PROJECT_ROOT = Path(__file__).parents[1]
QUARANTINE = PROJECT_ROOT / "services" / "quarantine"
TOOL_PATH = PROJECT_ROOT / "tools" / "contract_fixture_hashes.py"
PACKAGE_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "research-package"
JOURNAL_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "lifecycle-events"
NOT_FIXTURES = {"expected.json", "README.md"}


def _load(name: str, filename: str | Path) -> ModuleType:
    """A quarantine module by file name, or any module by absolute path."""

    module = sys.modules.get(name)
    if module is None:
        location = filename if isinstance(filename, Path) else QUARANTINE / filename
        spec = importlib.util.spec_from_file_location(name, location)
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
TOOL = _load("contract_fixture_hashes", TOOL_PATH)

# Assembled at run time by the reseal helper: the committed files only hold
# the placeholders.
RUNTIME_FRAGMENTS = TOOL.RUNTIME_FRAGMENTS

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
    return TOOL.expand(filename, (PACKAGE_FIXTURES / filename).read_bytes())


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


class ResealHelperTests(unittest.TestCase):
    """tools/contract_fixture_hashes.py gives the digests a fixture must carry."""

    def run_tool(self, *paths: Path) -> tuple[int, list[dict[str, Any]], str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = TOOL.main([str(path) for path in paths])
        return code, [json.loads(line) for line in stdout.getvalue().splitlines()], stderr.getvalue()

    def test_every_sealed_package_matches_its_recomputed_digest(self) -> None:
        cases = expected_cases(PACKAGE_FIXTURES)["cases"]
        codes = {case["file"]: {finding["code"] for finding in case["findings"]} for case in cases if "max_bytes" not in case}
        code, rows, _ = self.run_tool()
        self.assertEqual(1, code)  # the invalid-json-* fixtures are refused on purpose
        self.assertEqual(fixture_files(PACKAGE_FIXTURES), {row["file"] for row in rows})
        for row in rows:
            with self.subTest(file=row["file"]):
                if "refused" in row:
                    self.assertIn(row["refused"], codes[row["file"]])
                elif R.INTEGRITY_MISMATCH in codes[row["file"]]:
                    self.assertFalse(row["match"])
                else:
                    self.assertTrue(row["match"])
                    self.assertEqual(row["declared"], row["computed"])
        templates = [row for row in rows if row["file"].endswith(".template.json")]
        self.assertTrue(templates)
        # The digest of a template is the digest of its expanded form.
        for row in templates:
            expanded = C.loads_strict(package_bytes(row["file"]))
            self.assertEqual(C.package_sha256(expanded), row["computed"])

    def test_journal_mode_prints_the_chain_digests(self) -> None:
        path = JOURNAL_FIXTURES / "valid-package-lifecycle.jsonl"
        code, rows, _ = self.run_tool(path)
        self.assertEqual(0, code)
        events, reasons, _index = read_journal(path.name)
        self.assertEqual((), reasons)
        self.assertEqual([L.event_sha256(event) for event in events], [row["event_sha256"] for row in rows])
        seen: set[str] = set()
        for row in rows:
            if row["previous_event_sha256"] is not None:
                self.assertIn(row["previous_event_sha256"], seen)
            seen.add(row["event_sha256"])

    def test_the_helper_never_writes_and_reports_unreadable_input(self) -> None:
        before = {path.name: path.read_bytes() for path in PACKAGE_FIXTURES.iterdir()}
        self.run_tool()
        self.assertEqual(before, {path.name: path.read_bytes() for path in PACKAGE_FIXTURES.iterdir()})
        code, rows, stderr = self.run_tool(PACKAGE_FIXTURES / "absent-fixture.json")
        self.assertEqual((2, []), (code, rows))
        self.assertNotIn("absent-fixture", stderr)
        source = TOOL_PATH.read_text(encoding="utf-8")
        for forbidden in ("write_text", "write_bytes", "import socket", "urllib", "http.client", "subprocess"):
            self.assertNotIn(forbidden, source)


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
