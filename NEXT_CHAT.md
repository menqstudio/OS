# NEXT_CHAT — definitive handoff · վերջնական handoff

> **⏭️ CURRENT ACTIVE (2026-08-06): PR #54 · branch `fix/release-setup-node-pin`** (base `main`, task T-017) — a supply-chain hotfix against `main`. The release workflow pinned `actions/setup-node` to a SHA that does not exist in that repository, so it could not resolve its own action; it is re-pinned to the real v4.1.0 commit and `tools/check_action_pins.py` (11 self-tests, wired as the supply-chain `action-pins` job) now fails the build on any unresolvable or unpinned action reference instead of leaving it to be discovered at release time. It also carries the two supply-chain remediations `main` still lacks — the `undici` ^7.29.0 override clearing the un-waived high npm advisory, and the three triaged `cryptography` X.509/PKCS#7 waivers for surfaces the engine's Ed25519-only usage never reaches — so the PR is green on its own base rather than waiting on PR #53. PR #53 (`feat/windows-broker-machineproof`) remains the larger keystone workflow; the handoff below is ITS handoff and is unchanged by this hotfix.

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
> Tokens (validated against `config/current_state.json.status_tokens`): `CURRENT_ACTIVE_TASK: T-017` · `CURRENT_ACTIVE_WAVE: 3b-1B` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: GREEN` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: GREEN` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

> **Consolidation note (T-017 / Wave 3b):** the whole Wave 3b workflow — the 3b-1A boundary code, the 3b-1B design addendum, the 3b-1B/3b-2/3b-3 implementation, the live-proof kit, and the 22-page cockpit — is now **consolidated on branch `feat/cockpit-pages`**, **PR #48** (base `chore/main-resync`, head `38d5d715…`). This supersedes the earlier split (PR #46 impl / PR #31 design / PR #32 impl). PR #48 is the snapshot's **current_workflow_pr**, a **self-carrier** exact-head-anchored by its PR-body **`AUDIT_CANDIDATE_HEAD`** marker (event head == live headRefOid == marker; nothing is exempt).
> - **Design: `CURRENT_DESIGN_GATE: GREEN`.** The 3b-1B design is **Architect DESIGN GREEN at `CURRENT_DESIGN_CANDIDATE: rev-30`** (relayed by the Owner) — this supersedes the stale rev-27 RED / rev-28 pending history below. **Design-GREEN is NOT code-GREEN.**
> - **Code audit: `CURRENT_CODE_AUDIT: ARCHITECT_PENDING`.** Three independent adversarial security passes **converged** — 10 → 6 → 1 P1, **ALL fixed**; trust-boundary / chain / manifest **CLEAN**. That is the **BUILDER's evidence**; the external **Architect CODE-audit gate is still pending** — do **NOT** claim Architect code-GREEN.
> - **Live proof: `CURRENT_LINUX_E2E: proven`.** The **FULL 7-service production governed turn ran GREEN on real Linux** — the **FIRST production `trusted_verified` proven live** (real service accounts, real setuid launcher → executor, real ed25519 keys + root-signed manifest, `verify_and_accept`). **3b-2** (signed manifest / anti-rollback) and **3b-3** (production trust resolver) are **implemented + wired in the live kit** (`engine/ci/live/run_live_turn.sh`).
> - **Shipped app honesty: `CURRENT_PRODUCTION_VERIFIED: false`.** The SHIPPED desktop app's production "Verified" is **STILL fail-closed** — `main()` keeps `UpstreamBlockedExecutor`; the live chain is proven in the live kit, **not yet wired into the desktop runtime**. The chain is proven live, but the shipped app cannot render production `trusted_verified` yet.
> - **Cockpit:** the 22-page cockpit is **built + wired to real backends; app functional.**
> - **Next permitted action:** obtain the **Architect CODE-audit GREEN** on PR #48's exact head, then wire the live-proven trust chain into the shipped desktop runtime (retire `UpstreamBlockedExecutor` in `main()`) to enable production `trusted_verified`. Do **NOT** merge or expose "Verified" before Architect code-GREEN + Owner approval.
>
> The narrative below is the accurate 3b-0 design-review HISTORY (rev 1→5); it ends at the 3b-0 gate. Read the block above for the current reality.

