"""Strict loopback-only client for the temporary llama.cpp BOOTSTRAP runtime."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 2_000_000


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise RuntimeError("bootstrap redirect refused")


def validate_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("bootstrap endpoint must remain on loopback HTTP")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("bootstrap endpoint contains forbidden components")
    if parsed.path not in {"", "/"}:
        raise ValueError("bootstrap endpoint path must be empty")
    if parsed.port is None:
        raise ValueError("bootstrap endpoint must include an explicit port")
    return endpoint.rstrip("/")


class BootstrapClient:
    engine = "BOOTSTRAP"

    def __init__(self, endpoint: str = "http://127.0.0.1:8080", *, opener: Any | None = None) -> None:
        self.endpoint = validate_endpoint(endpoint)
        self.opener = opener or request.build_opener(request.ProxyHandler({}), _NoRedirect())

    def generate(self, messages: list[dict[str, str]], *, max_tokens: int = 512) -> str:
        if not isinstance(messages, list) or not 1 <= len(messages) <= 200:
            raise ValueError("message history is invalid")
        for message in messages:
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ValueError("message shape is invalid")
            if message["role"] not in {"system", "user", "assistant"}:
                raise ValueError("message role is invalid")
            if not isinstance(message["content"], str) or not 1 <= len(message["content"]) <= 45_000:
                raise ValueError("message content is invalid")
        if not isinstance(max_tokens, int) or not 1 <= max_tokens <= 2_048:
            raise ValueError("max_tokens is invalid")
        payload = json.dumps(
            {
                "model": "BOOTSTRAP",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": max_tokens,
                "stream": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        outgoing = request.Request(
            f"{self.endpoint}/v1/chat/completions",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self.opener.open(outgoing, timeout=180) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, error.URLError, error.HTTPError, RuntimeError) as failure:
            raise RuntimeError("bootstrap runtime is unavailable") from failure
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("bootstrap response exceeds the size limit")
        try:
            decoded = json.loads(body)
            answer = decoded["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
            raise RuntimeError("bootstrap response is invalid") from None
        if not isinstance(answer, str) or not 1 <= len(answer) <= 120_000:
            raise RuntimeError("bootstrap answer is invalid")
        return answer

