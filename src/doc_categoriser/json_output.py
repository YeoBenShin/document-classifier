"""Writes extracted documents as JSON files for the comprehension stage."""

import json
from pathlib import Path
from typing import Any

from doc_categoriser.models import ExtractedDocument


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
