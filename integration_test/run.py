"""Integration harness: ingest the CEO-notes corpus through the Odin CLI, then
observe the knowledge graph it produced.

Run from the repo ROOT, with the stack up and real provider keys set:

    docker compose up -d && just migrate
    just serve     # terminal 1
    just worker    # terminal 2
    uv run python integration_test/run.py

The harness seeds an admin, logs in, ingests the whole corpus into the admin's
single brain via `odin ingest`, consolidates, then reports documents, chunks,
entities, relationships, aliases, and sample searches.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from odin.config import get_settings
from odin.db import SessionLocal
from odin.graphdb import cypher
from odin.models import Chunk, Document
from odin.seed import seed_admin
from odin.services import resolution
from sqlalchemy import func, select

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
CONFIG = HERE / ".odin_config.yaml"
SERVER = os.environ.get("ODIN_SERVER", "http://localhost:8000")
ADMIN_EMAIL = "mara@helios.test"
ENV = {**os.environ, "ODIN_CONFIG": str(CONFIG)}
GRAPH = get_settings().age_graph


def cli(*args: str) -> Any:
    proc = subprocess.run(
        [sys.executable, "-m", "odin_cli.main", *args],
        capture_output=True,
        text=True,
        env=ENV,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"`odin {' '.join(args)}` failed:\n{proc.stderr.strip()}")
    out = proc.stdout.strip()
    return json.loads(out) if out else None


def preflight() -> None:
    try:
        httpx.get(f"{SERVER}/health", timeout=5.0).raise_for_status()
    except Exception as e:
        sys.exit(
            f"cannot reach the Odin API at {SERVER} ({e}).\n"
            "Bring up the stack first:\n"
            "  docker compose up -d && just migrate\n"
            "  just serve   # terminal 1\n"
            "  just worker  # terminal 2\n"
        )


def report_ingest(results: Any) -> None:
    for r in results:
        print(f"  {r['key']:34} {r['state']}")
    states = [r["state"] for r in results]
    other = [st for st in states if st not in ("done", "deduped")]
    print(f"  -> {states.count('done')} done, {states.count('deduped')} deduped", end="")
    print(f", {len(other)} other: {other}\n" if other else "\n")


async def observe() -> None:
    async with SessionLocal() as s:
        doc_rows = (
            await s.execute(
                select(Document.state, func.count()).group_by(Document.state)
            )
        ).all()
        chunks = await s.scalar(select(func.count()).select_from(Chunk))
        entities = await cypher(
            s,
            GRAPH,
            "MATCH (e:Entity) RETURN e.key, e.name, e.type",
            columns=("key", "name", "type"),
        )
        rels = await cypher(
            s,
            GRAPH,
            "MATCH (a:Entity)-[r:REL]->(b:Entity) "
            "RETURN a.key, r.predicate, b.key, r.confidence",
            columns=("sub", "pred", "obj", "conf"),
        )
        aliases = await cypher(
            s,
            GRAPH,
            "MATCH (:Document)-[m:MENTIONS]->(e:Entity) RETURN e.key, m.alias",
            columns=("key", "alias"),
        )
        objs = await cypher(
            s,
            GRAPH,
            "MATCH (o:Objective) RETURN o.text, o.origin, o.trust, o.confidence",
            columns=("text", "origin", "trust", "confidence"),
        )

    print("== documents ==")
    for state, n in doc_rows:
        print(f"  {state.value:9} {n}")
    print(f"  chunks: {chunks}\n")

    print(f"== entities ({len(entities)}) ==")
    for key, _name, typ in sorted(entities, key=lambda e: (str(e[2]), str(e[0]))):
        print(f"  {typ:12} {key}")
    print()

    print(f"== relationships ({len(rels)}) ==")
    for sub, pred, obj, conf in sorted(rels, key=lambda r: (str(r[0]), str(r[1]))):
        print(f"  {sub} -{pred}-> {obj}  ({conf})")
    print()

    alias_map: dict[str, set[str]] = {}
    for key, alias in aliases:
        if alias:
            alias_map.setdefault(key, set()).add(alias)
    multi = {k: v for k, v in alias_map.items() if len(v) > 1}
    print(f"== entities resolved from multiple surface forms ({len(multi)}) ==")
    for key, al in sorted(multi.items()):
        print(f"  {key}: {sorted(al)}")
    print()

    inferred = [o for o in objs if o[1] == "inferred"]
    print(f"== objectives inferred from content ({len(inferred)}) ==")
    for text, _origin, trust, conf in sorted(objs, key=lambda o: -(o[3] or 0)):
        print(f"  [{trust}] ({conf})  {text}")
    print()

    print("== search samples ==")
    samples = [
        "When does Project Atlas ship?",
        "How much was the Series B?",
        "my candid take on the team",
    ]
    for q in samples:
        hits = cli("search", q, "--top-k", "3", "--json")["hits"]
        print(f"  {q!r}")
        for h in hits:
            print(f"     {h['score']:.3f}  {h['text'][:70].strip()!r}")
    print()


async def main() -> None:
    preflight()
    async with SessionLocal() as s:
        user, token = await seed_admin(s, ADMIN_EMAIL)
        user_id = user.id

    cli("login", "--token", token, "--server", SERVER, "--json")
    print(f"admin: {ADMIN_EMAIL} ({user_id})\n")

    print("== ingest: corpus ==")
    report_ingest(cli("ingest", "-d", str(CORPUS), "--json"))

    print("== consolidate ==")
    async with SessionLocal() as s:
        n = await resolution.consolidate(s, user_id)
        await s.commit()
    print(f"  {n} merges\n")

    await observe()


if __name__ == "__main__":
    asyncio.run(main())
