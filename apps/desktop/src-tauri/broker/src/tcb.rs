//! The broker's Trusted Computing Base root anchor (Linux production trust root).
//!
//! The production-trust root PUBLIC key is compiled in HERE, never read from the deployment config — an
//! operator who can write the config directory cannot swap the root, because the broker's production resolver
//! pins the public key from this module and refuses any manifest not signed by the corresponding private
//! root. The root PRIVATE key is held OFFLINE by the operator and signs the manifest out-of-band; it never
//! appears in a deployed binary or on the serving box (mirrors the Windows kit's `crate::tcb`).

pub const ROOT_KEY_ID: &str = "brops-tcb-root-1"; // gitleaks:allow (public key-id)

/// The TCB-pinned PRODUCTION root PUBLIC key hex — the only root material in the broker binary. The private
/// half is held OFFLINE by the operator (see the Windows kit's `win_gen_root` + `CUSTODY_CEREMONY.md`) and
/// never appears in a deployed binary or on the serving box; the manifest is signed offline with it.
pub const ROOT_PUBLIC_KEY_HEX: &str =
    "3c83c2bc0e72c068824e2eebf663b6ed4cda337ff806c0b46e534aee19da0df5"; // gitleaks:allow (public key)

/// The DEMONSTRATION root key id — used ONLY by unit tests, never production.
pub const DEMO_ROOT_KEY_ID: &str = "brops-tcb-demo-root-1"; // gitleaks:allow (demo public key-id)

/// The DEMONSTRATION root PUBLIC key hex — a SEPARATE anchor whose private half is a fixed test seed, so it can
/// exercise the resolver in-process. NEVER a production anchor: the production path pins `ROOT_PUBLIC_KEY_HEX`
/// alone, so knowing the demo private cannot forge a production manifest.
pub const DEMO_ROOT_PUBLIC_KEY_HEX: &str =
    "59cfbe7b22c066c63f7c18fc698b58f63215d0705ebab5cd306bc37a49efeede"; // gitleaks:allow (demo public key)
