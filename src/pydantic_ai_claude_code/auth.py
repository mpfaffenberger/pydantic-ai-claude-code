"""httpx2 auth shim that authenticates Messages API calls with Claude Code tokens."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable

import httpx2

from pydantic_ai.exceptions import UserError

from . import config
from .credentials import ClaudeCodeCredentials
from .flow import refresh_credentials

CredentialsRefreshCallback = Callable[[ClaudeCodeCredentials], Awaitable[None]]


class ClaudeCodeCredentialsPersistenceError(UserError):
    """Raised after refreshed in-memory credentials could not be persisted."""


def _expires_soon(credentials: ClaudeCodeCredentials) -> bool:
    if credentials.expires_at is None:
        return False
    return time.time() + 30 >= credentials.expires_at.timestamp()


class _ClaudeCodeAuth(httpx2.Auth):
    requires_response_body = True

    def __init__(self, credentials: ClaudeCodeCredentials, callback: CredentialsRefreshCallback | None = None) -> None:
        self.credentials = credentials
        self.callback = callback
        self.revision = 0
        self.lock = asyncio.Lock()
        self.refresh_client = httpx2.AsyncClient()

    async def _refresh(self, used_revision: int) -> None:
        async with self.lock:
            if self.revision != used_revision:
                return
            updated = await refresh_credentials(self.credentials, http_client=self.refresh_client)
            self.credentials = updated
            self.revision += 1
            if self.callback is not None:
                try:
                    await self.callback(updated)
                except Exception as exc:  # noqa: BLE001 - surface the persistence failure to the caller
                    raise ClaudeCodeCredentialsPersistenceError(
                        "Claude Code credentials refreshed in memory, but the persistence callback failed."
                    ) from exc

    def _apply(self, request: httpx2.Request) -> int:
        request.headers["Authorization"] = f"Bearer {self.credentials.token}"
        request.headers["x-app"] = config.X_APP
        request.headers["user-agent"] = config.USER_AGENT
        # Anthropic's SDK manages its own betas; ours must be merged, not replaced.
        existing_beta = request.headers.get("anthropic-beta")
        if config.ANTHROPIC_BETA not in (existing_beta or ""):
            request.headers["anthropic-beta"] = ", ".join(filter(None, [existing_beta, config.ANTHROPIC_BETA]))

        return self.revision

    async def async_auth_flow(self, request: httpx2.Request) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        revision = self._apply(request)
        if _expires_soon(self.credentials):
            await self._refresh(revision)
            revision = self._apply(request)
        response = yield request
        if response.status_code != 401:
            return
        await response.aread()
        await response.aclose()
        await self._refresh(revision)
        self._apply(request)
        yield request
