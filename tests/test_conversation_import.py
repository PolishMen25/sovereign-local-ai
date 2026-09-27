import importlib.util
import hashlib
from pathlib import Path
import sys
import unittest
from unittest import mock
from uuid import uuid4

from tests._temp_support import sovereign_temporary_directory


MODULE_PATH = Path(__file__).parents[1] / "services" / "quarantine" / "conversation_import.py"
SPEC = importlib.util.spec_from_file_location("conversation_import", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def conversation() -> dict:
    return {"schema_version": "0.1.0", "conversation_id": str(uuid4()), "captured_at": "2026-08-31T12:00:00Z", "messages": [{"role": "user", "content": "Documente le NAS."}]}


class ConversationImportTests(unittest.TestCase):
    def test_clean_conversation_is_valid(self) -> None:
        MODULE.validate(conversation())

    def test_secret_is_rejected_before_storage(self) -> None:
        document = conversation()
        document["messages"][0]["content"] = "password: do-not-store"
        with self.assertRaises(ValueError):
            MODULE.validate(document)

    def test_unknown_fields_are_rejected(self) -> None:
        document = conversation()
        document["file_path"] = "/etc/passwd"
        with self.assertRaises(ValueError):
            MODULE.validate(document)

    def test_later_snapshot_keeps_original_and_is_idempotent(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            first = conversation()
            first_receipt = MODULE.import_raw(first, root)
            first_path = root / "raw" / "conversations" / f"{first['conversation_id']}.json"
            original = first_path.read_bytes()

            later = {**first, "messages": [*first["messages"], {"role": "assistant", "content": "Voici le plan."}]}
            later_receipt = MODULE.import_raw(later, root)
            version_path = (
                root / "raw" / "conversations" / "versions" / first["conversation_id"]
                / f"{later_receipt['sha256']}.json"
            )
            self.assertEqual(first_receipt["state"], "raw_imported")
            self.assertEqual(later_receipt["state"], "raw_imported")
            self.assertEqual(later_receipt["conversation_id"], first["conversation_id"])
            self.assertEqual(first_path.read_bytes(), original)
            self.assertEqual(hashlib.sha256(version_path.read_bytes()).hexdigest(), later_receipt["sha256"])
            self.assertEqual(MODULE.import_raw(later, root)["state"], "already_imported")
            self.assertEqual(first_path.read_bytes(), original)
            self.assertFalse((root / "validated").exists())

    def test_secret_in_later_snapshot_is_not_written(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            first = conversation()
            MODULE.import_raw(first, root)
            later = {**first, "messages": [{"role": "user", "content": "api_key: example"}]}
            with self.assertRaises(ValueError):
                MODULE.import_raw(later, root)
            self.assertFalse((root / "raw" / "conversations" / "versions").exists())

    def test_failed_fsync_removes_partial_temporary_file(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            document = conversation()
            with mock.patch.object(MODULE.os, "fsync", side_effect=OSError("storage failure")):
                with self.assertRaisesRegex(OSError, "storage failure"):
                    MODULE.import_raw(document, root)
            raw = root / "raw" / "conversations"
            self.assertEqual(list(raw.glob(".incoming-*")), [])
            self.assertFalse((raw / f"{document['conversation_id']}.json").exists())

    def test_directory_sync_failure_can_be_retried_without_replacing_raw(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            document = conversation()
            with mock.patch.object(MODULE, "_sync_directory", side_effect=OSError("directory sync failure")):
                with self.assertRaisesRegex(OSError, "directory sync failure"):
                    MODULE.import_raw(document, root)
            raw = root / "raw" / "conversations"
            original = (raw / f"{document['conversation_id']}.json").read_bytes()
            self.assertEqual(list(raw.glob(".incoming-*")), [])
            self.assertEqual(MODULE.import_raw(document, root)["state"], "already_imported")
            self.assertEqual((raw / f"{document['conversation_id']}.json").read_bytes(), original)

    def test_versions_symlink_cannot_redirect_storage(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            first = conversation()
            MODULE.import_raw(first, root)
            outside = root / "outside"
            outside.mkdir()
            versions = root / "raw" / "conversations" / "versions"
            try:
                versions.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlink unavailable: {error}")
            later = {**first, "messages": [*first["messages"], {"role": "assistant", "content": "Suite."}]}
            with self.assertRaisesRegex(ValueError, "escapes RAW"):
                MODULE.import_raw(later, root)
            self.assertEqual(list(outside.iterdir()), [])

    def test_conversation_version_symlink_cannot_redirect_storage(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            first = conversation()
            MODULE.import_raw(first, root)
            outside = root / "outside"
            outside.mkdir()
            versions = root / "raw" / "conversations" / "versions"
            versions.mkdir()
            try:
                (versions / first["conversation_id"]).symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlink unavailable: {error}")
            later = {**first, "messages": [*first["messages"], {"role": "assistant", "content": "Suite."}]}
            with self.assertRaisesRegex(ValueError, "escapes RAW"):
                MODULE.import_raw(later, root)
            self.assertEqual(list(outside.iterdir()), [])
