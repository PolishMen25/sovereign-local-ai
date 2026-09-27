#!/usr/bin/env python3
"""Validate a default-deny network flow matrix between abstract trust zones.

The matrix names logical zones, never addresses, hostnames, ports or devices.
This tool is static: it reads one bounded JSON file, performs no network I/O
and needs no third-party dependency. A valid matrix is not a proof of
isolation; only the negative tests on the real network are.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any
import unicodedata


SCHEMA_VERSION = "network-flow-matrix.v1"
DEFAULT_POLICY = "deny"
MAXIMUM_MATRIX_BYTES = 256 * 1024
MINIMUM_FLOWS = 1
MAXIMUM_FLOWS = 128

TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "matrix_id", "status", "synthetic", "default_policy", "flows"}
)
FLOW_KEYS = frozenset(
    {
        "flow_id", "origin_zone", "destination_zone", "direction",
        "identity", "data_class", "justification", "approval_ref",
    }
)
STATUSES = frozenset({"proposed", "approved"})
ZONES = frozenset(
    {
        "internet", "dmz", "quarantine", "transfer-airlock", "ia-core",
        "interface-airlock", "local-clients", "admin", "storage-raw",
        "storage-internal", "coding-agent",
    }
)
DIRECTIONS = frozenset({"push", "pull", "bidirectional"})
DATA_CLASSES = frozenset(
    {
        "research-exchange", "raw-package", "conversation-export",
        "promoted-derivative", "local-session", "inference-call",
        "internal-knowledge", "model-artifact", "backup", "management",
        "name-resolution", "time-sync", "software-update",
    }
)
PENDING_APPROVAL = "pending-owner-approval"

# Anchored patterns shared verbatim with the JSON Schema (parity-tested).
MATRIX_ID_PATTERN = "^[a-z]+(-[a-z0-9]+){0,7}$"
FLOW_ID_PATTERN = "^NF-[0-9]{2,3}$"
IDENTITY_PATTERN = "^[a-z]+(-[a-z]+){0,5}$"
APPROVAL_REF_PATTERN = "^(D-[0-9]{3}|ADR-[0-9]{4}|pending-owner-approval)$"
APPROVED_REF_PATTERN = "^(D-[0-9]{3}|ADR-[0-9]{4})$"
MATRIX_ID_LENGTH = (3, 64)
IDENTITY_LENGTH = (3, 48)
JUSTIFICATION_LENGTH = (20, 400)

# Zone roles used by the graph rules. Every rule reasons on data edges:
# push moves content origin -> destination, pull destination -> origin,
# bidirectional both ways. The origin always initiates the connection.
EXPOSED_ZONES = frozenset({"internet", "dmz"})
PROTECTED_ZONES = frozenset({"ia-core", "storage-internal"})
NO_EGRESS_ZONES = frozenset({"ia-core", "storage-internal", "storage-raw"})
INSPECTION_ZONE = "quarantine"
RELAY_GUARDED_ZONES = frozenset({"storage-raw", "storage-internal", "transfer-airlock"})
APPEND_ONLY_ZONE = "storage-raw"
INTERNET_ZONE = "internet"
INTERNET_PEER_ZONE = "dmz"

# Free text must not carry infrastructure identifiers. Refusals never echo
# the offending text.
REDACTION_PATTERNS = (
    re.compile(r"(?<![0-9])[0-9]{1,3}(?:\.[0-9]{1,3}){2,3}(?![0-9])"),
    re.compile(r"(?i)(?<![0-9a-z])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-z])"),
    re.compile(r"(?i)(?<![0-9a-z])[0-9a-f]{2}(?:-[0-9a-f]{2}){5}(?![0-9a-z])"),
    re.compile(r"(?i)[a-z][a-z0-9+.-]*://"),
    re.compile(r"(?i)(?<![\w-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z][a-z0-9-]*(?![\w-])"),
    re.compile(r"(?:^|(?<=[\s(\[\"'`]))/[\w.-]+/"),
    re.compile(r"(?i)(?<![a-z0-9])(?:ct|vm|lxc|vmid)[\s#_-]?[0-9]+(?![0-9])"),
    re.compile(r"[@\\]"),
)


class MatrixRefused(ValueError):
    """A generic refusal that never embeds document content."""


def _fail(message: str) -> None:
    raise MatrixRefused(message)


def _full_match(pattern: str, value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _bounded(value: Any, bounds: tuple[int, int]) -> bool:
    return isinstance(value, str) and bounds[0] <= len(value) <= bounds[1]


def _ensure_redacted(value: str, label: str) -> None:
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        _fail(f"{label} contains a control or format character")
    if any(pattern.search(value) for pattern in REDACTION_PATTERNS):
        _fail(f"{label} contains an address, hostname, path or device-like token")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("matrix contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    _fail("matrix contains a non-finite JSON number")


def read_matrix_bytes(path: Path) -> bytes:
    """Read one regular, non-symlink file within the size bound."""
    try:
        before = os.lstat(path)
    except OSError:
        raise MatrixRefused("matrix file is unreadable") from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        _fail("matrix must be a regular file")
    if not 1 <= before.st_size <= MAXIMUM_MATRIX_BYTES:
        _fail("matrix size is outside the allowed range")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise MatrixRefused("matrix file is unreadable") from None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            _fail("matrix file changed while opening")
        chunks: list[bytes] = []
        remaining = MAXIMUM_MATRIX_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        raise MatrixRefused("matrix file is unreadable") from None
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    if not 1 <= len(payload) <= MAXIMUM_MATRIX_BYTES:
        _fail("matrix size is outside the allowed range")
    return payload


def parse_matrix(payload: bytes) -> Any:
    """Decode strict UTF-8 JSON: no BOM, NUL, duplicate key or NaN."""
    if not 1 <= len(payload) <= MAXIMUM_MATRIX_BYTES or b"\x00" in payload:
        _fail("matrix size or encoding is invalid")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise MatrixRefused("matrix is not valid UTF-8") from None
    try:
        return json.loads(
            text, object_pairs_hook=_strict_object, parse_constant=_reject_constant
        )
    except (json.JSONDecodeError, RecursionError):
        raise MatrixRefused("matrix is not strict JSON") from None


def _validate_flow(flow: Any, position: int) -> None:
    if not isinstance(flow, dict) or set(flow) != FLOW_KEYS:
        _fail(f"flow #{position}: keys must be exactly {sorted(FLOW_KEYS)}")
    if not _full_match(FLOW_ID_PATTERN, flow["flow_id"]):
        _fail(f"flow #{position}: flow_id is invalid")
    label = f"flow {flow['flow_id']}"
    for field in ("origin_zone", "destination_zone"):
        if not isinstance(flow[field], str) or flow[field] not in ZONES:
            _fail(f"{label}: {field} is not a known zone")
    if flow["origin_zone"] == flow["destination_zone"]:
        _fail(f"{label}: an interzone flow needs two distinct zones")
    if not isinstance(flow["direction"], str) or flow["direction"] not in DIRECTIONS:
        _fail(f"{label}: direction is invalid")
    if not isinstance(flow["data_class"], str) or flow["data_class"] not in DATA_CLASSES:
        _fail(f"{label}: data_class is invalid")
    if not _bounded(flow["identity"], IDENTITY_LENGTH) or not _full_match(
        IDENTITY_PATTERN, flow["identity"]
    ):
        _fail(f"{label}: identity is invalid")
    _ensure_redacted(flow["identity"], f"{label}: identity")
    justification = flow["justification"]
    if not _bounded(justification, JUSTIFICATION_LENGTH) or len(justification.strip()) < JUSTIFICATION_LENGTH[0]:
        _fail(f"{label}: justification is missing or outside the allowed length")
    _ensure_redacted(justification, f"{label}: justification")
    if not _full_match(APPROVAL_REF_PATTERN, flow["approval_ref"]):
        _fail(f"{label}: approval_ref is invalid")
    zones = {flow["origin_zone"], flow["destination_zone"]}
    if INTERNET_ZONE in zones and zones != {INTERNET_ZONE, INTERNET_PEER_ZONE}:
        _fail(f"{label}: only the dmz zone may exchange with the internet zone")
    if flow["destination_zone"] == APPEND_ONLY_ZONE and flow["direction"] != "push":
        _fail(f"{label}: storage-raw is append-only and accepts push flows only")


def data_edges(flows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Return the directed zone pairs along which content can move."""
    edges: set[tuple[str, str]] = set()
    for flow in flows:
        origin, destination = flow["origin_zone"], flow["destination_zone"]
        if flow["direction"] in {"push", "bidirectional"}:
            edges.add((origin, destination))
        if flow["direction"] in {"pull", "bidirectional"}:
            edges.add((destination, origin))
    return edges


