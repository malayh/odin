"""Push local files/directories to the ingest API."""

import time
from pathlib import Path

import typer

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require

app = typer.Typer(no_args_is_help=True, help="Ingest documents.")

_SUPPORTED = {".txt", ".md", ".markdown", ".html", ".htm"}


def _poll(client: Client, job_id: str, *, timeout: float = 300.0, interval: float = 2.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get_job(job_id)
        if job["state"] == "done":
            return "done"
        if job["state"] == "failed":
            return f"failed: {job.get('error')}"
        time.sleep(interval)
    return "timeout"


@app.callback(invoke_without_command=True)
def ingest(
    directory: Path = typer.Option(
        ...,
        "-d",
        "--dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Directory to ingest.",
    ),
    scope: str | None = typer.Option(None, "--scope", help="Target scope (default from config)."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = require()
    target = scope or cfg.default_scope
    files = sorted(
        p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in _SUPPORTED
    )
    if not files:
        output.fail(f"no ingestible files (.txt/.md/.html) under {directory}")
    results = []
    with Client(cfg) as client:
        for path in files:
            key = str(path.relative_to(directory))
            try:
                res = client.ingest(path, key, target)
                state = _poll(client, res["job_id"]) if res.get("job_id") else "deduped"
            except ApiError as e:
                res = {}
                state = f"error: {e.message}"
            results.append({"key": key, "state": state, "document_id": res.get("document_id")})
            if not json_out:
                output.console.print(f"{key} → {state}")
    if json_out:
        output.print_json(results)
