# Wave 3b-1 re-scope — implementation index (3b-1A + 3b-1B)

> **STATUS (2026-07-24):** **3b-1A is Architect Code GREEN** (@ `dffd164`; latest exact-head
> CI 8/8 GREEN — query GitHub Checks for the current HEAD's run); **3b-1B is design-lock RED**
> — the Architect reviewed the consolidated **rev 15** (@ `848f2a6`; exact-head CI #119 SUCCESS;
> CI GREEN ≠ design GREEN) and returned Design RED with 3 P0 + 3 P1 protocol/proxy/state-consistency
> findings, mandating a **6-track read-only fan-out audit + one integrator + a fresh
> independent red-team**; the addendum is now **rev 16 (CONSOLIDATED)** — a
> proposed design-GREEN candidate, **not yet Architect-GREEN, no code**. See `NEXT_CHAT.md` §3
> for the authoritative current state, STOP gates, and next action.
>
> **This file is a concise IMPLEMENTATION INDEX, not a schema source.** The single normative
> source for every 3b-1B contract (artifact matrix, exact schemas, time model, capability
> profile, acceptance state machine, verification, authorities) is
> [`WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md).
> Where this file and the addendum disagree, **the addendum wins**; do not re-inline schemas
> here (they drift).

## 1. Re-scope

After the 2nd code-audit RED (PR #31), 3b-1 was split into **3b-1A** (isolated
signing-boundary completion — ✅ Architect Code GREEN) + **3b-1B** (authoritative
execution→receipt binding — design-lock in progress). Both on PR #31. **3b-2 does not
start** until 3b-1 is exact-head zero-trust GREEN and merged.

## 2. Existing engine primitives 3b-1B REUSES (no parallel executor)

The governed AI turn is run as a `bro_supervisor`-owned supervised execution reusing these
primitives — but see the addendum for the **governed-turn-specific** authorities/schemas
that wrap them (the base functions below are NOT used verbatim for the governed path):

- `engine/tools/bro_supervisor.py::run_task` / `spawn_builder` — process-group containment
  execution model (the model executor is the `builder_command`, run under the recorder).
- `engine/runtime/bro_evidence.py` — signed evidence chain + head (`event_hash`, `load_head`,
  `validate_chain`, `EvidenceHead`).
- `engine/tools/brops_live_runstate.py::LiveRunStateProvider` — the verifier; in 3b-1B it
  verifies the **signed** `brops.governed-turn-record.v1` and all cross-bindings (addendum §7).

**Governed-turn-specific contracts (NOT the base functions) — see the addendum:**
- **Lease:** `issue_governed_turn_lease` / `validate_governed_turn_lease` (addendum §4.3, §8)
  — a **dedicated** `brops.governed-turn-lease.v1` with the closed `governed-model-turn-v1`
  capability profile; **NOT** the base `issue_lease` / `validate_execution_lease`.
- **Receipt:** `brops.governed-turn-execution-receipt.v1` signed by the evidence-recorder
  runner, verified by `verify_governed_turn_receipt` (addendum §4.7); **NOT**
  `bro_run_receipt.run_and_sign` / `verify_passing_receipt` (those CRLF-normalize and are
  not byte-exact).
- **Terminal record:** `brops.governed-turn-record.v1` signed **only** by the dedicated
  **`governed-turn-recorder`** authority (addendum §4.8, §8) — **NOT** the evidence-recorder.
- **execution_attempt_id:** the **supervisor reserves it** inside the acceptance state
  machine (addendum §5); the desktop **never** supplies it, and it is **not** a
  `task-request` field.

## 3. Current-truth invariants (canonical)

- Unsigned JSON is **never** authority; the sole terminal authority is the signed
  `brops.governed-turn-record.v1`.
- The supervisor reserves `execution_attempt_id`; the desktop never supplies it.
- The dedicated `governed-turn-recorder` signs only the terminal record; the
  evidence-recorder runner signs the governed-turn receipt + evidence.
- All governed-turn timestamps are integer **epoch-milliseconds** (`_ms`); the base
  execution-lease (`*_epoch`, seconds) is unchanged and unused by this path.
- Full artifact matrix + exact schemas + acceptance state machine live ONLY in the addendum.

## 4. Order + non-goals

3b-1A (CI GREEN, done) → 3b-1B (design-GREEN → implement) → then 3b-2/3b-3. All on PR #31.
STOP: `NoTrustedManifest` unchanged, no production "Verified", PR #31 not merged until 3b-1B
is design-GREEN + implemented + code-audit GREEN + exact-head CI GREEN.
