"""Shared helpers for the `odin obj` command group."""

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from odin_cli import output
from odin_cli.client import ApiError, Client
from odin_cli.config import require


@contextmanager
def client() -> Iterator[Client]:
    cfg = require()
    try:
        with Client(cfg) as c:
            yield c
    except ApiError as e:
        output.fail(e.message)


def result_out(result: dict[str, Any], json_out: bool) -> None:
    if json_out:
        output.print_json(result)
        return
    output.console.print(result["summary"])


def load_body(body: str | None) -> dict[str, Any] | None:
    if body is None:
        return None
    if body == "-":
        raw = sys.stdin.read()
    elif body.startswith("@"):
        raw = Path(body[1:]).read_text(encoding="utf-8")
    else:
        raw = body
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        output.fail(f"invalid JSON body: {e}")
    if not isinstance(data, dict):
        output.fail("body must be a JSON object")
    return data


_SCHEMA_ROUTES: dict[str, dict[str, tuple[str, str]]] = {
    "entity": {
        "create": ("post", "/graph/entities"),
        "update": ("patch", "/graph/entities/{key}"),
    },
    "edge": {"create": ("post", "/graph/edges")},
    "objective": {"create": ("post", "/graph/objectives")},
}


def print_schema(object_name: str, which: str) -> None:
    routes = _SCHEMA_ROUTES.get(object_name, {})
    if which not in routes:
        output.fail(f"{object_name} has no {which} schema")
    method, path = routes[which]
    with client() as c:
        spec = c.openapi()
    schema = _request_schema(spec, path, method)
    if schema is None:
        output.fail(f"no request schema for {method.upper()} {path}")
    output.print_json(schema)


def _request_schema(spec: dict[str, Any], path: str, method: str) -> Any:
    op = spec.get("paths", {}).get(path, {}).get(method, {})
    content = op.get("requestBody", {}).get("content", {}).get("application/json", {})
    schema = content.get("schema")
    if schema is None:
        return None
    return _inline_refs(schema, spec, set())


def _inline_refs(node: Any, spec: dict[str, Any], seen: set[str]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if ref is not None:
            if ref in seen:
                return {"$ref": ref}
            return _inline_refs(_resolve_ref(spec, ref), spec, seen | {ref})
        return {k: _inline_refs(v, spec, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_refs(v, spec, seen) for v in node]
    return node


def _resolve_ref(spec: dict[str, Any], ref: str) -> Any:
    node: Any = spec
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node
