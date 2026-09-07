"""Narrow authenticated client for the private CORE inference service."""

from __future__ import annotations

import json
from urllib import error, request


class CoreClient:
    engine = "CORE-700M"

    def __init__(self, endpoint: str, token: str) -> None:
        if not endpoint.startswith("http://192.168.0.143:") or len(token) < 32:
            raise ValueError("CORE client requires the private CORE endpoint and a token")
        self.endpoint, self.token = endpoint.rstrip("/"), token

    def _call(self, path: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        target = request.Request(self.endpoint + path, data=body, headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with request.urlopen(target, timeout=90) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (OSError, error.URLError, json.JSONDecodeError) as failure:
            raise RuntimeError("CORE experimental runtime is unavailable") from failure
        if not isinstance(value, dict):
            raise RuntimeError("CORE experimental runtime returned an invalid response")
        return value

    def status(self) -> dict:
        return self._call("/internal/v1/status")

    def generate(self, prompt: str) -> str:
        value = self._call("/internal/v1/generate", {"prompt": prompt, "max_new_tokens": 32, "seed": 20260907})
        if value.get("engine") != self.engine or value.get("experimental") is not True or not isinstance(value.get("answer"), str):
            raise RuntimeError("CORE experimental runtime refused the request")
        return value["answer"]
