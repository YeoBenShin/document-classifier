"""
Command-line interface:
`doc-categoriser extract [--ocr-engine NAME] <input_dir> <output_dir>` and
`doc-categoriser name <extracted_dir> <output_dir> --model <file.gguf>` and
`doc-categoriser rename [--dry-run] <named_dir>` and
`doc-categoriser run <input_dir> <work_dir> --model <file.gguf>` (all three stages) and
`doc-categoriser web [root_dir]` (browser interface that queues `run` for folders).
"""

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
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
from doc_categoriser.models import ExtractedDocument, ExtractionMethod
from doc_categoriser.renaming import (
    OCR_METHOD,
    TEXT_LAYER_METHOD,
    RenameOutcome,
    RenameRecord,
    append_history,
    current_time_text,
    ensure_history_file,
    file_sha256,
    is_done,
    last_record_by_hash,
    name_with_folder,
    read_history,
    rename_document,
    write_history,
)

DUPLICATE_DOCUMENTS_EXIT_CODE = 3
"""Exit code of `run` when two or more documents in one folder have the same content. The run stops before any change."""


@dataclass(frozen=True)
class StageCounts:
    """The number of documents of one stage that were done, skipped and failed."""

    done: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def exit_code(self) -> int:
        """Return 1 if one or more documents failed, otherwise 0."""
        return 1 if self.failed else 0


@dataclass(frozen=True)
class RunSummary:
    """
    The document counts of one `run`, as written to `--summary-file`. `processed`: documents that have their new name
    at the end (renamed, or already renamed at the rename stage). `skipped_already_renamed`: documents left out by the
    rename history. `skipped_unsupported`: files of an unsupported type. `failed`: documents that failed in any stage.
    """

    processed: int
    skipped_already_renamed: int
    skipped_unsupported: int
    failed: int


def write_run_summary(summary_path: Path | None, summary: RunSummary) -> None:
    """Write `summary` as JSON to `summary_path`. Do nothing if `summary_path` is None."""
    if summary_path is None:
        return
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(asdict(summary), indent=2) + "\n", encoding="utf-8")


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
        help="Folder for the stage output during the run: `extracted/` (extracted JSON) and `named/` (name suggestion JSON). Deleted when the renaming has finished.",
    )
    add_ocr_engine_argument(run_command)
    add_model_arguments(run_command)
    run_command.add_argument(
        "--summary-file",
        type=Path,
        default=None,
        help="Write the document counts of the run (processed, skipped, failed) to this JSON file at the end.",
    )

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
    input_dir: Path,
    output_dir: Path,
    extractors: list[DocumentExtractor],
    ocr_engine: str,
    source_files: list[Path] | None = None,
) -> StageCounts:
    """
    Extract each file of `source_files` (default: every file under `input_dir`) into JSON files under `output_dir`.
    Each JSON file records `ocr_engine` as the OCR engine. Unsupported files are skipped.
    A file that fails is reported and the run continues. Return the counts of extracted, skipped and failed files.
    """
    extracted_count = skipped_count = failed_count = 0
    for source_path in find_source_files(input_dir) if source_files is None else source_files:
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
        write_document_json(replace(document, ocr_engine=ocr_engine), output_path_for(source_path, input_dir, output_dir))
        print(f"Extracted: {display_name}", flush=True)
        extracted_count += 1
    print(f"Extracted {extracted_count}, skipped {skipped_count}, failed {failed_count}", flush=True)
    return StageCounts(done=extracted_count, skipped=skipped_count, failed=failed_count)


def extraction_method(document: ExtractedDocument) -> str:
    """Return `ocr` if the text of one or more pages of `document` came from OCR, otherwise `text_layer`."""
    if any(page.method is ExtractionMethod.OCR for page in document.pages):
        return OCR_METHOD
    return TEXT_LAYER_METHOD


