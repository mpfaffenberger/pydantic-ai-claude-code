"""The CLAI2 plugin: registration, sign-in, the settings menu, and a real CLAI2 turn on a stubbed API."""

from __future__ import annotations

import ast
import asyncio
import io
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Generic, TypeVar, cast

import pytest
from pydantic import JsonValue
from pydantic_ai import Agent
from pydantic_ai.exceptions import UserError
from pydantic_clai2 import chat
from pydantic_clai2.commands import Command
from pydantic_clai2.config import Settings
from pydantic_clai2.config.settings_store import SettingsStore
from pydantic_clai2.plugins import LoadedPlugin, PluginHost, SessionEnd, SessionStart, TurnEnd, load_plugin
from pydantic_clai2.ui.menus.field_menu import Runners
from rich.console import Console
from termflow.tui import MenuItem
from termflow.tui.menu import Menu, MenuResult

from conftest import TEXT, MessagesServer
import pydantic_ai_claude_code
from pydantic_ai_claude_code import clai2, config, storage, updates
from pydantic_ai_claude_code.clai2 import (
    SIGNED_IN,
    SIGNED_OUT,
    ClaudeCodeConfig,
    ClaudeCodePlugin,
    ClaudeCodeSettings,
    configure,
    token_store,
)
from pydantic_ai_claude_code.credentials import ClaudeCodeCredentials
from pydantic_ai_claude_code.model import ClaudeCodeModel
from pydantic_ai_claude_code.storage import ClaudeCodeTokenStore, KeyringTokenStore, TokenStore

PromptT = TypeVar("PromptT")
CREDS = ClaudeCodeCredentials(access_token="sub-token", refresh_token="refresh")
URL = "https://claude.ai/oauth/authorize?state=x"


def load(saved: list[dict[str, JsonValue]] | None = None) -> LoadedPlugin[None]:
    """Load the plugin as CLAI2 does, on a host with a captured console."""
    host = PluginHost[None](
        name="claude_code",
        console=Console(file=io.StringIO(), width=300),
        settings={},
        save_settings=(saved if saved is not None else []).append,
    )
    return load_plugin(ClaudeCodePlugin, host)


def output(loaded: LoadedPlugin[None]) -> str:
    return cast(io.StringIO, loaded.host.console.file).getvalue()


def command(loaded: LoadedPlugin[None]) -> Command:
    return next(command for command in loaded.commands if command.name == clai2.COMMAND)


async def run(loaded: LoadedPlugin[None], *args: str) -> str:
    result = command(loaded).handler(list(args))
    return await cast(Awaitable[str], result)


async def fake_login(*, store: TokenStore, on_url: Callable[[str], None]) -> ClaudeCodeCredentials:
    on_url(URL)
    store.save(CREDS)
    return CREDS


async def failing_login(*, store: TokenStore, on_url: Callable[[str], None]) -> ClaudeCodeCredentials:
    raise UserError("Claude Code OAuth callback timed out.")


def pick(value: str) -> MenuResult:
    return MenuResult(item=MenuItem(value, value=value))


def scripted(*lists: MenuResult, choice: str = "file") -> Runners:
    remaining = iter(lists)

    def run_list(menu: Menu) -> MenuResult:
        return next(remaining, MenuResult(cancelled=True))

    return Runners(run_list=run_list, run_choice=lambda menu: pick(choice))


def test_models_are_the_current_claude_lineup() -> None:
    assert config.MODELS == ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-haiku-4-5")


def test_the_plugin_declares_the_prefix_the_login_the_menu_and_the_command() -> None:
    loaded = load()
    [provider] = loaded.model_providers
    assert provider.prefix == "claude-code"
    assert provider.names == tuple(f"claude-code:{name}" for name in config.MODELS)
    assert provider.settings_from == "anthropic"
    [login] = loaded.logins
    assert login.name == "claude"
    assert login.models == provider.names, "signing in adds every listed model"
    assert loaded.plugin.has_configure
    assert list(command(loaded).complete(["lo"])) == ["logout"]
    assert list(command(loaded).complete(["status", "x"])) == []


def test_the_package_declares_the_plugin_clai2_loads() -> None:
    assert issubclass(pydantic_ai_claude_code.ClaudeCodePlugin, ClaudeCodePlugin)
    assert pydantic_ai_claude_code.ClaudeCodePlugin.__module__ == "pydantic_ai_claude_code"


