"""
Command-line interface:
`doc-categoriser extract [--ocr-engine NAME] <input_dir> <output_dir>` and
`doc-categoriser name <extracted_dir> <output_dir> --model <file.gguf>` and
`doc-categoriser rename [--dry-run] <named_dir>` and
`doc-categoriser run <input_dir> <work_dir> --model <file.gguf>` (all three stages) and
`doc-categoriser web [root_dir]` (browser interface that queues `run` for folders).
"""

import argparse
import shutil
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from doc_categoriser.classification import DocumentNamer, LlamaCppNamer, suggest_document_name, unique_name
from doc_categoriser.errors import (
    ExtractionError,
    NamingError,
    OcrEngineUnavailableError,
    RenamingError,
    UnsupportedFileTypeError,
)
from doc_categoriser.extraction import DocumentExtractor, default_extractors, extract_document
from doc_categoriser.json_output import (
    output_path_for,
    read_document_json,
    read_name_suggestion_json,
    write_document_json,
    write_name_suggestion_json,
)
from doc_categoriser.extraction.ocr import OcrEngineName, create_ocr_engine, native_ocr_engine_name
from doc_categoriser.renaming import RenameOutcome, name_with_folder, rename_document


def positive_integer(text: str) -> int:
    """Return `text` as an integer. Raise argparse.ArgumentTypeError if it is not a whole number of 1 or more."""
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from error
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not allowed: the value must be 1 or more")
    return value


def add_ocr_engine_argument(command: argparse.ArgumentParser) -> None:
    """Add the `--ocr-engine` option to `command`."""
    command.add_argument(
        "--ocr-engine",
        choices=[engine_name.value for engine_name in OcrEngineName],
        default=None,
        help="OCR engine for scanned pages and images. Default: the engine of this operating system "
        "(apple-vision on macOS, windows on Windows).",
    )


