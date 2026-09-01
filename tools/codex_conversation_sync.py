"""Queue redacted Codex transcripts for the write-only Synology collector.

The SessionEnd hook must return quickly, so it only builds local queue files
and starts a detached sender.  Failed HTTPS submissions remain queued and are
retried by the SessionStart hook or the next completed session.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable
from urllib import error, request
from urllib.parse import urlsplit
from uuid import UUID, uuid5


COLLECTOR_URL_ENV = "SOVEREIGN_COLLECTOR_URL"
COLLECTOR_ALLOWED_HOST_ENV = "SOVEREIGN_COLLECTOR_ALLOWED_HOST"
SYNC_NAMESPACE = UUID("c8e104f4-41c4-4cdb-bb39-da7624d928cf")
SCHEMA_VERSION = "0.1.0"
MAX_MESSAGE_CHARS = 45_000
MAX_QUEUED_BODY_BYTES = 850_000
MAX_HOOK_INPUT_BYTES = 65_536
MAX_HTTP_RESPONSE_BYTES = 8_192

SENSITIVE_LINE = re.compile(
    r"(?im)^.*(?:password|passwd|mdp|mot\s+de\s+passe|api[_ -]?key|access[_ -]?token|private[_ -]?key)\s*[:=].*$"
)
# Match labels even when they are embedded in a quoted block or a single-line
# JSON/code fragment rather than starting at the beginning of a text line.
SENSITIVE_INLINE = re.compile(
    r"(?i)(?:password|passwd|mdp|mot\s+de\s+passe|api[_ -]?key|access[_ -]?token|private[_ -]?key)\s*[:=][^\r\n]*"
)
BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
KNOWN_SECRET_PREFIX = re.compile(r"(?i)\b(?:sk|ghp|github_pat|glpat|xox[baprs]|cfpat)[-_][A-Za-z0-9._-]{12,}")
URL_WITH_QUERY = re.compile(r"https://[^\s<>\]\)]+[?#][^\s<>\]\)]*")
TOKEN_CANDIDATE = re.compile(r"(?<![\w])([A-Za-z0-9@#$%^&*!=+_-]{12,})(?![\w])")


def sync_home() -> Path:
    configured = os.environ.get("SOVEREIGN_SYNC_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex" / "sovereign-sync"


def configured_collector_url() -> str:
    """Return a strictly validated owner-supplied Collector endpoint."""

    raw_url = os.environ.get(COLLECTOR_URL_ENV, "").strip()
    allowed_host = os.environ.get(COLLECTOR_ALLOWED_HOST_ENV, "").strip().lower()
    if not raw_url or not allowed_host:
        raise ValueError("collector endpoint configuration is missing")
    parsed = urlsplit(raw_url)
    if parsed.scheme != "https":
        raise ValueError("collector endpoint must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("collector endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("collector endpoint must not contain query or fragment")
    if parsed.port not in {None, 443}:
        raise ValueError("collector endpoint must use the standard HTTPS port")
    if parsed.hostname is None or parsed.hostname.lower() != allowed_host:
        raise ValueError("collector endpoint hostname is not explicitly allowed")
    if parsed.path != "/v1/conversations":
        raise ValueError("collector endpoint path is invalid")
    return raw_url


def sanitize_text(text: str) -> str:
    """Remove likely credentials while preserving ordinary conversation text."""

    sanitized = text.replace("\x00", "")
    sanitized = SENSITIVE_LINE.sub("[SENSITIVE DATA REMOVED]", sanitized)
    sanitized = SENSITIVE_INLINE.sub("[SENSITIVE DATA REMOVED]", sanitized)
    sanitized = BEARER_VALUE.sub("Bearer [REDACTED]", sanitized)
    sanitized = KNOWN_SECRET_PREFIX.sub("[SENSITIVE TOKEN REMOVED]", sanitized)
    sanitized = URL_WITH_QUERY.sub("[URL QUERY REMOVED]", sanitized)

    def redact_mixed_token(match: re.Match[str]) -> str:
        value = match.group(1)
        core_classes = (
            any(char.islower() for char in value),
            any(char.isupper() for char in value),
            any(char.isdigit() for char in value),
        )
        has_symbol = any(not char.isalnum() for char in value)
        looks_secret = all(core_classes) and (len(value) >= 16 or has_symbol)
        return "[SENSITIVE TOKEN REMOVED]" if looks_secret else value

    sanitized = TOKEN_CANDIDATE.sub(redact_mixed_token, sanitized).strip()
    if len(sanitized) > MAX_MESSAGE_CHARS:
        sanitized = sanitized[: MAX_MESSAGE_CHARS - 30].rstrip() + "\n[CONTENT TRUNCATED LOCALLY]"
    return sanitized or "[EMPTY AFTER REDACTION]"


def _message_text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") not in {"input_text", "output_text"}:
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
    return "\n".join(texts)


def read_transcript(path: Path) -> tuple[str | None, str, list[dict[str, str]]]:
    """Return embedded session id, stable capture time, and visible messages."""

    embedded_session_id: str | None = None
    captured_at: str | None = None
    messages: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", errors="replace") as transcript:
        for line in transcript:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            payload = item.get("payload")
            if item.get("type") == "session_meta" and isinstance(payload, dict):
                candidate = payload.get("session_id") or payload.get("id")
                if isinstance(candidate, str) and candidate:
                    embedded_session_id = candidate
                timestamp = payload.get("timestamp") or item.get("timestamp")
                if isinstance(timestamp, str) and "T" in timestamp:
                    captured_at = timestamp
                continue
            if item.get("type") != "response_item" or not isinstance(payload, dict):
                continue
            if payload.get("type") != "message" or payload.get("role") not in {"user", "assistant"}:
                continue
            text = _message_text(payload.get("content"))
            if text:
                messages.append({"role": payload["role"], "content": sanitize_text(text)})
    if captured_at is None:
        captured_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return embedded_session_id, captured_at, messages


def _split_messages(messages: Iterable[dict[str, str]]) -> list[list[dict[str, str]]]:
    chunks: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    current_size = 256
    for message in messages:
        encoded_size = len(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if current and current_size + encoded_size > MAX_QUEUED_BODY_BYTES:
            chunks.append(current)
            current = []
            current_size = 256
        current.append(message)
        current_size += encoded_size
    if current:
        chunks.append(current)
    return chunks


def build_documents(session_id: str, captured_at: str, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    chunks = _split_messages(messages)
    session_hash = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    documents: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        conversation_id = str(uuid5(SYNC_NAMESPACE, f"{session_id}:{index}"))
        header = {
            "role": "system",
            "content": f"Codex transcript capture; source=codex; session_hash={session_hash}; chunk={index + 1}/{len(chunks)}",
        }
        documents.append(
            {
                "schema_version": SCHEMA_VERSION,
                "conversation_id": conversation_id,
                "captured_at": captured_at,
                "messages": [header, *chunk],
            }
        )
    return documents


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def queue_transcript(path: Path, supplied_session_id: str | None = None) -> int:
    embedded_session_id, captured_at, messages = read_transcript(path)
    session_id = supplied_session_id or embedded_session_id
    if not session_id or not messages:
        return 0
    home = sync_home()
    queued = 0
    for document in build_documents(session_id, captured_at, messages):
        conversation_id = document["conversation_id"]
        if (home / "receipts" / f"{conversation_id}.json").exists():
            continue
        payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(payload) >= 1_048_576:
            raise ValueError("sanitized conversation chunk exceeds collector limit")
        _atomic_write(home / "queue" / f"{conversation_id}.json", payload)
        queued += 1
    return queued


def _log(event: str) -> None:
    home = sync_home()
    home.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with (home / "sync.log").open("a", encoding="utf-8") as log:
        log.write(f"{stamp} {event}\n")


def flush_queue() -> int:
    home = sync_home()
    try:
        collector_url = configured_collector_url()
    except ValueError:
        _log("flush_skipped collector_endpoint_invalid")
        return 2
    token_path = home / "collector.token"
    if not token_path.is_file():
        _log("flush_skipped token_missing")
        return 2
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        _log("flush_skipped token_invalid")
        return 2
    # This dedicated endpoint must not inherit developer-tool proxy variables.
    # The hostname and HTTPS scheme are fixed above, so disabling ambient
    # proxies narrows the network path instead of making it configurable.
    opener = request.build_opener(request.ProxyHandler({}))
    failures = 0
    for queued_path in sorted((home / "queue").glob("*.json")) if (home / "queue").exists() else []:
        payload = queued_path.read_bytes()
        upload = request.Request(
            collector_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                # Cloudflare's Browser Integrity Check rejects urllib's default
                # Python user-agent before the request reaches the collector.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                ),
            },
            method="POST",
        )
        try:
            with opener.open(upload, timeout=20) as response:
                body = response.read(MAX_HTTP_RESPONSE_BYTES)
                if response.status != 202:
                    raise RuntimeError(f"unexpected HTTP status {response.status}")
            receipt = json.loads(body)
            safe_receipt = {
                "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "state": receipt.get("state", "accepted"),
                "conversation_id": receipt.get("conversation_id", queued_path.stem),
                "sha256": receipt.get("sha256", ""),
            }
            _atomic_write(
                home / "receipts" / f"{queued_path.stem}.json",
                json.dumps(safe_receipt, separators=(",", ":"), sort_keys=True).encode("utf-8"),
            )
            queued_path.unlink()
            _log(f"upload_accepted conversation={queued_path.stem}")
        except (OSError, ValueError, RuntimeError, error.URLError, error.HTTPError) as upload_error:
            status = getattr(upload_error, "code", "network_error")
            _log(f"upload_deferred conversation={queued_path.stem} status={status}")
            failures += 1
    return 1 if failures else 0


def spawn_flush() -> None:
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--flush"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )


def _validated_hook_path(raw_path: str) -> Path:
    path = Path(raw_path).resolve(strict=True)
    sessions_root = (Path.home() / ".codex" / "sessions").resolve(strict=True)
    if sessions_root not in path.parents or path.suffix.lower() != ".jsonl":
        raise ValueError("hook transcript path is outside the Codex sessions directory")
    return path


def handle_event() -> int:
    raw = sys.stdin.buffer.read(MAX_HOOK_INPUT_BYTES + 1)
    if len(raw) > MAX_HOOK_INPUT_BYTES:
        return 2
    event = json.loads(raw)
    if not isinstance(event, dict) or event.get("hook_event_name") != "SessionEnd":
        return 0
    transcript_path = event.get("transcript_path")
    session_id = event.get("session_id")
    if not isinstance(transcript_path, str) or not isinstance(session_id, str):
        return 2
    queued = queue_transcript(_validated_hook_path(transcript_path), session_id)
    if queued:
        spawn_flush()
    return 0


def backfill(root: Path, older_than_minutes: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    queued = 0
    for path in sorted(root.rglob("*.jsonl")):
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified <= cutoff:
            queued += queue_transcript(path)
    if queued:
        spawn_flush()
    return queued


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--event", action="store_true")
    action.add_argument("--flush", action="store_true")
    action.add_argument("--backfill", type=Path)
    parser.add_argument("--older-than-minutes", type=int, default=30)
    arguments = parser.parse_args()
    try:
        if arguments.event:
            return handle_event()
        if arguments.flush:
            return flush_queue()
        count = backfill(arguments.backfill, max(0, arguments.older_than_minutes))
        print(json.dumps({"queued": count}))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as failure:
        _log(f"sync_error type={type(failure).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
