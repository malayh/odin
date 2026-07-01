"""`odin obj` command tests (client faked, no server needed)."""

import json

from odin_cli.commands.obj import _common
from odin_cli.config import Config
from odin_cli.main import app
from typer.testing import CliRunner

_OPENAPI = {
    "paths": {
        "/graph/entities": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/EntityIn"}}
                    }
                }
            }
        },
        "/graph/entities/{key}": {
            "patch": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/EntityRenameIn"}
                        }
                    }
                }
            }
        },
    },
    "components": {
        "schemas": {
            "EntityIn": {
                "type": "object",
                "properties": {"type": {"type": "string"}, "name": {"type": "string"}},
                "required": ["type", "name"],
            },
            "EntityRenameIn": {
                "type": "object",
                "properties": {"new_name": {"type": "string"}},
                "required": ["new_name"],
            },
        }
    },
}


class _FakeClient:
    def __init__(self, **data):
        self._data = data
        self.calls = data.setdefault("_calls", {})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def find_entities(self, q):
        return self._data.get("find", [])

    def list_entities(self, type_=None, limit=50, offset=0):
        return self._data.get("list", [])

    def get_entity(self, key, depth=1):
        return self._data["entity"]

    def entity_history(self, key):
        return self._data.get("history", [])

    def create_entity(self, body, dry_run=False):
        self.calls["create_entity"] = (body, dry_run)
        return self._data.get("result", {"applied": not dry_run, "summary": "created entity"})

    def update_entity(self, key, body, dry_run=False):
        self.calls["update_entity"] = (key, body, dry_run)
        return self._data.get("result", {"applied": not dry_run, "summary": "renamed"})

    def delete_entity(self, key, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "dropped entity"})

    def create_edge(self, body, dry_run=False):
        self.calls["create_edge"] = (body, dry_run)
        return self._data.get("result", {"applied": not dry_run, "summary": "added edge"})

    def delete_edge(self, subject_key, predicate, object_key, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "removed edge"})

    def create_objective(self, body, dry_run=False):
        self.calls["create_objective"] = (body, dry_run)
        return self._data.get("result", {"applied": not dry_run, "summary": "created objective"})

    def list_objectives(self):
        return self._data.get("objectives", [])

    def get_objective(self, objective_id):
        return self._data["objective"]

    def delete_objective(self, objective_id, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "dropped objective"})

    def list_documents(self, state=None, type_=None, limit=50, offset=0):
        self.calls["list_documents"] = (state, type_, limit, offset)
        return self._data.get("documents", [])

    def get_document(self, doc_id):
        return self._data["document"]

    def delete_document(self, doc_id, dry_run=False):
        return self._data.get(
            "result", {"applied": not dry_run, "summary": "soft-deleted document"}
        )

    def list_jobs(self, state=None, limit=50, offset=0):
        self.calls["list_jobs"] = (state, limit, offset)
        return self._data.get("jobs", [])

    def get_job(self, job_id):
        return self._data["job"]

    def openapi(self):
        return self._data.get("openapi", _OPENAPI)


def _patch(monkeypatch, **data):
    fake = _FakeClient(**data)
    monkeypatch.setattr(_common, "require", lambda: Config(token="odin_pat_x"))
    monkeypatch.setattr(_common, "Client", lambda cfg: fake)
    return fake


def test_entity_list_match(monkeypatch):
    _patch(monkeypatch, find=[{"key": "org:helios", "name": "Helios", "type": "Org"}])
    result = CliRunner().invoke(app, ["obj", "entity", "list", "--match", "helios"])
    assert result.exit_code == 0
    assert "org:helios" in result.output


def test_entity_list(monkeypatch):
    _patch(monkeypatch, list=[{"key": "org:helios", "name": "Helios", "type": "Org"}])
    result = CliRunner().invoke(app, ["obj", "entity", "list"])
    assert result.exit_code == 0
    assert "org:helios" in result.output


def test_entity_list_json(monkeypatch):
    _patch(monkeypatch, list=[{"key": "org:helios", "name": "Helios", "type": "Org"}])
    result = CliRunner().invoke(app, ["obj", "entity", "list", "--json"])
    assert result.exit_code == 0
    assert '"org:helios"' in result.output


