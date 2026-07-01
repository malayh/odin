"""Documents: list, inspect, soft-delete."""

import typer
from rich.table import Table

from odin_cli import output
from odin_cli.commands.obj._common import client, result_out

app = typer.Typer(no_args_is_help=True, help="Documents.")


@app.command("list")
def document_list(
    state: str | None = typer.Option(None, "--state", help="Filter by state."),
    type_: str | None = typer.Option(None, "--type", help="Filter by doc type."),
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List your documents."""
    with client() as c:
        rows = c.list_documents(state, type_, limit, offset)
    if json_out:
        output.print_json(rows)
        return
    if not rows:
        output.console.print("no documents")
        return
    table = Table("id", "key", "type", "state", "version")
    for d in rows:
        table.add_row(
            str(d["id"])[:8], d["key"], d["doc_type"], d["state"], str(d["version"])
        )
    output.console.print(table)


@app.command("get")
def document_get(
    doc_id: str = typer.Argument(..., help="Document id."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect a document."""
    with client() as c:
        doc = c.get_document(doc_id)
    if json_out:
        output.print_json(doc)
        return
    header = f"[bold]{doc['key']}[/bold] ({doc['doc_type']}) {doc['state']} v{doc['version']}"
    output.console.print(f"{header}  {doc['id']}")


@app.command("delete")
def document_delete(
    doc_id: str = typer.Argument(..., help="Document id."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Soft-delete a document."""
    with client() as c:
        result = c.delete_document(doc_id, dry_run)
    result_out(result, json_out)
