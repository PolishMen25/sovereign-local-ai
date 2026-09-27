"""RFC 8785 (JCS) canonical JSON and the three SHA-256 hash scopes.

PROVISOIRE: candidate contract for issue #6.  This module is a pure library.
It is not wired into any route, service or port, and it never touches the
network or the filesystem outside the optional command-line entry point.

Three hash scopes are defined (see docs/data/canonical-hashing.md):

* ``ingress-payload-bytes``: SHA-256 of the exact entity body received,
  kept only in the collector receipt or journal, never inside the package;
* ``canonical-package-excluding-integrity``: SHA-256 of the RFC 8785 form
  of a research package without its top-level ``integrity`` member;
* ``provider-raw-response-bytes``: SHA-256 of a provider response stored as
  a separate object, never the package that references it.

``json.dumps(sort_keys=True)`` is *not* RFC 8785: it sorts keys by code point
instead of UTF-16 code units, formats numbers differently (``1.0``,
``1e-07``) and accepts NaN.  Strict parsing here also refuses what
``json.loads`` silently accepts: duplicate keys, NaN/Infinity, overflowing
numbers, integers outside the I-JSON safe range and lone surrogates.

Errors carry a stable reason code and a fixed message.  They never echo the
document, a key or a value, and they are raised without exception chaining so
that a traceback cannot carry the rejected bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


CANONICALIZATION = "RFC8785"
HASH_ALGORITHM = "SHA-256"
SCOPE_INGRESS = "ingress-payload-bytes"
SCOPE_PACKAGE = "canonical-package-excluding-integrity"
SCOPE_PROVIDER_RESPONSE = "provider-raw-response-bytes"
INTEGRITY_MEMBER = "integrity"

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 64
MAX_SAFE_INTEGER = 2**53 - 1
_MAX_INTEGER_TOKEN_CHARS = 20

_SURROGATE = re.compile("[\ud800-\udfff]")
_ESCAPED = re.compile('[\\x00-\\x1f"\\\\]')
_SHORT_ESCAPES = {
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
    '"': '\\"',
    "\\": "\\\\",
}
_UTF8_BOM = b"\xef\xbb\xbf"

_MESSAGES = {
    "BOM_REFUSED": "a byte order mark is not allowed",
    "DEPTH_EXCEEDED": "nesting depth exceeds the limit",
    "DUPLICATE_KEY": "an object contains a duplicate key",
    "INTEGER_OUT_OF_RANGE": "an integer is outside the I-JSON safe range",
    "INVALID_UTF8": "the document is not valid UTF-8",
    "LONE_SURROGATE": "a string contains a lone surrogate",
    "MALFORMED_JSON": "the document is not valid JSON",
    "NON_FINITE_NUMBER": "NaN, Infinity and overflowing numbers are not allowed",
    "NON_STRING_KEY": "object keys must be strings",
    "NOT_AN_OBJECT": "a research package must be a JSON object",
    "NOT_BYTES": "hashed payloads must be bytes",
    "SIZE_EXCEEDED": "the document exceeds the size limit",
    "UNSUPPORTED_TYPE": "the value has a type JSON cannot represent",
}


class CanonicalJSONError(ValueError):
    """Refusal with a non-sensitive reason ``code``."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"{code}: {_MESSAGES[code]}")


def _fail(code: str) -> CanonicalJSONError:
    return CanonicalJSONError(code)


def _check_string(value: str) -> None:
    if _SURROGATE.search(value):
        raise _fail("LONE_SURROGATE")


def _check_integer(value: int) -> None:
    if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
        raise _fail("INTEGER_OUT_OF_RANGE")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _fail("DUPLICATE_KEY")
        document[key] = value
    return document


def _parse_integer(token: str) -> int:
    if len(token.lstrip("-")) > _MAX_INTEGER_TOKEN_CHARS:
        raise _fail("INTEGER_OUT_OF_RANGE")
    value = int(token)
    _check_integer(value)
    return value


def _parse_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise _fail("NON_FINITE_NUMBER")
    return value


def _parse_constant(_token: str) -> Any:
    raise _fail("NON_FINITE_NUMBER")


