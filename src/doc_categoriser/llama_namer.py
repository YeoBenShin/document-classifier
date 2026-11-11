"""Document namer that runs a local GGUF model in-process with llama-cpp-python."""

import calendar
import datetime
import json
import re
from pathlib import Path
from typing import Any

from llama_cpp import Llama

from doc_categoriser.errors import NamingError
from doc_categoriser.naming import NameSuggestion

_SYSTEM_PROMPT = (
    "You name document files. Read the document text from the user and suggest a short, descriptive file name "
    "based only on the content. A person must know what the document is from the name alone. "
    "Use the words that identify the document, such as who issued it and what it is. Use at most 12 words. Do not add a file extension. Do not put the date in the name.\n"
    "Also give the date of the document. In date_text, copy exactly the words of the document that state its date, "
    "or give an empty string. In date, give that date as YYYY-MM-DD: the date it was issued, or if it shows no issue date, "
    "the last day of the statement period it covers (for the period 01/03/2026 - 31/03/2026, the date is 2026-03-31). "
    "If it shows neither, use another date that the document states, such as a due date or a start date. Use only a date that the document states as a date. "
    "A year in a reference number, invoice number or account number is not a date. "
    "If the date shows only a month and a year, the date is the first day of that month, also for a period or a valuation "
    "(for 'as at March 2026', the date is 2026-03-01). "
    "If the document shows no day and month, give an empty string.\n"
    'Reply with JSON only: {"reason": "<one sentence>", "date_text": "<words from the document or empty>", '
    '"date": "<YYYY-MM-DD or empty>", "name": "<file name>"}.'
)

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "date_text": {"type": "string"},
        "date": {"type": "string", "pattern": "^([0-9]{4}-[0-9]{2}-[0-9]{2})?$"},
        "name": {"type": "string"},
    },
    "required": ["reason", "date_text", "date", "name"],
}

_PROMPT_TOKEN_ALLOWANCE = 1024
"""Context tokens kept free for the instructions and the chat template."""


class LlamaCppNamer:
    """Suggests file names from document text with a GGUF chat model. The model output is constrained to the response schema."""

    def __init__(self, model_path: Path, max_document_tokens: int = 1024, max_output_tokens: int = 256) -> None:
        """
        `max_document_tokens`: only the first this many tokens of the document text are given to the model.
        More tokens give the model more of the document, but each document takes longer.
        `max_output_tokens`: the maximum length of the JSON answer.
        """
        self._max_document_tokens = max_document_tokens
        self._max_output_tokens = max_output_tokens
        self._model = Llama(
            model_path=str(model_path),
            n_ctx=max_document_tokens + max_output_tokens + _PROMPT_TOKEN_ALLOWANCE,
            n_gpu_layers=-1,
            verbose=False,
        )

    def suggest_name(self, document_text: str) -> NameSuggestion:
        """Return the name the model suggests for `document_text`. Raise NamingError if the answer is not usable."""
        response: Any = self._model.create_chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": self._first_document_tokens(document_text)},
            ],
            response_format={"type": "json_object", "schema": _RESPONSE_SCHEMA},
            temperature=0,
            max_tokens=self._max_output_tokens,
        )
        return _parse_answer(response["choices"][0]["message"]["content"] or "", document_text)

    def _first_document_tokens(self, document_text: str) -> str:
        """Return `document_text` cut to its first `max_document_tokens` tokens."""
        tokens = self._model.tokenize(document_text.encode("utf-8"), add_bos=False)
        if len(tokens) <= self._max_document_tokens:
            return document_text
        return self._model.detokenize(tokens[: self._max_document_tokens]).decode("utf-8", errors="ignore")


def _parse_answer(answer_text: str, document_text: str) -> NameSuggestion:
    """
    Return the NameSuggestion in the model's JSON answer. The date is kept only if `_is_stated_in_document` accepts it.
    Raise NamingError if the answer is not complete JSON.
    """
    try:
        answer = json.loads(answer_text)
        name, reason, date_text, iso_date = (str(answer[key]) for key in ("name", "reason", "date_text", "date"))
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise NamingError(f"the model gave an answer that is not usable: {answer_text[:200]!r}") from error
    document_date = _parse_date(iso_date)
    if document_date is not None and not _is_stated_in_document(document_date, date_text, document_text):
        document_date = None
    return NameSuggestion(name=name, reason=reason, document_date=document_date)


def _parse_date(iso_date: str) -> datetime.date | None:
    """Return the date in `iso_date` (YYYY-MM-DD), or None if it is empty or not a real calendar date."""
    try:
        return datetime.date.fromisoformat(iso_date)
    except ValueError:
        return None


def _collapse_whitespace(text: str) -> str:
    """Return `text` in lowercase with each run of whitespace changed to one space."""
    return " ".join(text.lower().split())


def _is_stated_in_document(document_date: datetime.date, date_text: str, document_text: str) -> bool:
    """
    Return True if `date_text` occurs in `document_text` and shows `document_date`:
    the year (4 or 2 digits), the month (number or English name), and the day (number).
    A day of 1 needs no day number if the month is a name, for a document that shows only a month and a year.
    """
    if not date_text.strip() or _collapse_whitespace(date_text) not in _collapse_whitespace(document_text):
        return False
    lowercase_text = date_text.lower()
    numbers = re.findall(r"\d+", date_text)
    short_numbers = {int(number) for number in numbers if len(number) <= 2}
    year_shown = str(document_date.year) in numbers or f"{document_date.year % 100:02d}" in numbers
    month_names = (calendar.month_name[document_date.month].lower(), calendar.month_abbr[document_date.month].lower())
    month_name_shown = any(re.search(rf"\b{name}", lowercase_text) for name in month_names)
    month_shown = month_name_shown or document_date.month in short_numbers
    day_shown = document_date.day in short_numbers or (document_date.day == 1 and month_name_shown)
    return year_shown and month_shown and day_shown
