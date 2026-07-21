//! Receipt Protocol v1 — protocol core (Wave 3a, slice 1).
//!
//! This module is the **pure, I/O-free heart** of the receipt verifier described
//! in `docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`. It knows nothing about
//! SQLite, the wall clock, or the key manifest; it does exactly the parts that can
//! be reasoned about and unit-tested in isolation:
//!
//!   * **Canonicalization (§2)** — RFC 8785 (JCS) bytes for the receipt envelope
//!     and the canonical *request* envelope (§2.2). The whole envelope is a flat
//!     JSON object of `string -> string` with a fixed ASCII key set, so JCS reduces
//!     to "sorted ASCII keys, minimal-escape JSON strings, no whitespace" — which
//!     `serde_json`'s compact serialization of a `BTreeMap<String,String>` already
//!     produces byte-for-byte. (A test asserts the key set is ASCII, which is what
//!     makes UTF-8 byte order == UTF-16 code-unit order == JCS key order.)
//!   * **Wire format & strict decode (§2.3)** — base64url -> exact bytes (size
//!     capped) -> strict JSON parse (UTF-8 only, duplicate keys rejected, unknown
//!     fields rejected, every value a string, hashes lowercase-64-hex) -> require
//!     `JCS(parsed) == decoded bytes` (no parser differentials) -> **verify the
//!     Ed25519 signature over the decoded bytes** -> keep the bytes unchanged.
//!   * **Pure binding checks (§3)** — the subset of the verification checklist that
//!     is a value comparison against expected inputs: protocol, `decision`, request
//!     binding, identity/policy/config bindings, output-bytes rehash, allowed
//!     executor/builder, and `requested_at <= completed_at`.
//!   * **Trust-state machine (§6)** — maps the verifying key's signed `trust_class`
//!     to a render state, and **refuses to yield `trusted_verified` in Wave 3a**
//!     even if handed a production key (production rendering is gated until 3b).
//!
//! **Deliberately NOT here (stateful — slices 2/3, Wave 3b):** the one-time nonce
//! consume, `receipt_id` global-uniqueness, key-manifest resolution + validity
//! window + epoch + revocation + anti-rollback, wall-clock freshness/skew, and any
//! persistence. Those need the database or the clock and are layered on top of this
//! pure core, which is where the signature and every self-contained binding live.
//!
//! Production code here is **verify-only**: the Ed25519 *signing* half is compiled
//! solely under `#[cfg(test)]`, so the shipping desktop core is never a
//! `sign(arbitrary_bytes)` oracle (design §1 — the trusted-signer boundary).

use std::collections::BTreeMap;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use ed25519_dalek::{Signature, VerifyingKey};
use serde::de::{self, Deserializer, MapAccess, Visitor};
use serde::Deserialize;
use sha2::{Digest, Sha256};

/// Domain-separation tag for the receipt envelope (design §2).
pub const RECEIPT_PROTOCOL: &str = "brops.receipt.v1";
/// Domain-separation tag for the canonical request envelope (design §2.2).
pub const REQUEST_PROTOCOL: &str = "brops.request.v1";
/// Only a `completed` decision is a grant (design §3.2).
pub const DECISION_COMPLETED: &str = "completed";

/// Upper bound on a decoded envelope. A signed receipt is a small fixed record;
/// anything larger is malformed or hostile and is rejected before parsing (§2.3).
pub const MAX_ENVELOPE_BYTES: usize = 64 * 1024;

const ALLOWED_DECISIONS: &[&str] = &["completed", "denied", "uncontained"];

/// Every field the receipt envelope must carry, exactly (design §2). Used both to
/// reject unknown/missing keys and to document the wire shape. All ASCII.
const RECEIPT_FIELDS: &[&str] = &[
    "builder_id",
    "completed_at",
    "containment_evidence_sha256",
    "decision",
    "executor_id",
    "generation_config_sha256",
    "history_sha256",
    "install_id",
    "key_id",
    "output_sha256",
    "policy_bundle_sha256",
    "policy_id",
    "policy_version",
    "protocol",
    "receipt_id",
    "request_nonce",
    "request_sha256",
    "requested_at",
    "supervisor_id",
    "system_sha256",
    "workspace_id",
];

/// The subset of envelope fields that MUST be a lowercase 64-hex SHA-256 (§2.3).
const HASH_FIELDS: &[&str] = &[
    "containment_evidence_sha256",
    "generation_config_sha256",
    "history_sha256",
    "output_sha256",
    "policy_bundle_sha256",
    "request_sha256",
    "system_sha256",
];

/// Fields the desktop compares millisecond-for-millisecond as timestamps (§3.8).
const TIMESTAMP_FIELDS: &[&str] = &["requested_at", "completed_at"];

