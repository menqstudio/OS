//! §4's credential binding store — a store of REFERENCES, and the reason it is
//! not a store of values.
//!
//! # What this holds, and the instruction that was withdrawn
//!
//! An `auth_ref`: a name/handle/path that the ENGINE or the OPERATOR resolves,
//! on the other side of the trust boundary, to a secret **they** hold —
//! `engine:slack/bot-token`, `operator:helpdesk-api`, `keychain:brops/github`,
//! `env:SLACK_BOT_TOKEN`, `vault:kv/data/brops/smtp#password`.
//!
//! The first version of this module held the value. It said so plainly, in
//! three places, that the bytes sat in plaintext in the desktop's own SQLite
//! file — the disclosure was honest and the design was wrong. Migration 0022
//! had already settled the question for this whole process:
//!
//! > nothing in this table, this process, or this repository may ever hold the
//! > secret. The desktop is deliberately on the untrusted side of the boundary;
//! > a credential that got here would be a credential leaked.
//!
//! A second table holding what the first forbids is not a smaller version of
//! that decision, and a well-documented leak is still a leak. So there is no
//! `Secret` type here, no column that could hold one, and no function that
//! could read one: the type that existed to keep a value from escaping is gone
//! because the value never arrives.
//!
//! # The agent never holds the secret — now structurally, not by discipline
//!
//! A flow step names a **slot**. The bundle, the flow, the grant, the receipt,
//! the audit payload and every refusal string carry the slot NAME. They cannot
//! carry a value, because no value exists on this side to carry.
//!
//! # One rule, one implementation
//!
//! [`bind`] refuses anything `repo::integrations::normalize_auth_ref` does not
//! positively recognise as a reference — the same function the Integrations
//! page uses, not a copy of it — and the schema states the same rule again as a
//! CHECK. Neither can tell a reference from a password (`engine:hunter2` is
//! both); what protects the boundary is refusing anything not recognisable as a
//! reference, plus the standing rule that a credential must never arrive at
//! this process at all.
//!
//! # Born unbound
//!
//! `agent_runs::register` writes no bindings, exactly as it arms nothing.
//! Binding is [`bind`], a separate act behind a natively confirmed grant, with
//! its own audit record. Unbinding is [`unbind`] and is deliberately UNGATED —
//! removing a credential reference is a safety control, and an approval
//! ceremony in front of one is a denial of service on the operator, the same
//! asymmetry `automations::set_enabled` and `agent_runs::set_active` carry.

use rusqlite::{Connection, OptionalExtension};

use crate::{CoreError, CoreResult, repo::approvals, repo::audit};

/// Stated, not implied. In the design and NOT in this slice.
pub const NOT_IMPLEMENTED: &[&str] = &[
    "resolution: nothing here turns a reference into a secret, and nothing here \
     may — that happens on the other side of the trust boundary, in the engine \
     or in the operator's own hands",
    "proof that a reference is TRUE: a stored `auth_ref` records an INTENDED \
     handoff target. It does not prove the secret exists, is valid, is \
     reachable, or is the right one",
    "rotation: rebuilding the agent breaks the binding by design, and nothing \
     re-binds automatically — that is the gated act, on purpose",
    "the TRANSPORT that would carry a reference across the boundary: no call \
     leaves this box, so nothing yet asks for one",
];

/// The approval tuple one binding needs. The entity id is
/// `<bundle_digest>:<slot_id>` so a grant minted for one slot of one build can
/// never bind a different slot, or the same slot of a different build.
pub fn approval_entity_id(bundle_digest: &str, slot_id: &str) -> String {
    format!("{bundle_digest}:{slot_id}")
}

