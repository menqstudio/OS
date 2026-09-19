## Phase 2 — Governance Sidecar · Կառավարման Sidecar

**Objective.** Give the cockpit read-only, faithful **surfaces** onto the engine's governance truth —
approvals, decisions, the evidence chain, and gate notifications — so the owner can see and act on every
governed decision. The engine remains authoritative; the desktop only mirrors and requests.

**Scope.** In: the four governance pages (`approvals`, `decisions`, `security`, `notifications`), the
read IPC that streams engine ledger/evidence/verdicts, and the **approve/deny request** path (the desktop
*requests*; the engine *decides*). Out: any desktop-side decision authority; any change to the engine's
gate logic.

**Architecture.** A read/notify channel from the engine sidecar to the desktop: the engine emits
governance events (pending approval, verdict issued, evidence appended); the desktop renders them and can
POST an owner approval **request** that the engine's Ed25519 approval system adjudicates. Mirrors, never
decides (ARCHITECTURE principle 2).

**UI/UX work.** Full page-specs (per §D) for four pages:

- **`approvals` ✔ Հաստատումներ (Approval gate).** Components: approval queue (`apQueue`), decision pill
- **`decisions` ⚖ Որոշումներ (Decision ledger).** Components: chamber view (`chamber`), append-only ledger
- **`security` ⛨ Անվտանգություն (Evidence chain / posture).** Components: chain integrity view, control-plane
- **`notifications` ◈ Ազդանշաններ (Signals).** Components: signal feed, filter chips, per-signal action.

**Backend work.** Rust IPC commands to read the engine ledger/evidence/queue and to POST an approval
request; a thin desktop mirror store for display and dedupe. **No gate logic in the desktop.**

**Contracts / schemas.** Consume `verifier-receipt` + `execution receipt` + evidence events (§F). Add a
small `approval-request` shape (desktop→engine) if one does not already exist in the engine schemas —
if it requires an engine schema change, that is an **audited engine task**, flagged, not done here.

**Data models.** Desktop mirror tables: `governance_signal`, `approval_mirror`, `decision_mirror` (all
display caches keyed by engine ids; the engine ledger stays authoritative; caches are rebuildable).

**Dependencies.** Phase 1 (the bridge produces receipts/evidence the surfaces render). Can start as soon
as the Phase-1 contract exists, in parallel with early Phase-3 shell work (§E).

**Security gates.** All four pages are **read + request only**. The desktop cannot mint, alter, or
approve on its own; owner approval is adjudicated by the engine's Ed25519 system. A chain-integrity break
renders the `blocked` state and disables dependent actions.

**Tests.** Rust IPC read/parse tests; a contract test that a desktop approval-request never carries a
key/lease; a UI test that `blocked`/`error` states render on engine-unreachable and chain-break; verdict
rendering matches the engine verdict byte-for-byte.

**CI requirements.** Cockpit legs stay green with the new IPC + pages; add UI state tests to the frontend
leg. No new engine leg unless an engine schema was (audited) added.

**Documentation updates.** `docs/ARCHITECTURE.md` (governance surfaces section), this phase's page-specs,
`PROJECT_STATE.md`.

**Acceptance criteria.** The four pages render live engine governance data faithfully; owner can *request*
an approval that the engine adjudicates; every page implements all §D states incl. `blocked`; no desktop
decision authority exists.

**Merge gate.** Architect confirms "mirror, never decide" holds; state coverage complete; contracts
unchanged (or engine change separately audited); Owner approval.

**Stop conditions.** Any temptation to let the desktop decide/approve locally, or to cache a key/lease →
stop. Any needed engine gate change → separate audited task.

