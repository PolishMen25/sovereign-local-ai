#!/usr/bin/env python3
"""Measure lexical, vector and hybrid RAG retrieval on a gold set, offline.

The tool builds a throwaway ``HybridKnowledgeIndex`` from the gold documents
in a private work directory, then:

* runs the production ``search`` for the lexical and hybrid modes (the hybrid
  weights 0.45 lexical / 0.55 vector are hard-coded there);
* re-scores the same candidates for a sweep of the lexical weight, where
  weight 0 is the vector-only mode. At 0.45 the sweep must reproduce the
  production ranking and scores exactly, otherwise the run is refused.

The embedder is injected. From the command line it is either absent (lexical
only) or a loopback-only HTTP runtime reached through ``EmbedClient`` on a
literal loopback address. An unavailable embedder degrades to a lexical-only
report; an invalid vector is refused. The report is deterministic, carries
the input digests, no query or document text and no path. It decides
nothing: no threshold, no preferred weight.

Exit codes: 0 when a report was written, 1 when the inputs were refused
(nothing is written).
"""

from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import sys
import tempfile
from typing import Any, Iterator, Protocol, Sequence
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.knowledge import hybrid_index
from services.knowledge.hybrid_index import (
    IDENTIFIER,
    MAX_TEXT_CHARS,
    MAX_VECTOR_DIMENSIONS,
    QUERY_TERM,
    STOP_WORDS,
    HybridKnowledgeIndex,
    _decode_vector,
    _encode_vector,
    _normalized_vector,
)


REPORT_SCHEMA_VERSION = "retrieval-evaluation-report.v1"
GOLD_SCHEMA_VERSION = "retrieval-eval-gold.v1"
THRESHOLDS = "none_decided"
INTERPRETATION = "descriptive_only"

# Mirrors of the constants hard-coded in HybridKnowledgeIndex.search. A test
# pins them to the production source; the parity check pins the behaviour.
PRODUCTION_LEXICAL_PERCENT = 45
HYBRID_LEXICAL_DEPTH = 100
MAXIMUM_QUERY_TERMS = 20
SWEEP_LEXICAL_PERCENTS = (0, 10, 20, 30, 40, 45, 50, 60, 70, 80, 90, 100)

DEFAULT_K_VALUES = (1, 3, 5, 10)
MAXIMUM_K = 20
MAXIMUM_K_VALUES = 8
MAXIMUM_GOLD_BYTES = 16 * 1024 * 1024
MAXIMUM_DOCUMENTS = 10_000
MAXIMUM_QUERIES = 2_000
MAXIMUM_RELEVANT = 20
MAXIMUM_GRADE = 3
QUERY_LENGTH = (2, 500)
TITLE_LENGTH = (1, 500)

LANGUAGES = frozenset({"fr", "en", "mul"})
HEADER_KEYS = frozenset({"record_type", "schema_version", "gold_set_id", "synthetic"})
DOCUMENT_KEYS = frozenset({"record_type", "document_id", "title", "content", "provenance_id"})
QUERY_KEYS = frozenset({"record_type", "query_id", "language", "query", "relevant"})
RELEVANT_KEYS = frozenset({"document_id", "grade"})
SYNTHETIC_PROVENANCE_PREFIX = "synthetic-"
GOLD_SET_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+){0,7}$")
QUERY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DATABASE_NAME = "retrieval-eval.sqlite3"


class EvaluationRefused(ValueError):
    """A refusal whose message never embeds gold-set text."""


class _StrictJsonError(ValueError):
    pass


class Embedder(Protocol):
    def embed(self, text: str, *, is_query: bool = False) -> Sequence[float]:
        """Return one vector; raise ``RuntimeError`` when unavailable."""


