"""Authenticated client for the isolated Qwen coding runtime."""
from __future__ import annotations
import json
from urllib import error, request

from services.common.private_endpoints import PrivateEndpoint

class QwenClient:
    engine = "QWEN-CODER"
    def __init__(self, endpoint: str, token: str, *, pinned: PrivateEndpoint) -> None:
        # Exact-match pin on the private address configured outside Git (D-036).
        if (not isinstance(pinned, PrivateEndpoint) or pinned.name != "qwen_coder"
                or endpoint != pinned.url or len(token) < 32):
            raise ValueError("Qwen client requires the pinned private endpoint and a token")
        self.endpoint, self.token = pinned.url, token
        # Never follow a proxy from the environment: the pin must reach the
        # private endpoint directly (D-036), as the arena's ChatEngine does.
        self.opener = request.build_opener(request.ProxyHandler({}))
    def status(self) -> dict:
        try:
            with self.opener.open(request.Request(self.endpoint + "/health"), timeout=5) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (OSError, error.URLError, json.JSONDecodeError) as failure:
            raise RuntimeError("Qwen coding runtime is unavailable") from failure
        if not isinstance(value, dict):
            raise RuntimeError("Qwen coding runtime returned an invalid health response")
        return {"available": value.get("status") == "ok", "state": value.get("status", "unavailable")}
    def generate(self, prompt: str | list[dict[str, str]]) -> str:
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
        if not isinstance(messages, list) or not messages or len(messages) > 22:
            raise RuntimeError("Qwen coding runtime received an invalid conversation")
        if any(not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant"}
               or not isinstance(item.get("content"), str) for item in messages):
            raise RuntimeError("Qwen coding runtime received an invalid conversation")
        body = json.dumps({"messages": messages, "max_tokens": 512, "temperature": 0.2}, separators=(",", ":")).encode()
        target = request.Request(self.endpoint + "/v1/chat/completions", data=body, headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with self.opener.open(target, timeout=90) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (OSError, error.URLError, json.JSONDecodeError) as failure:
            raise RuntimeError("Qwen coding runtime is unavailable") from failure
        try:
            answer = value["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as failure:
            raise RuntimeError("Qwen coding runtime returned an invalid response") from failure
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Qwen coding runtime returned an invalid response")
        return answer
