"""The agent loop: model → tool calls → tool results → model, until it stops."""

import json
from pathlib import Path

from . import tools as toolkit
from .client import AtomGPT, AtomGPTError
from .config import MAX_STEPS
from .interrupt import escape_watch
from .permissions import ALLOW, Permissions
from .prompt import system_prompt

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class Agent:
    """Drives one conversation against one model with one tool set."""

    def __init__(self, client: AtomGPT, model: str, session,
                 permissions: Permissions = None, root: Path = None,
                 color: bool = True, remote=None):
        self.client = client
        self.model = model
        self.session = session
        self.root = root or Path.cwd()
        self.permissions = permissions or Permissions("ask", self.root)
        self.color = color
        # An MCPClient, when --materials is on. Its tools sit alongside the
        # local ones; the model does not need to know which is which.
        self.remote = remote
        self.remote_tools = set()
        self.tool_schema = list(toolkit.SCHEMA)
        if remote is not None:
            remote_schema = remote.schema()
            self.remote_tools = {t["function"]["name"] for t in remote_schema}
            self.tool_schema += remote_schema
        if not self.session.messages:
            self.session.messages.append({
                "role": "system",
                "content": system_prompt(str(self.root),
                                         materials=remote is not None),
            })

    def _dim(self, text: str) -> str:
        return f"{DIM}{text}{RESET}" if self.color else text

    def run(self, user_text: str) -> str:
        """Run one user turn to completion. Returns the final assistant text."""
        self.session.messages.append({"role": "user", "content": user_text})
        final = ""

        for _ in range(MAX_STEPS):
            # `last` doubles as "have we printed anything this step": stripped
            # channel markers leave stray blank lines, so leading whitespace is
            # swallowed and the closing newline is only added if one is missing.
            state = {"last": ""}

            def on_text(piece, state=state):
                if not state["last"] and not piece.strip():
                    return
                state["last"] = piece
                print(piece, end="", flush=True)

            try:
                with escape_watch() as cancelled:
                    result = self.client.stream(
                        self.session.messages, self.tool_schema, self.model,
                        on_text=on_text, cancelled=cancelled,
                    )
            except AtomGPTError as e:
                print(f"\n{self._dim('error:')} {e}")
                return ""

            message = result["message"]
            if state["last"] and not state["last"].endswith("\n"):
                print()
            self.session.messages.append(message)
            self.session.save()

            if result.get("finish_reason") == "cancelled":
                print(self._dim("  interrupted"))
                return message.get("content") or ""

            calls = message.get("tool_calls")
            if not calls:
                final = message.get("content") or ""
                if not final and not state["last"]:
                    print(self._dim("(no response, try rephrasing)"))
                return final

            for call in calls:
                self._run_tool(call)
            self.session.save()

        print(self._dim(f"stopped after {MAX_STEPS} steps"))
        return final

    def _run_tool(self, call: dict) -> None:
        """Execute one tool call and append its result to the conversation."""
        name = (call.get("function") or {}).get("name") or ""
        raw_args = (call.get("function") or {}).get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except ValueError:
            args = {}

        handler = toolkit.HANDLERS.get(name)
        if handler is None and name not in self.remote_tools:
            return self._reply(call, f"Error: no such tool {name!r}.")

        decision, reason = self.permissions.check(name, args)
        if decision != ALLOW:
            print(self._dim(f"  ✗ {name}: {reason}"))
            return self._reply(call, f"Denied: {reason}")

        print(self._dim(f"  · {name}({self._summarize(args)})"))
        try:
            if handler is None:
                output = self.remote.call(name, args)
            else:
                output = handler(self.root, **args)
        except TypeError as e:
            output = f"Error: bad arguments for {name}: {e}"
        except Exception as e:  # a tool must never kill the session
            output = f"Error: {name} raised {type(e).__name__}: {e}"
        self._reply(call, output)

    def _reply(self, call: dict, content: str) -> None:
        self.session.messages.append({
            "role": "tool",
            "tool_call_id": call.get("id") or "",
            "content": content,
        })

    @staticmethod
    def _summarize(args: dict) -> str:
        """One-line rendering of tool arguments for the activity log."""
        parts = []
        for key, value in args.items():
            text = value if isinstance(value, str) else json.dumps(value)
            text = text.replace("\n", " ")
            if len(text) > 60:
                text = text[:60] + "…"
            parts.append(f"{key}={text}")
        return ", ".join(parts)
