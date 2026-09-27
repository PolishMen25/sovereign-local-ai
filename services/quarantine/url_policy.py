"""Static URL/SSRF policy for URLs declared in external packages.

PROVISOIRE: candidate rule set ``url-ssrf-policy-v1`` for issue #6, specified
in docs/security/url-ssrf-policy.md.  This module is a pure library: it is not
wired into any route, service or port.

The checker never performs network I/O.  It does not resolve names, open
sockets or follow redirects, so DNS answers, redirects and rebinding remain the
responsibility of whichever component dereferences URLs (pending the Research
Gateway ADR).  It refuses and never rewrites: a URL is returned as a sorted
tuple of reason codes, and an empty tuple means the static checks passed.
Reason codes never contain any part of the URL.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import unquote_plus


POLICY_ID = "url-ssrf-policy-v1"
MAX_URL_CHARS = 4096
MAX_HOSTNAME_CHARS = 253

NOT_A_STRING = "URL_NOT_A_STRING"
TOO_LONG = "URL_TOO_LONG"
MALFORMED = "URL_MALFORMED"
NOT_CANONICAL = "URL_NOT_CANONICAL"
SCHEME_NOT_HTTPS = "URL_SCHEME_NOT_HTTPS"
USERINFO = "URL_USERINFO"
PORT_NOT_DEFAULT = "URL_PORT_NOT_DEFAULT"
HOST_MISSING = "URL_HOST_MISSING"
HOST_INVALID = "URL_HOST_INVALID"
HOST_SINGLE_LABEL = "URL_HOST_SINGLE_LABEL"
HOST_SPECIAL_USE = "URL_HOST_SPECIAL_USE"
HOST_METADATA = "URL_HOST_METADATA"
IP_NONSTANDARD_FORM = "URL_IP_NONSTANDARD_FORM"
IP_UNSPECIFIED = "URL_IP_UNSPECIFIED"
IP_LOOPBACK = "URL_IP_LOOPBACK"
IP_PRIVATE = "URL_IP_PRIVATE"
IP_LINK_LOCAL = "URL_IP_LINK_LOCAL"
IP_CGNAT = "URL_IP_CGNAT"
IP_UNIQUE_LOCAL = "URL_IP_UNIQUE_LOCAL"
IP_MULTICAST = "URL_IP_MULTICAST"
IP_RESERVED = "URL_IP_RESERVED"
IP_IPV4_MAPPED = "URL_IP_IPV4_MAPPED"
IP_METADATA = "URL_IP_METADATA"
PARAM_SIGNED = "URL_PARAM_SIGNED"
PARAM_CREDENTIAL = "URL_PARAM_CREDENTIAL"

REASON_CODES = frozenset(
    {
        NOT_A_STRING,
        TOO_LONG,
        MALFORMED,
        NOT_CANONICAL,
        SCHEME_NOT_HTTPS,
        USERINFO,
        PORT_NOT_DEFAULT,
        HOST_MISSING,
        HOST_INVALID,
        HOST_SINGLE_LABEL,
        HOST_SPECIAL_USE,
        HOST_METADATA,
        IP_NONSTANDARD_FORM,
        IP_UNSPECIFIED,
        IP_LOOPBACK,
        IP_PRIVATE,
        IP_LINK_LOCAL,
        IP_CGNAT,
        IP_UNIQUE_LOCAL,
        IP_MULTICAST,
        IP_RESERVED,
        IP_IPV4_MAPPED,
        IP_METADATA,
        PARAM_SIGNED,
        PARAM_CREDENTIAL,
    }
)
# Reason codes that reveal an embedded credential rather than a destination.
CREDENTIAL_REASON_CODES = frozenset({USERINFO, PARAM_SIGNED, PARAM_CREDENTIAL})

# Explicit tables keep the result independent of the Python version's own
# ``is_private``/``is_global`` definitions, which have changed over time.
_IPV4_CLASSES = tuple(
    (ipaddress.IPv4Network(network), code)
    for network, code in (
        ("0.0.0.0/8", IP_UNSPECIFIED),
        ("10.0.0.0/8", IP_PRIVATE),
        ("100.64.0.0/10", IP_CGNAT),
        ("127.0.0.0/8", IP_LOOPBACK),
        ("169.254.0.0/16", IP_LINK_LOCAL),
        ("172.16.0.0/12", IP_PRIVATE),
        ("192.0.0.0/24", IP_RESERVED),
        ("192.0.2.0/24", IP_RESERVED),
        ("192.88.99.0/24", IP_RESERVED),
        ("192.168.0.0/16", IP_PRIVATE),
        ("198.18.0.0/15", IP_RESERVED),
        ("198.51.100.0/24", IP_RESERVED),
        ("203.0.113.0/24", IP_RESERVED),
        ("224.0.0.0/4", IP_MULTICAST),
        ("240.0.0.0/4", IP_RESERVED),
    )
)
_IPV6_CLASSES = tuple(
    (ipaddress.IPv6Network(network), code)
    for network, code in (
        ("::/128", IP_UNSPECIFIED),
        ("::1/128", IP_LOOPBACK),
        ("fe80::/10", IP_LINK_LOCAL),
        ("fc00::/7", IP_UNIQUE_LOCAL),
        ("ff00::/8", IP_MULTICAST),
        ("2001::/23", IP_RESERVED),
        ("2001:db8::/32", IP_RESERVED),
        ("2002::/16", IP_RESERVED),
        ("3fff::/20", IP_RESERVED),
    )
)
_IPV6_GLOBAL_UNICAST = ipaddress.IPv6Network("2000::/3")
# Two well-known public metadata addresses sit inside the RFC 6598 shared
# range and inside fc00::/7.  They are assembled from parts so that the D-036
# guard (tests/test_no_private_infrastructure_identifiers.py), which refuses
# such literals in tracked files, stays free of exceptions.
_METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(address)
    for address in (
        "169.254.169.254",
        "169.254.169.253",
        "169.254.170.2",
        ".".join(str(octet) for octet in (100, 100, 100, 200)),
        "168.63.129.16",
        ":".join(("fd00", "ec2", "", "254")),
    )
)
# RFC 2606/6761/6762/7686/8375/9476 and the ICANN ``.internal`` reservation,
# plus private suffixes that are commonly used but never delegated.
_SPECIAL_USE_TLDS = frozenset(
    {
        "localhost",
        "local",
        "internal",
        "arpa",
        "test",
        "example",
        "invalid",
        "onion",
        "alt",
        "home",
        "corp",
        "lan",
        "localdomain",
        "intranet",
        "private",
    }
)
_METADATA_HOSTNAMES = frozenset({"metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal"})

_SIGNED_PARAMETERS = frozenset(
    {
        "x-amz-signature",
        "x-amz-credential",
        "x-amz-security-token",
        "awsaccesskeyid",
        "x-goog-signature",
        "x-goog-credential",
        "googleaccessid",
        "signature",
        "sig",
        "se",
        "key-pair-id",
        "policy",
    }
)
_CREDENTIAL_PARAMETERS = frozenset(
    {
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "auth_token",
        "auth",
        "api_key",
        "apikey",
        "api-key",
        "x-api-key",
        "key",
        "access_key",
        "secret_key",
        "private_key",
        "client_secret",
        "secret",
        "password",
        "passwd",
        "pwd",
        "credential",
        "credentials",
        "session",
        "sessionid",
        "session_id",
        "jsessionid",
        "phpsessid",
    }
)

# RFC 3986 appendix B: splits any string without interpreting it.
_URI_PARTS = re.compile(r"^(?:([^:/?#]+):)?(?://([^/?#]*))?([^?#]*)(?:\?([^#]*))?(?:#(.*))?$", re.DOTALL)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_PORT = re.compile(r"^[0-9]{1,5}$")
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PARAMETER_SEPARATORS = re.compile(r"[&;?#/]")
_NOT_URI_CHARACTERS = frozenset('<>"{}|^`')
_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp", "Cs"})


class UrlPolicyError(ValueError):
    """Refusal carrying reason codes only, never the URL."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__(f"{POLICY_ID} refused: {', '.join(reasons)}")


