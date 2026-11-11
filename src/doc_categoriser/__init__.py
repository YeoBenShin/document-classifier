"""Extract the text content of documents so they can be categorised later."""

from doc_categoriser.extraction import DocumentExtractor, UnsupportedFileTypeError, default_extractors, extract_document
from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText

__all__ = [
    "DocumentExtractor",
    "ExtractedDocument",
    "ExtractionMethod",
    "PageText",
    "UnsupportedFileTypeError",
    "default_extractors",
    "extract_document",
]
