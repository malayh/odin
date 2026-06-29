"""Push local files/directories to the ingest API."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pathspec
import typer

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require

app = typer.Typer(no_args_is_help=True, help="Ingest documents.")

_SUPPORTED = {".txt", ".md", ".markdown", ".html", ".htm"}


def _load_ignore(directory: Path) -> pathspec.GitIgnoreSpec | None:
    ignore_file = directory / ".odinignore"
    if not ignore_file.is_file():
        return None
    return pathspec.GitIgnoreSpec.from_lines(
        ignore_file.read_text(encoding="utf-8").splitlines()
    )


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


def _ingest_one(client: Client, directory: Path, path: Path) -> dict:
    key = str(path.relative_to(directory))
    try:
        res = client.ingest(path, key)
        state = _poll(client, res["job_id"]) if res.get("job_id") else "deduped"
    except ApiError as e:
        res = {}
        state = f"error: {e.message}"
    return {"key": key, "state": state, "document_id": res.get("document_id")}


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
    concurrency: int = typer.Option(
        8, "-c", "--concurrency", min=1, help="Max files to ingest in parallel."
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = require()
    spec = _load_ignore(directory)
    files = sorted(
        p
        for p in directory.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _SUPPORTED
        and not (spec and spec.match_file(p.relative_to(directory).as_posix()))
    )
    if not files:
        output.fail(f"no ingestible files (.txt/.md/.html) under {directory}")
    results = []
    with Client(cfg) as client:
        with ThreadPoolExecutor(max_workers=min(concurrency, len(files))) as pool:
            futures = {pool.submit(_ingest_one, client, directory, path): path for path in files}
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if not json_out:
                    output.console.print(f"{result['key']} → {result['state']}")
    results.sort(key=lambda r: r["key"])
    if json_out:
        output.print_json(results)
