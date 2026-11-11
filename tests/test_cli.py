"""Behaviour of the `doc-categoriser extract` and `name` commands, run as an operator runs them."""

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


def run_extract(input_dir: Path, output_dir: Path, *options: str) -> subprocess.CompletedProcess[str]:
    """Run `doc-categoriser extract [options] <input_dir> <output_dir>` and capture its output."""
    return subprocess.run(
        [str(CLI_EXECUTABLE), "extract", *options, str(input_dir), str(output_dir)],
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
    statement = json.loads((output_dir / "statement.pdf.json").read_text(encoding="utf-8"))
    assert statement["source_path"] == str((input_dir / "statement.pdf").resolve())
    assert statement["file_type"] == "pdf"
    assert statement["pages"][0]["page_number"] == 1
    assert statement["pages"][0]["method"] == "text_layer"
    assert "DBS Bank Statement" in statement["pages"][0]["text"]
    receipt = json.loads((output_dir / "2025" / "scans" / "receipt.png.json").read_text(encoding="utf-8"))
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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows OCR is available on Windows")
def test_extract_rejects_windows_ocr_on_another_platform(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()

    result = run_extract(input_dir, tmp_path / "extracted", "--ocr-engine", "windows")

    assert result.returncode == 2
    assert "Windows OCR is available only on Windows" in result.stderr
    assert not (tmp_path / "extracted").exists()


NATIVE_OCR_ENGINE_FOR_PLATFORM = {"darwin": "apple-vision", "win32": "windows"}


def test_extract_reads_scans_with_the_chosen_native_ocr_engine(
    tmp_path: Path, make_image: Callable[[str, PageLines], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_image("receipt.png", ["TAX INVOICE", "Amount due 312.50"]).rename(input_dir / "receipt.png")
    output_dir = tmp_path / "extracted"

    result = run_extract(input_dir, output_dir, "--ocr-engine", NATIVE_OCR_ENGINE_FOR_PLATFORM[sys.platform])

    assert result.returncode == 0, result.stderr
    receipt = json.loads((output_dir / "receipt.png.json").read_text(encoding="utf-8"))
    assert receipt["pages"] == [{"page_number": 1, "text": "TAX INVOICE\nAmount due 312.50", "method": "ocr"}]


@pytest.mark.skipif(sys.platform == "darwin", reason="Apple Vision OCR is available on macOS")
def test_extract_rejects_apple_vision_ocr_on_another_platform(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()

    result = run_extract(input_dir, tmp_path / "extracted", "--ocr-engine", "apple-vision")

    assert result.returncode == 2
    assert "Apple Vision OCR is available only on macOS" in result.stderr


def test_extract_lists_the_ocr_engines_for_an_unknown_engine(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()

    result = run_extract(input_dir, tmp_path / "extracted", "--ocr-engine", "tesseract")

    assert result.returncode == 2
    assert "invalid choice: 'tesseract'" in result.stderr
    assert "apple-vision" in result.stderr.split("invalid choice")[1]
    assert "windows" in result.stderr.split("invalid choice")[1]
CHARACTERS_NOT_ALLOWED_IN_FILE_NAMES = set('<>:"/\\|?*')


def run_name(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    """Run `doc-categoriser name <arguments>` and capture its output."""
    return subprocess.run(
        [str(CLI_EXECUTABLE), "name", *(str(argument) for argument in arguments)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_name_writes_a_suggested_name_for_each_extracted_document_mirroring_folders(
    tmp_path: Path,
    test_model_path: Path,
    make_text_pdf: Callable[[str, list[PageLines]], Path],
    make_image: Callable[[str, PageLines], Path],
) -> None:
    input_dir = tmp_path / "inbox"
    (input_dir / "2026").mkdir(parents=True)
    make_text_pdf(
        "scan_0001.pdf",
        [["DBS Bank Statement", "Account 123-456789-0", "Statement period 01/03/2026 - 31/03/2026", "Closing balance 980.40"]],
    ).rename(input_dir / "scan_0001.pdf")
    make_image("IMG_2231.png", ["TAX INVOICE", "Invoice No. INV-2026-0042", "Amount due 312.50"]).rename(
        input_dir / "2026" / "IMG_2231.png"
    )
    extracted_dir = tmp_path / "extracted"
    named_dir = tmp_path / "named"
    assert run_extract(input_dir, extracted_dir).returncode == 0

    result = run_name(extracted_dir, named_dir, "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    statement = json.loads((named_dir / "scan_0001.pdf.json").read_text())
    invoice = json.loads((named_dir / "2026" / "IMG_2231.png.json").read_text())
    assert statement["source_path"] == str((input_dir / "scan_0001.pdf").resolve())
    assert statement["suggested_name"].startswith("2026-03-31-")
    assert statement["document_date"] == "2026-03-31"
    assert statement["suggested_name"].endswith(".pdf")
    assert "statement" in statement["suggested_name"].lower()
    assert not CHARACTERS_NOT_ALLOWED_IN_FILE_NAMES & set(statement["suggested_name"])
    assert not {" ", "_"} & set(statement["suggested_name"] + invoice["suggested_name"])
    assert statement["reason"].strip()
    assert invoice["suggested_name"].startswith("undated-")
    assert invoice["document_date"] is None
    assert invoice["suggested_name"].endswith(".png")
    assert "invoice" in invoice["suggested_name"].lower()
    assert f"Named: scan_0001.pdf.json -> {statement['suggested_name']}" in result.stdout
    assert "Named 2, failed 0" in result.stdout


def test_documents_in_the_same_folder_never_get_the_same_name(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    statement_lines: list[PageLines] = [["DBS Bank Statement", "Statement period 01/03/2026 - 31/03/2026", "Closing balance 980.40"]]
    for file_name in ["copy_a.pdf", "copy_b.pdf", "copy_c.pdf"]:
        make_text_pdf(file_name, statement_lines).rename(input_dir / file_name)
    extracted_dir = tmp_path / "extracted"
    named_dir = tmp_path / "named"
    assert run_extract(input_dir, extracted_dir).returncode == 0

    result = run_name(extracted_dir, named_dir, "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    names = [
        json.loads((named_dir / f"{file_name}.json").read_text())["suggested_name"]
        for file_name in ["copy_a.pdf", "copy_b.pdf", "copy_c.pdf"]
    ]
    first_stem = names[0].removesuffix(".pdf")
    assert names == [f"{first_stem}.pdf", f"{first_stem}-(2).pdf", f"{first_stem}-(3).pdf"]


def test_name_reports_unusable_files_continues_and_exits_non_zero(
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
    named_dir = tmp_path / "named"

    result = run_name(extracted_dir, named_dir, "--model", test_model_path)

    assert result.returncode == 1
    assert sorted(path.name for path in named_dir.rglob("*") if path.is_file()) == ["statement.pdf.json"]
    assert "Failed: a_broken.pdf.json: the file is not an extracted document JSON file" in result.stderr
    assert "Failed: blank_scan.pdf.json: the document has no text" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Named 1, failed 2" in result.stdout


@pytest.mark.parametrize(
    ("problem", "expected_message"),
    [
        ("missing_input_folder", "is not a folder"),
        ("missing_model", "is not a file"),
        ("model_is_not_gguf", "cannot load the model"),
        ("zero_max_document_tokens", "must be 1 or more"),
    ],
)
def test_name_rejects_incorrect_arguments_before_it_reads_any_document(
    tmp_path: Path, test_model_path: Path, problem: str, expected_message: str
) -> None:
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    model_path = test_model_path
    extra_arguments: list[str] = []
    if problem == "missing_input_folder":
        extracted_dir = tmp_path / "does_not_exist"
    elif problem == "missing_model":
        model_path = tmp_path / "missing.gguf"
    elif problem == "model_is_not_gguf":
        model_path = tmp_path / "not_a_model.gguf"
        model_path.write_text("this is not a GGUF file", encoding="utf-8")
    else:
        extra_arguments = ["--max-document-tokens", "0"]

    result = run_name(extracted_dir, tmp_path / "named", "--model", model_path, *extra_arguments)

    assert result.returncode == 2
    assert expected_message in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "named").exists()


def run_rename(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    """Run `doc-categoriser rename <arguments>` and capture its output."""
    return subprocess.run(
        [str(CLI_EXECUTABLE), "rename", *(str(argument) for argument in arguments)],
        capture_output=True,
        text=True,
        check=False,
    )


def write_suggestion(named_dir: Path, relative_json_path: str, source_path: Path, suggested_name: str) -> None:
    """Write a name suggestion JSON file as `doc-categoriser name` writes it."""
    destination = named_dir / relative_json_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "source_path": str(source_path),
                "suggested_name": suggested_name,
                "document_date": None,
                "reason": "test",
            }
        ),
        encoding="utf-8",
    )


def file_names(folder: Path) -> list[str]:
    """Return the sorted relative paths, with `/`, of all files under `folder`."""
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file())


def test_extract_name_and_rename_give_each_document_its_suggested_name(
    tmp_path: Path,
    test_model_path: Path,
    make_text_pdf: Callable[[str, list[PageLines]], Path],
    make_image: Callable[[str, PageLines], Path],
) -> None:
    input_dir = tmp_path / "inbox"
    (input_dir / "2026").mkdir(parents=True)
    make_text_pdf(
        "scan_0001.pdf",
        [["DBS Bank Statement", "Statement period 01/03/2026 - 31/03/2026", "Closing balance 980.40"]],
    ).rename(input_dir / "scan_0001.pdf")
    make_image("IMG_2231.png", ["TAX INVOICE", "Invoice No. INV-2026-0042", "Amount due 312.50"]).rename(
        input_dir / "2026" / "IMG_2231.png"
    )
    statement_bytes = (input_dir / "scan_0001.pdf").read_bytes()
    extracted_dir = tmp_path / "extracted"
    named_dir = tmp_path / "named"
    assert run_extract(input_dir, extracted_dir).returncode == 0
    assert run_name(extracted_dir, named_dir, "--model", test_model_path).returncode == 0
    statement_name = json.loads((named_dir / "scan_0001.pdf.json").read_text())["suggested_name"]
    invoice_name = json.loads((named_dir / "2026" / "IMG_2231.png.json").read_text())["suggested_name"]

    result = run_rename(named_dir)

    assert result.returncode == 0, result.stderr
    assert file_names(input_dir) == sorted([f"inbox-{statement_name}", f"2026/2026-{invoice_name}"])
    assert (input_dir / f"inbox-{statement_name}").read_bytes() == statement_bytes
    assert f"Renamed: scan_0001.pdf.json: scan_0001.pdf -> inbox-{statement_name}" in result.stdout
    assert "Renamed 2, already renamed 0, failed 0" in result.stdout


def test_rename_again_reports_documents_that_already_have_their_names(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    (input_dir / "scan_0001.pdf").write_bytes(b"statement")
    named_dir = tmp_path / "named"
    write_suggestion(named_dir, "scan_0001.pdf.json", input_dir / "scan_0001.pdf", "2026-03-31-DBS-Statement.pdf")
    assert run_rename(named_dir).returncode == 0

    result = run_rename(named_dir)

    assert result.returncode == 0, result.stderr
    assert file_names(input_dir) == ["inbox-2026-03-31-DBS-Statement.pdf"]
    assert "Already renamed: scan_0001.pdf.json: inbox-2026-03-31-DBS-Statement.pdf" in result.stdout
    assert "Renamed 0, already renamed 1, failed 0" in result.stdout


def test_rename_dry_run_changes_no_file(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    (input_dir / "scan_0001.pdf").write_bytes(b"statement")
    named_dir = tmp_path / "named"
    write_suggestion(named_dir, "scan_0001.pdf.json", input_dir / "scan_0001.pdf", "2026-03-31-DBS-Statement.pdf")

    result = run_rename(named_dir, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert file_names(input_dir) == ["scan_0001.pdf"]
    assert "Would rename: scan_0001.pdf.json: scan_0001.pdf -> inbox-2026-03-31-DBS-Statement.pdf" in result.stdout
    assert "Would rename 1, already renamed 0, failed 0" in result.stdout


def test_rename_changes_only_the_case_of_a_name(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    (input_dir / "inbox-statement.pdf").write_bytes(b"statement")
    named_dir = tmp_path / "named"
    write_suggestion(named_dir, "statement.pdf.json", input_dir / "inbox-statement.pdf", "Statement.pdf")

    result = run_rename(named_dir)

    assert result.returncode == 0, result.stderr
    assert file_names(input_dir) == ["inbox-Statement.pdf"]


def test_rename_never_overwrites_a_file_and_reports_each_problem(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    for file_name in ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf", "inbox-taken.pdf", "ok.pdf"]:
        (input_dir / file_name).write_bytes(file_name.encode())
    named_dir = tmp_path / "named"
    write_suggestion(named_dir, "a.pdf.json", input_dir / "a.pdf", "taken.pdf")
    write_suggestion(named_dir, "b.pdf.json", input_dir / "b.pdf", "same.pdf")
    write_suggestion(named_dir, "c.pdf.json", input_dir / "c.pdf", "SAME.pdf")
    write_suggestion(named_dir, "d.pdf.json", input_dir / "d.pdf", "../escaped.pdf")
    write_suggestion(named_dir, "e.pdf.json", input_dir / "e.pdf", "2026-03-31-Statement.png")
    write_suggestion(named_dir, "gone.pdf.json", input_dir / "gone.pdf", "2026-03-31-Gone.pdf")
    write_suggestion(named_dir, "ok.pdf.json", input_dir / "ok.pdf", "2026-03-31-Ok.pdf")
    (named_dir / "broken.pdf.json").write_text("{not json", encoding="utf-8")

    result = run_rename(named_dir)

    assert result.returncode == 1
    assert file_names(input_dir) == sorted(
        ["inbox-2026-03-31-Ok.pdf", "a.pdf", "c.pdf", "d.pdf", "e.pdf", "inbox-same.pdf", "inbox-taken.pdf"]
    )
    assert (input_dir / "inbox-taken.pdf").read_bytes() == b"inbox-taken.pdf"
    assert (input_dir / "inbox-same.pdf").read_bytes() == b"b.pdf"
    assert not (tmp_path / "escaped.pdf").exists()
    assert "Failed: a.pdf.json: a file named inbox-taken.pdf already exists in " in result.stderr
    assert "Failed: c.pdf.json: another document already gets the name inbox-SAME.pdf in " in result.stderr
    assert "Failed: d.pdf.json: the suggested name '../escaped.pdf' is not a valid file name" in result.stderr
    assert "Failed: e.pdf.json: the suggested name changes the file extension from .pdf to .png" in result.stderr
    assert "Failed: gone.pdf.json: the source file " in result.stderr
    assert "Failed: broken.pdf.json: the file is not a name suggestion JSON file" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Renamed 2, already renamed 0, failed 6" in result.stdout


def test_rename_dry_run_reports_two_documents_with_the_same_new_name(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    (input_dir / "b.pdf").write_bytes(b"b")
    (input_dir / "c.pdf").write_bytes(b"c")
    named_dir = tmp_path / "named"
    write_suggestion(named_dir, "b.pdf.json", input_dir / "b.pdf", "same.pdf")
    write_suggestion(named_dir, "c.pdf.json", input_dir / "c.pdf", "same.pdf")

    result = run_rename(named_dir, "--dry-run")

    assert result.returncode == 1
    assert "Failed: c.pdf.json: another document already gets the name inbox-same.pdf in " in result.stderr
    assert "Would rename 1, already renamed 0, failed 1" in result.stdout


def test_rename_puts_the_folder_name_in_front_made_safe_for_file_names(tmp_path: Path) -> None:
    input_dir = tmp_path / "Bank  Statements_2026."
    input_dir.mkdir()
    (input_dir / "scan_0001.pdf").write_bytes(b"statement")
    named_dir = tmp_path / "named"
    write_suggestion(named_dir, "scan_0001.pdf.json", input_dir / "scan_0001.pdf", "2026-03-31-DBS-Statement.pdf")

    result = run_rename(named_dir)

    assert result.returncode == 0, result.stderr
    assert file_names(input_dir) == ["Bank-Statements-2026-2026-03-31-DBS-Statement.pdf"]


def test_rename_rejects_a_missing_folder(tmp_path: Path) -> None:
    result = run_rename(tmp_path / "does_not_exist")

    assert result.returncode == 2
    assert "is not a folder" in result.stderr


def run_pipeline(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    """Run `doc-categoriser run <arguments>` and capture its output."""
    return subprocess.run(
        [str(CLI_EXECUTABLE), "run", *(str(argument) for argument in arguments)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_run_extracts_names_and_renames_and_keeps_the_decisions_in_the_work_folder(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_text_pdf(
        "scan_0001.pdf",
        [["DBS Bank Statement", "Statement period 01/03/2026 - 31/03/2026", "Closing balance 980.40"]],
    ).rename(input_dir / "scan_0001.pdf")
    work_dir = tmp_path / "renaming-decision" / "inbox-run"

    result = run_pipeline(input_dir, work_dir, "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    decision = json.loads((work_dir / "named" / "scan_0001.pdf.json").read_text(encoding="utf-8"))
    assert not (work_dir / "extracted").exists()
    assert decision["source_path"] == str((input_dir / "scan_0001.pdf").resolve())
    assert file_names(input_dir) == [f"inbox-{decision['suggested_name']}"]
    stage_positions = [result.stdout.index(stage) for stage in ["Extraction", "Naming", "Renaming"]]
    assert stage_positions == sorted(stage_positions)
    assert "Extracted 1, skipped 0, failed 0" in result.stdout
    assert "Named 1, failed 0" in result.stdout
    assert "Renamed 1, already renamed 0, failed 0" in result.stdout


def test_run_ignores_its_own_work_folder_inside_the_input_folder(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_text_pdf("statement.pdf", [["DBS Bank Statement", "Closing balance 980.40"]]).rename(input_dir / "statement.pdf")
    work_dir = input_dir / "renaming-decision" / "inbox-run"

    result = run_pipeline(input_dir, work_dir, "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    assert "Extracted 1, skipped 0, failed 0" in result.stdout
    assert sorted(path.name for path in (work_dir / "named").rglob("*.json")) == ["statement.pdf.json"]


def test_run_reports_failed_documents_renames_the_others_and_exits_non_zero(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    (input_dir / "a_broken.pdf").write_bytes(b"this is not a pdf")
    make_text_pdf("statement.pdf", [["DBS Bank Statement", "Closing balance 980.40"]]).rename(input_dir / "statement.pdf")

    result = run_pipeline(input_dir, tmp_path / "work", "--model", test_model_path)

    assert result.returncode == 1
    assert "Failed: a_broken.pdf" in result.stderr
    assert "Renamed 1, already renamed 0, failed 0" in result.stdout
    assert "a_broken.pdf" in file_names(input_dir)
    assert not (tmp_path / "work" / "extracted").exists()


@pytest.mark.parametrize(
    ("problem", "expected_message"),
    [("missing_input_folder", "is not a folder"), ("missing_model", "is not a file")],
)
def test_run_rejects_incorrect_arguments_before_it_changes_anything(
    tmp_path: Path, test_model_path: Path, problem: str, expected_message: str
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    model_path = test_model_path
    if problem == "missing_input_folder":
        input_dir = tmp_path / "does_not_exist"
    else:
        model_path = tmp_path / "missing.gguf"

    result = run_pipeline(input_dir, tmp_path / "work", "--model", model_path)

    assert result.returncode == 2
    assert expected_message in result.stderr
    assert not (tmp_path / "work").exists()
