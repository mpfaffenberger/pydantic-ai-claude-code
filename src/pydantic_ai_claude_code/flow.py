"""Authorization-code PKCE flow for Claude Code credentials.

The browser flow hosts a short-lived localhost callback server, the same shape as
the Codex provider's `_REDIRECT_URI`. Both the `claude://` pasteback scheme and a
plain localhost redirect are supported.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx2

from pydantic_ai.exceptions import UserError

from . import config
from .credentials import ClaudeCodeCredentials


class ClaudeCodeOAuthFlow:
    """A side-effect-free authorization-code PKCE flow context."""

    def __init__(self, redirect_uri: str | None = None) -> None:
        self.redirect_uri = redirect_uri
        self.state = secrets.token_urlsafe(32)
        self.code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(self.code_verifier.encode()).digest()
        self.code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def authorization_url(self) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": config.CLIENT_ID,
                "redirect_uri": self.redirect_uri or "",
                "scope": config.SCOPES,
                "state": self.state,
                "code": "true",
                "code_challenge": self.code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{config.AUTH_URL}?{query}"

    async def exchange_code(self, code: str, *, http_client: httpx2.AsyncClient | None = None) -> ClaudeCodeCredentials:
        """Exchange an authorization code for credentials."""
        return await exchange_code(
            code, self.code_verifier, self.redirect_uri, state=self.state, http_client=http_client
        )


async def exchange_code(
    code: str,
    code_verifier: str,
    redirect_uri: str | None,
    *,
    state: str | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> ClaudeCodeCredentials:
    """Exchange an authorization code for Claude Code credentials."""
    async with _client_context(http_client) as client:
        response = await client.post(
            config.TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": config.CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "state": state,
            },
            headers=_token_headers(),
        )
        _raise_for_token_error(response)
        return ClaudeCodeCredentials.from_token_response(response.json())


async def refresh_credentials(
    credentials: ClaudeCodeCredentials, *, http_client: httpx2.AsyncClient | None = None
) -> ClaudeCodeCredentials:
    """Refresh Claude Code credentials without persisting them."""
    async with _client_context(http_client) as client:
        response = await client.post(
            config.TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": config.CLIENT_ID,
                "refresh_token": credentials.refresh_token.get_secret_value(),
            },
            headers=_token_headers(),
        )
        _raise_for_token_error(response)
        return ClaudeCodeCredentials.from_token_response(response.json(), previous=credentials)


def _raise_for_token_error(response: httpx2.Response) -> None:
    """Raise a `UserError` that includes the token server's error body.

    The token endpoints return sparse HTTP codes, so the reason lives in the
    JSON body; without it a 400 tells us nothing.
    """
    if response.status_code < 400:
        return
    body = response.text[:500]
    raise UserError(f"Claude Code token endpoint returned {response.status_code}: {body}")


def _token_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "anthropic-beta": config.ANTHROPIC_BETA,
        "User-Agent": config.USER_AGENT,
    }


def parse_pasteback(raw: str) -> tuple[str, str] | None:
    """Parse a `claude://oauth/callback?...` paste back into `(code, state)`.

    Returns `None` when the input isn't a pasteback URL.
    """
    if not raw.startswith(config.PASTEBACK_SCHEMES):
        return None
    try:
        query = raw.partition("?")[2]
        params = parse_qs(query)
    except ValueError:
        return None
    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]
    if not code:
        return None
    return code, state


class _CallbackServer(ThreadingHTTPServer):
    """Localhost server that captures the OAuth redirect query string."""

    def __init__(self) -> None:
        self.query: str | None = None
        self.received = threading.Event()
        super().__init__(("127.0.0.1", 0), _CallbackHandler)
        self.daemon_threads = True


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackServer

    def do_GET(self) -> None:  # noqa: N802
        if not self.server.received.is_set():
            self.server.query = self.path
            self.server.received.set()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h1>pydantic-ai-claude-code</h1><p>Auth successful. Return to your terminal.</p></body></html>"
        )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        pass


def start_login_callback_server() -> _CallbackServer:
    """Start a callback server plus a daemon thread serving it."""
    server = _CallbackServer()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def login(*, store: Any = None) -> ClaudeCodeCredentials:
    """Run the full OAuth flow and persist the minted credentials.

    Args:
        store: The token store to write to. Defaults to the standard store.

    Returns:
        The credentials that were persisted.
    """
    from .storage import default_store

    if store is None:
        store = default_store()
    server = start_login_callback_server()
    try:
        redirect_uri = f"{config.REDIRECT_HOST}:{server.server_address[1]}/{config.REDIRECT_PATH}"
        flow = ClaudeCodeOAuthFlow(redirect_uri=redirect_uri)
        url = flow.authorization_url()
        print(f"Open this URL in your browser if it did not open automatically:\n{url}")
        # Launch the browser off the event path: on some macOS setups `webbrowser.open`
        # hangs until the UI settles, which would starve the callback wait below.
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
        if not server.received.wait(config.CALLBACK_TIMEOUT):
            raise UserError("Claude Code OAuth callback timed out.")
        code, state = _parse_callback_query(server.query)
        if state and state != flow.state:
            raise UserError("Claude Code OAuth state mismatch; the redirect may be a replay.")
        if not code:
            raise UserError(f"Claude Code OAuth redirect did not include a `code` parameter: {server.query!r}")
        credentials = await flow.exchange_code(code)
    finally:
        server.shutdown()
        server.server_close()
    store.save(credentials)
    return credentials


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - best-effort: the URL is printed for manual use
        pass


def _parse_callback_query(raw: str | None) -> tuple[str, str]:
    """Extract `(code, state)` from a captured redirect path like `/callback?code=...`."""
    params = parse_qs((raw or "").split("?", 1)[-1])
    return params.get("code", [""])[0], params.get("state", [""])[0]


class _client_context:
    def __init__(self, client: httpx2.AsyncClient | None) -> None:
        self.client = client or httpx2.AsyncClient()
        self.owned = client is None

    async def __aenter__(self) -> httpx2.AsyncClient:
        return self.client

    async def __aexit__(self, *_: object) -> None:
        if self.owned:
            await self.client.aclose()
