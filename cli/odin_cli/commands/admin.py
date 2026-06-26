"""Manage users and tokens (initial-admin only)."""

import typer

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require

app = typer.Typer(no_args_is_help=True, help="User and token administration.")


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
