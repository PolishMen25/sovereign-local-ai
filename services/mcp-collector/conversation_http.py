"""Write-only HTTP ingress for redacted conversations.

TLS and public exposure belong to a trusted reverse proxy or tunnel. This
process binds to loopback by default and never exposes read/list operations.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import sys
from typing import Any


QUARANTINE_DIR = Path(__file__).parents[1] / "quarantine"
sys.path.insert(0, str(QUARANTINE_DIR))
from conversation_import import import_raw  # noqa: E402


MAX_BODY_BYTES = 1_048_576


def authorized(header: str | None, expected_token: str) -> bool:
    if not header or not header.startswith("Bearer ") or len(expected_token) < 32:
        return False
    return hmac.compare_digest(header[7:].encode("utf-8"), expected_token.encode("utf-8"))


def parse_submission(body: bytes) -> dict[str, Any]:
    if not body or len(body) > MAX_BODY_BYTES:
        raise ValueError("request body size is invalid")
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("request body is not valid JSON") from error
    if not isinstance(document, dict):
        raise ValueError("request body must be a JSON object")
    return document


class CollectorHandler(BaseHTTPRequestHandler):
    server_version = "SovereignConversationCollector/0.1"

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
            self.send_json(200, {"status": "ok", "mode": "write-only"})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/conversations":
            self.send_json(404, {"error": "not_found"})
            return
        expected_token = os.environ.get("SOVEREIGN_COLLECTOR_TOKEN", "")
        if not authorized(self.headers.get("Authorization"), expected_token):
            self.send_json(401, {"error": "unauthorized"})
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "unsupported_media_type"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_json(400, {"error": "invalid_content_length"})
            return
        if not 1 <= content_length <= MAX_BODY_BYTES:
            self.send_json(413, {"error": "payload_too_large"})
            return
        try:
            document = parse_submission(self.rfile.read(content_length))
            workbench = Path(os.environ["SOVEREIGN_WORKBENCH_ROOT"])
            receipt = import_raw(document, workbench)
        except KeyError:
            self.send_json(503, {"error": "collector_not_configured"})
            return
        except (OSError, ValueError):
            self.send_json(422, {"error": "submission_rejected"})
            return
        self.send_json(202, receipt)

    def log_message(self, format_string: str, *arguments: object) -> None:
        # Deliberately omit headers, bodies, query strings and client content.
        print(f"collector event status={arguments[1] if len(arguments) > 1 else 'unknown'}", file=sys.stderr, flush=True)


def main() -> int:
    host = os.environ.get("SOVEREIGN_COLLECTOR_HOST", "127.0.0.1")
    if host != "127.0.0.1":
        raise SystemExit(
            "SOVEREIGN_COLLECTOR_HOST must remain loopback-only at 127.0.0.1; "
            "put TLS/public exposure in a reverse proxy"
        )
    port = int(os.environ.get("SOVEREIGN_COLLECTOR_PORT", "8787"))
    if not os.environ.get("SOVEREIGN_COLLECTOR_TOKEN"):
        print("SOVEREIGN_COLLECTOR_TOKEN is required", file=sys.stderr)
        return 2
    if not os.environ.get("SOVEREIGN_WORKBENCH_ROOT"):
        print("SOVEREIGN_WORKBENCH_ROOT is required", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer((host, port), CollectorHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
