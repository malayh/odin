"""LLM client (OpenAI-compatible, OpenRouter by default): JSON-structured completions."""

import asyncio
from functools import lru_cache
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from odin.config import get_settings
from odin.errors import OdinError

_MAX_ATTEMPTS = 3


@lru_cache
def _client() -> Any:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise OdinError("OPENROUTER_API_KEY is not configured")
    return OpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)


def _complete_json_sync[T: BaseModel](
    model: str, system: str | None, prompt: str, schema: type[T], max_tokens: int | None
) -> T:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    last: Exception = RuntimeError("llm call failed")
    for _ in range(_MAX_ATTEMPTS):
        try:
            resp = _client().chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
            )
            return schema.model_validate_json(resp.choices[0].message.content or "")
        except Exception as e:
            last = e
    raise last


async def complete_json[T: BaseModel](
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> T:
    model = model or get_settings().answer_model
    return await asyncio.to_thread(_complete_json_sync, model, system, prompt, schema, max_tokens)
