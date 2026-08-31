"""Strict loader for the logical-agent registry.

This module is intentionally policy-only: it does not load a model, execute a
tool, open a socket, or enable a profile. Activation belongs to a later ADR.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FORBIDDEN_CAPABILITIES = frozenset(
    {"shell", "filesystem.read_arbitrary", "filesystem.write_arbitrary", "network.arbitrary", "secrets.read"}
)


class RegistryError(ValueError):
    """Raised when a registry is malformed or violates a safety invariant."""


def load_registry(path: Path) -> dict[str, Any]:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryError("agent registry is unavailable or invalid JSON") from error
    if not isinstance(registry, dict) or registry.get("schema_version") != "agent-profile-registry.v1":
        raise RegistryError("unsupported agent registry schema")
    profiles = registry.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise RegistryError("agent registry must contain profiles")
    identifiers: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise RegistryError("agent profile must be an object")
        identifier = profile.get("id")
        if not isinstance(identifier, str) or identifier in identifiers:
            raise RegistryError("agent profile identifiers must be unique strings")
        identifiers.add(identifier)
        if profile.get("status") not in {"draft", "enabled", "disabled", "retired"}:
            raise RegistryError(f"invalid status for profile {identifier}")
        if profile.get("action_policy") != "proposal_only":
            raise RegistryError(f"profile {identifier} is not proposal-only")
        if profile.get("memory_policy", {}).get("writes") is not False:
            raise RegistryError(f"profile {identifier} may not write memory")
        capabilities = set(profile.get("capabilities", []))
        tools = set(profile.get("tool_allowlist", []))
        if FORBIDDEN_CAPABILITIES & (capabilities | tools):
            raise RegistryError(f"profile {identifier} requests a forbidden capability")
    return registry


def get_profile(registry: dict[str, Any], identifier: str) -> dict[str, Any]:
    """Return a profile or fail closed when it is unknown."""

    for profile in registry["profiles"]:
        if profile["id"] == identifier:
            return profile
    raise RegistryError("unknown agent profile")
