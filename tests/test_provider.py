"""Tests for the Claude Code provider and its auth shim."""

from __future__ import annotations

import pytest
import httpx2

from pydantic_ai.exceptions import UserError

from pydantic_ai_claude_code.credentials import ClaudeCodeCredentials
from pydantic_ai_claude_code.provider import ClaudeCodeProvider
from pydantic_ai_claude_code.storage import ClaudeCodeTokenStore


def test_name() -> None:
    provider = ClaudeCodeProvider(credentials=ClaudeCodeCredentials(access_token="a", refresh_token="b"))
    assert provider.name == "claude-code"


def test_credentials_property() -> None:
    creds = ClaudeCodeCredentials(access_token="a", refresh_token="b")
    provider = ClaudeCodeProvider(credentials=creds)
    assert provider.credentials.token == "a"


def test_model_binding() -> None:
    provider = ClaudeCodeProvider(credentials=ClaudeCodeCredentials(access_token="a", refresh_token="b"))
    model = provider.model("claude-sonnet-4-5")
    assert model.model_name == "claude-sonnet-4-5"
    assert model._provider is provider  # type: ignore[attr-defined]


def test_missing_credentials_raises(tmp_path) -> None:
    store = ClaudeCodeTokenStore(path=tmp_path / "missing.json")
    with pytest.raises(UserError):
        ClaudeCodeProvider(store=store)


def test_auth_applies_headers() -> None:
    provider = ClaudeCodeProvider(
        credentials=ClaudeCodeCredentials(access_token="secret-token", refresh_token="refresh"),
        base_url="https://api.anthropic.com",
    )
    auth = provider._claude_code_auth  # type: ignore[attr-defined]
    request = httpx2.Request(
        "POST", "https://api.anthropic.com/v1/messages", headers={"anthropic-beta": "thinking-2025"}
    )
    auth._apply(request)
    assert request.headers["authorization"] == "Bearer secret-token"
    assert request.headers["x-app"] == "cli"
    assert "oauth-2025-04-20" in request.headers["anthropic-beta"]
    assert "thinking-2025" in request.headers["anthropic-beta"]
