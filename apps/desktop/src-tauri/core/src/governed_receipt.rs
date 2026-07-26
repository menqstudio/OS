//! Desktop verification and atomic persistence for Wave 3b governed receipts.
//!
//! Network/subprocess I/O and output assembly happen before this module is called.
//! This module verifies the immutable signer envelope, supervisor attestation, exact
//! output bytes and transport echoes outside the write transaction, then opens one
//! `BEGIN IMMEDIATE` transaction to re-check the durable manifest snapshot, consume
//! the desktop nonce, enforce global receipt-id uniqueness/freshness, and persist.

use std::collections::BTreeMap;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use ed25519_dalek::{Signature, VerifyingKey};
use rusqlite::{Connection, OptionalExtension};
use serde_json::{Map, Value};

use crate::domain::{CoreError, CoreResult, NewMessage};
use crate::manifest::{
    self, ManifestSnapshot, ManifestTrustClass, ResolvedAttestationKey, ResolvedReceiptKey,
};
use crate::receipt::{sha256_hex, IssuedRequest};
use crate::receipt_store::{bounded_reason, FreshnessWindow, ReceiptOutcome};
use crate::strict_json::{exact_object, lower_hex_64, parse_canonical, string, u64_value};

pub const ENVELOPE_PROTOCOL: &str = "brops.governed-receipt-envelope.v1";
pub const ATTESTATION_PROTOCOL: &str = "brops.run-attestation.v1";
const MAX_ENVELOPE_BYTES: usize = 4096;
const MAX_ATTESTATION_BYTES: usize = 3498;
const MAX_WIRE_ENVELOPE_B64: usize = 2848;
const MAX_WIRE_ATTESTATION_B64: usize = 4664;

const ENVELOPE_FIELDS: &[&str] = &[
    "artifact_type", "key_id", "receipt_id", "run_id", "execution_attempt_id", "task_id",
    "workspace_id", "install_id", "request_nonce", "request_sha256", "record_handle",
    "lease_handle", "execution_receipt_handle", "output_sha256", "output_bytes",
    "challenge_accepted_at_ms", "completed_at_ms", "evidence_final_event_hash",
    "evidence_event_count", "evidence_last_sequence", "evidence_head_sequence",
    "supervisor_attestation_key_id", "attestation_evidence_sha256",
];

const ATTESTATION_FIELDS: &[&str] = &[
    "run_id", "execution_attempt_id", "lease_id", "task_id", "request_nonce", "receipt_id",
    "decision", "workspace_id", "install_id", "supervisor_id", "executor_id", "runner_id",
    "policy_id", "policy_version", "requested_at_ms", "completed_at_ms",
    "challenge_accepted_at_ms", "system_handle", "history_handle", "generation_config_handle",
    "output_handle", "containment_evidence_handle", "policy_bundle_handle", "lease_handle",
    "execution_receipt_handle", "challenge_handle", "challenge_key_id",
    "challenge_registry_handle", "challenge_registry_hash", "challenge_registry_epoch",
    "challenge_registry_root_key_id", "evidence_event_id", "evidence_event_count",
    "evidence_last_sequence", "evidence_head_sequence", "evidence_final_event_hash",
];

fn invalid(value: impl Into<String>) -> CoreError {
    CoreError::Invalid { field: "governed_receipt", value: value.into() }
}

fn decode_canonical_b64(wire: &str, max_wire: usize, max_decoded: usize, field: &str) -> Result<Vec<u8>, String> {
    if wire.len() > max_wire { return Err(format!("`{field}` exceeds its wire cap")); }
    let decoded = URL_SAFE_NO_PAD.decode(wire.as_bytes()).map_err(|_| format!("`{field}` is not base64url"))?;
    if decoded.len() > max_decoded || URL_SAFE_NO_PAD.encode(&decoded) != wire {
        return Err(format!("`{field}` is oversized or non-canonical base64url"));
    }
    Ok(decoded)
}

fn decode_signature(wire: &str, field: &str) -> Result<[u8; 64], String> {
    let decoded = decode_canonical_b64(wire, 86, 64, field)?;
    decoded.try_into().map_err(|_| format!("`{field}` must decode to 64 bytes"))
}

