//! Wave 3b-1B — broker-turns correlation/idempotency store (implements the design-GREEN rev-30
//! §4.10(g) "Timeout / replay / idempotency (P1-1)" rule as a **durable** store).
//!
//! Slice 1 ([`crate::governed_turn_ipc`]) gave the broker a PURE payload-aware idempotency decision
//! (`decide_idempotency` over a `&[LiveTurn]`). That slice held the live set in memory only. This slice
//! BACKS that same decision against a SQLite table so the authoritative set of live governed turns
//! survives a broker restart / reconnect and is the one durable source of truth the reattach /
//! `retry_conflict` / `turn_in_progress` rules read from.
//!
//! **Authority boundary (rev-30 §4.10(g)):** the broker mints BOTH the durable `broker_turn_id`
//! (`brops_core::id()` UUIDv4) and the `request_nonce`; the renderer can supply NEITHER (slice-1's
//! `deny_unknown_fields` already rejects a renderer frame carrying them). This module therefore takes
//! `broker_turn_id` + `request_nonce` as CALLER-SUPPLIED parameters — it never mints them and never reads
//! them off a renderer request. The only renderer-derived value that enters the store is the validated,
//! normalized [`IdempotencyKey`] (`{client_request_id, conversation_id, agent}`).
//!
//! **Testable without the OS trust chain:** every fn takes a `&rusqlite::Connection`, and `now_ms` is an
//! injected parameter — no clock, socket, or global state. Tests open `Connection::open_in_memory()` and
//! drive the full lifecycle offline.

use rusqlite::{params, Connection, ErrorCode};

use crate::governed_turn_ipc::{
    decide_idempotency, IdempotencyDecision, IdempotencyKey, LiveTurn, ValidatedRequest,
};

/// The durable lifecycle state of a broker turn. Exactly mirrors the SQL `CHECK(state IN (...))` domain.
/// A turn is born [`TurnState::Live`] via [`record_new`] and moves to a terminal
/// [`TurnState::Committed`] / [`TurnState::Blocked`] via [`settle`]; there is no path back to live.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TurnState {
    Live,
    Committed,
    Blocked,
}

impl TurnState {
    /// The exact lowercase token persisted in the `state` column (matches the SQL CHECK domain).
    pub fn as_str(self) -> &'static str {
        match self {
            TurnState::Live => "live",
            TurnState::Committed => "committed",
            TurnState::Blocked => "blocked",
        }
    }

    /// A terminal (non-live) settlement state. [`settle`] refuses anything else.
    pub fn is_terminal(self) -> bool {
        matches!(self, TurnState::Committed | TurnState::Blocked)
    }
}

/// Store-layer errors. Kept local (no new crate dep) and deliberately distinct from
/// [`crate::governed_turn_ipc::TurnReason`]: a DB fault is an infrastructure failure, not a
/// renderer-facing protocol verdict, so the broker service maps these to its own outcome rather than
/// leaking a raw SQL error to the renderer.
#[derive(Debug)]
pub enum StoreError {
    /// An underlying rusqlite / SQLite failure (open, prepare, execute, or a PK/CHECK violation).
    Db(rusqlite::Error),
    /// [`record_new`] hit the partial UNIQUE `idx_broker_turns_one_live` index: a `live` turn already
    /// exists for this `conversation_id`. This is the DB-level, race-safe form of the
    /// [`IdempotencyDecision::TurnInProgress`] verdict — the caller maps it to the same fail-closed
    /// `turn_in_progress` reply. Distinct from [`StoreError::Db`] so a benign concurrency loser is never
    /// leaked as a generic infrastructure fault.
    TurnInProgress,
    /// [`settle`] was asked to move a turn to a non-terminal (`live`) state.
    NotTerminal,
    /// [`settle`] found no `live` row for the given `broker_turn_id` (already settled, or unknown id).
    NotLive,
}

impl std::fmt::Display for StoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StoreError::Db(e) => write!(f, "broker_turns store db error: {e}"),
            StoreError::TurnInProgress => {
                write!(f, "a live broker turn already exists for this conversation")
            }
            StoreError::NotTerminal => write!(f, "settle requires a terminal (committed|blocked) state"),
            StoreError::NotLive => write!(f, "no live broker turn for the given broker_turn_id"),
        }
    }
}

