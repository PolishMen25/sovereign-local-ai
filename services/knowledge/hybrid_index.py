"""Offline hybrid retrieval over validated text and operator-supplied embeddings.

The module never downloads or creates embeddings. A separately verified local
embedding runtime supplies finite vectors. Metadata remains in SQLite and the
vector index is rebuildable from validated records.
"""

from __future__ import annotations

from contextlib import closing
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


def _validated_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _normalized_vector(values: Iterable[float]) -> tuple[float, ...]:
    vector = tuple(float(value) for value in values)
    if not 1 <= len(vector) <= MAX_VECTOR_DIMENSIONS:
        raise ValueError("embedding dimension is invalid")
    if any(not math.isfinite(value) for value in vector):
        raise ValueError("embedding contains a non-finite value")
    norm = math.sqrt(sum(value * value for value in vector))
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

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
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
                """
            )

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
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("result limit is invalid")
        terms = QUERY_TERM.findall(query)[:20]
        if not terms:
            raise ValueError("query has no searchable terms")
        fts_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        normalized_query = None if query_embedding is None else _normalized_vector(query_embedding)

        with closing(self._connect()) as connection:
            all_rows = connection.execute(
                "SELECT document_id,title,content,provenance_id,embedding_dimensions,embedding FROM validated_chunks"
            ).fetchall()
            lexical_rows = connection.execute(
                "SELECT document_id,bm25(validated_chunks_fts) AS rank FROM validated_chunks_fts "
                "WHERE validated_chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, min(100, limit * 10)),
            ).fetchall()

        lexical_order = {row["document_id"]: index for index, row in enumerate(lexical_rows)}
        ranked: list[tuple[float, sqlite3.Row]] = []
        for row in all_rows:
            lexical_score = 0.0
            if row["document_id"] in lexical_order:
                lexical_score = 1.0 / (1.0 + lexical_order[row["document_id"]])
            vector_score = 0.0
            if normalized_query is not None:
                if row["embedding_dimensions"] == 0:
                    continue
                if row["embedding_dimensions"] != len(normalized_query):
                    continue
                stored = _decode_vector(row["embedding"], row["embedding_dimensions"])
                cosine = sum(left * right for left, right in zip(stored, normalized_query, strict=True))
                vector_score = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
            score = lexical_score if normalized_query is None else 0.45 * lexical_score + 0.55 * vector_score
            if score > 0:
                ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], item[1]["document_id"]))
        hits = [
            {
                "document_id": row["document_id"],
                "title": row["title"],
                "summary": row["content"][:2_000],
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
