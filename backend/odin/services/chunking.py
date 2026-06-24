"""Structure-aware, token-bounded chunking with overlap and citation metadata."""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import tiktoken

MAX_TOKENS = 512
OVERLAP_TOKENS = 64
MIN_TOKENS = 64
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Chunked:
    ordinal: int
    text: str
    section_meta: dict[str, Any]
    char_start: int
    char_end: int


@lru_cache
def _encoder() -> Any:
    return tiktoken.get_encoding("cl100k_base")


def _ntokens(text: str) -> int:
    return len(_encoder().encode(text))


def _headings(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), len(m.group(1)), m.group(2)) for m in _HEADING.finditer(text)]


def _heading_path(headings: list[tuple[int, int, str]], pos: int) -> list[str]:
    path: list[str] = []
    levels: list[int] = []
    for offset, level, title in headings:
        if offset > pos:
            break
        while levels and levels[-1] >= level:
            levels.pop()
            path.pop()
        levels.append(level)
        path.append(title)
    return path


def _budget_end(text: str, start: int, max_tokens: int) -> int:
    n = len(text)
    if _ntokens(text[start:]) <= max_tokens:
        return n
    lo, hi = start + 1, n
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _ntokens(text[start:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _prefer_break(text: str, start: int, end: int) -> int:
    floor = start + (end - start) // 2
    for sep in ("\n\n", "\n", " "):
        idx = text.rfind(sep, floor, end)
        if idx != -1:
            return idx + len(sep)
    return end


def _overlap_start(text: str, start: int, end: int, overlap_tokens: int) -> int:
    lo, hi = start + 1, end
    while lo < hi:
        mid = (lo + hi) // 2
        if _ntokens(text[mid:end]) <= overlap_tokens:
            hi = mid
        else:
            lo = mid + 1
    return max(start + 1, lo)


def chunk(
    text: str,
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
    min_tokens: int = MIN_TOKENS,
) -> list[Chunked]:
    headings = _headings(text)
    n = len(text)
    out: list[Chunked] = []
    pos = 0
    ordinal = 0
    while pos < n:
        end = _budget_end(text, pos, max_tokens)
        if end < n:
            end = _prefer_break(text, pos, end)
        out.append(
            Chunked(ordinal, text[pos:end], {"headings": _heading_path(headings, pos)}, pos, end)
        )
        ordinal += 1
        if end >= n:
            break
        pos = _overlap_start(text, pos, end, overlap_tokens)
    if len(out) > 1 and _ntokens(out[-1].text) < min_tokens:
        last = out.pop()
        prev = out.pop()
        out.append(
            Chunked(
                prev.ordinal,
                text[prev.char_start : last.char_end],
                prev.section_meta,
                prev.char_start,
                last.char_end,
            )
        )
    return out
