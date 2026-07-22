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
//!     `JCS(parsed) == decoded bytes` (no parser differentials) -> keep the bytes
//!     unchanged.
//!   * **A cryptographic type-state chain** — the only way to a render decision is
//!     `parse_strict` -> [`Parsed`] (exposes ONLY `key_id`) -> resolve the manifest
//!     key for that id -> [`Parsed::verify`] with a [`ResolvedManifestKey`] whose
//!     `key_id` MUST equal the envelope's -> [`Verified`] (carries the manifest
//!     `trust_class`) -> [`Verified::bind`] (§3 value bindings) -> [`BoundReceipt`]
//!     -> [`BoundReceipt::resolve_3a`]. Each state can only be reached from the
//!     previous, so no caller can name a trust state without a verified + bound
//!     receipt, and the signed `trust_class` travels with it the whole way.
//!   * **The Wave 3a trust gate** — [`BoundReceipt::resolve_3a`] returns a
//!     [`Wave3aTrustState`], an enum that has **no `TrustedVerified` variant at all**:
//!     Wave 3a code literally cannot name a "Verified" state. `development ⇒
//!     DevelopmentUntrusted`, `production ⇒ Blocked`. The production render path is a
//!     separate type introduced only by an audited Wave 3b change (design §5/§6:
//!     "Wave 3a never yields `trusted_verified`").
//!
//! **Two anti-forgery properties worth calling out:**
//!   * A [`ResolvedManifestKey`] has **private fields and no public constructor** —
//!     only an in-crate validated signed-manifest resolver (Wave 3b) can mint one, so
//!     a caller cannot pair an arbitrary `public_key`/`trust_class` with a `key_id`.
//!   * `request_sha256` is **recomputed** inside [`Verified::bind`] from the very
//!     [`IssuedRequest`] fields the desktop bound (§2.2), not accepted as a separate
//!     expected value — so a wiring bug cannot pair one request's hash with another
//!     request's timestamp / system / history.
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
use std::fmt;

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
    #[error("crypto: envelope `key_id` `{claimed}` != resolved manifest key `{resolved}`")]
    KeyIdMismatch { claimed: String, resolved: String },
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

/// A verifying key's **signed** trust classification from the manifest (§5). It is
/// what decides the render state — never inferred by the desktop.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrustClass {
    Production,
    Development,
}

/// The render state Wave 3a resolves a governed reply to. **It has no
/// `TrustedVerified` variant on purpose** — Wave 3a code cannot name a "Verified"
/// state at all, so the invariant "Wave 3a never yields `trusted_verified`" holds
/// across the *entire* surface, not just one method (design §6). The production
/// render state is a separate type introduced only by an audited Wave 3b change.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Wave3aTrustState {
    /// Renders + persists, badged "Development / untrusted". Never "Verified".
    DevelopmentUntrusted,
    /// Never renders, never persists to `messages`; evidence only.
    Blocked,
}

/// A verifying key resolved from the trusted signed manifest (§5): the `key_id` the
/// manifest entry is filed under, its pinned Ed25519 `public_key`, and the signed
/// `trust_class`.
///
/// **Fields are private and there is no public constructor.** Only an in-crate
/// validated signed-manifest resolver (Wave 3b) may mint one, so a caller can never
/// pair an arbitrary `public_key`/`trust_class` with a chosen `key_id` and thereby
/// (e.g.) render a production receipt as development-untrusted. Until that resolver
/// exists, only this crate's tests build fixtures via the private fields.
#[derive(Clone, Copy)]
pub struct ResolvedManifestKey<'a> {
    key_id: &'a str,
    public_key: &'a [u8],
    trust_class: TrustClass,
}