impl std::error::Error for StoreError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            StoreError::Db(e) => Some(e),
            _ => None,
        }
    }
}

impl From<rusqlite::Error> for StoreError {
    fn from(e: rusqlite::Error) -> Self {
        StoreError::Db(e)
    }
}

/// Create the `broker_turns` table (idempotent — `IF NOT EXISTS`). Safe to call at every broker boot.
///
/// - `broker_turn_id` — the broker-minted durable turn identity (PRIMARY KEY).
/// - `client_request_id` / `conversation_id` / `agent` — the normalized [`IdempotencyKey`] tuple
///   (`agent` is NULL when the request carried none). These three reconstruct the live-turn key.
/// - `state` — lifecycle, constrained to the [`TurnState`] domain by a CHECK.
/// - `created_at_ms` — injected wall clock at record time.
/// - `request_nonce` — the broker-minted one-time nonce (stored verbatim; the store never mints it).
///
/// A partial index keeps the hot `state='live'` scan (the idempotency read path) cheap even as terminal
/// rows accumulate. That partial index is additionally **UNIQUE** on `conversation_id`: it is the
/// DB-level enforcement of the rev-30 §4.10(g) one-live-turn-per-conversation invariant. Without it the
/// `decide` (read of `state='live'`) → `record_new` (INSERT) pair is a non-atomic check-then-insert: two
/// concurrent requests for one conversation could both observe no live turn and both INSERT distinct
/// `broker_turn_id`s (no PK conflict), forking two live turns. The partial UNIQUE index makes the second
/// such INSERT fail at the DB, so the invariant no longer rests on the broker's single-threaded accept
/// loop alone. Because it is partial (`WHERE state='live'`), terminal (committed/blocked) rows are exempt,
/// so a settled conversation can start a fresh live turn.
pub fn create_schema(conn: &Connection) -> Result<(), StoreError> {
    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS broker_turns (
            broker_turn_id    TEXT PRIMARY KEY NOT NULL,
            client_request_id TEXT NOT NULL,
            conversation_id   TEXT NOT NULL,
            agent             TEXT,
            state             TEXT NOT NULL CHECK (state IN ('live','committed','blocked')),
            created_at_ms     INTEGER NOT NULL,
            request_nonce     TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_broker_turns_one_live
            ON broker_turns (conversation_id)
            WHERE state = 'live';
        "#,
    )?;
    Ok(())
}

/// Durably record a freshly-started broker turn as `live`.
///
/// `broker_turn_id` and `request_nonce` are BROKER-minted and passed in — this store never derives them
/// from the renderer request (rev-30 §4.10(g) authority boundary). `key` is the validated normalized
/// tuple; `now_ms` is the injected clock.
///
/// Two distinct DB constraints guard this INSERT:
/// - the `broker_turn_id` PRIMARY KEY makes a repeated insert of the same id fail loudly
///   ([`StoreError::Db`]) rather than silently forking a live row (extended code `SQLITE_CONSTRAINT_PRIMARYKEY`);
/// - the partial UNIQUE `idx_broker_turns_one_live` index makes a *second live turn for the same
///   conversation* fail at INSERT (extended code `SQLITE_CONSTRAINT_UNIQUE`). That specific violation is
///   mapped to the typed [`StoreError::TurnInProgress`] so a benign concurrency loser is reported as
///   "turn in progress" (fail-closed, race-safe) rather than a generic infrastructure fault.
///
/// This closes the non-atomic check-then-insert window: even if two callers both saw no live turn in
/// [`decide`], only one INSERT can win; the other gets [`StoreError::TurnInProgress`].
pub fn record_new(
    conn: &Connection,
    key: &IdempotencyKey,
    broker_turn_id: &str,
    request_nonce: &str,
    now_ms: i64,
) -> Result<(), StoreError> {
    conn.execute(
        "INSERT INTO broker_turns \
         (broker_turn_id, client_request_id, conversation_id, agent, state, created_at_ms, request_nonce) \
         VALUES (?1, ?2, ?3, ?4, 'live', ?5, ?6)",
        params![
            broker_turn_id,
            key.client_request_id,
            key.conversation_id,
            key.agent,
            now_ms,
            request_nonce,
        ],
    )
    .map_err(map_record_new_error)?;
    Ok(())
}