> **⚖ Phase 2 was CHECKED AGAINST THE CODE before anything was built (T-019, 2026-08-15).** The
> exemption in `config/roadmap-order-exemptions.json` unlocked this phase while all four pages
> already existed, so the first act was verification, not construction. Every box below carries its
> evidence — file, line, test name — and a box whose surface exists but whose obligation is unmet
> **stays unticked and says which obligation**. Six of eleven were ticked; **eight are now**, after
> the Owner delegated both remaining decisions on 2026-08-15 and fact 2 turned out to be a build task
> after all. The three still open are one fact, tracked as `T-021`. Both facts as they stood:
>
> 1. **The approval-REQUEST path does not exist, on either side** (boxes 2 · 7 · 11). There is no
>    `approval-request` schema in `engine/schemas/` (21 schemas; none is one) and no desktop→engine
>    command. The `approvals` page's grant/deny/escalate drive the **desktop's own** approval system
>    (T-010/T-011 over local SQLite, behind a native confirmation the webview cannot forge) — a real
>    authority, correctly gated, but the desktop's, not a request across the wall. This phase's own
>    **Contracts** row pre-authorised that outcome: an `approval-request` needing an engine schema
>    change is *"an audited engine task, flagged, not done here"*. It is flagged, in
>    `governance.rs`'s module docs, here, and — since 2026-08-15 — on the one page that says what is
>    blocked and on whom: [`docs/OWNER_ACTION_REQUIRED.md` §2a(ii)](docs/OWNER_ACTION_REQUIRED.md).
>    Being flagged in the roadmap is not the same as being *routed*: a decision recorded only beside
>    the box it blocks is a decision the Owner has to go looking for.
>
>    **DECIDED 2026-08-15 (Owner delegated): opened as `T-021`, and still not built here.** Neither
>    "build it now" nor "carry it" was right. Building it now would add a new desktop→engine input to
>    a trust boundary whose standing audit verdict is **RED**, and would break this phase's own scope
>    line. Carrying it as a roadmap note is how an obligation disappears — Phase 2's **acceptance
>    criteria** promise *"owner can request an approval that the engine adjudicates"*, and a phase
>    must not close over a promise it kept only in prose. So the task exists, with its contract
>    invariants **fixed now** while the reasoning is fresh — no key, no lease, no nonce, no verdict
>    crosses; the desktop requests and never decides; the desktop's own T-010/T-011 authority stays a
>    separate thing — and it is sequenced explicitly **behind the standing audit**. Boxes 2 · 7 · 11
>    stay unticked, because the capability does not exist, and now they name what will build it.
> 2. ~~**`security`'s §D `sigbreathe` integrity pulse is deliberately NOT applied**~~ — **DECIDED
>    AND BUILT, 2026-08-15 (boxes 1 · 9 now ticked).** The Owner delegated the decision; it was taken
>    by reading the page rather than the argument about it, and **the argument turned out to be
>    wrong in its own favour**. The reasoning on record was sound — a breathing instrument would
>    paint liveness onto a chain nothing has confirmed — but `Security.tsx` was **already breathing**:
>    `.mc-halo` carried an unconditional `secHalo 2.6s infinite`, so the instrument pulsed hardest in
>    `blocked`, the exact state the comment two hundred lines above forbade it in. *An honesty
>    argument written in a comment is not an honesty property of the page.*
>
>    "Never animate" and "animate always" were also not the only options. §D's pulse is now
>    **bound to state**: `checking` is a chain read genuinely in flight, so motion there depicts
>    something that is happening; `broken` takes the faster danger cadence §D asks for; `blocked` is
>    **still**, which it was not before. The pulse says *"this surface is reading the chain right
>    now"* — a fact the desktop can establish — never *"the chain is alive"*, which it cannot:
>    `RECORDS_ARE_AUTHENTICATED` is permanently `false`. A pulse gated on a **confirmed** chain would
>    have been a branch that can never run — the shape this repository deletes rather than ships —
>    which is why the obvious "make it conditional on verified" reading was rejected.
>
>    Three mutants, all killed: applied unconditionally (2 tests red), never applied (1), bound to
>    `blocked` instead of `checking` (2). Reduced motion still stills all of it.
>
> One §D gap WAS closed rather than reported: §D binds `g` to grant and no `g` handler existed, so a
> keyboard owner could deny and escalate by keystroke and not grant. `g` now stages the same confirm
> dialog `d`/`e` stage — §D's own *"all actions confirm before committing"* — instead of committing
> on one keypress, which would have made the deliberate press-and-hold bypassable by the binding
> meant to complete it (`Approvals.tsx`; two tests, both mutation-verified).
>
> **One stale claim was corrected on the way.** `governance.rs` opened with *"the Phase-2 engine read
> endpoints do not answer yet"*. They answer: `bro_control_room_api.GOVERNANCE_SURFACES:47` names all
> four and `governance_read:568` dispatches them. What is still true is narrower — a shipped install
> reaches `Blocked` because nothing sets `BROPS_GOVERNANCE_STATE_DIR`. The steady state is unchanged;
> the reason for it is a deployment input, not a missing endpoint.

