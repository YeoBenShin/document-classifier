"""Behaviour of the `doc-categoriser extract` and `name` commands, run as an operator runs them."""

import hashlib
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


def write_suggestion(
    named_dir: Path, relative_json_path: str, source_path: Path, suggested_name: str, **run_settings: str | None
) -> None:
    """Write a name suggestion JSON file as `doc-categoriser name` writes it. `run_settings`: `method`, `ocr_engine`, `model`."""
    destination = named_dir / relative_json_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "source_path": str(source_path),
                "suggested_name": suggested_name,
                "document_date": None,
                "reason": "test",
                **run_settings,
            }
        ),
        encoding="utf-8",
    )


HISTORY_FILE_NAME = ".doc-categoriser-renames.jsonl"


def read_history_lines(folder: Path) -> list[dict[str, object]]:
    """Return the records of the rename history file of `folder`, in file order."""
    return [json.loads(line) for line in (folder / HISTORY_FILE_NAME).read_text(encoding="utf-8").splitlines()]


def write_history_lines(folder: Path, records: list[dict[str, object]]) -> None:
    """Write `records` as the rename history file of `folder`."""
    (folder / HISTORY_FILE_NAME).write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def test_rename_adds_one_history_line_for_each_rename_in_the_folder_of_the_document(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    (input_dir / "2026").mkdir(parents=True)
    (input_dir / "scan_0001.pdf").write_bytes(b"statement")
    (input_dir / "2026" / "IMG_1.png").write_bytes(b"invoice")
    named_dir = tmp_path / "named"
    write_suggestion(
        named_dir, "scan_0001.pdf.json", input_dir / "scan_0001.pdf", "2026-03-31-Statement.pdf",
        method="text_layer", ocr_engine=None, model="model-a.gguf",
    )
    write_suggestion(
        named_dir, "2026/IMG_1.png.json", input_dir / "2026" / "IMG_1.png", "2026-04-12-Invoice.png",
        method="ocr", ocr_engine="apple-vision", model="model-a.gguf",
    )

    result = run_rename(named_dir)

    assert result.returncode == 0, result.stderr
    [statement_record] = read_history_lines(input_dir)
    [invoice_record] = read_history_lines(input_dir / "2026")
    assert {key: value for key, value in statement_record.items() if key != "renamed_at"} == {
        "original_name": "scan_0001.pdf",
        "new_name": "inbox-2026-03-31-Statement.pdf",
        "sha256": hashlib.sha256(b"statement").hexdigest(),
        "method": "text_layer",
        "ocr_engine": None,
        "model": "model-a.gguf",
    }
    assert {key: value for key, value in invoice_record.items() if key != "renamed_at"} == {
        "original_name": "IMG_1.png",
        "new_name": "2026-2026-04-12-Invoice.png",
        "sha256": hashlib.sha256(b"invoice").hexdigest(),
        "method": "ocr",
        "ocr_engine": "apple-vision",
        "model": "model-a.gguf",
    }
    assert str(statement_record["renamed_at"])[:4].isdigit() and "T" in str(statement_record["renamed_at"])


def test_rename_again_adds_no_history_line_and_dry_run_writes_no_history(tmp_path: Path) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    (input_dir / "scan_0001.pdf").write_bytes(b"statement")
    named_dir = tmp_path / "named"
    write_suggestion(
        named_dir, "scan_0001.pdf.json", input_dir / "scan_0001.pdf", "2026-03-31-Statement.pdf",
        method="text_layer", ocr_engine=None, model="model-a.gguf",
    )

    assert run_rename(named_dir, "--dry-run").returncode == 0
    assert not (input_dir / HISTORY_FILE_NAME).exists()
    assert run_rename(named_dir).returncode == 0
    assert run_rename(named_dir).returncode == 0

    assert len(read_history_lines(input_dir)) == 1


def file_names(folder: Path) -> list[str]:
    """Return the sorted relative paths, with `/`, of all non-hidden files under `folder`."""
    return sorted(
        path.relative_to(folder).as_posix()
        for path in folder.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    )


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


def test_run_extracts_names_and_renames_then_deletes_its_work_folder(
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
    assert not work_dir.exists()
    assert (tmp_path / "renaming-decision").is_dir()
    [new_name] = file_names(input_dir)
    assert new_name.startswith("inbox-") and new_name.endswith(".pdf")
    assert f"Renamed: scan_0001.pdf.json: scan_0001.pdf -> {new_name}" in result.stdout
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
    assert "Named 1, failed 0" in result.stdout
    assert not work_dir.exists()


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
    assert not (tmp_path / "work").exists()


def test_run_keeps_other_files_in_its_work_folder(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_text_pdf("statement.pdf", [["DBS Bank Statement", "Closing balance 980.40"]]).rename(input_dir / "statement.pdf")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "notes.txt").write_text("keep", encoding="utf-8")

    result = run_pipeline(input_dir, work_dir, "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in work_dir.iterdir()) == ["notes.txt"]


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


def test_run_again_leaves_out_the_documents_its_rename_history_shows_as_done(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_text_pdf("statement.pdf", [["DBS Bank Statement", "Closing balance 980.40"]]).rename(input_dir / "statement.pdf")
    assert run_pipeline(input_dir, tmp_path / "work", "--model", test_model_path).returncode == 0
    [new_name] = file_names(input_dir)
    [record] = read_history_lines(input_dir)
    assert (record["original_name"], record["new_name"]) == ("statement.pdf", new_name)
    assert (record["method"], record["ocr_engine"], record["model"]) == ("text_layer", None, test_model_path.name)

    result = run_pipeline(input_dir, tmp_path / "work", "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    assert f"Already renamed (rename history): {new_name}" in result.stdout
    assert "To process 0, already renamed 1" in result.stdout
    assert "Extracted 0, skipped 0, failed 0" in result.stdout
    assert file_names(input_dir) == [new_name]
    assert len(read_history_lines(input_dir)) == 1


def test_run_creates_an_empty_rename_history_in_each_folder_with_files(
    tmp_path: Path, test_model_path: Path
) -> None:
    input_dir = tmp_path / "inbox"
    (input_dir / "2026").mkdir(parents=True)
    (input_dir / "notes.txt").write_text("not a document", encoding="utf-8")
    (input_dir / "2026" / "notes.txt").write_text("not a document", encoding="utf-8")

    result = run_pipeline(input_dir, tmp_path / "work", "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    assert (input_dir / HISTORY_FILE_NAME).read_text(encoding="utf-8") == ""
    assert (input_dir / "2026" / HISTORY_FILE_NAME).read_text(encoding="utf-8") == ""


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of the content of `path`, as lowercase hex."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def history_record(path: Path, **fields: object) -> dict[str, object]:
    """Return a history record for the file at `path` with its SHA-256. `fields` replace the default values."""
    return {
        "original_name": "x.pdf",
        "new_name": path.name,
        "sha256": file_sha256(path),
        "renamed_at": "2026-01-01T00:00:00+00:00",
        "method": "text_layer",
        "ocr_engine": None,
        "model": "model.gguf",
        **fields,
    }


def test_run_matches_documents_to_the_history_by_content_not_by_name(
    tmp_path: Path,
    test_model_path: Path,
    make_text_pdf: Callable[[str, list[PageLines]], Path],
    make_image: Callable[[str, PageLines], Path],
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    statement_lines = ["DBS Bank Statement", "Closing balance 980.40"]
    make_text_pdf("a.pdf", [statement_lines]).rename(input_dir / "renamed-by-hand.pdf")
    make_text_pdf("b.pdf", [statement_lines + ["Account 2"]]).rename(input_dir / "other-model.pdf")
    make_image("c.png", ["TAX INVOICE", "Amount due 312.50"]).rename(input_dir / "other-ocr.png")
    make_text_pdf("d.pdf", [statement_lines + ["Account 4"]]).rename(input_dir / "not-in-history.pdf")
    make_text_pdf("e.pdf", [statement_lines + ["Account 5"]]).rename(input_dir / "same-name-new-content.pdf")
    other_ocr_engine = "windows" if sys.platform == "darwin" else "apple-vision"
    model = test_model_path.name
    write_history_lines(
        input_dir,
        [
            history_record(
                input_dir / "renamed-by-hand.pdf", new_name="inbox-old-name.pdf", model=model, ocr_engine=other_ocr_engine
            ),
            history_record(input_dir / "other-model.pdf", model="other.gguf"),
            history_record(input_dir / "other-ocr.png", method="ocr", ocr_engine=other_ocr_engine, model=model),
            history_record(input_dir / "same-name-new-content.pdf", sha256="0" * 64, model=model),
        ],
    )

    result = run_pipeline(input_dir, tmp_path / "work", "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    assert "Already renamed (rename history): renamed-by-hand.pdf" in result.stdout
    assert "To process 4, already renamed 1" in result.stdout
    for processed_name in ["other-model.pdf", "other-ocr.png", "not-in-history.pdf", "same-name-new-content.pdf"]:
        assert f"Extracted: {processed_name}" in result.stdout
    assert "renamed-by-hand.pdf" in file_names(input_dir)
    records = read_history_lines(input_dir)
    assert [record["new_name"] for record in records[:3]] == ["inbox-old-name.pdf", "other-model.pdf", "other-ocr.png"]
    assert sorted(str(record["original_name"]) for record in records[3:]) == sorted(
        ["other-model.pdf", "other-ocr.png", "not-in-history.pdf", "same-name-new-content.pdf"]
    )
    assert all(record["model"] == model for record in records[3:])


def test_run_removes_history_lines_that_match_no_file_of_the_folder(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_text_pdf("a.pdf", [["DBS Bank Statement", "Closing balance 980.40"]]).rename(input_dir / "kept.pdf")
    kept_record = history_record(input_dir / "kept.pdf", model=test_model_path.name)
    deleted_record = history_record(input_dir / "kept.pdf", new_name="deleted.pdf", sha256="0" * 64)
    (input_dir / HISTORY_FILE_NAME).write_text(
        json.dumps(deleted_record) + "\n{not json\n" + json.dumps(kept_record) + "\n", encoding="utf-8"
    )

    result = run_pipeline(input_dir, tmp_path / "work", "--model", test_model_path)

    assert result.returncode == 0, result.stderr
    assert "Removed from rename history (no file with this content): deleted.pdf" in result.stdout
    assert "Already renamed (rename history): kept.pdf" in result.stdout
    assert read_history_lines(input_dir) == [kept_record]


def test_run_stops_before_any_change_when_two_documents_of_a_folder_have_the_same_content(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    (input_dir / "2026").mkdir(parents=True)
    statement = make_text_pdf("a.pdf", [["DBS Bank Statement", "Closing balance 980.40"]])
    (input_dir / "statement.pdf").write_bytes(statement.read_bytes())
    (input_dir / "statement copy.pdf").write_bytes(statement.read_bytes())
    (input_dir / "2026" / "statement.pdf").write_bytes(statement.read_bytes())
    (input_dir / "notes.txt").write_text("same", encoding="utf-8")
    (input_dir / "notes copy.txt").write_text("same", encoding="utf-8")

    result = run_pipeline(input_dir, tmp_path / "work", "--model", test_model_path)

    assert result.returncode == 3
    assert (
        "Duplicate: these files in one folder have the same content: statement copy.pdf, statement.pdf" in result.stderr
    )
    assert "2026" not in result.stderr
    assert "notes" not in result.stderr
    assert "Stopped: no file was changed." in result.stderr
    assert "== Stage 1" not in result.stdout
    assert file_names(input_dir) == sorted(
        ["2026/statement.pdf", "notes copy.txt", "notes.txt", "statement copy.pdf", "statement.pdf"]
    )
    assert not (input_dir / HISTORY_FILE_NAME).exists()
    assert not (tmp_path / "work").exists()
