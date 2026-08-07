//! Phase 5 — the **local write record** for memory entries and knowledge notes.
//!
//! A memory or knowledge write used to be an ordinary local row with nothing vouching
//! for it. This module gives every such write a durable, append-only record that is
//! appended **inside the same transaction as the write itself**, the same shape
//! [`crate::receipt_store`] uses for governed receipts: one transaction, evidence for
//! every attempt, an explicit outcome enum, and a fail-closed default.
//!
//! # What a record proves
//!
//! * **Content at write time** — `content_sha256` is a SHA-256 over a canonical
//!   (sorted-key, compact, RFC-8785-shaped) envelope of the subject's fields, so the
//!   exact bytes the store held are pinned.
//! * **That the row has not drifted since** — recompute the digest from the row on
//!   screen and compare: equal ⇒ [`SubjectState::Recorded`], different ⇒
//!   [`SubjectState::ContentDiverged`]. An out-of-band edit is *detected*, never
//!   silently absorbed.
//! * **That the ledger itself is unbroken** — each record carries the previous
//!   record's hash, `seq` is contiguous from 1, and the table is append-only at the DB
//!   layer (migration 0021 RAISEs on UPDATE/DELETE and on any INSERT that does not
//!   extend the current head). [`check_chain`] recomputes every hash and every link.
//!
//! # What a record does NOT prove — read before naming anything on screen
//!
//! **Nothing here is signed.** There is no key, no manifest, no external authority, no
//! containment. The record is produced by the same local process that performs the
//! write, so an attacker who already owns that process can append a chain that is
//! internally consistent. This is a **tamper-evidence** primitive against later
//! out-of-band edits of the database file — it is *not* attestation of the writer.
//!
//! Consequently this is **not** a governed receipt and **must never** be labelled
//! "verified". The production trust vocabulary (`trusted_verified`,
//! `development_untrusted`, `demonstration_verified`) belongs to
//! `receipt_verification_attempts` and to
//! [`crate::governed_verification`]; reusing it here would claim custody that does not
//! exist. The honest words are **recorded**, **local write record**, **content
//! diverged**, **unrecorded**.
//!
//! # No backfill
//!
//! Rows written before migration 0021 have no record and report
//! [`SubjectState::Unrecorded`]. Minting a record for a write nobody witnessed would be
//! a forged receipt, so the migration deliberately back-fills nothing.

use std::collections::BTreeMap;

use rusqlite::{Connection, OptionalExtension};
use serde::Serialize;

use crate::domain::{CoreError, CoreResult};
use crate::receipt::sha256_hex;

/// Protocol tag persisted on every record and bound into `record_sha256`. Bumping it is
/// a forward migration, never an in-place edit of existing rows.
pub const PROTOCOL: &str = "brops.local-write-record.v1";

/// `prev_record_sha256` of the genesis record (64 zeros — not a real digest, so it can
/// never collide with a record hash).
pub const GENESIS_PREV_SHA256: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";

/// The kinds of row a local write record can describe. Closed on purpose — it mirrors
/// the `subject_kind` CHECK domain in migration 0021 exactly.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SubjectKind {
    MemoryEntry,
    KnowledgeNote,
}

impl SubjectKind {
    /// The exact token persisted in the `subject_kind` column.
    pub fn as_str(self) -> &'static str {
        match self {
            SubjectKind::MemoryEntry => "memory_entry",
            SubjectKind::KnowledgeNote => "knowledge_note",
        }
    }

    /// Parse a stored token back. An unknown token is a corrupt/foreign value, not a
    /// default — callers surface it as a broken chain rather than guessing.
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "memory_entry" => Some(SubjectKind::MemoryEntry),
            "knowledge_note" => Some(SubjectKind::KnowledgeNote),
            _ => None,
        }
    }
}

/// The write that produced a record. Mirrors the `operation` CHECK domain in 0021.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum WriteOp {
    Created,
    Updated,
    Deleted,
}

impl WriteOp {
    pub fn as_str(self) -> &'static str {
        match self {
            WriteOp::Created => "created",
            WriteOp::Updated => "updated",
            WriteOp::Deleted => "deleted",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "created" => Some(WriteOp::Created),
            "updated" => Some(WriteOp::Updated),
            "deleted" => Some(WriteOp::Deleted),
            _ => None,
        }
    }
}

