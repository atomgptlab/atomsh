"""Escape-to-interrupt while the model is streaming.

Nothing reads the keyboard during a streaming response, so the only way out
is Ctrl-C, which is a blunter signal than people expect from a chat prompt.
This puts the terminal in cbreak for the duration of a response and watches
for ESC on a background thread.
"""

import contextlib
import sys
import threading

try:
    import termios
    import tty
except ImportError:  # not a POSIX terminal
    termios = tty = None

ESC = "\x1b"


@contextlib.contextmanager
def escape_watch():
    """Yield an Event that is set if the user presses Escape.

    A no-op where stdin is not a terminal, so piped and one-shot invocations
    behave exactly as before.
    """
    cancelled = threading.Event()
    if termios is None or not sys.stdin.isatty():
        yield cancelled
        return

    fd = sys.stdin.fileno()
    try:
        saved = termios.tcgetattr(fd)
    except termios.error:
        yield cancelled
        return

    stop = threading.Event()

    def watch():
        while not stop.is_set():
            try:
                import select

                if not select.select([sys.stdin], [], [], 0.05)[0]:
                    continue
                if sys.stdin.read(1) == ESC:
                    cancelled.set()
                    return
            except (OSError, ValueError):
                return

    try:
        tty.setcbreak(fd)
        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        yield cancelled
    finally:
        stop.set()
        with contextlib.suppress(termios.error):
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