fn verify_signature(bytes: &[u8], signature_wire: &str, public_key: &[u8; 32], field: &str) -> Result<[u8; 64], String> {
    let raw = decode_signature(signature_wire, field)?;
    let key = VerifyingKey::from_bytes(public_key).map_err(|_| format!("`{field}` key is invalid"))?;
    key.verify_strict(bytes, &Signature::from_bytes(&raw))
        .map_err(|_| format!("`{field}` does not verify"))?;
    Ok(raw)
}

fn id<'a>(object: &'a Map<String, Value>, field: &str) -> Result<&'a str, String> {
    string(object, field, 128)
}

fn hex<'a>(object: &'a Map<String, Value>, field: &str) -> Result<&'a str, String> {
    let value = string(object, field, 64)?;
    lower_hex_64(value, field)?;
    Ok(value)
}

fn equal(field: &str, left: &str, right: &str) -> Result<(), String> {
    if left != right { Err(format!("transport/binding mismatch for `{field}`")) } else { Ok(()) }
}

#[derive(Debug, Clone, Copy)]
pub struct GovernedExpected<'a> {
    pub request: IssuedRequest<'a>,
    pub task_id: &'a str,
    pub supervisor_id: &'a str,
}

#[derive(Debug, Clone, Copy)]
pub struct GovernedReceiptWire<'a> {
    pub envelope_jcs_b64: &'a str,
    pub signature_b64: &'a str,
    pub attestation_evidence_jcs_b64: &'a str,
    pub attestation_signature_b64: &'a str,
    pub supervisor_attestation_key_id: &'a str,
}

/// Transport-only values carried by the sidecar result. Every field is compared to
/// signed envelope/attestation authority; none is trusted by itself.
#[derive(Debug, Clone, Copy)]
pub struct GovernedTransportEchoes<'a> {
    pub key_id: &'a str,
    pub receipt_id: &'a str,
    pub run_id: &'a str,
    pub execution_attempt_id: &'a str,
    pub lease_id: &'a str,
    pub task_id: &'a str,
    pub challenge_accepted_at_ms: u64,
    pub challenge_handle: &'a str,
    pub challenge_key_id: &'a str,
    pub challenge_registry_handle: &'a str,
    pub challenge_registry_hash: &'a str,
    pub challenge_registry_epoch: u64,
    pub challenge_registry_root_key_id: &'a str,
    pub lease_handle: &'a str,
    pub execution_receipt_handle: &'a str,
    pub output_sha256: &'a str,
    pub output_bytes: u64,
    pub evidence_event_count: u64,
    pub evidence_last_sequence: u64,
    pub evidence_head_sequence: u64,
    pub evidence_final_event_hash: &'a str,
}

#[derive(Debug, Clone, Copy)]
pub struct GovernedTurn<'a> {
    pub wire: GovernedReceiptWire<'a>,
    pub echoes: GovernedTransportEchoes<'a>,
    pub expected: GovernedExpected<'a>,
    pub output: &'a [u8],
    pub now_ms: u64,
    pub freshness: FreshnessWindow,
}

struct Prepared {
    snapshot: ManifestSnapshot,
    receipt_key: ResolvedReceiptKey,
    _attestation_key: ResolvedAttestationKey,
    envelope_bytes: Vec<u8>,
    envelope_signature: [u8; 64],
    attestation_bytes: Vec<u8>,
    attestation_signature: [u8; 64],
    envelope: BTreeMap<String, Value>,
    attestation: BTreeMap<String, Value>,
    body: String,
}

fn object_to_btree(object: &Map<String, Value>) -> BTreeMap<String, Value> {
    object.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
}