#[cfg(test)]
impl<'a> ResolvedManifestKey<'a> {
    /// Test-only fixture builder for in-crate callers OUTSIDE this module (e.g. the
    /// `receipt_store` slice-2 transaction tests). It is `#[cfg(test)]`, so the
    /// shipping crate still has **no public constructor** — the slice-1 guarantee
    /// that only the validated Wave 3b manifest resolver may mint a resolved key
    /// (private fields, no ctor) is intact. `receipt.rs`'s own tests keep building
    /// fixtures via the private fields directly.
    pub(crate) fn for_test(key_id: &'a str, public_key: &'a [u8], trust_class: TrustClass) -> Self {
        Self { key_id, public_key, trust_class }
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
/// receipt's `request_sha256` to equal it. Field set is fixed (§2.2). Prefer
/// [`IssuedRequest::request_sha256`] at call sites so the hash and the per-field
/// bindings can never come from different values.
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

/// The exact governed request the desktop issued (design §2.2). It is the **single
/// source** of both the canonical `request_sha256` and the per-field bindings, so the
/// two can never diverge — [`Verified::bind`] recomputes the hash from these very
/// fields instead of trusting a separately-supplied hash.
#[derive(Debug, Clone, Copy)]
pub struct IssuedRequest<'a> {
    pub workspace_id: &'a str,
    pub install_id: &'a str,
    pub request_nonce: &'a str,
    pub system_sha256: &'a str,
    pub history_sha256: &'a str,
    pub generation_config_sha256: &'a str,
    pub requested_at: &'a str,
}

impl IssuedRequest<'_> {
    /// The canonical `request_sha256` (design §2.2) derived from these fields.
    pub fn request_sha256(&self) -> String {
        request_envelope_sha256(
            self.workspace_id,
            self.install_id,
            self.request_nonce,
            self.system_sha256,
            self.history_sha256,
            self.generation_config_sha256,
            self.requested_at,
        )
    }
}

// ---------------------------------------------------------------------------
// Type-state 1: Parsed — structurally valid + canonical, signature NOT checked.
// ---------------------------------------------------------------------------

/// A structurally-valid envelope whose bytes are proven canonical (design §2.3 steps
/// 1–3) but whose signature is **not yet verified**. It is the type-state seam that
/// lets the caller resolve the verifying key **by the envelope's own `key_id`** (§3.1
/// — the key comes from the manifest entry for that id) before checking the signature.
///
/// Only `key_id` is readable here; every other field is reachable only through the
/// downstream [`Verified`] / [`BoundReceipt`] states, so unverified envelope data can
/// never be mistaken for verified data. `Debug` is redacted for the same reason.
#[derive(Clone, PartialEq, Eq)]
pub struct Parsed {
    fields: BTreeMap<String, String>,
    canonical_bytes: Vec<u8>,
}

impl fmt::Debug for Parsed {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Only the fields legitimately readable pre-verification (design contract).
        f.debug_struct("Parsed")
            .field("key_id", &self.key_id())
            .field("bytes_len", &self.canonical_bytes.len())
            .finish_non_exhaustive()
    }
}

impl Parsed {
    /// The signing key id the envelope claims. The caller resolves the pinned public
    /// key (and its `trust_class`) for this id from the trusted manifest, then calls
    /// [`Parsed::verify`]. This is the ONLY field exposed before verification.
    pub fn key_id(&self) -> &str {
        self.fields.get("key_id").map(String::as_str).unwrap_or("")
    }

    /// Verify the Ed25519 signature over the exact decoded bytes (§2.3 steps 4–5).
    ///
    /// First requires `self.key_id() == resolved_key.key_id` — so the key that
    /// verifies the signature is the manifest entry the envelope actually names, not
    /// some other key. Because a [`ResolvedManifestKey`] can only be minted by the
    /// validated manifest resolver, its `public_key` and `trust_class` are known to
    /// belong to that same entry. The resulting [`Verified`] carries that
    /// `trust_class`.
    pub fn verify(
        self,
        resolved_key: &ResolvedManifestKey,
        signature_b64: &str,
    ) -> Result<Verified, ReceiptError> {
        if self.key_id() != resolved_key.key_id {
            return Err(ReceiptError::KeyIdMismatch {
                claimed: self.key_id().to_string(),
                resolved: resolved_key.key_id.to_string(),
            });
        }
        let key_bytes: [u8; 32] = resolved_key
            .public_key
            .try_into()
            .map_err(|_| ReceiptError::BadKeyLength(resolved_key.public_key.len()))?;
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
            trust_class: resolved_key.trust_class,
        })
    }
}

// ---------------------------------------------------------------------------
// Type-state 2: Verified — signature checked, §3 value bindings NOT yet checked.
// ---------------------------------------------------------------------------

/// A receipt whose bytes decoded strictly, canonicalized identically, and whose
/// Ed25519 signature verified over those exact bytes under the manifest key named by
/// its own `key_id`. It still must pass [`Verified::bind`] (§3 value bindings) before
/// its output may render. Carries the signed `trust_class` of the verifying key.
#[derive(Clone, PartialEq, Eq)]
pub struct Verified {
    fields: BTreeMap<String, String>,
    canonical_bytes: Vec<u8>,
    signature: [u8; 64],
    trust_class: TrustClass,
}

