"""Paths, endpoints and defaults for atomsh."""

import os
from pathlib import Path

API_BASE = os.environ.get("ATOMSH_API_BASE", "https://atomgpt.org")
API_URL = f"{API_BASE}/api"

# OAuth (see my-open-webui custom_routes/mcp_oauth.py): the authorization
# server hands back the user's existing atomgpt.org API key as the access
# token, so one browser login yields a Bearer usable against /api.
MCP_URL = f"{API_BASE}/mcp/"

AUTHORIZE_URL = f"{API_BASE}/oauth/authorize"
TOKEN_URL = f"{API_BASE}/oauth/token"
REGISTER_URL = f"{API_BASE}/oauth/register"
CLIENT_NAME = "atomsh"

DEFAULT_MODEL = "gemma-4-26b"

# The mcp.* models run the AtomGPT agent server-side and ignore any tools the
# client sends (see atomgpt_agent.py — it reads only `model` and `messages`).
# A coding agent needs client-side tool calls, so they are not selectable.
SERVER_SIDE_AGENT_PREFIX = "mcp."

REQUEST_TIMEOUT = 300
MAX_STEPS = 40


def _xdg(env_var: str, default: str) -> Path:
    return Path(os.environ.get(env_var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "atomsh"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "atomsh"
AUTH_FILE = CONFIG_DIR / "auth.json"
SESSION_DIR = DATA_DIR / "sessions"

# The materials tool list changes rarely, so it is cached rather than fetched
# on every start. The MCP session itself is opened lazily, on first use.
MCP_TOOLS_CACHE = DATA_DIR / "mcp-tools.json"
MCP_CACHE_TTL = 24 * 3600


def workspace_root(start=None) -> Path:
    """The directory the agent treats as its workspace.

    A repository is the boundary that means something to the user, so if the
    starting directory is inside a git checkout, its root wins. Launching from
    a subdirectory otherwise makes most of the repo "outside the workspace",
    which is friction without any safety benefit.
    """
    here = Path(start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return here
