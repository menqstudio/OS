//! The broker's Trusted Computing Base root anchor (Linux production trust root).
//!
//! The production-trust root PUBLIC key is compiled in HERE, never read from the deployment config — an
//! operator who can write the config directory cannot swap the root, because the broker's production resolver
//! pins the public key from this module and refuses any manifest not signed by the corresponding private
//! root. The root PRIVATE key is held OFFLINE by the operator and signs the manifest out-of-band; it never
//! appears in a deployed binary or on the serving box (mirrors the Windows kit's `crate::tcb`).

pub const ROOT_KEY_ID: &str = "brops-tcb-root-1"; // gitleaks:allow (public key-id)

/// The TCB-pinned root PUBLIC key hex — the only root material in the broker binary.
pub const ROOT_PUBLIC_KEY_HEX: &str =
    "59cfbe7b22c066c63f7c18fc698b58f63215d0705ebab5cd306bc37a49efeede"; // gitleaks:allow (public key)
