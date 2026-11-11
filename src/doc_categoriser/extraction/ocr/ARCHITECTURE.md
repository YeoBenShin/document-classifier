# extraction/ocr

OCR engines that turn a page image into text, and selection of an engine by name.

## How it works

```
create_ocr_engine(name)  (name from --ocr-engine or native_ocr_engine_name())
    ├── apple_vision.AppleVisionOcrEngine (macOS)
    └── windows.WindowsOcrEngine (Windows)
    both ──> layout.boxes_to_text
```

- `__init__.py`: the `OcrEngine` protocol, `OcrEngineName` (`apple-vision`, `windows`), `native_ocr_engine_name()` and `create_ocr_engine(name)`. `create_ocr_engine` raises `OcrEngineUnavailableError` if the engine is not for this operating system, and imports the engine module only then.
- `layout.py`: `TextBox` (text with a position as fractions of the image size) and `boxes_to_text`, which groups boxes into rows by vertical position and joins each row left to right, so table rows stay on one line.
- `apple_vision.py`: `AppleVisionOcrEngine`. Vision returns text fragments with bounding boxes. The engine changes Cyrillic and Greek look-alike letters to Latin letters (see Decisions), then calls `boxes_to_text`.
- `windows.py`: `WindowsOcrEngine`. Uses the languages of the Windows user profile, and raises `OcrEngineUnavailableError` if none has an installed OCR language. It scales an image down to `OcrEngine.MaxImageDimension`, copies it into a `SoftwareBitmap` (RGBA8), and runs `RecognizeAsync`. Windows returns lines of words with pixel bounding boxes. Each line becomes one `TextBox` that covers all its words, then `boxes_to_text` is called.

To add an OCR engine, write a class with `recognise_text(image)` in its own module in this folder, add a name to `OcrEngineName` and an entry to `_ENGINE_SPECS`.

## Decisions

### ocrmac imported only when OCR runs

- ocrmac depends on pyobjc, which exists only on macOS. If it were imported at the top, the CLI could not start on Windows, also for `name`, which does not use OCR. `__init__.py` imports an engine module only in `create_ocr_engine`.

### Reading order for OCR

- The row grouping is shared by both engines, so the output has the same shape on macOS and Windows.
- Windows already returns lines, but like Vision it can return two columns of one table row as separate lines. Thus its lines also go through the row grouping.
- Vision can return text fragments on the same visual row as separate results, for example the columns of a transaction table. Without grouping, the amount for a row can appear on a different line from its date. The grouping keeps each table row on one line, which is easier for an LLM to read.

### Cyrillic and Greek look-alike letters

- On noisy scans, Apple Vision can return Cyrillic letters that look like Latin letters. For example, "OCBC Bank" came back as "ОСВС Bank" (U+041E U+0421 U+0412 U+0421). The text looks correct but a search for the bank name fails.
- Vision settings do not prevent this. We tried `recognitionLanguages = ["en-US"]`, `automaticallyDetectsLanguage = False`, `usesLanguageCorrection = False`, and revisions 1-3.
- Thus the Apple Vision engine changes the look-alike letters to Latin, one word at a time. The Windows engine does not, because it recognises only the scripts of its installed languages. It changes a word only if every Cyrillic or Greek letter in it is a look-alike. A word with other Cyrillic or Greek letters ("Привет") stays as it is. A real Cyrillic word made only of look-alike letters (for example "ОСА") is changed in error. This risk is accepted because the documents are mostly English.

### Windows OCR

- pywinrt is the official Python projection of the Windows Runtime. It calls Windows.Media.Ocr directly, with no other program to install.
- The engine uses the languages of the user profile, not a fixed language. Windows has an OCR pack for each installed display language, so this works with no settings. If no pack is installed, the engine fails at start with a message that tells the operator how to install one.
- `RecognizeAsync` is asynchronous. The engine calls it with `asyncio.run` for each page, so the rest of the program stays synchronous.
- Windows OCR supports images up to `MaxImageDimension` pixels on each side (10000 on the GitHub Actions Windows runner). Thus the engine scales a larger image down first. A 300 dpi page is far below this limit; a very high resolution scan is not.
- The engine modules have file-level pyright settings for missing imports. Each engine package installs only on its own operating system, so pyright on the other system cannot find it.
