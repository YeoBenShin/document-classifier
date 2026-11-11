"""
Command-line interface:
`doc-categoriser extract <input_dir> <output_dir>` and
`doc-categoriser classify <extracted_dir> <output_dir> --model <file.gguf>`.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from doc_categoriser.categories import Category, load_categories
from doc_categoriser.classification import DocumentClassifier, classify_document
from doc_categoriser.errors import CategoryFileError, ClassificationError, ExtractionError, UnsupportedFileTypeError
from doc_categoriser.extraction import default_extractors, extract_document
from doc_categoriser.json_output import (
    output_path_for,
    read_document_json,
    write_classification_json,
    write_document_json,
)
from doc_categoriser.llama_classifier import LlamaCppClassifier


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
    """Return the parser for the `extract` and `classify` subcommands and their arguments."""
    parser = argparse.ArgumentParser(prog="doc-categoriser")
    subcommands = parser.add_subparsers(dest="command", required=True)

    extract_command = subcommands.add_parser("extract", help="Extract the text of every document in a folder to JSON files.")
    extract_command.add_argument("input_dir", type=Path, help="Folder with the source documents. Subfolders are included.")
    extract_command.add_argument("output_dir", type=Path, help="Folder for the JSON files. The subfolder structure is kept.")

    classify_command = subcommands.add_parser(
        "classify", help="Classify every extracted document JSON file in a folder with a local GGUF model."
    )
    classify_command.add_argument("input_dir", type=Path, help="Folder with the JSON files written by `extract`.")
    classify_command.add_argument("output_dir", type=Path, help="Folder for the classification JSON files.")
    classify_command.add_argument("--model", type=Path, required=True, help="Path to the GGUF model file.")
    classify_command.add_argument(
        "--categories", type=Path, default=Path("categories.toml"), help="TOML file with the categories (default: %(default)s)."
    )
    classify_command.add_argument(
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


def run_extract(input_dir: Path, output_dir: Path) -> int:
    """
    Extract every file under `input_dir` into JSON files under `output_dir`.
    Unsupported files are skipped. A file that fails is reported and the run continues.
    Return 1 if any file failed, otherwise 0.
    """
    extractors = default_extractors()
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


def run_classify(
    input_dir: Path, output_dir: Path, categories: Sequence[Category], classifier: DocumentClassifier
) -> int:
    """
    Classify every `.json` file under `input_dir` and write one classification JSON file for each under `output_dir`.
    A file that fails is reported and the run continues. Return 1 if any file failed, otherwise 0.
    """
    classified_count = failed_count = 0
    for json_path in (path for path in find_source_files(input_dir) if path.suffix.lower() == ".json"):
        display_name = json_path.relative_to(input_dir)
        try:
            document = read_document_json(json_path)
            classification = classify_document(document, categories, classifier)
        except ClassificationError as error:
            print(f"Failed: {display_name}: {error}", file=sys.stderr, flush=True)
            failed_count += 1
            continue
        except Exception as error:
            print(f"Failed: {display_name}: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            failed_count += 1
            continue
        write_classification_json(document.source_path, classification, output_dir / display_name)
        print(f"Classified: {display_name} -> {classification.category}", flush=True)
        classified_count += 1
    print(f"Classified {classified_count}, failed {failed_count}")
    return 1 if failed_count else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run the chosen subcommand."""
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    if not arguments.input_dir.is_dir():
        parser.error(f"{arguments.input_dir} is not a folder")
    if arguments.command == "extract":
        return run_extract(arguments.input_dir, arguments.output_dir)
    try:
        categories = load_categories(arguments.categories)
    except CategoryFileError as error:
        parser.error(str(error))
    if not arguments.model.is_file():
        parser.error(f"{arguments.model} is not a file")
    try:
        classifier = LlamaCppClassifier(arguments.model, max_document_tokens=arguments.max_document_tokens)
    except ValueError as error:
        parser.error(f"{arguments.model}: cannot load the model ({error})")
    return run_classify(arguments.input_dir, arguments.output_dir, categories, classifier)
