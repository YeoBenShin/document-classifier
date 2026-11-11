"""Entry point that selects an extractor for a file and runs it."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from doc_categoriser.errors import UnsupportedFileTypeError
from doc_categoriser.extraction.image_extractor import ImageExtractor
from doc_categoriser.models import ExtractedDocument
from doc_categoriser.extraction.ocr import OcrEngine, create_ocr_engine, native_ocr_engine_name
from doc_categoriser.extraction.pdf_extractor import PdfExtractor


class DocumentExtractor(Protocol):
    """Extracts page-by-page text from files whose lowercase suffix is in `supported_suffixes`."""

    @property
    def supported_suffixes(self) -> frozenset[str]: ...

    def extract(self, path: Path) -> ExtractedDocument: ...


def default_extractors(ocr_engine: OcrEngine | None = None) -> list[DocumentExtractor]:
    """
    Return the extractors for PDF and image files, sharing one OCR engine.
    If `ocr_engine` is None, the native engine of this operating system is used.
    """
    if ocr_engine is None:
        ocr_engine = create_ocr_engine(native_ocr_engine_name())
    return [PdfExtractor(ocr_engine=ocr_engine), ImageExtractor(ocr_engine=ocr_engine)]


def extract_document(path: Path, extractors: Sequence[DocumentExtractor] | None = None) -> ExtractedDocument:
    """Return the page-by-page text content of the file at `path`, using the first extractor that supports its suffix."""
    for extractor in extractors if extractors is not None else default_extractors():
        if path.suffix.lower() in extractor.supported_suffixes:
            return extractor.extract(path)
    raise UnsupportedFileTypeError(path)
