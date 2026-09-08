"""Token storage for Claude Code credentials.

By default credentials live in the OS keyring: the Keychain on macOS, Credential
Manager on Windows, Secret Service on Linux. When no keychain is available, a
JSON file with `0644` permissions is used instead. Force a backend with the
`CLAUDE_CODE_CREDENTIALS` env var (`keyring` or `file`); the file path honors
`CLAUDE_CODE_AUTH_FILE`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from pydantic_ai.exceptions import UserError

from .credentials import ClaudeCodeCredentials

_FILE_PERMISSIONS = 0o644


class TokenStore(Protocol):
    """Sibling store backends must both implement this shape."""

    def load(self) -> ClaudeCodeCredentials | None:
        """Return stored credentials, or `None` when nothing is stored yet."""
        ...

    def save(self, credentials: ClaudeCodeCredentials) -> None:
        """Persist credentials for the next run."""
        ...


def default_auth_path() -> Path:
    """The fallback token file path, honoring the `CLAUDE_CODE_AUTH_FILE` override."""
    env_path = os.environ.get("CLAUDE_CODE_AUTH_FILE")
    if env_path:
        return Path(env_path).expanduser()
    data_dir = Path(os.environ.get("XDG_DATA_HOME", "") or (Path.home() / ".local" / "share"))
    return data_dir / "pydantic-ai-claude-code" / "auth.json"


def default_store() -> TokenStore:
    """The default store: keyring when available, otherwise the JSON file."""
    backend = os.environ.get("CLAUDE_CODE_CREDENTIALS", "auto").lower()
    if backend not in ("auto", "keyring", "file"):
        raise UserError(f"Unknown CLAUDE_CODE_CREDENTIALS backend {backend!r}; expected 'auto', 'keyring', or 'file'.")
    if backend == "file":
        return ClaudeCodeTokenStore()
    if backend == "keyring" or _keyring_available():
        return KeyringTokenStore()
    return ClaudeCodeTokenStore()


class ClaudeCodeTokenStore:
    """JSON-file store with `0644` permissions, the no-keychain fallback."""

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
        """Persist credentials atomically with `0644` permissions."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(credentials.to_wire_dict(), indent=2))
        tmp.chmod(_FILE_PERMISSIONS)
        os.replace(tmp, self.path)


class KeyringTokenStore:
    """OS-keyring store backed by the `keyring` package.

    The service name is `pydantic-ai-claude-code` and credentials are stored as
    a single JSON blob under the `default` user name.
    """

    SERVICE = "pydantic-ai-claude-code"
    USERNAME = "default"

    def __init__(self, service: str = SERVICE, username: str = USERNAME) -> None:
        self.service = service
        self.username = username

    def load(self) -> ClaudeCodeCredentials | None:
        """Return stored credentials from the keyring, or `None` when absent."""
        raw = self._keyring_get()
        if not raw:
            return None
        return ClaudeCodeCredentials.from_token_file(json.loads(raw))

    def save(self, credentials: ClaudeCodeCredentials) -> None:
        """Persist credentials to the keyring."""
        self._keyring_require()
        import keyring

        keyring.set_password(self.service, self.username, json.dumps(credentials.to_wire_dict()))

    def _keyring_get(self) -> str | None:
        self._keyring_require()
        import keyring

        return keyring.get_password(self.service, self.username)

    @staticmethod
    def _keyring_require() -> None:
        try:
            import keyring

            keyring.get_keyring()
        except Exception as exc:  # noqa: BLE001 - no keychain service on this machine
            raise UserError(
                "No OS keyring is available. Set CLAUDE_CODE_CREDENTIALS=file to use the JSON file store."
            ) from exc


def _keyring_available() -> bool:
    try:
        import keyring

        keyring.get_keyring()
        return True
    except Exception:  # noqa: BLE001 - probe only; the store validates again on use
        return False
