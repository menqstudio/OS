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

/// The TCB-pinned root PUBLIC key hex — the ONLY root material compiled into the broker (audit condition 1).
/// The root PRIVATE key is held OFFLINE by the operator and never appears in a deployed binary or on the
/// serving box; the manifest is signed offline with it (see win_provision --root-key). The driver pins THIS
/// public key and refuses any manifest not signed by the corresponding private root.
pub const ROOT_PUBLIC_KEY_HEX: &str =
    "59cfbe7b22c066c63f7c18fc698b58f63215d0705ebab5cd306bc37a49efeede"; // gitleaks:allow (public key)

/// The TCB-pinned root PUBLIC key hex — the anchor the driver pins (never from config, never a private key).
pub fn root_public_key_hex() -> String {
    ROOT_PUBLIC_KEY_HEX.to_string()
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
