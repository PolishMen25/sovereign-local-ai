#!/usr/bin/env python3
"""Apply owner-approved corpus promotions from an inbox (gated worker).

The gateway never mutates the corpus: when the owner approves an increment in
the web UI it drops a signed approval JSON into an inbox.  This worker — run by
a systemd timer — reads each approval, finds the matching RAW arena increment by
its ``increment_id``, promotes it to the validated corpus with
``promote_arena_increment``, and moves the approval to ``processed/`` labelled
``applied`` or ``refused``.  It trains nothing.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from tools import promote_arena_increment as promote


def index_raw_increments(raw_root: Path) -> dict[str, Path]:
    """Map increment_id -> directory for every readable RAW increment."""

    index: dict[str, Path] = {}
    if not raw_root.is_dir():
        return index
    for manifest_path in raw_root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        increment_id = manifest.get("increment_id")
        if isinstance(increment_id, str) and increment_id:
            index[increment_id] = manifest_path.parent
    return index


def apply_inbox(inbox: Path, raw_root: Path, validated_root: Path) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    if not inbox.is_dir():
        return outcomes
    processed = inbox / "processed"
    index = index_raw_increments(raw_root)
    for path in sorted(inbox.glob("*.json")):
        outcome, detail = "refused", ""
        try:
            approval = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            approval, detail = {}, f"unreadable approval: {error}"
        target = str(approval.get("target_id", "")) if isinstance(approval, dict) else ""
        increment_dir = index.get(target)
        if increment_dir is None:
            detail = detail or f"no RAW increment matches {target!r}"
        else:
            try:
                validated = promote.promote(increment_dir, path, validated_root)
                outcome, detail = "applied", validated["increment_id"]
            except promote.PromotionRefused as error:
                detail = str(error)
        processed.mkdir(exist_ok=True)
        shutil.move(str(path), str(processed / f"{path.stem}.{outcome}.json"))
        outcomes.append({"approval": path.name, "outcome": outcome, "detail": detail})
        print(f"{outcome}: {path.name} -> {detail}")
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox", type=Path, default=Path("/var/lib/sovereign-gateway/corpus-inbox"))
    parser.add_argument("--raw-root", type=Path, default=Path("/mnt/sovereign-ai/raw/corpus/arena"))
    parser.add_argument("--validated-root", type=Path, default=Path("/mnt/sovereign-ai/validated/corpus/arena-increments"))
    args = parser.parse_args(argv)
    outcomes = apply_inbox(args.inbox, args.raw_root, args.validated_root)
    applied = sum(1 for o in outcomes if o["outcome"] == "applied")
    print(f"done: {applied} applied, {len(outcomes) - applied} refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
