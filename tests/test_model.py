"""Tests for the Claude Code persona prepend logic."""

from __future__ import annotations

from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart

from pydantic_ai_claude_code import config
from pydantic_ai_claude_code.model import _prepend_persona


def test_persona_prepended_to_leading_request() -> None:
    messages = [ModelRequest([SystemPromptPart("You are a helpful assistant."), UserPromptPart("hi")])]
    out = _prepend_persona(messages)
    leading = out[0]
    assert isinstance(leading, ModelRequest)
    persona, user_system = leading.parts[:2]
    assert isinstance(persona, SystemPromptPart)
    assert persona.content == config.CLAUDE_CODE_SYSTEM_PROMPT
    assert isinstance(user_system, SystemPromptPart)
    assert user_system.content == "You are a helpful assistant."
    # The user prompt is untouched.
    assert leading.parts[2].content == "hi"  # type: ignore[attr-defined]


def test_persona_prepend_is_idempotent() -> None:
    messages = [ModelRequest([SystemPromptPart("hi")])]
    once = _prepend_persona(messages)
    twice = _prepend_persona(once)
    parts = twice[0].parts  # type: ignore[attr-defined]
    assert (
        sum(1 for p in parts if isinstance(p, SystemPromptPart) and p.content == config.CLAUDE_CODE_SYSTEM_PROMPT) == 1
    )
