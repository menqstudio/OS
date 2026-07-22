//! Wave 3a slice 2: durable, atomic verify → consume → persist for governed
//! receipts (design §3 stateful subset + §4).
//!
//! The pure slice-1 core (`crate::receipt`) parses, verifies the Ed25519 signature,
//! and binds the §3 *value* subset, but holds no state. This module layers the
//! stateful checks the core defers — one-time **nonce** consume, **`receipt_id`**
//! global uniqueness, and wall-clock **freshness/skew** — on top of the type-state
//! chain `parse_strict → verify → bind → resolve_3a`, and records **every** attempt
//! (accepted or blocked) as re-verifiable evidence, all in **one transaction**.
//!
//! ## Invariants (design §4)
//! - A crash can neither persist an accepted message without consuming its nonce nor
//!   consume a nonce without persisting the message — the whole thing is one tx.
//! - A **blocked** verdict is NOT an error: it still **commits** its evidence row (so
//!   the forensic record survives). Only a real SQLite/internal failure returns `Err`
//!   and rolls the transaction back.
//! - A `blocked` attempt never becomes a `messages` row (enforced again in the schema).
//! - Wave 3a never yields `trusted_verified`: a production-class key resolves to
//!   `Blocked` here, so [`ReceiptOutcome`] has no "Verified" variant.

use crate::domain::{CoreError, CoreResult};
use crate::receipt::{
    self, Expected, IssuedRequest, ResolvedManifestKey, Wave3aTrustState, MAX_ENVELOPE_BYTES,
};
use crate::{id, NewMessage};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use rusqlite::{Connection, OptionalExtension};
use std::collections::BTreeMap;

/// Max characters of raw wire stored as evidence, so the attempts table cannot be
/// turned into a storage-DoS vector (Architect fix 1). These match the core protocol
/// caps in [`crate::receipt`]: an envelope b64 above the base64 expansion of
/// [`MAX_ENVELOPE_BYTES`] can never decode within the cap, and an Ed25519 signature
/// b64 is 86 chars (`Parsed::verify` rejects > 128).
const MAX_WIRE_ENVELOPE_B64: usize = MAX_ENVELOPE_BYTES / 3 * 4 + 4;
const MAX_WIRE_SIGNATURE_B64: usize = 128;

/// Wall-clock freshness / skew policy (design §3.8). **Host-owned** — the webview
/// cannot widen it. All values in milliseconds.
#[derive(Debug, Clone, Copy)]
pub struct FreshnessWindow {
    /// How far a timestamp may lead the local clock (clock skew).
    pub future_skew_ms: u64,
    /// How old a receipt may be before it is refused as stale.
    pub max_age_ms: u64,
}

impl FreshnessWindow {
    /// Initial policy: 60s future skew, 300s stale (Architect-accepted default).
    pub const DEFAULT: FreshnessWindow = FreshnessWindow {
        future_skew_ms: 60_000,
        max_age_ms: 300_000,
    };
}

/// The wire form of a receipt as received from the sidecar (design §2.3).
#[derive(Debug, Clone, Copy)]
pub struct ReceiptWire<'a> {
    pub envelope_jcs_b64: &'a str,
    pub signature_b64: &'a str,
}

/// Everything needed to verify + record one governed turn's receipt. Bundled so the
/// entry point stays a two-argument call (and to keep the resolved key + expected
/// bindings travelling together).
///
/// No `Debug`: it carries a [`ResolvedManifestKey`], which deliberately has no `Debug`
/// (it holds key material and keeps a minimal slice-1 surface).
#[derive(Clone, Copy)]
pub struct GovernedTurn<'a> {
    pub wire: ReceiptWire<'a>,
    /// The verifying key resolved from the trusted manifest. In slice 2 this is an
    /// input (test fixtures mint it via the `#[cfg(test)]` builder); the live
    /// validated manifest resolver is Wave 3b. `ResolvedManifestKey` keeps its
    /// no-public-constructor guarantee.
    pub resolved_key: ResolvedManifestKey<'a>,
    pub expected: Expected<'a>,
    /// The exact reply bytes (design §2.1, hashed as opaque bytes).
    pub output: &'a [u8],
    /// The host wall clock in ms (injected so freshness is host-owned and testable).
    pub now_ms: u64,
    pub freshness: FreshnessWindow,
}

/// The durable outcome of verifying + recording one governed receipt.
///
/// There is **no `TrustedVerified` variant** — Wave 3a cannot name "Verified" (design
/// §6). A production-class key resolves to [`ReceiptOutcome::Blocked`] here, exactly
/// as [`Wave3aTrustState`] has no `TrustedVerified` variant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReceiptOutcome {
    /// Accepted; rendered + persisted, badged development/untrusted. Carries the new
    /// message row and its evidence attempt row.
    DevelopmentUntrusted { message_id: String, attempt_id: String },
    /// Not accepted; evidence recorded, no message. `error` is the machine reason.
    Blocked { attempt_id: String, error: String },
}

/// Record a fresh desktop challenge (the issuing half of the one-time nonce). The
/// desktop calls this when it issues a governed request; the returned receipt must
/// later carry this exact nonce, still unconsumed. Inserted `consumed_at = NULL`.
///
/// Takes the single [`IssuedRequest`] and derives BOTH the stored `nonce` and
/// `request_sha256` from it — never a separate caller-supplied nonce/hash pair. This
/// closes the split-authority seam (audit round 2): a wiring bug cannot pair one
/// request's nonce with another request's hash, exactly as [`IssuedRequest::
/// request_sha256`] recomputes rather than trusting a supplied hash in slice 1. The
/// same `IssuedRequest` (inside `Expected`) is what the verifier later recomputes and
/// compares against, so issuance and verification share one source of truth.
pub fn issue_challenge(
    conn: &Connection,
    conversation_id: &str,
    request: &IssuedRequest,
    now_ms: u64,
) -> CoreResult<()> {
    conn.execute(
        "INSERT INTO receipt_challenges(nonce, conversation_id, request_sha256, issued_at, consumed_at)
         VALUES (?1, ?2, ?3, ?4, NULL)",
        rusqlite::params![
            request.request_nonce,
            conversation_id,
            request.request_sha256(),
            now_ms.to_string()
        ],
    )?;
    Ok(())
}

