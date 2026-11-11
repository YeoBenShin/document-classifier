"""Extraction stage: read the text of each page of a PDF or image, with OCR for pages that have no text layer."""

from doc_categoriser.extraction.extractor import DocumentExtractor, default_extractors, extract_document

__all__ = ["DocumentExtractor", "default_extractors", "extract_document"]
