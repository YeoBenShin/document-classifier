"""The summary log of one queue run: `logs<N>.txt` with the result and the document counts of each job."""

import datetime
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

LOG_FILE_PATTERN = re.compile(r"^logs(\d+)\.txt$")

STATUS_LABELS = {
    "succeeded": "Done",
    "finished_with_errors": "Done with errors",
    "failed": "Failed",
    "cancelled": "Cancelled",
}
"""The text of each final job status, as the page shows it."""


@dataclass(frozen=True)
class DocumentCounts:
    """The document counts that `doc-categoriser run --summary-file` writes."""

    processed: int
    skipped_already_renamed: int
    skipped_unsupported: int
    failed: int

    @property
    def skipped(self) -> int:
        """Return the number of skipped documents: already renamed plus unsupported type."""
        return self.skipped_already_renamed + self.skipped_unsupported


def read_document_counts(summary_path: Path) -> DocumentCounts | None:
    """Return the counts in the run summary JSON at `summary_path`, or None if the file is missing or not valid."""
    try:
        content = json.loads(summary_path.read_text(encoding="utf-8"))
        return DocumentCounts(
            processed=int(content["processed"]),
            skipped_already_renamed=int(content["skipped_already_renamed"]),
            skipped_unsupported=int(content["skipped_unsupported"]),
            failed=int(content["failed"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


@dataclass(frozen=True)
class JobSummary:
    """The result of one finished job. `counts` is None if the run stopped before it wrote its counts."""

    input_dir: Path
    status: str
    exit_code: int | None
    counts: DocumentCounts | None


def next_log_path(folder: Path) -> Path:
    """Return `<folder>/logs<N>.txt`, with N one more than the highest N of the files in `folder` (1 if there is none)."""
    numbers = [
        int(match.group(1))
        for path in (folder.iterdir() if folder.is_dir() else [])
        if (match := LOG_FILE_PATTERN.match(path.name))
    ]
    return folder / f"logs{max(numbers, default=0) + 1}.txt"


def now_text() -> str:
    """Return the local date and time as `YYYY-MM-DD HH:MM:SS`."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SummaryLog:
    """
    The summary log of one queue run. The file is written again in full after each change: a summary at the top
    (number of jobs that succeeded and failed, one line for each folder), then the details of each job.
    A job succeeded if its status is `succeeded`. All other final statuses count as failed.
    """

    def __init__(self, folder: Path) -> None:
        """Create the next `logs<N>.txt` file in `folder` (the folder is created if necessary)."""
        folder.mkdir(parents=True, exist_ok=True)
        self.path = next_log_path(folder)
        self._started_at = now_text()
        self._finished_at: str | None = None
        self._jobs: list[JobSummary] = []
        self._write()

    def add_job(self, job: JobSummary) -> None:
        """Add the result of a finished job and write the file."""
        self._jobs.append(job)
        self._write()

    def finish(self) -> None:
        """Record that the queue is empty and write the file. The file does not change after this."""
        self._finished_at = now_text()
        self._write()

    def render(self) -> str:
        """Return the text of the log file."""
        succeeded_count = sum(1 for job in self._jobs if job.status == "succeeded")
        lines = [
            f"Started: {self._started_at}",
            f"Finished: {self._finished_at or 'not yet (the queue is running)'}",
            f"Jobs succeeded: {succeeded_count}",
            f"Jobs failed: {len(self._jobs) - succeeded_count}",
            "",
        ]
        lines += [f"- {job.input_dir.name}: {self._result_text(job)}" for job in self._jobs]
        lines += ["", "Details", ""]
        for number, job in enumerate(self._jobs, start=1):
            lines += [f"{number}. {job.input_dir.name}", f"Folder: {job.input_dir}", f"Result: {self._result_text(job)}"]
            if job.counts is None:
                lines.append("Number of files: not known (the run stopped before the end)")
            else:
                lines += [
                    f"Number of files processed: {job.counts.processed}",
                    f"Number of files skipped: {job.counts.skipped} (already renamed {job.counts.skipped_already_renamed}, "
                    f"unsupported type {job.counts.skipped_unsupported})",
                    f"Number of files failed: {job.counts.failed}",
                ]
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _result_text(job: JobSummary) -> str:
        """Return the status label of `job`, with the exit code for a failed job."""
        label = STATUS_LABELS.get(job.status, job.status)
        if job.status == "failed" and job.exit_code is not None:
            return f"{label} (exit code {job.exit_code})"
        return label

    def _write(self) -> None:
        """Write the file through a temporary file, so that a reader never sees a part of it."""
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        temporary_path.write_text(self.render(), encoding="utf-8")
        os.replace(temporary_path, self.path)
