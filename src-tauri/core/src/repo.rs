//! Repositories: typed CRUD over the SQLite schema. No raw SQL escapes to callers.

use crate::domain::*;
use crate::{id, now};
use rusqlite::{Connection, OptionalExtension, Row};

/// Hard cap applied to list queries so no screen ever materializes an
/// unbounded table (L-1a).
const MAX_PAGE: u32 = 1000;
/// Page size used when a paginated list is called without an explicit limit.
const DEFAULT_PAGE: u32 = 500;

/// Normalize caller-supplied pagination into bound SQL params: `limit` is
/// clamped to `MAX_PAGE` and defaults to `DEFAULT_PAGE`; `offset` defaults to 0.
fn page(limit: Option<u32>, offset: Option<u32>) -> (i64, i64) {
    (
        i64::from(limit.unwrap_or(DEFAULT_PAGE).min(MAX_PAGE)),
        i64::from(offset.unwrap_or(0)),
    )
}

/// Run `f` atomically. When the connection is in autocommit mode this opens a
/// transaction (the `unchecked_transaction` pattern) and commits only after `f`
/// succeeds — an error rolls everything back, so a mutation and its audit row
/// land together or not at all (M-5). When the caller already holds a
/// transaction (`seed`, `runs::advance` calling `set_status`), the work joins
/// it instead of nesting a second BEGIN, and the outer transaction owns
/// commit/rollback.
fn atomic<T, F>(conn: &Connection, f: F) -> CoreResult<T>
where
    F: FnOnce(&Connection) -> CoreResult<T>,
{
    if conn.is_autocommit() {
        let tx = conn.unchecked_transaction()?;
        let out = f(&tx)?;
        tx.commit()?;
        Ok(out)
    } else {
        f(conn)
    }
}

fn map_project(r: &Row) -> rusqlite::Result<Project> {
    Ok(Project {
        id: r.get("id")?,
        workspace_id: r.get("workspace_id")?,
        name: r.get("name")?,
        description: r.get("description")?,
        status: r.get("status")?,
        priority: r.get("priority")?,
        created_at: r.get("created_at")?,
        updated_at: r.get("updated_at")?,
        archived_at: r.get("archived_at")?,
    })
}

fn map_task(r: &Row) -> rusqlite::Result<Task> {
    Ok(Task {
        id: r.get("id")?,
        project_id: r.get("project_id")?,
        title: r.get("title")?,
        description: r.get("description")?,
        status: r.get("status")?,
        priority: r.get("priority")?,
        assigned_agent_id: r.get("assigned_agent_id")?,
        due_at: r.get("due_at")?,
        position: r.get("position")?,
        created_at: r.get("created_at")?,
        updated_at: r.get("updated_at")?,
        completed_at: r.get("completed_at")?,
    })
}

pub mod projects {
    use super::*;

    pub fn create(conn: &Connection, input: NewProject) -> CoreResult<Project> {
        if !is_valid(&input.priority, PRIORITIES) {
            return Err(CoreError::Invalid { field: "priority", value: input.priority });
        }
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO projects(id, workspace_id, name, description, status, priority, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, 'planned', ?5, ?6, ?6)",
                rusqlite::params![id, input.workspace_id, input.name, input.description, input.priority, now],
            )?;
            super::audit::record(tx, "project.created", "user", "gev", "project", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Project> {
        conn.query_row("SELECT * FROM projects WHERE id = ?1", [id], map_project)
            .map_err(|e| match e {
                rusqlite::Error::QueryReturnedNoRows => CoreError::NotFound(id.to_string()),
                other => CoreError::Sqlite(other),
            })
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Project>> {
        let mut stmt = conn.prepare("SELECT * FROM projects ORDER BY updated_at DESC LIMIT ?1")?;
        let rows = stmt.query_map([super::MAX_PAGE], map_project)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn set_status(conn: &Connection, id: &str, status: &str) -> CoreResult<Project> {
        if !is_valid(status, PROJECT_STATUSES) {
            return Err(CoreError::Invalid { field: "status", value: status.to_string() });
        }
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE projects SET status = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![status, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "project.status_changed", "user", "gev", "project", id)?;
            Ok(())
        })?;
        get(conn, id)
    }

    /// Edit a project's name, description, and priority.
    pub fn update(conn: &Connection, id: &str, name: &str, description: &str, priority: &str) -> CoreResult<Project> {
        if !is_valid(priority, PRIORITIES) {
            return Err(CoreError::Invalid { field: "priority", value: priority.to_string() });
        }
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE projects SET name = ?1, description = ?2, priority = ?3, updated_at = ?4 WHERE id = ?5",
                rusqlite::params![name, description, priority, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "project.updated", "user", "gev", "project", id)?;
            Ok(())
        })?;
        get(conn, id)
    }
}

pub mod tasks {
    use super::*;

    pub fn create(conn: &Connection, input: NewTask) -> CoreResult<Task> {
        if !is_valid(&input.priority, PRIORITIES) {
            return Err(CoreError::Invalid { field: "priority", value: input.priority });
        }
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO tasks(id, project_id, title, description, status, priority, assigned_agent_id, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, 'inbox', ?5, ?6, ?7, ?7)",
                rusqlite::params![id, input.project_id, input.title, input.description, input.priority, input.assigned_agent_id, now],
            )?;
            super::audit::record(tx, "task.created", "user", "gev", "task", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Task> {
        conn.query_row("SELECT * FROM tasks WHERE id = ?1", [id], map_task)
            .map_err(|e| match e {
                rusqlite::Error::QueryReturnedNoRows => CoreError::NotFound(id.to_string()),
                other => CoreError::Sqlite(other),
            })
    }

    pub fn list_by_project(conn: &Connection, project_id: &str) -> CoreResult<Vec<Task>> {
        let mut stmt = conn.prepare(
            "SELECT * FROM tasks WHERE project_id = ?1 ORDER BY position, created_at",
        )?;
        let rows = stmt.query_map([project_id], map_task)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn list_by_status(conn: &Connection, status: &str) -> CoreResult<Vec<Task>> {
        let mut stmt = conn.prepare("SELECT * FROM tasks WHERE status = ?1 ORDER BY updated_at DESC")?;
        let rows = stmt.query_map([status], map_task)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// All tasks, newest-updated first — used by the board view which groups by
    /// status client-side.
    pub fn list_all(conn: &Connection) -> CoreResult<Vec<Task>> {
        let mut stmt = conn.prepare("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?1")?;
        let rows = stmt.query_map([super::MAX_PAGE], map_task)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Edit a task's title, description, and priority.
    pub fn update(conn: &Connection, id: &str, title: &str, description: &str, priority: &str) -> CoreResult<Task> {
        if !is_valid(priority, PRIORITIES) {
            return Err(CoreError::Invalid { field: "priority", value: priority.to_string() });
        }
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE tasks SET title = ?1, description = ?2, priority = ?3, updated_at = ?4 WHERE id = ?5",
                rusqlite::params![title, description, priority, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "task.updated", "user", "gev", "task", id)?;
            Ok(())
        })?;
        get(conn, id)
    }

    pub fn set_status(conn: &Connection, id: &str, status: &str) -> CoreResult<Task> {
        if !is_valid(status, TASK_STATUSES) {
            return Err(CoreError::Invalid { field: "status", value: status.to_string() });
        }
        let completed = if status == "done" { Some(now()) } else { None };
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE tasks SET status = ?1, completed_at = ?2, updated_at = ?3 WHERE id = ?4",
                rusqlite::params![status, completed, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "task.status_changed", "user", "gev", "task", id)?;
            Ok(())
        })?;
        get(conn, id)
    }
}

/// Directed task dependencies: `task_id` depends on `depends_on_id` (the latter
/// should finish first). Used by the board to show blockers.
pub mod task_deps {
    use super::*;

