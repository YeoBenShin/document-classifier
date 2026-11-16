"""Reads and writes the JSON files that pass documents between the extraction, naming and renaming stages."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doc_categoriser.errors import NamingError, RenamingError
from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText
from doc_categoriser.classification.naming import NameSuggestion


def document_to_json_dict(document: ExtractedDocument) -> dict[str, Any]:
    """Return the JSON-ready form of `document`: absolute source path, file type, OCR engine and pages."""
    return {
        "source_path": str(document.source_path.resolve()),
        "file_type": document.source_path.suffix.lower().removeprefix("."),
        "ocr_engine": document.ocr_engine,
        "pages": [
            {"page_number": page.page_number, "text": page.text, "method": page.method.value}
            for page in document.pages
        ],
    }


def output_path_for(source_path: Path, input_dir: Path, output_dir: Path) -> Path:
    """Return `<output_dir>/<path relative to input_dir>.json`, so the original name and extension stay visible."""
    relative_path = source_path.relative_to(input_dir)
    return output_dir / relative_path.with_name(relative_path.name + ".json")


def write_document_json(document: ExtractedDocument, destination: Path) -> None:
    """Write `document` as UTF-8 JSON to `destination`, creating parent folders if necessary."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document_to_json_dict(document), ensure_ascii=False, indent=2), encoding="utf-8")


def read_document_json(path: Path) -> ExtractedDocument:
    """Return the ExtractedDocument in a JSON file written by `write_document_json`. Raise NamingError if it is not one."""
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        return ExtractedDocument(
            source_path=Path(content["source_path"]),
            pages=[
                PageText(page_number=page["page_number"], text=page["text"], method=ExtractionMethod(page["method"]))
                for page in content["pages"]
            ],
            ocr_engine=content.get("ocr_engine"),
        )
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError) as error:
        raise NamingError("the file is not an extracted document JSON file") from error


@dataclass(frozen=True)
class NameSuggestionFile:
    """
    The content of a name suggestion JSON file that the renaming stage uses.
    `method`, `ocr_engine` and `model` are None if the file does not give them.
    """

    source_path: Path
    suggested_name: str
    method: str | None
    ocr_engine: str | None
    model: str | None


def write_name_suggestion_json(
    source_path: Path,
    suggestion: NameSuggestion,
    destination: Path,
    *,
    method: str | None,
    ocr_engine: str | None,
    model: str | None,
) -> None:
    """
    Write the source path, suggested name, document date (YYYY-MM-DD or null), reason, extraction method
    (`ocr` or `text_layer`), OCR engine and model file name as UTF-8 JSON to `destination`, creating parent folders if necessary.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = {
        "source_path": str(source_path),
        "suggested_name": suggestion.name,
        "document_date": suggestion.document_date.isoformat() if suggestion.document_date else None,
        "reason": suggestion.reason,
        "method": method,
        "ocr_engine": ocr_engine,
        "model": model,
    }
    destination.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def read_name_suggestion_json(path: Path) -> NameSuggestionFile:
    """
    Return the content of a JSON file written by `write_name_suggestion_json`. `method`, `ocr_engine` and `model` are optional.
    Raise RenamingError if it is not one.
    """
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        source_path, suggested_name = content["source_path"], content["suggested_name"]
        optional_values = [content.get(key) for key in ("method", "ocr_engine", "model")]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, AttributeError) as error:
        raise RenamingError("the file is not a name suggestion JSON file") from error
    if (
        not isinstance(source_path, str)
        or not isinstance(suggested_name, str)
        or not all(value is None or isinstance(value, str) for value in optional_values)
    ):
        raise RenamingError("the file is not a name suggestion JSON file")
    method, ocr_engine, model = optional_values
    return NameSuggestionFile(Path(source_path), suggested_name, method, ocr_engine, model)
