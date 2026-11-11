"""Entry point that suggests a file name for an extracted document from its content, with a namer such as a local LLM."""

import re
from dataclasses import dataclass
from typing import Protocol

from doc_categoriser.errors import NamingError
from doc_categoriser.models import ExtractedDocument

MAX_NAME_STEM_CHARACTERS = 120
"""Maximum length of a suggested name without its extension."""

_CHARACTER_REPLACEMENTS = str.maketrans(
    {"/": "-", "\\": "-", "|": "-", ":": " - ", '"': "", "<": "", ">": "", "?": "", "*": ""}
)
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))}
)


@dataclass(frozen=True)
class NameSuggestion:
    """A suggested file name and the namer's short explanation of it."""

    name: str
    reason: str


class DocumentNamer(Protocol):
    """Suggests a descriptive file name, without an extension, for a document, given the document's text."""

    def suggest_name(self, document_text: str) -> NameSuggestion: ...


def document_text_for_naming(document: ExtractedDocument) -> str:
    """Return the text of all pages, each page preceded by a `--- Page N ---` line."""
    return "\n\n".join(f"--- Page {page.page_number} ---\n{page.text}" for page in document.pages)


def suggest_document_name(document: ExtractedDocument, namer: DocumentNamer) -> NameSuggestion:
    """
    Return the name that `namer` suggests for `document`, made into a safe file name with the extension of the source file.
    Raise NamingError if no page has text, or if the suggested name has no usable characters.
    """
    if not any(page.text.strip() for page in document.pages):
        raise NamingError("the document has no text")
    suggestion = namer.suggest_name(document_text_for_naming(document))
    extension = document.source_path.suffix
    return NameSuggestion(name=_safe_name_stem(suggestion.name, extension) + extension, reason=suggestion.reason)


def _safe_name_stem(raw_name: str, extension: str) -> str:
    """
    Return `raw_name` as a file name stem that Windows and macOS accept:
    characters not allowed in file names are replaced or removed, whitespace is collapsed,
    a copy of `extension` at the end is removed, trailing dots and spaces are removed,
    Windows device names get " document" added, and the length is limited to MAX_NAME_STEM_CHARACTERS.
    """
    stem = " ".join(raw_name.translate(_CHARACTER_REPLACEMENTS).split())
    if extension and stem.lower().endswith(extension.lower()):
        stem = stem[: -len(extension)]
    stem = _strip_trailing_dots_and_spaces(stem[:MAX_NAME_STEM_CHARACTERS])
    if not re.search(r"\w", stem):
        raise NamingError("the model gave no usable name")
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"{stem} document"
    return stem


def _strip_trailing_dots_and_spaces(text: str) -> str:
    """Return `text` without dots and spaces at its end, which Windows removes from file names."""
    return text.rstrip(". ")


def unique_name(name: str, names_in_use: set[str]) -> str:
    """
    Return `name`, or `name` with " (2)", " (3)" and so on before the extension if it is already in `names_in_use`.
    The comparison ignores case, as on Windows and macOS. The returned name is added to `names_in_use` in lowercase.
    """
    stem, dot, extension = name.rpartition(".") if "." in name else (name, "", "")
    candidate = name
    copy_number = 2
    while candidate.lower() in names_in_use:
        candidate = f"{stem} ({copy_number}){dot}{extension}"
        copy_number += 1
    names_in_use.add(candidate.lower())
    return candidate
