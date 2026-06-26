"""Ask-eval harness: run a fixed question set through `odin ask` against the live
stack and record each grounded, cited answer for an LLM judge to grade.

Run from the repo ROOT, with the stack up, real provider keys set, and the
"Helios Robotics" corpus already ingested (see integration_test/run.py):

    docker compose up -d && just migrate
    just serve     # terminal 1
    just worker    # terminal 2
    uv run python integration_test/run.py     # ingest the corpus first
    uv run python integration_test/ask.py     # then this

The harness seeds/relogs the admin, resolves the org, then posts the cases to
POST /ask concurrently (up to ASK_CONCURRENCY at once, each with an extended
timeout — the real ask flow retrieves, reranks, and generates a grounded cited
answer over several LLM calls), prints a transcript, and writes
integration_test/ask_results.json. The cases span grounded
facts, deliberately conflicting facts (Odin surfaces both), off-corpus refusals,
scope isolation, alias resolution, and multi-hop inference over the denser corpus.
Each record carries an `expect` rubric so a judge can grade it. See
integration_test/ask_eval.md for the judging runbook.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from odin.db import SessionLocal
from odin.seed import seed_admin

HERE = Path(__file__).resolve().parent
CONFIG = HERE / ".odin_config.yaml"
RESULTS = HERE / "ask_results.json"
SERVER = os.environ.get("ODIN_SERVER", "http://localhost:8000")
ADMIN_EMAIL = "mara@helios.test"
ENV = {**os.environ, "ODIN_CONFIG": str(CONFIG)}
ASK_TIMEOUT = 240.0
ASK_CONCURRENCY = 3

CASES = [
    {
        "id": "grounded-ceo",
        "category": "grounded",
        "scope": "org",
        "question": "Who is the CEO of Helios?",
        "expect": "Mara Vance. Confident, with at least one org citation.",
    },
    {
        "id": "grounded-launch-customer",
        "category": "grounded",
        "scope": "org",
        "question": "Who is the launch customer for Project Atlas?",
        "expect": "Acme Logistics. Confident, with at least one org citation.",
    },
    {
        "id": "grounded-hq",
        "category": "grounded",
        "scope": "org",
        "question": "Where is Helios headquartered?",
        "expect": (
            "Austin (Austin HQ), with a secondary engineering office in Berlin. Confident + cited."
        ),
    },
    {
        "id": "grounded-atlas-lead",
        "category": "grounded",
        "scope": "org",
        "question": "Who leads Project Atlas engineering?",
        "expect": "Leo Zhang. Confident, with at least one org citation.",
    },
    {
        "id": "conflict-series-b",
        "category": "conflict",
        "scope": "org",
        "question": "How much was the Series B?",
        "expect": (
            "The corpus disagrees: $40M (board minutes) vs $45M (press release). A good answer "
            "surfaces BOTH figures rather than asserting one as fact."
        ),
    },
    {
        "id": "conflict-atlas-date",
        "category": "conflict",
        "scope": "org",
        "question": "When does Project Atlas ship?",
        "expect": (
            "The corpus disagrees: Q2 (board) vs Q3 (roadmap / engineering). A good answer "
            "surfaces BOTH dates and the disagreement, not a single committed date."
        ),
    },
    {
        "id": "conflict-dana-title",
        "category": "conflict",
        "scope": "org",
        "question": "What is Dana Okafor's title?",
        "expect": (
            "The corpus disagrees: CTO (board minutes) vs VP Engineering (company wiki). A good "
            "answer surfaces BOTH titles."
        ),
    },
    {
        "id": "conflict-vertex",
        "category": "conflict",
        "scope": "org",
        "question": "Is Vertex Dynamics a competitor or a potential partner?",
        "expect": (
            "The corpus frames Vertex Dynamics BOTH ways: a competitor (board / sales) and a "
            "potential partner for safety standards (offsite). A good answer surfaces both."
        ),
    },
    {
        "id": "refuse-sun",
        "category": "refuse",
        "scope": "org",
        "question": "Which way does the sun rise?",
        "expect": (
            "Off-corpus. Must refuse ('not in your knowledge base'), confident=false, no "
            "citations. Must NOT answer from world knowledge."
        ),
    },
    {
        "id": "refuse-capital",
        "category": "refuse",
        "scope": "org",
        "question": "What is the capital of France?",
        "expect": (
            "Off-corpus. Must refuse, confident=false, no citations. Must NOT answer 'Paris' from "
            "world knowledge."
        ),
    },
    {
        "id": "isolation-private-in-org",
        "category": "isolation",
        "scope": "org",
        "question": "What is Mara's candid private assessment of the team?",
        "expect": (
            "That assessment exists ONLY in personal scope. Asked in org scope it must refuse and "
            "leak none of the private content or any personal-scope citation."
        ),
    },
    {
        "id": "isolation-private-in-personal",
        "category": "grounded",
        "scope": "personal",
        "question": "What is Mara's candid private assessment of the team?",
        "expect": (
            "Control for the isolation case: in personal scope this SHOULD answer confidently "
            "with a personal citation (e.g. Dana strongest technical leader, Leo runs Atlas)."
        ),
    },
    {
        "id": "alias-northwind",
        "category": "alias",
        "scope": "org",
        "question": "Tell me about Northwind.",
        "expect": (
            "'Northwind' resolves to Northwind Capital: led the Series B and holds a Helios board "
            "seat. Confident, with at least one org citation."
        ),
    },
    {
        "id": "infer-nadia-reports",
        "category": "inference",
        "scope": "org",
        "question": "Who does Nadia Rahman ultimately report to?",
        "expect": (
            "Not stated in any one doc. Nadia Rahman reports to Leo Zhang, and Leo reports to "
            "Dana Okafor (org_chart). Correct answer: Dana Okafor, via Leo Zhang. Must traverse "
            "the reporting chain. Confident, with org citations."
        ),
    },
    {
        "id": "infer-atlas-risk-lead",
        "category": "inference",
        "scope": "org",
        "question": (
            "Who leads the team responsible for the biggest remaining technical risk to the "
            "Atlas launch?"
        ),
        "expect": (
            "Two hops: the biggest remaining Atlas risk is the gripper firmware "
            "(engineering_update / supply_chain_review); Nadia Rahman leads the gripper firmware "
            "team (org_chart). Answer: Nadia Rahman. Confident, with org citations."
        ),
    },
    {
        "id": "infer-shared-supplier",
        "category": "inference",
        "scope": "org",
        "question": "Does Helios share a supplier with any of its competitors?",
        "expect": (
            "Cross-doc: Meridian Robotics is the sole-source actuator supplier for the Atlas "
            "gripper (supply_chain_review); Vertex Dynamics also sources actuators from Meridian "
            "(competitive_intel). Answer: yes — Meridian Robotics supplies both Helios and the "
            "competitor Vertex Dynamics. Should cite both docs."
        ),
    },
    {
        "id": "infer-quanta-beacon",
        "category": "inference",
        "scope": "org",
        "question": (
            "If the Quanta Labs acquisition closes, whose technology would strengthen Project "
            "Beacon first?"
        ),
        "expect": (
            "Elena Sokolova founded Quanta Labs and built its perception stack "
            "(quanta_diligence_brief); Quanta perception folds into Beacon first "
            "(product_roadmap / engineering_update). Answer: Elena Sokolova's perception "
            "technology. Confident, with org citations."
        ),
    },
    {
        "id": "infer-investor-board-rep",
        "category": "inference",
        "scope": "org",
        "question": "Which board member represents Helios's largest investor?",
        "expect": (
            "Greta Holm is Northwind Capital's partner on the Helios board "
            "(quanta_diligence_brief); Northwind led the Series B (board_meeting / "
            "press_release), i.e. the lead investor. Answer: Greta Holm (Northwind Capital). "
            "Confident, with org citations."
        ),
    },
    {
        "id": "infer-acme-blocker",
        "category": "inference",
        "scope": "org",
        "question": "What single unresolved decision is blocking the Acme Logistics expansion?",
        "expect": (
            "The Acme expansion clause triggers only if Atlas ships by end of Q3 "
            "(customer_contract_summary); the Atlas ship date is unresolved (Q2 board vs Q3 "
            "roadmap). Answer: resolving the Atlas ship date. Must tie the clause to the open "
            "date, not just restate the conflict."
        ),
    },
    {
        "id": "isolation-quanta-timing-in-org",
        "category": "isolation",
        "scope": "org",
        "question": (
            "Is Mara planning to delay the Quanta Labs acquisition until after the Atlas launch?"
        ),
        "expect": (
            "That intention lives ONLY in Mara's personal board-prep notes ('I may stage it "
            "until after Atlas ships'). Quanta Labs and Greta Holm DO appear in org scope "
            "(diligence brief), so retrieval may surface the org brief — but it must NOT reveal "
            "Mara's private timing plan and must cite no personal doc."
        ),
    },
    {
        "id": "isolation-quanta-timing-in-personal",
        "category": "grounded",
        "scope": "personal",
        "question": (
            "Is Mara planning to delay the Quanta Labs acquisition until after the Atlas launch?"
        ),
        "expect": (
            "Control for the isolation case: in personal scope this SHOULD answer that yes, Mara "
            "is considering staging the Quanta acquisition until after Atlas ships "
            "(board_prep_notes), with a personal citation."
        ),
    },
]


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
            "  uv run python integration_test/run.py   # ingest the corpus\n"
        )


async def ask_case(
    http: httpx.AsyncClient, sem: asyncio.Semaphore, case: dict[str, Any]
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": case["id"],
        "category": case["category"],
        "scope": case["scope"],
        "question": case["question"],
        "expect": case["expect"],
    }
    try:
        async with sem:
            resp = await http.post("/ask", json={"question": case["question"]})
            resp.raise_for_status()
            data = resp.json()
        record |= {
            "answer": data["answer"],
            "confident": data["confident"],
            "citations": data["citations"],
            "error": None,
        }
    except Exception as e:
        record |= {"answer": None, "confident": None, "citations": [], "error": str(e)}
    return record


async def main() -> None:
    preflight()
    async with SessionLocal() as s:
        _, token = await seed_admin(s, ADMIN_EMAIL)
    cli("login", "--token", token, "--server", SERVER, "--json")
    print(f"admin: {ADMIN_EMAIL}\n")

    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(ASK_CONCURRENCY)
    async with httpx.AsyncClient(base_url=SERVER, headers=headers, timeout=ASK_TIMEOUT) as http:
        records = await asyncio.gather(*(ask_case(http, sem, case) for case in CASES))

    for record in records:
        cited = len(record["citations"])
        answer = record["answer"] or f"<error: {record['error']}>"
        print(f"[{record['category']}] {record['id']}  ({record['scope']})")
        print(f"  Q: {record['question']}")
        print(f"  confident={record['confident']}  citations={cited}")
        print(f"  A: {answer.strip()}\n")

    RESULTS.write_text(json.dumps(records, indent=2))
    print(f"wrote {len(records)} results -> {RESULTS}")
    print("Now judge them: see integration_test/ask_eval.md")


if __name__ == "__main__":
    asyncio.run(main())
