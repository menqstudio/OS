//! Wave 3b-1B — governed output-stream lifecycle (implements the design-GREEN rev-30 §4.10(f): the
//! broker-owned output stream's three-phase lifecycle — LIVE → tombstone (`stream_expired`) → swept
//! (`stream_unknown`) — with a one-shot capability token, a fixed TTL, per-install quota + FIFO eviction,
//! and a sweep that NEVER unlinks the content-addressed output (that is pinned by the terminal record).
//!
//! rusqlite-backed + fully testable in-memory. The capability token is anti-guessing only (integrity comes
//! from the signed envelope, §4.7); it is minted ONCE and never re-minted after expiry.
//!
//! # NOTHING CALLS `mint`/`resolve`/`sweep` (state as of 2026-08-09)
//!
//! Only [`create_schema`] has callers — `broker/src/main.rs`, `proof/src/bin/live_turn.rs`,
//! `win-live/src/bin/win_live_turn.rs`, `win-live/src/proof.rs` — so this module creates its table
//! and nothing ever writes a row. The three lifecycle functions are declared under `rust_symbols` in
//! `config/reachability-declarations.json` and defended by `tools/check_reachability.py`, which turns
//! RED the day a caller appears so the change gets recorded rather than absorbed.
//!
//! Three things a reader deserves to know before wiring one:
//!
//! 1. **This is not the roadmap's "governed streaming".** MASTER_EXECUTION_ROADMAP Phase 1 descopes
//!    delta-streaming; a governed turn is buffered by construction, because the desktop's authority
//!    is a signature over the WHOLE output. §4.10(f) is the opposite end: a chunked PULL of an
//!    already-completed output, verified against that same whole-output digest.
//! 2. **Nothing pulls yet.** The shipped broker runs the turn in-process and returns the output
//!    inline in its single-request/single-response reply, so no `output_stream_id` is ever minted.
//! 3. **The table below DIVERGES from the design it cites**, so wiring a caller is a rewrite and not
//!    a hookup. Design §4.10(f) is INSERT-ONCE (state derived, never stored) and binds
//!    `receipt_id`/`execution_attempt_id`/`output_handle`/`output_bytes`/`output_sha256` with
//!    `retained_until_ms` and a per-install quota of 64; this implementation carries a mutable
//!    `state` column, a `broker_turn_id` in place of those bindings, and a quota of 8. In particular
//!    the design's server-side `stream_binding_mismatch` — a valid token presented for a different
//!    receipt/attempt — cannot be produced here at all, because the columns it compares do not exist.

use rusqlite::{params, Connection};

/// Output-stream TTL + retention + sweep interval (rev-30 §4.10(f) constants).
pub const OUTPUT_STREAM_TTL_MS: i64 = 360_000;
pub const OUTPUT_STREAM_RETENTION_MS: i64 = 360_000;
pub const MAX_LIVE_STREAMS_PER_INSTALL: i64 = 8;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StreamError {
    /// The token did not match the minted one.
    TokenMismatch,
    /// The stream exists but is past its TTL (tombstone phase → `stream_expired`).
    Expired,
    /// No such live/tombstoned stream (absent or swept → `stream_unknown`).
    Unknown,
    /// A second mint under the same id (one-shot minting is violated).
    AlreadyMinted,
    Db,
}

impl StreamError {
    pub fn as_str(&self) -> &'static str {
        match self {
            StreamError::TokenMismatch => "token_mismatch",
            StreamError::Expired => "stream_expired",
            StreamError::Unknown => "stream_unknown",
            StreamError::AlreadyMinted => "already_minted",
            StreamError::Db => "db_error",
        }
    }
}
impl From<rusqlite::Error> for StreamError {
    fn from(_: rusqlite::Error) -> Self {
        StreamError::Db
    }
}

pub fn create_schema(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS governed_output_streams (
            output_stream_id TEXT PRIMARY KEY,
            broker_turn_id   TEXT NOT NULL,
            install_id       TEXT NOT NULL,
            capability_token TEXT NOT NULL,
            state            TEXT NOT NULL CHECK (state IN ('live','expired','swept')),
            created_at_ms    INTEGER NOT NULL,
            expires_at_ms    INTEGER NOT NULL
        );",
    )
}

