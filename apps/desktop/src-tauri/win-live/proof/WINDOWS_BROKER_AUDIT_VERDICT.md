# Windows governed-turn broker — independent audit verdict

Scope: `brops-win-live` (the Windows LIVE governed-turn kit) + `brops-win-broker` + the `brops-core`
verification core it depends on. This is the independent zero-trust audit standing in for the external
Architect gate (Owner-directed). It reflects **three** independent adversarial agent passes plus a
builder review, over the branch `feat/windows-broker-machineproof`.

> # CORRECTIONS — 2026-08-10 (remediation audit **R-19**)
>
> R-19 was "the Windows audit verdict document asserts two facts that the code at this commit
> contradicts". It was still true four days later, and re-checking turned up two more. A GREEN verdict
> that overstates what the code does is the same defect as a check that cannot fail: something
> displayed that nothing established. The false sentences are left below **struck through in prose**
> rather than deleted, because this file is a record and a document that quietly repairs itself is
> worse than one that is wrong out loud.
>
> **1. "it does not even link this kit" — FALSE.** `apps/desktop/src-tauri/Cargo.toml` carries
> `[target.'cfg(windows)'.dependencies] brops-win-live = { path = "win-live" }`, and TWO shipped
> `#[tauri::command]`s call into it: `governed_selftest.rs::governed_trust_selftest` and
> `commands.rs::demonstration_verified_reply`, both via
> `brops_win_live::proof::in_process_turn_produce`. What is true is the part that carries the weight:
> those callers run the in-process chain under the **compiled-in demonstration root**, so they can
> never render `production_verified=true` (`proof.rs` asserts it), and no live AI turn is routed
> through the kit. The gate stays false. But "does not link" and "not a shipped path" are both wrong,
> and the second one is what a reader takes away.
>
> **2. "`attest-run` is bound one-time to a lease the supervisor itself minted (R3)" — the ONE-TIME
> half is FALSE.** `Supervisor::attest_run` (`win-live/src/servers.rs`) takes a read lock on
> `accepted`, checks `run_id` and `state == COMPLETED`, and returns; there is no `remove`, no consumed
> flag, no state transition. Two calls on the same COMPLETED attempt return byte-identical
> `evidence_jcs` and `sig`. The binding to a supervisor-minted lease IS real; "one-time consume" is
> not implemented and the row below is corrected rather than the code changed — repeat attestation of
> an unchanged terminal state yields no bytes the caller did not already hold, and making it one-shot
> would turn a lost reply into an unrecoverable turn.
>
> **3. "Seed custody — seeds not plaintext at rest" — FALSE at rest.** `win_provision` writes
> `crypto::hex(&attest_seed)` and `crypto::hex(&signer_seed)`: 64 plaintext hex characters. What was
> genuinely fixed (P1, 2026-08-06) is the *race* — `provision_custody::create_locked_file` hands
> `CreateFileW` a finished `SE_DACL_PROTECTED` descriptor, so the restrictive DACL exists before the
> first byte and `icacls` is gone from the seed path. The DPAPI **seal-on-first-use** in
> `config.rs::read_seed` is the only thing that would remove the plaintext, and it is best-effort in
> three places (`if let Ok(blob)`, `if …is_ok()`, `let _ = rename`) — every one of which returns
> `Ok(seed)` and leaves the file as it found it. The honest statement is: seed custody is an **ACL**,
> not encryption at rest.
>
> **4. "P2/R1 anti-rollback floor … CONFIRMED-CLOSED" — over-stated, and the code says so.**
> `resolver.rs` and `tcb.rs` both state in their own comments that `floor_signing_key()` is a PUBLIC
> source constant, so the floor signature detects accidental corruption only and the real boundary is
> the OS write-ACL. Separately, `win_provision` writes `floor.json` unconditionally at a hardcoded
> `manifest_epoch = 2` on every run and never reads an existing one, so re-provisioning resets the
> floor. Both rows should read CLOSED-AGAINST-CORRUPTION, not CONFIRMED-CLOSED.
>
> **5. `platform_governed_execution_supported()`** is the §0.1 spec symbol; no function of that name
> exists in the tree. The real refusals are named in `docs/OWNER_ACTION_REQUIRED.md`.

