"""HTTP server for the web interface: the page, the folder listing, and the job queue API."""

import json
import re
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from doc_categoriser.webui.job_queue import JobAlreadyFinishedError, JobQueue, pipeline_command

LOCAL_HOST_NAMES = {"127.0.0.1", "localhost", "[::1]"}

_JOB_LOG_PATH = re.compile(r"^/api/jobs/(\d+)/log$")
_JOB_CANCEL_PATH = re.compile(r"^/api/jobs/(\d+)/cancel$")


@dataclass(frozen=True)
class WebUiSettings:
    """The folder the interface opens at, and the default output folder and model shown in the interface."""

    root_dir: Path
    default_output_dir: Path
    default_model_path: Path


class ApiError(Exception):
    """A request error. Its message is shown to the operator in the interface."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def list_subfolders(folder: Path) -> dict[str, Any]:
    """Return the folder, its parent and its non-hidden subfolders sorted by name. Raise ApiError if it is not a folder."""
    if not folder.is_dir():
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{folder} is not a folder")
    resolved_folder = folder.resolve()
    try:
        subfolders = sorted(
            (entry for entry in resolved_folder.iterdir() if entry.is_dir() and not entry.name.startswith(".")),
            key=lambda entry: entry.name.lower(),
        )
    except PermissionError as error:
        raise ApiError(HTTPStatus.FORBIDDEN, f"{folder} cannot be read: {error.strerror}") from error
    return {
        "path": str(resolved_folder),
        "parent": str(resolved_folder.parent) if resolved_folder.parent != resolved_folder else None,
        "folders": [{"name": entry.name, "path": str(entry)} for entry in subfolders],
    }


def parse_job_request(body: Any) -> tuple[list[Path], Path, Path]:
    """Return the folders, output folder and model file of a job submission. Raise ApiError if one is missing or incorrect."""
    if not isinstance(body, dict):
        raise ApiError(HTTPStatus.BAD_REQUEST, "the request body must be a JSON object")
    folders, output_dir, model_path = body.get("folders"), body.get("output_dir"), body.get("model_path")
    if not isinstance(folders, list) or not folders:
        raise ApiError(HTTPStatus.BAD_REQUEST, "select at least one folder")
    if not all(isinstance(folder, str) for folder in folders):
        raise ApiError(HTTPStatus.BAD_REQUEST, "each folder must be a path")
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "give the output folder")
    if not isinstance(model_path, str) or not model_path.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "give the model file")
    folder_paths = [Path(folder) for folder in folders]
    for folder in folder_paths:
        if not folder.is_dir():
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{folder} is not a folder")
    if Path(output_dir).exists() and not Path(output_dir).is_dir():
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{output_dir} is not a folder")
    if not Path(model_path).is_file():
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{model_path} is not a file")
    return folder_paths, Path(output_dir), Path(model_path)


def make_request_handler(settings: WebUiSettings, job_queue: JobQueue, host: str) -> type[BaseHTTPRequestHandler]:
    """Return a request handler class that serves `settings` and `job_queue` for a server bound to `host`."""
    allowed_host_names = LOCAL_HOST_NAMES | {host.lower(), f"[{host.lower()}]"}

    class WebUiRequestHandler(BaseHTTPRequestHandler):
        """Serves the page and the JSON API. Rejects requests that do not come from a page of this server."""

        def do_GET(self) -> None:
            self._handle(self._get)

        def do_POST(self) -> None:
            self._handle(self._post)

        def log_message(self, format: str, *args: Any) -> None:
            """Write no access log line for each request, because the page polls often."""

        def _handle(self, route: Any) -> None:
            """Check the request origin, run `route`, and send its result or the error as JSON."""
            try:
                self._check_host()
                route(urlsplit(self.path))
            except ApiError as error:
                self._send_json(error.status, {"error": str(error)})

        def _check_host(self) -> None:
            """Raise ApiError unless the Host header names this computer. This blocks DNS rebinding from other web sites."""
            host_name = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
            if host_name not in allowed_host_names:
                raise ApiError(HTTPStatus.FORBIDDEN, "requests must use the address of this computer")

        def _get(self, url: Any) -> None:
            if url.path in {"/", "/index.html"}:
                self._send_page()
            elif url.path == "/api/config":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "root_dir": str(settings.root_dir.resolve()),
                        "default_output_dir": str(settings.default_output_dir.resolve()),
                        "default_model_path": str(settings.default_model_path.resolve()),
                    },
                )
            elif url.path == "/api/folders":
                requested_path = parse_qs(url.query).get("path", [""])[0]
                self._send_json(HTTPStatus.OK, list_subfolders(Path(requested_path) if requested_path else settings.root_dir))
            elif url.path == "/api/jobs":
                self._send_json(HTTPStatus.OK, {"jobs": job_queue.jobs()})
            elif match := _JOB_LOG_PATH.match(url.path):
                self._send_job_log(int(match.group(1)), parse_qs(url.query).get("since", ["0"])[0])
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, f"{url.path} not found")

        def _post(self, url: Any) -> None:
            body = self._read_json_body()
            if url.path == "/api/jobs":
                folders, output_dir, model_path = parse_job_request(body)
                jobs = [job_queue.submit(folder, output_dir, model_path).to_json_dict() for folder in folders]
                self._send_json(HTTPStatus.CREATED, {"jobs": jobs})
            elif match := _JOB_CANCEL_PATH.match(url.path):
                try:
                    job = job_queue.cancel(int(match.group(1)))
                except KeyError as error:
                    raise ApiError(HTTPStatus.NOT_FOUND, f"job {match.group(1)} not found") from error
                except JobAlreadyFinishedError as error:
                    raise ApiError(HTTPStatus.CONFLICT, str(error)) from error
                self._send_json(HTTPStatus.OK, job.to_json_dict())
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, f"{url.path} not found")

        def _read_json_body(self) -> Any:
            """
            Return the JSON request body. Raise ApiError for another content type: a form from another web site
            cannot send JSON without the browser asking this server first, and this server never allows it.
            """
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "the request body must be JSON")
            length = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as error:
                raise ApiError(HTTPStatus.BAD_REQUEST, "the request body is not valid JSON") from error

        def _send_job_log(self, job_id: int, since_text: str) -> None:
            """Send the log lines of a job from line `since_text`, the number of the next line, and the job status."""
            first_line = int(since_text) if since_text.isdigit() else 0
            try:
                lines, status = job_queue.log_since(job_id, first_line)
            except KeyError as error:
                raise ApiError(HTTPStatus.NOT_FOUND, f"job {job_id} not found") from error
            self._send_json(HTTPStatus.OK, {"lines": lines, "next": first_line + len(lines), "status": status.value})

        def _send_page(self) -> None:
            """Send the single-page interface."""
            page = files("doc_categoriser.webui").joinpath("static/index.html").read_bytes()
            self._send_bytes(HTTPStatus.OK, page, "text/html; charset=utf-8")

        def _send_json(self, status: HTTPStatus, content: Any) -> None:
            self._send_bytes(status, json.dumps(content, ensure_ascii=False).encode("utf-8"), "application/json")

        def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return WebUiRequestHandler


def create_web_server(settings: WebUiSettings, job_queue: JobQueue, host: str, port: int) -> ThreadingHTTPServer:
    """Return a server, not yet serving, bound to `host` and `port` (0 picks a free port)."""
    server = ThreadingHTTPServer((host, port), make_request_handler(settings, job_queue, host))
    server.daemon_threads = True
    return server


def serve_web_ui(
    root_dir: Path, default_output_dir: Path, default_model_path: Path, host: str, port: int, open_browser: bool
) -> int:
    """Serve the interface until Ctrl+C, optionally open it in the web browser, then stop the running job. Return 0."""
    job_queue = JobQueue(pipeline_command)
    server = create_web_server(WebUiSettings(root_dir, default_output_dir, default_model_path), job_queue, host, port)
    url = f"http://{host if ':' not in host else f'[{host}]'}:{server.server_address[1]}/"
    print(f"Web interface: {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=[url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping. The running job is cancelled.", flush=True)
    finally:
        server.server_close()
        job_queue.close()
    return 0
