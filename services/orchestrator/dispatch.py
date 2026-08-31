"""Fail-closed request preparation for the local assistant orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .registry import RegistryError, get_profile


@dataclass(frozen=True)
class PreparedRequest:
    request_id: str
    profile_id: str
    message: str
    data_scopes: tuple[str, ...]
    tool_allowlist: tuple[str, ...]


def prepare_request(registry: dict[str, Any], request: dict[str, Any]) -> PreparedRequest:
    """Validate and bind a chat request to one registered profile.

    This function only prepares an envelope. It never calls a model, tool,
    network, filesystem path, or secret store.
    """

    if not isinstance(request, dict) or request.get("schema_version") != "local-chat-request.v1":
        raise ValueError("unsupported chat request schema")
    request_id = request.get("request_id")
    message = request.get("message")
    profile_id = request.get("profile_id", "coordination")
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
        raise ValueError("request_id is invalid")
    if not isinstance(message, str) or not 1 <= len(message) <= 12_000:
        raise ValueError("message is invalid")
    if not isinstance(profile_id, str):
        raise ValueError("profile_id is invalid")
    try:
        profile = get_profile(registry, profile_id)
    except RegistryError as error:
        raise ValueError("unknown profile") from error
    if profile["status"] != "enabled":
        raise ValueError("profile is not enabled")
    return PreparedRequest(
        request_id=request_id,
        profile_id=profile_id,
        message=message,
        data_scopes=tuple(profile["data_scopes"]),
        tool_allowlist=tuple(profile["tool_allowlist"]),
    )
