"""Unit tests for the Fanout OpenAI ("Luna") writer adapter.

`OpenAIWriterLLM` mirrors `AnthropicLLM`'s `complete_text` / `call_tool` interface
so the Fanout blog writer can route DRAFT prose to OpenAI. These tests exercise
the response-parsing logic with a fake OpenAI client (no network) — the net-new
code in this change. Cost logging is a no-op outside a metered run, so nothing
external is touched.
"""

import json
from types import SimpleNamespace

import pytest

from fanout.llm.openai_writer_client import OpenAIWriterLLM
from fanout.llm.openai_client import LLMError


def _make_llm(fake_create):
    llm = OpenAIWriterLLM(api_key="test", model="gpt-5.6-luna")
    # Replace the eagerly-constructed real client with a fake whose
    # chat.completions.create returns whatever the test supplies.
    llm._client = SimpleNamespace(  # type: ignore[attr-defined]
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    return llm


def _resp(*, content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20))


def test_complete_text_returns_stripped_content():
    def fake_create(**kwargs):
        # Plain-prose calls send no tools and use max_completion_tokens (GPT-5).
        assert "tools" not in kwargs
        assert "max_completion_tokens" in kwargs
        assert "temperature" not in kwargs  # GPT-5 rejects it
        return _resp(content="  Hello world  ")

    llm = _make_llm(fake_create)
    assert llm.complete_text(system="s", user="u", purpose="section") == "Hello world"


def test_complete_text_handles_empty_content():
    llm = _make_llm(lambda **_: _resp(content=None))
    assert llm.complete_text(system="s", user="u", purpose="section") == ""


def test_call_tool_parses_json_arguments():
    def fake_create(**kwargs):
        assert kwargs["tool_choice"]["function"]["name"] == "emit"
        call = SimpleNamespace(function=SimpleNamespace(name="emit", arguments='{"title": "X", "n": 3}'))
        return _resp(tool_calls=[call])

    llm = _make_llm(fake_create)
    out = llm.call_tool(
        system="s", user="u", tool_name="emit", tool_description="d",
        input_schema={"type": "object"}, purpose="title",
    )
    assert out == {"title": "X", "n": 3}


def test_call_tool_raises_when_no_tool_call():
    llm = _make_llm(lambda **_: _resp(tool_calls=[]))
    with pytest.raises(LLMError):
        llm.call_tool(
            system="s", user="u", tool_name="emit", tool_description="d",
            input_schema={"type": "object"}, purpose="title",
        )


def test_call_tool_raises_on_invalid_json():
    def fake_create(**_):
        call = SimpleNamespace(function=SimpleNamespace(name="emit", arguments="not json"))
        return _resp(tool_calls=[call])

    llm = _make_llm(fake_create)
    with pytest.raises(LLMError):
        llm.call_tool(
            system="s", user="u", tool_name="emit", tool_description="d",
            input_schema={"type": "object"}, purpose="title",
        )


def test_call_tool_raises_when_arguments_not_object():
    def fake_create(**_):
        call = SimpleNamespace(function=SimpleNamespace(name="emit", arguments=json.dumps([1, 2, 3])))
        return _resp(tool_calls=[call])

    llm = _make_llm(fake_create)
    with pytest.raises(LLMError):
        llm.call_tool(
            system="s", user="u", tool_name="emit", tool_description="d",
            input_schema={"type": "object"}, purpose="title",
        )
