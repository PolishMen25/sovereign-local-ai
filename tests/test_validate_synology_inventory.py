import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "validate_synology_inventory.py"
SPEC = importlib.util.spec_from_file_location("validate_synology_inventory", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_inventory() -> dict:
    return {
        "schema_version": "0.1.0",
        "asset_class": "synology-rs3617xs-plus",
        "observed_at": "2026-08-31T12:00:00Z",
        "storage": {
            "dsm_version": "7.4.1",
            "memory_gib": 31,
            "volumes": [{"filesystem": "btrfs", "total_gib": 100, "used_gib": 20, "available_gib": 80}],
            "arrays": [{"purpose": "data", "raid_level": "raid6", "expected_members": 11, "active_members": 11, "status": "healthy"}],
        },
        "network": {"active_physical_interfaces": 3, "virtual_networking_present": True, "vpn_tunnel_present": True},
        "controls": {"smart": "unknown", "scrubbing": "unknown", "snapshots": "unknown", "restore_test": "unknown", "acl_review": "unknown"},
    }


class SynologyInventoryTests(unittest.TestCase):
    def test_valid_inventory_is_accepted(self) -> None:
        MODULE.validate(valid_inventory())

    def test_sensitive_field_is_rejected(self) -> None:
        inventory = valid_inventory()
        inventory["network"]["hostname"] = "internal.example"
        with self.assertRaises(ValueError):
            MODULE.validate(inventory)

    def test_healthy_degraded_array_is_rejected(self) -> None:
        inventory = valid_inventory()
        inventory["storage"]["arrays"][0]["active_members"] = 10
        with self.assertRaises(ValueError):
            MODULE.validate(inventory)


if __name__ == "__main__":
    unittest.main()
