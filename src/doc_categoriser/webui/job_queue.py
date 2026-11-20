"""
A queue that runs one pipeline child process at a time, keeps the log of each, and can cancel a job.
Each queue run (from the first job that starts until the queue is empty) gets one summary log file.
"""

import datetime
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from doc_categoriser.webui.summary_log import JobSummary, SummaryLog, read_document_counts


class JobStatus(StrEnum):
    """The state of a job. A job in a final state never changes again."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FINISHED_WITH_ERRORS = "finished_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINAL_STATUSES = {JobStatus.SUCCEEDED, JobStatus.FINISHED_WITH_ERRORS, JobStatus.FAILED, JobStatus.CANCELLED}


class JobAlreadyFinishedError(Exception):
    """The job cannot be cancelled, because it is already in a final state."""


@dataclass
class Job:
    """
    One folder to run through the pipeline. `work_dir` receives the extracted and the name suggestion JSON files.
    `summary_path` receives the document counts of the run. `summary_log_path` is the summary log of the queue run of the job.
    """

    id: int
    input_dir: Path
    work_dir: Path
    model_path: Path
    summary_path: Path
    summary_log_path: Path | None = None
    status: JobStatus = JobStatus.QUEUED
    exit_code: int | None = None
    log_lines: list[str] = field(default_factory=lambda: [])

    def to_json_dict(self) -> dict[str, Any]:
        """Return the job without its log, as the HTTP API gives it."""
        return {
            "id": self.id,
            "input_dir": str(self.input_dir),
            "work_dir": str(self.work_dir),
            "model_path": str(self.model_path),
            "status": self.status.value,
            "exit_code": self.exit_code,
            "log_line_count": len(self.log_lines),
            "summary_log_path": str(self.summary_log_path) if self.summary_log_path else None,
        }


CommandBuilder = Callable[[Job], list[str]]
"""Returns the command line of the child process that runs the pipeline for a job."""


def pipeline_command(job: Job) -> list[str]:
    """Return the `doc-categoriser run` command for `job`, with the Python interpreter of this process."""
    return [
        sys.executable,
        "-u",
        "-m",
        "doc_categoriser",
        "run",
        str(job.input_dir),
        str(job.work_dir),
        "--model",
        str(job.model_path),
        "--summary-file",
        str(job.summary_path),
    ]


def status_for_exit_code(exit_code: int) -> JobStatus:
    """Return the final status for the exit code of `doc-categoriser run`: 0 all done, 1 some documents failed, other failed."""
    if exit_code == 0:
        return JobStatus.SUCCEEDED
    if exit_code == 1:
        return JobStatus.FINISHED_WITH_ERRORS
    return JobStatus.FAILED


class JobQueue:
    """
    Runs submitted jobs one at a time, in the order of submission, each in a child process from `build_command`.
    The standard output and standard error of the child are kept as the job log. All methods are thread-safe.
    When a job starts and no queue run is open, a queue run starts: a new `logs<N>.txt` in the parent folder of the
    job input folder. Each job that ran is added to it when it finishes. The queue run ends when no job is queued.
    """

    def __init__(self, build_command: CommandBuilder) -> None:
        self._build_command = build_command
        self._jobs: list[Job] = []
        self._running_process: subprocess.Popen[str] | None = None
        self._cancel_requested_job_ids: set[int] = set()
        self._lock = threading.Lock()
        self._job_added = threading.Condition(self._lock)
        self._closed = False
        self._summary_dir = tempfile.TemporaryDirectory(prefix="doc-categoriser-summaries-")
        self._summary_log: SummaryLog | None = None
        self._worker = threading.Thread(target=self._run_jobs, name="pipeline-job-queue", daemon=True)
        self._worker.start()

    def submit(self, input_dir: Path, output_dir: Path, model_path: Path) -> Job:
        """
        Queue `input_dir` and return its job. The job work folder is a new subfolder of `output_dir`,
        named after the input folder, the time of submission and the job number.
        """
        with self._lock:
            job_id = len(self._jobs) + 1
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            job = Job(
                id=job_id,
                input_dir=input_dir.resolve(),
                work_dir=output_dir.resolve() / f"{input_dir.resolve().name}-{timestamp}-{job_id}",
                model_path=model_path.resolve(),
                summary_path=Path(self._summary_dir.name) / f"job-{job_id}.json",
            )
            self._jobs.append(job)
            self._job_added.notify()
            return job

    def cancel(self, job_id: int) -> Job:
        """
        Cancel a queued job, or stop the child process of the running job.
        Raise KeyError for an unknown job, and JobAlreadyFinishedError for a job in a final state.
        """
        with self._lock:
            job = self._find_job(job_id)
            if job.status in FINAL_STATUSES:
                raise JobAlreadyFinishedError(f"job {job_id} has already finished ({job.status.value})")
            if job.status is JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.log_lines.append("Cancelled by the user before it started.")
            else:
                self._cancel_requested_job_ids.add(job_id)
                if self._running_process is not None:
                    self._running_process.terminate()
            return job

    def jobs(self) -> list[dict[str, Any]]:
        """Return all jobs, without logs, in the order of submission."""
        with self._lock:
            return [job.to_json_dict() for job in self._jobs]

    def log_since(self, job_id: int, first_line: int) -> tuple[list[str], JobStatus]:
        """Return the log lines of a job from line `first_line` (0 is the first line), and its status. Raise KeyError for an unknown job."""
        with self._lock:
            job = self._find_job(job_id)
            return job.log_lines[max(first_line, 0) :], job.status

    def close(self) -> None:
        """Stop the running child process and start no other job."""
        with self._lock:
            self._closed = True
            if self._running_process is not None:
                self._running_process.terminate()
            self._job_added.notify()
        self._worker.join(timeout=10)
        if not self._worker.is_alive():
            self._summary_dir.cleanup()

    def _find_job(self, job_id: int) -> Job:
        """Return the job with `job_id`. The caller holds the lock. Raise KeyError if there is none."""
        for job in self._jobs:
            if job.id == job_id:
                return job
        raise KeyError(job_id)

    def _next_queued_job(self) -> Job | None:
        """Wait for a queued job, mark it running and return it. Return None when the queue is closed."""
        with self._lock:
            while not self._closed:
                job = next((job for job in self._jobs if job.status is JobStatus.QUEUED), None)
                if job is not None:
                    job.status = JobStatus.RUNNING
                    return job
                self._job_added.wait()
            return None

    def _run_jobs(self) -> None:
        """Run queued jobs one after another until the queue is closed."""
        while (job := self._next_queued_job()) is not None:
            self._run_job(job)

    def _open_summary_log(self, job: Job) -> None:
        """Start a queue run if none is open, and give `job` its summary log path. The caller holds the lock."""
        if self._summary_log is None:
            try:
                self._summary_log = SummaryLog(job.input_dir.parent)
            except OSError as error:
                job.log_lines.append(f"Cannot write the summary log in {job.input_dir.parent}: {error}")
                return
        job.summary_log_path = self._summary_log.path
        job.log_lines.append(f"Summary log: {self._summary_log.path}")

    def _close_job_in_summary_log(self, job: Job) -> None:
        """
        Add the finished `job` to the summary log, and end the queue run if no job is queued or the queue is closed.
        The caller holds the lock.
        """
        counts = read_document_counts(job.summary_path)
        job.summary_path.unlink(missing_ok=True)
        summary_log = self._summary_log
        if summary_log is None:
            return
        queue_run_ends = self._closed or not any(other.status is JobStatus.QUEUED for other in self._jobs)
        if queue_run_ends:
            self._summary_log = None
        try:
            summary_log.add_job(JobSummary(job.input_dir, job.status.value, job.exit_code, counts))
            if queue_run_ends:
                summary_log.finish()
        except OSError as error:
            job.log_lines.append(f"Cannot write the summary log {summary_log.path}: {error}")

    def _run_job(self, job: Job) -> None:
        """Run the child process of `job`, keep its output as the log, set the final status, and add it to the summary log."""
        with self._lock:
            self._open_summary_log(job)
        command = self._build_command(job)
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
            )
        except OSError as error:
            with self._lock:
                job.log_lines.append(f"Cannot start the pipeline: {error}")
                job.status = JobStatus.FAILED
                self._close_job_in_summary_log(job)
            return
        with self._lock:
            self._running_process = process
            if job.id in self._cancel_requested_job_ids or self._closed:
                process.terminate()
        assert process.stdout is not None
        for line in process.stdout:
            with self._lock:
                job.log_lines.append(line.rstrip("\r\n"))
        exit_code = process.wait()
        with self._lock:
            self._running_process = None
            job.exit_code = exit_code
            if job.id in self._cancel_requested_job_ids or self._closed:
                job.status = JobStatus.CANCELLED
                job.log_lines.append("Cancelled by the user. Documents renamed before the cancel keep their new names.")
            else:
                job.status = status_for_exit_code(exit_code)
                job.log_lines.append(f"Finished with exit code {exit_code}.")
            self._close_job_in_summary_log(job)
