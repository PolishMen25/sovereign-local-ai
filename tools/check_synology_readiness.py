#!/usr/bin/env python3
"""Read-only readiness check of the Synology project share before a compute restart."""

# Compatibility contract: this file must stay stdlib-only and runnable by the
# Python 3.8 interpreter shipped with DSM 7, including as ``python3 - ARGS``
# with the source on standard input.  It never writes, never follows a
# symbolic link and prints only labels and aggregate numbers: no path, file
# name, account or host name ever reaches its output.

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time


SCHEMA_VERSION = "synology-readiness.v1"

EXIT_READY = 0
EXIT_ATTENTION = 1
EXIT_NOT_READY = 2
EXIT_USAGE = 64

STATUS_OK = "ok"
STATUS_ATTENTION = "attention"
STATUS_NOT_READY = "not_ready"
STATUS_SKIPPED = "skipped"
STATUS_RANK = {STATUS_OK: 0, STATUS_SKIPPED: 0, STATUS_ATTENTION: 1, STATUS_NOT_READY: 2}
OVERALL_BY_STATUS = {STATUS_OK: "ready", STATUS_ATTENTION: "attention", STATUS_NOT_READY: "not_ready"}
EXIT_BY_OVERALL = {"ready": EXIT_READY, "attention": EXIT_ATTENTION, "not_ready": EXIT_NOT_READY}

DEFAULT_EXPECTED_FOLDERS = ("raw", "validated", "models", "backups")
PUBLIC_FOLDER_LABELS = frozenset(DEFAULT_EXPECTED_FOLDERS)
FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_EXPECTED_FOLDERS = 16
MAX_SHARE_ROOT_CHARACTERS = 4096

# Synology metadata trees are never inspected: thumbnails, recycle bin and
# snapshot views are not project data and may be huge or out of scope.
METADATA_DIRECTORIES = frozenset({"@eaDir", "#recycle", "#snapshot"})
TEMPORARY_SUFFIXES = (
    ".tmp",
    ".temp",
    ".partial",
    ".part",
    ".crdownload",
    ".download",
    ".incomplete",
    ".swp",
    "~",
)
TEMPORARY_PREFIXES = (".~", "~$", ".nfs", ".smbdelete")

