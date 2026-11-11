"""Entry point that turns an extracted document into one category, with a classifier such as a local LLM."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from doc_categoriser.categories import Category
from doc_categoriser.errors import ClassificationError
from doc_categoriser.models import ExtractedDocument


@dataclass(frozen=True)
class Classification:
    """The chosen category name and the classifier's short explanation of the choice."""

    category: str
    reason: str


class DocumentClassifier(Protocol):
    """Chooses one of `categories` for a document, given the document's text."""

    def classify(self, document_text: str, categories: Sequence[Category]) -> Classification: ...


def document_text_for_classification(document: ExtractedDocument) -> str:
    """Return the text of all pages, each page preceded by a `--- Page N ---` line."""
    return "\n\n".join(f"--- Page {page.page_number} ---\n{page.text}" for page in document.pages)


def classify_document(
    document: ExtractedDocument, categories: Sequence[Category], classifier: DocumentClassifier
) -> Classification:
    """Return the category that `classifier` chooses for `document`. Raise ClassificationError if no page has text."""
    if not any(page.text.strip() for page in document.pages):
        raise ClassificationError("the document has no text")
    return classifier.classify(document_text_for_classification(document), categories)
