"""Pluggable converters: a Converter signature (bytes -> text) + native text/md/html."""

from collections.abc import Callable
from pathlib import PurePosixPath

from bs4 import BeautifulSoup

from odin.errors import ValidationError

Converter = Callable[[bytes], str]


def _text(data: bytes) -> str:
    return data.decode("utf-8")


def _html(data: bytes) -> str:
    return BeautifulSoup(data, "html.parser").get_text(separator="\n").strip()


CONVERTERS: dict[str, Converter] = {
    "text": _text,
    "markdown": _text,
    "html": _html,
}

_EXTENSIONS: dict[str, str] = {
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
}


def format_for_key(key: str) -> str:
    fmt = _EXTENSIONS.get(PurePosixPath(key).suffix.lower())
    if fmt is None:
        raise ValidationError(f"no converter for key: {key!r}")
    return fmt


def convert(data: bytes, key: str) -> str:
    return CONVERTERS[format_for_key(key)](data)
