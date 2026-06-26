"""Procrastinate app: the psycopg3-backed task queue (connector + task registry)."""

from procrastinate import App, PsycopgConnector

from odin.config import get_settings


def _conninfo() -> str:
    return get_settings().database_url.replace("+psycopg", "")


app = App(
    connector=PsycopgConnector(conninfo=_conninfo()),
    import_paths=["odin.worker.tasks"],
)
