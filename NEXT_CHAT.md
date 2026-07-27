# NEXT_CHAT — definitive handoff · վերջնական handoff

> **New Claude or ChatGPT session:** this file + the canonical files it points to are
> everything you need. GitHub (`menqstudio/OS`) is the single source of truth — this
> chat's predecessors are gone; do not rely on any prior chat memory. Read this in
> full, then follow [`START_HERE.md`](./START_HERE.md).
>
> **Նոր session (Claude կամ ChatGPT):** այս ֆայլը + իր ցույց տված canonical ֆայլերը
> բավական են։ GitHub-ն ա միակ ճշմարտության աղբյուրը; հին chat-երին մի ապավինիր։

**Last updated:** 2026-07-27 (Phase-0 repository-truth remediation) · **Maintained by:** the implementer session, in the same commit as any state change.

---

## 1. Identity

- **Repository:** `menqstudio/OS` — a governed AI-operations desktop: a safe cockpit (`apps/desktop/`, Tauri) on a contained governance engine (`engine/`, Python). **Target invariant (being built toward, NOT yet fully true):** every production AI action follows the governed chain `lease → gate → sandbox → signed receipt`. **Today:** only the main governed-chat seam is wired to that chain (fail-closed under `NoTrustedManifest` — production "Verified" not yet available); the remaining AI entry points (run-steps, Ask Bro, conversation-reply, automations, group chat, integrations) are **tracked open blockers**, not yet governed.
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

> **CURRENT STATE (authoritative; machine-mirror: [`config/current_state.json`](./config/current_state.json)).**
> Tokens (validated against `config/current_state.json.status_tokens`): `CURRENT_ACTIVE_TASK: T-017` · `CURRENT_ACTIVE_WAVE: 3b-1B` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: GREEN` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: GREEN` · `CURRENT_DESIGN_PR: 31-merged` · `CURRENT_IMPL_PR: 46` · `CURRENT_IMPL_STATE: WIP` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

