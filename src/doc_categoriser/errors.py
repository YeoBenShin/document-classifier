"""Errors raised by the extraction and classification stages. Their messages are written for the operator."""

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


class OcrUnavailableError(ExtractionError):
    """Raised when a page needs OCR but this system has no OCR engine."""

    def __init__(self) -> None:
        super().__init__("a page needs OCR, and OCR is available on macOS only")


class ClassificationError(Exception):
    """A document could not be classified for a known reason."""


class CategoryFileError(ClassificationError):
    """Raised when the categories file is missing or not in the expected format."""

    def __init__(self, path: Path, problem: str) -> None:
        super().__init__(f"{path}: {problem}")
        self.path = path
