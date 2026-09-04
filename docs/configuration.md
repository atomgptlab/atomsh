---
title: Configuration
---

# Configuration

Atomsh has no configuration file. Everything is a flag or an environment
variable, and the defaults are meant to be right.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `ATOMSH_API_KEY` | Use this credential instead of the stored one. Useful in CI |
| `ATOMSH_API_BASE` | Point at a different AtomGPT deployment. Default `https://atomgpt.org` |

`ATOMSH_API_KEY` takes precedence over `~/.config/atomsh/auth.json`, so you can
run a one-off against another account without logging out.

## Files

| Path | Contents |
|------|----------|
| `~/.config/atomsh/auth.json` | The stored credential, mode `0600` |
| `~/.local/share/atomsh/sessions/` | Saved conversations, one JSON file each |
| `~/.local/share/atomsh/mcp-tools.json` | Cached materials tool definitions |

These follow `XDG_CONFIG_HOME` and `XDG_DATA_HOME` when those are set.

Deleting the tool cache forces a refresh on the next run. Deleting a session
file removes that conversation. Neither breaks anything.

## Models

Set a model per invocation with `-m`, or per session with `/model`. The default
is `gemma-4-26b`. `atomsh models` lists what your account can reach, marking
the one in use.

Which models exist depends on the deployment, not on Atomsh. The list is
fetched at runtime.

## Uninstalling

```sh
uv tool uninstall atomsh
rm -rf ~/.config/atomsh ~/.local/share/atomsh
```

The second line removes your credential and saved sessions.
