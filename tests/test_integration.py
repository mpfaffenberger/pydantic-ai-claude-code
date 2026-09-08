"""End-to-end test of the provider composing with a real pydantic-ai Agent.

The Messages API is stubbed locally, so no subscription tokens are needed. This
verifies the whole path the wheel is responsible for: AnthropicModel bound to
our provider, auth headers, message building, and response parsing.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pydantic_ai import Agent

from pydantic_ai_claude_code.credentials import ClaudeCodeCredentials
from pydantic_ai_claude_code.provider import ClaudeCodeProvider


class _MessagesStub(BaseHTTPRequestHandler):
    received: dict = {}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        self.server.received = json.loads(raw)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        payload = {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [{"type": "text", "text": "Hello from the stub!"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 5},
        }
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def messages_stub(monkeypatch) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MessagesStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def test_agent_round_trip(messages_stub) -> None:
    creds = ClaudeCodeCredentials(access_token="sub-token", refresh_token="refresh")
    provider = ClaudeCodeProvider(credentials=creds, base_url=f"http://127.0.0.1:{messages_stub.server_address[1]}")
    agent = Agent(provider.model("claude-sonnet-4-5"))

    result = asyncio_run(agent.run("Say hi."))

    assert result.output == "Hello from the stub!"
    body = messages_stub.received
    assert body["model"] == "claude-sonnet-4-5"
    assert body["messages"][0]["content"][0]["text"] == "Say hi."


import asyncio  # noqa: E402


def asyncio_run(coro) -> object:  # noqa: ANN201
    return asyncio.run(coro)
