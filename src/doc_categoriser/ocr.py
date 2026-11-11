"""OCR engines that turn a page image into text."""

from dataclasses import dataclass
from typing import Protocol

from ocrmac import ocrmac
from PIL import Image


class OcrEngine(Protocol):
    """Turns an image of a page into plain text in reading order."""

    def recognise_text(self, image: Image.Image) -> str: ...


@dataclass(frozen=True)
class _TextBox:
    """One recognised text fragment with its position as fractions of the image size, origin at top left."""

    text: str
    left: float
    top: float
    height: float

    @property
    def vertical_centre(self) -> float:
        return self.top + self.height / 2


def _group_into_rows(boxes: list[_TextBox]) -> list[list[_TextBox]]:
    """Group boxes whose vertical centres fall inside the same row, top row first."""
    rows: list[list[_TextBox]] = []
    for box in sorted(boxes, key=lambda candidate: candidate.top):
        current_row = rows[-1] if rows else None
        if current_row is not None and abs(box.vertical_centre - current_row[0].vertical_centre) < current_row[0].height / 2:
            current_row.append(box)
        else:
            rows.append([box])
    return rows


def _boxes_to_text(boxes: list[_TextBox]) -> str:
    """Join boxes into lines, left to right within a row and top to bottom across rows."""
    lines = [
        " ".join(box.text for box in sorted(row, key=lambda candidate: candidate.left))
        for row in _group_into_rows(boxes)
    ]
    return "\n".join(lines)


class AppleVisionOcrEngine:
    """OCR with the macOS Vision framework, through ocrmac."""

    def __init__(self, language_preference: list[str] | None = None) -> None:
        """`language_preference` is a list of Vision language codes such as ["en-US"]. None lets Vision decide."""
        self._language_preference = language_preference

    def recognise_text(self, image: Image.Image) -> str:
        """Return the text in `image`, one line per visual row."""
        observations = ocrmac.text_from_image(
            image,
            recognition_level="accurate",
            language_preference=self._language_preference,
        )
        boxes = [
            _TextBox(text=text, left=x, top=1.0 - (y + height), height=height)
            for text, _confidence, (x, y, _width, height) in observations
        ]
        return _boxes_to_text(boxes)
