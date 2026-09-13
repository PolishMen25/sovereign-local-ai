"""Read-only, bounded tools the local chat model may call on its own.

The assistant (14B) can decide *when* and *what* to look up: search the local
validated knowledge base, list uploaded documents, read one of them, or ask the
time.  Nothing here touches the filesystem, the shell, or the network, and no
read-only tool has a side effect.  Action tools (run_python, write_file) live in
ACTION_TOOL_SPECS: the model only PROPOSES them, ``drive`` stops on the first
such call, and nothing runs until a human approves it — an output of the model
can never confirm itself.

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
    {
        "type": "function",
        "function": {
            "name": "list_workspace",
            "description": "Liste les fichiers déjà produits dans le dossier de travail de l'assistant.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_NAMES = frozenset(spec["function"]["name"] for spec in TOOL_SPECS)

# Action tools have side effects: the model only PROPOSES them; nothing runs until
# a human approves it in the UI. The loop stops (returns "confirm") on such a call.
ACTION_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Propose du code Python à EXÉCUTER dans un bac à sable local isolé (hors ligne, "
                "sans réseau ni accès aux fichiers de l'utilisateur). Rien ne s'exécute sans la "
                "confirmation explicite de l'utilisateur. Utilise-le pour calculer, vérifier ou "
                "produire un résultat par le code plutôt que de le deviner. Écris sur la sortie standard."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Le code Python complet à exécuter."},
                    "purpose": {"type": "string", "description": "Une phrase : ce que ce code fait / pourquoi."},
                },
                "required": ["code"],
            },
        },
    },
]
ACTION_TOOL_SPECS.append({
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Propose d'ÉCRIRE un fichier texte dans le dossier de travail local de l'assistant "
            "(jamais dans les dossiers personnels de l'utilisateur). Rien n'est écrit sans sa "
            "confirmation explicite. Utilise-le pour produire un livrable (note, script, CSV, rapport) "
            "que l'utilisateur pourra ensuite télécharger."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Nom du fichier, éventuellement dans un sous-dossier (ex. 'notes/resume.md')."},
                "content": {"type": "string", "description": "Le contenu texte complet du fichier."},
                "purpose": {"type": "string", "description": "Une phrase : à quoi sert ce fichier."},
            },
            "required": ["path", "content"],
        },
    },
})
ACTION_TOOL_NAMES = frozenset(spec["function"]["name"] for spec in ACTION_TOOL_SPECS)


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


def execute_tool(name: str, raw_arguments: Any, *, knowledge: Any, embed_query: Any | None = None, workspace: Any | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Run one read-only tool. Returns (text_for_the_model, citations).

    ``embed_query`` (optional) embeds the search query for hybrid retrieval; when
    absent or failing, search stays lexical.
    """

    if name not in TOOL_NAMES:
        raise ToolError(f"outil inconnu: {name}")
    arguments = _parse_arguments(raw_arguments)

    if name == "list_workspace":
        if workspace is None:
            return "Le dossier de travail n'est pas configuré.", []
        from services.web import workspace as workspace_module  # local import keeps the module optional
        entries = workspace_module.list_files(workspace)
        if not entries:
            return "Le dossier de travail est vide (aucun fichier produit pour l'instant).", []
        lines = [f"- {item['relative']} — {item['bytes']} octets (modifié {item['modified']})" for item in entries]
        return "Fichiers du dossier de travail :\n" + "\n".join(lines), []

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
        vector = None
        if embed_query is not None:
            try:
                vector = embed_query(query.strip())
            except Exception:  # noqa: BLE001 — embedding is best-effort; fall back to lexical
                vector = None
        try:
            retrieval = knowledge.search(query.strip(), query_embedding=vector, limit=limit)
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


def _merge_citations(into: list[dict[str, Any]], seen: set[str], new: list[dict[str, Any]]) -> None:
    for citation in new:
        key = str(citation.get("provenance_id") or citation.get("document_id") or "")
        if key and key not in seen:
            seen.add(key)
            into.append(citation)


def drive(
    chat: ChatFn,
    work: list[dict[str, Any]],
    *,
    execute: ExecFn,
    action_tools: frozenset[str] = frozenset(),
    citations: list[dict[str, Any]] | None = None,
    seen_provenance: set[str] | None = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
    on_tool: OnTool | None = None,
) -> dict[str, Any]:
    """Advance the tool-calling exchange over ``work`` (mutated in place).

    Read-only tools run immediately.  The first *action* tool call stops the loop
    and is returned for human confirmation (nothing is executed); the caller
    resumes by appending the action's tool result to ``work`` and calling drive
    again.  Returns {status:'final', answer, work, citations} or
    {status:'confirm', call:{id,name,arguments}, work, citations}.
    """

    citations = citations if citations is not None else []
    seen = seen_provenance if seen_provenance is not None else set()
    offer_actions = bool(action_tools)
    for round_index in range(max_rounds):
        last_round = round_index == max_rounds - 1
        offered_actions = [spec for spec in ACTION_TOOL_SPECS if spec["function"]["name"] in action_tools]
        tools = [] if last_round else (TOOL_SPECS + offered_actions)
        assistant = chat(work, tools)
        content = assistant.get("content")
        tool_calls = assistant.get("tool_calls") or []
        if not tool_calls:
            return {"status": "final", "answer": (content or "").strip(), "work": work, "citations": citations}
        calls = tool_calls[:MAX_TOOL_CALLS_PER_ROUND]
        work.append({"role": "assistant", "content": content or "", "tool_calls": calls})
        pending: dict[str, Any] | None = None
        for call in calls:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = str(function.get("name", ""))
            call_id = call.get("id") or f"call_{round_index}_{name}"
            if name in action_tools and pending is None:
                # Stop for confirmation; its tool result is appended on resume.
                pending = {"id": call_id, "name": name, "arguments": function.get("arguments", "{}")}
                continue
            if pending is not None:
                work.append({"role": "tool", "tool_call_id": call_id, "content": "Non traité : une seule action à la fois."})
                continue
            if on_tool is not None:
                on_tool(name, call_id)
            try:
                result, new_citations = execute(name, function.get("arguments", "{}"))
            except ToolError as failure:
                result, new_citations = f"Erreur outil: {failure}", []
            _merge_citations(citations, seen, new_citations)
            work.append({"role": "tool", "tool_call_id": call_id, "content": result[:8_000]})
        if pending is not None:
            return {"status": "confirm", "call": pending, "work": work, "citations": citations}
    assistant = chat(work, [])
    return {"status": "final", "answer": (assistant.get("content") or "").strip(), "work": work, "citations": citations}


def run_tool_loop(
    chat: ChatFn,
    messages: list[dict[str, Any]],
    *,
    execute: ExecFn,
    max_rounds: int = MAX_TOOL_ROUNDS,
    on_tool: OnTool | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Read-only convenience wrapper over ``drive`` (no action tools)."""
    result = drive(chat, list(messages), execute=execute, max_rounds=max_rounds, on_tool=on_tool)
    return result["answer"], result["citations"]
