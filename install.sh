#!/bin/sh
# Install or update the Claude Code plugin for CLAI2 (pass a tag, such as v0.5.0, to pin a release):
#   curl -fsSL https://raw.githubusercontent.com/mpfaffenberger/pydantic-ai-claude-code/main/install.sh | sh
set -eu

ref="${1:-main}"
plugins="${XDG_CONFIG_HOME:-$HOME/.config}/pydantic-clai2/plugins"
target="$plugins/claude_code"

download=$(mktemp -d)
trap 'rm -rf "$download"' EXIT

curl -fsSL "https://codeload.github.com/mpfaffenberger/pydantic-ai-claude-code/tar.gz/$ref" | tar -xz -C "$download"
mkdir -p "$plugins"
rm -rf "$target"
mv "$download"/*/src/pydantic_ai_claude_code "$target"

echo "Installed the Claude Code plugin ($ref) to $target."
echo "Start clai2, sign in with /login claude (or /claude_code login), then /model claude-code:claude-opus-5-5."
