# doc-categoriser

Extracts the text of documents (PDFs and images) to JSON files. A later stage will use the JSON to categorise and rename the documents.

## Requirements

- macOS (OCR with the Apple Vision framework) or Windows 10 or later (OCR with Windows.Media.Ocr).
- On Windows, an OCR language pack for a language of the user profile. English is installed with an English Windows. To add one: Settings > Time & Language > Language.
- [uv](https://docs.astral.sh/uv/).

## Run

```sh
uv sync
uv run doc-categoriser extract <input_dir> <output_dir>
uv run doc-categoriser extract --ocr-engine windows <input_dir> <output_dir>
```

- `--ocr-engine`: `apple-vision` or `windows`. Default: the engine of the operating system (`apple-vision` on macOS, `windows` on Windows). An engine that cannot run on this operating system gives exit code `2`.

- All files under `<input_dir>` are read, including subfolders. Hidden files and folders (names that start with `.`) are ignored.
- For each document, the command writes `<output_dir>/<relative path>/<original name>.json`.
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

## Moving parts

- `extract_document(path)`: selects an extractor by file suffix and returns the text, page by page.
- `PdfExtractor`: reads the PDF text layer with pdfplumber. A page with almost no text is rendered to an image and OCR'd.
- `ImageExtractor`: OCRs each frame of an image file.
- `AppleVisionOcrEngine`: OCR through ocrmac (macOS).
- `WindowsOcrEngine`: OCR through the Windows.Media.Ocr API, with the pywinrt packages (Windows).
- Both OCR engines put the recognised text in reading order, one line for each visual row.
- `doc-categoriser extract`: runs the extraction on a folder and writes JSON files.

## Tests

```sh
uv run pytest
uv run pyright
```

Tests use the real OCR engine of the operating system. GitHub Actions runs them on macOS and Windows (`.github/workflows/tests.yml`).
