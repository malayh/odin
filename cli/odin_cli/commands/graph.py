"""Explore the knowledge graph: find entities, inspect them, view provenance."""

import typer
from rich.table import Table

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require

app = typer.Typer(no_args_is_help=True, help="Knowledge-graph exploration.")


def _resolve(client: Client, name: str) -> str:
    matches = client.find_entities(name)
    if not matches:
        output.fail(f"no entity matching {name!r}")
    return matches[0]["key"]


@app.command("find")
def find(
    name: str = typer.Argument(..., help="Entity name or alias substring."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Find entities by name or alias."""
    cfg = require()
    try:
        with Client(cfg) as client:
            matches = client.find_entities(name)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(matches)
        return
    if not matches:
        output.console.print("no matches")
        return
    table = Table("key", "name", "type")
    for m in matches:
        table.add_row(m["key"], m["name"], m["type"])
    output.console.print(table)


@app.command("entity")
def entity(
    ref: str = typer.Argument(..., help="Entity key (type:name) or a name to resolve."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect an entity, its aliases, and its in-scope relationships."""
    cfg = require()
    try:
        with Client(cfg) as client:
            key = ref if ":" in ref else _resolve(client, ref)
            ent = client.get_entity(key)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(ent)
        return
    output.console.print(f"[bold]{ent['name']}[/bold] ({ent['type']})  {ent['key']}")
    if ent["aliases"]:
        output.console.print("aliases: " + ", ".join(ent["aliases"]))
    if ent["relationships"]:
        table = Table("predicate", "object")
        for rel in ent["relationships"]:
            table.add_row(rel["predicate"], rel["object_key"])
        output.console.print(table)


@app.command("history")
def history(
    key: str = typer.Argument(..., help="Entity key (type:name)."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show the in-scope mutation history (provenance) for an entity."""
    cfg = require()
    try:
        with Client(cfg) as client:
            rows = client.entity_history(key)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(rows)
        return
    if not rows:
        output.console.print("no history")
        return
    table = Table("seq", "actor", "op", "why")
    for row in rows:
        table.add_row(str(row["seq"]), row["actor"], row["op"], row["rationale"] or "")
    output.console.print(table)
