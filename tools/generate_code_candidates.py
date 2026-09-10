#!/usr/bin/env python3
"""Ask an offline engine to answer an evaluation suite once per task.

This tool generates; it never judges. It asks each task exactly once with an
empty history, records what came back, and stops. It deliberately offers no
retry: a score that reflects repeated attempts measures our persistence, not
the model. The agent loop is where retries belong.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CANDIDATES_SCHEMA = "core-code-evaluation-candidates.v1"
METADATA_SCHEMA = "core-code-evaluation-generation-metadata.v1"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)
EMPTY_SOURCE = "# no code produced"
INSTRUCTION = (
    "You are a Python programmer. Write only the requested function.\n"
    "Answer with a single Python code block and nothing else. "
    "No tests, no explanation, no example usage.\n\n"
)


class GenerationRefused(ValueError):
    """Raised when generation cannot meet its contract."""


def extract_source(answer: str) -> tuple[str, bool]:
    """Return the first fenced block, or the raw answer flagged as unfenced."""
    match = CODE_BLOCK.search(answer)
    if match:
        return match.group(1).strip(), False
    return answer.strip(), True


def read_api_key(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        key = path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError) as error:
        raise GenerationRefused("api key file is unreadable or empty") from error
    if not key:
        raise GenerationRefused("api key file is unreadable or empty")
    return key


def request_completion(*, endpoint: str, api_key: str | None, prompt: str,
                       max_tokens: int, temperature: float, seed: int,
                       timeout: int) -> tuple[dict[str, Any], float]:
    body = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature,
        "top_p": 1, "seed": seed,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(endpoint, data=body, headers=headers)
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            document = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise GenerationRefused(f"engine is unavailable: {error}") from error
    return document, time.time() - started


def generate(*, suite_path: Path, output_dir: Path, endpoint: str,
             api_key: str | None, model_name: str, weights_sha256: str,
             max_tokens: int, temperature: float, seed: int,
             timeout: int) -> dict[str, Any]:
    if HEX_SHA256.fullmatch(weights_sha256) is None:
        raise GenerationRefused("weights digest is invalid")
    try:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        tasks = suite["tasks"]
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise GenerationRefused("evaluation suite is unavailable or invalid") from error

    candidates: list[dict[str, str]] = []
    per_task: list[dict[str, Any]] = []
    generated = 0
    elapsed = 0.0
    for task in tasks:
        document, duration = request_completion(
            endpoint=endpoint, api_key=api_key, prompt=INSTRUCTION + task["prompt"],
            max_tokens=max_tokens, temperature=temperature, seed=seed, timeout=timeout)
        try:
            choice = document["choices"][0]
            answer = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise GenerationRefused("engine returned an invalid response") from error
        source, unfenced = extract_source(answer)
        usage = document.get("usage", {}) or {}
        generated += int(usage.get("completion_tokens") or 0)
        elapsed += duration
        candidates.append({"task_id": task["id"], "source": source or EMPTY_SOURCE})
        per_task.append({
            "task_id": task["id"],
            "duration_seconds": round(duration, 3),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "finish_reason": choice.get("finish_reason"),
            "unfenced_answer": unfenced,
            "truncated": choice.get("finish_reason") == "length",
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / "candidates.json"
    metadata_path = output_dir / "generation-metadata.json"
    for path in (candidates_path, metadata_path):
        if path.exists():
            raise GenerationRefused(f"destination already exists: {path}")

    document = {"schema_version": CANDIDATES_SCHEMA, "model_name": model_name,
                "checkpoint_sha256": weights_sha256, "candidates": candidates}
    candidates_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    metadata = {
        "schema_version": METADATA_SCHEMA,
        "endpoint": endpoint, "model_name": model_name,
        "weights_sha256": weights_sha256,
        "settings": {"max_tokens": max_tokens, "temperature": temperature,
                     "seed": seed, "attempts_per_task": 1},
        "suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "tasks": per_task,
        "totals": {"tasks": len(tasks), "completion_tokens": generated,
                   "seconds": round(elapsed, 1),
                   "tokens_per_second": round(generated / elapsed, 2) if elapsed else None,
                   "unfenced": sum(1 for t in per_task if t["unfenced_answer"]),
                   "truncated": sum(1 for t in per_task if t["truncated"])},
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return {"candidates_path": candidates_path, "metadata_path": metadata_path,
            "candidates_sha256": hashlib.sha256(candidates_path.read_bytes()).hexdigest(),
            "totals": metadata["totals"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        result = generate(
            suite_path=args.suite, output_dir=args.output_dir, endpoint=args.endpoint,
            api_key=read_api_key(args.api_key_file), model_name=args.model_name,
            weights_sha256=args.weights_sha256, max_tokens=args.max_tokens,
            temperature=args.temperature, seed=args.seed, timeout=args.timeout)
    except (OSError, GenerationRefused) as error:
        print(f"candidate generation refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"candidates_sha256": result["candidates_sha256"],
                      **result["totals"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
