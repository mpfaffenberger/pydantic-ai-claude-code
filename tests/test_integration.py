"""End-to-end test of the provider composing with a real pydantic-ai Agent.

The Messages API is stubbed locally (see `conftest.py`), so no subscription tokens are needed. This
verifies the whole path the wheel is responsible for: AnthropicModel bound to our provider, auth
headers, message building, and response parsing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai import Agent

from pydantic_ai_claude_code import config
from pydantic_ai_claude_code.auth import ClaudeCodeSignInExpiredError
from pydantic_ai_claude_code.credentials import ClaudeCodeCredentials
from pydantic_ai_claude_code.model import ClaudeCodeModel
from pydantic_ai_claude_code.provider import ClaudeCodeProvider

from conftest import TEXT, MessagesServer


@pytest.mark.parametrize("model_name", config.MODELS)
async def test_agent_round_trip(messages_stub: MessagesServer, model_name: str) -> None:
    creds = ClaudeCodeCredentials(access_token="sub-token", refresh_token="refresh")
    provider = ClaudeCodeProvider(credentials=creds, base_url=messages_stub.url)
    agent = Agent(ClaudeCodeModel(model_name, provider=provider))

    result = await agent.run("Say hi.")

    assert result.output == TEXT
    body = messages_stub.received
    assert body["model"] == model_name
    assert body["messages"][0]["content"][0]["text"] == "Say hi."  # type: ignore[index]
    # The Claude Code persona must open the system context, before any user prompt.
    assert "You are Claude Code" in str(body.get("system"))
    headers = {name.lower(): value for name, value in messages_stub.headers.items()}
    assert headers["authorization"] == "Bearer sub-token"
    assert "x-api-key" not in headers
    assert config.ANTHROPIC_BETA in headers["anthropic-beta"]


@pytest.mark.parametrize("stream", [False, True])
async def test_expired_sign_in_is_reported_not_a_connection_error(
    messages_stub: MessagesServer, monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    # The SDK wraps anything raised in the HTTP client as `Connection error.`; the model unwraps it again.
    monkeypatch.setattr(config, "TOKEN_URL", f"{messages_stub.url}/oauth/token")
    messages_stub.token_status = 400
    expired = ClaudeCodeCredentials(
        access_token="old", refresh_token="revoked", expires_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    agent = Agent(ClaudeCodeModel("claude-haiku-4-5", provider=ClaudeCodeProvider(expired, base_url=messages_stub.url)))

    with pytest.raises(
        ClaudeCodeSignInExpiredError, match=r"sign in again\. \(Claude Code token endpoint returned 400"
    ):
        if stream:
            async with agent.run_stream("hi") as response:
                await response.get_output()
        else:
            await agent.run("hi")
