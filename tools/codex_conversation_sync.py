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
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterable
from urllib import error, request
from urllib.parse import urlsplit
from uuid import UUID, uuid5


COLLECTOR_URL_ENV = "SOVEREIGN_COLLECTOR_URL"
COLLECTOR_ALLOWED_HOST_ENV = "SOVEREIGN_COLLECTOR_ALLOWED_HOST"
LOCAL_COLLECTOR_CONFIG_NAME = "collector-endpoint.json"
SYNC_NAMESPACE = UUID("c8e104f4-41c4-4cdb-bb39-da7624d928cf")
SCHEMA_VERSION = "0.1.0"
MAX_MESSAGE_CHARS = 45_000
MAX_CONVERSATION_MESSAGES = 10_000
MAX_QUEUED_BODY_BYTES = 850_000
MAX_COLLECTOR_BODY_BYTES = 1_048_576
MAX_HOOK_INPUT_BYTES = 65_536
MAX_HTTP_RESPONSE_BYTES = 8_192
MAX_LOCAL_COLLECTOR_CONFIG_BYTES = 4_096
RECEIPT_STATES = {"raw_imported", "already_imported"}

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
URL_WITH_QUERY = re.compile(
    r"https?://[^\s<>\]\)]+[?#][^\s<>\]\)]*",
    re.IGNORECASE,
)
TOKEN_CANDIDATE = re.compile(r"(?<![\w])([A-Za-z0-9@#$%^&*!=+_-]{12,})(?![\w])")
LOWERCASE_SHA256 = re.compile(r"[0-9a-f]{64}")


class _RejectRedirectHandler(request.HTTPRedirectHandler):
    """Turn every HTTP redirect into a terminal, locally handled failure."""

    def _reject_redirect(
        self,
        req: request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
    ) -> None:
        try:
            fp.close()
        except OSError:
            pass
        raise RuntimeError("collector redirect refused")

    http_error_301 = _reject_redirect
    http_error_302 = _reject_redirect
    http_error_303 = _reject_redirect
    http_error_307 = _reject_redirect
    http_error_308 = _reject_redirect