/// The atomic **verify → consume → persist** transaction (design §4).
///
/// Returns `Ok(Blocked{..})` for a *verdict* of blocked (evidence committed), and
/// `Ok(DevelopmentUntrusted{..})` for an accepted governed reply. Only a real
/// SQLite/internal failure returns `Err` — and rolls the whole transaction back, so
/// a would-be evidence row is never half-written.
pub fn verify_and_record_receipt(
    conn: &Connection,
    turn: &GovernedTurn,
) -> CoreResult<ReceiptOutcome> {
    in_immediate_tx(conn, |tx| record(tx, turn))
}

/// The transaction body. `tx` is an open connection inside `BEGIN IMMEDIATE`.
fn record(tx: &Connection, turn: &GovernedTurn) -> CoreResult<ReceiptOutcome> {
    let stamp = turn.now_ms.to_string();
    let wire_env = cap(turn.wire.envelope_jcs_b64, MAX_WIRE_ENVELOPE_B64);
    let wire_sig = cap(turn.wire.signature_b64, MAX_WIRE_SIGNATURE_B64);

    // --- Nonce: consume THIS desktop's own issued challenge for this turn --------
    // The challenge is keyed by what the desktop issued (`expected.request.
    // request_nonce`), never by a value read from the (possibly forged) receipt. A
    // valid + unconsumed challenge is consumed now, even if the receipt is later
    // blocked — a governed turn gets exactly one shot at its challenge.
    let want_nonce = turn.expected.request.request_nonce;
    let nonce_state = match load_challenge(tx, want_nonce)? {
        None => NonceState::Missing,
        Some((_, Some(_consumed), _)) => NonceState::Replay,
        Some((conversation_id, None, request_sha256)) => {
            let affected = tx.execute(
                "UPDATE receipt_challenges SET consumed_at = ?1 WHERE nonce = ?2 AND consumed_at IS NULL",
                rusqlite::params![stamp, want_nonce],
            )?;
            if affected == 1 {
                NonceState::Consumed { conversation_id, request_sha256 }
            } else {
                // Lost a race to consume — treat as replay.
                NonceState::Replay
            }
        }
    };

    // --- Pure core pipeline: parse → verify → bind ------------------------------
    let core = run_core(turn);

    // --- Decide the verdict + gather evidence -----------------------------------
    match core {
        // Failed at parse / verify / bind. Evidence is staged to what was validated
        // (design §4 — attempts is an auditable/re-verifiable record): pre-parse
        // failure => raw wire only; parsed + bad signature / verified + bind failure
        // => exact canonical envelope bytes + decoded 64-byte signature (+ key_id /
        // receipt_id when readable).
        CoreVerdict::Failed(ev) => {
            let attempt_id = insert_attempt(
                tx,
                &AttemptRow {
                    wire_env: &wire_env,
                    wire_sig: &wire_sig,
                    receipt_id: ev.receipt_id.as_deref(),
                    key_id: ev.key_id.as_deref(),
                    envelope_jcs: ev.envelope_jcs.as_deref(),
                    signature: ev.signature.as_deref(),
                    outcome: "blocked",
                    error: Some(&ev.error),
                    nonce: Some(want_nonce),
                    message_id: None,
                    stamp: &stamp,
                },
            )?;
            Ok(ReceiptOutcome::Blocked { attempt_id, error: ev.error })
        }

        // Signature + all pure §3 bindings passed. Now the stateful gates decide
        // accept vs blocked. We have full, re-verifiable evidence either way.
        CoreVerdict::Bound(bound) => {
            let decoded = bound.canonical_bytes().to_vec();
            let signature = bound.signature().to_vec();
            let receipt_id = bound.receipt_id().to_string();
            let key_id = bound.key_id().to_string();

            let block_reason: Option<String> = if !nonce_state.is_consumed() {
                Some(nonce_state.block_reason().to_string())
            } else if nonce_state.issued_request_sha256()
                != Some(turn.expected.request.request_sha256().as_str())
            {
                // The durable challenge was issued for a different request envelope
                // than the Expected the desktop is verifying against (§2.2 binding).
                Some("challenge request_sha256 does not match the expected request envelope".to_string())
            } else if matches!(bound.resolve_3a(), Wave3aTrustState::Blocked) {
                // production trust_class ⇒ Blocked in Wave 3a (never "Verified").
                Some("production trust_class is not renderable in Wave 3a".to_string())
            } else if receipt_id_seen(tx, &receipt_id)? {
                Some("receipt_id already accepted (replay)".to_string())
            } else {
                check_freshness(
                    bound.requested_at(),
                    bound.completed_at(),
                    turn.now_ms,
                    turn.freshness,
                )
                .err()
            };

            match block_reason {
                Some(error) => {
                    let attempt_id = insert_attempt(
                        tx,
                        &AttemptRow {
                            wire_env: &wire_env,
                            wire_sig: &wire_sig,
                            receipt_id: Some(&receipt_id),
                            key_id: Some(&key_id),
                            envelope_jcs: Some(&decoded),
                            signature: Some(&signature),
                            outcome: "blocked",
                            error: Some(&error),
                            nonce: Some(want_nonce),
                            message_id: None,
                            stamp: &stamp,
                        },
                    )?;
                    Ok(ReceiptOutcome::Blocked { attempt_id, error })
                }
                None => {
                    // Accepted (development_untrusted). `is_consumed()` guarantees the
                    // challenge existed, so its conversation_id is known.
                    let conversation_id = nonce_state
                        .conversation_id()
                        .expect("consumed nonce carries a conversation_id");

                    // The reply must render as text (design §2.1 exact UTF-8 bytes).
                    let body = match std::str::from_utf8(turn.output) {
                        Ok(s) => s.to_string(),
                        Err(_) => {
                            let error = "output bytes are not valid UTF-8".to_string();
                            let attempt_id = insert_attempt(
                                tx,
                                &AttemptRow {
                                    wire_env: &wire_env,
                                    wire_sig: &wire_sig,
                                    receipt_id: Some(&receipt_id),
                                    key_id: Some(&key_id),
                                    envelope_jcs: Some(&decoded),
                                    signature: Some(&signature),
                                    outcome: "blocked",
                                    error: Some(&error),
                                    nonce: Some(want_nonce),
                                    message_id: None,
                                    stamp: &stamp,
                                },
                            )?;
                            return Ok(ReceiptOutcome::Blocked { attempt_id, error });
                        }
                    };

                    // Order (Architect fix 2): message → accepted attempt → ledger,
                    // all in this tx. A real failure at any step rolls back the whole
                    // thing (including the nonce consume).
                    let msg = crate::repo::chat::post_message(
                        tx,
                        NewMessage {
                            conversation_id,
                            role: "agent".to_string(),
                            author: "agent".to_string(),
                            body,
                        },
                    )?;
                    let attempt_id = insert_attempt(
                        tx,
                        &AttemptRow {
                            wire_env: &wire_env,
                            wire_sig: &wire_sig,
                            receipt_id: Some(&receipt_id),
                            key_id: Some(&key_id),
                            envelope_jcs: Some(&decoded),
                            signature: Some(&signature),
                            outcome: "development_untrusted",
                            error: None,
                            nonce: Some(want_nonce),
                            message_id: Some(&msg.id),
                            stamp: &stamp,
                        },
                    )?;
                    tx.execute(
                        "INSERT INTO receipt_ids_seen(receipt_id, first_seen_at, attempt_id)
                         VALUES (?1, ?2, ?3)",
                        rusqlite::params![receipt_id, stamp, attempt_id],
                    )?;
                    Ok(ReceiptOutcome::DevelopmentUntrusted {
                        message_id: msg.id,
                        attempt_id,
                    })
                }
            }
        }
    }
}

