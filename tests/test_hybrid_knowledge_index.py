from pathlib import Path
import tempfile
import unittest

from services.knowledge.hybrid_index import HybridKnowledgeIndex


class HybridKnowledgeIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.index = HybridKnowledgeIndex(Path(self.temporary.name) / "knowledge.sqlite3")
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
        self.temporary.cleanup()

    def test_hybrid_search_returns_provenance(self) -> None:
        result = self.index.search("stockage modèles", query_embedding=[1.0, 0.0, 0.0])
        self.assertEqual("hybrid", result["mode"])
        self.assertEqual("storage-001", result["hits"][0]["document_id"])
        self.assertEqual("approved-storage-v1", result["hits"][0]["provenance_id"])

    def test_lexical_fallback_is_explicit(self) -> None:
        result = self.index.search("route Internet", query_embedding=None)
        self.assertEqual("lexical", result["mode"])
        self.assertEqual("network-001", result["hits"][0]["document_id"])

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
