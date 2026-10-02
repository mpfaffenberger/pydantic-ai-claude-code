"""Tests for the OAuth flow against a local stub endpoint."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from pydantic_ai.exceptions import UserError

from pydantic_ai_claude_code import config, flow
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


class _MemoryStore:
    def __init__(self) -> None:
        self.saved: ClaudeCodeCredentials | None = None

    def load(self) -> ClaudeCodeCredentials | None:
        return self.saved

    def save(self, credentials: ClaudeCodeCredentials) -> None:
        self.saved = credentials

    def delete(self) -> None:
        self.saved = None


def _visit_redirect_later(url: str, *, state: str | None = None) -> None:
    """Act as the browser: follow the authorization URL's redirect with a code, after a delay."""
    query = parse_qs(urlsplit(url).query)
    redirect = query["redirect_uri"][0].replace("localhost", "127.0.0.1")
    sent_state = state if state is not None else query["state"][0]

    def visit() -> None:
        time.sleep(0.2)
        httpx2.get(f"{redirect}?code=the-code&state={sent_state}")

    threading.Thread(target=visit, daemon=True).start()


async def test_login_waits_off_the_event_loop(token_stub, monkeypatch) -> None:
    monkeypatch.setattr(flow, "_open_browser", lambda url: None)
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    store = _MemoryStore()
    ticker = asyncio.create_task(tick())
    credentials = await flow.login(store=store, on_url=_visit_redirect_later)
    ticker.cancel()

    assert credentials.token == "fresh-token"
    assert store.saved == credentials
    assert token_stub.last_body["code"] == "the-code"
    assert ticks > 5, "the event loop was blocked while waiting for the browser"


async def test_login_rejects_a_mismatched_state(token_stub, monkeypatch) -> None:
    monkeypatch.setattr(flow, "_open_browser", lambda url: None)
    store = _MemoryStore()
    with pytest.raises(UserError, match="state mismatch"):
        await flow.login(store=store, on_url=lambda url: _visit_redirect_later(url, state="forged"))
    assert store.saved is None


@pytest.mark.parametrize(
    ("pasted", "parsed"),
    [
        ("http://localhost:8765/callback?code=abc&state=xyz", ("abc", "xyz")),
        ("  claude://oauth/callback?code=abc&state=xyz\n", ("abc", "xyz")),
        ("code=abc&state=xyz", ("abc", "xyz")),
        ("abc#xyz", ("abc", "xyz")),
        ("http://localhost:8765/callback?state=xyz", None),
        ("claude://oauth/callback", None),
        ("", None),
        ("two words", None),
    ],
)
def test_parse_pasteback(pasted: str, parsed: tuple[str, str] | None) -> None:
    assert parse_pasteback(pasted) == parsed


def _paste_from(url: str, *, state: str | None = None) -> str:
    """What a browser on another machine ends on: the localhost redirect, which it could not load."""
    query = parse_qs(urlsplit(url).query)
    return f"{query['redirect_uri'][0]}?code=pasted-code&state={state or query['state'][0]}"


async def test_login_takes_a_pasted_address_when_the_callback_never_comes(token_stub, monkeypatch) -> None:
    monkeypatch.setattr(flow, "_open_browser", lambda url: None)
    shown: list[str] = []

    async def paste() -> str:
        await asyncio.sleep(0)
        return _paste_from(shown[0])

    store = _MemoryStore()
    credentials = await flow.login(store=store, on_url=shown.append, read_pasteback=paste)
    assert store.saved == credentials
    assert token_stub.last_body["code"] == "pasted-code"
    assert token_stub.last_body["redirect_uri"] == parse_qs(urlsplit(shown[0]).query)["redirect_uri"][0]


async def test_login_cancels_the_paste_read_when_the_browser_gets_through(token_stub, monkeypatch) -> None:
    monkeypatch.setattr(flow, "_open_browser", lambda url: None)
    cancelled = asyncio.Event()

    async def wait_for_paste() -> str | None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return None  # pragma: no cover

    await flow.login(store=_MemoryStore(), on_url=_visit_redirect_later, read_pasteback=wait_for_paste)
    assert cancelled.is_set()
    assert token_stub.last_body["code"] == "the-code"


@pytest.mark.parametrize(
    ("pasted", "error"),
    [
        (None, "sign-in cancelled"),
        ("not a url", "no authorization code"),
        ("forged", "state mismatch"),
    ],
)
async def test_login_rejects_a_cancelled_empty_or_forged_paste(token_stub, monkeypatch, pasted, error) -> None:
    monkeypatch.setattr(flow, "_open_browser", lambda url: None)
    shown: list[str] = []

    async def paste() -> str | None:
        await asyncio.sleep(0)
        return _paste_from(shown[0], state="forged") if pasted == "forged" else pasted

    store = _MemoryStore()
    with pytest.raises(UserError, match=error):
        await flow.login(store=store, on_url=shown.append, read_pasteback=paste)
    assert store.saved is None
