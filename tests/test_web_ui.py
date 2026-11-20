"""Behaviour of the `doc-categoriser web` interface through its HTTP API, as the browser page uses it."""

import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import PageLines

from doc_categoriser.webui import Job, JobQueue, WebUiSettings, create_web_server, pipeline_command

FAKE_PIPELINE_SCRIPT = """
import pathlib, shutil, sys, time
input_dir = pathlib.Path(sys.argv[1])
summary_path = pathlib.Path(sys.argv[2])
print(f"working on {input_dir.name}", flush=True)
print("a line on stderr", file=sys.stderr, flush=True)
deadline = time.monotonic() + 60
while not (input_dir / "release").exists() and time.monotonic() < deadline:
    time.sleep(0.05)
print("done", flush=True)
if (input_dir / "counts.json").exists():
    shutil.copyfile(input_dir / "counts.json", summary_path)
exit_code_file = input_dir / "exit_code"
sys.exit(int(exit_code_file.read_text()) if exit_code_file.exists() else 0)
"""


def fake_pipeline_command(job: Job) -> list[str]:
    """
    Return a command that logs, waits until the file `release` is in the job folder, copies `counts.json` of the job folder
    to the summary file of the job, then exits with the code in `exit_code`.
    """
    return [sys.executable, "-u", "-c", FAKE_PIPELINE_SCRIPT, str(job.input_dir), str(job.summary_path)]