def reachable_zones(
    edges: set[tuple[str, str]],
    sources: frozenset[str],
    removed: frozenset[str] = frozenset(),
) -> set[str]:
    """Breadth-first reachability that never enters a removed zone."""
    adjacency: dict[str, set[str]] = {}
    for origin, destination in edges:
        adjacency.setdefault(origin, set()).add(destination)
    seen = {zone for zone in sources if zone not in removed}
    queue = deque(sorted(seen))
    while queue:
        zone = queue.popleft()
        for neighbour in sorted(adjacency.get(zone, ())):
            if neighbour not in seen and neighbour not in removed:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


def _validate_graph(flows: list[dict[str, Any]]) -> None:
    edges = data_edges(flows)
    inbound = reachable_zones(edges, EXPOSED_ZONES, frozenset({INSPECTION_ZONE}))
    for zone in sorted(inbound & PROTECTED_ZONES):
        _fail(f"a data path from an exposed zone reaches {zone} without crossing quarantine")
    outbound = reachable_zones(edges, NO_EGRESS_ZONES)
    for zone in sorted(outbound & EXPOSED_ZONES):
        _fail(f"a data path from an internal zone reaches {zone}")
    for zone in sorted(RELAY_GUARDED_ZONES):
        writers = {origin for origin, destination in edges if destination == zone}
        readers = {destination for origin, destination in edges if origin == zone}
        if len(writers & readers) >= 2:
            _fail(f"{zone} would relay data both ways between two distinct zones")


