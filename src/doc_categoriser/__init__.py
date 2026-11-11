"""Extract the text content of documents and suggest a descriptive file name for each document from its content."""

from doc_categoriser.errors import (
    ExtractionError,
    NamingError,
    OcrUnavailableError,
    PasswordProtectedDocumentError,
    UnsupportedFileTypeError,
)
from doc_categoriser.extraction import DocumentExtractor, default_extractors, extract_document
from doc_categoriser.llama_namer import LlamaCppNamer
from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText
from doc_categoriser.naming import DocumentNamer, NameSuggestion, suggest_document_name

__all__ = [
    "DocumentExtractor",
    "DocumentNamer",
    "ExtractedDocument",
    "ExtractionError",
    "ExtractionMethod",
    "LlamaCppNamer",
    "NameSuggestion",
    "NamingError",
    "OcrUnavailableError",
    "PageText",
    "PasswordProtectedDocumentError",
    "UnsupportedFileTypeError",
    "default_extractors",
    "extract_document",
    "suggest_document_name",
]