def test_entity_get_resolves_name_to_key(monkeypatch):
    _patch(
        monkeypatch,
        find=[{"key": "org:helios", "name": "Helios", "type": "Org"}],
        entity={
            "key": "org:helios",
            "name": "Helios",
            "type": "Org",
            "aliases": ["Helios Inc."],
            "relationships": [
                {"predicate": "BUILDS", "object_key": "project:atlas", "source_doc_id": None}
            ],
            "subgraph": [],
        },
    )
    result = CliRunner().invoke(app, ["obj", "entity", "get", "helios"])
    assert result.exit_code == 0
    assert "BUILDS" in result.output
    assert "project:atlas" in result.output


def test_entity_get_tree(monkeypatch):
    _patch(
        monkeypatch,
        entity={
            "key": "org:helios",
            "name": "Helios",
            "type": "Org",
            "aliases": [],
            "relationships": [],
            "subgraph": [
                {"subject_key": "org:helios", "predicate": "BUILDS", "object_key": "project:atlas"}
            ],
        },
    )
    result = CliRunner().invoke(app, ["obj", "entity", "get", "org:helios", "--tree"])
    assert result.exit_code == 0
    assert "project:atlas" in result.output


def test_entity_history(monkeypatch):
    _patch(
        monkeypatch,
        history=[
            {
                "seq": 1,
                "actor": "extractor",
                "op": "entity_create",
                "payload": {},
                "rationale": None,
                "confidence": 0.9,
                "created_at": "2026-01-01T00:00:00Z",
            }
        ],
    )
    result = CliRunner().invoke(app, ["obj", "entity", "history", "org:helios"])
    assert result.exit_code == 0
    assert "entity_create" in result.output


def test_entity_create(monkeypatch):
    fake = _patch(monkeypatch, result={"applied": True, "summary": "created entity person:bob"})
    result = CliRunner().invoke(app, ["obj", "entity", "create", "person:Bob"])
    assert result.exit_code == 0
    assert "created entity person:bob" in result.output
    assert fake.calls["create_entity"] == ({"type": "person", "name": "Bob"}, False)


