"""CLI config: ~/.odin/config.yaml (server URL, token, default scope)."""

import os
from dataclasses import asdict, dataclass
from pathlib import Path

import typer
import yaml

DEFAULT_SERVER = "http://localhost:8000"


def config_path() -> Path:
    override = os.environ.get("ODIN_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".odin" / "config.yaml"


def queue_path() -> Path:
    return config_path().parent / "ingest_queue.json"


@dataclass
class Config:
    server_url: str = DEFAULT_SERVER
    token: str | None = None


def load() -> Config:
    path = config_path()
    if not path.exists():
        return Config()
    data = yaml.safe_load(path.read_text()) or {}
    return Config(
        server_url=data.get("server_url", DEFAULT_SERVER),
        token=data.get("token"),
    )


def save(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(asdict(cfg), sort_keys=True))


def require() -> Config:
    cfg = load()
    if not cfg.token:
        typer.echo("not logged in — run `odin login --token <token>` first", err=True)
        raise typer.Exit(1)
    return cfg
