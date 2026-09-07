"""Prepare or build a lexical index from an explicitly approved manifest.

``manifest`` only records a candidate. ``build`` refuses to infer approval:
the operator supplies the exact manifest digest and an audit reference. The
existing index is replaced only after every source byte matches the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
from typing import Any

from services.knowledge.hybrid_index import HybridKnowledgeIndex


MANIFEST_SCHEMA = "sovereign-knowledge-manifest.v1"
APPROVAL_REFERENCE = re.compile(r"^[A-Za-z0-9_.:-]{8,160}$")


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(manifest)).hexdigest()


def relative_document(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.suffix != ".md":
        raise ValueError("document path is invalid")
    return path.as_posix()


def document_entry(source: Path, relative: str) -> dict[str, str]:
    path = source / relative
    if not path.is_file():
        raise ValueError(f"approved document is missing: {relative}")
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"approved document is not UTF-8: {relative}") from error
    if not raw.strip():
        raise ValueError(f"approved document is empty: {relative}")
    return {"path": relative, "sha256": hashlib.sha256(raw).hexdigest()}


def create_manifest(source: Path, documents: list[str]) -> dict[str, Any]:
    if not source.is_dir():
        raise ValueError("source directory is invalid")
    relative_paths = sorted({relative_document(item) for item in documents})
    if not relative_paths:
        raise ValueError("at least one document is required")
    return {
        "schema_version": MANIFEST_SCHEMA,
        "documents": [document_entry(source, relative) for relative in relative_paths],
    }


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("manifest is unreadable") from error
    if not isinstance(value, dict) or set(value) != {"schema_version", "documents"}:
        raise ValueError("manifest shape is invalid")
    if value["schema_version"] != MANIFEST_SCHEMA or not isinstance(value["documents"], list):
        raise ValueError("manifest schema is invalid")
    entries: list[dict[str, str]] = []
    for item in value["documents"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("manifest document is invalid")
        relative = relative_document(item["path"])
        digest = item["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("manifest document digest is invalid")
        entries.append({"path": relative, "sha256": digest})
    if not entries or entries != sorted(entries, key=lambda item: item["path"]):
        raise ValueError("manifest documents must be unique and sorted")
    return {"schema_version": MANIFEST_SCHEMA, "documents": entries}


def title_for(content: str, fallback: str) -> str:
    return next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), fallback)[:500]


def build_index(source: Path, database: Path, manifest: dict[str, Any], approval_reference: str) -> int:
    if not source.is_dir():
        raise ValueError("source directory is invalid")
    if not APPROVAL_REFERENCE.fullmatch(approval_reference):
        raise ValueError("approval reference is invalid")
    digest = manifest_digest(manifest)
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = database.with_name(f".{database.name}.{secrets.token_hex(12)}.tmp")
    try:
        index = HybridKnowledgeIndex(temporary)
        index.initialize()
        for entry in manifest["documents"]:
            relative = entry["path"]
            raw = (source / relative).read_bytes()
            if not secrets.compare_digest(hashlib.sha256(raw).hexdigest(), entry["sha256"]):
                raise ValueError(f"approved document changed: {relative}")
            content = raw.decode("utf-8")
            index.upsert_validated(
                document_id=f"approved:{relative}",
                title=title_for(content, relative),
                content=content,
                provenance_id=f"manifest-sha256:{digest}:{entry['sha256'][:16]}",
                embedding=None,
            )
        index.set_metadata("manifest_sha256", digest)
        index.set_metadata("approval_reference", approval_reference)
        index.set_metadata("schema_version", MANIFEST_SCHEMA)
        os.replace(temporary, database)
    finally:
        temporary.unlink(missing_ok=True)
    return len(manifest["documents"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    candidate = commands.add_parser("manifest", help="write a candidate manifest")
    candidate.add_argument("--source-directory", type=Path, required=True)
    candidate.add_argument("--document", action="append", default=[])
    candidate.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("build", help="build from an approved manifest")
    build.add_argument("--source-directory", type=Path, required=True)
    build.add_argument("--database", type=Path, required=True)
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--approved-manifest-sha256", required=True)
    build.add_argument("--approval-reference", required=True)
    args = parser.parse_args()
    try:
        if args.command == "manifest":
            manifest = create_manifest(args.source_directory.resolve(), args.document)
            args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            args.output.write_bytes(canonical_json(manifest) + b"\n")
            print(f"candidate_manifest_sha256={manifest_digest(manifest)} documents={len(manifest['documents'])}")
            return 0
        manifest = load_manifest(args.manifest)
        if not secrets.compare_digest(manifest_digest(manifest), args.approved_manifest_sha256):
            raise ValueError("approved manifest digest does not match")
        count = build_index(args.source_directory.resolve(), args.database, manifest, args.approval_reference)
        print(f"indexed_documents={count} manifest_sha256={manifest_digest(manifest)}")
        return 0
    except ValueError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    raise SystemExit(main())