/// Mint a new LIVE output stream (one-shot). A second mint under the same `output_stream_id` ⇒
/// `AlreadyMinted` (the token is never re-minted post-expiry). Enforces the per-install LIVE quota with
/// FIFO eviction of the oldest live stream (tombstoned, not deleted).
pub fn mint(
    conn: &Connection,
    output_stream_id: &str,
    broker_turn_id: &str,
    install_id: &str,
    capability_token: &str,
    now_ms: i64,
) -> Result<(), StreamError> {
    // one-shot: even an already-expired/swept row blocks a re-mint of the same id.
    let exists: i64 = conn.query_row(
        "SELECT COUNT(*) FROM governed_output_streams WHERE output_stream_id = ?1",
        params![output_stream_id],
        |r| r.get(0),
    )?;
    if exists > 0 {
        return Err(StreamError::AlreadyMinted);
    }
    // per-install FIFO eviction of the oldest LIVE stream over quota.
    let live: i64 = conn.query_row(
        "SELECT COUNT(*) FROM governed_output_streams WHERE install_id = ?1 AND state = 'live'",
        params![install_id],
        |r| r.get(0),
    )?;
    if live >= MAX_LIVE_STREAMS_PER_INSTALL {
        conn.execute(
            "UPDATE governed_output_streams SET state = 'expired'
             WHERE output_stream_id = (
                SELECT output_stream_id FROM governed_output_streams
                WHERE install_id = ?1 AND state = 'live' ORDER BY created_at_ms ASC LIMIT 1)",
            params![install_id],
        )?;
    }
    conn.execute(
        "INSERT INTO governed_output_streams
            (output_stream_id, broker_turn_id, install_id, capability_token, state, created_at_ms, expires_at_ms)
         VALUES (?1, ?2, ?3, ?4, 'live', ?5, ?6)",
        params![
            output_stream_id,
            broker_turn_id,
            install_id,
            capability_token,
            now_ms,
            now_ms + OUTPUT_STREAM_TTL_MS
        ],
    )?;
    Ok(())
}

/// Constant-time byte-slice equality. The length is compared first (the token length is not the
/// secret — only the bytes are), then every byte is folded into an accumulator with no early exit,
/// so the running time does not depend on the position of the first differing byte.
fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff: u8 = 0;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

/// Resolve an output stream for a read (rev-30 §4.10(f) three-phase). LIVE + token match + not-expired ⇒
/// Ok(broker_turn_id). Past TTL ⇒ `Expired` (tombstone). Absent/swept ⇒ `Unknown`. Wrong token ⇒
/// `TokenMismatch`. Verified OUTSIDE any DB write (read-only).
pub fn resolve(
    conn: &Connection,
    output_stream_id: &str,
    capability_token: &str,
    now_ms: i64,
) -> Result<String, StreamError> {
    let row = conn
        .query_row(
            "SELECT broker_turn_id, capability_token, state, expires_at_ms
             FROM governed_output_streams WHERE output_stream_id = ?1",
            params![output_stream_id],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, i64>(3)?,
                ))
            },
        )
        .ok();
    let (bt, tok, state, expires) = match row {
        Some(v) => v,
        None => return Err(StreamError::Unknown),
    };
    if state == "swept" {
        return Err(StreamError::Unknown);
    }
    // constant-time token check (length + bytes) before any phase decision: the byte comparison
    // must not short-circuit on the first differing byte, since the token is the sole anti-guessing
    // secret and a data-dependent early exit would leak it via a timing oracle.
    if !ct_eq(tok.as_bytes(), capability_token.as_bytes()) {
        return Err(StreamError::TokenMismatch);
    }
    if state == "expired" || now_ms >= expires {
        return Err(StreamError::Expired);
    }
    Ok(bt)
}

