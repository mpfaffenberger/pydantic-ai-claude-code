"""Tests for keyring-backed storage and `default_store()` selection."""

from __future__ import annotations

import json

import keyring
import pytest
from pydantic_ai.exceptions import UserError

from pydantic_ai_claude_code.credentials import ClaudeCodeCredentials
from pydantic_ai_claude_code.storage import (
    ClaudeCodeTokenStore,
    KeyringTokenStore,
    default_store,
)


@pytest.fixture
def fake_keyring(monkeypatch) -> dict[str, str]:
    store: dict[str, str] = {}

    def set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def get_keyring() -> object:
        # Pretend a keychain backend exists.
        return object()

    monkeypatch.setattr(keyring, "set_password", set_password)
    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setattr(keyring, "get_keyring", get_keyring)
    return store


def test_keyring_roundtrip(fake_keyring) -> None:
    store = KeyringTokenStore()
    creds = ClaudeCodeCredentials(access_token="a", refresh_token="b")
    store.save(creds)
    assert store.load() == creds
    stored = fake_keyring[(KeyringTokenStore.SERVICE, KeyringTokenStore.USERNAME)]
    assert json.loads(stored)["access_token"] == "a"


def test_default_store_prefers_keyring(fake_keyring, monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_CREDENTIALS", raising=False)
    assert isinstance(default_store(), KeyringTokenStore)


def test_default_store_falls_back_to_file(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CLAUDE_CODE_CREDENTIALS", raising=False)

    def no_keyring() -> object:
        raise RuntimeError("no keychain (headless)")

    monkeypatch.setattr(keyring, "get_keyring", no_keyring)
    assert isinstance(default_store(), ClaudeCodeTokenStore)
    # The real (working) backend is irrelevant: with keyring out of the picture the
    # file store must be used, and it must respect CLAUDE_CODE_AUTH_FILE.
    monkeypatch.setenv("CLAUDE_CODE_AUTH_FILE", str(tmp_path / "custom.json"))
    assert default_store().path == tmp_path / "custom.json"  # type: ignore[attr-defined]


def test_default_store_env_override(monkeypatch, fake_keyring) -> None:
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS", "file")
    assert isinstance(default_store(), ClaudeCodeTokenStore)
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS", "keyring")
    assert isinstance(default_store(), KeyringTokenStore)


def test_default_store_bad_env_raises(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS", "bogus")
    with pytest.raises(UserError):
        default_store()
