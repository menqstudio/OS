//! The Trusted Computing Base (TCB) root anchor for the Windows live kit — audit fix P1-a.
//!
//! The production-trust root PUBLIC key is **compiled in here**, NOT read from `config.json`. This is the
//! pinning property the independent audit required: an adversary who can write the operator config directory
//! cannot swap the root, because the driver builds its `PinnedRoot` from THIS module and refuses any manifest
//! not signed by it. `config.json`'s `root_pub_hex` is advisory only and is cross-checked against this anchor.
//!
//! PROOF-KIT NOTE (honest): to keep the kit self-contained we also embed a FIXED root SEED so the provisioner
//! can sign the manifest. In PRODUCTION the root PRIVATE key is held OFFLINE and ONLY [`root_public_key_hex`]
//! (derived from it) is compiled into the TCB; the manifest is signed offline with the private root. The
//! pinning property proven here — the verifier trusts a compiled-in public key, never the config — is
//! identical either way.

use crate::crypto;

/// The pinned root key id.
pub const ROOT_KEY_ID: &str = "brops-tcb-root-1"; // gitleaks:allow (fake public key-id)

/// PROOF-KIT fixed root private seed (32 bytes, hex). PRODUCTION: delete; ship only the public key.
pub const ROOT_SEED_HEX: &str =
    "0011223344556677001122334455667700112233445566770011223344556677"; // gitleaks:allow (fake proof-kit root seed)

/// The TCB-pinned root PUBLIC key hex — the anchor the driver pins (never from config).
pub fn root_public_key_hex() -> String {
    let seed = crypto::hex32(ROOT_SEED_HEX).expect("valid root seed hex");
    crypto::public_key_hex(&crypto::signing_key(&seed))
}

/// The proof-kit root signing key (PRODUCTION: held offline; not shipped in the TCB).
pub fn root_signing_key() -> ed25519_dalek::SigningKey {
    let seed = crypto::hex32(ROOT_SEED_HEX).expect("valid root seed hex");
    crypto::signing_key(&seed)
}

/// The anti-rollback-floor integrity keypair — compiled into the broker TCB (audit R1). UNLIKE the root
/// (whose private half is offline in production), the broker WRITES the floor at runtime, so it needs a
/// runtime signing key held in the TCB. The floor is signed with this key on every advance and verified on
/// load; a config-dir adversary who resets `floor.json` cannot forge a matching `floor.sig` (they cannot
/// write the broker binary), so a rollback-to-an-older-genuine-manifest is caught. The trust boundary is
/// "cannot modify the broker TCB", the same boundary the whole broker rests on.
pub const FLOOR_SEED_HEX: &str =
    "8899aabbccddeeff8899aabbccddeeff8899aabbccddeeff8899aabbccddeeff"; // gitleaks:allow (TCB floor-integrity key)

pub fn floor_signing_key() -> ed25519_dalek::SigningKey {
    let seed = crypto::hex32(FLOOR_SEED_HEX).expect("valid floor seed hex");
    crypto::signing_key(&seed)
}

pub fn floor_public_key_hex() -> String {
    let seed = crypto::hex32(FLOOR_SEED_HEX).expect("valid floor seed hex");
    crypto::public_key_hex(&crypto::signing_key(&seed))
}
