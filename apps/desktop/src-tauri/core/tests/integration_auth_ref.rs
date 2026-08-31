//! Phase 9 — the Integrations credential fact, through the public repository surface only.
//!
//! The Integrations page reports four independent facts per connector, each allowed to
//! say "I don't know". This file covers exactly one of them — credential custody — and
//! the claim under test is deliberately small, because it is the only claim the desktop
//! can honestly make:
//!
//!   * a connector's `auth_ref` is a REFERENCE to a secret the engine or the operator
//!     holds; it is never the secret, and nothing here ever resolves, fetches, validates
//!     or transmits one;
//!   * "no reference" is a real, truthful state — the default for a new connector and the
//!     permanent state of every row written before schema 0022 — and it is `None`, never
//!     an empty string that a reader could mistake for a configured-but-blank reference;
//!   * a value that is not positively recognisable as a reference is REFUSED, and the
//!     refusal never echoes what was refused (an error message is a log line, and a log
//!     line holding a pasted password is the leak this column exists to avoid);
//!   * naming a reference changes nothing else: no probe ran, no service was contacted,
//!     the connector's status is untouched, and it comes no closer to `connected_verified`.
//!
//! What is NOT claimed anywhere: that the referenced secret exists, is valid, is the right
//! one, or is reachable. The desktop is on the far side of the Phase-9 trust boundary and
//! cannot know any of that.

use brops_core::{db, repo, CoreError, Integration};
use rusqlite::Connection;

fn conn() -> Connection {
    db::open_in_memory().expect("open in-memory")
}

fn a_connector(c: &Connection) -> Integration {
    repo::integrations::create(c, "Slack", "slack").expect("create connector")
}

/// Mint and natively confirm the T-052 grant `set_auth_ref` now requires, through the
/// real approval path -- `approvals::create` then `approve_confirmed`, exactly the two
/// calls `commands::confirm_approval` makes. One grant unlocks one write: `set_auth_ref`
/// consumes it in the same transaction, so a test that sets a reference twice must call
/// this twice, and that is the property under test rather than an inconvenience.
fn grant_auth_ref(c: &Connection, integration_id: &str) {
    let ap = repo::approvals::create(
        c,
        repo::approvals::INTEGRATION_AUTH_REF_ACTION_TYPE,
        "test connector",
        "A2",
        "medium",
        Some(repo::approvals::INTEGRATION_ENTITY_TYPE),
        Some(integration_id),
        "webview:test",
        "sess-test",
        &brops_core::id(),
        brops_core::repo::audit::Actor::local_operator(),
    )
    .expect("mint approval");
    repo::approvals::approve_confirmed(
        c,
        &ap.id,
        repo::approvals::NATIVE_CONFIRMER_PRINCIPAL,
        None,
        ap.nonce.as_deref().unwrap(),
        ap.request_digest.as_deref().unwrap(),
        brops_core::repo::audit::Actor::native_confirmer("native:test"),
    )
    .expect("native confirmation");
}

/// Everything an error message can reach: the rendered `Display` text.
fn message(e: &CoreError) -> String {
    e.to_string()
}

// --- a row with NO reference -----------------------------------------------

#[test]
fn a_new_connector_holds_no_reference_and_says_so() {
    let c = conn();
    let created = a_connector(&c);

    assert_eq!(created.auth_ref, None, "a new connector names no credential");
    assert_eq!(repo::integrations::get(&c, &created.id).unwrap().auth_ref, None);
    assert_eq!(repo::integrations::list(&c).unwrap()[0].auth_ref, None);

    // The renderer reads `record.authRef` and treats a non-string as "no reference"
    // (`credentialCustodyOf`). It must therefore arrive as JSON null under the camelCase
    // key — not as "", and not under some other name.
    let json = serde_json::to_value(&created).unwrap();
    assert!(json.get("authRef").is_some(), "the field must be serialized, not skipped");
    assert!(json["authRef"].is_null(), "no reference must be null, never an empty string");
}

#[test]
fn a_blank_value_written_out_of_band_still_reads_as_no_reference() {
    // The database file is not ours alone, and the reader must be defensive on its own
    // merits rather than leaning on the CHECK. First: a normal write of '' is refused.
    let c = conn();
    let created = a_connector(&c);
    c.execute("UPDATE integrations SET auth_ref = '' WHERE id = ?1", rusqlite::params![created.id])
        .expect_err("the 0022 CHECK must refuse '' on any ordinary write");

    // Now simulate a writer that does not honour the constraint at all — exactly the case
    // the reader exists for. An empty (or whitespace-only) column must surface as "no
    // reference", never as a present-but-blank one, because the Integrations page would
    // otherwise report a custody fact nothing supports.
    for blank in ["", "   "] {
        c.execute_batch("PRAGMA ignore_check_constraints = ON;").unwrap();
        c.execute(
            "UPDATE integrations SET auth_ref = ?1 WHERE id = ?2",
            rusqlite::params![blank, created.id],
        )
        .expect("the pragma should let an unconstrained writer through");
        c.execute_batch("PRAGMA ignore_check_constraints = OFF;").unwrap();

        let read_back = repo::integrations::get(&c, &created.id).unwrap();
        assert_eq!(read_back.auth_ref, None, "blank text is never a reference");
        let json = serde_json::to_value(&read_back).unwrap();
        assert!(json["authRef"].is_null(), "and it must reach the renderer as null");
    }
}

