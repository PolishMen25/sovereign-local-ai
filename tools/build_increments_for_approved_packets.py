#!/usr/bin/env python3
"""Convert every owner-approved arena packet into a corpus increment, in one pass.

Approval stays exactly where it was: per packet, human, written by the gateway
as ``approval.json`` when the owner clicks. This tool never approves anything —
it only converts what the owner already approved, skips what is already built,
and says why it skipped the rest. That turns a stock of packets into corpus
without clicking through the same conversion forty times.

  # see the stock without writing anything
  python3 -m tools.build_increments_for_approved_packets --dry-run
  # convert every approved packet not yet built
  python3 -m tools.build_increments_for_approved_packets
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from services.knowledge import corpus_paths
from tools import build_core_increment_from_arena as builder

DEFAULT_PACKETS = Path("/var/lib/sovereign-arena/packets")
DEFAULT_SUITE = Path("/var/lib/sovereign-arena/practice-suite.v1.json")


def packet_report(packet_dir: Path, raw_root: Path) -> dict[str, Any]:
    """Describe one packet: its health, whether it is approved and already built."""
    report: dict[str, Any] = {"packet_id": packet_dir.name, "approved": (packet_dir / "approval.json").is_file()}
    try:
        manifest = json.loads((packet_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report.update({"status": "sans manifeste", "built": False})
        return report
    metrics = manifest.get("metrics") or {}
    report["status"] = manifest.get("status", "?")
    report["solutions"] = manifest.get("solutions")
    report["unique_ratio"] = metrics.get("unique_ratio", manifest.get("unique_ratio"))
    report["max_repetition"] = metrics.get("max_repetition", manifest.get("max_repetition"))
    packet_id = manifest.get("packet_id", packet_dir.name)
    report["built"] = (raw_root / f"arena-{packet_id}").is_dir()
    return report


def run(packets_dir: Path, suite: Path, raw_root: Path, *, dry_run: bool) -> dict[str, Any]:
    if not packets_dir.is_dir():
        raise SystemExit(f"dossier de paquets introuvable : {packets_dir}")
    if not dry_run:
        corpus_paths.require_share(raw_root)
    outcome = {"built": [], "already": [], "not_approved": [], "refused": [], "to_build": []}
    for packet_dir in sorted(packets_dir.iterdir()):
        if not packet_dir.is_dir():
            continue
        report = packet_report(packet_dir, raw_root)
        line = (f"{report['packet_id']:<34} {str(report.get('status','?')):<24} "
                f"unique={report.get('unique_ratio')} rep={report.get('max_repetition')} "
                f"{'approuvé' if report['approved'] else 'non approuvé':<13} {'déjà bâti' if report['built'] else ''}")
        print(" ", line.rstrip())
        if report["built"]:
            outcome["already"].append(report["packet_id"])
            continue
        if not report["approved"]:
            outcome["not_approved"].append(report["packet_id"])
            continue
        if dry_run:
            outcome["to_build"].append(report["packet_id"])
            continue
        try:
            increment = builder.build(packet_dir, suite, raw_root)
        except (builder.IncrementRefused, OSError, json.JSONDecodeError) as failure:
            outcome["refused"].append({"packet_id": report["packet_id"], "reason": str(failure)})
            print(f"    refusé : {failure}")
            continue
        outcome["built"].append(increment["increment_id"])
        print(f"    → incrément {increment['increment_id']} ({increment.get('record_count')} records)")
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packets-dir", type=Path, default=DEFAULT_PACKETS)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--raw-root", type=Path, default=corpus_paths.raw_arena_root())
    parser.add_argument("--dry-run", action="store_true", help="n'écrit rien, montre seulement l'état du stock")
    args = parser.parse_args(argv)

    print(f"paquets : {args.packets_dir}\nsuite   : {args.suite}\nRAW     : {args.raw_root}\n")
    outcome = run(args.packets_dir, args.suite, args.raw_root, dry_run=args.dry_run)
    lines = ["", "résumé :", f"  incréments créés         : {len(outcome['built'])}"]
    if outcome["to_build"]:
        lines.append(f"  approuvés à convertir    : {len(outcome['to_build'])}  (relance sans --dry-run)")
    lines.append(f"  déjà bâtis               : {len(outcome['already'])}")
    lines.append(f"  en attente d'approbation : {len(outcome['not_approved'])}")
    lines.append(f"  refusés                  : {len(outcome['refused'])}")
    print("\n".join(lines))
    if outcome["not_approved"]:
        print("  → approuve-les dans l'arène, puis relance cet outil.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