/// Result of the pure core pipeline, carrying enough to build the evidence row.
enum CoreVerdict {
    /// Signature + all pure §3 bindings passed.
    Bound(receipt::BoundReceipt),
    /// Failed at parse / verify / bind, with whatever evidence was validated.
    Failed(FailedEvidence),
}

/// Evidence gathered for a blocked (non-`Bound`) attempt, staged by how far the core
/// pipeline got before failing (design §4). `envelope_jcs` / `signature` /
/// `receipt_id` are populated only once strict parse succeeded (so we present exact
/// canonical bytes, never a re-serialization of garbage).
struct FailedEvidence {
    error: String,
    envelope_jcs: Option<Vec<u8>>,
    signature: Option<Vec<u8>>,
    key_id: Option<String>,
    receipt_id: Option<String>,
}

/// Run `parse_strict → verify → bind`. On failure, stage evidence: pre-parse failure
/// carries only the error; a post-parse failure (bad signature or bind mismatch)
/// carries the exact canonical envelope bytes, the decoded 64-byte signature (when
/// decodable), `key_id`, and `receipt_id`.
fn run_core(turn: &GovernedTurn) -> CoreVerdict {
    let parsed = match receipt::parse_strict(turn.wire.envelope_jcs_b64) {
        Ok(p) => p,
        // Bytes are not a valid canonical envelope — never present them as canonical
        // evidence; the raw wire (stored by the caller) is the record of what arrived.
        Err(e) => {
            return CoreVerdict::Failed(FailedEvidence {
                error: e.to_string(),
                envelope_jcs: None,
                signature: None,
                key_id: None,
                receipt_id: None,
            })
        }
    };
    // parse_strict succeeded => the wire decodes to exactly these canonical bytes.
    let key_id = parsed.key_id().to_string();
    let envelope_jcs = decode_envelope(turn.wire.envelope_jcs_b64);
    let signature = decode_signature(turn.wire.signature_b64);
    let receipt_id = envelope_jcs.as_deref().and_then(extract_receipt_id);
    let fail = |error: String| {
        CoreVerdict::Failed(FailedEvidence {
            error,
            envelope_jcs: envelope_jcs.clone(),
            signature: signature.clone(),
            key_id: Some(key_id.clone()),
            receipt_id: receipt_id.clone(),
        })
    };

    let verified = match parsed.verify(&turn.resolved_key, turn.wire.signature_b64) {
        Ok(v) => v,
        Err(e) => return fail(e.to_string()),
    };
    match verified.bind(&turn.expected, turn.output) {
        Ok(b) => CoreVerdict::Bound(b),
        Err(e) => fail(e.to_string()),
    }
}

/// Base64url-decode the envelope wire to its exact bytes, within the protocol caps.
/// `None` when the input is over-cap or not valid base64url.
fn decode_envelope(b64: &str) -> Option<Vec<u8>> {
    if b64.len() > MAX_WIRE_ENVELOPE_B64 {
        return None;
    }
    URL_SAFE_NO_PAD
        .decode(b64.as_bytes())
        .ok()
        .filter(|b| b.len() <= MAX_ENVELOPE_BYTES)
}

/// Base64url-decode the signature wire; `Some` only when it is exactly 64 bytes.
fn decode_signature(b64: &str) -> Option<Vec<u8>> {
    if b64.len() > MAX_WIRE_SIGNATURE_B64 {
        return None;
    }
    URL_SAFE_NO_PAD
        .decode(b64.as_bytes())
        .ok()
        .filter(|b| b.len() == 64)
}

/// Read `receipt_id` from already-decoded canonical bytes for the evidence row. This
/// is evidence-gathering only (no security decision rides on it — those already
/// happened in `parse_strict`/`verify`/`bind`), so a lenient re-parse is acceptable.
fn extract_receipt_id(bytes: &[u8]) -> Option<String> {
    serde_json::from_slice::<BTreeMap<String, String>>(bytes)
        .ok()?
        .get("receipt_id")
        .cloned()
}

/// The state of the desktop challenge for this turn.
enum NonceState {
    /// No challenge was ever issued for this turn's nonce.
    Missing,
    /// The challenge was already consumed (a replay), or a race lost the consume.
    Replay,
    /// A valid, unconsumed challenge that we consumed now. Carries the conversation to
    /// post the accepted message into and the `request_sha256` the challenge was
    /// durably issued with (bound against the Expected before any accept).
    Consumed { conversation_id: String, request_sha256: String },
}

impl NonceState {
    fn is_consumed(&self) -> bool {
        matches!(self, NonceState::Consumed { .. })
    }
    fn conversation_id(&self) -> Option<String> {
        match self {
            NonceState::Consumed { conversation_id, .. } => Some(conversation_id.clone()),
            _ => None,
        }
    }
    /// The `request_sha256` this challenge was issued with (only when consumed).
    fn issued_request_sha256(&self) -> Option<&str> {
        match self {
            NonceState::Consumed { request_sha256, .. } => Some(request_sha256),
            _ => None,
        }
    }
    fn block_reason(&self) -> &'static str {
        match self {
            NonceState::Missing => "no issued challenge for this turn's nonce",
            NonceState::Replay => "request_nonce already consumed (replay)",
            NonceState::Consumed { .. } => "",
        }
    }
}

