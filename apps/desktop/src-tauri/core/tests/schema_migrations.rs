//! End-to-end schema/migration test for `brops-core`.
//!
//! Applies every migration (0001..0015) in order to a fresh SQLite database and
//! asserts the resulting shape: `SCHEMA_VERSION == 16`, the ledger is contiguous
//! 1..=16, the key tables/columns exist, and the constraints introduced across
//! the migrations (status-guard triggers, the run_steps position uniqueness, and
//! the Wave-3a receipt tables' CHECK/PK/one-time-consume invariants) actually
//! bite. Migrations are forward-only (no down scripts), so the "down/idempotency"
//! leg here is the forward-only guarantee: re-running `migrate` — in the same
//! process and across a real file reopen — re-applies nothing and never re-runs
//! the non-idempotent `ALTER TABLE`s.
//!
//! Uses only the crate's public surface (`brops_core::db`) plus raw SQL through
//! the connection, matching the inline-test conventions in `src/lib.rs`
//! (`db::open_in_memory`, `db::migrate`, `db::current_version`).

use brops_core::db;
use rusqlite::{params, Connection};

// --- helpers ---------------------------------------------------------------

/// A migrated in-memory connection (foreign keys ON, all migrations applied) —
/// the same path production uses, mirroring `lib.rs`'s `conn()` helper.
fn conn() -> Connection {
    db::open_in_memory().expect("open in-memory")
}

/// True if a named object (table / virtual table / index / trigger) is present.
fn object_exists(c: &Connection, name: &str) -> bool {
    c.query_row(
        "SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE name = ?1)",
        [name],
        |r| r.get::<_, bool>(0),
    )
    .unwrap()
}

/// True if `table` has a column called `col` (via PRAGMA table_info).
fn has_column(c: &Connection, table: &str, col: &str) -> bool {
    // table names here are all test-controlled literals, so string-formatting the
    // PRAGMA (which does not accept bound parameters) is safe.
    let mut stmt = c
        .prepare(&format!("PRAGMA table_info({table})"))
        .expect("prepare table_info");
    let cols: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(1))
        .expect("query table_info")
        .filter_map(Result::ok)
        .collect();
    cols.iter().any(|c| c == col)
}

/// The applied versions in the ledger, ascending.
fn applied_versions(c: &Connection) -> Vec<i64> {
    let mut stmt = c
        .prepare("SELECT version FROM _migrations ORDER BY version")
        .unwrap();
    stmt.query_map([], |r| r.get::<_, i64>(0))
        .unwrap()
        .filter_map(Result::ok)
        .collect()
}

// --- migration application & versioning ------------------------------------

#[test]
fn migrate_applies_all_versions_in_order_to_a_fresh_db() {
    // A genuinely fresh connection driven straight through `migrate` (not the
    // `open_in_memory` convenience) — this is the "apply every migration in order
    // to a fresh in-memory SQLite DB" assertion.
    let c = Connection::open_in_memory().unwrap();
    c.pragma_update(None, "foreign_keys", "ON").unwrap();
    db::migrate(&c).unwrap();

    assert_eq!(db::SCHEMA_VERSION, 21, "crate SCHEMA_VERSION must be 21");
    assert_eq!(db::current_version(&c).unwrap(), 21);
    // The ledger is contiguous 1..=21 — nothing skipped, nothing double-counted.
    assert_eq!(applied_versions(&c), (1..=21).collect::<Vec<i64>>());
    // 0017 created the group-chat participants roster table.
    let has_participants: i64 = c
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='conversation_participants'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(has_participants, 1, "0017 must create conversation_participants");
    // 0018 created the additive demonstration-verified badge table (separate from the trust records).
    let has_demo: i64 = c
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='demonstration_verified_messages'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(has_demo, 1, "0018 must create demonstration_verified_messages");
    // 0019 widened the approvals.status guards to permit 'escalated' (higher-review routing).
    let esc_guarded: i64 = c
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='trigger' \
             AND name IN ('trg_approvals_status_ins','trg_approvals_status_upd') \
             AND sql LIKE '%escalated%'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(esc_guarded, 2, "0019 must allow 'escalated' in both approvals.status guards");
    // 0020 created the automation run-log table.
    let has_runs: i64 = c
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='automation_runs'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(has_runs, 1, "0020 must create automation_runs");
    // 0021 created the append-only LOCAL write-record ledger for memory/knowledge writes,
    // guarded so it can be appended to but never rewritten.
    let has_records: i64 = c
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='store_write_records'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(has_records, 1, "0021 must create store_write_records");
    let guards: i64 = c
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN \
             ('trg_store_write_records_no_update','trg_store_write_records_no_delete',\
              'trg_store_write_records_extends_head')",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(guards, 3, "0021 must install all three append-only chain guards");
}

