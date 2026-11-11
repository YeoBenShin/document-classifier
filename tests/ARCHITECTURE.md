# tests

## How it works

- `conftest.py`: builders that make sample documents in a temporary folder: PDFs with a text layer (reportlab), image-only PDFs, PDFs with both page types, and image files (Pillow).
- `test_extract_document.py`: tests the library seam, `extract_document(path)`.
- `test_cli.py`: tests the CLI seam. It runs the installed `doc-categoriser` command in a subprocess and examines the JSON files, stdout, stderr and exit code.

## Decisions

### Only two seams

- Tests use only the public seams: `extract_document` and the CLI. Internal functions (row grouping, output paths) are tested through these seams, so they can change without test changes.

### Real OCR, no mocks

- The tests use the real pdfplumber and the real Apple Vision OCR. The most likely errors are in how the program uses these libraries (rendering, coordinates, reading order), and a mock does not find those errors.
- The sample text is drawn with a large clear font, so the OCR result is stable and the tests can compare exact text.
- The first OCR call in a new process takes much longer than later calls, because Vision loads its model.

### HEIC sample

- The HEIC test file is written with `pillow_heif.from_pillow(...)`, not with the global HEIF opener. If the test registered the opener, the test could pass even when the program does not register it.
