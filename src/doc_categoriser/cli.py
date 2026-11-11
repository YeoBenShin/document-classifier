"""
Command-line interface:
`doc-categoriser extract [--ocr-engine NAME] <input_dir> <output_dir>` and
`doc-categoriser name <extracted_dir> <output_dir> --model <file.gguf>`.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from doc_categoriser.errors import ExtractionError, NamingError, OcrEngineUnavailableError, UnsupportedFileTypeError
from doc_categoriser.extraction import DocumentExtractor, default_extractors, extract_document
from doc_categoriser.json_output import (
    output_path_for,
    read_document_json,
    write_document_json,
    write_name_suggestion_json,
)
from doc_categoriser.llama_namer import LlamaCppNamer
from doc_categoriser.naming import DocumentNamer, suggest_document_name, unique_name
from doc_categoriser.ocr import OcrEngineName, create_ocr_engine, native_ocr_engine_name


def positive_integer(text: str) -> int:
    """Return `text` as an integer. Raise argparse.ArgumentTypeError if it is not a whole number of 1 or more."""
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from error
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not allowed: the value must be 1 or more")
    return value


def build_argument_parser() -> argparse.ArgumentParser:
    """Return the parser for the `extract` and `name` subcommands and their arguments."""
    parser = argparse.ArgumentParser(prog="doc-categoriser")
    subcommands = parser.add_subparsers(dest="command", required=True)

    extract_command = subcommands.add_parser("extract", help="Extract the text of every document in a folder to JSON files.")
    extract_command.add_argument("input_dir", type=Path, help="Folder with the source documents. Subfolders are included.")
    extract_command.add_argument("output_dir", type=Path, help="Folder for the JSON files. The subfolder structure is kept.")
    extract_command.add_argument(
        "--ocr-engine",
        choices=[engine_name.value for engine_name in OcrEngineName],
        default=None,
        help="OCR engine for scanned pages and images. Default: the engine of this operating system "
        "(apple-vision on macOS, windows on Windows).",
    )

    name_command = subcommands.add_parser(
        "name", help="Suggest a file name from the content of every extracted document, with a local GGUF model."
    )
    name_command.add_argument("input_dir", type=Path, help="Folder with the JSON files written by `extract`.")
    name_command.add_argument("output_dir", type=Path, help="Folder for the name suggestion JSON files.")
    name_command.add_argument("--model", type=Path, required=True, help="Path to the GGUF model file.")
    name_command.add_argument(
        "--max-document-tokens",
        type=positive_integer,
        default=1024,
        help="Only the first this many tokens of each document are read (default: %(default)s). Lower is faster.",
    )
    return parser


def is_hidden(path: Path, root: Path) -> bool:
    """Return True if any part of `path` below `root` starts with a dot, such as .DS_Store or .git."""
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def find_source_files(input_dir: Path) -> list[Path]:
    """Return every non-hidden file under `input_dir` in sorted order."""
    return sorted(path for path in input_dir.rglob("*") if path.is_file() and not is_hidden(path, input_dir))


def run_extract(input_dir: Path, output_dir: Path, extractors: list[DocumentExtractor]) -> int:
    """
    Extract every file under `input_dir` into JSON files under `output_dir`.
    Unsupported files are skipped. A file that fails is reported and the run continues.
    Return 1 if any file failed, otherwise 0.
    """
    extracted_count = skipped_count = failed_count = 0
    for source_path in find_source_files(input_dir):
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
    print(f"Extracted {extracted_count}, skipped {skipped_count}, failed {failed_count}")
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
    print(f"Named {named_count}, failed {failed_count}")
    return 1 if failed_count else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run the chosen subcommand."""
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    if not arguments.input_dir.is_dir():
        parser.error(f"{arguments.input_dir} is not a folder")
    if arguments.command == "extract":
        try:
            ocr_engine = create_ocr_engine(
                OcrEngineName(arguments.ocr_engine) if arguments.ocr_engine else native_ocr_engine_name()
            )
        except OcrEngineUnavailableError as error:
            parser.error(str(error))
        return run_extract(arguments.input_dir, arguments.output_dir, default_extractors(ocr_engine))
    if not arguments.model.is_file():
        parser.error(f"{arguments.model} is not a file")
    try:
        namer = LlamaCppNamer(arguments.model, max_document_tokens=arguments.max_document_tokens)
    except ValueError as error:
        parser.error(f"{arguments.model}: cannot load the model ({error})")
    return run_name(arguments.input_dir, arguments.output_dir, namer)