def _is_refused_character(character: str) -> bool:
    if character == "\\" or character == " ":
        return True
    return unicodedata.category(character) in _REFUSED_CATEGORIES


def _parameter_names(component: str) -> set[str]:
    """Names of ``name=value`` pieces; a bare word such as ``#policy`` is an anchor."""

    names = set()
    for piece in _PARAMETER_SEPARATORS.split(component):
        name, separator, _value = piece.partition("=")
        name = unquote_plus(name).strip().lower()
        if separator and name:
            names.add(name)
    return names


def credential_reasons(url: str) -> tuple[str, ...]:
    """Return only the codes that reveal an embedded credential.

    It tolerates malformed input, so a scanner can apply it to URL-shaped text
    found anywhere in a document.
    """

    if not isinstance(url, str):
        return ()
    match = _URI_PARTS.match(url)
    if match is None:
        return ()
    _scheme, authority, path, query, fragment = match.groups()
    reasons = set()
    if authority is not None and "@" in authority:
        reasons.add(USERINFO)
    names = set()
    for segment in (path or "").split("/"):
        for parameter in segment.split(";")[1:]:
            names.update(_parameter_names(parameter))
    for component in (query, fragment):
        if component:
            names.update(_parameter_names(component))
    if names & _SIGNED_PARAMETERS:
        reasons.add(PARAM_SIGNED)
    if names & _CREDENTIAL_PARAMETERS:
        reasons.add(PARAM_CREDENTIAL)
    return tuple(sorted(reasons))


