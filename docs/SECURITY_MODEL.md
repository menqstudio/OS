# OS Security Model

Status: **pre-production. The shipped app is fail-closed and never renders production `trusted_verified`.**
This document is the single narrative for the trust boundary, the current posture, the audit findings, and
exactly what must land before the production "Verified" gate can flip. It is honest by construction: where a
guarantee is not yet real, it says so.

## 1. The trust boundary

A live AI turn is `trusted_verified` only when a full governed chain runs behind the wall and the desktop
independently verifies a signed receipt:

```
offline ROOT (private, held by the operator, never on the serving box)
  └─ signs the key manifest  ──▶ TCB-pinned ROOT PUBLIC key (compiled into the broker, tcb.rs)
        challenge-authority ─▶ governed-supervisor (lease + attest) ─▶ isolated-signer (Ed25519)
              └─ receipt {envelope_jcs_b64, signature_b64}  ──▶ DESKTOP verify_and_accept
                    (recompute JCS, verify_strict, bind request+output+attestation, one-time nonce)
                          └─ resolve_trust_state ─▶ trusted_verified  (production key, non-revoked, in-window)
```

Invariants that HOLD today (verified by the 2026-08-04 builder audit — `apps/desktop/src-tauri/win-live/proof/BUILDER_AUDIT_VERDICT_2026-08-04.md`):

- **No fresh production forgery without the offline root.** The production root pin is compiled in (never read
  from config); a demonstration-root-signed manifest is rejected; `verify_strict` rejects malleable/short
  signatures; the demo-pinning constructors are `pub(crate)`.
- **Output→receipt binding is airtight.** The bytes hashed == signed == committed == the executor's stdout.
- **The root private is never written to the serving box** (`config.json root_seed=""`).
- **The desktop is the verification authority** — the bridge/receipt carries signed material only; there is
  **no wire `verified` boolean** (`bridge/contracts/bridge-result.schema.json`).
- **Server-side peer-SID gate** on every named pipe is fail-closed and kernel-attested.

## 2. Current posture — FAIL-CLOSED (shipped)

`platform_governed_execution_supported()` is **false**; `main()` keeps `UpstreamBlockedExecutor`; live turns run
under `NoTrustedManifest` and Block. The **only** wired chain path is the owner-visible self-test
(`governed_trust_selftest`), which runs the real crypto under a **compiled-in demonstration anchor** and reports
`demonstration_custody: true` — it never flips live turns. The UI shows a distinct "DEMONSTRATION CUSTODY" badge.

**Production custody has been proven once, locally** (2026-08-04): the operator's real offline root signed a
manifest the TCB pin accepted, and a full `win_live_turn` over real named pipes reached
`trusted_verified … production_verified=true bound=true` under the real root. That is the honest graduation from
demonstration custody — but it is a local proof, **not** the shipped badge.

## 3. Builder audit (2026-08-04) — findings and disposition

Owner-designated builder-side adversarial audit, 5 independent reviewers. Verdict: **NOT GREEN, central
guarantee HOLDS.** This is builder evidence, **not** the independent Architect verdict (`CURRENT_CODE_AUDIT:
ARCHITECT_PENDING`).

- **P0-2 pipe squat + broker impersonation — FIXED.** Client connects with `SECURITY_SQOS_PRESENT |
  SECURITY_IDENTIFICATION`; server creates with `FILE_FLAG_FIRST_PIPE_INSTANCE`.
- **P0-1 anti-rollback floor — CORRECTED (honesty).** `FLOOR_SEED_HEX` is a public source constant, so the
  floor signature is a corruption check, **not** the anti-rollback boundary. The real boundary is the OS
  write-ACL on the deployment dir (broker-principal-only). Full closure (ACL enforcement + per-deploy sealed
  floor key + TPM monotonic counter) is specified in `win-live/WINDOWS_ANTIROLLBACK_HARDENING.md`.
- **demonstration_custody (UI) — FIXED.** The self-test can no longer be read as production trust.
- **Open, gated:** executor emits a placeholder (not a real model answer); containment (restricted token /
  image verify) is not wired to the live executor spawn; serving-seed plaintext TOFU window; receipt/attest
  `key_usage` not manifest-encoded.

## 4. Residual engine items (O-1 … O-5)

Tracked on Bro's `fix/audit-followups`; each is its own audited engine task (never rushed).

- **O-1 (HIGH)** — bytecode-shadow: `assert_no_bytecode_shadow` has no caller and the wall is not run with `-B`.
- **O-2 (MED)** — audit-head anchor is dead code.
- **O-3 (MED)** — conductor session token is off by default.
- **O-4 (LOW)** — control-room actor is self-asserted.
- **O-5 (LOW)** — evidence high-water is not bound into the signed manifest.

## 5. What must land before the production "Verified" gate flips

All of the following, then an **independent** audit, then **Owner** approval:

1. **Executor → real model** — the contained executor invokes the model and emits its exact output (today a
   placeholder), then re-provision the pinned executor SHA.
2. **Wire the live chain into the shipped runtime** — route through the broker/manifest; retire
   `UpstreamBlockedExecutor`; select `GovernedEngine` with a real `ManifestReceiptKeyAuthority`.
3. **Session-0 isolation** — broker as its own dedicated service account, `CreateProcessAsUser` under a
   restricted token + `STARTUPINFOEX` handle list wired to the output-producing spawn, CNG key custody.
4. **Anti-rollback real closure** — provisioning-enforced deploy-dir ACL + per-deploy sealed floor key + TPM
   monotonic counter.
5. **O-1 … O-5** closed or owner-signed-deferred.
6. **Independent Architect CODE-audit** on the exact head + **Owner approval**.

Until every item above is real, the gate stays false and the app fails closed. **The badge is never faked.**
