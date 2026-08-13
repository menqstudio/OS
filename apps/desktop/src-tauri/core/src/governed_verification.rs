//! Wave 3b-1B — broker-owned FINAL ACCEPTANCE verification binding (implements the design-GREEN rev-30
//! §7 / §7.1 desktop/broker acceptance predicate + §4.6/§4.9 "authority rule").
//!
//! This is the **pure, I/O-free heart** of the trusted broker's *final* acceptance step (§6.1 step 14).
//! It takes ONLY injected inputs — no live sockets, no protected-store access, no clock — and decides
//! whether an isolated-signer receipt envelope (§4.9 artifact #12) + a supervisor attestation (§4.6)
//! *authorize* the exact reply bytes the broker is about to commit. Everything the broker trusts here is
//! either (a) a signature it re-verifies against a **pinned** manifest key, or (b) a value it recomputes
//! from its OWN trusted `Expected` resolution — never a bare transported echo (§4.6 authority rule:
//! "a bare bridge/sign-result echo never authorizes anything; the desktop never dereferences a store
//! handle; a mismatch Blocks").
//!
//! ## What the broker verifies here (rev-30 §7.1, in order)
//!
//! PARTIAL vs §7.1, and exactly where: envelope signature, attestation signature + turn
//! binding, request binding, output binding, the `_ms` FRESHNESS window and the receipt-id/nonce
//! replay claim are all implemented here. What §7.1 assigns to OTHER code and is NOT done in this
//! module: the §4.10(f) output fetch/reassemble (the caller hands the finished bytes in) and the
//! bridge/sign-result ECHO equality (the caller's frame handling). Read the numbered list as the
//! whole of what THIS function decides, never as the whole of §7.1.
//!  1. **Envelope identity** — `artifact_type` is the frozen §4.9 const and `key_id` equals the pinned
//!     isolated-signer key id; `supervisor_attestation_key_id` equals the pinned attestation key id.
//!  2. **Isolated-signer signature** — Ed25519 (`verify_strict`) over `JCS(payload)` under the pinned
//!     isolated-signer key. The payload JCS is **reconstructed** here from the envelope fields (sorted
//!     compact `serde_json` of a `Map`, RFC-8785-compatible for the ASCII key set — the same shortcut
//!     `receipt.rs` documents), so tampering ANY field breaks the signature.
//!  3. **Supervisor attestation** — Ed25519 over the attested `evidence_jcs` under the pinned attestation
//!     key, AND `SHA256(evidence_jcs) == envelope.attestation_evidence_sha256` (the envelope's binding to
//!     the exact bytes the supervisor signed, §4.9), AND — audit round 3 — the evidence is **PARSED** and
//!     required to be an account of *this* turn: `decision == "completed"`, the run identity matches the
//!     one the broker authorized, the request identity matches the broker's own `Expected`, and every
//!     field the evidence and the envelope both carry agrees. See [`bind_attested_evidence`].
//!  4. **Request binding** — `request_sha256` is **recomputed** from the broker's OWN trusted `Expected`
//!     ([`receipt::IssuedRequest`], carrying the system/history/generation_config/context hashes the
//!     broker resolved itself) via the frozen `receipt::request_envelope_sha256` formula, and required to
//!     equal `envelope.request_sha256`; `workspace_id`/`install_id`/`request_nonce` must also match the
//!     `Expected` value-for-value. A separate/forged hash can never diverge from the bound components.
//!  5. **Output binding** — `len(output) == envelope.output_bytes` (length gate) AND
//!     `SHA256(output) == envelope.output_sha256` (digest gate) over the **raw bytes**, with **no**
//!     trim/NFC/NFKC/CRLF/lossy decode (§4.6 P0-3). Only then is the output strict-UTF8 decoded for the
//!     committed body.
//!  6. **`receipt_id` freshness** — refused if the injected seen-set already contains it (global-unique
//!     replay defense, §7.1(d)).
//!  7. **`request_nonce` one-time consume** — the injected ledger consumes the nonce atomically; a
//!     second consume of the same nonce Blocks (§7.1(c), keyed by the pre-stored `receipt_challenges`
//!     nonce). On success the `receipt_id` is recorded so a later replay is caught at step 6.
//!  8. **Freshness (§7.1 "Freshness", §1 window-nesting)** — the envelope's own signed `_ms` fields
//!     (`challenge_accepted_at_ms`, `completed_at_ms`) must be legal §1 values, correctly ordered, and
//!     inside `FreshnessWindow{future_skew_ms: 60000, max_age_ms: 300000}` around the broker's injected
//!     `now_ms`. Ordered BEFORE the ledger claim (step 6+7) so a stale receipt burns no nonce; §6.1
//!     step 14 lists it after, but that ordering is about what runs inside the `BEGIN IMMEDIATE` tx,
//!     and this module claims the ledger last on purpose. See [`check_receipt_freshness`].
//!
//!     **What freshness is worth, exactly.** The acceptance ledger already stops the SAME receipt
//!     being accepted twice. Freshness is the different property: a bound on how old a
//!     never-yet-accepted receipt may be. Without it a validly-signed envelope kept from a year ago —
//!     or produced under a key that has since been rotated out but was pinned when it signed — is
//!     accepted today. It is measured against the LOCAL wall clock, which is what §1 names ("the
//!     desktop's own receipt-freshness window is ms … vs `now_ms`", "engine↔desktop wall-clock skew
//!     bounded ≤ 60000 ms (shared NTP)"); an attacker who can roll this machine's clock back can
//!     therefore still widen the window. That residual is the design's, not a shortcut here.
//!
//! Any failure ⇒ **Block** (no committed frame): a signature/binding/identity/freshness/nonce failure is
//! [`TurnReason::UpstreamBlocked`]; an output length/digest disagreement is
//! [`TurnReason::CommitReadbackMismatch`] (the same fail-closed reason `governed_message_store` uses when
//! the committed row disagrees with the accepted output). On success this returns the
//! [`AcceptedOutput`](crate::governed_message_store::AcceptedOutput) the broker hands to
//! `governed_message_store::persist_committed` — whose in-transaction re-read then re-checks the very same
//! `envelope_body_sha256` (defence in depth). **No message is persisted here**; this module only decides
//! *whether* the bytes are accepted.
//!
//! **Verify-only:** like `receipt.rs`, the Ed25519 *signing* half is compiled solely under
//! `#[cfg(test)]`, so the shipping broker core is never a `sign(arbitrary_bytes)` oracle.

use std::collections::{BTreeMap, HashSet};
use std::fmt;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use ed25519_dalek::{Signature, VerifyingKey};
use serde::de::{self, Deserializer, MapAccess, Visitor};
use serde::Deserialize;
use serde_json::{Map, Number, Value};

use crate::governed_message_store::AcceptedOutput;
use crate::governed_turn_ipc::TurnReason;
use crate::receipt::{sha256_hex, IssuedRequest};
use crate::receipt_store::FreshnessWindow;

/// The frozen `artifact_type` / `protocol` discriminator of the isolated-signer receipt envelope
/// (§4.9 artifact #12). Any other value is refused before a signature is even checked.
pub const RECEIPT_ENVELOPE_ARTIFACT_TYPE: &str = "brops.governed-receipt-envelope.v1";

/// Upper bound on the base64url of an Ed25519 signature (86 chars); reject longer input before decoding
/// so a giant `signature_b64` cannot force a large allocation (mirrors `receipt.rs`).
const MAX_SIG_B64_LEN: usize = 128;

/// The isolated-signer receipt envelope (§4.9 artifact #12) as its **payload fields** — everything the
/// signer put under `JCS(payload)`. The broker reconstructs `JCS(payload)` from exactly these fields and
/// re-verifies the isolated-signer signature over it, so no field can be tampered without breaking the
/// signature. Only a subset is *cross-bound* here (request/output/receipt/attestation-digest); the
/// remaining handles/head fields are carried verbatim so the reconstructed JCS is byte-faithful to what
/// the signer signed (their deep protected-store verification is the isolated signer's job, §7 — the
/// broker has no store access).
///
/// Borrowed — this is a pure verification input. `output_bytes` / the `_ms` / `evidence_*` counters are
/// the envelope's **integer** JSON fields (serialized as bare integers in the JCS, never quoted).
#[derive(Debug, Clone, Copy)]
pub struct ReceiptEnvelope<'a> {
    pub artifact_type: &'a str,
    pub key_id: &'a str,
    pub receipt_id: &'a str,
    pub run_id: &'a str,
    pub execution_attempt_id: &'a str,
    pub task_id: &'a str,
    pub workspace_id: &'a str,
    pub install_id: &'a str,
    pub request_nonce: &'a str,
    pub request_sha256: &'a str,
    pub record_handle: &'a str,
    pub lease_handle: &'a str,
    pub execution_receipt_handle: &'a str,
    pub output_sha256: &'a str,
    pub output_bytes: u64,
    pub challenge_accepted_at_ms: i64,
    pub completed_at_ms: i64,
    pub evidence_final_event_hash: &'a str,
    pub evidence_event_count: i64,
    pub evidence_last_sequence: i64,
    pub evidence_head_sequence: i64,
    pub supervisor_attestation_key_id: &'a str,
    pub attestation_evidence_sha256: &'a str,
}

impl ReceiptEnvelope<'_> {
    /// The canonical `JCS(payload)` bytes — sorted-key, compact `serde_json` of a `Map` (RFC 8785 for
    /// this fixed ASCII key set), exactly the bytes the isolated signer signs. `serde_json::Map` is
    /// `BTreeMap`-backed by default (the crate does not enable `preserve_order`), so keys come out sorted
    /// and whitespace-free; integer fields serialize as bare integers. Same shortcut `receipt.rs`
    /// documents for its `BTreeMap<String,String>` envelope, extended to the mixed string/integer shape.
    fn payload_jcs(&self) -> Result<Vec<u8>, TurnReason> {
        // Direct inserts (no capturing closures) so the mutable borrow of `m` is trivially local.
        let str_fields: [(&str, &str); 17] = [
            ("artifact_type", self.artifact_type),
            ("key_id", self.key_id),
            ("receipt_id", self.receipt_id),
            ("run_id", self.run_id),
            ("execution_attempt_id", self.execution_attempt_id),
            ("task_id", self.task_id),
            ("workspace_id", self.workspace_id),
            ("install_id", self.install_id),
            ("request_nonce", self.request_nonce),
            ("request_sha256", self.request_sha256),
            ("record_handle", self.record_handle),
            ("lease_handle", self.lease_handle),
            ("execution_receipt_handle", self.execution_receipt_handle),
            ("output_sha256", self.output_sha256),
            ("evidence_final_event_hash", self.evidence_final_event_hash),
            ("supervisor_attestation_key_id", self.supervisor_attestation_key_id),
            ("attestation_evidence_sha256", self.attestation_evidence_sha256),
        ];
        // Integer fields — serialized as BARE JSON integers (never quoted).
        let num_fields: [(&str, Number); 6] = [
            ("output_bytes", Number::from(self.output_bytes)),
            ("challenge_accepted_at_ms", Number::from(self.challenge_accepted_at_ms)),
            ("completed_at_ms", Number::from(self.completed_at_ms)),
            ("evidence_event_count", Number::from(self.evidence_event_count)),
            ("evidence_last_sequence", Number::from(self.evidence_last_sequence)),
            ("evidence_head_sequence", Number::from(self.evidence_head_sequence)),
        ];

        let mut m: Map<String, Value> = Map::new();
        for (k, v) in str_fields {
            m.insert(k.to_string(), Value::String(v.to_string()));
        }
        for (k, v) in num_fields {
            m.insert(k.to_string(), Value::Number(v));
        }
        serde_json::to_vec(&Value::Object(m)).map_err(|_| TurnReason::UpstreamBlocked)
    }
}