class WebUi:
    """A running web interface and helpers to call its HTTP API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def request(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        """Send a request and return the status code and the decoded JSON (or text) body."""
        data = json.dumps(body).encode() if body is not None else None
        all_headers = {"Content-Type": "application/json"} if body is not None else {}
        all_headers.update(headers or {})
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=all_headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, raw, content_type = response.status, response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            status, raw, content_type = error.code, error.read(), error.headers.get("Content-Type", "")
        return status, json.loads(raw) if "json" in content_type else raw.decode()

    def get(self, path: str) -> Any:
        status, body = self.request("GET", path)
        assert status == 200, body
        return body

    def submit(self, folders: list[Path], output_dir: Path, model_path: Path) -> list[dict[str, Any]]:
        status, body = self.request(
            "POST",
            "/api/jobs",
            {"folders": [str(folder) for folder in folders], "output_dir": str(output_dir), "model_path": str(model_path)},
        )
        assert status == 201, body
        return body["jobs"]

    def job(self, job_id: int) -> dict[str, Any]:
        return next(job for job in self.get("/api/jobs")["jobs"] if job["id"] == job_id)

    def log(self, job_id: int) -> str:
        return "\n".join(self.get(f"/api/jobs/{job_id}/log?since=0")["lines"])

    def wait_until(self, condition: Callable[[], bool], timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while not condition():
            assert time.monotonic() < deadline, "the condition did not become true in time"
            time.sleep(0.05)


def start_web_ui(settings: WebUiSettings, build_command: Callable[[Job], list[str]]) -> Iterator[WebUi]:
    """Start the server on a free port in a thread, yield it, then stop it and its jobs."""
    job_queue = JobQueue(build_command)
    server = create_web_server(settings, job_queue, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield WebUi(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
        job_queue.close()


@pytest.fixture
def root_dir(tmp_path: Path) -> Path:
    root = tmp_path / "documents"
    for folder in ["2025", "2026/march", ".hidden"]:
        (root / folder).mkdir(parents=True)
    (root / "notes.txt").write_text("not a folder", encoding="utf-8")
    return root


@pytest.fixture
def model_file(tmp_path: Path) -> Path:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake model")
    return model


@pytest.fixture
def web_ui(tmp_path: Path, root_dir: Path, model_file: Path) -> Iterator[WebUi]:
    settings = WebUiSettings(root_dir=root_dir, default_output_dir=tmp_path / "renaming-decision", default_model_path=model_file)
    yield from start_web_ui(settings, fake_pipeline_command)


def test_page_and_settings_open_at_the_given_folder(web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path) -> None:
    status, page = web_ui.request("GET", "/")

    assert status == 200
    assert "<html" in page
    assert web_ui.get("/api/config") == {
        "root_dir": str(root_dir.resolve()),
        "default_output_dir": str((tmp_path / "renaming-decision").resolve()),
        "default_model_path": str(model_file.resolve()),
    }


def test_folder_listing_shows_visible_subfolders_and_the_parent(web_ui: WebUi, root_dir: Path) -> None:
    root_listing = web_ui.get("/api/folders")
    march_listing = web_ui.get("/api/folders?path=" + urllib.parse.quote(str(root_dir / "2026")))

    assert root_listing["path"] == str(root_dir.resolve())
    assert root_listing["parent"] == str(root_dir.resolve().parent)
    assert [folder["name"] for folder in root_listing["folders"]] == ["2025", "2026"]
    assert root_listing["folders"][0]["path"] == str((root_dir / "2025").resolve())
    assert [folder["name"] for folder in march_listing["folders"]] == ["march"]


def test_folder_listing_rejects_a_path_that_is_not_a_folder(web_ui: WebUi, root_dir: Path) -> None:
    status, body = web_ui.request("GET", "/api/folders?path=" + urllib.parse.quote(str(root_dir / "notes.txt")))

    assert status == 400
    assert "is not a folder" in body["error"]


def test_queued_folders_run_one_after_another_and_show_their_logs(
    web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path
) -> None:
    first, second = web_ui.submit([root_dir / "2025", root_dir / "2026"], tmp_path / "decisions", model_file)

    web_ui.wait_until(lambda: "working on 2025" in web_ui.log(first["id"]))
    assert web_ui.job(first["id"])["status"] == "running"
    assert web_ui.job(second["id"])["status"] == "queued"
    assert "a line on stderr" in web_ui.log(first["id"])
    (root_dir / "2025" / "release").touch()
    web_ui.wait_until(lambda: web_ui.job(first["id"])["status"] == "succeeded")
    (root_dir / "2026" / "exit_code").write_text("1")
    (root_dir / "2026" / "release").touch()
    web_ui.wait_until(lambda: web_ui.job(second["id"])["status"] == "finished_with_errors")

    assert "done" in web_ui.log(first["id"])
    assert web_ui.job(first["id"])["exit_code"] == 0
    assert web_ui.job(second["id"])["exit_code"] == 1
    work_dir = Path(first["work_dir"])
    assert work_dir.parent == (tmp_path / "decisions").resolve()
    assert work_dir.name.startswith("2025-")
    assert Path(first["work_dir"]) != Path(second["work_dir"])


def write_counts(folder: Path, processed: int, already_renamed: int, unsupported: int, failed: int) -> None:
    """Write the counts that the fake pipeline gives as its run summary for `folder`."""
    counts = {
        "processed": processed,
        "skipped_already_renamed": already_renamed,
        "skipped_unsupported": unsupported,
        "failed": failed,
    }
    (folder / "counts.json").write_text(json.dumps(counts), encoding="utf-8")


def test_each_queue_run_writes_one_summary_log_in_the_parent_of_the_input_folders(
    web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path
) -> None:
    decisions_dir = tmp_path / "decisions"
    write_counts(root_dir / "2025", processed=5, already_renamed=2, unsupported=1, failed=0)
    write_counts(root_dir / "2026", processed=3, already_renamed=0, unsupported=0, failed=2)
    (root_dir / "2026" / "exit_code").write_text("1")
    first, second = web_ui.submit([root_dir / "2025", root_dir / "2026"], decisions_dir, model_file)
    web_ui.wait_until(lambda: web_ui.job(first["id"])["status"] == "running")
    log_path = root_dir / "logs1.txt"

    started_log = log_path.read_text(encoding="utf-8")
    (root_dir / "2025" / "release").touch()
    web_ui.wait_until(lambda: web_ui.job(first["id"])["status"] == "succeeded")
    web_ui.wait_until(lambda: web_ui.job(second["id"])["status"] == "running")
    log_after_first_job = log_path.read_text(encoding="utf-8")
    (root_dir / "2026" / "release").touch()
    web_ui.wait_until(lambda: web_ui.job(second["id"])["status"] == "finished_with_errors")

    assert "Jobs succeeded: 0\nJobs failed: 0\n" in started_log
    assert "Finished: not yet" in started_log
    assert "Jobs succeeded: 1\nJobs failed: 0\n" in log_after_first_job
    assert "- 2026:" not in log_after_first_job
    final_log = log_path.read_text(encoding="utf-8")
    assert final_log.startswith("Started: ")
    assert "Finished: not yet" not in final_log
    assert "Jobs succeeded: 1\nJobs failed: 1\n\n- 2025: Done\n- 2026: Done with errors\n" in final_log
    assert (
        f"1. 2025\nFolder: {(root_dir / '2025').resolve()}\nResult: Done\n"
        "Number of files processed: 5\n"
        "Number of files skipped: 3 (already renamed 2, unsupported type 1)\n"
        "Number of files failed: 0\n"
    ) in final_log
    assert (
        "2. 2026\n"
        f"Folder: {(root_dir / '2026').resolve()}\nResult: Done with errors\n"
        "Number of files processed: 3\n"
        "Number of files skipped: 0 (already renamed 0, unsupported type 0)\n"
        "Number of files failed: 2\n"
    ) in final_log
    assert web_ui.job(first["id"])["summary_log_path"] == str(log_path.resolve())
    assert f"Summary log: {log_path.resolve()}" in web_ui.log(second["id"])

    [third] = web_ui.submit([root_dir / "2025"], decisions_dir, model_file)
    web_ui.wait_until(lambda: web_ui.job(third["id"])["status"] == "succeeded")

    assert web_ui.job(third["id"])["summary_log_path"] == str((root_dir / "logs2.txt").resolve())
    second_run_log = (root_dir / "logs2.txt").read_text(encoding="utf-8")
    assert not list(decisions_dir.glob("logs*.txt"))
    assert "Jobs succeeded: 1\nJobs failed: 0\n\n- 2025: Done\n\n" in second_run_log
    assert log_path.read_text(encoding="utf-8") == final_log


def test_summary_log_counts_failed_and_cancelled_jobs_as_failed(
    web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path
) -> None:
    decisions_dir = tmp_path / "decisions"
    (root_dir / "logs7.txt").write_text("an earlier queue run", encoding="utf-8")
    (root_dir / "2026" / "exit_code").write_text("3")
    (root_dir / "2026" / "release").touch()
    first, second, third = web_ui.submit(
        [root_dir / "2025", root_dir / "2026", root_dir / "2026" / "march"], decisions_dir, model_file
    )
    web_ui.wait_until(lambda: web_ui.job(first["id"])["status"] == "running")
    web_ui.request("POST", f"/api/jobs/{third['id']}/cancel", {})
    web_ui.request("POST", f"/api/jobs/{first['id']}/cancel", {})
    web_ui.wait_until(lambda: web_ui.job(second["id"])["status"] == "failed")
    web_ui.wait_until(lambda: "Finished: not yet" not in (root_dir / "logs8.txt").read_text(encoding="utf-8"))

    log = (root_dir / "logs8.txt").read_text(encoding="utf-8")
    assert "Jobs succeeded: 0\nJobs failed: 2\n\n- 2025: Cancelled\n- 2026: Failed (exit code 3)\n\n" in log
    assert "march" not in log
    assert log.count("Number of files: not known (the run stopped before the end)") == 2


def test_log_can_be_read_from_a_line_number(web_ui: WebUi, root_dir: Path, tmp_path: Path, model_file: Path) -> None:
    (root_dir / "2025" / "release").touch()
    [job] = web_ui.submit([root_dir / "2025"], tmp_path / "decisions", model_file)
    web_ui.wait_until(lambda: web_ui.job(job["id"])["status"] == "succeeded")

    full_log = web_ui.get(f"/api/jobs/{job['id']}/log?since=0")
    rest_of_log = web_ui.get(f"/api/jobs/{job['id']}/log?since=1")

    assert full_log["next"] == len(full_log["lines"])
    assert rest_of_log["lines"] == full_log["lines"][1:]
    assert rest_of_log["status"] == "succeeded"


def test_cancel_stops_the_running_folder_and_the_next_folder_starts(
    web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path
) -> None:
    first, second = web_ui.submit([root_dir / "2025", root_dir / "2026"], tmp_path / "decisions", model_file)
    web_ui.wait_until(lambda: web_ui.job(first["id"])["status"] == "running")

    status, cancelled = web_ui.request("POST", f"/api/jobs/{first['id']}/cancel", {})

    assert status == 200, cancelled
    web_ui.wait_until(lambda: web_ui.job(first["id"])["status"] == "cancelled")
    web_ui.wait_until(lambda: "working on 2026" in web_ui.log(second["id"]))
    assert "done" not in web_ui.log(first["id"])
    assert "Cancelled" in web_ui.log(first["id"])


def test_cancel_a_queued_folder_before_it_starts(web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path) -> None:
    first, second = web_ui.submit([root_dir / "2025", root_dir / "2026"], tmp_path / "decisions", model_file)
    web_ui.wait_until(lambda: web_ui.job(first["id"])["status"] == "running")

    status, _ = web_ui.request("POST", f"/api/jobs/{second['id']}/cancel", {})
    (root_dir / "2025" / "release").touch()
    web_ui.wait_until(lambda: web_ui.job(first["id"])["status"] == "succeeded")

    assert status == 200
    assert web_ui.job(second["id"])["status"] == "cancelled"
    assert "working on" not in web_ui.log(second["id"])


def test_cancel_a_finished_folder_is_rejected(web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path) -> None:
    (root_dir / "2025" / "release").touch()
    [job] = web_ui.submit([root_dir / "2025"], tmp_path / "decisions", model_file)
    web_ui.wait_until(lambda: web_ui.job(job["id"])["status"] == "succeeded")

    status, body = web_ui.request("POST", f"/api/jobs/{job['id']}/cancel", {})

    assert status == 409
    assert "already finished" in body["error"]


@pytest.mark.parametrize(
    ("problem", "expected_message"),
    [
        ("missing_folder", "is not a folder"),
        ("no_folders", "select at least one folder"),
        ("missing_model", "is not a file"),
    ],
)
def test_submit_rejects_incorrect_settings_and_queues_nothing(
    web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path, problem: str, expected_message: str
) -> None:
    folders = [root_dir / "2025"]
    model_path = model_file
    if problem == "missing_folder":
        folders = [root_dir / "2025", root_dir / "does_not_exist"]
    elif problem == "no_folders":
        folders = []
    else:
        model_path = tmp_path / "missing.gguf"

    status, body = web_ui.request(
        "POST",
        "/api/jobs",
        {"folders": [str(folder) for folder in folders], "output_dir": str(tmp_path / "out"), "model_path": str(model_path)},
    )

    assert status == 400
    assert expected_message in body["error"]
    assert web_ui.get("/api/jobs")["jobs"] == []


def test_requests_from_other_web_sites_are_rejected(web_ui: WebUi, tmp_path: Path, root_dir: Path, model_file: Path) -> None:
    form_status, _ = web_ui.request(
        "POST",
        "/api/jobs",
        f"folders={root_dir / '2025'}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    other_host_status, _ = web_ui.request("GET", "/api/jobs", headers={"Host": "attacker.example:8765"})

    assert form_status == 415
    assert other_host_status == 403
    assert web_ui.get("/api/jobs")["jobs"] == []


def test_queued_folder_is_extracted_named_and_renamed_with_the_real_pipeline(
    tmp_path: Path, test_model_path: Path, make_text_pdf: Callable[[str, list[PageLines]], Path]
) -> None:
    input_dir = tmp_path / "inbox"
    input_dir.mkdir()
    make_text_pdf(
        "scan_0001.pdf",
        [["DBS Bank Statement", "Statement period 01/03/2026 - 31/03/2026", "Closing balance 980.40"]],
    ).rename(input_dir / "scan_0001.pdf")
    output_dir = tmp_path / "renaming-decision"
    settings = WebUiSettings(root_dir=tmp_path, default_output_dir=output_dir, default_model_path=test_model_path)

    for web_ui in start_web_ui(settings, pipeline_command):
        [job] = web_ui.submit([input_dir], output_dir, test_model_path)
        web_ui.wait_until(lambda: web_ui.job(job["id"])["status"] not in {"queued", "running"}, timeout=120)

        log = web_ui.log(job["id"])
        assert web_ui.job(job["id"])["status"] == "succeeded", log
        [new_name] = [path.name for path in input_dir.iterdir() if not path.name.startswith(".")]
        assert new_name.startswith("inbox-")
        assert f"Renamed: scan_0001.pdf.json: scan_0001.pdf -> {new_name}" in log
        assert "Renamed 1, already renamed 0, failed 0" in log
        assert not Path(job["work_dir"]).exists()
        summary_log = (tmp_path / "logs1.txt").read_text(encoding="utf-8")
        assert "Jobs succeeded: 1\nJobs failed: 0\n\n- inbox: Done\n" in summary_log
        assert "Number of files processed: 1\n" in summary_log
        assert "Number of files skipped: 0 (already renamed 0, unsupported type 0)\n" in summary_log
        assert "Number of files failed: 0\n" in summary_log
