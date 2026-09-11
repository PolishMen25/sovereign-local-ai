"""OpenAI-compatible chat client for the local llama.cpp engines used by the arena."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request


class EngineUnavailable(RuntimeError):
    """The engine did not answer usefully; the arena pauses and retries later."""


class ChatEngine:
    def __init__(self, name: str, endpoint: str, token: str = "", *, timeout: int = 240) -> None:
        if not endpoint.startswith(("http://127.0.0.1", "http://localhost", "http://192.168.")):
            raise ValueError("arena engines must stay on loopback or the private LAN")
        self.name, self.endpoint, self.token, self.timeout = name, endpoint.rstrip("/"), token, timeout
        # Never follow proxies from the environment: the engines are local.
        self.opener = request.build_opener(request.ProxyHandler({}))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def busy(self) -> bool:
        """True when another client (the owner's chat) is being served right now.

        Best effort: llama.cpp exposes ``/slots``; if it is disabled or refused,
        the arena assumes the engine is free.
        """

        try:
            with self.opener.open(request.Request(self.endpoint + "/slots", headers=self._headers()), timeout=5) as response:
                slots = json.load(response)
        except (OSError, error.URLError, json.JSONDecodeError, ValueError):
            return False
        return isinstance(slots, list) and any(isinstance(slot, dict) and slot.get("is_processing") for slot in slots)

    def chat(self, system_prompt: str, user_prompt: str, *, temperature: float, max_tokens: int, seed: int) -> str:
        body = json.dumps({
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": temperature, "max_tokens": max_tokens, "seed": seed, "stream": False,
        }).encode("utf-8")
        outgoing = request.Request(self.endpoint + "/v1/chat/completions", data=body, headers=self._headers())
        try:
            with self.opener.open(outgoing, timeout=self.timeout) as response:
                document: Any = json.load(response)
            content = document["choices"][0]["message"]["content"]
        except (OSError, error.URLError, json.JSONDecodeError, KeyError, IndexError, TypeError) as failure:
            raise EngineUnavailable(f"{self.name} did not answer") from failure
        if not isinstance(content, str):
            raise EngineUnavailable(f"{self.name} returned no text")
        return content