def sync_home() -> Path:
    configured = os.environ.get("SOVEREIGN_SYNC_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex" / "sovereign-sync"


def _validate_collector_endpoint(raw_url: str, allowed_host: str) -> str:
    """Validate one endpoint pair, regardless of its local configuration source."""

    raw_url = raw_url.strip()
    allowed_host = allowed_host.strip().lower()
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


def _strict_json_object(
    raw: bytes,
    *,
    context: str = "local collector configuration",
) -> dict[str, Any]:
    """Decode a small UTF-8 JSON object while rejecting duplicate keys."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, value in pairs:
            if key in decoded:
                raise ValueError(f"{context} contains duplicate fields")
            decoded[key] = value
        return decoded

    def reject_non_finite(value: str) -> Any:
        raise ValueError(f"{context} contains a non-finite JSON value")

    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_non_finite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as failure:
        raise ValueError(f"{context} is not strict UTF-8 JSON") from failure
    if not isinstance(decoded, dict):
        raise ValueError(f"{context} must be a JSON object")
    return decoded


def _read_bounded_regular_file(path: Path, maximum: int, *, context: str) -> bytes:
    """Read at most maximum + 1 bytes from one stable, non-symlink file."""

    try:
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError(f"{context} must be a regular file")
        with path.open("rb") as opened_file:
            opened = os.fstat(opened_file.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError(f"{context} must be a regular file")
            if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError(f"{context} changed while opening")
            raw = opened_file.read(maximum + 1)
    except FileNotFoundError as failure:
        raise ValueError(f"{context} is missing") from failure
    except OSError as failure:
        raise ValueError(f"{context} cannot be read safely") from failure
    if not 1 <= len(raw) <= maximum:
        raise ValueError(f"{context} size is invalid")
    return raw


def _local_collector_config() -> tuple[str, str]:
    """Load the endpoint pair from the bounded, non-symlink local file."""

    config_path = sync_home() / LOCAL_COLLECTOR_CONFIG_NAME
    try:
        initial = config_path.lstat()
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError("local collector configuration must be a regular file")
        if initial.st_size > MAX_LOCAL_COLLECTOR_CONFIG_BYTES:
            raise ValueError("local collector configuration exceeds its size limit")
        with config_path.open("rb") as config_file:
            opened = os.fstat(config_file.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("local collector configuration must be a regular file")
            if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError("local collector configuration changed while opening")
            raw = config_file.read(MAX_LOCAL_COLLECTOR_CONFIG_BYTES + 1)
    except FileNotFoundError as failure:
        raise ValueError("collector endpoint configuration is missing") from failure
    except OSError as failure:
        raise ValueError("local collector configuration cannot be read safely") from failure
    if len(raw) > MAX_LOCAL_COLLECTOR_CONFIG_BYTES:
        raise ValueError("local collector configuration exceeds its size limit")

    decoded = _strict_json_object(raw)
    expected_fields = {"collector_url", "allowed_host"}
    if set(decoded) != expected_fields:
        raise ValueError("local collector configuration fields are invalid")
    raw_url = decoded["collector_url"]
    allowed_host = decoded["allowed_host"]
    if not isinstance(raw_url, str) or not isinstance(allowed_host, str):
        raise ValueError("local collector configuration values must be strings")
    return raw_url, allowed_host


def configured_collector_url() -> str:
    """Return a strictly validated owner-supplied Collector endpoint.

    An explicitly present environment variable pair always wins.  A partial or
    empty pair fails closed instead of silently falling back to the local file.
    """

    environment_url = os.environ.get(COLLECTOR_URL_ENV)
    environment_host = os.environ.get(COLLECTOR_ALLOWED_HOST_ENV)
    if environment_url is not None or environment_host is not None:
        if environment_url is None or environment_host is None:
            raise ValueError("collector endpoint environment configuration is incomplete")
        return _validate_collector_endpoint(environment_url, environment_host)
    local_url, local_host = _local_collector_config()
    return _validate_collector_endpoint(local_url, local_host)


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


def _validate_conversation_document(
    document: dict[str, Any],
    *,
    expected_conversation_id: str,
) -> None:
    expected_fields = {"schema_version", "conversation_id", "captured_at", "messages"}
    if set(document) != expected_fields or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("queued conversation schema is invalid")
    conversation_id = document.get("conversation_id")
    if type(conversation_id) is not str or conversation_id != expected_conversation_id:
        raise ValueError("queued conversation id does not match its file")
    try:
        normalized_id = str(UUID(conversation_id))
    except (ValueError, TypeError, AttributeError) as failure:
        raise ValueError("queued conversation id is invalid") from failure
    if normalized_id != conversation_id:
        raise ValueError("queued conversation id is not canonical")
    captured_at = document.get("captured_at")
    if type(captured_at) is not str or "T" not in captured_at:
        raise ValueError("queued conversation capture time is invalid")
    messages = document.get("messages")
    if type(messages) is not list or not 1 <= len(messages) <= MAX_CONVERSATION_MESSAGES:
        raise ValueError("queued conversation message count is invalid")
    for message in messages:
        if type(message) is not dict or set(message) != {"role", "content"}:
            raise ValueError("queued conversation message schema is invalid")
        if message.get("role") not in {"user", "assistant", "system", "tool"}:
            raise ValueError("queued conversation role is invalid")
        content = message.get("content")
        if type(content) is not str or not 1 <= len(content) <= MAX_MESSAGE_CHARS:
            raise ValueError("queued conversation content size is invalid")


def _load_queued_conversation(path: Path) -> tuple[bytes, dict[str, Any]]:
    payload = _read_bounded_regular_file(
        path,
        MAX_COLLECTOR_BODY_BYTES,
        context="queued conversation",
    )
    document = _strict_json_object(payload, context="queued conversation")
    _validate_conversation_document(document, expected_conversation_id=path.stem)
    canonical_payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if payload != canonical_payload:
        raise ValueError("queued conversation is not canonically encoded")
    return payload, document


def _validate_receipt(
    receipt: dict[str, Any],
    *,
    payload: bytes,
    conversation_id: str,
    local: bool,
) -> None:
    expected_fields = {"state", "conversation_id", "sha256"}
    if local:
        expected_fields.add("received_at")
    if set(receipt) != expected_fields:
        raise ValueError("collector receipt fields are invalid")
    state = receipt.get("state")
    received_id = receipt.get("conversation_id")
    digest = receipt.get("sha256")
    if type(state) is not str or state not in RECEIPT_STATES:
        raise ValueError("collector receipt state is invalid")
    if type(received_id) is not str or received_id != conversation_id:
        raise ValueError("collector receipt id is invalid")
    if type(digest) is not str or LOWERCASE_SHA256.fullmatch(digest) is None:
        raise ValueError("collector receipt digest format is invalid")
    if digest != hashlib.sha256(payload).hexdigest():
        raise ValueError("collector receipt digest does not match payload")
    if local:
        received_at = receipt.get("received_at")
        if type(received_at) is not str:
            raise ValueError("local receipt time is invalid")
        normalized_time = received_at[:-1] + "+00:00" if received_at.endswith("Z") else received_at
        try:
            parsed_time = datetime.fromisoformat(normalized_time)
        except ValueError as failure:
            raise ValueError("local receipt time is invalid") from failure
        if parsed_time.tzinfo is None:
            raise ValueError("local receipt time must include a timezone")


def _local_receipt_matches(path: Path, *, payload: bytes, conversation_id: str) -> bool:
    try:
        raw = _read_bounded_regular_file(
            path,
            MAX_HTTP_RESPONSE_BYTES,
            context="local collector receipt",
        )
        receipt = _strict_json_object(raw, context="local collector receipt")
        _validate_receipt(
            receipt,
            payload=payload,
            conversation_id=conversation_id,
            local=True,
        )
    except ValueError:
        return False
    return True


def _validate_response_content_type(response: Any) -> None:
    headers = getattr(response, "headers", None)
    if headers is None:
        info = getattr(response, "info", None)
        headers = info() if callable(info) else None
    if headers is None:
        return
    get_content_type = getattr(headers, "get_content_type", None)
    if callable(get_content_type):
        content_type = get_content_type()
    else:
        get_header = getattr(headers, "get", None)
        if not callable(get_header):
            return
        raw_content_type = get_header("Content-Type")
        if type(raw_content_type) is not str:
            raise ValueError("collector receipt content type is missing")
        content_type = raw_content_type.split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ValueError("collector receipt content type is invalid")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        binary_file = os.fdopen(descriptor, "wb")
        descriptor = -1
        with binary_file:
            binary_file.write(data)
            binary_file.flush()
            os.fsync(binary_file.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def queue_transcript(path: Path, supplied_session_id: str | None = None) -> int:
    embedded_session_id, captured_at, messages = read_transcript(path)
    session_id = supplied_session_id or embedded_session_id
    if not session_id or not messages:
        return 0
    home = sync_home()
    queued = 0
    for document in build_documents(session_id, captured_at, messages):
        conversation_id = document["conversation_id"]
        payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if not 1 <= len(payload) <= MAX_COLLECTOR_BODY_BYTES:
            raise ValueError("sanitized conversation chunk exceeds collector limit")
        _validate_conversation_document(document, expected_conversation_id=conversation_id)
        receipt_path = home / "receipts" / f"{conversation_id}.json"
        if _local_receipt_matches(
            receipt_path,
            payload=payload,
            conversation_id=conversation_id,
        ):
            continue
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
    opener = request.build_opener(
        request.ProxyHandler({}),
        _RejectRedirectHandler(),
    )
    failures = 0
    for queued_path in sorted((home / "queue").glob("*.json")) if (home / "queue").exists() else []:
        try:
            payload, document = _load_queued_conversation(queued_path)
            conversation_id = document["conversation_id"]
            receipt_path = home / "receipts" / f"{conversation_id}.json"
            if _local_receipt_matches(
                receipt_path,
                payload=payload,
                conversation_id=conversation_id,
            ):
                queued_path.unlink()
                _log(f"queue_reconciled conversation={conversation_id}")
                continue
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
            with opener.open(upload, timeout=20) as response:
                if response.status != 202:
                    raise RuntimeError(f"unexpected HTTP status {response.status}")
                _validate_response_content_type(response)
                body = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
                if not 1 <= len(body) <= MAX_HTTP_RESPONSE_BYTES:
                    raise ValueError("collector receipt size is invalid")
            remote_receipt = _strict_json_object(body, context="remote collector receipt")
            _validate_receipt(
                remote_receipt,
                payload=payload,
                conversation_id=conversation_id,
                local=False,
            )
            local_receipt = {
                "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "state": remote_receipt["state"],
                "conversation_id": remote_receipt["conversation_id"],
                "sha256": remote_receipt["sha256"],
            }
            _atomic_write(
                receipt_path,
                json.dumps(local_receipt, separators=(",", ":"), sort_keys=True).encode("utf-8"),
            )
            if not _local_receipt_matches(
                receipt_path,
                payload=payload,
                conversation_id=conversation_id,
            ):
                raise ValueError("local collector receipt verification failed")
            queued_path.unlink()
            _log(f"upload_accepted conversation={conversation_id}")
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
