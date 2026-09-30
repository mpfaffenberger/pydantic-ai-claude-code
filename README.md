# pydantic-claude-code

Use your Claude Code subscription from a plain pydantic-ai `Agent` or from
[CLAI2](https://github.com/pydantic/pydantic-ai/tree/main/src/pydantic_clai2),
with full pydantic-ai tool support. No API key, no separate billing: if Claude
Code works from your terminal, this works too.

The repo is `mpfaffenberger/pydantic-ai-claude-code` and the import is
`pydantic_ai_claude_code`; the PyPI project is `pydantic-claude-code`
(`pip install pydantic-claude-code`).

## Models

| Model | ID |
|---|---|
| Claude Opus 5.5 | `claude-opus-5-5` |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` |
| Claude Fable 5.1 | `claude-fable-5-1` |
| Claude Haiku 4.5 | `claude-haiku-4-5` |

These are the current models, the ones CLAI2's menus offer (`config.MODELS`).
They were checked on 2026-09-30 against Anthropic's
[models overview](https://docs.anthropic.com/en/docs/about-claude/models/overview),
against the `anthropic` SDK's model list that pydantic-ai's `KnownModelName` is
built from, and live against a Claude subscription. Any other model ID your
subscription serves, such as `claude-opus-4-8`, works too; it just isn't listed.

## Use it in CLAI2

The plugin adds `claude-code:MODEL` models to CLAI2, next to its own providers,
so the stock agent, Coder, and your other plugins all keep working.

### Install: drop the folder in

The plugin is the `src/pydantic_ai_claude_code` folder, as is. Copy it into
CLAI2's plugins folder under the name `claude_code`. Nothing to `pip install`:
everything it imports (`pydantic-ai` with Anthropic support, `httpx2`,
`keyring`) already ships with CLAI2.

```bash
git clone --depth 1 https://github.com/mpfaffenberger/pydantic-ai-claude-code /tmp/claude-code-plugin
mkdir -p ~/.config/pydantic-clai2/plugins
cp -R /tmp/claude-code-plugin/src/pydantic_ai_claude_code ~/.config/pydantic-clai2/plugins/claude_code
```

The plugins folder is `$XDG_CONFIG_HOME/pydantic-clai2/plugins/`, which is
`~/.config/pydantic-clai2/plugins/` by default on macOS and Linux: the folder
next to CLAI2's `config.db`. To update, delete `claude_code` and copy again. To hack on the plugin, symlink the folder instead of copying it:
`ln -s "$PWD/src/pydantic_ai_claude_code" ~/.config/pydantic-clai2/plugins/claude_code`.

Dropped-in plugins load when CLAI2 starts. Inside CLAI2, `/plugins` lists it as
`claude_code`, where Space turns it off and on. (The shell's `clai2 plugins list`
shows only plugins added by name, so it won't appear there.)

**CLAI2 version:** the plugin needs `PluginHost.model_provider`
([pydantic/pydantic-ai#9468](https://github.com/pydantic/pydantic-ai/pull/9468),
merged), which the next `pydantic-clai2` release after 0.52.0 includes. On an
older CLAI2 the plugin fails to load with `This pydantic-clai2 cannot run plugin
models`. Until that release, run CLAI2 from pydantic-ai's `main`:

```bash
git clone https://github.com/pydantic/pydantic-ai
cd pydantic-ai
uv run clai2
```

Or install it as a package instead, into CLAI2's environment, and point CLAI2
at it: `uv tool install pydantic-clai2 --with pydantic-claude-code`, then
`/plugins add claude_code pydantic_ai_claude_code`.

### Sign in

Run `/claude_code login`. Your browser opens Claude's sign-in page, and CLAI2
prints the URL in case it doesn't. Or open the settings menu with `/claude_code`
(or `C` on the plugin in `/plugins`), choose **Sign-in**, and press Enter.

### Pick a model

Open `/add_model` and choose the `claude-code` provider, or type one directly:

```text
/add_model claude-code:claude-opus-5-5
/model claude-code:claude-sonnet-5-5
```

Headless runs work the same way:
`clai2 -p "Summarize this repo" -m claude-code:claude-fable-5-1`.

### Settings menu

`/plugins configure claude_code`, `C` in `/plugins`, or a bare `/claude_code`
opens it. Every change is saved right away and applies from the next run.

| Row | What it does | Stored in |
|---|---|---|
| Sign-in | Enter signs in through the browser; R signs out | the token store below, never in plugin settings |
| Credential storage | `auto` (`CLAUDE_CODE_CREDENTIALS`, else keyring, else a file), `keyring`, or `file` | plugin settings (`credentials`) |

`/claude_code login`, `/claude_code logout`, and `/claude_code status` do the
same without the menu.

### Where the sign-in lives

The sign-in is an OAuth token pair, not an API key, so it does not go in
`/keys`. It is kept where this package keeps it outside CLAI2, which means one
sign-in serves both CLAI2 and your own agents: the OS keyring (service
`pydantic-ai-claude-code`), or, without a keychain, a file readable only by
you. CLAI2's plugin settings are plaintext SQLite, so they hold only the
storage choice. Tokens are refreshed automatically and the refreshed pair is
saved back. The **Credential storage** row's `auto` follows the
`CLAUDE_CODE_CREDENTIALS` variable described below when it is set; `keyring`
and `file` override it.

Signing out deletes the stored tokens; they stay valid at Anthropic until they
expire. Switching storage does not move an existing sign-in, so sign in again
after switching.

If a run says `Sign in to Claude Code first` or `Your Claude Code sign-in has
expired`, run `/claude_code login`. If the
plugin fails to load with `This pydantic-clai2 cannot run plugin models`,
upgrade CLAI2 as described under [Install](#install-drop-the-folder-in).

## Use it from Python

pydantic-ai owns the loop: its `Agent` drives the conversation, runs your
tools, and validates structured output. This package is just a model plus a
provider. Instead of a `claude-code:` model string, construct
`ClaudeCodeModel('claude-fable-5-1')` directly; it connects itself to a
`ClaudeCodeProvider` by default.

### Quick start

```python
import asyncio

from pydantic_ai import Agent

from pydantic_ai_claude_code import ClaudeCodeModel, default_store, login


async def main() -> None:
    # One-time: opens your browser, mints tokens, stores them
    # (it only needs to run again when the tokens are revoked).
    if default_store().load() is None:
        await login()

    agent = Agent(ClaudeCodeModel('claude-opus-5-5'))

    result = await agent.run('Say hi in three words.')
    print(result.output)


asyncio.run(main())
```

You can also sign in from the shell: `python -m pydantic_ai_claude_code login`.

### With tools

```python
from pydantic_ai import Agent
from pydantic_ai_claude_code import ClaudeCodeModel

agent = Agent(ClaudeCodeModel('claude-sonnet-5-5'))

@agent.tool_plain
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
```

Tools defined on the agent are sent to the API as standard Anthropic tool
definitions. Structured output works the same way as with the built-in
`anthropic` provider.

### Structured output

```python
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai_claude_code import ClaudeCodeModel

class Weather(BaseModel):
    city: str
    temperature_c: float

agent = Agent(ClaudeCodeModel('claude-fable-5-1'), output_type=Weather)
result = await agent.run('Weather in Paris right now?')
assert result.output.city == 'Paris'
```

### Streaming

```python
from pydantic_ai import Agent
from pydantic_ai_claude_code import ClaudeCodeModel

agent = Agent(ClaudeCodeModel('claude-haiku-4-5'))
async with agent.run_stream('Count from 1 to 3.') as stream:
    async for chunk in stream.stream_text():
        print(chunk, end='', flush=True)
```

## How auth works

The flow uses the same shared public OAuth client that the Claude Code CLI
uses:

- Authorization URL: `https://claude.ai/oauth/authorize`
- Token URL: `https://platform.claude.com/v1/oauth/token`
- Scopes: `org:create_api_key user:profile user:inference`

Tokens are saved to the OS keyring by default: the Keychain on macOS,
Credential Manager on Windows, and Secret Service on Linux. On machines without
a keychain (including headless Linux, where `keyring` reports its `fail`
backend), credentials go to a JSON file instead, created `0600`. You can
override its path with `CLAUDE_CODE_AUTH_FILE`:

```
~/.local/share/pydantic-ai-claude-code/auth.json
```

The file only ever contains what the issuer gave us. We never read the CLI's
own credential files.

Force a backend with the `CLAUDE_CODE_CREDENTIALS` env var (`keyring` or
`file`), or pass one to `default_store('file')`.

Refreshes happen automatically: the auth shim refreshes before expiry and
retries once on a 401, exactly like pydantic-ai's Codex provider. When the
refresh token itself is rejected, runs raise `ClaudeCodeSignInExpiredError`
(a `UserError`) telling you to sign in again.

Requests identify as Claude Code 2.1.285. The persona
`"You are Claude Code, Anthropic's official CLI for Claude."` is prepended to
the system context (position 0), as the CLI sends it. The client version
matters: the subscription backend refuses newer models to older CLI versions
(Opus 5.5 needs 2.1.280 or newer).

## Security and scope

This is a plain Anthropic Messages API client, authenticated by your Claude
subscription tokens. It does not run the Claude Code CLI in a subprocess, so it
does not inherit Claude Code's sandboxing, permission prompts, or hooks. Treat
it like any agent that runs code: only give it tools you trust.

Projects using this are responsible for following Anthropic's rules for using
Claude Code credentials in their own products.

## Development

```bash
uv sync --extra dev --extra clai2
uv run ruff check src tests && uv run ruff format --check src tests
uv run pyright
uv run pytest
```

The tests never touch your real keychain or token file. They run against a
local Messages API stub, including a full CLAI2 turn through the plugin.

## Prior art

The OAuth mechanics (shared client ID, PKCE, token storage and refresh) are
lifted from the `claude_code_oauth` plugin in
[`code_puppy_core_plugins`](https://github.com/mpfaffenberger/code_puppy_core_plugins),
cleaned up and reshaped around the provider pattern in pydantic-ai.
