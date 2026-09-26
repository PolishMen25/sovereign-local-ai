"""Tests for the read-only Synology restart readiness checker."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests._temp_support import sovereign_temporary_directory
from tools import check_synology_readiness as readiness


TOOL_PATH = Path(__file__).parents[1] / "tools" / "check_synology_readiness.py"
HOUR = 3600
GIB = 1024 ** 3
SHARE_NAME = "share-private-name"


def _write(path: Path, payload: bytes, *, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _write_sidecar(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = path.with_name(path.name + ".sha256")
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return sidecar


def _write_backup(directory: Path, prefix: str, schema: str, payload: bytes, mtime: float) -> tuple[Path, Path]:
    digest = hashlib.sha256(payload).hexdigest()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(mtime))
    name = f"{prefix}-{stamp}-{digest[:16]}.sqlite3"
    artifact = _write(directory / name, payload, mtime=mtime)
    document = {"schema_version": schema, "artifact": name, "sha256": digest, "bytes": len(payload)}
    manifest = _write(
        artifact.with_suffix(".json"),
        json.dumps(document, sort_keys=True).encode("utf-8"),
        mtime=mtime,
    )
    return artifact, manifest


def _symlink_or_skip(test: unittest.TestCase, target: Path, link: Path, *, directory: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        test.skipTest("symbolic links are not permitted in this environment")


class SynologyReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        context = sovereign_temporary_directory()
        self.root = Path(context.__enter__())
        self.addCleanup(context.__exit__, None, None, None)

    def build_share(self, *, backup_age_hours: float = 1.0) -> Path:
        share = self.root / SHARE_NAME
        for folder in ("raw", "validated", "models"):
            (share / folder).mkdir(parents=True)
        _write(share / "raw" / "synthetic-archive.tar.gz", b"synthetic raw bytes")
        _write(share / "validated" / "catalogue.jsonl", b'{"id":"synthetic"}\n')
        model = _write(share / "models" / "synthetic-model.gguf", b"synthetic model bytes" * 64)
        _write_sidecar(model)
        mtime = time.time() - backup_age_hours * HOUR
        _write_backup(share / "backups", "memory", "private-memory-backup.v1", b"synthetic memory backup", mtime)
        _write_backup(
            share / "backups" / "knowledge-index",
            "knowledge-index",
            "knowledge-index-backup.v1",
            b"synthetic index backup",
            mtime,
        )
        return share

    def check(self, share: Path, *extra: str) -> dict:
        options = readiness.parse_arguments(["--share-root", str(share), "--min-free-gib", "0", *extra])
        return readiness.run_checks(options)

    def cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = readiness.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_path_free(self, output: str, share: Path) -> None:
        for fragment in (str(self.root), json.dumps(str(self.root))[1:-1], SHARE_NAME, "synthetic", "memory-", ".gguf"):
            self.assertNotIn(fragment, output)
        self.assertNotIn("/", output)
        self.assertNotIn("\\", output)

    # Nominal path -----------------------------------------------------------------

    def test_nominal_share_is_ready_and_verified(self) -> None:
        share = self.build_share()
        code, stdout, stderr = self.cli(["--share-root", str(share), "--min-free-gib", "0", "--verify-sha256"])
        self.assertEqual((code, stderr), (0, ""))
        report = json.loads(stdout)
        self.assertEqual(report["schema_version"], "synology-readiness.v1")
        self.assertEqual(report["overall"], "ready")
        self.assertEqual(report["reasons"], [])
        self.assertTrue(report["observed_at"].endswith("Z"))
        folders = report["checks"]["expected_folders"]["folders"]
        self.assertEqual(sorted(folders), ["backups", "models", "raw", "validated"])
        self.assertTrue(all(folder["state"] == "ok" for folder in folders.values()))
        self.assertEqual(folders["backups"]["files"], 4)
        backups = report["checks"]["backups"]
        self.assertEqual(backups["kinds"]["memory"]["files"], 1)
        self.assertEqual(backups["kinds"]["knowledge-index"]["files"], 1)
        self.assertAlmostEqual(backups["newest_age_hours"], 1.0, delta=0.2)
        sha = report["checks"]["sha256"]
        self.assertEqual((sha["sidecars"], sha["manifests"], sha["verified"], sha["mismatched"]), (1, 2, 3, 0))
        self.assert_path_free(stdout, share)

    def test_read_only_access_mode_accepts_a_read_only_account(self) -> None:
        share = self.build_share()
        real_access = os.access

        def no_write(path, mode, *args, **kwargs):
            return False if mode & os.W_OK else real_access(path, mode, *args, **kwargs)

        with mock.patch.object(readiness.os, "access", side_effect=no_write):
            refused = self.check(share)
            accepted = self.check(share, "--access", "read")
        self.assertEqual(refused["overall"], "not_ready")
        self.assertIn("folder_not_writable", refused["reasons"])
        self.assertEqual(refused["checks"]["backups"]["status"], "ok")
        self.assertEqual(accepted["overall"], "ready")

    def test_metadata_directories_are_not_inspected(self) -> None:
        share = self.build_share()
        _write(share / "models" / "@eaDir" / "thumbnail.tmp", b"")
        report = self.check(share)
        self.assertEqual(report["overall"], "ready")
        self.assertEqual(report["checks"]["walk"]["metadata_directories_skipped"], 1)
        self.assertEqual(report["checks"]["temporary_files"]["temporary"], 0)

    # Not ready ----------------------------------------------------------------------

    def test_missing_expected_folder_is_not_ready(self) -> None:
        share = self.build_share()
        shutil.rmtree(share / "validated")
        code, stdout, _ = self.cli(["--share-root", str(share), "--min-free-gib", "0"])
        report = json.loads(stdout)
        self.assertEqual(code, 2)
        self.assertEqual(report["overall"], "not_ready")
        self.assertIn("folder_missing", report["reasons"])
        self.assertEqual(report["checks"]["expected_folders"]["folders"]["validated"]["state"], "missing")
        self.assert_path_free(stdout, share)

    def test_missing_or_non_directory_share_root_is_not_ready(self) -> None:
        missing = self.check(self.root / "absent")
        self.assertEqual(missing["reasons"], ["share_root_missing"])
        self.assertEqual(missing["checks"]["walk"], {"status": "skipped"})
        regular = _write(self.root / "regular-file", b"x")
        self.assertEqual(self.check(regular)["reasons"], ["share_root_not_directory"])

    def test_unreadable_folder_is_not_ready(self) -> None:
        share = self.build_share()
        real_access = os.access
        denied = os.path.normpath(os.path.abspath(str(share / "raw")))

        def deny_raw(path, mode, *args, **kwargs):
            return False if str(path) == denied else real_access(path, mode, *args, **kwargs)

        with mock.patch.object(readiness.os, "access", side_effect=deny_raw):
            report = self.check(share)
        self.assertEqual(report["overall"], "not_ready")
        self.assertEqual(report["checks"]["expected_folders"]["folders"]["raw"]["state"], "not_readable")

    def test_unreadable_backup_folder_blocks_backup_check(self) -> None:
        share = self.build_share()
        real_access = os.access
        denied = os.path.normpath(os.path.abspath(str(share / "backups")))

        def deny_backups(path, mode, *args, **kwargs):
            return False if str(path) == denied else real_access(path, mode, *args, **kwargs)

        with mock.patch.object(readiness.os, "access", side_effect=deny_backups):
            report = self.check(share)
        self.assertEqual(report["checks"]["backups"]["status"], "not_ready")
        self.assertIn("backup_folder_unavailable", report["reasons"])

    def test_free_space_below_threshold_is_not_ready(self) -> None:
        share = self.build_share()
        report = self.check(share, "--min-free-gib", "1048576")
        self.assertEqual(report["overall"], "not_ready")
        self.assertEqual(report["reasons"], ["free_space_below_threshold"])

    def test_injected_low_free_space_is_not_ready(self) -> None:
        share = self.build_share()
        with mock.patch.object(readiness, "_disk_usage", return_value=(100 * GIB, 99 * GIB, GIB)):
            report = self.check(share, "--min-free-gib", "10")
        free = report["checks"]["free_space"]
        self.assertEqual((free["status"], free["free_gib"], free["total_gib"], free["used_percent"]), ("not_ready", 1, 100, 99))

    def test_unavailable_free_space_fails_closed(self) -> None:
        share = self.build_share()
        with mock.patch.object(readiness, "_disk_usage", side_effect=OSError("synthetic")):
            report = self.check(share)
        self.assertEqual(report["reasons"], ["free_space_unavailable"])
        self.assertEqual(report["overall"], "not_ready")

    def test_required_mount_point_refuses_a_plain_directory(self) -> None:
        share = self.build_share()
        report = self.check(share, "--require-mount-point")
        self.assertIn("share_root_not_mount_point", report["reasons"])
        self.assertEqual(report["overall"], "not_ready")

    # Attention ----------------------------------------------------------------------

    def test_stale_backup_is_attention(self) -> None:
        share = self.build_share(backup_age_hours=48)
        code, stdout, _ = self.cli(["--share-root", str(share), "--min-free-gib", "0"])
        report = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(report["overall"], "attention")
        self.assertEqual(report["reasons"], ["backup_stale"])
        self.assertAlmostEqual(report["checks"]["backups"]["newest_age_hours"], 48.0, delta=0.2)
        relaxed = self.check(share, "--max-backup-age-hours", "72")
        self.assertEqual(relaxed["overall"], "ready")

    def test_one_stale_backup_kind_is_attention(self) -> None:
        share = self.build_share(backup_age_hours=48)
        _write_backup(share / "backups", "memory", "private-memory-backup.v1", b"fresh memory", time.time() - 60)
        report = self.check(share)
        self.assertEqual(report["reasons"], ["backup_stale"])
        self.assertAlmostEqual(report["checks"]["backups"]["kinds"]["knowledge-index"]["newest_age_hours"], 48.0, delta=0.2)

    def test_missing_or_future_backup_is_attention(self) -> None:
        share = self.build_share()
        shutil.rmtree(share / "backups")
        (share / "backups").mkdir()
        self.assertEqual(self.check(share)["reasons"], ["backup_missing"])
        _write(share / "backups" / "late.sqlite3", b"x", mtime=time.time() + 2 * HOUR)
        future_artifact, _ = _write_backup(
            share / "backups", "memory", "private-memory-backup.v1", b"future memory", time.time() + 2 * HOUR
        )
        report = self.check(share)
        self.assertEqual(report["reasons"], ["backup_in_future", "backup_kind_missing", "future_mtime_present"])
        self.assertEqual(report["checks"]["backups"]["future_files"], 1)
        self.assertTrue(future_artifact.is_file())

    def test_stray_files_or_manifests_never_count_as_a_backup(self) -> None:
        share = self.build_share()
        shutil.rmtree(share / "backups")
        _write(share / "backups" / "notes.txt", b"not a backup")
        stray = self.check(share)
        self.assertEqual((stray["overall"], stray["reasons"]), ("attention", ["backup_missing"]))
        self.assertEqual((stray["checks"]["backups"]["files"], stray["checks"]["backups"]["artifacts"]), (1, 0))
        _, manifest = _write_backup(share / "backups", "memory", "private-memory-backup.v1", b"memory", time.time())
        for artifact in (share / "backups").glob("*.sqlite3"):
            artifact.unlink()
        self.assertTrue(manifest.is_file())
        only_manifest = self.check(share, "--max-backup-age-hours", "1")
        self.assertEqual(only_manifest["reasons"], ["backup_missing"])
        self.assertIsNone(only_manifest["checks"]["backups"]["newest_at"])

    def test_one_missing_backup_kind_is_attention(self) -> None:
        share = self.build_share(backup_age_hours=0.25)
        shutil.rmtree(share / "backups" / "knowledge-index")
        code, stdout, _ = self.cli(["--share-root", str(share), "--min-free-gib", "0", "--max-backup-age-hours", "1"])
        report = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(report["reasons"], ["backup_kind_missing"])
        kinds = report["checks"]["backups"]["kinds"]
        self.assertEqual((kinds["memory"]["files"], kinds["knowledge-index"]["files"]), (1, 0))
        self.assertIsNone(kinds["knowledge-index"]["newest_age_hours"])

    def test_temporary_file_is_attention_and_not_a_fresh_backup(self) -> None:
        share = self.build_share(backup_age_hours=48)
        _write(share / "models" / "synthetic-model.gguf.partial", b"half")
        _write(share / "backups" / "memory-staged.sqlite3.tmp", b"staged")
        report = self.check(share)
        self.assertEqual(report["overall"], "attention")
        self.assertEqual(report["reasons"], ["backup_stale", "temporary_files_present"])
        self.assertEqual(report["checks"]["temporary_files"]["temporary"], 2)

    def test_empty_file_is_attention(self) -> None:
        share = self.build_share()
        _write(share / "validated" / "truncated.bin", b"")
        report = self.check(share)
        self.assertEqual(report["reasons"], ["empty_files_present"])
        self.assertEqual(report["checks"]["temporary_files"]["empty"], 1)

    def test_walk_bounds_are_attention(self) -> None:
        share = self.build_share()
        truncated = self.check(share, "--max-entries", "3")
        self.assertTrue(truncated["checks"]["walk"]["truncated"])
        self.assertIn("walk_truncated", truncated["reasons"])
        shallow = self.check(share, "--max-depth", "1")
        # The knowledge-index backups sit one level deeper and stay unseen.
        self.assertEqual(shallow["reasons"], ["backup_kind_missing", "walk_depth_limited"])
        self.assertEqual(shallow["overall"], "attention")

    def test_listing_stops_once_the_time_budget_is_spent(self) -> None:
        share = self.build_share()
        directory = share / "raw"
        identity = readiness._identity(os.lstat(directory))
        entries, stopped = readiness._list_directory(str(directory), identity, 10, time.monotonic() - 1)
        self.assertEqual((entries, stopped), ([], True))
        entries, stopped = readiness._list_directory(str(directory), identity, 10, time.monotonic() + 60)
        self.assertEqual((len(entries), stopped), (1, False))

    # SHA-256 verification ------------------------------------------------------------

    def test_sidecar_mismatch_is_not_ready(self) -> None:
        share = self.build_share()
        sidecar = share / "models" / "synthetic-model.gguf.sha256"
        sidecar.write_text("a" * 64 + "  synthetic-model.gguf\n", encoding="ascii")
        code, stdout, _ = self.cli(["--share-root", str(share), "--min-free-gib", "0", "--verify-sha256"])
        report = json.loads(stdout)
        self.assertEqual(code, 2)
        self.assertEqual(report["reasons"], ["sha256_mismatch"])
        self.assertEqual(report["checks"]["sha256"]["mismatched"], 1)
        self.assert_path_free(stdout, share)

    def test_manifest_size_mismatch_is_not_ready(self) -> None:
        share = self.build_share()
        manifest = next((share / "backups").glob("memory-*.json"))
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["bytes"] += 1
        manifest.write_text(json.dumps(document), encoding="utf-8")
        report = self.check(share, "--verify-sha256")
        self.assertEqual(report["reasons"], ["sha256_mismatch"])

    def test_sidecar_without_target_is_not_ready(self) -> None:
        share = self.build_share()
        (share / "models" / "synthetic-model.gguf").unlink()
        report = self.check(share, "--verify-sha256")
        self.assertEqual(report["reasons"], ["sha256_target_missing"])
        self.assertEqual(report["overall"], "not_ready")

    def test_malformed_documents_are_attention(self) -> None:
        share = self.build_share()
        (share / "models" / "synthetic-model.gguf.sha256").write_text("a" * 64 + "  another-file.gguf\n", encoding="ascii")
        manifest = next((share / "backups").glob("memory-*.json"))
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(text[:-1] + ',"bytes":1}', encoding="utf-8")
        report = self.check(share, "--verify-sha256")
        self.assertEqual(report["reasons"], ["sha256_document_invalid"])
        self.assertEqual(report["checks"]["sha256"]["invalid_documents"], 2)

    def test_oversized_sidecar_is_invalid(self) -> None:
        share = self.build_share()
        (share / "models" / "synthetic-model.gguf.sha256").write_bytes(b"a" * 5000)
        report = self.check(share, "--verify-sha256")
        self.assertEqual(report["reasons"], ["sha256_document_invalid"])

    def test_hash_budget_and_empty_verification_are_attention(self) -> None:
        share = self.build_share()
        budget = self.check(share, "--verify-sha256", "--max-hash-files", "2")
        self.assertEqual((budget["overall"], budget["reasons"]), ("attention", ["sha256_budget_exhausted"]))
        sha = budget["checks"]["sha256"]
        self.assertEqual((sha["verified"], sha["skipped_budget"], sha["manifests_skipped_budget"]), (2, 1, 0))
        starved = self.check(share, "--verify-sha256", "--max-hash-files", "1")
        self.assertEqual(starved["overall"], "not_ready")
        self.assertEqual(starved["reasons"], ["sha256_backup_budget_exhausted", "sha256_budget_exhausted"])
        self.assertEqual(starved["checks"]["sha256"]["manifests_skipped_budget"], 1)
        (share / "models" / "synthetic-model.gguf.sha256").unlink()
        for manifest in (share / "backups").rglob("*.json"):
            manifest.unlink()
        nothing = self.check(share, "--verify-sha256")
        self.assertEqual(nothing["reasons"], ["sha256_nothing_to_verify"])

    def test_sidecar_flood_cannot_hide_a_corrupt_backup(self) -> None:
        share = self.build_share()
        for index in range(70):
            _write_sidecar(_write(share / "raw" / "flood" / f"part-{index:03d}.bin", f"part {index}".encode()))
        manifest = next((share / "backups").glob("memory-*.json"))
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["sha256"] = "c" * 64
        manifest.write_text(json.dumps(document), encoding="utf-8")
        report = self.check(share, "--verify-sha256")
        sha = report["checks"]["sha256"]
        self.assertEqual(report["overall"], "not_ready")
        self.assertIn("sha256_mismatch", report["reasons"])
        self.assertEqual((sha["mismatched"], sha["manifests_skipped_budget"]), (1, 0))
        self.assertEqual(sha["skipped_budget"], 71 + 2 - 64)

    def test_only_recent_backup_manifests_are_hashed(self) -> None:
        share = self.build_share()
        for age in range(2, 7):
            _write_backup(share / "backups", "memory", "private-memory-backup.v1", f"older {age}".encode(), time.time() - age * HOUR)
        report = self.check(share, "--verify-sha256")
        sha = report["checks"]["sha256"]
        self.assertEqual((sha["manifests"], sha["manifests_not_selected"], sha["verified"]), (4, 3, 5))
        self.assertEqual(report["overall"], "ready")

    # Symbolic links ------------------------------------------------------------------

    def test_symlink_escape_is_refused_and_never_followed(self) -> None:
        share = self.build_share()
        outside = self.root / "outside"
        _write(outside / "leak.partial", b"outside temporary")
        leaked = _write(outside / "leak.gguf", b"outside model")
        (outside / "leak.gguf.sha256").write_text("b" * 64 + "  leak.gguf\n", encoding="ascii")
        _symlink_or_skip(self, outside, share / "models" / "linked", directory=True)
        _symlink_or_skip(self, leaked, share / "models" / "leak.gguf", directory=False)
        (share / "models" / "leak.gguf.sha256").write_text(hashlib.sha256(b"outside model").hexdigest() + "\n", encoding="ascii")
        code, stdout, _ = self.cli(["--share-root", str(share), "--min-free-gib", "0", "--verify-sha256"])
        report = json.loads(stdout)
        self.assertEqual(code, 2)
        self.assertEqual(report["checks"]["walk"]["symlinks"], 2)
        self.assertEqual(report["checks"]["walk"]["symlinks_escaping"], 2)
        self.assertEqual(report["checks"]["temporary_files"]["temporary"], 0)
        self.assertEqual(report["checks"]["sha256"]["sidecars"], 2)
        self.assertEqual(report["checks"]["sha256"]["refused_targets"], 1)
        in_share_bytes = len(b"synthetic model bytes" * 64) + len(b"synthetic memory backup") + len(b"synthetic index backup")
        self.assertEqual(report["checks"]["sha256"]["bytes_hashed"], in_share_bytes)
        self.assertIn("symlink_escape_refused", report["reasons"])
        self.assert_path_free(stdout, share)

    def test_internal_symlink_is_attention_only(self) -> None:
        share = self.build_share()
        _symlink_or_skip(self, share / "raw", share / "validated" / "alias", directory=True)
        report = self.check(share)
        self.assertEqual(report["reasons"], ["symlinks_present"])
        self.assertEqual(report["overall"], "attention")

    def test_symlinked_share_root_or_folder_is_refused(self) -> None:
        share = self.build_share()
        alias = self.root / "alias-root"
        _symlink_or_skip(self, share, alias, directory=True)
        self.assertEqual(self.check(alias)["reasons"], ["share_root_symlink_refused"])
        shutil.rmtree(share / "raw")
        _symlink_or_skip(self, self.root, share / "raw", directory=True)
        report = self.check(share)
        self.assertEqual(report["checks"]["expected_folders"]["folders"]["raw"]["state"], "symlink_refused")
        self.assertIn("symlink_escape_refused", report["reasons"])

    def test_symlink_escape_detection_is_lexical(self) -> None:
        root = os.path.normpath(os.path.abspath(str(self.root / "share")))
        directory = os.path.join(root, "models")
        cases = {
            os.path.join("..", "raw"): False,
            os.path.join("..", "..", "elsewhere"): True,
            os.path.abspath(str(self.root / "elsewhere")): True,
        }
        for target, escapes in cases.items():
            with mock.patch.object(readiness.os, "readlink", return_value=target):
                self.assertIs(readiness._symlink_escapes(root, directory, "link"), escapes)
        with mock.patch.object(readiness.os, "readlink", side_effect=OSError("synthetic")):
            self.assertTrue(readiness._symlink_escapes(root, directory, "link"))

    # Output, errors and CLI ------------------------------------------------------------

    def test_private_folder_names_are_replaced_by_labels(self) -> None:
        share = self.build_share()
        (share / "private-extra").mkdir()
        code, stdout, _ = self.cli(
            ["--share-root", str(share), "--min-free-gib", "0", "--expected-folders", "raw,validated,models,backups,private-extra"]
        )
        self.assertEqual(code, 0)
        self.assertIn('"folder_5"', stdout)
        self.assertNotIn("private-extra", stdout)
        self.assert_path_free(stdout, share)

    def test_internal_error_fails_closed_without_detail(self) -> None:
        share = self.build_share()
        with mock.patch.object(readiness._Walk, "run", side_effect=RuntimeError(str(share))):
            code, stdout, stderr = self.cli(["--share-root", str(share), "--min-free-gib", "0"])
        report = json.loads(stdout)
        self.assertEqual(code, 2)
        self.assertEqual((report["overall"], report["reasons"]), ("not_ready", ["internal_error"]))
        self.assertEqual(stderr, "")
        self.assert_path_free(stdout, share)

    def test_usage_errors_exit_64_without_echoing_values(self) -> None:
        secret = str(self.root / "secret-location")
        cases = (
            [],
            ["--share-root", secret, "--min-free-gib", "not-a-number"],
            ["--share-root", secret, "--min-free-gib", "-1"],
            ["--share-root", secret, "--max-depth", "0"],
            ["--share-root", secret, "--expected-folders", "../escape"],
            ["--share-root", secret, "--expected-folders", "raw,raw"],
            ["--share-root", secret, "--backup-folder", "elsewhere"],
            ["--share-root", secret, "--access", "admin"],
            ["--share-root", secret, "--unknown-option"],
            ["--share-root", "", "--verify-sha256"],
            ["--share-root", secret, "--access", "exists", "--verify-sha256"],
        )
        for arguments in cases:
            code, stdout, stderr = self.cli(arguments)
            self.assertEqual(code, 64, arguments)
            self.assertEqual(stdout, "")
            self.assertNotIn("secret-location", stderr)
            self.assertNotIn("escape", stderr)

    def test_help_never_exits_zero_nor_writes_stdout(self) -> None:
        for flag in ("--help", "-h"):
            code, stdout, stderr = self.cli([flag])
            self.assertEqual((code, stdout), (64, ""), flag)
            self.assertIn("--share-root", stderr)
            self.assertNotIn("usage error", stderr)

    def test_presence_mode_accepts_closed_folders_without_walking(self) -> None:
        share = self.build_share()
        real_access = os.access
        folders = {os.path.normpath(os.path.abspath(str(share / name))) for name in ("raw", "validated", "models", "backups")}

        def closed(path, mode, *args, **kwargs):
            return False if str(path) in folders else real_access(path, mode, *args, **kwargs)

        with mock.patch.object(readiness.os, "access", side_effect=closed):
            report = self.check(share, "--access", "exists")
            strict = self.check(share, "--access", "read")
        self.assertEqual((report["overall"], report["reasons"]), ("ready", []))
        states = {label: folder["state"] for label, folder in report["checks"]["expected_folders"]["folders"].items()}
        self.assertEqual(set(states.values()), {"present"})
        for name in ("walk", "backups", "temporary_files", "sha256"):
            self.assertEqual(report["checks"][name], {"status": "skipped"})
        self.assertIn("free_gib", report["checks"]["free_space"])
        self.assertEqual(strict["overall"], "not_ready")
        shutil.rmtree(share / "models")
        missing = self.check(share, "--access", "exists")
        self.assertEqual((missing["overall"], missing["reasons"]), ("not_ready", ["folder_missing"]))

    def test_share_without_backups_can_skip_the_backup_check(self) -> None:
        share = self.build_share()
        refused, _, _ = self.cli(["--share-root", str(share), "--expected-folders", "raw,validated,models"])
        self.assertEqual(refused, 64)
        code, stdout, _ = self.cli(
            ["--share-root", str(share), "--min-free-gib", "0", "--expected-folders", "raw,validated,models", "--no-backup-check"]
        )
        report = json.loads(stdout)
        self.assertEqual((code, report["overall"]), (0, "ready"))
        self.assertEqual(report["checks"]["backups"]["status"], "skipped")
        self.assertFalse(report["limits"]["backup_check"])
        verified = self.check(share, "--expected-folders", "raw,validated,models", "--no-backup-check", "--verify-sha256")
        self.assertEqual(verified["checks"]["sha256"]["manifests"], 0)
        self.assertEqual(verified["checks"]["sha256"]["verified"], 1)

    def test_source_stays_python_38_compatible(self) -> None:
        source = TOOL_PATH.read_text(encoding="utf-8")
        ast.parse(source, filename=TOOL_PATH.name, feature_version=(3, 8))
        for forbidden in ("removeprefix", "removesuffix", "datetime.UTC", "BooleanOptionalAction", "file_digest"):
            self.assertNotIn(forbidden, source)

    def test_standard_input_execution_matches_exit_codes(self) -> None:
        share = self.build_share()
        source = TOOL_PATH.read_bytes()
        ready = subprocess.run(
            [sys.executable, "-B", "-", "--share-root", str(share), "--min-free-gib", "0"],
            input=source,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(ready.returncode, 0, ready.stderr)
        self.assertEqual(json.loads(ready.stdout)["overall"], "ready")
        shutil.rmtree(share / "models")
        refused = subprocess.run(
            [sys.executable, "-B", "-", "--share-root", str(share), "--min-free-gib", "0"],
            input=source,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(json.loads(refused.stdout)["overall"], "not_ready")


if __name__ == "__main__":
    unittest.main()
