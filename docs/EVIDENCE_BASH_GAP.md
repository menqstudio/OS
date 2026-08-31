# Evidence: a conscientious agent bypassed the coordination wall dozens of times, in silence

**Date:** 2026-08-30 · **Repository:** `menqstudio/OS` · **Head at measurement:** `main` @ `fe26a78`

**Status of every claim below: `measured`.** Each is followed by the command that produced it and
what that command printed. Nothing here is inferred, and nothing is the Builder's recollection.

---

## What happened

In one night's session, an AI agent working under this repository's own governance wrote to
`tools/`, `.github/workflows/` and the canonical coordination documents dozens of times without
the `PreToolUse` hook firing once. It had no intent to evade anything. It did not know. Nothing
told it, and nothing told the Owner either.

It was found only because a *different* agent, doing an unrelated design task, was asked to read
the hook matchers and report them.

The agent's own words, when it understood what it had been doing:

> I have written to `tools/`, `.github/` and canonical files with Bash dozens of times tonight —
> heredocs, `sed -i`, `python -c`. Every one of them passed beside `PreToolUse`. I did it not to
> get around the wall, but because auto mode prefers Bash, and the hook is silent.

## The measurement

The root hook configuration, from `.claude/settings.json`:

```
SessionStart         matcher='(none)'
SubagentStart        matcher='(none)'
UserPromptSubmit     matcher='(none)'
PreToolUse           matcher='Edit|Write|MultiEdit|NotebookEdit'
Stop                 matcher='(none)'
```

`Bash` is absent from that matcher. Therefore a file written by `cat > path`, `tee`, `sed -i`, or
`python -c "open(path,'w')"` reaches the disk without the hook being invoked at all — no phase
declaration, no canonical-law gate, no coordination check.

The engine's own configuration, from `engine/.claude/settings.json`, is different:

```
PreToolUse           matcher='*'
PostToolUse          matcher='Bash|PowerShell|Shell'
PostToolUseFailure   matcher='Bash|PowerShell|Shell'
```

**The precise claim, and it matters that it is precise.** The engine's enforcement wall is not
bypassed this way; its `PreToolUse` matcher is `*`. What is bypassed is the **root coordination
gate** — phase declaration, the canonical law gate, and coordination-document consistency.

## Two things that make it worse than it first looks

**1. The wall loads from the SESSION's project root, not from the directory being edited.**
`CLAUDE.md` §5 states this, and this session is the live demonstration: its project directory is
the repository root, the per-turn injected context comes from `.claude/hooks/canonical_law_gate.py`,
and the engine's `bro_hook.py` produced no output at any point in the session. So work done from a
root checkout — which is every session and every agent in this repository — runs under the weaker
matcher **even when it edits `engine/` itself**.

`README.md` already carried the sentence "wiring it at the root is a known open decision". That
sentence is this gap. It was rhetoric; it is now a measurement.

**2. The engine's Bash coverage is `PostToolUse` — after the write.**
`engine/runtime/bro_hook.py:148-177` handles `post-tool`; on a not-green settlement it calls
`_observe_or_block`, which at `:94-102` either emits `[SHADOW] would block …` or calls
`deny(reason)` and emits `{"decision": "block"}`. There is no revert, no unlink and no restore
anywhere in it. **The write that already happened stays on disk.**

That is worth having — the evidence chain records what occurred and the session is stopped before
the next step — but it is **detection plus a halt, not containment**. A security model that says
"Bash is covered" without saying which of the two it means is overclaiming, and this document
exists so that it cannot.

## Why this is published rather than quietly patched

This repository's thesis is that an AI agent's authority must be enforced by something that runs,
not stated in a document it is asked to obey. The night this was found produced the cleanest
possible demonstration of that thesis, and the demonstration is against ourselves:

* a **conscientious** agent, with no incentive to evade;
* **zero** malicious intent;
* **dozens** of violations;
* complete **silence** from the control;
* and it surfaced only because someone **measured the matcher** rather than reading the design.

Every part of that is the argument for enforcement over instruction. An agent that wanted to
bypass the gate would not have needed to try; the default tool did it.

## What was done about it

Tracked as `T-053`. The remedy is deliberately sequenced, because the fix itself is a hazard:
changing the matcher while other agents are mid-task would refuse their work under a rule that did
not exist when they started.

1. The gap is **proven first** by a test that writes a protected path through Bash and asserts the
   hook did not fire. That test asserts today's behaviour, so it is a regression guard and changes
   nothing for anyone.
2. The containment change lands **separately and last**, on a tree with no other work in flight.

Deciding which paths an arbitrary shell command writes is undecidable in the general case —
`sh -c "$(printf …)"`, a Python one-liner, a Makefile target, a script that writes a script — so
"add `Bash` to the matcher" is not automatically the right answer. The design records honestly
whether a reliable pre-execution check is possible, and if it is not, names the containment that
is: a content-based check of what changed on disk rather than an intent-based reading of what the
command said. That is the shape the engine already uses for `Bash|PowerShell|Shell`.

## What this document does not claim

It does not claim the engine's enforcement wall was bypassed — it was not. It does not claim any
harm resulted; every write in this session was ordinary repository work by an agent doing what it
was asked. And it does not claim the gap is closed: at the time of writing it is measured,
documented and sequenced, and the containment has not landed.

---

## Postscript, 2026-08-30: the fix caught its own author, and nobody was testing it

The section above closes with *"the containment has not landed"*. It landed the same night, as
`T-053b` (PR #191): one new `PostToolUse` event on `Bash|PowerShell|Shell`, running the same
predicates as the `PreToolUse` path against what changed on disk. `Bash` was deliberately **not**
added to `PreToolUse`, for the reason this document already gave — the pre-execution question is
undecidable.

It fired twice on the session that integrated it. The first was a deliberate probe: a write to
`apps/desktop/src/App.tsx` returned `{"decision": "block"}` naming the meta scope, and cleared on
revert. That one proves sensitivity and nothing more, because it was invited.

The second was not invited, and it is the one that matters:

    NEXT_CHAT.md is 8,602 bytes against a ceiling of 8,500. While a canonical document is
    over budget the only accepted edit is one that makes it smaller.

**I was not testing. I was writing the handoff.** The text describing this very change went over
the canon ceiling, the settlement halted the turn, and it kept firing across successive shell
calls — not once and forgotten — until the text was cut back under the ceiling. Nothing about that
was staged, and nothing about it was noticed until the block arrived.

That is the difference between a demonstration and evidence, and it is the whole reason this
postscript exists rather than a line in a commit message. A demonstration proves the author can
make the thing fire. An unplanned firing, hours later, on ordinary work, against its own author,
proves it fires when nobody is watching for it — which is the only condition it will ever run in.

The arc is closed and each step is separately checkable:

| | |
|---|---|
| the gap existed | this document, and `tools/test_wall_bash_gap.py` asserting today's behaviour |
| the fix was designed, and the obvious one rejected | `T-053b`'s commit message: a `PreToolUse` shell path-check is undecidable, twelve spellings of one write carried as the corpus |
| the fix works | two mutants — *baseline the violator too*, *shell-tool filter removed* — each 1 failure of 33; hook restored byte-exact, `sha256 ce97e2da…`, recomputed at integration rather than taken from the branch |
| the fix caught its author | the unplanned second firing above |

What it still is not: **detection plus halting the turn, not containment.** The write has already
landed and nothing undoes it. The engine's own `PostToolUse` path has the same limit. A security
model claiming containment from either overstates both, and `docs/ARCHITECTURE.md` now says so in
the row that used to describe the wall.
