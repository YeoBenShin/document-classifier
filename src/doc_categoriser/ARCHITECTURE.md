# doc_categoriser package

## How it works

Extraction (`doc-categoriser extract`):

```
cli.py ──> extraction.extract_document(path, extractors)
               │  selects the first extractor whose supported_suffixes has the file suffix
               ├── pdf_extractor.PdfExtractor ──┐
               └── image_extractor.ImageExtractor ──> ocr.OcrEngine (AppleVisionOcrEngine on macOS, UnavailableOcrEngine elsewhere)
           <── models.ExtractedDocument
cli.py ──> json_output.write_document_json(...)
```

Naming (`doc-categoriser name`):

```
cli.py ──> llama_namer.LlamaCppNamer(model_path)            (loads the GGUF model once)
for each extracted JSON file:
cli.py ──> json_output.read_document_json(path) ──> models.ExtractedDocument
cli.py ──> naming.suggest_document_name(document, namer)
               │  joins the pages as "--- Page N ---" + text
               ├── namer.suggest_name(text)  (DocumentNamer protocol)
               │       LlamaCppNamer: cuts the text to max_document_tokens, chat completion with a JSON schema
               └── makes the name a safe file name and adds the source file extension
           <── naming.NameSuggestion (name, reason)
cli.py ──> naming.unique_name(name, names used in the same folder)
cli.py ──> json_output.write_name_suggestion_json(...)
```

- `models.py`: `ExtractedDocument` (source path + list of `PageText`), `PageText` (page number, text, `ExtractionMethod`).
- `errors.py`: `ExtractionError` and its subclasses `UnsupportedFileTypeError`, `PasswordProtectedDocumentError` and `OcrUnavailableError`. `NamingError`. Their messages are written for the operator.
- `extraction.py`: the `DocumentExtractor` protocol, `default_extractors()`, and `extract_document()`. Raises `UnsupportedFileTypeError` when no extractor supports the suffix. `default_extractors()` uses `AppleVisionOcrEngine` on macOS and `UnavailableOcrEngine` on other systems.
- `pdf_extractor.py`: raises `PasswordProtectedDocumentError` for an encrypted PDF. For each page, reads the text layer with pdfplumber. If the page has fewer than `min_text_layer_chars` (20) non-whitespace characters, it renders the page at `ocr_resolution_dpi` (300) and sends the image to the OCR engine.
- `image_extractor.py`: opens the image with Pillow (HEIC through pillow-heif) and sends each frame to the OCR engine. A multi-page TIFF gives one page per frame.
- `ocr.py`: the `OcrEngine` protocol, `AppleVisionOcrEngine` and `UnavailableOcrEngine` (raises `OcrUnavailableError` for each page). `AppleVisionOcrEngine` imports ocrmac only when it runs. Vision returns text fragments with bounding boxes. The engine changes Cyrillic and Greek look-alike letters to Latin letters (see Decisions), then groups fragments into rows by vertical position and joins each row left to right, so table rows stay on one line.
- `naming.py`: `NameSuggestion` (name, reason, document date or None), the `DocumentNamer` protocol, `suggest_document_name()` and `unique_name()`. `suggest_document_name` raises `NamingError` if no page has text, so a blank scan is not given to the model. It then makes the suggested name safe: `/ \\ |` become `-`, `:` becomes ` - `, `" < > ? *` are removed, whitespace is collapsed, an extension that the model added is removed, copies of the document date (YYYY-MM-DD) are removed, the length is limited to 120 characters, and separators (space, `_`, `-`, `.`) at the start and end are removed. It raises `NamingError` if no letter or digit is left. The result is `YYYY-MM-DD-<name><extension>`, or `undated-<name><extension>` if the document date is None. The extension of the source file is added unchanged. `unique_name` adds ` (2)`, ` (3)` and so on before the extension, and ignores case.
- `llama_namer.py`: `LlamaCppNamer`. Loads the GGUF model with a context of `max_document_tokens` + `max_output_tokens` + 1024 tokens for the instructions. For each document: cuts the text to `max_document_tokens` with the model tokenizer, sends the instructions and the text, and constrains the answer to the JSON schema `{reason, date_text, date, name}`, with `date` limited to `YYYY-MM-DD` or empty. Temperature 0. Keeps the date only if `date_text` occurs in the document and shows the year, month and day of `date` (see Decisions). Raises `NamingError` if the answer is not complete JSON.
- `json_output.py`: converts an `ExtractedDocument` to JSON and back (`read_document_json`), writes the name suggestion JSON, and calculates the output path.
- `cli.py`: `extract` finds the files, runs `extract_document` on each, writes the JSON, prints a summary. `name` checks the arguments (folder, model file, `--max-document-tokens` of 1 or more) before it loads the model, reports a model that cannot load as an argument error, then suggests a name for each `.json` file, makes the names unique in each folder, and prints a summary. In both commands, a failure on one file does not stop the run.

