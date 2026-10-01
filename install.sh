#!/bin/sh
# Install or update the Claude Code plugin for CLAI2, at the latest release (pass a tag such as v0.5.0, or main):
#   curl -fsSL https://raw.githubusercontent.com/mpfaffenberger/pydantic-ai-claude-code/main/install.sh | sh
set -eu

ref="${1:-}"
if [ -z "$ref" ]; then
    version=$(curl -fsSL https://pypi.org/pypi/pydantic-claude-code/json | grep -o '"version": *"[^"]*"' | head -n 1 | cut -d '"' -f 4)
    if [ -z "$version" ]; then
        echo "Could not look up the latest release on PyPI. Pass a tag (sh -s -- v0.5.0) or main." >&2
        exit 1
    fi
    ref="v$version"
fi
plugins="${XDG_CONFIG_HOME:-$HOME/.config}/pydantic-clai2/plugins"
target="$plugins/claude_code"

download=$(mktemp -d)
trap 'rm -rf "$download"' EXIT

curl -fsSL "https://codeload.github.com/mpfaffenberger/pydantic-ai-claude-code/tar.gz/$ref" | tar -xz -C "$download"
mkdir -p "$plugins"
rm -rf "$target"
mv "$download"/*/src/pydantic_ai_claude_code "$target"

echo "Installed the Claude Code plugin ($ref) to $target."
echo "Start clai2, sign in with /login claude, then /model claude-code:claude-opus-5-5."
