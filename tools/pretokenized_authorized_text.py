"""Strict, local-only access to a pre-tokenized authorized train split."""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from tools.authorized_text_bundle import AuthorizedTextBundle


MAXIMUM_MANIFEST_BYTES = 1024 * 1024
MAXIMUM_TOKEN_BYTES = 1024 * 1024 * 1024
MAXIMUM_OFFSET_BYTES = 64 * 1024 * 1024
TOKEN_FILE_NAME = "tokens.u16.bin"
OFFSET_FILE_NAME = "offsets.u64.bin"
MANIFEST_FILE_NAME = "manifest.json"


def _read_bounded(path: Path, *, maximum_bytes: int, label: str) -> bytes:
    try:
        if not path.is_file():
            raise RuntimeError(f"Pre-tokenized {label} is unavailable")
        size = path.stat().st_size
        if not 1 <= size <= maximum_bytes:
            raise RuntimeError(f"Pre-tokenized {label} size is outside the bounded range")
        payload = path.read_bytes()
    except OSError as error:
        raise RuntimeError(f"Pre-tokenized {label} is unavailable") from error
    if len(payload) != size:
        raise RuntimeError(f"Pre-tokenized {label} changed while being read")
    return payload


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class PretokenizedAuthorizedText:
    """Validated token rows with the same record/window selection as the source path."""

    tokens: array = field(repr=False)
    offsets: array = field(repr=False)
    record_count: int
    token_count: int
    vocabulary_size: int

    def tokens_for(self, record_index: int, *, start: int, count: int) -> list[int]:
        if not 0 <= record_index < self.record_count:
            raise RuntimeError("Pre-tokenized record index is outside the bundle")
        if not 0 <= start or not 1 <= count:
            raise RuntimeError("Pre-tokenized token slice is invalid")
        first = self.offsets[record_index]
        final = self.offsets[record_index + 1]
        if start + count > final - first:
            raise RuntimeError("Pre-tokenized token slice exceeds its record")
        return list(self.tokens[first + start : first + start + count])


def load_pretokenized_authorized_text(
    directory: Path, *, bundle: AuthorizedTextBundle
) -> PretokenizedAuthorizedText:
    """Load only a cache that exactly belongs to ``bundle``.

    The cache is an optimization, never a new source of training data: its
    manifest has to bind the already-validated corpus, train split and
    tokenizer.  Its byte-level hashes and offset table are verified before
    model initialization.
    """

    if not isinstance(directory, Path) or not isinstance(bundle, AuthorizedTextBundle):
        raise ValueError("Pre-tokenized input requires a validated training bundle")
    if sys.byteorder != "little":
        raise RuntimeError("Pre-tokenized uint16 cache requires a little-endian CPU")

    manifest_bytes = _read_bounded(
        directory / MANIFEST_FILE_NAME,
        maximum_bytes=MAXIMUM_MANIFEST_BYTES,
        label="manifest",
    )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Pre-tokenized manifest is invalid") from error
    if not isinstance(manifest, dict):
        raise RuntimeError("Pre-tokenized manifest is invalid")
    expected = {
        "artefact": "pretokenized-authorized-train",
        "corpus_manifest_sha256": bundle.manifest_sha256,
        "train_jsonl_sha256": bundle.train_sha256,
        "tokenizer_sha256": bundle.tokenizer_sha256,
        "encode_parameters": {"bos": True, "eos": True},
        "record_count": bundle.train_record_count,
        "dtype": "uint16",
        "tokens_file": TOKEN_FILE_NAME,
        "offsets_file": OFFSET_FILE_NAME,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Pre-tokenized manifest does not match the authorized bundle")
    token_count = manifest.get("token_count")
    if type(token_count) is not int or not bundle.train_record_count <= token_count:
        raise RuntimeError("Pre-tokenized token count is invalid")
    for key in ("tokens_sha256", "offsets_sha256"):
        if not _is_sha256(manifest.get(key)):
            raise RuntimeError("Pre-tokenized manifest hash is invalid")

    tokens_payload = _read_bounded(
        directory / TOKEN_FILE_NAME,
        maximum_bytes=MAXIMUM_TOKEN_BYTES,
        label="tokens",
    )
    offsets_payload = _read_bounded(
        directory / OFFSET_FILE_NAME,
        maximum_bytes=MAXIMUM_OFFSET_BYTES,
        label="offsets",
    )
    if (
        len(tokens_payload) != token_count * 2
        or len(offsets_payload) != (bundle.train_record_count + 1) * 8
        or _sha256(tokens_payload) != manifest["tokens_sha256"]
        or _sha256(offsets_payload) != manifest["offsets_sha256"]
    ):
        raise RuntimeError("Pre-tokenized cache bytes do not match its manifest")

    tokens = array("H")
    tokens.frombytes(tokens_payload)
    offsets = array("Q")
    offsets.frombytes(offsets_payload)
    if (
        len(tokens) != token_count
        or len(offsets) != bundle.train_record_count + 1
        or offsets[0] != 0
        or offsets[-1] != token_count
        or any(left > right for left, right in zip(offsets, offsets[1:]))
        or any(token >= bundle.tokenizer_vocabulary_size for token in tokens)
    ):
        raise RuntimeError("Pre-tokenized cache structure is invalid")
    return PretokenizedAuthorizedText(
        tokens=tokens,
        offsets=offsets,
        record_count=bundle.train_record_count,
        token_count=token_count,
        vocabulary_size=bundle.tokenizer_vocabulary_size,
    )


def pretokenized_text_token_rows(
    cache: PretokenizedAuthorizedText,
    *,
    step: int,
    batch_size: int,
    sequence_length: int,
    seed: int,
) -> list[list[int]]:
    """Return the exact deterministic rows of the uncached authorized path."""

    if not isinstance(cache, PretokenizedAuthorizedText):
        raise ValueError("Pre-tokenized rows require a validated cache")
    if type(step) is not int or step < 0 or type(seed) is not int:
        raise ValueError("Pre-tokenized row selection is invalid")
    if type(batch_size) is not int or not 1 <= batch_size <= 8:
        raise ValueError("Pre-tokenized batch size is invalid")
    if type(sequence_length) is not int or not 2 <= sequence_length <= 512:
        raise ValueError("Pre-tokenized sequence length is invalid")
    required = sequence_length + 1
    rows: list[list[int]] = []
    for row_index in range(batch_size):
        record_index = (seed + step * 131 + row_index * 977) % cache.record_count
        record_length = cache.offsets[record_index + 1] - cache.offsets[record_index]
        if record_length >= required:
            maximum_start = record_length - required
            start = (seed * 17 + step * 104_729 + row_index * 1_009) % (maximum_start + 1)
            rows.append(cache.tokens_for(record_index, start=start, count=required))
            continue
        row = cache.tokens_for(record_index, start=0, count=record_length)
        while len(row) < required:
            record_index = (record_index + 1) % cache.record_count
            following_length = cache.offsets[record_index + 1] - cache.offsets[record_index]
            row.extend(
                cache.tokens_for(
                    record_index,
                    start=0,
                    count=min(following_length, required - len(row)),
                )
            )
        rows.append(row)
    return rows