fn prepare_with_snapshot(turn: &GovernedTurn<'_>, snapshot: ManifestSnapshot) -> Result<Prepared, String> {
    let envelope_bytes = decode_canonical_b64(
        turn.wire.envelope_jcs_b64, MAX_WIRE_ENVELOPE_B64, MAX_ENVELOPE_BYTES, "envelope_jcs_b64",
    )?;
    let envelope_value = parse_canonical(&envelope_bytes, MAX_ENVELOPE_BYTES)?;
    let envelope = exact_object(&envelope_value, ENVELOPE_FIELDS, "governed receipt envelope")?;
    if string(envelope, "artifact_type", 64)? != ENVELOPE_PROTOCOL { return Err("wrong envelope artifact_type".to_string()); }
    let key_id = id(envelope, "key_id")?;
    let receipt_key = manifest::resolve_receipt_key(
        &snapshot, key_id, turn.expected.request.workspace_id, turn.expected.request.install_id,
        turn.expected.supervisor_id, turn.now_ms,
    )?;
    equal("key_id", key_id, &receipt_key.key_id)?;
    let envelope_signature = verify_signature(
        &envelope_bytes, turn.wire.signature_b64, &receipt_key.public_key, "signature_b64",
    )?;

    let attestation_bytes = decode_canonical_b64(
        turn.wire.attestation_evidence_jcs_b64, MAX_WIRE_ATTESTATION_B64,
        MAX_ATTESTATION_BYTES, "attestation_evidence_jcs_b64",
    )?;
    let attestation_value = parse_canonical(&attestation_bytes, MAX_ATTESTATION_BYTES)?;
    let attestation = exact_object(&attestation_value, ATTESTATION_FIELDS, "supervisor attestation evidence")?;
    let attestation_key_id = id(envelope, "supervisor_attestation_key_id")?;
    equal("supervisor_attestation_key_id", attestation_key_id, turn.wire.supervisor_attestation_key_id)?;
    let attestation_key = manifest::resolve_attestation_key(
        &snapshot, attestation_key_id, turn.expected.supervisor_id, turn.now_ms,
    )?;
    let attestation_signature = verify_signature(
        &attestation_bytes, turn.wire.attestation_signature_b64,
        &attestation_key.public_key, "attestation_signature_b64",
    )?;
    equal("attestation_evidence_sha256", hex(envelope, "attestation_evidence_sha256")?, &sha256_hex(&attestation_bytes))?;

    // Bind desktop-owned request context and signed envelope authority.
    equal("task_id", id(envelope, "task_id")?, turn.expected.task_id)?;
    equal("workspace_id", id(envelope, "workspace_id")?, turn.expected.request.workspace_id)?;
    equal("install_id", id(envelope, "install_id")?, turn.expected.request.install_id)?;
    equal("request_nonce", id(envelope, "request_nonce")?, turn.expected.request.request_nonce)?;
    equal("request_sha256", hex(envelope, "request_sha256")?, &turn.expected.request.request_sha256())?;
    // record_handle is consumed later (post-verify) via field_str; type-validate it here as a
    // 64-hex store handle so a signed envelope carrying a non-string handle refuses cleanly
    // rather than panicking downstream ("refuse, never panic").
    let _ = hex(envelope, "record_handle")?;

    // The independently supervisor-signed evidence must agree with the envelope.
    if string(attestation, "decision", 32)? != "completed" { return Err("attestation decision is not completed".to_string()); }
    equal("supervisor_id", id(attestation, "supervisor_id")?, turn.expected.supervisor_id)?;
    for field in ["run_id", "execution_attempt_id", "task_id", "request_nonce", "receipt_id",
                  "workspace_id", "install_id", "lease_handle", "execution_receipt_handle",
                  "evidence_final_event_hash"] {
        equal(field, id_or_hex(envelope, field)?, id_or_hex(attestation, field)?)?;
    }
    equal("supervisor_attestation_key_id", attestation_key_id, turn.wire.supervisor_attestation_key_id)?;
    if u64_value(envelope, "challenge_accepted_at_ms")? != u64_value(attestation, "challenge_accepted_at_ms")?
        || u64_value(envelope, "completed_at_ms")? != u64_value(attestation, "completed_at_ms")?
        || u64_value(envelope, "evidence_event_count")? != u64_value(attestation, "evidence_event_count")?
        || u64_value(envelope, "evidence_last_sequence")? != u64_value(attestation, "evidence_last_sequence")?
        || u64_value(envelope, "evidence_head_sequence")? != u64_value(attestation, "evidence_head_sequence")? {
        return Err("envelope/attestation numeric binding mismatch".to_string());
    }

    // Raw output is authoritative only through the signed envelope hash+length.
    let output_bytes = u64_value(envelope, "output_bytes")?;
    if output_bytes > 8 * 1024 * 1024 || output_bytes != turn.output.len() as u64 {
        return Err("output length does not match the signed envelope".to_string());
    }
    equal("output_sha256", hex(envelope, "output_sha256")?, &sha256_hex(turn.output))?;
    equal("output_handle", hex(attestation, "output_handle")?, hex(envelope, "output_sha256")?)?;
    let body = std::str::from_utf8(turn.output).map_err(|_| "output is not valid UTF-8")?.to_string();

    // Every sidecar/supervisor echo is transport-only and must equal signed authority.
    let e = &turn.echoes;
    equal("echo.key_id", e.key_id, key_id)?;
    equal("echo.receipt_id", e.receipt_id, id(envelope, "receipt_id")?)?;
    equal("echo.run_id", e.run_id, id(envelope, "run_id")?)?;
    equal("echo.execution_attempt_id", e.execution_attempt_id, id(envelope, "execution_attempt_id")?)?;
    equal("echo.lease_id", e.lease_id, id(attestation, "lease_id")?)?;
    equal("echo.task_id", e.task_id, id(envelope, "task_id")?)?;
    equal("echo.lease_handle", e.lease_handle, hex(envelope, "lease_handle")?)?;
    equal("echo.execution_receipt_handle", e.execution_receipt_handle, hex(envelope, "execution_receipt_handle")?)?;
    equal("echo.output_sha256", e.output_sha256, hex(envelope, "output_sha256")?)?;
    equal("echo.evidence_final_event_hash", e.evidence_final_event_hash, hex(envelope, "evidence_final_event_hash")?)?;
    equal("echo.challenge_handle", e.challenge_handle, hex(attestation, "challenge_handle")?)?;
    equal("echo.challenge_key_id", e.challenge_key_id, id(attestation, "challenge_key_id")?)?;
    equal("echo.challenge_registry_handle", e.challenge_registry_handle, hex(attestation, "challenge_registry_handle")?)?;
    equal("echo.challenge_registry_hash", e.challenge_registry_hash, hex(attestation, "challenge_registry_hash")?)?;
    equal("echo.challenge_registry_root_key_id", e.challenge_registry_root_key_id, id(attestation, "challenge_registry_root_key_id")?)?;
    if e.challenge_accepted_at_ms != u64_value(envelope, "challenge_accepted_at_ms")?
        || e.challenge_registry_epoch != u64_value(attestation, "challenge_registry_epoch")?
        || e.output_bytes != output_bytes
        || e.evidence_event_count != u64_value(envelope, "evidence_event_count")?
        || e.evidence_last_sequence != u64_value(envelope, "evidence_last_sequence")?
        || e.evidence_head_sequence != u64_value(envelope, "evidence_head_sequence")? {
        return Err("numeric transport echo mismatch".to_string());
    }

    let requested_at = turn.expected.request.requested_at.parse::<u64>().map_err(|_| "requested_at is invalid")?;
    if u64_value(attestation, "requested_at_ms")? != requested_at { return Err("attestation requested_at mismatch".to_string()); }
    check_freshness(
        requested_at, u64_value(envelope, "challenge_accepted_at_ms")?,
        u64_value(envelope, "completed_at_ms")?, turn.now_ms, turn.freshness,
    )?;

    Ok(Prepared {
        snapshot, receipt_key, _attestation_key: attestation_key,
        envelope_bytes, envelope_signature, attestation_bytes, attestation_signature,
        envelope: object_to_btree(envelope), attestation: object_to_btree(attestation), body,
    })
}

