# doc-categoriser

Extracts the text of documents (PDFs and images) to JSON files, then classifies each document into a category with a local LLM. No document leaves the machine.

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
uv run doc-categoriser classify <extracted_dir> <classified_dir> --model models/Qwen3.5-4B-Q4_K_M.gguf
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

### classify

- Reads every `.json` file under `<extracted_dir>` and writes a file with the same relative path under `<classified_dir>`.
- `--model`: path to the GGUF file (required).
- `--categories`: TOML file with the categories (default `categories.toml` in the current folder). Edit `categories.toml` to change the categories. Each entry needs a `name` and a `description`.
- `--max-document-tokens`: only the first this many tokens of each document are read (default 1024). Lower is faster. Higher reads more of each document.
- Exit code: `0` if no file failed, `1` if one or more files failed, `2` for incorrect arguments (missing folder, missing model file, incorrect categories file).

Output file:

```json
{
  "source_path": "/abs/path/inbox/statement.pdf",
  "category": "bank_statement",
  "reason": "The document is a DBS bank statement with an opening and closing balance."
}
```

## Moving parts

- `extract_document(path)`: selects an extractor by file suffix and returns the text, page by page.
- `PdfExtractor`: reads the PDF text layer with pdfplumber. A page with almost no text is rendered to an image and OCR'd.
- `ImageExtractor`: OCRs each frame of an image file.
- `AppleVisionOcrEngine`: OCR through ocrmac (macOS). `UnavailableOcrEngine` is used on other systems.
- `load_categories(path)`: reads the categories file.
- `classify_document(document, categories, classifier)`: gives the document text to a classifier and returns the category and reason.
- `LlamaCppClassifier`: runs the GGUF model in-process with llama-cpp-python. The answer is constrained to one of the category names.
- `doc-categoriser extract` / `classify`: run the two stages on a folder.

## Tests

```sh
uv run pytest
uv run pyright
```

The classification tests use the model at `models/Qwen3.5-4B-Q4_K_M.gguf`, or the path in the environment variable `DOC_CATEGORISER_TEST_MODEL`. If the file is not there, these tests are skipped.