    /// Record that `task_id` depends on `depends_on_id`. Refuses a self-edge and
    /// any cycle — direct OR transitive (A→B→C→A) — via a reachability walk;
    /// duplicates are idempotent.
    pub fn add(conn: &Connection, task_id: &str, depends_on_id: &str) -> CoreResult<()> {
        if task_id == depends_on_id {
            return Err(CoreError::Invalid { field: "depends_on_id", value: "a task cannot depend on itself".into() });
        }
        // Cycle check and insert run in one transaction so a concurrent add
        // cannot slip a cycle in between them (L-3c).
        super::atomic(conn, |tx| {
            // both tasks must exist (clear error rather than a FK failure)
            tasks::get(tx, task_id)?;
            tasks::get(tx, depends_on_id)?;
            // Adding task_id → depends_on_id closes a cycle iff depends_on_id can
            // already reach task_id by following depends-on edges. Walk the graph.
            let creates_cycle: bool = tx.query_row(
                "WITH RECURSIVE reach(id) AS (
                     SELECT depends_on_id FROM task_dependencies WHERE task_id = ?1
                     UNION
                     SELECT d.depends_on_id FROM task_dependencies d JOIN reach r ON d.task_id = r.id
                 )
                 SELECT EXISTS(SELECT 1 FROM reach WHERE id = ?2)",
                rusqlite::params![depends_on_id, task_id],
                |r| r.get(0),
            )?;
            if creates_cycle {
                return Err(CoreError::Invalid { field: "depends_on_id", value: "that would create a dependency cycle".into() });
            }
            tx.execute(
                "INSERT OR IGNORE INTO task_dependencies(task_id, depends_on_id) VALUES (?1, ?2)",
                rusqlite::params![task_id, depends_on_id],
            )?;
            super::audit::record(tx, "task.dependency_added", "user", "gev", "task", task_id)?;
            Ok(())
        })
    }

    /// Remove a dependency edge. Errors when the edge does not exist and audits
    /// the removal — dropping a blocker is a sensitive graph mutation (L-3f).
    pub fn remove(conn: &Connection, task_id: &str, depends_on_id: &str) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "DELETE FROM task_dependencies WHERE task_id = ?1 AND depends_on_id = ?2",
                rusqlite::params![task_id, depends_on_id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(format!("dependency {task_id} -> {depends_on_id}")));
            }
            super::audit::record(tx, "task.dependency_removed", "user", "gev", "task", task_id)?;
            Ok(())
        })
    }

    /// The tasks that `task_id` depends on (its blockers), newest edge first.
    pub fn list_for(conn: &Connection, task_id: &str) -> CoreResult<Vec<Task>> {
        let mut stmt = conn.prepare(
            "SELECT t.* FROM tasks t
             JOIN task_dependencies d ON d.depends_on_id = t.id
             WHERE d.task_id = ?1 ORDER BY t.updated_at DESC",
        )?;
        let rows = stmt.query_map([task_id], map_task)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }
}

pub mod audit {
    use super::*;

    /// The actor kinds an audit event may carry (L-4a).
    pub const ACTOR_TYPES: &[&str] = &["user", "agent", "system"];

    /// Record an audit event. `actor_type` is passed explicitly by trusted repo
    /// code (never hardcoded `'user'`), so agent-originated events stay
    /// distinguishable from human ones in `security::summary` (L-4a). Call
    /// sites at the command layer must derive `actor_id` from trusted context,
    /// not from the request body.
    pub fn record(
        conn: &Connection,
        event_type: &str,
        actor_type: &str,
        actor_id: &str,
        entity_type: &str,
        entity_id: &str,
    ) -> CoreResult<()> {
        if !is_valid(actor_type, ACTOR_TYPES) {
            return Err(CoreError::Invalid { field: "actor_type", value: actor_type.to_string() });
        }
        conn.execute(
            "INSERT INTO audit_events(id, event_type, actor_type, actor_id, entity_type, entity_id, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            rusqlite::params![id(), event_type, actor_type, actor_id, entity_type, entity_id, now()],
        )?;
        Ok(())
    }

    pub fn count(conn: &Connection) -> CoreResult<i64> {
        Ok(conn.query_row("SELECT COUNT(*) FROM audit_events", [], |r| r.get(0))?)
    }
}

