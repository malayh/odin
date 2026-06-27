"""`odin graph` command tests (client faked, no server needed)."""

from odin_cli.commands import graph as graph_cmd
from odin_cli.config import Config
from odin_cli.main import app
from typer.testing import CliRunner


class _FakeClient:
    def __init__(self, **data):
        self._data = data

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

    def add_entity(self, type_, name, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "created entity"})

    def rename_entity(self, key, new_name, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "renamed"})

    def drop_entity(self, key, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "dropped entity"})

    def add_edge(self, subject_key, predicate, object_key, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "added edge"})

    def remove_edge(self, subject_key, predicate, object_key, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "removed edge"})

    def add_objective(self, text, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "created objective"})

    def list_objectives(self):
        return self._data.get("objectives", [])

    def drop_objective(self, objective_id, dry_run=False):
        return self._data.get("result", {"applied": not dry_run, "summary": "dropped objective"})


def _patch(monkeypatch, **data):
    monkeypatch.setattr(graph_cmd, "require", lambda: Config(token="odin_pat_x"))
    monkeypatch.setattr(graph_cmd, "Client", lambda cfg: _FakeClient(**data))


def test_entity_find(monkeypatch):
    _patch(monkeypatch, find=[{"key": "org:helios", "name": "Helios", "type": "Org"}])
    result = CliRunner().invoke(app, ["graph", "entity", "find", "helios"])
    assert result.exit_code == 0
    assert "org:helios" in result.output


def test_entity_find_json(monkeypatch):
    _patch(monkeypatch, find=[{"key": "org:helios", "name": "Helios", "type": "Org"}])
    result = CliRunner().invoke(app, ["graph", "entity", "find", "helios", "--json"])
    assert result.exit_code == 0
    assert '"org:helios"' in result.output


def test_entity_list(monkeypatch):
    _patch(monkeypatch, list=[{"key": "org:helios", "name": "Helios", "type": "Org"}])
    result = CliRunner().invoke(app, ["graph", "entity", "list"])
    assert result.exit_code == 0
    assert "org:helios" in result.output


def test_entity_show_resolves_name_to_key(monkeypatch):
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
    result = CliRunner().invoke(app, ["graph", "entity", "show", "helios"])
    assert result.exit_code == 0
    assert "BUILDS" in result.output
    assert "project:atlas" in result.output


def test_entity_show_tree(monkeypatch):
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
    result = CliRunner().invoke(app, ["graph", "entity", "show", "org:helios", "--tree"])
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
    result = CliRunner().invoke(app, ["graph", "entity", "history", "org:helios"])
    assert result.exit_code == 0
    assert "entity_create" in result.output


def test_entity_add(monkeypatch):
    _patch(monkeypatch, result={"applied": True, "summary": "created entity person:bob"})
    result = CliRunner().invoke(app, ["graph", "entity", "add", "person:Bob"])
    assert result.exit_code == 0
    assert "created entity person:bob" in result.output


def test_entity_add_requires_type(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(app, ["graph", "entity", "add", "Bob"])
    assert result.exit_code == 1


def test_entity_drop_dry_run(monkeypatch):
    _patch(
        monkeypatch,
        result={"applied": False, "summary": "would drop entity person:bob and detach its edges"},
    )
    result = CliRunner().invoke(app, ["graph", "entity", "drop", "person:bob", "--dry-run"])
    assert result.exit_code == 0
    assert "would drop entity" in result.output


def test_edge_add(monkeypatch):
    _patch(
        monkeypatch,
        result={"applied": True, "summary": "added edge person:bob -WORKS_AT-> org:helios"},
    )
    result = CliRunner().invoke(
        app, ["graph", "edge", "add", "person:bob", "WORKS_AT", "org:helios"]
    )
    assert result.exit_code == 0
    assert "added edge" in result.output


def test_objective_add(monkeypatch):
    _patch(monkeypatch, result={"applied": True, "summary": "created objective abc", "id": "abc"})
    result = CliRunner().invoke(app, ["graph", "objective", "add", "ship L5"])
    assert result.exit_code == 0
    assert "created objective" in result.output


def test_objective_list(monkeypatch):
    _patch(monkeypatch, objectives=[{"id": "abc", "text": "ship L5", "created_at": None}])
    result = CliRunner().invoke(app, ["graph", "objective", "list"])
    assert result.exit_code == 0
    assert "ship L5" in result.output