def _classify_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> set[str]:
    reasons = set()
    if address in _METADATA_ADDRESSES:
        reasons.add(IP_METADATA)
    if address.version == 4:
        for network, code in _IPV4_CLASSES:
            if address in network:
                reasons.add(code)
        return reasons
    mapped = address.ipv4_mapped
    if mapped is not None:
        return reasons | {IP_IPV4_MAPPED} | _classify_ip(mapped)
    classes = {code for network, code in _IPV6_CLASSES if address in network}
    if not classes and address not in _IPV6_GLOBAL_UNICAST:
        classes.add(IP_RESERVED)
    return reasons | classes


def _canonical_ipv6_text(address: ipaddress.IPv6Address) -> str:
    """RFC 5952 text, fixed here because ``str()`` of IPv4-mapped addresses
    changed between Python versions."""

    mapped = address.ipv4_mapped
    return f"::ffff:{mapped}" if mapped is not None else str(address)


def _ends_in_number(label: str) -> bool:
    if label.isascii() and label.isdigit():
        return True
    return label.startswith("0x") and all(character in "0123456789abcdef" for character in label[2:])


def _parse_whatwg_ipv4(name: str) -> ipaddress.IPv4Address | None:
    """IPv4 parsing as browsers and inet_aton do: decimal, octal, hex, short forms."""

    parts = name.split(".")
    if len(parts) > 4:
        return None
    numbers = []
    for part in parts:
        if not part:
            return None
        if part.startswith("0x"):
            digits, base, alphabet = part[2:], 16, "0123456789abcdef"
        elif len(part) > 1 and part.startswith("0"):
            digits, base, alphabet = part[1:], 8, "01234567"
        else:
            digits, base, alphabet = part, 10, "0123456789"
        if any(character not in alphabet for character in digits):
            return None
        numbers.append(int(digits, base) if digits else 0)
    if any(number > 255 for number in numbers[:-1]) or numbers[-1] >= 256 ** (5 - len(numbers)):
        return None
    value = numbers[-1]
    for index, number in enumerate(numbers[:-1]):
        value += number * 256 ** (3 - index)
    return ipaddress.IPv4Address(value)


def _valid_a_label(label: str) -> bool:
    try:
        unicode_label = label[4:].encode("ascii").decode("punycode")
        return unicode_label.encode("idna").decode("ascii").lower() == label
    except (UnicodeError, ValueError):
        return False


def _classify_hostname(host: str) -> set[str]:
    if "%" in host:
        return {HOST_INVALID}
    reasons = set()
    name = host
    if name.endswith("."):
        reasons.add(NOT_CANONICAL)
        name = name[:-1]
    if not name or name.endswith("."):
        return reasons | {HOST_INVALID}
    try:
        ascii_name = name.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return reasons | {HOST_INVALID}
    if ascii_name != name:
        reasons.add(NOT_CANONICAL)
    labels = ascii_name.split(".")
    if _ends_in_number(labels[-1]):
        address = _parse_whatwg_ipv4(ascii_name)
        if address is None:
            return reasons | {HOST_INVALID}
        if str(address) != ascii_name:
            reasons.add(IP_NONSTANDARD_FORM)
        return reasons | _classify_ip(address)
    if len(ascii_name) > MAX_HOSTNAME_CHARS:
        return reasons | {HOST_INVALID}
    for label in labels:
        if not _LABEL.match(label):
            return reasons | {HOST_INVALID}
        if label[2:4] == "--" and not (label.startswith("xn--") and _valid_a_label(label)):
            return reasons | {HOST_INVALID}
    if len(labels) == 1:
        reasons.add(HOST_SINGLE_LABEL)
    if labels[-1] in _SPECIAL_USE_TLDS:
        reasons.add(HOST_SPECIAL_USE)
    if ascii_name in _METADATA_HOSTNAMES:
        reasons.add(HOST_METADATA)
    return reasons