def test_entity_create_requires_type(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(app, ["obj", "entity", "create", "Bob"])
    assert result.exit_code == 1


def test_entity_create_body_inline(monkeypatch):
    fake = _patch(monkeypatch, result={"applied": True, "summary": "created entity"})
    result = CliRunner().invoke(
        app, ["obj", "entity", "create", "--body", '{"type": "person", "name": "Bob"}']
    )
    assert result.exit_code == 0
    assert fake.calls["create_entity"] == ({"type": "person", "name": "Bob"}, False)


def test_entity_create_body_stdin(monkeypatch):
    fake = _patch(monkeypatch, result={"applied": True, "summary": "created entity"})
    result = CliRunner().invoke(
        app, ["obj", "entity", "create", "--body", "-"], input='{"type": "org", "name": "Acme"}'
    )
    assert result.exit_code == 0
    assert fake.calls["create_entity"] == ({"type": "org", "name": "Acme"}, False)


def test_entity_create_body_invalid_json(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(app, ["obj", "entity", "create", "--body", "{not json"])
    assert result.exit_code == 1
    assert "invalid JSON" in result.output


def test_entity_update(monkeypatch):
    fake = _patch(monkeypatch, result={"applied": True, "summary": "renamed"})
    result = CliRunner().invoke(
        app, ["obj", "entity", "update", "person:bob", "--new-name", "Bobby"]
    )
    assert result.exit_code == 0
    assert fake.calls["update_entity"] == ("person:bob", {"new_name": "Bobby"}, False)


def test_entity_update_requires_input(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(app, ["obj", "entity", "update", "person:bob"])
    assert result.exit_code == 1


def test_entity_delete_dry_run(monkeypatch):
    _patch(
        monkeypatch,
        result={"applied": False, "summary": "would drop entity person:bob and detach its edges"},
    )
    result = CliRunner().invoke(app, ["obj", "entity", "delete", "person:bob", "--dry-run"])
    assert result.exit_code == 0
    assert "would drop entity" in result.output


def test_entity_schema_create(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(app, ["obj", "entity", "schema", "--create"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["properties"]["name"]["type"] == "string"
    assert "$ref" not in result.output


def test_entity_schema_update(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(app, ["obj", "entity", "schema", "--update"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "new_name" in payload["properties"]


def test_edge_create(monkeypatch):
    fake = _patch(
        monkeypatch,
        result={"applied": True, "summary": "added edge person:bob -WORKS_AT-> org:helios"},
    )
    result = CliRunner().invoke(
        app, ["obj", "edge", "create", "person:bob", "WORKS_AT", "org:helios"]
    )
    assert result.exit_code == 0
    assert "added edge" in result.output
    assert fake.calls["create_edge"][0] == {
        "subject_key": "person:bob",
        "predicate": "WORKS_AT",
        "object_key": "org:helios",
    }


def test_edge_create_requires_args(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(app, ["obj", "edge", "create", "person:bob"])
    assert result.exit_code == 1


def test_objective_create(monkeypatch):
    fake = _patch(
        monkeypatch, result={"applied": True, "summary": "created objective abc", "id": "abc"}
    )
    result = CliRunner().invoke(app, ["obj", "objective", "create", "ship L5"])
    assert result.exit_code == 0
    assert "created objective" in result.output
    assert fake.calls["create_objective"][0] == {"text": "ship L5"}


def test_objective_list(monkeypatch):
    _patch(monkeypatch, objectives=[{"id": "abc", "text": "ship L5", "created_at": None}])
    result = CliRunner().invoke(app, ["obj", "objective", "list"])
    assert result.exit_code == 0
    assert "ship L5" in result.output


def test_objective_get(monkeypatch):
    _patch(monkeypatch, objective={"id": "abc", "text": "ship L5", "created_at": None})
    result = CliRunner().invoke(app, ["obj", "objective", "get", "abc"])
    assert result.exit_code == 0
    assert "ship L5" in result.output


def test_document_list(monkeypatch):
    fake = _patch(
        monkeypatch,
        documents=[
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "key": "notes.md",
                "doc_type": "source",
                "state": "indexed",
                "version": 1,
            }
        ],
    )
    result = CliRunner().invoke(app, ["obj", "document", "list", "--state", "indexed"])
    assert result.exit_code == 0
    assert "notes.md" in result.output
    assert fake.calls["list_documents"] == ("indexed", None, 50, 0)


def test_document_get(monkeypatch):
    _patch(
        monkeypatch,
        document={
            "id": "11111111-1111-1111-1111-111111111111",
            "key": "notes.md",
            "doc_type": "source",
            "state": "indexed",
            "version": 2,
        },
    )
    result = CliRunner().invoke(
        app, ["obj", "document", "get", "11111111-1111-1111-1111-111111111111"]
    )
    assert result.exit_code == 0
    assert "notes.md" in result.output


def test_document_delete(monkeypatch):
    _patch(monkeypatch, result={"applied": True, "summary": "soft-deleted document"})
    result = CliRunner().invoke(
        app, ["obj", "document", "delete", "11111111-1111-1111-1111-111111111111"]
    )
    assert result.exit_code == 0
    assert "soft-deleted document" in result.output


def test_job_list(monkeypatch):
    fake = _patch(
        monkeypatch,
        jobs=[
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "type": "ingest",
                "state": "done",
                "attempts": 1,
                "error": None,
            }
        ],
    )
    result = CliRunner().invoke(app, ["obj", "job", "list"])
    assert result.exit_code == 0
    assert "ingest" in result.output
    assert fake.calls["list_jobs"] == (None, 50, 0)


def test_job_get(monkeypatch):
    _patch(
        monkeypatch,
        job={
            "id": "22222222-2222-2222-2222-222222222222",
            "type": "ingest",
            "state": "failed",
            "attempts": 3,
            "error": "boom",
        },
    )
    result = CliRunner().invoke(app, ["obj", "job", "get", "22222222-2222-2222-2222-222222222222"])
    assert result.exit_code == 0
    assert "failed" in result.output
    assert "boom" in result.output
