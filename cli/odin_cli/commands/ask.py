"""Ask a grounded, cited question."""

import typer
from rich.table import Table

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require


def ask(
    question: str = typer.Argument(..., help="Your question."),
    scope: str | None = typer.Option(
        None, "--scope", help="Limit to a scope (default: all readable)."
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Ask Odin a grounded, cited question."""
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.ask(question, scope)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(result)
        return
    output.console.print(result["answer"])
    if not result["confident"]:
        output.console.print("[yellow]low confidence[/yellow]")
    citations = result["citations"]
    if citations:
        table = Table("document", "scope")
        for c in citations:
            table.add_row(str(c["document_id"])[:8], f"{c['scope_type']}:{str(c['scope_id'])[:8]}")
        output.console.print(table)
