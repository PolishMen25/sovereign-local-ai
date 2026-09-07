#!/usr/bin/env python3
"""Produce one bounded, offline CORE-MINI CPU/NUMA placement proof."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import selectors
import signal
import socket
import stat
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Callable
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# The benchmark is started by a transient systemd unit, whose working directory
# is not the repository.  Make the repository importable explicitly rather than
# relying on the caller's current directory.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TRAINER = PROJECT_ROOT / "tools" / "train_core_mini.py"
SUMMARIZER = PROJECT_ROOT / "tools" / "summarize_training_metrics.py"
VERIFIER = PROJECT_ROOT / "tools" / "verify_core_checkpoint_compatibility.py"
CHILD_WRAPPER = PROJECT_ROOT / "tools" / "core_mini_numa_child.py"
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "models" / "core-mini.candidate.json"
RUNTIME_LOCK = (
    PROJECT_ROOT
    / "configs"
    / "runtime"
    / "pytorch-2.13.0-cpu-cp313-linux-x86_64.lock.json"
)
NUMPY_RUNTIME_LOCK = (
    PROJECT_ROOT
    / "configs"
    / "runtime"
    / "numpy-2.5.2-cpu-cp313-linux-x86_64.lock.json"
)

EVIDENCE_TYPE = "single-placement-run-proof"
MAXIMUM_SOURCE_BYTES = 2 * 1024 * 1024
MAXIMUM_SOURCE_ARCHIVE_BYTES = 64 * 1024 * 1024
MAXIMUM_SOURCE_TREE_BYTES = 64 * 1024 * 1024
MAXIMUM_SOURCE_MEMBERS = 2048
MAXIMUM_CHECKPOINT_BYTES = 256 * 1024 * 1024
MAXIMUM_METRICS_BYTES = 64 * 1024 * 1024
MAXIMUM_CHILD_OUTPUT_BYTES = 256 * 1024
MAXIMUM_ID_ITEMS = 4096
MAXIMUM_NUMA_NODES = 4096
MINIMUM_REPETITIONS = 3
MAXIMUM_REPETITIONS = 10
MINIMUM_STEPS = 6
MAXIMUM_STEPS = 1000
MINIMUM_TIMEOUT_SECONDS = 30
MAXIMUM_TIMEOUT_SECONDS = 3600
PRIVATE_DIRECTORY_MODE = 0o755 if os.name == "nt" else 0o700
SOURCE_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
SAFE_VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}")

MEMORY_POLICY_MODES = {
    1: "preferred",
    2: "bind",
    3: "interleave",
    4: "local",
}
PLACEMENT_IDS = ("placement-a", "placement-b")
SESSION_ID_PATTERN = re.compile(
    r"session-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
PLACEMENT_CONTRACT_KEYS = {
    "schema_version",
    "placement_id",
    "cpu_ids",
    "allowed_memory_nodes",
    "memory_policy",
    "policy_memory_nodes",
}

if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RUNTIME_PROBE = r'''
import errno
import json
import os
import platform
import socket
import sys

import numpy
import torch

DENIED_SOCKET_ERRORS = {
    errno.EPERM,
    errno.EACCES,
    errno.EAFNOSUPPORT,
    errno.EPROTONOSUPPORT,
}

def socket_denied(family, socket_type):
    try:
        value = socket.socket(family, socket_type)
    except OSError as error:
        return error.errno in DENIED_SOCKET_ERRORS
    value.close()
    return False

result = {
    "affinity": sorted(os.sched_getaffinity(0)),
    "cuda_available": bool(torch.cuda.is_available()),
    "cuda_build": getattr(torch.version, "cuda", None) is not None,
    "hip_build": getattr(torch.version, "hip", None) is not None,
    "inet4_dgram_socket_denied": socket_denied(socket.AF_INET, socket.SOCK_DGRAM),
    "inet4_stream_socket_denied": socket_denied(socket.AF_INET, socket.SOCK_STREAM),
    "inet6_dgram_socket_denied": socket_denied(socket.AF_INET6, socket.SOCK_DGRAM),
    "inet6_stream_socket_denied": socket_denied(socket.AF_INET6, socket.SOCK_STREAM),
    "python_version": ".".join(str(value) for value in sys.version_info[:3]),
    "platform_machine": platform.machine(),
    "platform_system": platform.system(),
    "glibc_version": platform.libc_ver()[1],
    "numpy_version": str(numpy.__version__),
    "torch_version": str(torch.__version__),
}
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
'''.strip()


class BenchmarkRefused(RuntimeError):
    """A safe refusal whose details must not cross the public CLI boundary."""


@dataclass(frozen=True)
class PlacementSnapshot:
    cpu_ids: tuple[int, ...]
    allowed_memory_nodes: tuple[int, ...]
    memory_policy: str
    policy_memory_nodes: tuple[int, ...]

@dataclass(frozen=True)
class ChildResult:
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkRefused("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise BenchmarkRefused("non-finite JSON value")


def _parse_json_object(
    payload: bytes,
    *,
    expected_keys: set[str],
    maximum_bytes: int = MAXIMUM_CHILD_OUTPUT_BYTES,
) -> dict[str, Any]:
    if not 1 <= len(payload) <= maximum_bytes or b"\x00" in payload:
        raise BenchmarkRefused("child JSON output is outside the allowed range")
    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, BenchmarkRefused):
        raise BenchmarkRefused("child JSON output is invalid") from None
    if not isinstance(document, dict) or set(document) != expected_keys:
        raise BenchmarkRefused("child JSON contract is incompatible")
    return document


def _read_regular_bytes(
    path: Path, *, maximum_bytes: int, minimum_bytes: int = 1
) -> bytes:
    if (
        type(minimum_bytes) is not int
        or type(maximum_bytes) is not int
        or not 0 <= minimum_bytes <= maximum_bytes
    ):
        raise BenchmarkRefused("artifact byte limits are invalid")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not minimum_bytes <= before.st_size <= maximum_bytes
        ):
            raise BenchmarkRefused("artifact is outside the allowed range")
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        payload = b"".join(chunks)
        if (
            len(payload) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise BenchmarkRefused("artifact changed while it was read")
        return payload
    except OSError:
        raise BenchmarkRefused("artifact is unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _sha256_regular_file(
    path: Path, *, maximum_bytes: int, minimum_bytes: int = 1
) -> tuple[str, int]:
    payload = _read_regular_bytes(
        path, maximum_bytes=maximum_bytes, minimum_bytes=minimum_bytes
    )
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _read_bounded_stream(path: Path, *, maximum_bytes: int) -> bytes:
    """Read a procfs-style regular stream whose advertised size may be zero."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BenchmarkRefused("kernel stream is not a regular entry")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                raise BenchmarkRefused("kernel stream is too large")
        payload = b"".join(chunks)
        if not payload:
            raise BenchmarkRefused("kernel stream is empty")
        return payload
    except OSError:
        raise BenchmarkRefused("kernel stream is unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
    except OSError:
        raise BenchmarkRefused("exclusive artifact creation failed") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_atomic_exclusive(path: Path, payload: bytes) -> None:
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        if os.path.lexists(path):
            raise BenchmarkRefused("evidence output already exists")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(temporary_path, path, follow_symlinks=False)
        temporary_path.unlink()
        temporary_path = None
        _fsync_directory(path.parent)
    except BenchmarkRefused:
        raise
    except OSError:
        raise BenchmarkRefused("atomic evidence creation failed") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_id_list(value: str) -> tuple[int, ...]:
    if not value or len(value) > 65536:
        raise BenchmarkRefused("kernel placement list is invalid")
    result: set[int] = set()
    for item in value.split(","):
        if not item:
            raise BenchmarkRefused("kernel placement list is invalid")
        bounds = item.split("-", 1)
        if any(not bound.isascii() or not bound.isdecimal() for bound in bounds):
            raise BenchmarkRefused("kernel placement list is invalid")
        start = int(bounds[0], 10)
        end = int(bounds[-1], 10)
        if start > end or end >= 1_048_576 or end - start >= MAXIMUM_ID_ITEMS:
            raise BenchmarkRefused("kernel placement list is invalid")
        result.update(range(start, end + 1))
        if len(result) > MAXIMUM_ID_ITEMS:
            raise BenchmarkRefused("kernel placement list is too large")
    if not result:
        raise BenchmarkRefused("kernel placement list is empty")
    return tuple(sorted(result))


def _read_proc_status_lists() -> tuple[tuple[int, ...], tuple[int, ...]]:
    payload = _read_bounded_stream(
        Path("/proc/self/status"), maximum_bytes=1024 * 1024
    )
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        raise BenchmarkRefused("procfs status is invalid") from None
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key in {"Cpus_allowed_list", "Mems_allowed_list"}:
            if key in values:
                raise BenchmarkRefused("procfs status is ambiguous")
            values[key] = value.strip()
    if set(values) != {"Cpus_allowed_list", "Mems_allowed_list"}:
        raise BenchmarkRefused("procfs placement fields are unavailable")
    return _parse_id_list(values["Cpus_allowed_list"]), _parse_id_list(
        values["Mems_allowed_list"]
    )


def _read_memory_policy() -> tuple[str, tuple[int, ...]]:
    library_name = ctypes.util.find_library("numa")
    if not library_name:
        raise BenchmarkRefused("NUMA policy API is unavailable")
    try:
        library = ctypes.CDLL(library_name, use_errno=True)
        function = library.get_mempolicy
    except (OSError, AttributeError):
        raise BenchmarkRefused("NUMA policy API is unavailable") from None
    word_bits = ctypes.sizeof(ctypes.c_ulong) * 8
    word_count = (MAXIMUM_NUMA_NODES + word_bits - 1) // word_bits
    mask_type = ctypes.c_ulong * word_count
    mask = mask_type()
    mode = ctypes.c_int(-1)
    function.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    function.restype = ctypes.c_int
    result = function(
        ctypes.byref(mode), mask, MAXIMUM_NUMA_NODES, None, 0
    )
    if result != 0 or mode.value not in MEMORY_POLICY_MODES:
        raise BenchmarkRefused("NUMA memory policy is incompatible")
    nodes = tuple(
        node
        for node in range(MAXIMUM_NUMA_NODES)
        if mask[node // word_bits] & (1 << (node % word_bits))
    )
    return MEMORY_POLICY_MODES[mode.value], nodes


def capture_placement(required_memory_policy: str) -> PlacementSnapshot:
    if not sys.platform.startswith("linux") or not hasattr(os, "sched_getaffinity"):
        raise BenchmarkRefused("the NUMA runner requires Linux")
    affinity = tuple(sorted(os.sched_getaffinity(0)))
    proc_cpus, allowed_nodes = _read_proc_status_lists()
    if not affinity or affinity != proc_cpus:
        raise BenchmarkRefused("CPU affinity sources disagree")
    memory_policy, policy_nodes = _read_memory_policy()
    if memory_policy != required_memory_policy:
        raise BenchmarkRefused("NUMA memory policy does not match the plan")
    if memory_policy in {"bind", "interleave", "preferred"} and not policy_nodes:
        raise BenchmarkRefused("NUMA memory policy has no target node")
    if any(node not in allowed_nodes for node in policy_nodes):
        raise BenchmarkRefused("NUMA memory policy escapes the allowed nodes")
    return PlacementSnapshot(
        cpu_ids=affinity,
        allowed_memory_nodes=allowed_nodes,
        memory_policy=memory_policy,
        policy_memory_nodes=policy_nodes,
    )


def require_inet_sockets_denied(
    socket_factory: Callable[..., socket.socket] = socket.socket,
) -> None:
    for family, socket_type in (
        (socket.AF_INET, socket.SOCK_STREAM),
        (socket.AF_INET, socket.SOCK_DGRAM),
        (socket.AF_INET6, socket.SOCK_STREAM),
        (socket.AF_INET6, socket.SOCK_DGRAM),
    ):
        try:
            value = socket_factory(family, socket_type)
        except OSError as error:
            if error.errno in {
                errno.EPERM,
                errno.EACCES,
                errno.EAFNOSUPPORT,
                errno.EPROTONOSUPPORT,
            }:
                continue
            raise BenchmarkRefused("Internet socket denial could not be proven") from None
        try:
            value.close()
        finally:
            raise BenchmarkRefused("Internet socket families remain available")


def _safe_child_environment(attempt_root: Path, *, threads: int) -> dict[str, str]:
    home = attempt_root / "home"
    temporary = attempt_root / "tmp"
    cache = attempt_root / "cache"
    for directory in (home, temporary, cache):
        directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
    thread_value = str(threads)
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "TMP": str(temporary),
        "TEMP": str(temporary),
        "XDG_CACHE_HOME": str(cache),
        "TORCH_HOME": str(cache / "torch"),
        "HF_HOME": str(cache / "huggingface"),
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": "",
        "ROCR_VISIBLE_DEVICES": "",
        "HIP_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": thread_value,
        "MKL_NUM_THREADS": thread_value,
        "OPENBLAS_NUM_THREADS": thread_value,
        "NUMEXPR_NUM_THREADS": thread_value,
        "VECLIB_MAXIMUM_THREADS": thread_value,
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "SOVEREIGN_OFFLINE_BENCHMARK": "1",
    }


def _limit_child() -> None:
    os.umask(0o077)
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (MAXIMUM_CHECKPOINT_BYTES, MAXIMUM_CHECKPOINT_BYTES),
        )
    except (ImportError, OSError, ValueError):
        os._exit(125)


