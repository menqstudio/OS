//! Wave 3b-1B — broker-owned committed governed-message store (implements the design-GREEN rev-30 §4.10(g)
//! P0 delivery invariant: the committed `message.body` is the exact accepted-output bytes, `message_id/
//! body/trust_state` equal the row the broker verification transaction committed, an in-transaction
//! re-read that disagrees FAILS CLOSED (`commit_readback_mismatch`), and only the broker writes a
//! `trusted_verified` row).
//!
//! This module is the BROKER-side persistence op only. The renderer never holds a handle to this DB; the
//! `trusted_verified` trust state is enforced by a table CHECK constraint (no other value is representable)
//! and set ONLY here, so no renderer/generic-chat write path can mint or mutate a verified message.

use rusqlite::{params, Connection};
use sha2::{Digest, Sha256};

use crate::governed_turn_ipc::{CommittedMessage, TurnReason, TRUSTED_VERIFIED};

/// Lowercase-hex SHA-256 of `bytes` (matches the receipt/envelope hashing convention).
pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    let d = h.finalize();
    let mut s = String::with_capacity(64);
    for b in d {
        use std::fmt::Write as _;
        let _ = write!(s, "{:02x}", b);
    }
    s
}

/// Create the broker committed-message table. `trust_state` is pinned by a CHECK constraint to the single
/// value `trusted_verified` — the DB itself refuses to store any other trust state.
pub fn create_schema(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS governed_messages (
            message_id     TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            broker_turn_id TEXT NOT NULL,
            author         TEXT NOT NULL,
            body           TEXT NOT NULL,
            body_sha256    TEXT NOT NULL,
            created_at_ms  INTEGER NOT NULL,
            trust_state    TEXT NOT NULL CHECK (trust_state = 'trusted_verified')
        );",
    )
}

/// What the broker holds after verification succeeds: the accepted output whose byte-length AND SHA-256
/// already matched the signed envelope (§4.7/§6.1). `accepted_body` is the exact strict-UTF8 bytes.
pub struct AcceptedOutput {
    pub broker_turn_id: String,
    pub message_id: String,
    pub conversation_id: String,
    pub author: String,
    pub accepted_body: String,
    /// The SHA-256 the signed envelope committed to (lowercase hex).
    pub envelope_body_sha256: String,
    pub created_at_ms: i64,
}

/// Verify a committed-row re-read against the accepted output (rev-30 P0 commit-readback invariant). Any
/// disagreement in body, hash, or trust state ⇒ `CommitReadbackMismatch`. Pure — unit-testable in isolation.
pub fn verify_readback(
    readback_body: &str,
    readback_sha256: &str,
    readback_trust_state: &str,
    accepted_body: &str,
    envelope_body_sha256: &str,
) -> Result<(), TurnReason> {
    let ok = readback_body == accepted_body
        && readback_sha256 == envelope_body_sha256
        && sha256_hex(readback_body.as_bytes()) == envelope_body_sha256
        && readback_trust_state == TRUSTED_VERIFIED;
    if ok {
        Ok(())
    } else {
        Err(TurnReason::CommitReadbackMismatch)
    }
}

