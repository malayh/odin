"""`odin ingest` directory-walk, `.odinignore`, and async-queue tests (client faked)."""

import json

from odin_cli.commands import ingest as ingest_cmd
from odin_cli.config import Config
from odin_cli.main import app
from typer.testing import CliRunner


class _FakeClient:
    def __init__(self, jobs=None):
        self._jobs = jobs or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ingest(self, path, key):
        return {"document_id": f"doc-{key}", "job_id": f"job-{key}", "deduped": False}

    def get_job(self, job_id):
        return self._jobs[job_id]


def _patch(monkeypatch, tmp_path, jobs=None):
    monkeypatch.setenv("ODIN_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setattr(ingest_cmd, "require", lambda: Config(token="odin_pat_x"))
    monkeypatch.setattr(ingest_cmd, "Client", lambda cfg: _FakeClient(jobs))


def _write(directory, rel, text="x"):
    target = directory / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _ingested_keys(tmp_path, monkeypatch, root):
    _patch(monkeypatch, tmp_path)
    result = CliRunner().invoke(app, ["ingest", "--dir", str(root), "--json"])
    assert result.exit_code == 0, result.output
    return {r["key"] for r in json.loads(result.output)}


def test_ignores_plain_and_directory_patterns(tmp_path, monkeypatch):
    root = tmp_path / "src"
    _write(root, "keep.md")
    _write(root, "notes/keep.md")
    _write(root, "secret.md")
    _write(root, "drafts/a.md")
    _write(root, "drafts/nested/b.md")
    _write(root, ".odinignore", "secret.md\ndrafts/\n")

    assert _ingested_keys(tmp_path, monkeypatch, root) == {"keep.md", "notes/keep.md"}


def test_negation_reincludes(tmp_path, monkeypatch):
    root = tmp_path / "src"
    _write(root, "keep.md")
    _write(root, "other.md")
    _write(root, ".odinignore", "*.md\n!keep.md\n")

    assert _ingested_keys(tmp_path, monkeypatch, root) == {"keep.md"}


def test_no_odinignore_keeps_all(tmp_path, monkeypatch):
    root = tmp_path / "src"
    _write(root, "keep.md")
    _write(root, "notes/also.md")

    assert _ingested_keys(tmp_path, monkeypatch, root) == {"keep.md", "notes/also.md"}


def test_upload_enqueues_jobs(tmp_path, monkeypatch):
    root = tmp_path / "src"
    _write(root, "a.md")
    _write(root, "b.md")
    _patch(monkeypatch, tmp_path)

    result = CliRunner().invoke(app, ["ingest", "--dir", str(root)])
    assert result.exit_code == 0, result.output

    queue = json.loads((tmp_path / "ingest_queue.json").read_text())
    assert {e["key"] for e in queue} == {"a.md", "b.md"}
    assert all(e["state"] == "pending" for e in queue)


def test_status_clears_done_keeps_others(tmp_path, monkeypatch):
    jobs = {
        "job-a": {"state": "done", "error": None},
        "job-b": {"state": "running", "error": None},
    }
    _patch(monkeypatch, tmp_path, jobs=jobs)
    queue = [
        {"key": "a.md", "job_id": "job-a", "document_id": "doc-a", "state": "pending"},
        {"key": "b.md", "job_id": "job-b", "document_id": "doc-b", "state": "pending"},
    ]
    (tmp_path / "ingest_queue.json").write_text(json.dumps(queue))

    result = CliRunner().invoke(app, ["ingest", "status", "--json"])
    assert result.exit_code == 0, result.output

    reported = {r["key"]: r["state"] for r in json.loads(result.output)}
    assert reported == {"a.md": "done", "b.md": "running"}

    remaining = json.loads((tmp_path / "ingest_queue.json").read_text())
    assert [e["key"] for e in remaining] == ["b.md"]


def test_status_empty_queue(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    result = CliRunner().invoke(app, ["ingest", "status", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []
