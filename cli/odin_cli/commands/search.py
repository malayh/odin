"""Run a search over your knowledge base."""

import typer
from rich.table import Table

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require


def search(
    query: str = typer.Argument(..., help="Search query."),
    top_k: int = typer.Option(10, "--top-k", "-k"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Search the knowledge base."""
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.search(query, top_k)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(result)
        return
    hits = result["hits"]
    if not hits:
        output.console.print("no hits")
        return
    table = Table("score", "document", "ordinal", "text")
    for h in hits:
        snippet = h["text"][:80].replace("\n", " ")
        table.add_row(f"{h['score']:.3f}", str(h["document_id"])[:8], str(h["ordinal"]), snippet)
    output.console.print(table)
