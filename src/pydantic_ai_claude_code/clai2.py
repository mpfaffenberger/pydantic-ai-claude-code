"""The CLAI2 plugin: chat with your Claude Code subscription as `claude-code:MODEL`.

Install it by copying this package's folder into CLAI2's plugins folder as `claude_code/`; CLAI2 loads it at
startup through the `ClaudeCodePlugin` the package's `__init__.py` declares. Everything it imports already ships with CLAI2, and it uses only
relative imports, so the copy runs on its own. `/login claude` signs in through the browser, and `/claude_code`
(or `C` in `/plugins`) opens the settings menu: sign in, sign out, and choose where the sign-in is kept. Then
pick a model in `/add_model` > `claude-code`.

The sign-in is an OAuth token pair, not an API key, so it does not go in `/keys`. It is kept where this
package keeps it outside CLAI2 (the OS keyring by default), so one sign-in serves CLAI2 and your own agents.
Plugin settings, which are plaintext SQLite, hold only the storage choice.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Sequence
from typing import IO, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.exceptions import UserError
from pydantic_clai2.commands import Command
from termflow.tui.terminal import raw_mode
from pydantic_clai2.plugins import ModelProvider, Plugin, PluginHost, PluginLogin, SessionEnd, SessionStart, TurnEnd
from pydantic_clai2.ui.menus.menu_worker import menu_key, run_worker
from pydantic_clai2.ui.menus.field_menu import TERMINAL, FieldMenu, FieldRow, Runners, first_error, run_flow_async

from . import __version__, config, updates
from .flow import login, parse_pasteback
from .model import ClaudeCodeModel
from .provider import ClaudeCodeProvider
from .storage import Backend, ClaudeCodeTokenStore, TokenStore, default_store

PREFIX = "claude-code"
"""Models run as `claude-code:NAME`; `NAME` is any Claude model ID the subscription serves."""

COMMAND = "claude_code"
"""CLAI2 command names are Python identifiers, so the command cannot share the prefix's hyphen."""

LOGIN = "claude"
"""`/login claude` signs in."""

SIGNED_IN = "signed in"
SIGNED_OUT = "not signed in"
_HELP = f"Usage: /{COMMAND} (settings menu), /{COMMAND} logout, or /{COMMAND} status. Sign in with /login {LOGIN}."


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

    def __init__(
        self,
        settings: ClaudeCodeSettings,
        save: Callable[[ClaudeCodeSettings], None],
    ) -> None:
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

    def model(self, name: str, source: ClaudeCodeConfig) -> ClaudeCodeModel:
        """Build `name` on the stored sign-in, raising `UserError` with setup steps when there is none."""
        backend = source.settings.credentials
        store = token_store(backend)
        credentials = store.load()
        if credentials is None:
            raise UserError(f"Sign in to Claude Code first: /login {LOGIN}.")
        provider = self._cached.get(backend)
        if provider is None or provider.credentials != credentials:
            provider = self._cached[backend] = ClaudeCodeProvider(credentials, store=store)
        return ClaudeCodeModel(name, provider=provider)


def status(source: ClaudeCodeConfig) -> str:
    """One line on whether the plugin can run models, and where the sign-in lives."""
    store = source.store()
    where = f"the file {store.path}" if isinstance(store, ClaudeCodeTokenStore) else "the OS keyring"
    if store.load() is None:
        return f"Not signed in (sign-in would be kept in {where}). Run /login {LOGIN}."
    return f"Signed in to Claude Code; tokens are kept in {where}."


async def sign_in(source: ClaudeCodeConfig, show_url: Callable[[str], None]) -> str:
    """Sign in through the browser, or a pasted redirect address, and save the tokens to the chosen store."""
    await login(store=source.store(), on_url=show_url, read_pasteback=lambda: run_worker(read_pasted_url))
    first = config.MODELS[0]
    return f"Signed in to Claude Code. Choose a model in /add_model > {PREFIX}, or run /model {PREFIX}:{first}."


PASTE_PROMPT = "Or paste the address your browser ended on, then Enter (Esc cancels): "


