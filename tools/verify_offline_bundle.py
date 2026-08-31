#!/usr/bin/env python3
"""Verify an acquired wheel directory against an auditable lock manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_LOCK = (
    Path(__file__).parents[1]
    / "configs"
    / "runtime"
    / "pytorch-2.13.0-cpu-cp313-linux-x86_64.lock.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as bundle_file:
        for block in iter(lambda: bundle_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_lock(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as lock_file:
        document = json.load(lock_file)
    validate_lock(document)
    return document


def validate_lock(document: dict[str, Any]) -> None:
    if document.get("schema_version") != "0.1.0":
        raise ValueError("Unsupported bundle lock schema_version")
    if document.get("policy", {}).get("cpu_only") is not True:
        raise ValueError("The bundle lock must require CPU-only packages")
    if document.get("policy", {}).get("offline_install_only") is not True:
        raise ValueError("The bundle lock must require offline-only installation")


def verify_bundle(lock: dict[str, Any], wheel_directory: Path) -> list[str]:
    if not wheel_directory.is_dir():
        raise ValueError(f"Wheel directory does not exist: {wheel_directory}")

    bundle_root = wheel_directory.resolve(strict=True)
    packages = lock.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Bundle lock must contain at least one package")

    forbidden = tuple(
        marker.lower()
        for marker in lock.get("policy", {}).get("forbidden_filename_markers", [])
    )
    expected_names: set[str] = set()
    errors: list[str] = []

    for package in packages:
        filename = package.get("filename")
        expected_hash = package.get("sha256")
        expected_size = package.get("bytes")
        if not isinstance(filename, str) or not filename.endswith(".whl"):
            errors.append("invalid package filename in lock")
            continue
        filename_path = Path(filename)
        if (
            filename_path.is_absolute()
            or filename_path.name != filename
            or "/" in filename
            or "\\" in filename
        ):
            errors.append(f"unsafe package filename in lock: {filename}")
            continue
        if filename in expected_names:
            errors.append(f"duplicate package in lock: {filename}")
            continue
        expected_names.add(filename)

        lowered = filename.lower()
        marker = next((item for item in forbidden if item in lowered), None)
        if marker is not None:
            errors.append(f"forbidden marker {marker!r} in {filename}")
            continue

        wheel_path = wheel_directory / filename
        if wheel_path.is_symlink():
            errors.append(f"symlink wheel is forbidden: {filename}")
            continue
        resolved_wheel = wheel_path.resolve(strict=False)
        if not resolved_wheel.is_relative_to(bundle_root):
            errors.append(f"wheel escapes bundle directory: {filename}")
            continue
        if not wheel_path.is_file():
            errors.append(f"missing wheel: {filename}")
            continue
        if wheel_path.stat().st_size != expected_size:
            errors.append(f"size mismatch: {filename}")
            continue
        if _sha256(wheel_path) != expected_hash:
            errors.append(f"sha256 mismatch: {filename}")

    actual_names = {path.name for path in wheel_directory.glob("*.whl")}
    for unexpected in sorted(actual_names - expected_names):
        errors.append(f"unexpected wheel: {unexpected}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel_directory", type=Path)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lock = load_lock(args.lock)
    errors = verify_bundle(lock, args.wheel_directory)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(
        f"OK {len(lock['packages'])} wheel files match the lock; "
        "forbidden filename policy satisfied"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
