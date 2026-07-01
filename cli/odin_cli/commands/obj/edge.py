"""Relationships (edges) between entities."""

import typer

from odin_cli import output
from odin_cli.commands.obj._common import client, load_body, print_schema, result_out

app = typer.Typer(no_args_is_help=True, help="Relationships.")


@app.command("create")
def edge_create(
    subject: str | None = typer.Argument(None, help="Subject entity key."),
    predicate: str | None = typer.Argument(None, help="Predicate."),
    obj: str | None = typer.Argument(None, help="Object entity key."),
    body: str | None = typer.Option(None, "--body", help="JSON body: @file, '-' stdin, or inline."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Create a relationship between two entities."""
    payload = load_body(body)
    if payload is None:
        if not (subject and predicate and obj):
            output.fail("provide <subject> <predicate> <object> (or --body)")
        payload = {"subject_key": subject, "predicate": predicate, "object_key": obj}
    with client() as c:
        result = c.create_edge(payload, dry_run)
    result_out(result, json_out)


@app.command("delete")
def edge_delete(
    subject: str = typer.Argument(..., help="Subject entity key."),
    predicate: str = typer.Argument(..., help="Predicate."),
    obj: str = typer.Argument(..., help="Object entity key."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a relationship between two entities."""
    with client() as c:
        result = c.delete_edge(subject, predicate, obj, dry_run)
    result_out(result, json_out)


@app.command("schema")
def edge_schema(
    create: bool = typer.Option(False, "--create", help="Show the create schema (default)."),
) -> None:
    """Print the JSON schema for the create body."""
    print_schema("edge", "create")
