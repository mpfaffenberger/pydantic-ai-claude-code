"""The Claude Code model: an `AnthropicModel` with the Claude Code persona prepended."""

from __future__ import annotations

from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart
from pydantic_ai.models.anthropic import AnthropicModel

from . import config


class ClaudeCodeModel(AnthropicModel):
    """AnthropicModel whose system prompt opens with the Claude Code persona.

    The subscription backend expects the Claude Code persona at position 0 of
    the system context. Prepending a `SystemPromptPart` here is idempotent:
    once it's in history it stays, and repeated `prepare_messages` calls don't
    duplicate it.
    """

    def prepare_messages(
        self,
        messages: list[ModelMessage],
        model_request_parameters=None,
    ) -> list[ModelMessage]:
        return super().prepare_messages(_prepend_persona(messages), model_request_parameters)


def _prepend_persona(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Return `messages` with the persona added first, unless it's already there."""
    for index, message in enumerate(messages):
        if not isinstance(message, ModelRequest):
            continue
        if any(
            isinstance(part, SystemPromptPart) and part.content.strip().startswith(config.CLAUDE_CODE_SYSTEM_PROMPT)
            for part in message.parts
        ):
            return messages
        updated = ModelRequest([SystemPromptPart(config.CLAUDE_CODE_SYSTEM_PROMPT), *message.parts])
        return [*messages[:index], updated, *messages[index + 1 :]]
    return messages
