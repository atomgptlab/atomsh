"""Command-line entry point for atomsh."""

import argparse
import select
import subprocess
import sys
from pathlib import Path

from . import __version__, auth
from .agent import Agent
from .client import AtomGPT, AtomGPTError
from .mcp import MCPClient, MCPError
from .config import (API_BASE, DEFAULT_MODEL, MCP_CACHE_TTL,
                     MCP_TOOLS_CACHE, MCP_URL, workspace_root)
from .permissions import Permissions
from .session import Session

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

BANNER = f"""{BOLD}atomsh{RESET} {DIM}v{__version__}, your autonomous coding agent for science{RESET}"""

REPL_HELP = """  !<command>    run a shell command yourself, without the model
  /history      replay this conversation in full
  /model <id>   switch model          /models   list models
  /clear        start a fresh thread   /help     this message
  /exit         quit (or Ctrl-D)
"""


def _require_token() -> str:
    token = auth.load_token()
    if not token:
        print(f"Not signed in. Run {BOLD}atomsh login{RESET} to connect "
              "your atomgpt.org account.")
        raise SystemExit(1)
    return token


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_login(args) -> int:
    if args.key:
        try:
            token = input("Paste your atomgpt.org API key (sk-…): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if not token.startswith("sk-"):
            print("That does not look like an API key (expected sk-…).")
            return 1
    else:
        try:
            token = auth.login_oauth(open_browser=not args.no_browser)
        except auth.AuthError as e:
            print(f"Login failed: {e}")
            print(f"On a headless machine, use {BOLD}atomsh login --key{RESET}.")
            return 1

    try:
        info = auth.whoami(token)
    except auth.AuthError as e:
        print(f"Could not verify the credential: {e}")
        return 1

    auth.save_token(token)
    print(f"Signed in to {API_BASE}. {len(info['models'])} models available.")
    return 0


def cmd_logout(_args) -> int:
    print("Signed out." if auth.forget_token() else "Was not signed in.")
    return 0


def cmd_whoami(_args) -> int:
    token = _require_token()
    try:
        info = auth.whoami(token)
    except auth.AuthError as e:
        print(f"Credential is not usable: {e}")
        return 1
    print(f"Signed in to {API_BASE} ({len(info['models'])} models).")
    return 0


def cmd_models(args) -> int:
    client = AtomGPT(_require_token())
    current = getattr(args, "model", None) or DEFAULT_MODEL
    try:
        for model in client.models():
            marker = "  * " if model == current else "    "
            print(f"{marker}{model}")
    except Exception as e:
        print(f"Could not list models: {e}")
        return 1
    return 0


# ── agent surfaces ───────────────────────────────────────────────────────────

def _build_agent(args, root: Path) -> Agent:
    token = _require_token()
    client = AtomGPT(token)

    remote = None
    if args.materials:
        remote = MCPClient(token, MCP_URL, client_version=__version__)
        try:
            remote.cached_schema(MCP_TOOLS_CACHE, MCP_CACHE_TTL)
        except MCPError as e:
            print(f"{DIM}materials tools unavailable ({e}), continuing "
                  f"without them{RESET}")
            remote = None

    session = None
    if args.continue_:
        session = Session.latest(str(root))
    if session is None:
        session = Session(cwd=str(root))
    mode = "auto" if args.yolo else ("readonly" if args.readonly else "ask")
    return Agent(
        client, args.model, session,
        permissions=Permissions(mode, root), root=root,
        color=not args.no_color, remote=remote,
    )


def run_once(args, root: Path) -> int:
    agent = _build_agent(args, root)
    agent.run(args.prompt)
    return 0


def run_repl(args, root: Path) -> int:
    try:
        import readline

        # Without this, every line of a pasted block is submitted as its own
        # prompt, so a 40-line paste becomes 40 model calls. Requires GNU
        # readline 8.1+; harmless where it is not supported, which is what
        # _read_input's coalescing covers.
        readline.parse_and_bind("set enable-bracketed-paste on")
    except (ImportError, OSError):
        pass

    agent = _build_agent(args, root)
    print(BANNER)
    surface = "materials + code" if agent.remote else "code"
    print(f"{DIM}{args.model} · {root} · {surface} · /help for commands{RESET}\n")
    if args.continue_ and len(agent.session.messages) > 1:
        _render_history(agent)

    while True:
        try:
            line = _read_input(f"{BOLD}›{RESET} ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/help":
            print(REPL_HELP)
            continue
        if line == "/clear":
            agent.session = Session(cwd=str(root))
            agent = _build_agent(args, root)
            print(f"{DIM}new thread{RESET}")
            continue
        # Split on the command word: matching "/model" as a prefix would make
        # a mistyped "/models <id>" silently switch the model.
        parts = line.split(maxsplit=1)
        verb, rest = parts[0], (parts[1].strip() if len(parts) == 2 else "")
        if verb == "/history":
            _render_history(agent, turns=None, width=None)
            continue
        if verb == "/models":
            cmd_models(args)
            continue
        if verb == "/model":
            if rest:
                agent.model = args.model = rest
                print(f"{DIM}model → {agent.model}{RESET}")
            else:
                print(f"{DIM}model is {agent.model}{RESET}")
            continue
        if line.startswith("!"):
            _shell_escape(agent, line[1:].strip(), root)
            continue
        if line.startswith("/"):
            print(f"{DIM}unknown command, see /help for the list{RESET}")
            continue

        try:
            agent.run(line)
        except SystemExit:
            print(f"{DIM}not signed in. Run `atomsh login` in another "
                  f"shell, then retry{RESET}")
        except KeyboardInterrupt:
            print(f"\n{DIM}interrupted{RESET}")
        except AtomGPTError as e:
            print(f"{DIM}error:{RESET} {e}")
        print()


def _shell_escape(agent, command: str, root) -> None:
    """Run a command the user typed directly.

    No approval prompt, since they typed it, and no model round-trip. The result
    is recorded in the conversation so the agent knows what just happened.
    """
    if not command:
        return
    try:
        proc = subprocess.run(command, shell=True, cwd=str(root), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"{DIM}could not run command: {e}{RESET}")
        return
    output = (proc.stdout or "").rstrip()
    if output:
        print(output)
    if proc.returncode != 0:
        print(f"{DIM}[exit {proc.returncode}]{RESET}")
    agent.session.messages.append({
        "role": "user",
        "content": f"I ran this command myself:\n$ {command}\n{output[:4000]}",
    })
    agent.session.save()


def _read_input(prompt: str) -> str:
    """Read one prompt, treating a pasted block as a single input.

    Bracketed paste handles this in the terminal when readline supports it.
    Where it does not, the give-away is timing: the rest of a paste is already
    sitting in the buffer the instant the first line is read, which no human
    typist can reproduce.
    """
    first = input(prompt)
    lines = [first]
    try:
        while select.select([sys.stdin], [], [], 0.01)[0]:
            more = sys.stdin.readline()
            if not more:
                break
            lines.append(more.rstrip("\n"))
    except (OSError, ValueError):
        pass
    if len(lines) > 1:
        print(f"{DIM}  ({len(lines)} lines pasted, sending as one "
              f"prompt){RESET}")
    return "\n".join(lines).strip()


def _render_history(agent, turns: int = 5, width: int = 500) -> None:
    """Replay a resumed conversation so the prompt is not a blank slate.

    Assistant answers are clipped: the point is to remind you where you were,
    not to reprint a thousand-line LAMMPS script. The full text is still in
    the model's context either way.
    """
    messages = [m for m in agent.session.messages if m.get("role") != "system"]
    if not messages:
        return

    starts = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    clipped = turns is not None and len(starts) > turns
    if clipped:
        messages = messages[starts[-turns]:]

    exchanges = len(starts)
    note = f" (last {turns} of {exchanges})" if clipped else ""
    print(f"{DIM}── resumed {agent.session.id} · {exchanges} exchanges"
          f"{note} ──{RESET}\n")

    for message in messages:
        role, content = message.get("role"), message.get("content") or ""
        if role == "user":
            text = content if len(content) <= width else content[:width] + "…"
            print(f"{BOLD}›{RESET} {text}")
        elif role == "assistant":
            for call in message.get("tool_calls") or []:
                name = (call.get("function") or {}).get("name", "?")
                print(f"{DIM}  · {name}(…){RESET}")
            if content:
                if width is not None and len(content) > width:
                    content = content[:width] + f"{DIM}… [clipped]{RESET}"
                print(content)
                print()
    print(f"{DIM}{'─' * 40}{RESET}\n")


# ── argument parsing ─────────────────────────────────────────────────────────

COMMANDS = {
    "login": cmd_login,
    "logout": cmd_logout,
    "whoami": cmd_whoami,
    "models": cmd_models,
}

EPILOG = """commands:
  login                 connect your atomgpt.org account
  logout                forget the stored credential
  whoami                check the stored credential
  models                list available models

examples:
  atomsh                          start an interactive session
  atomsh "fix the failing test"   run one prompt and exit
  git diff | atomsh "review this"
"""


def build_parser() -> argparse.ArgumentParser:
    """Parser for an agent invocation.

    Subcommands are dispatched in main() before this runs, because argparse
    subparsers and a free-text positional cannot coexist, since the first
    word of a prompt would be read as a command name.
    """
    p = argparse.ArgumentParser(
        prog="atomsh",
        description="Atomsh, your autonomous coding agent for science. Powered by AtomGPT (atomgpt.org).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("prompt", nargs="*",
                   help="Prompt to run. Omit for an interactive session.")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL,
                   help=f"Model to use (default: {DEFAULT_MODEL}).")
    p.add_argument("-c", "--continue", "--resume", dest="continue_",
                   action="store_true",
                   help="Resume the most recent session for this directory.")
    p.add_argument("--yolo", action="store_true",
                   help="Do not ask before writing files or running commands.")
    p.add_argument("--readonly", action="store_true",
                   help="Refuse all writes and shell commands.")
    p.add_argument("--materials", dest="materials", action="store_true",
                   default=True, help=argparse.SUPPRESS)
    p.add_argument("--no-materials", dest="materials", action="store_false",
                   help="Leave out the AtomGPT materials tools (JARVIS, "
                        "ALIGNN, band structures, XRD, folding), which are "
                        "loaded by default.")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI color.")
    p.add_argument("-V", "--version", action="version",
                   version=f"atomsh {__version__}")
    return p


def build_command_parser(name: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=f"atomsh {name}")
    if name == "login":
        p.add_argument("--key", action="store_true",
                       help="Paste an API key instead of using the browser.")
        p.add_argument("--no-browser", action="store_true",
                       help="Print the URL instead of opening a browser.")
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] in COMMANDS:
        name = argv[0]
        args = build_command_parser(name).parse_args(argv[1:])
        return COMMANDS[name](args)

    args = build_parser().parse_args(argv)
    args.prompt = " ".join(args.prompt).strip()

    root = workspace_root()
    if args.prompt:
        return run_once(args, root)
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            args.prompt = piped
            return run_once(args, root)
    return run_repl(args, root)


if __name__ == "__main__":
    raise SystemExit(main())
