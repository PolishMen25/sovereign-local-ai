"""A deliberately narrow, stdio-only MCP Knowledge server.

This prototype reads only an approved local catalogue. It never accepts client
paths, writes to storage, opens sockets, or launches subprocesses.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from typing import Any


PROTOCOL_VERSION = "2025-06-18"
MAX_MESSAGE_BYTES = 1_048_576
MAX_QUERY_LENGTH = 120
MAX_CATALOGUE_BYTES = 1_048_576
MAX_CATALOGUE_LINES = 1_000
MAX_RESULTS = 5
TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)


def error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def result(request_id: object, value: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def tool_error(message: str) -> dict[str, object]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def configured_catalogue() -> Path:
    root = Path(os.environ.get("SOVEREIGN_KNOWLEDGE_ROOT", "workbench/validated")).resolve()
    return root / "catalogue.jsonl"


def tools() -> list[dict[str, object]]:
    return [
        {
            "name": "knowledge_status",
            "description": "Returns only the local MCP Knowledge readiness state; it does not reveal document content.",
            "inputSchema": {"type": "object", "additionalProperties": False},
        },
        {
            "name": "search_validated",
            "description": "Searches the approved local catalogue. The server returns bounded excerpts and provenance only.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {"query": {"type": "string", "minLength": 2, "maxLength": MAX_QUERY_LENGTH}},
            },
        },
    ]


def catalogue_records(catalogue: Path) -> list[dict[str, str]]:
    if not catalogue.is_file():
        return []
    if catalogue.stat().st_size > MAX_CATALOGUE_BYTES:
        raise ValueError("catalogue exceeds the configured size limit")
    records: list[dict[str, str]] = []
    with catalogue.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number > MAX_CATALOGUE_LINES:
                raise ValueError("catalogue exceeds the configured line limit")
            candidate = json.loads(line)
            if not isinstance(candidate, dict) or set(candidate) != {"document_id", "title", "summary", "provenance_id"}:
                raise ValueError("catalogue entry has an invalid shape")
            if not all(isinstance(value, str) for value in candidate.values()):
                raise ValueError("catalogue entry contains a non-text value")
            if any(len(candidate[key]) > 2_000 for key in candidate):
                raise ValueError("catalogue entry exceeds a field limit")
            records.append(candidate)
    return records


def status_tool() -> dict[str, object]:
    catalogue = configured_catalogue()
    try:
        count = len(catalogue_records(catalogue))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return tool_error("knowledge catalogue is unavailable or invalid")
    state = "ready" if catalogue.is_file() else "awaiting_validated_catalogue"
    payload = {"state": state, "catalogue_records": count, "transport": "stdio", "network": "disabled"}
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], "structuredContent": payload}


def search_tool(arguments: object) -> dict[str, object]:
    if not isinstance(arguments, dict) or set(arguments) != {"query"}:
        return tool_error("search_validated requires only a query")
    query = arguments.get("query")
    if not isinstance(query, str) or not 2 <= len(query) <= MAX_QUERY_LENGTH:
        return tool_error("query must contain between 2 and 120 characters")
    terms = set(TOKEN_PATTERN.findall(query.lower()))
    if not terms:
        return tool_error("query must contain at least one searchable term")
    try:
        records = catalogue_records(configured_catalogue())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return tool_error("knowledge catalogue is unavailable or invalid")
    ranked: list[tuple[int, dict[str, str]]] = []
    for record in records:
        haystack = f"{record['title']} {record['summary']}".lower()
        score = sum(term in haystack for term in terms)
        if score:
            ranked.append((score, record))
    ranked.sort(key=lambda item: (-item[0], item[1]["document_id"]))
    hits = [
        {"document_id": item["document_id"], "title": item["title"], "summary": item["summary"], "provenance_id": item["provenance_id"]}
        for _, item in ranked[:MAX_RESULTS]
    ]
    payload = {"hits": hits, "truncated": len(ranked) > MAX_RESULTS}
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], "structuredContent": payload}


def handle_request(message: object, initialized: bool) -> tuple[dict[str, object] | None, bool]:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return error(None, -32600, "invalid request"), initialized
    request_id = message.get("id")
    is_notification = "id" not in message
    method = message["method"]
    if method == "notifications/initialized":
        return None, True
    if method == "initialize":
        if initialized or not isinstance(message.get("params"), dict):
            return error(request_id, -32602, "invalid initialize request"), initialized
        response = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "sovereign-knowledge", "version": "0.1.0"},
            "instructions": "Local validated knowledge only. This server has no network or write capability.",
        }
        return result(request_id, response), initialized
    if method == "ping":
        return (None if is_notification else result(request_id, {})), initialized
    if not initialized:
        return error(request_id, -32002, "server is not initialized"), initialized
    if method == "tools/list":
        return result(request_id, {"tools": tools()}), initialized
    if method == "tools/call":
        parameters = message.get("params")
        if not isinstance(parameters, dict) or not isinstance(parameters.get("name"), str):
            return error(request_id, -32602, "invalid tools/call request"), initialized
        name = parameters["name"]
        if name == "knowledge_status":
            return result(request_id, status_tool()), initialized
        if name == "search_validated":
            return result(request_id, search_tool(parameters.get("arguments"))), initialized
        return error(request_id, -32602, f"unknown tool: {name}"), initialized
    return (None if is_notification else error(request_id, -32601, "method not found")), initialized


def main() -> int:
    initialized = False
    for raw_line in sys.stdin.buffer:
        if len(raw_line) > MAX_MESSAGE_BYTES:
            print(json.dumps(error(None, -32600, "message too large")), flush=True)
            continue
        try:
            message = json.loads(raw_line)
        except json.JSONDecodeError:
            print(json.dumps(error(None, -32700, "parse error")), flush=True)
            continue
        response, initialized = handle_request(message, initialized)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
