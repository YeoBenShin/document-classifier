"""Reads and writes the JSON files that pass documents between the extraction and naming stages."""

import json
from pathlib import Path
from typing import Any

from doc_categoriser.errors import NamingError
from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText
from doc_categoriser.classification.naming import NameSuggestion


def document_to_json_dict(document: ExtractedDocument) -> dict[str, Any]:
    """Return the JSON-ready form of `document`: absolute source path, file type and pages."""
    return {
        "source_path": str(document.source_path.resolve()),
        "file_type": document.source_path.suffix.lower().removeprefix("."),
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
        )
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError) as error:
        raise NamingError("the file is not an extracted document JSON file") from error


def write_name_suggestion_json(source_path: Path, suggestion: NameSuggestion, destination: Path) -> None:
    """
    Write the source path, suggested name, document date (YYYY-MM-DD or null) and reason as UTF-8 JSON to `destination`,
    creating parent folders if necessary.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = {
        "source_path": str(source_path),
        "suggested_name": suggestion.name,
        "document_date": suggestion.document_date.isoformat() if suggestion.document_date else None,
        "reason": suggestion.reason,
    }
    destination.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