def _fail(message: str) -> None:
    raise EvaluationRefused(message)


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_sha256(path: Path) -> str:
    """Digest of a source file with LF line endings, stable across checkouts."""
    return sha256_hex(path.read_bytes().replace(b"\r\n", b"\n"))


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def read_bounded_file(path: Path, *, maximum_bytes: int, context: str) -> bytes:
    """Read one regular, non-symlink file within its size bound."""
    try:
        before = os.lstat(path)
    except OSError:
        raise EvaluationRefused(f"{context} is unreadable") from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        _fail(f"{context} must be a regular file")
    if not 1 <= before.st_size <= maximum_bytes:
        _fail(f"{context} size is outside the bounded range")
    try:
        with open(path, "rb") as handle:
            payload = handle.read(maximum_bytes + 1)
    except OSError:
        raise EvaluationRefused(f"{context} is unreadable") from None
    if len(payload) != before.st_size:
        _fail(f"{context} changed while it was being read")
    return payload


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise _StrictJsonError("non-finite number")


def strict_json(text: str, context: str) -> Any:
    try:
        return json.loads(
            text, object_pairs_hook=_strict_object, parse_constant=_reject_constant
        )
    except (json.JSONDecodeError, RecursionError, _StrictJsonError):
        raise EvaluationRefused(f"{context} is not strict JSON") from None


@dataclass(frozen=True)
class GoldDocument:
    document_id: str
    provenance_id: str
    title: str = field(repr=False)
    content: str = field(repr=False)


@dataclass(frozen=True)
class GoldQuery:
    query_id: str
    language: str
    relevance: dict[str, int]
    query: str = field(repr=False)


@dataclass(frozen=True)
class GoldSet:
    gold_set_id: str
    synthetic: bool
    documents: tuple[GoldDocument, ...]
    queries: tuple[GoldQuery, ...]


def _bounded_text(value: Any, bounds: tuple[int, int]) -> bool:
    return isinstance(value, str) and bounds[0] <= len(value) <= bounds[1] and bool(value.strip())


def _parse_document(record: dict[str, Any], context: str, synthetic: bool) -> GoldDocument:
    if frozenset(record) != DOCUMENT_KEYS:
        _fail(f"{context}: document keys must be exactly {sorted(DOCUMENT_KEYS)}")
    for key in ("document_id", "provenance_id"):
        if not isinstance(record[key], str) or not IDENTIFIER.fullmatch(record[key]):
            _fail(f"{context}: {key} is invalid")
    if synthetic and not record["provenance_id"].startswith(SYNTHETIC_PROVENANCE_PREFIX):
        _fail(f"{context}: a synthetic gold set needs a synthetic- provenance_id")
    if not _bounded_text(record["title"], TITLE_LENGTH):
        _fail(f"{context}: title is invalid")
    if not _bounded_text(record["content"], (1, MAX_TEXT_CHARS)):
        _fail(f"{context}: content is invalid")
    return GoldDocument(
        document_id=record["document_id"],
        provenance_id=record["provenance_id"],
        title=record["title"],
        content=record["content"],
    )


def _parse_query(record: dict[str, Any], context: str) -> GoldQuery:
    if frozenset(record) != QUERY_KEYS:
        _fail(f"{context}: query keys must be exactly {sorted(QUERY_KEYS)}")
    if not isinstance(record["query_id"], str) or not QUERY_ID.fullmatch(record["query_id"]):
        _fail(f"{context}: query_id is invalid")
    if not isinstance(record["language"], str) or record["language"] not in LANGUAGES:
        _fail(f"{context}: language is invalid")
    if not _bounded_text(record["query"], QUERY_LENGTH):
        _fail(f"{context}: query text is outside the search bounds")
    relevant = record["relevant"]
    if not isinstance(relevant, list) or not 1 <= len(relevant) <= MAXIMUM_RELEVANT:
        _fail(f"{context}: relevant must list 1 to {MAXIMUM_RELEVANT} documents")
    relevance: dict[str, int] = {}
    for entry in relevant:
        if not isinstance(entry, dict) or frozenset(entry) != RELEVANT_KEYS:
            _fail(f"{context}: each relevant entry needs exactly document_id and grade")
        grade = entry["grade"]
        if type(grade) is not int or not 1 <= grade <= MAXIMUM_GRADE:
            _fail(f"{context}: grade must be an integer from 1 to {MAXIMUM_GRADE}")
        if not isinstance(entry["document_id"], str) or entry["document_id"] in relevance:
            _fail(f"{context}: relevant document_id is invalid or repeated")
        relevance[entry["document_id"]] = grade
    return GoldQuery(
        query_id=record["query_id"],
        language=record["language"],
        relevance=relevance,
        query=record["query"],
    )


