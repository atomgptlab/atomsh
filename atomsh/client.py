"""Streaming chat client for the AtomGPT OpenAI-compatible endpoint."""

import json
import time

import httpx

from .config import API_URL, REQUEST_TIMEOUT, SERVER_SIDE_AGENT_PREFIX
from .text import Scrubber


class AtomGPTError(Exception):
    """The endpoint returned an error, or the stream broke mid-response."""


class _Retryable(AtomGPTError):
    """A failure worth waiting out: rate limiting, or a server hiccup."""

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


# Statuses that mean "not now" rather than "not ever". A rate limit in
# particular is routine when several agents share one account, and losing a
# task to it wastes far more than the wait would have.
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
MAX_SLEEP = 60.0


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
               on_text=None, cancelled=None, notify=None) -> dict:
        """Run one completion, retrying transient failures.

        Retries happen before any text has been emitted - the status is
        checked before the body is streamed - so a retry can never duplicate
        output the caller has already rendered.
        """
        delay = 2.0
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._stream_once(messages, tools, model, on_text,
                                         cancelled)
            except _Retryable as e:
                if attempt == MAX_RETRIES:
                    raise AtomGPTError(f"{e} (gave up after "
                                       f"{MAX_RETRIES} retries)") from e
                wait = min(max(e.retry_after, delay), MAX_SLEEP)
                if notify:
                    notify(f"{e} — retrying in {wait:.0f}s")
                time.sleep(wait)
                delay *= 2
        raise AtomGPTError("unreachable")

    def _stream_once(self, messages: list, tools: list = None,
                     model: str = None, on_text=None, cancelled=None) -> dict:
        """One attempt: assemble the assistant message from the stream.

        `on_text` is called with each text delta as it arrives, so the caller
        can render tokens live. Tool-call deltas are accumulated by index and
        returned whole, because a half-parsed argument string is useless to a caller.
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
                    detail = (f"{r.status_code} from {self.base_url}: "
                              f"{r.text[:400]}")
                    if r.status_code in RETRY_STATUSES:
                        raise _Retryable(detail, _retry_after(r))
                    raise AtomGPTError(detail)
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
        except httpx.TimeoutException as e:
            raise _Retryable(f"request to {self.base_url} timed out: {e}") \
                from e
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


def _retry_after(response) -> float:
    """Seconds the server asked us to wait, if it said."""
    header = response.headers.get("retry-after", "")
    try:
        return max(0.0, float(header))
    except (TypeError, ValueError):
        return 0.0
