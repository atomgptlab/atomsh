"""Keeping a long conversation inside the model's context window.

A coding session grows without bound: every file read and every command's
output stays in the transcript forever. Past the window the endpoint answers
400 and the run is over mid-task, which is the worst moment to stop, so old
material has to be given up before that happens.

Tool output goes first. It is the bulk of a transcript and the least useful
part once it has been acted on: the assistant's own reasoning about a file
survives, the 30k characters of the file itself does not. Whole exchanges are
dropped only when elision alone is not enough.

What is never touched: the system prompt, the task the user asked for, and the
most recent exchanges, which are what the model is actually working from.
"""

# A tool call and its results are one indivisible unit. An assistant message
# carrying tool_calls whose results have been dropped - or a tool result whose
# call is gone - is a malformed request, and the endpoint rejects it.

ELIDED = "[output elided to fit the context window]"

# Rough, deliberately dependency-free. Four characters per token is the usual
# English approximation; being wrong by 20% only shifts when compaction fires.
CHARS_PER_TOKEN = 4

# Exchanges at the end that are never compacted, counted in blocks.
KEEP_RECENT = 4


def estimate_tokens(messages: list) -> int:
    """Approximate token count of a message list."""
    total = 0
    for m in messages:
        total += len(m.get("content") or "")
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            total += len(fn.get("name") or "")
            total += len(fn.get("arguments") or "")
        total += 16  # role, framing, and other per-message overhead
    return total // CHARS_PER_TOKEN


def _blocks(messages: list) -> list:
    """Group messages so a tool call stays attached to its results."""
    groups = []
    for message in messages:
        role = message.get("role")
        if role == "tool" and groups and groups[-1][0].get("tool_calls"):
            groups[-1].append(message)
        else:
            groups.append([message])
    return groups


def _split(messages: list):
    """(protected head, middle blocks, protected tail blocks)."""
    head = []
    rest = list(messages)
    if rest and rest[0].get("role") == "system":
        head.append(rest.pop(0))
    # The first user message is the task itself; losing it loses the goal.
    for i, message in enumerate(rest):
        if message.get("role") == "user":
            head.append(rest.pop(i))
            break
    groups = _blocks(rest)
    if len(groups) <= KEEP_RECENT:
        return head, [], groups
    return head, groups[:-KEEP_RECENT], groups[-KEEP_RECENT:]


def _elide(block: list) -> bool:
    """Blank out tool results in one block. True if anything changed."""
    changed = False
    for message in block:
        if message.get("role") == "tool" and message.get("content") != ELIDED:
            if len(message.get("content") or "") > len(ELIDED):
                message["content"] = ELIDED
                changed = True
    return changed


def compact(messages: list, limit: int):
    """Return (messages, compacted) with the list brought under `limit`.

    Messages are mutated in place where content is elided, so the caller's
    session ends up holding the smaller version too - the point is to bound
    memory and the saved session file, not only the request.
    """
    if estimate_tokens(messages) <= limit:
        return messages, False

    head, middle, tail = _split(messages)

    def rebuilt():
        out = list(head)
        for block in middle:
            out.extend(block)
        for block in tail:
            out.extend(block)
        return out

    # First pass: drop the bodies of old tool results, oldest first.
    for block in middle:
        if estimate_tokens(rebuilt()) <= limit:
            break
        _elide(block)

    # Second pass: if elision was not enough, drop whole old exchanges. Each
    # block is removed entire, so calls and results never separate.
    while middle and estimate_tokens(rebuilt()) > limit:
        middle.pop(0)

    return rebuilt(), True
