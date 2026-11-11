"""Behaviour of the `doc-categoriser extract` command, run as an operator runs it."""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

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
