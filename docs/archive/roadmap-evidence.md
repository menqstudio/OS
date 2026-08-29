# Roadmap evidence — the prose under each Definition-of-Done box

Moved out of `MASTER_EXECUTION_ROADMAP.md` on 2026-08-29 (`T-045`).

The checkbox is the contract; the paragraph under it is the record of what was measured.
Phase 1's Definition of Done alone was **16,290 bytes — 63% of a 26 KB phase** — while the
other fifteen required sections came to 9.6 KB between them. A session may only work the
first phase that is not done (`tools/check_roadmap_order.py`), so every session was carrying
ten phases of other people's evidence into its context to reach one phase of its own.

Nothing is shortened here. Every line is as it was written.

---


## Phase 1 — AMENDED 2026-08-09 — it reports; it does not set

****Governed-provider status control** (Settings). **AMENDED 2026-08-09 — it reports; it does not set.****

  The original text asked for an opt-in *toggle* carrying `BROPS_AI_PROVIDER`, default OFF. That was
  written before the provider policy landed, and it is not honestly buildable today.
  `ai.rs::resolve_provider` resolves the provider from the **backend process environment**
  (`BROPS_AI_PROVIDER` + `BROPS_ALLOW_GOVERNED_ENGINE` + `BROPS_ALLOW_UNGOVERNED`), and this phase's own
  Security gates say *"Desktop never holds lease/key/env"*: a webview-writable control would hand the
  renderer the choice of whether its own turns are governed — **including the downgrade direction** —
  which is the one authority this architecture refuses it (ARCHITECTURE principle 2: mirrors, never
  decides). A second and independent reason: the flip could not change an outcome in either direction,
  because `commands.rs::governed_verification_unconfigured()` returns `Some(...)` unconditionally, so a
  governed turn is blocked before the model is called. Switching it "on" would replace a working
  ungoverned chat with a uniformly refusing one — a *different refusal*, never the governed behaviour
  the row promised. **What ships, and what this criterion now means:** a read-only control reporting all
  three named states from the real `ai_status` — `default` (no governed provider resolved) / `on`
  (governed and ready) / `blocked` (governed, sidecar never became ready → the fail-closed reason is
  shown). Keyboard: focusable and announced (`role=switch` + `aria-checked` + `aria-disabled`, and
  **never** the `disabled` attribute, which drops the state out of the tab order); activation is inert
  by construction. *If the trust root moves so that a provider choice can be made outside the renderer
  and merely **requested** from it, this reverts to a real toggle — as a new slice, not this one.*

****Receipt indicator on the chat turn**: a small verified-receipt badge on each governed AI message**

  (reproduces a `mark`/`pill` element). States: `pending` (turn running, shimmer), `verified` (mint check
  + receipt id on hover), `unverified/blocked` (danger — and per contract **no result is shown**), `error`.
  Motion: `--fast` badge flip; live region announces "governed turn verified". A11y: `aria-live=polite`
  on the badge, receipt id exposed as `aria-label`.


## Phase 1 — Definition of Done

**`task-request` + `bridge-result` contracts defined and tested — **but only `task-request` is**

      enforced at runtime.** `bridge/engine_adapter.py:120` validates against it. `bridge-result.schema.json`
      is loaded in exactly one place, `bridge/tests/test_engine_sidecar.py:19`; `engine_sidecar.py` emits its
      result without checking it and `ai.rs` parses it with serde. It is a **test-only** contract, and the
      unqualified word "tested" above was hiding that.