/// The same 23-key §4.9 payload, OWNED — parsed once out of a wire document so a borrowed
/// [`ReceiptEnvelope`] can point at it.
///
/// It lives here rather than beside its caller because there is now more than one caller, and the
/// mapping from the isolated signer's 23 JSON keys onto the 23 struct fields is a CONTRACT: a second
/// copy is a second thing that can drift from the payload the signer actually emits, and drift in a
/// deserializer is invisible until the day the two disagree about which field the digest lives in.
/// `broker/src/chain_executor.rs` held the only copy until 2026-08-12, when the §4.10(f) live pull
/// driver (`core/src/bin/ladder_output_pull.rs`) needed the same mapping to turn a real §4.6 frame's
/// `envelope_jcs` into the envelope `governed_output_pull::pull_output` reads its signed length and
/// digest off.
///
/// It parses and it does NOT verify. A `ReceiptEnvelope` built from this is exactly as trustworthy as
/// the bytes it came from — which is why every gate that matters takes the envelope only after
/// [`verify_and_accept`] has checked the signature over those same bytes.
#[derive(Debug, Clone)]
pub struct OwnedReceiptEnvelope {
    artifact_type: String,
    key_id: String,
    receipt_id: String,
    run_id: String,
    execution_attempt_id: String,
    task_id: String,
    workspace_id: String,
    install_id: String,
    request_nonce: String,
    request_sha256: String,
    record_handle: String,
    lease_handle: String,
    execution_receipt_handle: String,
    output_sha256: String,
    evidence_final_event_hash: String,
    supervisor_attestation_key_id: String,
    attestation_evidence_sha256: String,
    output_bytes: u64,
    challenge_accepted_at_ms: i64,
    completed_at_ms: i64,
    evidence_event_count: i64,
    evidence_last_sequence: i64,
    evidence_head_sequence: i64,
}

impl OwnedReceiptEnvelope {
    /// Strict-parse the flat 23-key payload. A missing or mistyped key fails closed BEFORE any
    /// signature check — `verify_and_accept` re-checks the identity fields regardless.
    pub fn from_payload(p: &Value) -> Result<Self, TurnReason> {
        let s = |k: &str| {
            p.get(k)
                .and_then(Value::as_str)
                .map(str::to_string)
                .ok_or(TurnReason::UpstreamBlocked)
        };
        let i = |k: &str| p.get(k).and_then(Value::as_i64).ok_or(TurnReason::UpstreamBlocked);
        let u = |k: &str| p.get(k).and_then(Value::as_u64).ok_or(TurnReason::UpstreamBlocked);
        Ok(OwnedReceiptEnvelope {
            artifact_type: s("artifact_type")?,
            key_id: s("key_id")?,
            receipt_id: s("receipt_id")?,
            run_id: s("run_id")?,
            execution_attempt_id: s("execution_attempt_id")?,
            task_id: s("task_id")?,
            workspace_id: s("workspace_id")?,
            install_id: s("install_id")?,
            request_nonce: s("request_nonce")?,
            request_sha256: s("request_sha256")?,
            record_handle: s("record_handle")?,
            lease_handle: s("lease_handle")?,
            execution_receipt_handle: s("execution_receipt_handle")?,
            output_sha256: s("output_sha256")?,
            evidence_final_event_hash: s("evidence_final_event_hash")?,
            supervisor_attestation_key_id: s("supervisor_attestation_key_id")?,
            attestation_evidence_sha256: s("attestation_evidence_sha256")?,
            output_bytes: u("output_bytes")?,
            challenge_accepted_at_ms: i("challenge_accepted_at_ms")?,
            completed_at_ms: i("completed_at_ms")?,
            evidence_event_count: i("evidence_event_count")?,
            evidence_last_sequence: i("evidence_last_sequence")?,
            evidence_head_sequence: i("evidence_head_sequence")?,
        })
    }

    /// Borrow it as the verification input.
    pub fn as_receipt_envelope(&self) -> ReceiptEnvelope<'_> {
        ReceiptEnvelope {
            artifact_type: &self.artifact_type,
            key_id: &self.key_id,
            receipt_id: &self.receipt_id,
            run_id: &self.run_id,
            execution_attempt_id: &self.execution_attempt_id,
            task_id: &self.task_id,
            workspace_id: &self.workspace_id,
            install_id: &self.install_id,
            request_nonce: &self.request_nonce,
            request_sha256: &self.request_sha256,
            record_handle: &self.record_handle,
            lease_handle: &self.lease_handle,
            execution_receipt_handle: &self.execution_receipt_handle,
            output_sha256: &self.output_sha256,
            output_bytes: self.output_bytes,
            challenge_accepted_at_ms: self.challenge_accepted_at_ms,
            completed_at_ms: self.completed_at_ms,
            evidence_final_event_hash: &self.evidence_final_event_hash,
            evidence_event_count: self.evidence_event_count,
            evidence_last_sequence: self.evidence_last_sequence,
            evidence_head_sequence: self.evidence_head_sequence,
            supervisor_attestation_key_id: &self.supervisor_attestation_key_id,
            attestation_evidence_sha256: &self.attestation_evidence_sha256,
        }
    }

    /// The `receipt_id` the isolated signer bound into the payload.
    ///
    /// Exposed for ONE purpose: the §4.10(f) live pull driver's `binding-mismatch` negative control has
    /// to present a receipt id that is NOT this turn's, and it must build that value from the real one
    /// so the frame it sends is well-formed in every other respect. Nothing gates on it — the gate is
    /// server-side, in `governed_output_read.gate_output_read`, which compares the row's three-tuple.
    pub fn receipt_id(&self) -> &str {
        &self.receipt_id
    }
}

/// The supervisor attestation (§4.6): the exact `JCS(governed-sign-request evidence)` bytes the supervisor
/// signed, plus its detached Ed25519 signature (base64url). The broker re-verifies the signature under the
/// pinned attestation key AND checks `SHA256(evidence_jcs) == envelope.attestation_evidence_sha256`.
#[derive(Debug, Clone, Copy)]
pub struct SupervisorAttestation<'a> {
    pub evidence_jcs: &'a [u8],
    pub signature_b64: &'a str,
}

// =================================================================================================
// The attested evidence (§4.6) — PARSED, not merely hashed.
//
// AUDIT (round 3). Step 3 used to do exactly two things with `evidence_jcs`: verify the supervisor's
// signature over it, and check `SHA256(evidence_jcs) == envelope.attestation_evidence_sha256`. It
// never looked inside. Both of those hold for a supervisor attestation about a COMPLETELY DIFFERENT
// turn, so the "supervisor attestation" contributed no fact about the run being accepted — it proved
// only that the supervisor had, at some point, attested something, and that the signer had committed
// to those bytes. Whether the attested run was this run was decided by nobody.
//
// The bytes are now parsed into the fixed §4.6 evidence record and required to be an account of THIS
// turn. What that buys, stated exactly: the supervisor's signed account and the isolated signer's
// signed account must AGREE, field by field, on every fact they share, and both must agree with the
// broker's own resolution. It does not detect a supervisor and a signer that lie consistently — a
// second opinion catches disagreement, not a coherent forgery by both key holders.
// =================================================================================================

/// Upper bound on the attested `evidence_jcs`. The §4.6 evidence is a fixed 29-key record of small
/// ids, 64-hex handles and integers; anything larger is malformed or hostile and is refused before
/// any parse allocation (mirrors `receipt::MAX_ENVELOPE_BYTES`).
pub const MAX_ATTESTATION_EVIDENCE_BYTES: usize = 16 * 1024;

/// The only `decision` that is a grant (§3.2 / §4.6). The supervisor STAMPS this itself.
const EVIDENCE_DECISION_COMPLETED: &str = "completed";

/// The 23 string-valued keys of the attested evidence object. This set is frozen by
/// `governed_supervisor.evidence_from_state` + `isolated_signer.EVIDENCE_FIELDS` (Linux) and
/// `win-live/src/servers.rs::attest_run` + `ATTEST_INPUT_FIELDS` (Windows) — both platforms build
/// the identical 29-key object, which is what lets one parser serve both.
const EVIDENCE_STRING_KEYS: [&str; 23] = [
    "builder_id",
    "containment_evidence_handle",
    "decision",
    "evidence_final_event_hash",
    "execution_attempt_id",
    "execution_receipt_handle",
    "executor_id",
    "generation_config_handle",
    "history_handle",
    "install_id",
    "lease_handle",
    "output_handle",
    "policy_bundle_handle",
    "policy_id",
    "policy_version",
    "receipt_id",
    "record_handle",
    "request_nonce",
    "run_id",
    "supervisor_id",
    "system_handle",
    "task_id",
    "workspace_id",
];

/// The 6 integer-valued keys of the attested evidence object (bare JSON integers, never quoted).
const EVIDENCE_INTEGER_KEYS: [&str; 6] = [
    "challenge_accepted_at_ms",
    "completed_at",
    "evidence_event_count",
    "evidence_head_sequence",
    "evidence_last_sequence",
    "requested_at",
];

/// One attested evidence value: the record is flat and every value is either a string or a bare
/// integer. A nested object, an array, a bool, a null or a float is a shape violation, not a value.
#[derive(Debug, Clone, PartialEq, Eq)]
enum EvidenceValue {
    Str(String),
    Int(i64),
}

/// A strict `serde` shim over the evidence object: duplicate keys are rejected (a JSON parser that
/// silently keeps the last one is a parser-differential seam across the supervisor/signer/broker
/// boundary), and only strings and bare integers are accepted as values.
struct StrictEvidenceMap(BTreeMap<String, EvidenceValue>);

impl<'de> Deserialize<'de> for StrictEvidenceMap {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = BTreeMap<String, EvidenceValue>;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("a flat JSON object of string and integer values")
            }
            fn visit_map<A>(self, mut access: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut out: BTreeMap<String, EvidenceValue> = BTreeMap::new();
                while let Some(key) = access.next_key::<String>()? {
                    let raw = access.next_value::<Value>()?;
                    let value = match raw {
                        Value::String(s) => EvidenceValue::Str(s),
                        // `as_i64` is `None` for a float, for a `u64` above `i64::MAX`, and for any
                        // non-number — so floats and oversize integers are refused here, not coerced.
                        Value::Number(n) => match n.as_i64() {
                            Some(i) => EvidenceValue::Int(i),
                            None => return Err(de::Error::custom("evidence: non-i64 number")),
                        },
                        _ => return Err(de::Error::custom("evidence: value is not a string or integer")),
                    };
                    if out.insert(key, value).is_some() {
                        return Err(de::Error::custom("evidence: duplicate key"));
                    }
                }
                Ok(out)
            }
        }
        deserializer.deserialize_map(V).map(StrictEvidenceMap)
    }
}

/// The parsed §4.6 attested evidence — proven to carry EXACTLY the 29 frozen keys with the right
/// value kinds. Construction is the only way to get one, so a caller cannot hold a half-checked
/// record. Every accessor is infallible because the key set was proven at parse time.
#[derive(Debug, Clone)]
pub struct AttestedEvidence {
    fields: BTreeMap<String, EvidenceValue>,
}

impl AttestedEvidence {
    fn s(&self, key: &str) -> &str {
        match self.fields.get(key) {
            Some(EvidenceValue::Str(v)) => v.as_str(),
            // Unreachable: `parse` proved every key in EVIDENCE_STRING_KEYS is present and a string.
            _ => unreachable!("evidence string key {key} was proven present at parse time"),
        }
    }
    fn i(&self, key: &str) -> i64 {
        match self.fields.get(key) {
            Some(EvidenceValue::Int(v)) => *v,
            _ => unreachable!("evidence integer key {key} was proven present at parse time"),
        }
    }

    /// Strict-parse the exact bytes the supervisor signed. Size-capped, duplicate keys rejected,
    /// every value a string or a bare integer, and EXACTLY the frozen 29-key set — no unknown key,
    /// none missing, none of the wrong kind. Any failure ⇒ Block (an evidence record the broker
    /// cannot read is one it cannot check, and accepting it restores the digest-only step).
    pub fn parse(evidence_jcs: &[u8]) -> Result<Self, TurnReason> {
        if evidence_jcs.len() > MAX_ATTESTATION_EVIDENCE_BYTES {
            return Err(TurnReason::UpstreamBlocked);
        }
        let fields = serde_json::from_slice::<StrictEvidenceMap>(evidence_jcs)
            .map_err(|_| TurnReason::UpstreamBlocked)?
            .0;

        // Exact key set. Unknown keys first: an evidence object carrying an extra field is a
        // different shape than the one both supervisors build, and the broker must not guess.
        if fields.len() != EVIDENCE_STRING_KEYS.len() + EVIDENCE_INTEGER_KEYS.len() {
            return Err(TurnReason::UpstreamBlocked);
        }
        for key in EVIDENCE_STRING_KEYS {
            match fields.get(key) {
                Some(EvidenceValue::Str(v)) if !v.is_empty() => {}
                _ => return Err(TurnReason::UpstreamBlocked),
            }
        }
        for key in EVIDENCE_INTEGER_KEYS {
            match fields.get(key) {
                Some(EvidenceValue::Int(_)) => {}
                _ => return Err(TurnReason::UpstreamBlocked),
            }
        }
        Ok(AttestedEvidence { fields })
    }
}

