"""Structural and semantic validator for research-package 0.1.0.

PROVISOIRE: candidate contract ``research-package-contract-v1`` for issue #6,
specified in docs/data/research-package-validation.md.  This module is a pure
library.  It is not wired into any route, service or port, and no HTTP handler
imports it.  It never touches the network, and only the command-line entry
point reads a file.

Two layers run on every package:

1. a structural layer that mirrors ``schemas/research-package.schema.json``
   (exact keys, types, bounds, patterns, ``const`` and ``enum``) through the
   closed-schema interpreter; ``tests/test_research_package_contract.py``
   proves the mirror equals the schema file, annotations aside;
2. semantic rules the schema cannot express: timestamp order, unique ids,
   citation to source integrity, code-point offsets, token usage consistency,
   the controlled system prompt digest, the RFC 8785 package digest and the
   static URL/SSRF policy.

Results are reason codes with a JSON Pointer made of schema names and array
indexes only.  They never echo a value, an unknown key or a URL.  The
secret-scan outcome (hard reject at ingress or flag at PENDING) is an owner
decision, so ``secret_scan`` is deliberately not applied here.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any


POLICY_ID = "research-package-contract-v1"
SCHEMA_VERSION = "0.1.0"
CODE_PREFIX = "PKG_"
JSON_PREFIX = "JSON_"


def _load_sibling(name: str, filename: str) -> ModuleType:
    """Load a sibling module by path, without touching sys.path."""

    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        if spec is None or spec.loader is None:
            raise ImportError(f"{filename} is missing next to research_package.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


_CANONICAL = _load_sibling("sovereign_quarantine_canonical_json", "canonical_json.py")
_URL_POLICY = _load_sibling("sovereign_quarantine_url_policy", "url_policy.py")
_SCHEMA = _load_sibling("sovereign_quarantine_closed_schema", "closed_schema.py")

Finding = _SCHEMA.Finding

# Semantic rule codes, in addition to the generic structural codes of
# closed_schema (prefixed ``PKG_``), the URL policy codes (``URL_``) and the
# strict JSON codes (``JSON_``).
LIFECYCLE_STATE_NOT_RAW = "PKG_LIFECYCLE_STATE_NOT_RAW"
TIMESTAMP_ORDER = "PKG_TIMESTAMP_ORDER"
DUPLICATE_ID = "PKG_DUPLICATE_ID"
CITATION_SOURCE_UNKNOWN = "PKG_CITATION_SOURCE_UNKNOWN"
CITATION_OFFSET_ORDER = "PKG_CITATION_OFFSET_ORDER"
CITATION_OFFSET_RANGE = "PKG_CITATION_OFFSET_RANGE"
USAGE_CACHED_EXCEEDS_INPUT = "PKG_USAGE_CACHED_EXCEEDS_INPUT"
USAGE_REASONING_EXCEEDS_OUTPUT = "PKG_USAGE_REASONING_EXCEEDS_OUTPUT"
USAGE_TOTAL_BELOW_SUM = "PKG_USAGE_TOTAL_BELOW_SUM"
SYSTEM_PROMPT_SHA256_MISMATCH = "PKG_SYSTEM_PROMPT_SHA256_MISMATCH"
INTEGRITY_MISMATCH = "PKG_INTEGRITY_MISMATCH"

SEMANTIC_CODES = frozenset(
    {
        LIFECYCLE_STATE_NOT_RAW,
        TIMESTAMP_ORDER,
        DUPLICATE_ID,
        CITATION_SOURCE_UNKNOWN,
        CITATION_OFFSET_ORDER,
        CITATION_OFFSET_RANGE,
        USAGE_CACHED_EXCEEDS_INPUT,
        USAGE_REASONING_EXCEEDS_OUTPUT,
        USAGE_TOTAL_BELOW_SUM,
        SYSTEM_PROMPT_SHA256_MISMATCH,
        INTEGRITY_MISMATCH,
    }
)
STRUCTURAL_CODES = frozenset(CODE_PREFIX + code for code in _SCHEMA.GENERIC_CODES)
JSON_CODES = frozenset(JSON_PREFIX + code for code in _CANONICAL._MESSAGES)
URL_CODES = frozenset(_URL_POLICY.REASON_CODES)
REASON_CODES = SEMANTIC_CODES | STRUCTURAL_CODES | JSON_CODES | URL_CODES

# Candidate order (PROVISOIRE): request_started_at <= response_completed_at
# <= collected_at <= created_at.
TIMESTAMP_SEQUENCE = ("request_started_at", "response_completed_at", "collected_at", "created_at")

# ---------------------------------------------------------------------------
# Mirror of schemas/research-package.schema.json (annotations removed).
# ---------------------------------------------------------------------------

_ID_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_MEDIA_TYPE_PATTERN = "^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$"
_PARAMETER_NAME_PATTERN = (
    "^(?!.*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth(?:orization)?|password|passwd|secret|credential"
    "|cookie|private[_-]?key))[a-z][a-z0-9_.-]{0,63}$"
)
_SCALAR_VALUES = [
    {"type": "string", "maxLength": 10000},
    {"type": "number"},
    {"type": "boolean"},
    {"type": "null"},
]

SCHEMA_MIRROR: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "package_id",
        "lifecycle_state",
        "producer",
        "timestamps",
        "request",
        "response",
        "sources",
        "citations",
        "attachments",
        "usage",
        "cost",
        "generation_parameters",
        "errors",
        "security",
        "integrity",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "package_id": {"type": "string", "format": "uuid"},
        "lifecycle_state": {"const": "RAW"},
        "producer": {"$ref": "#/$defs/producer"},
        "timestamps": {"$ref": "#/$defs/timestamps"},
        "request": {"$ref": "#/$defs/request"},
        "response": {"$ref": "#/$defs/response"},
        "sources": {"type": "array", "maxItems": 1000, "items": {"$ref": "#/$defs/source"}},
        "citations": {"type": "array", "maxItems": 5000, "items": {"$ref": "#/$defs/citation"}},
        "attachments": {"type": "array", "maxItems": 100, "items": {"$ref": "#/$defs/attachmentMetadata"}},
        "usage": {"$ref": "#/$defs/usage"},
        "cost": {"$ref": "#/$defs/cost"},
        "generation_parameters": {"type": "array", "maxItems": 100, "items": {"$ref": "#/$defs/generationParameter"}},
        "errors": {"type": "array", "maxItems": 100, "items": {"$ref": "#/$defs/sanitizedError"}},
        "security": {"$ref": "#/$defs/security"},
        "integrity": {"$ref": "#/$defs/integrity"},
    },
    "$defs": {
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "dateTime": {"type": "string", "format": "date-time"},
        "producer": {
            "type": "object",
            "additionalProperties": False,
            "required": ["provider", "model"],
            "properties": {
                "provider": {"type": "string", "minLength": 1, "maxLength": 100},
                "model": {"type": "string", "minLength": 1, "maxLength": 200},
                "provider_request_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "gateway_version": {"type": "string", "minLength": 1, "maxLength": 100},
            },
        },
        "timestamps": {
            "type": "object",
            "additionalProperties": False,
            "required": ["created_at", "request_started_at", "response_completed_at", "collected_at"],
            "properties": {
                "created_at": {"$ref": "#/$defs/dateTime"},
                "request_started_at": {"$ref": "#/$defs/dateTime"},
                "response_completed_at": {"$ref": "#/$defs/dateTime"},
                "collected_at": {"$ref": "#/$defs/dateTime"},
            },
        },
        "request": {
            "type": "object",
            "additionalProperties": False,
            "required": ["question"],
            "properties": {
                "question": {"type": "string", "minLength": 1, "maxLength": 200000},
                "controlled_system_prompt": {"$ref": "#/$defs/controlledSystemPrompt"},
                "conversation_id": {"type": "string", "minLength": 1, "maxLength": 256},
            },
        },
        "controlledSystemPrompt": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "controlled_by", "sha256"],
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 200000},
                "controlled_by": {"type": "string", "enum": ["research_gateway", "local_operator", "approved_template"]},
                "template_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "sha256": {"$ref": "#/$defs/sha256"},
            },
        },
        "response": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {
                "text": {"type": "string", "maxLength": 2000000},
                "language": {"type": "string", "pattern": "^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"},
                "finish_reason": {"type": "string", "minLength": 1, "maxLength": 100},
                "provider_status": {"type": "string", "enum": ["completed", "partial", "failed"]},
            },
        },
        "source": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_id", "kind", "retrieved_at"],
            "properties": {
                "source_id": {"type": "string", "pattern": _ID_PATTERN},
                "kind": {"type": "string", "enum": ["web", "document", "dataset", "api", "conversation", "other"]},
                "url": {"type": "string", "format": "uri", "pattern": "^https://", "maxLength": 4096},
                "title": {"type": "string", "maxLength": 2000},
                "publisher": {"type": "string", "maxLength": 500},
                "authors": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                },
                "published_at": {"$ref": "#/$defs/dateTime"},
                "retrieved_at": {"$ref": "#/$defs/dateTime"},
                "content_sha256": {"$ref": "#/$defs/sha256"},
                "media_type": {"type": "string", "pattern": _MEDIA_TYPE_PATTERN, "maxLength": 255},
            },
        },
        "citation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["citation_id", "source_id"],
            "properties": {
                "citation_id": {"type": "string", "pattern": _ID_PATTERN},
                "source_id": {"type": "string", "pattern": _ID_PATTERN},
                "response_start": {"type": "integer", "minimum": 0},
                "response_end": {"type": "integer", "minimum": 0},
                "locator": {"type": "string", "maxLength": 1000},
                "quoted_text_sha256": {"$ref": "#/$defs/sha256"},
            },
            "dependentRequired": {"response_start": ["response_end"], "response_end": ["response_start"]},
        },
        "attachmentMetadata": {
            "type": "object",
            "additionalProperties": False,
            "required": ["attachment_id", "filename", "media_type", "byte_size", "content_sha256"],
            "properties": {
                "attachment_id": {"type": "string", "pattern": _ID_PATTERN},
                "filename": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                    "pattern": "^[^\\\\/\\u0000-\\u001F]+$",
                },
                "media_type": {"type": "string", "pattern": _MEDIA_TYPE_PATTERN, "maxLength": 255},
                "byte_size": {"type": "integer", "minimum": 0, "maximum": 1073741824},
                "content_sha256": {"$ref": "#/$defs/sha256"},
                "source_url": {"type": "string", "format": "uri", "pattern": "^https://", "maxLength": 4096},
                "created_at": {"$ref": "#/$defs/dateTime"},
            },
        },
        "usage": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "input_tokens": {"type": "integer", "minimum": 0},
                "output_tokens": {"type": "integer", "minimum": 0},
                "total_tokens": {"type": "integer", "minimum": 0},
                "cached_input_tokens": {"type": "integer", "minimum": 0},
                "reasoning_tokens": {"type": "integer", "minimum": 0},
            },
        },
        "cost": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "amount": {"type": "number", "minimum": 0},
                "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
                "estimated": {"type": "boolean"},
            },
            "dependentRequired": {
                "amount": ["currency", "estimated"],
                "currency": ["amount", "estimated"],
                "estimated": ["amount", "currency"],
            },
        },
        "generationParameter": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "value"],
            "properties": {
                "name": {"type": "string", "pattern": _PARAMETER_NAME_PATTERN},
                "value": {
                    "oneOf": [
                        *_SCALAR_VALUES,
                        {"type": "array", "maxItems": 1000, "items": {"oneOf": list(_SCALAR_VALUES)}},
                    ]
                },
            },
        },
        "sanitizedError": {
            "type": "object",
            "additionalProperties": False,
            "required": ["code", "phase", "message", "retryable", "occurred_at"],
            "properties": {
                "code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,63}$"},
                "phase": {"type": "string", "enum": ["request", "provider", "collection", "attachment", "validation"]},
                "message": {"type": "string", "maxLength": 2000},
                "retryable": {"type": "boolean"},
                "occurred_at": {"$ref": "#/$defs/dateTime"},
                "provider_http_status": {"type": "integer", "minimum": 100, "maximum": 599},
                "provider_error_type": {"type": "string", "maxLength": 256},
            },
        },
        "security": {
            "type": "object",
            "additionalProperties": False,
            "required": ["producer_secret_scan_status", "redaction_policy_version", "scanned_at", "redactions_count"],
            "properties": {
                "producer_secret_scan_status": {"const": "passed"},
                "redaction_policy_version": {"type": "string", "minLength": 1, "maxLength": 100},
                "scanned_at": {"$ref": "#/$defs/dateTime"},
                "redactions_count": {"type": "integer", "minimum": 0},
                "redacted_categories": {
                    "type": "array",
                    "uniqueItems": True,
                    "maxItems": 50,
                    "items": {
                        "type": "string",
                        "enum": [
                            "api_key",
                            "access_token",
                            "cookie",
                            "credential",
                            "password",
                            "private_key",
                            "session_identifier",
                            "signed_url",
                            "personal_data",
                            "other",
                        ],
                    },
                },
            },
        },
        "integrity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["algorithm", "canonicalization", "hash_scope", "package_sha256"],
            "properties": {
                "algorithm": {"const": "SHA-256"},
                "canonicalization": {"const": "RFC8785"},
                "hash_scope": {"const": "canonical-package-excluding-integrity"},
                "package_sha256": {"$ref": "#/$defs/sha256"},
                "provider_raw_response_sha256": {"$ref": "#/$defs/sha256"},
            },
        },
    },
}

_VALIDATOR = _SCHEMA.ClosedSchema(SCHEMA_MIRROR, code_prefix=CODE_PREFIX)
_SHA256 = _VALIDATOR.definition("sha256")

# Bounds reused by the semantic layer so it never walks an oversized array.
MAX_SOURCES = SCHEMA_MIRROR["properties"]["sources"]["maxItems"]
MAX_CITATIONS = SCHEMA_MIRROR["properties"]["citations"]["maxItems"]
MAX_ATTACHMENTS = SCHEMA_MIRROR["properties"]["attachments"]["maxItems"]
MAX_PARAMETERS = SCHEMA_MIRROR["properties"]["generation_parameters"]["maxItems"]


class ResearchPackageError(ValueError):
    """Refusal carrying reason codes only, never content."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__(f"{POLICY_ID} refused: {', '.join(reasons)}")


