"""Approval gate for tools that touch the filesystem or run commands."""

import json

from .tools import MUTATING, is_outside

ALLOW = "allow"
DENY = "deny"


class Permissions:
    """Decide whether a tool call may run.

    Modes:
      ask       — prompt before anything that writes or executes (default)
      auto      — never prompt
      readonly  — refuse writes and commands outright
    """

    def __init__(self, mode: str = "ask", root=None):
        self.mode = mode
        self.root = root
        self.always = set()

    def check(self, name: str, args: dict):
        """Return (decision, reason)."""
        escapes = self._escapes_workspace(name, args)

        if name not in MUTATING and not escapes:
            return ALLOW, ""
        if self.mode == "readonly":
            return DENY, "atomsh is running in read-only mode."
        if self.mode == "auto":
            return ALLOW, ""
        if name in self.always and not escapes:
            return ALLOW, ""
        return self._prompt(name, args, escapes)

    def _escapes_workspace(self, name: str, args: dict) -> bool:
        path = args.get("path")
        if not path or self.root is None:
            return False
        return is_outside(path, self.root)

    def _prompt(self, name: str, args: dict, escapes: bool):
        print()
        print(f"  atomsh wants to run: {name}")
        for key, value in args.items():
            rendered = value if isinstance(value, str) else json.dumps(value)
            if len(rendered) > 300:
                rendered = rendered[:300] + f"… (+{len(rendered) - 300} chars)"
            indented = rendered.replace("\n", "\n      ")
            print(f"    {key}: {indented}")
        if escapes:
            print("    ! this path is outside the workspace")
        try:
            # Capital N marks the default: a bare Enter denies.
            answer = input("  allow? [y]es / [N]o / [a]lways: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return DENY, "user interrupted the approval prompt."
        if answer.startswith("a") and not escapes:
            self.always.add(name)
            return ALLOW, ""
        if answer.startswith("y"):
            return ALLOW, ""
        return DENY, "user declined this tool call."