/// Persist the verified accepted output as the committed `trusted_verified` message, then **re-read the row
/// in the same connection** and fail closed on ANY mismatch (rev-30 P0). Returns the exact broker-produced
/// immutable projection to hand to the renderer, or a `TurnReason` (never a partial/committed frame on
/// failure). The pre-persist gate also rejects an accepted body whose recomputed SHA-256 does not equal the
/// envelope's (defense in depth — the caller should already have verified this).
pub fn persist_committed(
    conn: &Connection,
    accepted: &AcceptedOutput,
) -> Result<CommittedMessage, TurnReason> {
    // Pre-persist: the body bytes must hash to exactly the envelope-committed digest.
    if sha256_hex(accepted.accepted_body.as_bytes()) != accepted.envelope_body_sha256 {
        return Err(TurnReason::CommitReadbackMismatch);
    }
    conn.execute(
        "INSERT INTO governed_messages
            (message_id, conversation_id, broker_turn_id, author, body, body_sha256, created_at_ms, trust_state)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'trusted_verified')",
        params![
            accepted.message_id,
            accepted.conversation_id,
            accepted.broker_turn_id,
            accepted.author,
            accepted.accepted_body,
            accepted.envelope_body_sha256,
            accepted.created_at_ms,
        ],
    )
    .map_err(|_| TurnReason::CommitReadbackMismatch)?;

    // In-tx re-read: the committed row must equal the accepted output, else fail closed.
    let (rb_body, rb_sha, rb_trust, rb_created): (String, String, String, i64) = conn
        .query_row(
            "SELECT body, body_sha256, trust_state, created_at_ms FROM governed_messages WHERE message_id = ?1",
            params![accepted.message_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .map_err(|_| TurnReason::CommitReadbackMismatch)?;

    verify_readback(&rb_body, &rb_sha, &rb_trust, &accepted.accepted_body, &accepted.envelope_body_sha256)?;
    if rb_created != accepted.created_at_ms {
        return Err(TurnReason::CommitReadbackMismatch);
    }

    Ok(CommittedMessage::new(
        accepted.message_id.clone(),
        accepted.author.clone(),
        rb_body, // the exact committed-row body, not the caller's copy
        rb_created,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn accepted(body: &str) -> AcceptedOutput {
        AcceptedOutput {
            broker_turn_id: "bt-1".into(),
            message_id: "m-1".into(),
            conversation_id: "conv-1".into(),
            author: "Bro".into(),
            accepted_body: body.into(),
            envelope_body_sha256: sha256_hex(body.as_bytes()),
            created_at_ms: 1_700_000_000_000,
        }
    }

    #[test]
    fn persist_then_readback_yields_the_committed_projection() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let msg = persist_committed(&conn, &accepted("hello world")).unwrap();
        assert_eq!(msg.message_id, "m-1");
        assert_eq!(msg.body, "hello world");
        assert_eq!(msg.role, crate::governed_turn_ipc::ASSISTANT_ROLE);
        assert_eq!(msg.trust_state, TRUSTED_VERIFIED);
    }

    #[test]
    fn pre_persist_rejects_body_not_matching_envelope_hash() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let mut a = accepted("hello");
        a.envelope_body_sha256 = sha256_hex(b"a DIFFERENT body"); // envelope says something else
        assert_eq!(persist_committed(&conn, &a), Err(TurnReason::CommitReadbackMismatch));
    }

    #[test]
    fn readback_verify_fails_closed_on_any_mismatch() {
        let body = "reply";
        let good = sha256_hex(body.as_bytes());
        // happy path
        assert!(verify_readback(body, &good, TRUSTED_VERIFIED, body, &good).is_ok());
        // tampered body
        assert_eq!(
            verify_readback("TAMPERED", &good, TRUSTED_VERIFIED, body, &good),
            Err(TurnReason::CommitReadbackMismatch)
        );
        // wrong stored hash
        assert_eq!(
            verify_readback(body, "deadbeef", TRUSTED_VERIFIED, body, &good),
            Err(TurnReason::CommitReadbackMismatch)
        );
        // downgraded trust state
        assert_eq!(
            verify_readback(body, &good, "unverified", body, &good),
            Err(TurnReason::CommitReadbackMismatch)
        );
    }

    #[test]
    fn table_check_constraint_refuses_a_non_verified_trust_state() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        // a direct write attempting any other trust state must be refused by the DB itself
        let r = conn.execute(
            "INSERT INTO governed_messages
                (message_id, conversation_id, broker_turn_id, author, body, body_sha256, created_at_ms, trust_state)
             VALUES ('x','c','bt','a','b',?1,1,'forged_verified')",
            params![sha256_hex(b"b")],
        );
        assert!(r.is_err(), "CHECK constraint must reject a non-trusted_verified trust_state");
    }

    #[test]
    fn duplicate_message_id_is_refused() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        persist_committed(&conn, &accepted("one")).unwrap();
        // same message_id again ⇒ PK violation ⇒ mapped to fail-closed
        assert_eq!(persist_committed(&conn, &accepted("one")), Err(TurnReason::CommitReadbackMismatch));
    }
}