// --- 0021: the local write-record ledger is append-only in the DB itself ----

#[test]
fn store_write_records_rejects_update_delete_and_a_non_extending_insert() {
    let c = conn();
    let genesis = "0000000000000000000000000000000000000000000000000000000000000000";
    let hex = |n: u8| std::iter::repeat_n(format!("{n:02x}"), 32).collect::<String>();

    c.execute(
        "INSERT INTO store_write_records
           (seq, id, protocol, subject_kind, subject_id, operation, content_sha256,
            prev_record_sha256, record_sha256, recorded_at)
         VALUES (1, 'r-1', 'brops.local-write-record.v1', 'memory_entry', 'm-1', 'created',
                 ?1, ?2, ?3, '1000')",
        params![hex(0xaa), genesis, hex(0xbb)],
    )
    .unwrap();

    assert!(
        c.execute("UPDATE store_write_records SET content_sha256 = ?1 WHERE seq = 1", [hex(0xcc)])
            .is_err(),
        "a write record must never be rewritable"
    );
    assert!(
        c.execute("DELETE FROM store_write_records WHERE seq = 1", []).is_err(),
        "a write record must never be removable"
    );
    // A second record that does not link to the head is refused by the trigger.
    assert!(
        c.execute(
            "INSERT INTO store_write_records
               (seq, id, protocol, subject_kind, subject_id, operation, content_sha256,
                prev_record_sha256, record_sha256, recorded_at)
             VALUES (2, 'r-2', 'brops.local-write-record.v1', 'memory_entry', 'm-2', 'created',
                     ?1, ?2, ?3, '1001')",
            params![hex(0xaa), genesis, hex(0xdd)],
        )
        .is_err(),
        "an appended record must extend the current head"
    );
    // A foreign subject_kind / operation is outside the CHECK domain.
    assert!(
        c.execute(
            "INSERT INTO store_write_records
               (seq, id, protocol, subject_kind, subject_id, operation, content_sha256,
                prev_record_sha256, record_sha256, recorded_at)
             VALUES (2, 'r-3', 'brops.local-write-record.v1', 'chat_message', 'x', 'created',
                     ?1, ?2, ?3, '1001')",
            params![hex(0xaa), hex(0xbb), hex(0xee)],
        )
        .is_err(),
        "subject_kind is a closed domain"
    );
}

#[test]
fn current_version_is_zero_before_any_migration() {
    // A brand-new connection has no `_migrations` ledger yet -> reported as 0
    // (never mistaken for "already at latest").
    let c = Connection::open_in_memory().unwrap();
    assert_eq!(db::current_version(&c).unwrap(), 0);
}

// --- key tables & ALTER-added columns exist --------------------------------

