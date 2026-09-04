# Atomsh

**Your autonomous coding agent for science.**

Atomsh reads and edits files, searches the codebase, and runs commands from
your terminal — and it can look a material up while doing it. It runs on
[AtomGPT](https://atomgpt.org) alone: one account, no other provider.

## Install

```sh
curl -fsSL https://atomgpt.org/install | bash
```

The installer uses `uv` when it is present, falls back to a virtualenv, and
bootstraps `uv` if the system Python is unusable. Everything lands in an
isolated environment with a launcher in `~/.local/bin`. No sudo.

## Connect

```sh
atomsh login
```

This opens atomgpt.org in your browser, you approve once, and the credential
is stored `0600` in `~/.config/atomsh/auth.json`. On a headless machine use
`atomsh login --key` and paste an API key instead.

## Use

```sh
atomsh                            # interactive session
atomsh "fix the failing test"     # run one prompt and exit
atomsh -c                         # resume this directory's last session
git diff | atomsh "review this"   # read a prompt from stdin
```

| Flag | Effect |
|------|--------|
| `-m, --model` | Pick a model (default `gemma-4-26b`) |
| `-c, --continue` | Resume the most recent session for this directory |
| `--yolo` | Do not ask before writing files or running commands |
| `--readonly` | Refuse all writes and shell commands |
| `--no-materials` | Leave out the AtomGPT materials tools |

Commands: `login`, `logout`, `whoami`, `models`.

In a session: `!<command>` runs a shell command yourself, `/history` replays
the conversation, `/model` switches model, `/clear` starts a fresh thread.
**Escape** interrupts a response while it is streaming.

## Permissions

By default atomsh asks before anything that writes a file or runs a
command; reads and searches happen unattended. Answering `a` allows that tool
for the rest of the session. A path outside the working directory always
prompts, even after `a`.

## Models

`atomsh models` lists what your account can use. The `mcp.*` models are
excluded on purpose: those run the AtomGPT materials agent server-side and
ignore client-supplied tools, so they cannot drive a coding loop. Use them
through a chat client instead.

## Tools

`read_file`, `write_file`, `edit_file`, `list_dir`, `glob_files`,
`grep_files`, `bash`.

### Materials tools

atomsh connects to the AtomGPT MCP server with the same credential and
carries six more tools by default: `explore`, `build`, `predict`,
`characterize`, `apply`, `validate`. Each dispatches to a family of AtomGPT apps — JARVIS-DFT lookups,
ALIGNN predictions, band structures, XRD, interfaces, protein folding — so the
agent can look a material up instead of answering from the model's memory:

```
$ atomsh --materials "bandgap of silicon JVASP-1002 from JARVIS-DFT"
  · explore(app=/jarvis_dft/query, params={"jid": "JVASP-1002"})
OptB88vdW 0.731 eV · mBJ 1.277 eV · HSE 1.22 eV
```

The tool list is cached under `~/.local/share/atomsh/` and refreshed daily,
and the MCP session is opened on first use, so carrying them costs nothing at
startup. `--no-materials` leaves them out — worth doing for pure coding work,
where a narrower tool surface is easier for the model.

## Development

```sh
uv venv && uv pip install -e .
ATOMSH_API_KEY=sk-… atomsh --readonly "what does this repo do?"
```

`ATOMSH_API_BASE` points the client at a different deployment.

The copy of `install.sh` served at `atomgpt.org/install` lives in the
my-open-webui repo under `backend/open_webui/custom_static/install.sh`; this
file is the canonical source.

## License

Apache-2.0
