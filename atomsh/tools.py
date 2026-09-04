"""The coding tools atomsh exposes to the model.

Each tool returns a string — that is what goes back to the model as the tool
result. Errors are returned as text rather than raised, so a bad path or a
failed command becomes something the model can read and correct.
"""

import fnmatch
import os
import re
import subprocess
from pathlib import Path

MAX_OUTPUT = 30000
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".next", "target", ".ruff_cache",
}


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit} more characters]"


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
    replace_all is set — an ambiguous edit is a bug, not a choice."""
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


def bash(root: Path, command: str, timeout: int = 120) -> str:
    """Run a shell command in the workspace and return combined output."""
    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(root), timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s."
    except OSError as e:
        return f"Error running command: {e}"
    output = proc.stdout or ""
    if proc.returncode != 0:
        output += f"\n[exit code {proc.returncode}]"
    return _truncate(output.strip() or "(no output)")


HANDLERS = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_dir": list_dir,
    "glob_files": glob_files,
    "grep_files": grep_files,
    "bash": bash,
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
        "Run a shell command in the workspace. Use for builds, tests and git; "
        "prefer grep_files and glob_files for searching.",
        {"command": {"type": "string"},
         "timeout": {"type": "integer", "description": "Seconds before the command is killed."}},
        ["command"]),
]
