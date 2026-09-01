"""Validate the strict, content-free manifest for an offline training corpus."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any


SHA256 = re.compile(r"^[a-f0-9]{64}$")
PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CORPUS_ID = re.compile(r"^corpus-[a-z0-9][a-z0-9-]{2,62}$")
LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
POLICY_ID = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")

TOP_LEVEL = {
    "schema_version", "corpus_id", "lifecycle_state", "classification", "materialization",
    "source_packages", "splits", "tokenizer_contract", "approvals",
}
SENSITIVE_KEY_FRAGMENTS = ("password", "secret", "credential", "private_key", "path", "hostname", "address", "ip")
SENSITIVE_TOKEN_FIELD = re.compile(r"(?:^|[_-])token(?:$|[_-])")


def fail(message: str) -> None:
    raise ValueError(message)


def exact_keys(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"{context}: keys must be exactly {sorted(keys)}")
    return value


def require_sha256(value: Any, context: str) -> None:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        fail(f"{context} must be a lowercase SHA-256")


def ensure_no_sensitive_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = key.lower()
            if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS) or SENSITIVE_TOKEN_FIELD.search(lowered):
                fail(f"forbidden sensitive field: {key}")
            ensure_no_sensitive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            ensure_no_sensitive_keys(nested)


def validate(document: Any, *, require_training_authorization: bool = False) -> None:
    """Validate structure and invariants; it never validates the corpus bytes themselves."""
    ensure_no_sensitive_keys(document)
    doc = exact_keys(document, TOP_LEVEL, "manifest")
    if doc["schema_version"] != "0.1.0":
        fail("unsupported schema_version")
    if not isinstance(doc["corpus_id"], str) or not CORPUS_ID.fullmatch(doc["corpus_id"]):
        fail("invalid corpus_id")
    if doc["lifecycle_state"] != "VALIDATED":
        fail("only VALIDATED source material can be declared")
    if doc["classification"] not in {"synthetic", "approved_training"}:
        fail("invalid classification")

    materialization = exact_keys(doc["materialization"], {"format", "content_sha256", "byte_size", "record_count"}, "materialization")
    if materialization["format"] != "jsonl-utf8":
        fail("unsupported materialization format")
    require_sha256(materialization["content_sha256"], "materialization.content_sha256")
    if not all(isinstance(materialization[field], int) and materialization[field] > 0 for field in ("byte_size", "record_count")):
        fail("materialization sizes must be positive integers")

    packages = doc["source_packages"]
    if not isinstance(packages, list) or not packages:
        fail("source_packages must not be empty")
    package_ids: set[str] = set()
    for package in packages:
        package = exact_keys(package, {"package_id", "provenance_id", "content_sha256", "license", "languages", "review_state"}, "source_package")
        package_id = package["package_id"]
        if not isinstance(package_id, str) or not PACKAGE_ID.fullmatch(package_id) or package_id in package_ids:
            fail("source package identifiers must be unique and stable")
        package_ids.add(package_id)
        if not isinstance(package["provenance_id"], str) or not PACKAGE_ID.fullmatch(package["provenance_id"]):
            fail("invalid provenance_id")
        require_sha256(package["content_sha256"], "source_package.content_sha256")
        if not isinstance(package["license"], str) or not package["license"].strip():
            fail("source_package.license is required")
        if package["review_state"] != "approved":
            fail("each source package requires approval")
        languages = package["languages"]
        if not isinstance(languages, list) or not languages or any(not isinstance(language, str) or not LANGUAGE.fullmatch(language) for language in languages):
            fail("source_package.languages must contain language tags")

    splits = exact_keys(doc["splits"], {"train", "validation", "test"}, "splits")
    assigned_ids: set[str] = set()
    for split_name, split in splits.items():
        split = exact_keys(split, {"package_ids", "content_sha256", "record_count"}, f"splits.{split_name}")
        package_refs = split["package_ids"]
        if not isinstance(package_refs, list) or not package_refs or any(not isinstance(value, str) for value in package_refs):
            fail(f"splits.{split_name}.package_ids must not be empty")
        if len(package_refs) != len(set(package_refs)) or any(value not in package_ids for value in package_refs):
            fail(f"splits.{split_name} references an invalid package")
        if assigned_ids.intersection(package_refs):
            fail("a source package may belong to only one split")
        assigned_ids.update(package_refs)
        require_sha256(split["content_sha256"], f"splits.{split_name}.content_sha256")
        if not isinstance(split["record_count"], int) or split["record_count"] <= 0:
            fail(f"splits.{split_name}.record_count must be positive")
    if assigned_ids != package_ids:
        fail("every source package must be assigned to exactly one split")

    tokenizer = exact_keys(doc["tokenizer_contract"], {"input_encoding", "normalization_policy_id", "candidate_vocabulary_size", "review_state"}, "tokenizer_contract")
    if tokenizer["input_encoding"] != "utf-8":
        fail("tokenizer input encoding must be utf-8")
    if not isinstance(tokenizer["normalization_policy_id"], str) or not POLICY_ID.fullmatch(tokenizer["normalization_policy_id"]):
        fail("invalid tokenizer normalization policy")
    if not isinstance(tokenizer["candidate_vocabulary_size"], int) or not 256 <= tokenizer["candidate_vocabulary_size"] <= 262144:
        fail("tokenizer vocabulary size is out of range")
    if tokenizer["review_state"] not in {"pending", "approved"}:
        fail("invalid tokenizer review state")

    approvals = exact_keys(doc["approvals"], {"data_governance", "training_authorization"}, "approvals")
    if approvals["data_governance"] not in {"pending", "approved"} or approvals["training_authorization"] not in {"not_approved", "approved"}:
        fail("invalid approval state")
    if doc["classification"] == "synthetic" and approvals["training_authorization"] == "approved":
        fail("synthetic material cannot authorize linguistic training")
    if require_training_authorization and (doc["classification"] != "approved_training" or approvals != {"data_governance": "approved", "training_authorization": "approved"} or tokenizer["review_state"] != "approved"):
        fail("corpus is not fully approved for linguistic training")


def main() -> int:
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[1] != "--require-training-authorization"):
        print("usage: validate_training_corpus_manifest.py [--require-training-authorization] MANIFEST.json", file=sys.stderr)
        return 2
    require_training_authorization = len(sys.argv) == 3
    filename = sys.argv[-1]
    try:
        validate(json.loads(Path(filename).read_text(encoding="utf-8")), require_training_authorization=require_training_authorization)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"invalid training corpus manifest: {error}", file=sys.stderr)
        return 1
    print("valid training corpus manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
