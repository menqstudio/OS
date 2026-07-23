# PROJECT_STATE — live status · կենդանի վիճակ

> **Canonical file. Read it at the start of every session, and update it in the SAME commit as any change.**
> **Canonical ֆայլ։ Կարդա ամեն session-ի սկզբում, ու թարմացրու նույն commit-ում ինչ փոփոխությունը։**

**Last updated · Վերջին թարմացում (2026-07-24):** **Wave 3a COMPLETE + merged** (slices 1/2/3 → `6c920d0`, `9b214e5`, `8a580028`; fail-closed strict 3a — every governed turn Blocks under `NoTrustedManifest`). **Wave 3b-0 design Architect-GREEN + merged** (PR #30 `df3c0ac`). **Active work = Wave 3b-1 (T-017) on `feat/wave-3b1-isolated-signer` (PR #31, OPEN, NOT merged):** re-scoped into **3b-1A** (isolated signing boundary) + **3b-1B** (authoritative execution→receipt binding). **3b-1A is ✅ Architect Code GREEN** (approved HEAD `dffd1644e9882f6a1dab285c5e6bc6fc76d2c061`; exact-head CI **#106/#107/#108 fully GREEN — all 8 jobs incl. the two mandatory gates `Engine · governance runtime` + `Engine · signer isolation proof`**; the Linux isolation job proves a positive supervisor→signer signed round-trip before the four same-login-user denials with dedicated service users). **3b-1B is ❌ design RED** — [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md) at **rev 6** is the implementer's *proposed* closure of the rev-5 RED and is **NOT Architect-GREEN**; **3b-1B code has NOT started**, and its five open design contracts (challenge-authority custody, challenge↔context binding, exact executor-input delivery, one normative bounded ingress, durable authenticated-challenge evidence) remain **OPEN** until the Architect returns design-GREEN. **STOP gates:** `NoTrustedManifest` unchanged; no production "Verified"; **3b-2 and 3b-3 NOT started**; **PR #31 must NOT merge** until 3b-1B is design-GREEN + implemented + zero-trust code-audit GREEN + exact-head CI GREEN. Schema on `main` = migration **0014** (`SCHEMA_VERSION`=14); the 3b-2 `0015` migration exists only on the separate un-merged `feat/wave-3b2-manifest-antirollback` branch. **The authoritative current state, evidence, next-action and truth-rules live in [`NEXT_CHAT.md`](./NEXT_CHAT.md) §3; the per-slice audit history is in [`TASKS.md`](./TASKS.md) (T-014…T-017).** Prior waves complete: Wave 1 (T-012), Wave 2a (T-013), Wave 2 (T-010 + T-011), Wave 3 design (PR #23).

---

## 📍 Where we are · Որտեղ ենք

- **Canonical execution source:** [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md) — status
  `v1.0 · Canonical Execution Authority` 🔒 **Locked** (Owner-approved 2026-07-21, basis HEAD `2e0157b`),
  **11 phases** fully expanded (16 sections each) with per-page UI specs from `brops-aios.html`, an
  Execution Ownership Matrix (§G), a Canonical Artifact Registry (§H), and Change Control (§I, now in
  force). A cold-start session takes the next unchecked task there. **Locked = product content
  change-controlled, not execution frozen** — building proceeds.
- **Coordination enforcement (T-007):** the Startup Law / docs-sync is now **enforced, not
  remembered** — a fail-closed **CI gate** (`tools/check_coordination.py`: roadmap 11×16, canonical
  files, TASKS statuses, PROJECT_STATE freshness) plus a fail-open **Stop-hook** (`.claude/`) that
  reminds when code changes without a coordination-doc sync.
- **Phase 0 — Foundation:** ✅ DONE (locked). OS monorepo assembled (`engine/` = Bro, `apps/desktop/` =
  BroPS, subtree history preserved), bilingual docs, unified CI.
- **Engine CI:** ✅ green — the 9 monorepo-coupled tests skip-guard themselves (option **C**);
  `OK (591 passed, 38 skipped, 0 failed)`.
- **Phase 1 — Bridge:** 🔨 in progress — `bridge/DESIGN.md` **APPROVED**; slice 1 (contract + adapter +
  tests + **bridge CI leg**) **merged to `main`** (PR #3, HEAD `41cf4ff`, 10/10 canonical — receipt-must-
  VERIFY invariant landed) **and** slice 2 **transport** — desktop Rust `Provider::GovernedEngine` in
  `ai.rs` (opt-in, default OFF) + governed sidecar wiring + chat receipt badge — **merged** (PR #8). *(The
  Settings governed toggle shipped in PR #8 was **removed in Wave 1** — replaced by a read-only provider
  status, PR #15.)* Slice 2 is **transport/infrastructure only**. **Still pending (not done):**
  the verify-seam (adapter → injected verifier), receipt-plumbing into the turn, one real governed
  round-trip end-to-end, and governed streaming.

## 👷 Who's working on what (NOW) · Ով ինչի վրա ա (ՀԻՄԱ)

| Agent | Task (see TASKS.md) | Branch | Status |
|---|---|---|---|
| 🔨 Claude | **Wave 3b (T-017) — 3b-1 isolated signer** (design GREEN) | `feat/wave-3b1-isolated-signer` | 🔨 **3b-1 code-audit RED ×2 → Owner-directed re-scope into 3b-1A (signing-boundary completion, CI GREEN) + 3b-1B (authoritative execution→receipt binding on the real `bro_supervisor` path), both on PR #31.** Implementation map written: [`docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md`](./docs/design/WAVE_3B1_EXECUTION_BINDING_MAP.md) — existing execution functions + the exact signed `brops.governed-turn-record.v1` schema (no unsigned JSON as signing authority). **CURRENT (2026-07-24): ✅ 3b-1A Architect CODE GREEN** — approved HEAD `dffd164`, exact-head CI **#106/#107/#108 fully GREEN** (all 8 jobs incl. both mandatory gates `Engine · governance runtime` + `Engine · signer isolation proof`; the Linux isolation job proves a positive supervisor→signer signed round-trip BEFORE the four same-login-user denials via dedicated service users). **❌ 3b-1B design RED** — the 3b-1B design-lock [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md) went RED rev 3→4→5; **rev 6 on the branch is a *proposed* closure, NOT Architect-GREEN** (five contracts still OPEN: dedicated challenge-authority custody / challenge↔context binding / exact executor-input delivery / one normative bounded ingress / durable authenticated-challenge evidence). **3b-1B code has NOT started.** STOP gates: `NoTrustedManifest` unchanged, no "Verified"; 3b-2 + 3b-3 NOT started; PR #31 NOT merged until 3b-1B is design-GREEN → implemented → code-audit GREEN → exact-head CI GREEN. Authoritative live state = [`NEXT_CHAT.md`](./NEXT_CHAT.md) §3. Prior remediation (well-bounded findings) done: oracle removal P0-2, auth checklist P1-7, forensic relay P1-6, framed codec P1-4, atomic publish P1-5, P0-3 record↔artifact cross-binding, IPC strictness, store 0640/setgid + per-service socket dirs. Owner-directed full rework closed all 3 P0 + 4 P1 + the CI RED: catalog orphan-registration (CI); atomic store publish P1-5; framed strict IPC codec P1-4; oracle removed P0-2; signer authorization checklist P1-7; forensic relay P1-6; authoritative `LiveRunStateProvider` (signed lease/receipt/evidence/containment) P0-3; real signer+supervisor **services** over an ACL'd Unix socket w/ `SO_PEERCRED` + a **Linux CI job** (`engine-isolation`) machine-proving all four same-login-user denials via dedicated service users P0-1; the sidecar now relays to the supervisor service and never reaches the signer. engine +40 brops tests (7 Windows-skipped, proven in Linux CI), bridge 37, clippy-clean, coordination GREEN. STOP intact (`NoTrustedManifest` unchanged, no "Verified"; 3b-2 not started; PR #31 not merged). Pushing new exact HEAD for zero-trust re-audit. — Prior: Owner approved starting 3b-1 non-stop. **Design PR #30 MERGED** (squash `df3c0ac` on `main`); 3b-1 rebased onto the new `main` as a single code commit. Built the isolated signer chain: `brops_canonical` (§4.0a formulas, reuse engine `canonical_bytes`), `brops_evidence_store` (content-addressed + §4.0 atomic publish), `brops_receipt_signer` (verify attestation → read store by handle → construct+sign 21-field `brops.receipt.v1`, base64url; refusal union; separate-process `__main__`), `brops_supervisor_attest` (evidence from `{run_id, attempt_id}` only, no oracle, + attestation), `brops_sign_flow`; IPC schemas `brops-{sign-request,sign-result,evidence-request}.v1`; bridge `containment_evidence_b64` (bounded); `engine_sidecar` wired (own `_SIGNER_PROVISION_ENV`, `--self-test-signed` mints a real signed receipt, real mode fail-closed pending live wiring). **Cross-language JCS parity GREEN both sides** (`receipt.rs::brops_all_formula_parity_matches_python`, env `37075e5f…`). Tests: engine **658** (42 skip, +30 new), bridge **37**, Rust core **90**; clippy-clean. **STOP honored:** `NoTrustedManifest` unchanged, no "Verified" (desktop still Blocks). **Deferred/flagged:** live supervisor→`RunState` provider + dedicated-principal socket ACL = Linux-first (CI); manifest/resolver + "Verified" = 3b-2/3b-3. — 3b-0 history below. Owner directive: custody boundary = trust boundary, Architect-gated design note before code. [`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md) **rev 2** locks: dedicated OS **security principal** (not just `0700`) / receipt-key custody unreachable by the sidecar / an **authenticated run-evidence chain** (supervisor = trusted producer + only authenticated caller, `brops.run-attestation.v1`; recompute ≠ authenticity) / not-an-oracle IPC / auth checklist / context-aware `KeyResolutionQuery` + scope-bound key + in-tx anti-rollback / signed-manifest+pinned-root+anti-rollback / fail-closed / normative §4 schemas / threat model. **Architect design RED history:** rev 1 (`6a6882e`, 4 P0) → rev 2 (`9801489`, 2 P0 + 3 P1) → **rev 3** closes them: the supervisor **builds evidence from `{run_id, attempt_id}`** (no `attest(caller_evidence)` oracle anywhere; single topology — sidecar never touches the signer); a **content-addressed protected evidence store** binds containment/large inputs to real artifact bytes; **one fixed 256 KiB IPC frame** (large inputs = handles, no inline); resolver query sourced from the **trusted `Expected`** (not the unsigned receipt); manifest floor **+ exact bytes persisted atomically** with semantic-uniqueness rejects. **Architect design YELLOW on rev 3 (`fa1b8cb`, CI #96 green) — architecture approved, no new P0; rev 4 closes 5 contract redlines:** per-artifact canonical-bytes table pinned to merged formulas + all-formula parity (P1-1), nonce schema fixed to the merged UUIDv4 `id()` not `hex(32B)` (P1-2), durable forensic-attestation record in `sign-result` + containment via bridge result (P1-3), supervisor process/service/ACL/store/IPC reclassified **BUILD** + 4 same-user isolation tests (P1-4), protected-store atomic publish algorithm (P1-5). **Architect design YELLOW on rev 4 (`73ff0f7`) — architecture confirmed; rev 5 closes the final contract:** the desktop resolves the **supervisor-attestation key from the root-signed manifest snapshot** (not signer config) via an explicit `key_usage: receipt_signing | supervisor_attestation` discriminator with **total type separation** (two disjoint in-tx resolvers; a receipt key can never verify an attestation and vice-versa) + attestation-key negative matrix. **✅ Architect DESIGN GREEN on rev 5 (approved HEAD `def7711`, exact-head CI #98 success) — 3b-0 design gate PASSED (no open P0/P1).** 3b implementation may start **only after Owner approval**; the 3b-1 stop condition holds (`NoTrustedManifest` unchanged, no production "Verified"); first `trusted_verified` only after the full 3b-1→3b-2→3b-3 chain is exact-head zero-trust GREEN. **Next: Owner merges design PR #30 + authorizes 3b-1 start.** **Wave 3a (slices 1+2+3) COMPLETE + merged** (`8a580028`). |
| 📐 ChatGPT | — | — | — |
| 👑 Gev | reviews / approvals · roadmap **v1.0 🔒 Locked** (Owner-approved, basis HEAD `2e0157b`) | — | — |

## ⏭️ Next task · Հաջորդ task

Follow [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md). Immediate open items:

1. **Wave 3b — isolated signer + signed manifest + production "Verified" (T-017)** — fill the
   `ReceiptKeyAuthority` seam slice 3 left (`NoTrustedManifest` ⇒ every governed turn Blocks): a minimal
   isolated trusted signer with real key custody (private key unreachable by the sidecar), an
   operator-provisioned signed key manifest validated against a binary-pinned root anchor (per-key
   `trust_class`, validity window, epoch, revocation), and anti-rollback (durable highest epoch + hash).
   Only 3b mints a real key ⇒ a production-class key renders **`trusted_verified`** ("Verified"). **IN
   PROGRESS on `feat/wave-3b1-isolated-signer` (PR #31, OPEN):** 3b-0 design merged (`df3c0ac`); 3b-1
   re-scoped → **3b-1A ✅ Architect CODE GREEN** (`dffd164`, CI #106/107/108) + **3b-1B ❌ design RED**
   (addendum rev 6 proposed, not GREEN, no code). Next action = get the 3b-1B addendum to Architect
   design-GREEN, then implement 3b-1B, then 3b-2/3b-3. See [`NEXT_CHAT.md`](./NEXT_CHAT.md) §3 + T-017.
2. **Phase 2 (Governance Sidecar)** — can start now (P1 contract exists): `approvals`/`decisions`/
   `security`/`notifications` surfaces, mirror-never-decide.
3. **T-005 — Option-2 (AUDITED, Phase 10)** — engine submodule + worktree-check native fix. Separate
   branch/PR, Owner approval, must not destabilize.

## 🚧 Blockers · Խոչընդոտներ

- ~~A/B root-model decision~~ → **DECIDED: Option 1 (subtree + C)** for stability (Architect call). The 9 enforcement-path tests stay skip-deferred (C); no security code touched. Option 2 (submodule + Bro worktree-check fix) is a future audited task — **T-005**. Verified finding: a submodule alone does NOT fix it (`git worktree list` reports the git-dir). See `CLAUDE.md` §3.
- Bro deferred security items **O-1..O-5** (residual-exploitable; tracked on Bro's `fix/audit-followups`) — do not rush, wall/owner-env coupled.

## 🔁 Startup Law · Startup օրենք

Every session, before anything: **`git pull` → read `CLAUDE.md` → read `PROJECT_STATE.md` → claim your task in `TASKS.md`**. Only then start.
Ամեն session, ամեն բանից առաջ՝ **`git pull` → կարդա `CLAUDE.md` → կարդա `PROJECT_STATE.md` → claim քո task-ը `TASKS.md`-ում**։ Միայն հետո սկսի։
