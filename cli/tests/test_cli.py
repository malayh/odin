"""Smoke + config round-trip tests for the Odin CLI (no server needed)."""

from odin_cli.config import Config, load, save
from odin_cli.main import app
from typer.testing import CliRunner


def test_config_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ODIN_CONFIG", str(tmp_path / "config.yaml"))
    save(Config(server_url="http://x:8000", token="odin_pat_abc", default_scope="org:1"))
    cfg = load()
    assert cfg.server_url == "http://x:8000"
    assert cfg.token == "odin_pat_abc"
    assert cfg.default_scope == "org:1"


def test_load_missing_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("ODIN_CONFIG", str(tmp_path / "nope.yaml"))
    cfg = load()
    assert cfg.token is None
    assert cfg.server_url == "http://localhost:8000"


def test_help_smoke():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Ingest documents" in result.output
