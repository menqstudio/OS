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
//!  1. **Envelope identity** — `artifact_type` is the frozen §4.9 const and `key_id` equals the pinned
//!     isolated-signer key id; `supervisor_attestation_key_id` equals the pinned attestation key id.
//!  2. **Isolated-signer signature** — Ed25519 (`verify_strict`) over `JCS(payload)` under the pinned
//!     isolated-signer key. The payload JCS is **reconstructed** here from the envelope fields (sorted
//!     compact `serde_json` of a `Map`, RFC-8785-compatible for the ASCII key set — the same shortcut
//!     `receipt.rs` documents), so tampering ANY field breaks the signature.
//!  3. **Supervisor attestation** — Ed25519 over the attested `evidence_jcs` under the pinned attestation
//!     key, AND `SHA256(evidence_jcs) == envelope.attestation_evidence_sha256` (the envelope's binding to
//!     the exact bytes the supervisor signed, §4.9).
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

use std::collections::HashSet;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use ed25519_dalek::{Signature, VerifyingKey};
use serde_json::{Map, Number, Value};

use crate::governed_message_store::AcceptedOutput;
use crate::governed_turn_ipc::TurnReason;
use crate::receipt::{sha256_hex, IssuedRequest};

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

/// The supervisor attestation (§4.6): the exact `JCS(governed-sign-request evidence)` bytes the supervisor
/// signed, plus its detached Ed25519 signature (base64url). The broker re-verifies the signature under the
/// pinned attestation key AND checks `SHA256(evidence_jcs) == envelope.attestation_evidence_sha256`.
#[derive(Debug, Clone, Copy)]
pub struct SupervisorAttestation<'a> {
    pub evidence_jcs: &'a [u8],
    pub signature_b64: &'a str,
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
    pub expected_execution_attempt_id: &'a str,
}

/// The injected acceptance-ledger ports: `receipt_id` global-uniqueness and one-time `request_nonce`
/// consume (§7.1(c)(d)). Kept as a trait so the pure verifier needs no DB — the broker's real
/// implementation is a `BEGIN IMMEDIATE` transaction, and tests inject an in-memory fake.
pub trait AcceptanceLedger {
    /// Has this `receipt_id` already been accepted? (global-unique replay defense).
    fn is_receipt_seen(&self, receipt_id: &str) -> bool;
    /// Atomically consume the one-time `request_nonce`. Returns `true` if it was newly consumed, `false`
    /// if it had already been consumed (a replay).
    fn consume_nonce(&mut self, request_nonce: &str) -> bool;
    /// Record a `receipt_id` as accepted (called only after every check passes).
    fn record_receipt(&mut self, receipt_id: &str);
}

