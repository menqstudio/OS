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
