"""Renaming stage: give each source document the file name suggested by the classification stage."""

from doc_categoriser.renaming.renamer import RenameOutcome, check_new_name, name_with_folder, rename_document

__all__ = ["RenameOutcome", "check_new_name", "name_with_folder", "rename_document"]
