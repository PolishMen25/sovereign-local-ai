"""Loopback-only HTTP shell for the future local assistant UI.

The server is deliberately inert until an operator supplies a long bearer
token. It never proxies Internet traffic and reports inference-unavailable
until a local model runtime is approved and installed.
"""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


MAX_BODY_BYTES = 1_048_576
INDEX_HTML = """<!doctype html><meta charset='utf-8'><title>Sovereign Local AI</title>
<main><h1>Sovereign Local AI</h1><p>Interface locale en préparation.</p>
<p>Le moteur d'inférence sera disponible après installation et validation des poids locaux.</p></main>"""


def authorize(header: str | None, expected: str) -> bool:
    return bool(header and header.startswith("Bearer ") and len(expected) >= 32 and hmac.compare_digest(header[7:], expected))


def parse_chat(body: bytes) -> dict[str, Any]:
    if not body or len(body) > MAX_BODY_BYTES:
        raise ValueError("request body size is invalid")
    try:
        request = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("request body is not valid JSON") from error
    if not isinstance(request, dict) or request.get("schema_version") != "local-chat-request.v1":
        raise ValueError("unsupported chat request schema")
    if not isinstance(request.get("request_id"), str) or not 8 <= len(request["request_id"]) <= 80:
        raise ValueError("request_id is invalid")
    if not isinstance(request.get("message"), str) or not 1 <= len(request["message"]) <= 12_000:
        raise ValueError("message is invalid")
    return request


def response(request_id: str, profile_id: str, status: str, answer: str) -> dict[str, Any]:
    return {
        "schema_version": "local-assistant-response.v1",
        "request_id": request_id,
        "profile_id": profile_id,
        "status": status,
        "answer": answer,
        "citations": [],
        "proposals": [],
    }


class LocalWebHandler(BaseHTTPRequestHandler):
    server_version = "SovereignLocalWeb/0.1"

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_json(200, {"status": "ok", "mode": "loopback-only", "inference": "not_ready"})
            return
        if self.path == "/":
            encoded = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(encoded)
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/chat":
            self.send_json(404, {"error": "not_found"})
            return
        token = os.environ.get("SOVEREIGN_WEB_TOKEN", "")
        if not authorize(self.headers.get("Authorization"), token):
            self.send_json(401, {"error": "unauthorized"})
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "unsupported_media_type"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
            if not 1 <= length <= MAX_BODY_BYTES:
                self.send_json(413, {"error": "payload_too_large"})
                return
            request = parse_chat(self.rfile.read(length))
        except (ValueError, TypeError):
            self.send_json(422, {"error": "invalid_request"})
            return
        profile_id = request.get("profile_id", "coordination")
        self.send_json(503, response(request["request_id"], profile_id, "error", "local inference is not ready"))

    def log_message(self, format_string: str, *arguments: object) -> None:
        print(f"web event status={arguments[1] if len(arguments) > 1 else 'unknown'}", flush=True)


def main() -> int:
    host = os.environ.get("SOVEREIGN_WEB_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("SOVEREIGN_WEB_HOST must remain loopback-only in phase 0")
    token = os.environ.get("SOVEREIGN_WEB_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("SOVEREIGN_WEB_TOKEN is required and must contain at least 32 characters")
    server = ThreadingHTTPServer((host, int(os.environ.get("SOVEREIGN_WEB_PORT", "8765"))), LocalWebHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
