# NEXT_CHAT — definitive handoff · վերջնական handoff

> **New Claude or ChatGPT session:** this file + the canonical files it points to are
> everything you need. GitHub (`menqstudio/OS`) is the single source of truth — this
> chat's predecessors are gone; do not rely on any prior chat memory. Read this in
> full, then follow [`START_HERE.md`](./START_HERE.md).
>
> **Նոր session (Claude կամ ChatGPT):** այս ֆայլը + իր ցույց տված canonical ֆայլերը
> բավական են։ GitHub-ն ա միակ ճշմարտության աղբյուրը; հին chat-երին մի ապավինիր։

**Last updated:** 2026-07-22 · **Maintained by:** the implementer session, in the same commit as any state change.

---

## 1. Identity

- **Repository:** `menqstudio/OS` — a governed AI-operations desktop: a safe cockpit (`apps/desktop/`, Tauri) on a contained governance engine (`engine/`, Python). Every AI action flows `lease → gate → sandbox → signed receipt`; no direct ungoverned model execution.
- **Owner:** 👑 **Gev** (`menqstudio`, ohanyan.88@gmail.com). Armenian-speaking — reply in Armenian by default; English only for code/identifiers/commands.
- **Roles ([`OWNERS.md`](./OWNERS.md)):**
  - 🔨 **Claude** — Builder / Implementer. Writes code, tests, commits, opens PRs.
  - 📐 **ChatGPT** — Architect / **zero-trust auditor**. Reviews each security PR against the exact HEAD and returns GREEN / YELLOW / RED. **The audit is the gate.**
  - 👑 **Gev** — Owner / final approver & merger.

## 2. Single source of truth + mandatory startup

**GitHub is canonical. A textual claim ("I read it", "it's done") is not evidence — verify against the repo.**

Startup read order (from [`START_HERE.md`](./START_HERE.md), extended):

