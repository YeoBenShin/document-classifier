"""Behaviour of the `doc-categoriser extract` and `classify` commands, run as an operator runs them."""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import PageLines
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen.canvas import Canvas

CLI_EXECUTABLE = Path(sys.executable).parent / "doc-categoriser"


def run_extract(input_dir: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run `doc-categoriser extract <input_dir> <output_dir>` and capture its output."""
    return subprocess.run(
        [str(CLI_EXECUTABLE), "extract", str(input_dir), str(output_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_extract_writes_one_json_file_per_document_mirroring_folders(
    tmp_path: Path,
    make_text_pdf: Callable[[str, list[PageLines]], Path],
    make_image: Callable[[str, PageLines], Path],
) -> None:
    input_dir = tmp_path / "inbox"
    (input_dir / "2025" / "scans").mkdir(parents=True)
    make_text_pdf("statement.pdf", [["DBS Bank Statement", "Opening balance 1,250.00"]]).rename(
        input_dir / "statement.pdf"
    )
    make_image("receipt.png", ["TAX INVOICE", "Amount due 312.50"]).rename(input_dir / "2025" / "scans" / "receipt.png")
    output_dir = tmp_path / "extracted"

    result = run_extract(input_dir, output_dir)

    assert result.returncode == 0, result.stderr
    statement = json.loads((output_dir / "statement.pdf.json").read_text())
    assert statement["source_path"] == str((input_dir / "statement.pdf").resolve())
    assert statement["file_type"] == "pdf"
    assert statement["pages"][0]["page_number"] == 1
    assert statement["pages"][0]["method"] == "text_layer"
    assert "DBS Bank Statement" in statement["pages"][0]["text"]
    receipt = json.loads((output_dir / "2025" / "scans" / "receipt.png.json").read_text())
    assert receipt["file_type"] == "png"
    assert receipt["pages"] == [{"page_number": 1, "text": "TAX INVOICE\nAmount due 312.50", "method": "ocr"}]


def test_extract_skips_unsupported_files_and_ignores_hidden_files(
    tmp_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_text_pdf("statement.pdf", [["DBS Bank Statement", "Opening balance 1,250.00"]]).rename(input_dir / "statement.pdf")
    (input_dir / "portfolio.xlsx").write_bytes(b"spreadsheet")
    (input_dir / ".DS_Store").write_bytes(b"finder metadata")
    output_dir = tmp_path / "extracted"

    result = run_extract(input_dir, output_dir)

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in output_dir.rglob("*") if path.is_file()) == ["statement.pdf.json"]
    assert "Skipped (unsupported type): portfolio.xlsx" in result.stdout
    assert ".DS_Store" not in result.stdout
    assert "Extracted 1, skipped 1, failed 0" in result.stdout


def test_extract_reports_a_broken_file_continues_and_exits_non_zero(
    tmp_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    (input_dir / "a_broken.pdf").write_bytes(b"this is not a pdf")
    make_text_pdf("statement.pdf", [["DBS Bank Statement", "Opening balance 1,250.00"]]).rename(input_dir / "statement.pdf")
    output_dir = tmp_path / "extracted"

    result = run_extract(input_dir, output_dir)

    assert result.returncode == 1
    assert (output_dir / "statement.pdf.json").exists()
    assert not (output_dir / "a_broken.pdf.json").exists()
    assert "Failed: a_broken.pdf" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Extracted 1, skipped 0, failed 1" in result.stdout


def test_extract_rejects_a_missing_input_folder(tmp_path: Path) -> None:
    result = run_extract(tmp_path / "does_not_exist", tmp_path / "extracted")

    assert result.returncode == 2
    assert "is not a folder" in result.stderr
    assert not (tmp_path / "extracted").exists()


def test_extract_reports_a_password_protected_pdf_clearly(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    canvas = Canvas(str(input_dir / "locked_statement.pdf"), encrypt=StandardEncryption("S1234567A"))
    canvas.drawString(72, 770, "Confidential bank statement")
    canvas.save()

    result = run_extract(input_dir, tmp_path / "extracted")

    assert result.returncode == 1
    assert "Failed: locked_statement.pdf: the PDF is password-protected" in result.stderr


REPOSITORY_CATEGORIES_FILE = Path(__file__).resolve().parent.parent / "categories.toml"


def run_classify(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    """Run `doc-categoriser classify <arguments>` and capture its output."""
    return subprocess.run(
        [str(CLI_EXECUTABLE), "classify", *(str(argument) for argument in arguments)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_classify_writes_the_category_of_each_extracted_document_mirroring_folders(
    tmp_path: Path,
    test_model_path: Path,
    make_text_pdf: Callable[[str, list[PageLines]], Path],
    make_image: Callable[[str, PageLines], Path],
) -> None:
    input_dir = tmp_path / "inbox"
    (input_dir / "2026").mkdir(parents=True)
    make_text_pdf(
        "statement.pdf",
        [["DBS Bank Statement", "Account 123-456789-0", "Opening balance 1,250.00", "Closing balance 980.40"]],
    ).rename(input_dir / "statement.pdf")
    make_image("receipt.png", ["TAX INVOICE", "Invoice No. INV-2026-0042", "Amount due 312.50"]).rename(
        input_dir / "2026" / "receipt.png"
    )
    extracted_dir = tmp_path / "extracted"
    classified_dir = tmp_path / "classified"
    assert run_extract(input_dir, extracted_dir).returncode == 0

    result = run_classify(
        extracted_dir, classified_dir, "--model", test_model_path, "--categories", REPOSITORY_CATEGORIES_FILE
    )

    assert result.returncode == 0, result.stderr
    statement = json.loads((classified_dir / "statement.pdf.json").read_text())
    assert statement["source_path"] == str((input_dir / "statement.pdf").resolve())
    assert statement["category"] == "bank_statement"
    assert statement["reason"].strip()
    receipt = json.loads((classified_dir / "2026" / "receipt.png.json").read_text())
    assert receipt["category"] == "invoice_receipt"
    assert "Classified: statement.pdf.json -> bank_statement" in result.stdout
    assert "Classified 2, failed 0" in result.stdout


def test_classify_reports_unusable_files_continues_and_exits_non_zero(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_text_pdf("statement.pdf", [["DBS Bank Statement", "Closing balance 980.40"]]).rename(input_dir / "statement.pdf")
    extracted_dir = tmp_path / "extracted"
    assert run_extract(input_dir, extracted_dir).returncode == 0
    (extracted_dir / "a_broken.pdf.json").write_text("{not json", encoding="utf-8")
    (extracted_dir / "blank_scan.pdf.json").write_text(
        json.dumps(
            {
                "source_path": "/inbox/blank_scan.pdf",
                "file_type": "pdf",
                "pages": [{"page_number": 1, "text": "", "method": "ocr"}],
            }
        ),
        encoding="utf-8",
    )
    classified_dir = tmp_path / "classified"

    result = run_classify(
        extracted_dir, classified_dir, "--model", test_model_path, "--categories", REPOSITORY_CATEGORIES_FILE
    )

    assert result.returncode == 1
    assert sorted(path.name for path in classified_dir.rglob("*") if path.is_file()) == ["statement.pdf.json"]
    assert "Failed: a_broken.pdf.json: the file is not an extracted document JSON file" in result.stderr
    assert "Failed: blank_scan.pdf.json: the document has no text" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Classified 1, failed 2" in result.stdout


@pytest.mark.parametrize(
    ("problem", "expected_message"),
    [
        ("missing_input_folder", "is not a folder"),
        ("missing_model", "is not a file"),
        ("invalid_categories", "has no [[category]] entries"),
        ("categories_is_a_folder", "cannot be read"),
        ("model_is_not_gguf", "cannot load the model"),
        ("zero_max_document_tokens", "must be 1 or more"),
    ],
)
def test_classify_rejects_incorrect_arguments_before_it_reads_any_document(
    tmp_path: Path, test_model_path: Path, problem: str, expected_message: str
) -> None:
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    categories_file = tmp_path / "categories.toml"
    categories_file.write_text('[[category]]\nname = "other"\ndescription = "Anything."\n', encoding="utf-8")
    model_path = test_model_path
    extra_arguments: list[str] = []
    if problem == "missing_input_folder":
        extracted_dir = tmp_path / "does_not_exist"
    elif problem == "missing_model":
        model_path = tmp_path / "missing.gguf"
    elif problem == "invalid_categories":
        categories_file.write_text('name = "other"\n', encoding="utf-8")
    elif problem == "categories_is_a_folder":
        categories_file = tmp_path / "categories_folder.toml"
        categories_file.mkdir()
    elif problem == "model_is_not_gguf":
        model_path = tmp_path / "not_a_model.gguf"
        model_path.write_text("this is not a GGUF file", encoding="utf-8")
    else:
        extra_arguments = ["--max-document-tokens", "0"]

    result = run_classify(
        extracted_dir,
        tmp_path / "classified",
        "--model",
        model_path,
        "--categories",
        categories_file,
        *extra_arguments,
    )

    assert result.returncode == 2
    assert expected_message in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "classified").exists()
