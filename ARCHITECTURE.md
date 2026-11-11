# Architecture

## How it works

The program is a pipeline of stages: **extraction**, then **naming**. A later stage will rename the documents with the suggested names.

```
input folder ──> doc-categoriser extract ──> folder of extracted JSON ──> doc-categoriser name ──> folder of name suggestion JSON ──> (later) rename
                  (pdfplumber, OCR)                                         (local GGUF model)
```

- `src/doc_categoriser/`: the extraction and naming library and the CLI. See its `ARCHITECTURE.md`.
- `tests/`: tests at the public seams (library and CLI). See its `ARCHITECTURE.md`.
- `models/` (not committed): the GGUF model files.

The extracted JSON files are the contract between extraction and naming. Each file holds the source path, the file type, and the text of each page with the method used. The name suggestion JSON files hold the source path, the suggested name and the reason.

## Decisions

### Pipeline split

- Extraction and comprehension are separate stages with files between them. Extraction (OCR especially) is slow, and comprehension will change often (prompts, models). With files between them, comprehension can run again without OCR again.

### Local processing

- All processing is local. The documents are financial (bank statements, loan agreements, portfolio values) and must not go to a third-party service.
- OCR uses Apple Vision (through ocrmac). It is local, fast, accurate, and needs no model download. The cost is that OCR works only on macOS.

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

- The documents have no naming convention and are not sorted into fixed categories. The model names each document from its content only. The instructions say what a useful name holds (who issued it, what it is, the date or period), but do not set a format. Thus the separators and word order can differ between documents.
- The command writes suggestions only and renames no file. The operator can examine the names before a later step applies them.

### Constrained output

- The model answer is constrained by a JSON schema (llama.cpp grammar): `reason` (text) then `name` (text). The output is always JSON.
- `reason` comes before `name`, so the model writes a short explanation before it names the document. The operator also uses the reason to examine a doubtful name.

### Only the start of each document

- The namer reads only the first `max_document_tokens` tokens (default 1024). The title and first page usually identify the document type. Prompt processing on a laptop CPU is the slowest part, so a long statement must not be read completely.
- The limit is in tokens, not characters, because the namer knows the tokenizer. Text with many digits (statements) uses about one token per digit, so a character limit would not reliably fit in the context.

### Scope

- Supported types are PDF and images only. Emails, Word and Excel files are not supported yet.
