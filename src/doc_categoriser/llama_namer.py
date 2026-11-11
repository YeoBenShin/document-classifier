"""Document namer that runs a local GGUF model in-process with llama-cpp-python."""

import json
from pathlib import Path
from typing import Any

from llama_cpp import Llama

from doc_categoriser.errors import NamingError
from doc_categoriser.naming import NameSuggestion

_SYSTEM_PROMPT = (
    "You name document files. Read the document text from the user and suggest a short, descriptive file name "
    "based only on the content. A person must know what the document is from the name alone. "
    "Use the words that identify the document, such as who issued it, what it is, and the date or period it covers, "
    "if the document shows them. Use at most 12 words. Do not add a file extension.\n"
    'Reply with JSON only: {"reason": "<one sentence>", "name": "<file name>"}.'
)

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "name": {"type": "string"}},
    "required": ["reason", "name"],
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
        return _parse_answer(response["choices"][0]["message"]["content"] or "")

    def _first_document_tokens(self, document_text: str) -> str:
        """Return `document_text` cut to its first `max_document_tokens` tokens."""
        tokens = self._model.tokenize(document_text.encode("utf-8"), add_bos=False)
        if len(tokens) <= self._max_document_tokens:
            return document_text
        return self._model.detokenize(tokens[: self._max_document_tokens]).decode("utf-8", errors="ignore")


def _parse_answer(answer_text: str) -> NameSuggestion:
    """Return the NameSuggestion in the model's JSON answer. Raise NamingError if it is not complete JSON."""
    try:
        answer = json.loads(answer_text)
        return NameSuggestion(name=str(answer["name"]), reason=str(answer["reason"]))
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise NamingError(f"the model gave an answer that is not usable: {answer_text[:200]!r}") from error