def validate(document: Any) -> dict[str, Any]:
    """Refuse any matrix that breaks the contract; return a content-free summary."""
    if not isinstance(document, dict) or set(document) != TOP_LEVEL_KEYS:
        _fail(f"matrix keys must be exactly {sorted(TOP_LEVEL_KEYS)}")
    if document["schema_version"] != SCHEMA_VERSION:
        _fail("unsupported schema_version")
    if not _bounded(document["matrix_id"], MATRIX_ID_LENGTH) or not _full_match(
        MATRIX_ID_PATTERN, document["matrix_id"]
    ):
        _fail("matrix_id is invalid")
    _ensure_redacted(document["matrix_id"], "matrix_id")
    if not isinstance(document["status"], str) or document["status"] not in STATUSES:
        _fail("status is invalid")
    if not isinstance(document["synthetic"], bool):
        _fail("synthetic must be a boolean")
    if document["default_policy"] != DEFAULT_POLICY:
        _fail("default_policy must be deny")
    flows = document["flows"]
    if not isinstance(flows, list) or not MINIMUM_FLOWS <= len(flows) <= MAXIMUM_FLOWS:
        _fail("flows must be a bounded non-empty list")
    for position, flow in enumerate(flows, start=1):
        _validate_flow(flow, position)
    flow_ids = [flow["flow_id"] for flow in flows]
    if len(flow_ids) != len(set(flow_ids)):
        _fail("flow_id values must be unique")
    identities = [flow["identity"] for flow in flows]
    if len(identities) != len(set(identities)):
        _fail("each identity must be dedicated to exactly one flow")
    references = {flow["approval_ref"] for flow in flows}
    if document["synthetic"] and (
        document["status"] != "proposed" or references != {PENDING_APPROVAL}
    ):
        _fail("a synthetic matrix stays proposed with pending approvals only")
    if document["status"] == "approved" and (
        document["synthetic"]
        or not all(_full_match(APPROVED_REF_PATTERN, reference) for reference in references)
    ):
        _fail("an approved matrix must be real and cite a recorded decision for every flow")
    _validate_graph(flows)
    return {
        "status": document["status"],
        "synthetic": document["synthetic"],
        "flows": len(flows),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a default-deny network flow matrix (static, offline)."
    )
    parser.add_argument("matrix", type=Path, help="matrix JSON file to validate")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        summary = validate(parse_matrix(read_matrix_bytes(arguments.matrix)))
    except MatrixRefused as error:
        print(f"invalid network flow matrix: {error}", file=sys.stderr)
        return 1
    print(
        "valid network flow matrix: "
        f"status={summary['status']} "
        f"synthetic={'true' if summary['synthetic'] else 'false'} "
        f"flows={summary['flows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