## VERDICT: GREEN — for the shipped fail-closed posture and the crypto-verification core

Nothing an in-scope adversary can do forges a production `trusted_verified`, and the shipped desktop app
stays fail-closed on Windows (~~it does not even link this kit~~ — **correction 1**: it does link it, and
two shipped commands drive the in-process chain under the demonstration root; no live AI turn and no
production verdict is reachable). The Windows governed gate
(~~`platform_governed_execution_supported()`~~ — **correction 5**) correctly stays **false**; this kit is
a proven, audited slice, ~~not a shipped path~~ (**correction 1**).

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
  a substituted output ⇒ `CommitReadbackMismatch`. And `attest-run` is bound to a lease the supervisor
  itself minted (R3) — ~~one-time~~, **correction 2**: it is not consumed, and repeat calls return the
  same bytes.
- **Compromised supervisor, continued (audit R-42, closed 2026-08-10):** the supervisor now also holds a
  DURABLE cross-run evidence-head floor (`brops_core::supervisor_ledger::evidence_floor_cas`), so a
  genuinely-signed OLDER evidence chain re-presented on a later turn is refused `stale_evidence` and a
  reused head sequence is refused `evidence_fork`. Until then this platform had no such floor at all
  while the ledger described one as running "on every `complete-run`".
- **Compromised isolated-signer:** can forge — it legitimately holds the receipt key; that is the trusted
  principal isolation is meant to protect (compromising it is compromising a root CA, not an "in-scope
  single principal" break).
- `production_trust::resolve_trust_state` binds "Production" to the exact key `verify_and_accept` verified
  under, so a manifest `key_id` with an attacker public key cannot decouple the verdict.

### Findings — all closed
*(Read with the CORRECTIONS block at the top of this file: four of these rows overstate what the code
does, and the remediation audit's R-19 is exactly that overstatement.)*
| Finding | Status |
|---|---|
| P1-a TCB root pin (root from `crate::tcb`, never config; disagreeing config root refused) | CONFIRMED-CLOSED |
| P1-b production `ManifestResolver` inside acceptance (feeds the pinned key `verify_and_accept` uses) | CONFIRMED-CLOSED |
| P2 anti-rollback floor persisted atomically | CLOSED-AGAINST-CORRUPTION (**correction 4**: `win_provision` rewrites `floor.json` unconditionally at a hardcoded `manifest_epoch = 2` and never reads an existing one) |
| R1 anti-rollback floor is TCB-signed (self-contained signed `floor.json`) | CLOSED-AGAINST-CORRUPTION (**correction 4**: `tcb::floor_signing_key()` is a PUBLIC source constant — `resolver.rs:147` and `tcb.rs:54` both say a source-reading adversary forges a lowered floor; the boundary is the write-ACL, not the signature) |
| R2 supervisor-attestation key resolved through `resolve_production_key` (class/window/revocation enforced) | CONFIRMED-CLOSED |
| R3 `attest-run` bound to a supervisor-minted `accept-open` lease | BINDING CLOSED; ~~one-time consume~~ NOT IMPLEMENTED (**correction 2**) |
| A root PRIVATE key no longer written to the serving box (`keys/root.seed` removed) | CLOSED |
| D floor persisted as ONE self-contained signed file (single atomic rename; no json/sig desync) | CLOSED |
| Seed custody | a protected DACL applied AT CREATION (`create_locked_file`, no plaintext-then-`icacls` window). ~~seeds not plaintext at rest~~ **correction 3**: `win_provision` writes 64 plaintext hex chars; the DPAPI seal-on-first-use is best-effort and silent on failure |
| Restricted-token executor launch | real (`CreateRestrictedToken` + `verify_restricted_token` hard-fails the launch) |
| Shipped honesty | ~~app does not link the kit~~ **correction 1**: it does, and two shipped commands drive the in-process chain under the DEMONSTRATION root — `production_verified` is unreachable from them. Windows gate false; nothing flips a shipped gate |

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
