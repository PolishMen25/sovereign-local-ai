"""Hygiene of the committed test fixtures (public repository).

Every file under tests/fixtures is scanned with the candidate secret scanner
``collector-secret-scan-v1`` and with reserved-value checks: an e-mail
address, a host name or an IP address must belong to the names and ranges
reserved for documentation (RFC 2606, RFC 6761, RFC 5737, RFC 3849).
Findings name a file and a check code only, never the matched text.
"""

from __future__ import annotations

import importlib.util
import ipaddress
from pathlib import Path
import re
import sys
import unittest

from tests._temp_support import sovereign_temporary_directory


PROJECT_ROOT = Path(__file__).parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
SCANNER_PATH = PROJECT_ROOT / "services" / "quarantine" / "secret_scan.py"
SCANNER_NAME = "sovereign_quarantine_secret_scan"
if SCANNER_NAME not in sys.modules:
    SPEC = importlib.util.spec_from_file_location(SCANNER_NAME, SCANNER_PATH)
    assert SPEC is not None and SPEC.loader is not None
    _MODULE = importlib.util.module_from_spec(SPEC)
    sys.modules[SCANNER_NAME] = _MODULE
    SPEC.loader.exec_module(_MODULE)
SCAN = sys.modules[SCANNER_NAME]

EMAIL_NOT_RESERVED = "EMAIL_DOMAIN_NOT_RESERVED"
HOST_NOT_RESERVED = "URL_HOST_NOT_RESERVED"
IPV4_NOT_DOCUMENTATION = "IPV4_NOT_DOCUMENTATION"
IPV6_NOT_DOCUMENTATION = "IPV6_NOT_DOCUMENTATION"

RESERVED_DOMAINS = ("example.com", "example.net", "example.org")
RESERVED_TOP_LEVEL = ("example", "test", "invalid", "localhost")
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(network) for network in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
_URL_AUTHORITY = re.compile(r"(?i)\b[a-z][a-z0-9+.-]{1,15}://([^\s/?#\"'<>\\]+)")
_IPV4 = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
_IPV6 = re.compile(r"(?<![0-9A-Za-z:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Za-z:])")


def reserved_name(host: str) -> bool:
    host = host.lower().rstrip(".")
    if any(host == domain or host.endswith("." + domain) for domain in RESERVED_DOMAINS):
        return True
    return host.rpartition(".")[2] in RESERVED_TOP_LEVEL


def documentation_address(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    return any(address.version == network.version and address in network for network in DOCUMENTATION_NETWORKS)


def _host_codes(authority: str) -> set[str]:
    host = authority.rpartition("@")[2]
    if host.startswith("["):
        literal = host[1:].partition("]")[0]
        return set() if documentation_address(literal) else {IPV6_NOT_DOCUMENTATION}
    host = host.partition(":")[0]
    if _IPV4.fullmatch(host):
        return set() if documentation_address(host) else {IPV4_NOT_DOCUMENTATION}
    return set() if reserved_name(host) else {HOST_NOT_RESERVED}


def text_codes(text: str) -> set[str]:
    """Check codes for one text: secret categories and non-reserved values."""

    codes = set(SCAN.scan_text(text).categories)
    for match in _EMAIL.finditer(text):
        if not reserved_name(match.group(1)):
            codes.add(EMAIL_NOT_RESERVED)
    for match in _URL_AUTHORITY.finditer(text):
        codes |= _host_codes(match.group(1))
    for match in _IPV4.finditer(text):
        if not documentation_address(match.group(0)):
            codes.add(IPV4_NOT_DOCUMENTATION)
    for match in _IPV6.finditer(text):
        candidate = match.group(0)
        try:
            ipaddress.IPv6Address(candidate)
        except ValueError:
            continue  # clock times such as 10:00:05 are not addresses
        if not documentation_address(candidate):
            codes.add(IPV6_NOT_DOCUMENTATION)
    return codes


def scan_tree(root: Path) -> tuple[int, list[tuple[str, str]]]:
    """(files scanned, sorted findings) for every file below ``root``."""

    findings: set[tuple[str, str]] = set()
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        count += 1
        text = path.read_bytes().decode("utf-8", errors="replace")
        relative = path.relative_to(root).as_posix()
        findings |= {(relative, code) for code in text_codes(text)}
    return count, sorted(findings)


class FixtureHygieneTests(unittest.TestCase):
    def test_committed_fixtures_are_clean(self) -> None:
        count, findings = scan_tree(FIXTURES)
        self.assertEqual([], findings)
        self.assertGreaterEqual(count, 50)

    def test_every_fixture_file_is_scanned(self) -> None:
        files = [path for path in FIXTURES.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
        count, _findings = scan_tree(FIXTURES)
        self.assertEqual(len(files), count)
        for directory in ("research-package", "lifecycle-events"):
            self.assertTrue(any(path.parent.name == directory for path in files), directory)

    def test_planted_hits_are_detected_without_echo(self) -> None:
        planted = {
            "secret.txt": ("jeton : " + "ghp_" + "Zx9k" * 8, "SECRET_KNOWN_PREFIX"),
            "header.json": ('{"h": "Authorization: Bearer ' + "a1b2c3d4" * 3 + '"}', "SECRET_BEARER_TOKEN"),
            "email.jsonl": ('{"contact": "personne@' + "exemple-reel" + '.fr"}', EMAIL_NOT_RESERVED),
            "host.json": ('{"url": "https://' + "intranet" + '.corp/page"}', HOST_NOT_RESERVED),
            "ipv4.txt": ("hôte 10." + "20.30.40 joignable", IPV4_NOT_DOCUMENTATION),
            "url-ipv4.txt": ("https://" + "172.16." + "0.9/api", IPV4_NOT_DOCUMENTATION),
            "ipv6.txt": ("adresse fd00:" + ":7 locale", IPV6_NOT_DOCUMENTATION),
            # Undecodable bytes do not hide what follows them.
            "nested/deep.bin": (b"\xff\xfe" + b"fe80:" + b":1", IPV6_NOT_DOCUMENTATION),
        }
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            for name, (content, _code) in planted.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content if type(content) is bytes else content.encode("utf-8"))
            count, findings = scan_tree(root)
        self.assertEqual(len(planted), count)
        for name, (content, code) in planted.items():
            with self.subTest(name=name):
                self.assertIn((name, code), findings)
        self.assertEqual(set(planted), {name for name, _code in findings})
        rendered = repr(findings)
        for content, _code in planted.values():
            text = content.decode("latin-1") if type(content) is bytes else content
            for fragment in re.findall(r"[A-Za-z0-9:.]{6,}", text):
                self.assertNotIn(fragment, rendered)

    def test_reserved_values_pass(self) -> None:
        clean = "\n".join(
            (
                '{"url": "https://www.example.org/rapport.pdf", "autre": "https://intranet.example/page"}',
                "contact : reader@example.com, relais@collector.test",
                "https://reader@example.com/articles et https://example.com:8443/",
                "adresses 192.0.2.10, 198.51.100.7, 203.0.113.9 et https://[2001:db8::10]/rapport.pdf",
                "horodatages 2026-09-01T10:00:05Z et 12:00:06+02:00, version 0.1.0",
                "https://example.com/o?{{signed_param}}=" + "0" * 64,
                "empreinte " + "ab" * 32,
            )
        )
        self.assertEqual(set(), text_codes(clean))
        with sovereign_temporary_directory() as directory:
            (Path(directory) / "clean.txt").write_text(clean, encoding="utf-8")
            self.assertEqual((1, []), scan_tree(Path(directory)))


if __name__ == "__main__":
    unittest.main()
