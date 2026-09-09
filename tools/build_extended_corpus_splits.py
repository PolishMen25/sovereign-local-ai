#!/usr/bin/env python3
"""Build a review-pending extended corpus split without pilot-v3 holdout leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, BinaryIO


SPLITS = ("train", "validation", "test")
MANIFEST_NAME = "extended-corpus-splits.candidate.json"
MAXIMUM_RECORD_BYTES = 2 * 1024 * 1024


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_line(line: bytes, *, source_name: str, line_number: int) -> dict[str, Any]:
    if not 1 <= len(line) <= MAXIMUM_RECORD_BYTES:
        raise ValueError(f"{source_name}: record size is outside the bounded range")
    try:
        record = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{source_name}: record is not valid UTF-8 JSON") from error
    if not isinstance(record, dict):
        raise ValueError(f"{source_name}: record must be an object")
    return record


def heldout_record_ids(*, validation_path: Path, test_path: Path) -> set[str]:
    heldout: set[str] = set()
    for source_path in (validation_path, test_path):
        try:
            source = source_path.open("rb")
        except OSError as error:
            raise ValueError("pilot-v3 holdout split is unavailable") from error
        with source:
            for number, line in enumerate(source, start=1):
                record = parse_line(line, source_name="pilot-v3 holdout", line_number=number)
                if set(record) != {"record_id", "text"} or not isinstance(record["record_id"], str) or not isinstance(record["text"], str):
                    raise ValueError("pilot-v3 holdout record shape is invalid")
                record_id = text_digest(record["text"])
                if record["record_id"] != record_id or record_id in heldout:
                    raise ValueError("pilot-v3 holdout record identity is invalid or duplicated")
                heldout.add(record_id)
    if not heldout:
        raise ValueError("pilot-v3 holdout split is empty")
    return heldout


def destination_split(record_id: str) -> str:
    bucket = int(record_id[:8], 16) % 100
    if bucket == 0:
        return "test"
    if bucket == 1:
        return "validation"
    return "train"


def write_splits(
    *, extended_path: Path, heldout: set[str], temporary: Path
) -> dict[str, Any]:
    writers: dict[str, BinaryIO] = {}
    digests = {name: hashlib.sha256() for name in SPLITS}
    counts = {name: 0 for name in SPLITS}
    packages = {name: set() for name in SPLITS}
    seen: set[str] = set()
    excluded = {"pilot_v3_holdout": 0}
    input_digest = hashlib.sha256()
    try:
        for name in SPLITS:
            writers[name] = (temporary / f"{name}.jsonl").open("xb")
        with extended_path.open("rb") as source:
            for number, line in enumerate(source, start=1):
                input_digest.update(line)
                record = parse_line(line, source_name="extended corpus", line_number=number)
                text, package = record.get("text"), record.get("package")
                if not isinstance(text, str) or not text or not isinstance(package, str) or not package.strip():
                    raise ValueError("extended corpus record requires non-empty text and package")
                record_id = text_digest(text)
                if record_id in seen:
                    raise ValueError("extended corpus contains a duplicate text record")
                seen.add(record_id)
                if record_id in heldout:
                    excluded["pilot_v3_holdout"] += 1
                    continue
                split = destination_split(record_id)
                payload = canonical({"package": package, "record_id": record_id, "text": text})
                writers[split].write(payload)
                digests[split].update(payload)
                counts[split] += 1
                packages[split].add(package)
    finally:
        for writer in writers.values():
            writer.close()
    if any(counts[name] < 1 for name in SPLITS):
        raise ValueError("extended corpus split is empty")
    verified = {
        name: {
            "content_sha256": file_digest(temporary / f"{name}.jsonl"),
            "record_count": counts[name],
            "package_count": len(packages[name]),
            "package_ids": sorted(packages[name]),
        }
        for name in SPLITS
    }
    if any(verified[name]["content_sha256"] != digests[name].hexdigest() for name in SPLITS):
        raise RuntimeError("split readback hash differs from written bytes")
    return {
        "input_sha256": input_digest.hexdigest(),
        "input_record_count": len(seen),
        "excluded": excluded,
        "splits": verified,
    }


def build(
    *, extended_path: Path, pilot_validation_path: Path, pilot_test_path: Path, output_dir: Path
) -> dict[str, Any]:
    if not extended_path.is_file() or extended_path.is_symlink():
        raise ValueError("extended corpus must be an existing regular file")
    if output_dir.exists():
        raise ValueError("extended corpus split destination already exists")
    heldout = heldout_record_ids(validation_path=pilot_validation_path, test_path=pilot_test_path)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".extended-corpus-splits-", dir=output_dir.parent))
    try:
        result = write_splits(extended_path=extended_path, heldout=heldout, temporary=temporary)
        manifest = {
            "schema_version": "extended-corpus-splits.candidate.v1",
            "lifecycle_state": "RAW_DERIVED_PENDING_REVIEW",
            "automatic_promotion": False,
            "input": {"content_sha256": result["input_sha256"], "record_count": result["input_record_count"]},
            "pilot_v3_holdout_record_count": len(heldout),
            "excluded": result["excluded"],
            "splits": result["splits"],
        }
        (temporary / MANIFEST_NAME).write_bytes(canonical(manifest))
        if json.loads((temporary / MANIFEST_NAME).read_text(encoding="utf-8")) != manifest:
            raise RuntimeError("split manifest readback differs from written data")
        os.replace(temporary, output_dir)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extended-jsonl", type=Path, required=True)
    parser.add_argument("--pilot-validation-jsonl", type=Path, required=True)
    parser.add_argument("--pilot-test-jsonl", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = build(
            extended_path=args.extended_jsonl,
            pilot_validation_path=args.pilot_validation_jsonl,
            pilot_test_path=args.pilot_test_jsonl,
            output_dir=args.output_dir,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"extended corpus split refused: {error}")
        return 1
    print(json.dumps({"excluded": manifest["excluded"], "splits": manifest["splits"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
