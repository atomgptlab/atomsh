"""Streaming chat client for the AtomGPT OpenAI-compatible endpoint."""

import json

import httpx

from .config import API_URL, REQUEST_TIMEOUT, SERVER_SIDE_AGENT_PREFIX
from .text import Scrubber


class AtomGPTError(Exception):
    """The endpoint returned an error, or the stream broke mid-response."""


class AtomGPT:
    """Thin client over POST /api/chat/completions.

    Only the pieces a coding agent needs: streaming text, streaming tool
    calls, and the model list.
    """

    def __init__(self, token: str, base_url: str = API_URL,
                 timeout: int = REQUEST_TIMEOUT):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def models(self, tool_capable_only: bool = True) -> list:
        """List model ids served by the endpoint.

        The mcp.* entries run the AtomGPT materials agent on the server and
        do not make client-side tool calls, so they are filtered out by
        default.
        """
        r = httpx.get(f"{self.base_url}/models", headers=self._headers,
                      timeout=30)
        r.raise_for_status()
        ids = [m.get("id", "") for m in (r.json().get("data") or [])]
        if tool_capable_only:
            ids = [i for i in ids if not i.startswith(SERVER_SIDE_AGENT_PREFIX)]
        return sorted(i for i in ids if i)

    def stream(self, messages: list, tools: list = None, model: str = None,
               on_text=None, cancelled=None) -> dict:
        """Run one completion and return the assembled assistant message.

        `on_text` is called with each text delta as it arrives, so the caller
        can render tokens live. Tool-call deltas are accumulated by index and
        returned whole — a half-parsed argument string is useless to a caller.
        """
        body = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        text_parts = []
        tool_calls = {}
        finish_reason = None
        scrubber = Scrubber()

        try:
            with httpx.stream("POST", f"{self.base_url}/chat/completions",
                              headers=self._headers, json=body,
                              timeout=self.timeout) as r:
                if r.status_code >= 400:
                    r.read()
                    raise AtomGPTError(
                        f"{r.status_code} from {self.base_url}: {r.text[:400]}"
                    )
                for line in r.iter_lines():
                    if cancelled is not None and cancelled.is_set():
                        finish_reason = "cancelled"
                        break
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        raise AtomGPTError(str(chunk["error"])[:400])
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            visible = scrubber.feed(piece)
                            if visible:
                                text_parts.append(visible)
                                if on_text:
                                    on_text(visible)
                        for tc in delta.get("tool_calls") or []:
                            self._merge_tool_call(tool_calls, tc)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except httpx.HTTPError as e:
            raise AtomGPTError(f"request to {self.base_url} failed: {e}") from e

        tail = scrubber.flush()
        if tail:
            text_parts.append(tail)
            if on_text:
                on_text(tail)

        message = {"role": "assistant", "content": "".join(text_parts) or None}
        if finish_reason == "cancelled":
            # Tool calls are dropped: an assistant message carrying calls that
            # never get results makes the next request invalid.
            message["content"] = message["content"] or "(interrupted)"
            return {"message": message, "finish_reason": "cancelled"}
        if tool_calls:
            message["tool_calls"] = [
                tool_calls[i] for i in sorted(tool_calls)
            ]
            # Some backends report "stop" alongside tool calls; the calls are
            # what actually decides whether the loop continues.
            finish_reason = "tool_calls"
        return {"message": message, "finish_reason": finish_reason}

    @staticmethod
    def _merge_tool_call(acc: dict, delta: dict) -> None:
        """Fold one streamed tool_call delta into the accumulator."""
        idx = delta.get("index", 0)
        entry = acc.setdefault(idx, {
            "id": "", "type": "function",
            "function": {"name": "", "arguments": ""},
        })
        if delta.get("id"):
            entry["id"] = delta["id"]
        fn = delta.get("function") or {}
        if fn.get("name"):
            entry["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            entry["function"]["arguments"] += fn["arguments"]
