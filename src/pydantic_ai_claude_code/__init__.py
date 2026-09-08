"""Use your Claude Code subscription from a Pydantic AI Agent.

Quick start:

    from pydantic_ai import Agent
    from pydantic_ai_claude_code import ClaudeCodeModel

    agent = Agent(ClaudeCodeModel('claude-fable-5-1'))
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
from .storage import ClaudeCodeTokenStore, KeyringTokenStore, default_auth_path, default_store

__all__ = [
    "ClaudeCodeCredentials",
    "ClaudeCodeModel",
    "ClaudeCodeOAuthFlow",
    "ClaudeCodeProvider",
    "ClaudeCodeTokenStore",
    "KeyringTokenStore",
    "default_auth_path",
    "default_store",
    "exchange_code",
    "login",
    "parse_pasteback",
    "refresh_credentials",
]
