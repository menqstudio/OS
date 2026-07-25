# NEXT_CHAT — definitive handoff · վերջնական handoff

> **New Claude or ChatGPT session:** this file + the canonical files it points to are
> everything you need. GitHub (`menqstudio/OS`) is the single source of truth — this
> chat's predecessors are gone; do not rely on any prior chat memory. Read this in
> full, then follow [`START_HERE.md`](./START_HERE.md) and the machine-readable
> [`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json).
>
> **Նոր session (Claude կամ ChatGPT):** այս ֆայլը + իր ցույց տված canonical ֆայլերը
> բավական են։ GitHub-ն ա միակ ճշմարտության աղբյուրը; հին chat-երին մի ապավինիր։

**Last updated:** 2026-07-25 · **Maintained by:** the implementer session, in the same commit as any state change.

---

## 0. ⏭️ RESUME HERE — self-contained handoff for a brand-new GPT/Claude session

*(You have NO prior chat memory and need none. Everything below is re-derivable from GitHub. Read §3 for the full detail; this is the at-a-glance resume.)*

- **Repo / branch / PR:** `menqstudio/OS` · branch `feat/wave-3b1-isolated-signer` · **PR #31** (OPEN, **NOT merged**).
- **Exact current HEAD:** the **rev-23 (CONSOLIDATED)** design-lock candidate is committed locally and pushed by Claude this cycle (push/PR-write are Owner-delegated to Claude, §3.3). The immediately-preceding **rev-22** design was Architect-reviewed at the live tip **`47033511bbb44bf4ca174a34e3c92fd4780c069c`** (exact-head CI **#129** 8/8 SUCCESS; the rev-22 design content is at `a84ee12` — `4703351` was a coordination-only commit, so the rev-22 normative design was unchanged — CI GREEN ≠ design GREEN). **Resolve the live tip yourself:** `gh pr view 31 --json headRefOid -q .headRefOid` (or `git rev-parse HEAD` after `git pull`), then query GitHub Checks for THAT exact SHA (`gh api repos/menqstudio/OS/commits/<sha>/check-runs`). **GitHub Checks is the CI authority — never trust a hardcoded run number, and CI GREEN ≠ design/Architect GREEN.**
- **Where it stands:** **3b-1A** = ✅ Architect Code GREEN (`dffd164`). **3b-1B** = ❌ Architect **Design RED** — the Architect reviewed **rev 22** @ `4703351` (exact-head CI **#129** 8/8 SUCCESS; CI GREEN ≠ design GREEN), **CONFIRMED CLOSED** the rev-21 `PreparedGovernedTurnV1B`-lifecycle P0, and returned RED with **1 P0 · 1 P1** on the same command's contract (**P0-1** `governed_turn_execute` omitted `conversation_id`/`run_id` and wrongly took system/history/workspace/install/generation_config from the renderer; **P1-1** the transport-failure "nonce not consumed / retryable" claim isn't durable); **rev 23** closes both in place (§4.10(g), §6.1) via a read-only real-code investigation + one integrator + a fresh independent red-team. rev 23 is a **PROPOSED** design-GREEN candidate — **NOT Architect-GREEN.** **No 3b-1B / 3b-2 / 3b-3 code exists.**
- **Your next action:** rev 23 is pushed by Claude + the PR #31 body refreshed; submit **rev 23** (`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`, the single normative source) for Architect design review **at the exact resolved HEAD**. If RED → run the fan-out/integrator/red-team loop and revise in place; if GREEN → only then write 3b-1B code. Do **not** merge PR #31, do **not** start 3b-2/3b-3, do **not** claim Architect-GREEN, do **not** touch `NoTrustedManifest` or expose production "Verified". **Push/PR-write are Owner-delegated to Claude (see §3.3); merge + final design approval remain the Owner's (Gev). The AI never merges.**
- **Read order:** [`START_HERE.md`](./START_HERE.md) → **this file §3** (authoritative current-state block) → [`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json) → the design chain [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md) + [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md). `PROJECT_STATE.md` + `TASKS.md` (T-017) carry the same state + full audit history.
- **One-line instruction that fully bootstraps you:** *"Go to menqstudio/OS, open START_HERE.md on the current PR #31 head, follow the canonical startup chain completely, verify the exact GitHub HEAD and GitHub Checks, and continue autonomously from the recorded next action. GitHub is the only source of truth; do not use prior chat memory."*

