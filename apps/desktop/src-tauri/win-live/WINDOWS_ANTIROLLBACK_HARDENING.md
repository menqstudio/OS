# Anti-Rollback Floor — Hardening (audit P0-1)

## The finding (honest)

The anti-rollback floor (`floor.json` = `{highest_epoch, highest_hash, sig}`) is meant to stop a rollback:
replaying an OLD, genuinely-root-signed manifest (e.g. one that used a signer key later **revoked**) by
lowering the recorded floor epoch. The code signs the floor with a compiled-in key
([`tcb::FLOOR_SEED_HEX`](src/tcb.rs)) and verifies it on load ([`resolver::load_verified_floor`](src/resolver.rs)),
and older comments claimed this made a floor reset unforgeable "because the attacker cannot write the broker
binary."

**That claim was false.** `FLOOR_SEED_HEX` is a **public constant in open source**. Forging `floor.sig` needs
only the seed — not the binary. So a source-reading adversary who can also **write the deployment directory**
recomputes `floor_signing_key()`, signs an arbitrary lowered `{highest_epoch, highest_hash}`, and passes
`load_verified_floor`. They then replay a previously-root-signed manifest at that lower epoch and a
since-revoked production key resolves and renders `trusted_verified` — **without ever signing as the root**. The Linux
broker path (`broker/src/main.rs`) is worse: it reads the floor with **no signature check at all**.

Two independent audit reviewers converged on this (rated P0 / P1). The **central** trust guarantee is
unaffected — you still cannot forge a *fresh* `trusted_verified` without the root private, which nobody
holds (Owner decision #78: the install mints trust, no person carries a key); this is a
rollback/revocation-revival bypass that requires (a) a prior genuine manifest at a lower epoch and (b) write
access to the deployment directory.

## What was changed now (honesty, no fake fix)

- The false "cannot forge floor.sig" claims in `tcb.rs`, `resolver.rs` (incl. the test), `win_provision.rs`,
  and `broker/src/main.rs` are replaced with the SECURITY REALITY: the floor signature is a **corruption /
  accidental-tamper check only**, and the **real anti-rollback boundary is the OS write-protection on the
  deployment directory**. No fake verification was added (a signature under a public key would be security
  theatre).
- **One site was missed by that sweep.** `src/bin/win_live_turn.rs` — the driver, the caller of
  `load_verified_floor` — kept the comment "a reset/tampered floor.json is rejected because floor.sig will
  not verify under the TCB floor key" until 2026-10-02 (T-145). It now carries the same correction. That
  comment was also wrong about the file: there is no separate `floor.sig`; the signature is the `sig` field
  of `floor.json`.

## The real boundary (what actually protects anti-rollback)

`floor.json` (and the whole deployment dir) MUST be writable **only by the broker service principal** — a
dedicated service account whose SID is **not** the interactive login SID and **not** the in-scope sidecar SID.
In the shipped **cross-account** deployment, the in-scope attacker (sidecar RCE as its own account; the login
user) then **cannot write `floor.json` at all**, so the rollback is out of scope. This is the same boundary
the whole broker rests on, and it is the honest place the guarantee lives.

## Required to flip the shipped Windows gate (follow-up, gated)

1. **Provisioning-enforced ACL (primary).** `win_provision` (Windows) must set an explicit DACL on the
   deployment dir + `floor.json` granting **write** only to the broker service SID (+ SYSTEM), and **deny**
   the login/sidecar SIDs — via `SetNamedSecurityInfo`/SDDL. On Linux, `chown` to the broker UID + mode
   `0700`/`0600`. This makes the OS boundary explicit rather than an operator convention.
2. **Defense-in-depth: per-deployment sealed floor key (recommended).** Replace the public `FLOOR_SEED_HEX`
   with a **random per-deployment floor key** generated at provision and sealed at rest exactly like the
   serving seeds (`seedstore::dpapi_seal` + the `read_seed` TOFU path; Linux: file-perm-protected).
   *(Read "exactly like the serving seeds" with care: that TOFU seal does not succeed for a provisioned
   service account — it holds read on the seed and no write on `keys\`, and `read_seed` swallows the
   failure — so the serving seeds are plaintext hex under an ACL today. A floor key sealed "the same way"
   would need the seal done at provisioning time, under the owning account.)* Store the
   floor **public** key in the root-signed manifest (or config bound to it) so the signature also resists a
   *source-reading* attacker. Residual: a **same-principal** compromise can still DPAPI-unseal it — which is
   why (3) exists. (This changes the deployment format and requires re-provisioning + re-running the
   `win_live_turn` proof to re-verify `trusted_verified`; do it as a verified step, not a blind edit.)
3. **TPM / hardware monotonic counter (full-admin-compromise case).** Anchor `highest_epoch` to a TPM NV
   monotonic counter so even a same-principal / admin compromise cannot roll the floor back. This is the
   roadmap item `windows_production_isolation → TPM/monotonic anti-rollback` and is required for the strongest
   posture.
4. **Broker (Linux) path.** Once (2) lands, `broker/src/main.rs` should verify the floor under the
   per-deployment key too (today it does not verify — protected only by (1)).

Until (1)+(2)+(3) are in place **and** independently audited **and** Owner-approved, the shipped
Windows gate stays **shut** and the app fails closed: `connect_broker()` returns `UnsupportedPlatform`
off Linux, and chat is refused earlier by `governed_verification_unconfigured()`. *(This sentence named
`platform_governed_execution_supported()`. No function of that name exists in the tree — it is the
§0.1 specification symbol.)* Nothing here fakes trust.
