"""Authenticate to an Odin server and store a token in ~/.odin/."""

import typer

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import DEFAULT_SERVER, Config, save

app = typer.Typer(no_args_is_help=True, help="Authenticate to an Odin server.")


@app.callback(invoke_without_command=True)
def login(
    token: str = typer.Option(..., "--token", "-t", help="Personal access token."),
    server: str = typer.Option(DEFAULT_SERVER, "--server", "-s", help="Odin server URL."),
    scope: str = typer.Option("personal", "--scope", help="Default scope for commands."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    cfg = Config(server_url=server, token=token, default_scope=scope)
    try:
        with Client(cfg) as client:
            me = client.whoami()
    except ApiError as e:
        output.fail(e.message)
    save(cfg)
    if json_out:
        output.print_json(me)
        return
    output.success(f"logged in as {me['user']['email']} → {server}")
