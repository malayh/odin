"""Odin CLI entrypoint — a thin Typer app wrapping the Odin API.

Run with: ``uv run odin --help``
"""

import typer

from odin_cli.commands import admin, ask, graph, ingest, login, search

app = typer.Typer(no_args_is_help=True, help="Odin — the seeker of knowledge.")

app.add_typer(login.app, name="login")
app.add_typer(ingest.app, name="ingest")
app.add_typer(search.app, name="search")
app.add_typer(ask.app, name="ask")
app.add_typer(admin.app, name="admin")
app.add_typer(graph.app, name="graph")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
