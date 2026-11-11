"""Data types produced by the extraction stage."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ExtractionMethod(StrEnum):
    """How the text of a page was obtained."""

    TEXT_LAYER = "text_layer"
    OCR = "ocr"


@dataclass(frozen=True)
class PageText:
    """The text of one page and the method used to get it. Page numbers start at 1."""

    page_number: int
    text: str
    method: ExtractionMethod


@dataclass(frozen=True)
class ExtractedDocument:
    """The text content of one source file, page by page."""

    source_path: Path
    pages: list[PageText]
