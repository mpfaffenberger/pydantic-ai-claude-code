"""Use your Claude Code subscription from a Pydantic AI Agent.

Quick start:

    from pydantic_ai import Agent
    from pydantic_ai_claude_code import ClaudeCodeProvider

    provider = ClaudeCodeProvider()
    agent = Agent(provider.model('claude-fable-5-1'))
"""

from .credentials import ClaudeCodeCredentials
from .flow import (
    ClaudeCodeOAuthFlow,
    exchange_code,
    login,
    parse_pasteback,
    refresh_credentials,
)
from .model import ClaudeCodeModel
from .provider import ClaudeCodeProvider
from .storage import ClaudeCodeTokenStore, default_auth_path

__all__ = [
    "ClaudeCodeCredentials",
    "ClaudeCodeModel",
    "ClaudeCodeOAuthFlow",
    "ClaudeCodeProvider",
    "ClaudeCodeTokenStore",
    "default_auth_path",
    "exchange_code",
    "login",
    "parse_pasteback",
    "refresh_credentials",
]