/// Require the parsed attestation to be an account of **this** turn (audit round 3).
///
/// Three groups, and it is worth being precise about what each one is worth:
///
///  * **Grant** — `decision` must be `completed`. A `denied`/`uncontained` attestation is not a
///    grant however validly it is signed.
///  * **Agreement with the isolated signer** — every field the evidence and the envelope BOTH carry
///    must be equal. The envelope is signed by the signer, the evidence by the supervisor; the two
///    are separate key holders, so this is a genuine second opinion. `output_handle` is compared to
///    `output_sha256` because both platforms' signers derive the latter from the content-addressed
///    bytes named by the former, so they are the same digest by construction.
///  * **Agreement with the broker's own resolution** — the run/task/attempt identity the broker
///    authorized, and the workspace/install/nonce/request-component digests it resolved itself.
///    Against a compromised broker this half is self-comparison; against a stale, foreign or
///    replayed SUPERVISOR attestation it is exactly the check that was missing.
///
/// A supervisor attestation for a different turn now fails here even when its signature is perfect
/// and the signer committed to its digest.
pub fn bind_attested_evidence(
    evidence: &AttestedEvidence,
    envelope: &ReceiptEnvelope,
    expected: &IssuedRequest,
    ctx: &BrokerContext,
) -> Result<(), TurnReason> {
    // (a) The decision must be a grant.
    if evidence.s("decision") != EVIDENCE_DECISION_COMPLETED {
        return Err(TurnReason::UpstreamBlocked);
    }

    // (b) Every string field the supervisor's account and the signer's account both carry.
    let string_pairs: [(&str, &str); 11] = [
        (evidence.s("run_id"), envelope.run_id),
        (evidence.s("execution_attempt_id"), envelope.execution_attempt_id),
        (evidence.s("task_id"), envelope.task_id),
        (evidence.s("workspace_id"), envelope.workspace_id),
        (evidence.s("install_id"), envelope.install_id),
        (evidence.s("request_nonce"), envelope.request_nonce),
        (evidence.s("receipt_id"), envelope.receipt_id),
        (evidence.s("record_handle"), envelope.record_handle),
        (evidence.s("lease_handle"), envelope.lease_handle),
        (evidence.s("execution_receipt_handle"), envelope.execution_receipt_handle),
        (evidence.s("evidence_final_event_hash"), envelope.evidence_final_event_hash),
    ];
    for (attested, signed) in string_pairs {
        if attested != signed {
            return Err(TurnReason::UpstreamBlocked);
        }
    }
    // The reply bytes: the store handle the supervisor attested IS the digest the signer signed.
    if evidence.s("output_handle") != envelope.output_sha256 {
        return Err(TurnReason::UpstreamBlocked);
    }

    // (c) The integer fields both accounts carry.
    let int_pairs: [(i64, i64); 4] = [
        (evidence.i("challenge_accepted_at_ms"), envelope.challenge_accepted_at_ms),
        (evidence.i("completed_at"), envelope.completed_at_ms),
        (evidence.i("evidence_event_count"), envelope.evidence_event_count),
        (evidence.i("evidence_last_sequence"), envelope.evidence_last_sequence),
    ];
    for (attested, signed) in int_pairs {
        if attested != signed {
            return Err(TurnReason::UpstreamBlocked);
        }
    }
    if evidence.i("evidence_head_sequence") != envelope.evidence_head_sequence {
        return Err(TurnReason::UpstreamBlocked);
    }

    // (d) The run identity the BROKER authorized (its own resolution + the attempt id from the lease
    //     the supervisor granted it) — the same three fields step 4b binds on the envelope, now also
    //     required of the supervisor's independently-signed account.
    if evidence.s("run_id") != ctx.expected_run_id || evidence.s("task_id") != ctx.expected_task_id {
        return Err(TurnReason::UpstreamBlocked);
    }
    // The attempt id is compared only by a caller that INDEPENDENTLY holds one (see
    // [`BrokerContext::expected_execution_attempt_id`]); a ladder caller holds none and passes `None`
    // rather than feeding this comparison the value it is meant to check.
    if let Some(expected_attempt) = ctx.expected_execution_attempt_id {
        if evidence.s("execution_attempt_id") != expected_attempt {
            return Err(TurnReason::UpstreamBlocked);
        }
    }

    // (e) The request the broker itself issued. The three component handles are compared to the
    //     broker's own resolved digests: the store is content-addressed, so a handle IS the digest of
    //     the bytes it names, on both platforms' signers.
    if evidence.s("workspace_id") != expected.workspace_id
        || evidence.s("install_id") != expected.install_id
        || evidence.s("request_nonce") != expected.request_nonce
        || evidence.s("system_handle") != expected.system_sha256
        || evidence.s("history_handle") != expected.history_sha256
        || evidence.s("generation_config_handle") != expected.generation_config_sha256
    {
        return Err(TurnReason::UpstreamBlocked);
    }
    // `requested_at` is an integer in the evidence and the canonical decimal string in the §2.2
    // request envelope; compare in the request envelope's form.
    if evidence.i("requested_at").to_string() != expected.requested_at {
        return Err(TurnReason::UpstreamBlocked);
    }

    Ok(())
}

/// The two manifest keys the broker has **pinned** (§4.9 — the isolated-signer key the desktop pins, and
/// the `supervisor_attestation` key). Public keys are raw 32-byte Ed25519; the broker takes authority ONLY
/// from signatures under these.
#[derive(Debug, Clone, Copy)]
pub struct PinnedKeys<'a> {
    pub isolated_signer_key_id: &'a str,
    pub isolated_signer_public_key: &'a [u8],
    pub supervisor_attestation_key_id: &'a str,
    pub supervisor_attestation_public_key: &'a [u8],
}

/// The broker-owned message identity for the committed row (the renderer never supplies these — they come
/// from the broker's own turn state). `message_id`/`broker_turn_id`/`conversation_id`/`author` flow
/// straight into the [`AcceptedOutput`] this module returns.
#[derive(Debug, Clone, Copy)]
pub struct BrokerContext<'a> {
    pub broker_turn_id: &'a str,
    pub message_id: &'a str,
    pub conversation_id: &'a str,
    pub author: &'a str,
    // ---- the run identity the broker itself authorized (audit F-26) ----
    //
    // The envelope's `run_id` / `task_id` / `execution_attempt_id` are SIGNED but were compared to
    // nothing: the broker held both sides — its own resolution, and the attempt id from the lease it
    // obtained — and carried the signed values straight through. A receipt produced under a DIFFERENT
    // attempt could therefore be accepted for this turn as long as the nonce and output bytes lined
    // up. These three make the receipt's own account of which execution it describes load-bearing.
    pub expected_run_id: &'a str,
    pub expected_task_id: &'a str,
    /// The attempt id the broker itself authorized — `Some` ONLY for a principal that obtained the
    /// §5 lease and therefore holds an independent copy of this value.
    ///
    /// **`None` is not "skip a check", it is "this principal is not entitled to make one", and the
    /// difference is why this is an `Option` rather than an empty string.** On the rev-30 §4.10(g)
    /// sidecar ladder the broker does not open the turn: §2.6 gives `accept-open` to the SIDECAR
    /// principal, so `execution_attempt_id` is minted by the supervisor and reaches this side only
    /// as the §4.10(e) TRANSPORT echo and inside the signed envelope itself. Passing either of those
    /// here would be this process comparing a value against itself — the F-01 signing-oracle shape,
    /// which an audit has already found twice in this tree — so the ladder passes `None` and the
    /// type records the loss instead of hiding it.
    ///
    /// What still binds one challenge to one attempt when this is `None`: the supervisor's own
    /// acceptance ledger, whose `governed_turn_acceptance` table carries
    /// `UNIQUE (challenge_handle)`, `UNIQUE (install_id, request_nonce)` and
    /// `UNIQUE (execution_attempt_id)` (`core/schema/supervisor_ledger.sql`), plus `run_id`/`task_id`
    /// above, which the broker DOES mint and which stay mandatory. That is a durable constraint held
    /// by a different party, not a check this process performs.
    pub expected_execution_attempt_id: Option<&'a str>,
}

/// Why the acceptance ledger refused to claim a turn — or failed trying.
///
/// Every variant is a REFUSAL. There is deliberately no "unknown/degraded" value that a caller could
/// read as "probably fine": a replay defence that cannot answer must block, never accept.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LedgerRefusal {
    /// §7.1(c): this `receipt_id` has already been accepted — a receipt replay.
    ReceiptReplay,
    /// §7.1(d): this `request_nonce` has already been consumed — a nonce replay.
    NonceReplay,
    /// The ledger could not be read or written (I/O, lock timeout, corrupt/absent table, a caller that
    /// already held a transaction). NEVER reported as "fresh" — an unavailable replay defence refuses.
    Fault,
}

impl std::fmt::Display for LedgerRefusal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LedgerRefusal::ReceiptReplay => write!(f, "receipt_id already accepted (replay)"),
            LedgerRefusal::NonceReplay => write!(f, "request_nonce already consumed (replay)"),
            LedgerRefusal::Fault => write!(f, "acceptance ledger unavailable (fail-closed)"),
        }
    }
}

/// The injected acceptance-ledger port: §7.1(c) `receipt_id` global uniqueness AND §7.1(d) one-time
/// `request_nonce` consume, claimed together in ONE atomic step.
///
/// The two defences are a single trait method on purpose. Split into `is_seen` / `consume` / `record`
/// they were a read-then-write: two concurrent turns could both observe a fresh `receipt_id`, and a
/// failure to *record* had no way to be reported, so an accepted-but-unrecorded receipt stayed
/// replayable. [`claim`](AcceptanceLedger::claim) is all-or-nothing — on any refusal NOTHING is
/// recorded and NOTHING is consumed, so a blocked turn never burns state.
///
/// Kept as a trait so the pure verifier needs no DB. The production implementation is
/// [`crate::broker_turns::DurableAcceptanceLedger`] (a `BEGIN IMMEDIATE` transaction over the broker's
/// SQLite database, so both defences survive a restart). [`InMemoryLedger`] is for tests ONLY.
pub trait AcceptanceLedger {
    /// Atomically claim BOTH the `receipt_id` (globally once, ever) and the one-time `request_nonce`.
    ///
    /// `Ok(())` means both were fresh AND both are now recorded — the caller may accept. Every other
    /// outcome is a [`LedgerRefusal`] and the turn MUST be refused.
    fn claim(&mut self, receipt_id: &str, request_nonce: &str) -> Result<(), LedgerRefusal>;
}

/// A process-lifetime in-memory [`AcceptanceLedger`] (two sets).
///
/// **NOT FOR PRODUCTION — this is a test/dry-run double.** It holds the §7.1(c)(d) replay state in
/// process memory, so every entry is lost when the process exits: after a restart the exact same signed
/// `receipt_id` and the exact same one-time `request_nonce` are accepted again. It also shares nothing
/// between processes, so two brokers over one deployment do not see each other's accepted receipts.
/// Wiring this into a real governed turn silently removes the replay defence the chain claims to have.
///
/// Production callers MUST use [`crate::broker_turns::DurableAcceptanceLedger`].
#[derive(Debug, Default)]
pub struct InMemoryLedger {
    seen_receipts: HashSet<String>,
    consumed_nonces: HashSet<String>,
}

impl InMemoryLedger {
    pub fn new() -> Self {
        Self::default()
    }
    /// Pre-seed an already-accepted `receipt_id` (e.g. to model a replay in a test/dry-run).
    pub fn with_seen_receipt(mut self, receipt_id: &str) -> Self {
        self.seen_receipts.insert(receipt_id.to_string());
        self
    }
    /// Pre-seed an already-consumed `request_nonce`.
    pub fn with_consumed_nonce(mut self, request_nonce: &str) -> Self {
        self.consumed_nonces.insert(request_nonce.to_string());
        self
    }
}

impl AcceptanceLedger for InMemoryLedger {
    fn claim(&mut self, receipt_id: &str, request_nonce: &str) -> Result<(), LedgerRefusal> {
        // Mirrors the durable implementation's order and all-or-nothing semantics: check both, then
        // write both, so a refusal leaves the set exactly as it was.
        if self.seen_receipts.contains(receipt_id) {
            return Err(LedgerRefusal::ReceiptReplay);
        }
        if self.consumed_nonces.contains(request_nonce) {
            return Err(LedgerRefusal::NonceReplay);
        }
        self.seen_receipts.insert(receipt_id.to_string());
        self.consumed_nonces.insert(request_nonce.to_string());
        Ok(())
    }
}

