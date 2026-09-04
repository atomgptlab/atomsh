"""Cleanup for raw model output.

The chat models served by atomgpt.org sometimes emit channel control markers
(`<|channel>thought`, `<channel|>`, `<|end|>` …) in their visible text. They
are not filtered on the way out, so a client has to strip them itself.
"""

import re

# An opening channel marker is followed by the channel's name, which is
# metadata rather than text, so the name goes with it.
CHANNEL_OPEN = re.compile(r"<\|channel\|?>\s*\w*")

# Any remaining lone control marker.
MARKER = re.compile(
    r"<\|?/?(?:channel|message|start|end|return|assistant|final|thought)\b[^>]*\|?>"
)

# Longest marker run we might be holding half of at the end of a chunk.
_MAX_MARKER = 64


def clean(text: str) -> str:
    """Strip control markers from a complete string."""
    return MARKER.sub("", CHANNEL_OPEN.sub("", text or ""))


class Scrubber:
    """Strips markers from a token stream without stalling it.

    A marker can straddle two chunks, so everything from the last '<' onward
    is held back until a later chunk resolves it. Held text is never cleaned
    until it is released, which keeps a half-arrived marker from being
    stripped down to its own channel name.
    """

    def __init__(self):
        self.buffer = ""

    def feed(self, chunk: str) -> str:
        """Return the portion of the stream that is safe to display now."""
        self.buffer += chunk
        cut = self.buffer.rfind("<")
        if cut != -1 and len(self.buffer) - cut < _MAX_MARKER:
            safe, self.buffer = self.buffer[:cut], self.buffer[cut:]
        else:
            safe, self.buffer = self.buffer, ""
        return clean(safe)

    def flush(self) -> str:
        """Return whatever is still held back, cleaned."""
        out = clean(self.buffer)
        self.buffer = ""
        return out
