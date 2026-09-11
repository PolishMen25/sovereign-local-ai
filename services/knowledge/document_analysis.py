"""Full-document analysis by map-reduce over its indexed chunks (local 14B).

The chat RAG only pulls the few most relevant chunks — great for a targeted
question, useless for "analyse the whole document".  Here we take every chunk of
one uploaded document, ask the local model to extract the key points of each
(map), then ask it once more to combine those notes into a complete, structured
analysis (reduce).  Bounded and offline; ``generate`` is the gateway's local
runtime, called as ``generate(messages) -> str``.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

MAP_SYSTEM = ("Tu analyses un extrait d'un document. Liste en français, en points concis, toutes les "
              "informations importantes de cet extrait (faits, chiffres, définitions, obligations). "
              "N'invente rien ; reste fidèle au texte.")
REDUCE_SYSTEM = ("Tu reçois les notes d'analyse de tous les extraits d'un document, dans l'ordre. "
                 "Produis une synthèse complète, structurée et fidèle en français : un court résumé, "
                 "puis les sections/points clés. N'invente rien et ne répète pas inutilement.")

MAX_ANALYZE_CHUNKS = 30
MAP_CHUNK_CHARS = 8_000
REDUCE_INPUT_CHARS = 24_000

Generate = Callable[[list[dict[str, str]]], str]
Progress = Callable[[int, int], None]


def analyze(generate: Generate, chunks: Sequence[dict[str, str]], *, on_progress: Progress | None = None) -> dict[str, Any]:
    if not chunks:
        raise ValueError("no chunks to analyze")
    selected = list(chunks[:MAX_ANALYZE_CHUNKS])
    notes: list[str] = []
    for index, chunk in enumerate(selected):
        content = str(chunk.get("content", ""))[:MAP_CHUNK_CHARS].strip()
        if not content:
            continue
        summary = generate([
            {"role": "system", "content": MAP_SYSTEM},
            {"role": "user", "content": content},
        ]).strip()
        notes.append(f"[Extrait {index + 1}]\n{summary}")
        if on_progress is not None:
            on_progress(index + 1, len(selected))
    if not notes:
        raise ValueError("no usable text in the document")
    combined = "\n\n".join(notes)[:REDUCE_INPUT_CHARS]
    analysis = generate([
        {"role": "system", "content": REDUCE_SYSTEM},
        {"role": "user", "content": combined},
    ]).strip()
    return {
        "analysis": analysis,
        "analyzed_chunks": len(notes),
        "total_chunks": len(chunks),
        "truncated": len(chunks) > len(selected),
    }
