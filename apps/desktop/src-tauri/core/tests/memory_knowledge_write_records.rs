//! Phase 5 — end-to-end proof that a memory / knowledge write really carries a local
//! write record, through the public repository surface only.
//!
//! The claim under test is deliberately narrow, and every assertion here is a thing the
//! backend can actually defend:
//!
//!   * every create / pin / delete appends exactly one record, in the SAME transaction
//!     as the row write (a failed write leaves no record; a failed record rolls the
//!     write back);
//!   * the record pins the exact content, so an out-of-band edit of the row is reported
//!     as `ContentDiverged` rather than silently absorbed;
//!   * a delete record OUTLIVES the row it describes;
//!   * pre-existing rows are `Unrecorded` — never back-filled into a fake record;
//!   * the ledger is append-only and its chain recomputes.
//!
//! What is NOT claimed anywhere: signatures, custody, or "verified". Nothing here is
//! signed (see `local_write_record`'s module docs).

use brops_core::local_write_record::{
    self as lwr, ChainIntegrity, SubjectKind, SubjectState, WriteOp,
};
use brops_core::{db, repo, NewKnowledgeNote, NewMemoryEntry};
use rusqlite::Connection;

fn conn() -> Connection {
    db::open_in_memory().expect("open in-memory")
}

fn new_memory(content: &str) -> NewMemoryEntry {
    NewMemoryEntry {
        scope: "global".into(),
        kind: "note".into(),
        content: content.into(),
    }
}

fn new_note(title: &str) -> NewKnowledgeNote {
    NewKnowledgeNote {
        title: title.into(),
        body: "body".into(),
        source: "src".into(),
        tags: "a,b".into(),
    }
}

fn intact(c: &Connection) -> i64 {
    match lwr::check_chain(c).unwrap() {
        ChainIntegrity::Intact { records, .. } => records,
        other => panic!("chain must be intact, got {other:?}"),
    }
}

// --- memory ----------------------------------------------------------------

#[test]
fn creating_a_memory_records_it_and_the_row_reads_back_as_recorded() {
    let c = conn();
    let entry = repo::memory::create(&c, new_memory("rotate the API key monthly")).unwrap();

    let records = repo::memory::write_records(&c, &entry.id).unwrap();
    assert_eq!(records.len(), 1, "exactly one record per write");
    assert_eq!(records[0].operation, WriteOp::Created);
    assert_eq!(records[0].subject_kind, SubjectKind::MemoryEntry);
    assert_eq!(records[0].subject_id, entry.id);
    assert_eq!(
        records[0].content_sha256,
        lwr::memory_content_sha256(&entry.scope, &entry.kind, &entry.content, entry.pinned),
        "the record must pin the row that was actually stored"
    );

    assert!(matches!(
        repo::memory::write_record_state(&c, &entry.id).unwrap(),
        SubjectState::Recorded { .. }
    ));
    assert_eq!(intact(&c), 1);
}

#[test]
fn pinning_records_an_update_so_a_pin_never_looks_like_tampering() {
    let c = conn();
    let entry = repo::memory::create(&c, new_memory("a")).unwrap();
    let pinned = repo::memory::set_pinned(&c, &entry.id, true).unwrap();
    assert!(pinned.pinned);

    let records = repo::memory::write_records(&c, &entry.id).unwrap();
    assert_eq!(records.len(), 2);
    assert_eq!(records[1].operation, WriteOp::Updated);
    // The row still matches its LATEST record — a real change must move the record with it.
    assert!(matches!(
        repo::memory::write_record_state(&c, &entry.id).unwrap(),
        SubjectState::Recorded { .. }
    ));
    assert_eq!(intact(&c), 2);
}

#[test]
fn an_out_of_band_edit_of_the_row_is_reported_as_diverged() {
    let c = conn();
    let entry = repo::memory::create(&c, new_memory("original")).unwrap();

    // Simulate another tool editing the database file directly — the exact tamper the
    // record exists to expose.
    c.execute(
        "UPDATE memory_entries SET content = 'silently rewritten' WHERE id = ?1",
        [&entry.id],
    )
    .unwrap();

    match repo::memory::write_record_state(&c, &entry.id).unwrap() {
        SubjectState::ContentDiverged { record, actual_content_sha256 } => {
            assert_eq!(record.content_sha256, lwr::memory_content_sha256("global", "note", "original", false));
            assert_eq!(
                actual_content_sha256,
                lwr::memory_content_sha256("global", "note", "silently rewritten", false)
            );
        }
        other => panic!("an out-of-band edit must be reported as diverged, got {other:?}"),
    }
    // The ledger itself is untouched and still recomputes — divergence is a statement
    // about the ROW, not a broken chain.
    assert_eq!(intact(&c), 1);
}

