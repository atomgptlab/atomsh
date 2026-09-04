"""Paths, endpoints and defaults for agapicode."""

import os
from pathlib import Path

API_BASE = os.environ.get("AGAPICODE_API_BASE", "https://atomgpt.org")
API_URL = f"{API_BASE}/api"

# OAuth (see my-open-webui custom_routes/mcp_oauth.py): the authorization
# server hands back the user's existing atomgpt.org API key as the access
# token, so one browser login yields a Bearer usable against /api.
AUTHORIZE_URL = f"{API_BASE}/oauth/authorize"
TOKEN_URL = f"{API_BASE}/oauth/token"
REGISTER_URL = f"{API_BASE}/oauth/register"
CLIENT_NAME = "agapicode"

DEFAULT_MODEL = "gemma-4-26b"

# The mcp.* models run the AtomGPT agent server-side and ignore any tools the
# client sends (see atomgpt_agent.py — it reads only `model` and `messages`).
# A coding agent needs client-side tool calls, so they are not selectable.
SERVER_SIDE_AGENT_PREFIX = "mcp."

REQUEST_TIMEOUT = 300
MAX_STEPS = 40


def _xdg(env_var: str, default: str) -> Path:
    return Path(os.environ.get(env_var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "agapicode"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "agapicode"
AUTH_FILE = CONFIG_DIR / "auth.json"
SESSION_DIR = DATA_DIR / "sessions"
