"""Offline hybrid retrieval over validated text and operator-supplied embeddings.

The module never downloads or creates embeddings. A separately verified local
embedding runtime supplies finite vectors. Metadata remains in SQLite and the
vector index is rebuildable from validated records.
"""

from __future__ import annotations

from contextlib import closing
import heapq
from itertools import islice
import math
from pathlib import Path
import re
import sqlite3
import struct
from typing import Any, Iterable


IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")
QUERY_TERM = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9_+#.-]{2,}")
MAX_TEXT_CHARS = 120_000
MAX_VECTOR_DIMENSIONS = 1_024
MAX_SUMMARY_CHARS = 2_000
STOP_WORDS = frozenset(
    "a an and are as at be by can do for from how in is it of on or that the this to was what with "
    "au aux avec ce ces comment dans de des du elle en est et il je la le les leur lui ma mes mon "
    "ne nos nous on ou par pas peut pour que quel quelle quels quelles qui sa se ses son sur ta "
    "tes ton tu un une vos votre vous".split()
)


def _validated_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _normalized_vector(values: Iterable[float]) -> tuple[float, ...]:
    vector = tuple(float(value) for value in islice(values, MAX_VECTOR_DIMENSIONS + 1))
    if not 1 <= len(vector) <= MAX_VECTOR_DIMENSIONS:
        raise ValueError("embedding dimension is invalid")
    if any(not math.isfinite(value) for value in vector):
        raise ValueError("embedding contains a non-finite value")
    norm = math.hypot(*vector)
    if norm == 0:
        raise ValueError("embedding norm must be non-zero")
    return tuple(value / norm for value in vector)


def _encode_vector(vector: tuple[float, ...]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _decode_vector(payload: bytes, dimensions: int) -> tuple[float, ...]:
    if len(payload) != dimensions * 4:
        raise ValueError("stored embedding size is invalid")
    return struct.unpack(f"<{dimensions}f", payload)


class HybridKnowledgeIndex:
    def __init__(self, database: Path) -> None:
        self.database = database

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(self.database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        else:
            self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS validated_chunks (
                    document_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provenance_id TEXT NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    embedding BLOB NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS validated_chunks_fts USING fts5(
                    document_id UNINDEXED,
                    title,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TABLE IF NOT EXISTS knowledge_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def set_metadata(self, key: str, value: str) -> None:
        key = _validated_identifier(key, "metadata key")
        if not isinstance(value, str) or not value or len(value) > 500:
            raise ValueError("metadata value is invalid")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO knowledge_metadata(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def status(self) -> dict[str, Any]:
        """Return a small, content-free view suitable for an authenticated UI."""
        try:
            with closing(self._connect(read_only=True)) as connection:
                count = int(connection.execute("SELECT COUNT(*) FROM validated_chunks").fetchone()[0])
        except (OSError, sqlite3.Error):
            return {"ready": False, "state": "unavailable", "mode": "lexical", "documents": 0}
        return {
            "ready": count > 0,
            "state": "ready" if count > 0 else "empty",
            "mode": "lexical",
            "documents": count,
        }

    def upsert_validated(
        self,
        *,
        document_id: str,
        title: str,
        content: str,
        provenance_id: str,
        embedding: Iterable[float] | None,
    ) -> None:
        document_id = _validated_identifier(document_id, "document_id")
        provenance_id = _validated_identifier(provenance_id, "provenance_id")
        if not isinstance(title, str) or not 1 <= len(title) <= 500:
            raise ValueError("title is invalid")
        if not isinstance(content, str) or not 1 <= len(content) <= MAX_TEXT_CHARS:
            raise ValueError("content is invalid")
        vector = None if embedding is None else _normalized_vector(embedding)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM validated_chunks_fts WHERE document_id = ?", (document_id,))
            connection.execute(
                "INSERT INTO validated_chunks(document_id,title,content,provenance_id,embedding_dimensions,embedding) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET "
                "title=excluded.title,content=excluded.content,provenance_id=excluded.provenance_id,"
                "embedding_dimensions=excluded.embedding_dimensions,embedding=excluded.embedding",
                (document_id, title, content, provenance_id, 0 if vector is None else len(vector), b"" if vector is None else _encode_vector(vector)),
            )
            connection.execute(
                "INSERT INTO validated_chunks_fts(document_id,title,content) VALUES(?,?,?)",
                (document_id, title, content),
            )

    def search(
        self,
        query: str,
        *,
        query_embedding: Iterable[float] | None,
        limit: int = 5,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not 2 <= len(query) <= 500:
            raise ValueError("query is invalid")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("result limit is invalid")
        terms = list(dict.fromkeys(term.casefold() for term in QUERY_TERM.findall(query)))[:20]
        terms = [term for term in terms if term not in STOP_WORDS]
        if not terms:
            return {"mode": "hybrid" if query_embedding is not None else "lexical", "hits": [], "truncated": False}
        fts_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        normalized_query = None if query_embedding is None else _normalized_vector(query_embedding)

        with closing(self._connect(read_only=True)) as connection:
            lexical_rows = connection.execute(
                "SELECT c.document_id,c.title,c.provenance_id,"
                "snippet(validated_chunks_fts,2,'','',' … ',48) AS summary,"
                "bm25(validated_chunks_fts,0,3,1) AS rank FROM validated_chunks_fts "
                "JOIN validated_chunks c ON c.document_id=validated_chunks_fts.document_id "
                "WHERE validated_chunks_fts MATCH ? ORDER BY rank,c.document_id LIMIT ?",
                (fts_query, limit + 1 if normalized_query is None else 100),
            ).fetchall()
            if normalized_query is None:
                ranked = [(1.0 / (1 + position), row) for position, row in enumerate(lexical_rows)]
            else:
                lexical_order = {row["document_id"]: position for position, row in enumerate(lexical_rows)}
                summaries = {row["document_id"]: row["summary"] for row in lexical_rows}

                def vector_candidates() -> Iterable[tuple[float, str]]:
                    # Exact CPU scoring streams only embeddings; whole documents
                    # are fetched for the selected results, never for lexical search.
                    rows = connection.execute(
                        "SELECT document_id,embedding,embedding_dimensions FROM validated_chunks "
                        "WHERE embedding_dimensions=?", (len(normalized_query),)
                    )
                    for row in rows:
                        position = lexical_order.get(row["document_id"])
                        lexical_score = 0.0 if position is None else 1.0 / (1 + position)
                        stored = _decode_vector(row["embedding"], row["embedding_dimensions"])
                        cosine = sum(left * right for left, right in zip(stored, normalized_query, strict=True))
                        vector_score = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
                        score = 0.45 * lexical_score + 0.55 * vector_score
                        if score > 0:
                            yield score, row["document_id"]

                selected = heapq.nsmallest(limit + 1, vector_candidates(), key=lambda item: (-item[0], item[1]))
                ranked = []
                for score, identifier in selected:
                    row = dict(connection.execute(
                        "SELECT document_id,title,content,provenance_id FROM validated_chunks WHERE document_id=?",
                        (identifier,),
                    ).fetchone())
                    row["summary"] = summaries.get(identifier, row["content"][:MAX_SUMMARY_CHARS])
                    ranked.append((score, row))
        hits = [
            {
                "document_id": row["document_id"],
                "title": row["title"],
                "summary": row["summary"][:MAX_SUMMARY_CHARS],
                "provenance_id": row["provenance_id"],
                "score": round(score, 6),
            }
            for score, row in ranked[:limit]
        ]
        return {
            "mode": "hybrid" if normalized_query is not None else "lexical",
            "hits": hits,
            "truncated": len(ranked) > limit,
        }