impl fmt::Debug for Verified {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Verified")
            .field("key_id", &field(&self.fields, "key_id"))
            .field("receipt_id", &field(&self.fields, "receipt_id"))
            .field("trust_class", &self.trust_class)
            .finish_non_exhaustive()
    }
}

/// Everything the desktop already knows for this turn and requires the receipt to
/// match, value-for-value (design §3). Borrowed — this is a pure comparison input.
///
/// The request half is a single [`IssuedRequest`]: [`Verified::bind`] recomputes
/// `request_sha256` from it (never accepts a separate hash), so the receipt's
/// `request_sha256` is bound to the exact same workspace/install/nonce/system/
/// history/generation/timestamp values that are also checked field-by-field.
#[derive(Debug, Clone, Copy)]
pub struct Expected<'a> {
    pub request: IssuedRequest<'a>,
    pub supervisor_id: &'a str,
    pub policy_id: &'a str,
    pub policy_version: &'a str,
    pub policy_bundle_sha256: &'a str,
    pub containment_evidence_sha256: &'a str,
    pub allowed_executors: &'a [&'a str],
    pub allowed_builders: &'a [&'a str],
}

fn field<'a>(fields: &'a BTreeMap<String, String>, name: &str) -> &'a str {
    fields.get(name).map(String::as_str).unwrap_or("")
}

impl Verified {
    /// The pure subset of the §3 verification checklist: every binding that is a
    /// value comparison against what the desktop already knows, plus the output
    /// re-hash and the intra-receipt time order. `output` is the exact reply bytes
    /// (§2.1 — hashed as opaque bytes, no normalization). Any failure ⇒ **Blocked**.
    ///
    /// On success returns a [`BoundReceipt`], the only state from which a trust state
    /// can be resolved — so the badge can never be decided without a verified AND
    /// bound receipt.
    ///
    /// Not covered here (stateful, layered on in slice 2 / Wave 3b): one-time nonce
    /// consume, `receipt_id` uniqueness, key-manifest validity/epoch/revocation/
    /// anti-rollback, and wall-clock freshness/skew.
    pub fn bind(self, expected: &Expected, output: &[u8]) -> Result<BoundReceipt, ReceiptError> {
        let get = |name: &str| field(&self.fields, name);

        if get("protocol") != RECEIPT_PROTOCOL {
            return Err(ReceiptError::Protocol(get("protocol").to_string()));
        }
        if get("decision") != DECISION_COMPLETED {
            return Err(ReceiptError::NotCompleted(get("decision").to_string()));
        }

        // Identity / request-component / policy / config bindings — each an
        // expected-value match. The request fields all come from the single
        // `IssuedRequest`, and `requested_at` is bound (not merely ordered).
        let req = &expected.request;
        let equals: &[(&'static str, &str)] = &[
            ("workspace_id", req.workspace_id),
            ("install_id", req.install_id),
            ("request_nonce", req.request_nonce),
            ("system_sha256", req.system_sha256),
            ("history_sha256", req.history_sha256),
            ("generation_config_sha256", req.generation_config_sha256),
            ("requested_at", req.requested_at),
            ("supervisor_id", expected.supervisor_id),
            ("policy_id", expected.policy_id),
            ("policy_version", expected.policy_version),
            ("policy_bundle_sha256", expected.policy_bundle_sha256),
            ("containment_evidence_sha256", expected.containment_evidence_sha256),
        ];
        for (name, want) in equals {
            if get(name) != *want {
                return Err(ReceiptError::Mismatch { field: name });
            }
        }

        // `request_sha256` is RECOMPUTED from the same IssuedRequest fields (§2.2) and
        // compared — never accepted as a separate expected value. So a wiring bug can
        // never pair one request's hash with another request's components.
        if get("request_sha256") != req.request_sha256() {
            return Err(ReceiptError::Mismatch { field: "request_sha256" });
        }

        // Executor / builder must be in the allowed set for this install (§3.8).
        if !expected.allowed_executors.contains(&get("executor_id")) {
            return Err(ReceiptError::NotAllowed("executor_id"));
        }
        if !expected.allowed_builders.contains(&get("builder_id")) {
            return Err(ReceiptError::NotAllowed("builder_id"));
        }

        // Output binding: the returned bytes must hash to the signed output_sha256
        // (§2.1, exact bytes). This is what makes the signature cover the reply.
        if sha256_hex(output) != get("output_sha256") {
            return Err(ReceiptError::OutputMismatch);
        }

        // Intra-receipt time order (the wall-clock freshness window is slice 2). Both
        // fields were validated as ms integers during decode.
        let requested = get("requested_at").parse::<u64>().unwrap_or(u64::MAX);
        let completed = get("completed_at").parse::<u64>().unwrap_or(u64::MAX);
        if requested > completed {
            return Err(ReceiptError::TimeOrder { requested, completed });
        }

        Ok(BoundReceipt {
            fields: self.fields,
            canonical_bytes: self.canonical_bytes,
            signature: self.signature,
            trust_class: self.trust_class,
        })
    }
}

// ---------------------------------------------------------------------------
// Type-state 3: BoundReceipt — signature + all §3 pure bindings passed.
// ---------------------------------------------------------------------------

/// A receipt that verified AND passed every pure §3 binding. This is the only state
/// from which a [`Wave3aTrustState`] can be resolved, and it carries the signed
/// `trust_class` of the verifying key plus the exact canonical bytes + signature to
/// persist (slice 2, §4).
#[derive(Clone, PartialEq, Eq)]
pub struct BoundReceipt {
    fields: BTreeMap<String, String>,
    canonical_bytes: Vec<u8>,
    signature: [u8; 64],
    trust_class: TrustClass,
}

impl fmt::Debug for BoundReceipt {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BoundReceipt")
            .field("key_id", &self.key_id())
            .field("receipt_id", &self.receipt_id())
            .field("trust_class", &self.trust_class)
            .finish_non_exhaustive()
    }
}