def run_name(input_dir: Path, output_dir: Path, namer: DocumentNamer, model_name: str) -> StageCounts:
    """
    Suggest a name for every `.json` file under `input_dir` and write one name suggestion JSON file for each under `output_dir`.
    Each name suggestion JSON file records the extraction method, the OCR engine (only for the `ocr` method) and `model_name`.
    Documents from the same folder never get the same name. A file that fails is reported and the run continues.
    Return the counts of named and failed files.
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
        method = extraction_method(document)
        write_name_suggestion_json(
            document.source_path,
            suggestion,
            output_dir / display_name,
            method=method,
            ocr_engine=document.ocr_engine if method == OCR_METHOD else None,
            model=model_name,
        )
        print(f"Named: {display_name} -> {suggestion.name}", flush=True)
        named_count += 1
    print(f"Named {named_count}, failed {failed_count}", flush=True)
    return StageCounts(done=named_count, failed=failed_count)


def run_rename(input_dir: Path, dry_run: bool) -> StageCounts:
    """
    Rename the source document of every `.json` file under `input_dir` to `<folder>-<suggested name>`, in the folder where it is.
    With `dry_run`, change no file. No file is overwritten, and no two documents get the same new name in one folder.
    Each rename adds a line to the rename history of the folder, with the SHA-256 of the file. A document found already renamed
    adds a line only if the last line for its SHA-256 has another new name, method, OCR engine or model. With `dry_run`, no line is added.
    A file that fails is reported and the run continues. Return the counts: `done` holds the renamed and the already
    renamed documents, `skipped` the already renamed documents only.
    """
    renamed_label = "Would rename" if dry_run else "Renamed"
    renamed_count = already_renamed_count = failed_count = 0
    new_names_in_use: set[tuple[Path, str]] = set()
    for json_path in (path for path in find_source_files(input_dir) if path.suffix.lower() == ".json"):
        display_name = json_path.relative_to(input_dir)
        try:
            suggestion = read_name_suggestion_json(json_path)
            source_path = suggestion.source_path
            new_name = name_with_folder(source_path, suggestion.suggested_name)
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
        if not dry_run:
            record = RenameRecord(
                original_name=source_path.name,
                new_name=new_name,
                sha256=file_sha256(source_path.with_name(new_name)),
                renamed_at=current_time_text(),
                method=suggestion.method,
                ocr_engine=suggestion.ocr_engine,
                model=suggestion.model,
            )
            records, _ = read_history(source_path.parent)
            last_record = last_record_by_hash(records).get(record.sha256)
            if outcome is RenameOutcome.RENAMED or not _same_result(last_record, record):
                append_history(source_path.parent, record)
        if outcome is RenameOutcome.ALREADY_RENAMED:
            print(f"Already renamed: {display_name}: {new_name}", flush=True)
            already_renamed_count += 1
        else:
            print(f"{renamed_label}: {display_name}: {source_path.name} -> {new_name}", flush=True)
            renamed_count += 1
    print(f"{renamed_label} {renamed_count}, already renamed {already_renamed_count}, failed {failed_count}", flush=True)
    return StageCounts(done=renamed_count + already_renamed_count, skipped=already_renamed_count, failed=failed_count)


def _same_result(last_record: RenameRecord | None, record: RenameRecord) -> bool:
    """Return True if `last_record` exists and has the new name, method, OCR engine and model of `record`."""
    return last_record is not None and (
        last_record.new_name,
        last_record.method,
        last_record.ocr_engine,
        last_record.model,
    ) == (record.new_name, record.method, record.ocr_engine, record.model)


def hash_documents(source_files: list[Path], supported_suffixes: set[str]) -> dict[Path, str]:
    """
    Return the SHA-256 of each file of `source_files` whose lowercase suffix is in `supported_suffixes`.
    A file that cannot be read is left out, so that extraction reports it.
    """
    hashes: dict[Path, str] = {}
    for source_path in source_files:
        if source_path.suffix.lower() not in supported_suffixes:
            continue
        try:
            hashes[source_path] = file_sha256(source_path)
        except OSError:
            continue
    return hashes


def report_duplicate_documents(input_dir: Path, hashes: dict[Path, str]) -> int:
    """
    Print on stderr each group of two or more files in one folder with the same SHA-256 in `hashes`.
    Return the number of files in all groups (0 if there is no group).
    """
    groups: dict[tuple[Path, str], list[Path]] = {}
    for source_path, sha256 in hashes.items():
        groups.setdefault((source_path.parent, sha256), []).append(source_path)
    duplicate_groups = [sorted(paths) for paths in groups.values() if len(paths) > 1]
    for paths in sorted(duplicate_groups):
        names = ", ".join(str(path.relative_to(input_dir)) for path in paths)
        print(f"Duplicate: these files in one folder have the same content: {names}", file=sys.stderr, flush=True)
    if duplicate_groups:
        print(
            "Stopped: no file was changed. Remove or move the duplicate files, then run again.",
            file=sys.stderr,
            flush=True,
        )
    return sum(len(paths) for paths in duplicate_groups)


def select_files_to_process(
    input_dir: Path, source_files: list[Path], hashes: dict[Path, str], ocr_engine: str, model_name: str
) -> list[Path]:
    """
    Return the files of `source_files` that the rename history does not show as done with `model_name` and `ocr_engine`
    (see renaming.is_done). A file is matched to the last history line with its SHA-256 in `hashes`; its name is not used.
    In each folder that holds a file: create an empty history file if there is none, and remove the history lines
    whose SHA-256 matches no file of the folder (also the lines that are not records).
    Print each removed line, each file that is left out, and a summary.
    """
    last_records: dict[Path, dict[str, RenameRecord]] = {}
    for folder in sorted({path.parent for path in source_files}):
        ensure_history_file(folder)
        records, invalid_count = read_history(folder)
        folder_hashes = {sha256 for path, sha256 in hashes.items() if path.parent == folder}
        kept_records = [record for record in records if record.sha256 in folder_hashes]
        for record in records:
            if record.sha256 not in folder_hashes:
                print(
                    f"Removed from rename history (no file with this content): {(folder / record.new_name).relative_to(input_dir)}",
                    flush=True,
                )
        if len(kept_records) < len(records) or invalid_count:
            write_history(folder, kept_records)
        last_records[folder] = last_record_by_hash(kept_records)
    selected: list[Path] = []
    for source_path in source_files:
        sha256 = hashes.get(source_path)
        record = last_records[source_path.parent].get(sha256) if sha256 else None
        if is_done(record, model_name, ocr_engine):
            print(f"Already renamed (rename history): {source_path.relative_to(input_dir)}", flush=True)
        else:
            selected.append(source_path)
    print(f"To process {len(selected)}, already renamed {len(source_files) - len(selected)}", flush=True)
    return selected


def run_pipeline(
    input_dir: Path,
    work_dir: Path,
    extractors: list[DocumentExtractor],
    ocr_engine: str,
    namer: DocumentNamer,
    model_name: str,
    summary_path: Path | None = None,
) -> int:
    """
    Hash the documents and check the rename history of each folder, then run extraction into `<work_dir>/extracted`, naming into `<work_dir>/named`,
    then renaming, one stage after the other. A file that the rename history shows as done with `model_name` and `ocr_engine`
    is left out. If two or more documents in one folder have the same content, stop before any change and return
    DUPLICATE_DOCUMENTS_EXIT_CODE. When the renaming stage has finished, `<work_dir>/extracted` and `<work_dir>/named` are deleted, then
    `work_dir` if it is empty. Files under `work_dir` are not extracted. A failed document does not stop the run:
    the next stages use the documents that did not fail. Return 1 if any document failed in any stage, otherwise 0.
    At the end (also at the stop for duplicate documents), write the document counts to `summary_path` if it is given.
    The duplicate documents count as failed.
    """
    print(f"== Rename history: {input_dir.resolve()} (model {model_name}, OCR engine {ocr_engine})", flush=True)
    all_source_files = find_source_files(input_dir, work_dir)
    supported_suffixes = {suffix for extractor in extractors for suffix in extractor.supported_suffixes}
    hashes = hash_documents(all_source_files, supported_suffixes)
    duplicate_count = report_duplicate_documents(input_dir, hashes)
    if duplicate_count:
        write_run_summary(summary_path, RunSummary(0, 0, 0, failed=duplicate_count))
        return DUPLICATE_DOCUMENTS_EXIT_CODE
    extracted_dir = work_dir / "extracted"
    named_dir = work_dir / "named"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    named_dir.mkdir(parents=True, exist_ok=True)
    source_files = select_files_to_process(input_dir, all_source_files, hashes, ocr_engine, model_name)
    print(f"== Stage 1 of 3: Extraction: {input_dir.resolve()} -> {extracted_dir.resolve()}", flush=True)
    extract_counts = run_extract(input_dir, extracted_dir, extractors, ocr_engine, source_files)
    print(f"== Stage 2 of 3: Naming: {extracted_dir.resolve()} -> {named_dir.resolve()}", flush=True)
    name_counts = run_name(extracted_dir, named_dir, namer, model_name)
    print(f"== Stage 3 of 3: Renaming: {named_dir.resolve()}", flush=True)
    rename_counts = run_rename(named_dir, dry_run=False)
    shutil.rmtree(extracted_dir)
    print(f"Deleted the extracted JSON files: {extracted_dir.resolve()}", flush=True)
    shutil.rmtree(named_dir)
    print(f"Deleted the name suggestion JSON files: {named_dir.resolve()}", flush=True)
    if not any(work_dir.iterdir()):
        work_dir.rmdir()
    write_run_summary(
        summary_path,
        RunSummary(
            processed=rename_counts.done,
            skipped_already_renamed=len(all_source_files) - len(source_files),
            skipped_unsupported=extract_counts.skipped,
            failed=extract_counts.failed + name_counts.failed + rename_counts.failed,
        ),
    )
    return max(extract_counts.exit_code, name_counts.exit_code, rename_counts.exit_code)


def create_extractors_or_exit(
    parser: argparse.ArgumentParser, engine_option: str | None
) -> tuple[str, list[DocumentExtractor]]:
    """
    Return the name of the OCR engine of `engine_option` (default: the engine of this operating system) and the default
    extractors with that engine. Exit with code 2 if the engine is unavailable.
    """
    try:
        engine_name = OcrEngineName(engine_option) if engine_option else native_ocr_engine_name()
        ocr_engine = create_ocr_engine(engine_name)
    except OcrEngineUnavailableError as error:
        parser.error(str(error))
    return engine_name.value, default_extractors(ocr_engine)


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
        engine_name, extractors = create_extractors_or_exit(parser, arguments.ocr_engine)
        return run_extract(arguments.input_dir, arguments.output_dir, extractors, engine_name).exit_code
    if arguments.command == "rename":
        return run_rename(arguments.input_dir, arguments.dry_run).exit_code
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
        engine_name, extractors = create_extractors_or_exit(parser, arguments.ocr_engine)
        namer = load_namer_or_exit(parser, arguments.model, arguments.max_document_tokens)
        return run_pipeline(
            arguments.input_dir,
            arguments.work_dir,
            extractors,
            engine_name,
            namer,
            arguments.model.name,
            arguments.summary_file,
        )
    namer = load_namer_or_exit(parser, arguments.model, arguments.max_document_tokens)
    return run_name(arguments.input_dir, arguments.output_dir, namer, arguments.model.name).exit_code
