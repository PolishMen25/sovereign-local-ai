"""Offline text extraction for uploaded documents (feeds the local RAG).

Pure-Python for text and .docx; shells out to fully offline tools for the rest:
``pdftotext`` (poppler) for PDFs, ``tesseract`` for images and scanned PDFs
(``pdftoppm`` rasterises pages first).  Nothing here reaches the network and no
model is trained: OCR is a tool, not a learned capability.

extract_text(path, filename) -> (text, method); raises ExtractionError with a
plain message the gateway can surface.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

MAX_TEXT_CHARS = 500_000
OCR_LANGUAGES = "fra+eng"
TOOL_TIMEOUT = 120
SCANNED_PDF_TEXT_THRESHOLD = 40  # below this many chars, treat a PDF as scanned

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".log", ".json", ".yaml", ".yml", ".ini", ".rst", ".tsv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}


class ExtractionError(RuntimeError):
    """The document could not be turned into text (bad file, or a tool is missing)."""


def _bound(text: str) -> str:
    text = text.replace("\x00", "")
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS]


def _run(command: list[str], *, stdin_path: Path | None = None) -> str:
    tool = command[0]
    if shutil.which(tool) is None:
        raise ExtractionError(f"outil « {tool} » absent du serveur")
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=TOOL_TIMEOUT,
            stdin=stdin_path.open("rb") if stdin_path else None,
        )
    except subprocess.TimeoutExpired:
        raise ExtractionError(f"« {tool} » a dépassé le temps imparti") from None
    if completed.returncode != 0:
        raise ExtractionError(f"« {tool} » a échoué")
    return completed.stdout.decode("utf-8", errors="replace")


def _from_plain_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _from_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError) as error:
        raise ExtractionError("fichier .docx illisible") from error
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    text = re.sub(r"&amp;", "&", re.sub(r"&lt;", "<", re.sub(r"&gt;", ">", xml)))
    return "\n".join(line.rstrip() for line in text.splitlines())


def _ocr_image(path: Path) -> str:
    return _run(["tesseract", str(path), "stdout", "-l", OCR_LANGUAGES])


def _from_pdf(path: Path) -> tuple[str, str]:
    text = _run(["pdftotext", "-q", str(path), "-"])
    if len(text.strip()) >= SCANNED_PDF_TEXT_THRESHOLD:
        return text, "pdftotext"
    # Scanned PDF: rasterise pages and OCR each one.
    with tempfile.TemporaryDirectory() as work:
        prefix = Path(work) / "page"
        _run(["pdftoppm", "-png", "-r", "200", str(path), str(prefix)])
        pages = sorted(Path(work).glob("page*.png"))
        if not pages:
            raise ExtractionError("PDF scanné : aucune page à reconnaître")
        return "\n\n".join(_ocr_image(page) for page in pages), "ocr-pdf"


def extract_text(path: Path, *, filename: str) -> tuple[str, str]:
    """Return (text, method) for an uploaded document, or raise ExtractionError."""

    suffix = Path(filename).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return _bound(_from_plain_text(path)), "text"
    if suffix == ".docx":
        return _bound(_from_docx(path)), "docx"
    if suffix == ".pdf":
        text, method = _from_pdf(path)
        return _bound(text), method
    if suffix in IMAGE_SUFFIXES:
        return _bound(_ocr_image(path)), "ocr-image"
    raise ExtractionError(f"type de fichier non pris en charge : {suffix or 'inconnu'}")
