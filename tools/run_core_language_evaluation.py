#!/usr/bin/env python3
"""Produce a bounded, reproducible, owner-reviewable CORE-30M E1 result package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.runtime import InferenceUnavailable, LocalInferenceRuntime
from tools.validate_language_evaluation_suite import validate as validate_suite


RESULTS_NAME = "responses.jsonl"
REVIEW_NAME = "owner-review-template.json"
RECEIPT_NAME = "receipt.json"
RECEIPT_SCHEMA = "core-language-evaluation-receipt.v1"
REVIEW_SCHEMA = "core-language-evaluation-owner-review.v1"


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidate_suite(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("evaluation suite is unavailable or invalid") from error
    validate_suite(document)
    return document


def require_regular_files(paths: tuple[Path, ...]) -> None:
    if any(not path.is_file() for path in paths):
        raise ValueError("evaluation contract artifact is unavailable")


def write_package(
    *, output_dir: Path, suite: dict[str, Any], results: list[dict[str, Any]], receipt: dict[str, Any]
) -> dict[str, Any]:
    if output_dir.exists():
        raise ValueError("evaluation output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".core-language-evaluation-", dir=output_dir.parent))
    try:
        result_payload = b"".join(canonical_json(item) for item in results)
        (temporary / RESULTS_NAME).write_bytes(result_payload)
        result_sha256 = hashlib.sha256(result_payload).hexdigest()
        review = {
            "schema_version": REVIEW_SCHEMA,
            "status": "owner_review_pending",
            "evaluation_result_sha256": result_sha256,
            "response_count": len(results),
            "decisions": [
                {"id": item["id"], "decision": None, "reason": ""} for item in results
            ],
        }
        receipt = dict(receipt)
        receipt["responses_sha256"] = result_sha256
        receipt["response_count"] = len(results)
        receipt["suite_sha256"] = hashlib.sha256(canonical_json(suite)).hexdigest()
        (temporary / REVIEW_NAME).write_bytes(canonical_json(review))
        (temporary / RECEIPT_NAME).write_bytes(canonical_json(receipt))
        os.replace(temporary, output_dir)
        return receipt
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def run_evaluation(
    *, suite_path: Path, checkpoint_path: Path, config_path: Path, tokenizer_path: Path,
    manifest_path: Path, preflight_path: Path, output_dir: Path, seed: int, max_new_tokens: int
) -> dict[str, Any]:
    if not 1 <= max_new_tokens <= 64 or type(seed) is not int:
        raise ValueError("evaluation generation limits are invalid")
    if output_dir.exists():
        raise ValueError("evaluation output directory already exists")
    require_regular_files((suite_path, checkpoint_path, config_path, tokenizer_path, manifest_path, preflight_path))
    suite = load_candidate_suite(suite_path)
    runtime = LocalInferenceRuntime(
        suite["model_name"], checkpoint_path, config_path=config_path,
        tokenizer_path=tokenizer_path, manifest_path=manifest_path,
        preflight_path=preflight_path,
    )
    if not runtime.status().generation_available:
        raise InferenceUnavailable("evaluation checkpoint contract was refused")
    results: list[dict[str, Any]] = []
    for prompt in suite["prompts"]:
        generated = runtime.generate(prompt["prompt"], max_new_tokens=max_new_tokens, seed=seed)
        answer = generated.get("answer")
        if not isinstance(answer, str):
            raise InferenceUnavailable("evaluation generation response is invalid")
        results.append({
            "id": prompt["id"], "language": prompt["language"], "category": prompt["category"],
            "prompt": prompt["prompt"], "answer": answer, "engine": generated.get("engine"),
            "experimental": generated.get("experimental"), "seed": seed,
            "max_new_tokens": max_new_tokens,
        })
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "owner_review_pending",
        "model_name": suite["model_name"],
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "model_config_sha256": sha256_file(config_path),
        "tokenizer_sha256": sha256_file(tokenizer_path),
        "manifest_sha256": sha256_file(manifest_path),
        "preflight_sha256": sha256_file(preflight_path),
        "seed": seed,
        "max_new_tokens": max_new_tokens,
    }
    return write_package(output_dir=output_dir, suite=suite, results=results, receipt=receipt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--max-new-tokens", type=int, default=64)
    args = parser.parse_args(argv)
    try:
        receipt = run_evaluation(
            suite_path=args.suite, checkpoint_path=args.checkpoint, config_path=args.config,
            tokenizer_path=args.tokenizer, manifest_path=args.manifest,
            preflight_path=args.preflight, output_dir=args.output_dir, seed=args.seed,
            max_new_tokens=args.max_new_tokens,
        )
    except (OSError, ValueError, InferenceUnavailable) as error:
        print(f"CORE language evaluation refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": receipt["status"], "response_count": receipt["response_count"], "responses_sha256": receipt["responses_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
