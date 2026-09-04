---
title: Getting started
---

# Getting started

## Requirements

An account on [atomgpt.org](https://atomgpt.org), and Python 3.10 or newer.
Linux and macOS work directly; on Windows use WSL.

You do not need an OpenAI or Anthropic key. Atomsh talks only to atomgpt.org.

## Install

```sh
curl -fsSL https://atomgpt.org/install | bash
```

The installer prefers [uv](https://docs.astral.sh/uv/), falls back to a
virtualenv, and bootstraps uv if the system Python has no working pip. It
installs into an isolated environment and links a launcher into
`~/.local/bin`. No sudo, nothing system-wide.

If you already use uv or pipx:

```sh
uv tool install atomsh
# or
pipx install atomsh
```

If `~/.local/bin` is not on your PATH, the installer says so and prints the
line to add.

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

On a machine with no browser:

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

```sh
uv tool upgrade atomsh
```

Or run the installer again, which upgrades in place.
