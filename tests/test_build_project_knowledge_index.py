from pathlib import Path
import importlib.util
import unittest

from services.knowledge.hybrid_index import HybridKnowledgeIndex
from tests._temp_support import sovereign_temporary_directory


MODULE_PATH = Path(__file__).parents[1] / "tools" / "build_project_knowledge_index.py"
SPEC = importlib.util.spec_from_file_location("build_project_knowledge_index", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BuildProjectKnowledgeIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = sovereign_temporary_directory()
        self.root = Path(self.temporary.__enter__())
        self.source = self.root / "docs"
        (self.source / "project").mkdir(parents=True)
        (self.source / "project" / "status.md").write_text("# Statut\nContenu validé.", encoding="utf-8")
        self.database = self.root / "knowledge.sqlite3"

    def tearDown(self) -> None:
        self.temporary.__exit__(None, None, None)

    def test_candidate_requires_exact_digest_and_build_is_searchable(self) -> None:
        manifest = MODULE.create_manifest(self.source, ["project/status.md"])
        digest = MODULE.manifest_digest(manifest)
        self.assertEqual(1, MODULE.build_index(self.source, self.database, manifest, "owner-approval-20260907"))
        result = HybridKnowledgeIndex(self.database).search("contenu validé", query_embedding=None)
        self.assertEqual("approved:project/status.md", result["hits"][0]["document_id"])
        self.assertTrue(result["hits"][0]["provenance_id"].startswith(f"manifest-sha256:{digest}:"))

    def test_changed_source_refuses_without_replacing_existing_index(self) -> None:
        manifest = MODULE.create_manifest(self.source, ["project/status.md"])
        MODULE.build_index(self.source, self.database, manifest, "owner-approval-20260907")
        before = self.database.read_bytes()
        (self.source / "project" / "status.md").write_text("# Statut\nContenu modifié.", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            MODULE.build_index(self.source, self.database, manifest, "owner-approval-20260907")
        self.assertEqual(before, self.database.read_bytes())

    def test_manifest_rejects_traversal_and_duplicate_order(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.create_manifest(self.source, ["../secret.md"])
        with self.assertRaises(ValueError):
            MODULE.load_manifest(self.root / "missing.json")


if __name__ == "__main__":
    unittest.main()
