"""`odin ingest` directory-walk + `.odinignore` tests (client faked, no server needed)."""

import json

from odin_cli.commands import ingest as ingest_cmd
from odin_cli.config import Config
from odin_cli.main import app
from typer.testing import CliRunner


class _FakeClient:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ingest(self, path, key):
        return {}


def _patch(monkeypatch):
    monkeypatch.setattr(ingest_cmd, "require", lambda: Config(token="odin_pat_x"))
    monkeypatch.setattr(ingest_cmd, "Client", lambda cfg: _FakeClient())


def _write(directory, rel, text="x"):
    target = directory / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _ingested_keys(tmp_path, monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(app, ["ingest", "--dir", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    return {r["key"] for r in json.loads(result.output)}


def test_ignores_plain_and_directory_patterns(tmp_path, monkeypatch):
    _write(tmp_path, "keep.md")
    _write(tmp_path, "notes/keep.md")
    _write(tmp_path, "secret.md")
    _write(tmp_path, "drafts/a.md")
    _write(tmp_path, "drafts/nested/b.md")
    _write(tmp_path, ".odinignore", "secret.md\ndrafts/\n")

    assert _ingested_keys(tmp_path, monkeypatch) == {"keep.md", "notes/keep.md"}


def test_negation_reincludes(tmp_path, monkeypatch):
    _write(tmp_path, "keep.md")
    _write(tmp_path, "other.md")
    _write(tmp_path, ".odinignore", "*.md\n!keep.md\n")

    assert _ingested_keys(tmp_path, monkeypatch) == {"keep.md"}


def test_no_odinignore_keeps_all(tmp_path, monkeypatch):
    _write(tmp_path, "keep.md")
    _write(tmp_path, "notes/also.md")

    assert _ingested_keys(tmp_path, monkeypatch) == {"keep.md", "notes/also.md"}
