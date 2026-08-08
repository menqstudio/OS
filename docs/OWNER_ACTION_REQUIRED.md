# Owner action required

Everything in this repository that cannot move without Gev. One page, kept current, so the answer
to "what is waiting on me" is never reconstructed from a chat log.

Nothing here is a suggestion to flip anything. `platform_governed_execution_supported()` is false
and `main()` keeps `UpstreamBlockedExecutor`; that stands until every item below is closed, a
**separate** audit passes, and the Owner approves — in that order.

---

## 1. How a production trust registry gets minted — a decision, not a task

**This blocks O-2, O-3 and O-5, and nothing else can unblock them.**

Nothing in this repository can produce a production trust root, and that is deliberate:

| Where | What it does |
|---|---|
| `engine/tools/broctl.py` — `build-registry` | hardcodes `"production": false` and stamps *DEVELOPMENT REGISTRY* |
| `engine/tools/broctl.py` — `keygen --production` | refuses outright |
| `engine/runtime/bro_signature.py` | refuses a non-production registry whenever the operator pin comes from the production `BRO_OPERATOR_ROOT_PUBKEY_FILE` path |

So the ceremony in [`OWNER_CEREMONY.md`](./OWNER_CEREMONY.md) runs honestly end to end and produces
a **development** root. That is enough to exercise every path, watch each refusal turn into an
acceptance, and find the next problem. It is not enough to close O-2, O-3 or O-5, and recording it
as though it were is the exact failure this repository has spent a week removing.

The decision is yours because it is a custody question, not an engineering one: **what process
mints the production registry, and where does its private half live?** A tool in this repository
that could do it would defeat the reason the refusals exist.

Until that is answered, treat every ceremony run as a rehearsal.

---

## 2. Ceremony steps only you can run

From [`DEBIAN_DEPLOYMENT.md`](./DEBIAN_DEPLOYMENT.md). Each one touches the operator private key,
which is why no agent may run them and why Step 4 carries its own warning — `build-registry` reads
private halves out of `--keydir`.

| Step | What it is | State |
|---|---|---|
| 1 | the offline root key | done — development root on USB |
| 2 | **O-3**, the conductor session | waiting on you |
| 3 | **O-5**, the evidence floor anchor | waiting on you |
| 4 | publish the keys — **a signing step** | waiting on you |
| 5 | **O-2**, the audit signer | waiting on you |

Steps 0, 6 and 7 are agent-runnable and have been run on the Debian box. Step 6 and Step 7 both
had to be rewritten afterwards; see PR #71 and PR #72.

Everything you produce here is anchored to a development root until item 1 is decided.

---

## 3. The independent audit, then your approval

The gate does not open when O-1..O-5 close. It needs an audit of the whole chain **by someone who
did not build it**, and then your approval.

A green CI is not an audit. CI runs the tests we wrote. Three audits on this repository have come
back RED on rows the builder had marked closed, which is why `✅` in these documents means
*independently confirmed* and `◑` means *the builder's unverified claim*.

---

## 4. Merge authority

Normally yours. On the night of 2026-08-07 you delegated it explicitly ("քըմիթ փուշ մերջ սաղ քո
վրայա") for that session only. Merges made under that delegation are listed in the PR history with
their CI state at the time; the delegation does not extend past that session and does not extend to
the gate under any circumstances.

---

## 5. Known open, not blocked on you

Recorded here only so nothing looks closed that is not. These are being worked and need no decision
from you.

- `docs/PHASE_10_PRODUCTION_ITEMS.md` — O-1 through O-5, all OPEN. `tools/check_residual_items.py`
  holds that document to a complete inventory and agrees with `CLAUDE.md` and
  `docs/SECURITY_MODEL.md`.
- The read-only control plane (O-1) is **deployed and verified** on the Debian box — root itself
  cannot write to `/opt/brops/engine` — but O-1 stays open until the acknowledgement path is
  removed rather than merely unused.
- **22 tests skipped in every CI run**, including the entire live enforcement-wall subprocess suite
  and the execution-transaction drills, because both modules are gated on `engine/` being its own
  git worktree root and it is not one in this monorepo. They were proved to pass against a
  throwaway git-root copy of the tree; being fixed with a fixture, so they run rather than being
  waived.
- **A Windows security check did nothing where it mattered.** The operator-root pin refuses a pin
  file owned by the account reading it (audit F-06) — an anchor one write away from being whatever
  that account wants. On the CI runner it did not refuse, because an administrator's files are
  owned by `BUILTIN\Administrators` rather than by the user, so the "is the owner me?" comparison
  came back unequal. The question is being changed to the one that matters: *can the reading
  account rewrite this file?* Found by running the engine suite on Windows for the first time.

*The last two are why `engine-windows` and the prerequisite guard were added in PR #72: a test
that never runs and a check that never fires both read exactly like coverage.*

---

*Update this file in the same commit as any change to what it claims. A page about what is blocked
is worthless the moment it is stale, and staleness here reads as progress.*