// --- a row WITH a reference ------------------------------------------------

#[test]
fn a_reference_round_trips_through_the_record() {
    let c = conn();
    let created = a_connector(&c);

    grant_auth_ref(&c, &created.id);
    let updated =
        repo::integrations::set_auth_ref(&c, &created.id, Some("engine:slack/bot-token"), brops_core::repo::audit::Actor::local_operator()).unwrap();
    assert_eq!(updated.auth_ref.as_deref(), Some("engine:slack/bot-token"));

    // ...and it is durable, not just returned.
    assert_eq!(
        repo::integrations::get(&c, &created.id).unwrap().auth_ref.as_deref(),
        Some("engine:slack/bot-token")
    );
    let json = serde_json::to_value(&updated).unwrap();
    assert_eq!(json["authRef"], "engine:slack/bot-token", "camelCase for the renderer");

    // Every documented scheme is accepted, and surrounding whitespace is trimmed rather
    // than stored (a stored " engine:x" would not equal the reference anyone named).
    for good in [
        "engine:slack/bot-token",
        "operator:helpdesk-api",
        "keychain:brops/github",
        "env:SLACK_BOT_TOKEN",
        "vault:kv/data/brops/smtp",
        "  engine:trimmed/ref  ",
    ] {
        grant_auth_ref(&c, &created.id);
        let r = repo::integrations::set_auth_ref(&c, &created.id, Some(good), brops_core::repo::audit::Actor::local_operator()).unwrap();
        assert_eq!(r.auth_ref.as_deref(), Some(good.trim()), "`{good}` must round-trip");
    }
}

#[test]
fn a_reference_can_be_cleared_back_to_no_reference() {
    let c = conn();
    let created = a_connector(&c);
    grant_auth_ref(&c, &created.id);
    repo::integrations::set_auth_ref(&c, &created.id, Some("vault:kv/data/brops/smtp"), brops_core::repo::audit::Actor::local_operator()).unwrap();

    // Clearing is a truthful state change, not an error — and both spellings of "clear"
    // (no value at all, and an empty box in the UI) mean the same thing.
    for clear in [None, Some(""), Some("   ")] {
        grant_auth_ref(&c, &created.id);
        repo::integrations::set_auth_ref(&c, &created.id, Some("engine:x/y"), brops_core::repo::audit::Actor::local_operator()).unwrap();
        // Clearing is gated too, so it needs its own grant: one approval, one write.
        grant_auth_ref(&c, &created.id);
        let cleared = repo::integrations::set_auth_ref(&c, &created.id, clear, brops_core::repo::audit::Actor::local_operator()).unwrap();
        assert_eq!(cleared.auth_ref, None, "clearing must yield no reference, not ''");
    }
}

// --- refusals: if it might be a secret, it is a secret ---------------------

#[test]
fn secret_shaped_and_malformed_values_are_refused() {
    let c = conn();
    let created = a_connector(&c);

    for bad in [
        "slack-bot-token",                          // no scheme — could be anything
        "azure:kv/foo",                             // a scheme this build does not know
        "engine:",                                  // nothing after the scheme
        "engine:has space",                         // whitespace never appears in a reference
        "engine:tok=en",                            // '=' — base64 padding
        "engine:eyJhbGciOiJIUzI1NiJ9.e30.signature", // a JWT
        "engine:sk-ant-api03-AAAABBBBCCCCDDDD",     // an API key
        "engine:ghp_AAAABBBBCCCCDDDDEEEEFFFF",      // a GitHub token
        "engine:github_pat_11AAAA_bbbbcccc",        // a fine-grained GitHub PAT
        "engine:xoxb-1111-2222-abcdefghij",         // a Slack bot token
        "engine:AKIAIOSFODNN7EXAMPLE",              // an AWS access key id
        "vault:AIzaSyA00000000000000000000",        // a Google API key
        "operator:-----BEGINPRIVATEKEY",            // PEM armor
        "engine:naïve/ref",                         // outside the reference alphabet
        "e:x",                                      // too short to be a scheme we know
    ] {
        let err = match repo::integrations::set_auth_ref(&c, &created.id, Some(bad), brops_core::repo::audit::Actor::local_operator()) {
            Ok(_) => panic!("`{bad}` must be refused"),
            Err(e) => e,
        };
        match &err {
            CoreError::Invalid { field, .. } => assert_eq!(*field, "auth_ref"),
            other => panic!("`{bad}` refused with the wrong error: {other}"),
        }
        // THE POINT: the refusal must not repeat the thing it refused. If that was a
        // pasted credential, echoing it into an error string — which travels to the
        // renderer and into logs — would be the exact leak being prevented.
        assert!(
            !message(&err).contains(bad),
            "the refusal for `{bad}` echoed the rejected value: {}",
            message(&err)
        );
        assert!(
            message(&err).contains("<withheld>"),
            "a refusal must say the value is withheld, not print it"
        );
    }

    // A key-sized blob does not fit at all.
    let blob = format!("engine:{}", "a".repeat(400));
    assert!(repo::integrations::set_auth_ref(&c, &created.id, Some(&blob), brops_core::repo::audit::Actor::local_operator()).is_err());

    // And after all of that, the record still holds nothing.
    assert_eq!(repo::integrations::get(&c, &created.id).unwrap().auth_ref, None);
}

