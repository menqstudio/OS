//! The additive demonstration-verified badge derives ONLY from a recorded row that carries the SHA-256
//! of the body it is painted on (0018 + 0024), and never collides with the production trust records.
//! Proves the end-to-end DB behaviour the desktop relies on.

use brops_core::db;
use brops_core::domain::NewMessage;
use brops_core::repo;

fn receipt_of(conn: &rusqlite::Connection, conv_id: &str, msg_id: &str) -> Option<String> {
    repo::chat::list_messages(conn, conv_id, None, None)
        .expect("list messages")
        .into_iter()
        .find(|m| m.id == msg_id)
        .expect("message present")
        .receipt
}

#[test]
fn demonstration_verified_badge_derives_from_the_recorded_row_only() {
    let c = db::open_in_memory().expect("open migrated db");
    let conv = repo::chat::create_conversation(&c, "direct", "Bro", brops_core::repo::audit::Actor::local_operator()).expect("conversation");
    let m = repo::chat::post_message(
        &c,
        NewMessage {
            conversation_id: conv.id.clone(),
            role: "agent".to_string(),
            author: "Bro".to_string(),
            body: "the reply the in-process chain produced + verified".to_string(),
        },
    )
    .expect("post message");

    // Before any record, the message carries NO badge (no production receipt, no demonstration row).
    assert_eq!(receipt_of(&c, &conv.id, &m.id), None, "no badge before recording");

    // Recording (only done by the desktop AFTER the in-process chain verifies) makes the projection derive
    // the honest demonstration badge — a distinct value, never production trusted_verified.
    repo::chat::record_demonstration_verified(
        &c,
        &m.id,
        "the reply the in-process chain produced + verified",
    )
    .expect("record demonstration-verified");
    assert_eq!(
        receipt_of(&c, &conv.id, &m.id).as_deref(),
        Some("demonstration_verified"),
        "the badge derives to demonstration_verified after recording",
    );

    // Idempotent: recording again does not error or change the derived badge.
    repo::chat::record_demonstration_verified(
        &c,
        &m.id,
        "the reply the in-process chain produced + verified",
    )
    .expect("idempotent record");
    assert_eq!(receipt_of(&c, &conv.id, &m.id).as_deref(), Some("demonstration_verified"));
}

#[test]
fn post_message_demonstration_verified_posts_and_badges_atomically() {
    let c = db::open_in_memory().expect("open migrated db");
    let conv = repo::chat::create_conversation(&c, "direct", "Bro", brops_core::repo::audit::Actor::local_operator()).expect("conversation");

    // The combined writer returns the message already carrying the demonstration badge — the reply and
    // its anchor are committed in one transaction, so the returned Message is immediately consistent.
    let m = repo::chat::post_message_demonstration_verified(
        &c,
        NewMessage {
            conversation_id: conv.id.clone(),
            role: "agent".to_string(),
            author: "Bro".to_string(),
            body: "verified reply bytes".to_string(),
        },
    )
    .expect("post + record atomically");
    assert_eq!(m.receipt.as_deref(), Some("demonstration_verified"), "returned message is badged");
    // And a fresh read derives the same badge (the anchor row was really committed).
    assert_eq!(receipt_of(&c, &conv.id, &m.id).as_deref(), Some("demonstration_verified"));
}

/// A demonstration row that does NOT carry the digest of the body it sits on paints no badge.
///
/// This is the shape the table had before migration 0024 and the shape every row written before it
/// still has: `(message_id, recorded_at)` and nothing else. The command that writes these deletes the
/// chain's working directory on its way out, so the receipt, envelope and signature that justified
/// the green are gone; if the row alone were enough, the only green badge the shipped app can display
/// would rest on the existence of two columns. It is not enough.
#[test]
fn a_flag_row_with_no_body_digest_paints_no_badge() {
    let c = db::open_in_memory().expect("open migrated db");
    let conv = repo::chat::create_conversation(&c, "direct", "Bro", brops_core::repo::audit::Actor::local_operator()).expect("conversation");
    let m = repo::chat::post_message(
        &c,
        NewMessage {
            conversation_id: conv.id.clone(),
            role: "agent".to_string(),
            author: "Bro".to_string(),
            body: "a reply nobody verified".to_string(),
        },
    )
    .expect("post message");

    // Exactly what 0018 wrote, and exactly what a pre-0024 database still holds.
    c.execute(
        "INSERT INTO demonstration_verified_messages(message_id, recorded_at) VALUES (?1, '0')",
        [&m.id],
    )
    .expect("plant a bare flag row");

    assert_eq!(
        receipt_of(&c, &conv.id, &m.id),
        None,
        "a badge with no digest behind it must not be painted",
    );
}

/// The digest must cover THIS body. A row whose digest was earned over other bytes — a row pointed at
/// the wrong message, or a body that changed after the fact — paints nothing.
#[test]
fn a_body_digest_that_covers_other_bytes_paints_no_badge() {
    let c = db::open_in_memory().expect("open migrated db");
    let conv = repo::chat::create_conversation(&c, "direct", "Bro", brops_core::repo::audit::Actor::local_operator()).expect("conversation");
    let m = repo::chat::post_message(
        &c,
        NewMessage {
            conversation_id: conv.id.clone(),
            role: "agent".to_string(),
            author: "Bro".to_string(),
            body: "the text on screen".to_string(),
        },
    )
    .expect("post message");

    // The chain verified something else entirely.
    repo::chat::record_demonstration_verified(&c, &m.id, "the text the chain actually verified")
        .expect("record");

    assert_eq!(
        receipt_of(&c, &conv.id, &m.id),
        None,
        "the badge must not survive a digest that does not cover the displayed body",
    );

    // Sanity, so the test above cannot pass merely because nothing ever badges: the same row with the
    // right bytes DOES badge.
    c.execute("DELETE FROM demonstration_verified_messages WHERE message_id = ?1", [&m.id])
        .expect("clear");
    repo::chat::record_demonstration_verified(&c, &m.id, "the text on screen").expect("record");
    assert_eq!(receipt_of(&c, &conv.id, &m.id).as_deref(), Some("demonstration_verified"));
}
