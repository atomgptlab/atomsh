"""Authentication against atomgpt.org.

The preferred flow is `atomsh login`: an OAuth 2.1 authorization-code
exchange with PKCE against atomgpt.org, using a loopback redirect. The
authorization server hands back the user's existing atomgpt.org API key as the
access token, so the result is a Bearer credential usable against /api.

`atomsh login --key` is the fallback for headless machines, where opening a
browser is not possible.
"""

import base64
import hashlib
import json
import os
import secrets
import select
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

from .browser import open_url
from .config import (
    API_URL,
    AUTHORIZE_URL,
    AUTH_FILE,
    CLIENT_NAME,
    REGISTER_URL,
    TOKEN_URL,
)


class AuthError(Exception):
    """Login failed, or the stored credential is not usable."""


# ── stored credential ────────────────────────────────────────────────────────

def load_token() -> str:
    """Return the stored token, or None. ATOMSH_API_KEY wins if set."""
    env = os.environ.get("ATOMSH_API_KEY")
    if env:
        return env.strip()
    try:
        with open(AUTH_FILE, encoding="utf-8") as fh:
            return json.load(fh).get("access_token")
    except (OSError, ValueError):
        return None


def save_token(token: str) -> None:
    """Persist the token 0600, creating the config dir if needed."""
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Create with restrictive permissions before writing the secret.
    fd = os.open(AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"access_token": token}, fh)


def forget_token() -> bool:
    """Delete the stored credential. Returns whether there was one."""
    try:
        AUTH_FILE.unlink()
        return True
    except OSError:
        return False


def whoami(token: str) -> dict:
    """Validate a token and return the account it belongs to.

    /api/models is the cheapest authenticated endpoint that exists on every
    deployment, so it doubles as the credential check.
    """
    try:
        r = httpx.get(
            f"{API_URL}/models",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except httpx.HTTPError as e:
        raise AuthError(f"could not reach {API_URL}: {e}") from e
    if r.status_code in (401, 403):
        raise AuthError("token rejected by atomgpt.org (401/403)")
    r.raise_for_status()
    models = [m.get("id") for m in (r.json().get("data") or [])]
    return {"models": models}


# ── OAuth login ──────────────────────────────────────────────────────────────

def _pkce_pair() -> tuple:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-shot handler that captures ?code=&state= from the redirect."""

    result = None

    def do_GET(self):  # noqa: N802, name fixed by BaseHTTPRequestHandler
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.result = {k: v[0] for k, v in params.items()}
        ok = "code" in _CallbackHandler.result
        body = (
            "<h2>atomsh is connected.</h2><p>You can close this tab.</p>"
            if ok
            else "<h2>Authorization failed.</h2><p>Return to the terminal.</p>"
        )
        payload = f"<!doctype html><meta charset=utf-8><body style='font-family:system-ui;margin:80px auto;max-width:420px'>{body}</body>".encode()
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        """Silence the default stderr access log."""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_flow(port: int) -> dict:
    """Register this client and build the authorization URL."""
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    try:
        reg = httpx.post(
            REGISTER_URL,
            json={"client_name": CLIENT_NAME, "redirect_uris": [redirect_uri]},
            timeout=30,
        )
        reg.raise_for_status()
        client_id = reg.json()["client_id"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise AuthError(f"client registration failed: {e}") from e

    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": "mcp",
    })
    return {"client_id": client_id, "redirect_uri": redirect_uri,
            "verifier": verifier, "state": state, "url": url}


def _exchange(flow: dict, code: str) -> str:
    """Trade an authorization code for the access token."""
    try:
        tok = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": flow["redirect_uri"],
                "client_id": flow["client_id"],
                "code_verifier": flow["verifier"],
            },
            timeout=30,
        )
        tok.raise_for_status()
        return tok.json()["access_token"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise AuthError(f"token exchange failed: {e}") from e


def _code_from_input(text: str) -> tuple:
    """Accept either the whole redirect URL or a bare code."""
    text = text.strip()
    if "?" in text or text.startswith("http"):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(text).query)
        return (params.get("code", [""])[0], params.get("state", [""])[0])
    return (text, "")


def login_manual(timeout: int = 300) -> str:
    """Login without a listener, for a machine the browser cannot reach.

    On a remote host the redirect lands on the browser's own 127.0.0.1, not the
    host running Atomsh, so nothing can catch the code. The browser still shows
    it in the address bar, and pasting that back is enough to finish.
    """
    flow = _start_flow(_free_port())
    print("Open this URL in a browser on any machine:\n")
    print(f"  {flow['url']}\n")
    print("After approving, the browser will fail to load a 127.0.0.1 page.")
    print("That is expected on a remote host. Copy its full address and paste "
          "it here.\n")
    try:
        pasted = input("Redirect URL (or just the code): ")
    except (EOFError, KeyboardInterrupt):
        print()
        raise AuthError("cancelled")

    code, state = _code_from_input(pasted)
    if not code:
        raise AuthError("no authorization code found in that input")
    if state and state != flow["state"]:
        raise AuthError("state mismatch, aborting")

    token = _exchange(flow, code)
    save_token(token)
    return token


def _await_paste(delivered: threading.Event, timeout: int):
    """Read a pasted line, unless the listener gets there first.

    input() cannot be cancelled, so stdin is polled instead: the moment the
    redirect lands on the local listener the prompt gives up and the browser
    path wins, with nothing for the user to do.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if delivered.is_set():
            return None
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 0.25)
        except (OSError, ValueError):
            delivered.wait(max(0, deadline - time.time()))
            return None
        if ready:
            line = sys.stdin.readline()
            if not line:          # EOF, fall back to waiting on the listener
                delivered.wait(max(0, deadline - time.time()))
                return None
            line = line.strip()
            if line:
                return line
    return None


