#!/usr/bin/env python3
"""Derive a distinct 4096-token CORE-MINI manifest from approved text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.validate_training_corpus_manifest import validate


CORE_MINI_VOCABULARY_SIZE = 4096


def canonical_json(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def derive(source: dict[str, Any], *, corpus_id: str) -> dict[str, Any]:
    validate(source, require_training_authorization=True)
    derived = dict(source)
    derived["corpus_id"] = corpus_id
    derived["tokenizer_contract"] = {
        **source["tokenizer_contract"],
        "candidate_vocabulary_size": CORE_MINI_VOCABULARY_SIZE,
    }
    validate(derived, require_training_authorization=True)
    return derived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--corpus-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.output_manifest.exists():
            raise ValueError("derived manifest output already exists")
        document = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("source manifest must be a JSON object")
        derived = derive(document, corpus_id=args.corpus_id)
        args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
        with args.output_manifest.open("xb") as output:
            output.write(canonical_json(derived))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"CORE-MINI manifest derivation refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"corpus_id": derived["corpus_id"], "vocabulary_size": CORE_MINI_VOCABULARY_SIZE}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