/// Verify a detached Ed25519 signature (base64url) over `msg` under a raw 32-byte public key.
/// `verify_strict` rejects non-canonical `s` and small-order keys — the right default for a security
/// boundary (mirrors `receipt.rs`). Any failure maps to `UpstreamBlocked` (no verified signature ⇒ Block).
fn verify_ed25519(public_key: &[u8], msg: &[u8], signature_b64: &str) -> Result<(), TurnReason> {
    let key_bytes: [u8; 32] = public_key.try_into().map_err(|_| TurnReason::UpstreamBlocked)?;
    let verifying_key = VerifyingKey::from_bytes(&key_bytes).map_err(|_| TurnReason::UpstreamBlocked)?;
    if signature_b64.len() > MAX_SIG_B64_LEN {
        return Err(TurnReason::UpstreamBlocked);
    }
    let sig_bytes = URL_SAFE_NO_PAD
        .decode(signature_b64.as_bytes())
        .map_err(|_| TurnReason::UpstreamBlocked)?;
    let sig_arr: [u8; 64] = sig_bytes.as_slice().try_into().map_err(|_| TurnReason::UpstreamBlocked)?;
    let signature = Signature::from_bytes(&sig_arr);
    verifying_key
        .verify_strict(msg, &signature)
        .map_err(|_| TurnReason::UpstreamBlocked)
}

// =================================================================================================
// §7.1 FRESHNESS — the bound on how OLD an accepted receipt may be
// =================================================================================================
//
// The chain had replay protection (the acceptance ledger) and no freshness bound, which are not the
// same property: the ledger stops the same receipt being accepted TWICE, and stops nothing about a
// receipt that has never been accepted at all and was signed a year ago. Every other check in this
// module is time-free — a signature that verified when it was minted verifies forever — so before
// this, "validly signed at some point in the past" was sufficient to commit a governed reply today.

/// The §7.1 / §1-LOCKED freshness policy: `future_skew_ms = 60000`, `max_age_ms = 300000`. These are
/// the exact `receipt_store::FreshnessWindow::DEFAULT` values §7.1 names ("the real `receipt_store.rs`
/// values"), reused rather than re-declared so the governed path can never drift from the v1 path.
///
/// It is a **maximum**, not a suggestion: [`check_receipt_freshness`] refuses any window WIDER than
/// this, so no caller — present or future — can widen the bound the design locked.
pub const GOVERNED_TURN_FRESHNESS: FreshnessWindow = FreshnessWindow::DEFAULT;

/// §1: every governed-turn `_ms` value is a JSON integer with `1 ≤ v ≤ 2^53-1` ("overflow/negative
/// rejected"). Applied here to the envelope's signed `_ms` fields AND to the injected clock.
const MIN_GOVERNED_MS: i64 = 1;
const MAX_GOVERNED_MS: i64 = (1i64 << 53) - 1;

/// The broker's clock reading for one acceptance, plus the window it is judged against.
///
/// The window is **not** a caller-supplied knob: [`Freshness::at`] is the only constructor outside
/// this module's tests and it always installs [`GOVERNED_TURN_FRESHNESS`]. There is deliberately no
/// way to express "no window" — the type has no `None` and no `Default`, so a caller cannot reach
/// `verify_and_accept` without a bound, and cannot silently fall back to an unbounded one.
#[derive(Debug, Clone, Copy)]
pub struct Freshness {
    now_ms: i64,
    window: FreshnessWindow,
}

impl Freshness {
    /// One acceptance at `now_ms` (the broker's wall clock, epoch ms) under the LOCKED §1 window.
    ///
    /// `now_ms` is NOT trusted blindly: a clock that reads 0 — which is exactly what a
    /// `SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or(0)` returns on a machine whose clock
    /// is set before 1970 — is outside the §1 `_ms` range and refuses at
    /// [`check_receipt_freshness`], instead of collapsing the window to `[0, 60000]` where every
    /// 1970-stamped receipt is "fresh".
    pub fn at(now_ms: i64) -> Self {
        Freshness { now_ms, window: GOVERNED_TURN_FRESHNESS }
    }

    /// Tests ONLY: a hand-built window, so the "window wider than the locked policy refuses" and
    /// "window that bounds nothing refuses" rules are reachable from a test rather than only from a
    /// future editing mistake.
    #[cfg(test)]
    fn with_window(now_ms: i64, window: FreshnessWindow) -> Self {
        Freshness { now_ms, window }
    }
}

/// §7.1 "Freshness" — bound the envelope's own signed `_ms` fields against the broker's clock.
///
/// Which timestamps, and why these: the envelope (§4.9) carries exactly two `_ms` values, and §7.1
/// requires that "every governed-turn `_ms` field nests inside" the window.
///
///  * `challenge_accepted_at_ms` — the supervisor's ONE clock read (§1), the origin of the whole
///    lease/execution time-chain and the oldest fact in the envelope. Bounding it is what puts a
///    ceiling on the age of the turn as a whole.
///  * `completed_at_ms` — the end of that chain. Bounded separately because an envelope could carry
///    a fresh acceptance and an ancient completion or vice versa; neither is a turn that happened.
///
/// The acceptance-row timestamp is NOT a third clock here. `challenge_accepted_at_ms` IS the
/// acceptance-row value — §6.1 step 3 stamps it into the ledger row and §4.3 pins
/// `lease_issued_at_ms == challenge_accepted_at_ms` — and step 4c has already required the
/// supervisor's independently-signed evidence to carry the same integer. So one bound over the
/// envelope's field covers both accounts; adding a separate "acceptance row" comparison would only
/// compare the broker's copy to the broker's copy.
///
/// Fail-closed in every direction: a value outside the §1 integer range, a reversed pair, a clock the
/// caller could not read, or a window wider than the locked policy all Block.
fn check_receipt_freshness(envelope: &ReceiptEnvelope, freshness: &Freshness) -> Result<(), TurnReason> {
    let Freshness { now_ms, window } = *freshness;

    // (a) The window must actually bound something, and may never be wider than §1's locked policy.
    //     `max_age_ms == 0` is the degenerate "nothing is ever fresh" configuration; anything above
    //     the locked values is the far more dangerous direction — an unbounded window dressed as one.
    if window.max_age_ms == 0
        || window.max_age_ms > GOVERNED_TURN_FRESHNESS.max_age_ms
        || window.future_skew_ms > GOVERNED_TURN_FRESHNESS.future_skew_ms
    {
        return Err(TurnReason::UpstreamBlocked);
    }

    // (b) The clock itself must be a legal §1 `_ms` value. A verifier that cannot read a usable clock
    //     has no freshness opinion, and "no opinion" must not read as "fresh".
    if !(MIN_GOVERNED_MS..=MAX_GOVERNED_MS).contains(&now_ms) {
        return Err(TurnReason::UpstreamBlocked);
    }

    // (c) Both signed `_ms` fields must be legal §1 values (`1 ≤ v ≤ 2^53-1`), checked before any
    //     arithmetic so a hostile ±i64 extreme cannot be reasoned about at all.
    let accepted = envelope.challenge_accepted_at_ms;
    let completed = envelope.completed_at_ms;
    for t in [accepted, completed] {
        if !(MIN_GOVERNED_MS..=MAX_GOVERNED_MS).contains(&t) {
            return Err(TurnReason::UpstreamBlocked);
        }
    }

    // (d) §7 execution time-chain ordering: `lease_issued_at_ms (== challenge_accepted_at_ms) ≤
    //     started ≤ finished ≤ completed_at_ms`. The broker sees only the two ends, so it enforces
    //     the two ends. (The v1 path refuses the same shape: "requested_at is after completed_at".)
    if accepted > completed {
        return Err(TurnReason::UpstreamBlocked);
    }

    // (e) The window, INCLUSIVE on both ends (§1: "a time `t` is in a window iff `lo_ms ≤ t ≤ hi_ms`").
    //     i128 so neither limit can overflow for any input that passed (b)/(c).
    let future_limit = now_ms as i128 + window.future_skew_ms as i128;
    let stale_limit = now_ms as i128 - window.max_age_ms as i128;
    for t in [accepted, completed] {
        let t = t as i128;
        if t > future_limit || t < stale_limit {
            return Err(TurnReason::UpstreamBlocked);
        }
    }

    Ok(())
}

