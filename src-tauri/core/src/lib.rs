//! BroPS local data core: SQLite schema, forward-only migrations, and typed
//! repositories. This crate is UI- and Tauri-independent so it can be built and
//! tested on its own (`cargo test -p brops-core`).

pub mod db;
pub mod domain;
pub mod repo;

pub use domain::{
    ActivityEvent, Agent, Approval, CoreError, CoreResult, Decision, NewProject, NewTask,
    Notification, Project, Task,
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
    fn migrations_reach_v2_with_decisions() {
        let c = conn();
        assert_eq!(db::current_version(&c).unwrap(), 2);
        // decisions table exists and is usable
        repo::decisions::create(&c, "T", "gev", "why").unwrap();
        assert_eq!(repo::decisions::list(&c).unwrap().len(), 1);
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
