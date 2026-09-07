"""Load a bounded, authorized training split and bind its tokenizer.

This module performs lineage checks only.  It neither trains a model nor
promotes a tokenizer artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from services.inference.tokenizer import (
    CANDIDATE_CORE_STATUS,
    EXPERIMENTAL_STATUS,
    MAXIMUM_ARTIFACT_BYTES,
    ByteBpeTokenizer,
    validate_tokenizer_document,
)
from tools.validate_training_corpus_manifest import validate


BUNDLE_SCHEMA_VERSION = "0.1.0"
MAXIMUM_MANIFEST_BYTES = 4 * 1024 * 1024
MAXIMUM_TRAIN_BYTES = 64 * 1024 * 1024
MAXIMUM_TRAIN_RECORDS = 1_000_000
MAXIMUM_LINE_BYTES = 1024 * 1024


def fail(message: str) -> None:
    raise ValueError(message)


def _read_bounded(path: Path, *, maximum_bytes: int, context: str) -> bytes:
    size = path.stat().st_size
    if not 1 <= size <= maximum_bytes:
        fail(f"{context} size is outside the bounded range")
    payload = path.read_bytes()
    if len(payload) != size:
        fail(f"{context} changed while it was being read")
    return payload


def _parse_json(payload: bytes, *, context: str) -> dict[str, Any]:
    try:
        document = json.loads(payload.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ValueError(f"{context} must be valid UTF-8") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{context} must be valid JSON: {error.msg}") from error
    if not isinstance(document, dict):
        fail(f"{context} must be a JSON object")
    return document


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class AuthorizedTextRecord:
    record_id: str
    text: str = field(repr=False)


def parse_train_jsonl(
    payload: bytes, *, expected_record_count: int
) -> tuple[AuthorizedTextRecord, ...]:
    if (
        type(expected_record_count) is not int
        or not 1 <= expected_record_count <= MAXIMUM_TRAIN_RECORDS
    ):
        fail("train record_count is outside the bounded range")
    if not 1 <= len(payload) <= MAXIMUM_TRAIN_BYTES:
        fail("train split size is outside the bounded range")
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("train split must be valid UTF-8") from error

    lines = decoded.split("\n")
    if lines[-1] == "":
        lines.pop()
    if len(lines) != expected_record_count:
        fail("train split record count does not match its manifest")

    records: list[AuthorizedTextRecord] = []
    record_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if len(line.encode("utf-8")) > MAXIMUM_LINE_BYTES:
            fail(f"train record {line_number} exceeds the line size limit")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"invalid train JSONL record at line {line_number}: {error.msg}"
            ) from error
        if not isinstance(record, dict) or set(record) != {"record_id", "text"}:
            fail(
                f"train record {line_number} must contain only record_id and text"
            )
        record_id = record["record_id"]
        text = record["text"]
        if (
            not isinstance(record_id, str)
            or not record_id
            or len(record_id) > 128
        ):
            fail(f"train record {line_number} has an invalid record_id")
        if record_id in record_ids:
            fail(f"train record {line_number} repeats a record_id")
        if not isinstance(text, str) or not text:
            fail(f"train record {line_number} has invalid text")
        record_ids.add(record_id)
        records.append(AuthorizedTextRecord(record_id=record_id, text=text))
    return tuple(records)


@dataclass(frozen=True)
class AuthorizedTextBundle:
    corpus_id: str
    manifest_schema_version: str
    manifest_sha256: str
    train_sha256: str
    train_byte_size: int
    train_record_count: int
    tokenizer_sha256: str
    tokenizer_schema_version: str
    tokenizer_status: str
    tokenizer_vocabulary_size: int
    normalization_policy_id: str
    records: tuple[AuthorizedTextRecord, ...] = field(repr=False)
    tokenizer: ByteBpeTokenizer = field(repr=False, compare=False)

    def lineage_contract(self) -> dict[str, Any]:
        """Return content-free lineage suitable for a future run contract."""
        return {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "mode": "authorized-text",
            "corpus": {
                "corpus_id": self.corpus_id,
                "manifest_schema_version": self.manifest_schema_version,
                "manifest_sha256": self.manifest_sha256,
                "split": "train",
                "content_sha256": self.train_sha256,
                "byte_size": self.train_byte_size,
                "record_count": self.train_record_count,
            },
            "tokenizer": {
                "schema_version": self.tokenizer_schema_version,
                "status": self.tokenizer_status,
                "content_sha256": self.tokenizer_sha256,
                "vocabulary_size": self.tokenizer_vocabulary_size,
                "normalization_policy_id": self.normalization_policy_id,
            },
        }


def load_authorized_text_bundle(
    *,
    manifest_path: Path,
    train_jsonl_path: Path,
    tokenizer_path: Path,
) -> AuthorizedTextBundle:
    manifest_bytes = _read_bounded(
        manifest_path,
        maximum_bytes=MAXIMUM_MANIFEST_BYTES,
        context="training corpus manifest",
    )
    manifest = _parse_json(manifest_bytes, context="training corpus manifest")
    validate(manifest, require_training_authorization=True)

    train_bytes = _read_bounded(
        train_jsonl_path,
        maximum_bytes=MAXIMUM_TRAIN_BYTES,
        context="train split",
    )
    actual_train_sha256 = _sha256(train_bytes)
    declared_train = manifest["splits"]["train"]
    if actual_train_sha256 != declared_train["content_sha256"]:
        forbidden_materializations = {
            "validation": manifest["splits"]["validation"]["content_sha256"],
            "test": manifest["splits"]["test"]["content_sha256"],
            "global": manifest["materialization"]["content_sha256"],
        }
        matched = next(
            (
                name
                for name, digest in forbidden_materializations.items()
                if digest == actual_train_sha256
            ),
            None,
        )
        if matched is not None:
            fail(f"authorized-text accepts train only; received {matched} materialization")
        fail("train split SHA-256 does not match its manifest")
    if len(train_bytes) != declared_train["byte_size"]:
        fail("train split byte size does not match its manifest")
    records = parse_train_jsonl(
        train_bytes, expected_record_count=declared_train["record_count"]
    )

    tokenizer_bytes = _read_bounded(
        tokenizer_path,
        maximum_bytes=MAXIMUM_ARTIFACT_BYTES,
        context="tokenizer artifact",
    )
    tokenizer_document = _parse_json(
        tokenizer_bytes, context="tokenizer artifact"
    )
    validate_tokenizer_document(tokenizer_document)
    tokenizer_contract = manifest["tokenizer_contract"]
    if tokenizer_document["status"] not in {
        EXPERIMENTAL_STATUS,
        CANDIDATE_CORE_STATUS,
    }:
        fail("authorized-text requires an experimental or candidate_core tokenizer")
    if tokenizer_document["training_corpus_id"] != manifest["corpus_id"]:
        fail("tokenizer corpus id does not match the authorized corpus")
    if tokenizer_document["training_corpus_sha256"] != declared_train["content_sha256"]:
        fail("tokenizer was not trained from the authorized train split")
    if tokenizer_document["input_encoding"] != tokenizer_contract["input_encoding"]:
        fail("tokenizer input encoding does not match the corpus contract")
    if (
        tokenizer_document["normalization_policy_id"]
        != tokenizer_contract["normalization_policy_id"]
    ):
        fail("tokenizer normalization does not match the corpus contract")
    if (
        tokenizer_document["vocabulary_size"]
        != tokenizer_contract["candidate_vocabulary_size"]
    ):
        fail("tokenizer vocabulary does not match the corpus contract")

    tokenizer = ByteBpeTokenizer.from_document(tokenizer_document)
    return AuthorizedTextBundle(
        corpus_id=manifest["corpus_id"],
        manifest_schema_version=manifest["schema_version"],
        manifest_sha256=_sha256(manifest_bytes),
        train_sha256=actual_train_sha256,
        train_byte_size=len(train_bytes),
        train_record_count=len(records),
        tokenizer_sha256=_sha256(tokenizer_bytes),
        tokenizer_schema_version=tokenizer_document["schema_version"],
        tokenizer_status=tokenizer_document["status"],
        tokenizer_vocabulary_size=tokenizer_document["vocabulary_size"],
        normalization_policy_id=tokenizer_document["normalization_policy_id"],
        records=records,
        tokenizer=tokenizer,
    )