@dataclass(frozen=True)
class ValidationResult:
    policy_id: str
    schema_version: str
    findings: tuple[Any, ...]

    @property
    def valid(self) -> bool:
        return not self.findings

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return _SCHEMA.codes(self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "valid": self.valid,
            "findings": [{"code": finding.code, "pointer": finding.pointer} for finding in self.findings],
        }


def _member(document: Any, *names: str) -> Any:
    """Nested lookup that tolerates any malformed intermediate value."""

    value = document
    for name in names:
        if type(value) is not dict:
            return None
        value = value.get(name)
    return value


def _is_sha256(value: Any) -> bool:
    return _VALIDATOR.matches(_SHA256, value)


def _check_lifecycle_state(document: dict[str, Any], add: Any) -> None:
    if "lifecycle_state" in document and document["lifecycle_state"] != "RAW":
        add(LIFECYCLE_STATE_NOT_RAW, "/lifecycle_state")


def _check_timestamps(document: dict[str, Any], add: Any) -> None:
    timestamps = document.get("timestamps")
    if type(timestamps) is not dict:
        return
    keys = [_SCHEMA.parse_rfc3339(timestamps.get(name)) for name in TIMESTAMP_SEQUENCE]
    for index in range(1, len(TIMESTAMP_SEQUENCE)):
        earlier, later = keys[index - 1], keys[index]
        if earlier is not None and later is not None and later < earlier:
            add(TIMESTAMP_ORDER, f"/timestamps/{TIMESTAMP_SEQUENCE[index]}")


