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
8. Wave 3 security work (the active track): [`docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) (ratified), [`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md) (Wave 3b design, Architect-GREEN), [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md) (3b-1 implementation index — defers to the addendum), [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md) (**the single normative source for all 3b-1B contracts** — rev 15, **design RED, not yet GREEN**), and [`apps/desktop/SECURITY.md`](./apps/desktop/SECURITY.md).

---

## 3. CURRENT STATE — the authoritative block (read this before acting)

### 3.1 Repository / branch / PR / HEADs

- **Repository:** `menqstudio/OS` · **Active branch:** `feat/wave-3b1-isolated-signer` · **PR:** **#31** (OPEN, **NOT merged**).
- **Branch HEAD:** the tip of `feat/wave-3b1-isolated-signer` — confirm with `git rev-parse HEAD`. The substantive content is the **3b-1B addendum (currently rev 15 — CONSOLIDATED)** plus the documentation updates; the exact tip SHA moves with each doc commit. **Always re-confirm the exact HEAD from git, and query GitHub Checks for that HEAD's real CI — never trust a hardcoded run number.** (Architect-reviewed HEADs: rev 11 @ `ac35314`, rev 12 @ `8d83246` — CI #116 GREEN, rev 13 @ `415e3fd` — CI #117 GREEN, rev 14 @ `18a467d4e370503f2c1efa7d050c15c673a6ed67` — exact-head CI #118 GREEN.)
- **Base `main`:** `df3c0aca80cbe4a5537a9fdd53e16e26541c9c19` (Wave 3b-0 design merged, PR #30).
- The branch contains: **3b-1A code** (Architect-GREEN, §3.2) + the **3b-1 implementation index** (`WAVE_3B1_EXECUTION_BINDING_MAP.md`, now an index that defers to the addendum) + the **3b-1B design-lock addendum** (**rev 15**, design RED, §3.3 — the single normative source for all 3b-1B contracts). It carries **no 3b-1B, 3b-2, or 3b-3 code.**

### 3.2 Wave 3b-1A — ✅ Architect Code GREEN (do NOT reopen without new code evidence)

- **Approved code HEAD: `dffd1644e9882f6a1dab285c5e6bc6fc76d2c061`.** The GREEN remains valid through the later documentation-only HEADs (docs did not touch 3b-1A code).
- **Machine evidence:** every exact-head CI run through the rev-14 HEAD (`18a467d`, run **#118**) has been **fully GREEN** — all **8** jobs, including both mandatory gates **`Engine · governance runtime`** and **`Engine · signer isolation proof`**. The Linux isolation job proves a **positive supervisor→signer signed round-trip BEFORE** the four same-login-user **denial** proofs, using dedicated service users. Docs/addendum commits do not touch 3b-1A code, so the `dffd164` GREEN stands. **Query GitHub Checks for the CURRENT HEAD's run** (do not trust a hardcoded number). **CI GREEN ≠ design GREEN** — the 3b-1B addendum is still design RED (§3.3).
- **What 3b-1A delivered (the isolated signing boundary):** real isolated **signer service** + **supervisor service** over an **ACL'd Unix-domain socket** with **`SO_PEERCRED`** peer enforcement; the **sidecar connects only to the supervisor, never to the signer**; strict **u32-framed IPC**, fixed **256 KiB** frame cap, duplicate-key/unknown-field/UTF-8/canonical-base64url rejection; **no arbitrary attestation/signing oracle** (`produce_sign_request({run_id, execution_attempt_id})` is the only entry); signer **authorization checklist** (identity allow-set, policy-in-force, bundle-digest, timestamp/skew); **forensic-attestation relay** to the desktop; **atomic content-addressed store** publishing; **service-owned socket dirs**; **dedicated service principals**; **shared-store perms** that permit the supervisor→signer path but deny sidecar access; and the **positive-control + four denial** machine proofs. Authoritative `brops_live_runstate.LiveRunStateProvider` validates the **signed** lease + passing receipt + evidence-chain + containment and cross-binds `lease_id`/`receipt_id`.
- **These 3b-1A findings are CLOSED. Do not reopen them without new code evidence.**

### 3.3 Wave 3b-1B — ❌ design RED (design-lock only; NO code written)

- **File:** [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md), now at **rev 15 (CONSOLIDATED)** — **the single normative source for every 3b-1B contract** (artifact matrix §3, exact schemas §4 incl. the control-plane §4.10, ms time model §1, capability profile §2 + protocol-versioning §2.2 + store ACL §2.3 + bounded ingress §2.4, durable acceptance state machine §5, atomic order + E2E §6/§6.1, verification §7 + desktop-signatures-only §7.1, authorities §8; revision history in non-normative Appendix A). History: REDs rev 6→…→11 consolidation → rev 12 → rev 13 → rev 14 → the Architect **reviewed rev 14 at HEAD `18a467d` (exact-head CI #118 fully GREEN — CI GREEN ≠ design GREEN), and returned Design RED with 4 P0 + 3 P1 transport/version/lease findings, mandating a 7-track read-only fan-out audit + one integrator + a FRESH independent red-team (NOT single-context guessing, NOT a rewrite).** **rev 15 applies those corrections in place via that fan-out; it is NOT yet Architect-reviewed / NOT design-GREEN.** **3b-1B implementation has NOT started.**
- **Owner directive:** 3b-1 was re-scoped into **3b-1A** (isolated signing boundary — DONE/GREEN) + **3b-1B** (authoritative execution→receipt binding: the governed AI turn becomes a `bro_supervisor`-owned supervised execution that atomically emits a **signed** terminal record; **no unsigned run-state JSON may be signing authority**). The 3b-1 map is now a concise index that defers to the addendum: [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md).
- **The seven rev-14 → rev-15 findings (closed in place but treat as OPEN until the Architect returns design-GREEN):**
  1. **P0-1 — rev 14 redefined the already-SHIPPED `brops.governed-result.v1`** (`brops_supervisor_service.py`, shape `{status, output, receipt:{...}}`) with a new shape, and its bridge discriminator was FALSE (`envelope_jcs_b64` is REQUIRED in `bridge.result` too). **rev 15 (§2.2, §4.6, §4.10):** **freeze** the shipped `brops.governed-result.v1`; the 3b-1B result becomes **`brops.governed-turn-result.v1`** and the bridge parent **`bridge.governed-turn-result.v1`** with an explicit **top-level `protocol` const discriminator** (old strict `bridge.result` rejects the extra key; new requires it).
  2. **P0-2 — no protocol carried the signed challenge DOCUMENT to the supervisor** (verify-by-handle-before-possession is impossible). **rev 15 (§4.10(a0), §2.4, §6.1):** new **`brops.governed-turn-open.v1`** submits the exact `{payload,sig}` bytes (`challenge_doc_b64`); the supervisor decodes → computes the handle → resolves the registry from its OWN state → verifies → publishes the challenge doc → creates the `governed_turn_staging` UPLOADING row; staging-open now requires that existing row.
  3. **P0-3 — the real `brops_socket` is one-request/one-response (no push)** and the desktop↔sidecar is a one-shot subprocess, so rev-14's push stream was unimplementable. **rev 15 (§4.10(f), §6.1, §7.1):** an idempotent **PULL** `brops.governed-turn-output-read.v1 {output_stream_id, seq}` → `{seq, bytes_b64, eof}` (offset `seq·184320`, max seq 45 for 8 MiB, stream_id bound server-side); the desktop reassembles + length/SHA256-verifies **outside** the `BEGIN IMMEDIATE` tx.
  4. **P0-4 — an expired lease could authorize execution** (only `≤` ordering, no fixed duration, no pre-launch gate, §7 didn't check `started/finished`). **rev 15 (§4.3, §5, §7):** **`LEASE_DURATION_MS = 210000`**, `lease_issued_at_ms == challenge_accepted_at_ms`, a pre-launch wall-clock + remaining-budget gate (≥ 175000) else BLOCKED/EXPIRED (never auto-launch an expired `LEASE_READY`), and §7 enforces `lease_issued ≤ started ≤ finished ≤ lease_expires` + `completed ≥ finished`.
  5. **P1-5 — `governed-turn-recorder` was both a supervisor key and a distinct OS principal.** **rev 15 (§0, §2.3, §8):** it is a **supervisor-held signing-key authority, NOT a distinct OS principal** (key dir under `brops-supervisor`; constructor-only; no `sign(payload)` oracle); `brops-recorder` stays the separate `store/rec` writer.
  6. **P1-6 — the inline result frame provably OVERFLOWED** (266707 > 262144 at schema max; the rev-14 "≈252032" undercounted `evidence[]` + echoes). **rev 15 (§4.6, §4.10, §4.5):** **always-stream** (no inline output) makes the summary metadata-only (~9.9 KiB) with frozen exact **encoded** caps (`envelope_jcs_b64 ≤ 2848`, `attestation_evidence_jcs_b64 ≤ 4664`, `containment ≤ 65536`, `evidence[] ≤ 64×256`) + a machine-checked literal-max CI proof.
  7. **P1-7 — the "detect backup rollback" claim was unprovable** with a local SQLite floor (and offline/root restore is out of §0 scope). **rev 15 (§7):** **Option A honest scoping** — detect stale/fork vs the current floor; state the local table cannot detect a full-DB restore; defer external anti-rollback anchoring to 3b-2; drop the backup-rollback test; plus an **extend-or-scope** advance rule (a higher-seq divergent lineage refuses as `evidence_fork`).
- **Independent red-team (fresh, not the integrator):** PASS on all a–k, verifying the two load-bearing facts against live code (`brops_supervisor_service.py:48` shipped shape; `bridge-result.schema.json:17` requires `envelope_jcs_b64`); only two cosmetic nits, both fixed before commit.
- **Doc-law:** `CLAUDE.md`'s continuous-documentation law holds — **a CI result is not a doc-commit trigger** (GitHub Checks is the CI authority; never commit solely to bump a CI number).
- **Next permitted action:** submit rev 15 for Architect design review at the exact pushed HEAD; revise until **design-GREEN**. Only then may 3b-1B **code** be written.

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
| **3b-1B** | authoritative execution→receipt binding (design-lock) | ❌ **design RED** — Architect RED on the consolidated rev 14 (@ `18a467d`, CI #118 GREEN ≠ design GREEN); **rev 15 CONSOLIDATED proposed, not yet GREEN, no code** — §3.3 |
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
