"""Shared fixtures: an isolated home for credentials, and a local Messages API stub."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail

TEXT = "Hello from the stub!"
_MESSAGE = {
    "id": "msg_01",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-5",
    "content": [{"type": "text", "text": TEXT}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 12, "output_tokens": 5},
}


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Keep every test away from the real keychain and the user's token file and CLAI2 settings."""
    previous: KeyringBackend = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    for variable in ("CLAUDE_CODE_CREDENTIALS", "CLAUDE_CODE_AUTH_FILE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLAUDE_CODE_NO_UPDATE_CHECK", "1")  # tests that want it point it at `messages_stub`
    yield tmp_path
    keyring.set_keyring(previous)


def _stream_events() -> list[dict[str, object]]:
    """`_MESSAGE` as the Messages API streams it."""
    start = {**_MESSAGE, "content": [], "stop_reason": None, "usage": {"input_tokens": 12, "output_tokens": 0}}
    return [
        {"type": "message_start", "message": start},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": TEXT}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]


class MessagesServer(ThreadingHTTPServer):
    """Records the last Messages request body and its headers; `/oauth/token` answers `token_status`.

    A GET answers like PyPI's JSON API, with `release` as the latest version.
    """

    received: dict[str, object]
    headers: dict[str, str]
    token_status = 400
    release = "0.0.0"

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _MessagesStub(BaseHTTPRequestHandler):
    server: MessagesServer

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"info": {"version": self.server.release}}).encode())

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if self.path.endswith("/oauth/token"):
            self.send_response(self.server.token_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "invalid_grant", "error_description": "Refresh token not found or invalid"}')
            return
        self.server.received = json.loads(body)
        self.server.headers = dict(self.headers)
        self.send_response(200)
        if self.server.received.get("stream"):
            # Recent pydantic-ai streams Anthropic requests even for `agent.run`.
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in _stream_events():
                self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
            return
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(_MESSAGE).encode())

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def messages_stub() -> Iterator[MessagesServer]:
    server = MessagesServer(("127.0.0.1", 0), _MessagesStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()