/// Bind a REFERENCE to (bundle_digest, slot_id). Requires and CONSUMES a
/// natively confirmed grant for that exact pair.
///
/// `auth_ref` is normalized by the same function the Integrations page uses and
/// refused if it is not positively recognisable as a reference. A refusal never
/// echoes what was refused: if the caller has just handed us a password by
/// mistake, repeating it back into an error message that travels to the
/// renderer and into logs is precisely the leak this design exists to avoid.
///
/// An empty or whitespace-only `auth_ref` is REFUSED rather than treated as a
/// clear. Removing a binding is [`unbind`], which is a different act with a
/// different audit record, and letting one call mean either would make "the
/// operator revoked this" indistinguishable from "the operator submitted a
/// blank form".
pub fn bind(
    conn: &Connection,
    bundle_digest: &str,
    slot_id: &str,
    auth_ref: &str,
    actor: audit::Actor<'_>,
) -> CoreResult<()> {
    let reference = match crate::repo::integrations::normalize_auth_ref(Some(auth_ref))? {
        Some(r) => r,
        None => {
            return Err(CoreError::Invalid {
                field: "auth_ref",
                value: "<withheld> (a binding must name a reference; to remove one, unbind)"
                    .to_string(),
            });
        }
    };
    let entity = approval_entity_id(bundle_digest, slot_id);
    crate::repo::atomic(conn, |tx| {
        approvals::require_and_consume(
            tx,
            &entity,
            approvals::CREDENTIAL_BINDING_ENTITY_TYPE,
            approvals::CREDENTIAL_BIND_ACTION_TYPE,
        )?;
        tx.execute(
            "INSERT OR REPLACE INTO credential_bindings(bundle_digest, slot_id, auth_ref, bound_at) \
             VALUES (?1,?2,?3,?4)",
            rusqlite::params![bundle_digest, slot_id, reference, crate::now()],
        )?;
        // The SLOT, never the reference. `entity` carries the digest and the
        // slot and nothing else — a reference is not a secret, but it is also
        // not something an audit row needs, and the narrowest row is the one
        // that cannot be wrong later.
        audit::record(tx, "credential.bound", actor, "credential_binding", &entity)?;
        Ok(())
    })
}

/// Remove a binding. NOT gated, deliberately — see the module docs.
pub fn unbind(
    conn: &Connection,
    bundle_digest: &str,
    slot_id: &str,
    actor: audit::Actor<'_>,
) -> CoreResult<()> {
    let entity = approval_entity_id(bundle_digest, slot_id);
    crate::repo::atomic(conn, |tx| {
        tx.execute(
            "DELETE FROM credential_bindings WHERE bundle_digest = ?1 AND slot_id = ?2",
            rusqlite::params![bundle_digest, slot_id],
        )?;
        audit::record(tx, "credential.unbound", actor, "credential_binding", &entity)?;
        Ok(())
    })
}

/// Does a binding exist? Answers the question a RECEIPT needs — "has the
/// operator provided this credential" — without reading the reference.
pub fn is_bound(conn: &Connection, bundle_digest: &str, slot_id: &str) -> CoreResult<bool> {
    let n: i64 = conn.query_row(
        "SELECT COUNT(*) FROM credential_bindings WHERE bundle_digest = ?1 AND slot_id = ?2",
        rusqlite::params![bundle_digest, slot_id],
        |r| r.get(0),
    )?;
    Ok(n > 0)
}

