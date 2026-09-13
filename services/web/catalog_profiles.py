"""Turn the 60 versioned agent profiles (configs/agents/registry.json) into
selectable chat profiles.

Fast path: each profile gets a synthesized persona (from its mission,
capabilities and guardrails) and an engine chosen by family — code families use
the local Qwen-Coder, everyone else the 14B (which also gets the read-only tool
loop).  The registry's own per-profile eval gates are intentionally not enforced
here; this is the owner's deliberate choice to make all profiles usable.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from services.orchestrator.registry import load_registry

PROFILE_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
CODE_FAMILIES = frozenset({"development"})
GUARDRAILS = (
    "Reste dans ton domaine ; si la demande en sort, dis-le et oriente vers le bon profil. "
    "Tu proposes, tu n'exécutes jamais une action à effet externe ou durable sans confirmation humaine explicite. "
    "Tu es hors ligne : ni accès Internet, ni shell ; tu ne peux pas exécuter de code ni modifier de fichiers."
)


def engine_for_family(family: str) -> str:
    return "QWEN-CODER" if family in CODE_FAMILIES else "BOOTSTRAP"


def _system_prompt(profile: dict[str, Any]) -> str:
    name = str(profile.get("display_name") or profile.get("id") or "profil")
    mission = str(profile.get("mission") or "").strip()
    capabilities = [str(c) for c in profile.get("capabilities", []) if isinstance(c, str)][:12]
    parts = [f"Tu es « {name} », un profil spécialisé de l'assistant local Sovereign."]
    if mission:
        parts.append(f"Mission : {mission}.")
    if capabilities:
        parts.append("Capacités : " + ", ".join(capabilities)[:400] + ".")
    parts.append(GUARDRAILS)
    return " ".join(parts)


def load_catalog_profiles(path: Path) -> list[dict[str, Any]]:
    """Load the registry and return chat-ready profiles (excluding the builtin coordination)."""
    try:
        registry = load_registry(Path(path))
    except (OSError, ValueError):
        return []
    profiles: list[dict[str, Any]] = []
    for profile in registry.get("profiles", []):
        identifier = profile.get("id")
        if not isinstance(identifier, str) or PROFILE_ID.fullmatch(identifier) is None:
            continue
        if identifier == "coordination":  # keep the dedicated builtin profile
            continue
        family = str(profile.get("family") or "")
        engine = engine_for_family(family)
        profiles.append({
            "profile_id": identifier,
            "display_name": str(profile.get("display_name") or identifier)[:80],
            "family": family,
            "mission": str(profile.get("mission") or "")[:300],
            "engine": engine,
            "system_prompt": _system_prompt(profile),
            "tools": engine == "BOOTSTRAP",
        })
    return profiles