def _check_tree(value: Any, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise _fail("DEPTH_EXCEEDED")
    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise _fail("NON_STRING_KEY")
            _check_string(key)
            _check_tree(item, depth + 1)
    elif kind is list:
        for item in value:
            _check_tree(item, depth + 1)
    elif kind is str:
        _check_string(value)
    elif kind is int:
        _check_integer(value)
    elif kind is float:
        if not math.isfinite(value):
            raise _fail("NON_FINITE_NUMBER")
    elif value is None or kind is bool:
        return
    else:
        raise _fail("UNSUPPORTED_TYPE")


def loads_strict(data: bytes | str, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> Any:
    """Parse one JSON text under the strict I-JSON profile RFC 8785 requires."""

    # Refusals are raised outside every ``except`` block so that neither
    # ``__cause__`` nor ``__context__`` can keep the rejected text reachable.
    refusal: str | None = None
    if isinstance(data, str):
        try:
            data = data.encode("utf-8")
        except UnicodeEncodeError:
            refusal = "LONE_SURROGATE"
    if refusal is None and not isinstance(data, (bytes, bytearray)):
        refusal = "NOT_BYTES"
    if refusal is not None:
        raise _fail(refusal)
    if len(data) > max_bytes:
        raise _fail("SIZE_EXCEEDED")
    if bytes(data[:3]) == _UTF8_BOM:
        raise _fail("BOM_REFUSED")
    text = ""
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        refusal = "INVALID_UTF8"
    if refusal is not None:
        raise _fail(refusal)
    document: Any = None
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_int=_parse_integer,
            parse_float=_parse_float,
            parse_constant=_parse_constant,
        )
    except CanonicalJSONError as error:
        refusal = error.code
    except RecursionError:
        refusal = "DEPTH_EXCEEDED"
    except ValueError:
        refusal = "MALFORMED_JSON"
    if refusal is not None:
        raise _fail(refusal)
    _check_tree(document, 0)
    return document


def _escape(match: re.Match[str]) -> str:
    character = match.group(0)
    return _SHORT_ESCAPES.get(character) or f"\\u{ord(character):04x}"


def _serialize_string(value: str) -> str:
    _check_string(value)
    return '"' + _ESCAPED.sub(_escape, value) + '"'


def serialize_number(value: int | float) -> str:
    """Serialize a number exactly like ECMAScript ``Number.prototype.toString``."""

    if type(value) is int:
        _check_integer(value)
        return str(value)
    if type(value) is not float:
        raise _fail("UNSUPPORTED_TYPE")
    if not math.isfinite(value):
        raise _fail("NON_FINITE_NUMBER")
    if value == 0.0:
        return "0"
    if value < 0:
        return "-" + serialize_number(-value)
    # repr() yields the shortest digit string that round-trips, as ES6 requires.
    mantissa, _, exponent = repr(value).partition("e")
    integer_part, _, fraction_part = mantissa.partition(".")
    digits = integer_part + fraction_part
    point = len(integer_part) + int(exponent or "0")
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")
    k = len(digits)
    n = point
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits
    sign = "+" if n - 1 >= 0 else "-"
    head = digits[0] if k == 1 else digits[0] + "." + digits[1:]
    return f"{head}e{sign}{abs(n - 1)}"


def _serialize(value: Any, depth: int, out: list[str]) -> None:
    if depth > MAX_DEPTH:
        raise _fail("DEPTH_EXCEEDED")
    kind = type(value)
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif kind is str:
        out.append(_serialize_string(value))
    elif kind is int or kind is float:
        out.append(serialize_number(value))
    elif kind is list:
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _serialize(item, depth + 1, out)
        out.append("]")
    elif kind is dict:
        for key in value:
            if type(key) is not str:
                raise _fail("NON_STRING_KEY")
            _check_string(key)
        out.append("{")
        # RFC 8785 section 3.2.3: order by UTF-16 code units, not code points.
        for index, key in enumerate(sorted(value, key=lambda item: item.encode("utf-16-be"))):
            if index:
                out.append(",")
            out.append(_serialize_string(key))
            out.append(":")
            _serialize(value[key], depth + 1, out)
        out.append("}")
    else:
        raise _fail("UNSUPPORTED_TYPE")


def canonicalize(value: Any) -> bytes:
    """Return the RFC 8785 UTF-8 bytes of a JSON-compatible value."""

    out: list[str] = []
    _serialize(value, 0, out)
    return "".join(out).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonicalize(value)).hexdigest()


def package_sha256(package: Any) -> str:
    """Hash scope ``canonical-package-excluding-integrity``.

    Only the top-level ``integrity`` member is excluded; the input is never
    modified.  An absent ``integrity`` member gives the same digest, which is
    what lets a producer compute the value before writing it into the package.
    """

    if type(package) is not dict:
        raise _fail("NOT_AN_OBJECT")
    return canonical_sha256({key: item for key, item in package.items() if key != INTEGRITY_MEMBER})


def _bytes_sha256(payload: Any) -> str:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise _fail("NOT_BYTES")
    return hashlib.sha256(payload).hexdigest()


def ingress_sha256(body: bytes) -> str:
    """Hash scope ``ingress-payload-bytes``: the exact bytes received, unchanged."""

    return _bytes_sha256(body)


def provider_response_sha256(raw_response: bytes) -> str:
    """Hash scope ``provider-raw-response-bytes``: a separately stored object."""

    return _bytes_sha256(raw_response)


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise _fail("SIZE_EXCEEDED")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calcule une empreinte SHA-256 selon une portée définie (PROVISOIRE).")
    parser.add_argument(
        "--scope",
        required=True,
        choices=("canonical", "package", "ingress", "provider-response"),
        help="canonical : RFC 8785 du document entier ; package : RFC 8785 sans 'integrity' ; ingress/provider-response : octets exacts",
    )
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args(argv)
    # Exit codes: 0 digest printed, 1 document refused, 2 unreadable or oversized input.
    unreadable: str | None = None
    data = b""
    try:
        data = _read_bounded(arguments.path, MAX_DOCUMENT_BYTES)
    except OSError:
        unreadable = "the input file cannot be read"
    except CanonicalJSONError as error:
        unreadable = error.code
    if unreadable is not None:
        print(f"hash refused: {unreadable}", file=sys.stderr)
        return 2
    try:
        if arguments.scope == "ingress":
            scope, digest = SCOPE_INGRESS, ingress_sha256(data)
        elif arguments.scope == "provider-response":
            scope, digest = SCOPE_PROVIDER_RESPONSE, provider_response_sha256(data)
        elif arguments.scope == "package":
            scope, digest = SCOPE_PACKAGE, package_sha256(loads_strict(data))
        else:
            scope, digest = "canonical-document", canonical_sha256(loads_strict(data))
    except CanonicalJSONError as error:
        print(f"hash refused: {error.code}", file=sys.stderr)
        return 1
    print(canonicalize({"algorithm": HASH_ALGORITHM, "hash_scope": scope, "sha256": digest}).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