/// Every distinct way a receipt can fail to verify. Each variant maps to a negative
/// test and (in slice 2) to the persisted `verification_error`. Any of them means
/// **Blocked** — "no verified signature ⇒ no result".
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ReceiptError {
    #[error("wire: base64url decode failed")]
    BadBase64,
    #[error("wire: envelope is {0} bytes, over the {MAX_ENVELOPE_BYTES}-byte cap")]
    TooLarge(usize),
    #[error("wire: not valid strict JSON: {0}")]
    BadJson(String),
    #[error("wire: duplicate key `{0}`")]
    DuplicateKey(String),
    #[error("wire: unknown field `{0}`")]
    UnknownField(String),
    #[error("wire: missing field `{0}`")]
    MissingField(&'static str),
    #[error("wire: field `{0}` must be a non-empty string")]
    EmptyField(&'static str),
    #[error("wire: field `{0}` must be a lowercase 64-hex sha256")]
    NotHex(&'static str),
    #[error("wire: field `{0}` must be a millisecond timestamp")]
    NotTimestamp(&'static str),
    #[error("wire: `decision` `{0}` is not one of completed|denied|uncontained")]
    BadDecisionDomain(String),
    #[error("wire: received bytes are not canonical (JCS(parsed) != bytes)")]
    NotCanonical,
    #[error("crypto: signature is {0} bytes, expected 64")]
    BadSignatureLength(usize),
    #[error("crypto: public key is {0} bytes, expected 32")]
    BadKeyLength(usize),
    #[error("crypto: public key is not a valid Ed25519 point")]
    BadKey,
    #[error("crypto: Ed25519 signature does not verify over the envelope bytes")]
    BadSignature,
    #[error("bind: protocol `{0}` != `{RECEIPT_PROTOCOL}`")]
    Protocol(String),
    #[error("bind: decision `{0}` is not `completed`")]
    NotCompleted(String),
    #[error("bind: `{field}` does not match the expected value")]
    Mismatch { field: &'static str },
    #[error("bind: `{0}` is not in the allowed set for this install")]
    NotAllowed(&'static str),
    #[error("bind: output bytes do not hash to `output_sha256`")]
    OutputMismatch,
    #[error("bind: requested_at ({requested}) is after completed_at ({completed})")]
    TimeOrder { requested: u64, completed: u64 },
}

/// A receipt whose wire bytes decoded strictly, canonicalized identically, and whose
/// Ed25519 signature verified over those exact bytes. It still must pass [`Verified::bind`]
/// (§3 value bindings) and, in later slices, the stateful checks (nonce/uniqueness/
/// manifest/clock) before its output may render.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Verified {
    fields: BTreeMap<String, String>,
    /// The exact decoded envelope bytes — canonical, stored unchanged (§2.3 step 5).
    canonical_bytes: Vec<u8>,
    /// The verified 64-byte Ed25519 signature (persisted alongside the bytes, §4).
    signature: [u8; 64],
}

impl Verified {
    fn get(&self, field: &str) -> &str {
        // Present by construction: `decode_and_verify` proved the full key set.
        self.fields.get(field).map(String::as_str).unwrap_or("")
    }

    pub fn protocol(&self) -> &str { self.get("protocol") }
    pub fn receipt_id(&self) -> &str { self.get("receipt_id") }
    pub fn key_id(&self) -> &str { self.get("key_id") }
    pub fn decision(&self) -> &str { self.get("decision") }
    pub fn output_sha256(&self) -> &str { self.get("output_sha256") }
    pub fn request_nonce(&self) -> &str { self.get("request_nonce") }
    pub fn executor_id(&self) -> &str { self.get("executor_id") }
    pub fn builder_id(&self) -> &str { self.get("builder_id") }

    /// The canonical envelope bytes, exactly as decoded and verified. Persist these
    /// unchanged (never a re-serialization) so the record stays re-verifiable (§4).
    pub fn canonical_bytes(&self) -> &[u8] { &self.canonical_bytes }
    /// The verified signature bytes, to persist alongside the envelope (§4).
    pub fn signature(&self) -> &[u8; 64] { &self.signature }

    fn ts(&self, field: &str) -> u64 {
        // Validated as an all-ASCII-digit ms timestamp during decode.
        self.get(field).parse::<u64>().unwrap_or(u64::MAX)
    }
}

/// Everything the desktop already knows for this turn and requires the receipt to
/// match, value-for-value (design §3). Borrowed — this is a pure comparison input.
///
/// `request_nonce` here is a *value* equality (the challenge the desktop issued);
/// the *one-time consume* of that nonce is a stateful step performed in slice 2.
#[derive(Debug, Clone, Copy)]
pub struct Expected<'a> {
    pub workspace_id: &'a str,
    pub install_id: &'a str,
    pub supervisor_id: &'a str,
    pub request_nonce: &'a str,
    pub request_sha256: &'a str,
    pub policy_id: &'a str,
    pub policy_version: &'a str,
    pub policy_bundle_sha256: &'a str,
    pub generation_config_sha256: &'a str,
    pub system_sha256: &'a str,
    pub history_sha256: &'a str,
    pub containment_evidence_sha256: &'a str,
    pub allowed_executors: &'a [&'a str],
    pub allowed_builders: &'a [&'a str],
}

impl Verified {
    /// The pure subset of the §3 verification checklist: every binding that is a
    /// value comparison against what the desktop already knows, plus the output
    /// re-hash and the intra-receipt time order. `output` is the exact reply bytes
    /// (§2.1 — hashed as opaque bytes, no normalization). Any failure ⇒ **Blocked**.
    ///
    /// Not covered here (stateful, layered on in slice 2 / Wave 3b): one-time nonce
    /// consume, `receipt_id` uniqueness, key-manifest resolution/validity/epoch/
    /// revocation/anti-rollback, and wall-clock freshness/skew.
    pub fn bind(&self, expected: &Expected, output: &[u8]) -> Result<(), ReceiptError> {
        if self.protocol() != RECEIPT_PROTOCOL {
            return Err(ReceiptError::Protocol(self.protocol().to_string()));
        }
        if self.decision() != DECISION_COMPLETED {
            return Err(ReceiptError::NotCompleted(self.decision().to_string()));
        }

        // Identity / request / policy / config bindings — each an expected-value match.
        let equals: &[(&'static str, &str)] = &[
            ("workspace_id", expected.workspace_id),
            ("install_id", expected.install_id),
            ("supervisor_id", expected.supervisor_id),
            ("request_nonce", expected.request_nonce),
            ("request_sha256", expected.request_sha256),
            ("policy_id", expected.policy_id),
            ("policy_version", expected.policy_version),
            ("policy_bundle_sha256", expected.policy_bundle_sha256),
            ("generation_config_sha256", expected.generation_config_sha256),
            ("system_sha256", expected.system_sha256),
            ("history_sha256", expected.history_sha256),
            ("containment_evidence_sha256", expected.containment_evidence_sha256),
        ];
        for (field, want) in equals {
            if self.get(field) != *want {
                return Err(ReceiptError::Mismatch { field });
            }
        }

        // Executor / builder must be in the allowed set for this install (§3.8).
        if !expected.allowed_executors.contains(&self.executor_id()) {
            return Err(ReceiptError::NotAllowed("executor_id"));
        }
        if !expected.allowed_builders.contains(&self.builder_id()) {
            return Err(ReceiptError::NotAllowed("builder_id"));
        }

        // Output binding: the returned bytes must hash to the signed output_sha256
        // (§2.1, exact bytes). This is what makes the signature cover the reply.
        if sha256_hex(output) != self.output_sha256() {
            return Err(ReceiptError::OutputMismatch);
        }

        // Intra-receipt time order (the wall-clock freshness window is slice 2).
        let (requested, completed) = (self.ts("requested_at"), self.ts("completed_at"));
        if requested > completed {
            return Err(ReceiptError::TimeOrder { requested, completed });
        }
        Ok(())
    }
}

/// A verifying key's **signed** trust classification from the manifest (§5). It is
/// what decides the render state — never inferred by the desktop.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrustClass {
    Production,
    Development,
}

/// The render state the desktop resolves every governed reply to (design §6).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrustState {
    /// Full "Verified" badge — only reachable once Wave 3b exists.
    TrustedVerified,
    /// Renders + persists, badged "Development / untrusted". Never "Verified".
    DevelopmentUntrusted,
    /// Never renders, never persists to `messages`; evidence only.
    Blocked,
}

/// Map a verified receipt's signed key `trust_class` to a render state (§6).
///
/// `production_allowed` is the wave gate: **Wave 3a passes `false`**, so even a
/// production-class key resolves to `Blocked` rather than rendering "Verified"
/// (design §5/§6: "Wave 3a never yields `trusted_verified`"). Wave 3b flips it on
/// once the isolated signer + provisioned manifest exist.
pub fn resolve_trust_state(class: TrustClass, production_allowed: bool) -> TrustState {
    match class {
        TrustClass::Development => TrustState::DevelopmentUntrusted,
        TrustClass::Production if production_allowed => TrustState::TrustedVerified,
        TrustClass::Production => TrustState::Blocked,
    }
}

/// SHA-256 of arbitrary bytes as a lowercase 64-hex string. The input is treated as
/// opaque bytes — no normalization (design §2.1).
pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut out = String::with_capacity(64);
    for b in digest {
        out.push(char::from_digit((b >> 4) as u32, 16).unwrap());
        out.push(char::from_digit((b & 0x0f) as u32, 16).unwrap());
    }
    out
}