def _process_group_exists(process_id: int) -> bool:
    try:
        os.killpg(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if not _process_group_exists(process.pid):
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise BenchmarkRefused("child process could not be reaped") from None
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        raise BenchmarkRefused("child process group could not be terminated") from None
    deadline = time.monotonic() + 2.0
    while _process_group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _process_group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            raise BenchmarkRefused("child process group could not be terminated") from None
    deadline = time.monotonic() + 5.0
    while _process_group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _process_group_exists(process.pid):
        raise BenchmarkRefused("child process group survived termination")
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        raise BenchmarkRefused("child process could not be reaped") from None


def _persist_child_streams(
    *, stdout_path: Path, stderr_path: Path, stdout: bytes, stderr: bytes
) -> None:
    _write_exclusive(stdout_path, stdout)
    _write_exclusive(stderr_path, stderr)


def run_child(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
    stdout_path: Path,
    stderr_path: Path,
) -> ChildResult:
    if (
        not argv
        or not Path(argv[0]).is_absolute()
        or any(type(value) is not str or "\x00" in value for value in argv)
    ):
        raise BenchmarkRefused("child argument vector is invalid")
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    stdout = bytearray()
    stderr = bytearray()
    selector: selectors.BaseSelector | None = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
            start_new_session=True,
            preexec_fn=_limit_child,
        )
        if process.stdout is None or process.stderr is None:
            raise BenchmarkRefused("child stream setup failed")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, stdout)
        selector.register(process.stderr, selectors.EVENT_READ, stderr)
        deadline = started + timeout_seconds
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                _terminate_process_group(process)
                raise BenchmarkRefused("child process timed out")
            for key, _ in selector.select(timeout=min(0.1, remaining)):
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 65536)
                destination: bytearray = key.data
                if not chunk:
                    selector.unregister(stream)
                    continue
                destination.extend(chunk)
                if len(destination) > MAXIMUM_CHILD_OUTPUT_BYTES:
                    _terminate_process_group(process)
                    raise BenchmarkRefused("child output exceeded the limit")
        return_code = process.wait(timeout=1)
    except OSError:
        if process is not None and process.poll() is None:
            _terminate_process_group(process)
        raise BenchmarkRefused("child process could not start") from None
    except BaseException:
        if process is not None and process.poll() is None:
            _terminate_process_group(process)
        raise
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
    _persist_child_streams(
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
    )
    elapsed = time.monotonic() - started
    if return_code != 0 or not math.isfinite(elapsed) or elapsed <= 0.0:
        raise BenchmarkRefused("child process refused the workload")
    if stderr:
        raise BenchmarkRefused("child process emitted diagnostics")
    return ChildResult(
        stdout=bytes(stdout), stderr=bytes(stderr), elapsed_seconds=elapsed
    )


