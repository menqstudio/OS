# H-5 — Key revocation is defeatable: the trusted-key registry has no anti-rollback binding

- **Severity:** High
- **Confidence:** High
- **Files:** `runtime/bro_signature.py:271-319` (`load_trusted_keys`), `242-268` (pin resolution)
- **Status:** Proposed patch (read-only audit)

## Problem
The external pin (`BRO_OPERATOR_ROOT_PUBKEY[_FILE]`) fixes the operator-root **identity** but not **which registry version** is current. `load_trusted_keys` verifies the operator signature and the key's presence, but never compares `issued_at_epoch` (or a monotonic counter) to a trusted floor. Revocation works by publishing a new registry marking a leaked key `revoked` — but an attacker restores an earlier, **still-operator-signed** registry in which that key is `active`, and every signature (including one from the leaked key) verifies again. In-repo revocation is inert without an external monotonic reference.

## Fix
Bind registry freshness to the external anchor: alongside the pubkey pin, pin a monotonic `registry_version` (or a minimum `issued_at_epoch`, or the sha256 of the authorized registry) in the operator-controlled out-of-repo file, and in `load_trusted_keys` reject any registry whose version/`issued_at_epoch` is below the pinned floor.

## Acceptance criteria
- [ ] A registry with a lower `registry_version`/`issued_at_epoch` than the pinned floor is rejected, even if operator-signed.
- [ ] After "revoking" a key (new registry), replaying the old registry no longer verifies signatures from the revoked key.
- [ ] The current registry still loads normally.
