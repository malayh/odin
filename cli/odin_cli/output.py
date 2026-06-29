"""Output rendering: human-readable (Rich) by default; --json for scripting."""

import json
from typing import Any, NoReturn

import typer
from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def print_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


def fail(message: str) -> NoReturn:
    err_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(1)


def success(message: str) -> None:
    console.print(f"[green]{message}[/green]")


def thinking(message: str = "thinking…"):
    return console.status(message, spinner="dots")
