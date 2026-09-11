from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from services.knowledge import document_text as dt


class DocumentTextTests(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)

    def write(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_plain_text(self) -> None:
        path = self.write("note.txt", "Bonjour le monde\nLigne 2".encode("utf-8"))
        text, method = dt.extract_text(path, filename="note.txt")
        self.assertEqual(method, "text")
        self.assertIn("Bonjour le monde", text)

    def test_markdown(self) -> None:
        path = self.write("doc.md", b"# Titre\n\nContenu")
        text, method = dt.extract_text(path, filename="doc.md")
        self.assertEqual(method, "text")
        self.assertIn("Titre", text)

    def test_docx(self) -> None:
        path = self.root / "d.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml",
                             "<w:document><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p>"
                             "<w:p><w:r><w:t>World</w:t></w:r></w:p></w:body></w:document>")
        text, method = dt.extract_text(path, filename="d.docx")
        self.assertEqual(method, "docx")
        self.assertEqual([l for l in text.splitlines() if l.strip()], ["Hello", "World"])

    def test_bad_docx_raises(self) -> None:
        path = self.write("broken.docx", b"not a zip")
        with self.assertRaises(dt.ExtractionError):
            dt.extract_text(path, filename="broken.docx")

    def test_unsupported_extension(self) -> None:
        path = self.write("thing.xyz", b"data")
        with self.assertRaisesRegex(dt.ExtractionError, "non pris en charge"):
            dt.extract_text(path, filename="thing.xyz")

    def test_image_without_tesseract_reports_missing_tool(self) -> None:
        path = self.write("scan.png", b"\x89PNG fake")
        with mock.patch.object(dt.shutil, "which", return_value=None):
            with self.assertRaisesRegex(dt.ExtractionError, "absent"):
                dt.extract_text(path, filename="scan.png")

    def test_pdf_without_poppler_reports_missing_tool(self) -> None:
        path = self.write("scan.pdf", b"%PDF-1.4 fake")
        with mock.patch.object(dt.shutil, "which", return_value=None):
            with self.assertRaisesRegex(dt.ExtractionError, "absent"):
                dt.extract_text(path, filename="scan.pdf")

    def test_output_is_bounded(self) -> None:
        big = ("x" * (dt.MAX_TEXT_CHARS + 1000)).encode("utf-8")
        path = self.write("big.txt", big)
        text, _ = dt.extract_text(path, filename="big.txt")
        self.assertEqual(len(text), dt.MAX_TEXT_CHARS)


if __name__ == "__main__":
    unittest.main()
