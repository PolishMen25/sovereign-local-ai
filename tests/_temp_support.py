"""Portable temporary-directory support for local sandbox and CI tests."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import shutil
import tempfile
from typing import Iterator


@contextmanager
def sovereign_temporary_directory() -> Iterator[str]:
    """Yield an isolated directory under ``SOVEREIGN_TEST_TMP`` when set.

    Python 3.14 applies a restrictive Windows ACL for the ``0o700`` mode used
    by ``tempfile.TemporaryDirectory``.  A sandboxed child token can create
    that directory and then be denied access to it.  Under an explicit test
    root, create the unique child with an inherited Windows ACL instead.  CI
    and ordinary local runs keep the standard library implementation.
    """

    configured_root = os.environ.get("SOVEREIGN_TEST_TMP")
    if not configured_root:
        with tempfile.TemporaryDirectory() as directory:
            yield directory
        return

    root = Path(configured_root)
    root.mkdir(parents=True, exist_ok=True)
    mode = 0o755 if os.name == "nt" else 0o700
    directory: Path | None = None
    for _ in range(32):
        candidate = root / f"sovereign-test-{secrets.token_hex(12)}"
        try:
            candidate.mkdir(mode=mode)
        except FileExistsError:
            continue
        directory = candidate
        break
    if directory is None:
        raise RuntimeError("Could not allocate a unique test directory")
    try:
        yield str(directory)
    finally:
        shutil.rmtree(directory)
