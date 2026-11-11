"""OCR with the macOS Vision framework. Importable only on macOS."""

# ocrmac installs only on macOS, so on other systems its types are unknown to pyright.
# pyright: reportMissingImports=false

from ocrmac import ocrmac
from PIL import Image

from doc_categoriser.ocr.layout import TextBox, boxes_to_text


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
            TextBox(text=_latinise_lookalikes(text), left=x, top=1.0 - (y + height), height=height)
            for text, _confidence, (x, y, _width, height) in observations
        ]
        return boxes_to_text(boxes)
