"""The sleep-cycle verbs: `odin consolidate` and `odin dream` (async, single-flight)."""

import typer

from odin_cli import output
from odin_cli.commands.obj._common import client


def _render_status(result: dict, json_out: bool) -> None:
    if json_out:
        output.print_json(result)
        return
    run = result.get("run")
    if run is None:
        output.console.print("no runs yet")
        return
    line = f"{run['type']}: {run['state']}"
    if result.get("waiting_behind"):
        line += f" (waiting behind {result['waiting_behind']})"
    output.console.print(line)
    if run.get("stats"):
        output.print_json(run["stats"])
    if run.get("error"):
        output.console.print(f"[red]{run['error']}[/red]")


def _build(verb: str) -> typer.Typer:
    app = typer.Typer(no_args_is_help=False, help=f"Run the {verb} sleep phase (async).")

    @app.callback(invoke_without_command=True)
    def trigger(ctx: typer.Context, json_out: bool = typer.Option(False, "--json")) -> None:
        if ctx.invoked_subcommand is not None:
            return
        with client() as c:
            run = c.consolidate() if verb == "consolidate" else c.dream()
        if json_out:
            output.print_json(run)
            return
        output.success(f"{verb} queued (run {run['id']}) — check `odin {verb} status`")

    @app.command("status")
    def status(json_out: bool = typer.Option(False, "--json")) -> None:
        """Show the state of the latest run."""
        with client() as c:
            result = c.consolidate_status() if verb == "consolidate" else c.dream_status()
        _render_status(result, json_out)

    return app


consolidate_app = _build("consolidate")
dream_app = _build("dream")