def _check_unique(items: list[Any], collection: str, field: str, add: Any) -> None:
    seen: set[str] = set()
    for index, item in enumerate(items):
        value = _member(item, field)
        if type(value) is not str:
            continue
        if value in seen:
            add(DUPLICATE_ID, f"/{collection}/{index}/{field}")
        seen.add(value)


def _check_citations(document: dict[str, Any], sources: list[Any], add: Any) -> None:
    # Only string ids are collected: a list or object id is unhashable and is
    # already reported by the structural layer (PKG_TYPE_MISMATCH).
    known = {value for value in (_member(source, "source_id") for source in sources) if type(value) is str}
    text = _member(document, "response", "text")
    for index, citation in enumerate(_SCHEMA.bounded_list(document.get("citations"), MAX_CITATIONS)):
        if type(citation) is not dict:
            continue
        source_id = citation.get("source_id")
        if type(source_id) is str and source_id not in known:
            add(CITATION_SOURCE_UNKNOWN, f"/citations/{index}/source_id")
        start, end = citation.get("response_start"), citation.get("response_end")
        if type(start) is not int or type(end) is not int or start < 0 or end < 0:
            continue
        if start > end:
            add(CITATION_OFFSET_ORDER, f"/citations/{index}/response_start")
        # Offsets count Unicode code points, exactly like len() of a str.
        if type(text) is str and end > len(text):
            add(CITATION_OFFSET_RANGE, f"/citations/{index}/response_end")


