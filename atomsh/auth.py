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
import socket
import threading
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

    def do_GET(self):  # noqa: N802 — name fixed by BaseHTTPRequestHandler
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


def login_oauth(open_browser: bool = True, timeout: int = 300) -> str:
    """Run the browser login and return the access token.

    Starts a loopback listener, registers this client, sends the user to the
    consent screen, then exchanges the returned code for a token.
    """
    port = _free_port()
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

    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = timeout
    _CallbackHandler.result = None

    print("Open this URL to authorize atomsh:\n")
    print(f"  {url}\n")
    if open_browser:
        # In a thread: launching a Windows browser from WSL can block for
        # seconds, and the callback listener should already be waiting.
        threading.Thread(target=open_url, args=(url,), daemon=True).start()
        print("Trying to open it in your browser…")
    print(f"Waiting for authorization (Ctrl-C to cancel, {timeout}s timeout).")

    server.handle_request()  # blocks until the redirect arrives or times out
    server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise AuthError("timed out waiting for the browser redirect")
    if result.get("error"):
        raise AuthError(f"authorization denied: {result['error']}")
    if result.get("state") != state:
        raise AuthError("state mismatch — aborting")

    try:
        tok = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": result["code"],
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
            },
            timeout=30,
        )
        tok.raise_for_status()
        token = tok.json()["access_token"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise AuthError(f"token exchange failed: {e}") from e

    save_token(token)
    return token
