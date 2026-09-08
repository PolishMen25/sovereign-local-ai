from pathlib import Path
import unittest

from services.knowledge.hybrid_index import HybridKnowledgeIndex
from tests._temp_support import sovereign_temporary_directory


class HybridKnowledgeIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = sovereign_temporary_directory()
        temporary_path = self.temporary.__enter__()
        self.index = HybridKnowledgeIndex(Path(temporary_path) / "knowledge.sqlite3")
        self.index.initialize()
        self.index.upsert_validated(
            document_id="storage-001",
            title="Stockage hybride",
            content="Les modèles validés sont conservés sur le stockage durable.",
            provenance_id="approved-storage-v1",
            embedding=[1.0, 0.0, 0.0],
        )
        self.index.upsert_validated(
            document_id="network-001",
            title="Isolation réseau",
            content="Le coeur ne possède aucune route Internet.",
            provenance_id="approved-network-v1",
            embedding=[0.0, 1.0, 0.0],
        )

    def tearDown(self) -> None:
        self.temporary.__exit__(None, None, None)

    def test_hybrid_search_returns_provenance(self) -> None:
        result = self.index.search("stockage modèles", query_embedding=[1.0, 0.0, 0.0])
        self.assertEqual("hybrid", result["mode"])
        self.assertEqual("storage-001", result["hits"][0]["document_id"])
        self.assertEqual("approved-storage-v1", result["hits"][0]["provenance_id"])

    def test_status_is_content_free_and_reports_ready_index(self) -> None:
        self.assertEqual(
            {"ready": True, "state": "ready", "mode": "lexical", "documents": 2},
            self.index.status(),
        )

    def test_status_reports_an_initialized_empty_index(self) -> None:
        empty = HybridKnowledgeIndex(self.index.database.with_name("empty.sqlite3"))
        empty.initialize()
        self.assertEqual(
            {"ready": False, "state": "empty", "mode": "lexical", "documents": 0},
            empty.status(),
        )

    def test_lexical_fallback_is_explicit(self) -> None:
        result = self.index.search("route Internet", query_embedding=None)
        self.assertEqual("lexical", result["mode"])
        self.assertEqual("network-001", result["hits"][0]["document_id"])

    def test_lexical_document_is_not_presented_as_a_vector(self) -> None:
        self.index.upsert_validated(
            document_id="lexical-001",
            title="Référence textuelle",
            content="Cette référence ne possède pas encore de vecteur validé.",
            provenance_id="approved-lexical-v1",
            embedding=None,
        )
        lexical = self.index.search("vecteur validé", query_embedding=None)
        self.assertEqual("lexical-001", lexical["hits"][0]["document_id"])
        hybrid = self.index.search("vecteur validé", query_embedding=[1.0, 0.0, 0.0])
        self.assertNotIn("lexical-001", [hit["document_id"] for hit in hybrid["hits"]])

    def test_invalid_or_non_finite_embeddings_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.index.search("network", query_embedding=[float("nan")])
        with self.assertRaises(ValueError):
            self.index.upsert_validated(
                document_id="bad/id?",
                title="bad",
                content="bad",
                provenance_id="approved-bad-v1",
                embedding=[1.0],
            )


if __name__ == "__main__":
    unittest.main()