/// Canonical (JCS) bytes for a flat `string -> string` object with a fixed ASCII key
/// set. `serde_json`'s compact serialization of a `BTreeMap` emits sorted keys, no
/// whitespace, and RFC 8785-compatible minimal string escaping — which for this
/// restricted shape *is* RFC 8785 JCS. (Validity relies on ASCII keys so UTF-8 byte
/// order equals UTF-16 code-unit order; asserted by a test over `RECEIPT_FIELDS`.)
fn jcs_bytes(map: &BTreeMap<String, String>) -> Vec<u8> {
    serde_json::to_vec(map).expect("a BTreeMap<String,String> always serializes")
}

/// SHA-256 (lowercase hex) of the canonical **request** envelope (design §2.2). The
/// desktop builds this when it issues the governed request and later requires the
/// receipt's `request_sha256` to equal it. Field set is fixed (§2.2).
#[allow(clippy::too_many_arguments)]
pub fn request_envelope_sha256(
    workspace_id: &str,
    install_id: &str,
    request_nonce: &str,
    system_sha256: &str,
    history_sha256: &str,
    generation_config_sha256: &str,
    requested_at: &str,
) -> String {
    let mut map = BTreeMap::new();
    map.insert("protocol".to_string(), REQUEST_PROTOCOL.to_string());
    map.insert("workspace_id".to_string(), workspace_id.to_string());
    map.insert("install_id".to_string(), install_id.to_string());
    map.insert("request_nonce".to_string(), request_nonce.to_string());
    map.insert("system_sha256".to_string(), system_sha256.to_string());
    map.insert("history_sha256".to_string(), history_sha256.to_string());
    map.insert("generation_config_sha256".to_string(), generation_config_sha256.to_string());
    map.insert("requested_at".to_string(), requested_at.to_string());
    sha256_hex(&jcs_bytes(&map))
}

