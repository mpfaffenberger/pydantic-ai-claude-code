"""OAuth endpoint and client configuration for Claude Code authentication.

These values mirror the shared OAuth client the official Claude Code CLI uses. See
`flow.py` for the authorization-code flow, and `provider.py` for the API client.
"""

# OAuth endpoints and shared client id used by the Claude Code CLI.
AUTH_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
SCOPES = "org:create_api_key user:profile user:inference"

# The subscription tokens minted by this flow are valid against api.anthropic.com.
API_BASE_URL = "https://api.anthropic.com"

# Redirect handling. We host a short-lived callback server on localhost, and also
# support pasting the `claude://oauth/callback?...` URL into the terminal.
REDIRECT_HOST = "http://localhost"
REDIRECT_PATH = "callback"
CALLBACK_PORT_RANGE = (8765, 8795)
CALLBACK_TIMEOUT = 180
PASTEBACK_SCHEMES = ("claude://",)

# Request headers that must accompany Claude Code subscription tokens. `anthropic-beta` is
# appended (never replaced) by the auth layer so feature betas set by pydantic-ai survive.
ANTHROPIC_BETA = "oauth-2025-04-20"
USER_AGENT = "claude-cli/2.1.263 (external, cli)"
X_APP = "cli"
