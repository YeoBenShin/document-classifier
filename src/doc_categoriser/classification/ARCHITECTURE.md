# classification

The classification stage. Suggests a dated, safe file name for an `ExtractedDocument` with a local LLM.

## How it works

```
llama_namer.LlamaCppNamer(model_path)            (loads the GGUF model once)
naming.suggest_document_name(document, namer)
    │  joins the pages as "--- Page N ---" + text
    ├── namer.suggest_name(text)  (DocumentNamer protocol)
    │       LlamaCppNamer: cuts the text to max_document_tokens, chat completion with a JSON schema
    └── makes the name a safe file name and adds the source file extension
<── naming.NameSuggestion (name, reason, document date)
naming.unique_name(name, names already used)
```

- `__init__.py`: exports `DocumentNamer`, `LlamaCppNamer`, `NameSuggestion`, `suggest_document_name` and `unique_name`.
- `naming.py`: `NameSuggestion` (name, reason, document date or None), the `DocumentNamer` protocol, `suggest_document_name()` and `unique_name()`. `suggest_document_name` raises `NamingError` if no page has text, so a blank scan is not given to the model. It then makes the suggested name safe: `/ \\ |` become `-`, `:` becomes ` - `, `" < > ? *` are removed, whitespace is collapsed, an extension that the model added is removed, copies of the document date (YYYY-MM-DD) are removed, spaces and `_` become `-` and repeated `-` become one, the length is limited to 120 characters, and separators (space, `_`, `-`, `.`) at the start and end are removed. It raises `NamingError` if no letter or digit is left. The result is `YYYY-MM-DD-<name><extension>`, or `undated-<name><extension>` if the document date is None. The extension of the source file is added unchanged. `unique_name` adds `-(2)`, `-(3)` and so on before the extension, and ignores case.
- `llama_namer.py`: `LlamaCppNamer`. Loads the GGUF model with a context of `max_document_tokens` + `max_output_tokens` + 1024 tokens for the instructions. For each document: cuts the text to `max_document_tokens` with the model tokenizer, sends the instructions and the text, and constrains the answer to the JSON schema `{reason, date_text, date, name}`, with `date` limited to `YYYY-MM-DD` or empty. Temperature 0. Keeps the date only if `date_text` occurs in the document and shows the year, month and day of `date` (see Decisions). Raises `NamingError` if the answer is not complete JSON.

To use a different LLM runtime, write a class with `suggest_name(document_text)` and give it to `suggest_document_name`.

## Decisions

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
- The date rule, in order: issue date; last day of a statement period; another date that the document states (due date, start date); for a month and a year only, the first day of the month. A policy with a start and an end date gets its start date, not the end of its term.
- The instructions include an example for a period (`01/03/2026 - 31/03/2026` gives `2026-03-31`) and for a month and a year (`as at March 2026` gives `2026-03-01`). Without the examples, the model took the first date of a period, and the last day of a month for "as at March 2026".
- The check cannot find a date in the wrong order of day and month (`03/04/2026` read as 4 March in place of 3 April), because both numbers occur in the text.