impl BoundReceipt {
    /// Resolve the render state for **Wave 3a** (design §6). Returns a
    /// [`Wave3aTrustState`], which has no `TrustedVerified` variant: `development ⇒
    /// DevelopmentUntrusted`, `production ⇒ Blocked`. Wave 3a therefore cannot render
    /// "Verified" anywhere; the production path is an audited Wave 3b addition.
    pub fn resolve_3a(&self) -> Wave3aTrustState {
        match self.trust_class {
            TrustClass::Development => Wave3aTrustState::DevelopmentUntrusted,
            TrustClass::Production => Wave3aTrustState::Blocked,
        }
    }

    /// The signed `trust_class` of the key that verified this receipt.
    pub fn trust_class(&self) -> TrustClass { self.trust_class }

    /// The canonical envelope bytes, exactly as decoded and verified. Persist these
    /// unchanged (never a re-serialization) so the record stays re-verifiable (§4).
    pub fn canonical_bytes(&self) -> &[u8] { &self.canonical_bytes }
    /// The verified signature bytes, to persist alongside the envelope (§4).
    pub fn signature(&self) -> &[u8; 64] { &self.signature }

    pub fn key_id(&self) -> &str { field(&self.fields, "key_id") }
    pub fn receipt_id(&self) -> &str { field(&self.fields, "receipt_id") }
    pub fn decision(&self) -> &str { field(&self.fields, "decision") }
    pub fn output_sha256(&self) -> &str { field(&self.fields, "output_sha256") }
    pub fn request_nonce(&self) -> &str { field(&self.fields, "request_nonce") }
    pub fn requested_at(&self) -> &str { field(&self.fields, "requested_at") }
    pub fn completed_at(&self) -> &str { field(&self.fields, "completed_at") }
}

