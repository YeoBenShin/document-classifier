"""The rename history: one hidden JSON Lines file in each document folder, with one line for each rename."""

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

HISTORY_FILE_NAME = ".doc-categoriser-renames.jsonl"
"""Name of the history file in each document folder. The leading dot makes it hidden, so no stage reads it as a document."""

TEXT_LAYER_METHOD = "text_layer"
OCR_METHOD = "ocr"

_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RenameRecord:
    """
    One line of the history file.
    `sha256`: the SHA-256 of the file content, as lowercase hex.
    `method`: `ocr` if the text of one or more pages came from OCR, otherwise `text_layer`. None if not known.
    `ocr_engine`: the OCR engine of the run (for example `apple-vision`) if `method` is `ocr`, otherwise None.
    `model`: the file name of the GGUF model that suggested the name. None if not known.
    `renamed_at`: local date and time of the rename, ISO 8601 with the UTC offset.
    """

    original_name: str
    new_name: str
    sha256: str
    renamed_at: str
    method: str | None
    ocr_engine: str | None
    model: str | None


def history_path(folder: Path) -> Path:
    """Return the path of the history file of `folder`."""
    return folder / HISTORY_FILE_NAME


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of the content of the file at `path`, as lowercase hex."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_history_file(folder: Path) -> None:
    """Create an empty history file in `folder` if it has none."""
    history_path(folder).touch(exist_ok=True)


def read_history(folder: Path) -> tuple[list[RenameRecord], int]:
    """
    Return the records of the history file of `folder` in file order, and the number of lines that are not records.
    Each line that is not a record is reported on stderr. Return ([], 0) if the file does not exist.
    """
    path = history_path(folder)
    if not path.is_file():
        return [], 0
    records: list[RenameRecord] = []
    invalid_count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            content = json.loads(line)
            record = RenameRecord(
                original_name=content["original_name"],
                new_name=content["new_name"],
                sha256=content["sha256"],
                renamed_at=content["renamed_at"],
                method=content.get("method"),
                ocr_engine=content.get("ocr_engine"),
                model=content.get("model"),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            print(f"Ignored: {path}: line {line_number} is not a rename record ({error})", file=sys.stderr, flush=True)
            invalid_count += 1
            continue
        records.append(record)
    return records, invalid_count


def last_record_by_hash(records: list[RenameRecord]) -> dict[str, RenameRecord]:
    """Return the last record of `records` for each SHA-256."""
    return {record.sha256: record for record in records}


def write_history(folder: Path, records: list[RenameRecord]) -> None:
    """Replace the history file of `folder` with `records`, one line each. The old file stays complete until the new one is in place."""
    path = history_path(folder)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text("".join(_record_line(record) for record in records), encoding="utf-8")
    os.replace(temporary_path, path)


def append_history(folder: Path, record: RenameRecord) -> None:
    """Add `record` as one line at the end of the history file of `folder`. Create the file if it does not exist."""
    with history_path(folder).open("a", encoding="utf-8") as history_file:
        history_file.write(_record_line(record))


def current_time_text() -> str:
    """Return the local date and time now, ISO 8601 to the second with the UTC offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_done(record: RenameRecord | None, model: str, ocr_engine: str) -> bool:
    """
    Return True if `record` shows a rename with the model `model`, and with no OCR or with the OCR engine `ocr_engine`.
    Return False if `record` is None.
    """
    if record is None or record.model != model:
        return False
    if record.method == TEXT_LAYER_METHOD:
        return True
    return record.method == OCR_METHOD and record.ocr_engine == ocr_engine


def _record_line(record: RenameRecord) -> str:
    """Return `record` as one JSON line, with the line end."""
    return json.dumps(asdict(record), ensure_ascii=False) + "\n"