fn id_or_hex<'a>(object: &'a Map<String, Value>, field: &str) -> Result<&'a str, String> {
    match field {
        "lease_handle" | "execution_receipt_handle" | "evidence_final_event_hash" => hex(object, field),
        _ => id(object, field),
    }
}

fn check_freshness(requested: u64, accepted: u64, completed: u64, now: u64, fw: FreshnessWindow) -> Result<(), String> {
    if requested > accepted || accepted > completed { return Err("governed timestamp order is invalid".to_string()); }
    let future = now.saturating_add(fw.future_skew_ms);
    let stale = now.saturating_sub(fw.max_age_ms);
    if requested > future || accepted > future || completed > future { return Err("governed timestamp is too far in the future".to_string()); }
    if requested < stale || accepted < stale || completed < stale { return Err("governed timestamp is stale".to_string()); }
    Ok(())
}

fn field<'a>(map: &'a BTreeMap<String, Value>, name: &str) -> &'a Value {
    map.get(name).expect("validated governed receipt field")
}
fn field_str<'a>(map: &'a BTreeMap<String, Value>, name: &str) -> &'a str {
    field(map, name).as_str().expect("validated governed receipt string")
}
fn field_u64(map: &BTreeMap<String, Value>, name: &str) -> u64 {
    field(map, name).as_u64().expect("validated governed receipt integer")
}

