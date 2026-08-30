#!/usr/bin/env python3
"""Audit-actor attribution gate -- no audited write may hardcode who did it (T-052).

`apps/desktop/src-tauri/core/src/repo.rs` states the rule at the definition of
`repo::audit::record` (repo.rs:313 before this task moved it):

    `actor_type` is passed explicitly by trusted repo code (never hardcoded 'user'),
    so agent-originated events stay distinguishable from human ones in
    `security::summary` (L-4a). Call sites at the command layer must derive `actor_id`
    from trusted context, not from the request body.

Thirty-four of the forty `audit::record` calls in that same file broke it, each passing the
literal pair `"user", "gev"`. The result was not a cosmetic wrong name. The automation
scheduler fires unattended once a minute (`automations::run_due`, spawned in `lib.rs`), and
every tick wrote `automation.ran` plus `task.created` or `knowledge.created` attributed to a
named human who was not present; `repo::seed` minted around forty more at first launch for
rows nobody created. An audit log that says a person did something they did not do is worse
than one that says nothing, because it reads as evidence.

Six calls were already correct, and they were not the same shape. Two derived BOTH halves
from trusted context (`&input.role, &input.author` in `chat::post_message`) -- that is the
shape this gate enforces. Two derived only the id and left the kind hardcoded
(`"user", requested_by`) -- half-fixed, and re-introducing the defect the rule names, so
this gate rejects that shape too. Two passed `"system", "system"` for genuinely
system-originated events, which is legitimate and is why SYSTEM_LITERALS exists.

What is checked
---------------
1. No `audit::record(...)` call passes a hardcoded `"user"` actor kind. The kind must be a
   variable, an `Actor` constructor or an expression -- something the caller had to derive.
2. No `audit::record(...)` call passes a literal PERSON name as the actor id.
3. No source file assembles `Actor { kind: "user", id: "<person>" }` by hand.

What is NOT checked, deliberately: rows written into `audit_events` by raw SQL rather than
through `audit::record`. `repo::seed` still does that for its fabricated activity-ECG rows,
and a gate that implied otherwise would be the same kind of unbacked claim this one exists
to stop.

Usage:  python3 tools/check_audit_actor.py [--root DIR]
Exit 0 + "GREEN: ..." when clean; exit 1 listing each offending path:line otherwise.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

SEARCH_ROOTS = [
    pathlib.Path("apps/desktop/src-tauri/core/src"),
    pathlib.Path("apps/desktop/src-tauri/src"),
    pathlib.Path("apps/desktop/src-tauri/core/tests"),
]

# Actor ids that name a component of this product rather than a person. A system-originated
# event is allowed to name itself; that is what makes it distinguishable from a human one.
# `local-operator` is here because it asserts only "a person at this cockpit", which is the
# most the desktop can establish -- it has no login and no operator credential.
SYSTEM_LITERALS = {
    "system", "seed", "scheduler", "automation", "run-executor", "local-operator",
}

# The call form under inspection: `audit::record(`, however it is module-qualified.
RECORD_CALL = re.compile(r"(?:^|[^A-Za-z0-9_:])((?:\w+::)*audit::record)\s*\(")
# A hand-assembled Actor literal.
ACTOR_LITERAL = re.compile(r"Actor\s*\{\s*kind\s*:\s*\"(\w+)\"\s*,\s*id\s*:\s*\"([^\"]*)\"")


def _close_paren(text: str, open_idx: int) -> int:
    """Index of the `)` matching the `(` at or after `open_idx`, skipping string and char
    literals and line comments so a paren inside `"a)b"` cannot end the call early."""
    i, depth = text.index("(", open_idx), 0
    while i < len(text):
        c = text[i]
        if c in "\"'":
            quote, i = c, i + 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
        elif c == "/" and text[i:i + 2] == "//":
            i = text.index("\n", i)
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced parentheses")


def _split_args(body: str) -> list[str]:
    out, depth, cur, i = [], 0, "", 0
    while i < len(body):
        c = body[i]
        if c in "\"'":
            quote, j = c, i + 1
            while j < len(body):
                if body[j] == "\\":
                    j += 2
                    continue
                if body[j] == quote:
                    break
                j += 1
            cur += body[i:j + 1]
            i = j + 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip():
        out.append(cur)
    return [a.strip() for a in out]


def _literal(arg: str) -> str | None:
    """The contents of `arg` if it is a plain string literal, else None."""
    m = re.fullmatch(r'"([^"]*)"', arg.strip())
    return m.group(1) if m else None


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def check_source(rel: pathlib.Path, text: str) -> list[str]:
    problems: list[str] = []

    for m in RECORD_CALL.finditer(text):
        open_idx = text.index("(", m.end() - 1)
        close_idx = _close_paren(text, open_idx)
        args = _split_args(text[open_idx + 1:close_idx])
        line = _line_of(text, m.start(1))
        # record(conn, event_type, actor, entity_type, entity_id) -- the T-052 signature.
        # The pre-T-052 signature spliced the actor across two literal arguments; both are
        # caught, because argument index 2 is the actor position either way.
        if len(args) < 3:
            problems.append(
                f"{rel}:{line}: audit::record call with too few arguments to inspect"
            )
            continue
        actor = args[2]
        kind = _literal(actor)
        if kind is not None:
            actor_id = _literal(args[3]) if len(args) > 3 else None
            if kind == "user":
                problems.append(
                    f"{rel}:{line}: audit::record hardcodes the actor kind \"user\""
                    + (f" for actor id {actor_id!r}" if actor_id else "")
                    + " -- derive it from trusted context (repo.rs, `audit::record`:"
                      " \"never hardcoded 'user'\"). Use an `audit::Actor` constructor."
                )
            elif actor_id is not None and actor_id not in SYSTEM_LITERALS:
                problems.append(
                    f"{rel}:{line}: audit::record hardcodes the actor id {actor_id!r}, "
                    f"which names neither a system component nor the local operator"
                )
        else:
            # An expression. Reject the half-fixed shape that still hardcodes the kind:
            # `Actor { kind: "user", id: <derived> }`.
            if re.search(r"kind\s*:\s*\"user\"", actor) and not re.search(r"Actor::\w+", actor):
                problems.append(
                    f"{rel}:{line}: audit::record builds an actor with a hardcoded kind "
                    f"\"user\" -- that is the half-fixed shape the rule at repo.rs "
                    f"`audit::record` names"
                )

    for m in ACTOR_LITERAL.finditer(text):
        kind, actor_id = m.group(1), m.group(2)
        if kind == "user" and actor_id not in SYSTEM_LITERALS:
            problems.append(
                f"{rel}:{_line_of(text, m.start())}: hand-built "
                f"`Actor {{ kind: \"user\", id: {actor_id!r} }}` names a person -- build it "
                f"with an `audit::Actor` constructor so the trust basis is written down"
            )

    return problems


def check(root: pathlib.Path) -> tuple[list[str], int, int]:
    problems: list[str] = []
    files = calls = 0
    for sub in SEARCH_ROOTS:
        base = root / sub
        if not base.exists():
            problems.append(f"{sub}: search root does not exist")
            continue
        for path in sorted(base.rglob("*.rs")):
            text = path.read_text(encoding="utf-8")
            files += 1
            calls += len(RECORD_CALL.findall(text))
            problems.extend(check_source(path.relative_to(root), text))
    if calls == 0:
        problems.append(
            "no audit::record call site was found at all -- this gate would pass "
            "vacuously, which means it has stopped looking at the code it was written for"
        )
    return problems, files, calls


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = pathlib.Path(args.root)

    problems, files, calls = check(root)
    if problems:
        print("RED: an audited write hardcodes who did it --", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s). The rule is stated at `repo::audit::record` in "
            f"apps/desktop/src-tauri/core/src/repo.rs: the actor is passed explicitly by "
            f"trusted repo code, never hardcoded 'user', so agent- and system-originated "
            f"events stay distinguishable from human ones (L-4a).",
            file=sys.stderr,
        )
        return 1
    print(
        f"GREEN: every audited write names an actor it derived ({calls} audit::record call "
        f"sites across {files} Rust files; no hardcoded \"user\" kind, no literal person as "
        f"an actor id)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