/// Read the bound REFERENCE — the string that names where the secret lives, on
/// the other side of the boundary.
///
/// This is not `resolve`: it resolves nothing, and what it returns is not a
/// credential. It has no production caller yet and is declared caller-less in
/// `config/reachability-declarations.json`, because the transport that would
/// carry a reference across the boundary does not exist and a `call` step is
/// still refused. Flip that declaration to `must_have_caller` in the same
/// commit that adds the transport.
pub fn reference_of(
    conn: &Connection,
    bundle_digest: &str,
    slot_id: &str,
) -> CoreResult<Option<String>> {
    Ok(conn
        .query_row(
            "SELECT auth_ref FROM credential_bindings WHERE bundle_digest = ?1 AND slot_id = ?2",
            rusqlite::params![bundle_digest, slot_id],
            |r| r.get(0),
        )
        .optional()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A well-formed reference, used wherever a test needs one that is not the
    /// subject of the test.
    const REF: &str = "engine:slack/bot-token";

    fn fixture() -> (Connection, String) {
        let conn = crate::db::open_in_memory().unwrap();
        let digest = "d".repeat(64);
        conn.execute(
            "INSERT INTO agent_bundles(bundle_digest, bundle_id, bundle_version, display_name, \
             built_at, state, created_at) VALUES (?1,'agt-t',1,'T',?2,'built',?2)",
            rusqlite::params![digest, crate::now()],
        )
        .unwrap();
        (conn, digest)
    }

    fn grant_for(conn: &Connection, digest: &str, slot: &str) {
        let entity = approval_entity_id(digest, slot);
        let ap = approvals::create(
            conn, approvals::CREDENTIAL_BIND_ACTION_TYPE, "T", "A2", "medium",
            Some(approvals::CREDENTIAL_BINDING_ENTITY_TYPE), Some(&entity),
            "webview:test", "sess-test", &crate::id(),
            audit::Actor::local_operator(),
        )
        .unwrap();
        approvals::approve_confirmed(
            conn, &ap.id, approvals::NATIVE_CONFIRMER_PRINCIPAL, None,
            ap.nonce.as_deref().unwrap(), ap.request_digest.as_deref().unwrap(),
            audit::Actor::native_confirmer("native:test"),
        )
        .unwrap();
    }

    /// BORN UNBOUND, and binding without a confirmed grant is refused.
    #[test]
    fn binding_without_a_confirmed_grant_is_refused() {
        let (conn, digest) = fixture();
        assert!(!is_bound(&conn, &digest, "slack_bot").unwrap(), "born unbound");
        let refused = bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator());
        assert!(refused.is_err(), "binding must require a grant");
        assert!(!is_bound(&conn, &digest, "slack_bot").unwrap());
    }

    /// And with one, it binds — so the refusal above is not a check that cannot
    /// pass. What comes back is the REFERENCE, byte-for-byte.
    #[test]
    fn binding_with_a_confirmed_grant_stores_the_reference() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator()).unwrap();
        assert!(is_bound(&conn, &digest, "slack_bot").unwrap());
        assert_eq!(reference_of(&conn, &digest, "slack_bot").unwrap().as_deref(), Some(REF));
    }

    /// The decisive one: this store REFUSES a secret. Each of these is refused
    /// for its own reason, and the message never echoes what was refused —
    /// repeating a mistakenly-pasted password back into an error that reaches
    /// the renderer and the logs is the leak the whole design avoids.
    #[test]
    fn a_secret_shaped_value_is_refused_and_never_echoed() {
        let (conn, digest) = fixture();
        // Assembled with `concat!` rather than written out: GitHub's push
        // protection reads a token-shaped LITERAL as a token and refuses the
        // push, and a repository that cannot accept a test for refusing
        // credentials is worse off than one whose fixture is spelled in two
        // pieces. Nothing here is a real credential; each is shaped like one.
        for (bad, why) in [
            (concat!("xoxb", "-1234567890-abcdefghijklmnop"), "a bare Slack token: no scheme"),
            (concat!("engine:xoxb", "-1234567890-abcdef"), "recognised key material after a valid scheme"),
            (concat!("engine:sk", "-abcdefghijklmnopqrstuvwxyz"), "an OpenAI-style key after a valid scheme"),
            ("hunter2", "no scheme at all"),
            ("nosuchscheme:thing", "a scheme this build does not know"),
            ("engine:", "an empty locator"),
            (concat!("-----BEGIN", " RSA PRIVATE KEY-----"), "PEM armor, and whitespace besides"),
        ] {
            grant_for(&conn, &digest, "slack_bot");
            let err = bind(&conn, &digest, "slack_bot", bad, audit::Actor::local_operator())
                .expect_err(&format!("must refuse: {why}"));
            let shown = format!("{err:?}");
            assert!(!shown.contains(bad), "the refusal echoed the input ({why}): {shown}");
            assert!(shown.contains("withheld"), "({why}) {shown}");
            assert!(
                !is_bound(&conn, &digest, "slack_bot").unwrap(),
                "a refused bind must store nothing ({why})"
            );
        }
    }

    /// An empty reference is a REFUSAL, not a clear. "The operator revoked
    /// this" and "the operator submitted a blank form" must not be the same
    /// call.
    #[test]
    fn an_empty_reference_is_refused_rather_than_treated_as_a_clear() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator()).unwrap();
        grant_for(&conn, &digest, "slack_bot");
        let refused = bind(&conn, &digest, "slack_bot", "   ", audit::Actor::local_operator());
        assert!(refused.is_err(), "an empty reference must not clear the binding");
        assert!(is_bound(&conn, &digest, "slack_bot").unwrap(), "and must not remove it");
    }

    /// One grant unlocks ONE binding. The second bind must be refused, or an
    /// approval would be a standing permission rather than a single act.
    #[test]
    fn a_grant_is_consumed_and_does_not_bind_twice() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator()).unwrap();
        let again = bind(&conn, &digest, "slack_bot", "engine:other/token", audit::Actor::local_operator());
        assert!(again.is_err(), "a consumed grant must not bind again");
        assert_eq!(reference_of(&conn, &digest, "slack_bot").unwrap().as_deref(), Some(REF));
    }

    /// A grant for ONE slot must not bind another. The entity id carries both
    /// the digest and the slot for exactly this reason.
    #[test]
    fn a_grant_for_one_slot_does_not_bind_a_different_one() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        let wrong = bind(&conn, &digest, "crm_token", REF, audit::Actor::local_operator());
        assert!(wrong.is_err(), "a slot's grant is that slot's alone");
    }

    /// UNBINDING is not gated: it is the operator's stop button.
    #[test]
    fn unbinding_needs_no_grant() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator()).unwrap();
        unbind(&conn, &digest, "slack_bot", audit::Actor::local_operator()).unwrap();
        assert!(!is_bound(&conn, &digest, "slack_bot").unwrap());
        assert!(reference_of(&conn, &digest, "slack_bot").unwrap().is_none());
    }

    /// `is_bound` answers about ONE slot. T-061's V-1: the slot half of its
    /// predicate was asserted by nothing — every other test varies the digest,
    /// so `WHERE slot_id = ?2` could have been dropped and stayed green, and a
    /// receipt would then say `present` for a slot nobody bound.
    #[test]
    fn is_bound_answers_about_the_slot_it_was_asked_about() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator()).unwrap();
        assert!(is_bound(&conn, &digest, "slack_bot").unwrap());
        assert!(!is_bound(&conn, &digest, "crm_token").unwrap(),
                "a binding on one slot must not answer for another");
        assert!(reference_of(&conn, &digest, "crm_token").unwrap().is_none());
    }

    /// Binding is to the DIGEST. A different build shares nothing.
    #[test]
    fn a_binding_does_not_reach_a_different_build() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator()).unwrap();
        let other = "e".repeat(64);
        assert!(!is_bound(&conn, &other, "slack_bot").unwrap(),
                "rebuilding an agent must break every binding it had");
        assert!(reference_of(&conn, &other, "slack_bot").unwrap().is_none());
    }

    /// An audit row for a binding names the slot, and carries neither the
    /// reference nor anything derived from it.
    #[test]
    fn the_audit_row_names_the_slot_and_never_the_reference() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator()).unwrap();
        let (etype, eid): (String, String) = conn
            .query_row(
                "SELECT entity_type, entity_id FROM audit_events WHERE event_type='credential.bound'",
                [], |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(etype, "credential_binding");
        assert!(eid.contains("slack_bot"));
        assert!(!eid.contains("bot-token"), "the audit row must not carry the reference");
        let any_ref: i64 = conn
            .query_row("SELECT COUNT(*) FROM audit_events WHERE COALESCE(payload_json,'') LIKE '%bot-token%'",
                       [], |r| r.get(0))
            .unwrap();
        assert_eq!(any_ref, 0, "no audit payload may contain the reference");
    }

    /// Retiring the bundle takes its bindings with it: a reference nothing can
    /// reach is a stale pointer at best and a misleading custody claim at worst.
    #[test]
    fn deleting_the_bundle_deletes_its_bindings() {
        let (conn, digest) = fixture();
        grant_for(&conn, &digest, "slack_bot");
        bind(&conn, &digest, "slack_bot", REF, audit::Actor::local_operator()).unwrap();
        conn.execute("DELETE FROM agent_bundles WHERE bundle_digest = ?1", [&digest]).unwrap();
        assert!(!is_bound(&conn, &digest, "slack_bot").unwrap());
    }

    /// What this module does NOT do is stated, not implied — including the one
    /// that matters most: it does not resolve anything.
    #[test]
    fn the_boundary_of_this_slice_is_stated() {
        assert!(NOT_IMPLEMENTED.iter().any(|s| s.contains("resolution")));
        assert!(NOT_IMPLEMENTED.iter().any(|s| s.contains("rotation")));
        assert!(NOT_IMPLEMENTED.iter().any(|s| s.contains("TRANSPORT")));
    }
}
