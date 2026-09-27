"""Interpreter for the closed JSON Schema subset mirrored by quarantine contracts.

PROVISOIRE: shared helper for the issue #6 candidate contracts.  It is a pure
library: no route, no port, no network and no filesystem access.

Each contract module (research packages, lifecycle events, derived artifacts)
embeds a *mirror* of its JSON schema as a Python literal.  This module checks
that the mirror only uses a small, explicitly supported keyword subset, then
evaluates documents against it.  Tests compare every mirror with its schema
file after removing annotations, so a drift between the two fails the suite.

Why a mirror instead of reading the schema file at run time: the validator
then depends on no file read during service start, interprets no keyword it
does not know, and cannot be loosened by an edit to a data file alone.

Deliberate differences with Draft 2020-12, all stricter:

* ``integer`` accepts only a JSON integer token, never ``1.0``;
* ``number`` refuses NaN and infinities;
* ``date-time`` requires an upper-case ``T`` and ``Z``, at most nine
  fractional digits and no leap second (``:60``);
* ``pattern`` follows ECMA-262: ``$`` matches only at the very end, and the
  locale-dependent classes ``\\d``, ``\\w``, ``\\s`` and ``\\b`` are refused;
* ``format`` is asserted, not an annotation; ``uri`` is delegated to the
  caller, which applies ``url_policy`` itself.

Findings carry a stable code and a JSON Pointer built only from schema
property names and array indexes.  An unknown member is reported on its
parent object, so a finding never echoes a key or a value of the document.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import importlib.util
import math
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any, Iterator


MAX_FINDINGS = 100

SCHEMA_KEYWORDS = frozenset(
    {
        "$ref",
        "type",
        "const",
        "enum",
        "pattern",
        "format",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
        "uniqueItems",
        "items",
        "properties",
        "additionalProperties",
        "required",
        "dependentRequired",
        "oneOf",
        "allOf",
        "if",
        "then",
        "else",
    }
)
ROOT_KEYWORDS = frozenset({"$defs"})
ANNOTATIONS = frozenset({"$schema", "$id", "title", "description", "$comment"})
TYPES = frozenset({"string", "integer", "number", "boolean", "null", "object", "array"})
FORMATS = frozenset({"uuid", "date-time", "uri"})
DELEGATED_FORMATS = frozenset({"uri"})

# Generic finding codes; a contract adds its own prefix (``PKG_``, ``EVENT_``...).
FIELD_MISSING = "FIELD_MISSING"
FIELD_UNKNOWN = "FIELD_UNKNOWN"
FIELD_FORBIDDEN = "FIELD_FORBIDDEN"
FIELD_DEPENDENCY_MISSING = "FIELD_DEPENDENCY_MISSING"
TYPE_MISMATCH = "TYPE_MISMATCH"
CONST_MISMATCH = "CONST_MISMATCH"
ENUM_MISMATCH = "ENUM_MISMATCH"
STRING_TOO_SHORT = "STRING_TOO_SHORT"
STRING_TOO_LONG = "STRING_TOO_LONG"
PATTERN_MISMATCH = "PATTERN_MISMATCH"
UUID_INVALID = "UUID_INVALID"
TIMESTAMP_INVALID = "TIMESTAMP_INVALID"
NUMBER_NOT_FINITE = "NUMBER_NOT_FINITE"
NUMBER_BELOW_MINIMUM = "NUMBER_BELOW_MINIMUM"
NUMBER_ABOVE_MAXIMUM = "NUMBER_ABOVE_MAXIMUM"
ARRAY_TOO_SHORT = "ARRAY_TOO_SHORT"
ARRAY_TOO_LONG = "ARRAY_TOO_LONG"
ARRAY_DUPLICATE_ITEM = "ARRAY_DUPLICATE_ITEM"
ONE_OF_MISMATCH = "ONE_OF_MISMATCH"
TOO_MANY_FINDINGS = "TOO_MANY_FINDINGS"

GENERIC_CODES = frozenset(
    {
        FIELD_MISSING,
        FIELD_UNKNOWN,
        FIELD_FORBIDDEN,
        FIELD_DEPENDENCY_MISSING,
        TYPE_MISMATCH,
        CONST_MISMATCH,
        ENUM_MISMATCH,
        STRING_TOO_SHORT,
        STRING_TOO_LONG,
        PATTERN_MISMATCH,
        UUID_INVALID,
        TIMESTAMP_INVALID,
        NUMBER_NOT_FINITE,
        NUMBER_BELOW_MINIMUM,
        NUMBER_ABOVE_MAXIMUM,
        ARRAY_TOO_SHORT,
        ARRAY_TOO_LONG,
        ARRAY_DUPLICATE_ITEM,
        ONE_OF_MISMATCH,
        TOO_MANY_FINDINGS,
    }
)

_RFC3339 = re.compile(
    r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
_LOCALE_CLASSES = re.compile(r"\\[dDwWsSbB]")


def _load_canonical_json() -> ModuleType:
    """Load the sibling ``canonical_json.py`` by path, without touching sys.path."""

    name = "sovereign_quarantine_canonical_json"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("canonical_json.py"))
        if spec is None or spec.loader is None:
            raise ImportError("canonical_json.py is missing next to closed_schema.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


_CANONICAL = _load_canonical_json()


class SchemaMirrorError(ValueError):
    """Programming error: a mirror uses a keyword this interpreter does not support."""


@dataclass(frozen=True, order=True)
class Finding:
    """One refusal: a JSON Pointer made of schema names and indexes, and a code."""

    pointer: str
    code: str


class _Overflow(Exception):
    pass


class _Sink:
    def __init__(self, prefix: str, limit: int) -> None:
        self.prefix = prefix
        self.limit = limit
        self.findings: set[Finding] = set()

    def add(self, code: str, pointer: str) -> None:
        self.findings.add(Finding(pointer, self.prefix + code))
        # Stop only once the cap is exceeded: exactly ``limit`` distinct
        # findings are all reported, without TOO_MANY_FINDINGS.
        if len(self.findings) > self.limit:
            raise _Overflow


def pointer_join(pointer: str, token: str | int) -> str:
    """RFC 6901 append; tokens are schema names or array indexes only."""

    text = str(token).replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{text}"


def parse_rfc3339(value: Any) -> tuple[datetime, int] | None:
    """Return a totally ordered UTC key for an RFC 3339 date-time, or ``None``.

    The key is ``(naive UTC datetime to the second, nanoseconds)``.  An offset
    is mandatory (``Z`` or ``±HH:MM``); ``-00:00`` is read as UTC.
    """

    if type(value) is not str:
        return None
    match = _RFC3339.match(value)
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    fraction, offset = match.group(7), match.group(8)
    if hour > 23 or minute > 59 or second > 59:
        return None
    if offset == "Z":
        delta = timedelta(0)
    else:
        offset_hours, offset_minutes = int(offset[1:3]), int(offset[4:6])
        if offset_hours > 23 or offset_minutes > 59:
            return None
        delta = timedelta(hours=offset_hours, minutes=offset_minutes)
        if offset[0] == "-":
            delta = -delta
    try:
        moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone(delta))
        utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        return None
    nanoseconds = int((fraction or "").ljust(9, "0"))
    return utc, nanoseconds


def is_uuid(value: Any) -> bool:
    return type(value) is str and _UUID.match(value) is not None


def json_equal(left: Any, right: Any) -> bool:
    """JSON equality: ``1 == 1.0`` but ``true != 1``; uncanonicalizable values never match."""

    try:
        return _CANONICAL.canonicalize(left) == _CANONICAL.canonicalize(right)
    except _CANONICAL.CanonicalJSONError:
        return False


def _ecma_pattern(pattern: str) -> re.Pattern[str]:
    """Compile an ECMA-262 pattern: an unescaped ``$`` outside a class ends the input."""

    if _LOCALE_CLASSES.search(pattern):
        raise SchemaMirrorError("locale-dependent regex classes are not supported")
    out: list[str] = []
    escaped = False
    in_class = False
    for character in pattern:
        if escaped:
            out.append(character)
            escaped = False
        elif character == "\\":
            out.append(character)
            escaped = True
        elif in_class:
            out.append(character)
            in_class = character != "]"
        elif character == "[":
            out.append(character)
            in_class = True
        elif character == "$":
            out.append(r"\Z")
        else:
            out.append(character)
    return re.compile("".join(out))


def _is_number(value: Any) -> bool:
    return type(value) is int or type(value) is float


def _type_matches(expected: str, value: Any) -> bool:
    if expected == "string":
        return type(value) is str
    if expected == "integer":
        return type(value) is int
    if expected == "number":
        return _is_number(value)
    if expected == "boolean":
        return type(value) is bool
    if expected == "null":
        return value is None
    if expected == "object":
        return type(value) is dict
    return type(value) is list


def _subschemas(node: dict[str, Any]) -> Iterator[Any]:
    for keyword in ("items", "if", "then", "else"):
        if keyword in node:
            yield node[keyword]
    for keyword in ("oneOf", "allOf"):
        yield from node.get(keyword, ())
    yield from node.get("properties", {}).values()


def strip_annotations(node: Any) -> Any:
    """Copy a schema without annotation keywords (keyword-aware, never property names)."""

    if type(node) is bool:
        return node
    result: dict[str, Any] = {}
    for keyword, value in node.items():
        if keyword in ANNOTATIONS:
            continue
        if keyword in ("properties", "$defs"):
            result[keyword] = {name: strip_annotations(item) for name, item in value.items()}
        elif keyword in ("items", "if", "then", "else"):
            result[keyword] = strip_annotations(value)
        elif keyword in ("oneOf", "allOf"):
            result[keyword] = [strip_annotations(item) for item in value]
        else:
            result[keyword] = value
    return result


class ClosedSchema:
    """Evaluate documents against a vetted mirror; findings only, never content."""

    def __init__(
        self,
        mirror: dict[str, Any],
        *,
        code_prefix: str,
        max_findings: int = MAX_FINDINGS,
    ) -> None:
        self.mirror = mirror
        self.code_prefix = code_prefix
        self.max_findings = max_findings
        self._definitions: dict[str, Any] = dict(mirror.get("$defs", {}))
        self._patterns: dict[str, re.Pattern[str]] = {}
        self._vet(mirror, root=True)

    # -- mirror vetting ----------------------------------------------------

    def _vet(self, node: Any, *, root: bool = False) -> None:
        if type(node) is bool:
            return
        if type(node) is not dict:
            raise SchemaMirrorError("a schema node must be an object or a boolean")
        allowed = SCHEMA_KEYWORDS | (ROOT_KEYWORDS if root else frozenset())
        unknown = set(node) - allowed
        if unknown:
            raise SchemaMirrorError("the mirror uses an unsupported keyword")
        if "$ref" in node:
            reference = node["$ref"]
            if not reference.startswith("#/$defs/") or reference[8:] not in self._definitions:
                raise SchemaMirrorError("only resolvable #/$defs/ references are supported")
        if "type" in node:
            types = node["type"] if type(node["type"]) is list else [node["type"]]
            if not types or set(types) - TYPES:
                raise SchemaMirrorError("unsupported type")
            if "object" in types and node.get("additionalProperties") is not False:
                raise SchemaMirrorError("every object schema must be closed")
        if "additionalProperties" in node and node["additionalProperties"] is not False:
            raise SchemaMirrorError("additionalProperties may only be false")
        if "format" in node and node["format"] not in FORMATS:
            raise SchemaMirrorError("unsupported format")
        if "pattern" in node:
            self._patterns.setdefault(node["pattern"], _ecma_pattern(node["pattern"]))
        for child in _subschemas(node):
            self._vet(child)
        if root:
            for definition in self._definitions.values():
                self._vet(definition)

    # -- evaluation ----------------------------------------------------------

    def evaluate(self, value: Any, *, schema: Any = None, pointer: str = "") -> tuple[Finding, ...]:
        """Findings for ``value`` against the root, or against a vetted subschema."""

        sink = _Sink(self.code_prefix, self.max_findings)
        try:
            self._apply(self.mirror if schema is None else schema, value, pointer, sink)
        except _Overflow:
            sink.findings.add(Finding("", self.code_prefix + TOO_MANY_FINDINGS))
        return finalize(sink.findings, self.code_prefix, self.max_findings)

    def definition(self, name: str) -> Any:
        return self._definitions[name]

    def matches(self, schema: Any, value: Any) -> bool:
        sink = _Sink("", 0)  # a limit of 0 stops at the first finding
        try:
            self._apply(schema, value, "", sink)
        except _Overflow:
            return False
        return not sink.findings

    def _apply(self, node: Any, value: Any, pointer: str, sink: _Sink) -> None:
        if node is True:
            return
        if node is False:
            sink.add(FIELD_FORBIDDEN, pointer)
            return
        if "$ref" in node:
            self._apply(self._definitions[node["$ref"][8:]], value, pointer, sink)
        if "type" in node:
            types = node["type"] if type(node["type"]) is list else [node["type"]]
            if not any(_type_matches(expected, value) for expected in types):
                sink.add(TYPE_MISMATCH, pointer)
                return
        if "const" in node and not json_equal(value, node["const"]):
            sink.add(CONST_MISMATCH, pointer)
        if "enum" in node and not any(json_equal(value, option) for option in node["enum"]):
            sink.add(ENUM_MISMATCH, pointer)
        if type(value) is str:
            self._apply_string(node, value, pointer, sink)
        elif _is_number(value):
            self._apply_number(node, value, pointer, sink)
        elif type(value) is list:
            self._apply_array(node, value, pointer, sink)
        elif type(value) is dict:
            self._apply_object(node, value, pointer, sink)
        if "oneOf" in node and sum(self.matches(option, value) for option in node["oneOf"]) != 1:
            sink.add(ONE_OF_MISMATCH, pointer)
        for option in node.get("allOf", ()):
            self._apply(option, value, pointer, sink)
        if "if" in node:
            branch = node.get("then") if self.matches(node["if"], value) else node.get("else")
            if branch is not None:
                self._apply(branch, value, pointer, sink)

    def _apply_string(self, node: dict[str, Any], value: str, pointer: str, sink: _Sink) -> None:
        if "minLength" in node and len(value) < node["minLength"]:
            sink.add(STRING_TOO_SHORT, pointer)
        if "maxLength" in node and len(value) > node["maxLength"]:
            sink.add(STRING_TOO_LONG, pointer)
            return
        if "pattern" in node and not self._patterns[node["pattern"]].search(value):
            sink.add(PATTERN_MISMATCH, pointer)
        form = node.get("format")
        if form == "uuid" and not is_uuid(value):
            sink.add(UUID_INVALID, pointer)
        elif form == "date-time" and parse_rfc3339(value) is None:
            sink.add(TIMESTAMP_INVALID, pointer)

    def _apply_number(self, node: dict[str, Any], value: int | float, pointer: str, sink: _Sink) -> None:
        if type(value) is float and not math.isfinite(value):
            sink.add(NUMBER_NOT_FINITE, pointer)
            return
        if "minimum" in node and value < node["minimum"]:
            sink.add(NUMBER_BELOW_MINIMUM, pointer)
        if "maximum" in node and value > node["maximum"]:
            sink.add(NUMBER_ABOVE_MAXIMUM, pointer)

    def _apply_array(self, node: dict[str, Any], value: list[Any], pointer: str, sink: _Sink) -> None:
        if "minItems" in node and len(value) < node["minItems"]:
            sink.add(ARRAY_TOO_SHORT, pointer)
        if "maxItems" in node and len(value) > node["maxItems"]:
            # Items beyond the bound are never inspected: the work stays bounded.
            sink.add(ARRAY_TOO_LONG, pointer)
            return
        if node.get("uniqueItems"):
            seen: set[bytes] = set()
            for index, item in enumerate(value):
                try:
                    key = _CANONICAL.canonicalize(item)
                except _CANONICAL.CanonicalJSONError:
                    continue
                if key in seen:
                    sink.add(ARRAY_DUPLICATE_ITEM, pointer_join(pointer, index))
                seen.add(key)
        if "items" in node:
            for index, item in enumerate(value):
                self._apply(node["items"], item, pointer_join(pointer, index), sink)

    def _apply_object(self, node: dict[str, Any], value: dict[str, Any], pointer: str, sink: _Sink) -> None:
        properties = node.get("properties", {})
        for name in node.get("required", ()):
            if name not in value:
                sink.add(FIELD_MISSING, pointer_join(pointer, name))
        if node.get("additionalProperties") is False and any(key not in properties for key in value):
            sink.add(FIELD_UNKNOWN, pointer)
        for name, dependencies in node.get("dependentRequired", {}).items():
            if name in value:
                for dependency in dependencies:
                    if dependency not in value:
                        sink.add(FIELD_DEPENDENCY_MISSING, pointer_join(pointer, dependency))
        for name, child in properties.items():
            if name in value:
                self._apply(child, value[name], pointer_join(pointer, name), sink)


def codes(findings: tuple[Finding, ...]) -> tuple[str, ...]:
    return tuple(sorted({finding.code for finding in findings}))


def finalize(findings: set[Finding], prefix: str, limit: int = MAX_FINDINGS) -> tuple[Finding, ...]:
    """Sort, deduplicate and cap findings; the cap itself is reported.

    Up to ``limit`` distinct findings are returned as they are.  Beyond that,
    or when an evaluation already stopped on the cap, ``limit - 1`` findings
    are kept and the last one is ``TOO_MANY_FINDINGS``.
    """

    overflow = Finding("", prefix + TOO_MANY_FINDINGS)
    ordered = sorted(item for item in findings if item != overflow)
    if len(ordered) > limit or overflow in findings:
        return tuple(sorted([*ordered[: limit - 1], overflow]))
    return tuple(ordered)


def bounded_list(value: Any, limit: int) -> list[Any]:
    """The list itself when it respects ``limit``; otherwise nothing to inspect."""

    return value if type(value) is list and len(value) <= limit else []
