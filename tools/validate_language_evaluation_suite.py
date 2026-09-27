"""Validate a content-free candidate suite for owner-reviewed CORE language evaluation.

The suite targets one supported CORE candidate and stays balanced: every
(language, category) cell holds the same number of prompts, numbered from 01.
The historical CORE-30M suite holds 50 prompts (5 per cell); a CORE-700M or
larger suite keeps the same contract with another per-cell count.  Callers may
pin the expected model and prompt count so a suite cannot silently change
target or size.
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
SUPPORTED_MODELS = ("CORE-30M", "CORE-700M")
LANGUAGES = ("fr", "en")
CATEGORIES = ("general", "explanation", "programming", "systems", "networking")
PROMPTS_PER_CELL_RANGE = (1, 99)
IDENTIFIER = re.compile(r"^(?:fr|en)-(?:general|explanation|programming|systems|networking)-([0-9]{2})$")
TOP_LEVEL = {"schema_version", "status", "model_name", "evaluation_mode", "languages", "categories", "prompts"}


def validate(document: Any, *, model_name: str | None = None, prompt_count: int | None = None) -> None:
    if not isinstance(document, dict) or set(document) != TOP_LEVEL:
        raise ValueError("evaluation suite keys are invalid")
    if document["schema_version"] != SUITE_SCHEMA or document["status"] != STATUS:
        raise ValueError("evaluation suite contract is invalid")
    if document["model_name"] not in SUPPORTED_MODELS or document["evaluation_mode"] != "owner_blind_review":
        raise ValueError("evaluation suite target is invalid")
    if model_name is not None and document["model_name"] != model_name:
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
    if prompt_count is not None and len(prompts) != prompt_count:
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
    parser.add_argument("--model", choices=SUPPORTED_MODELS, help="refuse a suite that targets another model")
    parser.add_argument("--prompt-count", type=int, help="refuse a suite with another number of prompts")
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
