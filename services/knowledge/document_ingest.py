"""Ingest an uploaded document into the local RAG (quarantine -> extract -> index).

The gateway hands raw bytes + a filename here.  We store the original under a
per-document quarantine directory, extract its text (``document_text``), split it
into chunks and index each chunk in the ``HybridKnowledgeIndex`` so the chat can
cite it.  Everything is offline; nothing trains a model.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Any

from services.knowledge.document_text import ExtractionError, extract_text

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
CHUNK_CHARS = 1200
MAX_CHUNKS = 400
SAFE_STEM = re.compile(r"[^A-Za-z0-9_-]+")


class IngestError(ValueError):
    """The upload could not be ingested (bad name, too big, or extraction failed)."""


def _document_id(filename: str) -> str:
    stem = SAFE_STEM.sub("-", Path(filename).stem).strip("-").lower()[:48] or "doc"
    return f"{stem}-{secrets.token_hex(4)}"


def _chunks(text: str) -> list[str]:
    """Split text into paragraph-aware chunks of at most CHUNK_CHARS characters."""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [text.strip()]:
        while len(paragraph) > CHUNK_CHARS:
            chunks.append(paragraph[:CHUNK_CHARS])
            paragraph = paragraph[CHUNK_CHARS:]
        if not paragraph:
            continue
        if len(current) + len(paragraph) + 2 > CHUNK_CHARS and current:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks[:MAX_CHUNKS]


def ingest(index: Any, storage_dir: Path, *, filename: str, data: bytes) -> dict[str, Any]:
    if not isinstance(filename, str) or not filename.strip() or "/" in filename or "\\" in filename:
        raise IngestError("nom de fichier invalide")
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise IngestError("fichier vide")
    if len(data) > MAX_UPLOAD_BYTES:
        raise IngestError(f"fichier trop volumineux (max {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)")

    document_id = _document_id(filename)
    quarantine = storage_dir / document_id
    quarantine.mkdir(parents=True, exist_ok=True)
    original = quarantine / ("original" + Path(filename).suffix.lower())
    original.write_bytes(bytes(data))

    try:
        text, method = extract_text(original, filename=filename)
    except ExtractionError as error:
        raise IngestError(str(error)) from error
    chunks = _chunks(text)
    if not chunks:
        raise IngestError("aucun texte exploitable dans le document")

    provenance_id = f"upload:{document_id}"
    title = filename[:300]
    for position, chunk in enumerate(chunks):
        index.upsert_validated(
            document_id=f"upload:{document_id}:{position:03d}",
            title=f"{title}" if len(chunks) == 1 else f"{title} ({position + 1}/{len(chunks)})",
            content=chunk,
            provenance_id=provenance_id,
            embedding=None,
        )
    (quarantine / "extracted.txt").write_text(text, encoding="utf-8")
    return {
        "document_id": document_id,
        "title": title,
        "provenance_id": provenance_id,
        "method": method,
        "chunks": len(chunks),
        "characters": len(text),
    }
