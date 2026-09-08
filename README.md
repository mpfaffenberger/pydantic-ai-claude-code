# pydantic-claude-code

Use your Claude Code subscription from a plain pydantic-ai `Agent`, with full
pydantic-ai tool support. No API key, no separate billing: if Claude Code works
from your terminal, this wheel works too.

The repo is `mpfaffenberger/pydantic-ai-claude-code` and the import is
`pydantic_ai_claude_code`; the PyPI project is `pydantic-claude-code`
(`pip install pydantic-claude-code`).

## Why

pydantic-ai gained a Codex OAuth path where `openai-codex:gpt-6-astra` just
works against a ChatGPT subscription. This wheel brings the same experience to
Claude: authenticate once, then run pydantic-ai agents against your Claude
subscription, using `claude-sonnet-4-5`, `claude-opus-5`, or whatever model you
subscribe to.

Two deliberate design choices distinguish this from a fork of pydantic-ai:

1. **pydantic-ai owns the loop.** We don't hand the whole agent loop to the
   Claude Code CLI. pydantic-ai's own `Agent` machinery drives the conversation,
   executes your tools, and validates structured output. The wheel is a model
   + provider, not a second agent fighting for control.
2. **Object-only resolution.** Instead of a `claude-code:` model-name string
   (which would require patching pydantic-ai's internals), pass the model
   object you build from the provider.

## Quick start

```python
import asyncio

from pydantic_ai import Agent

from pydantic_ai_claude_code import ClaudeCodeProvider, login

async def main() -> None:
    # One-time: opens your browser, mints tokens, stores them
    # (only needs to run again when tokens are revoked).
    await login()

    provider = ClaudeCodeProvider()  # loads the stored tokens
    agent = Agent(provider.model('claude-sonnet-4-5'))

    result = await agent.run('Say hi in three words.')
    print(result.data)

asyncio.run(main())
```

### With tools

```python
from pydantic_ai import Agent

provider = ClaudeCodeProvider()
agent = Agent(provider.model('claude-sonnet-4-5'))

@agent.tool_plain
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
```

Tools defined on the agent are passed to the API as standard Anthropic tool
definitions, and structured output works the same way as with the built-in
`anthropic` provider. That's the whole point of the wheel.

## How auth works

The flow uses the same shared OAuth client the Claude Code CLI uses:

- Authorization URL: `https://claude.ai/oauth/authorize`
- Token URL: `https://platform.claude.com/v1/oauth/token`
- Scopes: `org:create_api_key user:profile user:inference`

Tokens are stored in (overridable via `CLAUDE_CODE_AUTH_FILE`):

```
~/.local/share/pydantic-ai-claude-code/auth.json
```

The file is written with `0o600` permissions and only ever contains what the
issuer gave us. We never read the CLI's own credential files.

Refreshes happen automatically in the background: the auth shim refreshes
before expiry and retries once on a 401, exactly like the codex provider does.

Requests identify as Claude Code: `"You are Claude Code, Anthropic's official
CLI for Claude."` is prepended to the system context (position 0), the same
persona the CLI sends. The subscription backend expects it and rate-gates
premium models without it.

## Security and scope

This is a plain Anthropic Messages API client authenticated by your Claude
subscription tokens. It does not run the Claude Code CLI in a subprocess, so it
does not inherit Claude Code's sandboxing, permission prompts, or hooks. Treat
it like any code-executing agent: only give it tools you trust.

Projects using this are responsible for following Anthropic's rules for using
Claude Code credentials in their own products.

## Development

```bash
uv sync --extra dev  # or: source .venv/bin/activate && pip install -e ".[dev]"
ruff check src tests
pytest
```

## Prior art

The OAuth mechanics (shared client id, PKCE, token storage and refresh) are
lifted from the `claude_code_oauth` plugin in
[`code_puppy_core_plugins`](https://github.com/mpfaffenberger/code_puppy_core_plugins),
cleaned up and reshaped around the provider pattern in pydantic-ai.
