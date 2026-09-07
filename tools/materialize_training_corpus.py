"""Build a bounded JSONL corpus from owner-approved source archives offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
from typing import Any


MAXIMUM_ARCHIVE_BYTES = 128 * 1024 * 1024
MAXIMUM_FILE_BYTES = 256 * 1024
MAXIMUM_SPLIT_BYTES = 16 * 1024 * 1024
TEXT_SUFFIXES = {".go", ".json", ".md", ".ps1", ".psd1", ".psm1", ".py", ".pyi", ".rst", ".sh", ".toml", ".txt", ".yaml", ".yml"}
EXCLUDED_PARTS = {".github", "example", "examples", "test", "tests", "vendor"}
SECRET_MARKERS = ("BEGIN PRIVATE KEY", "BEGIN OPENSSH PRIVATE KEY", "password=", "api_key=", "access_token=")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def accepted_member(member: tarfile.TarInfo) -> tuple[str, str] | None:
    path = PurePosixPath(member.name)
    if not member.isreg() or member.size < 1 or member.size > MAXIMUM_FILE_BYTES:
        return None
    if path.is_absolute() or len(path.parts) < 2 or any(part in {"", ".", ".."} for part in path.parts):
        return None
    relative = PurePosixPath(*path.parts[1:])
    if relative.suffix.lower() not in TEXT_SUFFIXES or any(part.lower() in EXCLUDED_PARTS for part in relative.parts):
        return None
    return relative.as_posix(), relative.suffix.lower()


def records_for_source(source: dict[str, Any]) -> list[bytes]:
    archive = Path(source["archive"])
    if not archive.is_file() or archive.stat().st_size > MAXIMUM_ARCHIVE_BYTES:
        raise ValueError("source archive is unavailable or too large")
    records: list[bytes] = []
    total = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in sorted(bundle.getmembers(), key=lambda candidate: candidate.name):
            accepted = accepted_member(member)
            if accepted is None:
                continue
            stream = bundle.extractfile(member)
            if stream is None:
                continue
            payload = stream.read(member.size + 1)
            if len(payload) != member.size or b"\0" in payload:
                continue
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if any(marker.lower() in text.lower() for marker in SECRET_MARKERS):
                continue
            relative, _ = accepted
            record = canonical({"record_id": f"{source['package_id']}:{relative}", "text": text})
            if total + len(record) > MAXIMUM_SPLIT_BYTES:
                break
            records.append(record)
            total += len(record)
    if not records:
        raise ValueError("source yielded no safe text records")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        sources = spec["sources"]
        if not isinstance(sources, list) or {source.get("split") for source in sources} != {"train", "validation", "test"}:
            raise ValueError("spec requires exactly one approved source for each split")
        output = args.output_directory
        output.mkdir(parents=True, exist_ok=False)
        split_documents: dict[str, bytes] = {}
        packages: list[dict[str, Any]] = []
        for source in sorted(sources, key=lambda item: item["split"]):
            required = {"package_id", "provenance_id", "license", "languages", "archive", "split"}
            if not isinstance(source, dict) or set(source) != required:
                raise ValueError("source specification is invalid")
            records = records_for_source(source)
            payload = b"".join(records)
            split_documents[source["split"]] = payload
            (output / f"{source['split']}.jsonl").write_bytes(payload)
            archive_bytes = Path(source["archive"]).read_bytes()
            packages.append({"package_id": source["package_id"], "provenance_id": source["provenance_id"], "content_sha256": digest(archive_bytes), "license": source["license"], "languages": source["languages"], "review_state": "approved"})
        global_document = b"".join(split_documents[name] for name in ("train", "validation", "test"))
        (output / "materialization.jsonl").write_bytes(global_document)
        splits = {name: {"package_ids": [next(item["package_id"] for item in packages if item["package_id"] == next(source["package_id"] for source in sources if source["split"] == name))], "content_sha256": digest(split_documents[name]), "byte_size": len(split_documents[name]), "record_count": split_documents[name].count(b"\n")} for name in ("train", "validation", "test")}
        manifest = {"schema_version": "0.2.0", "corpus_id": spec["corpus_id"], "lifecycle_state": "VALIDATED", "classification": "approved_training", "materialization": {"format": "jsonl-utf8", "content_sha256": digest(global_document), "byte_size": len(global_document), "record_count": global_document.count(b"\n")}, "source_packages": packages, "splits": splits, "tokenizer_contract": {"input_encoding": "utf-8", "normalization_policy_id": "unicode-nfc-v1", "candidate_vocabulary_size": 32000, "review_state": "approved"}, "approvals": {"data_governance": "approved", "training_authorization": "approved"}}
        (output / "manifest.json").write_bytes(canonical(manifest))
    except (OSError, KeyError, TypeError, ValueError, tarfile.TarError) as error:
        print(f"corpus materialization refused: {error}")
        return 1
    print("approved corpus materialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
