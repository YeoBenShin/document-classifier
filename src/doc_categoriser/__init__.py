"""Extract the text content of documents so they can be categorised later."""

from doc_categoriser.errors import ExtractionError, PasswordProtectedDocumentError, UnsupportedFileTypeError
from doc_categoriser.extraction import DocumentExtractor, default_extractors, extract_document
from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText

__all__ = [
    "DocumentExtractor",
    "ExtractedDocument",
    "ExtractionError",
    "ExtractionMethod",
    "PageText",
    "PasswordProtectedDocumentError",
    "UnsupportedFileTypeError",
    "default_extractors",
    "extract_document",
]
