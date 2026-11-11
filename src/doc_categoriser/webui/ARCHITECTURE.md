# webui

## How it works

```
cli.py `web` ──> server.serve_web_ui(root folder, default decisions folder, default model, host, port)
                 ──> job_queue.JobQueue(pipeline_command)          (starts the queue thread)
                 ──> server.create_web_server(settings, job_queue)  (ThreadingHTTPServer)
                 ──> opens the page in the web browser

page (static/index.html) ──GET /api/config──────────────> root folder, default decisions folder, default model
                         ──GET /api/folders?path=─────────> folder, parent, non-hidden subfolders
                         ──POST /api/jobs─────────────────> JobQueue.submit(folder, decisions folder, model) for each folder
                         ──GET /api/jobs (each second)────> all jobs and their status
                         ──GET /api/jobs/<id>/log?since=N─> log lines from line N, next line number, status
                         ──POST /api/jobs/<id>/cancel─────> JobQueue.cancel(id)

queue thread: waits for a queued job ──> subprocess.Popen(pipeline_command(job)), stdout and stderr in one pipe
              each output line ──> job log
              exit code ──> status: 0 succeeded, 1 finished_with_errors, other failed (cancelled if cancel was asked)
```

- `job_queue.py`: `Job` (folder, work folder, model, status, exit code, log), `JobStatus`, `JobQueue` (one thread, one child process at a time, thread-safe), `pipeline_command(job)` (the `python -m doc_categoriser run` command line).
- `server.py`: `WebUiSettings`, the request handler (routes, checks of the request origin and the submitted folders), `create_web_server`, `serve_web_ui`.
- `static/index.html`: the page. Plain HTML, CSS and JavaScript. All text from the server is set with `textContent`, never as HTML.

## Decisions

### Command as a parameter of JobQueue

- `JobQueue` gets a function that returns the command line for a job. The server uses `pipeline_command`. The tests give a script that waits for a file, so that a job can be held in the `running` state.

### Cancel

- A queued job is only marked `cancelled`. A running job gets `terminate()` (SIGTERM on macOS, TerminateProcess on Windows). The queue thread sets `cancelled` when the process has stopped, then starts the next job.
- The cancel is recorded before the process exists, too. A cancel between the start of the job and the start of the process stops the process as soon as it starts.

### Work folder name

- `<folder name>-<YYYYMMDD-HHMMSS>-<job number>`. The job number makes two submissions in the same second different. The time makes runs of different server sessions different.

### Logs in memory

- The queue and the logs are kept in memory. They are for the operator to follow a run. The JSON files in the work folder are the lasting record of each decision.
