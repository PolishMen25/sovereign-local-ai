#!/usr/bin/env python3
"""Refuse CORE training unless the owner committed a matching corpus approval."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_POLICY = PROJECT_ROOT / "configs" / "corpus" / "core-v1-source-policy.candidate.json"
APPROVED_POLICY = PROJECT_ROOT / "configs" / "corpus" / "core-v1-source-policy.approved.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"corpus approval is absent: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid corpus approval JSON: {path}: {error.msg}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _source_without_sha256(source: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key != "sha256"}


def _permissive(license_name: Any) -> bool:
    if not isinstance(license_name, str):
        return False
    normalized = license_name.strip().lower()
    return normalized == "mit" or normalized.startswith("mit (") or normalized in {
        "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "cc0-1.0", "verified-public-domain"
    }


def _validate_source(source: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise ValueError(f"{label} source must be an object")
    sha256 = source.get("sha256")
    if not isinstance(sha256, str) or sha256.lower() in {"pending", "unverified"}:
        raise ValueError(f"{label} source has an unapproved sha256")
    if len(sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in sha256):
        raise ValueError(f"{label} source sha256 must be 64 hexadecimal characters")
    if not _permissive(source.get("license_detected")):
        raise ValueError(f"{label} source has a non-permissive or unverified license")
    return source


def verify_corpus_approval(
    *, candidate_path: Path = CANDIDATE_POLICY, approved_path: Path = APPROVED_POLICY
) -> dict[str, Any]:
    """Validate the owner-committed approval without reading corpus bytes."""

    candidate = _read_json(candidate_path)
    approved = _read_json(approved_path)
    for key in ("approved_by", "approved_at", "candidate_policy_commit", "sources"):
        if not approved.get(key):
            raise ValueError(f"corpus approval missing required field: {key}")
    try:
        datetime.fromisoformat(str(approved["approved_at"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("corpus approval approved_at must be ISO-8601") from error
    candidate_commit = str(approved["candidate_policy_commit"])
    if not 7 <= len(candidate_commit) <= 64 or any(char not in "0123456789abcdefABCDEF" for char in candidate_commit):
        raise ValueError("corpus approval candidate_policy_commit must be a Git commit identifier")

    candidate_sources = candidate.get("sources")
    approved_sources = approved.get("sources")
    if not isinstance(candidate_sources, list) or not isinstance(approved_sources, list):
        raise ValueError("candidate and approval sources must be lists")
    if len(candidate_sources) != len(approved_sources):
        raise ValueError("approved source list differs from candidate source list")
    for index, (candidate_source, approved_source) in enumerate(zip(candidate_sources, approved_sources, strict=True)):
        if not isinstance(candidate_source, dict) or not isinstance(approved_source, dict):
            raise ValueError("candidate and approval sources must be objects")
        if _source_without_sha256(candidate_source) != _source_without_sha256(approved_source):
            raise ValueError(f"approved source list differs from candidate at index {index}")
        _validate_source(approved_source, label=f"approved[{index}]")
    return {"approved_by": approved["approved_by"], "candidate_policy_commit": candidate_commit, "source_count": len(approved_sources)}
