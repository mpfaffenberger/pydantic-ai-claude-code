"""Tests for the OAuth flow against a local stub endpoint."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest

from pydantic_ai_claude_code import config
from pydantic_ai_claude_code.credentials import ClaudeCodeCredentials
from pydantic_ai_claude_code.flow import (
    ClaudeCodeOAuthFlow,
    exchange_code,
    parse_pasteback,
    refresh_credentials,
)


class _StubTokenServer(BaseHTTPRequestHandler):
    last_body: dict = {}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        self.server.last_body = json.loads(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        payload = {"access_token": "fresh-token", "refresh_token": "fresh-refresh"}
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def token_stub(monkeypatch) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubTokenServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "TOKEN_URL", f"http://127.0.0.1:{server.server_address[1]}/oauth/token")
    yield server
    server.shutdown()
    server.server_close()


def test_authorization_url_has_pkce_params() -> None:
    flow = ClaudeCodeOAuthFlow(redirect_uri="http://localhost:1234/callback")
    url = flow.authorization_url()
    assert "client_id=" in url
    assert "code_challenge=" in url
    assert flow.code_verifier
    assert len(flow.state) > 20


def test_exchange_code(token_stub) -> None:
    creds = asyncio.run(
        exchange_code(
            "some-code",
            "some-verifier",
            "http://localhost:1/callback",
            state="s3cret-state",
            http_client=httpx2.AsyncClient(),
        )
    )
    assert creds.token == "fresh-token"
    body = token_stub.last_body
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "some-code"
    assert body["state"] == "s3cret-state"


def test_refresh_credentials(token_stub) -> None:
    original = ClaudeCodeCredentials(access_token="old", refresh_token="orig-refresh")
    refreshed = asyncio.run(refresh_credentials(original, http_client=httpx2.AsyncClient()))
    assert refreshed.token == "fresh-token"
    assert refreshed.refresh_token.get_secret_value() == "fresh-refresh"


def test_parse_pasteback() -> None:
    assert parse_pasteback("claude://oauth/callback?code=abc&state=xyz") == ("abc", "xyz")
    assert parse_pasteback("https://example.com/callback?code=nope") is None
    assert parse_pasteback("claude://oauth/callback") is None  # missing code
