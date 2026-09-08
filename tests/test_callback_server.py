"""Tests for the local OAuth callback server."""

from __future__ import annotations

import httpx2

from pydantic_ai_claude_code.flow import _parse_callback_query, start_login_callback_server


def test_parse_callback_query_handles_path_prefix() -> None:
    # The bug that burned a real auth code: parse_qs on the full path keyed
    # everything under `callback?code`, so `code` came back empty.
    code, state = _parse_callback_query("/callback?code=ABC&state=xyz")
    assert code == "ABC"
    assert state == "xyz"
    assert _parse_callback_query(None) == ("", "")
    assert _parse_callback_query("/callback") == ("", "")


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
