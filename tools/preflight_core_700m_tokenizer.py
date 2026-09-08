#!/usr/bin/env python3
"""Verify a candidate-core tokenizer against CORE-700M without allocation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.configuration import load_core_candidate_configuration
from tools.authorized_text_bundle import load_authorized_text_bundle
from tools.verify_corpus_approval import verify_corpus_approval


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "models" / "core-700m.candidate.json"


def preflight(
    *, config_path: Path, manifest_path: Path, train_jsonl_path: Path, tokenizer_path: Path
) -> dict[str, Any]:
    """Bind one 32k candidate_core artifact to the unallocated CORE config."""

    verify_corpus_approval()
    document, config, config_sha256 = load_core_candidate_configuration(config_path)
    if document["name"] != "CORE-700M":
        raise ValueError("CORE-700M tokenizer preflight requires the CORE-700M configuration")
    bundle = load_authorized_text_bundle(
        manifest_path=manifest_path,
        train_jsonl_path=train_jsonl_path,
        tokenizer_path=tokenizer_path,
    )
    if bundle.tokenizer_status != "candidate_core":
        raise ValueError("CORE-700M tokenizer preflight requires candidate_core status")
    if bundle.tokenizer_vocabulary_size != config.vocabulary_size:
        raise ValueError("candidate_core tokenizer vocabulary does not match CORE-700M")
    return {
        "schema_version": "core-700m-tokenizer-preflight.v1",
        "model_name": document["name"],
        "model_config_sha256": config_sha256,
        "model_parameters": document["parameter_count"]["total_trainable"],
        "tokenizer_status": bundle.tokenizer_status,
        "tokenizer_sha256": bundle.tokenizer_sha256,
        "tokenizer_vocabulary_size": bundle.tokenizer_vocabulary_size,
        "corpus_id": bundle.corpus_id,
        "manifest_sha256": bundle.manifest_sha256,
        "train_split_sha256": bundle.train_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(preflight(
            config_path=args.config,
            manifest_path=args.manifest,
            train_jsonl_path=args.train_jsonl,
            tokenizer_path=args.tokenizer,
        ), sort_keys=True))
    except (OSError, ValueError) as error:
        print(f"CORE-700M tokenizer preflight refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
