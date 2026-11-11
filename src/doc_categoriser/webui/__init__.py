"""Browser interface that queues folders for the full pipeline (`doc-categoriser run`) and shows the log of each."""

from doc_categoriser.webui.job_queue import Job, JobAlreadyFinishedError, JobQueue, JobStatus, pipeline_command
from doc_categoriser.webui.server import WebUiSettings, create_web_server, serve_web_ui

__all__ = [
    "Job",
    "JobAlreadyFinishedError",
    "JobQueue",
    "JobStatus",
    "WebUiSettings",
    "create_web_server",
    "pipeline_command",
    "serve_web_ui",
]