1. `git pull` and confirm HEAD.
2. **This file** (`NEXT_CHAT.md`) — exact current state.
3. [`CLAUDE.md`](./CLAUDE.md) — the brain: what OS is, how to work, environment gotchas, security discipline.
4. [`PROJECT_STATE.md`](./PROJECT_STATE.md) — live status (who's on what, blockers).
5. [`TASKS.md`](./TASKS.md) — the task board; **claim your task before touching anything**.
6. [`OWNERS.md`](./OWNERS.md) — roles.
7. [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) + [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md) — design + canonical execution plan.
8. For the current security work: [`docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) and the machine-readable [`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json).

## 3. Current work — exact pointers

**Wave 3a slice 1 is DONE and merged.** **Slice 2 is IMPLEMENTED and in Review** on `feat/wave-3a-receipt-storage` — **not merged**; it awaits the Architect's zero-trust GREEN on the pushed candidate HEAD, then Owner merge.

| | |
|---|---|
| **Current task** | **Wave 3a slice 2 — receipt storage & atomicity** (T-015, §7). **IMPLEMENTED, in Review.** Migration **0014** (`SCHEMA_VERSION` 13→14) + `brops-core::receipt_store`: atomic `BEGIN IMMEDIATE` **verify→consume→persist**, `issue_challenge`, durable one-time nonce, `receipt_id` global uniqueness, freshness/skew on both timestamps; `ReceiptOutcome` has **no `TrustedVerified` variant** (production⇒Blocked, so 3a never renders "Verified"). Architect **YELLOW + RED×2** fixes applied (capped pre-decode `wire_*` evidence; `message_id` real FK + message→attempt→ledger order + **`ON DELETE RESTRICT`** so a delete with governed evidence is refused; blocked *verdict* commits evidence while only a real SQLite failure `Err`+rollbacks; nonce consumed even when later blocked; two-timestamp freshness; `issue_challenge` takes one `IssuedRequest`; real threaded race test). See the **Audit** row for the full R1/R2 detail. |
| **Branch** | **`feat/wave-3a-receipt-storage`** (cut off `main` @ `75a8d8f`; T-015 claimed). Push → PR → Architect zero-trust GREEN on the exact HEAD → Owner merge. |
| **Audit** | **Round 1 RED** (4, on `24869eb`) + **Round 2 RED** (3+hardening, on `c266417`) — both **RESOLVED**. R1: challenge `request_sha256` NOT-NULL+hex compared in-tx; staged decoded evidence (envelope+signature+key_id+receipt_id) on bad-sig/bind-fail; nested-tx reject + explicit COMMIT-failure rollback. R2: (1) `issue_challenge(conn, conversation_id, &IssuedRequest, now_ms)` derives nonce+hash from one `IssuedRequest` (no split-authority seam); (2) `message_id` `ON DELETE RESTRICT` + full accepted⇔message CHECK → deleting a conversation/message with governed evidence is **refused** (output bytes stay re-hashable in `messages.body`); (3) concurrency test is now a **real threaded race** (tempfile + 2 threads + `Barrier`, one accept / one block / both attempts recorded); hardening: `rusqlite` `hooks` → dev-dependencies. Awaiting **re-audit on the new pushed HEAD**. |
| **Verified** | `brops-core` = **83 tests** green (69 baseline + 14 slice-2 negative-matrix), clippy-clean; `tools/check_coordination.py` + `tools/check_capabilities.py` GREEN; app-workspace `cargo check` clean. |
| **Just merged** | **T-014 / slice 1 — PR #24 MERGED.** Approved HEAD `c51031e`; squash **merge commit `6c920d0`** on `main`; final CI 7/7 GREEN; Architect **zero-trust GREEN**. |

> **Slice 1 is GREEN + merged** (`git log main` → `6c920d0`, PR #24 MERGED). **Slice 2 is implemented on
> its branch and in zero-trust review — do NOT present it as merged/Done until the Architect GREENs the
> pushed HEAD and the Owner merges.** The next task AFTER slice 2 merges is slice 3 (transport wiring +
> receipt UI). The isolated signer + manifest + production "Verified" remain **Wave 3b** (§10).

## 4. Merged baseline (Done — verify via `git log main`)

- **Wave 1 — provider fail-closed** (audit P0-1), T-012, PR #15 (`15384cb`): `resolve()→Result`, no silent governed→ungoverned fallback; ungoverned only via `BROPS_ALLOW_UNGOVERNED=1`.
- **Wave 2a — webview message provenance** (audit P1-6), T-013, PR #16 (`d85dcba`): `WEBVIEW_MESSAGE_ROLES` restricted to `["user"]`; server-held answer via one-time `result_id`.
- **T-010 — Tauri capability boundary**, PR #19 (`7d537c3`): deny-by-default capability manifest over all 65 commands; the 4 L2 hard-delete commands DENIED; CI invariant `tools/check_capabilities.py`. Zero-trust GREEN.
- **T-011 — durable approval + native confirmation**, PR #20/#21 (merge `7638a64`): migrations 0012 (approval provenance) + 0013 (execution claim). Restart-safe self-approval by durable `origin_principal`; native-only approval authority; nonce compare-and-consume; canonical `RunExecutionScope` digest; atomic pre-dispatch execution claim; crash-recovery reconciliation; strict attempt ownership; enforced single-instance file lock. Zero-trust GREEN through multiple rounds.
- **Wave 3 Receipt Protocol v1 — design rev 4**, PR #23 (`35a6ab5`): Architect + Owner **GREEN**, merged. The design is the spec Wave 3a/3b implement.
- **Wave 3a slice 1 — receipt protocol core** (T-014), PR #24 (approved HEAD `c51031e`, **merge commit `6c920d0`**): `brops-core::receipt` — the pure verifier core (§5). Zero-trust GREEN after three RED rounds (§6).
- **Schema:** migrations through **0013**, `SCHEMA_VERSION = 13`. `brops-core` test suite: **69 tests** green.

## 5. Current slice — what IS implemented (PR #24)

`brops-core::receipt` — the **pure, I/O-free protocol core** (design §2, §2.3, and the pure subset of §3, §6):

- RFC 8785 (JCS) canonicalization for the receipt + canonical **request** envelope (§2, §2.2).
- Wire format + strict decode (§2.3): base64url → exact bytes (**64 KiB cap**), UTF-8, **duplicate-key** + **unknown-field** + **non-string-value** rejection, fixed field set/types, lowercase-64-hex hashes, numeric timestamps, `decision` domain, and **`JCS(parsed) == decoded bytes`** (parser-differential defense).
- **Verify-only** Ed25519 (`verify_strict`) over the decoded bytes, via a **type-state chain**: `parse_strict → Parsed` (exposes only `key_id`) → resolve the manifest key → `verify(&ResolvedManifestKey, sig)` (enforces `parsed.key_id == resolved_key.key_id`) → `Verified` (carries the signed `trust_class`) → `bind(&Expected, output)` → `BoundReceipt` → `resolve_3a()`. `ResolvedManifestKey` has **private fields + no public constructor** (only an in-crate validated resolver mints one).
- The pure §3 binding subset: protocol, `decision == completed`, identity/policy/config **expected-value** matches, allowed executor/builder, output-bytes re-hash (§2.1). The request half is a single `IssuedRequest` from which `bind` **recomputes** `request_sha256` (never a separate supplied hash), so hash and per-field bindings can't diverge.
- Trust-state gate (§6): `resolve_3a()` returns a **`Wave3aTrustState { DevelopmentUntrusted, Blocked }`** — a type with **no `TrustedVerified` variant**, so Wave 3a code cannot name a "Verified" state anywhere; `production ⇒ Blocked`.
- **Verify-only in production**: the Ed25519 *signing* half is compiled solely under `#[cfg(test)]` — the desktop core is never a `sign(arbitrary_bytes)` oracle (design §1).
- **69 core tests** (full negative-test matrix), clippy-clean.

## 6. Zero-trust audit history — RESOLVED (slice 1 is GREEN + merged)

Three RED rounds were closed and independently re-audited; the final HEAD `c51031e` got
**zero-trust GREEN** and merged (`6c920d0`). These are **resolved history, not current blockers.**

**Round 1 — RED on `a873501` (4 blockers), addressed in `aa4dc01`:**
1. **`key_id` not cryptographically bound to the passed key** → introduced `ResolvedManifestKey { key_id, public_key, trust_class }`; `verify` requires `parsed.key_id == resolved_key.key_id` before the signature (`KeyIdMismatch`); `Verified` carries that entry's `trust_class`; raw-key convenience is `#[cfg(test)]`-only.
2. **Trust state not bound to a verified+bound receipt** (standalone `resolve_trust_state(class, production_allowed)`) → removed it; trust state reachable only via `BoundReceipt::resolve_3a()`.
3. **`requested_at` not bound to the desktop request timestamp** → exact-equality binding added.
4. **`Parsed` derived `Debug` leaked private fields** → redacted manual `Debug` on `Parsed`/`Verified`/`BoundReceipt`.

**Round 2 — RED on `aa4dc01` (3 blockers), addressed in `f5b6ffe`:**
1. **`ResolvedManifestKey` was forgeable** — public fields let any caller pair an arbitrary `public_key`/`trust_class` with a chosen `key_id`. → *Addressed:* fields are now **private with no public constructor**; only an in-crate validated signed-manifest resolver (Wave 3b) can mint one; tests use the same-crate private fields.
2. **`TrustState::TrustedVerified` was directly constructible in shipping 3a code.** → *Addressed:* replaced `TrustState` with **`Wave3aTrustState { DevelopmentUntrusted, Blocked }`** — no `TrustedVerified` variant exists in 3a, so no code path can name a "Verified" state. The production state is a separate Wave 3b type.
3. **`request_sha256` was a separate caller-supplied value** — a wiring bug could pair request A's hash with request B's components. → *Addressed:* introduced an `IssuedRequest` (the 7 request-envelope fields); `Expected` embeds it and drops `request_sha256`; `bind` **recomputes** the canonical hash via `IssuedRequest::request_sha256()` and compares the receipt's signed value to it.

**Tests:** added the request-hash-recompute negative case; the mismatch matrix mutates every `IssuedRequest` component + policy/config field; trust-state tests use `Wave3aTrustState`. **69 core tests**, clippy-clean. **Final re-audit of `c51031e`: zero-trust GREEN → merged (`6c920d0`).**

## 7. Wave 3a slice 2 (receipt storage & atomicity) — the plan it followed

> **Status: IMPLEMENTED and in Review** on `feat/wave-3a-receipt-storage` (PR #26), awaiting
> re-audit on the pushed HEAD + Owner merge (see §3). The steps below are the design §3 (stateful
> items) + §4 plan the implementation followed; they are retained as the spec, not open work.

1. **Claim it:** cut `feat/wave-3a-receipt-storage` from `main`; add a T-015 row in `TASKS.md` (In-Progress).
2. **First concrete step — migration 0014** (`SCHEMA_VERSION` 13 → 14) in `apps/desktop/src-tauri/core/schema/0014_receipt_verification.sql`:
   - `receipt_verification_attempts` (exact canonical envelope bytes + signature + `key_id` + tri-state `outcome` {`trusted_verified`|`development_untrusted`|`blocked`} + `verification_error` + `verified_at` + link to the resulting message for accepted outcomes),
   - a durable **one-time nonce** table (issued → consumed) for the desktop challenge,
   - a **`receipt_id` global-uniqueness** constraint.
3. Then the **atomic verify → consume → persist** transaction (one DB tx): verify (via `brops-core::receipt`) → resolve `Wave3aTrustState` → consume the nonce → insert the attempt row → if accepted, insert the agent message (badge from outcome); a `blocked` attempt records evidence + error and never becomes a `messages` row.
4. Then wall-clock **freshness/skew** on `requested_at`/`completed_at`, and the `receipt_id`-unseen durable check.
5. Full negative-test matrix at the storage layer (replayed nonce, duplicate `receipt_id`, blocked-never-persists, crash-atomicity), then live-sync docs + open the PR for zero-trust audit. **Transport wiring + receipt UI are slice 3; the isolated signer + manifest + production "Verified" are Wave 3b** (§10).

## 8. Verify commands (Windows box)

```bash
# Rust data core (⚠ run cargo from PowerShell, NOT the Bash tool — see CLAUDE.md §5)
cargo test -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml   # 69 tests
cargo clippy -p brops-core --all-targets                                          # clippy-clean

# Coordination-docs gate (fails closed on stale coordination)
python tools/check_coordination.py

# Capability invariant (T-010)
python tools/check_capabilities.py

# Engine (Python) — MUST set BRO_ENV=ci
cd engine && BRO_ENV=ci python -m unittest discover -s tests
```

CI (`.github/workflows/ci.yml`) triggers on `push → main` and on `pull_request`. A feature-branch push **without a PR runs no CI**. **CI GREEN is not audit GREEN.**

## 9. Merge gate & prohibited shortcuts

- **A security PR merges only after the Architect's zero-trust GREEN on the exact candidate HEAD, then Owner approval.** No self-merge of a security PR before that GREEN.
- No direct work on `main`; every task = branch + PR (PR template).
- Never fabricate a commit SHA, test result, verdict, or file state. Do not write `Done`/`GREEN`/`approved`/`merge-ready` unless it is a verified fact in the repo.
- Do **not** present slice-1-deferred items (below) as implemented.
- Do not touch the engine's wall/leases/gates/signatures/control-plane casually — it is an audited security perimeter (CLAUDE.md §6). Engine-only work lives in [`engine/NEXT_CHAT.md`](./engine/NEXT_CHAT.md) and is a separate track ("do not touch BroPS" applies there in reverse here).

## 10. Deferred — NOT yet implemented (do not claim as done)

Slice 1 deliberately defers these to slice 2 / slice 3 / Wave 3b:

- durable nonce **issue/consume**; `receipt_id` global uniqueness
- manifest **loading + signature verification**; key validity window / epoch / revocation; manifest **anti-rollback**
- wall-clock **freshness/skew**
- **migration 0014**; **atomic verify → consume → persist**; `receipt_verification_attempts`
- desktop **transport wiring** (governed turn calls the verifier; sign-on-complete buffering); Python bridge changes; JCS **cross-language parity** test
- frontend **receipt trust UI** (dev/blocked badges)
- **Wave 3b** — isolated trusted signer + provisioned signed manifest + root anchor; only 3b enables production **`trusted_verified`** ("Verified")

Beyond Wave 3: Wave 4 (supervisor hardening, engine P0-4), Wave 5 (trusted sidecar, P0-3), production CI/release (P0-6), then the product roadmap phases (`MASTER_EXECUTION_ROADMAP.md`).

## 11. Handoff rule (keep this file true)

Every approved decision made in a Claude/ChatGPT chat must be written into the canonical repo docs **in the same commit** as the change it authorizes — `NEXT_CHAT.md`, `PROJECT_STATE.md`, `TASKS.md`, and any design/security doc it touches. A new chat must be able to continue correctly from GitHub alone. The chat is never the record.
