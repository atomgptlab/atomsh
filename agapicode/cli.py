"""Command-line entry point for agapicode."""

import argparse
import subprocess
import sys
from pathlib import Path

from . import __version__, auth
from .agent import Agent
from .client import AtomGPT, AtomGPTError
from .config import API_BASE, DEFAULT_MODEL, workspace_root
from .permissions import Permissions
from .session import Session

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

BANNER = f"""{BOLD}agapicode{RESET} {DIM}v{__version__} — powered by AtomGPT{RESET}"""

REPL_HELP = """  !<command>    run a shell command yourself, without the model
  /model <id>   switch model          /models   list models
  /clear        start a fresh thread   /help     this message
  /exit         quit (or Ctrl-D)
"""


def _require_token() -> str:
    token = auth.load_token()
    if not token:
        print(f"Not signed in. Run {BOLD}agapicode login{RESET} to connect "
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
            print(f"On a headless machine, use {BOLD}agapicode login --key{RESET}.")
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


def cmd_models(_args) -> int:
    client = AtomGPT(_require_token())
    try:
        for model in client.models():
            marker = "  * " if model == DEFAULT_MODEL else "    "
            print(f"{marker}{model}")
    except Exception as e:
        print(f"Could not list models: {e}")
        return 1
    return 0


# ── agent surfaces ───────────────────────────────────────────────────────────

def _build_agent(args, root: Path) -> Agent:
    client = AtomGPT(_require_token())
    session = None
    if args.continue_:
        session = Session.latest(str(root))
    if session is None:
        session = Session(cwd=str(root))
    mode = "auto" if args.yolo else ("readonly" if args.readonly else "ask")
    return Agent(
        client, args.model, session,
        permissions=Permissions(mode, root), root=root,
        color=not args.no_color,
    )


def run_once(args, root: Path) -> int:
    agent = _build_agent(args, root)
    agent.run(args.prompt)
    return 0


def run_repl(args, root: Path) -> int:
    try:
        import readline  # noqa: F401 — enables line editing and history
    except ImportError:
        pass

    agent = _build_agent(args, root)
    print(BANNER)
    print(f"{DIM}{args.model} · {root} · /help for commands{RESET}\n")

    while True:
        try:
            line = input(f"{BOLD}›{RESET} ").strip()
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
        if line == "/models":
            cmd_models(args)
            continue
        if line.startswith("/model"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                agent.model = args.model = parts[1].strip()
                print(f"{DIM}model → {agent.model}{RESET}")
            else:
                print(f"{DIM}model is {agent.model}{RESET}")
            continue
        if line.startswith("!"):
            _shell_escape(agent, line[1:].strip(), root)
            continue
        if line.startswith("/"):
            print(f"{DIM}unknown command — /help for the list{RESET}")
            continue

        try:
            agent.run(line)
        except KeyboardInterrupt:
            print(f"\n{DIM}interrupted{RESET}")
        except AtomGPTError as e:
            print(f"{DIM}error:{RESET} {e}")
        print()


def _shell_escape(agent, command: str, root) -> None:
    """Run a command the user typed directly.

    No approval prompt — they typed it — and no model round-trip. The result
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
  agapicode                          start an interactive session
  agapicode "fix the failing test"   run one prompt and exit
  git diff | agapicode "review this"
"""


def build_parser() -> argparse.ArgumentParser:
    """Parser for an agent invocation.

    Subcommands are dispatched in main() before this runs — argparse
    subparsers and a free-text positional cannot coexist, since the first
    word of a prompt would be read as a command name.
    """
    p = argparse.ArgumentParser(
        prog="agapicode",
        description="A coding agent powered by AtomGPT (atomgpt.org).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("prompt", nargs="*",
                   help="Prompt to run. Omit for an interactive session.")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL,
                   help=f"Model to use (default: {DEFAULT_MODEL}).")
    p.add_argument("-c", "--continue", dest="continue_", action="store_true",
                   help="Resume the most recent session for this directory.")
    p.add_argument("--yolo", action="store_true",
                   help="Do not ask before writing files or running commands.")
    p.add_argument("--readonly", action="store_true",
                   help="Refuse all writes and shell commands.")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI color.")
    p.add_argument("-V", "--version", action="version",
                   version=f"agapicode {__version__}")
    return p


def build_command_parser(name: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=f"agapicode {name}")
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