def parse_gold_set(payload: bytes) -> GoldSet:
    """Parse the strict JSONL gold set: one header, then documents and queries."""
    if payload.startswith(b"\xef\xbb\xbf") or b"\x00" in payload:
        _fail("gold set contains a byte order mark or a NUL byte")
    try:
        lines = payload.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        raise EvaluationRefused("gold set is not valid UTF-8") from None
    if lines[-1] == "":
        lines.pop()
    if not lines:
        _fail("gold set is empty")
    header = strict_json(lines[0], "gold set line 1")
    if (
        not isinstance(header, dict)
        or frozenset(header) != HEADER_KEYS
        or header["record_type"] != "header"
    ):
        _fail("gold set line 1 must be the header record")
    if header["schema_version"] != GOLD_SCHEMA_VERSION:
        _fail("unsupported gold set schema_version")
    if not isinstance(header["gold_set_id"], str) or not GOLD_SET_ID.fullmatch(header["gold_set_id"]):
        _fail("gold_set_id is invalid")
    if not isinstance(header["synthetic"], bool):
        _fail("synthetic must be a boolean")
    documents: list[GoldDocument] = []
    queries: list[GoldQuery] = []
    for line_number, line in enumerate(lines[1:], start=2):
        context = f"gold set line {line_number}"
        record = strict_json(line, context)
        if not isinstance(record, dict) or not isinstance(record.get("record_type"), str):
            _fail(f"{context}: record must be an object with a record_type")
        if record["record_type"] == "document":
            documents.append(_parse_document(record, context, header["synthetic"]))
        elif record["record_type"] == "query":
            queries.append(_parse_query(record, context))
        else:
            _fail(f"{context}: record_type must be document or query")
        if len(documents) > MAXIMUM_DOCUMENTS or len(queries) > MAXIMUM_QUERIES:
            _fail("gold set exceeds the bounded document or query count")
    if not documents or not queries:
        _fail("gold set needs at least one document and one query")
    document_ids = [document.document_id for document in documents]
    if len(document_ids) != len(set(document_ids)):
        _fail("document_id values must be unique")
    query_ids = [query.query_id for query in queries]
    if len(query_ids) != len(set(query_ids)):
        _fail("query_id values must be unique")
    known = set(document_ids)
    for query in queries:
        if not set(query.relevance) <= known:
            _fail(f"query {query.query_id} references an unknown document")
    return GoldSet(
        gold_set_id=header["gold_set_id"],
        synthetic=header["synthetic"],
        documents=tuple(documents),
        queries=tuple(queries),
    )


def validated_vector(values: Any, expected_dimensions: int | None) -> list[float]:
    """Refuse anything the index could not store as a finite, non-zero vector."""
    if not isinstance(values, (list, tuple)):
        _fail("embedding must be a list of numbers")
    if not 1 <= len(values) <= MAX_VECTOR_DIMENSIONS:
        _fail("embedding dimension is outside the bounded range")
    if any(type(value) not in (int, float) for value in values):
        _fail("embedding contains a non-numeric value")
    vector = [float(value) for value in values]
    if any(not math.isfinite(value) for value in vector):
        _fail("embedding contains a non-finite value")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        _fail("embedding norm must be finite and non-zero")
    if expected_dimensions is not None and len(vector) != expected_dimensions:
        _fail("embedding dimensions differ between texts")
    return vector