/// One durable record in the append-only chain.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WriteRecord {
    pub id: String,
    /// Chain position, contiguous from 1.
    pub seq: i64,
    pub subject_kind: SubjectKind,
    pub subject_id: String,
    pub operation: WriteOp,
    /// Digest of the subject's fields at write time (see [`memory_content_sha256`] /
    /// [`knowledge_content_sha256`]). For a `Deleted` record this is the digest of the
    /// row as it stood immediately before deletion.
    pub content_sha256: String,
    pub prev_record_sha256: String,
    pub record_sha256: String,
    pub recorded_at: String,
}

/// Where a subject stands against its own records. Every variant is a statement the
/// backend can actually defend; there is no "verified" variant because nothing here is
/// signed (see the module docs).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum SubjectState {
    /// The row's current content hashes to its most recent record.
    Recorded { record: WriteRecord },
    /// A record exists, but the row's current content no longer hashes to it — the row
    /// was changed outside the recorded path. This is the tamper signal; it is never
    /// downgraded to "recorded".
    ContentDiverged {
        record: WriteRecord,
        actual_content_sha256: String,
    },
    /// The latest record says the subject was deleted, yet a row is present under that
    /// id — a re-insert that bypassed the recorded path.
    DeletedButPresent { record: WriteRecord },
    /// No record at all: written before migration 0021, or written by a path that does
    /// not record. Never presented as anything stronger.
    Unrecorded,
}

/// Whole-ledger integrity, recomputed from the stored rows.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "integrity", rename_all = "snake_case")]
pub enum ChainIntegrity {
    /// Every record hash recomputes, every link matches, `seq` is contiguous from 1.
    Intact {
        records: i64,
        /// The head record's hash; `None` only when the ledger is empty.
        head_sha256: Option<String>,
    },
    /// The first record that fails, with the machine reason. A broken chain is a
    /// terminal statement — it is never rounded up to `Intact`.
    Broken { seq: i64, reason: String },
}

// ---------------------------------------------------------------------------
// Canonical digests
// ---------------------------------------------------------------------------

/// Canonical bytes for a flat `string -> string` envelope: `serde_json`'s compact
/// serialization of a `BTreeMap` emits sorted keys, no whitespace and minimal escaping,
/// which for this restricted ASCII-key shape *is* RFC 8785 JCS — the same construction
/// `receipt.rs` uses for the governed request envelope, so the two never diverge in
/// style.
fn jcs_bytes(map: &BTreeMap<String, String>) -> Vec<u8> {
    serde_json::to_vec(map).expect("a BTreeMap<String,String> always serializes")
}

/// Digest of a **memory entry**'s attestable fields. `id`, `created_at` and `updated_at`
/// are deliberately excluded: `updated_at` moves on every write (it would make the
/// digest a clock, not content), and the id is already bound by `subject_id` inside
/// `record_sha256`.
pub fn memory_content_sha256(scope: &str, kind: &str, content: &str, pinned: bool) -> String {
    let mut m = BTreeMap::new();
    m.insert("subject_kind".to_string(), SubjectKind::MemoryEntry.as_str().to_string());
    m.insert("scope".to_string(), scope.to_string());
    m.insert("kind".to_string(), kind.to_string());
    m.insert("content".to_string(), content.to_string());
    m.insert("pinned".to_string(), if pinned { "1" } else { "0" }.to_string());
    sha256_hex(&jcs_bytes(&m))
}

/// Digest of a **knowledge note**'s attestable fields (same exclusions as
/// [`memory_content_sha256`]).
pub fn knowledge_content_sha256(title: &str, body: &str, source: &str, tags: &str) -> String {
    let mut m = BTreeMap::new();
    m.insert("subject_kind".to_string(), SubjectKind::KnowledgeNote.as_str().to_string());
    m.insert("title".to_string(), title.to_string());
    m.insert("body".to_string(), body.to_string());
    m.insert("source".to_string(), source.to_string());
    m.insert("tags".to_string(), tags.to_string());
    sha256_hex(&jcs_bytes(&m))
}

