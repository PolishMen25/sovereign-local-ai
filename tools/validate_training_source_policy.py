"""Validate the content-free candidate policy used before corpus acquisition."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any


POLICY_ID = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
TOP_LEVEL = {
    "schema_version", "policy_id", "status", "target_languages", "priority_domains",
    "allowed_licenses", "excluded_content", "review_requirements",
    "catalog_status", "purpose", "acquisition_guard", "sources",
    "estimated_total_tokens", "rejected_sources",
}
ALLOWED_LICENSES = {"0BSD", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "CC-BY-4.0", "ISC", "MIT", "Unlicense"}
DOMAINS = {"software-development", "systems-administration", "networking"}
EXCLUSIONS = {"credentials", "personal-data", "private-conversations", "proprietary-content", "unknown-license"}
REVIEW_REQUIREMENTS = {"license-verified", "provenance-verified", "content-sha256", "human-approval"}


def _require_exact_list(value: Any, allowed: set[str], label: str) -> None:
    if not isinstance(value, list) or not value or len(value) != len(set(value)):
        raise ValueError(f"{label} must be a non-empty unique list")
    if any(not isinstance(item, str) or item not in allowed for item in value):
        raise ValueError(f"{label} contains an unsupported value")


def validate(document: Any) -> None:
    if not isinstance(document, dict) or set(document) != TOP_LEVEL:
        raise ValueError("policy keys are invalid")
    if document["schema_version"] != "training-source-policy.v1":
        raise ValueError("unsupported policy schema")
    if not isinstance(document["policy_id"], str) or POLICY_ID.fullmatch(document["policy_id"]) is None:
        raise ValueError("policy id is invalid")
    if document["status"] != "candidate":
        raise ValueError("a source policy must remain candidate until owner approval")
    if document["catalog_status"] != "candidate_requires_owner_approval":
        raise ValueError("catalog status must require owner approval")
    if not isinstance(document["purpose"], str) or not document["purpose"].strip():
        raise ValueError("purpose is invalid")
    _require_exact_list(document["target_languages"], {"fr", "en"}, "target languages")
    _require_exact_list(document["priority_domains"], DOMAINS, "priority domains")
    _require_exact_list(document["allowed_licenses"], ALLOWED_LICENSES, "allowed licenses")
    _require_exact_list(document["excluded_content"], EXCLUSIONS, "excluded content")
    _require_exact_list(document["review_requirements"], REVIEW_REQUIREMENTS, "review requirements")
    required = {"credentials", "personal-data", "private-conversations", "proprietary-content", "unknown-license"}
    if not required.issubset(document["excluded_content"]):
        raise ValueError("all protected content classes must be excluded")
    if not REVIEW_REQUIREMENTS.issubset(document["review_requirements"]):
        raise ValueError("all source review requirements are mandatory")
    guard = document["acquisition_guard"]
    if not isinstance(guard, dict) or set(guard) != {
        "raw_to_validated_promotion", "corpus_bytes_acquired", "allowed_licenses"
    }:
        raise ValueError("acquisition guard keys are invalid")
    if guard["raw_to_validated_promotion"] != "manual_owner_approval_only":
        raise ValueError("raw promotion must require owner approval")
    if not isinstance(guard["corpus_bytes_acquired"], bool):
        raise ValueError("acquisition state is invalid")
    _require_exact_list(guard["allowed_licenses"], ALLOWED_LICENSES | {"verified-public-domain"}, "acquisition licenses")
    if not isinstance(document["sources"], list) or len(document["sources"]) != 10:
        raise ValueError("candidate catalog must contain exactly ten sources")
    if not isinstance(document["rejected_sources"], list):
        raise ValueError("rejected sources are invalid")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_training_source_policy.py POLICY.json", file=sys.stderr)
        return 2
    try:
        validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"invalid training source policy: {error}", file=sys.stderr)
        return 1
    print("valid candidate training source policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
