"""Behaviour of the classification library seam: load_categories and classify_document."""

import re
from pathlib import Path

import pytest

from doc_categoriser import (
    Category,
    CategoryFileError,
    ClassificationError,
    ExtractedDocument,
    ExtractionMethod,
    LlamaCppClassifier,
    PageText,
    classify_document,
    load_categories,
)


def test_categories_are_loaded_in_file_order(tmp_path: Path) -> None:
    categories_file = tmp_path / "categories.toml"
    categories_file.write_text(
        '[[category]]\nname = "bank_statement"\ndescription = "A bank account statement."\n\n'
        '[[category]]\nname = "other"\ndescription = "Anything else."\n',
        encoding="utf-8",
    )

    categories = load_categories(categories_file)

    assert categories == [
        Category(name="bank_statement", description="A bank account statement."),
        Category(name="other", description="Anything else."),
    ]


@pytest.mark.parametrize(
    ("file_content", "expected_message"),
    [
        ('name = "bank_statement"\n', "has no [[category]] entries"),
        ('[[category]]\nname = "bank_statement"\n', "category 1 needs a text 'name' and 'description'"),
        (
            '[[category]]\nname = "other"\ndescription = "A."\n\n[[category]]\nname = "other"\ndescription = "B."\n',
            "category name 'other' is used more than once",
        ),
        ("[[category]\n", "is not valid TOML"),
    ],
)
def test_an_invalid_categories_file_is_reported_clearly(
    tmp_path: Path, file_content: str, expected_message: str
) -> None:
    categories_file = tmp_path / "categories.toml"
    categories_file.write_text(file_content, encoding="utf-8")

    with pytest.raises(CategoryFileError, match=re.escape(expected_message)):
        load_categories(categories_file)


def test_a_missing_categories_file_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(CategoryFileError, match="does not exist"):
        load_categories(tmp_path / "missing.toml")


SAMPLE_CATEGORIES = [
    Category(name="bank_statement", description="A periodic statement of a bank account, with transactions and balances."),
    Category(name="loan_agreement", description="A loan, mortgage or credit facility agreement or offer letter."),
    Category(name="invoice_receipt", description="An invoice, bill or receipt for goods or services."),
    Category(name="other", description="Any document that does not match one of the other categories."),
]


def make_document(*page_texts: str) -> ExtractedDocument:
    """Return an ExtractedDocument with one text-layer page for each text."""
    return ExtractedDocument(
        source_path=Path("/inbox/document.pdf"),
        pages=[
            PageText(page_number=page_number, text=text, method=ExtractionMethod.TEXT_LAYER)
            for page_number, text in enumerate(page_texts, start=1)
        ],
    )


@pytest.mark.parametrize(
    ("page_text", "expected_category"),
    [
        (
            "DBS Bank Statement\nAccount 123-456789-0\nStatement period 01/03/2026 - 31/03/2026\n"
            "Opening balance 1,250.00\n02/03 GIRO SP SERVICES -120.30\nClosing balance 980.40",
            "bank_statement",
        ),
        (
            "TAX INVOICE\nInvoice No. INV-2026-0042\nBill to: Tan Holdings Pte Ltd\n"
            "Website hosting, 12 months 480.00\nGST 9% 43.20\nAmount due 523.20",
            "invoice_receipt",
        ),
    ],
)
def test_document_is_classified_into_the_matching_category_with_a_reason(
    llama_classifier: LlamaCppClassifier, page_text: str, expected_category: str
) -> None:
    classification = classify_document(make_document(page_text), SAMPLE_CATEGORIES, llama_classifier)

    assert classification.category == expected_category
    assert classification.reason.strip()


def test_a_document_longer_than_the_model_context_is_classified_from_its_first_pages(
    llama_classifier: LlamaCppClassifier,
) -> None:
    first_page = (
        "LOAN AGREEMENT\nBorrower: Tan Holdings Pte Ltd\nLender: OCBC Bank\n"
        "Principal amount 500,000.00\nInterest rate 3.85% per annum\nTerm 60 months"
    )
    schedule_page = "Repayment schedule\n" + "\n".join(
        f"Instalment {number}  01/{number % 12 + 1:02d}/2027  9,180.25" for number in range(1, 61)
    )

    classification = classify_document(
        make_document(first_page, *[schedule_page] * 40), SAMPLE_CATEGORIES, llama_classifier
    )

    assert classification.category == "loan_agreement"


def test_a_document_without_text_is_reported_and_not_given_to_the_model(
    llama_classifier: LlamaCppClassifier,
) -> None:
    with pytest.raises(ClassificationError, match="the document has no text"):
        classify_document(make_document("", "  \n "), SAMPLE_CATEGORIES, llama_classifier)
