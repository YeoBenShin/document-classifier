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

Classification (`doc-categoriser classify`):

```
cli.py ──> categories.load_categories(categories.toml)
cli.py ──> llama_classifier.LlamaCppClassifier(model_path)            (loads the GGUF model once)
for each extracted JSON file:
cli.py ──> json_output.read_document_json(path) ──> models.ExtractedDocument
cli.py ──> classification.classify_document(document, categories, classifier)
               │  joins the pages as "--- Page N ---" + text
               └── classifier.classify(text, categories)  (DocumentClassifier protocol)
                       LlamaCppClassifier: cuts the text to max_document_tokens, chat completion with a JSON schema
           <── classification.Classification (category, reason)
cli.py ──> json_output.write_classification_json(...)
```

- `models.py`: `ExtractedDocument` (source path + list of `PageText`), `PageText` (page number, text, `ExtractionMethod`).
- `errors.py`: `ExtractionError` and its subclasses `UnsupportedFileTypeError`, `PasswordProtectedDocumentError` and `OcrUnavailableError`. `ClassificationError` and its subclass `CategoryFileError`. Their messages are written for the operator.
- `extraction.py`: the `DocumentExtractor` protocol, `default_extractors()`, and `extract_document()`. Raises `UnsupportedFileTypeError` when no extractor supports the suffix. `default_extractors()` uses `AppleVisionOcrEngine` on macOS and `UnavailableOcrEngine` on other systems.
- `pdf_extractor.py`: raises `PasswordProtectedDocumentError` for an encrypted PDF. For each page, reads the text layer with pdfplumber. If the page has fewer than `min_text_layer_chars` (20) non-whitespace characters, it renders the page at `ocr_resolution_dpi` (300) and sends the image to the OCR engine.
- `image_extractor.py`: opens the image with Pillow (HEIC through pillow-heif) and sends each frame to the OCR engine. A multi-page TIFF gives one page per frame.
- `ocr.py`: the `OcrEngine` protocol, `AppleVisionOcrEngine` and `UnavailableOcrEngine` (raises `OcrUnavailableError` for each page). `AppleVisionOcrEngine` imports ocrmac only when it runs. Vision returns text fragments with bounding boxes. The engine changes Cyrillic and Greek look-alike letters to Latin letters (see Decisions), then groups fragments into rows by vertical position and joins each row left to right, so table rows stay on one line.
- `categories.py`: `Category` (name, description) and `load_categories(path)`. Raises `CategoryFileError` for a missing file, incorrect TOML, no entries, an entry without a text name and description, or a name used twice.
- `classification.py`: `Classification` (category, reason), the `DocumentClassifier` protocol, and `classify_document()`. Raises `ClassificationError` if no page has text, so a blank scan is not given to the model.
- `llama_classifier.py`: `LlamaCppClassifier`. Loads the GGUF model with a context of `max_document_tokens` + `max_output_tokens` + 1024 tokens for the instructions. For each document: cuts the text to `max_document_tokens` with the model tokenizer, sends the instructions (category names and descriptions) and the text, and constrains the answer to the JSON schema `{reason, category}` with `category` limited to the category names. Temperature 0. Raises `ClassificationError` if the answer is not complete JSON.
- `json_output.py`: converts an `ExtractedDocument` to JSON and back (`read_document_json`), writes the classification JSON, and calculates the output path.
- `cli.py`: `extract` finds the files, runs `extract_document` on each, writes the JSON, prints a summary. `classify` checks the arguments (folder, categories file, model file) before it loads the model, then classifies each `.json` file and prints a summary. In both commands, a failure on one file does not stop the run.

To add a file type, write a class with `supported_suffixes` and `extract(path)`, and add it to `default_extractors()`. To use a different OCR engine, write a class with `recognise_text(image)` and give it to the extractors. To use a different LLM runtime, write a class with `classify(document_text, categories)` and give it to `classify_document`.

## Decisions

### Text layer first, OCR for each page

- Text from the PDF text layer is exact and fast. OCR is slower and can make errors. Thus OCR is used only where the text layer is almost empty.
- The decision is made for each page, not for each file. Scanned documents often have a digital cover page, or a digital document has scanned appendices.
- The threshold is 20 non-whitespace characters. A scanned page can have a small text layer, for example a page number or a stamp, that is less than this.

### Protocols for extractors, OCR and classifiers

- `DocumentExtractor`, `OcrEngine` and `DocumentClassifier` are protocols. The CLI, extractors and `classify_document` depend on these, not on pdfplumber, ocrmac or llama-cpp-python directly. Another OCR engine, file type or LLM runtime can be added without changes to the existing code.

### ocrmac imported only when OCR runs

- ocrmac depends on pyobjc, which exists only on macOS. If `ocr.py` imported it at the top, the CLI could not start on Windows, also for `classify`, which does not use OCR.

### Truncation in the classifier, not in classify_document

- Only the classifier knows its tokenizer and its context size. Thus `LlamaCppClassifier` cuts the text, and `classify_document` gives it all pages.

### Reading order for OCR

- Vision can return text fragments on the same visual row as separate results, for example the columns of a transaction table. Without grouping, the amount for a row can appear on a different line from its date. The grouping keeps each table row on one line, which is easier for an LLM to read.

### Cyrillic and Greek look-alike letters

- On noisy scans, Apple Vision can return Cyrillic letters that look like Latin letters. For example, "OCBC Bank" came back as "ОСВС Bank" (U+041E U+0421 U+0412 U+0421). The text looks correct but a search for the bank name fails.
- Vision settings do not prevent this. We tried `recognitionLanguages = ["en-US"]`, `automaticallyDetectsLanguage = False`, `usesLanguageCorrection = False`, and revisions 1-3.
- Thus the engine changes the look-alike letters to Latin, one word at a time. It changes a word only if every Cyrillic or Greek letter in it is a look-alike. A word with other Cyrillic or Greek letters ("Привет") stays as it is. A real Cyrillic word made only of look-alike letters (for example "ОСА") is changed in error. This risk is accepted because the documents are mostly English.

### Errors in the CLI

- For an `ExtractionError` or a `ClassificationError`, the CLI prints only its message, because the message is written for the operator. For other exceptions, it prints the exception type and message.
- An encrypted PDF gets its own error, because bank statements are often password-protected. Without it, pdfplumber gives an empty message.
- The CLI catches all exceptions for each file. One broken file in a large folder must not stop the run. The exit code is 1 so that a script can see that a file failed.
- `classify` checks the categories file and the model path before it loads the model. Loading takes several seconds, and an operator error must show at once with exit code 2.
