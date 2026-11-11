"""Entry point that suggests a file name for an extracted document from its content, with a namer such as a local LLM."""

import datetime
import re
from dataclasses import dataclass
from typing import Protocol

from doc_categoriser.errors import NamingError
from doc_categoriser.models import ExtractedDocument

MAX_NAME_STEM_CHARACTERS = 120
"""Maximum length of the descriptive part of a name, without the date prefix and the extension."""

UNDATED_PREFIX = "undated"
"""Prefix used in place of the date when the document shows no date."""

_CHARACTER_REPLACEMENTS = str.maketrans(
    {"/": "-", "\\": "-", "|": "-", ":": " - ", '"': "", "<": "", ">": "", "?": "", "*": ""}
)
_SEPARATORS = " _-."


@dataclass(frozen=True)
class NameSuggestion:
    """
    A suggested file name, the namer's short explanation of it, and the date of the document (None if it shows no date).
    From a DocumentNamer, `name` is only the descriptive part. From suggest_document_name, it is the full file name.
    """

    name: str
    reason: str
    document_date: datetime.date | None


class DocumentNamer(Protocol):
    """Suggests a descriptive name, without date or extension, and finds the date of a document, given the document's text."""

    def suggest_name(self, document_text: str) -> NameSuggestion: ...


def document_text_for_naming(document: ExtractedDocument) -> str:
    """Return the text of all pages, each page preceded by a `--- Page N ---` line."""
    return "\n\n".join(f"--- Page {page.page_number} ---\n{page.text}" for page in document.pages)


def suggest_document_name(document: ExtractedDocument, namer: DocumentNamer) -> NameSuggestion:
    """
    Return the file name `YYYY-MM-DD-<name><extension>` for `document`: the document date and the name that `namer` suggests,
    made safe for file systems, with the extension of the source file. A document without a date gets `undated-<name>`.
    Raise NamingError if no page has text, or if the suggested name has no usable characters.
    """
    if not any(page.text.strip() for page in document.pages):
        raise NamingError("the document has no text")
    suggestion = namer.suggest_name(document_text_for_naming(document))
    extension = document.source_path.suffix
    date_prefix = suggestion.document_date.isoformat() if suggestion.document_date else UNDATED_PREFIX
    stem = _safe_name_stem(suggestion.name, extension, suggestion.document_date)
    return NameSuggestion(
        name=f"{date_prefix}-{stem}{extension}", reason=suggestion.reason, document_date=suggestion.document_date
    )


def _safe_name_stem(raw_name: str, extension: str, document_date: datetime.date | None) -> str:
    """
    Return `raw_name` as the descriptive part of a file name that Windows and macOS accept:
    characters not allowed in file names are replaced or removed, whitespace is collapsed,
    a copy of `extension` at the end and copies of `document_date` (YYYY-MM-DD) are removed,
    spaces and `_` become `-` and repeated `-` become one, the length is limited to MAX_NAME_STEM_CHARACTERS, and separators (space, `_`, `-`, `.`) at the start and end are removed.
    Windows removes dots and spaces at the end of a file name, and a cut can leave a separator at the end.
    """
    stem = " ".join(raw_name.translate(_CHARACTER_REPLACEMENTS).split())
    if extension and stem.lower().endswith(extension.lower()):
        stem = stem[: -len(extension)]
    if document_date is not None:
        stem = _without_date(stem, document_date)
    stem = re.sub(r"-{2,}", "-", re.sub(r"[\s_]+", "-", stem))
    stem = stem.lstrip(_SEPARATORS)[:MAX_NAME_STEM_CHARACTERS].rstrip(_SEPARATORS)
    if not re.search(r"\w", stem):
        raise NamingError("the model gave no usable name")
    return stem


def _without_date(stem: str, document_date: datetime.date) -> str:
    """Return `stem` without the ISO form of `document_date`, which is already the prefix. The parts around it are joined with a space."""
    parts = (part.strip(_SEPARATORS) for part in stem.split(document_date.isoformat()))
    return " ".join(part for part in parts if part)


def unique_name(name: str, names_in_use: set[str]) -> str:
    """
    Return `name`, or `name` with "-(2)", "-(3)" and so on before the extension if it is already in `names_in_use`.
    The comparison ignores case, as on Windows and macOS. The returned name is added to `names_in_use` in lowercase.
    """
    stem, dot, extension = name.rpartition(".") if "." in name else (name, "", "")
    candidate = name
    copy_number = 2
    while candidate.lower() in names_in_use:
        candidate = f"{stem}-({copy_number}){dot}{extension}"
        copy_number += 1
    names_in_use.add(candidate.lower())
    return candidate
