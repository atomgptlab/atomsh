---
title: Permissions
---

# Permissions

Atomsh runs shell commands and writes files. It asks first.

## What is gated

Reads and searches run unattended: `read_file`, `list_dir`, `glob_files`,
`grep_files`, and the materials tools, which have no local side effects.

Anything that changes your machine asks: `write_file`, `edit_file`, `bash`.

```text
  atomsh wants to run: bash
    command: python3 -m pytest
  allow? [y]es / [N]o / [a]lways:
```

The capital `N` marks the default. Pressing Enter denies.

Answering `a` allows that tool for the rest of the session. It does not carry
over to a new session, and it never applies to a path outside the workspace,
which asks every time.

## Modes

| Mode | Behaviour |
|------|-----------|
| default | Ask before writes and commands |
| `--yolo` | Never ask |
| `--readonly` | Refuse all writes and commands outright |

`--readonly` is the right first setting when you are evaluating whether the
model is useful on your codebase. `--yolo` is for a task you have already
scoped and a repository under version control.

## The workspace boundary

Atomsh treats your git repository root as the workspace. Any path resolving
outside it is flagged in the prompt:

```text
    path: ../../etc/hosts
    ! this path is outside the workspace
```

That warning appears even in `always` mode, because the boundary is the point.

## What Atomsh never does

It does not send your code anywhere except to atomgpt.org, as the conversation
the model is answering. It stores no credentials other than the one in
`~/.config/atomsh/auth.json`, mode `0600`. It does not phone home, and it has
no telemetry.

## Interrupting

Press ++esc++ while a response is streaming to stop it. Ctrl-C also works, and
Ctrl-D exits.
