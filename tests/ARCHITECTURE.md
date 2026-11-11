# tests

## How it works

- `conftest.py`: builders that make sample documents in a temporary folder: PDFs with a text layer (reportlab), image-only PDFs, PDFs with both page types, and image files (Pillow).
- `test_extract_document.py`: tests the library seam, `extract_document(path)`.
- `test_cli.py`: tests the CLI seam, including `--ocr-engine`. It runs the installed `doc-categoriser` command in a subprocess and examines the JSON files, stdout, stderr and exit code.

## Decisions

### Only two seams

- Tests use only the public seams: `extract_document` and the CLI. Internal functions (row grouping, output paths) are tested through these seams, so they can change without test changes.

### Real OCR, no mocks

- The tests use the real pdfplumber and the real Apple Vision OCR. The most likely errors are in how the program uses these libraries (rendering, coordinates, reading order), and a mock does not find those errors.
- The sample text is drawn with a large clear font, so the OCR result is stable and the tests can compare exact text.
- The first OCR call in a new process takes much longer than later calls, because Vision loads its model.

### One test suite for each operating system

- The same tests run on macOS (Apple Vision) and on Windows (Windows OCR), because `extract_document` and the CLI use the native engine by default. Thus every OCR test checks both engines, in the GitHub Actions workflow.
- Tests that only apply to one engine are skipped on the other system: the look-alike letter test (Apple Vision only), and the test for an engine that is not for this system.

### Committed scan fixture

- `fixtures/noisy_bank_letter_scan.png` is a noisy, rotated scan of a bank letter. On a clean generated image, Vision does not return Cyrillic look-alike letters. On this scan it does, every time. The test for the look-alike fix needs this file.
- A newer macOS Vision version could read this file correctly without the fix. Then the test passes but no longer proves the fix.

### HEIC sample

- The HEIC test file is written with `pillow_heif.from_pillow(...)`, not with the global HEIF opener. If the test registered the opener, the test could pass even when the program does not register it.
