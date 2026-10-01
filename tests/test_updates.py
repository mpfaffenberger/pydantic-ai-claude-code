"""The update check: which PyPI versions count as newer, and what the plugin says about them."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from conftest import MessagesServer
from pydantic_ai_claude_code import __version__, updates


def test_the_folder_knows_its_release() -> None:
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    assert __version__ == pyproject["project"]["version"]


@pytest.mark.parametrize(
    ("release", "newer"),
    [("1.2.4", "1.2.4"), ("1.10.0", "1.10.0"), ("1.2.3", None), ("1.1.9", None), ("2.0.0rc1", None)],
)
async def test_only_a_newer_final_release_counts(
    messages_stub: MessagesServer, monkeypatch: pytest.MonkeyPatch, release: str, newer: str | None
) -> None:
    monkeypatch.setattr(updates, "RELEASES_URL", messages_stub.url)
    messages_stub.release = release
    assert await updates.newer_release("1.2.3") == newer


async def test_an_unreachable_index_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates, "RELEASES_URL", "http://127.0.0.1:9/")
    assert await updates.newer_release("1.2.3", timeout=1) is None


def test_the_env_var_turns_the_check_off(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not updates.enabled()  # conftest sets it for every test
    monkeypatch.setenv("CLAUDE_CODE_NO_UPDATE_CHECK", "0")
    assert updates.enabled()
    monkeypatch.delenv("CLAUDE_CODE_NO_UPDATE_CHECK")
    assert updates.enabled()


def test_the_notice_says_how_to_update() -> None:
    assert updates.notice("0.5.0", "0.6.0") == (
        f"Claude Code plugin 0.6.0 is out (you have 0.5.0). Update: {updates.INSTALL}"
    )
