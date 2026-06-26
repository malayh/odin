"""`odin ask` command tests (client faked, no server needed)."""

from odin_cli.commands import ask as ask_cmd
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

    def ask(self, question, scope, history=None):
        return self._data["ask"]


def _patch(monkeypatch, **data):
    monkeypatch.setattr(ask_cmd, "require", lambda: Config(token="odin_pat_x"))
    monkeypatch.setattr(ask_cmd, "Client", lambda cfg: _FakeClient(**data))


_GROUNDED = {
    "answer": "Mara founded Helios.",
    "confident": True,
    "citations": [
        {
            "document_id": "11111111-1111-1111-1111-111111111111",
            "scope_type": "personal",
            "scope_id": "22222222-2222-2222-2222-222222222222",
        }
    ],
}


def test_ask_prints_answer_and_citations(monkeypatch):
    _patch(monkeypatch, ask=_GROUNDED)
    result = CliRunner().invoke(app, ["ask", "who founded Helios?"])
    assert result.exit_code == 0
    assert "Mara founded Helios." in result.output
    assert "11111111" in result.output


def test_ask_json(monkeypatch):
    _patch(monkeypatch, ask=_GROUNDED)
    result = CliRunner().invoke(app, ["ask", "q", "--json"])
    assert result.exit_code == 0
    assert '"Mara founded Helios."' in result.output


def test_ask_refusal_shows_low_confidence(monkeypatch):
    _patch(
        monkeypatch,
        ask={"answer": "not in your knowledge base", "confident": False, "citations": []},
    )
    result = CliRunner().invoke(app, ["ask", "which way does the sun rise?"])
    assert result.exit_code == 0
    assert "low confidence" in result.output
