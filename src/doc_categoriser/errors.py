"""Errors raised by the extraction and naming stages. Their messages are written for the operator."""

from pathlib import Path


class ExtractionError(Exception):
    """A file could not be extracted for a known reason."""


class UnsupportedFileTypeError(ExtractionError):
    """Raised when no extractor supports the suffix of a file."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"No extractor supports the file type of {path}")
        self.path = path


class PasswordProtectedDocumentError(ExtractionError):
    """Raised when a document cannot be opened without a password."""

    def __init__(self, path: Path) -> None:
        super().__init__("the PDF is password-protected")
        self.path = path


class OcrEngineUnavailableError(ExtractionError):
    """Raised when the chosen OCR engine cannot run on this operating system or its parts are not installed."""


class NamingError(Exception):
    """A name could not be suggested for a document for a known reason."""
