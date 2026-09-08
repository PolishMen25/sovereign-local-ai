"""Strict, deterministic byte-level BPE artifacts for local inference.

The module has no network or third-party dependency.  Training and inference
share the same NFC normalization and ordered merge implementation so an
artifact cannot silently change tokenization between the two phases.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable
import unicodedata
from array import array
from heapq import heapify, heappop, heappush


SCHEMA_VERSION = "0.2.0"
EXPERIMENTAL_STATUS = "experimental"
CANDIDATE_CORE_STATUS = "candidate_core"
APPROVED_CORE_STATUS = "approved_core_v1"
# ``ARTIFACT_STATUS`` remains an alias for callers that create fresh BPE
# artifacts.  A newly trained artifact is never promoted implicitly.
ARTIFACT_STATUS = EXPERIMENTAL_STATUS
VALID_ARTIFACT_STATUSES = frozenset(
    {EXPERIMENTAL_STATUS, CANDIDATE_CORE_STATUS, APPROVED_CORE_STATUS}
)
ALGORITHM = "byte_bpe"
INPUT_ENCODING = "utf-8"
NORMALIZATION_POLICY_ID = "unicode-nfc-v1"
SPECIAL_TOKENS = ["<pad>", "<bos>", "<eos>", "<unk>"]
PAD_TOKEN_ID = 0
BOS_TOKEN_ID = 1
EOS_TOKEN_ID = 2
UNK_TOKEN_ID = 3

MAXIMUM_TOKEN_BYTES = 64
MAXIMUM_VOCABULARY_SIZE = 32_768
MAXIMUM_ARTIFACT_BYTES = 128 * 1024 * 1024
MAXIMUM_RUNTIME_TEXT_BYTES = 1024 * 1024
MAXIMUM_DECODE_TOKEN_IDS = 65_536

SHA256 = re.compile(r"^[0-9a-f]{64}$")
CORPUS_ID = re.compile(r"^corpus-[a-z0-9][a-z0-9-]{2,62}$")
HEX_TOKEN = re.compile(r"^(?:[0-9a-f]{2}){1,64}$")

DOCUMENT_KEYS = {
    "schema_version",
    "status",
    "algorithm",
    "training_corpus_id",
    "training_corpus_sha256",
    "input_encoding",
    "normalization_policy_id",
    "special_tokens",
    "tokens_hex",
    "merges",
    "vocabulary_size",
    "minimum_frequency",
    "maximum_token_bytes",
}


def fail(message: str) -> None:
    raise ValueError(message)


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        fail("text must be a string")
    return unicodedata.normalize("NFC", text)


def canonical_byte_tokens() -> tuple[str, ...]:
    return tuple(f"{value:02x}" for value in range(256))


def merge_sequence(
    sequence: list[str], pair: tuple[str, str], merged: str
) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(sequence):
        if (
            index + 1 < len(sequence)
            and sequence[index] == pair[0]
            and sequence[index + 1] == pair[1]
        ):
            output.append(merged)
            index += 2
        else:
            output.append(sequence[index])
            index += 1
    return output


@dataclass(frozen=True)
class BpeTrainingResult:
    """The non-special vocabulary and learned merges in stable rank order."""

    tokens_hex: tuple[str, ...]
    merges: tuple[tuple[str, str], ...]

    @property
    def vocabulary_size(self) -> int:
        return len(SPECIAL_TOKENS) + len(self.tokens_hex)


def train_byte_bpe(
    texts: Iterable[str],
    vocabulary_size: int,
    *,
    minimum_frequency: int = 2,
) -> BpeTrainingResult:
    """Learn bounded BPE merges deterministically from NFC-normalized text."""
    if type(vocabulary_size) is not int or not 260 <= vocabulary_size <= MAXIMUM_VOCABULARY_SIZE:
        fail(
            "vocabulary_size must be between 260 and "
            f"{MAXIMUM_VOCABULARY_SIZE}"
        )
    if type(minimum_frequency) is not int or not 1 <= minimum_frequency <= 1_000_000_000:
        fail("minimum_frequency must be an integer between 1 and 1000000000")

    if isinstance(texts, (str, bytes)):
        fail("texts must be an iterable of strings, not a single string")
    try:
        normalized = [normalize_text(text) for text in texts]
    except TypeError as error:
        raise ValueError("texts must be an iterable of strings") from error
    if not normalized or any(not text for text in normalized):
        fail("texts must be a non-empty iterable of non-empty strings")

    # Incremental implementation with output identical to the reference BPE.
    # The representation and pair accounting change, not eligibility, tie
    # breaking, or left-to-right non-overlapping merge semantics.
    symbol_strings = list(canonical_byte_tokens())
    symbol_lengths = [1] * 256
    tokens = list(symbol_strings)
    vocabulary = set(tokens)
    merges: list[tuple[str, str]] = []

    symbols = array("i")
    previous_index = array("i")
    next_index = array("i")
    base = 0
    for text in normalized:
        payload = text.encode(INPUT_ENCODING)
        length = len(payload)
        symbols.extend(payload)
        previous_index.extend(range(base - 1, base + length - 1))
        next_index.extend(range(base + 1, base + length + 1))
        previous_index[base] = -1
        next_index[base + length - 1] = -1
        base += length
    del normalized
    total = len(symbols)

    counts: dict[tuple[int, int], int] = {}
    positions: dict[tuple[int, int], array] = {}
    for position in range(total):
        following = next_index[position]
        if following == -1:
            continue
        key = (symbols[position], symbols[following])
        count = counts.get(key)
        if count is None:
            counts[key] = 1
            slot = array("i")
            slot.append(position)
            positions[key] = slot
        else:
            counts[key] = count + 1
            positions[key].append(position)

    heap = [
        (-count, symbol_strings[key[0]], symbol_strings[key[1]], key[0], key[1])
        for key, count in counts.items()
    ]
    heapify(heap)
    rebuild_at = max(4 * len(heap), 1_000_000)

    while len(SPECIAL_TOKENS) + len(tokens) < vocabulary_size:
        chosen = None
        while heap:
            recorded, left_string, right_string, left, right = heappop(heap)
            key = (left, right)
            current = counts.get(key, 0)
            if current != -recorded:
                if current > 0:
                    heappush(heap, (-current, left_string, right_string, left, right))
                continue
            if current < minimum_frequency:
                continue
            if symbol_lengths[left] + symbol_lengths[right] > MAXIMUM_TOKEN_BYTES:
                continue
            if left_string + right_string in vocabulary:
                continue
            chosen = key
            break
        if chosen is None:
            break

        left, right = chosen
        merged = symbol_strings[left] + symbol_strings[right]
        merged_id = len(symbol_strings)
        symbol_strings.append(merged)
        symbol_lengths.append(symbol_lengths[left] + symbol_lengths[right])
        vocabulary.add(merged)
        tokens.append(merged)
        merges.append((symbol_strings[left], symbol_strings[right]))

        occurrences = positions.pop(chosen, array("i"))
        counts.pop(chosen, None)

        for position in sorted(occurrences):
            if symbols[position] != left:
                continue
            following = next_index[position]
            if following == -1 or symbols[following] != right:
                continue
            preceding = previous_index[position]
            trailing = next_index[following]

            if preceding != -1:
                key = (symbols[preceding], left)
                count = counts.get(key)
                if count is not None:
                    if count <= 1:
                        del counts[key]
                        positions.pop(key, None)
                    else:
                        counts[key] = count - 1
            if trailing != -1:
                key = (right, symbols[trailing])
                count = counts.get(key)
                if count is not None:
                    if count <= 1:
                        del counts[key]
                        positions.pop(key, None)
                    else:
                        counts[key] = count - 1

            symbols[position] = merged_id
            symbols[following] = -1
            next_index[position] = trailing
            if trailing != -1:
                previous_index[trailing] = position

            if preceding != -1:
                key = (symbols[preceding], merged_id)
                count = counts.get(key, 0) + 1
                counts[key] = count
                slot = positions.get(key)
                if slot is None:
                    slot = array("i")
                    positions[key] = slot
                slot.append(preceding)
                heappush(heap, (-count, symbol_strings[key[0]], merged, key[0], merged_id))
            if trailing != -1:
                key = (merged_id, symbols[trailing])
                count = counts.get(key, 0) + 1
                counts[key] = count
                slot = positions.get(key)
                if slot is None:
                    slot = array("i")
                    positions[key] = slot
                slot.append(position)
                heappush(heap, (-count, merged, symbol_strings[key[1]], merged_id, key[1]))

        if len(heap) > rebuild_at:
            heap = [
                (-count, symbol_strings[key[0]], symbol_strings[key[1]], key[0], key[1])
                for key, count in counts.items()
            ]
            heapify(heap)
            rebuild_at = max(4 * len(heap), 1_000_000)

    return BpeTrainingResult(tokens_hex=tuple(tokens), merges=tuple(merges))


def experimental_tokenizer_document(
    *,
    training_corpus_id: str,
    training_corpus_sha256: str,
    result: BpeTrainingResult,
    minimum_frequency: int,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": ARTIFACT_STATUS,
        "algorithm": ALGORITHM,
        "training_corpus_id": training_corpus_id,
        "training_corpus_sha256": training_corpus_sha256,
        "input_encoding": INPUT_ENCODING,
        "normalization_policy_id": NORMALIZATION_POLICY_ID,
        "special_tokens": list(SPECIAL_TOKENS),
        "tokens_hex": list(result.tokens_hex),
        "merges": [list(pair) for pair in result.merges],
        "vocabulary_size": result.vocabulary_size,
        "minimum_frequency": minimum_frequency,
        "maximum_token_bytes": MAXIMUM_TOKEN_BYTES,
    }
    validate_tokenizer_document(document)
    return document


def promote_to_candidate_core(document: Any) -> dict[str, Any]:
    """Return a validated candidate-core copy of one experimental artifact.

    Promotion intentionally changes only the lifecycle status.  Provenance and
    the ordered BPE graph remain byte-for-byte represented by the source
    document; the caller is responsible for persisting the separate receipt
    that binds both artifact hashes to an approved corpus manifest.
    """

    validated = validate_tokenizer_document(document)
    if validated["status"] != EXPERIMENTAL_STATUS:
        fail("only an experimental tokenizer can be promoted to candidate_core")
    promoted = dict(validated)
    promoted["status"] = CANDIDATE_CORE_STATUS
    validate_tokenizer_document(promoted)
    return promoted


def _require_canonical_token(value: Any, context: str) -> str:
    if not isinstance(value, str) or not HEX_TOKEN.fullmatch(value):
        fail(f"{context} must be canonical lowercase hexadecimal bytes")
    return value


def validate_tokenizer_document(document: Any) -> dict[str, Any]:
    """Validate every field and prove that the ordered merge graph is sound."""
    if not isinstance(document, dict) or set(document) != DOCUMENT_KEYS:
        fail(f"tokenizer artifact keys must be exactly {sorted(DOCUMENT_KEYS)}")
    if document["schema_version"] != SCHEMA_VERSION:
        fail("unsupported tokenizer schema_version")
    if document["status"] not in VALID_ARTIFACT_STATUSES:
        fail("unsupported tokenizer artifact status")
    if document["algorithm"] != ALGORITHM:
        fail("unsupported tokenizer algorithm")
    if document["input_encoding"] != INPUT_ENCODING:
        fail("unsupported tokenizer input encoding")
    if document["normalization_policy_id"] != NORMALIZATION_POLICY_ID:
        fail("unsupported tokenizer normalization policy")
    if document["special_tokens"] != SPECIAL_TOKENS:
        fail("special tokens and their stable ids 0-3 do not match")
    if (
        not isinstance(document["training_corpus_id"], str)
        or not CORPUS_ID.fullmatch(document["training_corpus_id"])
    ):
        fail("invalid tokenizer training_corpus_id")
    if (
        not isinstance(document["training_corpus_sha256"], str)
        or not SHA256.fullmatch(document["training_corpus_sha256"])
    ):
        fail("invalid tokenizer training_corpus_sha256")
    if (
        type(document["minimum_frequency"]) is not int
        or not 1 <= document["minimum_frequency"] <= 1_000_000_000
    ):
        fail("invalid tokenizer minimum_frequency")
    if document["maximum_token_bytes"] != MAXIMUM_TOKEN_BYTES:
        fail("invalid tokenizer maximum_token_bytes")

    tokens = document["tokens_hex"]
    if not isinstance(tokens, list):
        fail("tokenizer tokens_hex must be a list")
    if not 256 <= len(tokens) <= MAXIMUM_VOCABULARY_SIZE - len(SPECIAL_TOKENS):
        fail("tokenizer token count is outside the bounded range")
    canonical_tokens = [
        _require_canonical_token(token, f"tokens_hex[{index}]")
        for index, token in enumerate(tokens)
    ]
    if len(canonical_tokens) != len(set(canonical_tokens)):
        fail("tokenizer tokens_hex contains a duplicate token")
    if canonical_tokens[:256] != list(canonical_byte_tokens()):
        fail("tokenizer must contain exactly one canonical token for each byte")

    merges = document["merges"]
    if not isinstance(merges, list) or len(merges) != len(canonical_tokens) - 256:
        fail("tokenizer merge count must match its learned tokens")
    available = set(canonical_byte_tokens())
    for rank, raw_pair in enumerate(merges):
        if not isinstance(raw_pair, list) or len(raw_pair) != 2:
            fail(f"merges[{rank}] must contain exactly two tokens")
        left = _require_canonical_token(raw_pair[0], f"merges[{rank}][0]")
        right = _require_canonical_token(raw_pair[1], f"merges[{rank}][1]")
        if left not in available or right not in available:
            fail(f"merges[{rank}] references a token unavailable at that rank")
        merged = left + right
        if len(merged) // 2 > MAXIMUM_TOKEN_BYTES:
            fail(f"merges[{rank}] exceeds the maximum token length")
        if merged in available:
            fail(f"merges[{rank}] recreates an existing token")
        if canonical_tokens[256 + rank] != merged:
            fail(f"merges[{rank}] does not produce the token assigned to its rank")
        available.add(merged)

    vocabulary_size = document["vocabulary_size"]
    if type(vocabulary_size) is not int or vocabulary_size != len(SPECIAL_TOKENS) + len(canonical_tokens):
        fail("tokenizer vocabulary_size does not match its token ids")
    if vocabulary_size > MAXIMUM_VOCABULARY_SIZE:
        fail("tokenizer vocabulary_size exceeds the bounded maximum")
    return document


@dataclass(frozen=True)
class ByteBpeTokenizer:
    """Immutable runtime view of a validated Byte-BPE artifact."""

    _document_json: str
    _tokens_hex: tuple[str, ...]
    _merges: tuple[tuple[str, str], ...]
    _vocabulary_size: int

    @classmethod
    def from_document(cls, document: Any) -> "ByteBpeTokenizer":
        validated = validate_tokenizer_document(document)
        # Keep only immutable runtime state.  The public document property
        # reconstructs a copy so callers cannot mutate tokenization in place.
        document_json = json.dumps(
            validated, sort_keys=True, separators=(",", ":")
        )
        return cls(
            _document_json=document_json,
            _tokens_hex=tuple(validated["tokens_hex"]),
            _merges=tuple(tuple(pair) for pair in validated["merges"]),
            _vocabulary_size=validated["vocabulary_size"],
        )

    @property
    def document(self) -> dict[str, Any]:
        """Return a detached serializable copy of the validated artifact."""

        return json.loads(self._document_json)

    @property
    def vocabulary_size(self) -> int:
        return self._vocabulary_size

    def encode(self, text: str, *, bos: bool = False, eos: bool = False) -> list[int]:
        payload = normalize_text(text).encode(INPUT_ENCODING)
        if len(payload) > MAXIMUM_RUNTIME_TEXT_BYTES:
            fail("text exceeds the bounded runtime tokenizer size")
        sequence = [f"{byte:02x}" for byte in payload]
        present_pairs = set(zip(sequence, sequence[1:]))
        for left, right in self._merges:
            if (left, right) not in present_pairs:
                continue
            sequence = merge_sequence(sequence, (left, right), left + right)
            present_pairs = set(zip(sequence, sequence[1:]))

        ids_by_token = {
            token: index
            for index, token in enumerate(
                self._tokens_hex, start=len(SPECIAL_TOKENS)
            )
        }
        token_ids = [BOS_TOKEN_ID] if bos else []
        token_ids.extend(ids_by_token[token] for token in sequence)
        if eos:
            token_ids.append(EOS_TOKEN_ID)
        return token_ids

    def decode(self, token_ids: Iterable[int]) -> str:
        tokens = [bytes.fromhex(token) for token in self._tokens_hex]
        output = bytearray()
        for position, token_id in enumerate(token_ids):
            if position >= MAXIMUM_DECODE_TOKEN_IDS:
                fail("token_ids exceeds the bounded decode length")
            if type(token_id) is not int:
                fail(f"token_ids[{position}] must be an integer")
            if token_id == EOS_TOKEN_ID:
                break
            if token_id in {PAD_TOKEN_ID, BOS_TOKEN_ID}:
                continue
            if token_id == UNK_TOKEN_ID:
                output.extend("�".encode(INPUT_ENCODING))
                continue
            index = token_id - len(SPECIAL_TOKENS)
            if not 0 <= index < len(tokens):
                fail(f"token_ids[{position}] is outside the tokenizer vocabulary")
            output.extend(tokens[index])
        return output.decode(INPUT_ENCODING, errors="replace")


def load_tokenizer(path: Path) -> ByteBpeTokenizer:
    size = path.stat().st_size
    if not 1 <= size <= MAXIMUM_ARTIFACT_BYTES:
        fail("tokenizer artifact size is outside the bounded range")
    raw = path.read_bytes()
    if len(raw) != size:
        fail("tokenizer artifact changed while it was being read")
    try:
        document = json.loads(raw.decode(INPUT_ENCODING))
    except UnicodeDecodeError as error:
        raise ValueError("tokenizer artifact must be valid UTF-8") from error
    return ByteBpeTokenizer.from_document(document)


def encode(
    document: dict[str, Any], text: str, *, bos: bool = False, eos: bool = False
) -> list[int]:
    return ByteBpeTokenizer.from_document(document).encode(text, bos=bos, eos=eos)


def decode(document: dict[str, Any], token_ids: Iterable[int]) -> str:
    return ByteBpeTokenizer.from_document(document).decode(token_ids)
