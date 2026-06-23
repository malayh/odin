import pytest
from odin.errors import ValidationError
from odin.services.converters import convert, format_for_key


def test_text_passthrough():
    assert convert(b"plain text", "a.txt") == "plain text"


def test_markdown_passthrough():
    assert convert(b"# Title\n\nbody", "notes.md") == "# Title\n\nbody"


def test_html_stripped():
    out = convert(b"<h1>Hi</h1><p>there</p>", "page.html")
    assert "Hi" in out
    assert "there" in out
    assert "<" not in out


def test_format_dispatch_is_case_insensitive():
    assert format_for_key("x.MD") == "markdown"
    assert format_for_key("a/b/c.htm") == "html"
    assert format_for_key("readme.txt") == "text"


def test_unsupported_format_raises():
    with pytest.raises(ValidationError):
        format_for_key("data.pdf")