/// Classify a `record_new` INSERT failure. Only a UNIQUE-constraint violation (the partial
/// `idx_broker_turns_one_live` index firing on a second live turn for the same conversation) becomes the
/// typed [`StoreError::TurnInProgress`]; every other failure — including a PRIMARY KEY collision on a
/// duplicate `broker_turn_id`, a CHECK violation, or an I/O fault — stays [`StoreError::Db`].
fn map_record_new_error(e: rusqlite::Error) -> StoreError {
    if let rusqlite::Error::SqliteFailure(ref info, _) = e {
        // SQLITE_CONSTRAINT_UNIQUE (2067) is the partial unique-index (one-live-per-conversation)
        // violation; SQLITE_CONSTRAINT_PRIMARYKEY (1555) is a duplicate broker_turn_id and must stay Db.
        if info.code == ErrorCode::ConstraintViolation
            && info.extended_code == rusqlite::ffi::SQLITE_CONSTRAINT_UNIQUE
        {
            return StoreError::TurnInProgress;
        }
    }
    StoreError::Db(e)
}

/// The currently-live turns, reconstructed as slice-1 [`LiveTurn`] values so
/// [`decide_idempotency`] can be applied verbatim. Reads only `state='live'` rows.
pub fn live_turns(conn: &Connection) -> Result<Vec<LiveTurn>, StoreError> {
    let mut stmt = conn.prepare(
        "SELECT broker_turn_id, client_request_id, conversation_id, agent \
         FROM broker_turns WHERE state = 'live'",
    )?;
    let rows = stmt.query_map([], |row| {
        let broker_turn_id: String = row.get(0)?;
        let client_request_id: String = row.get(1)?;
        let conversation_id: String = row.get(2)?;
        let agent: Option<String> = row.get(3)?;
        Ok(LiveTurn {
            key: IdempotencyKey {
                client_request_id,
                conversation_id,
                agent,
            },
            broker_turn_id,
        })
    })?;
    let mut out = Vec::new();
    for r in rows {
        out.push(r?);
    }
    Ok(out)
}

/// Decide idempotency for `req` against the DURABLE live set (rev-30 §4.10(g) P1-1). Reuses the pure
/// slice-1 [`decide_idempotency`] over the rows returned by [`live_turns`] — the store adds durability,
/// never a second copy of the decision logic:
/// - exact live-key duplicate ⇒ [`IdempotencyDecision::Reattach`] (same `broker_turn_id`);
/// - same `client_request_id`, different conversation/agent ⇒ [`IdempotencyDecision::RetryConflict`];
/// - different request while the conversation already has a live turn ⇒ [`IdempotencyDecision::TurnInProgress`];
/// - otherwise ⇒ [`IdempotencyDecision::New`] (caller mints a fresh `broker_turn_id` and [`record_new`]s it).
pub fn decide(conn: &Connection, req: &ValidatedRequest) -> Result<IdempotencyDecision, StoreError> {
    let live = live_turns(conn)?;
    Ok(decide_idempotency(req, &live))
}

/// Move a `live` turn to a terminal state (`committed` or `blocked`). Refuses a non-terminal target
/// ([`StoreError::NotTerminal`]) and refuses a turn that is not currently `live`
/// ([`StoreError::NotLive`] — already settled or unknown id). The `WHERE state='live'` guard makes this a
/// one-shot transition: a turn can never be re-settled or resurrected, so a late/duplicate settle is a
/// visible no-op error rather than a silent overwrite.
pub fn settle(
    conn: &Connection,
    broker_turn_id: &str,
    committed_or_blocked: TurnState,
) -> Result<(), StoreError> {
    if !committed_or_blocked.is_terminal() {
        return Err(StoreError::NotTerminal);
    }
    let affected = conn.execute(
        "UPDATE broker_turns SET state = ?1 WHERE broker_turn_id = ?2 AND state = 'live'",
        params![committed_or_blocked.as_str(), broker_turn_id],
    )?;
    if affected == 0 {
        return Err(StoreError::NotLive);
    }
    Ok(())
}

