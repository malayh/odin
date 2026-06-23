"""Apache AGE access: LOAD on connect, a cypher() helper, and agtype parsing."""

import json
import re
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

_GRAPH_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SUFFIXES = ("::vertex", "::edge", "::path")


def register_age(sync_engine: Engine) -> None:
    @event.listens_for(sync_engine, "connect")
    def _load_age(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("LOAD 'age'")
        cur.close()


def _parse_agtype(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    s = raw
    for suffix in _SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s


async def cypher(
    session: AsyncSession,
    graph: str,
    query: str,
    params: dict[str, Any] | None = None,
    *,
    columns: tuple[str, ...] = ("v",),
) -> list[tuple[Any, ...]]:
    if not _GRAPH_RE.match(graph):
        raise ValueError(f"unsafe graph name: {graph!r}")
    coldefs = ", ".join(f"{c} agtype" for c in columns)
    sql = text(
        f"SELECT * FROM ag_catalog.cypher('{graph}', $cy${query}$cy$, "
        f"CAST(:age_args AS agtype)) AS ({coldefs})"
    )
    result = await session.execute(sql, {"age_args": json.dumps(params or {})})
    return [tuple(_parse_agtype(v) for v in row) for row in result.all()]
