"""A small MCP client for the AtomGPT tool server.

Enough of the streamable-HTTP transport to initialize a session, list tools,
and call them: JSON-RPC over POST, with responses framed as server-sent
events. The same Bearer token used for the chat endpoint authenticates here,
so `--materials` costs the user nothing extra to set up.
"""

import json
import time
from pathlib import Path

import httpx

PROTOCOL_VERSION = "2025-06-18"


class MCPError(Exception):
    """The tool server refused a request, or returned something unusable."""


class MCPClient:
    """Session against one MCP server."""

    def __init__(self, token: str, url: str, timeout: int = 300,
                 client_name: str = "atomsh", client_version: str = "0.1.0"):
        self.token = token
        self.url = url
        self.timeout = timeout
        self.client_name = client_name
        self.client_version = client_version
        self.session_id = None
        self._tools = None
        self._next_id = 0

    # ── transport ────────────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            # Streamable HTTP: the server picks the framing, so accept both.
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        return headers

    @staticmethod
    def _parse(body: str) -> dict:
        """Pull the JSON-RPC payload out of a plain or SSE-framed response."""
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except ValueError:
                    continue
        try:
            return json.loads(body)
        except ValueError as e:
            raise MCPError(f"unparseable response from {self.url}") from e

    def _request(self, method: str, params: dict = None) -> dict:
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            r = httpx.post(self.url, headers=self._headers, json=payload,
                           timeout=self.timeout)
        except httpx.HTTPError as e:
            raise MCPError(f"could not reach {self.url}: {e}") from e
        if r.status_code >= 400:
            raise MCPError(f"{r.status_code} from {self.url}: {r.text[:300]}")
        if not self.session_id:
            self.session_id = r.headers.get("mcp-session-id")

        message = self._parse(r.text)
        if message.get("error"):
            raise MCPError(str(message["error"])[:300])
        return message.get("result") or {}

    def _notify(self, method: str) -> None:
        try:
            httpx.post(self.url, headers=self._headers,
                       json={"jsonrpc": "2.0", "method": method},
                       timeout=self.timeout)
        except httpx.HTTPError:
            pass  # a dropped notification is not worth failing the session for

    # ── protocol ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": self.client_name,
                           "version": self.client_version},
        })
        self._notify("notifications/initialized")

    def list_tools(self) -> list:
        if self._tools is None:
            if not self.session_id:
                self.connect()
            self._tools = self._request("tools/list").get("tools") or []
        return self._tools

    def schema(self) -> list:
        """The server's tools, as OpenAI function definitions."""
        out = []
        for tool in self.list_tools():
            out.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": (tool.get("description") or "")[:1024],
                    "parameters": tool.get("inputSchema")
                    or {"type": "object", "properties": {}},
                },
            })
        return out

    def cached_schema(self, cache_path, max_age: int = 24 * 3600) -> list:
        """Tool definitions, from disk when they are recent enough.

        Startup should not pay a network round-trip for a list that changes
        when apps are added. A stale cache is refreshed on the next start; a
        wrong one costs at most one rejected tool call, which the model
        recovers from.
        """
        cache = Path(cache_path)
        try:
            if time.time() - cache.stat().st_mtime < max_age:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                if cached:
                    self._tools = cached
                    return self.schema()
        except (OSError, ValueError):
            pass

        schema = self.schema()          # network path; populates self._tools
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(self._tools), encoding="utf-8")
        except OSError:
            pass
        return schema

    def call(self, name: str, arguments: dict) -> str:
        """Run a tool and flatten its result to text for the model."""
        if not self.session_id:
            self.connect()
        try:
            result = self._request("tools/call",
                                   {"name": name, "arguments": arguments})
        except MCPError as e:
            return f"Error: {name} failed: {e}"

        parts = []
        for item in result.get("content") or []:
            if item.get("type") == "text":
                parts.append(item.get("text") or "")
            else:
                # Images and resources cannot go inline in a tool result, so
                # say what came back rather than dropping it silently.
                parts.append(f"[{item.get('type')} returned by {name}]")
        text = "\n".join(p for p in parts if p) or json.dumps(result)[:2000]
        if result.get("isError"):
            return f"Error from {name}: {text}"
        return text
