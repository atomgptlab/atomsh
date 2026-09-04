# Atomsh

**Your autonomous coding agent for science.**

Atomsh reads and edits files, searches the codebase, and runs commands from
your terminal, and it can look a material up while doing it.

> **You need an account on [atomgpt.org](https://atomgpt.org).** That account
> is the only credential Atomsh uses. There is no OpenAI or Anthropic key to
> supply, and no other provider to configure. Sign up first, then install.

Python 3.10 or newer. Tested on Linux and WSL2; macOS should work.
Windows needs WSL.

Full documentation: **<https://atomgptlab.github.io/atomsh>**

## Install

```sh
curl -fsSL https://atomgpt.org/install | bash
```

The installer uses `uv` when it is present, falls back to a virtualenv, and
bootstraps `uv` if the system Python is unusable. Everything lands in an
isolated environment with a launcher in `~/.local/bin`. No sudo.

## Connect

Sign in at [atomgpt.org](https://atomgpt.org) first if you have not already,
then:

```sh
atomsh login
```

This opens atomgpt.org in your browser and starts a one-request listener on
`127.0.0.1`; you approve once, and the credential comes back to your machine
and is stored `0600` in `~/.config/atomsh/auth.json`. Nothing is sent anywhere
else. On a headless machine use `atomsh login --key` and paste an API key from
Settings → Account → API Keys instead.

`atomsh whoami` checks the stored credential; `atomsh logout` forgets it.

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
excluded on purpose: those run the AtomGPT materials agent on the server and
answer in prose rather than making tool calls, so they cannot drive a coding
loop. Use them through a chat client instead.

## Tools

`read_file`, `write_file`, `edit_file`, `list_dir`, `glob_files`,
`grep_files`, `bash`.

### Materials tools

atomsh connects to the AtomGPT MCP server with the same credential and
carries six more tools by default: `explore`, `build`, `predict`,
`characterize`, `apply`, `validate`. Each dispatches to a family of AtomGPT apps: JARVIS-DFT lookups,
ALIGNN predictions, band structures, XRD, interfaces, protein folding, so the
agent can look a material up instead of answering from the model's memory:

```
$ atomsh --materials "bandgap of silicon JVASP-1002 from JARVIS-DFT"
  · explore(app=/jarvis_dft/query, params={"jid": "JVASP-1002"})
OptB88vdW 0.731 eV · mBJ 1.277 eV · HSE 1.22 eV
```

The tool list is cached under `~/.local/share/atomsh/` and refreshed daily,
and the MCP session is opened on first use, so carrying them costs nothing at
startup. `--no-materials` leaves them out, worth doing for pure coding work,
where a narrower tool surface is easier for the model.

## Development

```sh
uv venv && uv pip install -e .
ATOMSH_API_KEY=sk-… atomsh --readonly "what does this repo do?"
```

`ATOMSH_API_BASE` points the client at a different deployment.

`install.sh` here is the canonical installer; `atomgpt.org/install` serves a
copy of it.

## License

Apache-2.0

## Citing

Atomsh builds on the AtomGPT platform and the JARVIS infrastructure. If it
contributes to work you publish, please cite the relevant papers below.

1. J. Lee, J. Ely, K. Zhang, A. Ajith, C. R. Campbell and K. Choudhary,
   "AGAPI-Agents: An Open-Access Agentic AI Platform for Accelerated Materials
   Design on AtomGPT.org", *The Journal of Physical Chemistry Letters* **17**
   (26), 7221-7231 (2026).
   [doi:10.1021/acs.jpclett.6c00837](https://doi.org/10.1021/acs.jpclett.6c00837)

2. K. Choudhary, "The JARVIS infrastructure is all you need for materials
   design", *Computational Materials Science* **259**, 114063 (2025).
   [doi:10.1016/j.commatsci.2025.114063](https://doi.org/10.1016/j.commatsci.2025.114063)

3. K. Choudhary, "ChatGPT Material Explorer: Design and Implementation of a
   Custom GPT Assistant for Materials Science Applications", *Integrating
   Materials and Manufacturing Innovation* **14** (3), 276-283 (2025).
   [doi:10.1007/s40192-025-00410-9](https://doi.org/10.1007/s40192-025-00410-9)
