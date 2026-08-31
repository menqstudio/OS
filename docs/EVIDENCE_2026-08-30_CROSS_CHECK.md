# Evidence: six errors, four sources, one mechanism — a single night, recorded

**Date:** 2026-08-30 · **Repository:** `menqstudio/OS` · **Session:** one night, `main` `40be210` → `34c5fb5`

Every line below is a measurement with the command that produced it. Nothing here is a
recollection, and nothing is a promise about future behaviour.

---

## What happened

In one working night, six factual errors were made by four different parties — the Owner, a
builder agent, an architect agent, and a design lead. **None of them reached `main`.** Each was
caught, and in every case the thing that caught it was an artifact that runs — a gate, a test, a
mutation, a re-measurement — rather than someone reading carefully.

| Source | The error | What caught it |
| :--- | :--- | :--- |
| **Owner** | "34 hardcoded audit actors" — the real count is 39 | `grep -c` before the task was handed over |
| **Owner** | "`contracts/` holds 6 schemas" — it holds 5, and the same sentence listed five | `ls` before the file was copied |
| **Owner** | "the whole wall is bypassable through Bash" — the engine's `PreToolUse` matcher is `*` and does catch Bash | reading both `settings.json` files instead of one |
| **Owner** | `$BROPS_SHADOW_LEDGER` — the variable is `BRO_SHADOW_LEDGER` | `grep` for the name at its read site |
| **Owner** | "a missing ledger falls back to shadow — fail-open" — it does not; every failure path denies | reading `_observe()`'s four exits |
| **Builder agent** | a §0.3 invariant claimed but not bound | an architect agent's mutation sweep |
| **Architect agent** | `T-050` re-introduced the "verdict depends on the machine" defect **in the same file, three lines below the comment explaining it** | the README agent, running the gate from a worktree |
| **Architect agent** | "exactly one call site is already correct" — six are, and the arithmetic behind the one was wrong (39 counts LINES, 40 counts CALLS) | the Owner's hand count |
| **Design lead** | four cited line numbers off by two | its own re-read, corrected out loud rather than silently |

## The one thing worth taking from it

**No error was caught by attention. Every one was caught by an artifact.**

That distinction is the whole argument. Attention is not repeatable, does not survive a tired
hour, and cannot be handed to the next session. A gate that runs is repeatable by construction —
and it caught the repository's own author as readily as it caught the agents working for him.

Two of the nine are worth reading twice, because they are the cases where care would not have
been enough:

* The architect **re-introduced a defect three lines below the comment that explains the defect**.
  It had read that comment. Reading was not the failure.
* The Owner's five errors all share one shape — *measured one instance, stated a conclusion about
  the class*. That is the failure mode the repository's own gates exist against
  (`check_doc_claims`, `check_reachability`, `check_dead_tokens`), and it was produced by the
  person who commissioned them.

## What this is not

It is not a claim that the mechanism catches everything: it caught these six, and says nothing
about what it missed. It is not a claim that the product is finished — the production gate is
shut, the independent verdict is RED at the ninth round, and every mark added since is the
Builder's own (◑). And it is not a claim of unusual diligence by anyone: the errors are ordinary,
which is exactly why the record is worth keeping.

It is one night, with the commands, published including the parts that are unflattering to the
people who published it.

## Postscript, the same night: the author broke a rule inside the sentence describing it

**2026-08-30, `TASKS.md`, the `T-056` row.** The row describes a gate that refuses a control wired
to nothing. It cited `config/control-invocation.json` — the registry that gate would read, which
does not exist yet. `tools/check_doc_claims.py` refused it:

    RED: TASKS.md references `config/control-invocation.json`, which does not exist.
         A citation to a file nobody filed is how `A-06` happened — twice

Forty minutes earlier the same session had written, in `docs/README_CLAIM_HISTORY.md`, that a
forward reference and a rotted one are the same defect. The rule was on screen. It did not help.

It happened twice in one night. Three hours before this, the session recorded
*one-measurement-is-not-the-whole* — count the population before generalising — and then proposed
a hand-maintained list where the population had to be derived.

**Writing a rule does not protect against breaking it.** Not when the author is the one who wrote
it, and not while the words are still on the screen. Only an artifact that runs protects against
it, and here one did — twice, in the file describing the rule it was enforcing.

Lesson files are the most dangerous place for this gate to be lenient, not the least: they are
written about work that has not happened yet, so a forward reference is the natural temptation.
When this gate goes red inside `docs/`, that is the gate working. The remedy is the one the
repository already uses for deferred work — **name what must exist first, do not point at it**:
`blocked_on:`, never a path.