#[test]
fn the_documented_limit_is_real_a_wellformed_reference_may_still_be_a_secret() {
    // Asserted so nobody mistakes shape-checking for secret detection. `engine:hunter2`
    // is a perfectly well-formed reference AND a perfectly good password; neither the
    // CHECK nor the Rust validator can tell which it is, and both accept it. The rule
    // that keeps credentials out is the one outside this file: they must never arrive.
    let c = conn();
    let created = a_connector(&c);
    grant_auth_ref(&c, &created.id);
    let r = repo::integrations::set_auth_ref(&c, &created.id, Some("engine:hunter2"), brops_core::repo::audit::Actor::local_operator()).unwrap();
    assert_eq!(r.auth_ref.as_deref(), Some("engine:hunter2"));
}

// --- the write is bounded: it records intent and nothing else --------------

#[test]
fn setting_a_reference_audits_the_event_but_never_the_reference() {
    let c = conn();
    let created = a_connector(&c);
    let secret_looking = "vault:kv/data/brops/smtp";
    grant_auth_ref(&c, &created.id);
    repo::integrations::set_auth_ref(&c, &created.id, Some(secret_looking), brops_core::repo::audit::Actor::local_operator()).unwrap();
    grant_auth_ref(&c, &created.id);
    repo::integrations::set_auth_ref(&c, &created.id, None, brops_core::repo::audit::Actor::local_operator()).unwrap();

    let events: Vec<String> = c
        .prepare("SELECT event_type FROM audit_events WHERE entity_id = ?1 ORDER BY created_at, id")
        .unwrap()
        .query_map(rusqlite::params![created.id], |r| r.get(0))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    assert!(events.contains(&"integration.auth_ref_set".to_string()));
    assert!(events.contains(&"integration.auth_ref_cleared".to_string()));

    // The audit log records THAT a reference was set, for WHICH connector — and nothing
    // about the reference itself.
    let leaked: i64 = c
        .query_row(
            "SELECT count(*) FROM audit_events
              WHERE event_type LIKE ?1 OR actor_id LIKE ?1 OR entity_type LIKE ?1 OR entity_id LIKE ?1",
            rusqlite::params![format!("%{secret_looking}%")],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(leaked, 0, "no audit column may contain the reference text");
}

#[test]
fn naming_a_reference_does_not_connect_anything() {
    // Credential custody and reachability are independent facts. Recording where a secret
    // lives contacts nothing, proves nothing, and must not move the connector's status —
    // the only input to enablement, and one of the two things `connected_verified` needs.
    let c = conn();
    let created = a_connector(&c);
    assert_eq!(created.status, "disconnected");

    grant_auth_ref(&c, &created.id);
    let after =
        repo::integrations::set_auth_ref(&c, &created.id, Some("engine:slack/bot-token"), brops_core::repo::audit::Actor::local_operator()).unwrap();
    assert_eq!(after.status, "disconnected", "a reference must not enable a connector");
    assert_eq!(after.provider, created.provider);
    assert_eq!(after.name, created.name);
    assert_eq!(after.created_at, created.created_at);
}

#[test]
fn setting_a_reference_on_an_unknown_connector_is_not_found() {
    let c = conn();
    let err = repo::integrations::set_auth_ref(&c, "no-such-connector", Some("engine:x/y"), brops_core::repo::audit::Actor::local_operator())
        .expect_err("an unknown connector must not be silently created");
    assert!(matches!(err, CoreError::NotFound(_)), "got {err}");

    // A refusal is decided BEFORE the row is looked up only when the value is bad — an
    // invalid reference for an unknown connector is still an `auth_ref` refusal, and
    // still says nothing about the value.
    let err = repo::integrations::set_auth_ref(&c, "no-such-connector", Some("sk-live-AAAABBBB"), brops_core::repo::audit::Actor::local_operator())
        .expect_err("a secret-shaped value must be refused");
    assert!(matches!(err, CoreError::Invalid { field: "auth_ref", .. }), "got {err}");
    assert!(!message(&err).contains("sk-live-AAAABBBB"));
}
