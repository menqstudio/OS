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

| | |
|---|---|
| **Active task** | **T-014 — Wave 3a Receipt Protocol v1, slice 1 (pure protocol core)** |
| **Branch** | `feat/wave-3a-receipt-protocol` |
| **PR** | **#24** — OPEN, **merge-BLOCKED** |
| **Branch HEAD** | `aa4dc01` (round-2 fixes) |
| **Last *audited* HEAD** | `a873501` — verdict **RED / REQUEST CHANGES** |
| **CI on the PR** | 7/7 GREEN — *but CI GREEN ≠ security-audit GREEN* |
| **Merge status** | **BLOCKED — awaiting the Architect's zero-trust re-audit of `aa4dc01`** |

> **Honesty note:** `a873501` was audited **RED** (4 authority-API blockers, below). `aa4dc01`
> was pushed to address all four **in code**, but it has **not yet been re-audited** — there is
> **no GREEN verdict** on `aa4dc01`. Treat the blockers as *addressed-pending-verification*, not
> resolved. **Do not merge PR #24** until the Architect returns GREEN on the exact re-audited HEAD.

## 4. Merged baseline (Done — verify via `git log main`)

- **Wave 1 — provider fail-closed** (audit P0-1), T-012, PR #15 (`15384cb`): `resolve()→Result`, no silent governed→ungoverned fallback; ungoverned only via `BROPS_ALLOW_UNGOVERNED=1`.
- **Wave 2a — webview message provenance** (audit P1-6), T-013, PR #16 (`d85dcba`): `WEBVIEW_MESSAGE_ROLES` restricted to `["user"]`; server-held answer via one-time `result_id`.
- **T-010 — Tauri capability boundary**, PR #19 (`7d537c3`): deny-by-default capability manifest over all 65 commands; the 4 L2 hard-delete commands DENIED; CI invariant `tools/check_capabilities.py`. Zero-trust GREEN.
- **T-011 — durable approval + native confirmation**, PR #20/#21 (merge `7638a64`): migrations 0012 (approval provenance) + 0013 (execution claim). Restart-safe self-approval by durable `origin_principal`; native-only approval authority; nonce compare-and-consume; canonical `RunExecutionScope` digest; atomic pre-dispatch execution claim; crash-recovery reconciliation; strict attempt ownership; enforced single-instance file lock. Zero-trust GREEN through multiple rounds.
- **Wave 3 Receipt Protocol v1 — design rev 4**, PR #23 (`35a6ab5`): Architect + Owner **GREEN**, merged. The design is the spec Wave 3a/3b implement.
- **Schema:** migrations through **0013**, `SCHEMA_VERSION = 13`. `brops-core` test suite: **68 tests** green.

## 5. Current slice — what IS implemented (PR #24)

`brops-core::receipt` — the **pure, I/O-free protocol core** (design §2, §2.3, and the pure subset of §3, §6):

- RFC 8785 (JCS) canonicalization for the receipt + canonical **request** envelope (§2, §2.2).
- Wire format + strict decode (§2.3): base64url → exact bytes (**64 KiB cap**), UTF-8, **duplicate-key** + **unknown-field** + **non-string-value** rejection, fixed field set/types, lowercase-64-hex hashes, numeric timestamps, `decision` domain, and **`JCS(parsed) == decoded bytes`** (parser-differential defense).
- **Verify-only** Ed25519 (`verify_strict`) over the decoded bytes, via a **type-state chain**: `parse_strict → Parsed` (exposes only `key_id`) → resolve the manifest key → `verify(&ResolvedManifestKey, sig)` (enforces `parsed.key_id == resolved_key.key_id`) → `Verified` (carries the signed `trust_class`) → `bind(&Expected, output)` → `BoundReceipt` → `resolve_3a()`.
- The pure §3 binding subset: protocol, `decision == completed`, identity/policy/config **expected-value** matches, `requested_at` **exact** desktop-issued binding, allowed executor/builder, output-bytes re-hash (§2.1).
- Trust-state machine (§6): `resolve_3a()` **hard-codes** `production ⇒ Blocked` — Wave 3a **never** yields `trusted_verified`.
- **Verify-only in production**: the Ed25519 *signing* half is compiled solely under `#[cfg(test)]` — the desktop core is never a `sign(arbitrary_bytes)` oracle (design §1).
- **68 core tests** (full negative-test matrix), clippy-clean.

## 6. Current zero-trust blockers (from the RED on `a873501`) — full text

All four were addressed in `aa4dc01`; each still needs the Architect's re-audit to confirm.

1. **`key_id` not cryptographically bound to the passed key.** `Parsed::verify()` took a raw public key and did not enforce that the key + trust class come from the manifest entry for the envelope's claimed `key_id`. → *Addressed in `aa4dc01`:* introduced `ResolvedManifestKey { key_id, public_key, trust_class }`; `verify` requires `parsed.key_id == resolved_key.key_id` before the signature check (`KeyIdMismatch`); `Verified` carries that entry's `trust_class`; the raw-key convenience is now `#[cfg(test)]`-only.
2. **Trust state not bound to a verified+bound receipt.** A standalone public `resolve_trust_state(class, production_allowed)` could be called without verification/binding, and its caller-controlled bool let 3a emit `TrustedVerified`. → *Addressed:* removed it; trust state is reachable only via `BoundReceipt::resolve_3a()`, which hard-codes `production ⇒ Blocked` (no switch); the `trusted_verified` path is deferred to an audited Wave 3b change.
3. **`requested_at` not bound to the desktop request timestamp.** Only `requested_at <= completed_at` was checked; the receipt's `requested_at` could diverge from the value hashed into `request_sha256`. → *Addressed:* added `Expected.requested_at` with exact-equality binding (§3.8); `completed_at` stays signer-produced under the time-order check.
4. **Contract leak — `Parsed` derived `Debug`** printed private fields, contradicting "only `key_id` readable pre-verification". → *Addressed:* redacted manual `Debug` on `Parsed`/`Verified`/`BoundReceipt` (ids + byte length only); a test asserts no binding value leaks.

**Test corrections required by the RED (done in `aa4dc01`):** the mismatch matrix now covers all 13 expected-value bindings (every hash field + `requested_at`); added tests for claimed-`key_id` ≠ resolved-`key_id`, production key ⇒ `Blocked`, trust resolution reachable only from `BoundReceipt`, and Debug redaction.

## 7. Exact next action

1. **Get the Architect's re-audit verdict on `aa4dc01`** (PR #24).
   - **RED/YELLOW** → fix on `feat/wave-3a-receipt-protocol`, push, re-request audit. Do **not** merge.
   - **GREEN** → Owner merges PR #24; flip T-014 → Done in `TASKS.md` + `PROJECT_STATE.md` (same commit); then start **slice 2**.
2. **Slice 2 (after slice 1 is GREEN + merged)** — the stateful storage layer (design §3 stateful items + §4): migration **0014** (`receipt_verification_attempts` + durable one-time nonce state + `receipt_id` global-uniqueness), the **atomic verify → consume → persist** transaction, tri-state outcome storage (accepted → `messages`, blocked → attempts only), and wall-clock freshness/skew.

## 8. Verify commands (Windows box)

```bash
# Rust data core (⚠ run cargo from PowerShell, NOT the Bash tool — see CLAUDE.md §5)
cargo test -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml   # 68 tests
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