@dataclass(frozen=True)
class GoldEmbeddings:
    dimensions: int
    documents: dict[str, list[float]]
    queries: dict[str, list[float]]

    def digest(self) -> str:
        """SHA-256 over the stored float32 form, to compare two runs."""
        digest = hashlib.sha256()
        for kind, table in (("D", self.documents), ("Q", self.queries)):
            for identifier in sorted(table):
                digest.update(f"{kind}\0{identifier}\0".encode("utf-8"))
                digest.update(_encode_vector(_normalized_vector(table[identifier])))
        return digest.hexdigest()


def embed_gold_set(embedder: Embedder, gold: GoldSet) -> GoldEmbeddings | None:
    """Embed documents verbatim and queries as queries; None if unavailable."""
    dimensions: int | None = None
    documents: dict[str, list[float]] = {}
    queries: dict[str, list[float]] = {}
    for document in gold.documents:
        try:
            raw = embedder.embed(document.content, is_query=False)
        except RuntimeError:
            return None
        documents[document.document_id] = validated_vector(raw, dimensions)
        dimensions = len(documents[document.document_id])
    for query in gold.queries:
        try:
            raw = embedder.embed(query.query, is_query=True)
        except RuntimeError:
            return None
        queries[query.query_id] = validated_vector(raw, dimensions)
    assert dimensions is not None
    return GoldEmbeddings(dimensions=dimensions, documents=documents, queries=queries)


class LoopbackEmbedder:
    """``EmbedClient`` restricted to a literal loopback address (no name lookup)."""

    def __init__(self, endpoint: str, *, opener: Any | None = None) -> None:
        from services.web.embed_client import EmbedClient

        if not isinstance(endpoint, str):
            _fail("embedding endpoint must be a string")
        try:
            host = urlsplit(endpoint).hostname or ""
            address = ipaddress.ip_address(host)
        except ValueError:
            raise EvaluationRefused("embedding endpoint must use a literal loopback address") from None
        if not address.is_loopback:
            _fail("embedding endpoint must use a literal loopback address")
        try:
            self._client = EmbedClient(endpoint, opener=opener)
        except ValueError as error:
            raise EvaluationRefused(f"embedding endpoint refused: {error}") from None

    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        return self._client.embed(text, is_query=is_query)


@contextmanager
def work_directory(parent: Path | None) -> Iterator[Path]:
    """Create a unique private directory for the throwaway index, then remove it."""
    base = Path(tempfile.gettempdir()) if parent is None else parent
    if not base.is_dir():
        _fail("work directory parent must be an existing directory")
    mode = 0o755 if os.name == "nt" else 0o700
    directory: Path | None = None
    for _ in range(32):
        candidate = base / f".retrieval-eval-{secrets.token_hex(12)}"
        try:
            candidate.mkdir(mode=mode)
        except FileExistsError:
            continue
        directory = candidate
        break
    if directory is None:
        _fail("could not allocate a work directory")
    try:
        yield directory
    finally:
        # Fail closed: a leftover index would keep gold-set text on disk.
        shutil.rmtree(directory)


def build_index(database: Path, gold: GoldSet, embeddings: GoldEmbeddings | None) -> HybridKnowledgeIndex:
    index = HybridKnowledgeIndex(database)
    index.initialize()
    for document in gold.documents:
        index.upsert_validated(
            document_id=document.document_id,
            title=document.title,
            content=document.content,
            provenance_id=document.provenance_id,
            embedding=None if embeddings is None else embeddings.documents[document.document_id],
        )
    return index


def query_terms(query: str) -> list[str]:
    """The exact term extraction of HybridKnowledgeIndex.search."""
    terms = list(dict.fromkeys(term.casefold() for term in QUERY_TERM.findall(query)))[:MAXIMUM_QUERY_TERMS]
    return [term for term in terms if term not in STOP_WORDS]