pub mod agents {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<Agent> {
        Ok(Agent {
            id: r.get("id")?,
            slug: r.get("slug")?,
            display_name: r.get("display_name")?,
            role: r.get("role")?,
            status: r.get("status")?,
            model: r.get("model")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, slug: &str, name: &str, role: &str, model: &str) -> CoreResult<Agent> {
        let now = now();
        let id = id();
        conn.execute(
            "INSERT INTO agents(id, slug, display_name, role, status, model, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, 'idle', ?5, ?6, ?6)",
            rusqlite::params![id, slug, name, role, model, now],
        )?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Agent> {
        conn.query_row("SELECT * FROM agents WHERE id = ?1", [id], map)
            .map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Agent>> {
        let mut s = conn.prepare("SELECT * FROM agents ORDER BY display_name")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }
}

pub mod approvals {
    use super::*;

    /// The entity/action tuple an approval must carry to gate run-step
    /// execution. `approved_for` matches the full tuple, so a grant minted for
    /// another action can never unlock a step (M-2).
    pub const RUN_STEP_ENTITY_TYPE: &str = "run_step";
    pub const RUN_STEP_ACTION_TYPE: &str = "Execute run step";

    fn map(r: &Row) -> rusqlite::Result<Approval> {
        Ok(Approval {
            id: r.get("id")?,
            action_type: r.get("action_type")?,
            target: r.get("target")?,
            level: r.get("level")?,
            risk_level: r.get("risk_level")?,
            status: r.get("status")?,
            requested_by: r.get("requested_by")?,
            decision_note: r.get("decision_note")?,
            entity_type: r.get("entity_type")?,
            entity_id: r.get("entity_id")?,
            requested_at: r.get("requested_at")?,
            decided_at: r.get("decided_at")?,
        })
    }

    /// A bounded page of approvals, newest request first. `limit` is clamped
    /// to `MAX_PAGE` and defaults to `DEFAULT_PAGE`; `offset` defaults to 0.
    pub fn list(conn: &Connection, limit: Option<u32>, offset: Option<u32>) -> CoreResult<Vec<Approval>> {
        let (limit, offset) = super::page(limit, offset);
        let mut s = conn.prepare("SELECT * FROM approvals ORDER BY requested_at DESC LIMIT ?1 OFFSET ?2")?;
        let rows = s.query_map(rusqlite::params![limit, offset], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Create a pending approval, optionally linked to the entity that needs it.
    #[allow(clippy::too_many_arguments)]
    pub fn create(
        conn: &Connection,
        action_type: &str,
        target: &str,
        level: &str,
        risk_level: &str,
        requested_by: &str,
        entity_type: Option<&str>,
        entity_id: Option<&str>,
    ) -> CoreResult<Approval> {
        let id = id();
        super::atomic(conn, |tx| {
            // An approval may only point at an entity that actually exists — a
            // grant minted against an arbitrary id must not be creatable (M-2).
            if entity_type == Some(RUN_STEP_ENTITY_TYPE) {
                if let Some(step_id) = entity_id {
                    super::runs::get_step(tx, step_id)?;
                }
            }
            tx.execute(
                "INSERT INTO approvals(id, action_type, target, level, risk_level, status, requested_by, entity_type, entity_id, requested_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, 'pending', ?6, ?7, ?8, ?9)",
                rusqlite::params![id, action_type, target, level, risk_level, requested_by, entity_type, entity_id, now()],
            )?;
            super::audit::record(tx, "approval.requested", "user", requested_by, "approval", &id)?;
            Ok(())
        })?;
        conn.query_row("SELECT * FROM approvals WHERE id = ?1", [id.clone()], map).map_err(not_found(&id))
    }

    /// True when a decided, still-unconsumed approval exists for the full
    /// gating tuple — entity id, entity type, AND action type (M-2). A grant
    /// for a different action or entity kind never satisfies the gate.
    pub fn approved_for(
        conn: &Connection,
        entity_id: &str,
        entity_type: &str,
        action_type: &str,
    ) -> CoreResult<bool> {
        let n: i64 = conn.query_row(
            "SELECT COUNT(*) FROM approvals
               WHERE entity_id = ?1 AND entity_type = ?2 AND action_type = ?3
                 AND status = 'approved' AND decided_at IS NOT NULL",
            rusqlite::params![entity_id, entity_type, action_type],
            |r| r.get(0),
        )?;
        Ok(n > 0)
    }

    /// Consume the approved grant(s) for a gating tuple so a single approval
    /// unlocks exactly one completion (M-2). Must run in the same transaction
    /// as the write that completes the gated work.
    pub fn consume_for(
        conn: &Connection,
        entity_id: &str,
        entity_type: &str,
        action_type: &str,
    ) -> CoreResult<()> {
        conn.execute(
            "UPDATE approvals SET status = 'consumed'
              WHERE entity_id = ?1 AND entity_type = ?2 AND action_type = ?3 AND status = 'approved'",
            rusqlite::params![entity_id, entity_type, action_type],
        )?;
        Ok(())
    }

    /// True when a rejected approval exists for the gating tuple and none is
    /// approved — i.e. the entity is blocked by a rejection.
    pub fn rejected_for(
        conn: &Connection,
        entity_id: &str,
        entity_type: &str,
        action_type: &str,
    ) -> CoreResult<bool> {
        if approved_for(conn, entity_id, entity_type, action_type)? {
            return Ok(false);
        }
        let n: i64 = conn.query_row(
            "SELECT COUNT(*) FROM approvals
               WHERE entity_id = ?1 AND entity_type = ?2 AND action_type = ?3
                 AND status = 'rejected' AND decided_at IS NOT NULL",
            rusqlite::params![entity_id, entity_type, action_type],
            |r| r.get(0),
        )?;
        Ok(n > 0)
    }

    /// The most recent still-pending approval for an entity, if any.
    pub fn pending_for(conn: &Connection, entity_id: &str) -> CoreResult<Option<Approval>> {
        Ok(conn
            .query_row(
                "SELECT * FROM approvals WHERE entity_id = ?1 AND status = 'pending' ORDER BY requested_at DESC LIMIT 1",
                [entity_id],
                map,
            )
            .optional()?)
    }

    /// Decide a pending approval. `decision` must be "approved" or "rejected".
    pub fn decide(conn: &Connection, id: &str, decision: &str, note: Option<&str>) -> CoreResult<Approval> {
        if !is_valid(decision, APPROVAL_DECISIONS) {
            return Err(CoreError::Invalid { field: "decision", value: decision.to_string() });
        }
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE approvals SET status = ?1, decision_note = ?2, decided_at = ?3 WHERE id = ?4 AND status = 'pending'",
                rusqlite::params![decision, note, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(format!("pending approval {id}")));
            }
            super::audit::record(tx, "approval.decided", "user", "gev", "approval", id)?;
            Ok(())
        })?;
        conn.query_row("SELECT * FROM approvals WHERE id = ?1", [id], map).map_err(not_found(id))
    }
}

pub mod notifications {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<Notification> {
        Ok(Notification {
            id: r.get("id")?,
            kind: r.get("type")?,
            severity: r.get("severity")?,
            title: r.get("title")?,
            body: r.get("body")?,
            entity_type: r.get("entity_type")?,
            entity_id: r.get("entity_id")?,
            read_at: r.get("read_at")?,
            created_at: r.get("created_at")?,
        })
    }

    /// A bounded page of notifications, newest first. `limit` is clamped to
    /// `MAX_PAGE` and defaults to `DEFAULT_PAGE`; `offset` defaults to 0.
    pub fn list(conn: &Connection, limit: Option<u32>, offset: Option<u32>) -> CoreResult<Vec<Notification>> {
        let (limit, offset) = super::page(limit, offset);
        let mut s = conn.prepare("SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?1 OFFSET ?2")?;
        let rows = s.query_map(rusqlite::params![limit, offset], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn mark_read(conn: &Connection, id: &str) -> CoreResult<Notification> {
        let changed = conn.execute(
            "UPDATE notifications SET read_at = ?1 WHERE id = ?2 AND read_at IS NULL",
            rusqlite::params![now(), id],
        )?;
        if changed == 0 {
            // already read or missing; return current row if it exists
            return conn.query_row("SELECT * FROM notifications WHERE id = ?1", [id], map).map_err(not_found(id));
        }
        conn.query_row("SELECT * FROM notifications WHERE id = ?1", [id], map).map_err(not_found(id))
    }
}

pub mod decisions {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<Decision> {
        Ok(Decision {
            id: r.get("id")?,
            title: r.get("title")?,
            status: r.get("status")?,
            owner: r.get("owner")?,
            rationale: r.get("rationale")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, title: &str, owner: &str, rationale: &str) -> CoreResult<Decision> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO decisions(id, title, status, owner, rationale, created_at, updated_at)
                 VALUES (?1, ?2, 'proposed', ?3, ?4, ?5, ?5)",
                rusqlite::params![id, title, owner, rationale, now],
            )?;
            super::audit::record(tx, "decision.created", "user", "gev", "decision", &id)?;
            Ok(())
        })?;
        conn.query_row("SELECT * FROM decisions WHERE id = ?1", [id.clone()], map).map_err(not_found(&id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Decision>> {
        let mut s = conn.prepare("SELECT * FROM decisions ORDER BY updated_at DESC LIMIT ?1")?;
        let rows = s.query_map([super::MAX_PAGE], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }
}

pub mod activity {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<ActivityEvent> {
        Ok(ActivityEvent {
            id: r.get("id")?,
            event_type: r.get("event_type")?,
            actor_id: r.get("actor_id")?,
            entity_type: r.get("entity_type")?,
            entity_id: r.get("entity_id")?,
            created_at: r.get("created_at")?,
        })
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<ActivityEvent>> {
        let mut s = conn.prepare("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 200")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }
}

pub mod chat {
    use super::*;

    fn map_conversation(r: &Row) -> rusqlite::Result<Conversation> {
        Ok(Conversation {
            id: r.get("id")?,
            kind: r.get("kind")?,
            title: r.get("title")?,
            message_count: r.get("message_count")?,
            last_message_at: r.get("last_message_at")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    fn map_message(r: &Row) -> rusqlite::Result<Message> {
        Ok(Message {
            id: r.get("id")?,
            conversation_id: r.get("conversation_id")?,
            role: r.get("role")?,
            author: r.get("author")?,
            body: r.get("body")?,
            created_at: r.get("created_at")?,
        })
    }

    // Conversations carry a derived message count and last-activity timestamp so
    // the list view needs a single round trip.
    const CONVERSATION_SELECT: &str = "SELECT c.id, c.kind, c.title, c.created_at, c.updated_at, \
         COUNT(m.id) AS message_count, MAX(m.created_at) AS last_message_at \
         FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id";

    pub fn create_conversation(conn: &Connection, kind: &str, title: &str) -> CoreResult<Conversation> {
        if !is_valid(kind, CONVERSATION_KINDS) {
            return Err(CoreError::Invalid { field: "kind", value: kind.to_string() });
        }
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO conversations(id, kind, title, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?4)",
                rusqlite::params![id, kind, title, now],
            )?;
            super::audit::record(tx, "conversation.created", "user", "gev", "conversation", &id)?;
            Ok(())
        })?;
        get_conversation(conn, &id)
    }

    pub fn get_conversation(conn: &Connection, id: &str) -> CoreResult<Conversation> {
        let sql = format!("{CONVERSATION_SELECT} WHERE c.id = ?1 GROUP BY c.id");
        conn.query_row(&sql, [id], map_conversation).map_err(not_found(id))
    }

    pub fn list_conversations(conn: &Connection, kind: Option<&str>) -> CoreResult<Vec<Conversation>> {
        match kind {
            Some(k) => {
                let sql = format!("{CONVERSATION_SELECT} WHERE c.kind = ?1 GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?2");
                let mut s = conn.prepare(&sql)?;
                let rows = s.query_map(rusqlite::params![k, super::MAX_PAGE], map_conversation)?;
                Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
            }
            None => {
                let sql = format!("{CONVERSATION_SELECT} GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?1");
                let mut s = conn.prepare(&sql)?;
                let rows = s.query_map([super::MAX_PAGE], map_conversation)?;
                Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
            }
        }
    }

    /// A bounded page of messages in chronological order. The page is anchored
    /// at the **newest** end: `offset` 0 returns the latest `limit` messages
    /// (still oldest-first within the page) and larger offsets walk back
    /// through history — so both the chat view and AI-history callers see the
    /// most recent context by default (L-1a). `limit` is clamped to `MAX_PAGE`
    /// and defaults to `DEFAULT_PAGE`.
    pub fn list_messages(
        conn: &Connection,
        conversation_id: &str,
        limit: Option<u32>,
        offset: Option<u32>,
    ) -> CoreResult<Vec<Message>> {
        let (limit, offset) = super::page(limit, offset);
        let mut s = conn.prepare(
            "SELECT * FROM messages WHERE conversation_id = ?1 \
             ORDER BY created_at DESC, rowid DESC LIMIT ?2 OFFSET ?3",
        )?;
        let rows = s.query_map(rusqlite::params![conversation_id, limit, offset], map_message)?;
        let mut msgs = rows.collect::<rusqlite::Result<Vec<_>>>()?;
        msgs.reverse(); // newest page, presented oldest-first
        Ok(msgs)
    }

    /// Append a message to a conversation and bump the conversation's activity
    /// timestamp. Rejects an unknown conversation and invalid role.
    pub fn post_message(conn: &Connection, input: NewMessage) -> CoreResult<Message> {
        if !is_valid(&input.role, MESSAGE_ROLES) {
            return Err(CoreError::Invalid { field: "role", value: input.role });
        }
        let now = now();
        let id = id();
        // Message insert, conversation bump, and audit row commit atomically —
        // a crash can no longer leave a message without its activity bump or
        // audit trail (M-5).
        super::atomic(conn, |tx| {
            // Fail cleanly if the conversation does not exist (FK would also reject).
            get_conversation(tx, &input.conversation_id)?;
            tx.execute(
                "INSERT INTO messages(id, conversation_id, role, author, body, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                rusqlite::params![id, input.conversation_id, input.role, input.author, input.body, now],
            )?;
            tx.execute(
                "UPDATE conversations SET updated_at = ?1 WHERE id = ?2",
                rusqlite::params![now, input.conversation_id],
            )?;
            // The message role doubles as the audit actor type: user messages
            // audit as 'user', agent messages as 'agent' (L-4a).
            super::audit::record(tx, "message.posted", &input.role, &input.author, "conversation", &input.conversation_id)?;
            Ok(())
        })?;
        conn.query_row("SELECT * FROM messages WHERE id = ?1", [id.clone()], map_message)
            .map_err(not_found(&id))
    }

    /// Delete a conversation and (via the FK cascade) all of its messages.
    /// Rejects an unknown conversation.
    pub fn delete_conversation(conn: &Connection, id: &str) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM conversations WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "conversation.deleted", "user", "gev", "conversation", id)?;
            Ok(())
        })
    }

    /// Rename a conversation and bump its activity timestamp. Rejects an unknown
    /// conversation.
    pub fn rename_conversation(conn: &Connection, id: &str, title: &str) -> CoreResult<Conversation> {
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE conversations SET title = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![title, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "conversation.renamed", "user", "gev", "conversation", id)?;
            Ok(())
        })?;
        get_conversation(conn, id)
    }
}

pub mod knowledge {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<KnowledgeNote> {
        Ok(KnowledgeNote {
            id: r.get("id")?,
            title: r.get("title")?,
            body: r.get("body")?,
            source: r.get("source")?,
            tags: r.get("tags")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, input: NewKnowledgeNote) -> CoreResult<KnowledgeNote> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO knowledge_notes(id, title, body, source, tags, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
                rusqlite::params![id, input.title, input.body, input.source, input.tags, now],
            )?;
            super::audit::record(tx, "knowledge.created", "user", "gev", "knowledge_note", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<KnowledgeNote> {
        conn.query_row("SELECT * FROM knowledge_notes WHERE id = ?1", [id], map)
            .map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<KnowledgeNote>> {
        let mut s = conn.prepare("SELECT * FROM knowledge_notes ORDER BY updated_at DESC LIMIT ?1")?;
        let rows = s.query_map([super::MAX_PAGE], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Case-insensitive substring search over title, body, and tags. An empty
    /// query returns everything (same as `list`).
    pub fn search(conn: &Connection, query: &str) -> CoreResult<Vec<KnowledgeNote>> {
        let q = query.trim();
        if q.is_empty() {
            return list(conn);
        }
        // Escape LIKE wildcards so a literal % or _ in the query matches itself
        // instead of acting as a wildcard.
        let escaped = q.replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_");
        let like = format!("%{escaped}%");
        let mut s = conn.prepare(
            "SELECT * FROM knowledge_notes \
             WHERE title LIKE ?1 ESCAPE '\\' OR body LIKE ?1 ESCAPE '\\' OR tags LIKE ?1 ESCAPE '\\' \
             ORDER BY updated_at DESC LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![like, super::MAX_PAGE], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn delete(conn: &Connection, id: &str) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM knowledge_notes WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "knowledge.deleted", "user", "gev", "knowledge_note", id)?;
            Ok(())
        })
    }
}

pub mod memory {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<MemoryEntry> {
        Ok(MemoryEntry {
            id: r.get("id")?,
            scope: r.get("scope")?,
            kind: r.get("kind")?,
            content: r.get("content")?,
            pinned: r.get::<_, i64>("pinned")? != 0,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, input: NewMemoryEntry) -> CoreResult<MemoryEntry> {
        if !is_valid(&input.kind, MEMORY_KINDS) {
            return Err(CoreError::Invalid { field: "kind", value: input.kind });
        }
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO memory_entries(id, scope, kind, content, pinned, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, 0, ?5, ?5)",
                rusqlite::params![id, input.scope, input.kind, input.content, now],
            )?;
            super::audit::record(tx, "memory.created", "user", "gev", "memory_entry", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<MemoryEntry> {
        conn.query_row("SELECT * FROM memory_entries WHERE id = ?1", [id], map)
            .map_err(not_found(id))
    }

    /// List entries, pinned first, then most-recently updated. Optionally
    /// filtered to a single scope.
    pub fn list(conn: &Connection, scope: Option<&str>) -> CoreResult<Vec<MemoryEntry>> {
        match scope {
            Some(sc) => {
                let mut s = conn.prepare(
                    "SELECT * FROM memory_entries WHERE scope = ?1 ORDER BY pinned DESC, updated_at DESC LIMIT ?2",
                )?;
                let rows = s.query_map(rusqlite::params![sc, super::MAX_PAGE], map)?;
                Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
            }
            None => {
                let mut s = conn.prepare(
                    "SELECT * FROM memory_entries ORDER BY pinned DESC, updated_at DESC LIMIT ?1",
                )?;
                let rows = s.query_map([super::MAX_PAGE], map)?;
                Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
            }
        }
    }

    pub fn set_pinned(conn: &Connection, id: &str, pinned: bool) -> CoreResult<MemoryEntry> {
        let changed = conn.execute(
            "UPDATE memory_entries SET pinned = ?1, updated_at = ?2 WHERE id = ?3",
            rusqlite::params![pinned as i64, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        get(conn, id)
    }

    pub fn delete(conn: &Connection, id: &str) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM memory_entries WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "memory.deleted", "user", "gev", "memory_entry", id)?;
            Ok(())
        })
    }
}

pub mod runs {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<Run> {
        Ok(Run {
            id: r.get("id")?,
            intent: r.get("intent")?,
            status: r.get("status")?,
            plan: r.get("plan")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, intent: &str, plan: &str) -> CoreResult<Run> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO runs(id, intent, status, plan, created_at, updated_at)
                 VALUES (?1, ?2, 'drafted', ?3, ?4, ?4)",
                rusqlite::params![id, intent, plan, now],
            )?;
            super::audit::record(tx, "run.created", "user", "gev", "run", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Run> {
        conn.query_row("SELECT * FROM runs WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Run>> {
        let mut s = conn.prepare("SELECT * FROM runs ORDER BY updated_at DESC LIMIT ?1")?;
        let rows = s.query_map([super::MAX_PAGE], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn set_status(conn: &Connection, id: &str, status: &str) -> CoreResult<Run> {
        if !is_valid(status, RUN_STATUSES) {
            return Err(CoreError::Invalid { field: "status", value: status.to_string() });
        }
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE runs SET status = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![status, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "run.status_changed", "user", "gev", "run", id)?;
            Ok(())
        })?;
        get(conn, id)
    }

    // --- run steps: the ordered plan the run executes through ---

    fn map_step(r: &Row) -> rusqlite::Result<RunStep> {
        Ok(RunStep {
            id: r.get("id")?,
            run_id: r.get("run_id")?,
            position: r.get("position")?,
            title: r.get("title")?,
            detail: r.get("detail")?,
            status: r.get("status")?,
            result: r.get("result")?,
            requires_approval: r.get::<_, i64>("requires_approval")? != 0,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    /// Flag (or unflag) whether a step needs approval before it can execute.
    pub fn set_step_requires_approval(conn: &Connection, id: &str, requires: bool) -> CoreResult<RunStep> {
        let changed = conn.execute(
            "UPDATE run_steps SET requires_approval = ?1, updated_at = ?2 WHERE id = ?3",
            rusqlite::params![requires as i64, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        get_step(conn, id)
    }

    /// The step an execution should run next: the active one if present,
    /// otherwise the lowest-position pending one. `None` when nothing remains.
    pub fn next_runnable_step(conn: &Connection, run_id: &str) -> CoreResult<Option<RunStep>> {
        if let Some(active) = conn
            .query_row(
                "SELECT * FROM run_steps WHERE run_id = ?1 AND status = 'active' ORDER BY position LIMIT 1",
                [run_id],
                map_step,
            )
            .optional()?
        {
            return Ok(Some(active));
        }
        let pending = conn
            .query_row(
                "SELECT * FROM run_steps WHERE run_id = ?1 AND status = 'pending' ORDER BY position LIMIT 1",
                [run_id],
                map_step,
            )
            .optional()?;
        Ok(pending)
    }

    /// Record a produced result for a step and mark it done. Enforces the same
    /// approval gate as `set_step_status` — a gated step can never be marked
    /// done without a matching approval, whichever function sets it (M-3). The
    /// gate read, the UPDATE, and the approval consumption run in one
    /// transaction so the guarantee lives with the write.
    pub fn set_step_result(conn: &Connection, id: &str, result: &str) -> CoreResult<RunStep> {
        super::atomic(conn, |tx| {
            let step = get_step(tx, id)?;
            if step.requires_approval {
                if !super::approvals::approved_for(
                    tx,
                    id,
                    super::approvals::RUN_STEP_ENTITY_TYPE,
                    super::approvals::RUN_STEP_ACTION_TYPE,
                )? {
                    return Err(CoreError::Invalid {
                        field: "status",
                        value: "step requires approval before it can be completed".to_string(),
                    });
                }
                // one grant unlocks one completion (M-2)
                super::approvals::consume_for(
                    tx,
                    id,
                    super::approvals::RUN_STEP_ENTITY_TYPE,
                    super::approvals::RUN_STEP_ACTION_TYPE,
                )?;
            }
            tx.execute(
                "UPDATE run_steps SET result = ?1, status = 'done', updated_at = ?2 WHERE id = ?3",
                rusqlite::params![result, now(), id],
            )?;
            super::audit::record(tx, "run_step.executed", "user", "gev", "run_step", id)?;
            Ok(())
        })?;
        get_step(conn, id)
    }

    pub fn add_step(conn: &Connection, run_id: &str, title: &str, detail: &str) -> CoreResult<RunStep> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            get(tx, run_id)?; // reject an unknown run before inserting
            // Compute the next position inside the INSERT itself so two
            // concurrent adds cannot read the same MAX and collide (L-3a; a
            // UNIQUE(run_id, position) index backs this at the schema level).
            tx.execute(
                "INSERT INTO run_steps(id, run_id, position, title, detail, status, created_at, updated_at)
                 SELECT ?1, ?2, COALESCE(MAX(position), 0) + 1, ?3, ?4, 'pending', ?5, ?5
                   FROM run_steps WHERE run_id = ?2",
                rusqlite::params![id, run_id, title, detail, now],
            )?;
            Ok(())
        })?;
        get_step(conn, &id)
    }

    pub fn get_step(conn: &Connection, id: &str) -> CoreResult<RunStep> {
        conn.query_row("SELECT * FROM run_steps WHERE id = ?1", [id], map_step).map_err(not_found(id))
    }

    pub fn list_steps(conn: &Connection, run_id: &str) -> CoreResult<Vec<RunStep>> {
        let mut s = conn.prepare("SELECT * FROM run_steps WHERE run_id = ?1 ORDER BY position")?;
        let rows = s.query_map([run_id], map_step)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn set_step_status(conn: &Connection, id: &str, status: &str) -> CoreResult<RunStep> {
        if !is_valid(status, STEP_STATUSES) {
            return Err(CoreError::Invalid { field: "status", value: status.to_string() });
        }
        super::atomic(conn, |tx| {
            // Enforce the approval gate here too, not just in advance()/stream_run_step:
            // a gated step can never be marked `done` without a matching approval,
            // whichever command sets it. Gate read and UPDATE share one transaction.
            if status == "done" {
                let step = get_step(tx, id)?;
                if step.requires_approval {
                    if !super::approvals::approved_for(
                        tx,
                        id,
                        super::approvals::RUN_STEP_ENTITY_TYPE,
                        super::approvals::RUN_STEP_ACTION_TYPE,
                    )? {
                        return Err(CoreError::Invalid {
                            field: "status",
                            value: "step requires approval before it can be completed".to_string(),
                        });
                    }
                    // one grant unlocks one completion (M-2)
                    super::approvals::consume_for(
                        tx,
                        id,
                        super::approvals::RUN_STEP_ENTITY_TYPE,
                        super::approvals::RUN_STEP_ACTION_TYPE,
                    )?;
                }
            }
            let changed = tx.execute(
                "UPDATE run_steps SET status = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![status, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            Ok(())
        })?;
        get_step(conn, id)
    }

    /// Advance a run's execution by one step: mark the active step done and
    /// activate the next pending one. When no pending steps remain the run
    /// terminates: `failed` if any step failed, `succeeded` only when the work
    /// actually completed (M-6); the run moves to `running` on the first
    /// advance. This models the lifecycle only — it never executes anything on
    /// the host.
    ///
    /// Rejects advancing a terminated run (succeeded/failed/cancelled) or a run
    /// with no steps. All reads and state changes share one transaction.
    pub fn advance(conn: &Connection, run_id: &str) -> CoreResult<Run> {
        super::atomic(conn, |tx| {
            let run = get(tx, run_id)?;
            if matches!(run.status.as_str(), "succeeded" | "failed" | "cancelled") {
                return Err(CoreError::Invalid { field: "status", value: run.status });
            }
            let total_steps: i64 =
                tx.query_row("SELECT COUNT(*) FROM run_steps WHERE run_id = ?1", [run_id], |r| r.get(0))?;
            if total_steps == 0 {
                return Err(CoreError::Invalid { field: "steps", value: "none".to_string() });
            }

            // A manual advance must not complete a gated step that isn't approved —
            // that would bypass the approval. Execution goes through stream_run_step,
            // which handles the gate (and only calls advance once the step is done).
            let active = tx
                .query_row(
                    "SELECT * FROM run_steps WHERE run_id = ?1 AND status = 'active' ORDER BY position LIMIT 1",
                    [run_id],
                    map_step,
                )
                .optional()?;
            if let Some(active) = &active {
                if active.requires_approval
                    && !super::approvals::approved_for(
                        tx,
                        &active.id,
                        super::approvals::RUN_STEP_ENTITY_TYPE,
                        super::approvals::RUN_STEP_ACTION_TYPE,
                    )?
                {
                    return Err(CoreError::Invalid { field: "approval", value: "required".to_string() });
                }
            }

            let now = now();
            tx.execute(
                "UPDATE run_steps SET status = 'done', updated_at = ?1 WHERE run_id = ?2 AND status = 'active'",
                rusqlite::params![now, run_id],
            )?;
            // The grant that unlocked the just-completed gated step is spent
            // in the same transaction (M-2).
            if let Some(active) = &active {
                if active.requires_approval {
                    super::approvals::consume_for(
                        tx,
                        &active.id,
                        super::approvals::RUN_STEP_ENTITY_TYPE,
                        super::approvals::RUN_STEP_ACTION_TYPE,
                    )?;
                }
            }
            // Only QueryReturnedNoRows becomes None; any real error propagates.
            let next: Option<String> = tx
                .query_row(
                    "SELECT id FROM run_steps WHERE run_id = ?1 AND status = 'pending' ORDER BY position LIMIT 1",
                    [run_id],
                    |r| r.get(0),
                )
                .optional()?;
            match next {
                Some(step_id) => {
                    tx.execute(
                        "UPDATE run_steps SET status = 'active', updated_at = ?1 WHERE id = ?2",
                        rusqlite::params![now, step_id],
                    )?;
                    if run.status != "running" {
                        set_status(tx, run_id, "running")?;
                    }
                }
                None => {
                    // No active or pending step remains — inspect outcomes
                    // before stamping the terminal status: a run with failed
                    // work must not report `succeeded` (M-6).
                    let failed: i64 = tx.query_row(
                        "SELECT COUNT(*) FROM run_steps WHERE run_id = ?1 AND status = 'failed'",
                        [run_id],
                        |r| r.get(0),
                    )?;
                    let terminal = if failed > 0 { "failed" } else { "succeeded" };
                    set_status(tx, run_id, terminal)?;
                }
            }
            super::audit::record(tx, "run.advanced", "user", "gev", "run", run_id)?;
            Ok(())
        })?;
        get(conn, run_id)
    }
}

pub mod events {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<Event> {
        Ok(Event {
            id: r.get("id")?,
            title: r.get("title")?,
            kind: r.get("kind")?,
            location: r.get("location")?,
            starts_at: r.get("starts_at")?,
            ends_at: r.get("ends_at")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, input: NewEvent) -> CoreResult<Event> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO events(id, title, kind, location, starts_at, ends_at, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?7)",
                rusqlite::params![id, input.title, input.kind, input.location, input.starts_at, input.ends_at, now],
            )?;
            super::audit::record(tx, "event.created", "user", "gev", "event", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Event> {
        conn.query_row("SELECT * FROM events WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Event>> {
        let mut s = conn.prepare("SELECT * FROM events ORDER BY starts_at ASC LIMIT ?1")?;
        let rows = s.query_map([super::MAX_PAGE], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn delete(conn: &Connection, id: &str) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM events WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "event.deleted", "user", "gev", "event", id)?;
            Ok(())
        })
    }
}

pub mod automations {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<Automation> {
        Ok(Automation {
            id: r.get("id")?,
            name: r.get("name")?,
            trigger: r.get("trigger")?,
            action: r.get("action")?,
            enabled: r.get::<_, i64>("enabled")? != 0,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, input: NewAutomation) -> CoreResult<Automation> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO automations(id, name, trigger, action, enabled, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, 1, ?5, ?5)",
                rusqlite::params![id, input.name, input.trigger, input.action, now],
            )?;
            super::audit::record(tx, "automation.created", "user", "gev", "automation", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Automation> {
        conn.query_row("SELECT * FROM automations WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Automation>> {
        let mut s = conn.prepare("SELECT * FROM automations ORDER BY name LIMIT ?1")?;
        let rows = s.query_map([super::MAX_PAGE], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn set_enabled(conn: &Connection, id: &str, enabled: bool) -> CoreResult<Automation> {
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE automations SET enabled = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![enabled as i64, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "automation.toggled", "user", "gev", "automation", id)?;
            Ok(())
        })?;
        get(conn, id)
    }

    pub fn delete(conn: &Connection, id: &str) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM automations WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "automation.deleted", "user", "gev", "automation", id)?;
            Ok(())
        })
    }
}

pub mod integrations {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<Integration> {
        Ok(Integration {
            id: r.get("id")?,
            name: r.get("name")?,
            provider: r.get("provider")?,
            status: r.get("status")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, name: &str, provider: &str) -> CoreResult<Integration> {
        let now = now();
        let id = id();
        conn.execute(
            "INSERT INTO integrations(id, name, provider, status, created_at, updated_at)
             VALUES (?1, ?2, ?3, 'disconnected', ?4, ?4)",
            rusqlite::params![id, name, provider, now],
        )?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Integration> {
        conn.query_row("SELECT * FROM integrations WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Integration>> {
        let mut s = conn.prepare("SELECT * FROM integrations ORDER BY name")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Set a connector's local status. This records the desired state; it does
    /// not itself reach any external service.
    pub fn set_status(conn: &Connection, id: &str, status: &str) -> CoreResult<Integration> {
        if !is_valid(status, INTEGRATION_STATUSES) {
            return Err(CoreError::Invalid { field: "status", value: status.to_string() });
        }
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE integrations SET status = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![status, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "integration.status_changed", "user", "gev", "integration", id)?;
            Ok(())
        })?;
        get(conn, id)
    }
}

pub mod analytics {
    use super::*;

    fn count(conn: &Connection, sql: &str) -> CoreResult<i64> {
        Ok(conn.query_row(sql, [], |r| r.get(0))?)
    }

    /// A curated set of headline counts computed over the live tables.
    pub fn metrics(conn: &Connection) -> CoreResult<Vec<Metric>> {
        let defs: &[(&str, &str, &str)] = &[
            ("projects", "Projects", "SELECT COUNT(*) FROM projects"),
            ("projects_active", "Active projects", "SELECT COUNT(*) FROM projects WHERE status = 'active'"),
            ("tasks", "Tasks", "SELECT COUNT(*) FROM tasks"),
            ("tasks_open", "Open tasks", "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('done','cancelled')"),
            ("approvals_pending", "Pending approvals", "SELECT COUNT(*) FROM approvals WHERE status = 'pending'"),
            ("runs", "Runs", "SELECT COUNT(*) FROM runs"),
            ("events", "Events", "SELECT COUNT(*) FROM events"),
            ("automations_on", "Automations enabled", "SELECT COUNT(*) FROM automations WHERE enabled = 1"),
            ("knowledge", "Knowledge notes", "SELECT COUNT(*) FROM knowledge_notes"),
            ("memory", "Memory entries", "SELECT COUNT(*) FROM memory_entries"),
            ("audit", "Audit events", "SELECT COUNT(*) FROM audit_events"),
        ];
        let mut out = Vec::with_capacity(defs.len());
        for (key, label, sql) in defs {
            out.push(Metric { key: (*key).to_string(), label: (*label).to_string(), value: count(conn, sql)? });
        }
        Ok(out)
    }
}

pub mod security {
    use super::*;

    fn map_event(r: &Row) -> rusqlite::Result<ActivityEvent> {
        Ok(ActivityEvent {
            id: r.get("id")?,
            event_type: r.get("event_type")?,
            actor_id: r.get("actor_id")?,
            entity_type: r.get("entity_type")?,
            entity_id: r.get("entity_id")?,
            created_at: r.get("created_at")?,
        })
    }

    /// Read-only security posture computed from approvals and the audit log.
    /// "Sensitive" events are approvals, deletions, and status changes.
    pub fn summary(conn: &Connection) -> CoreResult<SecuritySummary> {
        let pending: i64 = conn.query_row(
            "SELECT COUNT(*) FROM approvals WHERE status = 'pending'", [], |r| r.get(0))?;
        // 'consumed' grants were approved and then spent by a completed step
        // (M-2) — they remain decided approvals for posture reporting.
        let decided: i64 = conn.query_row(
            "SELECT COUNT(*) FROM approvals WHERE status IN ('approved','rejected','consumed')", [], |r| r.get(0))?;
        let audit: i64 = conn.query_row("SELECT COUNT(*) FROM audit_events", [], |r| r.get(0))?;

        let mut s = conn.prepare(
            "SELECT * FROM audit_events \
             WHERE event_type LIKE '%approval%' OR event_type LIKE '%deleted%' \
                OR event_type LIKE '%status_changed%' \
             ORDER BY created_at DESC LIMIT 25",
        )?;
        let rows = s.query_map([], map_event)?;
        let sensitive = rows.collect::<rusqlite::Result<Vec<_>>>()?;

        Ok(SecuritySummary {
            pending_approvals: pending,
            decided_approvals: decided,
            audit_events: audit,
            sensitive_events: sensitive,
        })
    }
}

pub mod search {
    use super::*;

    /// Per-entity result cap so no single kind floods the palette.
    const CAP: i64 = 5;

    /// Truncate a string to at most `max` characters (on a char boundary),
    /// appending an ellipsis when it was cut.
    fn clip(s: &str, max: usize) -> String {
        if s.chars().count() <= max {
            s.to_string()
        } else {
            format!("{}…", s.chars().take(max).collect::<String>())
        }
    }

    /// Turn free user text into a safe FTS5 MATCH query: each whitespace token
    /// becomes a quoted prefix term joined by implicit AND (e.g. `foo ba` →
    /// `"foo"* "ba"*`). Punctuation is stripped so the query can never be an FTS
    /// syntax error; non-ASCII letters (Armenian, Cyrillic) are kept. Returns
    /// None when no usable token remains, so the caller returns no results.
    fn fts_query(query: &str) -> Option<String> {
        let mut terms: Vec<String> = Vec::new();
        for raw in query.split_whitespace() {
            let cleaned: String = raw.chars().filter(|c| c.is_alphanumeric() || *c == '_').collect();
            if !cleaned.is_empty() {
                terms.push(format!("\"{cleaned}\"*"));
            }
        }
        if terms.is_empty() { None } else { Some(terms.join(" ")) }
    }

    /// Full-text search across the primary entities via the `search_index` FTS5
    /// table (tokenized, prefix, multi-term AND). An empty/whitespace query
    /// yields no results. Each entity kind contributes at most `CAP` rows;
    /// results are grouped by kind in a stable order.
    pub fn global(conn: &Connection, query: &str) -> CoreResult<Vec<SearchResult>> {
        let fts = match fts_query(query) {
            Some(f) => f,
            None => return Ok(Vec::new()),
        };
        let mut out: Vec<SearchResult> = Vec::new();

        // projects
        let mut s = conn.prepare(
            "SELECT id, name, status FROM projects \
             WHERE id IN (SELECT entity_id FROM search_index WHERE kind = 'project' AND search_index MATCH ?1) \
             ORDER BY updated_at DESC LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![fts, CAP], |r| {
            Ok(SearchResult {
                kind: "project".to_string(),
                id: r.get("id")?,
                title: r.get("name")?,
                subtitle: r.get("status")?,
                route: "projects".to_string(),
            })
        })?;
        out.extend(rows.collect::<rusqlite::Result<Vec<_>>>()?);

        // tasks
        let mut s = conn.prepare(
            "SELECT id, title, status FROM tasks \
             WHERE id IN (SELECT entity_id FROM search_index WHERE kind = 'task' AND search_index MATCH ?1) \
             ORDER BY updated_at DESC LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![fts, CAP], |r| {
            Ok(SearchResult {
                kind: "task".to_string(),
                id: r.get("id")?,
                title: r.get("title")?,
                subtitle: r.get("status")?,
                route: "tasks".to_string(),
            })
        })?;
        out.extend(rows.collect::<rusqlite::Result<Vec<_>>>()?);

        // knowledge notes
        let mut s = conn.prepare(
            "SELECT id, title, tags FROM knowledge_notes \
             WHERE id IN (SELECT entity_id FROM search_index WHERE kind = 'knowledge' AND search_index MATCH ?1) \
             ORDER BY updated_at DESC LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![fts, CAP], |r| {
            Ok(SearchResult {
                kind: "knowledge".to_string(),
                id: r.get("id")?,
                title: r.get("title")?,
                subtitle: r.get("tags")?,
                route: "knowledge".to_string(),
            })
        })?;
        out.extend(rows.collect::<rusqlite::Result<Vec<_>>>()?);

        // decisions
        let mut s = conn.prepare(
            "SELECT id, title, status FROM decisions \
             WHERE id IN (SELECT entity_id FROM search_index WHERE kind = 'decision' AND search_index MATCH ?1) \
             ORDER BY updated_at DESC LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![fts, CAP], |r| {
            Ok(SearchResult {
                kind: "decision".to_string(),
                id: r.get("id")?,
                title: r.get("title")?,
                subtitle: r.get("status")?,
                route: "decisions".to_string(),
            })
        })?;
        out.extend(rows.collect::<rusqlite::Result<Vec<_>>>()?);

        // agents
        let mut s = conn.prepare(
            "SELECT id, display_name, role FROM agents \
             WHERE id IN (SELECT entity_id FROM search_index WHERE kind = 'agent' AND search_index MATCH ?1) \
             ORDER BY display_name LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![fts, CAP], |r| {
            Ok(SearchResult {
                kind: "agent".to_string(),
                id: r.get("id")?,
                title: r.get("display_name")?,
                subtitle: r.get("role")?,
                route: "agents".to_string(),
            })
        })?;
        out.extend(rows.collect::<rusqlite::Result<Vec<_>>>()?);

        // conversations (route depends on the conversation kind)
        let mut s = conn.prepare(
            "SELECT id, title, kind FROM conversations \
             WHERE id IN (SELECT entity_id FROM search_index WHERE kind = 'conversation' AND search_index MATCH ?1) \
             ORDER BY updated_at DESC LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![fts, CAP], |r| {
            let conv_kind: String = r.get("kind")?;
            let route = if conv_kind == "group" { "groupChat" } else { "chat" };
            Ok(SearchResult {
                kind: "conversation".to_string(),
                id: r.get("id")?,
                title: r.get("title")?,
                subtitle: conv_kind,
                route: route.to_string(),
            })
        })?;
        out.extend(rows.collect::<rusqlite::Result<Vec<_>>>()?);

        // memory entries (title is the content, truncated for the palette)
        let mut s = conn.prepare(
            "SELECT id, content, scope FROM memory_entries \
             WHERE id IN (SELECT entity_id FROM search_index WHERE kind = 'memory' AND search_index MATCH ?1) \
             ORDER BY pinned DESC, updated_at DESC LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![fts, CAP], |r| {
            let content: String = r.get("content")?;
            Ok(SearchResult {
                kind: "memory".to_string(),
                id: r.get("id")?,
                title: clip(&content, 60),
                subtitle: r.get("scope")?,
                route: "memory".to_string(),
            })
        })?;
        out.extend(rows.collect::<rusqlite::Result<Vec<_>>>()?);

        Ok(out)
    }
}

fn not_found(id: &str) -> impl Fn(rusqlite::Error) -> CoreError + '_ {
    move |e| match e {
        rusqlite::Error::QueryReturnedNoRows => CoreError::NotFound(id.to_string()),
        other => CoreError::Sqlite(other),
    }
}

/// Populate a fresh database with initial content so the app is demonstrable.
/// Real rows inserted through the repositories — not a mock layer. Idempotent:
/// runs only when there are no projects yet. The COUNT guard and every insert
/// share one transaction, so a failure mid-seed rolls back entirely instead of
/// locking in a partial seed forever (L-3b).
pub fn seed(conn: &Connection) -> CoreResult<()> {
    atomic(conn, |conn| {
        let existing: i64 = conn.query_row("SELECT COUNT(*) FROM projects", [], |r| r.get(0))?;
        if existing > 0 {
            return Ok(());
        }

        let specialists = [
            ("forge", "Forge", "Engineering", "claude-opus"),
            ("mason", "Mason", "Architecture", "claude-opus"),
            ("pixel", "Pixel", "Design", "claude-sonnet"),
            ("probe", "Probe", "Testing", "claude-sonnet"),
            ("shield", "Shield", "Security", "claude-opus"),
            ("lezu", "Lezu", "Localization", "claude-sonnet"),
        ];
        for (slug, name, role, model) in specialists {
            agents::create(conn, slug, name, role, model)?;
        }

        let p1 = projects::create(conn, NewProject { name: "BroPS Desktop Foundation".into(), description: "React + Tauri app shell and core runtime.".into(), priority: "high".into(), workspace_id: None })?;
        let p2 = projects::create(conn, NewProject { name: "Localization HY/EN/RU".into(), description: "Trilingual runtime parity.".into(), priority: "high".into(), workspace_id: None })?;
        projects::set_status(conn, &p1.id, "active")?;

        tasks::create(conn, NewTask { project_id: Some(p1.id.clone()), title: "Implement app shell + routing".into(), description: "".into(), priority: "high".into(), assigned_agent_id: None })?;
        let t2 = tasks::create(conn, NewTask { project_id: Some(p1.id.clone()), title: "Command palette (Ctrl/Cmd+K)".into(), description: "".into(), priority: "normal".into(), assigned_agent_id: None })?;
        tasks::set_status(conn, &t2.id, "active")?;
        tasks::create(conn, NewTask { project_id: Some(p2.id.clone()), title: "Russian dictionary parity".into(), description: "".into(), priority: "high".into(), assigned_agent_id: None })?;

        conn.execute(
            "INSERT INTO approvals(id, action_type, target, level, risk_level, status, requested_by, requested_at)
             VALUES (?1,'Send external email','vendor@example.com','A2','medium','pending','lezu',?2),
                    (?3,'Destructive DB migration','local database','A3','critical','pending','forge',?2)",
            rusqlite::params![id(), now(), id()],
        )?;

        conn.execute(
            "INSERT INTO notifications(id, type, severity, title, body, read_at, created_at)
             VALUES (?1,'approval_required','warning','Approval required','A destructive migration awaits your decision.',NULL,?2),
                    (?3,'run_completed','success','Run completed','Blocker digest finished with evidence.',NULL,?2)",
            rusqlite::params![id(), now(), id()],
        )?;

        decisions::create(conn, "Trilingual product scope (HY/EN/RU)", "gev", "Newest explicit decision supersedes bilingual wording (D-009).")?;
        decisions::create(conn, "Foundation v1 is Locked", "gev", "Reviewed, canonicalized, Phase 1 UX added (D-010).")?;

        let direct = chat::create_conversation(conn, "direct", "Bro")?;
        chat::post_message(conn, NewMessage { conversation_id: direct.id.clone(), role: "user".into(), author: "gev".into(), body: "Bro, where does the desktop build stand?".into() })?;
        chat::post_message(conn, NewMessage { conversation_id: direct.id.clone(), role: "agent".into(), author: "Bro".into(), body: "Data core is green and CRUD is wired to real SQLite. Chat is now persisted too.".into() })?;

        let room = chat::create_conversation(conn, "group", "Foundation room")?;
        chat::post_message(conn, NewMessage { conversation_id: room.id.clone(), role: "agent".into(), author: "Mason".into(), body: "Schema reached v3 — conversations and messages added.".into() })?;
        chat::post_message(conn, NewMessage { conversation_id: room.id.clone(), role: "agent".into(), author: "Probe".into(), body: "Chat repository covered by unit tests.".into() })?;

        knowledge::create(conn, NewKnowledgeNote { title: "Typed IPC boundary".into(), body: "React reaches SQLite only through #[tauri::command]s; no raw SQL crosses the boundary.".into(), source: "docs/architecture".into(), tags: "architecture,ipc".into() })?;
        knowledge::create(conn, NewKnowledgeNote { title: "Forward-only migrations".into(), body: "Schema advances one numbered migration at a time; runner is idempotent.".into(), source: "src-tauri/core/db.rs".into(), tags: "sqlite,migrations".into() })?;

        let m = memory::create(conn, NewMemoryEntry { scope: "global".into(), kind: "preference".into(), content: "Respond in Armenian; work only in menqstudio/BroPS.".into() })?;
        memory::set_pinned(conn, &m.id, true)?;
        memory::create(conn, NewMemoryEntry { scope: "global".into(), kind: "fact".into(), content: "Foundation v1 is Locked (D-010).".into() })?;

        let r1 = runs::create(conn, "Wire the remaining workspaces to the backend", "schema → repos → commands → UI")?;
        runs::add_step(conn, &r1.id, "Design schema", "migration 0005")?;
        runs::add_step(conn, &r1.id, "Write repositories", "")?;
        let gated = runs::add_step(conn, &r1.id, "Register commands", "")?;
        runs::set_step_requires_approval(conn, &gated.id, true)?; // demo: this step needs approval to run
        runs::add_step(conn, &r1.id, "Build the screens", "")?;
        runs::advance(conn, &r1.id)?; // moves the run to running with the first step active
        runs::create(conn, "Draft the Phase 6 verification report", "")?;

        let start = now();
        events::create(conn, NewEvent { title: "Phase 5 review".into(), kind: "review".into(), location: "Desktop".into(), starts_at: start.clone(), ends_at: None })?;
        events::create(conn, NewEvent { title: "Foundation sync".into(), kind: "meeting".into(), location: "Group Chat".into(), starts_at: start, ends_at: None })?;

        let a1 = automations::create(conn, NewAutomation { name: "Notify on failed run".into(), trigger: "run.status = failed".into(), action: "create notification".into() })?;
        let a2 = automations::create(conn, NewAutomation { name: "Auto-archive done projects".into(), trigger: "project.status = completed".into(), action: "set archived".into() })?;
        automations::set_enabled(conn, &a2.id, false)?;
        let _ = a1;

        let i1 = integrations::create(conn, "GitHub", "github")?;
        integrations::set_status(conn, &i1.id, "connected")?;
        integrations::create(conn, "Slack", "slack")?;

        Ok(())
    })
}
