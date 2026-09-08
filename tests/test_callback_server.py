"""Tests for the local OAuth callback server."""

from __future__ import annotations

import httpx2

from pydantic_ai_claude_code.flow import start_login_callback_server


def test_callback_server_captures_query() -> None:
    server = start_login_callback_server()
    try:
        port = server.server_address[1]
        resp = httpx2.get(f"http://127.0.0.1:{port}/callback?code=abc&state=xyz")
        assert resp.status_code == 200
        assert server.received.wait(1)
        assert server.query == "/callback?code=abc&state=xyz"
    finally:
        server.shutdown()
        server.server_close()
