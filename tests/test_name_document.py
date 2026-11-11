"""Behaviour of the naming library seam: suggest_document_name."""

import datetime
from pathlib import Path

import pytest

from doc_categoriser import (
    ExtractedDocument,
    ExtractionMethod,
    LlamaCppNamer,
    NameSuggestion,
    NamingError,
    PageText,
    suggest_document_name,
)

CHARACTERS_NOT_ALLOWED_IN_FILE_NAMES = set('<>:"/\\|?*')


def make_document(*page_texts: str, file_name: str = "scan_0001.pdf") -> ExtractedDocument:
    """Return an ExtractedDocument with one text-layer page for each text."""
    return ExtractedDocument(
        source_path=Path("/inbox") / file_name,
        pages=[
            PageText(page_number=page_number, text=text, method=ExtractionMethod.TEXT_LAYER)
            for page_number, text in enumerate(page_texts, start=1)
        ],
    )


class FixedAnswerNamer:
    """Returns the same name for every document, as a model could. Used to give exact unsafe names."""

    def __init__(self, name: str, document_date: datetime.date | None = datetime.date(2026, 3, 31)) -> None:
        self._name = name
        self._document_date = document_date

    def suggest_name(self, document_text: str) -> NameSuggestion:
        return NameSuggestion(name=self._name, reason="Fixed answer.", document_date=self._document_date)


@pytest.mark.parametrize(
    ("page_text", "expected_prefix", "expected_words"),
    [
        (
            "DBS Bank Statement\nAccount 123-456789-0\nStatement date 31/03/2026\n"
            "Statement period 01/03/2026 - 31/03/2026\n"
            "Opening balance 1,250.00\n02/03 GIRO SP SERVICES -120.30\nClosing balance 980.40",
            "2026-03-31-",
            ["dbs", "statement"],
        ),
        (
            "TAX INVOICE\nInvoice No. INV-2026-0042\nDate: 14 Feb 2026\nFrom: Bright Web Services Pte Ltd\n"
            "Bill to: Tan Holdings Pte Ltd\nWebsite hosting, 12 months 480.00\nGST 9% 43.20\nAmount due 523.20",
            "2026-02-14-",
            ["invoice"],
        ),
        (
            "Team meeting notes\nAttendees: Ken, Mei, Raj\nAgreed to move the office to the third floor.\n"
            "Raj will ask the landlord for a quote.",
            "undated-",
            ["meeting"],
        ),
        (
            "TAX INVOICE\nInvoice No. INV-2026-0042\nFrom: Bright Web Services Pte Ltd\nAmount due 312.50",
            "undated-",
            ["invoice"],
        ),
        (
            "Raffles Wealth Management\nPortfolio valuation as at March 2026\nEquities 1,200,000.00\nBonds 800,000.00",
            "2026-03-01-",
            ["portfolio"],
        ),
    ],
)
def test_document_gets_its_date_and_a_name_that_describes_its_content_with_a_reason(
    llama_namer: LlamaCppNamer, page_text: str, expected_prefix: str, expected_words: list[str]
) -> None:
    suggestion = suggest_document_name(make_document(page_text), llama_namer)

    assert suggestion.name.startswith(expected_prefix), suggestion.name
    assert suggestion.name.endswith(".pdf")
    assert all(word in suggestion.name.lower() for word in expected_words), suggestion.name
    assert not CHARACTERS_NOT_ALLOWED_IN_FILE_NAMES & set(suggestion.name)
    assert suggestion.reason.strip()


def test_a_document_longer_than_the_model_context_is_named_from_its_first_pages(llama_namer: LlamaCppNamer) -> None:
    first_page = (
        "LOAN AGREEMENT\nBorrower: Tan Holdings Pte Ltd\nLender: OCBC Bank\n"
        "Principal amount 500,000.00\nInterest rate 3.85% per annum\nTerm 60 months"
    )
    schedule_page = "Repayment schedule\n" + "\n".join(
        f"Instalment {number}  01/{number % 12 + 1:02d}/2027  9,180.25" for number in range(1, 61)
    )

    suggestion = suggest_document_name(make_document(first_page, *[schedule_page] * 40), llama_namer)

    assert "loan" in suggestion.name.lower()
    assert suggestion.name.startswith(("undated-", "20"))


def test_a_document_without_text_is_reported_and_not_given_to_the_model(llama_namer: LlamaCppNamer) -> None:
    with pytest.raises(NamingError, match="the document has no text"):
        suggest_document_name(make_document("", "  \n "), llama_namer)


@pytest.mark.parametrize(
    ("model_name", "source_file_name", "expected_name"),
    [
        ("DBS Statement 01/03/2026 - 15/03/2026", "scan.pdf", "2026-03-31-DBS Statement 01-03-2026 - 15-03-2026.pdf"),
        ('Invoice: "Bright Web" <INV|42>?*', "receipt.PNG", "2026-03-31-Invoice - Bright Web INV-42.PNG"),
        ("  Letter   from\tIRAS \n", "letter.pdf", "2026-03-31-Letter from IRAS.pdf"),
        ("Notice of Assessment 2026.pdf", "notice.pdf", "2026-03-31-Notice of Assessment 2026.pdf"),
        ("Policy schedule...", "policy.pdf", "2026-03-31-Policy schedule.pdf"),
        ("CON", "scan.pdf", "2026-03-31-CON.pdf"),
        ("A" * 300, "scan.pdf", "2026-03-31-" + "A" * 120 + ".pdf"),
        ("Board_" * 30, "scan.pdf", "2026-03-31-" + "Board_" * 19 + "Board.pdf"),
        ("DBS_Bank_Statement_2026-03-31", "scan.pdf", "2026-03-31-DBS_Bank_Statement.pdf"),
        ("2026-03-31 DBS Bank Statement", "scan.pdf", "2026-03-31-DBS Bank Statement.pdf"),
    ],
)
def test_the_suggested_name_is_a_safe_file_name_with_the_original_extension(
    model_name: str, source_file_name: str, expected_name: str
) -> None:
    suggestion = suggest_document_name(
        make_document("Some text", file_name=source_file_name), FixedAnswerNamer(model_name)
    )

    assert suggestion.name == expected_name


@pytest.mark.parametrize("model_name", ["", "   ", "???", "..."])
def test_a_suggested_name_with_no_usable_characters_is_reported(model_name: str) -> None:
    with pytest.raises(NamingError, match="the model gave no usable name"):
        suggest_document_name(make_document("Some text"), FixedAnswerNamer(model_name))


def test_a_document_without_a_date_gets_the_undated_prefix() -> None:
    suggestion = suggest_document_name(make_document("Some text"), FixedAnswerNamer("Meeting notes", document_date=None))

    assert suggestion.name == "undated-Meeting notes.pdf"


def test_a_name_that_is_only_the_date_is_reported() -> None:
    with pytest.raises(NamingError, match="the model gave no usable name"):
        suggest_document_name(make_document("Some text"), FixedAnswerNamer("2026-03-31"))
