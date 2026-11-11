"""Behaviour of extract_document, the library seam of the extraction stage."""

import sys
from collections.abc import Callable
from pathlib import Path

import pillow_heif
import pytest
from PIL import Image, ImageDraw, ImageFont
from conftest import PageLines, render_text_image

from doc_categoriser import ExtractionMethod, UnsupportedFileTypeError, extract_document


def test_text_layer_pdf_is_read_without_ocr(make_text_pdf: Callable[[str, list[PageLines]], Path]) -> None:
    pdf_path = make_text_pdf(
        "statement.pdf",
        [
            ["DBS Bank Statement", "Opening balance 1,250.00"],
            ["Closing balance 980.40"],
        ],
    )

    document = extract_document(pdf_path)

    assert document.source_path == pdf_path
    assert [page.page_number for page in document.pages] == [1, 2]
    assert all(page.method is ExtractionMethod.TEXT_LAYER for page in document.pages)
    assert "DBS Bank Statement" in document.pages[0].text
    assert "Opening balance 1,250.00" in document.pages[0].text
    assert "Closing balance 980.40" in document.pages[1].text


def test_scanned_pdf_pages_are_read_with_ocr(make_scanned_pdf: Callable[[str, list[PageLines]], Path]) -> None:
    pdf_path = make_scanned_pdf(
        "loan.pdf",
        [
            ["LOAN AGREEMENT", "Principal amount 500,000"],
            ["Repayment schedule"],
        ],
    )

    document = extract_document(pdf_path)

    assert [page.page_number for page in document.pages] == [1, 2]
    assert all(page.method is ExtractionMethod.OCR for page in document.pages)
    assert "LOAN AGREEMENT" in document.pages[0].text
    assert "Principal amount 500,000" in document.pages[0].text
    assert "Repayment schedule" in document.pages[1].text


@pytest.mark.parametrize("file_name", ["receipt.png", "receipt.jpg", "receipt.JPEG", "receipt.tiff"])
def test_image_file_is_read_with_ocr_as_one_page(
    make_image: Callable[[str, PageLines], Path], file_name: str
) -> None:
    image_path = make_image(file_name, ["TAX INVOICE", "Amount due 312.50"])

    document = extract_document(image_path)

    assert len(document.pages) == 1
    assert document.pages[0].page_number == 1
    assert document.pages[0].method is ExtractionMethod.OCR
    assert document.pages[0].text.splitlines() == ["TAX INVOICE", "Amount due 312.50"]


def test_unsupported_file_type_is_rejected(tmp_path: Path) -> None:
    spreadsheet_path = tmp_path / "portfolio.xlsx"
    spreadsheet_path.write_bytes(b"not used")

    with pytest.raises(UnsupportedFileTypeError, match="portfolio.xlsx"):
        extract_document(spreadsheet_path)


def test_pdf_with_text_and_scanned_pages_uses_the_method_each_page_needs(
    make_mixed_pdf: Callable[[str, list[tuple[str, PageLines]]], Path],
) -> None:
    pdf_path = make_mixed_pdf(
        "valuation.pdf",
        [
            ("text", ["Portfolio Valuation Report", "Prepared for client account 8812"]),
            ("scan", ["Total market value 2,400,000"]),
        ],
    )

    document = extract_document(pdf_path)

    assert [page.method for page in document.pages] == [ExtractionMethod.TEXT_LAYER, ExtractionMethod.OCR]
    assert "Portfolio Valuation Report" in document.pages[0].text
    assert "Total market value 2,400,000" in document.pages[1].text


def test_multi_page_tiff_gives_one_page_per_frame(tmp_path: Path) -> None:
    tiff_path = tmp_path / "scan.tiff"
    first_page = render_text_image(["Account history January"])
    second_page = render_text_image(["Account history February"])
    first_page.save(tiff_path, save_all=True, append_images=[second_page])

    document = extract_document(tiff_path)

    assert [page.page_number for page in document.pages] == [1, 2]
    assert document.pages[0].text == "Account history January"
    assert document.pages[1].text == "Account history February"


def test_heic_photo_is_read_with_ocr(tmp_path: Path) -> None:
    heic_path = tmp_path / "photo.heic"
    pillow_heif.from_pillow(render_text_image(["Electricity bill", "Due date 30 Nov"])).save(heic_path)

    document = extract_document(heic_path)

    assert document.pages[0].text.splitlines() == ["Electricity bill", "Due date 30 Nov"]


def test_ocr_keeps_table_columns_on_the_same_line_in_reading_order(tmp_path: Path) -> None:
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    table_cells = [
        (100, 150, "Date"), (900, 150, "Amount"),
        (100, 230, "03 Jan"), (900, 233, "120.00"),
        (100, 310, "17 Jan"), (900, 307, "45.90"),
    ]
    for left, top, cell_text in table_cells:
        draw.text((left, top), cell_text, fill="black", font=font)
    image_path = tmp_path / "transactions.png"
    image.save(image_path)

    document = extract_document(image_path)

    assert document.pages[0].text.splitlines() == ["Date Amount", "03 Jan 120.00", "17 Jan 45.90"]


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.skipif(sys.platform != "darwin", reason="the look-alike letter fix is for Apple Vision OCR")
def test_ocr_gives_latin_letters_for_latin_words_on_a_noisy_scan() -> None:
    document = extract_document(FIXTURES_DIR / "noisy_bank_letter_scan.png")

    text = document.pages[0].text
    assert text.splitlines()[0] == "OCBC Bank"
    assert not [character for character in text if "Ͱ" <= character <= "ӿ"]
