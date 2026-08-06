//! The additive demonstration-verified badge derives ONLY from a real recorded row (0018) and never
//! collides with the production trust records. Proves the end-to-end DB behaviour the desktop relies on.

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
    let conv = repo::chat::create_conversation(&c, "direct", "Bro").expect("conversation");
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
    repo::chat::record_demonstration_verified(&c, &m.id).expect("record demonstration-verified");
    assert_eq!(
        receipt_of(&c, &conv.id, &m.id).as_deref(),
        Some("demonstration_verified"),
        "the badge derives to demonstration_verified after recording",
    );

    // Idempotent: recording again does not error or change the derived badge.
    repo::chat::record_demonstration_verified(&c, &m.id).expect("idempotent record");
    assert_eq!(receipt_of(&c, &conv.id, &m.id).as_deref(), Some("demonstration_verified"));
}

#[test]
fn post_message_demonstration_verified_posts_and_badges_atomically() {
    let c = db::open_in_memory().expect("open migrated db");
    let conv = repo::chat::create_conversation(&c, "direct", "Bro").expect("conversation");

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