/// A simple in-memory [`AcceptanceLedger`] (two sets). The real broker backs these by its receipt DB
/// under one `BEGIN IMMEDIATE` transaction; this is for the pure verifier's own tests and any host-side
/// dry-run. Fully offline.
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
    fn is_receipt_seen(&self, receipt_id: &str) -> bool {
        self.seen_receipts.contains(receipt_id)
    }
    fn consume_nonce(&mut self, request_nonce: &str) -> bool {
        self.consumed_nonces.insert(request_nonce.to_string())
    }
    fn record_receipt(&mut self, receipt_id: &str) {
        self.seen_receipts.insert(receipt_id.to_string());
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
/// identity; `ledger` is the one-time nonce + receipt-id freshness store.
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
    if envelope.run_id != ctx.expected_run_id
        || envelope.task_id != ctx.expected_task_id
        || envelope.execution_attempt_id != ctx.expected_execution_attempt_id
    {
        return Err(TurnReason::UpstreamBlocked);
    }

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

    // 6. receipt_id freshness (global-unique replay defense) — before consuming the nonce.
    if ledger.is_receipt_seen(envelope.receipt_id) {
        return Err(TurnReason::UpstreamBlocked);
    }
    // 7. request_nonce one-time consume; a replayed nonce Blocks. On success record the receipt_id.
    if !ledger.consume_nonce(envelope.request_nonce) {
        return Err(TurnReason::UpstreamBlocked);
    }
    ledger.record_receipt(envelope.receipt_id);

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
    const ATTEST_EVIDENCE: &[u8] = br#"{"protocol":"brops.governed-sign-request.v1","x":1}"#;

    // 64-hex handle/head literals (owned 'static so borrowing them in the fixture is sound; their
    // values are not cross-checked by this slice — only carried into the signed JCS).
    const H_RECORD: &str = "1111111111111111111111111111111111111111111111111111111111111111";
    const H_LEASE: &str = "2222222222222222222222222222222222222222222222222222222222222222";
    const H_RECEIPT: &str = "3333333333333333333333333333333333333333333333333333333333333333";
    const H_EVIDENCE: &str = "7777777777777777777777777777777777777777777777777777777777777777";

    // Stable owned strings the borrowed structs point at.
    struct Fx {
        system: String,
        history: String,
        generation: String,
        request_sha256: String,
        output_sha256: String,
        attest_sha256: String,
        iso_pub: [u8; 32],
        sup_pub: [u8; 32],
        env_sig: String,
        attest_sig: String,
    }

    fn fx() -> Fx {
        let system = hx(0x55);
        let history = hx(0x66);
        let generation = hx(0x44);
        let request_sha256 = crate::receipt::request_envelope_sha256(
            "ws-1", "install-1", "nonce-xyz", &system, &history, &generation, "1000",
        );
        let output_sha256 = sha256_hex(OUTPUT);
        let attest_sha256 = sha256_hex(ATTEST_EVIDENCE);
        let iso = signing_key(7);
        let sup = signing_key(9);
        let mut f = Fx {
            system,
            history,
            generation,
            request_sha256,
            output_sha256,
            attest_sha256,
            iso_pub: iso.verifying_key().to_bytes(),
            sup_pub: sup.verifying_key().to_bytes(),
            env_sig: String::new(),
            attest_sig: String::new(),
        };
        // Sign the reconstructed payload JCS + the attestation evidence.
        let env_sig = {
            let env = envelope(&f);
            sign_b64(&iso, &env.payload_jcs().unwrap())
        };
        f.env_sig = env_sig;
        f.attest_sig = sign_b64(&sup, ATTEST_EVIDENCE);
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
            requested_at: "1000",
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
            output_bytes: OUTPUT.len() as u64,
            challenge_accepted_at_ms: 1000,
            completed_at_ms: 2000,
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
        SupervisorAttestation { evidence_jcs: ATTEST_EVIDENCE, signature_b64: &f.attest_sig }
    }

    const CTX: BrokerContext<'static> = BrokerContext {
        broker_turn_id: "bt-1",
        message_id: "m-1",
        conversation_id: "conv-1",
        author: "Bro",
        expected_run_id: "run-1",
        expected_task_id: "task-1",
        expected_execution_attempt_id: "att-1",
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
                BrokerContext { expected_execution_attempt_id: "att-OTHER", ..CTX },
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
                &expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &ctx, &mut ledger,
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

    // ---- REQUIRED: matching bindings => Ok(AcceptedOutput with exact body) ----
    #[test]
    fn matching_bindings_accept_the_exact_output() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new();
        let accepted =
            verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger).unwrap();
        assert_eq!(accepted.accepted_body.as_bytes(), OUTPUT);
        assert_eq!(accepted.envelope_body_sha256, sha256_hex(OUTPUT));
        assert_eq!(accepted.message_id, "m-1");
        assert_eq!(accepted.broker_turn_id, "bt-1");
        assert_eq!(accepted.conversation_id, "conv-1");
        assert_eq!(accepted.author, "Bro");
        assert_eq!(accepted.created_at_ms, 2000);
        // The nonce is now consumed and the receipt_id recorded.
        assert!(ledger.is_receipt_seen("receipt-abc"));
        assert!(!ledger.consume_nonce("nonce-xyz"), "nonce must be one-time");
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
        assert!(matches!(verify_and_accept(&exp, &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
        // A blocked turn consumes nothing.
        assert!(!ledger.is_receipt_seen("receipt-abc"));
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
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, &tampered, &CTX, &mut ledger), Err(TurnReason::CommitReadbackMismatch)));
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
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
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
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, &longer, &CTX, &mut ledger), Err(TurnReason::CommitReadbackMismatch)));
    }

    #[test]
    fn a_replayed_nonce_blocks_even_with_a_fresh_receipt_id() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let a = attest(&f);
        let mut ledger = InMemoryLedger::new().with_consumed_nonce("nonce-xyz");
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
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
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
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
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn a_bad_supervisor_attestation_signature_blocks() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let mut ledger = InMemoryLedger::new();
        // Attestation signed by the WRONG key.
        let forged = sign_b64(&signing_key(123), ATTEST_EVIDENCE);
        let a = SupervisorAttestation { evidence_jcs: ATTEST_EVIDENCE, signature_b64: &forged };
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn attestation_evidence_digest_mismatch_blocks() {
        let f = fx();
        let env = envelope(&f);
        let k = keys(&f);
        let mut ledger = InMemoryLedger::new();
        // Different evidence bytes, correctly signed — but their SHA-256 no longer equals the envelope's
        // attestation_evidence_sha256, so the binding fails.
        let other_evidence = br#"{"protocol":"brops.governed-sign-request.v1","x":2}"#;
        let sig = sign_b64(&signing_key(9), other_evidence);
        let a = SupervisorAttestation { evidence_jcs: other_evidence, signature_b64: &sig };
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn a_wrong_artifact_type_blocks_before_any_signature_check() {
        let f = fx();
        let k = keys(&f);
        let a = attest(&f);
        let mut env = envelope(&f);
        env.artifact_type = "brops.some-other.v1";
        let mut ledger = InMemoryLedger::new();
        assert!(matches!(verify_and_accept(&expected(&f), &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
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
        assert!(matches!(verify_and_accept(&exp, &env, &f.env_sig, &a, &k, OUTPUT, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn invalid_utf8_output_blocks_even_when_the_digest_matches() {
        // The envelope commits to the digest+length of raw (non-UTF8) bytes; the gates pass but the
        // strict-UTF8 decode for the committed body fails ⇒ Block.
        let raw: &[u8] = &[0xff, 0xfe, 0x00, 0x80];
        let f0 = fx();
        let iso = signing_key(7);
        let sup = signing_key(9);
        let out_sha = sha256_hex(raw);
        let attest_sha = sha256_hex(ATTEST_EVIDENCE);
        let f = Fx {
            output_sha256: out_sha,
            attest_sha256: attest_sha,
            ..f0
        };
        let mut env = envelope(&f);
        env.output_bytes = raw.len() as u64;
        let env_sig = sign_b64(&iso, &env.payload_jcs().unwrap());
        let attest_sig = sign_b64(&sup, ATTEST_EVIDENCE);
        let k = keys(&f);
        let a = SupervisorAttestation { evidence_jcs: ATTEST_EVIDENCE, signature_b64: &attest_sig };
        let mut ledger = InMemoryLedger::new();
        assert!(matches!(verify_and_accept(&expected(&f), &env, &env_sig, &a, &k, raw, &CTX, &mut ledger), Err(TurnReason::UpstreamBlocked)));
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
}
