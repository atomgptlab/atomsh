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
# English approximation, but a coding agent's transcript is mostly not English:
# source, dense JSON, base64 and - when a tool reads a binary file by mistake -
# effectively random bytes, all of which tokenize far worse. Under-counting is
# the dangerous direction, because the run dies on a 400 rather than merely
# compacting sooner than it had to.
CHARS_PER_TOKEN = 3

# Exchanges at the end that are never compacted, counted in blocks.
KEEP_RECENT = 4

# How much of the newest tool result survives when even that has to give.
TRIM_TO = 2000


IMAGE_TOKEN_COST = 1600


def _content_chars(content) -> int:
    """Characters in a message body, whether it is text or mixed parts.

    An image is charged a flat token cost rather than the length of its data
    URL: base64 is enormous and would swamp the estimate, but the image is not
    free either, and treating it as free is how a transcript quietly overruns.
    """
    if isinstance(content, str):
        return len(content)
    if not isinstance(content, list):
        return 0
    total = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "image_url":
            total += IMAGE_TOKEN_COST * CHARS_PER_TOKEN
        else:
            total += len(part.get("text") or "")
    return total


def estimate_tokens(messages: list) -> int:
    """Approximate token count of a message list."""
    total = 0
    for m in messages:
        total += _content_chars(m.get("content"))
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


ELIDED_IMAGE = "[image elided to fit the context window]"


def _elide(block: list) -> bool:
    """Blank out tool results and images in one block. True if changed."""
    changed = False
    for message in block:
        content = message.get("content")
        # An image costs as much as a long file and is rarely needed twice,
        # so it goes at the same point old tool output does.
        if isinstance(content, list):
            if any(p.get("type") == "image_url"
                   for p in content if isinstance(p, dict)):
                text = " ".join(p.get("text") or "" for p in content
                                if isinstance(p, dict)
                                and p.get("type") != "image_url")
                message["content"] = f"{text} {ELIDED_IMAGE}".strip()
                changed = True
            continue
        if message.get("role") == "tool" and content != ELIDED:
            if len(content or "") > len(ELIDED):
                message["content"] = ELIDED
                changed = True
    return changed


def compact(messages: list, limit: int, force: bool = False):
    """Return (messages, compacted) with the list brought under `limit`.

    Messages are mutated in place where content is elided, so the caller's
    session ends up holding the smaller version too - the point is to bound
    memory and the saved session file, not only the request.

    `force` is for the case the estimate got it wrong and the endpoint has
    already refused the request as too long. Trusting the estimate then would
    do nothing at all, so the target becomes half of what is currently there,
    which guarantees the retry is smaller than the attempt that failed.
    """
    current = estimate_tokens(messages)
    if force:
        limit = min(limit, current // 2)
    elif current <= limit:
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

    if not force:
        return rebuilt(), True

    # Forcing means the endpoint has already refused this transcript, so the
    # recent exchanges are no longer sacred: a task that continues with less
    # context beats one that stops. The newest block is kept longest, and even
    # it is trimmed rather than emptied, so the model still sees what its last
    # tool call returned.
    for block in tail[:-1]:
        if estimate_tokens(rebuilt()) <= limit:
            break
        _elide(block)

    if estimate_tokens(rebuilt()) > limit and tail:
        for message in tail[-1]:
            if message.get("role") == "tool":
                body = message.get("content") or ""
                if len(body) > TRIM_TO:
                    message["content"] = body[:TRIM_TO] + "\n" + ELIDED

    return rebuilt(), True
