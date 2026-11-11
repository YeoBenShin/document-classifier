"""Document classifier that runs a local GGUF model in-process with llama-cpp-python."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from llama_cpp import Llama

from doc_categoriser.categories import Category
from doc_categoriser.classification import Classification
from doc_categoriser.errors import ClassificationError


def _system_prompt(categories: Sequence[Category]) -> str:
    """Return the instructions for the model, with each category name and description on its own line."""
    category_lines = "\n".join(f"- {category.name}: {category.description}" for category in categories)
    return (
        "You classify documents. Read the document text from the user and choose the one category that fits best.\n"
        f"Categories:\n{category_lines}\n\n"
        'Reply with JSON only: {"reason": "<one sentence>", "category": "<category name>"}.'
    )


def _response_schema(categories: Sequence[Category]) -> dict[str, Any]:
    """Return the JSON schema that limits the model output to a reason and one of the category names."""
    return {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "category": {"type": "string", "enum": [category.name for category in categories]},
        },
        "required": ["reason", "category"],
    }


_PROMPT_TOKEN_ALLOWANCE = 1024
"""Context tokens kept free for the instructions, the category list and the chat template."""


class LlamaCppClassifier:
    """Classifies document text with a GGUF chat model. The model output is constrained to the response schema."""

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

    def classify(self, document_text: str, categories: Sequence[Category]) -> Classification:
        """Return the category the model chooses for `document_text`. Raise ClassificationError if the answer is not usable."""
        response: Any = self._model.create_chat_completion(
            messages=[
                {"role": "system", "content": _system_prompt(categories)},
                {"role": "user", "content": self._first_document_tokens(document_text)},
            ],
            response_format={"type": "json_object", "schema": _response_schema(categories)},
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


def _parse_answer(answer_text: str) -> Classification:
    """Return the Classification in the model's JSON answer. Raise ClassificationError if it is not complete JSON."""
    try:
        answer = json.loads(answer_text)
        return Classification(category=answer["category"], reason=answer["reason"])
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ClassificationError(f"the model gave an answer that is not usable: {answer_text[:200]!r}") from error
