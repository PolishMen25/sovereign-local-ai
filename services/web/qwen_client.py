"""Authenticated client for the isolated Qwen coding runtime."""
from __future__ import annotations
import json
from urllib import error, request

class QwenClient:
    engine = "QWEN-CODER"
    def __init__(self, endpoint: str, token: str) -> None:
        if endpoint != "http://192.168.0.144:8790" or len(token) < 32:
            raise ValueError("Qwen client requires the private endpoint and a token")
        self.endpoint, self.token = endpoint.rstrip("/"), token
    def status(self) -> dict:
        try:
            with request.urlopen(request.Request(self.endpoint + "/health"), timeout=5) as response:
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
            with request.urlopen(target, timeout=90) as response:
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
