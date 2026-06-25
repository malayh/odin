"""Manage orgs, members, roles, and scopes."""

import typer

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require

app = typer.Typer(no_args_is_help=True, help="Org and membership administration.")


@app.command("create-user")
def create_user(
    email: str = typer.Option(..., "--email"),
    display_name: str | None = typer.Option(None, "--display-name"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = require()
    try:
        with Client(cfg) as client:
            user = client.create_user(email, display_name)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(user)
        return
    output.success(f"user {user['id']} ({user['email']})")


@app.command("create-org")
def create_org(
    name: str = typer.Option(..., "--name"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = require()
    try:
        with Client(cfg) as client:
            org = client.create_org(name)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(org)
        return
    output.success(f"org {org['id']} ({org['name']})")


@app.command("add-member")
def add_member(
    org_id: str = typer.Option(..., "--org-id"),
    user_id: str = typer.Option(..., "--user-id"),
    role: str = typer.Option("admin", "--role", help="admin | editor | viewer"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = require()
    try:
        with Client(cfg) as client:
            membership = client.add_member(org_id, user_id, role)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(membership)
        return
    output.success(f"{user_id} → {role} in {org_id}")


@app.command("create-token")
def create_token(
    user_id: str = typer.Option(..., "--user-id"),
    name: str | None = typer.Option(None, "--name"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = require()
    try:
        with Client(cfg) as client:
            token = client.create_token(user_id, name)
    except ApiError as e:
        output.fail(e.message)
    if json_out:
        output.print_json(token)
        return
    output.success(f"token for {user_id}:")
    output.console.print(token["token"])
