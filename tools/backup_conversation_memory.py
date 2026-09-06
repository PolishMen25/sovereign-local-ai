"""Operator-only backup, verification and restore for private conversation memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.memory.durable_backup import create_backup, restore_backup, verify_backup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    backup = actions.add_parser("backup")
    backup.add_argument("--source", type=Path, required=True)
    backup.add_argument("--destination-directory", type=Path, required=True)
    verify = actions.add_parser("verify")
    verify.add_argument("--artifact", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    restore = actions.add_parser("restore")
    restore.add_argument("--artifact", type=Path, required=True)
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.action == "backup":
        result = create_backup(args.source, args.destination_directory)
    elif args.action == "verify":
        result = verify_backup(args.artifact, args.manifest)
    else:
        result = restore_backup(args.artifact, args.manifest, args.destination)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
