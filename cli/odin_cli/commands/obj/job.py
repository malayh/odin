"""Jobs: the ingest/work queue (read-only)."""

import typer
from rich.table import Table

from odin_cli import output
from odin_cli.commands.obj._common import client

app = typer.Typer(no_args_is_help=True, help="Jobs.")


@app.command("list")
def job_list(
    state: str | None = typer.Option(None, "--state", help="Filter by state."),
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List your jobs."""
    with client() as c:
        rows = c.list_jobs(state, limit, offset)
    if json_out:
        output.print_json(rows)
        return
    if not rows:
        output.console.print("no jobs")
        return
    table = Table("id", "type", "state", "attempts", "error")
    for j in rows:
        table.add_row(
            str(j["id"])[:8], j["type"], j["state"], str(j["attempts"]), j.get("error") or ""
        )
    output.console.print(table)


@app.command("get")
def job_get(
    job_id: str = typer.Argument(..., help="Job id."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect a job."""
    with client() as c:
        job = c.get_job(job_id)
    if json_out:
        output.print_json(job)
        return
    line = f"{job['type']}: {job['state']} (attempts {job['attempts']})  {job['id']}"
    output.console.print(line)
    if job.get("error"):
        output.console.print(f"[red]{job['error']}[/red]")
