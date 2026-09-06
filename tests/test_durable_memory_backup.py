from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from uuid import uuid4

from services.memory.durable_backup import create_backup, restore_backup, verify_backup


class DurableMemoryBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        test_root = Path(__file__).parents[1] / ".codex-test-tmp"
        test_root.mkdir(exist_ok=True)
        self.root = test_root / f"durable-memory-{uuid4().hex}"
        self.root.mkdir()
        self.database = self.root / "memory.sqlite3"
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("CREATE TABLE messages (content TEXT NOT NULL)")
            connection.execute("INSERT INTO messages(content) VALUES(?)", ("message de test",))
            connection.commit()
        finally:
            connection.close()
        self.backups = self.root / "backups"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_backup_verify_and_restore_are_content_free_and_equivalent(self) -> None:
        manifest = create_backup(self.database, self.backups)
        artifact = self.backups / manifest["artifact"]
        manifest_path = artifact.with_suffix(".json")
        self.assertEqual(manifest, verify_backup(artifact, manifest_path))
        self.assertNotIn("message de test", manifest_path.read_text(encoding="utf-8"))
        restored = self.backups / "restored.sqlite3"
        result = restore_backup(artifact, manifest_path, restored)
        self.assertEqual(result["restored_sha256"], manifest["sha256"])
        with sqlite3.connect(restored) as connection:
            self.assertEqual(connection.execute("SELECT content FROM messages").fetchone()[0], "message de test")

    def test_verify_refuses_tampered_manifest(self) -> None:
        manifest = create_backup(self.database, self.backups)
        artifact = self.backups / manifest["artifact"]
        manifest_path = artifact.with_suffix(".json")
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["bytes"] += 1
        manifest_path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(ValueError):
            verify_backup(artifact, manifest_path)

    def test_catalogue_backup_uses_a_distinct_schema_and_name(self) -> None:
        manifest = create_backup(
            self.database,
            self.backups,
            artifact_prefix="knowledge-index",
            schema_version="knowledge-index-backup.v1",
        )
        artifact = self.backups / manifest["artifact"]
        self.assertTrue(artifact.name.startswith("knowledge-index-"))
        self.assertEqual(
            manifest,
            verify_backup(artifact, artifact.with_suffix(".json"), schema_version="knowledge-index-backup.v1"),
        )
        restored = self.root / "knowledge-restored.sqlite3"
        result = restore_backup(
            artifact,
            artifact.with_suffix(".json"),
            restored,
            schema_version="knowledge-index-backup.v1",
        )
        self.assertEqual("knowledge-index-backup.v1", result["schema_version"])
        with self.assertRaises(ValueError):
            verify_backup(artifact, artifact.with_suffix(".json"))
