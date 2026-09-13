#!/usr/bin/env python3
"""Re-measure existing arena packets against the corrected anti-collapse gate.

The thresholds have not moved (``MIN_UNIQUE_RATIO``, ``MAX_REPETITION`` in
``services/arena/league.py``). What changed is the population they are applied
to: the gate used to measure the *raw accepted pool*, which made a packet's
health depend on how often the arena replayed the same task, and flagged
packets whose actual content was clean. It now measures the packet's own
content — the deduplicated solutions that would reach CORE.

Packets created before that fix carry the old verdict frozen in their manifest
and in the arena database, so they stay flagged forever. This tool recomputes
their health **from their own solutions.jsonl** and, with ``--apply``, writes
the corrected verdict back.

What it never does:
  * approve anything — approval stays per packet and human, in the arena UI;
  * touch a packet the owner already approved;
  * touch a packet whose solutions.jsonl no longer matches its manifest digest;
  * modify a single solution.

  python3 -m tools.recheck_packet_health              # show what would change
  python3 -m tools.recheck_packet_health --apply      # write the corrected verdict
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from services.arena import league
from services.arena.store import ArenaStore

DEFAULT_PACKETS = Path("/var/lib/sovereign-arena/packets")
DEFAULT_DATABASE = Path("/var/lib/sovereign-arena/arena.sqlite3")


class PacketUnreadable(RuntimeError):
    """The packet cannot be re-measured, so it is left exactly as it is."""


def rows_from_packet(packet_dir: Path) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Read a packet's own content back into the shape ``packet_selection`` expects."""

    try:
        manifest = json.loads((packet_dir / "manifest.json").read_text(encoding="utf-8"))
        body = (packet_dir / "solutions.jsonl").read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as failure:
        raise PacketUnreadable(str(failure)) from failure
    digest = league.sha256_text(body)
    if manifest.get("solutions_sha256") != digest:
        raise PacketUnreadable("solutions.jsonl no longer matches the manifest digest")
    rows = []
    for number, line in enumerate(body.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            source = record["source"]
            task_id = record["task_id"]
        except (json.JSONDecodeError, KeyError, TypeError) as failure:
            raise PacketUnreadable(f"line {number}: {failure}") from failure
        rows.append({"task_id": task_id,
                     "normalized_sha256": league.sha256_text(league.normalize_source(source))})
    if not rows:
        raise PacketUnreadable("no solution in solutions.jsonl")
    return rows, digest, manifest


def recheck(packet_dir: Path) -> dict[str, Any]:
    rows, digest, manifest = rows_from_packet(packet_dir)
    selection, metrics = league.packet_selection(rows)
    if len(selection) != len(rows):  # the packet was already deduplicated at creation
        raise PacketUnreadable(f"{len(rows) - len(selection)} duplicate solution(s) inside the packet")
    # The raw accepted pool is not in the packet — only the deduplicated result
    # is. Recomputing pool metrics here would always return 1.0 and claim the
    # arena was not redundant, which we do not know. Drop them rather than
    # write a comfortable lie into the manifest.
    for pool_only in ("pool_unique_ratio", "accepted"):
        metrics.pop(pool_only, None)
    metrics["pool_metrics"] = "unavailable: recomputed from the packed packet, not from the accepted pool"
    old = manifest.get("metrics") or {}
    return {
        "packet_id": manifest.get("packet_id", packet_dir.name),
        "path": packet_dir, "manifest": manifest, "solutions_sha256": digest,
        "solutions": len(selection), "metrics": metrics, "status": league.packet_status(metrics),
        "old_status": manifest.get("status", "?"),
        "old_unique_ratio": old.get("unique_ratio", manifest.get("unique_ratio")),
    }


def write_back(report: dict[str, Any], store: ArenaStore | None) -> str:
    """Write the corrected verdict to the manifest, then to the database."""

    manifest = dict(report["manifest"])
    manifest["metrics"] = report["metrics"]
    manifest["status"] = report["status"]
    manifest["gate"] = "measured on the packet's own deduplicated content (corrected 2026-09)"
    (report["path"] / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if store is None:
        return "manifeste"
    stored = store.restate_packet(report["packet_id"], report["solutions_sha256"], report["metrics"], report["status"])
    return "manifeste + base" if stored else "manifeste (base : refusé — déjà approuvé ou digest différent)"


def run(packets_dir: Path, database: Path | None, *, apply: bool) -> dict[str, Any]:
    if not packets_dir.is_dir():
        raise SystemExit(f"dossier de paquets introuvable : {packets_dir}")
    store = None
    if apply and database is not None and database.is_file():
        store = ArenaStore(database)
    outcome: dict[str, Any] = {"unblocked": [], "unchanged": [], "still_flagged": [], "skipped": []}
    for packet_dir in sorted(packets_dir.iterdir()):
        if not packet_dir.is_dir():
            continue
        try:
            report = recheck(packet_dir)
        except PacketUnreadable as failure:
            outcome["skipped"].append({"packet_id": packet_dir.name, "reason": str(failure)})
            print(f"  {packet_dir.name:<34} ignoré : {failure}")
            continue
        changed = report["status"] != report["old_status"]
        if report["old_status"] == "approved":
            outcome["unchanged"].append(report["packet_id"])
            print(f"  {report['packet_id']:<34} déjà approuvé — laissé intact")
            continue
        verdict = f"{report['old_status']} → {report['status']}" if changed else report["status"]
        written = write_back(report, store) if apply and changed else ("—" if not changed else "simulation")
        print(f"  {report['packet_id']:<34} {report['solutions']:>4} sol.  "
              f"unique {report['old_unique_ratio']} → {report['metrics']['unique_ratio']}  "
              f"rep {report['metrics']['max_repetition']}  "
              f"tâches {report['metrics']['distinct_tasks']} "
              f"(max {report['metrics']['max_task_share']})  {verdict}  [{written}]")
        if report["status"] == "flagged":
            outcome["still_flagged"].append(report["packet_id"])
        elif changed:
            outcome["unblocked"].append(report["packet_id"])
        else:
            outcome["unchanged"].append(report["packet_id"])
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packets-dir", type=Path, default=DEFAULT_PACKETS)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--apply", action="store_true", help="écrit le verdict corrigé (sinon : simulation)")
    args = parser.parse_args(argv)

    print(f"paquets : {args.packets_dir}\nbase    : {args.database}\n"
          f"mode    : {'écriture' if args.apply else 'simulation (rien n’est écrit)'}\n")
    outcome = run(args.packets_dir, args.database, apply=args.apply)
    print("\nrésumé :")
    print(f"  débloqués (flagged → à approuver) : {len(outcome['unblocked'])}")
    print(f"  toujours signalés                 : {len(outcome['still_flagged'])}")
    print(f"  inchangés                         : {len(outcome['unchanged'])}")
    print(f"  ignorés                           : {len(outcome['skipped'])}")
    if outcome["unblocked"]:
        print("  → ils attendent maintenant TON approbation dans l’arène. Rien n’est approuvé ici.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
