"""Entities: explore and deterministically edit."""

from collections import defaultdict

import typer
from rich.table import Table
from rich.tree import Tree

from odin_cli import output
from odin_cli.commands.obj._common import client, load_body, print_schema, result_out

app = typer.Typer(no_args_is_help=True, help="Entities.")


def _resolve(c, name: str) -> str:
    matches = c.find_entities(name)
    if not matches:
        output.fail(f"no entity matching {name!r}")
    return matches[0]["key"]


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


@app.command("list")
def entity_list(
    match: str | None = typer.Option(None, "--match", help="Name/alias substring search."),
    type_: str | None = typer.Option(None, "--type", help="Filter by entity type."),
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List entities (use --match to search by name/alias)."""
    with client() as c:
        rows = c.find_entities(match) if match else c.list_entities(type_, limit, offset)
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


@app.command("get")
def entity_get(
    ref: str = typer.Argument(..., help="Entity key (type:name) or a name to resolve."),
    depth: int = typer.Option(1, "--depth", help="Neighborhood depth."),
    tree: bool = typer.Option(False, "--tree", help="Render the neighborhood as a tree."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect an entity, its aliases, and its neighborhood."""
    with client() as c:
        key = ref if ":" in ref else _resolve(c, ref)
        ent = c.get_entity(key, depth)
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


@app.command("history")
def entity_history(
    key: str = typer.Argument(..., help="Entity key (type:name)."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show the mutation history (provenance) for an entity."""
    with client() as c:
        rows = c.entity_history(key)
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


@app.command("create")
def entity_create(
    ref: str | None = typer.Argument(None, help="<type>:<name>, e.g. person:Bob."),
    body: str | None = typer.Option(None, "--body", help="JSON body: @file, '-' stdin, or inline."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Create an entity."""
    payload = load_body(body)
    if payload is None:
        if not ref or ":" not in ref:
            output.fail("entity must be <type>:<name> (or pass --body)")
        type_, name = ref.split(":", 1)
        payload = {"type": type_, "name": name}
    with client() as c:
        result = c.create_entity(payload, dry_run)
    result_out(result, json_out)


@app.command("update")
def entity_update(
    key: str = typer.Argument(..., help="Entity key (type:name)."),
    new_name: str | None = typer.Option(None, "--new-name", help="New name."),
    body: str | None = typer.Option(None, "--body", help="JSON body: @file, '-' stdin, or inline."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Update an entity (rename; re-keys and re-points its edges)."""
    payload = load_body(body)
    if payload is None:
        if not new_name:
            output.fail("provide --new-name (or --body)")
        payload = {"new_name": new_name}
    with client() as c:
        result = c.update_entity(key, payload, dry_run)
    result_out(result, json_out)


@app.command("delete")
def entity_delete(
    key: str = typer.Argument(..., help="Entity key (type:name)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Delete an entity and detach its edges."""
    with client() as c:
        result = c.delete_entity(key, dry_run)
    result_out(result, json_out)


@app.command("schema")
def entity_schema(
    create: bool = typer.Option(False, "--create", help="Show the create schema (default)."),
    update: bool = typer.Option(False, "--update", help="Show the update schema."),
) -> None:
    """Print the JSON schema for create/update bodies."""
    print_schema("entity", "update" if update else "create")
