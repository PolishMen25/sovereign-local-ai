#!/usr/bin/env python3
"""Acquire only the owner-approved candidate source archives into RAW.

This tool never promotes content, never writes ``approved.json``, and refuses a
source that does not have the exact GitHub tag layout used by the candidate
catalogue.  It is intentionally a narrow acquisition boundary, not a corpus
materializer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = PROJECT_ROOT / "configs" / "corpus" / "core-v1-source-policy.candidate.json"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("sources"), list):
        raise ValueError("candidate policy must contain a sources list")
    if len(value["sources"]) != 10:
        raise ValueError("candidate policy must contain exactly 10 sources")
    return value


def archive_url(source: dict[str, Any]) -> str:
    """Return the single permitted GitHub tag archive URL for one source."""

    source_url = source.get("url")
    pin = source.get("version_or_commit_pin")
    if not isinstance(source_url, str) or not isinstance(pin, str) or not SAFE_NAME.fullmatch(pin):
        raise ValueError("source URL or version pin is invalid")
    parsed = urllib.parse.urlparse(source_url)
    parts = parsed.path.strip("/").split("/")
    if parsed.scheme != "https" or parsed.netloc != "github.com" or len(parts) != 4 or parts[2] != "tree":
        raise ValueError(f"source URL is not an exact GitHub tree URL: {source_url}")
    owner, repository, _, url_pin = parts
    if url_pin != pin or not SAFE_NAME.fullmatch(owner) or not SAFE_NAME.fullmatch(repository):
        raise ValueError(f"source pin does not match its URL: {source_url}")
    return f"https://github.com/{owner}/{repository}/archive/refs/tags/{urllib.parse.quote(pin)}.tar.gz"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_stats(path: Path) -> tuple[int, int]:
    with tarfile.open(path, "r:gz") as archive:
        files = [member for member in archive.getmembers() if member.isfile()]
    return len(files), sum(member.size for member in files)


def acquire(policy_path: Path, raw_root: Path, *, opener=urllib.request.urlopen) -> list[dict[str, Any]]:
    """Download each catalogue archive once, returning destination-verified facts."""

    policy = load_policy(policy_path)
    root = raw_root.resolve()
    if not root.is_dir():
        raise ValueError(f"RAW directory is absent: {root}")
    results: list[dict[str, Any]] = []
    for source in policy["sources"]:
        if not isinstance(source, dict):
            raise ValueError("source must be an object")
        name = source.get("name")
        pin = source.get("version_or_commit_pin")
        if not isinstance(name, str) or not isinstance(pin, str):
            raise ValueError("source name or pin is invalid")
        filename = f"{name.lower().replace(' ', '-')}-{pin}.tar.gz"
        destination = (root / filename).resolve()
        if destination.parent != root or destination.exists():
            raise ValueError(f"refusing existing or out-of-RAW destination: {destination}")
        temporary = destination.with_suffix(destination.suffix + ".partial")
        if temporary.exists():
            raise ValueError(f"refusing unfinished prior acquisition: {temporary}")
        url = archive_url(source)
        try:
            with opener(url, timeout=60) as response, temporary.open("xb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            with tarfile.open(temporary, "r:gz"):
                pass
            temporary.replace(destination)
        except Exception:
            # Evidence is intentionally retained in RAW as an incomplete artifact.
            raise
        file_count, unpacked_bytes = _archive_stats(destination)
        results.append({
            "name": name,
            "url": url,
            "archive": destination.name,
            "sha256": _sha256(destination),
            "archive_bytes": destination.stat().st_size,
            "archive_file_count": file_count,
            "archive_unpacked_bytes": unpacked_bytes,
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    results = acquire(args.policy, args.raw_root)
    args.receipt.write_text(json.dumps({"sources": results}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