// ---------------------------------------------------------------------------
// Strict decode.
// ---------------------------------------------------------------------------

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
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
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
    for f in RECEIPT_FIELDS {
        if !map.contains_key(*f) {
            return Err(ReceiptError::MissingField(f));
        }
    }

    // Per-field value shape. Every field is non-empty; hashes are lowercase 64-hex;
    // timestamps are millisecond integers; `decision` is in its fixed domain.
    for (name, value) in &map {
        if value.is_empty() {
            // `&'static str` for the error: recover the interned field name. Safe:
            // the unknown-field pass above proved every key is in RECEIPT_FIELDS.
            let interned = RECEIPT_FIELDS.iter().find(|f| **f == name).unwrap();
            return Err(ReceiptError::EmptyField(interned));
        }
    }
    for f in HASH_FIELDS {
        if !is_lower_hex64(map.get(*f).unwrap()) {
            return Err(ReceiptError::NotHex(f));
        }
    }
    for f in TIMESTAMP_FIELDS {
        if map.get(*f).unwrap().parse::<u64>().is_err() {
            return Err(ReceiptError::NotTimestamp(f));
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

    fn hx(n: u8) -> String {
        let mut s = String::new();
        for _ in 0..32 {
            s.push_str(&format!("{n:02x}"));
        }
        s
    }

    /// A fully-valid field map for a `completed` receipt. `request_sha256` is the REAL
    /// canonical hash of the request components, so `bind`'s recompute matches. Tests
    /// mutate one field to drive a single negative case. `key_id` is always "key-dev-1".
    fn valid_fields() -> BTreeMap<String, String> {
        let request_sha256 = request_envelope_sha256(
            "ws-1", "install-1", "nonce-xyz", &hx(0x55), &hx(0x66), &hx(0x44), "1000",
        );
        let mut m = BTreeMap::new();
        m.insert("protocol".into(), RECEIPT_PROTOCOL.into());
        m.insert("receipt_id".into(), "receipt-abc".into());
        m.insert("key_id".into(), "key-dev-1".into());
        m.insert("workspace_id".into(), "ws-1".into());
        m.insert("install_id".into(), "install-1".into());
        m.insert("request_nonce".into(), "nonce-xyz".into());
        m.insert("request_sha256".into(), request_sha256);
        m.insert("decision".into(), DECISION_COMPLETED.into());
        m.insert("policy_id".into(), "pol-1".into());
        m.insert("policy_version".into(), "1".into());
        m.insert("policy_bundle_sha256".into(), hx(0x22));
        m.insert("containment_evidence_sha256".into(), hx(0x33));
        m.insert("generation_config_sha256".into(), hx(0x44));
        m.insert("system_sha256".into(), hx(0x55));
        m.insert("history_sha256".into(), hx(0x66));
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
        (URL_SAFE_NO_PAD.encode(&bytes), URL_SAFE_NO_PAD.encode(sig.to_bytes()))
    }

    /// The manifest key for the receipts in these tests (`key-dev-1`), with a chosen
    /// trust class. Only in-crate code (like this test module, via the private fields)
    /// can build one; production goes through the Wave 3b manifest resolver.
    fn resolved(pk: &[u8], trust: TrustClass) -> ResolvedManifestKey<'_> {
        ResolvedManifestKey { key_id: "key-dev-1", public_key: pk, trust_class: trust }
    }

    // Owned hex strings for the expected bindings — `Expected`/`IssuedRequest` borrow.
    struct ExpHashes {
        bundle: String,
        containment: String,
        generation: String,
        system: String,
        history: String,
        wrong: String,
    }
    static EXP: std::sync::LazyLock<ExpHashes> = std::sync::LazyLock::new(|| ExpHashes {
        bundle: "22".repeat(32),
        containment: "33".repeat(32),
        generation: "44".repeat(32),
        system: "55".repeat(32),
        history: "66".repeat(32),
        wrong: "00".repeat(32),
    });

    fn expected() -> Expected<'static> {
        Expected {
            request: IssuedRequest {
                workspace_id: "ws-1",
                install_id: "install-1",
                request_nonce: "nonce-xyz",
                system_sha256: &EXP.system,
                history_sha256: &EXP.history,
                generation_config_sha256: &EXP.generation,
                requested_at: "1000",
            },
            supervisor_id: "sup-1",
            policy_id: "pol-1",
            policy_version: "1",
            policy_bundle_sha256: &EXP.bundle,
            containment_evidence_sha256: &EXP.containment,
            allowed_executors: &["exec-1", "exec-2"],
            allowed_builders: &["build-1"],
        }
    }

    /// Full happy-path flow to a `BoundReceipt` under a chosen trust class.
    fn bound_with(trust: TrustClass) -> BoundReceipt {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        parse_strict(&env)
            .unwrap()
            .verify(&resolved(key.verifying_key().as_bytes(), trust), &sig)
            .unwrap()
            .bind(&expected(), OUTPUT)
            .unwrap()
    }

    /// Test convenience: parse → verify with a development key for `key-dev-1`. The
    /// real flow resolves the key by `key_id`; the dedicated key_id-mismatch test
    /// covers that seam. Returns the `Verified` (bind is exercised separately).
    fn decode_and_verify(env: &str, sig: &str, pk: &[u8]) -> Result<Verified, ReceiptError> {
        parse_strict(env)?.verify(&resolved(pk, TrustClass::Development), sig)
    }

    // ---- happy path -------------------------------------------------------

    #[test]
    fn a_valid_receipt_verifies_binds_and_resolves_dev() {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        let bound = parse_strict(&env)
            .unwrap()
            .verify(&resolved(key.verifying_key().as_bytes(), TrustClass::Development), &sig)
            .unwrap()
            .bind(&expected(), OUTPUT)
            .unwrap();
        assert_eq!(bound.decision(), "completed");
        assert_eq!(bound.resolve_3a(), Wave3aTrustState::DevelopmentUntrusted);
        // The stored bytes are exactly what was signed.
        assert_eq!(bound.canonical_bytes(), jcs_bytes(&valid_fields()).as_slice());
    }

    // ---- key-id ↔ key binding (blocker 1) ---------------------------------

    #[test]
    fn key_id_is_readable_before_verification() {
        let key = signing_key(7);
        let (env, _sig) = wire(&valid_fields(), &key);
        assert_eq!(parse_strict(&env).unwrap().key_id(), "key-dev-1");
    }

    #[test]
    fn claimed_key_id_must_equal_resolved_key_id() {
        // The envelope claims `key-dev-1`; a manifest key filed under a DIFFERENT id
        // (even with the correct public key) must be refused before any signature
        // check — a compromised wiring can't verify a prod-id envelope with a dev key.
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);
        let vk = key.verifying_key();
        let wrong_id = ResolvedManifestKey {
            key_id: "key-prod-9",
            public_key: vk.as_bytes(),
            trust_class: TrustClass::Development,
        };
        assert_eq!(
            parse_strict(&env).unwrap().verify(&wrong_id, &sig),
            Err(ReceiptError::KeyIdMismatch {
                claimed: "key-dev-1".into(),
                resolved: "key-prod-9".into(),
            })
        );
    }

    // ---- crypto -----------------------------------------------------------

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
        let (_env, sig) = wire(&fields, &key);
        // Flip a field and re-encode with the OLD signature.
        fields.insert("workspace_id".into(), "ws-evil".into());
        let forged_env = URL_SAFE_NO_PAD.encode(jcs_bytes(&fields));
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
        assert_eq!(parse_strict("not valid base64!!"), Err(ReceiptError::BadBase64));
    }

    #[test]
    fn oversize_envelope_is_rejected_before_parsing() {
        let big = URL_SAFE_NO_PAD.encode(vec![b'x'; MAX_ENVELOPE_BYTES + 1]);
        assert!(matches!(parse_strict(&big), Err(ReceiptError::TooLarge(_))));
    }

    #[test]
    fn duplicate_key_is_rejected() {
        let raw = br#"{"decision":"completed","decision":"denied"}"#;
        let env = URL_SAFE_NO_PAD.encode(raw);
        assert_eq!(parse_strict(&env), Err(ReceiptError::DuplicateKey("decision".into())));
    }

    #[test]
    fn unknown_field_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("evil_extra".into(), "1".into());
        let (env, _sig) = wire(&fields, &key);
        assert_eq!(parse_strict(&env), Err(ReceiptError::UnknownField("evil_extra".into())));
    }

    #[test]
    fn missing_field_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.remove("supervisor_id");
        let (env, _sig) = wire(&fields, &key);
        assert_eq!(parse_strict(&env), Err(ReceiptError::MissingField("supervisor_id")));
    }

    #[test]
    fn non_string_value_is_rejected() {
        let raw = br#"{"decision":123}"#;
        let env = URL_SAFE_NO_PAD.encode(raw);
        assert!(matches!(parse_strict(&env), Err(ReceiptError::BadJson(_))));
    }

    #[test]
    fn empty_field_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("receipt_id".into(), "".into());
        let (env, _sig) = wire(&fields, &key);
        assert_eq!(parse_strict(&env), Err(ReceiptError::EmptyField("receipt_id")));
    }

    #[test]
    fn non_hex_hash_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("output_sha256".into(), "ZZZ".into());
        let (env, _sig) = wire(&fields, &key);
        assert_eq!(parse_strict(&env), Err(ReceiptError::NotHex("output_sha256")));
    }

    #[test]
    fn uppercase_hash_is_rejected_as_non_lowercase_hex() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("system_sha256".into(), "AB".repeat(32));
        let (env, _sig) = wire(&fields, &key);
        assert_eq!(parse_strict(&env), Err(ReceiptError::NotHex("system_sha256")));
    }

    #[test]
    fn non_timestamp_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("requested_at".into(), "not-a-number".into());
        let (env, _sig) = wire(&fields, &key);
        assert_eq!(parse_strict(&env), Err(ReceiptError::NotTimestamp("requested_at")));
    }

    #[test]
    fn bad_decision_domain_is_rejected() {
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("decision".into(), "totally-fine".into());
        let (env, _sig) = wire(&fields, &key);
        assert_eq!(parse_strict(&env), Err(ReceiptError::BadDecisionDomain("totally-fine".into())));
    }

    #[test]
    fn non_canonical_bytes_with_a_valid_signature_are_rejected() {
        // Sign NON-canonical bytes (extra whitespace). The signature would verify over
        // those exact bytes, but the parsed map re-canonicalizes differently — so the
        // JCS(parsed)==bytes check rejects it at parse time (parser-differential
        // defense), before a key is even resolved.
        let canonical = jcs_bytes(&valid_fields());
        let mut noncanon = canonical.clone();
        noncanon.insert(1, b' '); // space after '{': valid JSON, not canonical
        let env = URL_SAFE_NO_PAD.encode(&noncanon);
        assert_eq!(parse_strict(&env), Err(ReceiptError::NotCanonical));
    }

    // ---- §3 pure bindings + request-hash recompute (blocker 3) ------------

    #[test]
    fn every_expected_value_mismatch_blocks() {
        let key = signing_key(7);
        let (env, sig) = wire(&valid_fields(), &key);

        // Each expected-value binding, mutated one at a time — every request component
        // (from the IssuedRequest), the desktop-issued requested_at, and every policy/
        // config field. (request_sha256 is no longer an input — it is recomputed.)
        #[allow(clippy::type_complexity)]
        let cases: &[(&str, fn(&mut Expected))] = &[
            ("workspace_id", |e| e.request.workspace_id = "ws-evil"),
            ("install_id", |e| e.request.install_id = "install-evil"),
            ("request_nonce", |e| e.request.request_nonce = "nonce-evil"),
            ("system_sha256", |e| e.request.system_sha256 = &EXP.wrong),
            ("history_sha256", |e| e.request.history_sha256 = &EXP.wrong),
            ("generation_config_sha256", |e| e.request.generation_config_sha256 = &EXP.wrong),
            ("requested_at", |e| e.request.requested_at = "9999"),
            ("supervisor_id", |e| e.supervisor_id = "sup-evil"),
            ("policy_id", |e| e.policy_id = "pol-evil"),
            ("policy_version", |e| e.policy_version = "9"),
            ("policy_bundle_sha256", |e| e.policy_bundle_sha256 = &EXP.wrong),
            ("containment_evidence_sha256", |e| e.containment_evidence_sha256 = &EXP.wrong),
        ];
        for (name, mutate) in cases {
            // Fresh Verified per case (bind consumes it).
            let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();
            let mut exp = expected();
            mutate(&mut exp);
            assert_eq!(
                v.bind(&exp, OUTPUT),
                Err(ReceiptError::Mismatch { field: name }),
                "mutating expected {name} must block"
            );
        }
    }

    #[test]
    fn request_sha256_must_equal_the_hash_recomputed_from_the_components() {
        // Blocker 3: every request COMPONENT is correct, but the receipt's
        // request_sha256 is a wrong (yet well-formed) hash. bind must recompute the
        // canonical request hash from the IssuedRequest and reject the mismatch — a
        // separate/forged hash can never diverge from the bound components.
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("request_sha256".into(), "99".repeat(32));
        let (env, sig) = wire(&fields, &key);
        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();
        assert_eq!(
            v.bind(&expected(), OUTPUT),
            Err(ReceiptError::Mismatch { field: "request_sha256" })
        );
    }

    #[test]
    fn decision_must_be_completed_to_bind() {
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

        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();
        let mut exp = expected();
        exp.allowed_builders = &["someone-else"];
        assert_eq!(v.bind(&exp, OUTPUT), Err(ReceiptError::NotAllowed("builder_id")));
    }

    #[test]
    fn requested_after_completed_is_rejected() {
        // requested_at must still be <= completed_at. Move BOTH the receipt and the
        // expected requested_at (and recompute the receipt's request hash) so the
        // exact-match bindings pass and the time-order check is what fires.
        let key = signing_key(7);
        let mut fields = valid_fields();
        fields.insert("requested_at".into(), "5000".into());
        fields.insert("completed_at".into(), "2000".into());
        fields.insert(
            "request_sha256".into(),
            request_envelope_sha256("ws-1", "install-1", "nonce-xyz", &hx(0x55), &hx(0x66), &hx(0x44), "5000"),
        );
        let (env, sig) = wire(&fields, &key);
        let v = decode_and_verify(&env, &sig, key.verifying_key().as_bytes()).unwrap();
        let mut exp = expected();
        exp.request.requested_at = "5000";
        assert_eq!(
            v.bind(&exp, OUTPUT),
            Err(ReceiptError::TimeOrder { requested: 5000, completed: 2000 })
        );
    }

    // ---- trust state (blocker 2) -----------------------------------------

    #[test]
    fn trust_state_is_only_reachable_from_a_bound_receipt() {
        // Compile-time: `resolve_3a` exists only on BoundReceipt, and BoundReceipt is
        // only produced by `Verified::bind`. This test exercises that path.
        assert_eq!(
            bound_with(TrustClass::Development).resolve_3a(),
            Wave3aTrustState::DevelopmentUntrusted
        );
    }

    #[test]
    fn wave_3a_blocks_a_production_key_and_has_no_verified_state() {
        // A production-class key that fully verifies AND binds resolves to Blocked in
        // 3a. `Wave3aTrustState` has no TrustedVerified variant, so no code path —
        // resolve_3a or otherwise — can render "Verified" in Wave 3a.
        assert_eq!(bound_with(TrustClass::Production).resolve_3a(), Wave3aTrustState::Blocked);
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
    fn request_envelope_hash_is_deterministic_and_input_sensitive() {
        let a = request_envelope_sha256("ws", "in", "n", &"aa".repeat(32), &"bb".repeat(32), &"cc".repeat(32), "1000");
        let b = request_envelope_sha256("ws", "in", "n", &"aa".repeat(32), &"bb".repeat(32), &"cc".repeat(32), "1000");
        assert_eq!(a, b);
        assert!(is_lower_hex64(&a));
        let c = request_envelope_sha256("ws2", "in", "n", &"aa".repeat(32), &"bb".repeat(32), &"cc".repeat(32), "1000");
        assert_ne!(a, c);
        // IssuedRequest derives the same hash.
        let r = IssuedRequest {
            workspace_id: "ws", install_id: "in", request_nonce: "n",
            system_sha256: &"aa".repeat(32), history_sha256: &"bb".repeat(32),
            generation_config_sha256: &"cc".repeat(32), requested_at: "1000",
        };
        assert_eq!(r.request_sha256(), a);
    }

    #[test]
    fn request_envelope_jcs_matches_python_cross_language_parity() {
        // Cross-language parity (design §2, §10.1): Rust's canonical request-envelope
        // hash MUST byte-equal Python's JCS (json.dumps sort_keys, compact separators)
        // for the same envelope. `bridge/tests/test_jcs_parity.py` asserts the SAME
        // hex from Python — if either side's canonicalization drifts, both break.
        let hash = request_envelope_sha256(
            "ws-1", "install-1", "nonce-xyz",
            &"55".repeat(32), &"66".repeat(32), &"44".repeat(32), "1000",
        );
        assert_eq!(hash, "e6b54c0426e36d869d0451dbc68480c87f053bcea52f3fff52ba9cd10723f31b");
    }

    #[test]
    fn jcs_is_sorted_compact_and_minimally_escaped() {
        let mut m = BTreeMap::new();
        m.insert("b".to_string(), "x".to_string());
        m.insert("a".to_string(), "y\n\"z".to_string());
        assert_eq!(jcs_bytes(&m), br#"{"a":"y\n\"z","b":"x"}"#);
    }

    #[test]
    fn parsed_debug_does_not_leak_envelope_fields() {
        // The pre-verification contract: only key_id (+ a byte length) is observable.
        let key = signing_key(7);
        let (env, _sig) = wire(&valid_fields(), &key);
        let dbg = format!("{:?}", parse_strict(&env).unwrap());
        assert!(dbg.contains("key-dev-1"), "key_id is allowed: {dbg}");
        assert!(!dbg.contains(&"55".repeat(32)), "system_sha256 leaked into Debug: {dbg}");
        assert!(!dbg.contains("nonce-xyz"), "request_nonce leaked into Debug: {dbg}");
    }
}
