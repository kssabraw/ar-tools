"""Regression test: the fanout Anthropic client must STREAM, not messages.create.

The orchestrator's big chunk calls (large prompt, up to 16k output tokens) can
generate for minutes; a non-streaming request sends no bytes until completion,
and idle upstream connections were killed at ~2 minutes regardless of the
client-side timeout — observed in production as a retry loop that starved
article planning. Streaming keeps bytes flowing; get_final_message() returns
the same Message object, so callers are unchanged.

This test wires the real anthropic SDK to an httpx.MockTransport serving an
SSE response and asserts (1) the wire request asks for a stream and (2) the
tool-use extraction still works end to end.
"""

import json

import httpx
import pytest

pytest.importorskip("anthropic")

from fanout.llm.anthropic_client import AnthropicLLM  # noqa: E402


_SSE_EVENTS = [
    ("message_start", {
        "type": "message_start",
        "message": {
            "id": "msg_test", "type": "message", "role": "assistant",
            "model": "claude-opus-4-7", "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 1},
        },
    }),
    ("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "tool_use", "id": "toolu_test",
                          "name": "emit_plan", "input": {}},
    }),
    ("content_block_delta", {
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "input_json_delta",
                  "partial_json": "{\"clusters\": [\"a\", \"b\"]}"},
    }),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use", "stop_sequence": None},
        "usage": {"output_tokens": 42},
    }),
    ("message_stop", {"type": "message_stop"}),
]


def _sse_body() -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(payload)}\n\n"
        for name, payload in _SSE_EVENTS
    ).encode()


def test_invoke_streams_and_extracts_tool_input():
    import anthropic

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse_body(),
        )

    llm = AnthropicLLM(api_key="test-key", model="claude-opus-4-7",
                       max_tokens=16000, timeout_s=600.0,
                       max_transport_attempts=1)
    # swap in a mocked HTTP layer under the real SDK client
    llm._client = anthropic.Anthropic(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    out = llm.call_tool(
        system="You are the orchestrator.",
        user="Plan the articles.",
        tool_name="emit_plan",
        tool_description="Emit the article plan.",
        input_schema={"type": "object"},
        purpose="test",
    )

    # 1. The wire request must be a streaming request — a non-streaming call
    #    sends no bytes until completion and gets killed upstream at ~2 min.
    assert seen["path"] == "/v1/messages"
    assert seen["body"].get("stream") is True

    # 2. The accumulated final message parses the tool input as before.
    assert out == {"clusters": ["a", "b"]}


# ── second-Anthropic-account failover ────────────────────────────────────────
import types  # noqa: E402

import anthropic  # noqa: E402

from fanout.llm.anthropic_client import AnthropicError  # noqa: E402


def _fake_final_message(tool_name: str, tool_input: dict):
    block = types.SimpleNamespace(type="tool_use", name=tool_name, input=tool_input)
    usage = types.SimpleNamespace(input_tokens=10, output_tokens=5)
    return types.SimpleNamespace(content=[block], usage=usage)


class _FakeStreamCM:
    def __init__(self, exc=None, message=None):
        self._exc = exc
        self._message = message

    def __enter__(self):
        if self._exc is not None:
            raise self._exc
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, *, exc=None, message=None):
        self._exc = exc
        self._message = message
        self.calls = 0

    def stream(self, **kwargs):
        self.calls += 1
        return _FakeStreamCM(self._exc, self._message)


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages


def _rate_limit():
    return anthropic.RateLimitError.__new__(anthropic.RateLimitError)


def _status(code):
    exc = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
    exc.status_code = code
    return exc


def _make_llm():
    # max_transport_attempts=1 → one attempt per account, then failover/raise.
    return AnthropicLLM(api_key="k", model="claude-opus-4-7", max_transport_attempts=1)


def test_invoke_fails_over_to_secondary_account():
    llm = _make_llm()
    primary = _FakeMessages(exc=_rate_limit())  # primary account saturated
    secondary = _FakeMessages(message=_fake_final_message("emit_plan", {"x": 1}))
    llm._client = _FakeClient(primary)
    llm._secondary_client = _FakeClient(secondary)

    out = llm.call_tool(
        system="s", user="u", tool_name="emit_plan",
        tool_description="d", input_schema={"type": "object"}, purpose="test",
    )
    assert out == {"x": 1}
    assert primary.calls == 1     # primary tried once
    assert secondary.calls == 1   # then the second account served it


def test_invoke_terminal_error_does_not_fail_over():
    llm = _make_llm()
    primary = _FakeMessages(exc=_status(400))  # bad request — not retryable
    secondary = _FakeMessages(message=_fake_final_message("emit_plan", {"x": 1}))
    llm._client = _FakeClient(primary)
    llm._secondary_client = _FakeClient(secondary)

    with pytest.raises(AnthropicError):
        llm.call_tool(
            system="s", user="u", tool_name="emit_plan",
            tool_description="d", input_schema={"type": "object"}, purpose="test",
        )
    assert primary.calls == 1
    assert secondary.calls == 0  # no failover on a non-transient error


def test_invoke_both_accounts_exhausted_raises():
    llm = _make_llm()
    primary = _FakeMessages(exc=_rate_limit())
    secondary = _FakeMessages(exc=_rate_limit())
    llm._client = _FakeClient(primary)
    llm._secondary_client = _FakeClient(secondary)

    with pytest.raises(AnthropicError):
        llm.call_tool(
            system="s", user="u", tool_name="emit_plan",
            tool_description="d", input_schema={"type": "object"}, purpose="test",
        )
    assert primary.calls == 1
    assert secondary.calls == 1  # both accounts fully exhausted


def test_invoke_no_secondary_still_raises_on_primary():
    llm = _make_llm()
    primary = _FakeMessages(exc=_rate_limit())
    llm._client = _FakeClient(primary)
    llm._secondary_client = None  # no failover configured

    with pytest.raises(AnthropicError):
        llm.call_tool(
            system="s", user="u", tool_name="emit_plan",
            tool_description="d", input_schema={"type": "object"}, purpose="test",
        )
    assert primary.calls == 1
