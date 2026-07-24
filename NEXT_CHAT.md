# NEXT_CHAT — definitive handoff · վերջնական handoff

> **New Claude or ChatGPT session:** this file + the canonical files it points to are
> everything you need. GitHub (`menqstudio/OS`) is the single source of truth — this
> chat's predecessors are gone; do not rely on any prior chat memory. Read this in
> full, then follow [`START_HERE.md`](./START_HERE.md) and the machine-readable
> [`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json).
>
> **Նոր session (Claude կամ ChatGPT):** այս ֆայլը + իր ցույց տված canonical ֆայլերը
> բավական են։ GitHub-ն ա միակ ճշմարտության աղբյուրը; հին chat-երին մի ապավինիր։

**Last updated:** 2026-07-24 · **Maintained by:** the implementer session, in the same commit as any state change.

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
8. Wave 3 security work (the active track): [`docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) (ratified), [`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md) (Wave 3b design, Architect-GREEN), [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md) (3b-1 implementation index — defers to the addendum), [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md) (**the single normative source for all 3b-1B contracts** — rev 14, **design RED, not yet GREEN**), and [`apps/desktop/SECURITY.md`](./apps/desktop/SECURITY.md).

---

## 3. CURRENT STATE — the authoritative block (read this before acting)

### 3.1 Repository / branch / PR / HEADs

- **Repository:** `menqstudio/OS` · **Active branch:** `feat/wave-3b1-isolated-signer` · **PR:** **#31** (OPEN, **NOT merged**).
- **Branch HEAD:** the tip of `feat/wave-3b1-isolated-signer` — confirm with `git rev-parse HEAD`. The substantive content is the **3b-1B addendum (currently rev 14 — CONSOLIDATED)** plus the documentation updates; the exact tip SHA moves with each doc commit. **Always re-confirm the exact HEAD from git, and query GitHub Checks for that HEAD's real CI — never trust a hardcoded run number.** (Architect-reviewed HEADs: rev 10 @ `6b1f8f4`, rev 11 @ `ac353149bb6a0c9eb0c930fba73b2c739d0229c7`, rev 12 @ `8d83246786120d5f3c6337315d904222d7991c19` — CI #116 GREEN, rev 13 @ `415e3fdef10b8a571b2544ec889c9758ca883071` — exact-head CI #117 GREEN.)
- **Base `main`:** `df3c0aca80cbe4a5537a9fdd53e16e26541c9c19` (Wave 3b-0 design merged, PR #30).
- The branch contains: **3b-1A code** (Architect-GREEN, §3.2) + the **3b-1 implementation index** (`WAVE_3B1_EXECUTION_BINDING_MAP.md`, now an index that defers to the addendum) + the **3b-1B design-lock addendum** (**rev 14**, design RED, §3.3 — the single normative source for all 3b-1B contracts). It carries **no 3b-1B, 3b-2, or 3b-3 code.**

### 3.2 Wave 3b-1A — ✅ Architect Code GREEN (do NOT reopen without new code evidence)

- **Approved code HEAD: `dffd1644e9882f6a1dab285c5e6bc6fc76d2c061`.** The GREEN remains valid through the later documentation-only HEADs (docs did not touch 3b-1A code).
- **Machine evidence:** every exact-head CI run through the rev-13 HEAD (`415e3fd`, run **#117**) has been **fully GREEN** — all **8** jobs, including both mandatory gates **`Engine · governance runtime`** and **`Engine · signer isolation proof`**. The Linux isolation job proves a **positive supervisor→signer signed round-trip BEFORE** the four same-login-user **denial** proofs, using dedicated service users. Docs/addendum commits do not touch 3b-1A code, so the `dffd164` GREEN stands. **Query GitHub Checks for the CURRENT HEAD's run** (do not trust a hardcoded number). **CI GREEN ≠ design GREEN** — the 3b-1B addendum is still design RED (§3.3).
- **What 3b-1A delivered (the isolated signing boundary):** real isolated **signer service** + **supervisor service** over an **ACL'd Unix-domain socket** with **`SO_PEERCRED`** peer enforcement; the **sidecar connects only to the supervisor, never to the signer**; strict **u32-framed IPC**, fixed **256 KiB** frame cap, duplicate-key/unknown-field/UTF-8/canonical-base64url rejection; **no arbitrary attestation/signing oracle** (`produce_sign_request({run_id, execution_attempt_id})` is the only entry); signer **authorization checklist** (identity allow-set, policy-in-force, bundle-digest, timestamp/skew); **forensic-attestation relay** to the desktop; **atomic content-addressed store** publishing; **service-owned socket dirs**; **dedicated service principals**; **shared-store perms** that permit the supervisor→signer path but deny sidecar access; and the **positive-control + four denial** machine proofs. Authoritative `brops_live_runstate.LiveRunStateProvider` validates the **signed** lease + passing receipt + evidence-chain + containment and cross-binds `lease_id`/`receipt_id`.
- **These 3b-1A findings are CLOSED. Do not reopen them without new code evidence.**

### 3.3 Wave 3b-1B — ❌ design RED (design-lock only; NO code written)

- **File:** [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md), now at **rev 14 (CONSOLIDATED)** — **the single normative source for every 3b-1B contract** (artifact matrix §3, exact schemas §4 incl. the control-plane §4.10, ms time model §1 with the legacy epoch-seconds evidence exception + freshness/window-nesting, closed capability profile §2 + protocol-versioning §2.2 + store ACL §2.3 + bounded ingress §2.4, durable acceptance state machine §5, atomic order + E2E §6/§6.1, verification §7 + desktop-signatures-only §7.1, authorities §8; revision history demoted to non-normative Appendix A). History: REDs rev 6→…→11 consolidation → rev 12 → rev 13 → the Architect **reviewed rev 13 at HEAD `415e3fd` (exact-head CI #117 fully GREEN — CI GREEN ≠ design GREEN), and returned Design RED with 3 P0 + 4 P1 targeted implementation-readiness findings, mandating a 7-track read-only fan-out audit + one integrator + a FRESH independent red-team (NOT single-context guessing, NOT a rewrite).** **rev 14 applies those corrections in place via that fan-out; it is NOT yet Architect-reviewed / NOT design-GREEN.** **3b-1B implementation has NOT started.**
- **Owner directive:** 3b-1 was re-scoped into **3b-1A** (isolated signing boundary — DONE/GREEN) + **3b-1B** (authoritative execution→receipt binding: the governed AI turn becomes a `bro_supervisor`-owned supervised execution that atomically emits a **signed** terminal record; **no unsigned run-state JSON may be signing authority**). The 3b-1 map is now a concise index that defers to the addendum: [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md).
- **The seven rev-13 → rev-14 findings (closed in place but treat as OPEN until the Architect returns design-GREEN):**
  1. **P0-1 — the `2770` store granted GROUP WRITE** to signer + both namespace owners (breaking signer-read-only / recorder-can't-write-`sup/` / supervisor-can't-write-`rec/`); the 3b-1A prover runs only as the login user, so it never proved those denials. **rev 14 (§2.3):** an **enforceable `2750` owner-write / group read-only** model — dedicated `brops-recorder` OS principal, `umask 0027`, `_harden_dir` refuses `S_IWGRP`, only the namespace owner creates/renames/unlinks, per-principal machine tests run AS each identity + a mode-regression guard (group-write bit clear).
  2. **P0-2 — staging↔acceptance deadlock + untrusted policy.** `staging-open` required an acceptance-ledger row that acceptance itself needed staging to create; and the sidecar was told to upload `policy_bundle` against a `policy_bundle_sha256` the challenge never mints. **rev 14 (§2.4, §5, §6):** a **pre-accept `governed_turn_staging` state machine** (VERIFYING→UPLOADING→INPUTS_READY, gated by the verified challenge, no execution right); the clock is read once at acceptance (after INPUTS_READY); the sidecar uploads **only** system/history/generation_config; the **supervisor self-resolves/publishes/binds policy** from its own authoritative registry (`RunState.policy_bundle` + signer `BROPS_EXPECTED_POLICY_BUNDLE_SHA256`); abandoned staging is reclaimed without consuming the challenge nonce.
  3. **P0-3 — the rendered reply rode an unauthenticated transport string** (a regression vs the v1 `receipt.rs` `sha256(output)==output_sha256` gate). **rev 14 (§4.6, §6.1 s13, §7.1):** the reply is delivered as **exact bytes** (`output_b64` inline for ≤128 KiB, else the §4.10f bounded chunked stream) and the desktop asserts `len==envelope.output_bytes` **and** `SHA256==envelope.output_sha256` **before any normalization**, strict-UTF8 for display only; substitution/mutation/truncation/normalization/invalid-UTF8/wrong-length/tampered-chunk all Block.
  4. **P1-4 — a 256 KiB decoded chunk overflows the 256 KiB frame after base64.** **rev 14 (§2.4):** **`MAX_STAGING_CHUNK_BYTES = 184320` (180 KiB)** → base64url 245760 + envelope ≤ 262144; the validator checks **both** the decoded cap and the encoded-frame cap; byte-proof + exact-max/max+1/oversized-frame tests.
  5. **P1-5 — two orphan protocols + three field-list-only staging messages + an inner-only bridge object.** **rev 14 (§4.10, §4.6):** **complete §4.10 control-plane schemas** for `governed-staging-open/-chunk/-final.v1`, the `governed-evidence-request.v1` execute trigger, `governed-result.v1` (supervisor→sidecar tagged union), and the `governed-result-open/-chunk/-final.v1` egress stream; the full `{ok, output_b64, receipt, error}` bridge parent (`receipt.envelope_jcs_b64` a required key absent from `bridge.result`); each has a `protocol` const discriminator + producer/consumer + strict v1-rejection.
  6. **P1-6 — `EXECUTION_TIMEOUT` had no value.** **rev 14 (§4.7, §1):** **`EXECUTION_TIMEOUT_MS = 120000`** nested inside the real `max_age_ms = 300000` freshness window (60 s skew + 30 s pre + 120 s exec + 40 s post = 250 s < 300 s); monotonic-elapsed / wall-signed clock split; **immediate SIGKILL** + 5 s grace + 10 s cgroup-teardown deadline; challenge TTL ≤ 30 s, lease window ≥ timeout+teardown, engine↔desktop skew ≤ 60 s.
  7. **P1-7 — the evidence-head floor had no storage/authority/CAS** (`min_head_sequence` was a caller-only param, never persisted). **rev 14 (§7):** a **signer-owned durable `governed_evidence_head_floor`** (`0700`/`0600`) with a `BEGIN IMMEDIATE` CAS (no-row→insert; `<`→refuse; `==`+diff-hash→refuse; `==`+same-hash→idempotent; `>`→advance) committed **before** the envelope is minted; crash-after-commit re-signs the identical envelope; startup + backup-rollback refusal; concurrent/crash/seq tests. Wording reconciled to **signer-owned** across §1/matrix/§6.1/§7/Appendix B.
- **Independent red-team (fresh, not the integrator):** three passes; it caught an egress contradiction (the result frame could not carry an 8 MiB output) → fixed with the §4.10f chunked stream + a `INLINE_OUTPUT_MAX = 131072` inline threshold proven to fit the 262144 frame with all co-resident fields at schema max; the final pass is PASS on every item.
- **Doc-law:** `CLAUDE.md`'s continuous-documentation law holds — **a CI result is not a doc-commit trigger** (GitHub Checks is the CI authority; never commit solely to bump a CI number).
- **Next permitted action:** submit rev 14 for Architect design review at the exact pushed HEAD; revise until **design-GREEN**. Only then may 3b-1B **code** be written.

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
| **3b-1B** | authoritative execution→receipt binding (design-lock) | ❌ **design RED** — Architect RED on the consolidated rev 13 (@ `415e3fd`, CI #117 GREEN ≠ design GREEN); **rev 14 CONSOLIDATED proposed, not yet GREEN, no code** — §3.3 |
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
