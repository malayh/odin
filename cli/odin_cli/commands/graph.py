"""Knowledge graph: explore and deterministically edit entities, edges, objectives."""

from collections import defaultdict
from typing import Any

import typer
from rich.table import Table
from rich.tree import Tree

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require

app = typer.Typer(no_args_is_help=True, help="Knowledge graph: explore and edit.")
entity_app = typer.Typer(no_args_is_help=True, help="Entities.")
edge_app = typer.Typer(no_args_is_help=True, help="Relationships.")
objective_app = typer.Typer(no_args_is_help=True, help="Objectives.")
app.add_typer(entity_app, name="entity")
app.add_typer(edge_app, name="edge")
app.add_typer(objective_app, name="objective")


def _resolve(client: Client, name: str) -> str:
    matches = client.find_entities(name)
    if not matches:
        output.fail(f"no entity matching {name!r}")
    return matches[0]["key"]


def _result(result: Any, json_out: bool) -> None:
    if json_out:
        output.print_json(result)
        return
    output.console.print(result["summary"])


def _render_tree(ent: dict) -> None:
    children: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in ent.get("subgraph", []):
        children[e["subject_key"]].append((e["predicate"], e["object_key"]))
    root = Tree(f"[bold]{ent['key']}[/bold]")
    seen = {ent["key"]}

    def _add(node: Tree, key: str) -> None:
        for predicate, obj in children.get(key, []):
            child = node.add(f"-{predicate}-> {obj}")
            if obj not in seen:
                seen.add(obj)
                _add(child, obj)

    _add(root, ent["key"])
    output.console.print(root)


@entity_app.command("find")
def entity_find(
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


@entity_app.command("list")
def entity_list(
    type_: str | None = typer.Option(None, "--type", help="Filter by entity type."),
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List entities you own."""
    cfg = require()
    try:
        with Client(cfg) as client:
            rows = client.list_entities(type_, limit, offset)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(rows)
        return
    if not rows:
        output.console.print("no entities")
        return
    table = Table("key", "name", "type")
    for m in rows:
        table.add_row(m["key"], m["name"], m["type"])
    output.console.print(table)


@entity_app.command("show")
def entity_show(
    ref: str = typer.Argument(..., help="Entity key (type:name) or a name to resolve."),
    depth: int = typer.Option(1, "--depth", help="Neighborhood depth."),
    tree: bool = typer.Option(False, "--tree", help="Render the neighborhood as a tree."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect an entity, its aliases, and its neighborhood."""
    cfg = require()
    try:
        with Client(cfg) as client:
            key = ref if ":" in ref else _resolve(client, ref)
            ent = client.get_entity(key, depth)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(ent)
        return
    output.console.print(f"[bold]{ent['name']}[/bold] ({ent['type']})  {ent['key']}")
    if ent["aliases"]:
        output.console.print("aliases: " + ", ".join(ent["aliases"]))
    if tree:
        _render_tree(ent)
    elif ent["relationships"]:
        table = Table("predicate", "object")
        for rel in ent["relationships"]:
            table.add_row(rel["predicate"], rel["object_key"])
        output.console.print(table)


@entity_app.command("history")
def entity_history(
    key: str = typer.Argument(..., help="Entity key (type:name)."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show the mutation history (provenance) for an entity."""
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


@entity_app.command("add")
def entity_add(
    ref: str = typer.Argument(..., help="<type>:<name>, e.g. person:Bob."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Create an entity (confirmed)."""
    if ":" not in ref:
        output.fail("entity must be <type>:<name>")
    type_, name = ref.split(":", 1)
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.add_entity(type_, name, dry_run)
    except ApiError as e:
        output.fail(e.message)
    _result(result, json_out)


@entity_app.command("rename")
def entity_rename(
    key: str = typer.Argument(..., help="Entity key (type:name)."),
    new_name: str = typer.Argument(..., help="New name."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Rename an entity (re-keys and re-points its edges)."""
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.rename_entity(key, new_name, dry_run)
    except ApiError as e:
        output.fail(e.message)
    _result(result, json_out)


@entity_app.command("drop")
def entity_drop(
    key: str = typer.Argument(..., help="Entity key (type:name)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Delete an entity and detach its edges."""
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.drop_entity(key, dry_run)
    except ApiError as e:
        output.fail(e.message)
    _result(result, json_out)


@edge_app.command("add")
def edge_add(
    subject: str = typer.Argument(..., help="Subject entity key."),
    predicate: str = typer.Argument(..., help="Predicate."),
    obj: str = typer.Argument(..., help="Object entity key."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Create a relationship between two entities."""
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.add_edge(subject, predicate, obj, dry_run)
    except ApiError as e:
        output.fail(e.message)
    _result(result, json_out)


@edge_app.command("rm")
def edge_rm(
    subject: str = typer.Argument(..., help="Subject entity key."),
    predicate: str = typer.Argument(..., help="Predicate."),
    obj: str = typer.Argument(..., help="Object entity key."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a relationship between two entities."""
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.remove_edge(subject, predicate, obj, dry_run)
    except ApiError as e:
        output.fail(e.message)
    _result(result, json_out)


@objective_app.command("add")
def objective_add(
    text: str = typer.Argument(..., help="The objective text."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Declare an objective."""
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.add_objective(text, dry_run)
    except ApiError as e:
        output.fail(e.message)
    _result(result, json_out)


@objective_app.command("list")
def objective_list(json_out: bool = typer.Option(False, "--json")) -> None:
    """List your objectives."""
    cfg = require()
    try:
        with Client(cfg) as client:
            rows = client.list_objectives()
    except ApiError as e:
        output.fail(e.message)
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


@objective_app.command("drop")
def objective_drop(
    objective_id: str = typer.Argument(..., help="Objective id."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Drop an objective."""
    cfg = require()
    try:
        with Client(cfg) as client:
            result = client.drop_objective(objective_id, dry_run)
    except ApiError as e:
        output.fail(e.message)
    _result(result, json_out)
