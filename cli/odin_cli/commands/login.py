"""Authenticate to an Odin server and store a token in ~/.odin/."""

import typer

app = typer.Typer(no_args_is_help=True, help="Authenticate to an Odin server.")
