"""Validate a sanitized Synology discovery record without third-party dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


REQUIRED_TOP_LEVEL = {"schema_version", "asset_class", "observed_at", "storage", "network", "controls"}
FORBIDDEN_KEY_FRAGMENTS = ("password", "secret", "token", "address", "hostname", "ip", "serial", "share", "path", "user")


def fail(message: str) -> None:
    raise ValueError(message)


def require_exact_keys(value: dict[str, Any], required: set[str], context: str) -> None:
    keys = set(value)
    if keys != required:
        fail(f"{context}: keys must be exactly {sorted(required)}")


def ensure_no_sensitive_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = key.lower()
            if any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS):
                fail(f"forbidden sensitive field: {key}")
            ensure_no_sensitive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            ensure_no_sensitive_keys(nested)


def validate(document: Any) -> None:
    if not isinstance(document, dict):
        fail("inventory must be an object")
    ensure_no_sensitive_keys(document)
    require_exact_keys(document, REQUIRED_TOP_LEVEL, "inventory")
    if document["schema_version"] != "0.1.0":
        fail("unsupported schema_version")
    if document["asset_class"] != "synology-rs3617xs-plus":
        fail("unexpected asset_class")
    if not isinstance(document["observed_at"], str) or "T" not in document["observed_at"]:
        fail("observed_at must be an ISO-8601 timestamp")

    storage = document["storage"]
    require_exact_keys(storage, {"dsm_version", "memory_gib", "volumes", "arrays"}, "storage")
    if not isinstance(storage["memory_gib"], int) or not 1 <= storage["memory_gib"] <= 1024:
        fail("storage.memory_gib is out of range")
    if not isinstance(storage["volumes"], list) or not storage["volumes"]:
        fail("storage.volumes must not be empty")
    for volume in storage["volumes"]:
        require_exact_keys(volume, {"filesystem", "total_gib", "used_gib", "available_gib"}, "volume")
        if volume["filesystem"] not in {"btrfs", "ext4", "other"}:
            fail("unsupported volume filesystem")
        if not all(isinstance(volume[field], int) and volume[field] >= 0 for field in ("total_gib", "used_gib", "available_gib")):
            fail("volume capacities must be non-negative integers")
        if volume["total_gib"] < volume["used_gib"] + volume["available_gib"]:
            fail("volume total capacity is smaller than used plus available")

    for array in storage["arrays"]:
        require_exact_keys(array, {"purpose", "raid_level", "expected_members", "active_members", "status"}, "array")
        if array["purpose"] not in {"data", "system", "ssd"} or array["raid_level"] not in {"raid1", "raid5", "raid6", "other"}:
            fail("unsupported array classification")
        if not isinstance(array["expected_members"], int) or not isinstance(array["active_members"], int):
            fail("array member counts must be integers")
        if not 0 <= array["active_members"] <= array["expected_members"]:
            fail("array active_members is inconsistent")
        if array["status"] == "healthy" and array["active_members"] != array["expected_members"]:
            fail("a healthy array must have all expected members")

    network = document["network"]
    require_exact_keys(network, {"active_physical_interfaces", "virtual_networking_present", "vpn_tunnel_present"}, "network")
    if not isinstance(network["active_physical_interfaces"], int) or not 0 <= network["active_physical_interfaces"] <= 32:
        fail("network.active_physical_interfaces is out of range")

    controls = document["controls"]
    control_fields = {"smart", "scrubbing", "snapshots", "restore_test", "acl_review"}
    require_exact_keys(controls, control_fields, "controls")
    if any(controls[field] not in {"verified", "present", "unknown", "not_configured"} for field in control_fields):
        fail("invalid control status")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_synology_inventory.py INVENTORY.json", file=sys.stderr)
        return 2
    try:
        document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        validate(document)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"invalid inventory: {error}", file=sys.stderr)
        return 1
    print("valid sanitized Synology inventory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