/// The broker's FINAL ACCEPTANCE predicate (§6.1 step 14, §7.1). Pure over the injected inputs — no
/// socket, store, or clock. On success returns the [`AcceptedOutput`] to hand to
/// `governed_message_store::persist_committed`; on any failure returns a [`TurnReason`] and **consumes
/// nothing** except where noted (the nonce/receipt-id ledger is touched only once every cryptographic and
/// binding check has passed).
///
/// `expected` is the broker's OWN trusted resolution (system/history/generation_config/context hashes it
/// computed itself, §4.10(g)); `envelope`+`envelope_signature_b64` is the isolated-signer receipt envelope
/// (§4.9); `attestation` is the supervisor attestation (§4.6); `keys` are the pinned manifest keys;
/// `output` is the exact reassembled reply bytes (§4.10(f) pull); `ctx` is the broker-owned message
/// identity; `ledger` is the one-time nonce + receipt-id replay store; `freshness` carries the broker's
/// wall-clock reading for THIS acceptance (§7.1 — the module is still clock-free, the clock is injected).
#[allow(clippy::too_many_arguments)]
pub fn verify_and_accept(
    expected: &IssuedRequest,
    envelope: &ReceiptEnvelope,
    envelope_signature_b64: &str,
    attestation: &SupervisorAttestation,
    keys: &PinnedKeys,
    output: &[u8],
    ctx: &BrokerContext,
    ledger: &mut dyn AcceptanceLedger,
    freshness: &Freshness,
) -> Result<AcceptedOutput, TurnReason> {
    // 1. Envelope identity: frozen artifact type + pinned key ids. Refused before any signature check.
    if envelope.artifact_type != RECEIPT_ENVELOPE_ARTIFACT_TYPE {
        return Err(TurnReason::UpstreamBlocked);
    }
    if envelope.key_id != keys.isolated_signer_key_id {
        return Err(TurnReason::UpstreamBlocked);
    }
    if envelope.supervisor_attestation_key_id != keys.supervisor_attestation_key_id {
        return Err(TurnReason::UpstreamBlocked);
    }

    // 2. Isolated-signer signature over the reconstructed JCS(payload) under the pinned signer key.
    let payload_jcs = envelope.payload_jcs()?;
    verify_ed25519(keys.isolated_signer_public_key, &payload_jcs, envelope_signature_b64)?;

    // 3. Supervisor attestation signature over the attested evidence, + the envelope's binding to the
    //    exact evidence bytes (attestation_evidence_sha256).
    verify_ed25519(
        keys.supervisor_attestation_public_key,
        attestation.evidence_jcs,
        attestation.signature_b64,
    )?;
    if sha256_hex(attestation.evidence_jcs) != envelope.attestation_evidence_sha256 {
        return Err(TurnReason::UpstreamBlocked);
    }
    //    The attestation is not yet an account of THIS turn — that is step 4c, once the broker's own
    //    Expected/ctx bindings below have been established to compare it against.

    // 4. Request binding: recompute request_sha256 from the broker's OWN trusted Expected and require the
    //    envelope to match it (+ the request-context ids). A forged/mismatched request hash Blocks.
    if envelope.workspace_id != expected.workspace_id
        || envelope.install_id != expected.install_id
        || envelope.request_nonce != expected.request_nonce
    {
        return Err(TurnReason::UpstreamBlocked);
    }
    if envelope.request_sha256 != expected.request_sha256() {
        return Err(TurnReason::UpstreamBlocked);
    }

    // 4b. Run-identity binding (audit F-26). The signed envelope names the run, task and execution
    //     attempt it describes; the broker knows all three — `run_id`/`task_id` from its own trusted
    //     resolution, and `execution_attempt_id` from the lease the supervisor granted IT. Comparing
    //     them is what stops a genuinely-signed receipt for a different attempt from being committed
    //     as this turn's. Before this, the three were carried through the signature check and never
    //     looked at again.
    if envelope.run_id != ctx.expected_run_id || envelope.task_id != ctx.expected_task_id {
        return Err(TurnReason::UpstreamBlocked);
    }
    if let Some(expected_attempt) = ctx.expected_execution_attempt_id {
        if envelope.execution_attempt_id != expected_attempt {
            return Err(TurnReason::UpstreamBlocked);
        }
    }

    // 4c. ATTESTATION TURN BINDING (audit round 3). Step 3 proved the supervisor signed these exact
    //     bytes and that the signer committed to their digest — both of which are equally true of an
    //     attestation about a completely different turn. The bytes are now PARSED and required to be
    //     an account of THIS turn: a grant decision, agreement with the isolated signer's separately
    //     signed envelope field by field, and agreement with the broker's own resolution. Nothing is
    //     parsed until the supervisor's signature over these exact bytes verified at step 3, so the
    //     parser only ever runs on supervisor-authenticated input.
    let attested = AttestedEvidence::parse(attestation.evidence_jcs)?;
    bind_attested_evidence(&attested, envelope, expected, ctx)?;

    // 4d. FRESHNESS (§7.1). Every check above is time-free: a signature that verified when it was
    //     minted verifies forever, and the identity/binding equalities hold forever too. So until
    //     here, a receipt validly produced at ANY point in the past was acceptable today. The
    //     envelope's own signed `_ms` fields are now required to sit inside the §1-LOCKED window
    //     around the broker's clock. Placed before the output digest work and before the ledger
    //     claim, so a stale receipt costs neither a hash of ≤8 MiB nor the one-time nonce.
    check_receipt_freshness(envelope, freshness)?;

    // 5. Output binding: length gate + digest gate over the RAW bytes (no normalization). A disagreement
    //    is a commit-readback-class failure — the accepted body would not match the envelope's digest.
    if output.len() as u64 != envelope.output_bytes {
        return Err(TurnReason::CommitReadbackMismatch);
    }
    if sha256_hex(output) != envelope.output_sha256 {
        return Err(TurnReason::CommitReadbackMismatch);
    }
    // Only after the digest gate: strict-UTF8 decode for the committed body (invalid UTF-8 ⇒ Block).
    let accepted_body = match std::str::from_utf8(output) {
        Ok(s) => s.to_string(),
        Err(_) => return Err(TurnReason::UpstreamBlocked),
    };

    // 6+7. §7.1(c)(d) replay defence, claimed as ONE atomic step: `receipt_id` global uniqueness AND the
    //      one-time `request_nonce` consume. A receipt replay, a nonce replay, or a ledger that cannot
    //      answer (I/O, lock, missing table) all Block — there is no branch here that accepts on a
    //      ledger it could not consult. On refusal the ledger records nothing, so a blocked turn does
    //      not burn the nonce or the receipt id.
    ledger
        .claim(envelope.receipt_id, envelope.request_nonce)
        .map_err(|_| TurnReason::UpstreamBlocked)?;

    Ok(AcceptedOutput {
        broker_turn_id: ctx.broker_turn_id.to_string(),
        message_id: ctx.message_id.to_string(),
        conversation_id: ctx.conversation_id.to_string(),
        author: ctx.author.to_string(),
        accepted_body,
        envelope_body_sha256: envelope.output_sha256.to_string(),
        created_at_ms: envelope.completed_at_ms,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer as _, SigningKey};

    // ---- test-only signer (verify-only in production; sign lives under cfg(test)) ----
    fn signing_key(seed: u8) -> SigningKey {
        SigningKey::from_bytes(&[seed; 32])
    }
    fn sign_b64(key: &SigningKey, msg: &[u8]) -> String {
        URL_SAFE_NO_PAD.encode(key.sign(msg).to_bytes())
    }
    fn hx(n: u8) -> String {
        let mut s = String::new();
        for _ in 0..32 {
            s.push_str(&format!("{n:02x}"));
        }
        s
    }

    const OUTPUT: &[u8] = b"the exact governed reply bytes";

    // ---- the fixture's time-chain (§1). REAL epoch-ms values, not 1000/2000: with a toy `now_ms`
    // the stale limit `now - 300000` goes negative and the stale branch can never be exercised, so a
    // freshness test over toy timestamps would pass while proving nothing about the shipped path.
    const T_REQUESTED_MS: i64 = 1_754_000_000_000; // 2025-08-01T00:53:20Z
    const T_ACCEPTED_MS: i64 = T_REQUESTED_MS; // §1 allows `requested_at_ms == challenge_accepted_at_ms`
    const T_COMPLETED_MS: i64 = T_ACCEPTED_MS + 2_000;
    /// The broker's clock at acceptance: 1 s after the turn completed — an ordinary live turn.
    const T_NOW_MS: i64 = T_COMPLETED_MS + 1_000;
    /// `requested_at` in the §2.2 request envelope's canonical decimal-string form.
    const REQUESTED_AT_STR: &str = "1754000000000";

    fn fresh() -> Freshness {
        Freshness::at(T_NOW_MS)
    }

    // 64-hex handle/head literals (owned 'static so borrowing them in the fixture is sound).
    const H_RECORD: &str = "1111111111111111111111111111111111111111111111111111111111111111";
    const H_LEASE: &str = "2222222222222222222222222222222222222222222222222222222222222222";
    const H_RECEIPT: &str = "3333333333333333333333333333333333333333333333333333333333333333";
    const H_EVIDENCE: &str = "7777777777777777777777777777777777777777777777777777777777777777";
    const H_POLICY: &str = "8888888888888888888888888888888888888888888888888888888888888888";
    const H_CONTAIN: &str = "9999999999999999999999999999999999999999999999999999999999999999";

    /// One §4.6 attested-evidence field, as the supervisor writes it.
    struct Ev(&'static str, Value);

    /// Build the canonical JCS of a full 29-key §4.6 evidence record. `overrides` replaces named
    /// fields, so a test can produce a well-formed attestation for a DIFFERENT turn (or one that
    /// disagrees with the envelope about exactly one fact) without hand-rolling 29 keys.
    ///
    /// `serde_json::to_vec` of a `Map` is sorted + compact, byte-identical to what both supervisors
    /// sign (`json.dumps(sort_keys=True, separators=(",",":"))` / `crypto::jcs`).
    fn evidence_jcs_with(system: &str, history: &str, generation: &str, output_sha256: &str, overrides: &[Ev]) -> Vec<u8> {
        let mut m: Map<String, Value> = Map::new();
        let base: [(&str, Value); 29] = [
            ("run_id", "run-1".into()),
            ("execution_attempt_id", "att-1".into()),
            ("task_id", "task-1".into()),
            ("request_nonce", "nonce-xyz".into()),
            ("receipt_id", "receipt-abc".into()),
            ("workspace_id", "ws-1".into()),
            ("install_id", "install-1".into()),
            ("supervisor_id", "sup-1".into()),
            ("executor_id", "exec-1".into()),
            ("builder_id", "build-1".into()),
            ("policy_id", "pol-1".into()),
            ("policy_version", "1".into()),
            ("policy_bundle_handle", H_POLICY.into()),
            ("system_handle", system.into()),
            ("history_handle", history.into()),
            ("generation_config_handle", generation.into()),
            ("output_handle", output_sha256.into()),
            ("containment_evidence_handle", H_CONTAIN.into()),
            ("record_handle", H_RECORD.into()),
            ("lease_handle", H_LEASE.into()),
            ("execution_receipt_handle", H_RECEIPT.into()),
            ("evidence_final_event_hash", H_EVIDENCE.into()),
            ("decision", "completed".into()),
            ("requested_at", Value::Number(Number::from(T_REQUESTED_MS))),
            ("challenge_accepted_at_ms", Value::Number(Number::from(T_ACCEPTED_MS))),
            ("completed_at", Value::Number(Number::from(T_COMPLETED_MS))),
            ("evidence_event_count", Value::Number(Number::from(3))),
            ("evidence_last_sequence", Value::Number(Number::from(12))),
            ("evidence_head_sequence", Value::Number(Number::from(12))),
        ];
        for (k, v) in base {
            m.insert(k.to_string(), v);
        }
        for Ev(k, v) in overrides {
            assert!(m.contains_key(*k), "override names a field the evidence does not carry: {k}");
            m.insert((*k).to_string(), v.clone());
        }
        serde_json::to_vec(&Value::Object(m)).unwrap()
    }

    // Stable owned strings the borrowed structs point at.
    struct Fx {
        /// The envelope's two signed `_ms` fields. Held on the fixture (not as file constants) so a
        /// freshness test can move the turn in time and still get a genuinely signed envelope +
        /// attestation: step 4c requires the supervisor's evidence to carry the SAME integers, so a
        /// test that edited only one of the two would be refused for the wrong reason.
        accepted_ms: i64,
        completed_ms: i64,
        system: String,
        history: String,
        generation: String,
        request_sha256: String,
        output_sha256: String,
        output_bytes: u64,
        attest_evidence: Vec<u8>,
        attest_sha256: String,
        iso_pub: [u8; 32],
        sup_pub: [u8; 32],
        env_sig: String,
        attest_sig: String,
    }

    fn fx() -> Fx {
        fx_over(OUTPUT, &[])
    }

    /// The genuine fixture with its time-chain moved to `accepted_ms`/`completed_ms`. BOTH the
    /// envelope and the attested evidence carry the new values and everything is re-signed.
    fn fx_at(accepted_ms: i64, completed_ms: i64) -> Fx {
        fx_full(
            OUTPUT,
            &[
                Ev("challenge_accepted_at_ms", Value::Number(Number::from(accepted_ms))),
                Ev("completed_at", Value::Number(Number::from(completed_ms))),
            ],
            accepted_ms,
            completed_ms,
        )
    }

    /// The fixture for a genuine turn over `output`, with `overrides` applied to the attested
    /// evidence. Every signature is recomputed, so the ONLY thing a test varies is the fact it is
    /// testing — an override never leaves a broken signature behind to pass the test for it.
    fn fx_over(output: &[u8], overrides: &[Ev]) -> Fx {
        fx_full(output, overrides, T_ACCEPTED_MS, T_COMPLETED_MS)
    }

    fn fx_full(output: &[u8], overrides: &[Ev], accepted_ms: i64, completed_ms: i64) -> Fx {
        let system = hx(0x55);
        let history = hx(0x66);
        let generation = hx(0x44);
        let request_sha256 = crate::receipt::request_envelope_sha256(
            "ws-1", "install-1", "nonce-xyz", &system, &history, &generation, REQUESTED_AT_STR,
        );
        let output_sha256 = sha256_hex(output);
        let attest_evidence =
            evidence_jcs_with(&system, &history, &generation, &output_sha256, overrides);
        let attest_sha256 = sha256_hex(&attest_evidence);
        let iso = signing_key(7);
        let sup = signing_key(9);
        let mut f = Fx {
            accepted_ms,
            completed_ms,
            system,
            history,
            generation,
            request_sha256,
            output_sha256,
            output_bytes: output.len() as u64,
            attest_evidence,
            attest_sha256,
            iso_pub: iso.verifying_key().to_bytes(),
            sup_pub: sup.verifying_key().to_bytes(),
            env_sig: String::new(),
            attest_sig: String::new(),
        };
        // Sign the reconstructed payload JCS + the attestation evidence.
        f.env_sig = {
            let env = envelope(&f);
            sign_b64(&iso, &env.payload_jcs().unwrap())
        };
        f.attest_sig = sign_b64(&sup, &f.attest_evidence);
        f
    }

    fn expected(f: &Fx) -> IssuedRequest<'_> {
        IssuedRequest {
            workspace_id: "ws-1",
            install_id: "install-1",
            request_nonce: "nonce-xyz",
            system_sha256: &f.system,
            history_sha256: &f.history,
            generation_config_sha256: &f.generation,
            requested_at: REQUESTED_AT_STR,
        }
    }

    fn envelope(f: &Fx) -> ReceiptEnvelope<'_> {
        ReceiptEnvelope {
            artifact_type: RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            key_id: "iso-signer-1",
            receipt_id: "receipt-abc",
            run_id: "run-1",
            execution_attempt_id: "att-1",
            task_id: "task-1",
            workspace_id: "ws-1",
            install_id: "install-1",
            request_nonce: "nonce-xyz",
            request_sha256: &f.request_sha256,
            record_handle: H_RECORD,
            lease_handle: H_LEASE,
            execution_receipt_handle: H_RECEIPT,
            output_sha256: &f.output_sha256,
            output_bytes: f.output_bytes,
            challenge_accepted_at_ms: f.accepted_ms,
            completed_at_ms: f.completed_ms,
            evidence_final_event_hash: H_EVIDENCE,
            evidence_event_count: 3,
            evidence_last_sequence: 12,
            evidence_head_sequence: 12,
            supervisor_attestation_key_id: "sup-att-1",
            attestation_evidence_sha256: &f.attest_sha256,
        }
    }

    fn keys(f: &Fx) -> PinnedKeys<'_> {
        PinnedKeys {
            isolated_signer_key_id: "iso-signer-1",
            isolated_signer_public_key: &f.iso_pub,
            supervisor_attestation_key_id: "sup-att-1",
            supervisor_attestation_public_key: &f.sup_pub,
        }
    }

    fn attest(f: &Fx) -> SupervisorAttestation<'_> {
        SupervisorAttestation { evidence_jcs: &f.attest_evidence, signature_b64: &f.attest_sig }
    }

    const CTX: BrokerContext<'static> = BrokerContext {
        broker_turn_id: "bt-1",
        message_id: "m-1",
        conversation_id: "conv-1",
        author: "Bro",
        expected_run_id: "run-1",
        expected_task_id: "task-1",
        expected_execution_attempt_id: Some("att-1"),
    };

    // ---- F-26: the signed run identity must match the run the broker authorized ----
    //
    // These three fields were signed and then compared to nothing, so a genuinely-signed receipt for
    // a DIFFERENT execution attempt was acceptable for this turn as long as the nonce and output
    // matched. Each case below is a real receipt whose only defect is naming another run.
    #[test]
    fn a_receipt_naming_another_run_is_refused() {
        for (field, ctx) in [
            (
                "run_id",
                BrokerContext { expected_run_id: "run-OTHER", ..CTX },
            ),
            (
                "task_id",
                BrokerContext { expected_task_id: "task-OTHER", ..CTX },
            ),
            (
                "execution_attempt_id",
                BrokerContext { expected_execution_attempt_id: Some("att-OTHER"), ..CTX },
            ),
        ] {
            let f = fx();
            let env = envelope(&f);
            let k = keys(&f);
            let a = attest(&f);
            let mut ledger = InMemoryLedger::new();
            // The envelope + signature are untouched and valid — only the broker's own expectation
            // differs, which is exactly the "receipt from another attempt" shape.
            let r = verify_and_accept(
                &expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &ctx, &mut ledger, &fresh(),
            );
            match r {
                Err(TurnReason::UpstreamBlocked) => {}
                Err(other) => panic!("{field}: expected UpstreamBlocked, got {other:?}"),
                Ok(_) => panic!(
                    "a receipt whose {field} is not the one the broker authorized must Block"
                ),
            }
        }
    }

    /// The §4.10(g) LADDER caller passes `expected_execution_attempt_id: None`, and this pins
    /// exactly what that costs and exactly what it does not.
    ///
    /// It costs the attempt-id comparison: a receipt naming ANY attempt is accepted, which is why
    /// the field is an `Option` a reader has to think about rather than an empty string that reads
    /// like a value. It does NOT cost `run_id`/`task_id` — those are minted by the broker on the
    /// ladder too and stay mandatory, so a receipt from another RUN still Blocks with `None` in
    /// place. A change that made `None` skip all three would pass the first assertion here and fail
    /// the second two.
    #[test]
    fn a_ladder_caller_that_authorized_no_attempt_still_binds_run_and_task() {
        let ladder = BrokerContext { expected_execution_attempt_id: None, ..CTX };
        // (1) The attempt id is no longer compared — stated as a test, not as a comment.
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        assert!(
            verify_and_accept(
                &expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &ladder, &mut ledger, &fresh(),
            )
            .is_ok(),
            "with None the attempt id binds nothing, and this turn is otherwise valid"
        );
        // (2)+(3) run_id and task_id are still load-bearing under the SAME None.
        for (field, ctx) in [
            ("run_id", BrokerContext { expected_run_id: "run-OTHER", ..ladder }),
            ("task_id", BrokerContext { expected_task_id: "task-OTHER", ..ladder }),
        ] {
            let f = fx();
            let env = envelope(&f);
            let k = keys(&f);
            let a = attest(&f);
            let mut ledger = InMemoryLedger::new();
            assert!(
                matches!(
                    verify_and_accept(
                        &expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &ctx, &mut ledger, &fresh(),
                    ),
                    Err(TurnReason::UpstreamBlocked)
                ),
                "a None attempt id must not switch off the {field} binding"
            );
        }
    }

    // ---- REQUIRED: matching bindings => Ok(AcceptedOutput with exact body) ----
    #[test]
    fn matching_bindings_accept_the_exact_output() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        let accepted =
            verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()).unwrap();
        assert_eq!(accepted.accepted_body.as_bytes(), OUTPUT);
        assert_eq!(accepted.envelope_body_sha256, sha256_hex(OUTPUT));
        assert_eq!(accepted.message_id, "m-1");
        assert_eq!(accepted.broker_turn_id, "bt-1");
        assert_eq!(accepted.conversation_id, "conv-1");
        assert_eq!(accepted.author, "Bro");
        assert_eq!(accepted.created_at_ms, T_COMPLETED_MS);
        // The receipt_id is now recorded (§7.1(c)) and the nonce spent (§7.1(d)).
        assert_eq!(
            ledger.claim("receipt-abc", "nonce-fresh"),
            Err(LedgerRefusal::ReceiptReplay),
            "the accepted receipt_id must never be claimable again"
        );
        assert_eq!(
            ledger.claim("receipt-fresh", "nonce-xyz"),
            Err(LedgerRefusal::NonceReplay),
            "the spent nonce must be one-time"
        );
    }

    // ---- REQUIRED: request_sha256 mismatch => Err(UpstreamBlocked) ----
    #[test]
    fn request_sha256_mismatch_blocks() {
        let f = fx();
        let env = envelope(&f); // envelope carries the REAL request_sha256, validly signed
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        // Feed a DIFFERENT trusted Expected (wrong system hash) so the recompute diverges from the
        // envelope's signed request_sha256. Signature is still valid over the envelope bytes.
        let wrong = hx(0x00);
        let mut exp = expected(&f);
        exp.system_sha256 = &wrong;
        assert!(matches!(verify_and_accept(&exp, &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
        // A blocked turn consumes nothing — both ids are still claimable.
        assert_eq!(ledger.claim("receipt-abc", "nonce-xyz"), Ok(()));
    }

    // ---- REQUIRED: output-hash mismatch => Err(CommitReadbackMismatch) ----
    #[test]
    fn output_hash_mismatch_is_commit_readback_mismatch() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        // Same length, one byte flipped ⇒ SHA-256 differs from the signed output_sha256.
        let mut tampered = OUTPUT.to_vec();
        tampered[0] ^= 0x01;
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, &tampered, &CTX, &mut ledger, &fresh()), Err(TurnReason::CommitReadbackMismatch)));
    }

    // ---- REQUIRED: replayed receipt_id => Err(UpstreamBlocked) ----
    #[test]
    fn replayed_receipt_id_blocks() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        // The receipt_id has already been accepted (seen-set pre-seeded).
        let mut ledger = InMemoryLedger::new().with_seen_receipt("receipt-abc");
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    // ---- extra hardening ----

    #[test]
    fn output_length_mismatch_is_commit_readback_mismatch() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        let mut longer = OUTPUT.to_vec();
        longer.push(b'!'); // length gate fires before the digest gate
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, &longer, &CTX, &mut ledger, &fresh()), Err(TurnReason::CommitReadbackMismatch)));
    }

    #[test]
    fn a_replayed_nonce_blocks_even_with_a_fresh_receipt_id() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new().with_consumed_nonce("nonce-xyz");
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn tampering_any_signed_envelope_field_breaks_the_signature() {
        let f = fx();
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        // Flip completed_at_ms: signed field, so the reconstructed JCS no longer matches the signature.
        let mut env = envelope(&f);
        env.completed_at_ms = 9999;
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn a_wrong_isolated_signer_key_blocks() {
        let f = fx();
        let env = envelope(&f);
        let a = attest(&f);
        let other = signing_key(200).verifying_key().to_bytes();
        let mut k = keys(&f);
        k.isolated_signer_public_key = &other; // not the key that signed the envelope
        let mut ledger = InMemoryLedger::new();
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn a_bad_supervisor_attestation_signature_blocks() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let mut ledger = InMemoryLedger::new();
        // Attestation signed by the WRONG key.
        let forged = sign_b64(&signing_key(123), &f.attest_evidence);
        let a = SupervisorAttestation { evidence_jcs: &f.attest_evidence, signature_b64: &forged };
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn attestation_evidence_digest_mismatch_blocks() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let mut ledger = InMemoryLedger::new();
        // Different evidence bytes, correctly signed — but their SHA-256 no longer equals the envelope's
        // attestation_evidence_sha256, so the binding fails BEFORE the turn-binding parse.
        let other_evidence =
            evidence_jcs_with(&f.system, &f.history, &f.generation, &f.output_sha256, &[Ev("receipt_id", "receipt-OTHER".into())]);
        let sig = sign_b64(&signing_key(9), &other_evidence);
        let a = SupervisorAttestation { evidence_jcs: &other_evidence, signature_b64: &sig };
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn a_wrong_artifact_type_blocks_before_any_signature_check() {
        let f = fx();
        let k = keys(&f);
        let a = attest(&f);
        let mut env = envelope(&f);
        env.artifact_type = "brops.some-other.v1";
        let mut ledger = InMemoryLedger::new();
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn a_mismatched_request_nonce_blocks() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut exp = expected(&f);
        exp.request_nonce = "nonce-evil"; // envelope says nonce-xyz
        let mut ledger = InMemoryLedger::new();
        assert!(matches!(verify_and_accept(&exp, &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn invalid_utf8_output_blocks_even_when_the_digest_matches() {
        // The envelope commits to the digest+length of raw (non-UTF8) bytes; the gates pass but the
        // strict-UTF8 decode for the committed body fails ⇒ Block.
        let raw: &[u8] = &[0xff, 0xfe, 0x00, 0x80];
        let f = fx_over(raw, &[]);
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, raw, &CTX, &mut ledger, &fresh()), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn payload_jcs_is_deterministic_sorted_and_has_bare_integers() {
        let f = fx();
        let env = envelope(&f);
        let a = env.payload_jcs().unwrap();
        let b = env.payload_jcs().unwrap();
        assert_eq!(a, b, "JCS must be deterministic");
        let s = String::from_utf8(a).unwrap();
        // sorted keys: artifact_type is first, request_sha256 precedes run_id, etc.
        assert!(s.starts_with(r#"{"artifact_type":"#));
        // integer field is a bare integer, never quoted.
        assert!(s.contains(&format!("\"output_bytes\":{}", OUTPUT.len())));
        assert!(!s.contains(&format!("\"output_bytes\":\"{}\"", OUTPUT.len())));
        // no whitespace between members.
        assert!(!s.contains(", "));
        assert!(!s.contains(": "));
    }

    // =============================================================================================
    // Step 4c — the supervisor attestation must be an account of THIS turn.
    //
    // Before this, step 3 hashed `evidence_jcs` and never parsed it, so a supervisor attestation
    // about a DIFFERENT run satisfied both of its checks: the signature verifies (it is genuine) and
    // the digest matches (the signer committed to whatever bytes it was handed). The headline test
    // below is exactly that adversary — every signature in it is real.
    // =============================================================================================

    /// Pair THIS turn's envelope with a genuine supervisor attestation for a DIFFERENT turn, and
    /// re-sign the envelope so its `attestation_evidence_sha256` commits to the foreign bytes. Every
    /// signature is valid, the digest binding holds, the request/output/run bindings all match the
    /// broker's own Expected — the only defect is that the supervisor attested another run.
    fn envelope_bound_to_foreign_attestation(f: &Fx, foreign: &[u8]) -> (String, String) {
        let mut env = envelope(f);
        let foreign_sha = sha256_hex(foreign);
        env.attestation_evidence_sha256 = &foreign_sha;
        let env_sig = sign_b64(&signing_key(7), &env.payload_jcs().unwrap());
        (foreign_sha, env_sig)
    }

    #[test]
    fn a_valid_attestation_for_a_different_turn_is_refused() {
        let f = fx();
        // A COMPLETE, well-formed, correctly-signed §4.6 attestation — about another run.
        let foreign = evidence_jcs_with(
            &hx(0x11),
            &hx(0x22),
            &hx(0x33),
            &sha256_hex(b"a different turn's reply"),
            &[
                Ev("run_id", "run-OTHER".into()),
                Ev("task_id", "task-OTHER".into()),
                Ev("execution_attempt_id", "att-OTHER".into()),
                Ev("request_nonce", "nonce-OTHER".into()),
                Ev("receipt_id", "receipt-OTHER".into()),
            ],
        );
        let foreign_sig = sign_b64(&signing_key(9), &foreign);
        let (foreign_sha, env_sig) = envelope_bound_to_foreign_attestation(&f, &foreign);

        let mut env = envelope(&f);
        env.attestation_evidence_sha256 = &foreign_sha;
        let k = keys(&f);
        let a = SupervisorAttestation { evidence_jcs: &foreign, signature_b64: &foreign_sig };
        let mut ledger = InMemoryLedger::new();

        // Sanity: the attestation really is genuine and really is bound to this envelope, i.e. the
        // test is not passing because something upstream of step 4c is broken.
        assert!(
            verify_ed25519(&f.sup_pub, &foreign, &foreign_sig).is_ok(),
            "the foreign attestation must carry a REAL supervisor signature"
        );
        assert_eq!(
            sha256_hex(a.evidence_jcs),
            env.attestation_evidence_sha256,
            "the envelope must be bound to the foreign evidence bytes (step 3 must pass)"
        );

        match verify_and_accept(&expected(&f), &env, &env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()) {
            Err(TurnReason::UpstreamBlocked) => {}
            Err(other) => panic!("expected UpstreamBlocked, got {other:?}"),
            Ok(_) => panic!(
                "a genuinely-signed supervisor attestation about ANOTHER run must never authorize this turn"
            ),
        }
        // A blocked turn burns nothing.
        assert_eq!(ledger.claim("receipt-abc", "nonce-xyz"), Ok(()));
    }

    #[test]
    fn an_attestation_that_disagrees_with_the_envelope_about_one_fact_is_refused() {
        // Each case is a genuine, fully-signed attestation for this turn that differs from the
        // isolated signer's separately-signed envelope in exactly ONE field.
        let cases: Vec<(&str, Ev)> = vec![
            ("run_id", Ev("run_id", "run-2".into())),
            ("execution_attempt_id", Ev("execution_attempt_id", "att-2".into())),
            ("task_id", Ev("task_id", "task-2".into())),
            ("workspace_id", Ev("workspace_id", "ws-2".into())),
            ("install_id", Ev("install_id", "install-2".into())),
            ("request_nonce", Ev("request_nonce", "nonce-2".into())),
            ("receipt_id", Ev("receipt_id", "receipt-2".into())),
            ("record_handle", Ev("record_handle", H_LEASE.into())),
            ("lease_handle", Ev("lease_handle", H_RECORD.into())),
            ("execution_receipt_handle", Ev("execution_receipt_handle", H_RECORD.into())),
            ("evidence_final_event_hash", Ev("evidence_final_event_hash", H_RECORD.into())),
            ("output_handle", Ev("output_handle", sha256_hex(b"other bytes").into())),
            ("challenge_accepted_at_ms", Ev("challenge_accepted_at_ms", Value::Number(Number::from(1001)))),
            ("completed_at", Ev("completed_at", Value::Number(Number::from(2001)))),
            ("evidence_event_count", Ev("evidence_event_count", Value::Number(Number::from(4)))),
            ("evidence_last_sequence", Ev("evidence_last_sequence", Value::Number(Number::from(13)))),
            ("evidence_head_sequence", Ev("evidence_head_sequence", Value::Number(Number::from(13)))),
            ("system_handle", Ev("system_handle", hx(0x56).into())),
            ("history_handle", Ev("history_handle", hx(0x67).into())),
            ("generation_config_handle", Ev("generation_config_handle", hx(0x45).into())),
            ("requested_at", Ev("requested_at", Value::Number(Number::from(1001)))),
            ("decision", Ev("decision", "denied".into())),
        ];
        for (name, over) in cases {
            // The ENVELOPE stays this turn's (built by `fx()`); only the attestation varies, and it
            // is re-signed, so the supervisor signature and the digest binding both still hold.
            let f = fx();
            let variant = evidence_jcs_with(&f.system, &f.history, &f.generation, &f.output_sha256, &[over]);
            let variant_sig = sign_b64(&signing_key(9), &variant);
            let variant_sha = sha256_hex(&variant);
            let mut env = envelope(&f);
            env.attestation_evidence_sha256 = &variant_sha;
            let env_sig = sign_b64(&signing_key(7), &env.payload_jcs().unwrap());
            let k = keys(&f);
            let a = SupervisorAttestation { evidence_jcs: &variant, signature_b64: &variant_sig };
            let mut ledger = InMemoryLedger::new();
            match verify_and_accept(&expected(&f), &env, &env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()) {
                Err(TurnReason::UpstreamBlocked) => {}
                Err(other) => panic!("{name}: expected UpstreamBlocked, got {other:?}"),
                Ok(_) => panic!("{name}: the supervisor and the signer disagree about this turn — Block"),
            }
        }
    }

    #[test]
    fn the_genuine_attestation_still_binds_and_accepts() {
        // The counterweight to the refusals above: if `bind_attested_evidence` were merely "always
        // refuse", every negative test would pass and the module would be dead. This proves the
        // full 29-key record of a real turn passes step 4c.
        let f = fx();
        let attested = AttestedEvidence::parse(&f.attest_evidence).expect("real evidence must parse");
        let env = envelope(&f);
        bind_attested_evidence(&attested, &env, &expected(&f), &CTX)
            .expect("the supervisor's account of THIS turn must bind");
    }

    #[test]
    fn malformed_attested_evidence_is_refused_rather_than_ignored() {
        let f = fx();
        let good = String::from_utf8(f.attest_evidence.clone()).unwrap();
        let cases: Vec<(&str, Vec<u8>)> = vec![
            ("not json", b"not json at all".to_vec()),
            ("not an object", b"[1,2,3]".to_vec()),
            ("empty object", b"{}".to_vec()),
            (
                "duplicate key",
                // A duplicate `run_id`: a lax parser keeps the last one, so the field the broker
                // reads and the field a differently-lax reader reads can disagree.
                good.replacen(r#""run_id":"run-1""#, r#""run_id":"run-1","run_id":"run-1""#, 1).into_bytes(),
            ),
            (
                "unknown extra key",
                good.replacen('{', r#"{"aaa_unknown":"x","#, 1).into_bytes(),
            ),
            (
                "missing key",
                good.replacen(r#""supervisor_id":"sup-1","#, "", 1).into_bytes(),
            ),
            (
                "integer field sent as a string",
                good.replacen(&format!(r#""completed_at":{T_COMPLETED_MS}"#), &format!(r#""completed_at":"{T_COMPLETED_MS}""#), 1).into_bytes(),
            ),
            (
                "string field sent as a number",
                good.replacen(r#""run_id":"run-1""#, r#""run_id":1"#, 1).into_bytes(),
            ),
            (
                "nested value",
                good.replacen(r#""run_id":"run-1""#, r#""run_id":{"a":1}"#, 1).into_bytes(),
            ),
            (
                "empty string field",
                good.replacen(r#""run_id":"run-1""#, r#""run_id":"""#, 1).into_bytes(),
            ),
            (
                "float where an integer is required",
                good.replacen(&format!(r#""completed_at":{T_COMPLETED_MS}"#), &format!(r#""completed_at":{T_COMPLETED_MS}.5"#), 1).into_bytes(),
            ),
            ("oversize", vec![b'x'; MAX_ATTESTATION_EVIDENCE_BYTES + 1]),
        ];
        for (name, bytes) in cases {
            assert!(
                AttestedEvidence::parse(&bytes).is_err(),
                "{name}: malformed attested evidence must be refused, not read past"
            );
            // ...and it must Block the whole turn, with every signature over it genuine.
            let sig = sign_b64(&signing_key(9), &bytes);
            let sha = sha256_hex(&bytes);
            let mut env = envelope(&f);
            env.attestation_evidence_sha256 = &sha;
            let env_sig = sign_b64(&signing_key(7), &env.payload_jcs().unwrap());
            let k = keys(&f);
            let a = SupervisorAttestation { evidence_jcs: &bytes, signature_b64: &sig };
            let mut ledger = InMemoryLedger::new();
            assert!(
                matches!(
                    verify_and_accept(&expected(&f), &env, &env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()),
                    Err(TurnReason::UpstreamBlocked)
                ),
                "{name}: must Block"
            );
        }
    }

    // =============================================================================================
    // IDX-67 / IDX-86 / IDX-94 — the replay defence must SURVIVE A RESTART.
    //
    // The finding was not that the §7.1(c)(d) checks were missing: it was that every production call
    // site handed `verify_and_accept` an `InMemoryLedger`, whose two HashSets die with the process.
    // The tests above prove the checks fire; these prove they still fire on a DIFFERENT run of the
    // program, driving the REAL verifier against the REAL durable ledger over a REAL file. Swap
    // `DurableAcceptanceLedger` back for `InMemoryLedger` here and both of these fail.
    // =============================================================================================

    fn durable(db: &std::path::Path) -> crate::broker_turns::DurableAcceptanceLedger {
        crate::broker_turns::DurableAcceptanceLedger::open(db.to_str().unwrap())
            .expect("open durable acceptance ledger")
    }

    #[test]
    fn a_receipt_replayed_after_a_restart_is_still_refused() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("broker.db");
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);

        // --- run 1: a genuine, fully-verified turn is accepted and its receipt_id recorded ---
        {
            let mut ledger = durable(&db);
            verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh())
                .expect("the first genuine turn must be accepted");
        } // ledger + its connection dropped == the broker process exiting

        // --- run 2: the SAME signed envelope, byte for byte, replayed against a fresh process ---
        let mut ledger = durable(&db);
        assert!(
            matches!(
                verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()),
                Err(TurnReason::UpstreamBlocked)
            ),
            "a receipt_id accepted before the restart must still be refused after it"
        );
    }

    #[test]
    fn a_nonce_replayed_after_a_restart_is_still_refused() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("broker.db");
        let f = fx();
        let k = keys(&f);
        let a = attest(&f);

        // --- run 1: accept a genuine turn, spending `nonce-xyz` ---
        {
            let env = envelope(&f);
            let mut ledger = durable(&db);
            verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh())
                .expect("the first genuine turn must be accepted");
        }

        // --- run 2: a DIFFERENT receipt, genuinely re-signed by the same isolated signer, reusing the
        //     already-spent request_nonce. The receipt-id defence cannot catch this one; only the
        //     one-time nonce can, and only if it outlived the restart. ---
        let mut second = envelope(&f);
        second.receipt_id = "receipt-second";
        let second_sig = sign_b64(&signing_key(7), &second.payload_jcs().unwrap());
        assert_eq!(second.request_nonce, "nonce-xyz", "the replay reuses the spent nonce");

        let mut ledger = durable(&db);
        assert!(
            matches!(
                verify_and_accept(&expected(&f), &second, &second_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &fresh()),
                Err(TurnReason::UpstreamBlocked)
            ),
            "a request_nonce consumed before the restart must still be refused after it"
        );
        // And the refusal wrote nothing: `receipt-second` was rolled back with the failed claim, so it
        // is still free for the turn it legitimately belongs to.
        assert_eq!(ledger.claim("receipt-second", "nonce-unspent"), Ok(()));
    }

    // =============================================================================================
    // §7.1 FRESHNESS — the bound on how OLD an accepted receipt may be.
    //
    // Every test below drives the REAL `verify_and_accept`, with every signature genuinely recomputed
    // for the timestamps under test. The only thing that varies is when the turn happened and what the
    // broker's clock says now.
    // =============================================================================================

    /// Run the genuine fixture for a turn at `accepted_ms`/`completed_ms` against a broker clock of
    /// `now_ms` under the LOCKED window. Returns the verdict and the ledger, so a caller can also ask
    /// whether the refusal burned anything.
    fn accept_at(
        accepted_ms: i64,
        completed_ms: i64,
        now_ms: i64,
    ) -> (Result<AcceptedOutput, TurnReason>, InMemoryLedger) {
        accept_with(accepted_ms, completed_ms, Freshness::at(now_ms))
    }

    fn accept_with(
        accepted_ms: i64,
        completed_ms: i64,
        freshness: Freshness,
    ) -> (Result<AcceptedOutput, TurnReason>, InMemoryLedger) {
        let f = fx_at(accepted_ms, completed_ms);
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        let r =
            verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger, &freshness);
        (r, ledger)
    }

    /// THE FINDING. A receipt that was validly signed — every signature, binding, identity and digest
    /// perfect — but produced a year ago. Before the freshness step this committed a governed reply
    /// today; the acceptance ledger has no opinion about it, because it was never accepted before.
    #[test]
    fn a_perfectly_signed_receipt_from_a_year_ago_is_refused() {
        const YEAR_MS: i64 = 365 * 24 * 60 * 60 * 1000;
        let (r, mut ledger) = accept_at(T_ACCEPTED_MS, T_COMPLETED_MS, T_NOW_MS + YEAR_MS);
        assert!(matches!(r, Err(TurnReason::UpstreamBlocked)), "a year-old receipt must Block");
        // ...and the refusal burned nothing: freshness is decided before the ledger is claimed, so the
        // one-time nonce is still available to the turn it legitimately belongs to.
        assert_eq!(
            ledger.claim("receipt-abc", "nonce-xyz"),
            Ok(()),
            "a stale receipt must not consume the nonce or the receipt id"
        );
    }

    /// §1: "a time `t` is in a window iff `lo_ms ≤ t ≤ hi_ms`" — both ends INCLUSIVE. Exercised on the
    /// stale side and the future side, one millisecond either way, with the arithmetic written out.
    #[test]
    fn the_freshness_window_boundaries_are_inclusive_on_both_ends() {
        let max_age = GOVERNED_TURN_FRESHNESS.max_age_ms as i64; // 300000
        let skew = GOVERNED_TURN_FRESHNESS.future_skew_ms as i64; // 60000
        let now = T_NOW_MS;

        // --- stale side: the OLDEST field (`challenge_accepted_at_ms`) sits exactly on the limit ---
        assert!(accept_at(now - max_age, now, now).0.is_ok(), "t == now - max_age_ms is INSIDE");
        assert!(
            matches!(accept_at(now - max_age - 1, now, now).0, Err(TurnReason::UpstreamBlocked)),
            "t == now - max_age_ms - 1 is OUTSIDE"
        );

        // --- future side: the NEWEST field (`completed_at_ms`) sits exactly on the limit ---
        assert!(accept_at(now, now + skew, now).0.is_ok(), "t == now + future_skew_ms is INSIDE");
        assert!(
            matches!(accept_at(now, now + skew + 1, now).0, Err(TurnReason::UpstreamBlocked)),
            "t == now + future_skew_ms + 1 is OUTSIDE"
        );
    }

    /// The two `_ms` fields are bounded INDEPENDENTLY. A single check over one of them would let an
    /// envelope pair a fresh stamp with an ancient one — a turn that did not happen either way.
    #[test]
    fn each_signed_ms_field_is_bounded_on_its_own() {
        let max_age = GOVERNED_TURN_FRESHNESS.max_age_ms as i64;
        let skew = GOVERNED_TURN_FRESHNESS.future_skew_ms as i64;
        let now = T_NOW_MS;
        // Ancient acceptance, fresh completion. (Passes the ordering check — only the window catches it.)
        assert!(
            matches!(accept_at(now - max_age - 1, now, now).0, Err(TurnReason::UpstreamBlocked)),
            "an out-of-window challenge_accepted_at_ms must Block even with a fresh completed_at_ms"
        );
        // Fresh acceptance, far-future completion.
        assert!(
            matches!(accept_at(now, now + skew + 1, now).0, Err(TurnReason::UpstreamBlocked)),
            "an out-of-window completed_at_ms must Block even with a fresh challenge_accepted_at_ms"
        );
    }

    /// §7's execution time-chain runs `challenge_accepted_at_ms ≤ … ≤ completed_at_ms`. A reversed pair
    /// is refused even when BOTH values sit comfortably inside the window — otherwise the ordering rule
    /// would be masked by the window rule and could never be observed failing on its own.
    #[test]
    fn a_reversed_time_chain_is_refused_with_both_stamps_inside_the_window() {
        let now = T_NOW_MS;
        let accepted = now - 1_000;
        let completed = now - 2_000;
        // Both are unambiguously inside [now-300000, now+60000] — proven here, not asserted by comment.
        let max_age = GOVERNED_TURN_FRESHNESS.max_age_ms as i64;
        assert!(accepted >= now - max_age && completed >= now - max_age && accepted <= now && completed <= now);
        assert!(
            matches!(accept_at(accepted, completed, now).0, Err(TurnReason::UpstreamBlocked)),
            "completed_at_ms before challenge_accepted_at_ms must Block"
        );
        // The same pair in the right order is accepted, so the refusal above is the ORDER and nothing else.
        assert!(accept_at(completed, accepted, now).0.is_ok());
    }

    /// §1's `_ms` range (`1 ≤ v ≤ 2^53-1`), tested at clock positions where the WINDOW would accept the
    /// value — otherwise the range check is invisible behind the window check and could be deleted
    /// without any test noticing.
    #[test]
    fn out_of_range_ms_values_are_refused_where_the_window_alone_would_admit_them() {
        // Lower end: at now == max_age_ms the stale limit is exactly 0, so `t == 0` is INSIDE the
        // window (inclusive) and only the §1 range check can refuse it.
        let now = GOVERNED_TURN_FRESHNESS.max_age_ms as i64; // 300000
        assert_eq!(now - GOVERNED_TURN_FRESHNESS.max_age_ms as i64, 0, "stale limit is exactly 0 here");
        assert!(
            matches!(accept_at(0, 1_000, now).0, Err(TurnReason::UpstreamBlocked)),
            "challenge_accepted_at_ms == 0 must Block (§1: 1 ≤ v)"
        );
        // ...and 1 — the smallest LEGAL value — is accepted at the same clock, so the refusal above is
        // the range and not the window.
        assert!(accept_at(1, 1_000, now).0.is_ok());

        // Upper end: at now == 2^53-1 the future limit is 2^53-1+60000, so `t == 2^53` is INSIDE the
        // window and only the §1 range check can refuse it.
        let now = MAX_GOVERNED_MS;
        let out_of_range = MAX_GOVERNED_MS as i128 + 1; // 2^53 — one past the §1 ceiling
        let future_limit = now as i128 + GOVERNED_TURN_FRESHNESS.future_skew_ms as i128;
        assert!(
            out_of_range <= future_limit,
            "the value under test must be INSIDE the window, or this proves nothing about the range check"
        );
        assert!(
            matches!(accept_at(MAX_GOVERNED_MS, MAX_GOVERNED_MS + 1, now).0, Err(TurnReason::UpstreamBlocked)),
            "completed_at_ms == 2^53 must Block (§1: v ≤ 2^53-1)"
        );
        assert!(accept_at(MAX_GOVERNED_MS - 1, MAX_GOVERNED_MS, now).0.is_ok());
    }

    /// A clock the broker could not read must REFUSE, not collapse the window.
    ///
    /// `SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or(0)` — the shape that already exists in
    /// this repository — yields 0 on a machine whose clock is set before 1970. With `now_ms == 0` the
    /// window becomes `[-300000, 60000]`, inside which a 1970-stamped receipt is "fresh". The clock is
    /// therefore range-checked as a §1 `_ms` value in its own right.
    #[test]
    fn a_clock_that_reads_zero_or_negative_refuses_instead_of_collapsing_the_window() {
        // The receipt that a collapsed window would admit: stamps of 1 ms and 2 ms past the epoch.
        assert!(
            matches!(accept_at(1, 2, 0).0, Err(TurnReason::UpstreamBlocked)),
            "now_ms == 0 is not a clock reading; it must Block"
        );
        assert!(matches!(accept_at(1, 2, -1).0, Err(TurnReason::UpstreamBlocked)), "a negative clock must Block");
        assert!(
            matches!(accept_at(1, 2, MAX_GOVERNED_MS + 1).0, Err(TurnReason::UpstreamBlocked)),
            "a clock beyond the §1 range must Block"
        );
        // The SAME receipt at the smallest LEGAL clock reading is accepted — so what refused above was
        // the illegal clock, not the receipt.
        assert!(accept_at(1, 2, 1).0.is_ok(), "now_ms == 1 is legal, and this receipt is fresh for it");
    }

    /// A window that bounds nothing is refused rather than honoured. There is no public constructor
    /// that can build one — [`Freshness::at`] always installs the locked policy — but the rule is
    /// enforced in the checker so that a future caller-supplied window cannot widen the bound.
    #[test]
    fn a_window_wider_than_the_locked_policy_is_refused() {
        let cases: [(&str, FreshnessWindow); 4] = [
            ("unbounded max_age", FreshnessWindow { future_skew_ms: 60_000, max_age_ms: u64::MAX }),
            ("max_age one ms wider than locked", FreshnessWindow { future_skew_ms: 60_000, max_age_ms: 300_001 }),
            ("skew one ms wider than locked", FreshnessWindow { future_skew_ms: 60_001, max_age_ms: 300_000 }),
            ("max_age of zero bounds nothing usable", FreshnessWindow { future_skew_ms: 60_000, max_age_ms: 0 }),
        ];
        for (name, window) in cases {
            let (r, _) = accept_with(T_ACCEPTED_MS, T_COMPLETED_MS, Freshness::with_window(T_NOW_MS, window));
            assert!(matches!(r, Err(TurnReason::UpstreamBlocked)), "{name}: must Block");
        }
        // The locked window on the same turn accepts, so the refusals above are the WINDOW and nothing else.
        let (r, _) =
            accept_with(T_ACCEPTED_MS, T_COMPLETED_MS, Freshness::with_window(T_NOW_MS, GOVERNED_TURN_FRESHNESS));
        assert!(r.is_ok());
    }

    /// The locked policy is the design's, and it is the SAME object the v1 receipt path uses (§7.1:
    /// "the real `receipt_store.rs` values"). If either side is ever retuned this goes red.
    #[test]
    fn the_locked_window_is_the_design_values() {
        assert_eq!(GOVERNED_TURN_FRESHNESS.future_skew_ms, 60_000);
        assert_eq!(GOVERNED_TURN_FRESHNESS.max_age_ms, 300_000);
        assert_eq!(GOVERNED_TURN_FRESHNESS.future_skew_ms, FreshnessWindow::DEFAULT.future_skew_ms);
        assert_eq!(GOVERNED_TURN_FRESHNESS.max_age_ms, FreshnessWindow::DEFAULT.max_age_ms);
        assert_eq!(MAX_GOVERNED_MS, 9_007_199_254_740_991);
    }

    /// THE ARITHMETIC, done rather than asserted in a comment (§1 window-nesting, §4.3).
    ///
    /// A cap larger than the largest legal input is a check that cannot fail. So: what is the OLDEST
    /// `challenge_accepted_at_ms` a legitimate turn can present at broker acceptance, and is
    /// `max_age_ms` above it — and by how much?
    ///
    ///   worst legitimate age of `challenge_accepted_at_ms` at acceptance
    ///     = LEASE_DURATION_MS (210000; §4.3 pins `lease_issued_at_ms == challenge_accepted_at_ms`
    ///       and `completed_at_ms ≤ lease_expires_at_ms == +210000`)
    ///     + whatever the broker then spends pulling and verifying the output.
    ///   max_age_ms − 210000 = 90000 ms of budget for that tail.
    ///
    /// §1's own nesting sentence adds the challenge TTL (≤30000) on the front — 30000 + 210000 =
    /// 240000 < 300000 — which is the age of `challenge_issued_at_ms`, a field the envelope does not
    /// carry. Both readings leave the window strictly wider than any legitimate turn, and strictly
    /// narrower than "unbounded". The test then SHOWS both edges on the real verifier.
    #[test]
    fn the_locked_window_nests_the_whole_legitimate_lease_budget_with_real_slack() {
        use crate::supervisor_ledger::LEASE_DURATION_MS;
        const DESIGN_CHALLENGE_TTL_MAX_MS: i64 = 30_000; // §4.1/§5 challenge TTL ceiling
        let max_age = GOVERNED_TURN_FRESHNESS.max_age_ms as i64;

        assert_eq!(LEASE_DURATION_MS, 210_000);
        assert_eq!(DESIGN_CHALLENGE_TTL_MAX_MS + LEASE_DURATION_MS, 240_000);
        assert!(
            DESIGN_CHALLENGE_TTL_MAX_MS + LEASE_DURATION_MS < max_age,
            "§1 window-nesting: the whole challenge+lease budget must fit inside max_age_ms"
        );
        assert_eq!(max_age - LEASE_DURATION_MS, 90_000, "post-completion budget the broker gets");

        // The window admits a turn at the worst legitimate age (a receipt whose acceptance stamp is a
        // full lease-duration old when the broker finally verifies it)...
        let now = T_NOW_MS;
        assert!(
            accept_at(now - LEASE_DURATION_MS, now - 1_000, now).0.is_ok(),
            "a legitimate slow-but-legal turn must NOT be refused as stale"
        );
        // ...and it is not a cap above every legal input: one millisecond past max_age_ms Blocks.
        assert!(
            matches!(accept_at(now - max_age - 1, now - 1_000, now).0, Err(TurnReason::UpstreamBlocked)),
            "the cap must be reachable by an illegal input, or it is not a check"
        );
    }
}