#[test]
fn all_key_tables_exist() {
    let c = conn();
    for t in [
        // 0001
        "workspaces", "agents", "projects", "tasks", "task_dependencies",
        "approvals", "notifications", "audit_events", "settings",
        // 0002..0005
        "decisions", "conversations", "messages", "knowledge_notes",
        "memory_entries", "runs", "events", "automations", "integrations",
        // 0006 + FTS 0010
        "run_steps", "search_index",
        // 0014 receipt tables
        "receipt_challenges", "receipt_verification_attempts", "receipt_ids_seen",
        // 0015 library + research
        "library_items", "research_items",
        // migration ledger
        "_migrations",
    ] {
        assert!(object_exists(&c, t), "table `{t}` should exist after migration");
    }
}

#[test]
fn alter_added_columns_are_present() {
    let c = conn();
    // 0007 result, 0008 approval gate, 0013 execution-claim triple.
    for col in [
        "result",
        "requires_approval",
        "execution_attempt_id",
        "execution_owner_session_id",
        "execution_started_at",
    ] {
        assert!(has_column(&c, "run_steps", col), "run_steps.{col} missing");
    }
    // 0008 entity link + 0012 durable approval provenance / native-confirm columns.
    for col in [
        "entity_type", "entity_id",
        "origin_principal", "origin_session_id", "request_digest", "nonce",
        "confirmed_at", "confirmed_by", "confirmation_method", "confirmation_digest",
    ] {
        assert!(has_column(&c, "approvals", col), "approvals.{col} missing");
    }
}

#[test]
fn key_indexes_and_triggers_exist() {
    let c = conn();
    // 0011 unique run-step ordering; 0010/0011 representative triggers.
    for obj in [
        "idx_run_steps_run_pos",
        "trg_runs_status_ins",
        "trg_run_steps_status_ins",
        "trg_approvals_status_ins",
        "trg_run_steps_delete_approvals",
        "trg_search_tasks_ai",
    ] {
        assert!(object_exists(&c, obj), "expected `{obj}` to exist");
    }
}

// --- constraints introduced by the migrations actually bite ----------------

#[test]
fn status_guard_triggers_reject_out_of_enum_values() {
    let c = conn();
    // 0011: a run whose status is outside the canonical set is aborted at insert.
    let bad = c.execute(
        "INSERT INTO runs(id, intent, status, plan, created_at, updated_at)
         VALUES ('r-bad', 'i', 'bogus', '', '1', '1')",
        [],
    );
    assert!(bad.is_err(), "invalid runs.status must be refused by the guard trigger");

    // A valid status is accepted...
    c.execute(
        "INSERT INTO runs(id, intent, status, plan, created_at, updated_at)
         VALUES ('r-ok', 'i', 'drafted', '', '1', '1')",
        [],
    )
    .unwrap();
    // ...and updating it to an invalid one is likewise aborted.
    assert!(
        c.execute("UPDATE runs SET status = 'nonsense' WHERE id = 'r-ok'", []).is_err(),
        "invalid runs.status must be refused on UPDATE too"
    );
}

#[test]
fn run_step_position_is_unique_per_run() {
    let c = conn();
    c.execute(
        "INSERT INTO runs(id, intent, status, plan, created_at, updated_at)
         VALUES ('r1', 'i', 'drafted', '', '1', '1')",
        [],
    )
    .unwrap();
    c.execute(
        "INSERT INTO run_steps(id, run_id, position, title, detail, status, created_at, updated_at)
         VALUES ('s1', 'r1', 1, 't', '', 'pending', '1', '1')",
        [],
    )
    .unwrap();
    // 0011 unique index (run_id, position): a duplicate position is refused.
    let dup = c.execute(
        "INSERT INTO run_steps(id, run_id, position, title, detail, status, created_at, updated_at)
         VALUES ('s2', 'r1', 1, 't2', '', 'pending', '1', '1')",
        [],
    );
    assert!(dup.is_err(), "duplicate (run_id, position) must be rejected");
}

#[test]
fn foreign_keys_are_enforced() {
    let c = conn();
    // FK: a run_step pointing at a non-existent run is refused (foreign_keys=ON).
    let orphan = c.execute(
        "INSERT INTO run_steps(id, run_id, position, title, detail, status, created_at, updated_at)
         VALUES ('s-orphan', 'no-such-run', 1, 't', '', 'pending', '1', '1')",
        [],
    );
    assert!(orphan.is_err(), "run_step with unknown run_id must be rejected by FK");
}