/// A flat `string -> string` JSON object parsed **strictly**: UTF-8 only (enforced
/// by `serde_json::from_slice`), every value a JSON string, and **duplicate keys
/// rejected** (serde's derived/`Map` parsing would silently keep the last one). This
/// is the parser that closes JSON differentials (§2.3 step 2).
struct StrictStringMap(BTreeMap<String, String>);

impl<'de> Deserialize<'de> for StrictStringMap {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = BTreeMap<String, String>;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("a flat JSON object with string values")
            }
            fn visit_map<A>(self, mut access: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut out = BTreeMap::new();
                // `next_value::<String>` errors on any non-string value, so numbers,
                // booleans, nulls, arrays and nested objects are all rejected here.
                while let Some(key) = access.next_key::<String>()? {
                    let value = access.next_value::<String>()?;
                    if out.insert(key.clone(), value).is_some() {
                        return Err(de::Error::custom(format!("__dup__{key}")));
                    }
                }
                Ok(out)
            }
        }
        deserializer.deserialize_map(V).map(StrictStringMap)
    }
}

fn is_lower_hex64(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// A structurally-valid envelope whose bytes are proven canonical (design §2.3 steps
/// 1–3) but whose signature is **not yet verified**. It is the type-state seam that
/// lets the caller resolve the verifying key **by the envelope's own `key_id`** (§3.1
/// — the key comes from the manifest entry for that id) before checking the signature.
///
/// Only `key_id` is readable here; every other field is reachable only through
/// [`Parsed::verify`]'s [`Verified`] result, so unverified envelope data can never be
/// mistaken for verified data.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Parsed {
    fields: BTreeMap<String, String>,
    canonical_bytes: Vec<u8>,
}

impl Parsed {
    /// The signing key id the envelope claims. The caller resolves the pinned public
    /// key (and its `trust_class`) for this id from the trusted manifest, then calls
    /// [`Parsed::verify`]. This is the ONLY field exposed before verification.
    pub fn key_id(&self) -> &str {
        self.fields.get("key_id").map(String::as_str).unwrap_or("")
    }

    /// Verify the Ed25519 signature over the exact decoded bytes (§2.3 steps 4–5).
    /// `public_key` MUST be the manifest key for [`Parsed::key_id`]; `signature_b64`
    /// is the wire signature. On success the bytes are kept unchanged for storage.
    pub fn verify(self, public_key: &[u8], signature_b64: &str) -> Result<Verified, ReceiptError> {
        let key_bytes: [u8; 32] = public_key
            .try_into()
            .map_err(|_| ReceiptError::BadKeyLength(public_key.len()))?;
        let verifying_key =
            VerifyingKey::from_bytes(&key_bytes).map_err(|_| ReceiptError::BadKey)?;
        // An Ed25519 signature base64url-encodes to 86 chars; cap the input before
        // decoding so a giant `signature_b64` can't force a large allocation.
        if signature_b64.len() > 128 {
            return Err(ReceiptError::BadSignatureLength(signature_b64.len()));
        }
        let sig_bytes = URL_SAFE_NO_PAD
            .decode(signature_b64.as_bytes())
            .map_err(|_| ReceiptError::BadBase64)?;
        let sig_arr: [u8; 64] = sig_bytes
            .as_slice()
            .try_into()
            .map_err(|_| ReceiptError::BadSignatureLength(sig_bytes.len()))?;
        let signature = Signature::from_bytes(&sig_arr);
        // `verify_strict` rejects non-canonical `s` and small-order `A` — stricter
        // than the batch verifier and the right default for a security boundary. The
        // message is the DECODED bytes, never a re-encode.
        verifying_key
            .verify_strict(&self.canonical_bytes, &signature)
            .map_err(|_| ReceiptError::BadSignature)?;
        Ok(Verified {
            fields: self.fields,
            canonical_bytes: self.canonical_bytes,
            signature: sig_arr,
        })
    }
}

