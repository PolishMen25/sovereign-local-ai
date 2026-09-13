"""Strict loopback-only client for the local Qwen3-Embedding runtime (llama.cpp).

Offline dense embeddings for hybrid retrieval.  The model (Qwen3-Embedding-0.6B,
Apache-2.0) is served by llama-server with ``--embedding --pooling last`` on
loopback only.  Queries carry a short retrieval instruction (recommended by the
model authors); documents are embedded verbatim.  Every failure raises
``RuntimeError`` so callers can fall back to lexical search without crashing.
"""

from __future__ import annotations

import json
import math
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 4_000_000
MAX_INPUT_CHARS = 8_000
MAX_DIMENSIONS = 1_024
QUERY_INSTRUCTION = (
    "Instruct: Retrouve dans la base de connaissances locale les passages pertinents pour la requête.\nQuery: "
)


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise RuntimeError("embedding redirect refused")


def validate_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("embedding endpoint must remain on loopback HTTP")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("embedding endpoint contains forbidden components")
    if parsed.path not in {"", "/"}:
        raise ValueError("embedding endpoint path must be empty")
    if parsed.port is None:
        raise ValueError("embedding endpoint must include an explicit port")
    return endpoint.rstrip("/")


class EmbedClient:
    engine = "EMBED"

    def __init__(self, endpoint: str = "http://127.0.0.1:8082", *, opener: Any | None = None) -> None:
        self.endpoint = validate_endpoint(endpoint)
        self.opener = opener or request.build_opener(request.ProxyHandler({}), _NoRedirect())

    def status(self) -> dict[str, Any]:
        outgoing = request.Request(f"{self.endpoint}/health", headers={"Accept": "application/json"})
        try:
            with self.opener.open(outgoing, timeout=5) as response:
                json.loads(response.read(16_384))
        except (OSError, error.URLError, error.HTTPError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError):
            return {"available": False, "state": "unavailable"}
        return {"available": True, "state": "ready"}

    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        """Return a finite embedding vector for one text. Raises RuntimeError on failure."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text to embed is empty")
        payload_text = (QUERY_INSTRUCTION + text if is_query else text)[:MAX_INPUT_CHARS + len(QUERY_INSTRUCTION)]
        body = json.dumps({"model": "embed", "input": payload_text}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        outgoing = request.Request(
            f"{self.endpoint}/v1/embeddings",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self.opener.open(outgoing, timeout=60) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, error.URLError, error.HTTPError, RuntimeError) as failure:
            raise RuntimeError("embedding runtime is unavailable") from failure
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError("embedding response exceeds the size limit")
        try:
            vector = json.loads(raw)["data"][0]["embedding"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
            raise RuntimeError("embedding response is invalid") from None
        if not isinstance(vector, list) or not 1 <= len(vector) <= MAX_DIMENSIONS:
            raise RuntimeError("embedding dimension is invalid")
        try:
            values = [float(component) for component in vector]
        except (TypeError, ValueError):
            raise RuntimeError("embedding contains a non-numeric value") from None
        if any(not math.isfinite(component) for component in values):
            raise RuntimeError("embedding contains a non-finite value")
        if math.hypot(*values) == 0:
            raise RuntimeError("embedding norm is zero")
        return values