// --- Wave 3a receipt tables (0014) invariants ------------------------------

#[test]
fn receipt_challenge_hash_shape_and_nonce_uniqueness() {
    let c = conn();
    c.execute(
        "INSERT INTO conversations(id, kind, title, created_at, updated_at)
         VALUES ('conv1', 'direct', 'Bro', '1', '1')",
        [],
    )
    .unwrap();
    let good_hash = "a".repeat(64); // 64 lowercase hex chars

    // A well-formed challenge inserts.
    c.execute(
        "INSERT INTO receipt_challenges(nonce, conversation_id, request_sha256, issued_at)
         VALUES ('n1', 'conv1', ?1, '1')",
        params![good_hash],
    )
    .unwrap();

    // CHECK(length==64 AND all hex) rejects a malformed digest.
    let bad_hash = c.execute(
        "INSERT INTO receipt_challenges(nonce, conversation_id, request_sha256, issued_at)
         VALUES ('n2', 'conv1', 'not-a-valid-sha256', '1')",
        [],
    );
    assert!(bad_hash.is_err(), "non-hex / wrong-length request_sha256 must be refused");

    // nonce is PRIMARY KEY -> re-issuing the same nonce is refused.
    let dup_nonce = c.execute(
        "INSERT INTO receipt_challenges(nonce, conversation_id, request_sha256, issued_at)
         VALUES ('n1', 'conv1', ?1, '2')",
        params![good_hash],
    );
    assert!(dup_nonce.is_err(), "duplicate challenge nonce must be refused (PK)");
}

#[test]
fn receipt_challenge_nonce_is_consumed_at_most_once() {
    let c = conn();
    c.execute(
        "INSERT INTO conversations(id, kind, title, created_at, updated_at)
         VALUES ('conv1', 'direct', 'Bro', '1', '1')",
        [],
    )
    .unwrap();
    c.execute(
        "INSERT INTO receipt_challenges(nonce, conversation_id, request_sha256, issued_at)
         VALUES ('n1', 'conv1', ?1, '1')",
        params!["b".repeat(64)],
    )
    .unwrap();

    // The one-time compare-and-consume: first UPDATE affects the row, the second
    // (already-consumed) affects none. This is the DB-level replay mutual exclusion.
    let first = c
        .execute(
            "UPDATE receipt_challenges SET consumed_at = '2' WHERE nonce = 'n1' AND consumed_at IS NULL",
            [],
        )
        .unwrap();
    assert_eq!(first, 1, "first consume must claim the nonce");
    let second = c
        .execute(
            "UPDATE receipt_challenges SET consumed_at = '3' WHERE nonce = 'n1' AND consumed_at IS NULL",
            [],
        )
        .unwrap();
    assert_eq!(second, 0, "a spent nonce must not be consumable again");
}