def sweep_rankings(
    database: Path, query: str, query_vector: list[float], percents: Sequence[int]
) -> dict[int, list[tuple[float, str]]]:
    """Re-score the production hybrid candidates for each lexical weight."""
    terms = query_terms(query)
    if not terms:
        return {percent: [] for percent in percents}
    fts_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    normalized_query = _normalized_vector(query_vector)
    components: list[tuple[str, float, float]] = []
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        lexical_rows = connection.execute(
            "SELECT c.document_id,bm25(validated_chunks_fts,0,3,1) AS rank FROM validated_chunks_fts "
            "JOIN validated_chunks c ON c.document_id=validated_chunks_fts.document_id "
            "WHERE validated_chunks_fts MATCH ? ORDER BY rank,c.document_id LIMIT ?",
            (fts_query, HYBRID_LEXICAL_DEPTH),
        ).fetchall()
        lexical_order = {row["document_id"]: position for position, row in enumerate(lexical_rows)}
        for row in connection.execute(
            "SELECT document_id,embedding,embedding_dimensions FROM validated_chunks "
            "WHERE embedding_dimensions=?",
            (len(normalized_query),),
        ):
            position = lexical_order.get(row["document_id"])
            lexical_score = 0.0 if position is None else 1.0 / (1 + position)
            stored = _decode_vector(row["embedding"], row["embedding_dimensions"])
            cosine = sum(left * right for left, right in zip(stored, normalized_query, strict=True))
            vector_score = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
            components.append((row["document_id"], lexical_score, vector_score))
    rankings: dict[int, list[tuple[float, str]]] = {}
    for percent in percents:
        lexical_weight = percent / 100
        vector_weight = (100 - percent) / 100
        scored = [
            (lexical_weight * lexical_score + vector_weight * vector_score, identifier)
            for identifier, lexical_score, vector_score in components
        ]
        rankings[percent] = sorted(
            (item for item in scored if item[0] > 0), key=lambda item: (-item[0], item[1])
        )
    return rankings


def query_metrics(ranked: Sequence[str], relevance: dict[str, int], k_values: Sequence[int]) -> dict[str, Any]:
    """Recall@k, reciprocal rank (cut at the largest k) and nDCG@k with graded gains."""
    depth = max(k_values)
    ranked = list(ranked[:depth])
    first = next((position for position, identifier in enumerate(ranked, start=1) if identifier in relevance), None)
    ideal = sorted(relevance.values(), reverse=True)
    recall: dict[str, float] = {}
    ndcg: dict[str, float] = {}
    for k in k_values:
        top = ranked[:k]
        recall[str(k)] = sum(1 for identifier in top if identifier in relevance) / len(relevance)
        dcg = sum(
            (2 ** relevance[identifier] - 1) / math.log2(position + 1)
            for position, identifier in enumerate(top, start=1)
            if identifier in relevance
        )
        ideal_dcg = sum((2 ** grade - 1) / math.log2(position + 1) for position, grade in enumerate(ideal[:k], start=1))
        ndcg[str(k)] = dcg / ideal_dcg
    return {
        "recall_at_k": recall,
        "reciprocal_rank": 0.0 if first is None else 1.0 / first,
        "ndcg_at_k": ndcg,
    }


def aggregate(per_query: list[tuple[GoldQuery, dict[str, Any]]], k_values: Sequence[int]) -> dict[str, Any]:
    def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "queries": len(rows),
            "recall_at_k": {str(k): _mean([row["recall_at_k"][str(k)] for row in rows]) for k in k_values},
            "mrr": _mean([row["reciprocal_rank"] for row in rows]),
            "ndcg_at_k": {str(k): _mean([row["ndcg_at_k"][str(k)] for row in rows]) for k in k_values},
        }

    languages = sorted({query.language for query, _metrics in per_query})
    return {
        "overall": summary([metrics for _query, metrics in per_query]),
        "by_language": {
            language: summary([metrics for query, metrics in per_query if query.language == language])
            for language in languages
        },
    }


def validated_k_values(values: Sequence[int]) -> tuple[int, ...]:
    if not 1 <= len(values) <= MAXIMUM_K_VALUES:
        _fail(f"between 1 and {MAXIMUM_K_VALUES} k values are required")
    if any(type(value) is not int or not 1 <= value <= MAXIMUM_K for value in values):
        _fail(f"every k must be an integer from 1 to {MAXIMUM_K}")
    if len(set(values)) != len(values):
        _fail("k values must be unique")
    return tuple(sorted(values))


