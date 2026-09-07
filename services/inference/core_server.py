"""Private HTTP boundary for the CPU-only experimental CORE runtime."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path

from services.inference.runtime import InferenceUnavailable, LocalInferenceRuntime


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        expected = self.server.token  # type: ignore[attr-defined]
        supplied = self.headers.get("Authorization", "")
        return supplied.startswith("Bearer ") and hmac.compare_digest(supplied[7:], expected)

    def _send(self, status: int, value: dict) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/internal/v1/status" or not self._authorized(): self._send(404, {"error": "not_found"}); return
        status = self.server.runtime.status()  # type: ignore[attr-defined]
        self._send(200, {"engine": status.model_name, "available": status.generation_available, "state": status.state, "experimental": True})

    def do_POST(self) -> None:
        if self.path != "/internal/v1/generate" or not self._authorized(): self._send(404, {"error": "not_found"}); return
        try:
            length = int(self.headers.get("Content-Length", "0")); payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"prompt", "max_new_tokens", "seed"}: raise ValueError
            result = self.server.runtime.generate(payload["prompt"], max_new_tokens=payload["max_new_tokens"], seed=payload["seed"])  # type: ignore[attr-defined]
        except (ValueError, TypeError): self._send(422, {"error": "invalid_request"}); return
        except InferenceUnavailable as failure: self._send(503, {"error": "checkpoint_refused", "detail": str(failure)}); return
        except RuntimeError: self._send(503, {"error": "runtime_unavailable"}); return
        self._send(200, result)

    def log_message(self, *_: object) -> None: pass


def main() -> int:
    token = os.environ.get("SOVEREIGN_CORE_TOKEN", "")
    if len(token) < 32: raise SystemExit("SOVEREIGN_CORE_TOKEN must contain at least 32 characters")
    runtime = LocalInferenceRuntime("CORE-700M", Path(os.environ["SOVEREIGN_CORE_WEIGHTS"]), config_path=Path(os.environ["SOVEREIGN_CORE_CONFIG"]), tokenizer_path=Path(os.environ["SOVEREIGN_CORE_TOKENIZER"]), manifest_path=Path(os.environ["SOVEREIGN_CORE_MANIFEST"]), preflight_path=Path(os.environ["SOVEREIGN_CORE_PREFLIGHT"]))
    server = ThreadingHTTPServer(("192.168.0.143", int(os.environ.get("SOVEREIGN_CORE_PORT", "8790"))), Handler)
    server.runtime, server.token = runtime, token  # type: ignore[attr-defined]
    server.serve_forever(); return 0


if __name__ == "__main__": raise SystemExit(main())