def _check_usage(document: dict[str, Any], add: Any) -> None:
    usage = document.get("usage")
    if type(usage) is not dict:
        return
    counts = {name: value for name, value in usage.items() if type(value) is int and value >= 0}
    if "cached_input_tokens" in counts and "input_tokens" in counts:
        if counts["cached_input_tokens"] > counts["input_tokens"]:
            add(USAGE_CACHED_EXCEEDS_INPUT, "/usage/cached_input_tokens")
    if "reasoning_tokens" in counts and "output_tokens" in counts:
        if counts["reasoning_tokens"] > counts["output_tokens"]:
            add(USAGE_REASONING_EXCEEDS_OUTPUT, "/usage/reasoning_tokens")
    if {"total_tokens", "input_tokens", "output_tokens"} <= counts.keys():
        if counts["total_tokens"] < counts["input_tokens"] + counts["output_tokens"]:
            add(USAGE_TOTAL_BELOW_SUM, "/usage/total_tokens")


def _check_system_prompt(document: dict[str, Any], add: Any) -> None:
    prompt = _member(document, "request", "controlled_system_prompt")
    if type(prompt) is not dict:
        return
    text, declared = prompt.get("text"), prompt.get("sha256")
    if type(text) is not str or not _is_sha256(declared):
        return
    try:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return  # a lone surrogate is reported by the canonical digest check
    if digest != declared:
        add(SYSTEM_PROMPT_SHA256_MISMATCH, "/request/controlled_system_prompt/sha256")