#[test]
fn deleting_a_memory_keeps_its_record_including_what_was_deleted() {
    let c = conn();
    let entry = repo::memory::create(&c, new_memory("to be forgotten")).unwrap();
    let created_digest = lwr::memory_content_sha256("global", "note", "to be forgotten", false);

    repo::memory::delete(&c, &entry.id).unwrap();
    assert!(repo::memory::get(&c, &entry.id).is_err(), "the row is gone");

    let records = repo::memory::write_records(&c, &entry.id).unwrap();
    assert_eq!(records.len(), 2, "the delete record must outlive the row");
    assert_eq!(records[1].operation, WriteOp::Deleted);
    assert_eq!(
        records[1].content_sha256, created_digest,
        "the delete record pins WHAT was removed"
    );
    assert_eq!(intact(&c), 2);
}

#[test]
fn a_failed_write_records_nothing() {
    let c = conn();
    // Invalid kind: rejected before any transaction opens.
    let bad = repo::memory::create(
        &c,
        NewMemoryEntry { scope: "global".into(), kind: "not-a-kind".into(), content: "x".into() },
    );
    assert!(bad.is_err());
    // Deleting a row that does not exist.
    assert!(repo::memory::delete(&c, "nope").is_err());
    assert!(repo::memory::set_pinned(&c, "nope", true).is_err());

    assert_eq!(lwr::count(&c).unwrap(), 0, "a refused write must leave no record behind");
}

#[test]
fn a_row_written_before_the_ledger_existed_is_unrecorded_not_recorded() {
    let c = conn();
    // A row inserted straight into the table (what every pre-0021 row looks like).
    c.execute(
        "INSERT INTO memory_entries(id, scope, kind, content, pinned, created_at, updated_at)
         VALUES ('legacy-1', 'global', 'note', 'from before', 0, '1', '1')",
        [],
    )
    .unwrap();

    assert_eq!(
        repo::memory::write_record_state(&c, "legacy-1").unwrap(),
        SubjectState::Unrecorded,
        "an unwitnessed write must never be dressed up as recorded"
    );
    assert!(repo::memory::write_records(&c, "legacy-1").unwrap().is_empty());
}

// --- knowledge --------------------------------------------------------------

#[test]
fn knowledge_create_and_delete_are_recorded_the_same_way() {
    let c = conn();
    let note = repo::knowledge::create(&c, new_note("Migrations")).unwrap();

    let records = repo::knowledge::write_records(&c, &note.id).unwrap();
    assert_eq!(records.len(), 1);
    assert_eq!(records[0].subject_kind, SubjectKind::KnowledgeNote);
    assert_eq!(
        records[0].content_sha256,
        lwr::knowledge_content_sha256(&note.title, &note.body, &note.source, &note.tags)
    );
    assert!(matches!(
        repo::knowledge::write_record_state(&c, &note.id).unwrap(),
        SubjectState::Recorded { .. }
    ));

    repo::knowledge::delete(&c, &note.id).unwrap();
    let records = repo::knowledge::write_records(&c, &note.id).unwrap();
    assert_eq!(records.len(), 2);
    assert_eq!(records[1].operation, WriteOp::Deleted);
    assert_eq!(intact(&c), 2);
}

#[test]
fn an_out_of_band_edit_of_a_note_is_reported_as_diverged() {
    let c = conn();
    let note = repo::knowledge::create(&c, new_note("Migrations")).unwrap();
    c.execute("UPDATE knowledge_notes SET body = 'rewritten' WHERE id = ?1", [&note.id]).unwrap();

    assert!(matches!(
        repo::knowledge::write_record_state(&c, &note.id).unwrap(),
        SubjectState::ContentDiverged { .. }
    ));
}

// --- the shared ledger ------------------------------------------------------

#[test]
fn memory_and_knowledge_share_one_chain_that_recomputes_end_to_end() {
    let c = conn();
    let m1 = repo::memory::create(&c, new_memory("one")).unwrap();
    let k1 = repo::knowledge::create(&c, new_note("two")).unwrap();
    repo::memory::set_pinned(&c, &m1.id, true).unwrap();
    repo::knowledge::delete(&c, &k1.id).unwrap();
    let m2 = repo::memory::create(&c, new_memory("three")).unwrap();
    repo::memory::delete(&c, &m2.id).unwrap();

    // 6 writes -> 6 records, contiguous, each linking to the previous.
    assert_eq!(intact(&c), 6);
    let head = lwr::head(&c).unwrap().expect("a head exists");
    assert_eq!(head.seq, 6);

    let mem_hist = repo::memory::write_records(&c, &m1.id).unwrap();
    assert_eq!(
        mem_hist.iter().map(|r| r.operation).collect::<Vec<_>>(),
        vec![WriteOp::Created, WriteOp::Updated]
    );
}

#[test]
fn the_ledger_cannot_be_rewritten_through_the_live_connection() {
    let c = conn();
    let entry = repo::memory::create(&c, new_memory("a")).unwrap();
    let _ = entry;

    assert!(
        c.execute("DELETE FROM store_write_records", []).is_err(),
        "records must not be deletable"
    );
    assert!(
        c.execute("UPDATE store_write_records SET recorded_at = '0'", []).is_err(),
        "records must not be editable"
    );
    assert_eq!(intact(&c), 1);
}