**Definition of Done.**
- [x] `approvals`, `decisions`, `security`, `notifications` pages built to full §D spec. — all four exist and are real, every §D state, keyboard map and a11y role verified against the source. The one thing this box was held open for — `security`'s `sigbreathe` pulse — is **built and bound to state** (2026-08-15, Owner-delegated decision; see fact 2 above): `Security.tsx` adds the `sigbreathe` class in `checking` only, the halo's cadence is per-state, and `blocked` is now still where it used to breathe. Three mutants killed (`Security.test.tsx`); reduced motion stills all of it. **The change that closed this box also broke it, for one day.** The `animation` shorthand replaced `.reveal`'s entrance, so the instrument rendered at `opacity:0` for the whole of `checking` — the fifth audit measured it in a real browser (`A-01`) and nothing here could, because vitest runs with `css: false`. Fixed 2026-08-16 by composing the animation list, and `tools/check_c1_tokens.py::animation_clobber` now refuses the shape statically: putting the shorthand back turns the gate RED.
- [ ] Read IPC streams engine ledger/evidence/verdicts; approval-**request** path works. — **the read half is complete and wired end to end**: four commands (`governance.rs:611/619/626/634`), registered (`lib.rs:227-230`), served by the engine (`bro_control_room_api.py:47`, `:568`, `:616-621`), relayed verbatim (`engine_sidecar.py:477`, `:808`), consumed by the renderer (`desktop.ts:344-355`). **The approval-request half does not exist** — no engine schema, no command. **Tracked as `T-021`** (opened 2026-08-15 by Owner-delegated decision), sequenced behind the standing audit, with its contract invariants fixed in the task row. Stays unticked: a capability that does not exist does not tick, and naming its owner is not the same as having it.
- [x] `blocked` + `error` states proven against engine-unreachable and chain-break. — unreachable: `governance.rs::unreachable_transport_maps_to_unreachable`, plus `Notifications.chain.test.tsx:76`, `Security.test.tsx:40`, `Approvals.test.tsx:41`. Chain-break, both doors: the engine reporting one (`ok_false_reply_maps_to_blocked`) and a malformed link arriving in the records (`a_broken_chain_link_blocks_the_whole_read_rather_than_showing_part_of_it`, with a positive control and mutant `P1` killed). **The limit is written inside the box:** the desktop does not WALK the chain — it checks `previous_event_hash` is null-or-64-hex and no more. Fork detection is the supervisor's on both platforms; re-deriving a head from records the desktop cannot authenticate would be a check that cannot fail.
- [x] No desktop-side decision authority; no cached keys/leases. — structural, and now **checked** rather than asserted: `no_governance_command_can_take_a_key_a_lease_or_the_database` reads this module's own source and requires every `#[tauri::command]` to take nothing but an optional `task_id` filter (mutant `P2` — a command growing a `key_id` parameter — killed). The request carries `read_only: true` and no key/lease/nonce/verdict (`governance.rs:586-595`); `RECORDS_ARE_AUTHENTICATED` is `false` and the engine's own `record_authentication` claim is pinned as unable to flip it. CI-enforced at `tools/check_capabilities.py:53-60`, which names all four with written reasons; gate GREEN.
- [x] Docs + `PROJECT_STATE.md` synced. — `docs/ARCHITECTURE.md` gained the **governance surfaces** section this phase's Documentation row names and that had never been written; `PROJECT_STATE.md` / `NEXT_CHAT.md` / `TASKS.md` / `config/current_state.json` updated in the same commit per the Continuous-Documentation Law.

**Task checklist.**
- [x] Build the governance read IPC (ledger/evidence/queue) in Rust; parse tests. — `apps/desktop/src-tauri/src/governance.rs`, four commands + a fail-closed three-valued `GovernanceRead`, validated against `verifier-receipt.schema.json` and `evidence-event.schema.json`. **29 tests, measured** (`cargo test -p brops --lib governance::` → 29 passed).
- [ ] `approvals` page (queue + grant/deny/escalate **request**) per §D. — the page is built and its actions are real, but they are the **desktop's** approval commands, not an engine request. Unticked for fact 1 above, not for a missing surface; the request half is `T-021`.
- [x] `decisions` page (ledger + evidence viewer, read-only) per §D. — `Decisions.tsx`: `chamber` (`:464`), `ledger` `role=log` + `aria-readonly` (`:229-245`), `chEvidence` (`:500`), arrow/Home/End navigation and `Enter`-opens-evidence (`:193-203`), `aria-live` announcer (`:557`). `chReweigh` is present and **disabled by design** (`:508`) — reweighing is the engine's. Evidence renders the real `ok`/`blocked`/`unreachable` read and fabricates nothing (`Decisions.evidence.test.tsx`, `Decisions.governance.test.tsx`).
- [x] `security` page (chain integrity + control-plane digest + residual tracker) per §D. — all four sections are built (integrity instrument, posture strip, control-plane digest honestly blocked, residual tracker O-1..O-5, key/lease registry blocked by design) with `[`/`]` sectioned tab order and a live region that escalates to `assertive` on a break. §D's `sigbreathe` motion is applied and **bound to state** (fact 2 above) — and closing it removed an existing dishonesty rather than adding a feature: the halo animated unconditionally, so the instrument breathed hardest in `blocked`.
- [x] `notifications` page (signal feed) per §D. — `Notifications.tsx`: `role=feed` (`:269`), per-signal `role=article` (`:287`), `aria-live=polite` (`:256`), filter chips (`:247`), `↑/↓` · `Enter` · `x` (`:123-136`). The read-path chain node is earned, never assumed — `Notifications.chain.test.tsx` covers unreachable / blocked / empty-ok / unauthenticated-records / the engine's attributed reason, six tests.
- [ ] Contract test: approval-request carries no key/lease; verdicts render faithfully. — the second half holds (`parse_verifier_receipt` enforces `verdict == GREEN`, the id and 64-hex patterns and a non-empty evidence list; `Bridge.test.tsx` drives the real command). The **first half is structurally unwritable today**: there is no approval-request, and a test asserting that a nonexistent request carries no key is a check that cannot fail — the shape this repository deletes rather than ships. It becomes writable with `T-021`, and the invariant it must pin is already written in that task row so the test is not designed by whoever is trying to pass it.

---