**Adapter (`engine_adapter.py`) built; slice-1 tests **10/10** (PR #3, commit `5be8d95`) — re-run**

      2026-08-10, still 10. **Built, correct, and not reached:** its only caller is
      `bridge/engine_sidecar.py:485`, entered only from `ai.rs::governed_engine`, which no turn can start
      (see the round-trip row below).

**Opt-in `Provider::GovernedEngine` in desktop `ai.rs` (default OFF) — **transport shipped** (PR #8,**

      slice 2). Default-OFF holds (`ai.rs:405-460`; governed needs `BROPS_ALLOW_GOVERNED_ENGINE=1`), and
      the transport is real (`ai.rs:2880` spawns `bridge/engine_sidecar.py`). **No turn can use it:** all
      three callers of `ai::governed_turn` — `commands.rs:1385`, `:1865`, `:2077` — sit *after* the
      unconditional refusal at `commands.rs:1152`. "Transport shipped" is carrying the whole sentence.

**One governed round-trip proven end-to-end. **Still open, and an independent auditor has now**

      confirmed WHY.** The third audit (`apps/desktop/AUDIT/2026-08-14-zero-trust-audit-e0dd969.md`)
      read the three refusals rather than trusting the prose and found all three **closed** at
      `e0dd969`: `governed_verification_unconfigured()` is `Some(...)` with no branch
      (`commands.rs:1161-1164`), `connect_broker` is `#[cfg(target_os = "linux")]`
      (`governed_turn.rs:225-232`), and `build_governed_executor` returns `fail_closed()` unless
      `$BROPS_BROKER_CONFIG` is set and parses (`broker/src/main.rs:266-280`). **The gate is shut, on
      purpose, and confirmed shut by someone who did not build it.** That is what keeps this row
      open — not a missing implementation. It closes when an audit passes and the Owner approves, in
      that order. *(Its previous correction, kept:)* **This box read `[x]` and said "done", and it was
      false — corrected 2026-08-10 by checking the claim against the code instead of against its own
      commit message.** The box had already narrowed "round-trip" to a *fail-closed* one ending in
      `Blocked`; it is false even on those narrowed terms. The production order at
      `commands.rs:1338-1428` is `issue_challenge` (:1370) → `governed_unconfigured_block` (:1379) →
      **early `return`** (:1382) → and only *then*, unreached, `ai::governed_turn` (:1385) and
      `verify_and_record_receipt` (:1424). The gate is unconditional (`governed_verification_unconfigured`,
      `commands.rs:1152`, `Some(...)` with no condition), and the same shape guards the other two
      governed surfaces at `:1854` and `:2061`. So nothing is sent, no receipt is produced, and no
      signature is examined: `verify_and_record_receipt` and `verify_and_record_held_answer` have **zero
      runtime-reachable production callers**. The 23 green `receipt_store` tests exercise the seam in
      isolation, which is not the same claim.
      **What IS proven, and is a different seam:** `engine/ci/live/run_live_turn.sh`, driven by the
      `live-governed-turn` job (`ci.yml:72-119`), runs a real end-to-end governed turn — through
      `broker_orchestrator::run_governed_turn` + `governed_verification::verify_and_accept`, which never
      touches the chat path or the bridge adapter. Citing that run under this box would be the same
      substitution the box already made once. **The refusal itself is deliberate and stays:** the gate
      is the Owner's standing constraint, and this row is open because the roadmap was describing a
      round-trip the gate forbids — not because the gate is wrong.

**Governed output delivery through the wall. **Delta-streaming is DESCOPED** (see Scope — a governed**

      turn is buffered by construction, because the desktop's authority is a signature over the whole
      output). What this box now tracks is the thing that was being mistaken for it and is genuinely
      unbuilt: the rev-30 §4.10(f) chunked **output pull**. **HALF of it landed 2026-08-10** — the
      SUPERVISOR hop. `brops.governed-turn-output-read.v1` is served from the supervisor front door to
      the sidecar principal (`engine/runtime/governed_output_read.py`), the durable
      `governed_output_streams` table is in the canonical `supervisor_ledger.sql` with INSERT-ONCE /
      fixed-lifetime / digest-binding triggers, and the mint has a real production caller in the §5
      `complete-run` op. The `core/src/governed_output_stream.rs` (deleted 2026-08-10, see this cell) ladder this box used to point at was
      **DELETED** in the same change: it had zero production callers, its table diverged from the
      design, and its `CREATE TABLE IF NOT EXISTS` ran on the same connection one line before
      `supervisor_ledger::create_schema`, so keeping it would have made the canonical DDL a no-op.
      **STILL OPEN — but not for the reason this row carried until 2026-08-13.** It said the DESKTOP
      hop "does not exist". That sentence was written 2026-08-10; Slice 3 landed 2026-08-12 and this row
      was never updated, which is the standing docs row below doing its damage in the one place a cold
      reader would trust. The hop **exists**: the `protocol`-keyed branch is `_bridge_output_read`
      (`bridge/engine_sidecar.py:730`) behind `BRIDGE_OUTPUT_READ_PROTOCOL` (`:574`), and the pull loop is
      `brops_core::governed_output_pull`, driven end to end by the `ladder-governed-turn` job. The helper
      this row named, `governed_turn_output_read`, is in no file — the same class of error as the
      `platform_governed_execution_supported()` these documents watched for weeks.
      **The "wiring" sentence this row carried on 2026-08-14 is also corrected, same day, by reading the
      broker instead of the note about it.** It said the shipped broker "still reads the recorder's output
      with `std::fs::read(&report_path)` (`chain_executor.rs:882`) and never touches the egress". That
      cites the **direct AF_UNIX chain, which `build_governed_executor` no longer builds** — the Owner
      retired it on 2026-08-12 (`docs/OWNER_ACTION_REQUIRED.md` §1d RESOLVED) and `main.rs:246-252` says
      so in its own doc comment. The only governed executor the broker constructs is the §4.10(g) ladder
      (`main.rs:541`, `LadderChain::new`), and **the ladder pulls**: `governed_output_pull::pull_output`,
      imported at `ladder_executor.rs:63` and called at `:330`, listed as step 5 of the ladder at `:34`.
      The pull IS driven by the product's own executor.
      **So what actually keeps this row open is not a missing pull — it is the same gate as the row
      above.** `build_governed_executor` returns `UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG`
      names a deployment config with a TCB-root-signed manifest, and **nothing in the shipped app sets
      that variable** — every occurrence in the tree is a doc, a config sample or a comment. The ladder,
      and therefore the pull, is built only in a deployment that configures it.
      **Both open rows in this Definition of Done now reduce to one fact, and it is the Owner's:** the
      product path does not reach the governed machinery because the gate deliberately forbids it. No
      Builder change closes either row; an independent audit passing and the Owner approving does.
      Built, proven in CI, wired into the only executor the broker builds — and unreached by the shipped
      app **by design**. **Open.**

**Bridge CI leg added and green (PR #3, merged to `main`) — job `bridge` at `ci.yml:574-586`, no**

      `paths` filter, so it runs on every push and PR; its exact command re-run 2026-08-10 gives **60
      tests, 0 failures**. Two honest qualifiers: this phase's CI paragraph specifies `BRO_ENV=ci` and
      the job does not set it (nothing in `bridge/` reads it, so it is cosmetic drift, not a hole); and
      the job **runs**, and since 2026-08-17 it is a **required** check — `main` carries branch protection: **33 required status checks**, `enforce_admins`, `strict`, linear history, no force pushes, no deletions (enabled 2026-08-17 by Owner decision after the seventh audit's `G-01`; widened from 12 to 33 on 2026-08-18 after the eighth audit's `H-01`). Exactly two pull-request jobs are excluded, each for a measured reason: `AI-surface inventory gate` (a `paths:` filter means it does not report on unrelated PRs, and GitHub treats a skipped required context as pending) and `Trust provisioning (windows-latest)` (`T-023`, three recorded occurrences). *(This line said `main` had no branch protection until the eighth audit's `H-04`.)* Which is the
      Owner's to enable and is tracked in `docs/OWNER_ACTION_REQUIRED.md`.

**Chat receipt badge + governed-provider status control shipped in the cockpit UI — **shipped and**

      reachable, and it can only ever paint a demonstration badge.** The badge renders at
      `Conversations.tsx:535/548` on the `chat` route, and the control at `Settings.tsx:282-293`; 19
      vitest cases pass. But the badge is driven by `MESSAGE_RECEIPT_PROJECTION` (`core/src/repo.rs:966`),
      and `trusted_verified` / `development_untrusted` need an accepted row in
      `receipt_verification_attempts`, which needs the round-trip row above — impossible today. The only
      badge a user can actually produce is `demonstration_verified`, via `demonstration_verified_reply`
      (`commands.rs:2454`), which is `#[cfg(windows)]`-only and needs `BROPS_SELFTEST_MODEL_CMD`. Also
      short of the UI/UX spec: it names four badge states (`pending` shimmer / `verified` /
      `unverified-blocked` / `error`) and `receiptBadge` returns three tones or `null` — **no `pending`
      and no `blocked`/`error` state ships**. Shipped as **transport**
      (PR #8); control **amended 2026-08-09** to the read-only three-state row the UI/UX section now
      specifies (`default`/`on`/`blocked`, focusable, `aria-disabled`, inert), because a webview-writable
      provider switch contradicts this phase's own "Desktop never holds lease/key/env" gate and could not
      change an outcome anyway.


## Phase 1 — Task checklist

**T-003 slice 1 — contract + adapter + tests (verified **10/10**, PR #3, commit `5be8d95`). *Same**

      fact as the adapter row in the Definition of Done above; kept because it is the task ledger, but it
      is not a second delivery.*

**Slice 2 — prove one governed round-trip (adapter ↔ real supervisor), record evidence — **done**

      2026-08-12, on a real Linux runner, and worded deliberately.** `engine/ci/live/run_ladder_turn.sh`
      + CI job `ladder-governed-turn` drive ONE `bridge.governed-turn-submit.v1` frame through the real
      one-shot sidecar from a seventh `brops-sidecar` principal, against the real
      `OpenService`/`StagingService`/`EvidenceRequestService`/`OutputReadService` and the real §5
      `AcceptanceDriver`, reaching the **real §6.1 step-5 contained execution** — privileged recorder →
      setuid launcher → contained executor, six uids, `caps_all_zero`, `no_new_privs`. No stand-in.
      Verbatim from run 31606043144 at `59dc394`:
      `RESULT: ladder-round-trip ok=true reason=none attempt=58d4358… output_sha256=8e30d8db…`,
      `POSITIVE: GREEN — one submit frame became one §4.6 frame whose envelope verifies`, and
      `NEGATIVE: GREEN — refused with digest_mismatch, and the harness exited non-zero (1)`.
      **The negative half is not decoration:** every run drives the same verifier over an artifact the
      challenge never committed and requires a non-zero exit naming `digest_mismatch`, because both of
      this repository's PowerShell proofs were found unable to report PASS at all, through three audit
      rounds. `ladder_evidence.py` records the §4.6 frame, the §4.9 envelope, the digests and the
      `SO_PEERCRED` uid of every hop, and uploads them as a CI artifact.
      **What this box does NOT say.** It does not say the shipped app takes this path — it does not.
      `governed_turn_submit_prepared` has a transport and **no caller**, `ChainExecutor` still drives
      direct AF_UNIX, and `governed_verification_unconfigured` still returns `Some(...)`
      unconditionally. This is the **adapter ↔ supervisor** round trip, proven; the product's own path
      is the open row above it.

**Bridge CI leg added to the unified workflow (PR #3, merged `41cf4ff`) — job `bridge`, one of**

      `ci.yml`'s 19 jobs. *Same fact as the Bridge-CI row above.*

**Slice 2 — ship the chat verified-receipt badge + Settings governed-provider control (per UI/UX**

      above) — **transport** (PR #8); control amended to read-only three-state 2026-08-09. *Same fact as
      the badge row above.* The three states are honestly derived from a real `ai_status`, and every
      install shows `default`, because `on`/`blocked` need a governed provider no turn can use.


## Phase 1 — done 2026-08-12, on a real Linux runner

**Slice 3 — the §4.10(f) chunked output pull — **done 2026-08-12, on a real Linux runner.****

      Delta-streaming stays DESCOPED (a governed turn is buffered by construction: the desktop's
      authority is a signature over the whole output). What this row tracked was the pull, and it is
      now driven end to end by `ladder-governed-turn`. Verbatim from run 31621209556 at `5090e53`:
      `pull=ok chunks=1 served_to_uid=5003 negatives=digest_mismatch,length_mismatch,`
      `refused:stream_binding_mismatch,refused:stream_unknown` and `PULL: GREEN`.
      The supervisor hop is `governed_output_read.py` + `governed_output_stream.py` + the
      `governed_output_streams` DDL, minted from `complete-run`; the desktop hop is the
      `bridge.governed-turn-output-read.v1` branch and `brops_core::governed_output_pull`, driven by
      `core/src/bin/ladder_output_pull.rs`. The uncalled `core/src/governed_output_stream.rs` (deleted 2026-08-10, see this cell) ladder
      was **deleted** rather than wired — its table diverged from the design it cited, and its
      `create_schema` ran one line before the canonical one with `CREATE TABLE IF NOT EXISTS`, which
      would have made the canonical DDL a silent no-op.
      **Four negatives are driven every run and refused by name**, plus a sign-flip control that
      requires the positive to report `digest_mismatch` — because both of this repository's
      PowerShell proofs were found unable to report PASS at all, through three audit rounds.
      **Three limits, stated in the box rather than found later.** The live pull is **single-chunk**:
      the executor's output is a fixed 322 bytes, so `seq` never exceeds 0 on the runner; a forced
      400000-byte output gives 3 reads locally, so the striding loop is proven but not by CI. The
      driver runs as the script's **root** orchestrator (it must `sudo -u` the sidecar), so it proves
      nothing about who may read the store — that the bytes came through the egress rests entirely on
      the supervisor's `SO_PEERCRED` hop log, which `check_pull` refuses to proceed without. And this
      is a **CI proof, not a product path**: the shipped broker still reads the recorder's output with
      `std::fs::read(&report_path)` and never touches this egress. That is the open row above.

**Update `PROJECT_STATE.md` + this roadmap when each slice lands. **Standing — never permanently**

      checked**, and it is the row whose neglect produced eleven corrections on 2026-08-14: five
      documents claiming the Builder could not merge while it merged, an audit figure (`122`) that
      appears in no audit report, `SCHEMA_VERSION` two migrations behind, and two canonical design
      docs disagreeing about whether three merged slices exist. Most recently satisfied for the
      **third independent audit** cycle — report committed, nine claims promoted, three stale rows
      corrected, five findings answered. Detail: **`T-018`** in [`TASKS.md`](./TASKS.md).


## Phase 2 — `approvals` ✔ Հաստատումներ (Approval gate)

****`approvals` ✔ Հաստատումներ (Approval gate).** Components: approval queue (`apQueue`), decision pill**

  (`apPill`), grant/deny/escalate actions (`apGrant`/`apDeny`/`apEsc`), live gate state (`apGate`),
  countdown clock (`apClock`). States: `default`(queue), `loading`(skeleton rows), `empty`("no pending
  approvals" HY), `error`(engine unreachable), `blocked`(owner not authenticated). Motion: new item
  `reveal`+`--stagger`; grant → mint `stamp`, deny → danger `strike`. Keyboard: `↑/↓` select, `g` grant,
  `d` deny, `e` escalate, `Enter` confirm, `Esc` cancel; all actions confirm before committing.
  A11y: queue is a `role=list`, each item `role=listitem`, actions labeled HY, verdict announced via
  `aria-live`. Data: engine approval queue (read) + approval-request POST.


## Phase 2 — `decisions` ⚖ Որոշումներ (Decision ledger)

****`decisions` ⚖ Որոշումներ (Decision ledger).** Components: chamber view (`chamber`), append-only ledger**

  (`ledger`), evidence viewer (`chEvidence`), reweigh control (`chReweigh`). States incl. `empty`(no
  decisions), `blocked`(evidence sealed). Motion: ledger rows `reveal`; new decision `stamp`. Keyboard:
  arrow-navigate ledger, `Enter` opens evidence. A11y: ledger `role=log`, immutable rows marked
  `aria-readonly`. Data: engine decision ledger + evidence chain (read-only).


## Phase 2 — `security` ⛨ Անվտանգություն (Evidence chain / posture)

****`security` ⛨ Անվտանգություն (Evidence chain / posture).** Components: chain integrity view, control-plane**

  digest status, residual-item tracker (O-1..O-5), key/lease registry status. States: `default`,
  `loading`, `error`(chain break → danger), `blocked`. Motion: integrity pulse (`sigbreathe`) — **bound to
  state, per the Owner decision of 2026-08-15**: the pulse runs while a chain read is genuinely in flight,
  takes the faster danger cadence on a break, and is **still** in `blocked`, where nothing is established.
  Motion depicts what is happening, never what is hoped. Keyboard:
  sectioned tab order. A11y: integrity status is a live region; a broken chain is announced. Data: engine
  evidence chain + protected-control-plane digest (read-only).


## Phase 2 — `notifications` ◈ Ազդանշաններ (Signals)

****`notifications` ◈ Ազդանշաններ (Signals).** Components: signal feed, filter chips, per-signal action.**

  States incl. `empty`("all clear" HY). Motion: incoming signal `reveal`; severity color from semantic
  tokens. Keyboard: `↑/↓` feed, `Enter` open, `x` dismiss. A11y: `role=feed`, `aria-live=polite` for new
  signals, severity in the accessible name. Data: engine governance events + desktop notification store.


## Phase 3 — App shell

****App shell.** Components: brand (`.brand` `Br·PS` live mark), `#nav` (22-entry icon+label rail), `.stage`**

  main region, `cmd-dock`. Responsive: rail collapses to icons <1024; stage single-column narrow. States:
  route `loading`/`error`(page failed to mount)/`blocked`. Motion: page `--enter` reveal, nav active
  `--fast`. Keyboard: `⌘K` opens dock, `1..9`/typed route jumps, `Tab` cycles rail, focus-visible rings.
  A11y: `nav` labeled HY "Ուղի/Նավիգացիա", `main tabindex=-1` receives focus on route change, current
  page `aria-current=page`.


## Phase 3 — `home` ⌂ Ամփոփում (Overview)

****`home` ⌂ Ամփոփում (Overview).** Components: summary tiles (system pulse, pending approvals count,**

  recent turns, quick actions). States incl. `empty`(first-run welcome HY + "Talk to Bro" CTA). Motion:
  tiles `reveal`+`--stagger`. Keyboard: tiles are links, arrow-navigable. Data: aggregates engine status
  + desktop product state.


## Phase 3 — `chat` ✦ Զրույց Bro-ի հետ (governed)

****`chat` ✦ Զրույց Bro-ի հետ (governed).** Components: thread (`thread`), composer (`composer`/`compInput`),**

  send (`sendBtn`), mention pop (`mentionPop`), context rail (`ctx-rail`: skill/confidence/recalls), the
  Phase-1 **verified-receipt badge** per turn. States: `default`, `loading`(turn running — `pwThink`
  pulse), `empty`(first message hint), `error`(turn failed), `blocked`(governed provider on but sidecar
  down → fail-closed reason, **no result**). Motion: message `emit`/`stream`; badge flip on verify.
  Keyboard: `Enter` send, `Shift+Enter` newline, `@` mention, `↑` edit last, `Esc` cancel run. A11y:
  thread `role=log aria-live=polite`, composer labeled, badge announces verification. Data: desktop
  SQLite conversation + bridge governed turn (receipt id + `verified`).


## Phase 3 — `settings` ⚙ Կարգավորումներ

****`settings` ⚙ Կարգավորումներ.** Components: sections (provider, appearance/theme, governance sidecar**

  config, about `MENQ OS v0.9`). Includes the Phase-1 governed-provider toggle. States incl. `blocked`
  (sidecar misconfigured → guidance). Keyboard: sectioned tab order, toggles `Space`. A11y: each control
  labeled + described; theme change respects `prefers-reduced-motion`. Data: desktop settings store.


## Phase 4 — Component library

****Component library.** Surfaces (`surface`/`cut`/`hud`/`soft`), marks (`mark live`), pills, tiles,**

  data tables, skeleton (`reveal`+`--stagger`), toast/inline-alert, modal/drawer, rails (`ctx-rail`/
  `cmd-rail`/`grp-rail`). Each component ships all §D states + keyboard + aria + reduced-motion variants
  and a usage doc. This is where the per-page §D template becomes enforceable via shared primitives.


## Phase 4 — `activity` ♥ Զարկերակ

****`activity` ♥ Զարկերակ.** Components: ECG strip (`paBeatline`/`buildECG`), vitals readout (system pulse,**

  avg response, network load, error rate), blip markers per event, freeze/plot/sweep controls
  (`paFreeze`/`paPlot`/`paSweep`), core panel (`paCore`). States: `default`(live), `loading`(strip
  skeleton), `empty`(no activity yet), `error`(stream lost), `blocked`. Motion: `nowPulse` heartbeat,
  integer count-up on vitals, blips `reveal`. Keyboard: `Space` freeze, `←/→` scrub blips, `Enter`
  open a beat's detail. A11y: strip has a text-equivalent live region ("system pulse 70/min"); blips are
  buttons with HY labels. Data: engine runtime telemetry (live).


## Phase 4 — `analytics` ◈ Վերլուծություն

****`analytics` ◈ Վերլուծություն.** Components: live deck (`anLive`/`anDeck`), distribution-by-node**

  (`anPlot`/`anCap`/`anTotal`), autonomy split, channel split, scrubber (`anScrub`). States incl. `empty`
  (no data range) and `error`. Motion: chart series `--enter`, scrub `--fast`. Keyboard: scrubber is a
  slider (`role=slider`, arrows), legend toggles focusable. A11y: each chart has an accessible summary +
  data table fallback; color is never the only signal (use §dataviz patterns). Data: engine analytics
  aggregates.


## Phase 4 — `library` ❑ Դարան

****`library` ❑ Դարան.** Components: the component/prompt/pattern catalog with live previews, search,**

  filter chips. States incl. `empty`("nothing saved") vs "filtered to nothing". Keyboard: `/` focus
  search, arrow-navigate results, `Enter` open. A11y: results `role=list`, previews labeled. Data:
  desktop library store (product) + engine skill registry (read).


## Phase 5 — `memory` ❖ Հիշողություն

****`memory` ❖ Հիշողություն.** Components: memory list (typed: user/feedback/project/reference), detail,**

  add/edit, link graph (`[[name]]` links), confidence. States incl. `empty`("Bro has no memories yet")
  and `blocked`(a memory that references sealed evidence). Keyboard: `/` search, `n` new, `Enter` open,
  `e` edit. A11y: list `role=list`; graph has a text-list fallback. Data: desktop memory store.


## Phase 5 — `knowledge` ⁂ Գիտելիք

****`knowledge` ⁂ Գիտելիք.** Components: knowledge base (collections, articles), editor, citation view,**

  search. States incl. `empty` vs `filtered-empty`, `error`. Keyboard: full editor keymap, `/` search.
  A11y: article `role=article`, headings structured. Data: desktop knowledge store.


## Phase 5 — `research` ⌖ Հետազոտում

****`research` ⌖ Հետազոտում.** Components: research query, run status (governed — with **verified-receipt**

  badge**), sources list, synthesis, save-to-knowledge. States: `default`, `loading`(run in progress —
  pulse), `empty`(no runs), `error`(run failed), `blocked`(governed provider off/sidecar down → no
  result). Keyboard: `Enter` run, `Esc` cancel, arrow-navigate sources. A11y: run status live region;
  each source labeled + linked. Data: bridge governed research turn → receipt; results saved to knowledge.


## Phase 5 — `files` ▤ Ֆայլեր

****`files` ▤ Ֆայլեր.** Components: file index (`frows`/`fCount`), query (`fQuery`/`fHits`/`fChips`),**

  plane/preview (`plane`), tray, per-file guard state (open/read/sealed). States incl. `empty`(no files),
  `blocked`(sealed file → cannot open; shows guard reason). Keyboard: `/` query, arrows navigate,
  `Enter` preview, `Space` select. A11y: index `role=grid` or `list`; guard state in accessible name.
  Data: desktop file store + engine scope guard for wall-crossing content.


## Phase 6 — `agents` ⬡ Կենդանի Ցանց

****`agents` ⬡ Կենդանի Ցանց.** Components: agent lattice (`lattice`/`latStage`/`latLinks`), dossier**

  (`dossier`), per-agent state (idle/flowing/throttled/blocked/completed), owner + role. States: live
  lattice, `loading`(building), `empty`(no active agents), `error`(link lost), `blocked`. Motion: link
  `stream`/`emit`, node state color from semantic tokens, `suspend`/`interrupt` on throttle/block.
  Keyboard: arrow-navigate nodes, `Enter` open dossier, `Esc` close. A11y: lattice has a node **list**
  fallback (`role=list`), each node labeled "agent · role · state"; state announced on change. Data:
  engine supervisor live pack state.


## Phase 6 — `command` ❖ Հրամանի Միջուկ

****`command` ❖ Հրամանի Միջուկ.** Components: command dock/reactor (`cmdForm`/`cmdInput`/`reactor`),**

  active dispatch (`cmdActive`/`cmdStatePill`), trace (`cmdTrace`), assigned team (`cmdAssigned`),
  chains/recall/linked/confidence rails. States: `default`, `loading`(dispatch running), `empty`(no
  active command), `error`, `blocked`(dispatch denied by wall → reason). Motion: reactor `sigbreathe`,
  dispatch `emit`. Keyboard: `⌘K`/`Enter` dispatch, `Esc` abort, arrow-navigate trace. A11y: trace
  `role=log aria-live`, state pill in accessible name. Data: engine dispatch + per-builder receipts.


## Phase 6 — `tasks` ◈ Առաքելություն

****`tasks` ◈ Առաքելություն.** Components: mission board (states: todo/in-progress/review/done/blocked),**

  claim, assignment, evidence link. States incl. `empty`("no missions") and `blocked`. Keyboard: board
  arrow-nav, `Enter` open, `c` claim. A11y: board columns `role=list`, cards labeled. Data: desktop
  mission store mirrored from engine task contracts.


## Phase 6 — `projects` ❖ Հոսքեր

****`projects` ❖ Հոսքեր.** Components: flow view (pipelines of tasks), per-flow status, ownership. States**

  incl. `empty` and `error`. Keyboard: arrow-navigate flows, `Enter` open. A11y: flow graph has a
  step-list fallback. Data: desktop flow store + engine task lifecycle.


## Phase 7 — `group` ⧉ Համագործակցության Սրահ

****`group` ⧉ Համագործակցության Սրահ.** Components: room header (`grpTitle`/`grpSub`/`grpElapsed`/**

  `grpPill`), shared thread (`grpLog`), session/participants (`grpSess`), loom/handoff view (`grpLoom`),
  composer with mentions, per-agent verified-receipt badges, consensus readout (participants/handoffs/
  messages/consensus %). States: `default`(active room), `loading`(joining), `empty`(new room hint),
  `error`(participant/turn failed), `blocked`(an agent turn denied by the wall → shown inline, no result).
  Motion: message `emit`/`stream`, handoff `--enter`, consensus meter `--slow`. Keyboard: `Enter` send,
  `@` mention participant, `↑` edit, `Esc` leave, arrow-navigate log. A11y: thread `role=log aria-live=
  polite`, each message names its author + governance state; consensus meter has a text value. Data:
  desktop room store + bridge governed turns per agent participant.


## Phase 8 — `automations` ⇶ Ավտոմատներ

****`automations` ⇶ Ավտոմատներ.** Components: automation index (`arows`/`aCount`/`afilter`), schematic/**

  manifold view (`manifold`/`schem`), per-automation state (idle/flowing/throttled/blocked/completed),
  scheduler (`auSched`), owner. States: `default`(list), `loading`, `empty`("no automations yet" + create
  CTA), `error`, `blocked`(automation denied by wall / guard tripped → reason + how to fix). Motion:
  flow `stream`, state color from tokens, `suspend` on throttle. Keyboard: `n` new, `/` filter, arrow-nav,
  `Enter` open, `Space` enable/disable. A11y: index `role=list`, state in accessible name; the schematic
  has a step-list fallback. Data: desktop automation store → governed dispatch → receipts.


## Phase 8 — `calendar` ▦ Օրացույց

****`calendar` ▦ Օրացույց.** Components: day grid (`daygrid`/`calGrid`), now-line (`calNow`), agenda**

  (`calAgenda`), clock (`calClock`), playhead (`calPlay`/`calPhTime`). States incl. `empty`(no scheduled
  runs), `error`. Motion: now-line `nowPulse`, agenda `reveal`. Keyboard: arrow-navigate days/slots,
  `Enter` open, `t` today. A11y: grid `role=grid`, slots labeled with date+time+run; agenda `role=list`.
  Data: desktop schedule + run history (with receipt ids).


## Phase 9 — `integrations` ✦ Ինտեգրումներ

****`integrations` ✦ Ինտեգրումներ.** Components: connector catalog (available/connected), per-connector**

  config, health/status, inbound-trigger + outbound-sink mapping, auth handoff (to operator/engine).
  States: `default`(list), `loading`, `empty`("no integrations" + browse CTA), `error`(connector
  unhealthy), `blocked`(auth not provisioned / would run ungoverned → reason + how to provision). Motion:
  connect `--enter`, health pulse. Keyboard: `/` search catalog, `Enter` open, `Space` enable/disable.
  A11y: catalog `role=list`, health/status in accessible name; auth handoff clearly labeled. Data:
  desktop connector registry + engine/operator secret + governed inbound/outbound.


## Phase 10 — UI/UX work

**Every page passes a production a11y audit (keyboard-complete, AA contrast, live regions, HY SR labels)**

  and a performance budget (first-paint, interaction latency, reduced-motion parity).


## Phase 10 — Definition of Done

**`contracts/` finalized as the single source; duplicates deleted; versioned. — **most of it is**

      done and the box stays UNTICKED on purpose (2026-08-29, ninth audit `I-13`).** `contracts/` holds
      the five cross-half schemas as the **source**, `contracts/index.json` carries each one's version as a
      JSON Pointer into its own `const`, and `tools/check_contracts_single_source.py` (17 tests, in CI)
      makes drift, a one-sided version bump, an unclassified new engine schema and a stray third copy all
      RED. **What is not true is the box's own words:** *duplicates deleted*. Two copies of five files
      still exist — drift is impossible, deletion has not happened — and ticking on a paraphrase is how a
      checkbox stops meaning anything. The remaining move is an audited **engine** change (root-relative
      loaders; `engine/` is a subtree of `menqstudio/Bro`), **not** the production gate.

**Every page passes production a11y + performance gates; no placeholder copy. — **DONE**

      2026-08-29.** The word this row waited on was `production`, and it is answered: axe now runs in
      real Chromium with the app's stylesheet graph loaded, `color-contrast` enabled, over 23 pages ×
      2 states × **2 themes** plus the shell and the ⌘K palette — 98 checks. It found **eleven**
      defects nothing here could see, ten of them in the light theme, and all eleven are fixed. The
      history below is kept because it is what the row used to say. — *three of the
      four halves are done and measured (2026-08-29); the box stays UNTICKED for the fourth.**
      *a11y:* `pages.a11y.spec.tsx` mounts all **23** route components under axe and the job is green.
      *performance:* every route now has a ceiling — `perf-budget.json` gained a `routes` section and
      `check_bundle_budget.py` enforces it bidirectionally. Until this landed the gate measured the
      **entry and nothing else**: 23 lazily-loaded chunks, **256.7 KB gzip**, no ceiling at all.
      *placeholder copy:* zero hits for lorem/TODO/TBD/coming-soon across the locale and
      `*.strings.ts` files. **What is NOT true is the word `production` in the a11y half:** axe runs
      in **jsdom**, not against the built app. The `computed-style (real Chromium)` workflow already
      has the browser; pointing axe at it is what would finish this row.


## Phase 10 — Task checklist

**`contracts/` final dedupe (lease/approval/task-contract/mode-grant) + versioning. — **versioning is**

      done, the dedupe is not** (see the Definition-of-Done row above). Note also that `approval` names a
      schema that **does not exist anywhere in the tree**: the approval path across the wall exists on
      neither side and is tracked as `T-021`. This row cannot be finished as written until that is built.

**Production a11y + performance gate pass over all 22 pages; real HY copy. — **DONE 2026-08-29**,**

      see the Definition-of-Done row above. — *the performance
      half is done (per-route budgets, 2026-08-29) and `real HY copy` is measured and true:** 238
      locale keys with **2** identical to English (`app.name` = `BroPS`, `chat.you` = `gev`, both
      proper nouns) and **1 170** en/hy pairs across `*.strings.ts` with **7** identical, every one an
      identifier (`GitHub`, `desktop-owner`, `local-scheduler`, cron syntax, `DIGEST`). The row stays
      unticked for the same single reason as the Definition-of-Done row above: axe runs in jsdom.

****Lease** — a scoped, single-use Ed25519-signed execution grant, issued **into a builder**, never held**

  by the conductor (the desktop is a conductor).

****Verified receipt** — a signed execution receipt confirmed by an injected verifier; **no verified**

  receipt ⇒ no result** (the product-wide invariant).

****`blocked` state** — the UI state when an action is denied by the wall; shows the verdict reason and the**

  lawful next step. Mandatory wherever an action crosses the wall.

****Option 1 / Option 2 / T-005** — subtree+skip-guard (now) vs submodule+native worktree fix (audited,**

  Phase 10) for the engine root-model.

****O-1..O-5** — residual/deferred engine security items (bytecode-shadow, audit-head anchor, conductor**

  session token, control-room actor, evidence high-water), closed in Phase 10.
