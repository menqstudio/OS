//! BroPS local data core: SQLite schema, forward-only migrations, and typed
//! repositories. This crate is UI- and Tauri-independent so it can be built and
//! tested on its own (`cargo test -p brops-core`).

pub mod db;
pub mod domain;
pub mod repo;

pub use domain::{
    ActivityEvent, Agent, Approval, Automation, Conversation, CoreError, CoreResult, Decision,
    Event, Integration, KnowledgeNote, Message, MemoryEntry, Metric, NewAutomation, NewEvent,
    NewKnowledgeNote, NewMemoryEntry, NewMessage, NewProject, NewTask, Notification, Project, Run,
    RunStep, SearchResult, SecuritySummary, Task,
};

/// A new UUID v4 string. IDs are opaque text everywhere in the schema.
pub fn id() -> String {
    uuid::Uuid::new_v4().to_string()
}

/// Current timestamp as milliseconds since the Unix epoch, rendered as text.
/// The fixed 13-digit width keeps lexicographic `ORDER BY … DESC` correct (all
/// timestamp columns store this same format — never mix in ISO-8601 text).
pub fn now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    ms.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn conn() -> rusqlite::Connection {
        db::open_in_memory().expect("open in-memory")
    }

    #[test]
    fn migrate_is_idempotent() {
        let c = conn();
        db::migrate(&c).unwrap();
        db::migrate(&c).unwrap();
        assert_eq!(db::current_version(&c).unwrap(), db::SCHEMA_VERSION);
    }

    #[test]
    fn project_and_task_crud() {
        let c = conn();
        let p = repo::projects::create(
            &c,
            NewProject { name: "Foundation".into(), description: "".into(), priority: "high".into(), workspace_id: None },
        )
        .unwrap();
        assert_eq!(p.status, "planned");

        let t = repo::tasks::create(
            &c,
            NewTask { project_id: Some(p.id.clone()), title: "Build shell".into(), description: "".into(), priority: "normal".into(), assigned_agent_id: None },
        )
        .unwrap();
        assert_eq!(t.status, "inbox");
        assert_eq!(repo::tasks::list_by_project(&c, &p.id).unwrap().len(), 1);

        let done = repo::tasks::set_status(&c, &t.id, "done").unwrap();
        assert_eq!(done.status, "done");
        assert!(done.completed_at.is_some());
        assert_eq!(repo::tasks::list_by_status(&c, "done").unwrap().len(), 1);
    }

    #[test]
    fn task_update_and_list_all() {
        let c = conn();
        let p = repo::projects::create(
            &c,
            NewProject { name: "P".into(), description: "".into(), priority: "low".into(), workspace_id: None },
        ).unwrap();
        let t = repo::tasks::create(
            &c,
            NewTask { project_id: Some(p.id.clone()), title: "orig".into(), description: "".into(), priority: "low".into(), assigned_agent_id: None },
        ).unwrap();
        let up = repo::tasks::update(&c, &t.id, "new title", "a desc", "high").unwrap();
        assert_eq!(up.title, "new title");
        assert_eq!(up.description, "a desc");
        assert_eq!(up.priority, "high");
        assert!(matches!(
            repo::tasks::update(&c, &t.id, "x", "y", "bogus"),
            Err(CoreError::Invalid { field: "priority", .. })
        ));
        assert_eq!(repo::tasks::list_all(&c).unwrap().len(), 1);
    }

    #[test]
    fn task_dependencies_add_list_remove_and_guards() {
        let c = conn();
        let mk = |title: &str| repo::tasks::create(
            &c,
            NewTask { project_id: None, title: title.into(), description: "".into(), priority: "normal".into(), assigned_agent_id: None },
        ).unwrap();
        let a = mk("A");
        let b = mk("B");

        // A depends on B
        repo::task_deps::add(&c, &a.id, &b.id).unwrap();
        let deps = repo::task_deps::list_for(&c, &a.id).unwrap();
        assert_eq!(deps.len(), 1);
        assert_eq!(deps[0].id, b.id);

        // idempotent
        repo::task_deps::add(&c, &a.id, &b.id).unwrap();
        assert_eq!(repo::task_deps::list_for(&c, &a.id).unwrap().len(), 1);

        // self-edge refused
        assert!(matches!(
            repo::task_deps::add(&c, &a.id, &a.id),
            Err(CoreError::Invalid { field: "depends_on_id", .. })
        ));
        // direct cycle refused (B already depends on A? no — A depends on B, so B→A is a cycle)
        assert!(matches!(
            repo::task_deps::add(&c, &b.id, &a.id),
            Err(CoreError::Invalid { field: "depends_on_id", .. })
        ));

        // transitive cycle refused: A→B, B→C already; C→A must be rejected
        let cc = mk("C");
        repo::task_deps::add(&c, &b.id, &cc.id).unwrap(); // B depends on C
        assert!(matches!(
            repo::task_deps::add(&c, &cc.id, &a.id), // C→A would close A→B→C→A
            Err(CoreError::Invalid { field: "depends_on_id", .. })
        ));
        repo::task_deps::remove(&c, &b.id, &cc.id).unwrap();

        // removing the edge, then deleting a task cascades
        repo::task_deps::remove(&c, &a.id, &b.id).unwrap();
        assert_eq!(repo::task_deps::list_for(&c, &a.id).unwrap().len(), 0);
    }

    #[test]
    fn foreign_keys_enforced() {
        let c = conn();
        let err = repo::tasks::create(
            &c,
            NewTask { project_id: Some("does-not-exist".into()), title: "orphan".into(), description: "".into(), priority: "low".into(), assigned_agent_id: None },
        );
        assert!(err.is_err(), "task with unknown project_id must be rejected by FK");
    }

    #[test]
    fn invalid_priority_rejected() {
        let c = conn();
        let err = repo::projects::create(
            &c,
            NewProject { name: "x".into(), description: "".into(), priority: "bogus".into(), workspace_id: None },
        );
        assert!(matches!(err, Err(CoreError::Invalid { field: "priority", .. })));
    }

    #[test]
    fn invalid_status_transition_rejected() {
        let c = conn();
        let p = repo::projects::create(
            &c,
            NewProject { name: "x".into(), description: "".into(), priority: "low".into(), workspace_id: None },
        )
        .unwrap();
        assert!(repo::projects::set_status(&c, &p.id, "not-a-status").is_err());
    }

    #[test]
    fn migrations_reach_latest_with_all_tables() {
        let c = conn();
        assert_eq!(db::current_version(&c).unwrap(), db::SCHEMA_VERSION);
        // decisions table exists and is usable
        repo::decisions::create(&c, "T", "gev", "why").unwrap();
        assert_eq!(repo::decisions::list(&c).unwrap().len(), 1);
        // conversations table exists and is usable
        let conv = repo::chat::create_conversation(&c, "direct", "Bro").unwrap();
        assert_eq!(conv.message_count, 0);
        // knowledge + memory tables exist and are usable
        repo::knowledge::create(&c, NewKnowledgeNote { title: "K".into(), body: "".into(), source: "".into(), tags: "".into() }).unwrap();
        assert_eq!(repo::knowledge::list(&c).unwrap().len(), 1);
        repo::memory::create(&c, NewMemoryEntry { scope: "global".into(), kind: "note".into(), content: "M".into() }).unwrap();
        assert_eq!(repo::memory::list(&c, None).unwrap().len(), 1);
        // runs / events / automations / integrations tables exist and are usable
        repo::runs::create(&c, "intent", "").unwrap();
        assert_eq!(repo::runs::list(&c).unwrap().len(), 1);
        repo::events::create(&c, NewEvent { title: "E".into(), kind: "event".into(), location: "".into(), starts_at: "1".into(), ends_at: None }).unwrap();
        assert_eq!(repo::events::list(&c).unwrap().len(), 1);
        repo::automations::create(&c, NewAutomation { name: "A".into(), trigger: "".into(), action: "".into() }).unwrap();
        assert_eq!(repo::automations::list(&c).unwrap().len(), 1);
        repo::integrations::create(&c, "GH", "github").unwrap();
        assert_eq!(repo::integrations::list(&c).unwrap().len(), 1);
    }

    #[test]
    fn run_status_transitions_and_validates() {
        let c = conn();
        let r = repo::runs::create(&c, "do the thing", "plan").unwrap();
        assert_eq!(r.status, "drafted");
        let running = repo::runs::set_status(&c, &r.id, "running").unwrap();
        assert_eq!(running.status, "running");
        assert!(matches!(
            repo::runs::set_status(&c, &r.id, "bogus"),
            Err(CoreError::Invalid { field: "status", .. })
        ));
    }

    #[test]
    fn run_steps_advance_lifecycle() {
        let c = conn();
        let r = repo::runs::create(&c, "ship it", "").unwrap();
        repo::runs::add_step(&c, &r.id, "one", "").unwrap();
        repo::runs::add_step(&c, &r.id, "two", "").unwrap();
        // steps are positioned in insertion order and start pending
        let steps = repo::runs::list_steps(&c, &r.id).unwrap();
        assert_eq!(steps.len(), 2);
        assert_eq!(steps[0].position, 1);
        assert_eq!(steps[1].position, 2);
        assert!(steps.iter().all(|s| s.status == "pending"));

        // first advance: run -> running, step 1 active
        let after1 = repo::runs::advance(&c, &r.id).unwrap();
        assert_eq!(after1.status, "running");
        let steps = repo::runs::list_steps(&c, &r.id).unwrap();
        assert_eq!(steps[0].status, "active");
        assert_eq!(steps[1].status, "pending");

        // second advance: step 1 done, step 2 active
        repo::runs::advance(&c, &r.id).unwrap();
        let steps = repo::runs::list_steps(&c, &r.id).unwrap();
        assert_eq!(steps[0].status, "done");
        assert_eq!(steps[1].status, "active");

        // third advance: step 2 done, no pending left -> run succeeded
        let done = repo::runs::advance(&c, &r.id).unwrap();
        assert_eq!(done.status, "succeeded");
        let steps = repo::runs::list_steps(&c, &r.id).unwrap();
        assert!(steps.iter().all(|s| s.status == "done"));

        // a terminated (succeeded) run cannot be advanced again
        assert!(matches!(
            repo::runs::advance(&c, &r.id),
            Err(CoreError::Invalid { field: "status", .. })
        ));

        // invalid step status rejected
        assert!(matches!(
            repo::runs::set_step_status(&c, &steps[0].id, "bogus"),
            Err(CoreError::Invalid { field: "status", .. })
        ));
    }

    #[test]
    fn run_step_result_and_next_runnable() {
        let c = conn();
        let r = repo::runs::create(&c, "do work", "").unwrap();
        repo::runs::add_step(&c, &r.id, "step one", "").unwrap();
        repo::runs::add_step(&c, &r.id, "step two", "").unwrap();

        // next runnable is the first pending step; steps start with empty result
        let n = repo::runs::next_runnable_step(&c, &r.id).unwrap().unwrap();
        assert_eq!(n.title, "step one");
        assert_eq!(n.result, "");

        // recording a result marks the step done and stores the text
        let done = repo::runs::set_step_result(&c, &n.id, "produced output").unwrap();
        assert_eq!(done.status, "done");
        assert_eq!(done.result, "produced output");

        // next runnable now points at step two
        let n2 = repo::runs::next_runnable_step(&c, &r.id).unwrap().unwrap();
        assert_eq!(n2.title, "step two");

        repo::runs::set_step_result(&c, &n2.id, "second output").unwrap();
        // all steps done -> nothing runnable remains
        assert!(repo::runs::next_runnable_step(&c, &r.id).unwrap().is_none());
    }

    #[test]
    fn approval_gating_links_and_resolves() {
        let c = conn();
        let r = repo::runs::create(&c, "gated run", "").unwrap();
        let step = repo::runs::add_step(&c, &r.id, "risky step", "").unwrap();
        assert!(!step.requires_approval);
        let gated = repo::runs::set_step_requires_approval(&c, &step.id, true).unwrap();
        assert!(gated.requires_approval);

        // nothing approved or pending yet
        assert!(!repo::approvals::approved_for(&c, &step.id, "run_step", "Execute run step").unwrap());
        assert!(repo::approvals::pending_for(&c, &step.id).unwrap().is_none());

        // request an approval linked to the step
        let ap = repo::approvals::create(
            &c, "Execute run step", "risky step", "A2", "medium", "gev", Some("run_step"), Some(&step.id),
            "webview:test", "sess-test", &crate::id(),
        ).unwrap();
        assert_eq!(ap.entity_id.as_deref(), Some(step.id.as_str()));
        assert!(repo::approvals::pending_for(&c, &step.id).unwrap().is_some());
        assert!(!repo::approvals::approved_for(&c, &step.id, "run_step", "Execute run step").unwrap());

        // approving flips both queries
        repo::approvals::approve_confirmed(&c, &ap.id, "native", "native:main", None, ap.nonce.as_deref().unwrap(), ap.request_digest.as_deref().unwrap()).unwrap();
        assert!(repo::approvals::approved_for(&c, &step.id, "run_step", "Execute run step").unwrap());
        assert!(repo::approvals::pending_for(&c, &step.id).unwrap().is_none());
    }

    #[test]
    fn advance_blocks_unapproved_gated_step_and_rejected_is_terminal() {
        let c = conn();
        let r = repo::runs::create(&c, "gated", "").unwrap();
        repo::runs::add_step(&c, &r.id, "one", "").unwrap();
        let s2 = repo::runs::add_step(&c, &r.id, "two", "").unwrap();
        repo::runs::set_step_requires_approval(&c, &s2.id, true).unwrap();

        repo::runs::advance(&c, &r.id).unwrap(); // step 1 active
        repo::runs::advance(&c, &r.id).unwrap(); // step 1 done, gated step 2 active
        // a manual advance can't complete the unapproved gated step
        assert!(matches!(
            repo::runs::advance(&c, &r.id),
            Err(CoreError::Invalid { field: "approval", .. })
        ));

        // approve it -> advance now proceeds
        let ap = repo::approvals::create(&c, "Execute run step", "two", "A2", "medium", "gev", Some("run_step"), Some(&s2.id), "webview:test", "sess-test", &crate::id()).unwrap();
        repo::approvals::approve_confirmed(&c, &ap.id, "native", "native:main", None, ap.nonce.as_deref().unwrap(), ap.request_digest.as_deref().unwrap()).unwrap();
        assert!(repo::runs::advance(&c, &r.id).is_ok());

        // rejected_for: a rejection with no approval blocks
        let r2 = repo::runs::create(&c, "r2", "").unwrap();
        let s = repo::runs::add_step(&c, &r2.id, "x", "").unwrap();
        let rej = repo::approvals::create(&c, "Execute run step", "x", "A2", "low", "gev", Some("run_step"), Some(&s.id), "webview:test", "sess-test", &crate::id()).unwrap();
        repo::approvals::decide(&c, &rej.id, "rejected", None).unwrap();
        assert!(repo::approvals::rejected_for(&c, &s.id, "run_step", "Execute run step").unwrap());
        // a later approval clears the rejected-block
        let ok = repo::approvals::create(&c, "Execute run step", "x", "A2", "low", "gev", Some("run_step"), Some(&s.id), "webview:test", "sess-test", &crate::id()).unwrap();
        repo::approvals::approve_confirmed(&c, &ok.id, "native", "native:main", None, ok.nonce.as_deref().unwrap(), ok.request_digest.as_deref().unwrap()).unwrap();
        assert!(!repo::approvals::rejected_for(&c, &s.id, "run_step", "Execute run step").unwrap());
    }

    #[test]
    fn set_step_status_cannot_bypass_the_approval_gate() {
        let c = conn();
        let r = repo::runs::create(&c, "gated", "").unwrap();
        let step = repo::runs::add_step(&c, &r.id, "risky", "").unwrap();
        repo::runs::set_step_requires_approval(&c, &step.id, true).unwrap();
        // directly marking a gated step done (bypassing advance/stream) is refused
        assert!(matches!(
            repo::runs::set_step_status(&c, &step.id, "done"),
            Err(CoreError::Invalid { field: "status", .. })
        ));
        // other statuses are still fine
        assert!(repo::runs::set_step_status(&c, &step.id, "active").is_ok());
        // once approved, done succeeds
        let ap = repo::approvals::create(&c, "Execute run step", "risky", "A2", "medium", "gev", Some("run_step"), Some(&step.id), "webview:test", "sess-test", &crate::id()).unwrap();
        repo::approvals::approve_confirmed(&c, &ap.id, "native", "native:main", None, ap.nonce.as_deref().unwrap(), ap.request_digest.as_deref().unwrap()).unwrap();
        assert!(repo::runs::set_step_status(&c, &step.id, "done").is_ok());
    }

    // T-011: a pending approval carries its durable origin_principal, a one-time
    // nonce, and a request digest bound to the current entity state. Returns
    // (step_id, approval_id, nonce, request_digest).
    fn t011_pending(c: &rusqlite::Connection) -> (String, String, String, String) {
        let r = repo::runs::create(c, "gated", "plan-body").unwrap();
        let step = repo::runs::add_step(c, &r.id, "risky", "detail").unwrap();
        repo::runs::set_step_requires_approval(c, &step.id, true).unwrap();
        let ap = repo::approvals::create(
            c, "Execute run step", "risky", "A2", "medium", "gev",
            Some("run_step"), Some(&step.id), "webview:main", "sess-1", &crate::id(),
        ).unwrap();
        assert_eq!(ap.origin_principal.as_deref(), Some("webview:main"));
        (step.id, ap.id, ap.nonce.clone().unwrap(), ap.request_digest.clone().unwrap())
    }

    #[test]
    fn t011_self_approval_by_durable_principal_is_refused_but_native_confirms() {
        let c = conn();
        let (_step, ap_id, nonce, digest) = t011_pending(&c);
        // Approving while claiming the SAME principal that requested it is refused.
        assert!(matches!(
            repo::approvals::approve_confirmed(&c, &ap_id, "webview:main", "native:main", None, &nonce, &digest),
            Err(CoreError::Invalid { field: "approver", .. })
        ));
        // The renderer-independent native confirmation is a DISTINCT principal.
        let ok = repo::approvals::approve_confirmed(&c, &ap_id, "native", "native:main", None, &nonce, &digest).unwrap();
        assert_eq!(ok.status, "approved");
        assert_eq!(ok.confirmation_method.as_deref(), Some("native"));
        assert!(ok.confirmed_at.is_some());
        assert!(ok.nonce.is_none(), "nonce must be consumed");
        // And the grant is now valid at the authority layer.
        assert!(repo::approvals::approved_for(&c, &ok.entity_id.clone().unwrap(), "run_step", "Execute run step").unwrap());
    }

    #[test]
    fn t011_nonce_replay_is_refused() {
        let c = conn();
        let (_step, ap_id, nonce, digest) = t011_pending(&c);
        repo::approvals::approve_confirmed(&c, &ap_id, "native", "native:main", None, &nonce, &digest).unwrap();
        // Replaying the SAME nonce is refused (it was consumed), not merely blocked
        // by the status guard.
        assert!(matches!(
            repo::approvals::approve_confirmed(&c, &ap_id, "native", "native:main", None, &nonce, &digest),
            Err(CoreError::NotFound(_) | CoreError::Invalid { field: "nonce", .. })
        ));
    }

    #[test]
    fn t011_request_mutation_after_raise_is_refused() {
        let c = conn();
        let (step_id, ap_id, nonce, digest) = t011_pending(&c);
        // Mutate the underlying step AFTER the approval was raised.
        c.execute("UPDATE run_steps SET title = 'tampered' WHERE id = ?1", [&step_id]).unwrap();
        assert!(matches!(
            repo::approvals::approve_confirmed(&c, &ap_id, "native", "native:main", None, &nonce, &digest),
            Err(CoreError::Invalid { field: "request_digest", .. })
        ));
    }

    #[test]
    fn t011_dialog_and_prompt_share_one_scope_including_detail() {
        // The confirmed payload, the provider prompt, and the digest all derive from
        // the SAME RunExecutionScope — step_detail (e.g. a safety condition) that the
        // owner sees in the dialog MUST also reach the provider.
        let c = conn();
        let r = repo::runs::create(&c, "the-intent", "the-plan").unwrap();
        let step = repo::runs::add_step(&c, &r.id, "the-title", "SAFETY: do not delete data").unwrap();
        let scope = repo::approvals::run_execution_scope(&c, &step.id).unwrap();
        let prompt = scope.provider_json().to_string();
        assert!(prompt.contains("SAFETY: do not delete data"), "prompt must include step_detail: {prompt}");
        assert!(prompt.contains("the-plan"), "prompt must include plan: {prompt}");
        assert!(scope.dialog_text().contains("SAFETY: do not delete data"));
        assert!(scope.dialog_text().contains("the-plan"));
    }

    #[test]
    fn t011_internal_tokens_are_not_serialized_to_the_webview() {
        // The nonce and integrity digests are server-only; they must never reach the
        // untrusted renderer via a command response (e.g. list_approvals).
        let c = conn();
        let (_s, ap_id, _n, _d) = t011_pending(&c);
        let ap = repo::approvals::get(&c, &ap_id).unwrap();
        let json = serde_json::to_string(&ap).unwrap();
        for leaked in ["nonce", "requestDigest", "confirmationDigest", "originSessionId"] {
            assert!(!json.contains(leaked), "internal token `{leaked}` must not be serialized: {json}");
        }
        // Safe provenance IS still exposed for display.
        assert!(json.contains("originPrincipal"));
    }

    #[test]
    fn t011_plan_change_after_raise_is_refused() {
        // A benign intent/title with a swapped PLAN must not pass — the plan is part
        // of the execution payload and is bound by the digest.
        let c = conn();
        let (step_id, ap_id, nonce, digest) = t011_pending(&c);
        let run_id: String = c
            .query_row("SELECT run_id FROM run_steps WHERE id = ?1", [&step_id], |r| r.get(0))
            .unwrap();
        c.execute("UPDATE runs SET plan = 'malicious-plan' WHERE id = ?1", [&run_id]).unwrap();
        assert!(matches!(
            repo::approvals::approve_confirmed(&c, &ap_id, "native", "native:main", None, &nonce, &digest),
            Err(CoreError::Invalid { field: "request_digest", .. })
        ));
    }

    #[test]
    fn t011_self_approval_survives_a_real_reopen() {
        // Restart-safe for real: create in one connection, DROP it, reopen the same
        // file, and confirm the durable origin_principal still blocks self-approval.
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("t011.db");
        let path = path.to_str().unwrap();
        let (ap_id, nonce, digest) = {
            let c1 = db::open(path).unwrap();
            let (_s, ap_id, nonce, digest) = t011_pending(&c1);
            (ap_id, nonce, digest)
        }; // c1 dropped — simulates app close
        let c2 = db::open(path).unwrap(); // reopen + migrate (idempotent)
        assert!(matches!(
            repo::approvals::approve_confirmed(&c2, &ap_id, "webview:main", "native:main", None, &nonce, &digest),
            Err(CoreError::Invalid { field: "approver", .. })
        ));
        // A genuine native confirmation still works after the reopen.
        assert!(repo::approvals::approve_confirmed(&c2, &ap_id, "native", "native:main", None, &nonce, &digest).is_ok());
    }

    #[test]
    fn advance_rejects_terminal_and_stepless_runs() {
        let c = conn();
        // a run with no steps cannot be advanced (no accidental jump to succeeded)
        let empty = repo::runs::create(&c, "no plan", "").unwrap();
        assert!(matches!(
            repo::runs::advance(&c, &empty.id),
            Err(CoreError::Invalid { field: "steps", .. })
        ));
        assert_eq!(repo::runs::get(&c, &empty.id).unwrap().status, "drafted");

        // a cancelled run with pending steps is NOT resurrected by advance
        let r = repo::runs::create(&c, "cancel me", "").unwrap();
        repo::runs::add_step(&c, &r.id, "s1", "").unwrap();
        repo::runs::add_step(&c, &r.id, "s2", "").unwrap();
        repo::runs::set_status(&c, &r.id, "cancelled").unwrap();
        assert!(matches!(
            repo::runs::advance(&c, &r.id),
            Err(CoreError::Invalid { field: "status", .. })
        ));
        // still cancelled; steps untouched
        assert_eq!(repo::runs::get(&c, &r.id).unwrap().status, "cancelled");
        assert!(repo::runs::list_steps(&c, &r.id).unwrap().iter().all(|s| s.status == "pending"));
    }

    #[test]
    fn run_steps_cascade_delete_with_run() {
        let c = conn();
        let r = repo::runs::create(&c, "temp", "").unwrap();
        repo::runs::add_step(&c, &r.id, "s", "").unwrap();
        assert_eq!(repo::runs::list_steps(&c, &r.id).unwrap().len(), 1);
        c.execute("DELETE FROM runs WHERE id = ?1", [&r.id]).unwrap();
        assert_eq!(repo::runs::list_steps(&c, &r.id).unwrap().len(), 0);
        // adding a step to a missing run is rejected
        assert!(repo::runs::add_step(&c, "nope", "x", "").is_err());
    }

    #[test]
    fn automation_toggle_and_integration_status() {
        let c = conn();
        let a = repo::automations::create(&c, NewAutomation { name: "A".into(), trigger: "t".into(), action: "x".into() }).unwrap();
        assert!(a.enabled);
        let off = repo::automations::set_enabled(&c, &a.id, false).unwrap();
        assert!(!off.enabled);

        let i = repo::integrations::create(&c, "GitHub", "github").unwrap();
        assert_eq!(i.status, "disconnected");
        let on = repo::integrations::set_status(&c, &i.id, "connected").unwrap();
        assert_eq!(on.status, "connected");
        assert!(repo::integrations::set_status(&c, &i.id, "bogus").is_err());
    }

    #[test]
    fn analytics_and_security_compute_over_seed() {
        let c = conn();
        repo::seed(&c).unwrap();
        let metrics = repo::analytics::metrics(&c).unwrap();
        let projects = metrics.iter().find(|m| m.key == "projects").unwrap();
        assert!(projects.value >= 2);
        let runs = metrics.iter().find(|m| m.key == "runs").unwrap();
        assert!(runs.value >= 2);

        let sec = repo::security::summary(&c).unwrap();
        assert!(sec.pending_approvals >= 1);
        assert!(sec.audit_events >= 1);
        // seeded run/automation/integration status changes are sensitive events
        assert!(!sec.sensitive_events.is_empty());
    }

    #[test]
    fn knowledge_search_matches_title_body_tags() {
        let c = conn();
        repo::knowledge::create(&c, NewKnowledgeNote { title: "Migrations".into(), body: "forward only".into(), source: "".into(), tags: "sqlite".into() }).unwrap();
        repo::knowledge::create(&c, NewKnowledgeNote { title: "IPC".into(), body: "typed boundary".into(), source: "".into(), tags: "architecture".into() }).unwrap();
        assert_eq!(repo::knowledge::search(&c, "forward").unwrap().len(), 1);
        assert_eq!(repo::knowledge::search(&c, "sqlite").unwrap().len(), 1);
        assert_eq!(repo::knowledge::search(&c, "typed").unwrap().len(), 1);
        assert_eq!(repo::knowledge::search(&c, "").unwrap().len(), 2); // empty = list all
        assert_eq!(repo::knowledge::search(&c, "nomatch").unwrap().len(), 0);
    }

    #[test]
    fn search_finds_across_entities() {
        let c = conn();
        repo::seed(&c).unwrap();
        // "Localization" appears in a seeded project name and an agent role.
        assert!(repo::search::global(&c, "Localization").unwrap().len() >= 1);
        // an empty query returns nothing (no accidental full dump).
        assert_eq!(repo::search::global(&c, "").unwrap().len(), 0);
        assert_eq!(repo::search::global(&c, "   ").unwrap().len(), 0);
    }

    #[test]
    fn fts_search_prefix_multiterm_and_trigger_sync() {
        let c = conn();
        let p = repo::projects::create(
            &c,
            NewProject { name: "Localization Engine".into(), description: "translate strings".into(), priority: "high".into(), workspace_id: None },
        ).unwrap();

        // prefix match: "Local" finds "Localization" via the INSERT trigger
        assert_eq!(repo::search::global(&c, "Local").unwrap().iter().filter(|r| r.kind == "project").count(), 1);
        // body is indexed too
        assert_eq!(repo::search::global(&c, "translate").unwrap().iter().filter(|r| r.kind == "project").count(), 1);
        // multi-term is AND: both must match
        assert_eq!(repo::search::global(&c, "Local translate").unwrap().iter().filter(|r| r.kind == "project").count(), 1);
        assert_eq!(repo::search::global(&c, "Local nomatchxyz").unwrap().iter().filter(|r| r.kind == "project").count(), 0);
        // punctuation-only / empty queries never error and return nothing
        assert_eq!(repo::search::global(&c, "  ***  ").unwrap().len(), 0);
        assert_eq!(repo::search::global(&c, "\"';--").unwrap().len(), 0);

        // UPDATE trigger re-indexes: old term gone, new term found
        repo::projects::update(&c, &p.id, "Renamed Widget", "translate strings", "high").unwrap();
        assert_eq!(repo::search::global(&c, "Localization").unwrap().iter().filter(|r| r.kind == "project").count(), 0);
        assert_eq!(repo::search::global(&c, "Widget").unwrap().iter().filter(|r| r.kind == "project").count(), 1);

        // DELETE trigger removes it from the index (cascade also drops it, but
        // deleting the project directly must clear the search row)
        c.execute("DELETE FROM projects WHERE id = ?1", [&p.id]).unwrap();
        assert_eq!(repo::search::global(&c, "Widget").unwrap().iter().filter(|r| r.kind == "project").count(), 0);
    }

    #[test]
    fn memory_pin_orders_and_delete_works() {
        let c = conn();
        repo::memory::create(&c, NewMemoryEntry { scope: "global".into(), kind: "note".into(), content: "first".into() }).unwrap();
        let second = repo::memory::create(&c, NewMemoryEntry { scope: "global".into(), kind: "fact".into(), content: "second".into() }).unwrap();
        // pin the older one so it sorts to the top
        repo::memory::set_pinned(&c, &second.id, true).unwrap();
        let list = repo::memory::list(&c, None).unwrap();
        assert!(list[0].pinned);
        assert_eq!(list[0].content, "second");
        // bad kind rejected
        assert!(matches!(
            repo::memory::create(&c, NewMemoryEntry { scope: "global".into(), kind: "bogus".into(), content: "x".into() }),
            Err(CoreError::Invalid { field: "kind", .. })
        ));
        // delete removes it
        repo::memory::delete(&c, &second.id).unwrap();
        assert_eq!(repo::memory::list(&c, None).unwrap().len(), 1);
    }

    #[test]
    fn chat_post_and_list_ordered() {
        let c = conn();
        let conv = repo::chat::create_conversation(&c, "group", "room").unwrap();
        repo::chat::post_message(&c, NewMessage { conversation_id: conv.id.clone(), role: "user".into(), author: "gev".into(), body: "first".into() }).unwrap();
        repo::chat::post_message(&c, NewMessage { conversation_id: conv.id.clone(), role: "agent".into(), author: "Bro".into(), body: "second".into() }).unwrap();

        let msgs = repo::chat::list_messages(&c, &conv.id, None, None).unwrap();
        assert_eq!(msgs.len(), 2);
        assert_eq!(msgs[0].body, "first");
        assert_eq!(msgs[1].body, "second");

        // the conversation aggregate reflects the posted messages
        let reloaded = repo::chat::get_conversation(&c, &conv.id).unwrap();
        assert_eq!(reloaded.message_count, 2);
        assert!(reloaded.last_message_at.is_some());
    }

    #[test]
    fn chat_rejects_bad_role_and_unknown_conversation() {
        let c = conn();
        let conv = repo::chat::create_conversation(&c, "direct", "Bro").unwrap();
        assert!(matches!(
            repo::chat::post_message(&c, NewMessage { conversation_id: conv.id.clone(), role: "bogus".into(), author: "x".into(), body: "y".into() }),
            Err(CoreError::Invalid { field: "role", .. })
        ));
        assert!(repo::chat::post_message(&c, NewMessage { conversation_id: "nope".into(), role: "user".into(), author: "x".into(), body: "y".into() }).is_err());
        assert!(repo::chat::create_conversation(&c, "bogus-kind", "x").is_err());
    }

    #[test]
    fn chat_list_filters_by_kind() {
        let c = conn();
        repo::chat::create_conversation(&c, "direct", "Bro").unwrap();
        repo::chat::create_conversation(&c, "group", "room a").unwrap();
        repo::chat::create_conversation(&c, "group", "room b").unwrap();
        assert_eq!(repo::chat::list_conversations(&c, Some("group")).unwrap().len(), 2);
        assert_eq!(repo::chat::list_conversations(&c, Some("direct")).unwrap().len(), 1);
        assert_eq!(repo::chat::list_conversations(&c, None).unwrap().len(), 3);
    }

    #[test]
    fn conversation_delete_and_rename() {
        let c = conn();
        let conv = repo::chat::create_conversation(&c, "group", "old title").unwrap();
        repo::chat::post_message(&c, NewMessage { conversation_id: conv.id.clone(), role: "user".into(), author: "gev".into(), body: "hi".into() }).unwrap();
        repo::chat::post_message(&c, NewMessage { conversation_id: conv.id.clone(), role: "agent".into(), author: "Bro".into(), body: "hello".into() }).unwrap();

        // rename updates the stored title
        let renamed = repo::chat::rename_conversation(&c, &conv.id, "new title").unwrap();
        assert_eq!(renamed.title, "new title");
        assert_eq!(repo::chat::get_conversation(&c, &conv.id).unwrap().title, "new title");

        // a second conversation so we can watch the list count drop on delete
        repo::chat::create_conversation(&c, "group", "keep me").unwrap();
        assert_eq!(repo::chat::list_conversations(&c, None).unwrap().len(), 2);

        // delete removes the conversation and cascades its messages away
        repo::chat::delete_conversation(&c, &conv.id).unwrap();
        assert_eq!(repo::chat::list_conversations(&c, None).unwrap().len(), 1);
        assert_eq!(repo::chat::list_messages(&c, &conv.id, None, None).unwrap().len(), 0);
        assert!(repo::chat::get_conversation(&c, &conv.id).is_err());

        // deleting/renaming an unknown conversation is a clean NotFound
        assert!(matches!(repo::chat::delete_conversation(&c, "nope"), Err(CoreError::NotFound(_))));
        assert!(matches!(repo::chat::rename_conversation(&c, "nope", "x"), Err(CoreError::NotFound(_))));
    }

    #[test]
    fn seed_populates_and_is_idempotent() {
        let c = conn();
        repo::seed(&c).unwrap();
        let after_first = repo::projects::list(&c).unwrap().len();
        assert!(after_first >= 2);
        assert!(repo::agents::list(&c).unwrap().len() >= 6);
        assert!(repo::approvals::list(&c, None, None).unwrap().len() >= 2);
        assert!(repo::notifications::list(&c, None, None).unwrap().len() >= 2);
        assert!(repo::decisions::list(&c).unwrap().len() >= 2);
        assert!(repo::chat::list_conversations(&c, None).unwrap().len() >= 2);
        assert!(repo::knowledge::list(&c).unwrap().len() >= 2);
        assert!(repo::memory::list(&c, None).unwrap().len() >= 2);
        assert!(repo::runs::list(&c).unwrap().len() >= 2);
        assert!(repo::events::list(&c).unwrap().len() >= 2);
        assert!(repo::automations::list(&c).unwrap().len() >= 2);
        assert!(repo::integrations::list(&c).unwrap().len() >= 2);
        // the first seeded run has an executable plan and is mid-flight
        let seeded_run = repo::runs::list(&c).unwrap().into_iter().find(|r| r.status == "running").unwrap();
        let steps = repo::runs::list_steps(&c, &seeded_run.id).unwrap();
        assert!(steps.len() >= 4);
        assert_eq!(steps[0].status, "active");
        // running again must not duplicate
        repo::seed(&c).unwrap();
        assert_eq!(repo::projects::list(&c).unwrap().len(), after_first);
    }

    #[test]
    fn approval_decide_is_reject_only() {
        let c = conn();
        repo::seed(&c).unwrap();
        let pending: Vec<_> = repo::approvals::list(&c, None, None).unwrap().into_iter().filter(|a| a.status == "pending").collect();
        assert!(!pending.is_empty());
        // T-011: approve is refused at the authority layer — the only approve path is
        // `approve_confirmed` (native confirmation), never `decide`.
        assert!(matches!(
            repo::approvals::decide(&c, &pending[0].id, "approved", None),
            Err(CoreError::Invalid { field: "decision", .. })
        ));
        // reject works, is atomic + pending-only.
        let rejected = repo::approvals::decide(&c, &pending[0].id, "rejected", Some("ok")).unwrap();
        assert_eq!(rejected.status, "rejected");
        assert!(rejected.decided_at.is_some());
        // deciding a non-pending approval fails
        assert!(repo::approvals::decide(&c, &pending[0].id, "rejected", None).is_err());
    }

    #[test]
    fn audit_events_recorded() {
        let c = conn();
        let p = repo::projects::create(
            &c,
            NewProject { name: "x".into(), description: "".into(), priority: "low".into(), workspace_id: None },
        )
        .unwrap();
        repo::tasks::create(
            &c,
            NewTask { project_id: Some(p.id), title: "t".into(), description: "".into(), priority: "low".into(), assigned_agent_id: None },
        )
        .unwrap();
        assert!(repo::audit::count(&c).unwrap() >= 2);
    }
}