/// Reconcile stranded `live` turns whose [`settle`] never ran (broker crash, lost reply, killed process).
///
/// Without this a `live` row lives forever, and because the partial UNIQUE `idx_broker_turns_one_live`
/// index allows only one live turn per conversation, that stranded row **permanently wedges** the
/// conversation — every subsequent [`record_new`] fails `TurnInProgress` and the reattach path can never
/// settle it (audit F-34: `created_at_ms` was written but never read, and there was no expiry/DELETE).
///
/// A `live` turn older than `ttl_ms` (i.e. `created_at_ms <= now_ms - ttl_ms`) is moved to the terminal
/// `blocked` state — fail-closed: an unsettled turn is treated as failed, NEVER committed — which frees
/// the conversation while leaving an auditable terminal row (no silent DELETE). Returns the number of
/// turns reconciled. Idempotent; safe to call at broker boot and before each new turn. A fresh, still
/// in-flight turn (younger than `ttl_ms`) is untouched, so a legitimately slow turn is never stolen.
pub fn expire_stale_live(conn: &Connection, now_ms: i64, ttl_ms: i64) -> Result<usize, StoreError> {
    let cutoff = now_ms.saturating_sub(ttl_ms);
    let affected = conn.execute(
        "UPDATE broker_turns SET state = 'blocked' WHERE state = 'live' AND created_at_ms <= ?1",
        params![cutoff],
    )?;
    Ok(affected)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::governed_turn_ipc::REQUEST_PROTOCOL;

    const CRID: &str = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"; // canonical lowercase UUIDv4
    const CRID2: &str = "00000000-0000-4000-8000-000000000000"; // a different valid UUIDv4

    fn store() -> Connection {
        let conn = Connection::open_in_memory().expect("open in-memory");
        create_schema(&conn).expect("create schema");
        conn
    }

    /// Build + validate a renderer request frame (mirrors slice-1's construction) so `decide` runs over
    /// a real [`ValidatedRequest`], not a hand-built key.
    fn req(conv: &str, agent: Option<&str>, crid: &str) -> ValidatedRequest {
        let agent_field = match agent {
            Some(a) => format!(r#","agent":"{a}""#),
            None => String::new(),
        };
        let raw = format!(
            r#"{{"protocol":"{REQUEST_PROTOCOL}","conversation_id":"{conv}"{agent_field},"client_request_id":"{crid}"}}"#
        );
        ValidatedRequest::decode(&raw).expect("valid request")
    }

    #[test]
    fn schema_create_is_idempotent() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        create_schema(&conn).unwrap(); // second call must not error
        assert!(live_turns(&conn).unwrap().is_empty());
    }

    #[test]
    fn exact_duplicate_reattaches_same_broker_turn_id() {
        let conn = store();
        let r = req("conv-1", Some("agent-x"), CRID);
        record_new(&conn, &r.idempotency_key(), "bt-1", "nonce-1", 1_000).unwrap();

        // An exact-duplicate request re-attaches to the SAME broker_turn_id (never a second turn).
        assert_eq!(
            decide(&conn, &r).unwrap(),
            IdempotencyDecision::Reattach("bt-1".to_string())
        );
        // ...and no new row was written by decide (read-only).
        assert_eq!(live_turns(&conn).unwrap().len(), 1);
    }

    #[test]
    fn same_crid_different_conversation_is_retry_conflict() {
        let conn = store();
        let r = req("conv-1", Some("agent-x"), CRID);
        record_new(&conn, &r.idempotency_key(), "bt-1", "nonce-1", 1_000).unwrap();

        // Same correlation token, DIFFERENT conversation ⇒ retry_conflict.
        let dup = req("conv-2", Some("agent-x"), CRID);
        assert_eq!(decide(&conn, &dup).unwrap(), IdempotencyDecision::RetryConflict);

        // Same correlation token, DIFFERENT agent ⇒ retry_conflict too.
        let dup_agent = req("conv-1", Some("agent-y"), CRID);
        assert_eq!(
            decide(&conn, &dup_agent).unwrap(),
            IdempotencyDecision::RetryConflict
        );
    }

    #[test]
    fn different_request_same_conversation_is_turn_in_progress() {
        let conn = store();
        let r = req("conv-1", Some("agent-x"), CRID);
        record_new(&conn, &r.idempotency_key(), "bt-1", "nonce-1", 1_000).unwrap();

        // New client_request_id while the conversation already has a live turn ⇒ turn_in_progress.
        let other = req("conv-1", Some("agent-x"), CRID2);
        assert_eq!(
            decide(&conn, &other).unwrap(),
            IdempotencyDecision::TurnInProgress
        );
    }

    #[test]
    fn settle_then_new_request_is_new() {
        let conn = store();
        let r = req("conv-1", Some("agent-x"), CRID);
        record_new(&conn, &r.idempotency_key(), "bt-1", "nonce-1", 1_000).unwrap();

        settle(&conn, "bt-1", TurnState::Committed).unwrap();
        assert!(live_turns(&conn).unwrap().is_empty());

        // With the prior turn settled, a brand-new request (even the SAME key) is New.
        assert_eq!(decide(&conn, &r).unwrap(), IdempotencyDecision::New);
        // And an entirely unrelated request is New as well.
        let fresh = req("conv-9", None, CRID2);
        assert_eq!(decide(&conn, &fresh).unwrap(), IdempotencyDecision::New);
    }

    #[test]
    fn new_when_no_live_turn() {
        let conn = store();
        let r = req("conv-1", Some("agent-x"), CRID);
        assert_eq!(decide(&conn, &r).unwrap(), IdempotencyDecision::New);
    }

    #[test]
    fn null_agent_roundtrips_through_the_store() {
        let conn = store();
        let r = req("conv-1", None, CRID);
        record_new(&conn, &r.idempotency_key(), "bt-1", "nonce-1", 7).unwrap();

        let live = live_turns(&conn).unwrap();
        assert_eq!(live.len(), 1);
        assert_eq!(live[0].key.agent, None);
        // Exact duplicate (agent still absent) reattaches.
        assert_eq!(
            decide(&conn, &r).unwrap(),
            IdempotencyDecision::Reattach("bt-1".to_string())
        );
    }

    #[test]
    fn duplicate_broker_turn_id_is_rejected_by_primary_key() {
        let conn = store();
        let r = req("conv-1", Some("agent-x"), CRID);
        record_new(&conn, &r.idempotency_key(), "bt-1", "nonce-1", 1_000).unwrap();
        // Re-inserting the same broker_turn_id must fail (PK), never silently fork a live row. We use a
        // DIFFERENT conversation so the one-live-per-conversation UNIQUE index does not also fire — this
        // isolates the PRIMARY KEY guard, which stays a generic StoreError::Db (extended code 1555),
        // distinct from the TurnInProgress mapping reserved for the unique-live violation (2067).
        let other = req("conv-2", Some("agent-x"), CRID2);
        let err = record_new(&conn, &other.idempotency_key(), "bt-1", "nonce-2", 2_000);
        assert!(matches!(err, Err(StoreError::Db(_))));
    }

    #[test]
    fn second_live_turn_same_conversation_is_rejected_by_unique_index() {
        let conn = store();
        // First live turn for conv-1.
        let r = req("conv-1", Some("agent-x"), CRID);
        record_new(&conn, &r.idempotency_key(), "bt-1", "nonce-1", 1_000).unwrap();

        // A DIFFERENT broker_turn_id (no PK collision) but the SAME conversation, while bt-1 is still
        // live. This is exactly the check-then-insert race: without the partial UNIQUE index both would
        // INSERT and fork two live turns. It must instead fail at the DB with the TYPED TurnInProgress
        // (the unique-constraint violation), never Ok and never a generic StoreError::Db.
        let dup = req("conv-1", Some("agent-x"), CRID2);
        let err = record_new(&conn, &dup.idempotency_key(), "bt-2", "nonce-2", 2_000);
        assert!(
            matches!(err, Err(StoreError::TurnInProgress)),
            "expected typed TurnInProgress from the one-live-per-conversation unique index, got {err:?}"
        );

        // And no second live row was forked: conv-1 still has exactly one live turn, still bt-1.
        let live = live_turns(&conn).unwrap();
        assert_eq!(live.len(), 1);
        assert_eq!(live[0].broker_turn_id, "bt-1");

        // Once bt-1 settles, the conversation is free again: a fresh live turn now inserts cleanly
        // (the index is partial on state='live', so the terminal row does not block it).
        settle(&conn, "bt-1", TurnState::Committed).unwrap();
        record_new(&conn, &dup.idempotency_key(), "bt-2", "nonce-2", 3_000).unwrap();
        let live = live_turns(&conn).unwrap();
        assert_eq!(live.len(), 1);
        assert_eq!(live[0].broker_turn_id, "bt-2");
    }

    #[test]
    fn settle_rejects_non_terminal_and_unknown_turn() {
        let conn = store();
        let r = req("conv-1", Some("agent-x"), CRID);
        record_new(&conn, &r.idempotency_key(), "bt-1", "nonce-1", 1_000).unwrap();

        // A non-terminal settle target is refused.
        assert!(matches!(
            settle(&conn, "bt-1", TurnState::Live),
            Err(StoreError::NotTerminal)
        ));
        // An unknown broker_turn_id is refused.
        assert!(matches!(
            settle(&conn, "bt-unknown", TurnState::Blocked),
            Err(StoreError::NotLive)
        ));
        // Settling twice: the second settle finds no live row.
        settle(&conn, "bt-1", TurnState::Blocked).unwrap();
        assert!(matches!(
            settle(&conn, "bt-1", TurnState::Committed),
            Err(StoreError::NotLive)
        ));
    }

    #[test]
    fn expire_stale_live_frees_a_wedged_conversation_but_spares_fresh_turns() {
        let conn = store();
        // A turn that was recorded live and then never settled (crash before settle).
        let r = req("conv-1", Some("agent-x"), CRID);
        record_new(&conn, &r.idempotency_key(), "bt-stale", "nonce-1", 1_000).unwrap();

        // A NEW request for the same conversation is wedged: the one-live index blocks it.
        let other = req("conv-1", Some("agent-x"), CRID2);
        assert!(matches!(
            record_new(&conn, &other.idempotency_key(), "bt-new", "nonce-2", 1_500),
            Err(StoreError::TurnInProgress)
        ));

        // Reconcile with a TTL such that the stale turn (created at 1_000) is now expired at 1_000_000,
        // but NOT so aggressive that it would touch a fresh turn.
        let reconciled = expire_stale_live(&conn, 1_000_000, 300_000).unwrap();
        assert_eq!(reconciled, 1);
        // The stranded row is now terminal `blocked`, so the conversation has no live turn.
        assert!(live_turns(&conn).unwrap().is_empty());
        // ...and a fresh turn for that conversation now records cleanly.
        record_new(&conn, &other.idempotency_key(), "bt-new", "nonce-2", 1_000_001).unwrap();
        assert_eq!(live_turns(&conn).unwrap().len(), 1);

        // A still-fresh live turn (younger than the TTL) is NOT reconciled.
        let fresh = req("conv-2", None, CRID);
        record_new(&conn, &fresh.idempotency_key(), "bt-fresh", "nonce-3", 1_000_100).unwrap();
        assert_eq!(expire_stale_live(&conn, 1_000_200, 300_000).unwrap(), 0);
        assert!(live_turns(&conn).unwrap().iter().any(|t| t.broker_turn_id == "bt-fresh"));
    }

    #[test]
    fn concurrent_conversations_are_independent() {
        let conn = store();
        let a = req("conv-a", Some("agent-x"), CRID);
        let b = req("conv-b", Some("agent-x"), CRID2);
        record_new(&conn, &a.idempotency_key(), "bt-a", "nonce-a", 1).unwrap();
        record_new(&conn, &b.idempotency_key(), "bt-b", "nonce-b", 2).unwrap();

        assert_eq!(live_turns(&conn).unwrap().len(), 2);
        assert_eq!(
            decide(&conn, &a).unwrap(),
            IdempotencyDecision::Reattach("bt-a".to_string())
        );
        assert_eq!(
            decide(&conn, &b).unwrap(),
            IdempotencyDecision::Reattach("bt-b".to_string())
        );
        // Settling one leaves the other live.
        settle(&conn, "bt-a", TurnState::Committed).unwrap();
        let live = live_turns(&conn).unwrap();
        assert_eq!(live.len(), 1);
        assert_eq!(live[0].broker_turn_id, "bt-b");
    }
}
