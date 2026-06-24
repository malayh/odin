import pytest
from odin.services import llm
from pydantic import BaseModel, ValidationError


class _Out(BaseModel):
    name: str
    value: int


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _FakeCompletions:
    def __init__(self, parent):
        self.parent = parent

    def create(self, model, messages, response_format=None):
        self.parent.calls.append(messages)
        if self.parent.fail_times > 0:
            self.parent.fail_times -= 1
            raise RuntimeError("transient")
        return _Resp(self.parent.outputs.pop(0))


class _FakeChat:
    def __init__(self, parent):
        self.completions = _FakeCompletions(parent)


class _FakeClient:
    def __init__(self, outputs, fail_times=0):
        self.calls = []
        self.outputs = list(outputs)
        self.fail_times = fail_times
        self.chat = _FakeChat(self)


async def test_complete_json_parses(monkeypatch):
    fake = _FakeClient(['{"name": "x", "value": 1}'])
    monkeypatch.setattr(llm, "_client", lambda: fake)
    out = await llm.complete_json("go", _Out)
    assert out == _Out(name="x", value=1)


async def test_complete_json_retries_then_succeeds(monkeypatch):
    fake = _FakeClient(['{"name": "y", "value": 2}'], fail_times=2)
    monkeypatch.setattr(llm, "_client", lambda: fake)
    out = await llm.complete_json("go", _Out)
    assert out.value == 2
    assert len(fake.calls) == 3


async def test_complete_json_raises_on_schema_violation(monkeypatch):
    fake = _FakeClient(['{"nope": true}'] * 3)
    monkeypatch.setattr(llm, "_client", lambda: fake)
    with pytest.raises(ValidationError):
        await llm.complete_json("go", _Out)
    assert len(fake.calls) == 3


@pytest.mark.live
async def test_complete_json_live():
    out = await llm.complete_json(
        'Return JSON with keys "name" (a string) and "value" (an integer).', _Out
    )
    assert isinstance(out.name, str)
    assert isinstance(out.value, int)
