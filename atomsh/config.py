"""Paths, endpoints and defaults for atomsh."""

import os
from pathlib import Path

API_BASE = os.environ.get("ATOMSH_API_BASE", "https://atomgpt.org")
API_URL = f"{API_BASE}/api"

# atomgpt.org is the authorization server: one browser approval returns a
# Bearer credential usable against /api, so there is no key to paste.
MCP_URL = f"{API_BASE}/mcp/"

AUTHORIZE_URL = f"{API_BASE}/oauth/authorize"
TOKEN_URL = f"{API_BASE}/oauth/token"
REGISTER_URL = f"{API_BASE}/oauth/register"
CLIENT_NAME = "atomsh"

DEFAULT_MODEL = "gemma-4-26b"

# The mcp.* models run the AtomGPT materials agent on the server and answer in
# prose; tools sent by a client are not used. A coding agent needs client-side
# tool calls, so those models are not selectable here.
SERVER_SIDE_AGENT_PREFIX = "mcp."

REQUEST_TIMEOUT = 300

# One installation or port can easily run past a hundred tool calls: configure,
# build, read the failure, patch, rebuild, test. A cap low enough to stop that
# mid-build reads to the user as the agent giving up, so it is generous here
# and overridable for anyone who wants a tighter leash.
MAX_STEPS = int(os.environ.get("ATOMSH_MAX_STEPS") or 200)

# Ceiling for the transcript sent to the model. Under the real window, since
# the estimate is approximate and the reply needs room of its own; a 400 for
# an overlong request ends the run, so it is better to compact slightly early.
CONTEXT_TOKENS = int(os.environ.get("ATOMSH_CONTEXT_TOKENS") or 40000)


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
