"""Objectives: the organizing force of the brain."""

import typer
from rich.table import Table

from odin_cli import output
from odin_cli.commands.obj._common import client, load_body, print_schema, result_out

app = typer.Typer(no_args_is_help=True, help="Objectives.")


@app.command("create")
def objective_create(
    text: str | None = typer.Argument(None, help="The objective text."),
    body: str | None = typer.Option(None, "--body", help="JSON body: @file, '-' stdin, or inline."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Declare an objective."""
    payload = load_body(body)
    if payload is None:
        if not text:
            output.fail("provide the objective text (or --body)")
        payload = {"text": text}
    with client() as c:
        result = c.create_objective(payload, dry_run)
    result_out(result, json_out)


@app.command("list")
def objective_list(json_out: bool = typer.Option(False, "--json")) -> None:
    """List your objectives."""
    with client() as c:
        rows = c.list_objectives()
    if json_out:
        output.print_json(rows)
        return
    if not rows:
        output.console.print("no objectives")
        return
    table = Table("id", "text")
    for row in rows:
        table.add_row(row["id"], row["text"])
    output.console.print(table)


@app.command("get")
def objective_get(
    objective_id: str = typer.Argument(..., help="Objective id."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect an objective."""
    with client() as c:
        obj = c.get_objective(objective_id)
    if json_out:
        output.print_json(obj)
        return
    output.console.print(f"[bold]{obj['text']}[/bold]  {obj['id']}")


@app.command("delete")
def objective_delete(
    objective_id: str = typer.Argument(..., help="Objective id."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Drop an objective."""
    with client() as c:
        result = c.delete_objective(objective_id, dry_run)
    result_out(result, json_out)


@app.command("schema")
def objective_schema(
    create: bool = typer.Option(False, "--create", help="Show the create schema (default)."),
) -> None:
    """Print the JSON schema for the create body."""
    print_schema("objective", "create")