> **▶ POST-MERGE (current).** Wave 3b-1B DESIGN rev-30 is **Architect DESIGN GREEN** and **MERGED to main** (PR #31, squash `9c1b901`, with the 3b-1A isolated-signer code = Architect Code GREEN). The dependency-safe quality/CI gates are integrated. The 3b-1B **implementation** is WIP on PR #46 (branch `impl/wave-3b1b-core`, not code-audited). `config/current_state.json` is the authoritative machine mirror. `NoTrustedManifest` stays fail-closed; no production `trusted_verified` until the 3b-1 chain is code-audit GREEN + 3b-2/3b-3 land.

> **▶ rev-30 UPDATE (current).** The **rev-29** candidate was **Architect design RED — 1 P0 + 3 P1** at exact HEAD `1a79bc2` (CI run 30297820594 9/9 GREEN; CI ≠ design GREEN). **rev-30 remediates all four and is re-submitted, PENDING_REAUDIT** — P0 the exact broker-committed output delivery path (§4.10(g) reply frame now returns the broker-produced immutable `message{message_id, role, author, body, created_at_ms, trust_state:"trusted_verified"}`; `body` = exact strict-UTF8 envelope bytes = committed row; in-tx commit-readback mismatch ⇒ fail-closed; only the broker tx creates the verified message; blocked ⇒ no message; +E2E tests); P1-1 `client_request_id` correlation + broker-minted `broker_turn_id`/`request_nonce` + payload-aware idempotency on `{client_request_id, conversation_id, agent}` (a different request on a live conversation ⇒ `turn_in_progress`, replacing the old conversation_id-reattach rule); P1-2 the 0/1/2 stdio lifecycle (recorder opens inert; launcher verifies+closes before `fexecve`; only 3–6 survive; `/proc/self/fd` test); P1-3 this canonical sync. **`config/current_state.json` is the authoritative machine mirror.** Do NOT merge PR #31 until rev-30 is Architect design-GREEN at the exact HEAD.
> `main` = **`b6c6712`** (baseline-at-sync — resolve the live `main` HEAD each session; this goes stale on the next merge). **Active task: T-017** (Wave 3b-1). **Wave 3a is COMPLETE** (slices 1/2/3 merged). **Wave 3b-0 design MERGED via PR #30** (`df3c0ac`). **Phase 0 (repository-truth remediation) is DONE — merged via PR #33** (Owner-approved GREEN at exact `45f3793`, squash **`b6c6712`**); the Phase-0 carrier machinery is retired. Active work now:
> - **PR #31** (`feat/wave-3b1-isolated-signer`, base `main`, open, **rebased onto the repaired `main` `b6c6712`**): the **3b-1A** isolated-signer boundary **code is Architect Code GREEN**; it also carries the **3b-1B design-lock addendum**, which is **Architect design RED** — **rev-27 received 2 P0 + 4 P1** at exact HEAD `0e41ef6` (CI run `30270454903` 9/9 GREEN — CI is NOT design GREEN); **rev-27** remediates them and is re-submitted for the Architect design audit. PR #31 is the snapshot's **current_workflow_pr**, exact-head-anchored by its PR-body **`AUDIT_CANDIDATE_HEAD`** marker (event head == live headRefOid == marker; **nothing is exempt** from exact-head verification — the old `self_carrier` exemption is removed).
> - **PR #32** (`impl/wave-3b1b-execution-binding`, base PR #31, HEAD `0e7ee1a`, **Draft/WIP**): holds **UNAPPROVED Draft/WIP 3b-1B code** with **no authority over the design**. It is **NOT an RC, NOT merge-ready, NOT Architect-approved**; it must be rebased + adapted **only after** the rev-27 design is Architect design-GREEN, and stays **frozen from architectural expansion** until then.
> - **Honest framing:** there is **no Architect-approved or merged 3b-1B implementation**. Do not say "3b-1B code has not started" (a Draft/WIP exists in PR #32) and do not treat that WIP as authoritative. **Do NOT** merge either PR until **rev-27 is Architect design-GREEN at the exact HEAD**. `NoTrustedManifest` stays fail-closed; no production "Verified".
> - **Next permitted action:** the earlier 3 preparation-P0 are closed (§2.5/§2.6/§0.1/§0.W), but the **Architect verdict on rev-27 is RED (2 P0 + 4 P1)**. rev-28 closes them — **P0-1** the challenge-authority topology (8 distinct principals; desktop-UI client is an untrusted producer owning no key/store; `desktop-challenge-authority` is a separate service/principal; 3 threat actors separated); **P0-2** the launcher model (Model A: root/TCB-owned setuid helper, invoked only by the recorder, not a persistent runtime UID). Then **re-submit rev-28 for the Architect design audit at PR #31's exact HEAD.** Preparation-review closure is NOT the Architect's verdict.
>
> The narrative below is the accurate 3b-0 design-review HISTORY (rev 1→5); it ends at the 3b-0 gate. Read the block above for the post-3b-0 reality.

<!-- HISTORY_BEGIN -->
**Wave 3a is COMPLETE — slices 1, 2 AND 3 are DONE and merged.** **Wave 3b DESIGN-FIRST history** — its **3b-0 design** was reviewed and **MERGED via PR #30** (merge commit `df3c0ac`); the design lived on `design/wave-3b-isolated-signer` ([`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md)). **Architect design RED ×2 (rev 1 `6a6882e` = 4 P0; rev 2 `9801489` = 2 P0 + 3 P1); rev 3 closes them all.** rev 3 locks: the **supervisor builds evidence itself from `{run_id, execution_attempt_id}`** — no `attest(caller_evidence)` oracle anywhere and a single topology (the signer's only peer is the supervisor over direct ACL'd IPC; the sidecar never connects to the signer); a **content-addressed protected evidence store** so containment + large inputs bind to real artifact bytes, not a hashed reference; **one fixed 256 KiB IPC frame** with large inputs as handles (no inline); the resolver query sourced from the **trusted `Expected`/turn** (only `key_id` from the unsigned receipt); and the manifest floor **plus exact canonical bytes persisted atomically** with semantic-uniqueness rejects + signed-in `root_key_id`. **Architect design YELLOW on rev 3 (`fa1b8cb`, CI #96 green) — architecture approved (no new P0); rev 4 closes 5 contract redlines:** per-artifact canonical-bytes table pinned to the merged desktop formulas + all-formula parity (P1-1), the nonce schema fixed to the merged UUIDv4 `brops_core::id()` not `hex(32B)` (P1-2), a durable forensic-attestation record in `sign-result` + containment bytes via the bridge result (P1-3), the supervisor process split/service/ACL/store/IPC reclassified **BUILD** (only `bro_supervisor.py` logic is reused; the live path still spawns `engine_sidecar.py` with fail-closed placeholders) + 4 same-login-user isolation acceptance tests (P1-4), and the protected-store atomic publish algorithm (P1-5). **Architect design YELLOW on rev 4 (`73ff0f7`) — architecture confirmed; rev 5 closes the final signed-key-authority contract:** the desktop resolves the **supervisor-attestation key from the root-signed manifest snapshot** (not signer config, which the desktop can't trust) via an explicit `key_usage: receipt_signing | supervisor_attestation` discriminator, with **total type separation** — two disjoint in-tx resolvers so a receipt key can never verify an attestation and an attestation key can never render "Verified" — plus the attestation-key negative matrix. **✅ Architect DESIGN GREEN on rev 5 (approved HEAD `def7711`, exact-head CI #98 success) — the 3b-0 design gate is PASSED (no open P0/P1).** Per the Architect verdict, 3b implementation may begin **only after Owner approval**; the 3b-1 stop condition stays mandatory (`NoTrustedManifest` unchanged, no production "Verified" exposed), and the first `trusted_verified` is allowed only after the full 3b-1→3b-2→3b-3 chain is exact-head zero-trust GREEN. **[SUPERSEDED — see the CURRENT STATE block above: PR #30 is MERGED (`df3c0ac`); 3b-1 is underway as PR #31 (3b-1A Code GREEN + 3b-1B rev-26 design candidate PENDING re-audit — the RED verdicts above were on the EARLIER 3b-0 revs 1–2, not rev-26) with WIP implementation in PR #32.]** (Owner directive: the private-key custody boundary IS the trust boundary — no rushing the engine perimeter.) Slice 3 (T-016, PR #28, approved HEAD `dee6661`, squash **merge commit `8a580028`**) wired the desktop to CALL the merged verifier on a real governed turn (fail-closed strict 3a: every governed turn Blocks until Wave 3b provisions a trusted key), through the `ReceiptKeyAuthority` seam, a single `PreparedGovernedTurn` source, exact structured `system`+`history` as the bridge signing authority, buffered `governed_turn`, a turn-level Blocked notice with no double-post, dev/blocked badges, JCS cross-language parity, and bounded transport-failure evidence. Zero-trust GREEN after a YELLOW + two RED rounds; final CI 7/7 GREEN.
<!-- HISTORY_END -->
> _(The authoritative present-tense state is the CURRENT STATE block in §3 above. The narrative above is 3b-0 design-review history.)_

| | |
|---|---|
| **Next task** | **Wave 3b-1B rev-27 design remediation** on **PR #31** (`feat/wave-3b1-isolated-signer`). rev-26 got an **Architect design RED (2 P0 + 3 P1)** at `0e41ef6`. In `docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`, rev-28 closes: **P0-1** challenge-authority topology — **eight** distinct principals (desktop-UI/backend client = untrusted request producer owning NO challenge key/store; `desktop-challenge-authority` = separate service/principal with own UID/SID, key + pending store unreadable/unlistable/unwritable by desktop-UI/login/sidecar/every other principal; desktop→authority IPC authenticates the exact client principal); the **three threat actors** stated separately (malicious login user / compromised renderer-client / RCE in the dedicated sidecar SERVICE UID); update `verify_distinct_principals()`, the platform gate, Linux accounts, Windows SIDs, ACL/IPC matrices, tests. **P0-2** launcher — lock **Model A** (root/TCB-owned setuid helper, invoked only by the recorder UID, effective identity root/TCB, **not** a persistent runtime UID; strict peer/lease/hash/FD/target-UID/cgroup checks; drops to executor + `fexecve`; no env inheritance; no arbitrary target/argv/cap/FD) with full Linux+Windows mapping + confused-deputy/oracle negative matrix. Then set the PR-body `AUDIT_CANDIDATE_HEAD` marker to the new exact head and **re-submit rev-28 for the Architect design audit** at that exact HEAD. Only after design-GREEN + implemented + code-audit GREEN + CI GREEN does 3b-1 merge; then 3b-2 → 3b-3 (first production `trusted_verified`). `NoTrustedManifest` stays fail-closed until the full chain is exact-head zero-trust GREEN. |
| **Just merged** | **PR #33 — Phase 0 repository-truth remediation + semantic/live-truth exact-head gates** MERGED to `main` (Owner-approved GREEN at exact `45f3793`, squash **`b6c6712`**); main-push CI 8/8 GREEN (carrier verified MERGED, no self-red/self-stale). Prior: **PR #30 — Wave 3b-0 isolated-signer DESIGN** MERGED (`df3c0ac`, Architect DESIGN GREEN rev 5 `def7711`); **T-016 / slice 3 — PR #28** (`8a580028`) wired the desktop verifier into a real governed turn fail-closed. |
| **Baseline (main `b6c6712`)** | Test suites (each separate, they do NOT sum): `brops-core` **89**, host `brops` **42**, bridge **35** py, frontend **6** — all green (as recorded at 3a completion); clippy-clean; migrations through **0014**, `SCHEMA_VERSION = 14`; `tools/check_coordination.py` + `tools/check_repo_state.py` + `tools/check_capabilities.py` GREEN. (PR #31 adds the 3b-1 engine/bridge/host code + rev-26 design; PR #32 adds the WIP impl — see `config/current_state.json`.) |

> **Wave 3a is COMPLETE** — slices 1, 2, 3 all GREEN + merged (`git log main` → `6c920d0`, `9b214e5`, `8a580028`).
> The desktop now issues a nonce challenge, runs the governed turn buffered, and verifies the signed receipt
> (fail-closed: no trusted key yet ⇒ Blocked). The isolated signer + provisioned manifest + production
> "Verified" are **Wave 3b**. Precise status (do NOT flatten to "not implemented" OR to "done"): **Wave
> 3b-1B WIP code EXISTS in PR #32** — but it is **not merged, not an RC, not production-authoritative**,
> and **production `trusted_verified` remains unavailable** (`NoTrustedManifest` fail-closed). Wave 3b-2
> and 3b-3 are **not started**.

## 4. Merged baseline (Done — verify via `git log main`)

- **Wave 1 — provider fail-closed** (audit P0-1), T-012, PR #15 (`15384cb`): `resolve()→Result`, no silent governed→ungoverned fallback; ungoverned only via `BROPS_ALLOW_UNGOVERNED=1`.
- **Wave 2a — webview message provenance** (audit P1-6), T-013, PR #16 (`d85dcba`): `WEBVIEW_MESSAGE_ROLES` restricted to `["user"]`; server-held answer via one-time `result_id`.
- **T-010 — Tauri capability boundary**, PR #19 (`7d537c3`): deny-by-default capability manifest over all 65 commands; the 4 L2 hard-delete commands DENIED; CI invariant `tools/check_capabilities.py`. Zero-trust GREEN.
- **T-011 — durable approval + native confirmation**, PR #20/#21 (merge `7638a64`): migrations 0012 (approval provenance) + 0013 (execution claim). Restart-safe self-approval by durable `origin_principal`; native-only approval authority; nonce compare-and-consume; canonical `RunExecutionScope` digest; atomic pre-dispatch execution claim; crash-recovery reconciliation; strict attempt ownership; enforced single-instance file lock. Zero-trust GREEN through multiple rounds.
- **Wave 3 Receipt Protocol v1 — design rev 4**, PR #23 (`35a6ab5`): Architect + Owner **GREEN**, merged. The design is the spec Wave 3a/3b implement.
- **Wave 3a slice 1 — receipt protocol core** (T-014), PR #24 (approved HEAD `c51031e`, **merge commit `6c920d0`**): `brops-core::receipt` — the pure verifier core (§5). Zero-trust GREEN after three RED rounds (§6).
- **Wave 3a slice 2 — receipt storage & atomicity** (T-015), PR #26 (approved HEAD `64c2372`, **merge commit `9b214e5`**): migration **0014** + `brops-core::receipt_store` — the durable, atomic `verify→consume→persist` layer on the slice-1 core (`issue_challenge`, one-time nonce, `receipt_id` uniqueness, freshness/skew, `ON DELETE RESTRICT` evidence, tri-state outcome with no "Verified"). Zero-trust GREEN after a YELLOW + two RED rounds (see the T-015 row in `TASKS.md`).
- **Wave 3a slice 3 — transport wiring + receipt trust UI** (T-016), PR #28 (approved HEAD `dee6661`, **merge commit `8a580028`**): the desktop CALLS the merged verifier on a real governed turn — `ai::PreparedGovernedTurn` single source, structured `system`+`history` bridge authority, `commands.rs` `issue_challenge`→`verify_and_record_receipt(&NoTrustedManifest)`→`StreamEvent::Blocked` notice (no double-post), `receipt_store::{record_pre_verification_block, bounded_reason}`, `Message.receipt` projection + dev/blocked badges, JCS cross-language parity + e2e. Fail-closed strict 3a. Zero-trust GREEN after a YELLOW + two RED rounds (see the T-016 row in `TASKS.md`). **Wave 3a complete.**
- **Schema:** migrations through **0014**, `SCHEMA_VERSION = 14`. Test suites: `brops-core` **89**, host `brops` **42**, bridge **35** py, frontend **6** — green.

## 5. What IS implemented — slice 1 (PR #24) + slice 2 (PR #26)

**Slice 1 — `brops-core::receipt`** — the **pure, I/O-free protocol core** (design §2, §2.3, and the pure subset of §3, §6):

- RFC 8785 (JCS) canonicalization for the receipt + canonical **request** envelope (§2, §2.2).
- Wire format + strict decode (§2.3): base64url → exact bytes (**64 KiB cap**), UTF-8, **duplicate-key** + **unknown-field** + **non-string-value** rejection, fixed field set/types, lowercase-64-hex hashes, numeric timestamps, `decision` domain, and **`JCS(parsed) == decoded bytes`** (parser-differential defense).
- **Verify-only** Ed25519 (`verify_strict`) over the decoded bytes, via a **type-state chain**: `parse_strict → Parsed` (exposes only `key_id`) → resolve the manifest key → `verify(&ResolvedManifestKey, sig)` (enforces `parsed.key_id == resolved_key.key_id`) → `Verified` (carries the signed `trust_class`) → `bind(&Expected, output)` → `BoundReceipt` → `resolve_3a()`. `ResolvedManifestKey` has **private fields + no public constructor** (only an in-crate validated resolver mints one).
- The pure §3 binding subset: protocol, `decision == completed`, identity/policy/config **expected-value** matches, allowed executor/builder, output-bytes re-hash (§2.1). The request half is a single `IssuedRequest` from which `bind` **recomputes** `request_sha256` (never a separate supplied hash), so hash and per-field bindings can't diverge.
- Trust-state gate (§6): `resolve_3a()` returns a **`Wave3aTrustState { DevelopmentUntrusted, Blocked }`** — a type with **no `TrustedVerified` variant**, so Wave 3a code cannot name a "Verified" state anywhere; `production ⇒ Blocked`.
- **Verify-only in production**: the Ed25519 *signing* half is compiled solely under `#[cfg(test)]` — the desktop core is never a `sign(arbitrary_bytes)` oracle (design §1).

**Slice 2 — `brops-core::receipt_store`** — the durable, atomic storage layer (design §3 stateful subset + §4), merged in PR #26:

- **Migration 0014** (`SCHEMA_VERSION` 14): `receipt_challenges` (durable one-time nonce; `request_sha256` NOT-NULL+hex, compared in-tx to `expected.request.request_sha256()`), `receipt_verification_attempts` (capped raw `wire_*` + decoded envelope/signature + tri-state `outcome`; `message_id` real FK **`ON DELETE RESTRICT`** with the full accepted⇔message / blocked⇔no-message CHECK), `receipt_ids_seen` (accepted-only uniqueness ledger).
- **`verify_and_record_receipt`** — one `BEGIN IMMEDIATE` **verify → consume → persist**: consume the desktop nonce, run the slice-1 pipeline, apply the stateful gates (`receipt_id` unseen, two-timestamp freshness/skew), then persist. A **blocked verdict commits its evidence**; only a real SQLite failure returns `Err` (with an explicit rollback); a **nested (non-owning) transaction is rejected**. `issue_challenge(conn, conversation_id, &IssuedRequest, now_ms)` derives nonce+hash from one source.
- **`ReceiptOutcome`** has **no `TrustedVerified` variant** (production ⇒ `Blocked`); deleting a conversation/message with governed evidence is **refused** so the output stays re-verifiable. Verified by a **real two-thread `Barrier` race** (one accept + one block, both evidence rows).
- **83 core tests** total (slice 1 + slice 2 negative-matrix), clippy-clean.

## 6. Zero-trust audit history — RESOLVED (slices 1 + 2 are GREEN + merged)

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

## 7. Wave 3a slice 2 (receipt storage & atomicity) — DONE, merged (the followed plan)

> **Status: DONE and merged** — PR #26, squash **merge commit `9b214e5`** on `main`, zero-trust GREEN.
> The steps below are the design §3 (stateful items) + §4 plan the implementation followed; they are
> retained as the spec/record. The next task is **slice 3** (transport + UI), see §3.

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
cargo test -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml   # 83 tests
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

**Wave 3a is complete** — slices 1 + 2 + 3 merged (durable nonce issue/consume, `receipt_id` uniqueness,
wall-clock freshness/skew, migration 0014, atomic verify→consume→persist, `receipt_verification_attempts`,
**and** the desktop transport wiring + structured bridge contract + receipt trust UI + JCS parity + e2e —
all **done**, §5). Still deferred to **Wave 3b**:

- **Wave 3b** — the isolated trusted signer (real key custody, not a `sign(arbitrary_bytes)` oracle) +
  operator-provisioned signed key manifest + binary-pinned root anchor; manifest **loading + signature
  verification**; key validity window / epoch / revocation; manifest **anti-rollback**. It fills the
  `ReceiptKeyAuthority` seam (today `NoTrustedManifest` ⇒ Blocked); only 3b enables production
  **`trusted_verified`** ("Verified").

Beyond Wave 3: Wave 4 (supervisor hardening, engine P0-4), Wave 5 (trusted sidecar, P0-3), production CI/release (P0-6), then the product roadmap phases (`MASTER_EXECUTION_ROADMAP.md`).

## 11. Handoff rule (keep this file true)

Every approved decision made in a Claude/ChatGPT chat must be written into the canonical repo docs **in the same commit** as the change it authorizes — `NEXT_CHAT.md`, `PROJECT_STATE.md`, `TASKS.md`, and any design/security doc it touches. A new chat must be able to continue correctly from GitHub alone. The chat is never the record.
