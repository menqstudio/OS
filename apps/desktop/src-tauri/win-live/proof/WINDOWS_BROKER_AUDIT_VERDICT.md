# Windows governed-turn broker — independent audit verdict

Scope: `brops-win-live` (the Windows LIVE governed-turn kit) + `brops-win-broker` + the `brops-core`
verification core it depends on. This is the independent zero-trust audit standing in for the external
Architect gate (Owner-directed). It reflects **three** independent adversarial agent passes plus a
builder review, over the branch `feat/windows-broker-machineproof`.

## VERDICT: GREEN — for the shipped fail-closed posture and the crypto-verification core

Nothing an in-scope adversary can do forges a production `trusted_verified`, and the shipped desktop app
stays fail-closed on Windows (it does not even link this kit). The Windows governed gate
(`platform_governed_execution_supported()`) correctly stays **false**; this kit is a proven, audited
slice, not a shipped path.

### Why nothing in scope can forge `trusted_verified`
The only gate is `brops_core::governed_verification::verify_and_accept`, reached only through
`GovernedChain::run_verified`; only its `Ok` commits a message. Every trust anchor is the broker's OWN
resolution, never a hop reply:
- **Renderer / sidecar (untrusted):** cannot reach any pipe — each server authenticates the kernel-attested
  peer SID (`ImpersonateNamedPipeClient`) and gates on the allowed broker SID before dispatch.
- **Compromised challenge-authority:** `verify_and_accept` recomputes `request_sha256` from the broker's own
  `Expected` and requires equality — attacker facts ⇒ Block.
- **Compromised supervisor:** the isolated signer re-derives all six `*_sha256` from the content-addressed
  store and the broker cross-binds the output bytes to `output_sha256` and `request_sha256` to `Expected` —
  a substituted output ⇒ `CommitReadbackMismatch`. And `attest-run` is bound one-time to a lease the
  supervisor itself minted (R3).
- **Compromised isolated-signer:** can forge — it legitimately holds the receipt key; that is the trusted
  principal isolation is meant to protect (compromising it is compromising a root CA, not an "in-scope
  single principal" break).
- `production_trust::resolve_trust_state` binds "Production" to the exact key `verify_and_accept` verified
  under, so a manifest `key_id` with an attacker public key cannot decouple the verdict.

### Findings — all closed
| Finding | Status |
|---|---|
| P1-a TCB root pin (root from `crate::tcb`, never config; disagreeing config root refused) | CONFIRMED-CLOSED |
| P1-b production `ManifestResolver` inside acceptance (feeds the pinned key `verify_and_accept` uses) | CONFIRMED-CLOSED |
| P2 anti-rollback floor persisted atomically | CONFIRMED-CLOSED |
| R1 anti-rollback floor is TCB-signed (self-contained signed `floor.json`; reset/tamper/forged-sig rejected on load; unit-tested) | CONFIRMED-CLOSED |
| R2 supervisor-attestation key resolved through `resolve_production_key` (class/window/revocation enforced) | CONFIRMED-CLOSED |
| R3 `attest-run` bound to a supervisor-minted `accept-open` lease (one-time consume) | CONFIRMED-CLOSED |
| A root PRIVATE key no longer written to the serving box (`keys/root.seed` removed) | CLOSED |
| D floor persisted as ONE self-contained signed file (single atomic rename; no json/sig desync) | CLOSED |
| Seed custody | per-user DPAPI seal-on-first-use; seeds not plaintext at rest; sound + fail-closed |
| Restricted-token executor launch | real (`CreateRestrictedToken` + `verify_restricted_token` hard-fails the launch) |
| Shipped honesty | app does not link the kit; Windows gate false; nothing flips a shipped gate |

## Conditions BEFORE the Windows governed gate may ever be flipped to `true` (not shipped today)
These are honest limitations of a software-only proof kit; the gate stays closed until they are met:
1. **Production key custody model — ROOT DONE.** The TCB (`tcb.rs`) now compiles in ONLY the root PUBLIC key
   (`ROOT_PUBLIC_KEY_HEX`); the root PRIVATE key is supplied by the operator from an offline location
   (`win_provision --root-key`), which must match the pinned public, and is never written to the serving box
   (proven: `keys/root.seed` no longer exists; the turn still reaches `trusted_verified`). REMAINING for full
   custody: give the runtime floor-integrity key real TCB-only custody (it is still a compiled-in constant —
   lower risk than the root, and covered defence-in-depth by condition 3's broker-only-writable floor).
2. **Dedicated least-privilege broker principal — DONE.** The broker now runs as a dedicated **non-SYSTEM**
   service account (`brops-broker`), NOT SYSTEM, so it cannot read the signer service's memory / DPAPI seed,
   and `allowed_broker_sid` is that account's exclusive SID. Proven: the full cross-account turn with the
   broker as `brops-broker` and the three servers as their own accounts reaches `trusted_verified`. This
   required building the win-live bins with **`-C target-feature=+crt-static`** — the earlier `0xC0000142`
   (`STATUS_DLL_INIT_FAILED`) was the debug-CRT DLL dependency a limited session-0 service account could not
   load; a static CRT removes it. (Deployment note: build the Windows kit with `+crt-static`.)
3. **Replay-proof anti-rollback — closed vs the in-scope (login-user) adversary; TPM for the admin case.**
   The floor lives in the broker-writable deployment root; the deploy ACL grants write only to the broker
   principal and denies the interactive login user, so the config-dir adversary cannot restore an old signed
   `floor.json` (combined with `floor.sig` tamper-evidence). A full admin/SYSTEM compromise can still reset
   any file — defeating any software custody — so hardware monotonic/TPM-backed freshness remains the answer
   for that (explicitly out of scope, same class as "admin defeats DPAPI").

Bottom line: **for the question the gate actually asks — can anything in scope forge a shipped
`trusted_verified`? — the answer is no.** The kit is GREEN as an audited proof, and the enablement path is
now proven end-to-end: conditions **1 (offline-root manifest signing)** and **2 (a dedicated non-SYSTEM
`brops-broker` principal)** are DONE, and **3** is closed against the in-scope login-user adversary via an
ACL-protected, TCB-signed floor — all reaching `trusted_verified` cross-account with three distinct
service-account principals. What remains is deployment/hardware-class only: the runtime floor-integrity key
custody sub-item and TPM/monotonic anti-rollback for the admin-compromise case — plus, separately, the Owner
decision to flip the shipped gate and wire the live chain into the desktop runtime.
