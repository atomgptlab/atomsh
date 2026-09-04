"""Conversation persistence, so `atomsh --continue` can pick up a thread."""

import json
import time
import uuid

from .config import SESSION_DIR


class Session:
    """A conversation stored as one JSON file under the session directory."""

    def __init__(self, session_id: str = None, messages: list = None,
                 cwd: str = None):
        self.id = session_id or uuid.uuid4().hex[:12]
        self.messages = messages or []
        self.cwd = cwd
        self.created = time.time()

    @property
    def path(self):
        return SESSION_DIR / f"{self.id}.json"

    def save(self) -> None:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": self.id,
            "cwd": self.cwd,
            "created": self.created,
            "updated": time.time(),
            "messages": self.messages,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.path)

    @classmethod
    def load(cls, session_id: str):
        path = SESSION_DIR / f"{session_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        s = cls(data["id"], data.get("messages", []), data.get("cwd"))
        s.created = data.get("created", time.time())
        return s

    @classmethod
    def latest(cls, cwd: str = None):
        """Most recently updated session, optionally restricted to one cwd."""
        try:
            files = sorted(SESSION_DIR.glob("*.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return None
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if cwd and data.get("cwd") != cwd:
                continue
            s = cls(data["id"], data.get("messages", []), data.get("cwd"))
            s.created = data.get("created", time.time())
            return s
        return None
