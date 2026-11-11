# tests

## How it works

- `conftest.py`: builders that make sample documents in a temporary folder: PDFs with a text layer (reportlab), image-only PDFs, PDFs with both page types, and image files (Pillow). The `test_model_path` and `llama_classifier` fixtures give the GGUF model (one load for the whole session).
- `test_extract_document.py`: tests the extraction library seam, `extract_document(path)`.
- `test_classify_document.py`: tests the classification library seam, `load_categories(path)` and `classify_document(document, categories, classifier)`.
- `test_cli.py`: tests the CLI seam. It runs the installed `doc-categoriser` command in a subprocess and examines the JSON files, stdout, stderr and exit code. The classify tests run `extract` first, as an operator does.

## Decisions

### Only the public seams

- Tests use only the public seams: `extract_document`, `load_categories`, `classify_document` and the CLI. Internal functions (row grouping, output paths) are tested through these seams, so they can change without test changes.

### Real OCR, no mocks

- The tests use the real pdfplumber and the real Apple Vision OCR. The most likely errors are in how the program uses these libraries (rendering, coordinates, reading order), and a mock does not find those errors.
- The sample text is drawn with a large clear font, so the OCR result is stable and the tests can compare exact text.
- The first OCR call in a new process takes much longer than later calls, because Vision loads its model.

### Committed scan fixture

- `fixtures/noisy_bank_letter_scan.png` is a noisy, rotated scan of a bank letter. On a clean generated image, Vision does not return Cyrillic look-alike letters. On this scan it does, every time. The test for the look-alike fix needs this file.
- A newer macOS Vision version could read this file correctly without the fix. Then the test passes but no longer proves the fix.

### HEIC sample

- The HEIC test file is written with `pillow_heif.from_pillow(...)`, not with the global HEIF opener. If the test registered the opener, the test could pass even when the program does not register it.

### Real model, no mocks

- The classification tests use the real Qwen3.5 4B GGUF model. The most likely errors are in how the program uses llama-cpp-python (chat template, JSON schema, context size, truncation), and a fake classifier does not find those errors.
- The model file is 2.7 GB and is not committed. The tests read `models/Qwen3.5-4B-Q4_K_M.gguf` or the path in `DOC_CATEGORISER_TEST_MODEL`, and skip if the file is not there.
- The sample documents are clear examples of one category each, and the temperature is 0, so the expected category is stable.
- The Windows paths (no ocrmac, prebuilt wheel) are not covered by the tests, because the tests run on macOS.