def _check_integrity(document: dict[str, Any], add: Any) -> None:
    refusal: str | None = None
    digest = ""
    try:
        digest = _CANONICAL.package_sha256(document)
    except _CANONICAL.CanonicalJSONError as error:
        refusal = error.code
    if refusal is not None:
        add(JSON_PREFIX + refusal, "")
        return
    declared = _member(document, "integrity", "package_sha256")
    if _is_sha256(declared) and declared != digest:
        add(INTEGRITY_MISMATCH, "/integrity/package_sha256")


def _check_urls(document: dict[str, Any], sources: list[Any], add: Any) -> None:
    targets = [(f"/sources/{index}/url", _member(source, "url")) for index, source in enumerate(sources)]
    attachments = _SCHEMA.bounded_list(document.get("attachments"), MAX_ATTACHMENTS)
    targets += [(f"/attachments/{index}/source_url", _member(item, "source_url")) for index, item in enumerate(attachments)]
    for pointer, url in targets:
        if type(url) is str:
            for reason in _URL_POLICY.evaluate_url(url):
                add(reason, pointer)


def evaluate(document: Any) -> ValidationResult:
    """Validate an already parsed package; reason codes and pointers only."""

    if type(document) is not dict:
        finding = Finding("", CODE_PREFIX + _SCHEMA.TYPE_MISMATCH)
        return ValidationResult(POLICY_ID, SCHEMA_VERSION, (finding,))
    found: set[Any] = set(_VALIDATOR.evaluate(document))

    def add(code: str, pointer: str) -> None:
        found.add(Finding(pointer, code))

    sources = _SCHEMA.bounded_list(document.get("sources"), MAX_SOURCES)
    _check_lifecycle_state(document, add)
    _check_timestamps(document, add)
    _check_unique(sources, "sources", "source_id", add)
    _check_unique(_SCHEMA.bounded_list(document.get("citations"), MAX_CITATIONS), "citations", "citation_id", add)
    _check_unique(_SCHEMA.bounded_list(document.get("attachments"), MAX_ATTACHMENTS), "attachments", "attachment_id", add)
    _check_unique(_SCHEMA.bounded_list(document.get("generation_parameters"), MAX_PARAMETERS), "generation_parameters", "name", add)
    _check_citations(document, sources, add)
    _check_usage(document, add)
    _check_system_prompt(document, add)
    _check_integrity(document, add)
    _check_urls(document, sources, add)
    return ValidationResult(POLICY_ID, SCHEMA_VERSION, _SCHEMA.finalize(found, CODE_PREFIX))


def evaluate_bytes(data: bytes, *, max_bytes: int | None = None) -> ValidationResult:
    """Parse with the strict RFC 8785 profile (duplicate keys, NaN... refused), then validate."""

    refusal: str | None = None
    document: Any = None
    limit = _CANONICAL.MAX_DOCUMENT_BYTES if max_bytes is None else max_bytes
    try:
        document = _CANONICAL.loads_strict(data, max_bytes=limit)
    except _CANONICAL.CanonicalJSONError as error:
        refusal = error.code
    if refusal is not None:
        return ValidationResult(POLICY_ID, SCHEMA_VERSION, (Finding("", JSON_PREFIX + refusal),))
    return evaluate(document)


def check(document: Any) -> None:
    result = evaluate(document)
    if not result.valid:
        raise ResearchPackageError(result.reason_codes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valide hors ligne un paquet research-package 0.1.0 (PROVISOIRE). "
        "La sortie ne contient que des codes de motif et des pointeurs, jamais le contenu."
    )
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args(argv)
    limit = _CANONICAL.MAX_DOCUMENT_BYTES
    try:
        with arguments.path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        print("validation refused: the input file cannot be read", file=sys.stderr)
        return 2
    result = evaluate_bytes(data, max_bytes=limit)
    print(_CANONICAL.canonicalize(result.as_dict()).decode("utf-8"))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
