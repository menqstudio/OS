"""Test helper: read the live kit's shell scripts as TEXT.

Two suites hold `engine/ci/live/*.sh` to account by lifting pieces out of them — a whole script,
one top-level function, one heredoc — and each had its own copy of the three readers. The copies
of `heredoc` had already diverged: one returned the body alone and followed a backslash-newline on
the opener line, the other returned `(index, body)` and did not. A reader that disagrees with its
twin about where a heredoc starts is a fixture testing its own drift, so there is one of each here.

Not a test module (no ``test_`` prefix), so unittest discovery ignores it.
"""
from __future__ import annotations

import os

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Derived from the engine tree: the kit ships INSIDE engine/, so it is present wherever the
# engine is, whatever the directory above it is called.
LIVE_DIR = os.path.join(ENGINE_ROOT, "ci", "live")


def script(name: str) -> str:
    """The text of `engine/ci/live/<name>`."""
    with open(os.path.join(LIVE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def shell_function(text: str, name: str) -> str:
    """The text of the top-level shell function `name() { ... }` in `text`."""
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith(name + "() {")]
    if len(starts) != 1:
        raise AssertionError("%d definitions of %s" % (len(starts), name))
    end = starts[0]
    while lines[end] != "}":
        end += 1
    return "\n".join(lines[starts[0]:end + 1]) + "\n"


def heredoc(text: str, tag: str) -> tuple[int, str]:
    """(index of the line carrying `<<'tag'`, the heredoc's body as bash would feed it).

    Exactly one heredoc may carry the tag. The body starts after the opener's LOGICAL line: a
    backslash-newline joins the opener to the next line, so those continuation lines belong to
    the command and not to the body.
    """
    lines = text.split("\n")
    openers = [i for i, line in enumerate(lines) if "<<'%s'" % tag in line]
    if len(openers) != 1:
        raise AssertionError("%d heredocs tagged %s" % (len(openers), tag))
    start = openers[0]
    while lines[start].endswith("\\"):
        start += 1
    start += 1
    end = start
    while lines[end] != tag:
        end += 1
    return openers[0], "\n".join(lines[start:end]) + "\n"