def add_model_arguments(command: argparse.ArgumentParser) -> None:
    """Add the required `--model` option and the `--max-document-tokens` option to `command`."""
    command.add_argument("--model", type=Path, required=True, help="Path to the GGUF model file.")
    command.add_argument(
        "--max-document-tokens",
        type=positive_integer,
        default=1024,
        help="Only the first this many tokens of each document are read (default: %(default)s). Lower is faster.",
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Return the parser for the `extract`, `name`, `rename`, `run` and `web` subcommands and their arguments."""
    parser = argparse.ArgumentParser(prog="doc-categoriser")
    subcommands = parser.add_subparsers(dest="command", required=True)

    extract_command = subcommands.add_parser("extract", help="Extract the text of every document in a folder to JSON files.")
    extract_command.add_argument("input_dir", type=Path, help="Folder with the source documents. Subfolders are included.")
    extract_command.add_argument("output_dir", type=Path, help="Folder for the JSON files. The subfolder structure is kept.")
    add_ocr_engine_argument(extract_command)

    name_command = subcommands.add_parser(
        "name", help="Suggest a file name from the content of every extracted document, with a local GGUF model."
    )
    name_command.add_argument("input_dir", type=Path, help="Folder with the JSON files written by `extract`.")
    name_command.add_argument("output_dir", type=Path, help="Folder for the name suggestion JSON files.")
    add_model_arguments(name_command)

    rename_command = subcommands.add_parser(
        "rename", help="Rename every source document to the name suggested by `name`, in the folder where it is."
    )
    rename_command.add_argument("input_dir", type=Path, help="Folder with the JSON files written by `name`.")
    rename_command.add_argument(
        "--dry-run", action="store_true", help="Show what would be renamed, and change no file."
    )

    run_command = subcommands.add_parser(
        "run", help="Run extract, name and rename on a folder, one stage after the other."
    )
    run_command.add_argument("input_dir", type=Path, help="Folder with the source documents. Subfolders are included.")
    run_command.add_argument(
        "work_dir",
        type=Path,
        help="Folder for the stage output: `extracted/` (extracted JSON) and `named/` (name suggestion JSON).",
    )
    add_ocr_engine_argument(run_command)
    add_model_arguments(run_command)

    web_command = subcommands.add_parser(
        "web", help="Open a browser interface to queue folders for the full pipeline (extract, name, rename)."
    )
    web_command.add_argument(
        "input_dir",
        type=Path,
        nargs="?",
        default=Path.cwd(),
        help="Folder the interface opens at (default: the current folder).",
    )
    web_command.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "renaming-decision",
        help="Default folder for the stage output of each run (default: %(default)s). Can be changed in the interface.",
    )
    web_command.add_argument(
        "--model",
        type=Path,
        default=Path.cwd() / "models" / "Qwen3.5-4B-Q4_K_M.gguf",
        help="Default GGUF model file (default: %(default)s). Can be changed in the interface.",
    )
    web_command.add_argument("--host", default="127.0.0.1", help="Address to listen on (default: %(default)s).")
    web_command.add_argument("--port", type=int, default=8765, help="Port to listen on (default: %(default)s). 0 picks a free port.")
    web_command.add_argument("--no-browser", action="store_true", help="Do not open the interface in a web browser.")
    return parser


def is_hidden(path: Path, root: Path) -> bool:
    """Return True if any part of `path` below `root` starts with a dot, such as .DS_Store or .git."""
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def find_source_files(input_dir: Path, excluded_dir: Path | None = None) -> list[Path]:
    """Return every non-hidden file under `input_dir` in sorted order. Files under `excluded_dir` are left out."""
    resolved_excluded_dir = excluded_dir.resolve() if excluded_dir else None
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file()
        and not is_hidden(path, input_dir)
        and not (resolved_excluded_dir and path.resolve().is_relative_to(resolved_excluded_dir))
    )


def run_extract(
    input_dir: Path, output_dir: Path, extractors: list[DocumentExtractor], excluded_dir: Path | None = None
) -> int:
    """
    Extract every file under `input_dir`, except the files under `excluded_dir`, into JSON files under `output_dir`.
    Unsupported files are skipped. A file that fails is reported and the run continues.
    Return 1 if any file failed, otherwise 0.
    """
    extracted_count = skipped_count = failed_count = 0
    for source_path in find_source_files(input_dir, excluded_dir):
        display_name = source_path.relative_to(input_dir)
        try:
            document = extract_document(source_path, extractors)
        except UnsupportedFileTypeError:
            print(f"Skipped (unsupported type): {display_name}")
            skipped_count += 1
            continue
        except ExtractionError as error:
            print(f"Failed: {display_name}: {error}", file=sys.stderr, flush=True)
            failed_count += 1
            continue
        except Exception as error:
            print(f"Failed: {display_name}: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            failed_count += 1
            continue
        write_document_json(document, output_path_for(source_path, input_dir, output_dir))
        print(f"Extracted: {display_name}", flush=True)
        extracted_count += 1
    print(f"Extracted {extracted_count}, skipped {skipped_count}, failed {failed_count}", flush=True)
    return 1 if failed_count else 0


def run_name(input_dir: Path, output_dir: Path, namer: DocumentNamer) -> int:
    """
    Suggest a name for every `.json` file under `input_dir` and write one name suggestion JSON file for each under `output_dir`.
    Documents from the same folder never get the same name. A file that fails is reported and the run continues.
    Return 1 if any file failed, otherwise 0.
    """
    named_count = failed_count = 0
    names_in_use_by_folder: dict[Path, set[str]] = {}
    for json_path in (path for path in find_source_files(input_dir) if path.suffix.lower() == ".json"):
        display_name = json_path.relative_to(input_dir)
        try:
            document = read_document_json(json_path)
            suggestion = suggest_document_name(document, namer)
        except NamingError as error:
            print(f"Failed: {display_name}: {error}", file=sys.stderr, flush=True)
            failed_count += 1
            continue
        except Exception as error:
            print(f"Failed: {display_name}: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            failed_count += 1
            continue
        names_in_use = names_in_use_by_folder.setdefault(display_name.parent, set())
        suggestion = replace(suggestion, name=unique_name(suggestion.name, names_in_use))
        write_name_suggestion_json(document.source_path, suggestion, output_dir / display_name)
        print(f"Named: {display_name} -> {suggestion.name}", flush=True)
        named_count += 1
    print(f"Named {named_count}, failed {failed_count}", flush=True)
    return 1 if failed_count else 0


def run_rename(input_dir: Path, dry_run: bool) -> int:
    """
    Rename the source document of every `.json` file under `input_dir` to `<folder>-<suggested name>`, in the folder where it is.
    With `dry_run`, change no file. No file is overwritten, and no two documents get the same new name in one folder.
    A file that fails is reported and the run continues. Return 1 if any file failed, otherwise 0.
    """
    renamed_label = "Would rename" if dry_run else "Renamed"
    renamed_count = already_renamed_count = failed_count = 0
    new_names_in_use: set[tuple[Path, str]] = set()
    for json_path in (path for path in find_source_files(input_dir) if path.suffix.lower() == ".json"):
        display_name = json_path.relative_to(input_dir)
        try:
            source_path, suggested_name = read_name_suggestion_json(json_path)
            new_name = name_with_folder(source_path, suggested_name)
            new_name_key = (source_path.parent, new_name.lower())
            if new_name_key in new_names_in_use:
                raise RenamingError(f"another document already gets the name {new_name} in {source_path.parent}")
            outcome = rename_document(source_path, new_name, dry_run=dry_run)
        except RenamingError as error:
            print(f"Failed: {display_name}: {error}", file=sys.stderr, flush=True)
            failed_count += 1
            continue
        except Exception as error:
            print(f"Failed: {display_name}: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            failed_count += 1
            continue
        new_names_in_use.add(new_name_key)
        if outcome is RenameOutcome.ALREADY_RENAMED:
            print(f"Already renamed: {display_name}: {new_name}", flush=True)
            already_renamed_count += 1
        else:
            print(f"{renamed_label}: {display_name}: {source_path.name} -> {new_name}", flush=True)
            renamed_count += 1
    print(f"{renamed_label} {renamed_count}, already renamed {already_renamed_count}, failed {failed_count}", flush=True)
    return 1 if failed_count else 0


def run_pipeline(input_dir: Path, work_dir: Path, extractors: list[DocumentExtractor], namer: DocumentNamer) -> int:
    """
    Run extraction into `<work_dir>/extracted`, naming into `<work_dir>/named`, then renaming, one stage after the other.
    When the renaming stage has finished, `<work_dir>/extracted` is deleted. Files under `work_dir` are not extracted. A failed document does not stop the run: the next stages use the documents
    that did not fail. Return 1 if any document failed in any stage, otherwise 0.
    """
    extracted_dir = work_dir / "extracted"
    named_dir = work_dir / "named"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    named_dir.mkdir(parents=True, exist_ok=True)
    print(f"== Stage 1 of 3: Extraction: {input_dir.resolve()} -> {extracted_dir.resolve()}", flush=True)
    extract_status = run_extract(input_dir, extracted_dir, extractors, excluded_dir=work_dir)
    print(f"== Stage 2 of 3: Naming: {extracted_dir.resolve()} -> {named_dir.resolve()}", flush=True)
    name_status = run_name(extracted_dir, named_dir, namer)
    print(f"== Stage 3 of 3: Renaming: {named_dir.resolve()}", flush=True)
    rename_status = run_rename(named_dir, dry_run=False)
    shutil.rmtree(extracted_dir)
    print(f"Deleted the extracted JSON files: {extracted_dir.resolve()}", flush=True)
    return max(extract_status, name_status, rename_status)


def create_extractors_or_exit(parser: argparse.ArgumentParser, engine_option: str | None) -> list[DocumentExtractor]:
    """Return the default extractors with the OCR engine of `engine_option`. Exit with code 2 if the engine is unavailable."""
    try:
        ocr_engine = create_ocr_engine(OcrEngineName(engine_option) if engine_option else native_ocr_engine_name())
    except OcrEngineUnavailableError as error:
        parser.error(str(error))
    return default_extractors(ocr_engine)


def load_namer_or_exit(parser: argparse.ArgumentParser, model_path: Path, max_document_tokens: int) -> LlamaCppNamer:
    """Return a namer with the GGUF model at `model_path`. Exit with code 2 if the file is missing or cannot load."""
    if not model_path.is_file():
        parser.error(f"{model_path} is not a file")
    try:
        return LlamaCppNamer(model_path, max_document_tokens=max_document_tokens)
    except ValueError as error:
        parser.error(f"{model_path}: cannot load the model ({error})")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run the chosen subcommand."""
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    if not arguments.input_dir.is_dir():
        parser.error(f"{arguments.input_dir} is not a folder")
    if arguments.command == "extract":
        extractors = create_extractors_or_exit(parser, arguments.ocr_engine)
        return run_extract(arguments.input_dir, arguments.output_dir, extractors)
    if arguments.command == "rename":
        return run_rename(arguments.input_dir, arguments.dry_run)
    if arguments.command == "web":
        from doc_categoriser.webui import serve_web_ui

        return serve_web_ui(
            root_dir=arguments.input_dir,
            default_output_dir=arguments.output_dir,
            default_model_path=arguments.model,
            host=arguments.host,
            port=arguments.port,
            open_browser=not arguments.no_browser,
        )
    if arguments.command == "run":
        extractors = create_extractors_or_exit(parser, arguments.ocr_engine)
        namer = load_namer_or_exit(parser, arguments.model, arguments.max_document_tokens)
        return run_pipeline(arguments.input_dir, arguments.work_dir, extractors, namer)
    namer = load_namer_or_exit(parser, arguments.model, arguments.max_document_tokens)
    return run_name(arguments.input_dir, arguments.output_dir, namer)