BACKUP_KINDS = (
    ("memory", re.compile(r"^memory-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}\.sqlite3$")),
    ("knowledge-index", re.compile(r"^knowledge-index-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}\.sqlite3$")),
)
BACKUP_MANIFEST_SCHEMAS = frozenset({"private-memory-backup.v1", "knowledge-index-backup.v1"})
BACKUP_MANIFEST_KEYS = frozenset({"schema_version", "artifact", "sha256", "bytes"})
BACKUP_MANIFESTS_PER_KIND = 3
SIDECAR_SUFFIX = ".sha256"
SMALL_DOCUMENT_MAX_BYTES = 4096
SIDECAR_LINE = re.compile(r"^([0-9A-Fa-f]{64})(?:[ \t]+\*?([^ \t].*))?$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
FUTURE_TOLERANCE_SECONDS = 300
# The time budget is also checked inside one directory listing, every this
# many entries, so that a huge or slow directory cannot overrun it silently.
LISTING_DEADLINE_STRIDE = 1024
CHUNK_BYTES = 1024 * 1024
GIB = 1024 ** 3

REASON_SEVERITY = {
    "share_root_missing": STATUS_NOT_READY,
    "share_root_not_directory": STATUS_NOT_READY,
    "share_root_symlink_refused": STATUS_NOT_READY,
    "share_root_not_accessible": STATUS_NOT_READY,
    "share_root_not_mount_point": STATUS_NOT_READY,
    "folder_missing": STATUS_NOT_READY,
    "folder_not_directory": STATUS_NOT_READY,
    "folder_symlink_refused": STATUS_NOT_READY,
    "folder_not_readable": STATUS_NOT_READY,
    "folder_not_writable": STATUS_NOT_READY,
    "free_space_below_threshold": STATUS_NOT_READY,
    "free_space_unavailable": STATUS_NOT_READY,
    "backup_folder_unavailable": STATUS_NOT_READY,
    "backup_missing": STATUS_ATTENTION,
    "backup_kind_missing": STATUS_ATTENTION,
    "backup_stale": STATUS_ATTENTION,
    "backup_in_future": STATUS_ATTENTION,
    "temporary_files_present": STATUS_ATTENTION,
    "empty_files_present": STATUS_ATTENTION,
    "symlinks_present": STATUS_ATTENTION,
    "symlink_escape_refused": STATUS_NOT_READY,
    "special_files_present": STATUS_ATTENTION,
    "unreadable_directories": STATUS_ATTENTION,
    "walk_truncated": STATUS_ATTENTION,
    "walk_depth_limited": STATUS_ATTENTION,
    "walk_identity_changed": STATUS_ATTENTION,
    "mount_crossing_refused": STATUS_ATTENTION,
    "future_mtime_present": STATUS_ATTENTION,
    "sha256_mismatch": STATUS_NOT_READY,
    "sha256_target_missing": STATUS_NOT_READY,
    "sha256_document_invalid": STATUS_ATTENTION,
    "sha256_target_refused": STATUS_ATTENTION,
    "sha256_unreadable": STATUS_ATTENTION,
    "sha256_changed_during_read": STATUS_ATTENTION,
    "sha256_budget_exhausted": STATUS_ATTENTION,
    "sha256_backup_budget_exhausted": STATUS_NOT_READY,
    "sha256_nothing_to_verify": STATUS_ATTENTION,
    "internal_error": STATUS_NOT_READY,
}

# ``os.scandir`` accepts a directory descriptor on POSIX.  Opening each
# directory with O_NOFOLLOW and comparing its identity with the entry seen in
# the parent listing refuses a directory swapped for a link during the walk.
_DESCRIPTOR_WALK = os.scandir in getattr(os, "supports_fd", set()) and hasattr(os, "O_DIRECTORY")
_disk_usage = shutil.disk_usage


class UsageError(ValueError):
    """A command-line refusal that never embeds an argument value."""


class _IdentityChanged(OSError):
    """An entry no longer matches the identity recorded when it was listed."""


class _Refused(Exception):
    """A verification target is not a regular file on the share device."""


class _BudgetExhausted(Exception):
    """The hashing byte or time budget does not allow this file."""


class _ChangedDuringRead(Exception):
    """A file changed while it was hashed."""


class _InvalidDocument(Exception):
    """A sidecar or backup manifest does not follow its strict format."""


class _HelpRequested(Exception):
    """``--help`` was requested: help goes to stderr and no report is produced."""


class _PathFreeArgumentParser(argparse.ArgumentParser):
    """Print help on stderr, never echo a refused value and never exit 0 without a report."""

    def error(self, message: str) -> None:  # type: ignore[override]
        del message
        raise UsageError("invalid command line")

    def print_help(self, file=None) -> None:  # type: ignore[override]
        super().print_help(sys.stderr if file is None else file)

    def exit(self, status: int = 0, message=None) -> None:  # type: ignore[override]
        # Only the help action reaches this point (``error`` is overridden).
        # Exiting 0 here would let ``ssh ... && start`` read help as "ready".
        del status, message
        raise _HelpRequested()


def _bounded_int(minimum: int, maximum: int):
    def parse(text: str) -> int:
        if not isinstance(text, str) or re.fullmatch(r"[0-9]{1,9}", text) is None:
            raise argparse.ArgumentTypeError("invalid integer")
        value = int(text)
        if not minimum <= value <= maximum:
            raise argparse.ArgumentTypeError("integer out of range")
        return value

    return parse


def _share_root(text: str) -> str:
    if not isinstance(text, str) or not 1 <= len(text) <= MAX_SHARE_ROOT_CHARACTERS or "\x00" in text:
        raise argparse.ArgumentTypeError("invalid share root")
    return text


def _folder_list(text: str) -> tuple:
    if not isinstance(text, str) or not 1 <= len(text) <= 1024:
        raise argparse.ArgumentTypeError("invalid folder list")
    names = tuple(part.strip() for part in text.split(","))
    if not 1 <= len(names) <= MAX_EXPECTED_FOLDERS or len(set(names)) != len(names):
        raise argparse.ArgumentTypeError("invalid folder list")
    for name in names:
        if FOLDER_NAME.fullmatch(name) is None:
            raise argparse.ArgumentTypeError("invalid folder name")
    return names


def _folder_name(text: str) -> str:
    if not isinstance(text, str) or FOLDER_NAME.fullmatch(text) is None:
        raise argparse.ArgumentTypeError("invalid folder name")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = _PathFreeArgumentParser(
        prog="check_synology_readiness.py",
        description=__doc__,
        allow_abbrev=False,
    )
    parser.add_argument("--share-root", type=_share_root, required=True, help="project share root to inspect (never printed)")
    parser.add_argument(
        "--expected-folders",
        type=_folder_list,
        default=DEFAULT_EXPECTED_FOLDERS,
        help="comma-separated first-level folders (default: raw,validated,models,backups)",
    )
    parser.add_argument("--backup-folder", type=_folder_name, default="backups", help="expected folder holding backups")
    parser.add_argument(
        "--no-backup-check",
        action="store_true",
        help="skip backup freshness and manifests (for a share that holds no backups)",
    )
    parser.add_argument(
        "--access",
        choices=("exists", "read", "read-write"),
        default="read-write",
        help=(
            "access the running account must have on expected folders (default: read-write); "
            "'exists' only checks presence and free space, without walking the folders"
        ),
    )
    parser.add_argument("--min-free-gib", type=_bounded_int(0, 1048576), default=100)
    parser.add_argument("--max-backup-age-hours", type=_bounded_int(1, 87600), default=24)
    parser.add_argument("--verify-sha256", action="store_true", help="verify *.sha256 sidecars and recent backup manifests")
    parser.add_argument("--max-hash-files", type=_bounded_int(1, 100000), default=64)
    parser.add_argument("--max-hash-gib", type=_bounded_int(1, 16384), default=32)
    parser.add_argument("--max-entries", type=_bounded_int(1, 5000000), default=200000)
    parser.add_argument("--max-depth", type=_bounded_int(1, 64), default=16)
    parser.add_argument("--time-budget-seconds", type=_bounded_int(5, 86400), default=240)
    parser.add_argument("--require-mount-point", action="store_true", help="refuse a share root that is not a mount point")
    return parser


def parse_arguments(argv) -> argparse.Namespace:
    options = build_parser().parse_args(list(argv))
    if options.access == "exists":
        if options.verify_sha256:
            raise UsageError("sha256 verification needs read access")
        # Presence mode never walks the folders, so backups cannot be measured.
        options.no_backup_check = True
    if not options.no_backup_check and options.backup_folder not in options.expected_folders:
        raise UsageError("backup folder must be an expected folder")
    return options


def _iso(timestamp):
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _age_hours(now: float, timestamp):
    if timestamp is None:
        return None
    return round((now - timestamp) / 3600.0, 1)


def _worst(statuses) -> str:
    result = STATUS_OK
    for status in statuses:
        if STATUS_RANK[status] > STATUS_RANK[result]:
            result = status
    return result


def _status_for(reasons) -> str:
    return _worst(REASON_SEVERITY[reason] for reason in reasons)


def _folder_labels(names) -> dict:
    """Map each expected folder to an output label; private names never leak."""

    labels = {}
    for index, name in enumerate(names, start=1):
        labels[name] = name if name in PUBLIC_FOLDER_LABELS else "folder_{}".format(index)
    return labels


def _is_temporary(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(TEMPORARY_SUFFIXES) or name.startswith(TEMPORARY_PREFIXES)


def _backup_kind(name: str):
    for kind, pattern in BACKUP_KINDS:
        if pattern.fullmatch(name) is not None:
            return kind
    return None


def _identity(metadata) -> tuple:
    return (metadata.st_dev, metadata.st_ino)


def _list_directory(path: str, identity: tuple, limit: int, deadline: float) -> tuple:
    """Return up to ``limit`` (name, lstat) pairs and whether the listing stopped early.

    The listing also stops, reported as truncated, once ``deadline`` (a
    ``time.monotonic`` value) has passed.
    """

    entries = []
    if _DESCRIPTOR_WALK:
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISDIR(opened.st_mode) or _identity(opened) != identity:
                raise _IdentityChanged("directory identity changed")
            with os.scandir(descriptor) as iterator:
                for entry in iterator:
                    if len(entries) >= limit or _listing_expired(len(entries), deadline):
                        return entries, True
                    entries.append((entry.name, entry.stat(follow_symlinks=False)))
        finally:
            os.close(descriptor)
        return entries, False
    before = os.lstat(path)
    if not stat.S_ISDIR(before.st_mode) or _identity(before) != identity:
        raise _IdentityChanged("directory identity changed")
    with os.scandir(path) as iterator:
        for entry in iterator:
            if len(entries) >= limit or _listing_expired(len(entries), deadline):
                return entries, True
            entries.append((entry.name, os.lstat(os.path.join(path, entry.name))))
    return entries, False


def _listing_expired(count: int, deadline: float) -> bool:
    return count % LISTING_DEADLINE_STRIDE == 0 and time.monotonic() > deadline


def _symlink_escapes(root: str, directory: str, name: str) -> bool:
    """Decide lexically, without following it, whether a link leaves the root."""

    try:
        target = os.readlink(os.path.join(directory, name))
    except (OSError, ValueError):
        return True
    if isinstance(target, bytes):
        return True
    if os.name == "nt" and target.startswith("\\\\?\\"):
        target = target[4:]
    candidate = os.path.normpath(target if os.path.isabs(target) else os.path.join(directory, target))
    try:
        return os.path.commonpath([root, candidate]) != root
    except ValueError:
        return True


class _Walk:
    """Bounded, symlink-free walk that only keeps aggregate numbers."""

    def __init__(self, options, root: str, root_metadata, labels: dict, now: float, deadline: float) -> None:
        self.options = options
        self.root = root
        self.root_device = root_metadata.st_dev
        self.root_identity = _identity(root_metadata)
        self.labels = labels
        self.now = now
        self.deadline = deadline
        self.entries = 0
        self.directories = 0
        self.files = 0
        self.bytes = 0
        self.symlinks = 0
        self.symlinks_escaping = 0
        self.special_files = 0
        self.unreadable_directories = 0
        self.identity_changed = 0
        self.metadata_directories_skipped = 0
        self.depth_limited = 0
        self.mount_crossings_refused = 0
        self.unexpected_top_level_entries = 0
        self.future_mtime_files = 0
        self.temporary_files = 0
        self.empty_files = 0
        self.truncated = False
        self.newest = None
        self.per_label = {label: {"files": 0, "bytes": 0, "newest": None} for label in labels.values()}
        # ``files``/``bytes`` count every non-temporary file of the backup
        # folder; freshness only counts recognised backup artifacts, so that a
        # manifest or a stray file can never stand in for a backup.
        self.backup = {
            "files": 0,
            "bytes": 0,
            "artifacts": 0,
            "newest": None,
            "future": 0,
            "kinds": {kind: {"files": 0, "newest": None} for kind, _ in BACKUP_KINDS},
        }
        self.sidecars = []
        self.manifests = {kind: [] for kind, _ in BACKUP_KINDS}

    def _out_of_budget(self) -> bool:
        return self.entries >= self.options.max_entries or time.monotonic() > self.deadline

    def run(self) -> None:
        backup_name = None if self.options.no_backup_check else self.options.backup_folder
        stack = [(self.root, self.root_identity, 0, None, False)]
        while stack:
            path, identity, depth, label, in_backup = stack.pop()
            if self._out_of_budget():
                self.truncated = True
                return
            try:
                listing, more = _list_directory(path, identity, self.options.max_entries - self.entries + 1, self.deadline)
            except _IdentityChanged:
                self.identity_changed += 1
                continue
            except OSError:
                self.unreadable_directories += 1
                continue
            self.directories += 1
            for name, metadata in listing:
                if self._out_of_budget():
                    self.truncated = True
                    return
                self.entries += 1
                if depth == 0:
                    child_label = self.labels.get(name)
                    child_in_backup = name == backup_name
                else:
                    child_label = label
                    child_in_backup = in_backup
                mode = metadata.st_mode
                if stat.S_ISLNK(mode):
                    self.symlinks += 1
                    if _symlink_escapes(self.root, path, name):
                        self.symlinks_escaping += 1
                    continue
                if stat.S_ISDIR(mode):
                    if name in METADATA_DIRECTORIES:
                        self.metadata_directories_skipped += 1
                        continue
                    if depth == 0 and child_label is None:
                        self.unexpected_top_level_entries += 1
                    if metadata.st_dev != self.root_device:
                        self.mount_crossings_refused += 1
                        continue
                    if depth + 1 > self.options.max_depth:
                        self.depth_limited += 1
                        continue
                    stack.append((os.path.join(path, name), _identity(metadata), depth + 1, child_label, child_in_backup))
                    continue
                if stat.S_ISREG(mode):
                    if depth == 0:
                        self.unexpected_top_level_entries += 1
                    self._record_file(path, name, metadata, child_label, child_in_backup)
                    continue
                self.special_files += 1
            if more:
                self.truncated = True
                return

    def _record_file(self, directory: str, name: str, metadata, label, in_backup: bool) -> None:
        size = metadata.st_size
        mtime = metadata.st_mtime
        self.files += 1
        self.bytes += size
        temporary = _is_temporary(name)
        if temporary:
            self.temporary_files += 1
        elif size == 0:
            self.empty_files += 1
        future = mtime > self.now + FUTURE_TOLERANCE_SECONDS
        if future:
            self.future_mtime_files += 1
        if self.newest is None or mtime > self.newest:
            self.newest = mtime
        if label is not None:
            bucket = self.per_label[label]
            bucket["files"] += 1
            bucket["bytes"] += size
            if bucket["newest"] is None or mtime > bucket["newest"]:
                bucket["newest"] = mtime
        if in_backup and not temporary:
            backup = self.backup
            backup["files"] += 1
            backup["bytes"] += size
            kind = _backup_kind(name)
            if kind is not None:
                backup["artifacts"] += 1
                if future:
                    backup["future"] += 1
                if backup["newest"] is None or mtime > backup["newest"]:
                    backup["newest"] = mtime
                bucket = backup["kinds"][kind]
                bucket["files"] += 1
                if bucket["newest"] is None or mtime > bucket["newest"]:
                    bucket["newest"] = mtime
        if not self.options.verify_sha256 or temporary:
            return
        if name.lower().endswith(SIDECAR_SUFFIX) and len(name) > len(SIDECAR_SUFFIX):
            self.sidecars.append((mtime, directory, name, _identity(metadata)))
        elif in_backup and name.endswith(".json"):
            kind = _backup_kind(name[: -len(".json")] + ".sqlite3")
            if kind is not None:
                self.manifests[kind].append((mtime, directory, name, _identity(metadata)))


def _open_regular(path: str, identity: tuple):
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or _identity(metadata) != identity:
            raise _Refused("not the listed regular file")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, metadata


def _read_small_document(path: str, identity: tuple) -> bytes:
    descriptor, before = _open_regular(path, identity)
    try:
        if before.st_size > SMALL_DOCUMENT_MAX_BYTES:
            raise _InvalidDocument("document too large")
        chunks = []
        total = 0
        while total <= SMALL_DOCUMENT_MAX_BYTES:
            chunk = os.read(descriptor, SMALL_DOCUMENT_MAX_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(payload) != before.st_size or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise _ChangedDuringRead("document changed while read")
    return payload


def _hash_regular_file(path: str, identity: tuple, remaining_bytes: int, deadline: float) -> tuple:
    descriptor, before = _open_regular(path, identity)
    try:
        if before.st_size > remaining_bytes:
            raise _BudgetExhausted("byte budget")
        digest = hashlib.sha256()
        total = 0
        while True:
            if time.monotonic() > deadline:
                raise _BudgetExhausted("time budget")
            chunk = os.read(descriptor, CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > before.st_size:
                raise _ChangedDuringRead("file grew while read")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if total != before.st_size or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise _ChangedDuringRead("file changed while read")
    return digest.hexdigest(), total


def _parse_sidecar(payload: bytes, target_name: str) -> str:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        raise _InvalidDocument("sidecar is not ASCII") from None
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise _InvalidDocument("sidecar must hold exactly one entry")
    match = SIDECAR_LINE.fullmatch(lines[0].rstrip())
    if match is None:
        raise _InvalidDocument("sidecar format is invalid")
    listed = match.group(2)
    if listed is not None and listed != target_name:
        raise _InvalidDocument("sidecar names another file")
    return match.group(1).lower()


def _reject_duplicate_keys(pairs):
    document = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _reject_constant(name: str):
    raise ValueError("non-finite number")


def _parse_manifest(payload: bytes, artifact_name: str) -> tuple:
    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError):
        raise _InvalidDocument("manifest is not strict JSON") from None
    if not isinstance(document, dict) or set(document) != BACKUP_MANIFEST_KEYS:
        raise _InvalidDocument("manifest fields are invalid")
    digest = document["sha256"]
    size = document["bytes"]
    if (
        document["schema_version"] not in BACKUP_MANIFEST_SCHEMAS
        or document["artifact"] != artifact_name
        or not isinstance(digest, str)
        or SHA256_HEX.fullmatch(digest) is None
        or type(size) is not int
        or size < 0
    ):
        raise _InvalidDocument("manifest values are invalid")
    return digest, size


class _Verification:
    """Verify sidecars and recent backup manifests within explicit budgets."""

    def __init__(self, options, root_device: int, deadline: float) -> None:
        self.options = options
        self.root_device = root_device
        self.deadline = deadline
        self.remaining_bytes = options.max_hash_gib * GIB
        self.remaining_files = options.max_hash_files
        self.counts = {
            "sidecars": 0,
            "manifests": 0,
            "manifests_not_selected": 0,
            "verified": 0,
            "mismatched": 0,
            "missing_targets": 0,
            "invalid_documents": 0,
            "refused_targets": 0,
            "unreadable": 0,
            "changed_during_read": 0,
            "skipped_budget": 0,
            "manifests_skipped_budget": 0,
            "bytes_hashed": 0,
        }

    def run(self, walk: _Walk) -> None:
        # Backup manifests come first: a flood of sidecars must never use up
        # the budget and leave a corrupt backup unverified.
        work = []
        for kind, _ in BACKUP_KINDS:
            candidates = sorted(walk.manifests[kind], key=lambda item: item[0], reverse=True)
            self.counts["manifests_not_selected"] += max(0, len(candidates) - BACKUP_MANIFESTS_PER_KIND)
            for mtime, directory, name, identity in candidates[:BACKUP_MANIFESTS_PER_KIND]:
                self.counts["manifests"] += 1
                work.append(("manifest", directory, name, identity))
        for mtime, directory, name, identity in sorted(walk.sidecars, key=lambda item: item[0], reverse=True):
            self.counts["sidecars"] += 1
            work.append(("sidecar", directory, name, identity))
        for index, item in enumerate(work):
            if self.remaining_files <= 0 or time.monotonic() > self.deadline:
                for skipped in work[index:]:
                    self._count_budget_skip(skipped[0])
                return
            self.remaining_files -= 1
            self._verify_one(*item)

    def _count_budget_skip(self, kind: str) -> None:
        self.counts["skipped_budget"] += 1
        if kind == "manifest":
            self.counts["manifests_skipped_budget"] += 1

    def _verify_one(self, kind: str, directory: str, name: str, identity: tuple) -> None:
        try:
            payload = _read_small_document(os.path.join(directory, name), identity)
            if kind == "sidecar":
                target_name = name[: -len(SIDECAR_SUFFIX)]
                expected_digest = _parse_sidecar(payload, target_name)
                expected_size = None
            else:
                target_name = name[: -len(".json")] + ".sqlite3"
                expected_digest, expected_size = _parse_manifest(payload, target_name)
        except _InvalidDocument:
            self.counts["invalid_documents"] += 1
            return
        except _ChangedDuringRead:
            self.counts["changed_during_read"] += 1
            return
        except (_Refused, OSError):
            self.counts["unreadable"] += 1
            return
        target = os.path.join(directory, target_name)
        try:
            metadata = os.lstat(target)
        except FileNotFoundError:
            self.counts["missing_targets"] += 1
            return
        except OSError:
            self.counts["unreadable"] += 1
            return
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_dev != self.root_device:
            self.counts["refused_targets"] += 1
            return
        if expected_size is not None and metadata.st_size != expected_size:
            self.counts["mismatched"] += 1
            return
        try:
            digest, size = _hash_regular_file(target, _identity(metadata), self.remaining_bytes, self.deadline)
        except _BudgetExhausted:
            self._count_budget_skip(kind)
            return
        except _ChangedDuringRead:
            self.counts["changed_during_read"] += 1
            return
        except _Refused:
            self.counts["refused_targets"] += 1
            return
        except OSError:
            self.counts["unreadable"] += 1
            return
        self.remaining_bytes -= size
        self.counts["bytes_hashed"] += size
        if digest == expected_digest:
            self.counts["verified"] += 1
        else:
            self.counts["mismatched"] += 1


def _check_share_root(root: str, options) -> tuple:
    reasons = []
    metadata = None
    try:
        metadata = os.lstat(root)
    except FileNotFoundError:
        reasons.append("share_root_missing")
    except OSError:
        reasons.append("share_root_not_accessible")
    if metadata is not None:
        if stat.S_ISLNK(metadata.st_mode):
            reasons.append("share_root_symlink_refused")
        elif not stat.S_ISDIR(metadata.st_mode):
            reasons.append("share_root_not_directory")
        elif not os.access(root, os.R_OK | os.X_OK):
            reasons.append("share_root_not_accessible")
    mount_point = False
    if metadata is not None and stat.S_ISDIR(metadata.st_mode):
        try:
            mount_point = bool(os.path.ismount(root))
        except (OSError, ValueError):
            mount_point = False
        if options.require_mount_point and not mount_point:
            reasons.append("share_root_not_mount_point")
    usable = not reasons or reasons == ["share_root_not_mount_point"]
    check = {"status": _status_for(reasons), "mount_point": mount_point}
    return check, reasons, (metadata if usable and metadata is not None else None)


def _check_folders(root: str, options) -> tuple:
    reasons = []
    states = {}
    required = os.R_OK | os.X_OK
    writable = os.W_OK | os.X_OK
    for name in options.expected_folders:
        path = os.path.join(root, name)
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            state = "missing"
        except OSError:
            state = "not_readable"
        else:
            if stat.S_ISLNK(metadata.st_mode):
                state = "symlink_refused"
            elif not stat.S_ISDIR(metadata.st_mode):
                state = "not_directory"
            elif not os.access(path, required):
                # Presence mode accepts a folder that exists but is closed to
                # the running account, such as the inspection account.
                state = "present" if options.access == "exists" else "not_readable"
            elif options.access == "read-write" and not os.access(path, writable):
                state = "not_writable"
            else:
                state = "ok"
        states[name] = state
        if state not in ("ok", "present"):
            reasons.append("folder_" + state)
    return states, sorted(set(reasons))


def _check_free_space(root: str, options) -> tuple:
    try:
        usage = _disk_usage(root)
        total, used, free = int(usage[0]), int(usage[1]), int(usage[2])
    except (OSError, ValueError, TypeError, IndexError):
        return {"status": STATUS_NOT_READY, "min_free_gib": options.min_free_gib}, ["free_space_unavailable"]
    if total <= 0 or free < 0 or used < 0:
        return {"status": STATUS_NOT_READY, "min_free_gib": options.min_free_gib}, ["free_space_unavailable"]
    reasons = []
    if free < options.min_free_gib * GIB:
        reasons.append("free_space_below_threshold")
    check = {
        "status": _status_for(reasons),
        "free_gib": free // GIB,
        "total_gib": total // GIB,
        "used_percent": int(round(100.0 * used / total)),
        "min_free_gib": options.min_free_gib,
    }
    return check, reasons


def _check_backups(walk: _Walk, folder_ok: bool, options, now: float) -> tuple:
    maximum_age_seconds = options.max_backup_age_hours * 3600
    if not folder_ok:
        reasons = ["backup_folder_unavailable"]
        return {"status": _status_for(reasons), "max_age_hours": options.max_backup_age_hours}, reasons
    backup = walk.backup
    reasons = []
    kinds = {}
    missing_kinds = 0
    for kind, _ in BACKUP_KINDS:
        bucket = backup["kinds"][kind]
        kinds[kind] = {
            "files": bucket["files"],
            "newest_at": _iso(bucket["newest"]),
            "newest_age_hours": _age_hours(now, bucket["newest"]),
        }
        if bucket["newest"] is None:
            missing_kinds += 1
        elif now - bucket["newest"] > maximum_age_seconds:
            reasons.append("backup_stale")
    if backup["artifacts"] == 0:
        reasons.append("backup_missing")
    elif missing_kinds:
        reasons.append("backup_kind_missing")
    if backup["future"]:
        reasons.append("backup_in_future")
    reasons = sorted(set(reasons))
    check = {
        "status": _status_for(reasons),
        "files": backup["files"],
        "bytes": backup["bytes"],
        "artifacts": backup["artifacts"],
        "newest_at": _iso(backup["newest"]),
        "newest_age_hours": _age_hours(now, backup["newest"]),
        "future_files": backup["future"],
        "kinds": kinds,
        "max_age_hours": options.max_backup_age_hours,
    }
    return check, reasons


def _walk_reasons(walk: _Walk) -> list:
    reasons = []
    if walk.symlinks:
        reasons.append("symlinks_present")
    if walk.symlinks_escaping:
        reasons.append("symlink_escape_refused")
    if walk.special_files:
        reasons.append("special_files_present")
    if walk.unreadable_directories:
        reasons.append("unreadable_directories")
    if walk.truncated:
        reasons.append("walk_truncated")
    if walk.depth_limited:
        reasons.append("walk_depth_limited")
    if walk.identity_changed:
        reasons.append("walk_identity_changed")
    if walk.mount_crossings_refused:
        reasons.append("mount_crossing_refused")
    if walk.future_mtime_files:
        reasons.append("future_mtime_present")
    return reasons


def _verification_reasons(counts: dict) -> list:
    reasons = []
    if counts["mismatched"]:
        reasons.append("sha256_mismatch")
    if counts["missing_targets"]:
        reasons.append("sha256_target_missing")
    if counts["invalid_documents"]:
        reasons.append("sha256_document_invalid")
    if counts["refused_targets"]:
        reasons.append("sha256_target_refused")
    if counts["unreadable"]:
        reasons.append("sha256_unreadable")
    if counts["changed_during_read"]:
        reasons.append("sha256_changed_during_read")
    if counts["manifests_skipped_budget"]:
        reasons.append("sha256_backup_budget_exhausted")
    if counts["skipped_budget"] > counts["manifests_skipped_budget"]:
        reasons.append("sha256_budget_exhausted")
    if counts["sidecars"] + counts["manifests"] == 0:
        reasons.append("sha256_nothing_to_verify")
    return reasons


def _limits(options) -> dict:
    return {
        "access": options.access,
        "backup_check": not options.no_backup_check,
        "max_backup_age_hours": options.max_backup_age_hours,
        "max_depth": options.max_depth,
        "max_entries": options.max_entries,
        "max_hash_files": options.max_hash_files,
        "max_hash_gib": options.max_hash_gib,
        "min_free_gib": options.min_free_gib,
        "require_mount_point": options.require_mount_point,
        "time_budget_seconds": options.time_budget_seconds,
        "verify_sha256": options.verify_sha256,
    }


def _finish(report: dict, reasons) -> dict:
    statuses = [check["status"] for check in report["checks"].values()]
    statuses.extend(REASON_SEVERITY[reason] for reason in reasons)
    report["overall"] = OVERALL_BY_STATUS[_worst(statuses)]
    report["reasons"] = sorted(set(reasons))
    return report


def run_checks(options, now=None) -> dict:
    """Run every read-only check and return the path-free report."""

    started = time.monotonic()
    deadline = started + options.time_budget_seconds
    now = time.time() if now is None else float(now)
    root = os.path.normpath(os.path.abspath(options.share_root))
    labels = _folder_labels(options.expected_folders)
    report = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _iso(now),
        "limits": _limits(options),
        "checks": {},
    }
    reasons = []
    root_check, root_reasons, root_metadata = _check_share_root(root, options)
    report["checks"]["share_root"] = root_check
    reasons.extend(root_reasons)
    if root_metadata is None:
        skipped = {"status": STATUS_SKIPPED}
        for name in ("expected_folders", "free_space", "walk", "backups", "temporary_files", "sha256"):
            report["checks"][name] = dict(skipped)
        return _finish(report, reasons)

    states, folder_reasons = _check_folders(root, options)
    reasons.extend(folder_reasons)
    free_check, free_reasons = _check_free_space(root, options)
    report["checks"]["free_space"] = free_check
    reasons.extend(free_reasons)

    if options.access == "exists":
        return _finish_presence(report, reasons, states, folder_reasons, labels, options, started)

    walk = _Walk(options, root, root_metadata, labels, now, deadline)
    walk.run()

    folders = {}
    for name in options.expected_folders:
        label = labels[name]
        bucket = walk.per_label[label]
        folders[label] = {
            "state": states[name],
            "files": bucket["files"],
            "bytes": bucket["bytes"],
            "newest_at": _iso(bucket["newest"]),
        }
    report["checks"]["expected_folders"] = {"status": _status_for(folder_reasons), "folders": folders}

    walk_reasons = _walk_reasons(walk)
    reasons.extend(walk_reasons)
    report["checks"]["walk"] = {
        "status": _status_for(walk_reasons),
        "directories": walk.directories,
        "files": walk.files,
        "bytes": walk.bytes,
        "newest_at": _iso(walk.newest),
        "symlinks": walk.symlinks,
        "symlinks_escaping": walk.symlinks_escaping,
        "special_files": walk.special_files,
        "unreadable_directories": walk.unreadable_directories,
        "identity_changed": walk.identity_changed,
        "metadata_directories_skipped": walk.metadata_directories_skipped,
        "depth_limited": walk.depth_limited,
        "mount_crossings_refused": walk.mount_crossings_refused,
        "unexpected_top_level_entries": walk.unexpected_top_level_entries,
        "future_mtime_files": walk.future_mtime_files,
        "truncated": walk.truncated,
    }

    if options.no_backup_check:
        report["checks"]["backups"] = {"status": STATUS_SKIPPED, "max_age_hours": options.max_backup_age_hours}
    else:
        backup_ok = states[options.backup_folder] == "ok" or (
            options.access == "read-write" and states[options.backup_folder] == "not_writable"
        )
        backup_check, backup_reasons = _check_backups(walk, backup_ok, options, now)
        report["checks"]["backups"] = backup_check
        reasons.extend(backup_reasons)

    temporary_reasons = []
    if walk.temporary_files:
        temporary_reasons.append("temporary_files_present")
    if walk.empty_files:
        temporary_reasons.append("empty_files_present")
    reasons.extend(temporary_reasons)
    report["checks"]["temporary_files"] = {
        "status": _status_for(temporary_reasons),
        "temporary": walk.temporary_files,
        "empty": walk.empty_files,
    }

    if options.verify_sha256:
        verification = _Verification(options, walk.root_device, deadline)
        verification.run(walk)
        verification_reasons = _verification_reasons(verification.counts)
        reasons.extend(verification_reasons)
        sha_check = {"status": _status_for(verification_reasons)}
        sha_check.update(verification.counts)
        report["checks"]["sha256"] = sha_check
    else:
        report["checks"]["sha256"] = {"status": STATUS_SKIPPED}
    report["elapsed_seconds"] = round(time.monotonic() - started, 1)
    return _finish(report, reasons)


def _finish_presence(report: dict, reasons: list, states: dict, folder_reasons: list, labels: dict, options, started: float) -> dict:
    """Presence mode: folders and free space only; nothing below the folders is listed."""

    folders = {}
    for name in options.expected_folders:
        folders[labels[name]] = {"state": states[name], "files": None, "bytes": None, "newest_at": None}
    report["checks"]["expected_folders"] = {"status": _status_for(folder_reasons), "folders": folders}
    for name in ("walk", "backups", "temporary_files", "sha256"):
        report["checks"][name] = {"status": STATUS_SKIPPED}
    report["elapsed_seconds"] = round(time.monotonic() - started, 1)
    return _finish(report, reasons)


def _failure_report(now: float) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _iso(now),
        "overall": "not_ready",
        "reasons": ["internal_error"],
        "checks": {},
    }


def main(argv=None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        options = parse_arguments(arguments)
    except _HelpRequested:
        return EXIT_USAGE
    except UsageError:
        print("usage error: invalid command line; run with --help", file=sys.stderr)
        return EXIT_USAGE
    try:
        report = run_checks(options)
        encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except Exception:  # fail closed without echoing a message that could hold a path
        report = _failure_report(time.time())
        encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()
    return EXIT_BY_OVERALL[report["overall"]]


if __name__ == "__main__":
    raise SystemExit(main())
