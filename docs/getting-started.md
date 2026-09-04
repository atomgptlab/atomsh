---
title: Getting started
---

# Getting started

## Requirements

An account on [atomgpt.org](https://atomgpt.org), and Python 3.10 or newer.

Atomsh is tested on Linux and on Windows through WSL2. macOS is expected to
work, since the installer avoids GNU-only tools and the code uses nothing
Linux-specific, but it has not been run there yet; reports welcome. Native
Windows is not supported, because the installer is a shell script and the
terminal handling assumes a POSIX tty.

You do not need an OpenAI or Anthropic key. Atomsh talks only to atomgpt.org.

## Install

```sh
curl -fsSL https://atomgpt.org/install | bash
```

The installer prefers [uv](https://docs.astral.sh/uv/), falls back to a
virtualenv, and bootstraps uv if the system Python has no working pip. It
installs into an isolated environment and links a launcher into
`~/.local/bin`. No sudo, nothing system-wide.

If you already use uv or pipx, install it directly from PyPI:

```sh
uv tool install atomsh
```

```sh
pipx install atomsh
```

Both work anywhere Python does, including macOS, and skip the shell installer
entirely.

If `~/.local/bin` is not already on your PATH, the installer adds it to your
shell startup file and prints the one-line `export` to apply it to the shell
you are in, so you do not have to open a new terminal. Set
`ATOMSH_NO_MODIFY_PATH=1` to be told rather than helped.

## Connect

```sh
atomsh login
```

This opens atomgpt.org in your browser and starts a single-request listener on
`127.0.0.1` at a random port. You approve once, the authorization code comes
back to that listener, and Atomsh exchanges it for a credential stored with
mode `0600` in `~/.config/atomsh/auth.json`.

The loopback address is the point: the code travels from your browser to your
own machine and never crosses the network. The `code_challenge` in the URL is
PKCE, which stops an intercepted code from being redeemed by anyone else.

### On a remote machine

Over SSH, on a cluster login node, or anywhere the browser runs somewhere
else, the loopback flow cannot complete: the redirect lands on the browser
machine's own `127.0.0.1`, not on the host running Atomsh. Approving works and
nothing arrives.

```sh
atomsh login --manual
```

Approve in a browser anywhere, let the `127.0.0.1` page fail to load, then
paste that address back into the terminal. The code is in it, and no listener
is needed. Atomsh detects an SSH session and points this out before you start.

If you would rather not use a browser at all:

```sh
atomsh login --key
```

Paste an API key from atomgpt.org under Settings, Account, API Keys.

To check or clear the stored credential:

```sh
atomsh whoami
atomsh logout
```

## First run

Start in a repository you do not mind it reading:

```sh
atomsh --readonly "what does this repo do, and where is the entry point?"
```

`--readonly` refuses every write and shell command, so it is a free look at
whether the answers are useful before letting it touch anything. Then drop the
flag; it will ask before each write or command.

## Upgrading

Re-running the installer is the one instruction that works everywhere. It
finds the existing install and upgrades it in place, whether that was a uv
tool environment or the virtualenv fallback:

```sh
curl -fsSL https://atomgpt.org/install | bash
```

If you installed with uv or pipx directly, use those instead:

```sh
uv tool upgrade atomsh
```

```sh
pipx upgrade atomsh
```

Check what you got with `atomsh --version`.

To run an unreleased commit, point the installer at the repository:

```sh
curl -fsSL https://atomgpt.org/install | \
  ATOMSH_SOURCE="git+https://github.com/atomgptlab/atomsh.git" bash
```
