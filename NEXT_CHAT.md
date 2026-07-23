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
8. Wave 3 security work (the active track): [`docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) (ratified), [`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md) (Wave 3b design, Architect-GREEN), [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md) (3b-1 re-scope map), [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md) (3b-1B design-lock, **RED — not yet GREEN**), and [`apps/desktop/SECURITY.md`](./apps/desktop/SECURITY.md).

---

## 3. CURRENT STATE — the authoritative block (read this before acting)

### 3.1 Repository / branch / PR / HEADs

- **Repository:** `menqstudio/OS` · **Active branch:** `feat/wave-3b1-isolated-signer` · **PR:** **#31** (OPEN, **NOT merged**).
- **Branch HEAD:** the tip of `feat/wave-3b1-isolated-signer` — confirm with `git rev-parse HEAD`. The substantive content is the **3b-1B addendum (currently rev 10)** plus the documentation updates; the exact tip SHA moves with each doc commit. **Always re-confirm the exact HEAD from git, never from memory.** (Architect-reviewed HEADs: rev 8 @ `59a7f04`, rev 9 @ `cb821ed3ae27c7d7ed16d4f6104a7be0458cf254`.)
- **Base `main`:** `df3c0aca80cbe4a5537a9fdd53e16e26541c9c19` (Wave 3b-0 design merged, PR #30).
- The branch contains: **3b-1A code** (Architect-GREEN, §3.2) + the **3b-1 re-scope map** + the **3b-1B design-lock addendum** (**rev 10**, design RED, §3.3). It carries **no 3b-1B, 3b-2, or 3b-3 code.**

### 3.2 Wave 3b-1A — ✅ Architect Code GREEN (do NOT reopen without new code evidence)

- **Approved code HEAD: `dffd1644e9882f6a1dab285c5e6bc6fc76d2c061`.** The GREEN remains valid through the later documentation-only HEADs (docs did not touch 3b-1A code).
- **Machine evidence:** exact-head CI **#106, #107, #108, #111, #112** and the latest **#113** (on the rev-9 HEAD) were **fully GREEN** — all **8** jobs, including both mandatory gates **`Engine · governance runtime`** and **`Engine · signer isolation proof`**. The Linux isolation job proves a **positive supervisor→signer signed round-trip BEFORE** the four same-login-user **denial** proofs, using dedicated service users. The docs/addendum commits do not touch 3b-1A code, so the `dffd164` GREEN stands; **#113 is the latest exact-head fully-GREEN run. CI GREEN ≠ design GREEN** — the 3b-1B addendum is still design RED (§3.3).
- **What 3b-1A delivered (the isolated signing boundary):** real isolated **signer service** + **supervisor service** over an **ACL'd Unix-domain socket** with **`SO_PEERCRED`** peer enforcement; the **sidecar connects only to the supervisor, never to the signer**; strict **u32-framed IPC**, fixed **256 KiB** frame cap, duplicate-key/unknown-field/UTF-8/canonical-base64url rejection; **no arbitrary attestation/signing oracle** (`produce_sign_request({run_id, execution_attempt_id})` is the only entry); signer **authorization checklist** (identity allow-set, policy-in-force, bundle-digest, timestamp/skew); **forensic-attestation relay** to the desktop; **atomic content-addressed store** publishing; **service-owned socket dirs**; **dedicated service principals**; **shared-store perms** that permit the supervisor→signer path but deny sidecar access; and the **positive-control + four denial** machine proofs. Authoritative `brops_live_runstate.LiveRunStateProvider` validates the **signed** lease + passing receipt + evidence-chain + containment and cross-binds `lease_id`/`receipt_id`.
- **These 3b-1A findings are CLOSED. Do not reopen them without new code evidence.**

### 3.3 Wave 3b-1B — ❌ design RED (design-lock only; NO code written)

- **File:** [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md), now at **rev 10**. History: RED on rev 6 (2 P0+3 P1) → rev 7 → RED (2 P0+2 P1) → rev 8 → RED (1 P0+3 P1) → rev 9 → the Architect **reviewed rev 9 at HEAD `cb821ed` (exact-head CI #113 fully GREEN — CI GREEN ≠ design GREEN) and returned Design RED** on the final **1 P0 + 1 P1** replay/schema audit. **rev 10 is my proposed closure of those two; it is NOT yet Architect-reviewed / NOT design-GREEN.** **3b-1B implementation has NOT started.**
- **Owner directive:** 3b-1 was re-scoped into **3b-1A** (isolated signing boundary — DONE/GREEN) + **3b-1B** (authoritative execution→receipt binding: the governed AI turn becomes a `bro_supervisor`-owned supervised execution that atomically emits a **signed** terminal record; **no unsigned run-state JSON may be signing authority**). See the map: [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md).
- **The two rev-9 → rev-10 blockers (addressed by rev 10 but treat as OPEN until the Architect returns design-GREEN):**
  1. **P0 — the signed challenge was not atomically consumed at the supervisor.** The real `request_nonce` compare-and-consume lived in the **desktop** verify tx (after execution); checking "nonce unconsumed" then reserving as separate steps left a **supervisor-side replay window** where a compromised sidecar could resubmit one valid challenge and cause **duplicate model/tool execution** before the desktop accepted the first result. **rev 10 (§2.7):** one atomic supervisor acceptance transaction over a durable **acceptance ledger** — CAS `UNSEEN → ACCEPTED` keyed by `(install_id, request_nonce, challenge_handle)`, **fused** with attempt reservation + `challenge_accepted_at` stamp + `issue_governed_turn_lease`; a replay returns only the same attempt's idempotent result; a conflicting run/task/challenge binding is refused; crash-recovery is defined at every cut point; concurrent/sequential-replay + crash-retry + conflicting-binding negative tests. (Desktop nonce consumption still governs final **receipt** acceptance, but is not a substitute for supervisor-side **execution** replay prevention.)
  2. **P1 — `brops.governed-turn-lease.v1` was prose, and one binding was impossible.** rev 9 called it a "superset" without an exact schema and used field names conflicting with the strict base lease (`lease_nonce` vs `nonce`, `issued_at` vs `issued_at_epoch`), and its equality chain wrongly required `challenge_accepted_at` to equal a field inside the signed challenge (impossible — the supervisor stamps it *after* signing). **rev 10 (§2.6):** the **exact normative schema** — correct base field names, full required/allowed key set, type/size caps, unknown-field + duplicate-key rejection, JCS signed-byte formula, `ARTIFACT_AUTHORITY` mapping, `issue_governed_turn_lease` / `validate_governed_turn_lease` contracts (distinct from the base `validate_execution_lease`), and exact `brops.sign-request.v1` / `brops.sign-result.v1` / bridge-result / `brops.governed-turn-record.v1` extensions; the **impossible equality is removed** — `challenge_accepted_at` is byte-equal across the **supervisor-authoritative** chain only (lease → attestation → sign-result → bridge → record), and the lease binds back to the challenge via `challenge_handle`/`challenge_key_id`/`challenge_registry_*` + context ids.
- **Next permitted action:** submit rev 10 for Architect design review at the exact pushed HEAD; revise until **design-GREEN**. Only then may 3b-1B **code** be written.

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
| **3b-1A** | isolated signing boundary (services + ACL socket + authoritative RunState) | ✅ **Architect Code GREEN** @ `dffd164` (exact-head CI #113, 8/8) — §3.2 |
| **3b-1B** | authoritative execution→receipt binding (design-lock) | ❌ **design RED** — Architect RED on rev 9 (@ `cb821ed`, CI #113 GREEN ≠ design GREEN); **rev 10 proposed, not yet GREEN, no code** — §3.3 |
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
