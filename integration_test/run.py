"""Integration harness: ingest the CEO-notes corpus through the Odin CLI, then
observe the knowledge graph it produced.

Run from the repo ROOT, with the stack up and real provider keys set:

    docker compose up -d && just migrate
    just serve     # terminal 1
    just worker    # terminal 2
    uv run python integration_test/run.py

The harness seeds an admin, logs in, creates the "Helios Robotics" org, ingests
the personal and org corpora via `odin ingest`, then reports documents, chunks,
entities, relationships, aliases, sample searches, and a
scope-isolation spot-check.
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
from odin.models import Chunk, Document, Org
from odin.seed import seed_admin
from odin.services import resolution
from sqlalchemy import func, select

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
CONFIG = HERE / ".odin_config.yaml"
SERVER = os.environ.get("ODIN_SERVER", "http://localhost:8000")
ADMIN_EMAIL = "mara@helios.test"
ORG_NAME = "Helios Robotics"
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


async def ensure_org() -> str:
    try:
        return cli("admin", "create-org", "--name", ORG_NAME, "--json")["id"]
    except RuntimeError as e:
        if "already exists" not in str(e):
            raise
    async with SessionLocal() as s:
        org = await s.scalar(select(Org).where(Org.name == ORG_NAME))
    return str(org.id)


def report_ingest(results: Any) -> None:
    for r in results:
        print(f"  {r['key']:34} {r['state']}")
    states = [r["state"] for r in results]
    other = [st for st in states if st not in ("done", "deduped")]
    print(f"  -> {states.count('done')} done, {states.count('deduped')} deduped", end="")
    print(f", {len(other)} other: {other}\n" if other else "\n")


async def observe(org_id: str) -> None:
    async with SessionLocal() as s:
        doc_rows = (
            await s.execute(
                select(Document.scope_type, Document.state, func.count()).group_by(
                    Document.scope_type, Document.state
                )
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
            "RETURN a.key, r.predicate, b.key, r.scope_type, r.confidence",
            columns=("sub", "pred", "obj", "scope", "conf"),
        )
        aliases = await cypher(
            s,
            GRAPH,
            "MATCH (:Document)-[m:MENTIONS]->(e:Entity) RETURN e.key, m.alias",
            columns=("key", "alias"),
        )

    print("== documents ==")
    for scope_type, state, n in doc_rows:
        print(f"  {scope_type.value:9} {state.value:9} {n}")
    print(f"  chunks: {chunks}\n")

    print(f"== entities ({len(entities)}) ==")
    for key, _name, typ in sorted(entities, key=lambda e: (str(e[2]), str(e[0]))):
        print(f"  {typ:12} {key}")
    print()

    print(f"== relationships ({len(rels)}) ==")
    for sub, pred, obj, scope, conf in sorted(rels, key=lambda r: (str(r[3]), str(r[0]))):
        print(f"  [{scope}] {sub} -{pred}-> {obj}  ({conf})")
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

    print("== search samples ==")
    samples = [
        ("When does Project Atlas ship?", f"org:{org_id}"),
        ("How much was the Series B?", f"org:{org_id}"),
        ("my candid take on the team", "personal"),
    ]
    for q, scope in samples:
        hits = cli("search", q, "--scope", scope, "--top-k", "3", "--json")["hits"]
        print(f"  [{scope}] {q!r}")
        for h in hits:
            print(f"     {h['score']:.3f}  {h['text'][:70].strip()!r}")
    print()

    print("== isolation spot-check ==")
    q = "Series B from Northwind Capital"
    org_hits = cli("search", q, "--scope", f"org:{org_id}", "--top-k", "5", "--json")["hits"]
    per_hits = cli("search", q, "--scope", "personal", "--top-k", "5", "--json")["hits"]
    leaks = [h for h in org_hits if h["scope_type"] != "org"]
    leaks += [h for h in per_hits if h["scope_type"] != "personal"]
    org_ok = all(h["scope_type"] == "org" for h in org_hits)
    per_ok = all(h["scope_type"] == "personal" for h in per_hits)
    print(f"  org query      -> {len(org_hits)} hits, all org?      {org_ok}")
    print(f"  personal query -> {len(per_hits)} hits, all personal? {per_ok}")
    print(f"  RESULT: {'OK — no cross-scope leakage' if not leaks else f'LEAK: {leaks}'}")


async def main() -> None:
    preflight()
    async with SessionLocal() as s:
        user, token = await seed_admin(s, ADMIN_EMAIL)
        user_id = str(user.id)

    cli("login", "--token", token, "--server", SERVER, "--json")
    org_id = await ensure_org()
    print(f"admin: {ADMIN_EMAIL} ({user_id})")
    print(f"org:   {ORG_NAME} ({org_id})\n")

    print("== ingest: personal ==")
    report_ingest(cli("ingest", "-d", str(CORPUS / "personal"), "--scope", "personal", "--json"))
    print("== ingest: org ==")
    report_ingest(cli("ingest", "-d", str(CORPUS / "org"), "--scope", f"org:{org_id}", "--json"))

    print("== consolidate ==")
    async with SessionLocal() as s:
        n_personal = await resolution.consolidate(s, "personal", user_id)
        n_org = await resolution.consolidate(s, "org", org_id)
        await s.commit()
    print(f"  personal: {n_personal} merges, org: {n_org} merges\n")

    await observe(org_id)


if __name__ == "__main__":
    asyncio.run(main())
