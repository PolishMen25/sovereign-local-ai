"""Validate a content-free candidate suite for owner-reviewed CORE language evaluation."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any


SUITE_SCHEMA = "core-language-evaluation-suite.v1"
STATUS = "candidate_owner_review_required"
LANGUAGES = ("fr", "en")
CATEGORIES = ("general", "explanation", "programming", "systems", "networking")
IDENTIFIER = re.compile(r"^(?:fr|en)-(?:general|explanation|programming|systems|networking)-0[1-5]$")
TOP_LEVEL = {"schema_version", "status", "model_name", "evaluation_mode", "languages", "categories", "prompts"}


def validate(document: Any) -> None:
    if not isinstance(document, dict) or set(document) != TOP_LEVEL:
        raise ValueError("evaluation suite keys are invalid")
    if document["schema_version"] != SUITE_SCHEMA or document["status"] != STATUS:
        raise ValueError("evaluation suite contract is invalid")
    if document["model_name"] != "CORE-30M" or document["evaluation_mode"] != "owner_blind_review":
        raise ValueError("evaluation suite target is invalid")
    if document["languages"] != list(LANGUAGES) or document["categories"] != list(CATEGORIES):
        raise ValueError("evaluation suite dimensions are invalid")
    prompts = document["prompts"]
    if not isinstance(prompts, list) or len(prompts) != 50:
        raise ValueError("evaluation suite must contain exactly fifty prompts")
    identifiers: set[str] = set()
    dimensions: dict[tuple[str, str], int] = {(language, category): 0 for language in LANGUAGES for category in CATEGORIES}
    for prompt in prompts:
        if not isinstance(prompt, dict) or set(prompt) != {"id", "language", "category", "prompt"}:
            raise ValueError("evaluation prompt shape is invalid")
        identifier, language, category, text = prompt["id"], prompt["language"], prompt["category"], prompt["prompt"]
        if not isinstance(identifier, str) or IDENTIFIER.fullmatch(identifier) is None or identifier in identifiers:
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
    if any(count != 5 for count in dimensions.values()):
        raise ValueError("evaluation suite must be balanced by language and category")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_language_evaluation_suite.py SUITE.json", file=sys.stderr)
        return 2
    try:
        validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"invalid language evaluation suite: {error}", file=sys.stderr)
        return 1
    print("valid candidate language evaluation suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
