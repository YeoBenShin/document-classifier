# Architecture

## How it works

The program is a pipeline of stages: **extraction**, then **naming**, then **renaming**.

```
input folder ──> doc-categoriser extract ──> folder of extracted JSON ──> doc-categoriser name ──> folder of name suggestion JSON ──> doc-categoriser rename ──> input folder, files renamed
                  (pdfplumber, OCR)                                         (local GGUF model)                                         (in place, no overwrite)
```

- `src/doc_categoriser/`: the library and the CLI. `extraction/`, `classification/` and `renaming/` hold one stage each. See its `ARCHITECTURE.md`.
- `tests/`: tests at the public seams (library and CLI). See its `ARCHITECTURE.md`.
- `models/` (not committed): the GGUF model files.

The extracted JSON files are the contract between extraction and naming. Each file holds the source path, the file type, and the text of each page with the method used. The name suggestion JSON files hold the source path, the suggested name and the reason. They are the contract between naming and renaming.

## Decisions

### Pipeline split

- Extraction and comprehension are separate stages with files between them. Extraction (OCR especially) is slow, and comprehension will change often (prompts, models). With files between them, comprehension can run again without OCR again.

### Local processing

- All processing is local. The documents are financial (bank statements, loan agreements, portfolio values) and must not go to a third-party service.
- OCR uses the engine built into the operating system: Apple Vision on macOS (through ocrmac), Windows.Media.Ocr on Windows (through pywinrt). Both are local, fast, and need no model download.

### Native OCR for each operating system

- The program must run on macOS and on Windows. A cross-platform engine (for example Tesseract) needs a separate install and a model download, and is less accurate on photos and noisy scans than the built-in engines.
- The engine is chosen with `--ocr-engine`. The default is the engine of the operating system, so an operator does not need the option.
- An engine is only importable on its own operating system (ocrmac needs pyobjc, pywinrt needs Windows). Thus the dependencies have platform markers, and the engine modules are imported only when the engine is created.
- The Windows tests run on a GitHub Actions Windows runner. The development machine is a Mac, and no Windows machine is available to it.

### Target machine

- The program must run on a Windows laptop (Intel Core i7-1355U, 16 GB RAM, integrated graphics only). On that laptop, each third-party application needs a long approval process. Thus the program must not need a separate application such as Ollama, LM Studio or a C++ compiler. Python packages from prebuilt wheels are acceptable.
- On Windows, ocrmac is not installed (it is a macOS-only dependency) and is imported only when OCR runs. PDFs with a text layer extract. Pages that need OCR fail with a clear message. A Windows OCR engine is not done yet.

### LLM runtime: llama-cpp-python in-process

- llama-cpp-python runs a GGUF model inside the Python process. No server or separate application is necessary.
- On Windows and Linux, the package comes from the prebuilt CPU wheel index of the project (`abetlen.github.io/llama-cpp-python/whl/cpu`). PyPI has only the source, and a source build on Windows needs Visual Studio Build Tools. The wheel is `py3-none`, so it works with any Python 3 version.
- On macOS, the package is built from source. The macOS wheels of 0.3.35 and 0.3.36 on that index (CPU and Metal) are corrupt: `unzip -t` reports bad CRCs and uv refuses them. The build uses Apple clang (`/usr/bin/clang`), set in `tool.uv.extra-build-variables`. A Homebrew clang first on `PATH` fails on the macOS SDK headers (`-Welaborated-enum-base` errors in CFBase.h).
- Alternatives that were not selected: Ollama (a separate application), transformers on CPU (slow and uses much memory), MLX (macOS only), OpenVINO (more setup; possible later to use the integrated graphics).

### Model: Qwen3.5 4B, Q4_K_M

- Qwen3.5 4B had the best reported results among 4B-class open models in November 2026, and its 2.7 GB Q4_K_M file fits easily in 16 GB RAM. llama-cpp-python 0.3.36 loads it and its chat template without changes.
- Measured on an M3 Pro: about 10 s for a 720-token document on CPU only, 4 s with Metal. The i7-1355U laptop will be slower. Not measured yet.
- The model is a parameter (`--model`). A smaller model (Qwen3.5 0.8B or 2B) or a larger one can be used without code changes.

### Names from content, no categories

- The documents are not sorted into fixed categories. Each name is `YYYY-MM-DD-<name>`: the document date, then a descriptive part from the content only. The instructions say what a useful descriptive part holds (who issued it, what it is), but do not set a format. Thus the word order in that part can differ between documents. The program changes spaces and `_` to `-`, so all names use one separator. At rename, the name of the folder of the document goes in front: `<folder>-YYYY-MM-DD-<name>` (see `src/doc_categoriser/renaming/ARCHITECTURE.md`).
- `name` writes suggestions only and renames no file. The operator can examine (and edit) the names before `rename` applies them.

### Separate rename stage

- The rename changes the operator's files, and a wrong name from the model is likely sometimes. Thus it is a separate command that the operator runs after examining the suggestions, with `--dry-run` to see the result first.
- `rename` reads only the name suggestion JSON, not the model. It is fast and needs no model file.

### Constrained output

- The model answer is constrained by a JSON schema (llama.cpp grammar): `reason`, `date_text`, `date` (`YYYY-MM-DD` or empty), `name`. The output is always JSON.
- `reason` comes before `name`, so the model writes a short explanation before it names the document. The operator also uses the reason to examine a doubtful name.

### Only the start of each document

- The namer reads only the first `max_document_tokens` tokens (default 1024). The title and first page usually identify the document type. Prompt processing on a laptop CPU is the slowest part, so a long statement must not be read completely.
- The limit is in tokens, not characters, because the namer knows the tokenizer. Text with many digits (statements) uses about one token per digit, so a character limit would not reliably fit in the context.

### Scope

- Supported types are PDF and images only. Emails, Word and Excel files are not supported yet.