def test_the_package_imports_without_clai2() -> None:
    script = (
        "import sys; sys.modules['pydantic_clai2'] = None; import pydantic_ai_claude_code as package; "
        "assert not hasattr(package, 'ClaudeCodePlugin'); print(package.ClaudeCodeModel.__name__)"
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "ClaudeCodeModel"


def test_resolve_needs_a_sign_in_and_reuses_the_provider_until_it_changes() -> None:
    [provider] = load().model_providers
    with pytest.raises(UserError, match="Sign in to Claude Code first: /login claude"):
        provider.resolve("claude-opus-5-5")

    store = ClaudeCodeTokenStore()  # `auto` without a keychain, as in these tests, is the file
    store.save(CREDS)
    opus, sonnet = provider.resolve("claude-opus-5-5"), provider.resolve("claude-sonnet-5-5")
    assert isinstance(opus, ClaudeCodeModel) and opus.model_name == "claude-opus-5-5"
    assert isinstance(sonnet, ClaudeCodeModel) and sonnet.client is opus.client

    store.save(ClaudeCodeCredentials(access_token="new", refresh_token="new-refresh"))
    renewed = provider.resolve("claude-opus-5-5")
    assert isinstance(renewed, ClaudeCodeModel) and renewed.client is not opus.client


async def test_login_claude_then_the_command_reports_and_signs_out(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setattr(clai2, "login", fake_login)
    loaded = load()
    assert (await run(loaded, "status")).startswith("Not signed in (sign-in would be kept in the file ")

    [login] = loaded.logins
    message = await login.handler()
    assert message == (
        "Signed in to Claude Code. Choose a model in /add_model > claude-code, or run /model claude-code:claude-opus-5-5."
    )
    assert URL in output(loaded)
    status = await run(loaded, "status")
    assert status == f"Signed in to Claude Code; tokens are kept in the file {ClaudeCodeTokenStore().path}."
    assert str(isolated_home) in status

    assert (await run(loaded, "logout")).startswith("Signed out of Claude Code.")
    assert ClaudeCodeTokenStore().load() is None
    for retired in ("login", "bogus"):
        with pytest.raises(ValueError, match="Usage: /claude_code .*Sign in with /login claude"):
            await run(loaded, retired)


async def turns_until(loaded: LoadedPlugin[None], text: str) -> None:
    for _ in range(200):
        await loaded.dispatch(TurnEnd(text="hi", outcome="completed"))
        if text in output(loaded):
            return
        await asyncio.sleep(0.01)


async def test_an_update_is_mentioned_once_after_a_turn(
    messages_stub: MessagesServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_NO_UPDATE_CHECK")
    monkeypatch.setattr(updates, "RELEASES_URL", messages_stub.url)
    messages_stub.release = "99.0.0"
    loaded = load()
    await loaded.dispatch(SessionStart(agent=Agent("test"), settings=Settings()))
    await turns_until(loaded, "99.0.0")
    await loaded.dispatch(TurnEnd(text="hi", outcome="completed"))
    assert output(loaded).count("Claude Code plugin 99.0.0 is out") == 1
    await loaded.dispatch(SessionEnd(reason="exit"))


async def test_a_session_ending_mid_check_cancels_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_NO_UPDATE_CHECK")
    started, never = asyncio.Event(), asyncio.Event()

    async def slow(current: str) -> str | None:
        started.set()
        await never.wait()
        return "99.0.0"

    monkeypatch.setattr(updates, "newer_release", slow)
    loaded = load()
    await loaded.dispatch(SessionStart(agent=Agent("test"), settings=Settings()))
    await started.wait()
    await loaded.dispatch(TurnEnd(text="hi", outcome="completed"))
    await loaded.dispatch(SessionEnd(reason="exit"))
    await asyncio.sleep(0)
    assert "is out" not in output(loaded), "an unfinished check says nothing"


async def test_the_update_check_can_be_turned_off(
    messages_stub: MessagesServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(updates, "RELEASES_URL", messages_stub.url)
    messages_stub.release = "99.0.0"
    loaded = load()  # conftest sets CLAUDE_CODE_NO_UPDATE_CHECK=1
    await loaded.dispatch(SessionStart(agent=Agent("test"), settings=Settings()))
    await turns_until(loaded, "99.0.0")
    await loaded.dispatch(SessionEnd(reason="exit"))
    assert "is out" not in output(loaded)


async def test_bare_command_opens_the_settings_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_configure(source: ClaudeCodeConfig, show_url: Callable[[str], None]) -> str:
        show_url(URL)
        return f"menu for {source.settings.credentials}"

    monkeypatch.setattr(clai2, "configure", fake_configure)
    loaded = load()
    assert await run(loaded) == "menu for auto"
    assert await loaded.plugin.configure() == "menu for auto"
    assert URL in output(loaded)


async def test_menu_switches_storage_then_signs_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clai2, "login", fake_login)
    saved: list[ClaudeCodeSettings] = []
    source = ClaudeCodeConfig(ClaudeCodeSettings(), saved.append)
    urls: list[str] = []

    message = await configure(source, urls.append, scripted(pick("credentials"), pick("account")))

    assert saved == [ClaudeCodeSettings(credentials="file")]
    assert message.splitlines() == [
        "Claude Code credential storage: File (0600). "
        f"Not signed in (sign-in would be kept in the file {ClaudeCodeTokenStore().path}). Run /login claude.",
        "Signed in to Claude Code. Choose a model in /add_model > claude-code, or run /model claude-code:claude-opus-5-5.",
    ]
    assert urls == [URL]
    assert ClaudeCodeTokenStore().load() == CREDS


async def test_menu_reports_a_failed_sign_in_and_an_untouched_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clai2, "login", failing_login)
    source = ClaudeCodeConfig(ClaudeCodeSettings(), lambda settings: None)
    assert await configure(source, print, scripted(pick("account"))) == "Claude Code OAuth callback timed out."
    assert await configure(source, print, scripted()) == "Claude Code settings unchanged."


def test_auto_follows_the_env_var_and_explicit_choices_do_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "_keyring_available", lambda: True)
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS", "file")
    assert isinstance(token_store("auto"), ClaudeCodeTokenStore)
    assert isinstance(token_store("keyring"), KeyringTokenStore)
    monkeypatch.delenv("CLAUDE_CODE_CREDENTIALS")
    assert isinstance(token_store("auto"), KeyringTokenStore)
    assert isinstance(token_store("file"), ClaudeCodeTokenStore)


def test_rows_show_state_validate_and_reset() -> None:
    saved: list[ClaudeCodeSettings] = []
    source = ClaudeCodeConfig(ClaudeCodeSettings(credentials="file"), saved.append)
    account, storage = source.rows()
    assert source.current(account) == SIGNED_OUT
    assert source.current(storage) == "file"
    assert source.problem(account, "anything") is None
    assert source.problem(storage, "keyring") is None
    assert source.problem(storage, "cloud") is not None

    ClaudeCodeTokenStore().save(CREDS)
    assert source.current(account) == SIGNED_IN
    assert source.reset(account).startswith("Signed out")
    assert source.current(account) == SIGNED_OUT

    assert source.reset(storage).startswith("Claude Code credential storage: Keyring, else a file.")
    assert saved == [ClaudeCodeSettings(credentials="auto")]


PACKAGE = Path(pydantic_ai_claude_code.__file__).parent
# What CLAI2 itself installs, so a copied folder can import it: see pydantic-clai2's dependencies.
CLAI2_PROVIDES = {"anthropic", "httpx2", "keyring", "pydantic", "pydantic_ai", "pydantic_clai2"}


@pytest.mark.parametrize("module", sorted(PACKAGE.glob("*.py")), ids=lambda path: path.name)
def test_the_folder_imports_only_itself_the_stdlib_and_clai2s_dependencies(module: Path) -> None:
    """A copy in the plugins folder has no installed `pydantic_ai_claude_code` to fall back on."""
    for node in ast.walk(ast.parse(module.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level:
            continue  # relative: resolved inside the copied folder
        names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
        if isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            top = name.partition(".")[0]
            assert top in sys.stdlib_module_names or top in CLAI2_PROVIDES, f"{module.name} imports {name}"


async def test_clai2_runs_the_package_folder_as_a_drop_in(
    messages_stub: MessagesServer, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Copy the package folder into the plugins folder, as the README says; a CLAI2 turn runs through it."""
    ClaudeCodeTokenStore().save(CREDS)
    prompts = ["/plugins list", "/login nope", "hi", "/exit"]

    class Prompt(Generic[PromptT]):  # CLAI2 builds `PromptSession[str]`
        def __init__(self, **kwargs: object) -> None:
            pass

        async def prompt_async(self, label: str, **kwargs: object) -> str:
            return prompts.pop(0)

    monkeypatch.setattr("pydantic_clai2._app.PromptSession", Prompt)
    store = SettingsStore(isolated_home / "clai2" / "config.db")
    store.plugins_dir.mkdir(parents=True, exist_ok=True)
    drop_in = store.plugins_dir / "claude_code"
    shutil.copytree(PACKAGE, drop_in, ignore=shutil.ignore_patterns("__pycache__"))
    # The copy is its own module tree, so patching the installed `config` would not reach it.
    copied_config = drop_in / "config.py"
    copied_config.write_text(copied_config.read_text().replace(config.API_BASE_URL, messages_stub.url))
    shown = io.StringIO()

    await chat(
        Agent("test"),
        deps=None,
        settings=Settings(model="claude-code:claude-opus-5-5"),
        console=Console(file=shown, width=200),
        store=store,
    )

    assert f"claude_code: {drop_in / '__init__.py'} (enabled, loaded)" in shown.getvalue()
    assert "Usage: /login [codex|copilot|claude]" in shown.getvalue()
    assert TEXT in shown.getvalue()
    assert messages_stub.received["model"] == "claude-opus-5-5"
    loaded = {
        Path(module.__file__).parent for module in list(sys.modules.values()) if getattr(module, "__file__", None)
    }
    assert drop_in in loaded, "the turn ran on the copied folder"
    assert "You are Claude Code" in str(messages_stub.received.get("system"))
