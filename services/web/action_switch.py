"""D-035 — the explicit switch in front of the chat's action tools.

The chat *actions* are the tools with a side effect, listed in
``agent_tools.ACTION_TOOL_SPECS``: ``run_python`` (executes code in the offline
sandbox) and ``write_file`` (writes into the gateway workspace).  The read-only
tools (knowledge search, document listing/reading, time, workspace listing) are
not actions and are not governed by this switch.

The actions stay DISABLED unless the operator sets exactly
``SOVEREIGN_ACTIONS_ENABLED=1`` in the gateway environment.  The value is read
once, at startup, into a frozen ``ActionSwitch``; nothing changes it while the
service runs.  Parsing is strict and fail-closed:

- absent, empty or ``"0"``: disabled (the documented default, no warning);
- exactly ``"1"``: enabled;
- anything else (``"true"``, ``"yes"``, ``" 1"``, ``"1\\n"``…): disabled, with a
  warning in the service journal that never echoes the rejected value.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable, Mapping

ENVIRONMENT_VARIABLE = "SOVEREIGN_ACTIONS_ENABLED"
ENABLED_VALUE = "1"
SILENT_DISABLED_VALUES = frozenset({"", "0"})


@dataclass(frozen=True)
class ActionSwitch:
    """Immutable startup configuration of the chat actions (disabled by default)."""

    enabled: bool = False


DISABLED = ActionSwitch(enabled=False)
ENABLED = ActionSwitch(enabled=True)


def _journal(message: str) -> None:
    print(message, flush=True)


def parse(raw: str | None, *, log: Callable[[str], None] = _journal) -> ActionSwitch:
    """Turn the raw environment value into a switch; only ``"1"`` enables."""

    if raw == ENABLED_VALUE:
        return ENABLED
    if raw is not None and raw not in SILENT_DISABLED_VALUES:
        log(f"web warning {ENVIRONMENT_VARIABLE} has an unrecognized value; "
            "chat actions stay disabled (only the exact value 1 enables them)")
    return DISABLED


def from_environment(environ: Mapping[str, str] | None = None, *, log: Callable[[str], None] = _journal) -> ActionSwitch:
    """Read the switch once and journal the effective state (content-free)."""

    source = os.environ if environ is None else environ
    switch = parse(source.get(ENVIRONMENT_VARIABLE), log=log)
    log(f"web config actions_enabled={'1' if switch.enabled else '0'}")
    return switch
