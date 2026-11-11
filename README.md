# doc-categoriser

Extracts the text of documents (PDFs and images) to JSON files, suggests a descriptive file name for each document from its content with a local LLM, then renames the documents. No document leaves the machine. The suggestions are written to JSON files first, so the operator can examine them before the rename.

## Requirements

- Python 3.13 or later.
- [uv](https://docs.astral.sh/uv/) (optional on Windows, see below).
- A GGUF chat model file. Recommended: `Qwen3.5-4B-Q4_K_M.gguf` (2.7 GB) from <https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf>. Put it anywhere, for example `models/`.
- For `extract`: macOS (OCR with the Apple Vision framework) or Windows 10 or later (OCR with Windows.Media.Ocr). Other systems have no OCR engine, and `extract` gives exit code `2`. `name` works on all systems.
- On Windows, an OCR language pack for a language of the user profile. English is installed with an English Windows. To add one: Settings > Time & Language > Language.

## Install

macOS (builds llama-cpp-python from source with Apple clang, needs Xcode or the Command Line Tools):

```sh
uv sync
```

Windows or Linux with uv (uses the prebuilt CPU wheel of llama-cpp-python, no compiler):

```sh
uv sync
```

Windows without uv (only Python is necessary):

```bat
py -3.13 -m venv .venv
.venv\Scripts\pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --only-binary llama-cpp-python .
```

Then use `.venv\Scripts\doc-categoriser` in place of `uv run doc-categoriser` below.

## Run

```sh
uv run doc-categoriser extract <input_dir> <extracted_dir>
uv run doc-categoriser extract --ocr-engine windows <input_dir> <extracted_dir>
uv run doc-categoriser name <extracted_dir> <named_dir> --model models/Qwen3.5-4B-Q4_K_M.gguf
uv run doc-categoriser rename --dry-run <named_dir>
uv run doc-categoriser rename <named_dir>
uv run doc-categoriser run <input_dir> <work_dir> --model models/Qwen3.5-4B-Q4_K_M.gguf
uv run doc-categoriser web [<folder>]
```

### extract

- `--ocr-engine`: `apple-vision` or `windows`. Default: the engine of the operating system (`apple-vision` on macOS, `windows` on Windows). An engine that cannot run on this operating system gives exit code `2`.

- All files under `<input_dir>` are read, including subfolders. Hidden files and folders (names that start with `.`) are ignored.
- For each document, the command writes `<extracted_dir>/<relative path>/<original name>.json`.
- Supported types: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.heic`, `.heif`. Other types are skipped and reported.
- Exit code: `0` if no file failed, `1` if one or more files failed, `2` for incorrect arguments.

Output file:

```json
{
  "source_path": "/abs/path/inbox/statement.pdf",
  "file_type": "pdf",
  "pages": [
    {"page_number": 1, "text": "DBS Bank Statement\n...", "method": "text_layer"},
    {"page_number": 2, "text": "...", "method": "ocr"}
  ]
}
```

`method` is `text_layer` (text read from the PDF) or `ocr` (text recognised from the page image).

### name

- Reads every `.json` file under `<extracted_dir>` and writes a file with the same relative path under `<named_dir>`.
- `--model`: path to the GGUF file (required).
- Name format: `YYYY-MM-DD-<name><extension>`, for example `2026-03-31-DBS-Bank-Statement.pdf`. In the `<name>` part, spaces and `_` become `-`.
- The date is the date the document was issued. If it shows no issue date, the last day of the statement period it covers. If it shows neither, another date that the document states, such as a due date or a start date. If the date shows only a month and a year, the first day of that month.
- A document that shows no date, or whose date cannot be confirmed in its text, gets `undated-<name><extension>`.
- The `<name>` part has no fixed format. The model chooses words that describe the document, such as who issued it and what it is.
- The name is made safe for Windows and macOS: characters such as `/ : * ?` are replaced or removed, and the `<name>` part is limited to 120 characters. The extension of the original file is kept.
- Two documents from the same folder never get the same name: the second gets `-(2)`, the third `-(3)`, and so on, before the extension.
- `--max-document-tokens`: only the first this many tokens of each document are read (default 1024). Lower is faster. Higher reads more of each document.
- Exit code: `0` if no file failed, `1` if one or more files failed, `2` for incorrect arguments (missing folder, missing or unloadable model file, `--max-document-tokens` less than 1).

Output file:

```json
{
  "source_path": "/abs/path/inbox/statement.pdf",
  "suggested_name": "2026-03-31-DBS-Bank-Statement.pdf",
  "document_date": "2026-03-31",
  "reason": "The document is a bank statement from DBS covering March 2026."
}
```

### rename

- Reads every `.json` file under `<named_dir>`. For each, renames the file at `source_path` to `<folder>-<suggested_name>`, in the same folder. `<folder>` is the name of the folder that holds the file, with spaces and `_` changed to `-` (`Bank Statements/scan.pdf` becomes `Bank-Statements-2026-03-31-DBS-Bank-Statement.pdf`).
- `--dry-run`: shows what would be renamed, and changes no file.
- A file is never overwritten. If a different file already has the name, or two documents of one folder get the same name, the document is reported as failed and is not renamed.
- The suggested name must be one file name (no `/`, `\`, `..`) with the same extension as the source. Otherwise the document fails. The JSON files can be edited by hand before the rename.
- Safe to run again: a document that already has its new name is reported as `Already renamed`.
- Exit code: `0` if no file failed, `1` if one or more files failed, `2` for incorrect arguments (missing folder).

Output:

```
Renamed: statement.pdf.json: statement.pdf -> inbox-2026-03-31-DBS-Bank-Statement.pdf
Already renamed: 2026/IMG_2231.png.json: 2026-undated-Tax-Invoice.png
Failed: a.pdf.json: a file named inbox-2026-03-31-DBS-Bank-Statement.pdf already exists in /abs/path/inbox
Renamed 1, already renamed 1, failed 1
```

### run

- Runs `extract`, `name` and `rename` on `<input_dir>`, one after the other, in one process. The model is loaded once, before extraction.
- Writes the extracted JSON to `<work_dir>/extracted/` and the name suggestion JSON to `<work_dir>/named/`. When the renaming stage has finished, `<work_dir>/extracted/` is deleted. A cancelled run keeps it. Files under `<work_dir>` are not extracted, so `<work_dir>` can be inside `<input_dir>`.
- Renames without a pause for review. Use the three separate commands to examine the names first.
- Options: `--model` (required), `--ocr-engine`, `--max-document-tokens`, as for `extract` and `name`.
- A failed document does not stop the run. The next stages use the documents that did not fail.
- Output: a line `== Stage N of 3: ...` before each stage, then the output of that stage.
- Exit code: `0` if no document failed, `1` if one or more documents failed in any stage, `2` for incorrect arguments (missing folder, missing or unloadable model file, unavailable OCR engine).

### web

```sh
uv run doc-categoriser web                      # opens at the current folder
uv run doc-categoriser web ~/Documents/inbox    # opens at this folder
```

- Starts a local web server and opens the interface in the web browser. Stop it with Ctrl+C (this cancels the running folder).
- In the interface:
  - Browse folders (click a name to open it, `Up` for the parent, or type a path). Select one or more folders with the checkboxes, then `Add to queue`.
  - Each queued folder runs `doc-categoriser run` in a child process. One folder runs at a time, in queue order.
  - Click a folder in the queue to see its log, live.
  - `Cancel` removes a queued folder, or stops the running one. Documents renamed before the cancel keep their new names. Run the folder again to continue: all documents are extracted and named again, and a document that already has its new name (`<folder>-<suggested name>`) is reported as `Already renamed`.
  - `Decisions folder`: each queued folder gets the subfolder `<folder name>-<date>-<time>-<job number>` here, with `named/` (the rename decisions). `extracted/` is there during the run, and is deleted when the renaming has finished. Default: `renaming-decision` in the current folder.
  - `Model file`: the GGUF file. Default: `models/Qwen3.5-4B-Q4_K_M.gguf` in the current folder.
- Options: `--output-dir` and `--model` (the defaults shown in the interface), `--host` (default `127.0.0.1`), `--port` (default `8765`, `0` for a free port), `--no-browser`.
- Status of a folder: `Queued`, `Running`, `Done` (exit code 0), `Done with errors` (exit code 1: some documents failed, see the log), `Failed` (other exit code, for example a model file that cannot load), `Cancelled`.
- The queue and the logs are kept in memory only. They are lost when the server stops. The JSON files stay in the decisions folder.

## Moving parts

- `extract_document(path)`: selects an extractor by file suffix and returns the text, page by page.
- `PdfExtractor`: reads the PDF text layer with pdfplumber. A page with almost no text is rendered to an image and OCR'd.
- `ImageExtractor`: OCRs each frame of an image file.
- `AppleVisionOcrEngine`: OCR through ocrmac (macOS).
- `WindowsOcrEngine`: OCR through the Windows.Media.Ocr API, with the pywinrt packages (Windows).
- Both OCR engines put the recognised text in reading order, one line for each visual row.
- `suggest_document_name(document, namer)`: gives the document text to a namer, then builds `YYYY-MM-DD-<name><extension>` as a safe file name.
- `LlamaCppNamer`: runs the GGUF model in-process with llama-cpp-python. The answer is constrained to JSON with a name and a reason.
- `name_with_folder(source_path, suggested_name)`: puts the folder name in front of the suggested name.
- `rename_document(source_path, new_name)`: checks the name, then renames the file in its folder. Never overwrites.
- `doc-categoriser extract` / `name` / `rename`: run the three stages on a folder.
- `doc-categoriser run`: runs the three stages on a folder in one process.
- `doc-categoriser web`: a local HTTP server (Python standard library) with one page. A queue thread runs `doc-categoriser run` for each queued folder in a child process, and keeps its output as the log.

## Tests

```sh
uv run pytest
uv run pyright
```

Tests use the real OCR engine of the operating system. GitHub Actions runs them on macOS and Windows (`.github/workflows/tests.yml`).

The naming tests use the model at `models/Qwen3.5-4B-Q4_K_M.gguf`, or the path in the environment variable `DOC_CATEGORISER_TEST_MODEL`. If the file is not there, these tests are skipped.
