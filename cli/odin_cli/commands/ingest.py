"""Push local files/directories to the ingest API (async; track jobs in a queue)."""

import json
from contextlib import nullcontext
from pathlib import Path

import pathspec
import typer
from rich.table import Table

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import queue_path, require

app = typer.Typer(no_args_is_help=True, help="Ingest documents.")

_SUPPORTED = {".txt", ".md", ".markdown", ".html", ".htm"}


def _load_ignore(directory: Path) -> pathspec.GitIgnoreSpec | None:
    ignore_file = directory / ".odinignore"
    if not ignore_file.is_file():
        return None
    return pathspec.GitIgnoreSpec.from_lines(
        ignore_file.read_text(encoding="utf-8").splitlines()
    )


def _load_queue() -> list[dict]:
    path = queue_path()
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8") or "[]")


def _save_queue(entries: list[dict]) -> None:
    path = queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


@app.callback(invoke_without_command=True)
def ingest(
    ctx: typer.Context,
    directory: Path = typer.Option(
        None,
        "-d",
        "--dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Directory to ingest.",
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if directory is None:
        output.fail("missing option '--dir'")
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
    width = max(len(str(p.relative_to(directory))) for p in files)
    results, new_entries = [], []
    with Client(cfg) as client:
        for path in files:
            key = str(path.relative_to(directory))
            try:
                ctx_mgr = nullcontext() if json_out else output.thinking(f"uploading {key}…")
                with ctx_mgr:
                    res = client.ingest(path, key)
            except ApiError as e:
                res, state = {}, f"error: {e.message}"
            else:
                if res.get("job_id"):
                    state = "queued"
                    new_entries.append(
                        {
                            "key": key,
                            "job_id": str(res["job_id"]),
                            "document_id": str(res.get("document_id")),
                            "state": "pending",
                        }
                    )
                else:
                    state = "deduped"
            results.append(
                {
                    "key": key,
                    "state": state,
                    "job_id": res.get("job_id"),
                    "document_id": res.get("document_id"),
                }
            )
            if not json_out:
                output.console.print(f"↑ {key:<{width}}  {state}")
    if new_entries:
        queue = _load_queue()
        seen = {e["job_id"] for e in queue}
        queue.extend(e for e in new_entries if e["job_id"] not in seen)
        _save_queue(queue)
    if json_out:
        output.print_json(results)
    else:
        output.success(
            f"queued {len(new_entries)} job(s) — run `odin ingest status` to check progress"
        )


@app.command("status")
def status(json_out: bool = typer.Option(False, "--json")) -> None:
    cfg = require()
    entries = _load_queue()
    if not entries:
        if json_out:
            output.print_json([])
        else:
            output.console.print("no pending ingest jobs")
        return
    with Client(cfg) as client:
        ctx_mgr = nullcontext() if json_out else output.thinking(f"checking {len(entries)} job(s)…")
        with ctx_mgr:
            for e in entries:
                try:
                    job = client.get_job(e["job_id"])
                    e["state"], e["error"] = job["state"], job.get("error")
                except ApiError as ex:
                    e["state"], e["error"] = f"error: {ex.message}", ex.message
    _save_queue([e for e in entries if e["state"] != "done"])
    if json_out:
        output.print_json(entries)
    else:
        table = Table("key", "state", "error")
        for e in entries:
            table.add_row(e["key"], e["state"], e.get("error") or "")
        output.console.print(table)