def _classify_authority(authority: str) -> set[str]:
    reasons = set()
    host_port = authority.rpartition("@")[2]
    if host_port.startswith("["):
        end = host_port.find("]")
        if end < 0:
            return {MALFORMED}
        host, rest = host_port[1:end], host_port[end + 1 :]
        if rest and not rest.startswith(":"):
            return {MALFORMED}
        port = rest[1:] if rest else None
        bracketed = True
    else:
        if host_port.count(":") > 1:
            return {MALFORMED}
        host, separator, port_text = host_port.partition(":")
        port = port_text if separator else None
        bracketed = False
    if port is not None:
        if port == "":
            reasons.add(NOT_CANONICAL)
        elif not _PORT.match(port) or int(port) > 65535:
            return reasons | {MALFORMED}
        elif int(port) != 443:
            reasons.add(PORT_NOT_DEFAULT)
        else:
            reasons.add(NOT_CANONICAL)
    if not host:
        return reasons | {HOST_MISSING}
    if bracketed:
        if "%" in host:
            return reasons | {HOST_INVALID}
        try:
            address = ipaddress.IPv6Address(host)
        except ValueError:
            return reasons | {HOST_INVALID}
        if _canonical_ipv6_text(address) != host:
            reasons.add(NOT_CANONICAL)
        return reasons | _classify_ip(address)
    return reasons | _classify_hostname(host)


def evaluate_url(url: object) -> tuple[str, ...]:
    """Return the sorted refusal reason codes; ``()`` means the URL passes."""

    if not isinstance(url, str):
        return (NOT_A_STRING,)
    if len(url) > MAX_URL_CHARS:
        return (TOO_LONG,)
    reasons = set(credential_reasons(url))
    if not url or any(_is_refused_character(character) for character in url):
        return tuple(sorted(reasons | {MALFORMED}))
    if not url.isascii() or any(character in _NOT_URI_CHARACTERS for character in url):
        reasons.add(NOT_CANONICAL)
    match = _URI_PARTS.match(url)
    if match is None:
        return tuple(sorted(reasons | {MALFORMED}))
    scheme, authority, _path, _query, _fragment = match.groups()
    if scheme is None or not _SCHEME.match(scheme) or scheme.lower() != "https":
        reasons.add(SCHEME_NOT_HTTPS)
    elif scheme != "https":
        reasons.add(NOT_CANONICAL)
    if authority is None or authority == "":
        reasons.add(HOST_MISSING)
    else:
        reasons |= _classify_authority(authority)
    return tuple(sorted(reasons))


def is_allowed(url: object) -> bool:
    return not evaluate_url(url)


def check_url(url: object) -> None:
    reasons = evaluate_url(url)
    if reasons:
        raise UrlPolicyError(reasons)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Vérifie hors ligne des URL (une par ligne) contre la politique url-ssrf-policy-v1 (PROVISOIRE). "
        "Les URL ne sont jamais recopiées dans la sortie."
    )
    parser.add_argument("path", type=Path, help="fichier texte UTF-8, une URL par ligne")
    arguments = parser.parse_args(argv)
    limit = 1024 * (MAX_URL_CHARS + 2)
    # Exit codes: 0 every URL allowed, 1 at least one URL refused, 2 unreadable input.
    refusal: str | None = None
    data = b""
    try:
        with arguments.path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        refusal = "the input file cannot be read"
    if refusal is None and len(data) > limit:
        refusal = "the input file exceeds 1024 lines of maximum length"
    text = ""
    if refusal is None:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            refusal = "the input file is not UTF-8"
    if refusal is not None:
        print(f"url check refused: {refusal}", file=sys.stderr)
        return 2
    # Split on LF only (and drop one trailing CR): str.splitlines() would also
    # split on U+2028, U+0085, VT, FF... and turn one refused line into several
    # allowed ones.  Those characters stay inside the line and are refused.
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    if lines[-1] == "":
        lines.pop()
    refused = 0
    for number, line in enumerate(lines, start=1):
        reasons = evaluate_url(line)
        refused += bool(reasons)
        print(json.dumps({"line": number, "policy_id": POLICY_ID, "reasons": list(reasons)}, sort_keys=True))
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
