"""D-036: the public repository carries no private infrastructure identifier.

The test fails when a tracked text file contains an RFC 1918 or RFC 6598
(shared address space) IPv4 literal, an IPv6 unique-local literal, a per-guest
hypervisor path or a container id tied to Proxmox tooling.  Documentation
ranges (RFC 5737, RFC 3849) are not private and stay allowed, as does the
canonical notation of a private block itself (its network address followed by
its own prefix length).  Real values live in the private configuration outside
Git (``services/common/private_endpoints.py``).

Every network and address is built at runtime so this file never matches
itself.  Findings name the file, the line and the rule, never the value, so a
failure does not copy a private address into a CI log.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
import re
import subprocess
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BINARY_PROBE_BYTES = 8192


def _ipv4_block(first: int, second: int, prefix: int) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(((first << 24) | (second << 16), prefix))


# RFC 1918 private blocks and the RFC 6598 shared block (carrier-grade NAT and
# overlay networks such as a tailnet).
PRIVATE_IPV4_BLOCKS = (
    _ipv4_block(10, 0, 8),
    _ipv4_block(172, 16, 12),
    _ipv4_block(192, 168, 16),
    _ipv4_block(100, 64, 10),
)
CANONICAL_BLOCK_NOTATIONS = frozenset(str(block) for block in PRIVATE_IPV4_BLOCKS)
UNIQUE_LOCAL_IPV6 = ipaddress.IPv6Network((0xFC << 120, 7))

IPV4_CANDIDATE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?!\.?\d)(/\d{1,2}(?!\d))?")
IPV6_UNIQUE_LOCAL_CANDIDATE = re.compile(r"(?<![0-9A-Za-z:])(f[cd][0-9a-f]{2}:[0-9a-f:]*[0-9a-f])(?![0-9A-Za-z:])", re.IGNORECASE)
HYPERVISOR_RULES = (
    ("per-guest hypervisor path", re.compile(r"/etc/pve/(?:[\w.-]+/)*(?:lxc|qemu-server|firewall)/\d+\.(?:conf|fw)\b")),
    ("per-guest cgroup path", re.compile(r"\blxc/\d{3,9}\b")),
    ("container id passed to pct/qm", re.compile(r"\b(?:pct|qm)\s+[a-z-]+\s+\d{3,9}\b")),
    ("container id written as CT <id>", re.compile(r"\bCT\s?\d{3,9}\b")),
)

# Explicit exceptions, each with its reason.  They are exercise data about IPv4
# arithmetic (textbook addresses), not infrastructure; the frozen suites are
# referenced by task digest, so their bytes must not change.
ALLOWLIST = {
    "configs/arena/practice-suite.v1.json": (
        "Suite d'exercices d'arène figée : arithmétique IPv4 sur des adresses génériques de manuel, "
        "sans lien avec l'infrastructure ; les tâches sont référencées par empreinte dans les paquets."
    ),
    "configs/evaluation/core-python-e2.candidate.json": (
        "Suite d'évaluation figée : un exercice de validation IPv4 emploie une adresse générique de "
        "manuel ; les tâches sont référencées par empreinte."
    ),
    "tools/arena_tasks_v2.py": (
        "Source des exercices IPv4 de la suite d'arène figée ; modifier une assertion changerait "
        "l'empreinte des tâches déjà approuvées."
    ),
    "tools/generate_arena_practice_suite.py": (
        "Générateur de la suite d'arène figée ; mêmes exercices IPv4 de manuel que la suite publiée."
    ),
}


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=PROJECT_ROOT, capture_output=True, timeout=60, check=False,
    )
    if completed.returncode != 0:
        raise unittest.SkipTest("not a Git checkout: tracked files cannot be listed")
    return sorted(name for name in completed.stdout.decode("utf-8").split("\0") if name)


def findings(text: str) -> list[tuple[int, str]]:
    """Return (line, rule) pairs; never the matched value."""

    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in IPV4_CANDIDATE.finditer(line):
            try:
                address = ipaddress.IPv4Address(match.group(1))
            except ValueError:
                continue
            if not any(address in block for block in PRIVATE_IPV4_BLOCKS):
                continue
            if match.group(2) and match.group(1) + match.group(2) in CANONICAL_BLOCK_NOTATIONS:
                continue
            found.append((number, "private IPv4 literal"))
        for match in IPV6_UNIQUE_LOCAL_CANDIDATE.finditer(line):
            try:
                address6 = ipaddress.IPv6Address(match.group(1))
            except ValueError:
                continue
            if address6 in UNIQUE_LOCAL_IPV6:
                found.append((number, "unique-local IPv6 literal"))
        for rule, pattern in HYPERVISOR_RULES:
            if pattern.search(line):
                found.append((number, rule))
    return found


def read_text(relative: str) -> str | None:
    path = PROJECT_ROOT / relative
    if not path.is_file():  # deleted in the working tree, or a submodule
        return None
    payload = path.read_bytes()
    if b"\0" in payload[:BINARY_PROBE_BYTES]:
        return None
    return payload.decode("utf-8", errors="replace")


def synthetic(*octets: int) -> str:
    return ".".join(str(octet) for octet in octets)


class DetectorTests(unittest.TestCase):
    def test_flags_private_and_shared_ipv4_literals(self) -> None:
        for address in (synthetic(10, 1, 2, 3), synthetic(172, 20, 0, 9), synthetic(192, 168, 7, 8), synthetic(100, 100, 1, 2)):
            with self.subTest(address=address):
                self.assertEqual(findings(f"endpoint = http://{address}:9000"), [(1, "private IPv4 literal")])
                self.assertEqual(findings(f"bind {address}/24"), [(1, "private IPv4 literal")])

    def test_ignores_documentation_public_and_canonical_notations(self) -> None:
        text = "\n".join((
            "http://192.0.2.10:9000 198.51.100.7 203.0.113.9 8.8.8.8 127.0.0.1 0.0.0.0",
            "version 1." + synthetic(10, 0, 0, 1) + " and " + synthetic(10, 0, 0, 1) + ".5 and 300.1.1.1",
            "blocks: " + ", ".join(sorted(CANONICAL_BLOCK_NOTATIONS)),
            "2001:db8::1 and ::1",
        ))
        self.assertEqual(findings(text), [])

    def test_flags_unique_local_ipv6_and_hypervisor_identifiers(self) -> None:
        guest = str(100 + 7)
        lines = (
            "fd" + "12:3456:789a::1",
            "/etc/pve/" + "lxc/" + guest + ".conf",
            "/etc/pve/" + "firewall/" + guest + ".fw",
            "pct " + "exec " + guest + " -- true",
            "C" + "T " + guest,
            "/sys/fs/cgroup/" + "lxc/" + guest,
        )
        for line in lines:
            with self.subTest(line=line):
                self.assertTrue(findings(line))
        self.assertEqual(findings('CONF="/etc/pve/lxc/${CT_CHAT}.conf"; pct exec "$CT_CHAT" -- true'), [])


class RepositoryTests(unittest.TestCase):
    def test_tracked_files_carry_no_private_infrastructure_identifier(self) -> None:
        violations: list[str] = []
        for relative in tracked_files():
            if relative in ALLOWLIST:
                continue
            text = read_text(relative)
            if text is None:
                continue
            violations.extend(f"{relative}:{line}: {rule}" for line, rule in findings(text))
        self.assertEqual(
            violations, [],
            "D-036 : identifiant d'infrastructure privée dans un fichier suivi ; le déplacer dans la "
            "configuration privée hors Git ou utiliser une valeur RFC 5737 / RFC 2606 :\n" + "\n".join(violations),
        )

    def test_allowlist_is_explicit_and_not_stale(self) -> None:
        tracked = set(tracked_files())
        for relative, reason in ALLOWLIST.items():
            with self.subTest(path=relative):
                self.assertIn(relative, tracked)
                self.assertGreaterEqual(len(reason.split()), 8, "each exception needs a real reason")
                text = read_text(relative)
                self.assertIsNotNone(text)
                self.assertTrue(findings(text or ""), "stale exception: remove it from the allowlist")


if __name__ == "__main__":
    unittest.main()