def _validate_integer(value: Any, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise BenchmarkRefused("integer result is outside the allowed range")
    return value


def _validate_finite_float(value: Any, *, minimum: float = 0.0) -> float:
    if type(value) is not float or not math.isfinite(value) or value < minimum:
        raise BenchmarkRefused("floating-point result is invalid")
    return value


def _safe_version(value: Any) -> str:
    if not isinstance(value, str) or SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise BenchmarkRefused("runtime version is invalid")
    return value


def _version_parts(value: Any) -> tuple[int, ...]:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", value) is None:
        raise BenchmarkRefused("runtime version is invalid")
    return tuple(int(part) for part in value.split("."))


def load_offline_runtime_lock(
    path: Path,
) -> tuple[dict[str, Any], str, str, str, str, str]:
    payload = _read_regular_bytes(path, maximum_bytes=MAXIMUM_SOURCE_BYTES)
    document = _parse_json_object(
        payload,
        expected_keys={
            "schema_version",
            "status",
            "acquired_at",
            "source_index",
            "target",
            "policy",
            "packages",
        },
        maximum_bytes=MAXIMUM_SOURCE_BYTES,
    )
    target = document["target"]
    policy = document["policy"]
    packages = document["packages"]
    if (
        document["schema_version"] != "0.1.0"
        or document["status"] != "acquired_not_installed"
        or not isinstance(target, dict)
        or set(target)
        != {
            "host_role",
            "os",
            "architecture",
            "python",
            "abi",
            "minimum_glibc",
            "observed_glibc",
        }
        or target["os"] != "linux"
        or target["architecture"] != "x86_64"
        or not isinstance(target["python"], str)
        or re.fullmatch(r"[0-9]+\.[0-9]+", target["python"]) is None
        or target["abi"] != "cp" + target["python"].replace(".", "")
        or not isinstance(policy, dict)
        or set(policy)
        != {"cpu_only", "offline_install_only", "forbidden_filename_markers"}
        or policy["cpu_only"] is not True
        or policy["offline_install_only"] is not True
        or not isinstance(policy["forbidden_filename_markers"], list)
        or not policy["forbidden_filename_markers"]
        or any(
            not isinstance(marker, str) or not marker
            for marker in policy["forbidden_filename_markers"]
        )
        or not isinstance(packages, list)
        or not packages
    ):
        raise BenchmarkRefused("offline runtime lock is incompatible")
    forbidden = tuple(
        marker.casefold() for marker in policy["forbidden_filename_markers"]
    )
    names: set[str] = set()
    filenames: set[str] = set()
    torch_version: str | None = None
    required_package_keys = {
        "filename",
        "name",
        "version",
        "bytes",
        "sha256",
        "license_expression",
    }
    optional_package_keys = {
        "published_sha256_verified",
        "license_verified_from_wheel",
    }
    for package in packages:
        if (
            not isinstance(package, dict)
            or not required_package_keys <= set(package)
            or not set(package) <= required_package_keys | optional_package_keys
        ):
            raise BenchmarkRefused("offline runtime package lock is incompatible")
        filename = package["filename"]
        name = package["name"]
        version = package["version"]
        byte_size = package["bytes"]
        digest = package["sha256"]
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or not isinstance(name, str)
            or not name
            or not isinstance(version, str)
            or SAFE_VERSION_PATTERN.fullmatch(version) is None
            or type(byte_size) is not int
            or byte_size <= 0
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or any(marker in filename.casefold() for marker in forbidden)
        ):
            raise BenchmarkRefused("offline runtime package entry is invalid")
        folded_name = name.casefold()
        if folded_name in names or filename in filenames:
            raise BenchmarkRefused("offline runtime package is duplicated")
        names.add(folded_name)
        filenames.add(filename)
        if folded_name == "torch":
            torch_version = version
    if torch_version is None or not torch_version.endswith("+cpu"):
        raise BenchmarkRefused("offline runtime lock has no CPU-only torch package")
    return (
        document,
        hashlib.sha256(payload).hexdigest(),
        target["python"],
        target["architecture"],
        target["minimum_glibc"],
        torch_version,
    )