def evaluate(
    *,
    gold_path: Path,
    embedder: Embedder | None = None,
    embedder_kind: str = "injected",
    embedder_label: str | None = None,
    k_values: Sequence[int] = DEFAULT_K_VALUES,
    work_parent: Path | None = None,
    gold_sha256: str | None = None,
) -> dict[str, Any]:
    k_values = validated_k_values(k_values)
    if embedder is None:
        embedder_kind, embedder_label = "none", None
    else:
        if embedder_kind not in {"injected", "loopback"}:
            _fail("embedder kind must be injected or loopback")
        if not isinstance(embedder_label, str) or not LABEL.fullmatch(embedder_label):
            _fail("embedder label must match ^[a-z0-9][a-z0-9._-]{0,63}$")
    if gold_sha256 is not None and (not isinstance(gold_sha256, str) or not SHA256.fullmatch(gold_sha256)):
        _fail("pinned gold set SHA-256 must be 64 lowercase hexadecimal characters")
    payload = read_bounded_file(gold_path, maximum_bytes=MAXIMUM_GOLD_BYTES, context="gold set")
    gold_digest = sha256_hex(payload)
    if gold_sha256 is not None and gold_digest != gold_sha256:
        _fail("gold set does not match its pinned SHA-256")
    gold = parse_gold_set(payload)

    embeddings = None if embedder is None else embed_gold_set(embedder, gold)
    if embedder is None:
        embedder_state = "not_configured"
    else:
        embedder_state = "available" if embeddings is not None else "unavailable"
    depth = max(k_values)

    lexical: list[tuple[GoldQuery, dict[str, Any]]] = []
    hybrid: list[tuple[GoldQuery, dict[str, Any]]] = []
    sweep: dict[int, list[tuple[GoldQuery, dict[str, Any]]]] = {percent: [] for percent in SWEEP_LEXICAL_PERCENTS}
    with work_directory(work_parent) as directory:
        database = directory / DATABASE_NAME
        index = build_index(database, gold, embeddings)
        for query in gold.queries:
            result = index.search(query.query, query_embedding=None, limit=depth)
            lexical.append((query, query_metrics(
                [hit["document_id"] for hit in result["hits"]], query.relevance, k_values
            )))
            if embeddings is None:
                continue
            vector = embeddings.queries[query.query_id]
            production = index.search(query.query, query_embedding=vector, limit=depth)["hits"]
            rankings = sweep_rankings(database, query.query, vector, SWEEP_LEXICAL_PERCENTS)
            mirrored = rankings[PRODUCTION_LEXICAL_PERCENT][:depth]
            if (
                [hit["document_id"] for hit in production] != [identifier for _score, identifier in mirrored]
                or [hit["score"] for hit in production] != [round(score, 6) for score, _identifier in mirrored]
            ):
                _fail(f"weight sweep diverges from HybridKnowledgeIndex.search on query {query.query_id}")
            hybrid.append((query, query_metrics(
                [hit["document_id"] for hit in production], query.relevance, k_values
            )))
            for percent, ranked in rankings.items():
                sweep[percent].append((query, query_metrics(
                    [identifier for _score, identifier in ranked], query.relevance, k_values
                )))

    unavailable = {
        "status": "unavailable",
        "reason": f"embedder_{embedder_state}",
        "fallback": "lexical",
    }
    modes: dict[str, Any] = {
        "lexical": {"status": "measured", "source": "HybridKnowledgeIndex.search", **aggregate(lexical, k_values)},
        "vector": unavailable if embeddings is None else {
            "status": "measured",
            "source": "weight_sweep_lexical_weight_0",
            "lexical_weight": 0.0,
            **aggregate(sweep[0], k_values),
        },
        "hybrid": unavailable if embeddings is None else {
            "status": "measured",
            "source": "HybridKnowledgeIndex.search",
            "lexical_weight": PRODUCTION_LEXICAL_PERCENT / 100,
            **aggregate(hybrid, k_values),
        },
    }
    weight_sweep: dict[str, Any] = (
        {"status": "unavailable", "reason": f"embedder_{embedder_state}"}
        if embeddings is None
        else {
            "status": "measured",
            "parity_with_hybrid_index": True,
            "points": [
                {
                    "lexical_weight": percent / 100,
                    "vector_weight": (100 - percent) / 100,
                    **aggregate(sweep[percent], k_values),
                }
                for percent in SWEEP_LEXICAL_PERCENTS
            ],
        }
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "thresholds": THRESHOLDS,
        "interpretation": INTERPRETATION,
        "k_values": list(k_values),
        "gold_set": {
            "sha256": gold_digest,
            "byte_size": len(payload),
            "gold_set_id": gold.gold_set_id,
            "synthetic": gold.synthetic,
            "documents": len(gold.documents),
            "queries": len(gold.queries),
            "queries_by_language": {
                language: sum(1 for query in gold.queries if query.language == language)
                for language in sorted({query.language for query in gold.queries})
            },
            "queries_without_lexical_terms": sum(1 for query in gold.queries if not query_terms(query.query)),
        },
        "retrieval_code": {
            "hybrid_index_sha256": source_sha256(Path(hybrid_index.__file__)),
            "evaluator_sha256": source_sha256(Path(__file__)),
            "production_lexical_weight": PRODUCTION_LEXICAL_PERCENT / 100,
            "production_vector_weight": (100 - PRODUCTION_LEXICAL_PERCENT) / 100,
            "hybrid_lexical_depth": HYBRID_LEXICAL_DEPTH,
        },
        "embedder": {
            "kind": embedder_kind,
            "label": embedder_label,
            "state": embedder_state,
            "dimensions": None if embeddings is None else embeddings.dimensions,
            "vectors_sha256": None if embeddings is None else embeddings.digest(),
            "model_identity_verified": False,
        },
        "modes": modes,
        "weight_sweep": weight_sweep,
    }


