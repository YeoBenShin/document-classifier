# doc-categoriser

Extracts the text of documents (PDFs and images) to JSON files, then suggests a descriptive file name for each document from its content with a local LLM. No document leaves the machine. No file is renamed: the suggestions are written to JSON files.

## Requirements

- Python 3.13 or later.
- [uv](https://docs.astral.sh/uv/) (optional on Windows, see below).
- A GGUF chat model file. Recommended: `Qwen3.5-4B-Q4_K_M.gguf` (2.7 GB) from <https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf>. Put it anywhere, for example `models/`.
- OCR (for scanned pages and images) works on macOS only. On Windows and Linux, `extract` reads PDFs that have a text layer, and reports a failure for pages that need OCR.

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
uv run doc-categoriser name <extracted_dir> <named_dir> --model models/Qwen3.5-4B-Q4_K_M.gguf
```

### extract

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

## Moving parts

- `extract_document(path)`: selects an extractor by file suffix and returns the text, page by page.
- `PdfExtractor`: reads the PDF text layer with pdfplumber. A page with almost no text is rendered to an image and OCR'd.
- `ImageExtractor`: OCRs each frame of an image file.
- `AppleVisionOcrEngine`: OCR through ocrmac (macOS). `UnavailableOcrEngine` is used on other systems.
- `suggest_document_name(document, namer)`: gives the document text to a namer, then builds `YYYY-MM-DD-<name><extension>` as a safe file name.
- `LlamaCppNamer`: runs the GGUF model in-process with llama-cpp-python. The answer is constrained to JSON with a name and a reason.
- `doc-categoriser extract` / `name`: run the two stages on a folder.

## Tests

```sh
uv run pytest
uv run pyright
```

The naming tests use the model at `models/Qwen3.5-4B-Q4_K_M.gguf`, or the path in the environment variable `DOC_CATEGORISER_TEST_MODEL`. If the file is not there, these tests are skipped.
