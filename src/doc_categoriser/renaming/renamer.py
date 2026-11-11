"""Entry point that gives a source document the file name suggested for it, in the folder where it is."""

import os
import re
from enum import StrEnum
from pathlib import Path

from doc_categoriser.errors import RenamingError

_CHARACTERS_NOT_ALLOWED = set('<>:"/\\|?*') | {chr(code) for code in range(32)}


class RenameOutcome(StrEnum):
    """What rename_document did, or would do with dry_run."""

    RENAMED = "renamed"
    ALREADY_RENAMED = "already_renamed"


def check_new_name(source_path: Path, new_name: str) -> None:
    """
    Raise RenamingError if `new_name` is not a single file name that Windows and macOS accept,
    or if its extension is not the extension of `source_path`. The comparison of extensions ignores case.
    """
    if (
        not new_name
        or new_name in {".", ".."}
        or new_name != new_name.strip(" .")
        or _CHARACTERS_NOT_ALLOWED & set(new_name)
    ):
        raise RenamingError(f"the suggested name {new_name!r} is not a valid file name")
    new_extension = Path(new_name).suffix
    if new_extension.lower() != source_path.suffix.lower():
        raise RenamingError(
            f"the suggested name changes the file extension from {source_path.suffix or '(none)'} to {new_extension or '(none)'}"
        )


def name_with_folder(source_path: Path, suggested_name: str) -> str:
    """
    Return `<folder>-<suggested_name>`, where `<folder>` is the name of the folder of `source_path`:
    characters not allowed in file names are removed, whitespace and `_` become `-`, repeated `-` become one,
    and separators (space, `_`, `-`, `.`) at the start and end are removed.
    Raise RenamingError if `suggested_name` is not valid (see check_new_name), or if the folder name has no usable characters.
    """
    check_new_name(source_path, suggested_name)
    folder = "".join(character for character in source_path.parent.name if character not in _CHARACTERS_NOT_ALLOWED)
    folder = re.sub(r"-{2,}", "-", re.sub(r"[\s_]+", "-", folder)).strip(" _-.")
    if not re.search(r"\w", folder):
        raise RenamingError(f"the folder name of {source_path} has no characters usable in a file name")
    return f"{folder}-{suggested_name}"


def rename_document(source_path: Path, new_name: str, *, dry_run: bool = False) -> RenameOutcome:
    """
    Rename the file `source_path` to `new_name` in the same folder. With `dry_run`, change nothing and return the same outcome.
    Return ALREADY_RENAMED if the file already has `new_name`, or if `source_path` is gone and a file named `new_name` is in its folder.
    Raise RenamingError if `new_name` is not valid (see check_new_name), if another file already has `new_name`,
    or if neither the source file nor a file named `new_name` exists. No file is ever overwritten.
    """
    check_new_name(source_path, new_name)
    target_path = source_path.with_name(new_name)
    if not source_path.is_file():
        if _has_exact_name(target_path):
            return RenameOutcome.ALREADY_RENAMED
        raise RenamingError(f"the source file {source_path} does not exist")
    if target_path.exists():
        if not os.path.samefile(source_path, target_path):
            raise RenamingError(f"a file named {new_name} already exists in {source_path.parent}")
        if _has_exact_name(target_path):
            return RenameOutcome.ALREADY_RENAMED
    if not dry_run:
        source_path.rename(target_path)
    return RenameOutcome.RENAMED


def _has_exact_name(path: Path) -> bool:
    """Return True if a file with exactly the name of `path`, with the same case, is in its folder."""
    return path.is_file() and path.name in os.listdir(path.parent)