<!-- HISTORY_BEGIN -->
**Wave 3a is COMPLETE — slices 1, 2 AND 3 are DONE and merged.** **Wave 3b DESIGN-FIRST history** — its **3b-0 design** was reviewed and **MERGED via PR #30** (merge commit `df3c0ac`); the design lived on `design/wave-3b-isolated-signer` ([`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md)). **Architect design RED ×2 (rev 1 `6a6882e` = 4 P0; rev 2 `9801489` = 2 P0 + 3 P1); rev 3 closes them all.** rev 3 locks: the **supervisor builds evidence itself from `{run_id, execution_attempt_id}`** — no `attest(caller_evidence)` oracle anywhere and a single topology (the signer's only peer is the supervisor over direct ACL'd IPC; the sidecar never connects to the signer); a **content-addressed protected evidence store** so containment + large inputs bind to real artifact bytes, not a hashed reference; **one fixed 256 KiB IPC frame** with large inputs as handles (no inline); the resolver query sourced from the **trusted `Expected`/turn** (only `key_id` from the unsigned receipt); and the manifest floor **plus exact canonical bytes persisted atomically** with semantic-uniqueness rejects + signed-in `root_key_id`. **Architect design YELLOW on rev 3 (`fa1b8cb`, CI #96 green) — architecture approved (no new P0); rev 4 closes 5 contract redlines:** per-artifact canonical-bytes table pinned to the merged desktop formulas + all-formula parity (P1-1), the nonce schema fixed to the merged UUIDv4 `brops_core::id()` not `hex(32B)` (P1-2), a durable forensic-attestation record in `sign-result` + containment bytes via the bridge result (P1-3), the supervisor process split/service/ACL/store/IPC reclassified **BUILD** (only `bro_supervisor.py` logic is reused; the live path still spawns `engine_sidecar.py` with fail-closed placeholders) + 4 same-login-user isolation acceptance tests (P1-4), and the protected-store atomic publish algorithm (P1-5). **Architect design YELLOW on rev 4 (`73ff0f7`) — architecture confirmed; rev 5 closes the final signed-key-authority contract:** the desktop resolves the **supervisor-attestation key from the root-signed manifest snapshot** (not signer config, which the desktop can't trust) via an explicit `key_usage: receipt_signing | supervisor_attestation` discriminator, with **total type separation** — two disjoint in-tx resolvers so a receipt key can never verify an attestation and an attestation key can never render "Verified" — plus the attestation-key negative matrix. **✅ Architect DESIGN GREEN on rev 5 (approved HEAD `def7711`, exact-head CI #98 success) — the 3b-0 design gate is PASSED (no open P0/P1).** Per the Architect verdict, 3b implementation may begin **only after Owner approval**; the 3b-1 stop condition stays mandatory (`NoTrustedManifest` unchanged, no production "Verified" exposed), and the first `trusted_verified` is allowed only after the full 3b-1→3b-2→3b-3 chain is exact-head zero-trust GREEN. **[SUPERSEDED — see the CURRENT STATE block above: PR #30 is MERGED (`df3c0ac`); 3b-1 is underway as PR #31 (3b-1A Code GREEN + 3b-1B rev-26 design candidate PENDING re-audit — the RED verdicts above were on the EARLIER 3b-0 revs 1–2, not rev-26) with WIP implementation in PR #32.]** (Owner directive: the private-key custody boundary IS the trust boundary — no rushing the engine perimeter.) Slice 3 (T-016, PR #28, approved HEAD `dee6661`, squash **merge commit `8a580028`**) wired the desktop to CALL the merged verifier on a real governed turn (fail-closed strict 3a: every governed turn Blocks until Wave 3b provisions a trusted key), through the `ReceiptKeyAuthority` seam, a single `PreparedGovernedTurn` source, exact structured `system`+`history` as the bridge signing authority, buffered `governed_turn`, a turn-level Blocked notice with no double-post, dev/blocked badges, JCS cross-language parity, and bounded transport-failure evidence. Zero-trust GREEN after a YELLOW + two RED rounds; final CI 7/7 GREEN.
<!-- HISTORY_END -->
> _(The authoritative present-tense state is the CURRENT STATE block in §3 above. The narrative above is 3b-0 design-review history.)_

| | |
|---|---|
| **Active PR / branch / task** | **PR #48** (`feat/cockpit-pages`, base `chore/main-resync`, head `38d5d715…`) — the consolidated Wave 3b snapshot for **task T-017**. Self-carrier; exact-head anchored by its PR-body `AUDIT_CANDIDATE_HEAD` marker. |
| **Next task** | **Architect CODE-audit** of the consolidated implementation on **PR #48** at its exact head (`CURRENT_CODE_AUDIT: ARCHITECT_PENDING`), then **wire the live-proven trust chain into the shipped desktop runtime** (retire `UpstreamBlockedExecutor` in `main()`) to enable production `trusted_verified`. The 3b-1B design is already `CURRENT_DESIGN_GATE: GREEN` at `CURRENT_DESIGN_CANDIDATE: rev-30`. Design-GREEN is NOT code-GREEN: do **not** merge or expose "Verified" before Architect code-GREEN + Owner approval. |
| **Proven live** | The **full 7-service production governed turn ran GREEN on real Linux** — the first production `trusted_verified` proven live (`CURRENT_LINUX_E2E: proven`, via `engine/ci/live/run_live_turn.sh`). 3b-2 (signed manifest / anti-rollback) + 3b-3 (production trust resolver) are implemented + wired in the live kit. The **shipped desktop app stays fail-closed** (`CURRENT_PRODUCTION_VERIFIED: false`) until the live chain is wired into the desktop runtime. |
| **Merged baseline** | Prior merged history (durable): **PR #30** — Wave 3b-0 isolated-signer DESIGN GREEN (`df3c0ac`); Phase 0 repository-truth remediation merged (`b6c6712`); **T-016 / slice 3 — PR #28** (`8a580028`) wired the desktop verifier into a real governed turn. The earlier split PRs (#46 impl / #31 design / #32 impl) are **superseded by PR #48**. See `config/current_state.json`. |

> **Wave 3a is COMPLETE** — slices 1, 2, 3 all GREEN + merged (`git log main` → `6c920d0`, `9b214e5`, `8a580028`).
> The desktop issues a nonce challenge, runs the governed turn buffered, and verifies the signed receipt.
> **Current reality (do NOT flatten to "not implemented" OR to "done"):** the 3b-1B design is
> `CURRENT_DESIGN_GATE: GREEN` at `rev-30`; the 3b-1B/3b-2/3b-3 implementation is **consolidated on
> `feat/cockpit-pages` (PR #48)** and the full chain is **proven live on Linux** (`CURRENT_LINUX_E2E:
> proven`) — the first production `trusted_verified` ran end-to-end. **But** the external Architect
> CODE-audit is still pending (`CURRENT_CODE_AUDIT: ARCHITECT_PENDING`), and the **shipped desktop app's
> production "Verified" remains fail-closed** (`CURRENT_PRODUCTION_VERIFIED: false` — `main()` keeps
> `UpstreamBlockedExecutor`; the live chain is not yet wired into the desktop runtime). The 22-page
> cockpit is built + wired to real backends.

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
