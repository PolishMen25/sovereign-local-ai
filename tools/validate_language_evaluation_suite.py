"""Validate a content-free candidate suite for owner-reviewed CORE language evaluation.

The suite targets one supported CORE candidate and stays balanced: every
(language, category) cell holds the same number of prompts, numbered from 01.

Fail-closed by default: without arguments, ``validate`` accepts only the
CORE-30M suite of 50 prompts (5 per cell), the one the E1 runner and the V1
grid expect.  Another balanced size is accepted only when the caller pins it
explicitly (``prompt_count=``, ``--prompt-count``).  CORE-30M is the only
supported target: D-034 superseded CORE-700M (D-026), and adding an E1 target
requires an owner decision.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


SUITE_SCHEMA = "core-language-evaluation-suite.v1"
STATUS = "candidate_owner_review_required"
# Adding a target takes an owner decision (D-034 superseded CORE-700M, D-026).
SUPPORTED_MODELS = ("CORE-30M",)
DEFAULT_MODEL = "CORE-30M"
DEFAULT_PROMPT_COUNT = 50
LANGUAGES = ("fr", "en")
CATEGORIES = ("general", "explanation", "programming", "systems", "networking")
PROMPTS_PER_CELL_RANGE = (1, 99)
IDENTIFIER = re.compile(r"^(?:fr|en)-(?:general|explanation|programming|systems|networking)-([0-9]{2})$")
TOP_LEVEL = {"schema_version", "status", "model_name", "evaluation_mode", "languages", "categories", "prompts"}


def validate(document: Any, *, model_name: str = DEFAULT_MODEL, prompt_count: int = DEFAULT_PROMPT_COUNT) -> None:
    if not isinstance(document, dict) or set(document) != TOP_LEVEL:
        raise ValueError("evaluation suite keys are invalid")
    if document["schema_version"] != SUITE_SCHEMA or document["status"] != STATUS:
        raise ValueError("evaluation suite contract is invalid")
    if document["model_name"] not in SUPPORTED_MODELS or document["evaluation_mode"] != "owner_blind_review":
        raise ValueError("evaluation suite target is invalid")
    if document["model_name"] != model_name:
        raise ValueError("evaluation suite target does not match the expected model")
    if document["languages"] != list(LANGUAGES) or document["categories"] != list(CATEGORIES):
        raise ValueError("evaluation suite dimensions are invalid")
    prompts = document["prompts"]
    cells = len(LANGUAGES) * len(CATEGORIES)
    if not isinstance(prompts, list) or len(prompts) % cells != 0:
        raise ValueError(f"evaluation suite prompt count must be a multiple of {cells}")
    per_cell = len(prompts) // cells
    if not PROMPTS_PER_CELL_RANGE[0] <= per_cell <= PROMPTS_PER_CELL_RANGE[1]:
        raise ValueError("evaluation suite prompt count is outside the bounded range")
    if len(prompts) != prompt_count:
        raise ValueError("evaluation suite prompt count does not match the expected count")
    identifiers: set[str] = set()
    dimensions: dict[tuple[str, str], int] = {(language, category): 0 for language in LANGUAGES for category in CATEGORIES}
    for prompt in prompts:
        if not isinstance(prompt, dict) or set(prompt) != {"id", "language", "category", "prompt"}:
            raise ValueError("evaluation prompt shape is invalid")
        identifier, language, category, text = prompt["id"], prompt["language"], prompt["category"], prompt["prompt"]
        match = IDENTIFIER.fullmatch(identifier) if isinstance(identifier, str) else None
        if match is None or not 1 <= int(match.group(1)) <= per_cell or identifier in identifiers:
            raise ValueError("evaluation prompt id is invalid")
        if not isinstance(language, str) or language not in LANGUAGES or not isinstance(category, str) or category not in CATEGORIES:
            raise ValueError("evaluation prompt dimension is invalid")
        if not isinstance(text, str) or not 12 <= len(text) <= 500 or text != text.strip():
            raise ValueError("evaluation prompt text is invalid")
        expected_prefix = f"{language}-{category}-"
        if not identifier.startswith(expected_prefix):
            raise ValueError("evaluation prompt id does not match its dimensions")
        identifiers.add(identifier)
        dimensions[(language, category)] += 1
    if any(count != per_cell for count in dimensions.values()):
        raise ValueError("evaluation suite must be balanced by language and category")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("suite", type=Path, help="candidate language evaluation suite JSON")
    parser.add_argument("--model", choices=SUPPORTED_MODELS, default=DEFAULT_MODEL,
                        help=f"refuse a suite that targets another model (default {DEFAULT_MODEL})")
    parser.add_argument("--prompt-count", type=int, default=DEFAULT_PROMPT_COUNT,
                        help=f"refuse a suite with another number of prompts (default {DEFAULT_PROMPT_COUNT})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate(json.loads(args.suite.read_text(encoding="utf-8")), model_name=args.model, prompt_count=args.prompt_count)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"invalid language evaluation suite: {error}", file=sys.stderr)
        return 1
    print("valid candidate language evaluation suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
