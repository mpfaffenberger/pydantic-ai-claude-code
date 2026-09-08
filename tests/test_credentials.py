"""Tests for credential parsing."""

from __future__ import annotations

import json
import time

import pytest

from pydantic_ai.exceptions import UserError

from pydantic_ai_claude_code.credentials import ClaudeCodeCredentials


def test_from_token_response_happy_path() -> None:
    creds = ClaudeCodeCredentials.from_token_response({"access_token": "a", "refresh_token": "r", "expires_in": 3600})
    assert creds.token == "a"
    assert creds.refresh_token.get_secret_value() == "r"
    assert creds.expires_at is not None


def test_from_token_response_missing_access_token() -> None:
    with pytest.raises(UserError):
        ClaudeCodeCredentials.from_token_response({"refresh_token": "r"})


def test_from_token_response_refresh_reuses_previous() -> None:
    previous = ClaudeCodeCredentials(access_token="old", refresh_token="keep-me")
    creds = ClaudeCodeCredentials.from_token_response({"access_token": "new"}, previous=previous)
    assert creds.token == "new"
    assert creds.refresh_token.get_secret_value() == "keep-me"


def test_from_token_file_roundtrip(tmp_path) -> None:
    path = tmp_path / "auth.json"
    original = ClaudeCodeCredentials(access_token="a", refresh_token="b")
    path.write_text(json.dumps(original.to_wire_dict()))
    loaded = ClaudeCodeCredentials.from_token_file(json.loads(path.read_text()))
    assert loaded == original


def test_to_wire_dict_contains_plain_tokens() -> None:
    creds = ClaudeCodeCredentials(access_token="a", refresh_token="b")
    wire = creds.to_wire_dict()
    assert wire["access_token"] == "a"
    assert wire["refresh_token"] == "b"


def test_expires_at_from_expires_in() -> None:
    before = time.time()
    creds = ClaudeCodeCredentials.from_token_response({"access_token": "a", "refresh_token": "r", "expires_in": 60})
    after = time.time()
    assert before + 55 <= creds.expires_at.timestamp() <= after + 65
