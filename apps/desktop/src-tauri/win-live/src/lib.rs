//! Wave 3b-1B (§0.W) — the Windows LIVE governed-turn kit.
//!
//! This is the Rust twin of the Linux `engine/ci/live` Python service kit. The three trusted principals —
//! challenge-authority, governed-supervisor, isolated-signer — are here as PURE dispatch cores in
//! [`servers`], operating on `serde_json::Value` requests/replies and signing with the SAME ed25519 +
//! JCS + SHA-256 that `brops_core::governed_verification::verify_and_accept` (the broker's final acceptance)
//! trusts. Because the cores are host-independent, the WHOLE crypto chain (challenge → lease → attest →
//! sign → verify → `trusted_verified`) is proven by an in-process integration test that runs on the Linux CI
//! runner too — no winapi required. The Windows bins (`src/bin/*`) only swap the transport: the same cores
//! served over real named pipes with peer-SID auth, and the driver connecting over named pipes.
//!
//! Nothing here is a signing oracle beyond what the design mandates: each core RECOMPUTES every digest it
//! could recompute and only signs its own attested facts. `brops-core` exposes verify-only crypto by design,
//! so the signing halves live here (the trusted principals legitimately hold private keys); the broker side
//! reuses `brops-core` verbatim.

pub mod config;
pub mod execution;
/// The execution side's DURABLE monotonic evidence head-sequence counter (audit **R-42**) — the one
/// number the supervisor's anti-rollback floor can order two runs by. It used to be a config constant.
pub mod head_sequence;
#[cfg(windows)]
pub mod pipe;
/// The named-pipe DACL decision — pure, so the Linux runner covers it even though the pipe is not there.
pub mod pipe_acl;
pub mod proof;
/// Custody of what `win_provision` writes: the deployment root it is allowed to adopt, and the explicit
/// security descriptor every secret-bearing file is CREATED with. Pure decisions + a Windows effect.
pub mod provision_custody;
pub mod resolver;
#[cfg(windows)]
pub mod seedstore;
pub mod servers;
pub mod tcb;
/// The §2.5 TCB binary/config integrity floor for this kit — pure decision + a Windows probe.
pub mod tcb_floor;

/// Ed25519 + JCS + SHA-256 primitives, byte-compatible with the Python `live_crypto.py` and with
/// `brops_core`'s verifiers (the whole point: what these sign, `verify_and_accept` verifies).
pub mod crypto {
    use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
    use base64::Engine as _;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::Value;
    use std::collections::BTreeMap;

    /// SHA-256 lowercase hex — the exact function `brops-core` uses everywhere, so digests match.
    pub use brops_core::receipt::sha256_hex;

    /// Lowercase hex of raw bytes.
    pub fn hex(bytes: &[u8]) -> String {
        let mut s = String::with_capacity(bytes.len() * 2);
        for b in bytes {
            s.push_str(&format!("{b:02x}"));
        }
        s
    }

    /// Decode 64 hex chars into 32 bytes (public keys / seeds).
    pub fn hex32(s: &str) -> Option<[u8; 32]> {
        if s.len() != 64 {
            return None;
        }
        let b = s.as_bytes();
        let mut out = [0u8; 32];
        for i in 0..32 {
            let hi = (b[2 * i] as char).to_digit(16)?;
            let lo = (b[2 * i + 1] as char).to_digit(16)?;
            out[i] = (hi * 16 + lo) as u8;
        }
        Some(out)
    }

    /// A fresh 32-byte ed25519 seed from the OS CSPRNG.
    pub fn gen_seed() -> [u8; 32] {
        let mut seed = [0u8; 32];
        getrandom::getrandom(&mut seed).expect("OS CSPRNG");
        seed
    }

    /// Reconstruct a signing key from its raw 32-byte seed (the on-disk `*.priv` format).
    pub fn signing_key(seed: &[u8; 32]) -> SigningKey {
        SigningKey::from_bytes(seed)
    }

    /// The raw-32-byte public key hex of a signing key.
    pub fn public_key_hex(sk: &SigningKey) -> String {
        hex(sk.verifying_key().to_bytes().as_slice())
    }

    /// RFC-8785-compatible JCS bytes for a FLAT object of string/integer values: sorted keys, compact
    /// separators, bare integers. Built through a `BTreeMap` so the output is sorted independently of any
    /// `serde_json` feature flags — byte-identical to Python `json.dumps(obj, sort_keys=True,
    /// separators=(",",":"))` for the fixed ASCII key sets, and to `brops_core`'s `payload_jcs`
    /// reconstruction (both are `serde_json` compact of the same sorted string/int fields).
    pub fn jcs(obj: &serde_json::Map<String, Value>) -> Vec<u8> {
        let sorted: BTreeMap<&str, &Value> = obj.iter().map(|(k, v)| (k.as_str(), v)).collect();
        serde_json::to_vec(&sorted).expect("flat JCS object serializes")
    }

    /// Detached ed25519 signature over `msg`, base64url **without** padding — used for the challenge sig,
    /// the supervisor attestation sig, the receipt-envelope sig, and the `evidence_jcs_b64` transport.
    pub fn sign_b64url(sk: &SigningKey, msg: &[u8]) -> String {
        URL_SAFE_NO_PAD.encode(sk.sign(msg).to_bytes())
    }

    /// Detached ed25519 signature over `msg`, standard base64 **with** padding — used ONLY for the root
    /// manifest signature (`manifest.sig`), matching `key_manifest::base64_decode` (STANDARD).
    pub fn sign_b64std(sk: &SigningKey, msg: &[u8]) -> String {
        STANDARD.encode(sk.sign(msg).to_bytes())
    }

    /// base64url-nopad encode raw bytes (evidence_jcs transport).
    pub fn b64url(bytes: &[u8]) -> String {
        URL_SAFE_NO_PAD.encode(bytes)
    }

    /// The §2.4 request-envelope digest, recomputed via the SAME `brops-core` routine the broker uses, so
    /// every independent site (authority / supervisor / signer / broker) produces byte-identical hashes.
    /// `requested_at` is the decimal string of the epoch-ms.
    pub fn request_sha256(
        workspace_id: &str,
        install_id: &str,
        request_nonce: &str,
        system_sha256: &str,
        history_sha256: &str,
        generation_config_sha256: &str,
        requested_at: &str,
    ) -> String {
        brops_core::receipt::request_envelope_sha256(
            workspace_id,
            install_id,
            request_nonce,
            system_sha256,
            history_sha256,
            generation_config_sha256,
            requested_at,
        )
    }
}
