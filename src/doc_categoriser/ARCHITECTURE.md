# doc_categoriser package

## How it works

```
cli.py ──> extraction.extract_document(path, extractors)
               │  selects the first extractor whose supported_suffixes has the file suffix
               ├── pdf_extractor.PdfExtractor ──┐
               └── image_extractor.ImageExtractor ──> ocr.OcrEngine (AppleVisionOcrEngine)
           <── models.ExtractedDocument
cli.py ──> json_output.write_document_json(...)
```

- `models.py`: `ExtractedDocument` (source path + list of `PageText`), `PageText` (page number, text, `ExtractionMethod`).
- `errors.py`: `ExtractionError` and its subclasses `UnsupportedFileTypeError` and `PasswordProtectedDocumentError`. Their messages are written for the operator.
- `extraction.py`: the `DocumentExtractor` protocol, `default_extractors()`, and `extract_document()`. Raises `UnsupportedFileTypeError` when no extractor supports the suffix.
- `pdf_extractor.py`: raises `PasswordProtectedDocumentError` for an encrypted PDF. For each page, reads the text layer with pdfplumber. If the page has fewer than `min_text_layer_chars` (20) non-whitespace characters, it renders the page at `ocr_resolution_dpi` (300) and sends the image to the OCR engine.
- `image_extractor.py`: opens the image with Pillow (HEIC through pillow-heif) and sends each frame to the OCR engine. A multi-page TIFF gives one page per frame.
- `ocr.py`: the `OcrEngine` protocol and `AppleVisionOcrEngine`. Vision returns text fragments with bounding boxes. The engine changes Cyrillic and Greek look-alike letters to Latin letters (see Decisions), then groups fragments into rows by vertical position and joins each row left to right, so table rows stay on one line.
- `json_output.py`: converts an `ExtractedDocument` to JSON and calculates the output path.
- `cli.py`: finds the files, runs `extract_document` on each, writes the JSON, prints a summary. A failure on one file does not stop the run.

To add a file type, write a class with `supported_suffixes` and `extract(path)`, and add it to `default_extractors()`. To use a different OCR engine, write a class with `recognise_text(image)` and give it to the extractors.

## Decisions

### Text layer first, OCR for each page

- Text from the PDF text layer is exact and fast. OCR is slower and can make errors. Thus OCR is used only where the text layer is almost empty.
- The decision is made for each page, not for each file. Scanned documents often have a digital cover page, or a digital document has scanned appendices.
- The threshold is 20 non-whitespace characters. A scanned page can have a small text layer, for example a page number or a stamp, that is less than this.

### Protocols for extractors and OCR

- `DocumentExtractor` and `OcrEngine` are protocols. The CLI and extractors depend on these, not on pdfplumber or ocrmac directly. Another OCR engine or file type can be added without changes to the existing code.

### Reading order for OCR

- Vision can return text fragments on the same visual row as separate results, for example the columns of a transaction table. Without grouping, the amount for a row can appear on a different line from its date. The grouping keeps each table row on one line, which is easier for an LLM to read.

### Cyrillic and Greek look-alike letters

- On noisy scans, Apple Vision can return Cyrillic letters that look like Latin letters. For example, "OCBC Bank" came back as "ОСВС Bank" (U+041E U+0421 U+0412 U+0421). The text looks correct but a search for the bank name fails.
- Vision settings do not prevent this. We tried `recognitionLanguages = ["en-US"]`, `automaticallyDetectsLanguage = False`, `usesLanguageCorrection = False`, and revisions 1-3.
- Thus the engine changes the look-alike letters to Latin, one word at a time. It changes a word only if every Cyrillic or Greek letter in it is a look-alike. A word with other Cyrillic or Greek letters ("Привет") stays as it is. A real Cyrillic word made only of look-alike letters (for example "ОСА") is changed in error. This risk is accepted because the documents are mostly English.

### Errors in the CLI

- For an `ExtractionError`, the CLI prints only its message, because the message is written for the operator. For other exceptions, it prints the exception type and message.
- An encrypted PDF gets its own error, because bank statements are often password-protected. Without it, pdfplumber gives an empty message.
- The CLI catches all exceptions for each file. One broken file in a large folder must not stop the run. The exit code is 1 so that a script can see that a file failed.