def write_report(path: Path, report: dict[str, Any]) -> str:
    """Write canonical JSON to a new file only; return its SHA-256."""
    payload = canonical_json_bytes(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "xb") as output:
            output.write(payload)
    except FileExistsError:
        raise EvaluationRefused("report output already exists") from None
    return sha256_hex(payload)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure lexical, vector and hybrid retrieval on a gold set (offline)."
    )
    parser.add_argument("--gold", type=Path, required=True, help="gold set JSONL")
    parser.add_argument("--gold-sha256", help="optional pinned SHA-256 of the gold set")
    parser.add_argument("--output", type=Path, required=True, help="new report file (never overwritten)")
    parser.add_argument(
        "--embed-endpoint",
        help="loopback embedding runtime, e.g. http://127.0.0.1:<port>; omit for lexical only",
    )
    parser.add_argument("--embedder-label", help="operator label of the embedding model (required with an endpoint)")
    parser.add_argument("--k", type=int, action="append", dest="k_values", help="cut-off; repeatable")
    parser.add_argument("--work-dir", type=Path, help="existing parent directory for the throwaway index")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        if arguments.output.exists() or arguments.output.is_symlink():
            _fail("report output already exists")
        if (arguments.embed_endpoint is None) != (arguments.embedder_label is None):
            _fail("--embed-endpoint and --embedder-label must be given together")
        embedder = None if arguments.embed_endpoint is None else LoopbackEmbedder(arguments.embed_endpoint)
        report = evaluate(
            gold_path=arguments.gold,
            embedder=embedder,
            embedder_kind="loopback",
            embedder_label=arguments.embedder_label,
            k_values=tuple(arguments.k_values or DEFAULT_K_VALUES),
            work_parent=arguments.work_dir,
            gold_sha256=arguments.gold_sha256,
        )
        report_sha256 = write_report(arguments.output, report)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"retrieval evaluation refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(
        {
            "embedder_state": report["embedder"]["state"],
            "queries": report["gold_set"]["queries"],
            "report_sha256": report_sha256,
        },
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
