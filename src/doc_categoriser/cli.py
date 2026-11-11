"""Command-line interface: `doc-categoriser extract <input_dir> <output_dir>`."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from doc_categoriser.extraction import UnsupportedFileTypeError, default_extractors, extract_document
from doc_categoriser.json_output import output_path_for, write_document_json


def build_argument_parser() -> argparse.ArgumentParser:
    """Return the parser for the `extract` subcommand and its arguments."""
    parser = argparse.ArgumentParser(prog="doc-categoriser")
    subcommands = parser.add_subparsers(dest="command", required=True)
    extract_command = subcommands.add_parser("extract", help="Extract the text of every document in a folder to JSON files.")
    extract_command.add_argument("input_dir", type=Path, help="Folder with the source documents. Subfolders are included.")
    extract_command.add_argument("output_dir", type=Path, help="Folder for the JSON files. The subfolder structure is kept.")
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
        except Exception as error:
            print(f"Failed: {display_name}: {type(error).__name__}: {error}", file=sys.stderr)
            failed_count += 1
            continue
        write_document_json(document, output_path_for(source_path, input_dir, output_dir))
        print(f"Extracted: {display_name}")
        extracted_count += 1
    print(f"Extracted {extracted_count}, skipped {skipped_count}, failed {failed_count}")
    return 1 if failed_count else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run the chosen subcommand."""
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    if not arguments.input_dir.is_dir():
        parser.error(f"{arguments.input_dir} is not a folder")
    return run_extract(arguments.input_dir, arguments.output_dir)
