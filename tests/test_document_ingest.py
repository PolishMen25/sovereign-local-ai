from pathlib import Path
import tempfile
import unittest

from services.knowledge.document_ingest import ingest, IngestError, CHUNK_CHARS
from services.knowledge.hybrid_index import HybridKnowledgeIndex


class DocumentIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.index = HybridKnowledgeIndex(self.root / "knowledge.sqlite3")
        self.index.initialize()
        self.storage = self.root / "documents"

    def test_ingests_text_and_makes_it_searchable(self) -> None:
        data = "Le pare-feu bloque le trafic réseau non autorisé.".encode("utf-8")
        result = ingest(self.index, self.storage, filename="cours.txt", data=data)
        self.assertEqual(result["chunks"], 1)
        self.assertEqual(result["method"], "text")
        self.assertTrue((self.storage / result["document_id"] / "original.txt").is_file())
        self.assertTrue((self.storage / result["document_id"] / "extracted.txt").is_file())
        hits = self.index.search("pare-feu", query_embedding=None, limit=3)["hits"]
        self.assertTrue(any(h["provenance_id"] == result["provenance_id"] for h in hits))

    def test_long_document_is_chunked(self) -> None:
        para = ("phrase de test. " * 200).strip()
        data = (para + "\n\n" + para + "\n\n" + para).encode("utf-8")
        result = ingest(self.index, self.storage, filename="long.md", data=data)
        self.assertGreater(result["chunks"], 1)

    def test_rejects_empty_file(self) -> None:
        with self.assertRaisesRegex(IngestError, "vide"):
            ingest(self.index, self.storage, filename="x.txt", data=b"")

    def test_rejects_bad_filename(self) -> None:
        with self.assertRaisesRegex(IngestError, "invalide"):
            ingest(self.index, self.storage, filename="../evil.txt", data=b"hello")

    def test_rejects_unsupported_type(self) -> None:
        with self.assertRaisesRegex(IngestError, "non pris en charge"):
            ingest(self.index, self.storage, filename="thing.xyz", data=b"data")

    def test_document_id_is_a_valid_index_identifier(self) -> None:
        result = ingest(self.index, self.storage, filename="Mon Cours (2026).txt", data=b"contenu")
        # provenance and chunk ids must satisfy the index identifier rules (no spaces/parens)
        self.assertRegex(result["document_id"], r"^[A-Za-z0-9_-]+$")


if __name__ == "__main__":
    unittest.main()
