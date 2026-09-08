"""Tests for the token store."""

from __future__ import annotations

import stat

import pytest
from pydantic_ai.exceptions import UserError

from pydantic_ai_claude_code.credentials import ClaudeCodeCredentials
from pydantic_ai_claude_code.storage import ClaudeCodeTokenStore, default_auth_path


def test_save_load_roundtrip(tmp_path) -> None:
    store = ClaudeCodeTokenStore(path=tmp_path / "auth.json")
    creds = ClaudeCodeCredentials(access_token="a", refresh_token="b")
    store.save(creds)
    assert store.load() == creds


def test_save_sets_0644_perm(tmp_path) -> None:
    store = ClaudeCodeTokenStore(path=tmp_path / "auth.json")
    store.save(ClaudeCodeCredentials(access_token="a", refresh_token="b"))
    mode = stat.S_IMODE((tmp_path / "auth.json").stat().st_mode)
    assert mode == 0o644


def test_load_missing_returns_none(tmp_path) -> None:
    store = ClaudeCodeTokenStore(path=tmp_path / "nope.json")
    assert store.load() is None


def test_load_corrupt_raises(tmp_path) -> None:
    path = tmp_path / "auth.json"
    path.write_text("{not json")
    store = ClaudeCodeTokenStore(path=path)
    with pytest.raises(UserError):
        store.load()


def test_env_var_override(monkeypatch, tmp_path) -> None:
    target = tmp_path / "custom.json"
    monkeypatch.setenv("CLAUDE_CODE_AUTH_FILE", str(target))
    assert default_auth_path() == target


def test_default_path_uses_data_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CLAUDE_CODE_AUTH_FILE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_auth_path() == tmp_path / "pydantic-ai-claude-code" / "auth.json"
