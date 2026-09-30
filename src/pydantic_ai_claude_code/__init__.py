"""Use your Claude Code subscription from a Pydantic AI Agent, or as a CLAI2 plugin.

This folder is also a complete CLAI2 drop-in plugin: copy it into CLAI2's plugins folder as `claude_code/`
and CLAI2 calls `activate` below. It needs nothing CLAI2 does not already install.

Quick start:

    from pydantic_ai import Agent
    from pydantic_ai_claude_code import ClaudeCodeModel

    agent = Agent(ClaudeCodeModel('claude-fable-5-1'))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .auth import ClaudeCodeSignInExpiredError
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

if TYPE_CHECKING:
    from pydantic_clai2.plugins import DepsT, PluginHost


def activate(host: PluginHost[DepsT]) -> None:
    """CLAI2's plugin entry point; imported lazily so plain Pydantic AI use never needs CLAI2."""
    from .clai2 import activate as activate_plugin

    activate_plugin(host)


__all__ = [
    "ClaudeCodeCredentials",
    "ClaudeCodeModel",
    "ClaudeCodeOAuthFlow",
    "ClaudeCodeProvider",
    "ClaudeCodeSignInExpiredError",
    "ClaudeCodeTokenStore",
    "KeyringTokenStore",
    "activate",
    "default_auth_path",
    "default_store",
    "exchange_code",
    "login",
    "parse_pasteback",
    "refresh_credentials",
]
