"""The `odin obj` command group: CRUD over knowledge objects."""

import typer

from odin_cli.commands.obj import document, edge, entity, job, objective

app = typer.Typer(no_args_is_help=True, help="Knowledge objects: create, read, update, delete.")
app.add_typer(entity.app, name="entity")
app.add_typer(edge.app, name="edge")
app.add_typer(objective.app, name="objective")
app.add_typer(document.app, name="document")
app.add_typer(job.app, name="job")