/// Sweep tombstoned streams past their retention window to `swept` (rev-30 §4.10(f)). Returns the number
/// swept. NEVER unlinks the content-addressed output (pinned by the terminal record/receipt).
pub fn sweep(conn: &Connection, now_ms: i64) -> Result<usize, StreamError> {
    // tombstone any live-but-expired first
    conn.execute(
        "UPDATE governed_output_streams SET state = 'expired' WHERE state = 'live' AND ?1 >= expires_at_ms",
        params![now_ms],
    )?;
    let n = conn.execute(
        "UPDATE governed_output_streams SET state = 'swept'
         WHERE state = 'expired' AND ?1 >= expires_at_ms + ?2",
        params![now_ms, OUTPUT_STREAM_RETENTION_MS],
    )?;
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn conn() -> Connection {
        let c = Connection::open_in_memory().unwrap();
        create_schema(&c).unwrap();
        c
    }
    const TOK: &str = "0123456789012345678901234567890123456789012"; // 43-char anti-guessing token

    #[test]
    fn mint_then_resolve_live() {
        let c = conn();
        mint(&c, "os-1", "bt-1", "inst-1", TOK, 1000).unwrap();
        assert_eq!(resolve(&c, "os-1", TOK, 2000).unwrap(), "bt-1");
    }

    #[test]
    fn resolve_unknown_stream() {
        let c = conn();
        assert_eq!(resolve(&c, "nope", TOK, 1), Err(StreamError::Unknown));
    }

    #[test]
    fn resolve_wrong_token_is_mismatch() {
        let c = conn();
        mint(&c, "os-1", "bt-1", "inst-1", TOK, 1000).unwrap();
        assert_eq!(resolve(&c, "os-1", "wrong", 2000), Err(StreamError::TokenMismatch));
    }

    #[test]
    fn resolve_token_diff_first_or_last_byte_is_mismatch() {
        let c = conn();
        mint(&c, "os-1", "bt-1", "inst-1", TOK, 1000).unwrap();
        // exact match resolves
        assert_eq!(resolve(&c, "os-1", TOK, 2000).unwrap(), "bt-1");
        // same length as TOK, differing ONLY in the last byte
        let mut last = TOK.as_bytes().to_vec();
        *last.last_mut().unwrap() ^= 0x01;
        let last = String::from_utf8(last).unwrap();
        assert_ne!(last.as_str(), TOK);
        assert_eq!(resolve(&c, "os-1", &last, 2000), Err(StreamError::TokenMismatch));
        // same length as TOK, differing ONLY in the first byte
        let mut first = TOK.as_bytes().to_vec();
        first[0] ^= 0x01;
        let first = String::from_utf8(first).unwrap();
        assert_ne!(first.as_str(), TOK);
        assert_eq!(resolve(&c, "os-1", &first, 2000), Err(StreamError::TokenMismatch));
    }

    #[test]
    fn ct_eq_matches_plain_equality() {
        assert!(ct_eq(b"abc", b"abc"));
        assert!(!ct_eq(b"abc", b"abd")); // last byte differs
        assert!(!ct_eq(b"abc", b"zbc")); // first byte differs
        assert!(!ct_eq(b"abc", b"ab")); // length differs
        assert!(ct_eq(b"", b""));
    }

    #[test]
    fn past_ttl_is_expired_tombstone() {
        let c = conn();
        mint(&c, "os-1", "bt-1", "inst-1", TOK, 1000).unwrap();
        assert_eq!(resolve(&c, "os-1", TOK, 1000 + OUTPUT_STREAM_TTL_MS), Err(StreamError::Expired));
    }

    #[test]
    fn one_shot_mint_rejects_remint() {
        let c = conn();
        mint(&c, "os-1", "bt-1", "inst-1", TOK, 1000).unwrap();
        assert_eq!(mint(&c, "os-1", "bt-9", "inst-1", TOK, 5000), Err(StreamError::AlreadyMinted));
    }

    #[test]
    fn sweep_moves_expired_past_retention_to_swept_then_unknown() {
        let c = conn();
        mint(&c, "os-1", "bt-1", "inst-1", TOK, 1000).unwrap();
        // well past ttl + retention
        let far = 1000 + OUTPUT_STREAM_TTL_MS + OUTPUT_STREAM_RETENTION_MS + 1;
        assert_eq!(sweep(&c, far).unwrap(), 1);
        assert_eq!(resolve(&c, "os-1", TOK, far), Err(StreamError::Unknown)); // swept reads as unknown
    }

    #[test]
    fn fifo_eviction_over_per_install_quota() {
        let c = conn();
        for i in 0..MAX_LIVE_STREAMS_PER_INSTALL {
            mint(&c, &format!("os-{i}"), "bt", "inst-1", TOK, 100 + i).unwrap();
        }
        // one more live stream evicts the oldest (os-0) to expired
        mint(&c, "os-extra", "bt", "inst-1", TOK, 100 + MAX_LIVE_STREAMS_PER_INSTALL).unwrap();
        assert_eq!(resolve(&c, "os-0", TOK, 200), Err(StreamError::Expired));
        assert_eq!(resolve(&c, "os-extra", TOK, 200).unwrap(), "bt");
    }
}
