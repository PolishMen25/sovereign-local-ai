"""Tests for the closed JSON Schema subset interpreter shared by quarantine contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "services" / "quarantine" / "closed_schema.py"
SPEC = importlib.util.spec_from_file_location("closed_schema", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

S = MODULE


def found(mirror: dict, value: object) -> set[tuple[str, str]]:
    return {(finding.pointer, finding.code) for finding in S.ClosedSchema(mirror, code_prefix="T_").evaluate(value)}


CONDITIONAL = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind"],
    "properties": {
        "kind": {"enum": ["a", "b"]},
        "extra": {"type": ["string", "null"], "pattern": "^x+$"},
        "tags": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}},
    },
    "allOf": [
        {
            "if": {"properties": {"kind": {"const": "a"}}, "required": ["kind"]},
            "then": {"required": ["extra"]},
            "else": {"properties": {"extra": False}},
        }
    ],
}


class ClosedSchemaTests(unittest.TestCase):
    def test_if_then_else_and_false_schema(self) -> None:
        self.assertEqual(set(), found(CONDITIONAL, {"kind": "a", "extra": "xx"}))
        self.assertEqual(set(), found(CONDITIONAL, {"kind": "a", "extra": None}))
        self.assertEqual({("/extra", "T_FIELD_MISSING")}, found(CONDITIONAL, {"kind": "a"}))
        self.assertEqual({("/extra", "T_FIELD_FORBIDDEN")}, found(CONDITIONAL, {"kind": "b", "extra": "x"}))
        self.assertEqual(set(), found(CONDITIONAL, {"kind": "b"}))

    def test_type_lists_and_array_bounds(self) -> None:
        self.assertEqual({("/extra", "T_TYPE_MISMATCH")}, found(CONDITIONAL, {"kind": "a", "extra": 3}))
        self.assertEqual({("/tags", "T_ARRAY_TOO_SHORT")}, found(CONDITIONAL, {"kind": "b", "tags": []}))
        self.assertEqual({("/tags", "T_ARRAY_TOO_LONG")}, found(CONDITIONAL, {"kind": "b", "tags": ["a", "b", 3]}))
        self.assertEqual({("/tags/0", "T_TYPE_MISMATCH")}, found(CONDITIONAL, {"kind": "b", "tags": [1]}))

    def test_json_equality_distinguishes_booleans_from_numbers(self) -> None:
        self.assertTrue(S.json_equal(1, 1.0))
        self.assertFalse(S.json_equal(True, 1))
        self.assertFalse(S.json_equal(float("nan"), float("nan")))
        self.assertEqual({("", "T_CONST_MISMATCH")}, found({"const": 1}, True))
        self.assertEqual(set(), found({"const": 1}, 1))

    def test_rfc3339_keys_order_instants_in_utc(self) -> None:
        early = S.parse_rfc3339("2026-09-01T12:00:00+02:00")
        late = S.parse_rfc3339("2026-09-01T10:00:00.000000001Z")
        self.assertIsNotNone(early)
        self.assertIsNotNone(late)
        self.assertLess(early, late)
        self.assertEqual(S.parse_rfc3339("2026-09-01T10:00:00-00:00"), S.parse_rfc3339("2026-09-01T10:00:00Z"))
        for value in ("0001-01-01T00:00:00+00:01", "9999-12-31T23:59:59-00:01", "2026-09-01T10:00:00", 20260901, None):
            with self.subTest(value=value):
                self.assertIsNone(S.parse_rfc3339(value))

    def test_strip_annotations_keeps_properties_named_like_annotations(self) -> None:
        schema = {
            "title": "x",
            "type": "object",
            "additionalProperties": False,
            "properties": {"title": {"type": "string", "description": "d"}},
            "$defs": {"description": {"type": "string", "$comment": "c"}},
        }
        self.assertEqual(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"title": {"type": "string"}},
                "$defs": {"description": {"type": "string"}},
            },
            S.strip_annotations(schema),
        )

    def test_findings_are_capped_and_the_cap_is_reported(self) -> None:
        mirror = {"type": "array", "items": {"type": "string"}}
        result = S.ClosedSchema(mirror, code_prefix="T_", max_findings=5).evaluate(list(range(20)))
        self.assertEqual(5, len(result))
        self.assertIn(S.Finding("", "T_TOO_MANY_FINDINGS"), result)
        few = S.finalize({S.Finding("/a", "T_X")}, "T_", 5)
        self.assertEqual((S.Finding("/a", "T_X"),), few)

    def test_the_cap_is_reported_only_when_exceeded(self) -> None:
        mirror = {"type": "array", "items": {"type": "string"}}
        overflow = S.Finding("", "T_TOO_MANY_FINDINGS")
        for limit in (5, S.MAX_FINDINGS):
            schema = S.ClosedSchema(mirror, code_prefix="T_", max_findings=limit)
            for count, capped in ((limit - 1, False), (limit, False), (limit + 1, True)):
                with self.subTest(limit=limit, count=count):
                    result = schema.evaluate([1] * count)
                    self.assertEqual(min(count, limit), len(result))
                    self.assertEqual(capped, overflow in result)
                    if not capped:
                        self.assertEqual({S.Finding(f"/{index}", "T_TYPE_MISMATCH") for index in range(count)}, set(result))
                    findings = {S.Finding(f"/{index:03d}", "T_X") for index in range(count)}
                    self.assertEqual(capped, overflow in S.finalize(findings, "T_", limit))
        self.assertFalse(S.ClosedSchema(mirror, code_prefix="T_").matches({"type": "string"}, 1))
        self.assertTrue(S.ClosedSchema(mirror, code_prefix="T_").matches({"type": "string"}, "a"))

    def test_bounded_list_refuses_oversized_or_non_lists(self) -> None:
        self.assertEqual([1, 2], S.bounded_list([1, 2], 2))
        self.assertEqual([], S.bounded_list([1, 2, 3], 2))
        self.assertEqual([], S.bounded_list({"a": 1}, 2))


if __name__ == "__main__":
    unittest.main()