/// The record hash: SHA-256 over the canonical envelope of every stored field except the
/// hash itself. `prev_record_sha256` is inside the envelope, which is what makes the
/// chain a chain — altering any earlier record invalidates every later hash.
pub fn record_sha256(
    seq: i64,
    subject_kind: SubjectKind,
    subject_id: &str,
    operation: WriteOp,
    content_sha256: &str,
    prev_record_sha256: &str,
    recorded_at: &str,
) -> String {
    let mut m = BTreeMap::new();
    m.insert("protocol".to_string(), PROTOCOL.to_string());
    m.insert("seq".to_string(), seq.to_string());
    m.insert("subject_kind".to_string(), subject_kind.as_str().to_string());
    m.insert("subject_id".to_string(), subject_id.to_string());
    m.insert("operation".to_string(), operation.as_str().to_string());
    m.insert("content_sha256".to_string(), content_sha256.to_string());
    m.insert("prev_record_sha256".to_string(), prev_record_sha256.to_string());
    m.insert("recorded_at".to_string(), recorded_at.to_string());
    sha256_hex(&jcs_bytes(&m))
}

// ---------------------------------------------------------------------------
// Append
// ---------------------------------------------------------------------------

/// Append one record, extending the current chain head.
///
/// **Must be called from inside the caller's write transaction.** Being called on an
/// autocommit connection is refused rather than degraded: the whole point is that the
/// row write and its record commit together, and a standalone append would produce a
/// record for a write that may never land (or land differently). `repo::atomic` already
/// holds a transaction at every call site.
///
/// Concurrency: `seq` is read as `MAX(seq)+1` inside the transaction and inserted
/// explicitly. If two writers race, the loser violates the `seq` PRIMARY KEY (or the
/// 0021 head trigger) and its **entire** write rolls back — a fork is impossible, and a
/// failed append can never leave an unrecorded row behind.
pub fn append(
    tx: &Connection,
    subject_kind: SubjectKind,
    subject_id: &str,
    operation: WriteOp,
    content_sha256: &str,
    recorded_at: &str,
) -> CoreResult<WriteRecord> {
    if tx.is_autocommit() {
        return Err(CoreError::Invalid {
            field: "connection",
            value: "local write records must be appended inside the write's own \
                    transaction; this connection is in autocommit"
                .to_string(),
        });
    }
    if content_sha256.len() != 64 || !content_sha256.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(CoreError::Invalid {
            field: "content_sha256",
            value: content_sha256.to_string(),
        });
    }

    let head = head(tx)?;
    let seq = head.as_ref().map(|r| r.seq).unwrap_or(0) + 1;
    let prev = head
        .as_ref()
        .map(|r| r.record_sha256.clone())
        .unwrap_or_else(|| GENESIS_PREV_SHA256.to_string());
    let digest = record_sha256(
        seq,
        subject_kind,
        subject_id,
        operation,
        content_sha256,
        &prev,
        recorded_at,
    );
    let id = crate::id();

    tx.execute(
        "INSERT INTO store_write_records
           (seq, id, protocol, subject_kind, subject_id, operation, content_sha256,
            prev_record_sha256, record_sha256, recorded_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
        rusqlite::params![
            seq,
            id,
            PROTOCOL,
            subject_kind.as_str(),
            subject_id,
            operation.as_str(),
            content_sha256,
            prev,
            digest,
            recorded_at,
        ],
    )?;

    Ok(WriteRecord {
        id,
        seq,
        subject_kind,
        subject_id: subject_id.to_string(),
        operation,
        content_sha256: content_sha256.to_string(),
        prev_record_sha256: prev,
        record_sha256: digest,
        recorded_at: recorded_at.to_string(),
    })
}

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

fn map(r: &rusqlite::Row) -> rusqlite::Result<WriteRecord> {
    let kind: String = r.get("subject_kind")?;
    let op: String = r.get("operation")?;
    Ok(WriteRecord {
        id: r.get("id")?,
        seq: r.get("seq")?,
        // A token outside the CHECK domain cannot exist in a database this code wrote;
        // if one appears the row is foreign/corrupt, so fall back to a value that makes
        // `check_chain` fail loudly rather than silently mis-attributing the record.
        subject_kind: SubjectKind::parse(&kind).unwrap_or(SubjectKind::MemoryEntry),
        subject_id: r.get("subject_id")?,
        operation: WriteOp::parse(&op).unwrap_or(WriteOp::Updated),
        content_sha256: r.get("content_sha256")?,
        prev_record_sha256: r.get("prev_record_sha256")?,
        record_sha256: r.get("record_sha256")?,
        recorded_at: r.get("recorded_at")?,
    })
}

