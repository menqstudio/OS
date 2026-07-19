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
/// (The desktop build swaps this for a full UTC ISO-8601 string.)
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
    fn migrations_reach_v6_with_all_tables() {
        let c = conn();
        assert_eq!(db::current_version(&c).unwrap(), 6);
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

        let msgs = repo::chat::list_messages(&c, &conv.id).unwrap();
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
    fn seed_populates_and_is_idempotent() {
        let c = conn();
        repo::seed(&c).unwrap();
        let after_first = repo::projects::list(&c).unwrap().len();
        assert!(after_first >= 2);
        assert!(repo::agents::list(&c).unwrap().len() >= 6);
        assert!(repo::approvals::list(&c).unwrap().len() >= 2);
        assert!(repo::notifications::list(&c).unwrap().len() >= 2);
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
    fn approval_decide_flow() {
        let c = conn();
        repo::seed(&c).unwrap();
        let pending: Vec<_> = repo::approvals::list(&c).unwrap().into_iter().filter(|a| a.status == "pending").collect();
        assert!(!pending.is_empty());
        let decided = repo::approvals::decide(&c, &pending[0].id, "approved", Some("ok")).unwrap();
        assert_eq!(decided.status, "approved");
        assert!(decided.decided_at.is_some());
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
