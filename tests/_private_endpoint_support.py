"""Synthetic private endpoints for tests (D-036).

Addresses are assembled at runtime so that the public repository stores no
private IPv4 literal (see ``test_no_private_infrastructure_identifiers``).  They
belong to no real deployment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from services.common import private_endpoints
from services.common.private_endpoints import PRIVATE_ENDPOINTS_ENV, SCHEMA_VERSION, PrivateEndpoint


def synthetic_private_host(last_octet: int) -> str:
    return ".".join(str(part) for part in (10, 20, 30, last_octet))


CORE_ENDPOINT = PrivateEndpoint("core_inference", synthetic_private_host(43), 9000)
QWEN_ENDPOINT = PrivateEndpoint("qwen_coder", synthetic_private_host(44), 8790)


def write_private_endpoints(directory: str | Path, *endpoints: PrivateEndpoint) -> dict[str, str]:
    """Write a valid private file and return the environment that designates it."""

    path = Path(directory) / "private-endpoints.json"
    document = {
        "schema_version": SCHEMA_VERSION,
        "endpoints": {item.name: {"host": item.host, "port": item.port} for item in endpoints},
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(path, 0o600)
    return {PRIVATE_ENDPOINTS_ENV: str(path)}


def trust_test_account(test: unittest.TestCase) -> None:
    """Accept files and directories owned by the unprivileged test account.

    On POSIX the loader requires root ownership; test runs (CI included) are not
    root, so each test that loads a real file substitutes its own uid for the
    duration of the test only.  Nothing changes on other platforms.
    """

    if os.name == "posix":
        patcher = patch.object(private_endpoints, "TRUSTED_OWNER_UID", os.geteuid())
        patcher.start()
        test.addCleanup(patcher.stop)