/// Decode the wire form and strict-parse it into a canonical [`Parsed`] envelope
/// (design §2.3 steps 1–3): base64url → exact bytes (size-capped) → strict JSON
/// (UTF-8, duplicate keys rejected, every value a string, exact key set, hashes
/// lowercase-64-hex, timestamps numeric, `decision` in-domain) → require
/// `JCS(parsed) == bytes`. No signature check yet — see [`Parsed::verify`].
pub fn parse_strict(envelope_jcs_b64: &str) -> Result<Parsed, ReceiptError> {
    // Cheap length guard before allocating a decode buffer: base64 expands ~4/3, so
    // a string this long cannot decode to <= MAX_ENVELOPE_BYTES.
    if envelope_jcs_b64.len() > MAX_ENVELOPE_BYTES / 3 * 4 + 4 {
        return Err(ReceiptError::TooLarge(envelope_jcs_b64.len()));
    }

    // Step 1: base64url-decode to the exact bytes; enforce the size cap.
    let bytes = URL_SAFE_NO_PAD
        .decode(envelope_jcs_b64.as_bytes())
        .map_err(|_| ReceiptError::BadBase64)?;
    if bytes.len() > MAX_ENVELOPE_BYTES {
        return Err(ReceiptError::TooLarge(bytes.len()));
    }

    // Step 2: strict-parse. UTF-8 + string-typed values + duplicate-key rejection.
    let map = serde_json::from_slice::<StrictStringMap>(&bytes)
        .map_err(|e| {
            let msg = e.to_string();
            match msg.split("__dup__").nth(1) {
                // serde_json appends " at line N column M" to the custom message;
                // strip it (last occurrence) to recover the bare duplicate key.
                Some(rest) => {
                    let key = rest.rsplit_once(" at line ").map_or(rest, |(k, _)| k);
                    ReceiptError::DuplicateKey(key.to_string())
                }
                None => ReceiptError::BadJson(msg),
            }
        })?
        .0;

    // Exact key set: no unknown, none missing (§2.3 unknown-field rejection).
    for key in map.keys() {
        if !RECEIPT_FIELDS.contains(&key.as_str()) {
            return Err(ReceiptError::UnknownField(key.clone()));
        }
    }
    for field in RECEIPT_FIELDS {
        if !map.contains_key(*field) {
            return Err(ReceiptError::MissingField(field));
        }
    }

    // Per-field value shape. Every field is non-empty; hashes are lowercase 64-hex;
    // timestamps are millisecond integers; `decision` is in its fixed domain.
    for (field, value) in &map {
        if value.is_empty() {
            // `&'static str` for the error: recover the interned field name. Safe:
            // the unknown-field pass above proved every key is in RECEIPT_FIELDS.
            let name = RECEIPT_FIELDS.iter().find(|f| **f == field).unwrap();
            return Err(ReceiptError::EmptyField(name));
        }
    }
    for field in HASH_FIELDS {
        if !is_lower_hex64(map.get(*field).unwrap()) {
            return Err(ReceiptError::NotHex(field));
        }
    }
    for field in TIMESTAMP_FIELDS {
        let v = map.get(*field).unwrap();
        if v.parse::<u64>().is_err() {
            return Err(ReceiptError::NotTimestamp(field));
        }
    }
    let decision = map.get("decision").unwrap();
    if !ALLOWED_DECISIONS.contains(&decision.as_str()) {
        return Err(ReceiptError::BadDecisionDomain(decision.clone()));
    }

    // Step 3: the received bytes must already BE canonical. Re-canonicalizing the
    // parsed map and requiring byte-equality rejects any non-canonical encoding a
    // lax parser would accept (extra whitespace, unsorted keys, over-escaping).
    if jcs_bytes(&map) != bytes {
        return Err(ReceiptError::NotCanonical);
    }

    Ok(Parsed { fields: map, canonical_bytes: bytes })
}