/// `(conversation_id, consumed_at, request_sha256)` for the challenge, or `None`.
fn load_challenge(
    conn: &Connection,
    nonce: &str,
) -> CoreResult<Option<(String, Option<String>, String)>> {
    conn.query_row(
        "SELECT conversation_id, consumed_at, request_sha256 FROM receipt_challenges WHERE nonce = ?1",
        [nonce],
        |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, String>(2)?,
            ))
        },
    )
    .optional()
    .map_err(Into::into)
}

fn receipt_id_seen(conn: &Connection, receipt_id: &str) -> CoreResult<bool> {
    let seen: bool = conn.query_row(
        "SELECT EXISTS (SELECT 1 FROM receipt_ids_seen WHERE receipt_id = ?1)",
        [receipt_id],
        |r| r.get(0),
    )?;
    Ok(seen)
}

/// Freshness / skew on BOTH timestamps (Architect fix 4). `requested`/`completed` are
/// the receipt's ms-integer strings (already validated numeric during decode).
fn check_freshness(
    requested: &str,
    completed: &str,
    now_ms: u64,
    fw: FreshnessWindow,
) -> Result<(), String> {
    let requested: u64 = requested
        .parse()
        .map_err(|_| "requested_at is not a numeric timestamp".to_string())?;
    let completed: u64 = completed
        .parse()
        .map_err(|_| "completed_at is not a numeric timestamp".to_string())?;

    if requested > completed {
        return Err("requested_at is after completed_at".to_string());
    }
    let future_limit = now_ms.saturating_add(fw.future_skew_ms);
    if requested > future_limit {
        return Err("requested_at is in the future beyond the skew window".to_string());
    }
    if completed > future_limit {
        return Err("completed_at is in the future beyond the skew window".to_string());
    }
    let stale_limit = now_ms.saturating_sub(fw.max_age_ms);
    if requested < stale_limit {
        return Err("requested_at is older than the freshness window".to_string());
    }
    if completed < stale_limit {
        return Err("completed_at is older than the freshness window".to_string());
    }
    Ok(())
}

/// Evidence-row fields for one attempt.
struct AttemptRow<'a> {
    wire_env: &'a str,
    wire_sig: &'a str,
    receipt_id: Option<&'a str>,
    key_id: Option<&'a str>,
    envelope_jcs: Option<&'a [u8]>,
    signature: Option<&'a [u8]>,
    outcome: &'a str,
    error: Option<&'a str>,
    nonce: Option<&'a str>,
    message_id: Option<&'a str>,
    stamp: &'a str,
}

