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

/// The only trust states a committed row may carry — the closed set `TrustState::committed_label`
/// can produce. Kept beside the readback so a schema without the CHECK constraint (an older
/// database, a hand-made table) still cannot smuggle an unresolved state past verification.
const COMMITTABLE_TRUST_STATES: [&str; 2] = [TRUSTED_VERIFIED, "demonstration_custody"];

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

/// Create the broker committed-message table.
///
/// `trust_state` used to be pinned by `CHECK (trust_state = 'trusted_verified')`, so the column
/// could hold exactly one value and every committed row asserted full trust by construction.
/// Nothing computed it: an independent audit found that no production path ever called
/// `production_trust::resolve_trust_state`, so the custody question that module exists to answer
/// was never asked — and the answer was stored regardless.
///
/// The column now records what was actually RESOLVED. `demonstration_custody` is the honest value
/// for a run whose chain completed under a kit or demonstration root: real cryptography, real
/// binding, and custody that proves nothing about who controls the anchor. Storing that as
/// `trusted_verified` was the lie; refusing to store it at all would delete the evidence that the
/// chain ran. The renderer keys its badge off this string, so a demonstration turn renders as what
/// it is. The CHECK stays closed — an unresolved or invented state cannot be written.
///
/// NOTE for an existing database: `CREATE TABLE IF NOT EXISTS` leaves an older table's stricter
/// constraint in place, so a database created before this change rejects a `demonstration_custody`
/// row until it is recreated. Stated rather than silently worked around.
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
            trust_state    TEXT NOT NULL
                CHECK (trust_state IN ('trusted_verified', 'demonstration_custody'))
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
    expected_trust_state: &str,
) -> Result<(), TurnReason> {
    let ok = readback_body == accepted_body
        && readback_sha256 == envelope_body_sha256
        && sha256_hex(readback_body.as_bytes()) == envelope_body_sha256
        // Both halves matter. The equality catches a row that stored something other than what the
        // chain resolved; the membership catches a schema (an older DB without the CHECK) where the
        // caller and the row could agree on a value neither is allowed to use.
        && readback_trust_state == expected_trust_state
        && COMMITTABLE_TRUST_STATES.contains(&readback_trust_state);
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
///
/// `trust_state` is the state the chain actually RESOLVED for this turn, and it is a parameter
/// rather than a constant because that resolution used to not happen at all: every row was written
/// `'trusted_verified'` literally, so the value carried no information and could not be wrong. It
/// now has to be produced by someone who consulted the manifest and its root anchor, and a state
/// that does not warrant storing at all is refused here rather than downgraded silently.
pub fn persist_committed(
    conn: &Connection,
    accepted: &AcceptedOutput,
    trust_state: &crate::production_trust::TrustState,
) -> Result<CommittedMessage, TurnReason> {
    // Pre-persist: the body bytes must hash to exactly the envelope-committed digest.
    if sha256_hex(accepted.accepted_body.as_bytes()) != accepted.envelope_body_sha256 {
        return Err(TurnReason::CommitReadbackMismatch);
    }
    // A turn whose chain did not bind has nothing to commit. `NoTrustedManifest` reaching here is a
    // caller that verified nothing and asked to store it anyway — refuse, do not record a weaker
    // claim, because a row in this table IS the claim that a governed turn produced this body.
    let stored_state = trust_state.committed_label().ok_or(TurnReason::UpstreamBlocked)?;
    // Open ONE explicit transaction so the INSERT, the re-read, and every verification form a single
    // atomic snapshot. `unchecked_transaction` takes `&Connection` and yields a `Transaction` that ROLLS
    // BACK on drop unless `commit()` is called — so any fail-closed return below leaves NO committed row
    // (rev-30 §4.10(g) P0: the trusted_verified row must not durably survive a readback mismatch).
    let tx = conn
        .unchecked_transaction()
        .map_err(|_| TurnReason::CommitReadbackMismatch)?;

    tx.execute(
        "INSERT INTO governed_messages
            (message_id, conversation_id, broker_turn_id, author, body, body_sha256, created_at_ms, trust_state)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        params![
            accepted.message_id,
            accepted.conversation_id,
            accepted.broker_turn_id,
            accepted.author,
            accepted.accepted_body,
            accepted.envelope_body_sha256,
            accepted.created_at_ms,
            stored_state,
        ],
    )
    .map_err(|_| TurnReason::CommitReadbackMismatch)?;

    // In-tx re-read: the just-inserted row must equal the accepted output, else fail closed. Because this
    // read runs inside `tx`, a mismatch return drops `tx` (rollback) and the row never becomes durable.
    let (rb_body, rb_sha, rb_trust, rb_created): (String, String, String, i64) = tx
        .query_row(
            "SELECT body, body_sha256, trust_state, created_at_ms FROM governed_messages WHERE message_id = ?1",
            params![accepted.message_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .map_err(|_| TurnReason::CommitReadbackMismatch)?;

    verify_readback(
        &rb_body,
        &rb_sha,
        &rb_trust,
        &accepted.accepted_body,
        &accepted.envelope_body_sha256,
        stored_state,
    )?;
    if rb_created != accepted.created_at_ms {
        return Err(TurnReason::CommitReadbackMismatch);
    }

    // Only now — after the readback AND the created_at_ms equality both pass — make the row durable.
    tx.commit().map_err(|_| TurnReason::CommitReadbackMismatch)?;

    Ok(CommittedMessage::new(
        accepted.message_id.clone(),
        accepted.author.clone(),
        rb_body, // the exact committed-row body, not the caller's copy
        rb_created,
        rb_trust, // likewise the row's own re-read trust state, not the value we asked it to store
    ))
}

/// What an independent post-commit re-read establishes about a [`CommittedMessage`] projection: it is
/// backed by a durable committed row, and the body it carries hashes to the digest the signed envelope
/// committed to (the row's `body_sha256`, which [`persist_committed`] proved equal to
/// `envelope.output_sha256` before making the row durable).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommittedBinding {
    pub message_id: String,
    /// The envelope-committed body digest as stored in the durable row (lowercase hex).
    pub envelope_body_sha256: String,
}

/// Check that a [`CommittedMessage`] projection is actually backed by the durable committed row it
/// claims, re-reading the row and recomputing the digest here.
///
/// WHY this exists, plainly. A driver that wanted to report whether a turn was "bound" used to read
/// `message.trust_state == TRUSTED_VERIFIED`. That value is a hardcoded constant in
/// `CommittedMessage::new` — it is `trusted_verified` for every projection ever constructed, so the
/// comparison could not fail and the reported boolean was decoration. The falsifiable question a caller
/// holding a projection can still ask is a DELIVERY question: is this projection backed by a durable
/// `trusted_verified` row, and does the body it is about to display hash to that row's
/// envelope-committed digest? Everything below can be false — a rolled-back transaction, a projection
/// for a message that was never committed, a row or a projection altered after the commit, a stored
/// digest that no longer matches its body.
///
/// LIMIT: this re-verifies delivery, not cryptography. The envelope signature and the
/// output-length/digest gates are `governed_verification::verify_and_accept`'s job and are NOT redone
/// here; this only ensures nothing between that acceptance and the caller substituted the bytes.
pub fn verify_committed_binding(
    conn: &Connection,
    message: &CommittedMessage,
) -> Result<CommittedBinding, TurnReason> {
    let row: Option<(String, String, String, String, i64)> = conn
        .query_row(
            "SELECT body, body_sha256, trust_state, author, created_at_ms
               FROM governed_messages WHERE message_id = ?1",
            params![message.message_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
        )
        .ok();
    // No durable row ⇒ the projection is not backed by a commit (rolled back, or never persisted).
    let (body, body_sha256, trust_state, author, created_at_ms) =
        row.ok_or(TurnReason::CommitReadbackMismatch)?;

    if body != message.body {
        return Err(TurnReason::CommitReadbackMismatch);
    }
    // The binding itself: the bytes the caller will report must hash to the digest the envelope
    // committed to. Recomputed here rather than trusted from either side.
    if sha256_hex(message.body.as_bytes()) != body_sha256 {
        return Err(TurnReason::CommitReadbackMismatch);
    }
    // Defence in depth behind the table CHECK constraint: a row reached through a schema that lacks
    // it (an older DB, a hand-made table) must not pass. The set is closed — an unresolved or
    // invented state is refused here even if some other schema let it be written.
    if !COMMITTABLE_TRUST_STATES.contains(&trust_state.as_str()) {
        return Err(TurnReason::CommitReadbackMismatch);
    }
    if author != message.author || created_at_ms != message.created_at_ms {
        return Err(TurnReason::CommitReadbackMismatch);
    }

    Ok(CommittedBinding { message_id: message.message_id.clone(), envelope_body_sha256: body_sha256 })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::production_trust::TrustState;

    fn production() -> TrustState {
        TrustState::Production {
            key_id: "signer-prod".into(),
            key_epoch: 3,
            root_key_id: "root-external".into(),
        }
    }

    fn demonstration() -> TrustState {
        TrustState::DemonstrationCustody {
            key_id: "signer-prod".into(),
            key_epoch: 3,
            root_key_id: "root-kit".into(),
            root_provenance: crate::key_manifest::RootProvenance::KitGenerated,
        }
    }

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
        let msg = persist_committed(&conn, &accepted("hello world"), &production()).unwrap();
        assert_eq!(msg.message_id, "m-1");
        assert_eq!(msg.body, "hello world");
        assert_eq!(msg.role, crate::governed_turn_ipc::ASSISTANT_ROLE);
        assert_eq!(msg.trust_state, TRUSTED_VERIFIED);
    }

    /// The custody gate itself. `trust_state` used to be the literal `'trusted_verified'` in the
    /// INSERT, so this could not be written as a test at all — there was no input to vary. Delete
    /// the `ok_or` in `persist_committed` and this goes red.
    #[test]
    fn a_turn_with_no_resolved_custody_cannot_be_committed() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let unresolved = TrustState::NoTrustedManifest("no anchor in this deployment");
        assert_eq!(
            persist_committed(&conn, &accepted("hello world"), &unresolved),
            Err(TurnReason::UpstreamBlocked)
        );
        // And nothing durable was left behind — a refusal is not a half-commit.
        let rows: i64 = conn
            .query_row("SELECT COUNT(*) FROM governed_messages", [], |r| r.get(0))
            .unwrap();
        assert_eq!(rows, 0, "a refused turn must leave no row");
    }

    /// A demonstration-custody run is a real chain run whose anchor proves nothing about who holds
    /// the root. It commits — the evidence that the chain ran is worth keeping — but it commits
    /// under its own label, and nothing downstream can mistake it for production.
    #[test]
    fn demonstration_custody_commits_under_its_own_label_not_trusted_verified() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let msg = persist_committed(&conn, &accepted("hello world"), &demonstration()).unwrap();
        assert_eq!(msg.trust_state, "demonstration_custody");
        assert_ne!(msg.trust_state, TRUSTED_VERIFIED, "demonstration custody is NOT production trust");
        // The projection is the row, not a hopeful copy of it.
        let stored: String = conn
            .query_row("SELECT trust_state FROM governed_messages WHERE message_id = 'm-1'", [], |r| r.get(0))
            .unwrap();
        assert_eq!(stored, msg.trust_state);
    }

    /// The two states must not be interchangeable at the storage layer either: a row that says one
    /// thing while the chain resolved the other fails the readback. Delete the equality half of
    /// `verify_readback` and this goes red.
    #[test]
    fn readback_rejects_a_row_whose_trust_state_is_not_the_resolved_one() {
        let body = "reply";
        let good = sha256_hex(body.as_bytes());
        // Both values are individually legal; they simply are not the same answer.
        assert_eq!(
            verify_readback(body, &good, "demonstration_custody", body, &good, TRUSTED_VERIFIED),
            Err(TurnReason::CommitReadbackMismatch)
        );
        assert_eq!(
            verify_readback(body, &good, TRUSTED_VERIFIED, body, &good, "demonstration_custody"),
            Err(TurnReason::CommitReadbackMismatch)
        );
    }

    /// `committed_label` is the only door from a resolved state to a stored string, so the closed
    /// set it can produce is what the CHECK constraint and the readback are allowed to accept.
    #[test]
    fn every_committable_label_is_one_a_trust_state_can_actually_produce() {
        assert_eq!(production().committed_label(), Some(TRUSTED_VERIFIED));
        assert_eq!(demonstration().committed_label(), Some("demonstration_custody"));
        assert_eq!(TrustState::NoTrustedManifest("x").committed_label(), None);
        for label in COMMITTABLE_TRUST_STATES {
            assert!(
                [production().committed_label(), demonstration().committed_label()].contains(&Some(label)),
                "{label} is accepted by the readback but no TrustState can produce it"
            );
        }
    }

    #[test]
    fn pre_persist_rejects_body_not_matching_envelope_hash() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let mut a = accepted("hello");
        a.envelope_body_sha256 = sha256_hex(b"a DIFFERENT body"); // envelope says something else
        assert_eq!(
            persist_committed(&conn, &a, &production()),
            Err(TurnReason::CommitReadbackMismatch)
        );
    }

    #[test]
    fn readback_verify_fails_closed_on_any_mismatch() {
        let body = "reply";
        let good = sha256_hex(body.as_bytes());
        // happy path
        assert!(verify_readback(body, &good, TRUSTED_VERIFIED, body, &good, TRUSTED_VERIFIED).is_ok());
        // tampered body
        assert_eq!(
            verify_readback("TAMPERED", &good, TRUSTED_VERIFIED, body, &good, TRUSTED_VERIFIED),
            Err(TurnReason::CommitReadbackMismatch)
        );
        // wrong stored hash
        assert_eq!(
            verify_readback(body, "deadbeef", TRUSTED_VERIFIED, body, &good, TRUSTED_VERIFIED),
            Err(TurnReason::CommitReadbackMismatch)
        );
        // downgraded trust state
        assert_eq!(
            verify_readback(body, &good, "unverified", body, &good, TRUSTED_VERIFIED),
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
    fn readback_mismatch_rolls_back_the_committed_row_atomically() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        // An AFTER INSERT trigger tampers with the just-inserted row's body so the in-tx readback will
        // disagree with the accepted output. If persist_committed's INSERT + readback + verify were NOT
        // wrapped in one transaction, the tampered row would durably survive the fail-closed return. With
        // the fix, the transaction drops on the Err and the row is rolled back.
        conn.execute_batch(
            "CREATE TRIGGER tamper_after_insert
             AFTER INSERT ON governed_messages
             BEGIN
                 UPDATE governed_messages
                    SET body = 'TAMPERED-BY-TRIGGER'
                  WHERE message_id = NEW.message_id;
             END;",
        )
        .unwrap();

        // Must fail closed on the readback mismatch...
        assert_eq!(
            persist_committed(&conn, &accepted("hello world"), &production()),
            Err(TurnReason::CommitReadbackMismatch)
        );

        // ...and no row may survive: the whole transaction (INSERT + trigger UPDATE) rolled back.
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM governed_messages WHERE message_id = ?1",
                params!["m-1"],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(count, 0, "orphaned trusted_verified row must NOT survive the fail-closed path");
    }

    #[test]
    fn happy_path_commits_the_row_durably() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        // No tampering: readback matches, so the transaction must commit and the row must be durable.
        let msg = persist_committed(&conn, &accepted("hello world"), &production()).unwrap();
        assert_eq!(msg.body, "hello world");
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM governed_messages WHERE message_id = ?1 AND trust_state = 'trusted_verified'",
                params!["m-1"],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(count, 1, "a matching readback must leave exactly one committed trusted_verified row");
    }

    // ---- verify_committed_binding ------------------------------------------------------------------
    //
    // Each case below is constructed so that EXACTLY ONE of the checks in `verify_committed_binding`
    // rejects it. Delete that check and the corresponding test starts passing where it must not.

    #[test]
    fn committed_binding_returns_the_envelope_digest_for_a_real_committed_row() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let msg = persist_committed(&conn, &accepted("hello world"), &production()).unwrap();
        let b = verify_committed_binding(&conn, &msg).unwrap();
        assert_eq!(b.message_id, "m-1");
        assert_eq!(b.envelope_body_sha256, sha256_hex(b"hello world"));
    }

    #[test]
    fn committed_binding_refuses_a_projection_with_no_durable_row() {
        // The row-exists check in isolation: a projection whose message_id was never committed (a
        // rolled-back turn, or a projection minted by something other than persist_committed). Every
        // other check is unreachable because there is nothing to compare against.
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let ghost = CommittedMessage::new("never-committed".into(), "Bro".into(), "hi".into(), 1, TRUSTED_VERIFIED.into());
        assert_eq!(
            verify_committed_binding(&conn, &ghost),
            Err(TurnReason::CommitReadbackMismatch)
        );
    }

    #[test]
    fn committed_binding_refuses_a_row_whose_body_drifted_from_the_projection() {
        // The body-equality check in isolation. Only `body` is rewritten, so the row's stored
        // body_sha256 still equals SHA-256 of the PROJECTION's body — the digest check passes and only
        // the body comparison can catch the drift.
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let msg = persist_committed(&conn, &accepted("hello world"), &production()).unwrap();
        conn.execute("UPDATE governed_messages SET body = 'TAMPERED' WHERE message_id = 'm-1'", [])
            .unwrap();
        assert_eq!(verify_committed_binding(&conn, &msg), Err(TurnReason::CommitReadbackMismatch));
    }

    #[test]
    fn committed_binding_refuses_a_body_that_does_not_hash_to_the_stored_envelope_digest() {
        // The digest check in isolation: body and projection still agree, so the body-equality check
        // passes; only recomputing SHA-256 against the stored envelope digest catches it.
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let msg = persist_committed(&conn, &accepted("hello world"), &production()).unwrap();
        conn.execute(
            "UPDATE governed_messages SET body_sha256 = ?1 WHERE message_id = 'm-1'",
            params![sha256_hex(b"a DIFFERENT body")],
        )
        .unwrap();
        assert_eq!(verify_committed_binding(&conn, &msg), Err(TurnReason::CommitReadbackMismatch));
    }

    #[test]
    fn committed_binding_refuses_a_row_that_is_not_trusted_verified() {
        // The trust-state check in isolation. `create_schema`'s CHECK constraint makes this
        // unreachable through the normal table, so the test builds the same table WITHOUT the
        // constraint — the shape an older/hand-made DB could present. Body, digest, author and
        // timestamp all agree; only the trust state is wrong.
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE governed_messages (
                message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, broker_turn_id TEXT NOT NULL,
                author TEXT NOT NULL, body TEXT NOT NULL, body_sha256 TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL, trust_state TEXT NOT NULL);",
        )
        .unwrap();
        conn.execute(
            "INSERT INTO governed_messages VALUES ('m-1','c','bt','Bro','hello world',?1,7,'unverified')",
            params![sha256_hex(b"hello world")],
        )
        .unwrap();
        let msg = CommittedMessage::new("m-1".into(), "Bro".into(), "hello world".into(), 7, TRUSTED_VERIFIED.into());
        assert_eq!(verify_committed_binding(&conn, &msg), Err(TurnReason::CommitReadbackMismatch));
    }

    #[test]
    fn committed_binding_refuses_a_projection_whose_identity_fields_drifted() {
        // The author/created_at check in isolation: the body and its digest are untouched, so the two
        // content checks pass and only the identity comparison can reject the substitution.
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        let msg = persist_committed(&conn, &accepted("hello world"), &production()).unwrap();
        let restamped =
            CommittedMessage::new(msg.message_id.clone(), msg.author.clone(), msg.body.clone(), 1, TRUSTED_VERIFIED.into());
        assert_eq!(
            verify_committed_binding(&conn, &restamped),
            Err(TurnReason::CommitReadbackMismatch)
        );
        let reauthored =
            CommittedMessage::new(msg.message_id.clone(), "Someone Else".into(), msg.body.clone(), msg.created_at_ms, TRUSTED_VERIFIED.into());
        assert_eq!(
            verify_committed_binding(&conn, &reauthored),
            Err(TurnReason::CommitReadbackMismatch)
        );
    }

    #[test]
    fn duplicate_message_id_is_refused() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        persist_committed(&conn, &accepted("one"), &production()).unwrap();
        // same message_id again ⇒ PK violation ⇒ mapped to fail-closed
        assert_eq!(
            persist_committed(&conn, &accepted("one"), &production()),
            Err(TurnReason::CommitReadbackMismatch)
        );
    }
}
