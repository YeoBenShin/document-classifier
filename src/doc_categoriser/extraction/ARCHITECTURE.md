# extraction

The extraction stage. Reads the text of each page of a PDF or image to an `ExtractedDocument`.

## How it works

```
extractor.default_extractors(ocr_engine)
extractor.extract_document(path, extractors)
    │  selects the first extractor whose supported_suffixes has the file suffix
    ├── pdf_extractor.PdfExtractor ──┐
    └── image_extractor.ImageExtractor ──> ocr.OcrEngine (see ocr/ARCHITECTURE.md)
<── models.ExtractedDocument
```

- `__init__.py`: exports `DocumentExtractor`, `default_extractors` and `extract_document`.
- `extractor.py`: the `DocumentExtractor` protocol, `default_extractors(ocr_engine=None)`, and `extract_document()`. With no engine, `default_extractors` uses the native engine of the operating system. Raises `UnsupportedFileTypeError` when no extractor supports the suffix.
- `pdf_extractor.py`: raises `PasswordProtectedDocumentError` for an encrypted PDF. For each page, reads the text layer with pdfplumber. If the page has fewer than `min_text_layer_chars` (20) non-whitespace characters, it renders the page at `ocr_resolution_dpi` (300) and sends the image to the OCR engine.
- `image_extractor.py`: opens the image with Pillow (HEIC through pillow-heif) and sends each frame to the OCR engine. A multi-page TIFF gives one page per frame.
- `ocr/`: OCR engines. See its `ARCHITECTURE.md`.

To add a file type, write a class with `supported_suffixes` and `extract(path)`, and add it to `default_extractors()`.

## Decisions

### Text layer first, OCR for each page

- Text from the PDF text layer is exact and fast. OCR is slower and can make errors. Thus OCR is used only where the text layer is almost empty.
- The decision is made for each page, not for each file. Scanned documents often have a digital cover page, or a digital document has scanned appendices.
- The threshold is 20 non-whitespace characters. A scanned page can have a small text layer, for example a page number or a stamp, that is less than this.
