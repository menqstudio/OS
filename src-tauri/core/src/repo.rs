//! Repositories: typed CRUD over the SQLite schema. No raw SQL escapes to callers.

use crate::domain::*;
use crate::{id, now};
use rusqlite::{Connection, OptionalExtension, Row};

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
        conn.execute(
            "INSERT INTO projects(id, workspace_id, name, description, status, priority, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, 'planned', ?5, ?6, ?6)",
            rusqlite::params![id, input.workspace_id, input.name, input.description, input.priority, now],
        )?;
        super::audit::record(conn, "project.created", "gev", "project", &id)?;
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
        let mut stmt = conn.prepare("SELECT * FROM projects ORDER BY updated_at DESC")?;
        let rows = stmt.query_map([], map_project)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn set_status(conn: &Connection, id: &str, status: &str) -> CoreResult<Project> {
        if !is_valid(status, PROJECT_STATUSES) {
            return Err(CoreError::Invalid { field: "status", value: status.to_string() });
        }
        let changed = conn.execute(
            "UPDATE projects SET status = ?1, updated_at = ?2 WHERE id = ?3",
            rusqlite::params![status, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "project.status_changed", "gev", "project", id)?;
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
        conn.execute(
            "INSERT INTO tasks(id, project_id, title, description, status, priority, assigned_agent_id, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, 'inbox', ?5, ?6, ?7, ?7)",
            rusqlite::params![id, input.project_id, input.title, input.description, input.priority, input.assigned_agent_id, now],
        )?;
        super::audit::record(conn, "task.created", "gev", "task", &id)?;
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

    pub fn set_status(conn: &Connection, id: &str, status: &str) -> CoreResult<Task> {
        if !is_valid(status, TASK_STATUSES) {
            return Err(CoreError::Invalid { field: "status", value: status.to_string() });
        }
        let completed = if status == "done" { Some(now()) } else { None };
        let changed = conn.execute(
            "UPDATE tasks SET status = ?1, completed_at = ?2, updated_at = ?3 WHERE id = ?4",
            rusqlite::params![status, completed, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "task.status_changed", "gev", "task", id)?;
        get(conn, id)
    }
}

pub mod audit {
    use super::*;

    pub fn record(
        conn: &Connection,
        event_type: &str,
        actor_id: &str,
        entity_type: &str,
        entity_id: &str,
    ) -> CoreResult<()> {
        conn.execute(
            "INSERT INTO audit_events(id, event_type, actor_type, actor_id, entity_type, entity_id, created_at)
             VALUES (?1, ?2, 'user', ?3, ?4, ?5, ?6)",
            rusqlite::params![id(), event_type, actor_id, entity_type, entity_id, now()],
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
            requested_at: r.get("requested_at")?,
            decided_at: r.get("decided_at")?,
        })
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Approval>> {
        let mut s = conn.prepare("SELECT * FROM approvals ORDER BY requested_at DESC")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Decide a pending approval. `decision` must be "approved" or "rejected".
    pub fn decide(conn: &Connection, id: &str, decision: &str, note: Option<&str>) -> CoreResult<Approval> {
        if !is_valid(decision, APPROVAL_DECISIONS) {
            return Err(CoreError::Invalid { field: "decision", value: decision.to_string() });
        }
        let changed = conn.execute(
            "UPDATE approvals SET status = ?1, decision_note = ?2, decided_at = ?3 WHERE id = ?4 AND status = 'pending'",
            rusqlite::params![decision, note, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(format!("pending approval {id}")));
        }
        super::audit::record(conn, "approval.decided", "gev", "approval", id)?;
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

    pub fn list(conn: &Connection) -> CoreResult<Vec<Notification>> {
        let mut s = conn.prepare("SELECT * FROM notifications ORDER BY created_at DESC")?;
        let rows = s.query_map([], map)?;
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
        conn.execute(
            "INSERT INTO decisions(id, title, status, owner, rationale, created_at, updated_at)
             VALUES (?1, ?2, 'proposed', ?3, ?4, ?5, ?5)",
            rusqlite::params![id, title, owner, rationale, now],
        )?;
        super::audit::record(conn, "decision.created", "gev", "decision", &id)?;
        conn.query_row("SELECT * FROM decisions WHERE id = ?1", [id.clone()], map).map_err(not_found(&id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Decision>> {
        let mut s = conn.prepare("SELECT * FROM decisions ORDER BY updated_at DESC")?;
        let rows = s.query_map([], map)?;
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
        conn.execute(
            "INSERT INTO conversations(id, kind, title, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?4)",
            rusqlite::params![id, kind, title, now],
        )?;
        super::audit::record(conn, "conversation.created", "gev", "conversation", &id)?;
        get_conversation(conn, &id)
    }

    pub fn get_conversation(conn: &Connection, id: &str) -> CoreResult<Conversation> {
        let sql = format!("{CONVERSATION_SELECT} WHERE c.id = ?1 GROUP BY c.id");
        conn.query_row(&sql, [id], map_conversation).map_err(not_found(id))
    }

    pub fn list_conversations(conn: &Connection, kind: Option<&str>) -> CoreResult<Vec<Conversation>> {
        match kind {
            Some(k) => {
                let sql = format!("{CONVERSATION_SELECT} WHERE c.kind = ?1 GROUP BY c.id ORDER BY c.updated_at DESC");
                let mut s = conn.prepare(&sql)?;
                let rows = s.query_map([k], map_conversation)?;
                Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
            }
            None => {
                let sql = format!("{CONVERSATION_SELECT} GROUP BY c.id ORDER BY c.updated_at DESC");
                let mut s = conn.prepare(&sql)?;
                let rows = s.query_map([], map_conversation)?;
                Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
            }
        }
    }

    pub fn list_messages(conn: &Connection, conversation_id: &str) -> CoreResult<Vec<Message>> {
        let mut s = conn.prepare(
            "SELECT * FROM messages WHERE conversation_id = ?1 ORDER BY created_at ASC, rowid ASC",
        )?;
        let rows = s.query_map([conversation_id], map_message)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Append a message to a conversation and bump the conversation's activity
    /// timestamp. Rejects an unknown conversation and invalid role.
    pub fn post_message(conn: &Connection, input: NewMessage) -> CoreResult<Message> {
        if !is_valid(&input.role, MESSAGE_ROLES) {
            return Err(CoreError::Invalid { field: "role", value: input.role });
        }
        // Fail cleanly if the conversation does not exist (FK would also reject).
        get_conversation(conn, &input.conversation_id)?;
        let now = now();
        let id = id();
        conn.execute(
            "INSERT INTO messages(id, conversation_id, role, author, body, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            rusqlite::params![id, input.conversation_id, input.role, input.author, input.body, now],
        )?;
        conn.execute(
            "UPDATE conversations SET updated_at = ?1 WHERE id = ?2",
            rusqlite::params![now, input.conversation_id],
        )?;
        super::audit::record(conn, "message.posted", &input.author, "conversation", &input.conversation_id)?;
        conn.query_row("SELECT * FROM messages WHERE id = ?1", [id.clone()], map_message)
            .map_err(not_found(&id))
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
        conn.execute(
            "INSERT INTO knowledge_notes(id, title, body, source, tags, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
            rusqlite::params![id, input.title, input.body, input.source, input.tags, now],
        )?;
        super::audit::record(conn, "knowledge.created", "gev", "knowledge_note", &id)?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<KnowledgeNote> {
        conn.query_row("SELECT * FROM knowledge_notes WHERE id = ?1", [id], map)
            .map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<KnowledgeNote>> {
        let mut s = conn.prepare("SELECT * FROM knowledge_notes ORDER BY updated_at DESC")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Case-insensitive substring search over title, body, and tags. An empty
    /// query returns everything (same as `list`).
    pub fn search(conn: &Connection, query: &str) -> CoreResult<Vec<KnowledgeNote>> {
        let q = query.trim();
        if q.is_empty() {
            return list(conn);
        }
        let like = format!("%{q}%");
        let mut s = conn.prepare(
            "SELECT * FROM knowledge_notes \
             WHERE title LIKE ?1 OR body LIKE ?1 OR tags LIKE ?1 \
             ORDER BY updated_at DESC",
        )?;
        let rows = s.query_map([like], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn delete(conn: &Connection, id: &str) -> CoreResult<()> {
        let changed = conn.execute("DELETE FROM knowledge_notes WHERE id = ?1", [id])?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "knowledge.deleted", "gev", "knowledge_note", id)?;
        Ok(())
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
        conn.execute(
            "INSERT INTO memory_entries(id, scope, kind, content, pinned, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, 0, ?5, ?5)",
            rusqlite::params![id, input.scope, input.kind, input.content, now],
        )?;
        super::audit::record(conn, "memory.created", "gev", "memory_entry", &id)?;
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
                    "SELECT * FROM memory_entries WHERE scope = ?1 ORDER BY pinned DESC, updated_at DESC",
                )?;
                let rows = s.query_map([sc], map)?;
                Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
            }
            None => {
                let mut s = conn.prepare(
                    "SELECT * FROM memory_entries ORDER BY pinned DESC, updated_at DESC",
                )?;
                let rows = s.query_map([], map)?;
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
        let changed = conn.execute("DELETE FROM memory_entries WHERE id = ?1", [id])?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "memory.deleted", "gev", "memory_entry", id)?;
        Ok(())
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
        conn.execute(
            "INSERT INTO runs(id, intent, status, plan, created_at, updated_at)
             VALUES (?1, ?2, 'drafted', ?3, ?4, ?4)",
            rusqlite::params![id, intent, plan, now],
        )?;
        super::audit::record(conn, "run.created", "gev", "run", &id)?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Run> {
        conn.query_row("SELECT * FROM runs WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Run>> {
        let mut s = conn.prepare("SELECT * FROM runs ORDER BY updated_at DESC")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn set_status(conn: &Connection, id: &str, status: &str) -> CoreResult<Run> {
        if !is_valid(status, RUN_STATUSES) {
            return Err(CoreError::Invalid { field: "status", value: status.to_string() });
        }
        let changed = conn.execute(
            "UPDATE runs SET status = ?1, updated_at = ?2 WHERE id = ?3",
            rusqlite::params![status, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "run.status_changed", "gev", "run", id)?;
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
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn add_step(conn: &Connection, run_id: &str, title: &str, detail: &str) -> CoreResult<RunStep> {
        get(conn, run_id)?; // reject an unknown run before inserting
        let position: i64 = conn.query_row(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM run_steps WHERE run_id = ?1",
            [run_id],
            |r| r.get(0),
        )?;
        let now = now();
        let id = id();
        conn.execute(
            "INSERT INTO run_steps(id, run_id, position, title, detail, status, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, 'pending', ?6, ?6)",
            rusqlite::params![id, run_id, position, title, detail, now],
        )?;
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
        let changed = conn.execute(
            "UPDATE run_steps SET status = ?1, updated_at = ?2 WHERE id = ?3",
            rusqlite::params![status, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        get_step(conn, id)
    }

    /// Advance a run's execution by one step: mark the active step done and
    /// activate the next pending one. When no pending steps remain the run is
    /// marked `succeeded`; the run moves to `running` on the first advance.
    /// This models the lifecycle only — it never executes anything on the host.
    ///
    /// Rejects advancing a terminated run (succeeded/failed/cancelled) or a run
    /// with no steps. All state changes commit atomically.
    pub fn advance(conn: &Connection, run_id: &str) -> CoreResult<Run> {
        let run = get(conn, run_id)?;
        if matches!(run.status.as_str(), "succeeded" | "failed" | "cancelled") {
            return Err(CoreError::Invalid { field: "status", value: run.status });
        }
        let total_steps: i64 =
            conn.query_row("SELECT COUNT(*) FROM run_steps WHERE run_id = ?1", [run_id], |r| r.get(0))?;
        if total_steps == 0 {
            return Err(CoreError::Invalid { field: "steps", value: "none".to_string() });
        }

        let now = now();
        let tx = conn.unchecked_transaction()?;
        tx.execute(
            "UPDATE run_steps SET status = 'done', updated_at = ?1 WHERE run_id = ?2 AND status = 'active'",
            rusqlite::params![now, run_id],
        )?;
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
                    set_status(&tx, run_id, "running")?;
                }
            }
            None => set_status(&tx, run_id, "succeeded").map(|_| ())?,
        }
        super::audit::record(&tx, "run.advanced", "gev", "run", run_id)?;
        tx.commit()?;
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
        conn.execute(
            "INSERT INTO events(id, title, kind, location, starts_at, ends_at, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?7)",
            rusqlite::params![id, input.title, input.kind, input.location, input.starts_at, input.ends_at, now],
        )?;
        super::audit::record(conn, "event.created", "gev", "event", &id)?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Event> {
        conn.query_row("SELECT * FROM events WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Event>> {
        let mut s = conn.prepare("SELECT * FROM events ORDER BY starts_at ASC")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn delete(conn: &Connection, id: &str) -> CoreResult<()> {
        let changed = conn.execute("DELETE FROM events WHERE id = ?1", [id])?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "event.deleted", "gev", "event", id)?;
        Ok(())
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
        conn.execute(
            "INSERT INTO automations(id, name, trigger, action, enabled, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, 1, ?5, ?5)",
            rusqlite::params![id, input.name, input.trigger, input.action, now],
        )?;
        super::audit::record(conn, "automation.created", "gev", "automation", &id)?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<Automation> {
        conn.query_row("SELECT * FROM automations WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<Automation>> {
        let mut s = conn.prepare("SELECT * FROM automations ORDER BY name")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn set_enabled(conn: &Connection, id: &str, enabled: bool) -> CoreResult<Automation> {
        let changed = conn.execute(
            "UPDATE automations SET enabled = ?1, updated_at = ?2 WHERE id = ?3",
            rusqlite::params![enabled as i64, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "automation.toggled", "gev", "automation", id)?;
        get(conn, id)
    }

    pub fn delete(conn: &Connection, id: &str) -> CoreResult<()> {
        let changed = conn.execute("DELETE FROM automations WHERE id = ?1", [id])?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "automation.deleted", "gev", "automation", id)?;
        Ok(())
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
        let changed = conn.execute(
            "UPDATE integrations SET status = ?1, updated_at = ?2 WHERE id = ?3",
            rusqlite::params![status, now(), id],
        )?;
        if changed == 0 {
            return Err(CoreError::NotFound(id.to_string()));
        }
        super::audit::record(conn, "integration.status_changed", "gev", "integration", id)?;
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
        let decided: i64 = conn.query_row(
            "SELECT COUNT(*) FROM approvals WHERE status IN ('approved','rejected')", [], |r| r.get(0))?;
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

fn not_found(id: &str) -> impl Fn(rusqlite::Error) -> CoreError + '_ {
    move |e| match e {
        rusqlite::Error::QueryReturnedNoRows => CoreError::NotFound(id.to_string()),
        other => CoreError::Sqlite(other),
    }
}

/// Populate a fresh database with initial content so the app is demonstrable.
/// Real rows inserted through the repositories — not a mock layer. Idempotent:
/// runs only when there are no projects yet.
pub fn seed(conn: &Connection) -> CoreResult<()> {
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
    runs::add_step(conn, &r1.id, "Register commands", "")?;
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
}
