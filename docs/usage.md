---
title: Using Atomsh
---

# Using Atomsh

## Invocations

```sh
atomsh                             # interactive session
atomsh "fix the failing test"      # run one prompt and exit
atomsh -c                          # resume this directory's last session
git diff | atomsh "review this"    # read a prompt from stdin
```

With a prompt argument Atomsh runs one turn and exits, which makes it usable
in scripts and pipelines. With no argument and a terminal attached it starts
an interactive session.

## Flags

| Flag | Effect |
|------|--------|
| `-m`, `--model` | Model to use. Default `gemma-4-26b` |
| `-c`, `--continue`, `--resume` | Resume the most recent session for this directory |
| `--yolo` | Do not ask before writing files or running commands |
| `--readonly` | Refuse all writes and shell commands |
| `--no-materials` | Leave out the AtomGPT materials tools |
| `--no-color` | Disable ANSI colour |
| `-V`, `--version` | Print the version |

## Commands

```sh
atomsh login      # connect your atomgpt.org account
atomsh logout     # forget the stored credential
atomsh whoami     # check the stored credential
atomsh models     # list available models
```

## In a session

| Input | Effect |
|-------|--------|
| `!<command>` | Run a shell command yourself, with no model round-trip and no approval prompt |
| `/model <id>` | Switch model. Without an argument, print the current one |
| `/models` | List available models, marking the one in use |
| `/history` | Replay the conversation in full |
| `/clear` | Start a fresh thread |
| `/help` | Show the command list |
| `/exit` | Quit, as does Ctrl-D |
| ++esc++ | Interrupt a response while it is streaming |

Pasting multiple lines sends them as a single prompt rather than one prompt per
line.

## The workspace

Atomsh treats the root of your git repository as its workspace, so starting in
a subdirectory still lets it reach the whole project. Outside a repository, the
workspace is the current directory.

A path outside the workspace always asks for approval, even after you have
allowed a tool for the session.

## Sessions

Every conversation is saved under `~/.local/share/atomsh/sessions/`, keyed by
workspace. `atomsh -c` resumes the most recent one for the directory you are in
and replays the last few exchanges so you can see where you left off.

## Models

`atomsh models` lists what your account can reach. The `mcp.*` entries are
excluded on purpose: those run the AtomGPT materials agent on the server and
answer in prose rather than making tool calls, so they cannot drive a coding
loop. Use them from a chat client instead.
