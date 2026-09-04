---
title: Development
---

# Development

```sh
git clone https://github.com/atomgptlab/atomsh
cd atomsh
uv venv && uv pip install -e .
```

Run it against your account without installing globally:

```sh
ATOMSH_API_KEY=sk-… .venv/bin/atomsh --readonly "what does this repo do?"
```

## Layout

| Module | Responsibility |
|--------|----------------|
| `cli.py` | Argument parsing, commands, the interactive session |
| `agent.py` | The loop: model, tool calls, results, model |
| `client.py` | Streaming chat, tool-call assembly |
| `tools.py` | Code tools and their schemas |
| `mcp.py` | Client for the AtomGPT tool server |
| `auth.py` | OAuth login, credential storage |
| `permissions.py` | The approval gate |
| `session.py` | Conversation persistence |
| `text.py` | Stripping model control markers |
| `interrupt.py` | Escape-to-interrupt during streaming |
| `browser.py` | Opening a URL, including from WSL |
| `prompt.py` | The system prompt |

One runtime dependency, `httpx`. Python 3.10 or newer.

## Testing a change

```sh
uv tool install --editable .
```

Installs the launcher against your working tree, so edits take effect on the
next run with no reinstall.

## Releasing

Tagging publishes to PyPI through trusted publishing:

```sh
git tag v0.1.1 && git push origin v0.1.1
```

The workflow refuses to publish when the tag does not match the version in
`pyproject.toml`.

## Documentation

This site is MkDocs with the Material theme, deployed to GitHub Pages on every
push to `main`.

```sh
uvx --with mkdocs-material mkdocs serve
```