def read_pasted_url(keys: Callable[[], str] = menu_key, output: IO[str] = sys.stdout) -> str | None:
    """Read a pasted redirect address on one line, under the printed sign-in URL; `None` on Esc.

    The address carries the authorization code, so it is counted, not echoed: a long URL would also wrap
    and break the one-line redraw. `keys` is `run_worker`'s `menu_key`, which turns into `ctrl-c` when the
    browser's callback wins and `login` cancels this read.
    """
    chars: list[str] = []
    note = ""

    def draw() -> None:
        shown = note or (f"[{len(chars)} characters]" if chars else "")
        output.write(f"\r\x1b[K{PASTE_PROMPT}{shown}")
        output.flush()

    with raw_mode():
        draw()
        while True:
            key = keys()
            if key in ("escape", "ctrl-c"):
                output.write("\r\n")
                return None
            if key == "enter":
                if parse_pasteback("".join(chars)) is not None:
                    output.write("\r\n")
                    return "".join(chars)
                note = "no authorization code in that; paste the whole address"
            elif key == "backspace":
                chars[-1:] = []
                note = ""
            elif key == "ctrl-u":
                chars, note = [], ""
            elif len(key) == 1 and key.isprintable():
                chars.append(key)
                note = ""
            else:
                continue
            draw()


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


class ClaudeCodePlugin(Plugin[ClaudeCodeSettings]):
    """`claude-code:` models, `/login claude`, the settings menu, `/claude_code`, and the update notice."""

    def __init__(self, host: PluginHost, settings: ClaudeCodeSettings) -> None:
        """Build the provider and the menu's source once; CLAI2 loads the plugin again when settings change."""
        super().__init__(host, settings)
        self.source = ClaudeCodeConfig(settings, host.save_settings)
        self._providers = Providers()
        self._update: asyncio.Task[str | None] | None = None
        self.provider = ModelProvider(
            prefix=PREFIX, resolve=self._resolve, models=config.MODELS, settings_from="anthropic"
        )

    def _resolve(self, name: str) -> ClaudeCodeModel:
        return self._providers.model(name, self.source)

    def _show_url(self, url: str) -> None:
        self.host.console.print(
            "Opening your browser to sign in to Claude Code. If it does not open, or this machine's browser "
            f"cannot reach it (SSH, a remote box), open this anywhere and sign in:\n{url}",
            markup=False,
            soft_wrap=True,
        )

    def get_model_providers(self) -> Sequence[ModelProvider]:
        return (self.provider,)

    def get_logins(self) -> Sequence[PluginLogin]:
        return (PluginLogin(name=LOGIN, handler=self._sign_in, models=self.provider.names),)

    async def _sign_in(self) -> str:
        return await sign_in(self.source, self._show_url)

    def get_commands(self) -> Sequence[Command]:
        return (
            Command(
                name=COMMAND,
                description=f"Claude Code settings: sign-in, credential storage, logout, and status. "
                f"Sign in with /login {LOGIN}.",
                handler=self._command,
                complete=lambda args: (
                    [word for word in ("logout", "status") if word.startswith(args[0] if args else "")]
                    if len(args) <= 1
                    else []
                ),
            ),
        )

    async def _command(self, args: list[str]) -> str:
        if not args:
            return await self.configure()
        if args == ["logout"]:
            return await asyncio.to_thread(sign_out, self.source)
        if args == ["status"]:
            return await asyncio.to_thread(status, self.source)
        raise ValueError(_HELP)

    async def configure(self) -> str:
        return await configure(self.source, self._show_url)

    async def on_session_start(self, event: SessionStart) -> None:
        """Check PyPI for a newer release in the background, so startup never waits on it."""
        if updates.enabled():
            self._update = asyncio.create_task(updates.newer_release(__version__))

    async def on_turn_end(self, event: TurnEnd) -> None:
        """Mention a newer release once, after the first turn that finishes once the check is done."""
        if self._update is None or not self._update.done():
            return
        latest, self._update = self._update.result(), None
        if latest is not None:
            self.host.console.print(updates.notice(__version__, latest), markup=False, soft_wrap=True)

    async def on_session_end(self, event: SessionEnd) -> None:
        if self._update is not None:
            self._update.cancel()
