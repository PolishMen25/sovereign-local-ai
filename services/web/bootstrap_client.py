"""Strict loopback-only client for the temporary llama.cpp BOOTSTRAP runtime."""

from __future__ import annotations

import json
from collections.abc import Iterator
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

    def status(self) -> dict[str, str | bool]:
        """Check the loopback runtime without prompting it to generate text."""
        outgoing = request.Request(f"{self.endpoint}/health", headers={"Accept": "application/json"})
        try:
            with self.opener.open(outgoing, timeout=5) as response:
                body = response.read(16_384)
            value = json.loads(body)
        except (OSError, error.URLError, error.HTTPError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError):
            return {"available": False, "state": "unavailable"}
        if not isinstance(value, dict) or value.get("status") != "ok":
            return {"available": False, "state": "invalid_health_response"}
        return {"available": True, "state": "ready"}

    def _payload(self, messages: list[dict[str, str]], max_tokens: int, *, stream: bool) -> bytes:
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
        return json.dumps(
            {
                "model": "BOOTSTRAP",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": max_tokens,
                "stream": stream,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def generate(self, messages: list[dict[str, str]], *, max_tokens: int = 512) -> str:
        payload = self._payload(messages, max_tokens, stream=False)
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

    def _tools_payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int) -> bytes:
        if not isinstance(messages, list) or not 1 <= len(messages) <= 200:
            raise ValueError("message history is invalid")
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
                raise ValueError("message shape is invalid")
            content = message.get("content")
            if content is not None and (not isinstance(content, str) or len(content) > 60_000):
                raise ValueError("message content is invalid")
        if not isinstance(tools, list) or len(tools) > 32:
            raise ValueError("tools list is invalid")
        if not isinstance(max_tokens, int) or not 1 <= max_tokens <= 2_048:
            raise ValueError("max_tokens is invalid")
        body: dict[str, Any] = {
            "model": "BOOTSTRAP",
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int = 768,
    ) -> dict[str, Any]:
        """One OpenAI-style turn that may return tool_calls. Loopback only."""
        payload = self._tools_payload(messages, tools, max_tokens)
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
            message = json.loads(body)["choices"][0]["message"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
            raise RuntimeError("bootstrap response is invalid") from None
        content = message.get("content")
        tool_calls = message.get("tool_calls") or []
        if content is not None and not isinstance(content, str):
            raise RuntimeError("bootstrap answer is invalid")
        if not isinstance(tool_calls, list):
            raise RuntimeError("bootstrap tool_calls are invalid")
        return {"content": content, "tool_calls": tool_calls}

    def stream(self, messages: list[dict[str, str]], *, max_tokens: int = 512) -> Iterator[str]:
        """Yield bounded text chunks from the loopback-only OpenAI-compatible SSE API."""
        payload = self._payload(messages, max_tokens, stream=True)
        outgoing = request.Request(
            f"{self.endpoint}/v1/chat/completions",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        total = 0
        completed = False
        try:
            with self.opener.open(outgoing, timeout=180) as response:
                for raw_line in response:
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError as failure:
                        raise RuntimeError("bootstrap stream is not UTF-8") from failure
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        raise RuntimeError("bootstrap stream is malformed")
                    data = line[5:].lstrip()
                    if data == "[DONE]":
                        completed = True
                        break
                    try:
                        value = json.loads(data)
                        delta = value["choices"][0]["delta"].get("content", "")
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as failure:
                        raise RuntimeError("bootstrap stream is malformed") from failure
                    if delta is None:
                        continue
                    if not isinstance(delta, str):
                        raise RuntimeError("bootstrap stream contains an invalid delta")
                    if not delta:
                        continue
                    total += len(delta)
                    if total > 120_000:
                        raise RuntimeError("bootstrap stream exceeds the size limit")
                    yield delta
        except (OSError, error.URLError, error.HTTPError, RuntimeError) as failure:
            raise RuntimeError("bootstrap runtime is unavailable") from failure
        if not completed or total < 1:
            raise RuntimeError("bootstrap stream ended before a valid answer")