fn begin_immediate(conn: &Connection) -> CoreResult<()> {
    if !conn.is_autocommit() { return Err(invalid("governed receipt persistence must own its transaction")); }
    conn.execute_batch("BEGIN IMMEDIATE;")?;
    Ok(())
}

fn insert_attempt(
    conn: &Connection,
    turn: &GovernedTurn<'_>,
    prepared: Option<&Prepared>,
    outcome: &str,
    error: Option<&str>,
    message_id: Option<&str>,
) -> CoreResult<String> {
    let attempt_id = crate::id();
    let wire_env = if turn.wire.envelope_jcs_b64.len() <= MAX_WIRE_ENVELOPE_B64 {
        turn.wire.envelope_jcs_b64.to_string()
    } else { turn.wire.envelope_jcs_b64[..MAX_WIRE_ENVELOPE_B64].to_string() };
    let wire_sig = if turn.wire.signature_b64.len() <= 86 { turn.wire.signature_b64.to_string() }
        else { turn.wire.signature_b64[..86].to_string() };
    let p = prepared;
    conn.execute(
        "INSERT INTO receipt_verification_attempts(\n          id,wire_envelope_jcs_b64,wire_signature_b64,receipt_id,key_id,envelope_jcs,signature,\n          outcome,verification_error,nonce,message_id,verified_at,\n          attestation_evidence_jcs,attestation_signature,supervisor_attestation_key_id,\n          run_id,execution_attempt_id,lease_id,challenge_accepted_at_ms,record_handle,lease_handle,\n          execution_receipt_handle,output_sha256,output_bytes,evidence_final_event_hash,\n          evidence_event_count,evidence_last_sequence,evidence_head_sequence)\n         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,?21,?22,?23,?24,?25,?26,?27,?28)",
        rusqlite::params![
            attempt_id, wire_env, wire_sig,
            p.map(|x| field_str(&x.envelope, "receipt_id")),
            p.map(|x| field_str(&x.envelope, "key_id")),
            p.map(|x| x.envelope_bytes.as_slice()),
            p.map(|x| x.envelope_signature.as_slice()),
            outcome, error, turn.expected.request.request_nonce, message_id, turn.now_ms.to_string(),
            p.map(|x| x.attestation_bytes.as_slice()),
            p.map(|x| x.attestation_signature.as_slice()),
            p.map(|x| field_str(&x.envelope, "supervisor_attestation_key_id")),
            p.map(|x| field_str(&x.envelope, "run_id")),
            p.map(|x| field_str(&x.envelope, "execution_attempt_id")),
            p.map(|x| field_str(&x.attestation, "lease_id")),
            p.map(|x| field_u64(&x.envelope, "challenge_accepted_at_ms")),
            p.map(|x| field_str(&x.envelope, "record_handle")),
            p.map(|x| field_str(&x.envelope, "lease_handle")),
            p.map(|x| field_str(&x.envelope, "execution_receipt_handle")),
            p.map(|x| field_str(&x.envelope, "output_sha256")),
            p.map(|x| field_u64(&x.envelope, "output_bytes")),
            p.map(|x| field_str(&x.envelope, "evidence_final_event_hash")),
            p.map(|x| field_u64(&x.envelope, "evidence_event_count")),
            p.map(|x| field_u64(&x.envelope, "evidence_last_sequence")),
            p.map(|x| field_u64(&x.envelope, "evidence_head_sequence")),
        ],
    )?;
    Ok(attempt_id)
}

fn consume_nonce(conn: &Connection, nonce: &str, stamp: &str) -> CoreResult<Option<(String, String)>> {
    let row: Option<(String, String, Option<String>)> = conn.query_row(
        "SELECT conversation_id,request_sha256,consumed_at FROM receipt_challenges WHERE nonce=?1",
        [nonce], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
    ).optional()?;
    let Some((conversation, request_sha256, consumed_at)) = row else { return Ok(None) };
    if consumed_at.is_some() { return Ok(None); }
    let changed = conn.execute(
        "UPDATE receipt_challenges SET consumed_at=?1 WHERE nonce=?2 AND consumed_at IS NULL",
        rusqlite::params![stamp, nonce],
    )?;
    if changed == 1 { Ok(Some((conversation, request_sha256))) } else { Ok(None) }
}

