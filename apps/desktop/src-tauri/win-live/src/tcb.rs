//! The Trusted Computing Base (TCB) root anchor for the Windows live kit — audit fix P1-a.
//!
//! The production-trust root PUBLIC key is **compiled in here**, NOT read from `config.json`. This is the
//! pinning property the independent audit required: an adversary who can write the operator config directory
//! cannot swap the root, because the driver builds its `PinnedRoot` from THIS module and refuses any manifest
//! not signed by it. `config.json`'s `root_pub_hex` is advisory only and is cross-checked against this anchor.
//!
//! CUSTODY (production): the PRODUCTION root below ([`ROOT_PUBLIC_KEY_HEX`]) is a real operator-generated key
//! whose PRIVATE half is held OFFLINE (see `win_gen_root` + `CUSTODY_CEREMONY.md`) and never appears in any
//! binary or on the serving box. Only that offline private can sign a manifest the driver will accept.
//!
//! DEMONSTRATION root ([`DEMO_ROOT_PUBLIC_KEY_HEX`]): a SEPARATE anchor used ONLY by the in-process crypto-chain
//! proof (`proof::in_process_turn`) and unit tests, so the whole challenge→lease→attest→sign→verify chain can
//! be exercised host-independently with an in-code private. It is NEVER a production anchor — the production
//! path pins [`ROOT_PUBLIC_KEY_HEX`] alone, so a party who knows the demo private still cannot forge a
//! production manifest. The pinning property (verifier trusts a compiled-in public key, never the config) is
//! identical for both.

use crate::crypto;

/// The pinned PRODUCTION root key id.
pub const ROOT_KEY_ID: &str = "brops-tcb-root-1"; // gitleaks:allow (public key-id)

/// The TCB-pinned PRODUCTION root PUBLIC key hex — the ONLY root material compiled into the broker (audit
/// condition 1). The root PRIVATE key is held OFFLINE by the operator and never appears in a deployed binary or
/// on the serving box; the manifest is signed offline with it (see `win_gen_root` / `win_provision --root-key`).
/// The driver pins THIS public key and refuses any manifest not signed by the corresponding private root.
pub const ROOT_PUBLIC_KEY_HEX: &str =
    "3c83c2bc0e72c068824e2eebf663b6ed4cda337ff806c0b46e534aee19da0df5"; // gitleaks:allow (public key)

/// The TCB-pinned PRODUCTION root PUBLIC key hex — the anchor the driver pins (never config, never a private).
pub fn root_public_key_hex() -> String {
    ROOT_PUBLIC_KEY_HEX.to_string()
}

/// The DEMONSTRATION root key id — used ONLY by the in-process chain proof + unit tests, never production.
pub const DEMO_ROOT_KEY_ID: &str = "brops-tcb-demo-root-1"; // gitleaks:allow (demo public key-id)

/// The DEMONSTRATION root PUBLIC key hex. Its private half is the fixed test seed embedded in `proof.rs`, which
/// is exactly why it is NOT a production anchor: anyone with the source could sign under it. Kept separate from
/// [`ROOT_PUBLIC_KEY_HEX`] so exercising the crypto chain in-process never grants production trust.
pub const DEMO_ROOT_PUBLIC_KEY_HEX: &str =
    "59cfbe7b22c066c63f7c18fc698b58f63215d0705ebab5cd306bc37a49efeede"; // gitleaks:allow (demo public key)

/// The demonstration root PUBLIC key hex — pinned ONLY by the in-process proof + tests.
pub fn demo_root_public_key_hex() -> String {
    DEMO_ROOT_PUBLIC_KEY_HEX.to_string()
}

/// The anti-rollback-floor integrity keypair — compiled into the broker.
///
/// SECURITY REALITY (audit P0, corrected — the earlier claim below was FALSE): this seed is a public
/// compile-time constant in open source, so its signature is NOT a defense against an adversary who can read
/// the source AND write the deployment directory. Such an attacker recomputes `floor_signing_key()` and
/// forges a lowered, validly-signed `floor.json`, rolling the anti-rollback floor back to replay an older,
/// genuinely-root-signed manifest (e.g. reviving a since-revoked signer key) → `trusted_verified` WITHOUT the
/// offline root. The floor signature therefore only detects ACCIDENTAL corruption / non-source-reading
/// tampering; it is a defense-in-depth corruption check, not the anti-rollback trust boundary.
///
/// THE REAL anti-rollback boundary is the OS write-protection on the deployment directory: `floor.json` must
/// be writable ONLY by the broker service principal (a dedicated service account whose SID is NOT the
/// interactive login and NOT the in-scope sidecar). In the cross-account deployment that is the shipped
/// target, the in-scope attacker cannot write `floor.json` at all, so the rollback is out of scope. Provision
/// MUST enforce that ACL; strong protection against a same-principal compromise requires a TPM/hardware
/// monotonic counter (roadmap). See win-live/WINDOWS_ANTIROLLBACK_HARDENING.md.
///
/// (The earlier comment claimed "a config-dir adversary cannot forge floor.sig because they cannot write the
/// broker binary." That is wrong: forging the signature needs only the seed, which is a readable source
/// constant — writing the binary was never required.)
pub const FLOOR_SEED_HEX: &str =
    "8899aabbccddeeff8899aabbccddeeff8899aabbccddeeff8899aabbccddeeff"; // gitleaks:allow (public corruption-check key, NOT a trust boundary)

pub fn floor_signing_key() -> ed25519_dalek::SigningKey {
    let seed = crypto::hex32(FLOOR_SEED_HEX).expect("valid floor seed hex");
    crypto::signing_key(&seed)
}

pub fn floor_public_key_hex() -> String {
    let seed = crypto::hex32(FLOOR_SEED_HEX).expect("valid floor seed hex");
    crypto::public_key_hex(&crypto::signing_key(&seed))
}