def load_numpy_runtime_lock(path: Path) -> tuple[dict[str, Any], str, str]:
    payload = _read_regular_bytes(path, maximum_bytes=MAXIMUM_SOURCE_BYTES)
    document = _parse_json_object(
        payload,
        expected_keys={
            "schema_version",
            "status",
            "acquired_at",
            "source_index",
            "target",
            "policy",
            "packages",
        },
        maximum_bytes=MAXIMUM_SOURCE_BYTES,
    )
    target = document["target"]
    policy = document["policy"]
    packages = document["packages"]
    if (
        document["schema_version"] != "0.1.0"
        or document["status"] != "acquired_installed"
        or not isinstance(document["source_index"], str)
        or not document["source_index"].startswith("https://pypi.org/")
        or not isinstance(target, dict)
        or set(target)
        != {
            "host_role",
            "os",
            "architecture",
            "python",
            "abi",
            "minimum_glibc",
            "observed_glibc",
        }
        or target["os"] != "linux"
        or target["architecture"] != "x86_64"
        or target["python"] != "3.13"
        or target["abi"] != "cp313"
        or not isinstance(policy, dict)
        or set(policy)
        != {"cpu_only", "offline_install_only", "forbidden_filename_markers"}
        or policy["cpu_only"] is not True
        or policy["offline_install_only"] is not True
        or not isinstance(policy["forbidden_filename_markers"], list)
        or not policy["forbidden_filename_markers"]
        or not isinstance(packages, list)
        or len(packages) != 1
    ):
        raise BenchmarkRefused("NumPy runtime lock is incompatible")
    package = packages[0]
    required_package_keys = {
        "filename",
        "name",
        "version",
        "bytes",
        "sha256",
        "published_sha256_verified",
        "license_expression",
    }
    if not isinstance(package, dict) or set(package) != required_package_keys:
        raise BenchmarkRefused("NumPy runtime package lock is incompatible")
    filename = package["filename"]
    version = package["version"]
    forbidden = tuple(
        marker.casefold() for marker in policy["forbidden_filename_markers"]
        if isinstance(marker, str) and marker
    )
    if (
        len(forbidden) != len(policy["forbidden_filename_markers"])
        or not isinstance(filename, str)
        or Path(filename).name != filename
        or not filename.endswith(".whl")
        or package["name"].casefold() != "numpy"
        or not isinstance(version, str)
        or SAFE_VERSION_PATTERN.fullmatch(version) is None
        or type(package["bytes"]) is not int
        or package["bytes"] <= 0
        or not isinstance(package["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", package["sha256"]) is None
        or package["published_sha256_verified"] is not True
        or not isinstance(package["license_expression"], str)
        or not package["license_expression"]
        or any(marker in filename.casefold() for marker in forbidden)
    ):
        raise BenchmarkRefused("NumPy runtime package entry is invalid")
    return document, hashlib.sha256(payload).hexdigest(), version


def validate_runtime_observation(
    runtime: dict[str, Any], *, expected_python: str, expected_architecture: str,
    minimum_glibc: str, expected_torch: str, expected_numpy: str
) -> None:
    if (
        runtime.get("device") != "cpu_only"
        or runtime.get("accelerator_backend") != "absent"
        or not isinstance(runtime.get("python_version"), str)
        or not runtime["python_version"].startswith(expected_python + ".")
        or runtime.get("platform_system") != "Linux"
        or runtime.get("platform_machine") != expected_architecture
        or runtime.get("torch_version") != expected_torch
        or runtime.get("numpy_version") != expected_numpy
    ):
        raise BenchmarkRefused("observed runtime differs from the offline lock")
    observed_glibc = _version_parts(runtime.get("glibc_version"))
    minimum = _version_parts(minimum_glibc)
    padded_observed = observed_glibc + (0,) * (3 - len(observed_glibc))
    padded_minimum = minimum + (0,) * (3 - len(minimum))
    if padded_observed < padded_minimum:
        raise BenchmarkRefused("observed runtime does not meet the glibc minimum")


def _persist_canonical_contract(path: Path, document: Any) -> str:
    payload = _canonical_json_bytes(document) + b"\n"
    _write_exclusive(path, payload)
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(document: Any) -> bytes:
    try:
        return json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise BenchmarkRefused("canonical JSON creation failed") from None


def _sha256_document(document: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(document)).hexdigest()


def _validate_private_id_array(value: Any, *, maximum: int) -> tuple[int, ...]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAXIMUM_ID_ITEMS
        or any(type(item) is not int or not 0 <= item <= maximum for item in value)
    ):
        raise BenchmarkRefused("private placement identifiers are invalid")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise BenchmarkRefused("private placement identifiers are not canonical")
    return result


def load_private_placement_contract(
    path: Path,
) -> tuple[str, bytes, PlacementSnapshot]:
    payload = _read_regular_bytes(path, maximum_bytes=MAXIMUM_SOURCE_BYTES)
    document = _parse_json_object(
        payload,
        expected_keys=PLACEMENT_CONTRACT_KEYS,
        maximum_bytes=MAXIMUM_SOURCE_BYTES,
    )
    if document["schema_version"] != "core-mini-private-placement.v1":
        raise BenchmarkRefused("private placement contract version is incompatible")
    placement_id = document["placement_id"]
    if placement_id not in PLACEMENT_IDS:
        raise BenchmarkRefused("private placement label is incompatible")
    memory_policy = document["memory_policy"]
    if memory_policy not in set(MEMORY_POLICY_MODES.values()):
        raise BenchmarkRefused("private memory policy is incompatible")
    cpu_ids = _validate_private_id_array(document["cpu_ids"], maximum=1_048_575)
    allowed_nodes = _validate_private_id_array(
        document["allowed_memory_nodes"], maximum=MAXIMUM_NUMA_NODES - 1
    )
    policy_value = document["policy_memory_nodes"]
    if not isinstance(policy_value, list) or len(policy_value) > MAXIMUM_ID_ITEMS:
        raise BenchmarkRefused("private policy nodes are invalid")
    if policy_value:
        policy_nodes = _validate_private_id_array(
            policy_value, maximum=MAXIMUM_NUMA_NODES - 1
        )
    else:
        policy_nodes = ()
    if memory_policy in {"bind", "interleave", "preferred"} and not policy_nodes:
        raise BenchmarkRefused("private memory policy has no target node")
    if any(node not in allowed_nodes for node in policy_nodes):
        raise BenchmarkRefused("private memory policy escapes allowed nodes")
    return (
        placement_id,
        payload,
        PlacementSnapshot(
            cpu_ids=cpu_ids,
            allowed_memory_nodes=allowed_nodes,
            memory_policy=memory_policy,
            policy_memory_nodes=policy_nodes,
        ),
    )


def _placement_contract_commitment(payload: bytes, salt: bytes) -> str:
    if not payload or len(salt) != 32:
        raise BenchmarkRefused("placement commitment inputs are invalid")
    digest = hashlib.sha256()
    digest.update(b"core-mini-placement-commitment-v1\x00")
    digest.update(salt)
    digest.update(payload)
    return digest.hexdigest()


def _source_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for label, path in (
        ("runner", Path(__file__).resolve()),
        ("child_wrapper", CHILD_WRAPPER),
        ("trainer", TRAINER),
        ("summarizer", SUMMARIZER),
        ("verifier", VERIFIER),
    ):
        digest, _ = _sha256_regular_file(path, maximum_bytes=MAXIMUM_SOURCE_BYTES)
        result[label] = digest
    return result


def _ignored_source_relative(parts: tuple[str, ...]) -> bool:
    if not parts:
        return False
    return (
        parts[0] in {".git", ".codex-test-tmp", "runs"}
        or "__pycache__" in parts
        or parts[-1].endswith((".pyc", ".pyo"))
    )


