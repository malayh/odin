"""Odin CLI entrypoint — a thin Typer app wrapping the Odin API.

Run with: ``uv run odin --help``
"""

import typer

from odin_cli.commands import admin, ask, ingest, login, obj, search, sleep

app = typer.Typer(no_args_is_help=True, help="Odin — the seeker of knowledge.")

app.add_typer(login.app, name="login")
app.add_typer(ingest.app, name="ingest")
app.command("search")(search.search)
app.command("ask")(ask.ask)
app.add_typer(admin.app, name="admin")
app.add_typer(obj.app, name="obj")
app.add_typer(sleep.consolidate_app, name="consolidate")
app.add_typer(sleep.dream_app, name="dream")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
