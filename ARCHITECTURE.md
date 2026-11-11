# Architecture

## How it works

The program is a pipeline of stages. This repository has the first stage only: **extraction**.

```
input folder ──> doc-categoriser extract ──> output folder of JSON files ──> (later) comprehension + rename
```

- `src/doc_categoriser/`: the extraction library and the CLI. See its `ARCHITECTURE.md`.
- `tests/`: tests at the two public seams (library and CLI). See its `ARCHITECTURE.md`.

The JSON files are the contract between extraction and the later comprehension stage. Each file holds the source path, the file type, and the text of each page with the method used.

## Decisions

### Pipeline split

- Extraction and comprehension are separate stages with files between them. Extraction (OCR especially) is slow, and comprehension will change often (prompts, models, categories). With files between them, comprehension can run again without OCR again.

### Local processing

- All processing is local. The documents are financial (bank statements, loan agreements, portfolio values) and must not go to a third-party service.
- OCR uses Apple Vision (through ocrmac). It is local, fast, accurate, and needs no model download. The cost is that the program runs only on macOS.

### Output format

- One JSON file for each document, not one combined file. The comprehension stage can read one document at a time, and an operator can examine one file by hand.
- The output name keeps the original extension (`receipt.png.json`). Thus `receipt.png` and `receipt.pdf` in the same folder do not overwrite each other.
- Page boundaries and the method for each page are kept. The comprehension stage can use only the first pages, and can give less trust to OCR text.

### Scope

- Supported types are PDF and images only. Emails, Word and Excel files are not supported yet.
