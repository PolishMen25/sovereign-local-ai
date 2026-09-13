"""Read-only, bounded tools the local chat model may call on its own.

The assistant (14B) can decide *when* and *what* to look up: search the local
validated knowledge base, list uploaded documents, read one of them, or ask the
time.  Nothing here touches the filesystem, the shell, or the network, and no
tool has a side effect — an output of the model can never change state or run a
command.  Side-effectful tools (run code, write a file) are deliberately out of
scope for this version and must go behind an explicit human confirmation.

The loop is pure: ``run_tool_loop`` takes a ``chat`` callable
(``chat(messages, tools) -> assistant_message``) and an ``execute`` callable, so
it is unit-tested with a fake runtime and a fake knowledge index.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable

UPLOAD_PROVENANCE = re.compile(r"^upload:[A-Za-z0-9_-]{1,120}$")

SEARCH_MAX_LIMIT = 6
READ_MAX_CHARS = 6_000
LIST_MAX_DOCUMENTS = 50
MAX_TOOL_ROUNDS = 4
MAX_TOOL_CALLS_PER_ROUND = 4
MAX_ARGUMENTS_BYTES = 4_000

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Cherche dans la base de connaissances locale validée et les documents partagés "
                "(recherche plein-texte). À utiliser dès que la question porte sur les documents, "
                "le projet ou des faits locaux. Renvoie des extraits avec leur provenance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termes de recherche (2 à 500 caractères)."},
                    "limit": {"type": "integer", "description": "Nombre max d'extraits (1 à 6).", "minimum": 1, "maximum": SEARCH_MAX_LIMIT},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "Liste les documents que l'utilisateur a partagés et qui sont indexés localement.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "Lit le début d'un document partagé identifié par son provenance_id "
                "(de la forme 'upload:...', obtenu via list_documents ou search_knowledge)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provenance_id": {"type": "string", "description": "Identifiant 'upload:...' du document."},
                },
                "required": ["provenance_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_time",
            "description": "Donne la date et l'heure actuelles du serveur.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_NAMES = frozenset(spec["function"]["name"] for spec in TOOL_SPECS)


class ToolError(Exception):
    """A tool could not run with the arguments given (reported back to the model)."""


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        arguments = raw
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > MAX_ARGUMENTS_BYTES:
            raise ToolError("arguments trop volumineux")
        try:
            arguments = json.loads(raw or "{}")
        except (json.JSONDecodeError, ValueError):
            raise ToolError("arguments JSON invalides") from None
    else:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolError("les arguments doivent être un objet")
    return arguments


def execute_tool(name: str, raw_arguments: Any, *, knowledge: Any) -> tuple[str, list[dict[str, Any]]]:
    """Run one read-only tool. Returns (text_for_the_model, citations)."""

    if name not in TOOL_NAMES:
        raise ToolError(f"outil inconnu: {name}")
    arguments = _parse_arguments(raw_arguments)

    if name == "current_time":
        now = datetime.now(timezone.utc).astimezone()
        return f"Date et heure du serveur : {now.strftime('%A %d %B %Y, %H:%M:%S %Z')} (ISO {now.isoformat(timespec='seconds')}).", []

    if name == "search_knowledge":
        query = arguments.get("query")
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 500:
            raise ToolError("'query' doit faire de 2 à 500 caractères")
        limit = arguments.get("limit", SEARCH_MAX_LIMIT)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= SEARCH_MAX_LIMIT:
            limit = SEARCH_MAX_LIMIT
        try:
            retrieval = knowledge.search(query.strip(), query_embedding=None, limit=limit)
        except ValueError as failure:
            raise ToolError(f"recherche refusée : {failure}") from None
        hits = retrieval.get("hits", [])
        if not hits:
            return "Aucun extrait local ne correspond à cette recherche.", []
        lines = []
        citations = []
        for index, hit in enumerate(hits):
            title = str(hit.get("title", "Document"))[:240]
            provenance = str(hit.get("provenance_id", ""))[:200]
            summary = str(hit.get("summary", ""))[:600]
            lines.append(f"[{index + 1}] {title} (provenance: {provenance})\n{summary}")
            citations.append({
                "document_id": str(hit.get("document_id", ""))[:160],
                "title": title,
                "provenance_id": hit.get("provenance_id", ""),
            })
        return "\n\n".join(lines), citations

    if name == "list_documents":
        try:
            documents = knowledge.documents()[:LIST_MAX_DOCUMENTS]
        except (ValueError, AttributeError):
            documents = []
        if not documents:
            return "Aucun document partagé n'est indexé pour le moment.", []
        lines = [
            f"- {str(doc.get('title', 'Document'))[:200]} — {doc.get('chunks', 0)} passage(s), "
            f"{doc.get('characters', 0)} caractères (provenance: {doc.get('provenance_id', '')})"
            for doc in documents
        ]
        return "Documents partagés indexés :\n" + "\n".join(lines), []

    if name == "read_document":
        provenance_id = arguments.get("provenance_id")
        if not isinstance(provenance_id, str) or UPLOAD_PROVENANCE.fullmatch(provenance_id) is None:
            raise ToolError("'provenance_id' doit être de la forme 'upload:...'")
        try:
            chunks = knowledge.chunks_for_provenance(provenance_id)
        except (ValueError, AttributeError):
            chunks = []
        if not chunks:
            raise ToolError("aucun document ne correspond à ce provenance_id")
        title = str(chunks[0].get("title", "Document"))[:240]
        text = ""
        for chunk in chunks:
            text += str(chunk.get("content", ""))
            if len(text) >= READ_MAX_CHARS:
                break
        truncated = len(text) > READ_MAX_CHARS or len(chunks) > 1 and len(text) >= READ_MAX_CHARS
        body = text[:READ_MAX_CHARS]
        note = "\n\n[…document tronqué ; utilise search_knowledge pour cibler une partie précise.]" if truncated else ""
        citations = [{"document_id": str(chunks[0].get("document_id", ""))[:160], "title": title, "provenance_id": provenance_id}]
        return f"Contenu de « {title} » :\n{body}{note}", citations

    raise ToolError(f"outil non implémenté: {name}")  # pragma: no cover


ChatFn = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
ExecFn = Callable[[str, Any], tuple[str, list[dict[str, Any]]]]
OnTool = Callable[[str, str], None]


def run_tool_loop(
    chat: ChatFn,
    messages: list[dict[str, Any]],
    *,
    execute: ExecFn,
    max_rounds: int = MAX_TOOL_ROUNDS,
    on_tool: OnTool | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Drive a multi-turn tool-calling exchange and return (final_answer, citations).

    ``chat(messages, tools)`` returns an assistant message dict with optional
    ``content`` and ``tool_calls``.  On the last allowed round tools are withheld
    so the model must produce a final textual answer.
    """

    work = list(messages)
    citations: list[dict[str, Any]] = []
    seen_provenance: set[str] = set()
    for round_index in range(max_rounds):
        tools = TOOL_SPECS if round_index < max_rounds - 1 else []
        assistant = chat(work, tools)
        content = assistant.get("content")
        tool_calls = assistant.get("tool_calls") or []
        if not tool_calls:
            return (content or "").strip(), citations
        # Record the assistant turn verbatim so tool results attach to it.
        work.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls[:MAX_TOOL_CALLS_PER_ROUND]})
        for call in tool_calls[:MAX_TOOL_CALLS_PER_ROUND]:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = function.get("name", "")
            call_id = call.get("id") or f"call_{round_index}_{name}"
            if on_tool is not None:
                on_tool(str(name), call_id)
            try:
                result, new_citations = execute(str(name), function.get("arguments", "{}"))
            except ToolError as failure:
                result, new_citations = f"Erreur outil: {failure}", []
            for citation in new_citations:
                key = str(citation.get("provenance_id") or citation.get("document_id") or "")
                if key and key not in seen_provenance:
                    seen_provenance.add(key)
                    citations.append(citation)
            work.append({"role": "tool", "tool_call_id": call_id, "content": result[:8_000]})
    # Exhausted rounds without a final answer: ask once more with no tools.
    assistant = chat(work, [])
    return (assistant.get("content") or "").strip(), citations
