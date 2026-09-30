"""The CLAI2 plugin: chat with your Claude Code subscription as `claude-code:MODEL`.

Install it by copying this package's folder into CLAI2's plugins folder as `claude_code/`; CLAI2 loads it at
startup through the package's `activate`. Everything it imports already ships with CLAI2, and it uses only
relative imports, so the copy runs on its own. `/claude_code` (or `C` in `/plugins`) opens the settings menu:
sign in through the browser, sign out, and choose where the sign-in is kept. Then pick a model in
`/add_model` > `claude-code`.

The sign-in is an OAuth token pair, not an API key, so it does not go in `/keys`. It is kept where this
package keeps it outside CLAI2 (the OS keyring by default), so one sign-in serves CLAI2 and your own agents.
Plugin settings, which are plaintext SQLite, hold only the storage choice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.exceptions import UserError
from pydantic_clai2.commands import Command
from pydantic_clai2.plugins import DepsT, PluginHost
from pydantic_clai2.ui.menus.field_menu import TERMINAL, FieldMenu, FieldRow, Runners, first_error, run_flow_async

from . import config
from .flow import login
from .model import ClaudeCodeModel
from .provider import ClaudeCodeProvider
from .storage import Backend, ClaudeCodeTokenStore, TokenStore, default_store

PREFIX = "claude-code"
"""Models run as `claude-code:NAME`; `NAME` is any Claude model ID the subscription serves."""

COMMAND = "claude_code"
"""CLAI2 command names are Python identifiers, so the command cannot share the prefix's hyphen."""

SIGNED_IN = "signed in"
SIGNED_OUT = "not signed in"
_HELP = f"Usage: /{COMMAND} (settings menu), /{COMMAND} login, /{COMMAND} logout, or /{COMMAND} status"
_SIGN_IN_FIRST = f"Sign in to Claude Code first: /{COMMAND} login, or /plugins configure {COMMAND}."


class ClaudeCodeSettings(BaseModel):
    """The JSON a `claude_code` declaration may carry. Nothing here is secret."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    credentials: Backend = Field(
        default="auto",
        description="Where the sign-in is kept: auto follows CLAUDE_CODE_CREDENTIALS when set, else the OS "
        "keyring when one exists, else a file; or always the keyring; or always a file readable only by you.",
    )


def token_store(backend: Backend) -> TokenStore:
    """The store for a plugin setting; `auto` defers to `CLAUDE_CODE_CREDENTIALS`, as the package does."""
    return default_store(None if backend == "auto" else backend)


class ClaudeCodeConfig:
    """The settings menu's rows: the sign-in, kept in the token store, and the storage choice, in plugin settings."""

    title = "Claude Code settings"

    def __init__(self, settings: ClaudeCodeSettings, save: Callable[[ClaudeCodeSettings], None]) -> None:
        """`save` persists new settings, as `host.save_settings` does."""
        self.settings = settings
        self._save = save

    def store(self) -> TokenStore:
        """The token store the current settings choose."""
        return token_store(self.settings.credentials)

    def rows(self) -> Sequence[FieldRow]:
        """The sign-in first, then where it is kept."""
        return (
            FieldRow(
                key="account",
                label="Sign-in",
                description="Enter signs in to your Claude subscription through the browser; R signs out.",
                default=SIGNED_OUT,
            ),
            FieldRow(
                key="credentials",
                label="Credential storage",
                description=ClaudeCodeSettings.model_fields["credentials"].description or "",
                default="auto",
                choices=get_args(Backend),
                choice_labels={"auto": "Keyring, else a file", "keyring": "OS keyring", "file": "File (0600)"},
                allow_custom=False,
            ),
        )

    def current(self, row: FieldRow) -> str:
        """Whether a sign-in is stored, or the storage choice. The menu runs this off the event loop."""
        if row.key == "account":
            return SIGNED_IN if self.store().load() is not None else SIGNED_OUT
        return self.settings.credentials

    def problem(self, row: FieldRow, text: str) -> str | None:
        """Only the storage row takes a value; the sign-in row opens the browser instead."""
        if row.key == "account":
            return None
        try:
            self._validated(text)
        except ValidationError as exc:
            return first_error(exc)
        return None

    def apply(self, row: FieldRow, raw: str) -> str:
        """Save the storage choice now; the next run reads the sign-in from there."""
        settings = self._validated(raw)
        self._save(settings)
        self.settings = settings
        return f"Claude Code credential storage: {row.display(raw)}. {status(self)}"

    def reset(self, row: FieldRow) -> str:
        """Sign out, or restore automatic storage."""
        if row.key == "account":
            return sign_out(self)
        return self.apply(row, "auto")

    def _validated(self, raw: str) -> ClaudeCodeSettings:
        return ClaudeCodeSettings.model_validate({**self.settings.model_dump(), "credentials": raw})