---

## 1. Identity

- **Repository:** `menqstudio/OS` — a governed AI-operations desktop: a safe cockpit (`apps/desktop/`, Tauri) on a contained governance engine (`engine/`, Python). Every AI action flows `lease → gate → sandbox → signed receipt`; no direct ungoverned model execution.
- **Owner:** 👑 **Gev** (`menqstudio`, ohanyan.88@gmail.com). Armenian-speaking — reply in Armenian by default; English only for code/identifiers/commands.
- **Roles ([`OWNERS.md`](./OWNERS.md)):**
  - 🔨 **Claude** — Builder / Implementer. Writes code, tests, commits, opens PRs. **Cannot push or merge** (credential-isolated); prepares commits + hands the exact `git push` / `gh` commands to the Owner.
  - 📐 **ChatGPT** — Architect / **zero-trust auditor**. Reviews each security PR + each design against the **exact HEAD** and returns GREEN / YELLOW / RED. **The audit is the gate.**
  - 👑 **Gev** — Owner / final approver, pusher & merger.

## 2. Single source of truth + mandatory startup

**GitHub is canonical. A textual claim ("I read it", "it's done", "GREEN") is not evidence — verify against the repo + exact-head CI.** Startup read order (also in [`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json)):

1. `git pull` and confirm the exact HEAD.
2. **This file** (`NEXT_CHAT.md`) — exact current state (§3).
3. [`CLAUDE.md`](./CLAUDE.md) — how to work, environment gotchas, security discipline.
4. [`PROJECT_STATE.md`](./PROJECT_STATE.md) — live status (who's on what, blockers).
5. [`TASKS.md`](./TASKS.md) — the task board; **claim your task before touching anything**.
6. [`OWNERS.md`](./OWNERS.md) — roles.
7. [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) + [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md) — design + canonical execution plan.
8. Wave 3 security work (the active track): [`docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) (ratified), [`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md) (Wave 3b design, Architect-GREEN), [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md) (3b-1 implementation index — defers to the addendum), [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md) (**the single normative source for all 3b-1B contracts** — rev 23, **design RED, not yet GREEN**), and [`apps/desktop/SECURITY.md`](./apps/desktop/SECURITY.md).

---

## 3. CURRENT STATE — the authoritative block (read this before acting)

### 3.1 Repository / branch / PR / HEADs

- **Repository:** `menqstudio/OS` · **Active branch:** `feat/wave-3b1-isolated-signer` · **PR:** **#31** (OPEN, **NOT merged**).
- **Branch HEAD:** the tip of `feat/wave-3b1-isolated-signer` — the substantive content is the **3b-1B addendum (currently rev 23 — CONSOLIDATED)** plus the documentation updates; the exact tip SHA moves with each doc commit.
- **Exact current HEAD (how to resolve — GitHub is authoritative):** this doc is committed *inside* the tip, so it cannot name its own commit hash. Resolve the exact current HEAD from GitHub, not from memory: **`gh pr view 31 --json headRefOid -q .headRefOid`** (the PR head SHA) or **`git rev-parse HEAD`** after `git pull`. Then **query GitHub Checks for THAT exact SHA** (`gh api repos/menqstudio/OS/commits/<sha>/check-runs`) for the real CI — **never trust a hardcoded run number.** (Architect-reviewed HEADs, historical: rev 13 @ `415e3fd` — CI #117, rev 14 @ `18a467d` — CI #118, rev 15 @ `848f2a6` — CI #119, rev 16 @ `953f738` — CI #120, rev 17 @ `d8a6510c12192daef9053f74d674cfdb80044413` — exact-head CI #121 SUCCESS 8/8, rev 18 @ `89d0df4c7211c97c85c582090cea05c5da02bc42` — exact-head CI #124 SUCCESS 8/8 (Architect-reviewed → Design RED, 1 P0 + 2 P1), rev 19 @ `8d3451e28b542f290cc9b7c981c4636aec3dc54b` — exact-head CI #125 SUCCESS 8/8 (Architect-reviewed → rev-18 P0+P1 CONFIRMED CLOSED; new Design RED, 1 P0 · 0 P1), rev 20 @ `85240edf9bd66673d9f3e8f94e732aab155273f9` — exact-head CI #126 (mandatory gates SUCCESS; Architect-reviewed → rev-19 nonce/hash P0 CONFIRMED CLOSED; new Design RED, 1 P0 · 0 P1), rev 21 @ `a05629b7179e9ee87f315e5ac8452e88c8f4f89a` — exact-head CI #127 (mandatory gates SUCCESS; Architect-reviewed → rev-20 hash-source P0 CONFIRMED CLOSED; new Design RED, 1 P0 · 0 P1), rev 22 design @ `a84ee12dd8b7033729e8c7aa4628b18e23e02939` (live tip `4703351` was coordination-only) — exact-head CI #129 8/8 GREEN (Architect-reviewed → rev-21 lifecycle P0 CONFIRMED CLOSED; new Design RED, 1 P0 · 1 P1). The rev-23 candidate is pushed by Claude; its HEAD supersedes `4703351` — resolve the live tip as above and re-query GitHub Checks for it.)
- **Base `main`:** `df3c0aca80cbe4a5537a9fdd53e16e26541c9c19` (Wave 3b-0 design merged, PR #30).
- The branch contains: **3b-1A code** (Architect-GREEN, §3.2) + the **3b-1 implementation index** (`WAVE_3B1_EXECUTION_BINDING_MAP.md`, now an index that defers to the addendum) + the **3b-1B design-lock addendum** (**rev 23**, design RED, §3.3 — the single normative source for all 3b-1B contracts). It carries **no 3b-1B, 3b-2, or 3b-3 code.**

### 3.2 Wave 3b-1A — ✅ Architect Code GREEN (do NOT reopen without new code evidence)

- **Approved code HEAD: `dffd1644e9882f6a1dab285c5e6bc6fc76d2c061`.** The GREEN remains valid through the later documentation-only HEADs (docs did not touch 3b-1A code).
- **Machine evidence:** every exact-head CI run through the rev-17 HEAD (`d8a6510`, run **#121**) has been **fully GREEN** — all **8** jobs, including both mandatory gates **`Engine · governance runtime`** and **`Engine · signer isolation proof`**. The Linux isolation job proves a **positive supervisor→signer signed round-trip BEFORE** the four same-login-user **denial** proofs, using dedicated service users. Docs/addendum commits do not touch 3b-1A code, so the `dffd164` GREEN stands. **Query GitHub Checks for the CURRENT HEAD's run** (do not trust a hardcoded number). **CI GREEN ≠ design GREEN** — the 3b-1B addendum is still design RED (§3.3).
- **What 3b-1A delivered (the isolated signing boundary):** real isolated **signer service** + **supervisor service** over an **ACL'd Unix-domain socket** with **`SO_PEERCRED`** peer enforcement; the **sidecar connects only to the supervisor, never to the signer**; strict **u32-framed IPC**, fixed **256 KiB** frame cap, duplicate-key/unknown-field/UTF-8/canonical-base64url rejection; **no arbitrary attestation/signing oracle** (`produce_sign_request({run_id, execution_attempt_id})` is the only entry); signer **authorization checklist** (identity allow-set, policy-in-force, bundle-digest, timestamp/skew); **forensic-attestation relay** to the desktop; **atomic content-addressed store** publishing; **service-owned socket dirs**; **dedicated service principals**; **shared-store perms** that permit the supervisor→signer path but deny sidecar access; and the **positive-control + four denial** machine proofs. Authoritative `brops_live_runstate.LiveRunStateProvider` validates the **signed** lease + passing receipt + evidence-chain + containment and cross-binds `lease_id`/`receipt_id`.
- **These 3b-1A findings are CLOSED. Do not reopen them without new code evidence.**

### 3.3 Wave 3b-1B — ❌ design RED (design-lock only; NO code written)

- **File:** [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md), now at **rev 23 (CONSOLIDATED)** — **the single normative source for every 3b-1B contract** (artifact matrix §3, exact schemas §4 incl. the control-plane §4.10 + the desktop→sidecar ingress + preparation contract + the one `governed_turn_execute` command + its backend-owned `GovernedTurnExecutionV1B` §4.10(g), ms time model §1, capability profile §2 + challenge-creation channel §2.1 + protocol-versioning §2.2 + store ACL §2.3 + bounded ingress §2.4, durable acceptance state machine §5, atomic order + E2E §6/§6.1, verification §7 + desktop-signatures-only §7.1, authorities §8; revision history in non-normative Appendix A). History: REDs rev 6→…→21 (Architect RED @ `a05629b`, CI #127, 1 P0 · 0 P1) → rev 22 → the Architect **reviewed rev 22 at live tip `4703351` (design content `a84ee12`; exact-head CI #129 8/8 SUCCESS; CI GREEN ≠ design GREEN), CONFIRMED CLOSED the rev-21 `PreparedGovernedTurnV1B`-lifecycle P0, and returned Design RED with 1 P0 · 1 P1 (P0-1 `governed_turn_execute` missing routing identities `conversation_id`/`run_id` + wrongly renderer-sourced system/history/identities; P1-1 non-durable transport-failure retry contract), mandating a read-only real-code investigation + one integrator + a FRESH independent red-team (NOT single-context guessing, NOT a rewrite).** **rev 23 applies both corrections in place; it is NOT yet Architect-reviewed / NOT design-GREEN.** **3b-1B implementation has NOT started.**
- **Owner directive:** 3b-1 was re-scoped into **3b-1A** (isolated signing boundary — DONE/GREEN) + **3b-1B** (authoritative execution→receipt binding: the governed AI turn becomes a `bro_supervisor`-owned supervised execution that atomically emits a **signed** terminal record; **no unsigned run-state JSON may be signing authority**). The 3b-1 map is now a concise index that defers to the addendum: [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md).
- **The two rev-22 → rev-23 findings (closed in place but treat as OPEN until the Architect returns design-GREEN):** *(the rev-18 → … → rev-21 findings — orchestrator ordering, generation_config canonicalization, two-trust-model channel, nonce/`request_sha256` decoupling, generation_config hash-source split, prepared-object lifecycle — are CONFIRMED CLOSED by the Architect; now history in the addendum's non-normative Appendix A.)*
  1. **P0-1 — `governed_turn_execute` was missing routing identities + wrongly renderer-sourced.** rev 22 omitted `conversation_id` (the `receipt_challenges` pre-store FK + the final accepted-output persist need it) and `run_id` (challenge create-pending binds it), and listed `system`/`history`/`workspace_id`/`install_id`/`generation_config` as renderer inputs — but the merged `stream_reply(conversation_id, agent, on_event)` (`commands.rs:793-799`) takes **only** `conversation_id`+`agent` and **resolves** `system`/`history` from the message store (`commands.rs:801-815`) + identities/policy from the `GOVERNED_*` backend constants (`commands.rs:780-787`); there is **no `run_id`** in the frozen path. **rev 23 (§4.10(g), §6.1):** `governed_turn_execute(conversation_id, agent)` takes only those renderer inputs and builds a **backend-owned orchestration object `GovernedTurnExecutionV1B{conversation_id, run_id, task_id, prepared: PreparedGovernedTurnV1B}`** — `run_id`/`task_id`/`request_nonce` backend-generated (`brops_core::id()`/`governed_task_id()`), `system`/`history` resolved from the message store keyed by `conversation_id`, identities/policy from the `GOVERNED_*` constants; the renderer re-sends none of them.
  2. **P1-1 — the transport-failure retry contract was not durable.** rev 22 said a transport failure leaves the nonce **not** consumed so the challenge "may be retried" — but after the command returns the in-process prepared object / challenge document / pending id are gone (nothing durable resumes), and the merged path makes a transport failure a **terminal durable Block**. **rev 23 (§6.1 out-of-band contract):** a transport failure ⇒ `governed_turn_execute` calls `record_pre_verification_block` (`receipt_store.rs:175-208`) which in ONE tx **consumes the `request_nonce`** + writes a durable `blocked` evidence record (`StreamEvent::Blocked{reason}`); the challenge/nonce is **not** retryable (a later receipt on that nonce ⇒ `Replay` Block). The retryable claim is removed; the durable-orchestration-journal alternative is out of scope.
- **Independent red-team (fresh, not the integrator):** one adversarial pass over the full rev-23 working-tree diff + the real repo code; returned **no BLOCKER** — verified against the merged `stream_reply(conversation_id, agent, on_event)` shape (`commands.rs:793-935`, incl. backend-resolved system/history + `GOVERNED_*` constants + no run_id) and `record_pre_verification_block` (`receipt_store.rs:175-208`, nonce-consume + `blocked` record); the frozen 3b-1A/Wave-3a path proven untouched (not in the diff), and `check_coordination` + `check_capabilities` GREEN live. Any lower-severity notes were fixed before commit.
- **Doc-law:** `CLAUDE.md`'s continuous-documentation law holds — **a CI result is not a doc-commit trigger** (GitHub Checks is the CI authority; never commit solely to bump a CI number).
- **Push/PR-write mode (Owner-delegated 2026-07-25):** the Owner (Gev) has **delegated `git push` + `gh pr edit` to Claude** ("all pushes on you as well, I am checking only"); Claude now **commits, pushes, and updates the PR #31 body directly** each cycle, and Gev reviews. **Merge + final design approval remain the Owner's (Gev) per OWNERS; the AI NEVER merges** and never claims Architect/design-GREEN. (The Architect design review itself is still ChatGPT's; the audit is the gate.)
- **Next permitted action:** submit rev 23 @ the pushed HEAD (resolve the live tip from GitHub) for Architect design review; if RED, run the fan-out/integrator/red-team loop, revise in place, commit+push+refresh-PR-body, and re-submit; if GREEN, only then write 3b-1B **code** (after Owner "go").

### 3.4 STOP gates (mandatory — repeat in every status doc)

- `NoTrustedManifest` remains **unchanged**; there is **no production `Verified`** path anywhere.
- **3b-1B code has NOT started. 3b-2 has NOT started. 3b-3 has NOT started.**
- **PR #31 must NOT be merged** until **all** hold: (1) 3b-1B design is Architect-GREEN; (2) 3b-1B implementation is complete; (3) the zero-trust **code** re-audit is GREEN on the exact head; (4) exact-head CI is fully GREEN.

### 3.5 Truth rules (non-negotiable)

- **Repository evidence over chat memory.** Confirm HEAD, CI, and file state from git/GitHub, never from prior chat text.
- **No assumed GREEN.** Only an Architect verdict on the **exact head** is GREEN; **CI GREEN ≠ audit GREEN**.
- **No fabricated execution claims** (SHAs, test counts, verdicts, merges).
- **No local-only handoff** — every decision lands in a canonical repo file, in the same commit, and is pushed.

## 4. Wave 3 slicing map + status

| Slice | What | Status |
|---|---|---|
| Wave 3 design | Receipt Protocol v1 ([`WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md)) | ✅ ratified + merged (PR #23) |
| 3a-1/2/3 | receipt core → storage/atomicity → transport+UI | ✅ DONE + merged (`6c920d0`, `9b214e5`, `8a580028`); fail-closed strict 3a — every governed turn Blocks (`NoTrustedManifest`) |
| 3b-0 | isolated-signer design ([`WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md)) | ✅ Architect design-GREEN (rev 5, `def7711`); merged to `main` (PR #30, `df3c0ac`) |
| **3b-1A** | isolated signing boundary (services + ACL socket + authoritative RunState) | ✅ **Architect Code GREEN** @ `dffd164` (latest exact-head CI 8/8; query GitHub Checks) — §3.2 |
| **3b-1B** | authoritative execution→receipt binding (design-lock) | ❌ **design RED** — Architect RED on the consolidated rev 22 (@ `4703351`, design content `a84ee12`, CI #129 8/8 SUCCESS ≠ design GREEN; rev-21 lifecycle P0 CONFIRMED CLOSED; new 1 P0 · 1 P1 routing-identities + non-durable-retry); **rev 23 CONSOLIDATED proposed, not yet GREEN, no code** — §3.3 |
| 3b-2 | desktop signed key manifest + pinned root + anti-rollback + `key_usage` resolver | ⛔ NOT started (locked in `WAVE_3B_ISOLATED_SIGNER_DESIGN.md` §1.6–1.7, §4.3) |
| 3b-3 | resolver swap + **first production `trusted_verified`** | ⛔ NOT started |

## 5. Merged baseline (history — verify via `git log main`)

- **Wave 1 — provider fail-closed** (T-012, PR #15 `15384cb`); **Wave 2a — webview provenance** (T-013, PR #16 `d85dcba`); **T-010 — capability boundary** (PR #19 `7d537c3`); **T-011 — durable approval + native confirmation** (PR #20/#21, `7638a64`).
- **Wave 3 design rev 4** (PR #23 `35a6ab5`); **Wave 3a slice 1** (T-014, PR #24 `6c920d0`), **slice 2** (T-015, PR #26 `9b214e5`, migration **0014** `SCHEMA_VERSION=14`), **slice 3** (T-016, PR #28 `8a580028`).
- **Wave 3b-0 design** (PR #30 `df3c0ac`). Full per-slice audit history + exact HEADs live in [`TASKS.md`](./TASKS.md) (T-014…T-017 rows) — the authoritative record.
- **Schema on `main`:** migrations through **0014**, `SCHEMA_VERSION = 14`. (The 3b-2 migration `0015` exists only on the separate, un-merged `feat/wave-3b2-manifest-antirollback` branch — NOT on this branch or `main`.)

## 6. Validation commands (this Windows box)

```bash
# Rust data core — run cargo from PowerShell, NOT the Bash tool (Git Bash `link` shadows MSVC). See CLAUDE.md.
cargo test -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml
cargo clippy -p brops-core --all-targets

# Engine (Python) — MUST set BRO_ENV=ci
cd engine && BRO_ENV=ci python -m unittest discover -s tests
cd bridge && BRO_ENV=ci python -m unittest discover -s tests

# Coordination + capability + manifest gates (fail-closed)
python tools/check_coordination.py
python tools/check_capabilities.py
```

- **CI** (`.github/workflows/ci.yml`) runs on `push → main` and on `pull_request`. The mandatory Wave-3b gates are **`Engine · governance runtime`** and **`Engine · signer isolation proof`**. A feature-branch push **without a PR runs no CI**. **CI GREEN is not audit GREEN.**
- The Linux `engine-isolation` job (`engine/ci/isolation_proof.sh` + `gen_isolation_fixture.py` + `brops_isolation_prover.py`) provisions dedicated service users and proves the positive round-trip + the four denials.

## 7. Merge gate & prohibited shortcuts

- A security PR merges **only** after the Architect's zero-trust GREEN on the exact candidate HEAD, then Owner approval + push. **No self-merge.** Claude cannot push/merge.
- No direct work on `main`; every task = branch + PR. Never fabricate a SHA / test result / verdict / file state.
- Do not touch the engine's wall/leases/gates/signatures/control-plane casually — it is an audited security perimeter (`CLAUDE.md`). Engine-only work is a separate track in [`engine/NEXT_CHAT.md`](./engine/NEXT_CHAT.md).

## 8. Handoff rule (keep this file true)

Every approved decision made in a Claude/ChatGPT chat must be written into the canonical repo docs **in the same commit** as the change it authorizes — `NEXT_CHAT.md`, `PROJECT_STATE.md`, `TASKS.md`, and any design/security doc it touches. A new chat must be able to continue correctly from GitHub alone. **The chat is never the record.**
