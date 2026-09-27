"""Strict loader for the private infrastructure endpoints kept outside Git (D-036).

The public repository carries no internal address.  Each deployment installs a
small JSON file, named by ``SOVEREIGN_PRIVATE_ENDPOINTS_FILE``, that maps a
closed set of endpoint names to a literal private or loopback IPv4 host and a
port.  Clients keep exact-match pinning against these values and servers bind
to them; nothing falls back to a wildcard address or to a former hard-coded
value.  A missing or invalid file is a refusal, never a default.

Every error is deliberately content-free: it names the rule that failed, never
the file path nor any value read from it, so a refusal can be journaled without
publishing the private topology.

The module depends on the standard library only and runs as a script, so an
operator can validate the private file with the new revision before deploying
it (``--check``), inside each unit's own environment so that the legacy
override variables are checked too (``--legacy-env``).

A service that refuses its configuration exits with ``EXIT_CONFIGURATION_REFUSED``
(78, ``EX_CONFIG``) so that its unit can declare ``RestartPreventExitStatus=78``
instead of restarting forever on a static fault.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, NoReturn, Sequence

PRIVATE_ENDPOINTS_ENV = "SOVEREIGN_PRIVATE_ENDPOINTS_FILE"
SCHEMA_VERSION = "private-endpoints.v1"
MAXIMUM_FILE_BYTES = 16_384
ENDPOINT_NAMES = frozenset({"core_inference", "qwen_coder"})
# POSIX: the file and its directory must belong to root, so a compromised
# service account can neither rewrite its own pin nor swap the file.  Tests that
# run unprivileged substitute their own uid; nothing else changes this value.
TRUSTED_OWNER_UID = 0
# sysexits.h EX_CONFIG: a static configuration fault that a restart cannot fix.
EXIT_CONFIGURATION_REFUSED = 78
# Legacy variables still tolerated when they equal the pinned value exactly.
LEGACY_URL_VARIABLES = {"SOVEREIGN_CORE_ENDPOINT": "core_inference", "SOVEREIGN_QWEN_ENDPOINT": "qwen_coder"}
LEGACY_PORT_VARIABLES = {"SOVEREIGN_CORE_PORT": "core_inference"}
# RFC 1918 private blocks and the IPv4 loopback block.  Documentation (RFC 5737),
# shared (RFC 6598), link-local, wildcard and public addresses are refused.
ALLOWED_NETWORKS = tuple(
    ipaddress.IPv4Network(block)
    for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
)


class PrivateEndpointsError(RuntimeError):
    """The private endpoint configuration is absent or invalid (content-free message)."""


def _validate_host(value: Any) -> str:
    if not isinstance(value, str) or not value.isascii() or not 7 <= len(value) <= 15:
        raise PrivateEndpointsError("private endpoint host must be a literal IPv4 address")
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        raise PrivateEndpointsError("private endpoint host must be a literal IPv4 address") from None
    if str(address) != value:
        raise PrivateEndpointsError("private endpoint host must be a canonical IPv4 address")
    for network in ALLOWED_NETWORKS:
        if address in network:
            if address in (network.network_address, network.broadcast_address):
                raise PrivateEndpointsError("private endpoint host must not be a network or broadcast address")
            return value
    raise PrivateEndpointsError("private endpoint host must be in a private or loopback IPv4 range")


def _validate_port(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise PrivateEndpointsError("private endpoint port must be an integer between 1 and 65535")
    return value


@dataclass(frozen=True)
class PrivateEndpoint:
    """One validated endpoint; construction re-checks every field."""

    name: str
    host: str
    port: int

    def __post_init__(self) -> None:
        if self.name not in ENDPOINT_NAMES:
            raise PrivateEndpointsError("private endpoint name is not supported")
        _validate_host(self.host)
        _validate_port(self.port)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def configured_path(environ: Mapping[str, str] | None = None) -> Path:
    value = (os.environ if environ is None else environ).get(PRIVATE_ENDPOINTS_ENV, "")
    if not value:
        raise PrivateEndpointsError(f"{PRIVATE_ENDPOINTS_ENV} is not set")
    if "\x00" in value or not Path(value).is_absolute():
        raise PrivateEndpointsError(f"{PRIVATE_ENDPOINTS_ENV} must be an absolute path")
    return Path(value)


def _require_trusted_owner(status: os.stat_result, subject: str) -> None:
    if status.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise PrivateEndpointsError(f"private endpoint {subject} must not be group- or world-writable")
    if status.st_uid != TRUSTED_OWNER_UID:
        raise PrivateEndpointsError(f"private endpoint {subject} must be owned by root")


def _open_private_file(path: Path, flags: int) -> int:
    """Open the file; on POSIX, only through a checked, root-owned directory."""

    if os.name != "posix":
        return os.open(path, flags)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    try:
        _require_trusted_owner(os.fstat(directory), "directory")
        # Opened relative to the checked descriptor: the directory cannot be
        # swapped between the check and the open.
        return os.open(path.name, flags, dir_fd=directory)
    finally:
        os.close(directory)


def _read_private_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        descriptor = _open_private_file(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise PrivateEndpointsError("private endpoint file must be a regular file")
        if os.name == "posix":
            _require_trusted_owner(before, "file")
        if not 1 <= before.st_size <= MAXIMUM_FILE_BYTES:
            raise PrivateEndpointsError("private endpoint file size is outside the allowed range")
        chunks: list[bytes] = []
        total = 0
        while total <= MAXIMUM_FILE_BYTES:
            chunk = os.read(descriptor, MAXIMUM_FILE_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
    except PrivateEndpointsError:
        raise
    except (OSError, ValueError):
        raise PrivateEndpointsError("private endpoint file is unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    payload = b"".join(chunks)
    if len(payload) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise PrivateEndpointsError("private endpoint file changed while it was read")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON key")
        document[key] = value
    return document


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def parse_private_endpoints(payload: bytes) -> dict[str, PrivateEndpoint]:
    """Validate one private endpoint document; refuse anything not in the schema."""

    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise PrivateEndpointsError("private endpoint file is not strict JSON") from None
    if not isinstance(document, dict) or set(document) != {"schema_version", "endpoints"}:
        raise PrivateEndpointsError("private endpoint file must contain exactly schema_version and endpoints")
    if document["schema_version"] != SCHEMA_VERSION:
        raise PrivateEndpointsError("private endpoint schema version is not supported")
    entries = document["endpoints"]
    if not isinstance(entries, dict) or not entries:
        raise PrivateEndpointsError("private endpoint list must be a non-empty object")
    if not set(entries) <= ENDPOINT_NAMES:
        raise PrivateEndpointsError("private endpoint file names an unsupported endpoint")
    endpoints: dict[str, PrivateEndpoint] = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {"host", "port"}:
            raise PrivateEndpointsError("private endpoint entry must contain exactly host and port")
        endpoints[name] = PrivateEndpoint(name, _validate_host(entry["host"]), _validate_port(entry["port"]))
    if len({(item.host, item.port) for item in endpoints.values()}) != len(endpoints):
        raise PrivateEndpointsError("two private endpoints share the same address and port")
    return endpoints


def load_private_endpoints(environ: Mapping[str, str] | None = None) -> dict[str, PrivateEndpoint]:
    return parse_private_endpoints(_read_private_file(configured_path(environ)))


def require_endpoint(name: str, environ: Mapping[str, str] | None = None) -> PrivateEndpoint:
    if name not in ENDPOINT_NAMES:
        raise PrivateEndpointsError("private endpoint name is not supported")
    endpoints = load_private_endpoints(environ)
    if name not in endpoints:
        raise PrivateEndpointsError(f"private endpoint {name} is not configured")
    return endpoints[name]


def refuse_to_start(reason: str, *, prefix: str = "refusing to start") -> NoReturn:
    """Journal a content-free reason, then exit with EX_CONFIG (no restart loop)."""

    print(f"{prefix}: {reason}", file=sys.stderr, flush=True)
    raise SystemExit(EXIT_CONFIGURATION_REFUSED)


def endpoint_or_exit(name: str, environ: Mapping[str, str] | None = None) -> PrivateEndpoint:
    """Service entry points: refuse to start, with a content-free reason."""

    try:
        return require_endpoint(name, environ)
    except PrivateEndpointsError as failure:
        reason = str(failure)
    refuse_to_start(reason)


def check_legacy_overrides(endpoints: Mapping[str, PrivateEndpoint],
                           environ: Mapping[str, str] | None = None) -> list[str]:
    """Apply the services' start-up rule to every legacy variable present.

    A legacy URL variable must equal ``http://<host>:<port>`` exactly (no
    trailing slash, no path) and ``SOVEREIGN_CORE_PORT`` the configured port in
    decimal form, as the services require.  A legacy variable whose endpoint is
    absent from the private file is refused as well.  Returns the names of the
    variables checked; a refusal names the variable, never its value.
    """

    environ = os.environ if environ is None else environ
    checked: list[str] = []
    for variables, attribute in ((LEGACY_URL_VARIABLES, "url"), (LEGACY_PORT_VARIABLES, "port")):
        for variable, name in sorted(variables.items()):
            if variable not in environ:
                continue
            if name not in endpoints:
                raise PrivateEndpointsError(f"{variable} is set but private endpoint {name} is not configured")
            if environ[variable] != str(getattr(endpoints[name], attribute)):
                raise PrivateEndpointsError(f"{variable} does not match the pinned endpoint")
            checked.append(variable)
    return checked


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"Valide le fichier privé des points de terminaison désigné par {PRIVATE_ENDPOINTS_ENV}, sans afficher son contenu.",
    )
    parser.add_argument("--check", action="store_true", required=True, help="valider le fichier et sortir")
    parser.add_argument("--require", action="append", default=[], choices=sorted(ENDPOINT_NAMES),
                        help="point de terminaison qui doit être présent (répétable)")
    parser.add_argument("--legacy-env", action="store_true",
                        help="vérifier aussi, comme au démarrage des services, les anciennes variables présentes "
                             "dans l'environnement (" + ", ".join(sorted({**LEGACY_URL_VARIABLES, **LEGACY_PORT_VARIABLES})) + ")")
    arguments = parser.parse_args(argv)
    try:
        endpoints = load_private_endpoints()
        missing = sorted(set(arguments.require) - set(endpoints))
        if missing:
            raise PrivateEndpointsError("required private endpoint is not configured: " + ", ".join(missing))
        legacy = check_legacy_overrides(endpoints) if arguments.legacy_env else None
    except PrivateEndpointsError as failure:
        print(f"refused: {failure}", file=sys.stderr)
        return 2
    print("valid: " + ", ".join(sorted(endpoints)))
    if legacy is not None:
        print("legacy variables matching: " + (", ".join(legacy) if legacy else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