class Providers:
    """One provider per store, reused across runs so they share a connection pool.

    A provider is rebuilt when the stored sign-in differs from the one it holds: after signing in again here
    or from another process. Refreshes the provider makes itself are saved back, so they keep it in step.
    """

    def __init__(self) -> None:
        """Start empty; a provider is built on the first run."""
        self._cached: dict[Backend, ClaudeCodeProvider] = {}

    def model(self, name: str, backend: Backend) -> ClaudeCodeModel:
        """Build `name` on the stored sign-in, raising `UserError` with setup steps when there is none."""
        store = token_store(backend)
        credentials = store.load()
        if credentials is None:
            raise UserError(_SIGN_IN_FIRST)
        provider = self._cached.get(backend)
        if provider is None or provider.credentials != credentials:
            provider = self._cached[backend] = ClaudeCodeProvider(credentials, store=store)
        return ClaudeCodeModel(name, provider=provider)


def status(source: ClaudeCodeConfig) -> str:
    """One line on whether the plugin can run models, and where the sign-in lives."""
    store = source.store()
    where = f"the file {store.path}" if isinstance(store, ClaudeCodeTokenStore) else "the OS keyring"
    if store.load() is None:
        return f"Not signed in (sign-in would be kept in {where}). Run /{COMMAND} login."
    return f"Signed in to Claude Code; tokens are kept in {where}."


async def sign_in(source: ClaudeCodeConfig, show_url: Callable[[str], None]) -> str:
    """Sign in through the browser and save the tokens to the chosen store."""
    await login(store=source.store(), on_url=show_url)
    first = config.MODELS[0]
    return f"Signed in to Claude Code. Choose a model in /add_model > {PREFIX}, or run /model {PREFIX}:{first}."


def sign_out(source: ClaudeCodeConfig) -> str:
    """Forget the stored tokens; runs with `claude-code:` models then ask to sign in again."""
    source.store().delete()
    return "Signed out of Claude Code. The tokens stay valid at Anthropic until they expire."


async def configure(source: ClaudeCodeConfig, show_url: Callable[[str], None], runners: Runners = TERMINAL) -> str:
    """Open the settings menu until Esc or Save & close."""

    async def account() -> list[str]:
        try:
            return [await sign_in(source, show_url)]
        except UserError as exc:
            return [str(exc)]

    messages = await run_flow_async(FieldMenu(source), runners, submenus={"account": account})
    return "\n".join(messages) or "Claude Code settings unchanged."


def activate(host: PluginHost[DepsT]) -> None:
    """Register `claude-code:` models, the settings menu, and `/claude_code`."""
    if not hasattr(host, "model_provider"):
        raise RuntimeError(
            "This pydantic-clai2 cannot run plugin models. Upgrade to a release after 0.52.0, or until one is "
            "out, run `uv run clai2` from a checkout of https://github.com/pydantic/pydantic-ai main."
        )
    source = ClaudeCodeConfig(host.settings(ClaudeCodeSettings), host.save_settings)
    providers = Providers()
    host.model_provider(PREFIX, lambda name: providers.model(name, source.settings.credentials), models=config.MODELS)

    def show_url(url: str) -> None:
        host.console.print(
            f"Opening your browser to sign in to Claude Code. If it does not open, visit:\n{url}",
            markup=False,
            soft_wrap=True,
        )

    @host.configure
    async def settings_menu() -> str:
        return await configure(source, show_url)

    async def command(args: list[str]) -> str:
        if not args:
            return await settings_menu()
        if args == ["login"]:
            return await sign_in(source, show_url)
        if args == ["logout"]:
            return await asyncio.to_thread(sign_out, source)
        if args == ["status"]:
            return await asyncio.to_thread(status, source)
        raise ValueError(_HELP)

    host.commands.register(
        Command(
            name=COMMAND,
            description="Claude Code subscription: sign in, sign out, and credential storage (login, logout, status).",
            handler=command,
            complete=lambda args: (
                [word for word in ("login", "logout", "status") if word.startswith(args[0] if args else "")]
                if len(args) <= 1
                else []
            ),
        )
    )