fn persist_block(conn: &Connection, turn: &GovernedTurn<'_>, prepared: Option<&Prepared>, reason: &str) -> CoreResult<ReceiptOutcome> {
    let reason = bounded_reason(reason);
    begin_immediate(conn)?;
    let result = (|| -> CoreResult<ReceiptOutcome> {
        let _ = consume_nonce(conn, turn.expected.request.request_nonce, &turn.now_ms.to_string())?;
        let attempt_id = insert_attempt(conn, turn, prepared, "blocked", Some(&reason), None)?;
        Ok(ReceiptOutcome::Blocked { attempt_id, error: reason })
    })();
    match result {
        Ok(v) => { conn.execute_batch("COMMIT;")?; Ok(v) }
        Err(e) => { let _ = conn.execute_batch("ROLLBACK;"); Err(e) }
    }
}

pub fn verify_and_record_governed_receipt(conn: &Connection, turn: &GovernedTurn<'_>) -> CoreResult<ReceiptOutcome> {
    let snapshot = match manifest::load_snapshot(conn)? {
        Some(s) => s,
        None => return persist_block(conn, turn, None, "no accepted trusted key manifest"),
    };
    let prepared = match prepare_with_snapshot(turn, snapshot) {
        Ok(v) => v,
        Err(reason) => return persist_block(conn, turn, None, &reason),
    };

    begin_immediate(conn)?;
    let result = (|| -> CoreResult<ReceiptOutcome> {
        manifest::ensure_snapshot_current(conn, &prepared.snapshot)?;
        let stamp = turn.now_ms.to_string();
        let Some((conversation_id, issued_hash)) = consume_nonce(conn, turn.expected.request.request_nonce, &stamp)? else {
            let error = "request_nonce is missing or already consumed (replay)";
            let attempt_id = insert_attempt(conn, turn, Some(&prepared), "blocked", Some(error), None)?;
            return Ok(ReceiptOutcome::Blocked { attempt_id, error: error.to_string() });
        };
        if issued_hash != turn.expected.request.request_sha256() {
            let error = "durable challenge request_sha256 mismatch";
            let attempt_id = insert_attempt(conn, turn, Some(&prepared), "blocked", Some(error), None)?;
            return Ok(ReceiptOutcome::Blocked { attempt_id, error: error.to_string() });
        }
        let receipt_id = field_str(&prepared.envelope, "receipt_id");
        let seen: bool = conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM receipt_ids_seen WHERE receipt_id=?1)", [receipt_id], |r| r.get(0),
        )?;
        if seen {
            let error = "receipt_id already accepted (replay)";
            let attempt_id = insert_attempt(conn, turn, Some(&prepared), "blocked", Some(error), None)?;
            return Ok(ReceiptOutcome::Blocked { attempt_id, error: error.to_string() });
        }
        let outcome = match prepared.receipt_key.trust_class {
            ManifestTrustClass::Production => "trusted_verified",
            ManifestTrustClass::Development => "development_untrusted",
        };
        let message = crate::repo::chat::post_message(conn, NewMessage {
            conversation_id, role: "agent".to_string(), author: "Bro".to_string(),
            body: prepared.body.clone(),
        })?;
        let attempt_id = insert_attempt(conn, turn, Some(&prepared), outcome, None, Some(&message.id))?;
        conn.execute(
            "INSERT INTO receipt_ids_seen(receipt_id,first_seen_at,attempt_id) VALUES(?1,?2,?3)",
            rusqlite::params![receipt_id, stamp, attempt_id],
        )?;
        match prepared.receipt_key.trust_class {
            ManifestTrustClass::Production => Ok(ReceiptOutcome::TrustedVerified { message_id: message.id, attempt_id }),
            ManifestTrustClass::Development => Ok(ReceiptOutcome::DevelopmentUntrusted { message_id: message.id, attempt_id }),
        }
    })();
    match result {
        Ok(v) => { conn.execute_batch("COMMIT;")?; Ok(v) }
        Err(e) => { let _ = conn.execute_batch("ROLLBACK;"); Err(e) }
    }
}
