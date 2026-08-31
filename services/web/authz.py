"""Minimal, data-only authorization policy for the future local UI."""

from __future__ import annotations

from typing import Any


def allowed(policy: dict[str, Any], role: str, capability: str) -> bool:
    roles = policy.get("roles")
    if not isinstance(roles, dict) or role not in roles:
        return False
    capabilities = roles[role].get("capabilities", [])
    return isinstance(capabilities, list) and capability in capabilities