const COLUMNS: &str = "seq, id, subject_kind, subject_id, operation, content_sha256, \
                       prev_record_sha256, record_sha256, recorded_at";

/// The current chain head, or `None` on an empty ledger.
pub fn head(conn: &Connection) -> CoreResult<Option<WriteRecord>> {
    conn.query_row(
        &format!("SELECT {COLUMNS} FROM store_write_records ORDER BY seq DESC LIMIT 1"),
        [],
        map,
    )
    .optional()
    .map_err(Into::into)
}

/// Total number of records in the ledger.
pub fn count(conn: &Connection) -> CoreResult<i64> {
    Ok(conn.query_row("SELECT COUNT(*) FROM store_write_records", [], |r| r.get(0))?)
}

/// Every record for one subject, oldest first. A deleted subject keeps its history.
pub fn records_for(
    conn: &Connection,
    subject_kind: SubjectKind,
    subject_id: &str,
) -> CoreResult<Vec<WriteRecord>> {
    let mut s = conn.prepare(&format!(
        "SELECT {COLUMNS} FROM store_write_records \
         WHERE subject_kind = ?1 AND subject_id = ?2 ORDER BY seq"
    ))?;
    let rows = s.query_map(rusqlite::params![subject_kind.as_str(), subject_id], map)?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

/// The most recent record for one subject.
pub fn latest_for(
    conn: &Connection,
    subject_kind: SubjectKind,
    subject_id: &str,
) -> CoreResult<Option<WriteRecord>> {
    conn.query_row(
        &format!(
            "SELECT {COLUMNS} FROM store_write_records \
             WHERE subject_kind = ?1 AND subject_id = ?2 ORDER BY seq DESC LIMIT 1"
        ),
        rusqlite::params![subject_kind.as_str(), subject_id],
        map,
    )
    .optional()
    .map_err(Into::into)
}

/// Where a live row stands against its own record chain. `current_content_sha256` is the
/// digest recomputed from the row as it is right now (see [`memory_content_sha256`] /
/// [`knowledge_content_sha256`]).
pub fn state_of(
    conn: &Connection,
    subject_kind: SubjectKind,
    subject_id: &str,
    current_content_sha256: &str,
) -> CoreResult<SubjectState> {
    let Some(record) = latest_for(conn, subject_kind, subject_id)? else {
        return Ok(SubjectState::Unrecorded);
    };
    if record.operation == WriteOp::Deleted {
        return Ok(SubjectState::DeletedButPresent { record });
    }
    if record.content_sha256 == current_content_sha256 {
        Ok(SubjectState::Recorded { record })
    } else {
        Ok(SubjectState::ContentDiverged {
            actual_content_sha256: current_content_sha256.to_string(),
            record,
        })
    }
}

/// Recompute the whole ledger: every `record_sha256` from its own fields, every
/// `prev_record_sha256` against the actual predecessor, and `seq` contiguous from 1.
/// Reports the FIRST failing record — a chain is only as good as its weakest link, so a
/// single break is terminal.
pub fn check_chain(conn: &Connection) -> CoreResult<ChainIntegrity> {
    let mut s = conn.prepare(&format!(
        "SELECT {COLUMNS}, protocol FROM store_write_records ORDER BY seq"
    ))?;
    let rows = s.query_map([], |r| {
        let protocol: String = r.get("protocol")?;
        Ok((map(r)?, protocol))
    })?;

    let mut expected_seq: i64 = 1;
    let mut prev = GENESIS_PREV_SHA256.to_string();
    let mut head_sha256: Option<String> = None;
    let mut records: i64 = 0;

    for row in rows {
        let (rec, protocol) = row?;
        if rec.seq != expected_seq {
            return Ok(ChainIntegrity::Broken {
                seq: rec.seq,
                reason: format!("seq is not contiguous (expected {expected_seq})"),
            });
        }
        if protocol != PROTOCOL {
            return Ok(ChainIntegrity::Broken {
                seq: rec.seq,
                reason: format!("unknown record protocol '{protocol}'"),
            });
        }
        if rec.prev_record_sha256 != prev {
            return Ok(ChainIntegrity::Broken {
                seq: rec.seq,
                reason: "prev_record_sha256 does not link to the preceding record".to_string(),
            });
        }
        let recomputed = record_sha256(
            rec.seq,
            rec.subject_kind,
            &rec.subject_id,
            rec.operation,
            &rec.content_sha256,
            &rec.prev_record_sha256,
            &rec.recorded_at,
        );
        if recomputed != rec.record_sha256 {
            return Ok(ChainIntegrity::Broken {
                seq: rec.seq,
                reason: "record_sha256 does not match the record's own fields".to_string(),
            });
        }
        prev = rec.record_sha256.clone();
        head_sha256 = Some(rec.record_sha256);
        expected_seq += 1;
        records += 1;
    }

    Ok(ChainIntegrity::Intact { records, head_sha256 })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db;

    fn db() -> Connection {
        db::open_in_memory().unwrap()
    }

    /// Append inside a transaction, the way `repo::atomic` does.
    fn append_in_tx(
        conn: &Connection,
        kind: SubjectKind,
        subject_id: &str,
        op: WriteOp,
        content: &str,
        at: &str,
    ) -> CoreResult<WriteRecord> {
        let tx = conn.unchecked_transaction().unwrap();
        let rec = append(&tx, kind, subject_id, op, content, at)?;
        tx.commit().unwrap();
        Ok(rec)
    }

    fn mem_digest(content: &str) -> String {
        memory_content_sha256("global", "note", content, false)
    }

    // ---- append + chain shape ---------------------------------------------

    #[test]
    fn genesis_record_links_to_the_zero_prev_and_chain_grows_contiguously() {
        let c = db();
        let a = append_in_tx(&c, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, &mem_digest("a"), "1000")
            .unwrap();
        assert_eq!(a.seq, 1);
        assert_eq!(a.prev_record_sha256, GENESIS_PREV_SHA256);

        let b = append_in_tx(&c, SubjectKind::KnowledgeNote, "k-1", WriteOp::Created, &mem_digest("b"), "1001")
            .unwrap();
        assert_eq!(b.seq, 2);
        assert_eq!(b.prev_record_sha256, a.record_sha256, "each record links to the previous head");

        assert_eq!(count(&c).unwrap(), 2);
        assert_eq!(head(&c).unwrap().unwrap().record_sha256, b.record_sha256);
        assert_eq!(
            check_chain(&c).unwrap(),
            ChainIntegrity::Intact { records: 2, head_sha256: Some(b.record_sha256) }
        );
    }

    #[test]
    fn record_hash_recomputes_from_the_stored_fields() {
        let c = db();
        let r = append_in_tx(&c, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, &mem_digest("a"), "1000")
            .unwrap();
        assert_eq!(
            r.record_sha256,
            record_sha256(
                r.seq,
                r.subject_kind,
                &r.subject_id,
                r.operation,
                &r.content_sha256,
                &r.prev_record_sha256,
                &r.recorded_at,
            ),
            "the stored hash must be reproducible from the record alone"
        );
    }

    #[test]
    fn appending_on_an_autocommit_connection_is_refused() {
        // The whole guarantee is "the write and its record commit together"; a
        // standalone append would break it, so it is refused, not degraded.
        let c = db();
        let err = append(&c, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, &mem_digest("a"), "1000")
            .unwrap_err();
        assert!(matches!(err, CoreError::Invalid { field: "connection", .. }), "got {err:?}");
        assert_eq!(count(&c).unwrap(), 0, "nothing may be recorded outside a transaction");
    }

    #[test]
    fn a_non_hex_content_digest_is_refused() {
        let c = db();
        let tx = c.unchecked_transaction().unwrap();
        let err = append(&tx, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, "not-a-digest", "1000")
            .unwrap_err();
        assert!(matches!(err, CoreError::Invalid { field: "content_sha256", .. }), "got {err:?}");
    }

    // ---- append-only enforcement at the DB layer ---------------------------

    #[test]
    fn the_ledger_refuses_update_and_delete() {
        let c = db();
        append_in_tx(&c, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, &mem_digest("a"), "1000").unwrap();

        let upd = c.execute("UPDATE store_write_records SET content_sha256 = ?1 WHERE seq = 1", [mem_digest("b")]);
        assert!(upd.is_err(), "a record must not be rewritable");
        let del = c.execute("DELETE FROM store_write_records WHERE seq = 1", []);
        assert!(del.is_err(), "a record must not be removable");
        assert_eq!(count(&c).unwrap(), 1);
    }

    #[test]
    fn an_insert_that_does_not_extend_the_head_is_refused_by_the_database() {
        let c = db();
        let a = append_in_tx(&c, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, &mem_digest("a"), "1000")
            .unwrap();
        // Forked prev-link (points at genesis instead of the real head).
        let forked = c.execute(
            "INSERT INTO store_write_records
               (seq, id, protocol, subject_kind, subject_id, operation, content_sha256,
                prev_record_sha256, record_sha256, recorded_at)
             VALUES (2, 'x', ?1, 'memory_entry', 'm-2', 'created', ?2, ?3, ?4, '1001')",
            rusqlite::params![PROTOCOL, mem_digest("b"), GENESIS_PREV_SHA256, mem_digest("z")],
        );
        assert!(forked.is_err(), "a forked prev-link must be refused");
        // Gapped seq (skips 2) even with a correct prev-link.
        let gapped = c.execute(
            "INSERT INTO store_write_records
               (seq, id, protocol, subject_kind, subject_id, operation, content_sha256,
                prev_record_sha256, record_sha256, recorded_at)
             VALUES (7, 'y', ?1, 'memory_entry', 'm-2', 'created', ?2, ?3, ?4, '1001')",
            rusqlite::params![PROTOCOL, mem_digest("b"), a.record_sha256, mem_digest("z")],
        );
        assert!(gapped.is_err(), "a gapped seq must be refused");
        assert_eq!(count(&c).unwrap(), 1);
    }

    #[test]
    fn a_tampered_chain_is_reported_broken_not_intact() {
        // The triggers stop tampering through this connection, so simulate a database
        // edited by another tool: rebuild the table without the guards and re-point a
        // link. `check_chain` must still catch it by recomputation alone.
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch(
            "CREATE TABLE store_write_records (
                seq INTEGER PRIMARY KEY, id TEXT NOT NULL, protocol TEXT NOT NULL,
                subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL, operation TEXT NOT NULL,
                content_sha256 TEXT NOT NULL, prev_record_sha256 TEXT NOT NULL,
                record_sha256 TEXT NOT NULL, recorded_at TEXT NOT NULL);",
        )
        .unwrap();
        let seed = |seq: i64, prev: &str, content: &str, at: &str| -> String {
            let h = record_sha256(seq, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, content, prev, at);
            c.execute(
                "INSERT INTO store_write_records VALUES (?1,'id',?2,'memory_entry','m-1','created',?3,?4,?5,?6)",
                rusqlite::params![seq, PROTOCOL, content, prev, h, at],
            )
            .unwrap();
            h
        };
        let h1 = seed(1, GENESIS_PREV_SHA256, &mem_digest("a"), "1000");
        seed(2, &h1, &mem_digest("b"), "1001");
        assert!(matches!(check_chain(&c).unwrap(), ChainIntegrity::Intact { records: 2, .. }));

        // Rewrite record 1's content without re-deriving its hash — record 1 stops
        // recomputing AND record 2's link is left dangling.
        c.execute(
            "UPDATE store_write_records SET content_sha256 = ?1 WHERE seq = 1",
            [mem_digest("TAMPERED")],
        )
        .unwrap();
        match check_chain(&c).unwrap() {
            ChainIntegrity::Broken { seq, reason } => {
                assert_eq!(seq, 1);
                assert!(reason.contains("record_sha256"), "reason was: {reason}");
            }
            other => panic!("a tampered ledger must not report {other:?}"),
        }
    }

    #[test]
    fn an_empty_ledger_is_intact_with_no_head() {
        let c = db();
        assert_eq!(
            check_chain(&c).unwrap(),
            ChainIntegrity::Intact { records: 0, head_sha256: None }
        );
    }

    // ---- per-subject state -------------------------------------------------

    #[test]
    fn a_subject_with_no_record_is_unrecorded_never_recorded() {
        let c = db();
        assert_eq!(
            state_of(&c, SubjectKind::MemoryEntry, "never-written", &mem_digest("a")).unwrap(),
            SubjectState::Unrecorded,
            "a row written before the ledger existed must never claim a record"
        );
    }

    #[test]
    fn matching_content_is_recorded_and_drifted_content_is_diverged() {
        let c = db();
        append_in_tx(&c, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, &mem_digest("a"), "1000").unwrap();

        assert!(matches!(
            state_of(&c, SubjectKind::MemoryEntry, "m-1", &mem_digest("a")).unwrap(),
            SubjectState::Recorded { .. }
        ));
        match state_of(&c, SubjectKind::MemoryEntry, "m-1", &mem_digest("edited out of band")).unwrap() {
            SubjectState::ContentDiverged { record, actual_content_sha256 } => {
                assert_eq!(record.content_sha256, mem_digest("a"));
                assert_eq!(actual_content_sha256, mem_digest("edited out of band"));
            }
            other => panic!("an out-of-band edit must be reported as diverged, got {other:?}"),
        }
    }

    #[test]
    fn a_row_present_after_a_delete_record_is_flagged() {
        let c = db();
        append_in_tx(&c, SubjectKind::MemoryEntry, "m-1", WriteOp::Created, &mem_digest("a"), "1000").unwrap();
        append_in_tx(&c, SubjectKind::MemoryEntry, "m-1", WriteOp::Deleted, &mem_digest("a"), "1001").unwrap();
        assert!(matches!(
            state_of(&c, SubjectKind::MemoryEntry, "m-1", &mem_digest("a")).unwrap(),
            SubjectState::DeletedButPresent { .. }
        ));
    }

    #[test]
    fn subject_history_is_kept_in_order_and_scoped_by_kind() {
        let c = db();
        append_in_tx(&c, SubjectKind::MemoryEntry, "s-1", WriteOp::Created, &mem_digest("a"), "1000").unwrap();
        append_in_tx(&c, SubjectKind::KnowledgeNote, "s-1", WriteOp::Created, &mem_digest("k"), "1001").unwrap();
        append_in_tx(&c, SubjectKind::MemoryEntry, "s-1", WriteOp::Updated, &mem_digest("b"), "1002").unwrap();

        let hist = records_for(&c, SubjectKind::MemoryEntry, "s-1").unwrap();
        assert_eq!(hist.len(), 2, "the same id under another kind must not leak in");
        assert_eq!(hist[0].operation, WriteOp::Created);
        assert_eq!(hist[1].operation, WriteOp::Updated);
        assert_eq!(hist[0].seq, 1);
        assert_eq!(hist[1].seq, 3);
    }

    // ---- digest shape ------------------------------------------------------

    #[test]
    fn content_digests_separate_fields_and_kinds() {
        // A digest must not be forgeable by shuffling text across fields, and the two
        // subject kinds must never collide on the same field values.
        assert_ne!(
            memory_content_sha256("ab", "c", "d", false),
            memory_content_sha256("a", "bc", "d", false)
        );
        assert_ne!(
            memory_content_sha256("g", "n", "x", false),
            memory_content_sha256("g", "n", "x", true),
            "pinned is part of the recorded content"
        );
        assert_ne!(
            knowledge_content_sha256("t", "b", "s", "g"),
            knowledge_content_sha256("t", "b", "g", "s")
        );
        // Same field values, different kind ⇒ different digest (the kind is bound in).
        assert_ne!(
            memory_content_sha256("a", "b", "c", false),
            knowledge_content_sha256("a", "b", "c", "")
        );
    }

    #[test]
    fn digests_are_lowercase_64_hex() {
        for d in [
            memory_content_sha256("g", "note", "hello", false),
            knowledge_content_sha256("t", "b", "s", "x"),
            record_sha256(1, SubjectKind::MemoryEntry, "m", WriteOp::Created, &mem_digest("a"), GENESIS_PREV_SHA256, "1"),
        ] {
            assert_eq!(d.len(), 64);
            assert!(d.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)), "{d}");
        }
    }
}
