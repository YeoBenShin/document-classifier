"""Renaming stage: give each source document the file name suggested by the classification stage, and keep a rename history in each folder."""

from doc_categoriser.renaming.history import (
    HISTORY_FILE_NAME,
    OCR_METHOD,
    TEXT_LAYER_METHOD,
    RenameRecord,
    append_history,
    current_time_text,
    ensure_history_file,
    file_sha256,
    is_done,
    last_record_by_hash,
    read_history,
    write_history,
)
from doc_categoriser.renaming.renamer import RenameOutcome, check_new_name, name_with_folder, rename_document

__all__ = [
    "HISTORY_FILE_NAME",
    "OCR_METHOD",
    "TEXT_LAYER_METHOD",
    "RenameOutcome",
    "RenameRecord",
    "append_history",
    "check_new_name",
    "current_time_text",
    "ensure_history_file",
    "file_sha256",
    "is_done",
    "last_record_by_hash",
    "name_with_folder",
    "read_history",
    "rename_document",
    "write_history",
]