fn insert_attempt(conn: &Connection, row: &AttemptRow) -> CoreResult<String> {
    let attempt_id = id();
    conn.execute(
        "INSERT INTO receipt_verification_attempts
           (id, wire_envelope_jcs_b64, wire_signature_b64, receipt_id, key_id,
            envelope_jcs, signature, outcome, verification_error, nonce, message_id, verified_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
        rusqlite::params![
            attempt_id,
            row.wire_env,
            row.wire_sig,
            row.receipt_id,
            row.key_id,
            row.envelope_jcs,
            row.signature,
            row.outcome,
            row.error,
            row.nonce,
            row.message_id,
            row.stamp,
        ],
    )?;
    Ok(attempt_id)
}

/// Truncate raw wire to a byte cap on a char boundary (b64 is ASCII, but guard
/// against multibyte garbage) so the evidence table cannot be a storage-DoS vector.
fn cap(s: &str, max_bytes: usize) -> String {
    if s.len() <= max_bytes {
        return s.to_string();
    }
    let mut end = max_bytes;
    while end > 0 && !s.is_char_boundary(end) {
        end -= 1;
    }
    s[..end].to_string()
}

/// Run `f` inside a transaction this function **owns**: `BEGIN IMMEDIATE` (write lock
/// taken up front, so two connections cannot interleave a read-then-consume), COMMIT
/// on `Ok`, ROLLBACK on `Err`.
///
/// The public entry point MUST own its transaction — the atomicity contract (a blocked
/// *verdict* commits its evidence; only a real failure rolls back) cannot hold if an
/// outer transaction could later roll the work back. So a nested invocation (the
/// connection is already in a transaction) is **rejected**, not silently degraded.
///
/// A COMMIT that itself fails (e.g. busy, or a commit hook vetoing) triggers an
/// explicit ROLLBACK attempt and returns the error.
fn in_immediate_tx<T>(
    conn: &Connection,
    f: impl FnOnce(&Connection) -> CoreResult<T>,
) -> CoreResult<T> {
    if !conn.is_autocommit() {
        return Err(CoreError::Invalid {
            field: "connection",
            value: "verify_and_record_receipt must own its transaction; it was called \
                    inside an open transaction"
                .to_string(),
        });
    }
    conn.execute_batch("BEGIN IMMEDIATE;")?;
    match f(conn) {
        Ok(v) => match conn.execute_batch("COMMIT;") {
            Ok(()) => Ok(v),
            Err(e) => {
                // COMMIT failed — make the rollback explicit rather than leaving the
                // transaction state to chance, and surface the error.
                let _ = conn.execute_batch("ROLLBACK;");
                Err(e.into())
            }
        },
        Err(e) => {
            let _ = conn.execute_batch("ROLLBACK;");
            Err(e)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*; // brings the module's URL_SAFE_NO_PAD / Engine / BTreeMap into scope
    use crate::receipt::{sha256_hex, IssuedRequest, TrustClass};
    use ed25519_dalek::{Signer as _, SigningKey};

    const OUTPUT: &[u8] = b"the exact governed reply bytes";

    fn db() -> Connection {
        crate::db::open_in_memory().unwrap()
    }

    fn hx(n: u8) -> String {
        std::iter::repeat_n(format!("{n:02x}"), 32).collect()
    }

    /// A single governed turn's fixture: owns every string so `Expected` can borrow
    /// it, and holds the test signer. Timestamps are set fresh relative to `now`.
    struct Fx {
        nonce: String,
        requested: String,
        completed: String,
        system: String,
        history: String,
        generation: String,
        bundle: String,
        containment: String,
        key: SigningKey,
        pk: [u8; 32],
    }

    impl Fx {
        fn new(now: u64, nonce: &str) -> Self {
            let key = SigningKey::from_bytes(&[7u8; 32]);
            let pk = key.verifying_key().to_bytes();
            Fx {
                nonce: nonce.to_string(),
                requested: (now - 2_000).to_string(),
                completed: (now - 1_000).to_string(),
                system: hx(0x55),
                history: hx(0x66),
                generation: hx(0x44),
                bundle: hx(0x22),
                containment: hx(0x33),
                key,
                pk,
            }
        }

        fn request_sha256(&self) -> String {
            receipt::request_envelope_sha256(
                "ws-1",
                "install-1",
                &self.nonce,
                &self.system,
                &self.history,
                &self.generation,
                &self.requested,
            )
        }

        /// A fully-valid receipt field map. `receipt_id` and timestamps are given so
        /// tests can vary them.
        fn fields(&self, receipt_id: &str) -> BTreeMap<String, String> {
            let mut m = BTreeMap::new();
            m.insert("protocol".into(), "brops.receipt.v1".into());
            m.insert("receipt_id".into(), receipt_id.to_string());
            m.insert("key_id".into(), "key-dev-1".into());
            m.insert("workspace_id".into(), "ws-1".into());
            m.insert("install_id".into(), "install-1".into());
            m.insert("request_nonce".into(), self.nonce.clone());
            m.insert("request_sha256".into(), self.request_sha256());
            m.insert("decision".into(), "completed".into());
            m.insert("policy_id".into(), "pol-1".into());
            m.insert("policy_version".into(), "1".into());
            m.insert("policy_bundle_sha256".into(), self.bundle.clone());
            m.insert("containment_evidence_sha256".into(), self.containment.clone());
            m.insert("generation_config_sha256".into(), self.generation.clone());
            m.insert("system_sha256".into(), self.system.clone());
            m.insert("history_sha256".into(), self.history.clone());
            m.insert("output_sha256".into(), sha256_hex(OUTPUT));
            m.insert("executor_id".into(), "exec-1".into());
            m.insert("builder_id".into(), "build-1".into());
            m.insert("supervisor_id".into(), "sup-1".into());
            m.insert("requested_at".into(), self.requested.clone());
            m.insert("completed_at".into(), self.completed.clone());
            m
        }

        /// Sign a field map into the wire form (env_b64, sig_b64).
        fn wire_of(&self, m: &BTreeMap<String, String>) -> (String, String) {
            let bytes = serde_json::to_vec(m).unwrap();
            let sig = self.key.sign(&bytes);
            (
                URL_SAFE_NO_PAD.encode(&bytes),
                URL_SAFE_NO_PAD.encode(sig.to_bytes()),
            )
        }

        fn issued(&self) -> IssuedRequest<'_> {
            IssuedRequest {
                workspace_id: "ws-1",
                install_id: "install-1",
                request_nonce: &self.nonce,
                system_sha256: &self.system,
                history_sha256: &self.history,
                generation_config_sha256: &self.generation,
                requested_at: &self.requested,
            }
        }

        fn expected(&self) -> Expected<'_> {
            Expected {
                request: self.issued(),
                supervisor_id: "sup-1",
                policy_id: "pol-1",
                policy_version: "1",
                policy_bundle_sha256: &self.bundle,
                containment_evidence_sha256: &self.containment,
                allowed_executors: &["exec-1"],
                allowed_builders: &["build-1"],
            }
        }

        fn key_for(&self, trust: TrustClass) -> ResolvedManifestKey<'_> {
            ResolvedManifestKey::for_test("key-dev-1", &self.pk, trust)
        }
    }

    /// Create a conversation + issue the matching challenge; return the conv id.
    fn seed_turn(conn: &Connection, fx: &Fx, now: u64) -> String {
        let conv = crate::repo::chat::create_conversation(conn, "direct", "governed").unwrap();
        issue_challenge(conn, &conv.id, &fx.issued(), now).unwrap();
        conv.id
    }

    fn turn<'a>(
        fx: &'a Fx,
        env: &'a str,
        sig: &'a str,
        now: u64,
        trust: TrustClass,
    ) -> GovernedTurn<'a> {
        GovernedTurn {
            wire: ReceiptWire { envelope_jcs_b64: env, signature_b64: sig },
            resolved_key: fx.key_for(trust),
            expected: fx.expected(),
            output: OUTPUT,
            now_ms: now,
            freshness: FreshnessWindow::DEFAULT,
        }
    }

    fn count(conn: &Connection, sql: &str) -> i64 {
        conn.query_row(sql, [], |r| r.get(0)).unwrap()
    }

    // ---- happy path --------------------------------------------------------

    #[test]
    fn accepted_receipt_persists_message_attempt_and_ledger_atomically() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        seed_turn(&conn, &fx, now);
        let (env, sig) = fx.wire_of(&fx.fields("receipt-1"));

        let out = verify_and_record_receipt(&conn, &turn(&fx, &env, &sig, now, TrustClass::Development)).unwrap();

        let (message_id, attempt_id) = match out {
            ReceiptOutcome::DevelopmentUntrusted { message_id, attempt_id } => (message_id, attempt_id),
            other => panic!("expected DevelopmentUntrusted, got {other:?}"),
        };
        // Message persisted as an agent message with the exact output bytes.
        let body: String = conn
            .query_row("SELECT body FROM messages WHERE id = ?1", [&message_id], |r| r.get(0))
            .unwrap();
        assert_eq!(body.as_bytes(), OUTPUT);
        // Attempt row is development_untrusted and links the message.
        let (outcome, linked): (String, String) = conn
            .query_row(
                "SELECT outcome, message_id FROM receipt_verification_attempts WHERE id = ?1",
                [&attempt_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(outcome, "development_untrusted");
        assert_eq!(linked, message_id);
        // Ledger recorded the receipt_id; nonce consumed.
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_ids_seen WHERE receipt_id = 'receipt-1'"), 1);
        let consumed: Option<String> = conn
            .query_row("SELECT consumed_at FROM receipt_challenges WHERE nonce = 'nonce-A'", [], |r| r.get(0))
            .unwrap();
        assert!(consumed.is_some(), "nonce must be consumed on accept");
        // The stored envelope_jcs is exactly the signed canonical bytes.
        let stored: Vec<u8> = conn
            .query_row("SELECT envelope_jcs FROM receipt_verification_attempts WHERE id = ?1", [&attempt_id], |r| r.get(0))
            .unwrap();
        assert_eq!(stored, serde_json::to_vec(&fx.fields("receipt-1")).unwrap());
    }

    // ---- replayed nonce ----------------------------------------------------

    #[test]
    fn replayed_nonce_is_blocked_without_a_second_message_or_consume() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        seed_turn(&conn, &fx, now);
        let (env, sig) = fx.wire_of(&fx.fields("receipt-1"));

        // First call accepts.
        verify_and_record_receipt(&conn, &turn(&fx, &env, &sig, now, TrustClass::Development)).unwrap();
        // Second call with a *fresh* receipt_id but the SAME (now-consumed) challenge.
        let (env2, sig2) = fx.wire_of(&fx.fields("receipt-2"));
        let out = verify_and_record_receipt(&conn, &turn(&fx, &env2, &sig2, now, TrustClass::Development)).unwrap();

        assert!(matches!(out, ReceiptOutcome::Blocked { .. }), "replay must block: {out:?}");
        // Exactly one message, one accepted attempt; the replay left blocked evidence.
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 1);
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_verification_attempts WHERE outcome = 'development_untrusted'"), 1);
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_verification_attempts WHERE outcome = 'blocked'"), 1);
    }

    // ---- duplicate receipt_id ---------------------------------------------

    #[test]
    fn duplicate_receipt_id_is_blocked_no_message_no_ledger_dup() {
        let conn = db();
        let now = 1_000_000u64;
        // Turn 1 accepts receipt-1.
        let fx1 = Fx::new(now, "nonce-A");
        seed_turn(&conn, &fx1, now);
        let (e1, s1) = fx1.wire_of(&fx1.fields("receipt-1"));
        verify_and_record_receipt(&conn, &turn(&fx1, &e1, &s1, now, TrustClass::Development)).unwrap();

        // Turn 2: different (valid) challenge, but reuses receipt-1.
        let fx2 = Fx::new(now, "nonce-B");
        seed_turn(&conn, &fx2, now);
        let (e2, s2) = fx2.wire_of(&fx2.fields("receipt-1"));
        let out = verify_and_record_receipt(&conn, &turn(&fx2, &e2, &s2, now, TrustClass::Development)).unwrap();

        assert!(matches!(out, ReceiptOutcome::Blocked { .. }), "dup receipt_id must block: {out:?}");
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 1);
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_ids_seen"), 1);
        // The second challenge is still consumed (one shot spent even though blocked).
        let consumed: Option<String> = conn
            .query_row("SELECT consumed_at FROM receipt_challenges WHERE nonce = 'nonce-B'", [], |r| r.get(0))
            .unwrap();
        assert!(consumed.is_some());
    }

    // ---- blocked never persists a message ---------------------------------

    #[test]
    fn bad_signature_blocks_and_never_writes_a_message() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        seed_turn(&conn, &fx, now);
        let (env, _sig) = fx.wire_of(&fx.fields("receipt-1"));
        // A syntactically-valid but wrong signature (sign different bytes).
        let bad = fx.key.sign(b"not the envelope");
        let bad_sig = URL_SAFE_NO_PAD.encode(bad.to_bytes());

        let out = verify_and_record_receipt(&conn, &turn(&fx, &env, &bad_sig, now, TrustClass::Development)).unwrap();

        let attempt_id = match out {
            ReceiptOutcome::Blocked { attempt_id, .. } => attempt_id,
            other => panic!("expected Blocked, got {other:?}"),
        };
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 0);
        let (outcome, msg): (String, Option<String>) = conn
            .query_row(
                "SELECT outcome, message_id FROM receipt_verification_attempts WHERE id = ?1",
                [&attempt_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(outcome, "blocked");
        assert!(msg.is_none(), "blocked attempt must not link a message");
        // Blocker 2: a bad-signature failure got past strict-parse, so the exact
        // canonical envelope bytes + decoded signature + receipt_id are RETAINED as
        // re-verifiable evidence (not discarded).
        let (env_present, sig_present, rid): (bool, bool, Option<String>) = conn
            .query_row(
                "SELECT envelope_jcs IS NOT NULL, signature IS NOT NULL, receipt_id
                 FROM receipt_verification_attempts WHERE id = ?1",
                [&attempt_id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert!(env_present, "decoded envelope evidence must be retained on bad-sig");
        assert!(sig_present, "decoded signature evidence must be retained on bad-sig");
        assert_eq!(rid.as_deref(), Some("receipt-1"));
        // And the stored envelope bytes are exactly the signed canonical bytes.
        let stored: Vec<u8> = conn
            .query_row("SELECT envelope_jcs FROM receipt_verification_attempts WHERE id = ?1", [&attempt_id], |r| r.get(0))
            .unwrap();
        assert_eq!(stored, serde_json::to_vec(&fx.fields("receipt-1")).unwrap());
    }

    #[test]
    fn production_trust_class_is_blocked_in_wave_3a() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        seed_turn(&conn, &fx, now);
        let (env, sig) = fx.wire_of(&fx.fields("receipt-1"));

        // A perfectly valid receipt under a PRODUCTION key still blocks in 3a.
        let out = verify_and_record_receipt(&conn, &turn(&fx, &env, &sig, now, TrustClass::Production)).unwrap();

        assert!(matches!(out, ReceiptOutcome::Blocked { .. }), "3a never renders production 'Verified': {out:?}");
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 0);
        // But the nonce is still consumed (one shot) and evidence is recorded.
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_verification_attempts WHERE outcome = 'blocked'"), 1);
    }

    // ---- freshness / skew --------------------------------------------------

    #[test]
    fn stale_and_future_receipts_are_blocked() {
        let conn = db();
        let now = 1_000_000u64;

        // Stale: completed_at far older than max_age.
        let fx = Fx::new(now, "nonce-stale");
        let conv = crate::repo::chat::create_conversation(&conn, "direct", "c").unwrap();
        issue_challenge(&conn, &conv.id, &fx.issued(), now).unwrap();
        let (env, sig) = fx.wire_of(&fx.fields("receipt-stale"));
        // Move "now" forward well beyond max_age (300s) so the receipt is stale.
        let later = now + 10_000_000;
        let mut t = turn(&fx, &env, &sig, later, TrustClass::Development);
        // But re-issue the challenge under the later look-up? nonce lookup is by value,
        // already issued above; freshness uses t.now_ms = later.
        t.now_ms = later;
        let out = verify_and_record_receipt(&conn, &t).unwrap();
        assert!(matches!(out, ReceiptOutcome::Blocked { .. }), "stale must block: {out:?}");
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 0);

        // Future: requested/completed ahead of now beyond the skew window.
        let now2 = 5_000_000u64;
        let fut = Fx::new(now2 + 10_000_000, "nonce-future"); // timestamps far ahead of now2
        let conv2 = crate::repo::chat::create_conversation(&conn, "direct", "c2").unwrap();
        issue_challenge(&conn, &conv2.id, &fut.issued(), now2).unwrap();
        let (e2, s2) = fut.wire_of(&fut.fields("receipt-future"));
        let out2 = verify_and_record_receipt(&conn, &turn(&fut, &e2, &s2, now2, TrustClass::Development)).unwrap();
        assert!(matches!(out2, ReceiptOutcome::Blocked { .. }), "future must block: {out2:?}");
    }

    // ---- missing challenge -------------------------------------------------

    #[test]
    fn missing_challenge_blocks_and_consumes_nothing() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-never-issued");
        // No seed_turn: the challenge was never issued.
        let (env, sig) = fx.wire_of(&fx.fields("receipt-1"));
        let out = verify_and_record_receipt(&conn, &turn(&fx, &env, &sig, now, TrustClass::Development)).unwrap();
        assert!(matches!(out, ReceiptOutcome::Blocked { .. }), "missing challenge must block: {out:?}");
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 0);
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_challenges"), 0);
    }

    // ---- pre-decode (malformed) evidence + wire cap ------------------------

    #[test]
    fn malformed_wire_is_blocked_with_capped_evidence_and_consumes_the_nonce() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        seed_turn(&conn, &fx, now);

        // Oversized, non-base64 garbage well beyond the protocol cap.
        let garbage = "!".repeat(MAX_WIRE_ENVELOPE_B64 + 5_000);
        let out = verify_and_record_receipt(&conn, &turn(&fx, &garbage, "sig", now, TrustClass::Development)).unwrap();

        let attempt_id = match out {
            ReceiptOutcome::Blocked { attempt_id, .. } => attempt_id,
            other => panic!("expected Blocked, got {other:?}"),
        };
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 0);
        // Decoded columns are NULL (never decoded); wire evidence stored but CAPPED.
        let (env_null, decoded_null, wire_len): (bool, bool, i64) = conn
            .query_row(
                "SELECT envelope_jcs IS NULL, signature IS NULL, LENGTH(wire_envelope_jcs_b64)
                 FROM receipt_verification_attempts WHERE id = ?1",
                [&attempt_id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert!(env_null && decoded_null);
        assert!(wire_len as usize <= MAX_WIRE_ENVELOPE_B64, "wire evidence must be capped");
        // A valid + unconsumed challenge is consumed even though the receipt blocked.
        let consumed: Option<String> = conn
            .query_row("SELECT consumed_at FROM receipt_challenges WHERE nonce = 'nonce-A'", [], |r| r.get(0))
            .unwrap();
        assert!(consumed.is_some());
    }

    // ---- crash / real-error atomicity --------------------------------------

    #[test]
    fn a_real_error_mid_transaction_rolls_back_everything() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        // A real, valid challenge (so the nonce IS consumed inside the tx)...
        seed_turn(&conn, &fx, now);
        // ...then inject a deterministic failure at the accepted-branch message insert,
        // AFTER the nonce consume, so we can prove the whole tx rolls back. The trigger
        // is test-only and committed before the verify tx opens.
        conn.execute_batch(
            "CREATE TRIGGER fail_message_insert BEFORE INSERT ON messages
             BEGIN SELECT RAISE(ABORT, 'injected mid-transaction failure'); END;",
        )
        .unwrap();
        let (env, sig) = fx.wire_of(&fx.fields("receipt-1"));

        let res = verify_and_record_receipt(&conn, &turn(&fx, &env, &sig, now, TrustClass::Development));
        assert!(res.is_err(), "a real internal failure must return Err, not a verdict");

        // Full rollback: nonce NOT consumed, no attempt, no message, no ledger.
        let consumed: Option<String> = conn
            .query_row("SELECT consumed_at FROM receipt_challenges WHERE nonce = 'nonce-A'", [], |r| r.get(0))
            .unwrap();
        assert!(consumed.is_none(), "nonce consume must roll back with the failed tx");
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_verification_attempts"), 0);
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 0);
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_ids_seen"), 0);
    }

    // ---- blocker 1: challenge bound to the exact request envelope ---------

    #[test]
    fn challenge_bound_to_a_different_request_envelope_is_blocked() {
        let conn = db();
        let now = 1_000_000u64;
        // Two turns sharing the SAME nonce but a different request envelope (system
        // hash) — so their request_sha256 differ. The challenge is issued from A's
        // IssuedRequest; verification runs against B's receipt+Expected. Because
        // issue_challenge derives nonce AND hash from one IssuedRequest, this mismatch
        // can only arise from genuinely different envelopes, not a split-authority bug.
        let fx_a = Fx::new(now, "nonce-A");
        let mut fx_b = Fx::new(now, "nonce-A");
        fx_b.system = hx(0x77); // changes B's request_sha256 and its receipt/Expected
        assert_ne!(fx_a.request_sha256(), fx_b.request_sha256());

        let conv = crate::repo::chat::create_conversation(&conn, "direct", "c").unwrap();
        issue_challenge(&conn, &conv.id, &fx_a.issued(), now).unwrap();

        // B's receipt is internally valid (binds to B's Expected), but the durable
        // challenge was issued for A's request envelope -> blocked.
        let (env, sig) = fx_b.wire_of(&fx_b.fields("receipt-1"));
        let out = verify_and_record_receipt(&conn, &turn(&fx_b, &env, &sig, now, TrustClass::Development)).unwrap();
        assert!(matches!(out, ReceiptOutcome::Blocked { .. }), "challenge/request-envelope mismatch must block: {out:?}");
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 0);
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_ids_seen"), 0, "no ledger insert on a blocked mismatch");
        // The challenge is still consumed (one shot spent).
        let consumed: Option<String> = conn
            .query_row("SELECT consumed_at FROM receipt_challenges WHERE nonce = 'nonce-A'", [], |r| r.get(0))
            .unwrap();
        assert!(consumed.is_some());
    }

    // ---- blocker 2: accepted evidence stays fully re-verifiable -----------

    #[test]
    fn conversation_deletion_is_refused_when_governed_evidence_exists() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        let conv_id = seed_turn(&conn, &fx, now);
        let (env, sig) = fx.wire_of(&fx.fields("receipt-1"));
        let out = verify_and_record_receipt(&conn, &turn(&fx, &env, &sig, now, TrustClass::Development)).unwrap();
        let (message_id, attempt_id) = match out {
            ReceiptOutcome::DevelopmentUntrusted { message_id, attempt_id } => (message_id, attempt_id),
            other => panic!("expected DevelopmentUntrusted, got {other:?}"),
        };

        // Deleting the conversation would strand the accepted attempt from the message
        // holding its exact output bytes; ON DELETE RESTRICT REFUSES it, so the
        // evidence stays fully re-verifiable (output_sha256 can still be recomputed
        // from messages.body).
        let res = crate::repo::chat::delete_conversation(&conn, &conv_id);
        assert!(res.is_err(), "deleting a conversation with governed evidence must be refused");

        // Everything is intact: the output message, the attempt link, the ledger.
        let body: String = conn
            .query_row("SELECT body FROM messages WHERE id = ?1", [&message_id], |r| r.get(0))
            .unwrap();
        assert_eq!(body.as_bytes(), OUTPUT, "exact output bytes remain re-hashable");
        let (outcome, linked): (String, String) = conn
            .query_row(
                "SELECT outcome, message_id FROM receipt_verification_attempts WHERE id = ?1",
                [&attempt_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(outcome, "development_untrusted");
        assert_eq!(linked, message_id, "accepted attempt still links its output message");
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_ids_seen WHERE receipt_id = 'receipt-1'"), 1);
    }

    // ---- blocker 4: transaction ownership --------------------------------

    #[test]
    fn nested_transaction_is_rejected() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        seed_turn(&conn, &fx, now);
        let (env, sig) = fx.wire_of(&fx.fields("receipt-1"));

        // Open an OUTER transaction, then call the entry point: it must refuse rather
        // than run without owning its own BEGIN IMMEDIATE (where an outer rollback
        // could erase committed-by-contract evidence).
        conn.execute_batch("BEGIN;").unwrap();
        let res = verify_and_record_receipt(&conn, &turn(&fx, &env, &sig, now, TrustClass::Development));
        assert!(res.is_err(), "a nested invocation must be rejected, not silently degraded");
        conn.execute_batch("ROLLBACK;").unwrap();

        // Nothing was written; the nonce is untouched.
        let consumed: Option<String> = conn
            .query_row("SELECT consumed_at FROM receipt_challenges WHERE nonce = 'nonce-A'", [], |r| r.get(0))
            .unwrap();
        assert!(consumed.is_none());
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_verification_attempts"), 0);
    }

    #[test]
    fn concurrent_verifications_of_one_nonce_accept_exactly_once() {
        use std::sync::Barrier;

        // A real file-backed DB and two threads that hit verification SIMULTANEOUSLY
        // (a Barrier releases both at once), so two BEGIN IMMEDIATE writers genuinely
        // contend — not a sequential two-connection stand-in.
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("race.sqlite").to_str().unwrap().to_string();

        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        // Seed the shared DB (conversation + one challenge), then drop the connection.
        {
            let seed = crate::db::open(&path).unwrap();
            let conv = crate::repo::chat::create_conversation(&seed, "direct", "c").unwrap();
            issue_challenge(&seed, &conv.id, &fx.issued(), now).unwrap();
        }

        // Two distinct receipts for the SAME nonce.
        let (env1, sig1) = fx.wire_of(&fx.fields("receipt-1"));
        let (env2, sig2) = fx.wire_of(&fx.fields("receipt-2"));
        let t1 = turn(&fx, &env1, &sig1, now, TrustClass::Development);
        let t2 = turn(&fx, &env2, &sig2, now, TrustClass::Development);

        let barrier = Barrier::new(2);
        let (r1, r2) = std::thread::scope(|s| {
            let h1 = s.spawn(|| {
                let c = crate::db::open(&path).unwrap();
                barrier.wait();
                verify_and_record_receipt(&c, &t1)
            });
            let h2 = s.spawn(|| {
                let c = crate::db::open(&path).unwrap();
                barrier.wait();
                verify_and_record_receipt(&c, &t2)
            });
            (h1.join().unwrap(), h2.join().unwrap())
        });

        // Neither lost its forensic attempt to SQLITE_BUSY: both returned a *verdict*,
        // not a DB error (busy_timeout serializes the two BEGIN IMMEDIATE writers).
        let r1 = r1.expect("thread 1 must return a verdict, not a DB error");
        let r2 = r2.expect("thread 2 must return a verdict, not a DB error");
        let accepts = [&r1, &r2]
            .iter()
            .filter(|o| matches!(o, ReceiptOutcome::DevelopmentUntrusted { .. }))
            .count();
        let blocks = [&r1, &r2]
            .iter()
            .filter(|o| matches!(o, ReceiptOutcome::Blocked { .. }))
            .count();
        assert_eq!(accepts, 1, "exactly one concurrent accept: {r1:?} {r2:?}");
        assert_eq!(blocks, 1, "exactly one concurrent block: {r1:?} {r2:?}");

        // Durable state: one message, one ledger row, and BOTH attempts recorded
        // (accepted + blocked) — no forensic attempt dropped.
        let check = crate::db::open(&path).unwrap();
        assert_eq!(count(&check, "SELECT COUNT(*) FROM messages"), 1);
        assert_eq!(count(&check, "SELECT COUNT(*) FROM receipt_ids_seen"), 1);
        assert_eq!(count(&check, "SELECT COUNT(*) FROM receipt_verification_attempts"), 2, "both forensic attempts recorded");
        assert_eq!(count(&check, "SELECT COUNT(*) FROM receipt_verification_attempts WHERE outcome = 'development_untrusted'"), 1);
        assert_eq!(count(&check, "SELECT COUNT(*) FROM receipt_verification_attempts WHERE outcome = 'blocked'"), 1);
    }

    #[test]
    fn commit_failure_rolls_back_and_errors() {
        let conn = db();
        let now = 1_000_000u64;
        let fx = Fx::new(now, "nonce-A");
        seed_turn(&conn, &fx, now);
        let (env, sig) = fx.wire_of(&fx.fields("receipt-1"));

        // A commit hook returning true converts the COMMIT into a failure.
        conn.commit_hook(Some(|| true));
        let res = verify_and_record_receipt(&conn, &turn(&fx, &env, &sig, now, TrustClass::Development));
        conn.commit_hook(None::<fn() -> bool>); // clear it before assertions/cleanup

        assert!(res.is_err(), "a failed COMMIT must surface as Err, not a verdict");
        // The explicit rollback left nothing behind.
        let consumed: Option<String> = conn
            .query_row("SELECT consumed_at FROM receipt_challenges WHERE nonce = 'nonce-A'", [], |r| r.get(0))
            .unwrap();
        assert!(consumed.is_none(), "commit-failure rollback must undo the nonce consume");
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM receipt_verification_attempts"), 0);
        assert_eq!(count(&conn, "SELECT COUNT(*) FROM messages"), 0);
    }
}
