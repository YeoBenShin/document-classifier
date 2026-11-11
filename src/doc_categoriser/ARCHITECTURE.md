# doc_categoriser package

## How it works

The package has one folder for each pipeline stage, and shared modules at the top.

- `extraction/`: the extraction stage. See its `ARCHITECTURE.md`.
- `classification/`: the classification (naming) stage. See its `ARCHITECTURE.md`.
- `renaming/`: the renaming stage. See its `ARCHITECTURE.md`.

Extraction (`doc-categoriser extract`):

```
cli.py ──> extraction.ocr.create_ocr_engine(--ocr-engine or extraction.ocr.native_ocr_engine_name())
       ──> extraction.default_extractors(ocr_engine)
       ──> extraction.extract_document(path, extractors)
           <── models.ExtractedDocument
cli.py ──> json_output.write_document_json(...)
```

Classification (`doc-categoriser name`):

```
cli.py ──> classification.LlamaCppNamer(model_path)            (loads the GGUF model once)
for each extracted JSON file:
cli.py ──> json_output.read_document_json(path) ──> models.ExtractedDocument
cli.py ──> classification.suggest_document_name(document, namer)
           <── classification.NameSuggestion (name, reason, document date)
cli.py ──> classification.unique_name(name, names used in the same folder)
cli.py ──> json_output.write_name_suggestion_json(...)
```

Renaming (`doc-categoriser rename`):

```
for each name suggestion JSON file:
cli.py ──> json_output.read_name_suggestion_json(path) ──> (source path, suggested name)
cli.py ──> checks no other document of this run gets the same name in the same folder
cli.py ──> renaming.rename_document(source_path, suggested_name, dry_run)
           <── renaming.RenameOutcome (renamed, already renamed)
```

- `__init__.py`: the public library API. Exports the stage functions, protocols, models and errors.
- `models.py`: `ExtractedDocument` (source path + list of `PageText`), `PageText` (page number, text, `ExtractionMethod`).
- `errors.py`: `ExtractionError` and its subclasses `UnsupportedFileTypeError`, `PasswordProtectedDocumentError` and `OcrEngineUnavailableError`. `NamingError`. `RenamingError`. Their messages are written for the operator.
- `json_output.py`: converts an `ExtractedDocument` to JSON and back (`read_document_json`), writes and reads the name suggestion JSON (`read_name_suggestion_json`), and calculates the output path.
- `cli.py`: `extract` creates the OCR engine from `--ocr-engine` (exit code 2 if it is unavailable), finds the files, runs `extract_document` on each, writes the JSON, prints a summary. `name` checks the arguments (folder, model file, `--max-document-tokens` of 1 or more) before it loads the model, reports a model that cannot load as an argument error, then suggests a name for each `.json` file, makes the names unique in each folder, and prints a summary. `rename` renames the source of each `.json` file (or only reports with `--dry-run`), fails a document whose new name another document of the run already gets in the same folder, and prints a summary. In all commands, a failure on one file does not stop the run.

## Decisions

### Protocols for extractors, OCR and namers

- `DocumentExtractor`, `OcrEngine` and `DocumentNamer` are protocols. The CLI, extractors and `suggest_document_name` depend on these, not on pdfplumber, ocrmac or llama-cpp-python directly. Another OCR engine, file type or LLM runtime can be added without changes to the existing code.

### Unique names in each folder

- The suggestions will be used to rename the files. Two documents in the same folder with the same name would then overwrite each other, for example two copies of one statement. Thus the CLI makes each name unique in its source folder. The suffix is `-(2)` and not ` (2)`, because names have no spaces. The comparison ignores case, because Windows and macOS file systems usually ignore case.
- The CLI does it, not `suggest_document_name`, because only the CLI sees all documents of a folder.
- `rename` checks this again, because the JSON files can be edited by hand. In a real run, the file system would also stop the second rename. In a `--dry-run`, no file changes, so only this check finds it.

### Errors in the CLI

- For an `ExtractionError`, a `NamingError` or a `RenamingError`, the CLI prints only its message, because the message is written for the operator. For other exceptions, it prints the exception type and message.
- An encrypted PDF gets its own error, because bank statements are often password-protected. Without it, pdfplumber gives an empty message.
- The CLI catches all exceptions for each file. One broken file in a large folder must not stop the run. The exit code is 1 so that a script can see that a file failed.
- `name` checks the model path before it loads the model. Loading takes several seconds, and an operator error must show at once with exit code 2.
- Each progress line is flushed at once, so an operator who sends the output to a log file sees the progress during a long run.

### Folder for each stage

- Each pipeline stage is a subpackage. `models.py`, `errors.py` and `json_output.py` stay at the top, because both stages and the CLI use them. `ExtractedDocument` is the output of extraction and the input of classification.
