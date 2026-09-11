"""One-screen arena summary for a terminal: ``python3 -B -m services.arena.status``.

Read-only; meant for ``watch -n 10`` from the Proxmox host.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

from services.arena.store import ArenaStore


def render(overview: dict, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    state, totals = overview.get("state", {}), overview.get("totals", {})
    heartbeat = state.get("heartbeat")
    age = "?"
    if heartbeat:
        seconds = int((now - datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))).total_seconds())
        age = f"{seconds} s"
    lines = [
        f"arène : {state.get('status', '?')} ({state.get('reason', '?')}) · dernier signe de vie il y a {age}",
        f"matchs : {totals.get('matches', 0)} (dernière heure : {totals.get('matches_last_hour', 0)}) · "
        f"solutions validées : {totals.get('accepted', 0)} · tâches résolues : {totals.get('tasks_solved', 0)}",
        "",
        f"{'#':>2}  {'auteur':<32} {'moteur':<11} {'Elo':>5} {'matchs':>6} {'1er coup':>8}",
    ]
    authors = [p for p in overview.get("profiles", []) if p["role"] == "author" and p["status"] == "active"]
    for rank, profile in enumerate(sorted(authors, key=lambda p: -p["rating"]), start=1):
        first = f"{round(100 * profile['first_pass'] / profile['matches'])} %" if profile["matches"] else "-"
        lines.append(f"{rank:>2}  {profile['display_name'][:32]:<32} {profile['engine']:<11} {round(profile['rating']):>5} "
                     f"{profile['matches']:>6} {first:>8}")
    packets = overview.get("packets", [])
    if packets:
        lines += ["", "paquets : " + " · ".join(f"{p['packet_id']} {p['status']}" for p in packets[:3])]
    return "\n".join(lines)


def main() -> int:
    database = Path(os.environ.get("SOVEREIGN_ARENA_DB", "/var/lib/sovereign-arena/arena.sqlite3"))
    try:
        print(render(ArenaStore(database, read_only=True).overview()))
    except FileNotFoundError:
        print("arène : base absente (service jamais démarré ?)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
