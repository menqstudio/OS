# `contracts/` dedupe — the migration plan

**Status.** Phase 3 deliverable: *"`contracts/` dedupe plan recorded"*. This records it. Phase 3's own
Contracts row is explicit that the work here is to **reference, not relocate** — *"reference (do not
yet relocate) `execution-lease`/`approval`/`task-contract`/`mode-grant`; record the migration plan
for the final dedupe milestone"*. Nothing moves in Phase 3. The milestone that moves files is Phase
10.

**Written 2026-08-15.** Every count below was measured, not recalled.

---

## 1. What is actually there

Four homes, not two.

| Home | Files | Owner | Consumed how |
|---|---|---|---|
| `engine/schemas/` | 21 | Python engine | loaded at runtime by the engine; **hand-mirrored** in Rust |
| `engine/contracts/` | 3 (`brops-*.v1`) | the signer wire protocol | loaded by the signer/supervisor |
| `bridge/contracts/` | 4 | the desktop ↔ sidecar bridge | `task-request` is **loaded at runtime by Rust** (`governed_sidecar.rs`) |
| `contracts/` | 0 + a README | — | nothing consumes it |

The top-level `contracts/` directory named by the roadmap **holds no schemas at all**. It is a
README describing an intention.

## 2. The duplication is not what the README says it is

`contracts/README.md` says the schemas are *"mirrored informally in the desktop's Rust `domain`"* and
frames the risk as **two drifting copies of a file**. That framing is wrong in a way that matters for
the plan: **there are no duplicate schema files anywhere in this repository.** A search for a second
copy of any `*.schema.json` outside `node_modules` returns nothing.

The real duplication is **a schema in Python and a hand-written Rust type that must agree with it**,
with nothing but a doc comment connecting them:

| Python schema | Rust mirror | Binding today |
|---|---|---|
| `engine/schemas/verifier-receipt.schema.json` | `governance.rs::VerifierReceipt` | a doc comment |
| `engine/schemas/evidence-event.schema.json` | `governance.rs::EvidenceEvent` | a doc comment |
| `engine/schemas/task-contract.schema.json` | path rules in `ai.rs` | a doc comment |
| `bridge/contracts/task-request.schema.json` | `governed_sidecar.rs` | **the file is read at runtime** |
| `engine/contracts/brops-sign-result.v1.schema.json` | `governed_bridge_result.rs` | a frozen enum order in a comment |

That distinction changes the fix. Moving files into `contracts/` would relocate the *Python* side and
leave every Rust mirror exactly as unbound as it is now — motion without progress. The property worth
buying is **one definition that both sides are held to**, and the only row above that has it today is
`task-request`, because Rust *reads the file* instead of restating it.

**So the dedupe milestone's real deliverable is a binding, and relocation is only the filing that
makes the binding convenient.**

## 3. A schema this repository names in three places and does not have

`approval` does not exist. Not in `engine/schemas/` (21 files, none is one), not in
`bridge/contracts/`, not in `engine/contracts/`, nowhere in the tree outside `node_modules`.

It is named as one of the canonical five by:

- `contracts/README.md` — *"`execution-lease` · `mode-grant` · `approval` · `task-contract` · `verifier-receipt`"*
- `MASTER_EXECUTION_ROADMAP.md` Phase 3, Contracts row — *"reference … `execution-lease`/`approval`/`task-contract`/`mode-grant`"*
- and, by implication, Phase 10's dedupe item

This is the same finding Phase 2 recorded from the other end: **the approval-REQUEST path across the
wall does not exist on either side** (tracked as `T-021`). The missing schema and the missing path
are one absence seen twice. The desktop's approvals are its own authority — T-010/T-011 over local
SQLite — and they were never a contract between the two halves, so no contract was ever written.

**Corrected in this change:** `contracts/README.md` no longer lists a schema that does not exist, and
says which four are real. The roadmap's Contracts row is left alone deliberately — it is a phase
specification, and amending a phase's stated scope after the fact is how a plan stops being a record
of what was agreed. It is annotated instead, pointing here.

## 4. Also corrected: the README promised the wrong phase

`contracts/README.md` said *"Phase 3 extracts them here so both sides consume the same files."* Phase
3's Contracts row says the opposite in the same words the roadmap uses everywhere else: **reference,
do not yet relocate**. A reader who trusted the README would have arrived expecting files that Phase
3 was never going to move, concluded the phase had failed, and been wrong.

## 5. The migration, in the order it has to happen

Each step is independently mergeable and leaves the tree working.

**M1 — bind before you move (Phase 10 opens here).**
A gate that reads each `*.schema.json` and the Rust type that claims to mirror it, and fails when the
required-field sets disagree. Today `VerifierReceipt` gaining a field the schema forbids — or the
schema gaining a required field Rust does not parse — is caught by nothing until a real payload
fails in production. This is the whole value of the milestone and it needs **no file to move**.

*Precondition:* none. *Provable by:* delete a field from the schema, watch the gate go red.

**M2 — one home for the cross-half schemas.**
Move only the schemas both halves consume — `verifier-receipt`, `evidence-event`, `task-contract`,
`execution-lease`, `mode-grant` — into `contracts/`, leaving `engine/schemas/` re-pointed. The other
16 are engine-internal and moving them buys nothing but churn.

*Precondition:* M1 green, so the move is provably behaviour-preserving. *Risk:* every Python loader
path changes at once; that is why M1 comes first.

**M3 — the bridge and signer protocols stay where they are.**
`bridge/contracts/` and `engine/contracts/` are **wire protocols between two named processes**, not
shared domain objects. They are correctly filed next to the process that serves them, and folding
them into `contracts/` would make the directory mean two different things. Recorded as a decision, so
a later reader does not "finish" the job by moving them.

**M4 — retire the hand-mirrors that can be generated.**
Where a Rust type is a pure restatement of a schema, generate it. Where it is not — `GovernanceRead`
adds fail-closed states the schema has no concept of — keep the hand-written type and keep M1's gate
on the overlapping fields.

## 6. What is NOT in this plan

- No file moves in Phase 3. See §above; this is the roadmap's instruction, not a deferral.
- No new `approval` schema. That is `T-021`, sequenced behind the standing audit, and inventing the
  schema here would be building the thing the audit gate exists to sequence.
- No change to `engine/schemas/registry.json` semantics.

---

*Related:* `MASTER_EXECUTION_ROADMAP.md` Phase 3 (Contracts / schemas) · Phase 10 (`contracts/` dedupe)
· `docs/PHASE_10_PRODUCTION_ITEMS.md` §3 · `TASKS.md` `T-021`.