#[test]
fn receipt_attempt_outcome_and_message_link_check_holds() {
    let c = conn();

    // Blocked attempts NEVER link a message -> a NULL message_id is valid.
    c.execute(
        "INSERT INTO receipt_verification_attempts
            (id, wire_envelope_jcs_b64, wire_signature_b64, outcome, verified_at)
         VALUES ('att-blocked', 'e', 's', 'blocked', '1')",
        [],
    )
    .unwrap();

    // An accepted outcome with NO message violates the CHECK (accepted => message).
    let accepted_no_msg = c.execute(
        "INSERT INTO receipt_verification_attempts
            (id, wire_envelope_jcs_b64, wire_signature_b64, outcome, verified_at)
         VALUES ('att-bad', 'e', 's', 'development_untrusted', '1')",
        [],
    );
    assert!(
        accepted_no_msg.is_err(),
        "an accepted attempt with a NULL message_id must fail the CHECK"
    );

    // An out-of-domain outcome is refused by the outcome CHECK.
    let bad_outcome = c.execute(
        "INSERT INTO receipt_verification_attempts
            (id, wire_envelope_jcs_b64, wire_signature_b64, outcome, verified_at)
         VALUES ('att-x', 'e', 's', 'made-up', '1')",
        [],
    );
    assert!(bad_outcome.is_err(), "unknown outcome value must be refused");

    // A blocked attempt that DOES link a message violates the CHECK too. Build a
    // real message first so the failure is the CHECK, not the FK.
    c.execute(
        "INSERT INTO conversations(id, kind, title, created_at, updated_at)
         VALUES ('conv1', 'direct', 'Bro', '1', '1')",
        [],
    )
    .unwrap();
    c.execute(
        "INSERT INTO messages(id, conversation_id, role, author, body, created_at)
         VALUES ('m1', 'conv1', 'agent', 'Bro', 'hi', '1')",
        [],
    )
    .unwrap();
    let blocked_with_msg = c.execute(
        "INSERT INTO receipt_verification_attempts
            (id, wire_envelope_jcs_b64, wire_signature_b64, outcome, message_id, verified_at)
         VALUES ('att-b2', 'e', 's', 'blocked', 'm1', '1')",
        [],
    );
    assert!(
        blocked_with_msg.is_err(),
        "a blocked attempt linking a message must fail the CHECK"
    );

    // And the happy accepted path (real message linked) inserts cleanly.
    c.execute(
        "INSERT INTO receipt_verification_attempts
            (id, wire_envelope_jcs_b64, wire_signature_b64, outcome, message_id, verified_at)
         VALUES ('att-ok', 'e', 's', 'development_untrusted', 'm1', '1')",
        [],
    )
    .unwrap();
}

#[test]
fn accepted_receipt_id_is_globally_unique() {
    let c = conn();
    c.execute(
        "INSERT INTO receipt_ids_seen(receipt_id, first_seen_at) VALUES ('rid-1', '1')",
        [],
    )
    .unwrap();
    // PRIMARY KEY on receipt_id is the hard replay defense: no id accepted twice.
    let dup = c.execute(
        "INSERT INTO receipt_ids_seen(receipt_id, first_seen_at) VALUES ('rid-1', '2')",
        [],
    );
    assert!(dup.is_err(), "an accepted receipt_id must not be recordable twice");
}

// --- forward-only re-run / idempotency sanity ------------------------------

#[test]
fn migrate_is_idempotent_in_process() {
    // Mirrors lib.rs's `migrate_is_idempotent`, plus a ledger-stability check:
    // re-running migrate re-applies nothing (the non-idempotent ALTERs never re-run).
    let c = conn();
    let before = applied_versions(&c);
    db::migrate(&c).unwrap();
    db::migrate(&c).unwrap();
    assert_eq!(db::current_version(&c).unwrap(), db::SCHEMA_VERSION);
    assert_eq!(applied_versions(&c), before, "re-running migrate must not add ledger rows");
    assert_eq!(before.len(), 21);
}

#[test]
fn migrate_is_idempotent_across_a_real_file_reopen() {
    // The strongest forward-only check: persist to a file, drop the connection
    // (simulating app close), reopen, and confirm migrate is a clean no-op. If the
    // non-idempotent `ALTER TABLE`s (0007/0008/0012/0013) re-ran, the reopen would
    // error ("duplicate column"); a stable version proves they did not.
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("schema.db");
    let path = path.to_str().unwrap();

    {
        let c1 = db::open(path).unwrap();
        assert_eq!(db::current_version(&c1).unwrap(), 21);
    } // c1 dropped

    let c2 = db::open(path).unwrap(); // reopen re-runs migrate() (idempotent)
    assert_eq!(db::current_version(&c2).unwrap(), 21);
    assert_eq!(applied_versions(&c2), (1..=21).collect::<Vec<i64>>());
}
