# agapicode

A coding agent for your terminal, powered by [AtomGPT](https://atomgpt.org).

It reads and edits files, searches the codebase, and runs commands — using
only models served by atomgpt.org. One account, no other provider.

## Install

```sh
curl -fsSL https://atomgpt.org/install | bash
```

The installer uses `uv` when it is present, falls back to a virtualenv, and
bootstraps `uv` if the system Python is unusable. Everything lands in an
isolated environment with a launcher in `~/.local/bin`. No sudo.

## Connect

```sh
agapicode login
```

This opens atomgpt.org in your browser, you approve once, and the credential
is stored `0600` in `~/.config/agapicode/auth.json`. On a headless machine use
`agapicode login --key` and paste an API key instead.

## Use

```sh
agapicode                            # interactive session
agapicode "fix the failing test"     # run one prompt and exit
agapicode -c                         # resume this directory's last session
git diff | agapicode "review this"   # read a prompt from stdin
```

| Flag | Effect |
|------|--------|
| `-m, --model` | Pick a model (default `gemma-4-26b`) |
| `-c, --continue` | Resume the most recent session for this directory |
| `--yolo` | Do not ask before writing files or running commands |
| `--readonly` | Refuse all writes and shell commands |

Commands: `login`, `logout`, `whoami`, `models`.

## Permissions

By default agapicode asks before anything that writes a file or runs a
command; reads and searches happen unattended. Answering `a` allows that tool
for the rest of the session. A path outside the working directory always
prompts, even after `a`.

## Models

`agapicode models` lists what your account can use. The `mcp.*` models are
excluded on purpose: those run the AtomGPT materials agent server-side and
ignore client-supplied tools, so they cannot drive a coding loop. Use them
through a chat client instead.

## Tools

`read_file`, `write_file`, `edit_file`, `list_dir`, `glob_files`,
`grep_files`, `bash`.

## Development

```sh
uv venv && uv pip install -e .
AGAPICODE_API_KEY=sk-… agapicode --readonly "what does this repo do?"
```

`AGAPICODE_API_BASE` points the client at a different deployment.

The copy of `install.sh` served at `atomgpt.org/install` lives in the
my-open-webui repo under `backend/open_webui/custom_static/install.sh`; this
file is the canonical source.

## License

Apache-2.0
