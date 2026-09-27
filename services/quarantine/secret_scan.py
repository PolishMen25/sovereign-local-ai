"""Versioned server-side secret scanner ``collector-secret-scan-v1``.

PROVISOIRE: candidate detector for issue #6.  It is a pure library and is not
wired into any service: the live conversation collector keeps its own check
until the owner decides the per-category outcome policy (hard reject at
ingress or flag at PENDING) and the conversation contract, after PR #17.

The scanner reports category codes only.  Results, exceptions and the
command-line output never contain the matched text, an excerpt, an offset or a
length.  Refusals are raised outside ``except`` blocks, so no chained
exception keeps the scanned text reachable.

Categories (a text may match several):

``SECRET_BEARER_TOKEN``
    ``Bearer <value>`` with a value of at least 12 token characters.
``SECRET_BASIC_AUTH``
    ``Authorization: Basic <base64>``.
``SECRET_KNOWN_PREFIX``
    Provider token prefixes: ``sk``, ``ghp``/``gho``/``ghu``/``ghs``/``ghr``,
    ``github_pat``, ``glpat``, ``xox?``, ``cfpat`` followed by ``-`` or ``_``
    and at least 12 characters; ``hf_`` tokens; ``AKIA``/``ASIA`` access key
    ids; ``AIza`` API keys.
``SECRET_PRIVATE_KEY``
    A PEM or OpenPGP private-key header (``-----BEGIN ... PRIVATE KEY...``).
``SECRET_CREDENTIAL_ASSIGNMENT``
    ``password``, ``passwd``, ``mdp``, ``mot de passe``, ``api key``,
    ``access token`` or ``private key`` followed by ``:`` or ``=``, whatever the
    value.  This keeps what the live collector and the client relay already
    refuse or redact.
``SECRET_TOKEN_ASSIGNMENT``
    A ``token``, ``key``, ``secret``, ``passphrase``, ``pwd`` or
    ``credential`` label, possibly as a suffix (``client_secret``,
    ``clientSecret``, ``X-Api-Token``), assigned a value of at least 12 token
    characters that contains both a letter and a digit.
``SECRET_JWT``
    A JSON Web Token shape (``eyJ...``.``eyJ...``.``...``).
``SECRET_SIGNED_URL`` / ``SECRET_URL_CREDENTIAL_PARAM``
    A URL whose query, fragment or path parameters carry a signature or a
    credential, as decided by ``url_policy.credential_reasons``.
``SECRET_URL_USERINFO``
    A URL with ``user:password@`` (a user name alone is not reported).
``SECRET_MIXED_TOKEN``
    Low-precision heuristic kept for parity with the client relay: a run of at
    least 12 token characters mixing lower case, upper case and digits, with
    either 16 characters or a symbol.  It also fires on some identifiers and
    base64 data; its outcome policy is an owner decision.

Deliberate difference with the client relay (tools/codex_conversation_sync.py):
the relay strips every URL query string as a precaution.  The scanner only
reports URLs whose parameters are signed or credential-bearing, since a query
string alone is not a secret.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any


POLICY_ID = "collector-secret-scan-v1"
MAX_SCAN_CHARS = 4_000_000
MAX_DEPTH = 64
MAX_FILE_BYTES = 16 * 1024 * 1024

BEARER_TOKEN = "SECRET_BEARER_TOKEN"
BASIC_AUTH = "SECRET_BASIC_AUTH"
KNOWN_PREFIX = "SECRET_KNOWN_PREFIX"
PRIVATE_KEY = "SECRET_PRIVATE_KEY"
CREDENTIAL_ASSIGNMENT = "SECRET_CREDENTIAL_ASSIGNMENT"
TOKEN_ASSIGNMENT = "SECRET_TOKEN_ASSIGNMENT"
JWT = "SECRET_JWT"
SIGNED_URL = "SECRET_SIGNED_URL"
URL_CREDENTIAL_PARAM = "SECRET_URL_CREDENTIAL_PARAM"
URL_USERINFO = "SECRET_URL_USERINFO"
MIXED_TOKEN = "SECRET_MIXED_TOKEN"

CATEGORIES = frozenset(
    {
        BEARER_TOKEN,
        BASIC_AUTH,
        KNOWN_PREFIX,
        PRIVATE_KEY,
        CREDENTIAL_ASSIGNMENT,
        TOKEN_ASSIGNMENT,
        JWT,
        SIGNED_URL,
        URL_CREDENTIAL_PARAM,
        URL_USERINFO,
        MIXED_TOKEN,
    }
)

_STRONG_LABEL = r"(?:password|passwd|mdp|mot\s+de\s+passe|api[_ -]?key|access[_ -]?token|private[_ -]?key)"
_WEAK_LABEL = r"(?:token|key|secret|passphrase|pwd|credential)s?"
_ASSIGNMENT_VALUE = r"[A-Za-z0-9_~+/=!@#$%^&*-]{12,}"

_PATTERNS = (
    (BEARER_TOKEN, re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    (BASIC_AUTH, re.compile(r"(?i)\bAuthorization\s*:\s*Basic\s+[A-Za-z0-9+/=]{8,}")),
    (KNOWN_PREFIX, re.compile(r"(?i)\b(?:sk|ghp|gho|ghu|ghs|ghr|github_pat|glpat|xox[a-z]|cfpat)[-_][A-Za-z0-9._-]{12,}")),
    (KNOWN_PREFIX, re.compile(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{30,}")),
    (KNOWN_PREFIX, re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])")),
    (KNOWN_PREFIX, re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])")),
    (PRIVATE_KEY, re.compile(r"(?i)-----BEGIN[ A-Z0-9]*PRIVATE KEY(?: BLOCK)?-----")),
    (CREDENTIAL_ASSIGNMENT, re.compile(r"(?i)" + _STRONG_LABEL + r"[\"']?\s*[:=]")),
    (JWT, re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")),
)
# No left boundary: ``client_secret``, ``clientSecret`` and ``X-Api-Token`` all end
# with a weak label.  The value test keeps ``max_tokens: 4096`` and
# ``token = tokenizer.encode(text)`` out.
_TOKEN_ASSIGNMENT = re.compile(r"(?i)" + _WEAK_LABEL + r"[\"']?\s*[:=]\s*[\"']?(" + _ASSIGNMENT_VALUE + r")")
_STRONG_KEY = re.compile(r"(?i)" + _STRONG_LABEL)
_WEAK_KEY = re.compile(r"(?i)" + _WEAK_LABEL + r"$")
_ASSIGNMENT_VALUE_ONLY = re.compile(_ASSIGNMENT_VALUE)
_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]{1,15}://[^\s<>\"'`]+")
# Same candidate rule as the client relay's TOKEN_CANDIDATE heuristic.
_TOKEN_CANDIDATE = re.compile(r"(?<![\w])([A-Za-z0-9@#$%^&*!=+_-]{12,})(?![\w])")

_URL_REASON_TO_CATEGORY = {
    "URL_PARAM_SIGNED": SIGNED_URL,
    "URL_PARAM_CREDENTIAL": URL_CREDENTIAL_PARAM,
}

_MESSAGES = {
    "NOT_TEXT": "only text can be scanned",
    "SIZE_EXCEEDED": "the scanned content exceeds the size limit",
    "DEPTH_EXCEEDED": "nesting depth exceeds the limit",
    "UNSUPPORTED_TYPE": "the document contains a value that is not JSON",
}


class SecretScanError(ValueError):
    """Scan refusal with a non-sensitive ``code``; never carries content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"{code}: {_MESSAGES[code]}")


