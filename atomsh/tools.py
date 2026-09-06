"""The coding tools atomsh exposes to the model.

Each tool returns a string, which is what goes back to the model as the tool
result. Errors are returned as text rather than raised, so a bad path or a
failed command becomes something the model can read and correct.
"""

import base64
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .config import DATA_DIR

MAX_OUTPUT = 30000
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".next", "target", ".ruff_cache",
}


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit} more characters]"


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    """Shorten command output from the middle, keeping both ends.

    A build that fails says so on its last line, so cutting the tail is the
    one thing a command result must never do. Half the budget goes to the
    start (what was run, how it was configured) and half to the end (the
    error), with the middle elided.
    """
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    dropped = len(text) - limit
    return (text[:head]
            + f"\n… [{dropped} characters elided from the middle] …\n"
            + text[-tail:])


def _tail_file(path: Path, lines: int, window: int = 256 * 1024):
    """Last `lines` lines of a file, and its total size.

    Reads only the final `window` bytes. A background build can write a log
    far larger than memory, so the whole file is never loaded to show its
    tail.
    """
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            start = max(0, size - window)
            fh.seek(start)
            data = fh.read()
    except OSError as e:
        return f"(could not read {path}: {e})", 0
    text = data.decode("utf-8", "replace")
    if start:
        # The window almost certainly began mid-line; drop that fragment.
        text = text.split("\n", 1)[-1]
    parts = text.splitlines()
    return "\n".join(parts[-lines:]), size


# Background commands. A build or a batch job outlives any sane tool timeout,
# so `bash(background=True)` detaches it, and check_command reports on it.
RUN_DIR = DATA_DIR / "runs"
_JOBS = {}


def _shell(command: str):
    """Argv that runs `command` in a login shell when one is available.

    Non-interactive shells do not source the user's profile, which on an HPC
    system is where `module` (and therefore every compiler and every scheduler
    command) comes from. Falling back to sh keeps this working anywhere.
    """
    if shutil.which("bash"):
        return ["bash", "-lc", command]
    return ["sh", "-c", command]


def _job_meta(job_id: str):
    """Metadata for a job started earlier, possibly in an older session."""
    if job_id in _JOBS:
        return _JOBS[job_id]
    path = RUN_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _alive(meta) -> bool:
    proc = meta.get("proc")
    if proc is not None:
        return proc.poll() is None
    try:
        os.kill(meta["pid"], 0)
        return True
    except (OSError, KeyError):
        return False


def _exit_code(meta):
    """The command's exit status, from the Popen or from its status file.

    A job outlives the session that started it, so the status is also written
    to disk: after a restart there is no Popen left to ask.
    """
    proc = meta.get("proc")
    if proc is not None and proc.returncode is not None:
        return proc.returncode
    try:
        return int(Path(meta["rc"]).read_text().strip())
    except (OSError, ValueError, KeyError):
        return None


# Extensions we can hand to a vision model. Anything else binary is refused
# rather than decoded into replacement characters.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
IMAGE_MEDIA = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif",
               ".webp": "webp", ".bmp": "bmp"}

# Roughly what a served image costs once tiled; used only to keep the context
# estimate honest, since an image is not free the way its file size suggests.
IMAGE_TOKEN_COST = 1600

# Images cannot travel in a tool result - the format requires a string - so a
# viewed image is parked here and the agent turns it into a user message.
PENDING_IMAGES = []

MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _looks_binary(path: Path) -> bool:
    """Whether a file is binary, judged the way file(1) does: a NUL byte.

    Decoding a PDF or a checkpoint as text does not fail, it succeeds and
    returns thousands of replacement characters, which reads to a model as
    content rather than as an error and can exhaust the context window.
    """
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return False
    if b"\x00" in chunk:
        return True
    if not chunk:
        return False
    # A high proportion of undecodable bytes means the same thing.
    printable = sum(1 for b in chunk if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(chunk) < 0.7


def _resolve(path: str, root: Path) -> Path:
    p = Path(path).expanduser()
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def is_outside(path: str, root: Path) -> bool:
    """Whether a path escapes the workspace root."""
    try:
        _resolve(path, root).relative_to(root)
        return False
    except ValueError:
        return True


# ── tools ────────────────────────────────────────────────────────────────────

def read_file(root: Path, path: str, offset: int = 1, limit: int = 2000) -> str:
    """Return file contents with 1-indexed line numbers."""
    target = _resolve(path, root)
    if target.is_file() and _looks_binary(target):
        if target.suffix.lower() in IMAGE_SUFFIXES:
            return f"Error: {path} is an image. Use view_image to see it."
        return (f"Error: {path} looks like a binary file, not text. "
                f"Reading it returns replacement characters, not content.")
    try:
        with open(target, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except IsADirectoryError:
        return f"Error: {path} is a directory. Use list_dir."
    except FileNotFoundError:
        return f"Error: {path} does not exist."
    except OSError as e:
        return f"Error reading {path}: {e}"
    if not lines:
        return f"({path} is empty)"
    start = max(1, offset)
    chunk = lines[start - 1:start - 1 + limit]
    if not chunk:
        return f"Error: offset {offset} is past the end ({len(lines)} lines)."
    body = "".join(
        f"{start + i:6d}\t{line}" for i, line in enumerate(chunk)
    )
    if start - 1 + len(chunk) < len(lines):
        body += f"\n… [{len(lines) - (start - 1 + len(chunk))} more lines]"
    return _truncate(body)


def write_file(root: Path, path: str, content: str) -> str:
    """Create or overwrite a file."""
    target = _resolve(path, root)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"Error writing {path}: {e}"
    verb = "Updated" if existed else "Created"
    return f"{verb} {path} ({len(content.splitlines())} lines)."


def edit_file(root: Path, path: str, old_string: str, new_string: str,
              replace_all: bool = False) -> str:
    """Replace exact text in a file. The match must be unique unless
    replace_all is set. An ambiguous edit is a bug, not a choice."""
    target = _resolve(path, root)
    try:
        original = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: {path} does not exist."
    except OSError as e:
        return f"Error reading {path}: {e}"

    count = original.count(old_string)
    if count == 0:
        return (f"Error: old_string not found in {path}. "
                "Read the file and copy the exact text, including indentation.")
    if count > 1 and not replace_all:
        return (f"Error: old_string appears {count} times in {path}. "
                "Include more surrounding context, or set replace_all=true.")

    updated = (original.replace(old_string, new_string) if replace_all
               else original.replace(old_string, new_string, 1))
    try:
        target.write_text(updated, encoding="utf-8")
    except OSError as e:
        return f"Error writing {path}: {e}"
    return f"Edited {path} ({count if replace_all else 1} replacement(s))."


def list_dir(root: Path, path: str = ".") -> str:
    """List a directory, marking subdirectories with a trailing slash."""
    target = _resolve(path, root)
    if not target.exists():
        return f"Error: {path} does not exist."
    if not target.is_dir():
        return f"Error: {path} is not a directory."
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
        if item.name in SKIP_DIRS:
            continue
        entries.append(f"{item.name}/" if item.is_dir() else item.name)
    return "\n".join(entries) or "(empty directory)"


def glob_files(root: Path, pattern: str, path: str = ".") -> str:
    """Find files matching a glob, most recently modified first."""
    base = _resolve(path, root)
    hits = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = Path(dirpath) / name
            rel = os.path.relpath(full, base)
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                hits.append(full)
    if not hits:
        return f"No files match {pattern!r} under {path}."
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    listing = "\n".join(str(os.path.relpath(p, root)) for p in hits[:200])
    if len(hits) > 200:
        listing += f"\n… [{len(hits) - 200} more matches]"
    return listing


def grep_files(root: Path, pattern: str, path: str = ".",
               glob: str = "*", max_results: int = 200) -> str:
    """Search file contents for a regex, returning path:line:text."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"Error: bad regex {pattern!r}: {e}"
    base = _resolve(path, root)
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not fnmatch.fnmatch(name, glob):
                continue
            full = Path(dirpath) / name
            try:
                with open(full, encoding="utf-8", errors="ignore") as fh:
                    for n, line in enumerate(fh, 1):
                        if rx.search(line):
                            rel = os.path.relpath(full, root)
                            out.append(f"{rel}:{n}:{line.rstrip()}")
                            if len(out) >= max_results:
                                out.append("… [result limit reached]")
                                return _truncate("\n".join(out))
            except OSError:
                continue
    return _truncate("\n".join(out)) or f"No matches for {pattern!r}."


def bash(root: Path, command: str, timeout: int = 120,
         background: bool = False) -> str:
    """Run a shell command in the workspace and return combined output."""
    if background:
        return _start_background(root, command)
    try:
        proc = subprocess.run(
            _shell(command), cwd=str(root), timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except subprocess.TimeoutExpired as e:
        partial = e.output or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        note = (f"Error: command timed out after {timeout}s. Long work "
                f"belongs in the background: rerun with background=True "
                f"and poll it with check_command.")
        partial = partial.strip()
        if partial:
            note += f"\nOutput before the timeout:\n{_clip(partial)}"
        return note
    except OSError as e:
        return f"Error running command: {e}"
    # The exit code is appended after clipping: it is the one line that must
    # survive, and on a long failing build it sits at the very end.
    output = _clip((proc.stdout or "").strip() or "(no output)")
    if proc.returncode != 0:
        output += f"\n[exit code {proc.returncode}]"
    return output


def _start_background(root: Path, command: str) -> str:
    """Launch a command detached and return its job id."""
    job_id = uuid.uuid4().hex[:8]
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        log = RUN_DIR / f"{job_id}.log"
        rc = RUN_DIR / f"{job_id}.rc"
        # Record the status on the way out so it is still readable in a later
        # session, when this Popen no longer exists.
        # A trap, not a trailing line: a command may well end in `exit`,
        # which would jump straight past anything appended after it.
        wrapped = (f"__rcfile={shlex.quote(str(rc))}\n"
                   f"trap 'printf %s \"$?\" > \"$__rcfile\"' EXIT\n"
                   f"{command}\n")
        with open(log, "wb") as fh:
            proc = subprocess.Popen(
                _shell(wrapped), cwd=str(root), stdout=fh,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
    except OSError as e:
        return f"Error starting background command: {e}"
    meta = {"id": job_id, "pid": proc.pid, "command": command,
            "log": str(log), "rc": str(rc), "started": time.time()}
    try:
        (RUN_DIR / f"{job_id}.json").write_text(json.dumps(meta))
    except OSError:
        pass
    _JOBS[job_id] = dict(meta, proc=proc)
    return (f"Started background job {job_id} (pid {proc.pid}).\n"
            f"Output is being written to {log}\n"
            f'Poll it with check_command(job_id="{job_id}", wait=300).')


def check_command(root: Path, job_id: str = None, wait: int = 0,
                  lines: int = 80) -> str:
    """Report on a background command, optionally waiting for it to finish."""
    if not job_id:
        known = sorted(_JOBS) or [p.stem for p in RUN_DIR.glob("*.json")]
        if not known:
            return "No background commands have been started."
        return "Background jobs: " + ", ".join(known)

    meta = _job_meta(job_id)
    if meta is None:
        return f"Error: no background job {job_id!r}."

    deadline = time.time() + max(0, min(wait, 3600))
    while _alive(meta) and time.time() < deadline:
        time.sleep(2)

    elapsed = int(time.time() - meta.get("started", time.time()))
    output, size = _tail_file(Path(meta["log"]), max(1, lines))

    if _alive(meta):
        status = f"job {job_id}: still running after {elapsed}s"
    else:
        code = _exit_code(meta)
        code = "unknown, killed?" if code is None else code
        status = f"job {job_id}: finished after {elapsed}s [exit code {code}]"

    body = _clip(output.strip()) or "(no output yet)"
    return (f"{status}\n--- last {lines} lines of {meta['log']} "
            f"({size} bytes total) ---\n{body}")


def view_image(root: Path, path: str) -> str:
    """Show an image to the model.

    The image cannot be returned from here: a tool result has to be a string.
    It is parked in PENDING_IMAGES and the agent sends it as a user message
    straight after this call, so the model sees the picture in the
    conversation rather than a description of it.
    """
    target = _resolve(path, root)
    if not target.is_file():
        return f"Error: {path} does not exist."
    suffix = target.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        return (f"Error: {path} is not an image "
                f"({', '.join(sorted(IMAGE_SUFFIXES))}).")
    size = target.stat().st_size
    if size > MAX_IMAGE_BYTES:
        return (f"Error: {path} is {size} bytes, over the "
                f"{MAX_IMAGE_BYTES} limit for an image.")
    try:
        blob = base64.b64encode(target.read_bytes()).decode()
    except OSError as e:
        return f"Error reading {path}: {e}"
    media = IMAGE_MEDIA.get(suffix, "png")
    PENDING_IMAGES.append({
        "path": str(target),
        "url": f"data:image/{media};base64,{blob}",
    })
    return (f"Loaded {path} ({size} bytes). It follows in the next message; "
            f"describe what you need from it there.")


HANDLERS = {
    "read_file": read_file,
    "view_image": view_image,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_dir": list_dir,
    "glob_files": glob_files,
    "grep_files": grep_files,
    "bash": bash,
    "check_command": check_command,
}

# Tools that change something on disk or run arbitrary code. The permission
# layer gates these; everything else is read-only and runs unattended.
MUTATING = {"write_file", "edit_file", "bash"}


def _fn(name: str, description: str, properties: dict, required: list) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


SCHEMA = [
    _fn("read_file",
        "Read a file from the workspace. Returns contents with line numbers. "
        "Always read a file before editing it.",
        {"path": {"type": "string", "description": "File path, relative to the workspace."},
         "offset": {"type": "integer", "description": "First line to read (1-indexed)."},
         "limit": {"type": "integer", "description": "Maximum number of lines."}},
        ["path"]),
    _fn("write_file",
        "Create a new file or overwrite an existing one. For changing part of "
        "an existing file, prefer edit_file.",
        {"path": {"type": "string"},
         "content": {"type": "string", "description": "Full file contents."}},
        ["path", "content"]),
    _fn("edit_file",
        "Replace exact text in a file. old_string must match the file exactly, "
        "including indentation, and must be unique unless replace_all is true.",
        {"path": {"type": "string"},
         "old_string": {"type": "string", "description": "Text to replace."},
         "new_string": {"type": "string", "description": "Replacement text."},
         "replace_all": {"type": "boolean", "description": "Replace every occurrence."}},
        ["path", "old_string", "new_string"]),
    _fn("list_dir",
        "List the entries of a directory.",
        {"path": {"type": "string", "description": "Directory path. Defaults to the workspace root."}},
        []),
    _fn("glob_files",
        "Find files by glob pattern (e.g. '*.py', 'src/**/*.ts'), newest first.",
        {"pattern": {"type": "string"},
         "path": {"type": "string", "description": "Directory to search under."}},
        ["pattern"]),
    _fn("grep_files",
        "Search file contents with a regular expression. Returns path:line:text.",
        {"pattern": {"type": "string", "description": "Python regular expression."},
         "path": {"type": "string", "description": "Directory to search under."},
         "glob": {"type": "string", "description": "Only search files matching this glob."}},
        ["pattern"]),
    _fn("bash",
        "Run a shell command in the workspace, in a login shell so `module` "
        "and scheduler commands work. Use for builds, tests and git; prefer "
        "grep_files and glob_files for searching. Anything that may outlast "
        "the timeout (a build, a test suite, a batch job) should be started "
        "with background=True instead of a longer timeout.",
        {"command": {"type": "string"},
         "timeout": {"type": "integer", "description": "Seconds before the command is killed."},
         "background": {"type": "boolean",
                        "description": "Detach and return a job id now."}},
        ["command"]),
    _fn("view_image",
        "Look at an image file (png, jpg, gif, webp, bmp). The image is sent "
        "to you in the message after the tool result, so read it there. "
        "read_file cannot show an image.",
        {"path": {"type": "string"}},
        ["path"]),
    _fn("check_command",
        "Report on a command started with background=True: its status and "
        "the tail of its output. With `wait`, block until it finishes or the "
        "wait runs out, which is cheaper than polling. Omit job_id to list "
        "known jobs.",
        {"job_id": {"type": "string"},
         "wait": {"type": "integer",
                  "description": "Seconds to block waiting for it to finish."},
         "lines": {"type": "integer",
                   "description": "Trailing lines of output to show."}},
        []),
]
