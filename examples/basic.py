"""Run the OAuth web flow, then run a real agent on `claude-fable-5-1`.

Requires a Claude (chat) subscription and a browser. Run:

    python examples/basic.py
"""

from __future__ import annotations

import asyncio

from pydantic_ai import Agent

from pydantic_ai_claude_code import ClaudeCodeProvider, default_store, login


async def main() -> None:
    # Only run the browser flow when no usable credentials are stored yet.
    if default_store().load() is None:
        await login()

    provider = ClaudeCodeProvider()
    agent = Agent(provider.model("claude-fable-5-1"))

    result = await agent.run("Say hi in exactly three words.")
    print("Agent said:", result.output)


if __name__ == "__main__":
    asyncio.run(main())