def login_oauth(open_browser: bool = True, timeout: int = 300) -> str:
    """Run the browser login and return the access token.

    Starts a loopback listener, registers this client, sends the user to the
    consent screen, then exchanges the returned code for a token.
    """
    port = _free_port()
    flow = _start_flow(port)
    redirect_uri, state, url = flow["redirect_uri"], flow["state"], flow["url"]

    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = timeout
    _CallbackHandler.result = None

    delivered = threading.Event()

    def serve():
        try:
            server.handle_request()
        except OSError:
            pass
        finally:
            delivered.set()

    threading.Thread(target=serve, daemon=True).start()

    print("Open this URL to authorize atomsh:\n")
    print(f"  {url}\n")
    if open_browser:
        # In a thread: launching a Windows browser from WSL can block for
        # seconds, and the callback listener should already be waiting.
        threading.Thread(target=open_url, args=(url,), daemon=True).start()
        print("Trying to open it in your browser…")

    # Two ways in, whichever arrives first. The listener catches the redirect
    # when the browser is on this machine. When it is not, its 127.0.0.1 is a
    # different computer and nothing can arrive here, so the address bar is
    # the delivery mechanism and pasting it back finishes the job.
    can_paste = sys.stdin.isatty()
    if can_paste:
        print("\nWaiting for the browser. If it is on another machine, the "
              "127.0.0.1\npage will fail to load: paste its full address "
              "here instead.\n")
        pasted = _await_paste(delivered, timeout)
    else:
        print(f"Waiting for authorization (Ctrl-C to cancel, {timeout}s).")
        delivered.wait(timeout)
        pasted = None

    server.server_close()

    if pasted:
        code, pasted_state = _code_from_input(pasted)
        if not code:
            raise AuthError("no authorization code found in that input")
        if pasted_state and pasted_state != state:
            raise AuthError("state mismatch, aborting")
        token = _exchange(flow, code)
        save_token(token)
        return token

    result = _CallbackHandler.result
    if not result:
        raise AuthError(
            "timed out waiting for authorization. If the browser is on a "
            "different machine, paste the redirect address when prompted, or "
            "use `atomsh login --key`"
        )
    if result.get("error"):
        raise AuthError(f"authorization denied: {result['error']}")
    if result.get("state") != state:
        raise AuthError("state mismatch, aborting")

    token = _exchange(flow, result["code"])
    save_token(token)
    return token
