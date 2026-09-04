---
title: Troubleshooting
---

# Troubleshooting

## `atomsh: command not found` right after installing

The launcher lives in `~/.local/bin`. The installer adds that directory to
your shell startup file, but an already-open shell does not pick it up. Either
open a new terminal, or apply it to this one:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Sourcing `~/.bashrc` is not always enough, since many distributions return
early from it in a non-interactive context.

To install without the installer touching any startup file, set
`ATOMSH_NO_MODIFY_PATH=1`; it will print the line for you to add yourself.

## The browser does not open during login

Atomsh prints the URL before trying to open it. Paste that URL into any browser
on the same machine and approve there. The listener waits five minutes.

Under WSL the URL is handed to Windows, so your Windows default browser opens
and the callback still reaches the listener inside WSL through localhost
forwarding.

## Login approved, but nothing happened

You are on a remote host, and the redirect went to `127.0.0.1` on the machine
running the browser rather than the machine running Atomsh.

Paste the failed page's full address into the terminal at the prompt.
`atomsh login` is listening for that as well as for the redirect. Or use
`atomsh login --key` and paste an API key.

## `Not signed in`

No credential is stored. Run `atomsh login`. If you believe you are signed in,
`atomsh whoami` will say whether the stored credential still works; a key
revoked on atomgpt.org will fail here.

## A request fails with a connection error

```text
error: request to https://atomgpt.org/api failed: ...
```

Atomsh reports these rather than raising. Check that atomgpt.org is reachable
and that your credential is valid with `atomsh whoami`.

## A 429, or a quota message

The deployment meters usage per account. A 429 means you have reached the
limit for the current window. Conversations already in progress can continue;
new ones resume when the window rolls over. The message says how much you have
used and when to retry.

## The model edits the wrong text, or an edit fails

`edit_file` requires the old text to match exactly and to be unique. When it
fails, the error tells the model to read the file and copy the exact text, and
it usually recovers by itself. If it loops, `/clear` and describe the change
more precisely.

## A materials tool returns an error

The tools are self-describing. If the model guesses an app path that does not
exist, the error lists the real ones and it retries. Persistent failures on a
large structure usually mean the calculation exceeded the server's time limit;
try a smaller cell.

## Responses contain odd markers

Should not happen: Atomsh strips channel control markers such as
`<|channel>thought` from model output. If you see one, please open an issue
with the text.

## It will not stop

Press ++esc++ while a response streams. Ctrl-C interrupts, Ctrl-D exits.
