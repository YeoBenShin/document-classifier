"""Extract the text content of documents and classify the documents into categories."""

from doc_categoriser.categories import Category, load_categories
from doc_categoriser.classification import Classification, DocumentClassifier, classify_document
from doc_categoriser.errors import (
    CategoryFileError,
    ClassificationError,
    ExtractionError,
    OcrUnavailableError,
    PasswordProtectedDocumentError,
    UnsupportedFileTypeError,
)
from doc_categoriser.extraction import DocumentExtractor, default_extractors, extract_document
from doc_categoriser.llama_classifier import LlamaCppClassifier
from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText

__all__ = [
    "Category",
    "CategoryFileError",
    "Classification",
    "ClassificationError",
    "DocumentClassifier",
    "DocumentExtractor",
    "ExtractedDocument",
    "ExtractionError",
    "ExtractionMethod",
    "LlamaCppClassifier",
    "OcrUnavailableError",
    "PageText",
    "PasswordProtectedDocumentError",
    "UnsupportedFileTypeError",
    "classify_document",
    "default_extractors",
    "extract_document",
    "load_categories",
]
