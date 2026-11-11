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


_LATIN_FOR_LOOKALIKE = str.maketrans(
    {
        # Cyrillic
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "І": "I", "Ј": "J", "К": "K",
        "М": "M", "О": "O", "Р": "P", "Ѕ": "S", "Т": "T", "Х": "X", "У": "Y",
        "а": "a", "с": "c", "е": "e", "і": "i", "ј": "j", "о": "o", "р": "p", "ѕ": "s", "х": "x", "у": "y",
        # Greek
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M",
        "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "ο": "o",
    }
)
_LOOKALIKE_CHARACTERS = frozenset(chr(code_point) for code_point in _LATIN_FOR_LOOKALIKE)


def _is_greek_or_cyrillic(character: str) -> bool:
    return "Ͱ" <= character <= "ӿ"


def _latinise_lookalike_word(word: str) -> str:
    """
    Replace Cyrillic and Greek letters that look like Latin letters with the Latin letters,
    but only if every Cyrillic or Greek letter in `word` is such a look-alike. Other words are returned unchanged.
    """
    non_latin_letters = {character for character in word if _is_greek_or_cyrillic(character)}
    if non_latin_letters and non_latin_letters <= _LOOKALIKE_CHARACTERS:
        return word.translate(_LATIN_FOR_LOOKALIKE)
    return word


def _latinise_lookalikes(text: str) -> str:
    """Apply `_latinise_lookalike_word` to each space-separated word of `text`."""
    return " ".join(_latinise_lookalike_word(word) for word in text.split(" "))


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
            _TextBox(text=_latinise_lookalikes(text), left=x, top=1.0 - (y + height), height=height)
            for text, _confidence, (x, y, _width, height) in observations
        ]
        return _boxes_to_text(boxes)
