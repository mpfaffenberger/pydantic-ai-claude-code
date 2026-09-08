"""Persistent token storage for Claude Code credentials.

The file lives under the user's data directory, is created with `0o600`
permissions, and its path can be overridden with the `CLAUDE_CODE_AUTH_FILE`
environment variable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic_ai.exceptions import UserError

from .credentials import ClaudeCodeCredentials


def default_auth_path() -> Path:
    """The token file path, honoring the `CLAUDE_CODE_AUTH_FILE` override."""
    env_path = os.environ.get("CLAUDE_CODE_AUTH_FILE")
    if env_path:
        return Path(env_path).expanduser()
    data_dir = Path(os.environ.get("XDG_DATA_HOME", "") or (Path.home() / ".local" / "share"))
    return data_dir / "pydantic-ai-claude-code" / "auth.json"


class ClaudeCodeTokenStore:
    """Read and write `ClaudeCodeCredentials` to a single JSON file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_auth_path()

    def load(self) -> ClaudeCodeCredentials | None:
        """Return stored credentials, or `None` when nothing is stored yet."""
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise UserError(f"Unable to read Claude Code credentials from {str(self.path)!r}.") from exc
        return ClaudeCodeCredentials.from_token_file(data)

    def save(self, credentials: ClaudeCodeCredentials) -> None:
        """Persist credentials atomically with restrictive permissions."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(credentials.to_wire_dict(), indent=2))
        tmp.chmod(0o600)
        os.replace(tmp, self.path)
