# renaming

The renaming stage. Gives each source document the file name that the classification stage suggested, in the folder where the document is.

## How it works

```
renamer.rename_document(source_path, new_name, dry_run)
    ├── check_new_name: one valid file name, same extension as the source
    ├── source gone, file with new_name there         ──> ALREADY_RENAMED
    ├── source already has new_name (same case)       ──> ALREADY_RENAMED
    ├── other file has new_name                       ──> RenamingError
    └── rename in the same folder (skipped if dry_run) ──> RENAMED
```

- `__init__.py`: exports `RenameOutcome`, `check_new_name` and `rename_document`.
- `renamer.py`: `RenameOutcome` (`RENAMED`, `ALREADY_RENAMED`), `check_new_name()` and `rename_document()`. `check_new_name` raises `RenamingError` if the name is empty, is `.` or `..`, starts or ends with a space or a dot, contains `< > : " / \ | ? *` or a control character, or has an extension different from the source (case is ignored). `rename_document` raises `RenamingError` if another file already has the new name, or if neither the source nor a file with the new name exists. It never overwrites a file. A change of case only (`statement.pdf` to `Statement.pdf`) is a rename.

## Decisions

### Rename in place

- The document stays in its folder. Only its name changes. The operator already sorted the documents into folders, and the suggested names are unique only in each folder.

### No overwrite

- A file that already has the new name is never replaced. It can be a different document, and a lost financial document cannot be recovered. The document is reported as failed, and the operator decides.
- On a case-insensitive file system (Windows, macOS by default), `Statement.pdf` and `statement.pdf` are the same file. Thus a target that exists is compared with `os.path.samefile`, and a change of case only is allowed.

### Safe to run again

- After a rename, the JSON still holds the old source path. A second run finds the source gone and a file with the new name in its folder, and reports `already renamed`. A run that stopped part way can run again.
- The check for "already has the new name" compares the exact name in the folder listing, because on a case-insensitive file system the old path still exists after a change of case only.

### Check the name again

- The name suggestion JSON can be edited by hand, or come from another tool. Thus the name is checked again before the rename: a name with `/` or `..` could move the file to another folder, and a changed extension makes the file not open.