def verify_source_archive(path: Path) -> tuple[str, str, str]:
    """Bind the executed tree to one bounded Git archive and its PAX commit."""

    archive_bytes = _read_regular_bytes(
        path, maximum_bytes=MAXIMUM_SOURCE_ARCHIVE_BYTES
    )
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    expected_files: dict[str, tuple[str, int]] = {}
    total_bytes = 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(archive_bytes), mode="rb") as compressed:
            tar_bytes = compressed.read(MAXIMUM_SOURCE_TREE_BYTES + 1)
        if len(tar_bytes) > MAXIMUM_SOURCE_TREE_BYTES:
            raise BenchmarkRefused("source archive expands beyond the limit")
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r|") as archive:
            member_count = 0
            for member in archive:
                member_count += 1
                if member_count > MAXIMUM_SOURCE_MEMBERS:
                    raise BenchmarkRefused("source archive member count is invalid")
                member_path = PurePosixPath(member.name)
                if (
                    member_path.is_absolute()
                    or not member_path.parts
                    or member_path.parts[0] != "source"
                    or any(part in {"", ".", ".."} for part in member_path.parts)
                ):
                    raise BenchmarkRefused("source archive path is unsafe")
                if member.isdir():
                    continue
                if not member.isreg() or len(member_path.parts) == 1:
                    raise BenchmarkRefused("source archive member type is unsafe")
                relative = PurePosixPath(*member_path.parts[1:]).as_posix()
                if relative in expected_files:
                    raise BenchmarkRefused("source archive contains duplicate paths")
                if not 0 <= member.size <= MAXIMUM_SOURCE_BYTES:
                    raise BenchmarkRefused("source archive member is too large")
                total_bytes += member.size
                if total_bytes > MAXIMUM_SOURCE_TREE_BYTES:
                    raise BenchmarkRefused("source archive expands beyond the limit")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise BenchmarkRefused("source archive member is unreadable")
                payload = extracted.read(member.size + 1)
                if len(payload) != member.size:
                    raise BenchmarkRefused("source archive member size changed")
                expected_files[relative] = (
                    hashlib.sha256(payload).hexdigest(),
                    member.size,
                )
            source_revision = archive.pax_headers.get("comment")
            if (
                not isinstance(source_revision, str)
                or SOURCE_COMMIT_PATTERN.fullmatch(source_revision) is None
            ):
                raise BenchmarkRefused("source archive commit is unavailable")
            if not expected_files:
                raise BenchmarkRefused("source archive has no files")
    except BenchmarkRefused:
        raise
    except (OSError, tarfile.TarError, EOFError):
        raise BenchmarkRefused("source archive is invalid") from None

    observed_files: set[str] = set()
    for directory, directory_names, filenames in os.walk(
        PROJECT_ROOT, topdown=True, followlinks=False
    ):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(PROJECT_ROOT)
        retained_directories: list[str] = []
        for name in directory_names:
            relative_parts = (*relative_directory.parts, name)
            candidate = directory_path / name
            if _ignored_source_relative(relative_parts):
                continue
            if candidate.is_symlink():
                raise BenchmarkRefused("source tree contains a symbolic link")
            retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in filenames:
            relative_path = Path(*relative_directory.parts, name)
            if _ignored_source_relative(relative_path.parts):
                continue
            relative = PurePosixPath(*relative_path.parts).as_posix()
            expected = expected_files.get(relative)
            if expected is None:
                raise BenchmarkRefused("source tree contains an unexpected file")
            digest, size = _sha256_regular_file(
                PROJECT_ROOT / relative_path,
                maximum_bytes=MAXIMUM_SOURCE_BYTES,
                minimum_bytes=0,
            )
            if (digest, size) != expected:
                raise BenchmarkRefused("source tree differs from the Git archive")
            observed_files.add(relative)
    if observed_files != set(expected_files):
        raise BenchmarkRefused("source tree is incomplete")
    manifest = {
        relative: {"sha256": digest, "bytes": size}
        for relative, (digest, size) in sorted(expected_files.items())
    }
    return source_revision, archive_sha256, _sha256_document(manifest)


def _wrapped_child_command(
    phase: str,
    *,
    attestation_path: Path,
    required_memory_policy: str,
    phase_arguments: list[str] | None = None,
) -> list[str]:
    if phase not in {"runtime", "train", "summarize", "verify"}:
        raise BenchmarkRefused("child phase is incompatible")
    return [
        sys.executable,
        "-I",
        "-B",
        str(CHILD_WRAPPER),
        "--phase",
        phase,
        "--attestation",
        str(attestation_path),
        "--required-memory-policy",
        required_memory_policy,
        *(phase_arguments or []),
    ]


def validate_child_attestation(
    path: Path,
    *,
    expected_phase: str,
    expected_placement: PlacementSnapshot,
) -> str:
    payload = _read_regular_bytes(path, maximum_bytes=64 * 1024)
    document = _parse_json_object(
        payload,
        expected_keys={
            "schema_version",
            "phase",
            "cpu_ids",
            "allowed_memory_nodes",
            "memory_policy",
            "policy_memory_nodes",
            "inet_socket_policy",
        },
        maximum_bytes=64 * 1024,
    )
    if (
        document["schema_version"] != "core-mini-child-placement.v1"
        or document["phase"] != expected_phase
        or document["inet_socket_policy"] != "stream-and-dgram-denied"
    ):
        raise BenchmarkRefused("child placement attestation is incompatible")
    observed = PlacementSnapshot(
        cpu_ids=_validate_private_id_array(document["cpu_ids"], maximum=1_048_575),
        allowed_memory_nodes=_validate_private_id_array(
            document["allowed_memory_nodes"], maximum=MAXIMUM_NUMA_NODES - 1
        ),
        memory_policy=document["memory_policy"],
        policy_memory_nodes=(
            _validate_private_id_array(
                document["policy_memory_nodes"], maximum=MAXIMUM_NUMA_NODES - 1
            )
            if document["policy_memory_nodes"]
            else ()
        ),
    )
    if observed != expected_placement:
        raise BenchmarkRefused("child placement differs from the private contract")
    return hashlib.sha256(payload).hexdigest()


def _require_outside_project(path: Path, *, must_exist: bool) -> Path:
    try:
        resolved = path.resolve(strict=must_exist)
        project_root = PROJECT_ROOT.resolve(strict=True)
    except OSError:
        raise BenchmarkRefused("private path is unavailable") from None
    if resolved == project_root or project_root in resolved.parents:
        raise BenchmarkRefused("private artifacts must remain outside the source tree")
    return resolved


def _create_run_root(path: Path) -> Path:
    if not path.is_absolute() or os.path.lexists(path):
        raise BenchmarkRefused("run root must be a new absolute path")
    normalized = _require_outside_project(path, must_exist=False)
    if normalized != path:
        raise BenchmarkRefused("run root path is not canonical")
    parent = path.parent
    try:
        metadata = parent.lstat()
    except OSError:
        raise BenchmarkRefused("run root parent is unavailable") from None
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise BenchmarkRefused("run root parent is incompatible")
    try:
        path.mkdir(mode=PRIVATE_DIRECTORY_MODE)
    except OSError:
        raise BenchmarkRefused("run root could not be created") from None
    return path


def _runtime_probe(
    run_root: Path,
    *,
    threads: int,
    timeout_seconds: int,
    expected_placement: PlacementSnapshot,
    required_memory_policy: str,
) -> dict[str, Any]:
    attempt = run_root / "runtime-probe"
    attempt.mkdir(mode=PRIVATE_DIRECTORY_MODE)
    attestation_path = attempt / "placement-attestation.json"
    result = run_child(
        _wrapped_child_command(
            "runtime",
            attestation_path=attestation_path,
            required_memory_policy=required_memory_policy,
        ),
        cwd=PROJECT_ROOT,
        environment=_safe_child_environment(attempt, threads=threads),
        timeout_seconds=timeout_seconds,
        stdout_path=attempt / "stdout.json",
        stderr_path=attempt / "stderr.log",
    )
    validate_child_attestation(
        attestation_path,
        expected_phase="runtime",
        expected_placement=expected_placement,
    )
    document = _parse_json_object(
        result.stdout,
        expected_keys={
            "affinity",
            "cuda_available",
            "cuda_build",
            "hip_build",
            "inet4_dgram_socket_denied",
            "inet4_stream_socket_denied",
            "inet6_dgram_socket_denied",
            "inet6_stream_socket_denied",
            "python_version",
            "platform_machine",
            "platform_system",
            "glibc_version",
            "numpy_version",
            "torch_version",
        },
    )
    affinity = document["affinity"]
    if (
        not isinstance(affinity, list)
        or any(type(value) is not int for value in affinity)
        or tuple(affinity) != expected_placement.cpu_ids
    ):
        raise BenchmarkRefused("runtime child affinity changed")
    boolean_keys = {
        "cuda_available",
        "cuda_build",
        "hip_build",
        "inet4_dgram_socket_denied",
        "inet4_stream_socket_denied",
        "inet6_dgram_socket_denied",
        "inet6_stream_socket_denied",
    }
    if any(type(document[key]) is not bool for key in boolean_keys):
        raise BenchmarkRefused("runtime probe flags are invalid")
    if document["cuda_available"] or document["cuda_build"] or document["hip_build"]:
        raise BenchmarkRefused("runtime is not CPU-only")
    if any(
        not document[key]
        for key in (
            "inet4_dgram_socket_denied",
            "inet4_stream_socket_denied",
            "inet6_dgram_socket_denied",
            "inet6_stream_socket_denied",
        )
    ):
        raise BenchmarkRefused("runtime child can create Internet sockets")
    return {
        "python_version": _safe_version(document["python_version"]),
        "platform_machine": _safe_version(document["platform_machine"]),
        "platform_system": _safe_version(document["platform_system"]),
        "glibc_version": _safe_version(document["glibc_version"]),
        "numpy_version": _safe_version(document["numpy_version"]),
        "torch_version": _safe_version(document["torch_version"]),
        "accelerator_backend": "absent",
        "device": "cpu_only",
    }


