"""Text extraction from PDF files."""

from pathlib import Path

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.page import Page
from pdfplumber.pdf import PDF
from pdfplumber.utils.exceptions import PdfminerException

from doc_categoriser.errors import PasswordProtectedDocumentError
from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText
from doc_categoriser.extraction.ocr import OcrEngine


class PdfExtractor:
    """Reads the embedded text layer of each PDF page, and uses OCR for pages that have almost no embedded text."""

    supported_suffixes = frozenset({".pdf"})

    def __init__(self, ocr_engine: OcrEngine, min_text_layer_chars: int = 20, ocr_resolution_dpi: int = 300) -> None:
        """
        `min_text_layer_chars`: a page with fewer non-whitespace characters in its text layer is OCR'd.
        `ocr_resolution_dpi`: resolution at which a page is rendered to an image for OCR.
        """
        self._ocr_engine = ocr_engine
        self._min_text_layer_chars = min_text_layer_chars
        self._ocr_resolution_dpi = ocr_resolution_dpi

    def extract(self, path: Path) -> ExtractedDocument:
        """Return the text of every page in the PDF at `path`."""
        with self._open(path) as pdf:
            pages = [self._extract_page(page, page_index + 1) for page_index, page in enumerate(pdf.pages)]
        return ExtractedDocument(source_path=path, pages=pages)

    def _open(self, path: Path) -> PDF:
        """Open the PDF at `path`. Raise PasswordProtectedDocumentError if it needs a password."""
        try:
            return pdfplumber.open(path)
        except PdfminerException as error:
            if any(isinstance(argument, PDFPasswordIncorrect) for argument in error.args):
                raise PasswordProtectedDocumentError(path) from error
            raise

    def _extract_page(self, page: Page, page_number: int) -> PageText:
        """Return the text layer of `page` if it has enough characters, otherwise the OCR text of its rendered image."""
        embedded_text = page.extract_text()
        if self._has_enough_text(embedded_text):
            return PageText(page_number=page_number, text=embedded_text, method=ExtractionMethod.TEXT_LAYER)
        page_image = page.to_image(resolution=self._ocr_resolution_dpi).original
        return PageText(
            page_number=page_number,
            text=self._ocr_engine.recognise_text(page_image),
            method=ExtractionMethod.OCR,
        )

    def _has_enough_text(self, text: str) -> bool:
        """Return True if `text` has at least the minimum number of non-whitespace characters."""
        return len("".join(text.split())) >= self._min_text_layer_chars