To add a file type, write a class with `supported_suffixes` and `extract(path)`, and add it to `default_extractors()`. To use a different OCR engine, write a class with `recognise_text(image)` and give it to the extractors. To use a different LLM runtime, write a class with `suggest_name(document_text)` and give it to `suggest_document_name`.

## Decisions

### Text layer first, OCR for each page

- Text from the PDF text layer is exact and fast. OCR is slower and can make errors. Thus OCR is used only where the text layer is almost empty.
- The decision is made for each page, not for each file. Scanned documents often have a digital cover page, or a digital document has scanned appendices.
- The threshold is 20 non-whitespace characters. A scanned page can have a small text layer, for example a page number or a stamp, that is less than this.

### Protocols for extractors, OCR and namers

- `DocumentExtractor`, `OcrEngine` and `DocumentNamer` are protocols. The CLI, extractors and `suggest_document_name` depend on these, not on pdfplumber, ocrmac or llama-cpp-python directly. Another OCR engine, file type or LLM runtime can be added without changes to the existing code.

### ocrmac imported only when OCR runs

- ocrmac depends on pyobjc, which exists only on macOS. If `ocr.py` imported it at the top, the CLI could not start on Windows, also for `name`, which does not use OCR.

### Truncation in the namer, not in suggest_document_name

- Only the namer knows its tokenizer and its context size. Thus `LlamaCppNamer` cuts the text, and `suggest_document_name` gives it all pages.

### Safe names in suggest_document_name, not in the namer

- Every namer (any model or runtime) can return a name that is not a valid file name, for example a date with `/`. The rules are the same for all namers, so they are in one place.
- The rules follow Windows, the strictest target system. A name that is valid on Windows is also valid on macOS.
- The extension comes from the source file, not from the model. The model must not change the file type, and a name with the wrong extension would not open.

### Date prefix

- The date is in front of the name as `YYYY-MM-DD`, so the files of a folder sort by date.
- A device name such as `CON` cannot occur, because every name starts with a date or `undated`.
- The model often puts the date in the name too, even when told not to. Thus copies of the same `YYYY-MM-DD` date are removed from the name. Dates in other forms ("March 2026") stay.

### Date check in LlamaCppNamer

- A 4B model can give a date that the document does not state. For example, for an invoice with the number `INV-2026-0042` and no date, it gave `2026-01-01`. Instructions did not stop this.
- Thus the model must also copy the words that state the date (`date_text`). The date is kept only if these words occur in the document, and contain the year (4 or 2 digits), the month (number or English name), and the day. A day of 1 needs no day number if the month is a name, for "as at March 2026". Otherwise the document is `undated`. A wrong `undated` is less harmful than a wrong date, because the operator sees it.
- The instructions include an example for a period (`01/03/2026 - 31/03/2026` gives `2026-03-31`). Without it, the model took the first date of the period.
- The check cannot find a date in the wrong order of day and month (`03/04/2026` read as 4 March in place of 3 April), because both numbers occur in the text.

### Unique names in each folder

- The suggestions will be used to rename the files. Two documents in the same folder with the same name would then overwrite each other, for example two copies of one statement. Thus the CLI makes each name unique in its source folder. The comparison ignores case, because Windows and macOS file systems usually ignore case.
- The CLI does it, not `suggest_document_name`, because only the CLI sees all documents of a folder.

### Reading order for OCR

- Vision can return text fragments on the same visual row as separate results, for example the columns of a transaction table. Without grouping, the amount for a row can appear on a different line from its date. The grouping keeps each table row on one line, which is easier for an LLM to read.

### Cyrillic and Greek look-alike letters

- On noisy scans, Apple Vision can return Cyrillic letters that look like Latin letters. For example, "OCBC Bank" came back as "ОСВС Bank" (U+041E U+0421 U+0412 U+0421). The text looks correct but a search for the bank name fails.
- Vision settings do not prevent this. We tried `recognitionLanguages = ["en-US"]`, `automaticallyDetectsLanguage = False`, `usesLanguageCorrection = False`, and revisions 1-3.
- Thus the engine changes the look-alike letters to Latin, one word at a time. It changes a word only if every Cyrillic or Greek letter in it is a look-alike. A word with other Cyrillic or Greek letters ("Привет") stays as it is. A real Cyrillic word made only of look-alike letters (for example "ОСА") is changed in error. This risk is accepted because the documents are mostly English.

### Errors in the CLI

- For an `ExtractionError` or a `NamingError`, the CLI prints only its message, because the message is written for the operator. For other exceptions, it prints the exception type and message.
- An encrypted PDF gets its own error, because bank statements are often password-protected. Without it, pdfplumber gives an empty message.
- The CLI catches all exceptions for each file. One broken file in a large folder must not stop the run. The exit code is 1 so that a script can see that a file failed.
- `name` checks the model path before it loads the model. Loading takes several seconds, and an operator error must show at once with exit code 2.
- Each progress line is flushed at once, so an operator who sends the output to a log file sees the progress during a long run.