@dataclass(frozen=True)
class ScanResult:
    policy_id: str
    categories: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.categories


def _load_url_policy() -> ModuleType:
    """Load the sibling ``url_policy.py`` by path, without touching sys.path."""

    name = "sovereign_quarantine_url_policy"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("url_policy.py"))
        if spec is None or spec.loader is None:
            raise ImportError("url_policy.py is missing next to secret_scan.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


_URL_POLICY = _load_url_policy()


def _looks_like_secret_value(value: str) -> bool:
    return len(value) >= 12 and any(c.isalpha() for c in value) and any(c.isdigit() for c in value)


def _mixed_token(value: str) -> bool:
    classes = (
        any(c.islower() for c in value),
        any(c.isupper() for c in value),
        any(c.isdigit() for c in value),
    )
    has_symbol = any(not c.isalnum() for c in value)
    return all(classes) and (len(value) >= 16 or has_symbol)


def _userinfo_has_password(url: str) -> bool:
    authority = url.partition("://")[2]
    for separator in "/?#":
        authority = authority.partition(separator)[0]
    if "@" not in authority:
        return False
    userinfo = authority.rpartition("@")[0]
    _user, colon, password = userinfo.partition(":")
    return bool(colon and password)


def _categories_in_text(text: str, found: set[str]) -> None:
    for category, pattern in _PATTERNS:
        if category not in found and pattern.search(text):
            found.add(category)
    if TOKEN_ASSIGNMENT not in found:
        for match in _TOKEN_ASSIGNMENT.finditer(text):
            if _looks_like_secret_value(match.group(1)):
                found.add(TOKEN_ASSIGNMENT)
                break
    for match in _URL.finditer(text):
        url = match.group(0)
        for reason in _URL_POLICY.credential_reasons(url):
            category = _URL_REASON_TO_CATEGORY.get(reason)
            if category is not None:
                found.add(category)
        if _userinfo_has_password(url):
            found.add(URL_USERINFO)
    if MIXED_TOKEN not in found:
        for match in _TOKEN_CANDIDATE.finditer(text):
            if _mixed_token(match.group(1)):
                found.add(MIXED_TOKEN)
                break


def _categories_in_pair(key: str, value: str, found: set[str]) -> None:
    """Structured assignment: ``{"password": "..."}`` has no ``:`` in any string."""

    if _STRONG_KEY.search(key):
        found.add(CREDENTIAL_ASSIGNMENT)
    if _WEAK_KEY.search(key) and _ASSIGNMENT_VALUE_ONLY.fullmatch(value) and _looks_like_secret_value(value):
        found.add(TOKEN_ASSIGNMENT)


def _result(found: set[str]) -> ScanResult:
    return ScanResult(POLICY_ID, tuple(sorted(found)))


def scan_text(text: Any) -> ScanResult:
    """Scan one string and return category codes only."""

    if not isinstance(text, str):
        raise SecretScanError("NOT_TEXT")
    if len(text) > MAX_SCAN_CHARS:
        raise SecretScanError("SIZE_EXCEEDED")
    found: set[str] = set()
    _categories_in_text(text, found)
    return _result(found)


def scan_document(document: Any) -> ScanResult:
    """Scan every key and string of a JSON-compatible value.

    The total number of characters scanned is bounded by ``MAX_SCAN_CHARS``.
    """

    found: set[str] = set()
    budget = MAX_SCAN_CHARS
    stack: list[tuple[Any, int]] = [(document, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise SecretScanError("DEPTH_EXCEEDED")
        kind = type(value)
        if kind is str:
            budget -= len(value)
            if budget < 0:
                raise SecretScanError("SIZE_EXCEEDED")
            _categories_in_text(value, found)
        elif kind is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise SecretScanError("UNSUPPORTED_TYPE")
                budget -= len(key)
                if budget < 0:
                    raise SecretScanError("SIZE_EXCEEDED")
                _categories_in_text(key, found)
                if type(item) is str:
                    _categories_in_pair(key, item, found)
                stack.append((item, depth + 1))
        elif kind is list:
            stack.extend((item, depth + 1) for item in value)
        elif value is None or kind in (bool, int, float):
            continue
        else:
            raise SecretScanError("UNSUPPORTED_TYPE")
    return _result(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyse hors ligne un fichier avec collector-secret-scan-v1 (PROVISOIRE). "
        "Seules les catégories détectées sont affichées, jamais le texte trouvé."
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="analyser clés et chaînes d'un document JSON")
    arguments = parser.parse_args(argv)
    refusal: str | None = None
    data = b""
    try:
        with arguments.path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        refusal = "the input file cannot be read"
    if refusal is None and len(data) > MAX_FILE_BYTES:
        refusal = "the input file exceeds the size limit"
    text = ""
    if refusal is None:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            refusal = "the input file is not UTF-8"
    document: Any = None
    if refusal is None and arguments.json:
        try:
            document = json.loads(text)
        except ValueError:
            refusal = "the input file is not valid JSON"
    if refusal is not None:
        print(f"secret scan refused: {refusal}", file=sys.stderr)
        return 2
    try:
        result = scan_document(document) if arguments.json else scan_text(text)
    except SecretScanError as error:
        print(f"secret scan refused: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps({"categories": list(result.categories), "policy_id": result.policy_id}, sort_keys=True))
    return 0 if result.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
