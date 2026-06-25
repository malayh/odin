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

    def get_entity(self, key):
        return self._data["entity"]

    def entity_history(self, key):
        return self._data.get("history", [])


def _patch(monkeypatch, **data):
    monkeypatch.setattr(graph_cmd, "require", lambda: Config(token="odin_pat_x"))
    monkeypatch.setattr(graph_cmd, "Client", lambda cfg: _FakeClient(**data))


def test_find(monkeypatch):
    _patch(monkeypatch, find=[{"key": "org:helios", "name": "Helios", "type": "Org"}])
    result = CliRunner().invoke(app, ["graph", "find", "helios"])
    assert result.exit_code == 0
    assert "org:helios" in result.output


def test_find_json(monkeypatch):
    _patch(monkeypatch, find=[{"key": "org:helios", "name": "Helios", "type": "Org"}])
    result = CliRunner().invoke(app, ["graph", "find", "helios", "--json"])
    assert result.exit_code == 0
    assert '"org:helios"' in result.output


def test_entity_resolves_name_to_key(monkeypatch):
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
        },
    )
    result = CliRunner().invoke(app, ["graph", "entity", "helios"])
    assert result.exit_code == 0
    assert "BUILDS" in result.output
    assert "project:atlas" in result.output


def test_history(monkeypatch):
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
    result = CliRunner().invoke(app, ["graph", "history", "org:helios"])
    assert result.exit_code == 0
    assert "entity_create" in result.output
