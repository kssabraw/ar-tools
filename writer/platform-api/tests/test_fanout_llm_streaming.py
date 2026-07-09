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