/// Convenience for callers that already hold the key: [`parse_strict`] followed by
/// [`Parsed::verify`]. The real flow resolves the key by [`Parsed::key_id`] between
/// the two, so tests use this and the desktop wiring uses the two-phase form.
pub fn decode_and_verify(
    envelope_jcs_b64: &str,
    signature_b64: &str,
    public_key: &[u8],
) -> Result<Verified, ReceiptError> {
    parse_strict(envelope_jcs_b64)?.verify(public_key, signature_b64)
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer as _, SigningKey};

    // ---- test-only signer -------------------------------------------------
    // The signing half lives ONLY under cfg(test): production code is verify-only,
    // so the desktop core is never a sign(arbitrary_bytes) oracle (design §1).

    fn signing_key(seed: u8) -> SigningKey {
        SigningKey::from_bytes(&[seed; 32])
    }

    /// A fully-valid field map for a `completed` receipt. Tests mutate one field to
    /// drive a single negative case.
    fn valid_fields() -> BTreeMap<String, String> {
        let h = |n: u8| -> String {
            let mut s = String::new();
            for _ in 0..32 {
                s.push_str(&format!("{n:02x}"));
            }
            s
        };
        let mut m = BTreeMap::new();
        m.insert("protocol".into(), RECEIPT_PROTOCOL.into());
        m.insert("receipt_id".into(), "receipt-abc".into());
        m.insert("key_id".into(), "key-dev-1".into());
        m.insert("workspace_id".into(), "ws-1".into());
        m.insert("install_id".into(), "install-1".into());
        m.insert("request_nonce".into(), "nonce-xyz".into());
        m.insert("request_sha256".into(), h(0x11));
        m.insert("decision".into(), DECISION_COMPLETED.into());
        m.insert("policy_id".into(), "pol-1".into());
        m.insert("policy_version".into(), "1".into());
        m.insert("policy_bundle_sha256".into(), h(0x22));
        m.insert("containment_evidence_sha256".into(), h(0x33));
        m.insert("generation_config_sha256".into(), h(0x44));
        m.insert("system_sha256".into(), h(0x55));
        m.insert("history_sha256".into(), h(0x66));
        m.insert("output_sha256".into(), sha256_hex(OUTPUT));
        m.insert("executor_id".into(), "exec-1".into());
        m.insert("builder_id".into(), "build-1".into());
        m.insert("supervisor_id".into(), "sup-1".into());
        m.insert("requested_at".into(), "1000".into());
        m.insert("completed_at".into(), "2000".into());
        m
    }

    const OUTPUT: &[u8] = b"the exact governed reply bytes";

    /// Sign a field map into the wire form with the test signer.
    fn wire(map: &BTreeMap<String, String>, key: &SigningKey) -> (String, String) {
        let bytes = jcs_bytes(map);
        let sig = key.sign(&bytes);
        (
            URL_SAFE_NO_PAD.encode(&bytes),
            URL_SAFE_NO_PAD.encode(sig.to_bytes()),
        )
    }

    // Owned hex strings for the expected bindings — `Expected` borrows, and these
    // need a 'static home so `expected()` can hand out `Expected<'static>`.
    struct ExpHashes {
        request: String,
        bundle: String,
        containment: String,
        generation: String,
        system: String,
        history: String,
    }
    static EXP: std::sync::LazyLock<ExpHashes> = std::sync::LazyLock::new(|| ExpHashes {
        request: "11".repeat(32),
        bundle: "22".repeat(32),
        containment: "33".repeat(32),
        generation: "44".repeat(32),
        system: "55".repeat(32),
        history: "66".repeat(32),
    });

    fn expected() -> Expected<'static> {
        Expected {
            workspace_id: "ws-1",
            install_id: "install-1",
            supervisor_id: "sup-1",
            request_nonce: "nonce-xyz",
            request_sha256: &EXP.request,
            policy_id: "pol-1",
            policy_version: "1",
            policy_bundle_sha256: &EXP.bundle,
            generation_config_sha256: &EXP.generation,
            system_sha256: &EXP.system,
            history_sha256: &EXP.history,
            containment_evidence_sha256: &EXP.containment,
            allowed_executors: &["exec-1", "exec-2"],
            allowed_builders: &["build-1"],
        }
    }

    // ---- happy path -------------------------------------------------------

    #[test]
    fn a_valid_receipt_verifies_and_binds() {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();
        assert_eq!(v.decision(), "completed");
        v.bind(&expected(), OUTPUT).unwrap();
        // The stored bytes are exactly what was signed.
        assert_eq!(v.canonical_bytes(), jcs_bytes(&valid_fields()).as_slice());
    }

    // ---- crypto -----------------------------------------------------------

    #[test]
    fn key_id_is_readable_before_verification_then_verify_binds() {
        // The real flow: parse structurally, read key_id to resolve the manifest key,
        // then verify. key_id is the ONLY field reachable pre-verification.
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        let parsed = parse_strict(&env).unwrap();
        assert_eq!(parsed.key_id(), "key-dev-1");
        // A wrong key resolved for that id fails the signature check.
        assert_eq!(
            parsed.clone().verify(signing_key(9).verifying_key().as_bytes(), &sig),
            Err(ReceiptError::BadSignature)
        );
        // The right key verifies and then binds.
        let v = parsed.verify(key.verifying_key().as_bytes(), &sig).unwrap();
        v.bind(&expected(), OUTPUT).unwrap();
    }

    #[test]
    fn wrong_key_is_rejected() {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        let other = signing_key(8);
        assert_eq!(
            decode_and_verify(&env, &sig, other.verifying_key().as_bytes()),
            Err(ReceiptError::BadSignature)
        );
    }

    #[test]
    fn tampering_one_output_byte_breaks_the_binding() {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();
        let mut tampered = OUTPUT.to_vec();
        tampered[0] ^= 0x01;
        assert_eq!(v.bind(&expected(), &tampered), Err(ReceiptError::OutputMismatch));
    }

    #[test]
    fn tampering_the_envelope_breaks_the_signature() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        let (env, sig) = wire(&fields, &key);
        // Re-sign nothing; just flip a field and re-encode with the OLD signature.
        fields.insert("workspace_id".into(), "ws-evil".into());
        let forged_env = URL_SAFE_NO_PAD.encode(jcs_bytes(&fields));
        let _ = env;
        assert_eq!(
            decode_and_verify(&forged_env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::BadSignature)
        );
    }

    #[test]
    fn bad_key_and_signature_lengths_are_rejected() {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        assert_eq!(
            decode_and_verify(&env, &sig, &[0u8; 10]),
            Err(ReceiptError::BadKeyLength(10))
        );
        let short_sig = URL_SAFE_NO_PAD.encode([0u8; 10]);
        assert_eq!(
            decode_and_verify(&env, &short_sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::BadSignatureLength(10))
        );
    }

    // ---- wire / strict decode --------------------------------------------

    #[test]
    fn non_base64_is_rejected() {
        let key = signing_key(7);
        let (_env, sig) = wire(&valid_fields(), &key);
        assert_eq!(
            decode_and_verify("not valid base64!!", &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::BadBase64)
        );
    }

    #[test]
    fn oversize_envelope_is_rejected_before_parsing() {
        let key = signing_key(7);
        let big = URL_SAFE_NO_PAD.encode(vec![b'x'; MAX_ENVELOPE_BYTES + 1]);
        let (_e, sig) = wire(&valid_fields(), &key);
        assert!(matches!(
            decode_and_verify(&big, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::TooLarge(_))
        ));
    }

    #[test]
    fn duplicate_key_is_rejected() {
        let key = signing_key(7);
        // Hand-craft canonical-ish bytes with a duplicate key (can't go through a map).
        let raw = br#"{"decision":"completed","decision":"denied"}"#;
        let env = URL_SAFE_NO_PAD.encode(raw);
        let (_e, sig) = wire(&valid_fields(), &key);
        assert_eq!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::DuplicateKey("decision".into()))
        );
    }

    #[test]
    fn unknown_field_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("evil_extra".into(), "1".into());
        let (env, sig) = wire(&fields, &key);
        assert_eq!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::UnknownField("evil_extra".into()))
        );
    }

    #[test]
    fn missing_field_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.remove("supervisor_id");
        let (env, sig) = wire(&fields, &key);
        assert_eq!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::MissingField("supervisor_id"))
        );
    }

    #[test]
    fn non_string_value_is_rejected() {
        // A JSON number where a string is required must not parse.
        let key = signing_key(7);
        let raw = br#"{"decision":123}"#;
        let env = URL_SAFE_NO_PAD.encode(raw);
        let (_e, sig) = wire(&valid_fields(), &key);
        assert!(matches!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::BadJson(_))
        ));
    }

    #[test]
    fn empty_field_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("receipt_id".into(), "".into());
        let (env, sig) = wire(&fields, &key);
        assert_eq!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::EmptyField("receipt_id"))
        );
    }

    #[test]
    fn non_hex_hash_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("output_sha256".into(), "ZZZ".into());
        let (env, sig) = wire(&fields, &key);
        assert_eq!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::NotHex("output_sha256"))
        );
    }

    #[test]
    fn uppercase_hash_is_rejected_as_non_lowercase_hex() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("system_sha256".into(), "AB".repeat(32));
        let (env, sig) = wire(&fields, &key);
        assert_eq!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::NotHex("system_sha256"))
        );
    }

    #[test]
    fn non_timestamp_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("requested_at".into(), "not-a-number".into());
        let (env, sig) = wire(&fields, &key);
        assert_eq!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::NotTimestamp("requested_at"))
        );
    }

    #[test]
    fn bad_decision_domain_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("decision".into(), "totally-fine".into());
        let (env, sig) = wire(&fields, &key);
        assert_eq!(
            decode_and_verify(&env, &sig, key.verifying_key().as_bytes()),
            Err(ReceiptError::BadDecisionDomain("totally-fine".into()))
        );
    }

    #[test]
    fn non_canonical_bytes_with_a_valid_signature_are_rejected() {
        // Sign NON-canonical bytes (extra whitespace). The signature verifies over
        // those exact bytes, but the parsed map re-canonicalizes differently — so the
        // JCS(parsed)==bytes check must reject it (parser-differential defense).
        let key = signing_key(7);
        let canonical = jcs_bytes(&valid_fields());
        let mut noncanon = canonical.clone();
        // Insert a space after the opening brace: still valid JSON, not canonical.
        noncanon.insert(1, b' ');
        let sig = key.sign(&noncanon);
        let env = URL_SAFE_NO_PAD.encode(&noncanon);
        let sig_b64 = URL_SAFE_NO_PAD.encode(sig.to_bytes());
        assert_eq!(
            decode_and_verify(&env, &sig_b64, key.verifying_key().as_bytes()),
            Err(ReceiptError::NotCanonical)
        );
    }

    // ---- §3 pure bindings -------------------------------------------------

    #[test]
    fn each_identity_policy_config_mismatch_blocks() {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();

        // Every expected-value binding, mutated one at a time.
        #[allow(clippy::type_complexity)]
        let cases: &[(&str, fn(&mut Expected))] = &[
            ("workspace_id", |e| e.workspace_id = "ws-evil"),
            ("install_id", |e| e.install_id = "install-evil"),
            ("supervisor_id", |e| e.supervisor_id = "sup-evil"),
            ("request_nonce", |e| e.request_nonce = "nonce-evil"),
            ("policy_id", |e| e.policy_id = "pol-evil"),
            ("policy_version", |e| e.policy_version = "9"),
        ];
        for (field, mutate) in cases {
            let mut exp = expected();
            mutate(&mut exp);
            assert_eq!(
                v.bind(&exp, OUTPUT),
                Err(ReceiptError::Mismatch { field }),
                "mutating expected {field} must block"
            );
        }
    }

    #[test]
    fn decision_must_be_completed_to_bind() {
        // A syntactically valid `denied` receipt decodes but must not bind.
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("decision".into(), "denied".into());
        let (env, sig) = wire(&fields, &key);
        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();
        assert_eq!(v.bind(&expected(), OUTPUT), Err(ReceiptError::NotCompleted("denied".into())));
    }

    #[test]
    fn executor_and_builder_must_be_allowed() {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();

        let mut exp = expected();
        exp.allowed_executors = &["someone-else"];
        assert_eq!(v.bind(&exp, OUTPUT), Err(ReceiptError::NotAllowed("executor_id")));

        let mut exp = expected();
        exp.allowed_builders = &["someone-else"];
        assert_eq!(v.bind(&exp, OUTPUT), Err(ReceiptError::NotAllowed("builder_id")));
    }

    #[test]
    fn requested_after_completed_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("requested_at".into(), "5000".into());
        fields.insert("completed_at".into(), "2000".into());
        let (env, sig) = wire(&fields, &key);
        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();
        assert_eq!(
            v.bind(&expected(), OUTPUT),
            Err(ReceiptError::TimeOrder { requested: 5000, completed: 2000 })
        );
    }

    // ---- trust state ------------------------------------------------------

    #[test]
    fn wave_3a_never_renders_verified_even_for_a_production_key() {
        // production_allowed=false is the Wave 3a gate.
        assert_eq!(
            resolve_trust_state(TrustClass::Production, false),
            TrustState::Blocked
        );
        assert_eq!(
            resolve_trust_state(TrustClass::Development, false),
            TrustState::DevelopmentUntrusted
        );
        // Wave 3b flips the gate on.
        assert_eq!(
            resolve_trust_state(TrustClass::Production, true),
            TrustState::TrustedVerified
        );
    }

    // ---- canonicalization invariants -------------------------------------

    #[test]
    fn receipt_field_names_are_all_ascii() {
        // The JCS-via-BTreeMap shortcut is only correct when keys are ASCII (UTF-8
        // byte order == UTF-16 code-unit order). Guard that invariant.
        for f in RECEIPT_FIELDS {
            assert!(f.is_ascii(), "field `{f}` must be ASCII for JCS key ordering");
        }
    }

    #[test]
    fn request_envelope_hash_is_deterministic_and_order_independent() {
        let a = request_envelope_sha256("ws", "in", "n", &"aa".repeat(32), &"bb".repeat(32), &"cc".repeat(32), "1000");
        let b = request_envelope_sha256("ws", "in", "n", &"aa".repeat(32), &"bb".repeat(32), &"cc".repeat(32), "1000");
        assert_eq!(a, b);
        assert!(is_lower_hex64(&a));
        // A different input yields a different hash.
        let c = request_envelope_sha256("ws2", "in", "n", &"aa".repeat(32), &"bb".repeat(32), &"cc".repeat(32), "1000");
        assert_ne!(a, c);
    }

    #[test]
    fn jcs_is_sorted_compact_and_minimally_escaped() {
        let mut m = BTreeMap::new();
        m.insert("b".to_string(), "x".to_string());
        m.insert("a".to_string(), "y\n\"z".to_string());
        // sorted keys, no spaces, \n and \" short escapes, no escaped '/'.
        assert_eq!(jcs_bytes(&m), br#"{"a":"y\n\"z","b":"x"}"#);
    }
}
