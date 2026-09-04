---
title: Home
---

# Atomsh

**Your autonomous coding agent for science.**

Atomsh reads and edits files, searches a codebase, and runs commands from your
terminal. It also queries JARVIS-DFT, runs ALIGNN predictions, computes band
structures and analyses diffraction patterns, in the same loop, so it can look
a material up instead of recalling it.

It runs on [AtomGPT](https://atomgpt.org) alone. One account, no provider keys
to configure.

!!! note "You need an atomgpt.org account"
    That account is the only credential Atomsh uses. Sign up at
    [atomgpt.org](https://atomgpt.org) first, then install.

## Install

```sh
curl -fsSL https://atomgpt.org/install | bash
```

Then connect and start:

```sh
atomsh login
atomsh
```

## What it looks like

```text
atomsh v0.1.0, your autonomous coding agent for science
gemma-4-26b · /home/you/project · materials + code · /help for commands

› calc.py crashes when you run it. Fix it and verify.
  · read_file(path=calc.py)
  · edit_file(path=calc.py, old_string=def divide(a, b): …)
  · bash(command=python3 calc.py)
Fixed the ZeroDivisionError in calc.py:6 and verified by running it.
```

And the part no other coding agent does:

```text
› bandgap of silicon JVASP-1002 from JARVIS-DFT
  · explore(app=/jarvis_dft/query, params={"jid": "JVASP-1002"})
OptB88vdW 0.731 eV, mBJ 1.277 eV, HSE 1.22 eV
```

## Why it exists

A general coding agent asked about ALIGNN will describe something plausible and
wrong, because it is answering from model weights. Atomsh carries the AtomGPT
tools, so it answers from the database instead.

## Where to go next

- [Getting started](getting-started.md) for install and sign-in details
- [Using Atomsh](usage.md) for the commands and flags
- [Tools](tools.md) for what it can actually do
- [Permissions](permissions.md) for what it will ask before doing

Requires Python 3.10 or newer. Linux and macOS; Windows through WSL.
Apache-2.0 licensed.
