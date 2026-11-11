"""Extract the text content of documents and suggest a descriptive file name for each document from its content."""

from doc_categoriser.classification import DocumentNamer, LlamaCppNamer, NameSuggestion, suggest_document_name
from doc_categoriser.errors import (
    ExtractionError,
    NamingError,
    OcrEngineUnavailableError,
    PasswordProtectedDocumentError,
    UnsupportedFileTypeError,
)
from doc_categoriser.extraction import DocumentExtractor, default_extractors, extract_document
from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText

__all__ = [
    "DocumentExtractor",
    "DocumentNamer",
    "ExtractedDocument",
    "ExtractionError",
    "ExtractionMethod",
    "LlamaCppNamer",
    "NameSuggestion",
    "NamingError",
    "OcrEngineUnavailableError",
    "PageText",
    "PasswordProtectedDocumentError",
    "UnsupportedFileTypeError",
    "default_extractors",
    "extract_document",
    "suggest_document_name",
]
