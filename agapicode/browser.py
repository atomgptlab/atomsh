"""Opening a URL in the user's browser, including from WSL.

Python's webbrowser module shells out to xdg-open, which on a headless Linux
box (WSL included) prints a dozen "not found" lines to stderr before giving
up. That noise is worse than useless during login, so this module picks an
opener deliberately and keeps every child process quiet.
"""

import os
import shutil
import subprocess
import webbrowser


def is_wsl() -> bool:
    """Whether we are running under WSL, where the browser lives on Windows."""
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def _run(cmd: list) -> bool:
    """Launch a command with its output discarded. True if it started."""
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=20, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _candidates(url: str) -> list:
    cmds = []
    if is_wsl():
        # Hand the URL to Windows. explorer.exe exits non-zero even when it
        # works, so "did not raise" is the success test, not the exit code.
        cmds += [
            ["wslview", url],
            ["explorer.exe", url],
            ["powershell.exe", "-NoProfile", "-Command", "Start-Process", url],
        ]
    cmds += [["xdg-open", url], ["open", url]]
    return cmds


def _webbrowser_quiet(url: str) -> bool:
    """Last resort: webbrowser.open with the child's stderr muted."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return webbrowser.open(url)
    saved = os.dup(2)
    try:
        os.dup2(devnull, 2)
        return webbrowser.open(url)
    except Exception:
        return False
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


def open_url(url: str) -> bool:
    """Open `url` in a browser. False means the user has to do it themselves."""
    for cmd in _candidates(url):
        if shutil.which(cmd[0]) and _run(cmd):
            return True
    return _webbrowser_quiet(url)
