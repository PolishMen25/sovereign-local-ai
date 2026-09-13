#!/usr/bin/env python3
"""Backfill dense embeddings for validated chunks that have none.

Chunks indexed before the embedding runtime existed have
``embedding_dimensions = 0`` and are invisible to hybrid (vector) search.
This one-shot tool reads those rows, asks the local embedding runtime for a
vector, and re-stores them so they participate in hybrid retrieval.  Offline
and idempotent: run it again after adding documents while the embedder was down.

Run inside the gateway container, e.g.:
    SOVEREIGN_WEB_STATE=/var/lib/sovereign-gateway \\
    SOVEREIGN_EMBED_ENDPOINT=http://127.0.0.1:8082 \\
    python3 -m tools.reembed_validated_chunks
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from services.knowledge.hybrid_index import HybridKnowledgeIndex
from services.web.embed_client import EmbedClient


def main() -> int:
    state_root = Path(os.environ.get("SOVEREIGN_WEB_STATE", "/var/lib/sovereign-gateway"))
    database = state_root / "knowledge.sqlite3"
    endpoint = os.environ.get("SOVEREIGN_EMBED_ENDPOINT", "http://127.0.0.1:8082")
    if not database.exists():
        print(f"base introuvable: {database}")
        return 1

    index = HybridKnowledgeIndex(database)
    embedder = EmbedClient(endpoint)
    if not embedder.status().get("available"):
        print(f"runtime d'embeddings indisponible sur {endpoint} — démarre le service d'abord")
        return 1

    with closing(sqlite3.connect(database, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT document_id,title,content,provenance_id FROM validated_chunks "
            "WHERE embedding_dimensions = 0 ORDER BY document_id"
        ).fetchall()

    total = len(rows)
    print(f"{total} chunk(s) sans embedding à traiter")
    done = 0
    failed = 0
    for position, row in enumerate(rows, start=1):
        content = row["content"] or ""
        if not content.strip():
            continue
        try:
            vector = embedder.embed(content, is_query=False)
            index.upsert_validated(
                document_id=row["document_id"],
                title=row["title"],
                content=content,
                provenance_id=row["provenance_id"],
                embedding=vector,
            )
            done += 1
        except (RuntimeError, ValueError) as failure:
            failed += 1
            print(f"  échec sur {row['document_id']}: {failure}")
        if position % 20 == 0 or position == total:
            print(f"  {position}/{total} (ok={done}, échecs={failed})")

    print(f"terminé : {done} ré-indexés, {failed} échecs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