def _validate_summary(
    document: dict[str, Any],
    *,
    steps: int,
    warmup_steps: int,
    tokens_per_step: int,
) -> None:
    if document["schema_version"] != "core-mini-metrics-summary.v2":
        raise BenchmarkRefused("metrics summary version is incompatible")
    if document["data_mode"] != "synthetic":
        raise BenchmarkRefused("benchmark data mode is incompatible")
    _validate_integer(document["steps_total"], minimum=steps, maximum=steps)
    _validate_integer(
        document["warmup_steps"], minimum=warmup_steps, maximum=warmup_steps
    )
    _validate_integer(
        document["steps_measured"],
        minimum=steps - warmup_steps,
        maximum=steps - warmup_steps,
    )
    _validate_integer(
        document["tokens_per_step"], minimum=tokens_per_step, maximum=tokens_per_step
    )
    _validate_integer(
        document["tokens_measured"],
        minimum=tokens_per_step * (steps - warmup_steps),
        maximum=tokens_per_step * (steps - warmup_steps),
    )
    if not isinstance(document["metrics_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", document["metrics_sha256"]
    ):
        raise BenchmarkRefused("metrics digest is invalid")
    timing = document["timing_seconds"]
    expected_timing_keys = {
        "total",
        "mean_step",
        "median_step",
        "minimum_step",
        "maximum_step",
        "population_standard_deviation",
        "median_absolute_deviation",
    }
    if not isinstance(timing, dict) or set(timing) != expected_timing_keys:
        raise BenchmarkRefused("metrics timing contract is incompatible")
    for key in (
        "total",
        "mean_step",
        "median_step",
        "minimum_step",
        "maximum_step",
    ):
        _validate_finite_float(timing[key])
        if timing[key] <= 0.0:
            raise BenchmarkRefused("metrics timing value is not positive")
    for key in (
        "population_standard_deviation",
        "median_absolute_deviation",
    ):
        _validate_finite_float(timing[key])
    _validate_finite_float(document["tokens_per_second"], minimum=0.0)
    if document["tokens_per_second"] <= 0.0:
        raise BenchmarkRefused("metrics throughput is invalid")


def _aggregate(samples: list[float]) -> dict[str, Any]:
    if not MINIMUM_REPETITIONS <= len(samples) <= MAXIMUM_REPETITIONS:
        raise BenchmarkRefused("sample count is incompatible")
    if any(type(value) is not float or not math.isfinite(value) or value <= 0.0 for value in samples):
        raise BenchmarkRefused("throughput sample is invalid")
    median = statistics.median(samples)
    return {
        "sample_count": len(samples),
        "samples": samples,
        "mean": statistics.fmean(samples),
        "median": median,
        "minimum": min(samples),
        "maximum": max(samples),
        "population_standard_deviation": statistics.pstdev(samples),
        "median_absolute_deviation": statistics.median(
            abs(value - median) for value in samples
        ),
    }


def build_evidence(
    args: argparse.Namespace,
    *,
    placement_id: str,
    placement_contract_commitment_sha256: str,
    model_name: str,
    source_revision: str,
    source_archive_sha256: str,
    source_tree_manifest_sha256: str,
    config_sha256: str,
    offline_runtime_lock_sha256: str,
    numpy_runtime_lock_sha256: str,
    runtime_observation_sha256: str,
    environment_contract_sha256: str,
    repetitions: list[dict[str, Any]],
    proof_uuid: uuid.UUID | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    if placement_id not in PLACEMENT_IDS:
        raise BenchmarkRefused("placement label is incompatible")
    for digest in (
        placement_contract_commitment_sha256,
        source_archive_sha256,
        source_tree_manifest_sha256,
        config_sha256,
        offline_runtime_lock_sha256,
        numpy_runtime_lock_sha256,
        runtime_observation_sha256,
        environment_contract_sha256,
    ):
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise BenchmarkRefused("evidence digest is invalid")
    if SOURCE_COMMIT_PATTERN.fullmatch(source_revision) is None:
        raise BenchmarkRefused("source revision is invalid")
    if len(repetitions) != args.repetitions or any(
        run.get("repetition_id") != expected
        for expected, run in enumerate(repetitions, 1)
    ):
        raise BenchmarkRefused("repetition sequence is incompatible")
    throughput = _aggregate(
        [run["tokens_per_second"] for run in repetitions]
    )
    throughput.pop("sample_count")
    throughput.pop("samples")
    workload = {
        "model_name": model_name,
        "data_mode": "synthetic",
        "repetitions": args.repetitions,
        "source_revision": source_revision,
        "source_archive_sha256": source_archive_sha256,
        "source_tree_manifest_sha256": source_tree_manifest_sha256,
        "offline_runtime_lock_sha256": offline_runtime_lock_sha256,
        "numpy_runtime_lock_sha256": numpy_runtime_lock_sha256,
        "runtime_observation_sha256": runtime_observation_sha256,
        "environment_contract_sha256": environment_contract_sha256,
        "model_config_sha256": config_sha256,
        "steps": args.steps,
        "warmup_steps": args.warmup_steps,
        "batch_size": args.batch_size,
        "sequence_length": args.sequence_length,
        "learning_rate": 0.0003,
        "seed": args.seed,
        "threads": args.threads,
    }
    identifier = proof_uuid if proof_uuid is not None else uuid.uuid4()
    if identifier.version != 4:
        raise BenchmarkRefused("proof identifier is incompatible")
    created = created_at_utc
    if created is None:
        created = (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    if not isinstance(created, str) or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", created
    ) is None:
        raise BenchmarkRefused("evidence timestamp is incompatible")
    return {
        "schema_version": "0.2.0",
        "artifact_type": EVIDENCE_TYPE,
        "proof_id": f"proof-{identifier}",
        "created_at_utc": created,
        "benchmark_session_id": args.benchmark_session_id,
        "canonicalization": "canonical-json-v1",
        "placement": {
            "label": placement_id,
            "application": "external",
            "contract_commitment_sha256": placement_contract_commitment_sha256,
            "verification": "current-process-matched-private-contract",
        },
        "workload": workload,
        "workload_contract_sha256": _sha256_document(workload),
        "repetitions": repetitions,
        "aggregate": {
            "repetitions_completed": len(repetitions),
            "tokens_per_second": throughput,
        },
        "evidence_scope": "repeated-single-placement-only",
    }


def _run_repetition(
    run_root: Path,
    *,
    repetition: int,
    config_path: Path,
    model_name: str,
    expected_placement: PlacementSnapshot,
    required_memory_policy: str,
    steps: int,
    warmup_steps: int,
    batch_size: int,
    sequence_length: int,
    threads: int,
    seed: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    if capture_placement(required_memory_policy) != expected_placement:
        raise BenchmarkRefused("placement changed before repetition")
    attempt = run_root / f"repetition-{repetition:02d}"
    attempt.mkdir(mode=PRIVATE_DIRECTORY_MODE)
    training = attempt / "training"
    training.mkdir(mode=PRIVATE_DIRECTORY_MODE)
    environment = _safe_child_environment(attempt, threads=threads)
    training_result = run_child(
        _wrapped_child_command(
            "train",
            attestation_path=attempt / "train-placement-attestation.json",
            required_memory_policy=required_memory_policy,
            phase_arguments=[
            "--config",
            str(config_path),
            "--output-dir",
            str(training),
            "--steps",
            str(steps),
            "--batch-size",
            str(batch_size),
            "--sequence-length",
            str(sequence_length),
            "--seed",
            str(seed),
            "--threads",
            str(threads),
            ],
        ),
        cwd=PROJECT_ROOT,
        environment=environment,
        timeout_seconds=timeout_seconds,
        stdout_path=attempt / "train-stdout.json",
        stderr_path=attempt / "train-stderr.log",
    )
    validate_child_attestation(
        attempt / "train-placement-attestation.json",
        expected_phase="train",
        expected_placement=expected_placement,
    )
    train_document = _parse_json_object(
        training_result.stdout,
        expected_keys={"checkpoint_name", "checkpoint_sha256"},
    )
    expected_checkpoint_name = f"core-mini-step-{steps:06d}.pt"
    if train_document["checkpoint_name"] != expected_checkpoint_name:
        raise BenchmarkRefused("training checkpoint name is incompatible")
    if not isinstance(train_document["checkpoint_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", train_document["checkpoint_sha256"]
    ):
        raise BenchmarkRefused("training checkpoint digest is invalid")
    entries = {entry.name for entry in training.iterdir()}
    if entries != {"metrics.jsonl", expected_checkpoint_name}:
        raise BenchmarkRefused("training directory contains unexpected artifacts")
    metrics_path = training / "metrics.jsonl"
    checkpoint_path = training / expected_checkpoint_name
    metrics_sha256, _ = _sha256_regular_file(
        metrics_path, maximum_bytes=MAXIMUM_METRICS_BYTES
    )
    checkpoint_sha256, checkpoint_bytes = _sha256_regular_file(
        checkpoint_path, maximum_bytes=MAXIMUM_CHECKPOINT_BYTES
    )
    if checkpoint_sha256 != train_document["checkpoint_sha256"]:
        raise BenchmarkRefused("training checkpoint digest changed")
    for artifact in (metrics_path, checkpoint_path):
        descriptor = os.open(artifact, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    _fsync_directory(training)

    summary_path = attempt / "metrics-summary.json"
    summary_result = run_child(
        _wrapped_child_command(
            "summarize",
            attestation_path=attempt / "summary-placement-attestation.json",
            required_memory_policy=required_memory_policy,
            phase_arguments=[
            "--metrics",
            str(metrics_path),
            "--warmup-steps",
            str(warmup_steps),
            "--output",
            str(summary_path),
            ],
        ),
        cwd=PROJECT_ROOT,
        environment=environment,
        timeout_seconds=timeout_seconds,
        stdout_path=attempt / "summary-stdout.json",
        stderr_path=attempt / "summary-stderr.log",
    )
    validate_child_attestation(
        attempt / "summary-placement-attestation.json",
        expected_phase="summarize",
        expected_placement=expected_placement,
    )
    summary_bytes = _read_regular_bytes(
        summary_path, maximum_bytes=MAXIMUM_CHILD_OUTPUT_BYTES
    )
    if summary_result.stdout != summary_bytes:
        raise BenchmarkRefused("metrics summary output changed")
    summary_document = _parse_json_object(
        summary_bytes,
        expected_keys={
            "schema_version",
            "data_mode",
            "steps_total",
            "warmup_steps",
            "steps_measured",
            "tokens_per_step",
            "tokens_measured",
            "timing_seconds",
            "tokens_per_second",
            "metrics_sha256",
        },
    )
    _validate_summary(
        summary_document,
        steps=steps,
        warmup_steps=warmup_steps,
        tokens_per_step=batch_size * sequence_length,
    )
    if summary_document["metrics_sha256"] != metrics_sha256:
        raise BenchmarkRefused("metrics summary digest does not match the journal")

    verifier_result = run_child(
        _wrapped_child_command(
            "verify",
            attestation_path=attempt / "verify-placement-attestation.json",
            required_memory_policy=required_memory_policy,
            phase_arguments=[
            "--checkpoint",
            str(checkpoint_path),
            "--config",
            str(config_path),
            ],
        ),
        cwd=PROJECT_ROOT,
        environment=environment,
        timeout_seconds=timeout_seconds,
        stdout_path=attempt / "verify-stdout.json",
        stderr_path=attempt / "verify-stderr.log",
    )
    validate_child_attestation(
        attempt / "verify-placement-attestation.json",
        expected_phase="verify",
        expected_placement=expected_placement,
    )
    verify_document = _parse_json_object(
        verifier_result.stdout,
        expected_keys={
            "status",
            "backend",
            "network",
            "model_name",
            "checkpoint_schema_version",
            "checkpoint_sha256",
            "checkpoint_bytes",
            "step_before",
            "step_after",
            "resumed_steps",
            "resumed_loss",
            "model_state_keys",
            "optimizer_parameter_states",
        },
    )
    if (
        verify_document["status"] != "compatible"
        or verify_document["backend"] != "cpu_only"
        or verify_document["network"] != "disabled"
        or verify_document["model_name"] != model_name
        or verify_document["checkpoint_schema_version"] != "0.1.0"
        or verify_document["checkpoint_sha256"] != checkpoint_sha256
        or verify_document["checkpoint_bytes"] != checkpoint_bytes
        or verify_document["step_before"] != steps
        or verify_document["step_after"] != steps + 1
        or verify_document["resumed_steps"] != 1
    ):
        raise BenchmarkRefused("checkpoint verification contract is incompatible")
    _validate_finite_float(verify_document["resumed_loss"])
    _validate_integer(verify_document["model_state_keys"], minimum=1, maximum=100000)
    _validate_integer(
        verify_document["optimizer_parameter_states"], minimum=1, maximum=100000
    )
    checkpoint_after_sha256, checkpoint_after_bytes = _sha256_regular_file(
        checkpoint_path, maximum_bytes=MAXIMUM_CHECKPOINT_BYTES
    )
    if (
        checkpoint_after_sha256 != checkpoint_sha256
        or checkpoint_after_bytes != checkpoint_bytes
        or capture_placement(required_memory_policy) != expected_placement
    ):
        raise BenchmarkRefused("artifact or placement changed during repetition")
    return {
        "repetition_id": repetition,
        "status": "completed",
        "checkpoint_sha256": checkpoint_sha256,
        "metrics_sha256": metrics_sha256,
        "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "verification_sha256": hashlib.sha256(verifier_result.stdout).hexdigest(),
        "steps_total": summary_document["steps_total"],
        "steps_measured": summary_document["steps_measured"],
        "tokens_measured": summary_document["tokens_measured"],
        "tokens_per_second": summary_document["tokens_per_second"],
        "timing_seconds": summary_document["timing_seconds"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from services.inference.cli import PathFreeArgumentParser

    parser = PathFreeArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--placement-contract", type=Path, required=True)
    parser.add_argument("--benchmark-session-id", required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--warmup-steps", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--sequence-length", type=int, default=32)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    return parser.parse_args(argv)


def _validate_arguments(args: argparse.Namespace) -> None:
    if SESSION_ID_PATTERN.fullmatch(args.benchmark_session_id) is None:
        raise BenchmarkRefused("benchmark session identifier is invalid")
    _validate_integer(
        args.repetitions, minimum=MINIMUM_REPETITIONS, maximum=MAXIMUM_REPETITIONS
    )
    _validate_integer(args.steps, minimum=MINIMUM_STEPS, maximum=MAXIMUM_STEPS)
    _validate_integer(args.warmup_steps, minimum=1, maximum=args.steps - 3)
    _validate_integer(args.batch_size, minimum=1, maximum=64)
    _validate_integer(args.sequence_length, minimum=2, maximum=512)
    _validate_integer(args.threads, minimum=1, maximum=256)
    _validate_integer(args.seed, minimum=-(2**63), maximum=(2**63) - 1)
    _validate_integer(
        args.timeout_seconds,
        minimum=MINIMUM_TIMEOUT_SECONDS,
        maximum=MAXIMUM_TIMEOUT_SECONDS,
    )


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _validate_arguments(args)
    require_inet_sockets_denied()
    source_archive_path = _require_outside_project(args.source_archive, must_exist=True)
    source_provenance_before = verify_source_archive(source_archive_path)
    source_revision, source_archive_sha256, source_tree_manifest_sha256 = (
        source_provenance_before
    )
    placement_contract_path = _require_outside_project(
        args.placement_contract, must_exist=True
    )
    placement_id, placement_contract_bytes, private_placement = (
        load_private_placement_contract(placement_contract_path)
    )
    initial_placement = capture_placement(private_placement.memory_policy)
    if initial_placement != private_placement:
        raise BenchmarkRefused("observed placement does not match the private contract")
    if args.threads > len(initial_placement.cpu_ids):
        raise BenchmarkRefused("thread count exceeds the CPU affinity")
    source_hashes_before = _source_hashes()
    (
        _,
        offline_runtime_lock_sha256,
        expected_python_version,
        expected_architecture,
        minimum_glibc,
        expected_torch_version,
    ) = load_offline_runtime_lock(RUNTIME_LOCK)
    _, numpy_runtime_lock_sha256, expected_numpy_version = (
        load_numpy_runtime_lock(NUMPY_RUNTIME_LOCK)
    )
    config_bytes = _read_regular_bytes(DEFAULT_CONFIG, maximum_bytes=MAXIMUM_SOURCE_BYTES)
    config_sha256 = hashlib.sha256(config_bytes).hexdigest()
    run_root = _create_run_root(args.run_root)
    placement_salt = secrets.token_bytes(32)
    _write_exclusive(run_root / "placement-commitment-salt.bin", placement_salt)
    placement_contract_commitment_sha256 = _placement_contract_commitment(
        placement_contract_bytes, placement_salt
    )
    config_path = run_root / "core-mini.candidate.json"
    _write_exclusive(config_path, config_bytes)
    from services.inference.configuration import load_core_mini_configuration

    try:
        config_document, _, validated_config_sha256 = (
            load_core_mini_configuration(config_path)
        )
    except Exception:
        raise BenchmarkRefused("CORE-MINI configuration is invalid") from None
    if (
        validated_config_sha256 != config_sha256
        or config_document.get("name") != "CORE-MINI-1M"
        or config_document.get("execution", {}).get("device") != "cpu"
        or config_document.get("execution", {}).get("internet") != "disabled"
    ):
        raise BenchmarkRefused("CORE-MINI configuration is incompatible")
    runtime = _runtime_probe(
        run_root,
        threads=args.threads,
        timeout_seconds=args.timeout_seconds,
        expected_placement=initial_placement,
        required_memory_policy=private_placement.memory_policy,
    )
    validate_runtime_observation(
        runtime,
        expected_python=expected_python_version,
        expected_architecture=expected_architecture,
        minimum_glibc=minimum_glibc,
        expected_torch=expected_torch_version,
        expected_numpy=expected_numpy_version,
    )
    runtime_observation = {
        "schema_version": "core-mini-runtime-observation.v1",
        "runtime": runtime,
        "tool_sha256": source_hashes_before,
        "source_archive_sha256": source_archive_sha256,
        "source_tree_manifest_sha256": source_tree_manifest_sha256,
    }
    environment_contract = {
        "schema_version": "core-mini-benchmark-environment.v1",
        "child_environment": "allowlist-v1",
        "fresh_process_per_phase": True,
        "inet4_dgram_socket_creation": "denied",
        "inet4_stream_socket_creation": "denied",
        "inet6_dgram_socket_creation": "denied",
        "inet6_stream_socket_creation": "denied",
        "maximum_child_output_bytes": MAXIMUM_CHILD_OUTPUT_BYTES,
        "timeout_seconds": args.timeout_seconds,
    }
    runtime_observation_sha256 = _persist_canonical_contract(
        run_root / "runtime-observation.json", runtime_observation
    )
    environment_contract_sha256 = _persist_canonical_contract(
        run_root / "environment-contract.json", environment_contract
    )
    repetitions = [
        _run_repetition(
            run_root,
            repetition=index,
            config_path=config_path,
            model_name=config_document["name"],
            expected_placement=initial_placement,
            required_memory_policy=private_placement.memory_policy,
            steps=args.steps,
            warmup_steps=args.warmup_steps,
            batch_size=args.batch_size,
            sequence_length=args.sequence_length,
            threads=args.threads,
            seed=args.seed,
            timeout_seconds=args.timeout_seconds,
        )
        for index in range(1, args.repetitions + 1)
    ]
    if capture_placement(private_placement.memory_policy) != initial_placement:
        raise BenchmarkRefused("placement changed before evidence creation")
    if (
        _source_hashes() != source_hashes_before
        or verify_source_archive(source_archive_path) != source_provenance_before
    ):
        raise BenchmarkRefused("benchmark source changed during execution")
    evidence = build_evidence(
        args,
        placement_id=placement_id,
        placement_contract_commitment_sha256=placement_contract_commitment_sha256,
        model_name=config_document["name"],
        source_revision=source_revision,
        source_archive_sha256=source_archive_sha256,
        source_tree_manifest_sha256=source_tree_manifest_sha256,
        config_sha256=config_sha256,
        offline_runtime_lock_sha256=offline_runtime_lock_sha256,
        numpy_runtime_lock_sha256=numpy_runtime_lock_sha256,
        runtime_observation_sha256=runtime_observation_sha256,
        environment_contract_sha256=environment_contract_sha256,
        repetitions=repetitions,
    )
    encoded = _canonical_json_bytes(evidence) + b"\n"
    _write_atomic_exclusive(run_root / "evidence.json", encoded)
    sys.stdout.buffer.write(encoded)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception:
        print("CORE-MINI NUMA benchmark refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
