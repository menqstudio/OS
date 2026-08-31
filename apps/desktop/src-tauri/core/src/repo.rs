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
/// `pub(crate)` since T-058's §4 slice: `credentials` writes a binding and its
/// audit row in one transaction, and lives outside this module because a
/// credential store is not a repository of domain rows. Still crate-internal —
/// nothing outside this crate opens a transaction.
pub(crate) fn atomic<T, F>(conn: &Connection, f: F) -> CoreResult<T>
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

    pub fn create(conn: &Connection, input: NewProject, actor: audit::Actor<'_>) -> CoreResult<Project> {
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
            super::audit::record(tx, "project.created", actor, "project", &id)?;
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

    pub fn set_status(conn: &Connection, id: &str, status: &str, actor: audit::Actor<'_>) -> CoreResult<Project> {
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
            super::audit::record(tx, "project.status_changed", actor, "project", id)?;
            Ok(())
        })?;
        get(conn, id)
    }

    /// Edit a project's name, description, and priority.
    pub fn update(conn: &Connection, id: &str, name: &str, description: &str, priority: &str, actor: audit::Actor<'_>) -> CoreResult<Project> {
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
            super::audit::record(tx, "project.updated", actor, "project", id)?;
            Ok(())
        })?;
        get(conn, id)
    }
}

pub mod tasks {
    use super::*;

    pub fn create(conn: &Connection, input: NewTask, actor: audit::Actor<'_>) -> CoreResult<Task> {
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
            super::audit::record(tx, "task.created", actor, "task", &id)?;
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
    pub fn update(conn: &Connection, id: &str, title: &str, description: &str, priority: &str, actor: audit::Actor<'_>) -> CoreResult<Task> {
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
            super::audit::record(tx, "task.updated", actor, "task", id)?;
            Ok(())
        })?;
        get(conn, id)
    }

    pub fn set_status(conn: &Connection, id: &str, status: &str, actor: audit::Actor<'_>) -> CoreResult<Task> {
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
            super::audit::record(tx, "task.status_changed", actor, "task", id)?;
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
    pub fn add(conn: &Connection, task_id: &str, depends_on_id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
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
            super::audit::record(tx, "task.dependency_added", actor, "task", task_id)?;
            Ok(())
        })
    }

    /// Remove a dependency edge. Errors when the edge does not exist and audits
    /// the removal — dropping a blocker is a sensitive graph mutation (L-3f).
    pub fn remove(conn: &Connection, task_id: &str, depends_on_id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "DELETE FROM task_dependencies WHERE task_id = ?1 AND depends_on_id = ?2",
                rusqlite::params![task_id, depends_on_id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(format!("dependency {task_id} -> {depends_on_id}")));
            }
            super::audit::record(tx, "task.dependency_removed", actor, "task", task_id)?;
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

    /// The actor id recorded for a write a person made at this cockpit.
    ///
    /// It is deliberately NOT a personal name. This desktop has no login, no
    /// account and no operator credential, so the only thing the command layer
    /// can establish about a webview-originated write is *that a human drove the
    /// cockpit* -- never WHICH human. The literal `"gev"` that stood at 34 call
    /// sites until T-052 asserted a named person for every audited write in the
    /// product, including the ones no person was present for: the automation
    /// scheduler ticks once a minute and wrote `automation.ran`, `task.created`
    /// and `knowledge.created` rows attributed to that person. A guessed actor is
    /// worse than an absent one, because it reads as evidence.
    pub const LOCAL_OPERATOR: &str = "local-operator";

    /// The in-process automation scheduler (`automations::run_due`, spawned from
    /// `lib.rs` on a 60s tick). Nothing human is present when it fires.
    pub const SCHEDULER: &str = "scheduler";

    /// An automation's own declared action (`automations::execute_action`), which
    /// creates tasks and knowledge notes on the automation's behalf.
    pub const AUTOMATION: &str = "automation";

    /// Who caused an audited write.
    ///
    /// Carrying the pair together is what stops a call site from silently
    /// asserting a human: there is no `Default`, so **every** audited write must
    /// name its actor and the compiler enumerates any that does not. Build one
    /// with [`Actor::local_operator`], [`Actor::scheduler`], [`Actor::automation`]
    /// or [`Actor::agent`] rather than assembling the fields, so the trust basis
    /// for the value is written down beside it.
    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub struct Actor<'a> {
        /// One of [`ACTOR_TYPES`]; [`record`] rejects anything else.
        pub kind: &'a str,
        pub id: &'a str,
    }

    impl<'a> Actor<'a> {
        /// A person acting at this cockpit -- an unauthenticated local human.
        /// See [`LOCAL_OPERATOR`] for why the id is not a name.
        pub const fn local_operator() -> Actor<'static> {
            Actor { kind: "user", id: LOCAL_OPERATOR }
        }

        /// The product's own runtime, where no more specific component can be
        /// named: startup reconciliation of a crashed session's claim
        /// (`runs::reconcile_abandoned_executions`) and the gate enforcing a
        /// rejected approval (`runs::fail_step_and_run`). These are the two sites
        /// that already carried `("system", "system")` before T-052 and they keep
        /// exactly those values -- naming them `reconciler` or `approval-gate`
        /// would be a relabel this layer cannot establish, and a more specific
        /// actor that is guessed is worse than a vague one that is true.
        pub const fn system() -> Actor<'static> {
            Actor { kind: "system", id: "system" }
        }

        /// The starter workspace written by `repo::seed` at first launch. Nobody
        /// created these rows; before T-052 the seed minted ~40 audit records
        /// naming a person for rows the product wrote to itself.
        pub const fn seed() -> Actor<'static> {
            Actor { kind: "system", id: "seed" }
        }

        /// The unattended scheduler tick. No human is present.
        pub const fn scheduler() -> Actor<'static> {
            Actor { kind: "system", id: SCHEDULER }
        }

        /// An automation performing its own declared action.
        pub const fn automation() -> Actor<'static> {
            Actor { kind: "system", id: AUTOMATION }
        }

        /// The human who answered the renderer-independent native confirmation
        /// dialog (T-011). `id` is `native:<window label>`, built by
        /// `commands::confirm_approval` from the Tauri window -- the webview cannot
        /// forge it, which is what makes `user` an established fact here and not an
        /// assumption.
        pub const fn native_confirmer(id: &'a str) -> Actor<'a> {
            Actor { kind: "user", id }
        }

        /// The streaming run executor completing a step after the provider
        /// returned (`commands::stream_run_step`). Not the person who started the
        /// run: by the time this writes, the work was done by a model dispatched
        /// by this loop, and the operator's identity is not something this layer
        /// can establish anyway.
        pub const fn run_executor() -> Actor<'static> {
            Actor { kind: "system", id: "run-executor" }
        }

        /// A named agent. `id` must come from trusted context (a server-minted
        /// author), never from a request body.
        pub const fn agent(id: &'a str) -> Actor<'a> {
            Actor { kind: "agent", id }
        }

        /// An actor carried by already-trusted row data: the message role/author
        /// pair. The webview allowlist (`commands::WEBVIEW_MESSAGE_ROLES`) narrows
        /// the role a renderer may post to `user`; agent and system roles are
        /// minted server-side only.
        pub const fn from_message(role: &'a str, author: &'a str) -> Actor<'a> {
            Actor { kind: role, id: author }
        }
    }

    /// Record an audit event. The [`Actor`] is passed explicitly by trusted repo
    /// code (never hardcoded `'user'`), so agent- and system-originated events
    /// stay distinguishable from human ones in `security::summary` (L-4a) -- the
    /// `actor_type` column reaches that surface through `ActivityEvent`. Call
    /// sites at the command layer must derive the actor from trusted context, not
    /// from the request body.
    pub fn record(
        conn: &Connection,
        event_type: &str,
        actor: Actor<'_>,
        entity_type: &str,
        entity_id: &str,
    ) -> CoreResult<()> {
        record_with_payload(conn, event_type, actor, entity_type, entity_id, None)
    }

    /// The same record, carrying the WHAT alongside the who and the which.
    ///
    /// `audit_events.payload_json` has existed since migration 0001 and, until
    /// this call site, nothing in the tree wrote it and nothing read it — a
    /// column that answered to nothing. An egress decision is the first event
    /// whose meaning does not fit in `(event_type, entity)`: "denied" is not a
    /// record unless it says which destination, under which grant.
    ///
    /// The payload is written by trusted repo code from values the runtime
    /// holds. It is NOT signed, and nothing here makes it tamper-evident
    /// against whoever can write the database — `local_write_record.rs` says
    /// the same about its own half. Do not read it as attestation.
    pub fn record_with_payload(
        conn: &Connection,
        event_type: &str,
        actor: Actor<'_>,
        entity_type: &str,
        entity_id: &str,
        payload_json: Option<&str>,
    ) -> CoreResult<()> {
        let (actor_type, actor_id) = (actor.kind, actor.id);
        if !is_valid(actor_type, ACTOR_TYPES) {
            return Err(CoreError::Invalid { field: "actor_type", value: actor_type.to_string() });
        }
        conn.execute(
            "INSERT INTO audit_events(id, event_type, actor_type, actor_id, entity_type, entity_id, payload_json, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            rusqlite::params![id(), event_type, actor_type, actor_id, entity_type, entity_id, payload_json, now()],
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

    /// T-052 gating tuples for the three tier-X commands that reached the
    /// authority layer with no gate at all: `set_integration_auth_ref`,
    /// `set_integration_status` and `set_automation_enabled` were each
    /// `{"tier": "X", "grant": "allow"}` in `command-policy.json` and nothing
    /// else. X is the execution/spend tier: pointing a connector at a credential
    /// locator, declaring a connector connected, and arming an automation that
    /// then fires unattended once a minute are all acts a compromised renderer
    /// could perform silently.
    ///
    /// They use the SAME mechanism as the run-step gate — `approved_for` +
    /// `consume_for` over the full (entity_id, entity_type, action_type) tuple,
    /// inside the write's own transaction — so a grant minted for one of them can
    /// never unlock another, and only `approve_confirmed` (renderer-independent
    /// native confirmation, T-011) can produce a satisfying grant.
    pub const INTEGRATION_ENTITY_TYPE: &str = "integration";
    pub const INTEGRATION_AUTH_REF_ACTION_TYPE: &str = "Set integration credential reference";
    pub const INTEGRATION_STATUS_ACTION_TYPE: &str = "Set integration status";
    pub const AUTOMATION_ENTITY_TYPE: &str = "automation";
    pub const AUTOMATION_ENABLED_ACTION_TYPE: &str = "Arm automation";
    pub const AGENT_BUNDLE_ENTITY_TYPE: &str = "agent_bundle";
    pub const AGENT_BUNDLE_ARM_ACTION_TYPE: &str = "Arm agent bundle";
    pub const CREDENTIAL_BINDING_ENTITY_TYPE: &str = "credential_binding";
    pub const CREDENTIAL_BIND_ACTION_TYPE: &str = "Bind agent credential";

    /// Verify and spend the grant for a gated write, in the write's own
    /// transaction. Factored out of `runs::claim_step_execution`'s inline pair so
    /// the three T-052 gates cannot drift from it: a check that verified without
    /// consuming would let one approval unlock a command forever.
    pub fn require_and_consume(
        tx: &Connection,
        entity_id: &str,
        entity_type: &str,
        action_type: &str,
    ) -> CoreResult<()> {
        if !approved_for(tx, entity_id, entity_type, action_type)? {
            return Err(CoreError::Invalid { field: "approval", value: "required".into() });
        }
        consume_for(tx, entity_id, entity_type, action_type)
    }

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
            origin_principal: r.get("origin_principal")?,
            origin_session_id: r.get("origin_session_id")?,
            request_digest: r.get("request_digest")?,
            nonce: r.get("nonce")?,
            confirmed_at: r.get("confirmed_at")?,
            confirmed_by: r.get("confirmed_by")?,
            confirmation_method: r.get("confirmation_method")?,
            confirmation_digest: r.get("confirmation_digest")?,
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

    /// SHA-256 of `s`, lowercase hex.
    pub fn sha256_hex(s: &str) -> String {
        use sha2::{Digest, Sha256};
        let mut h = Sha256::new();
        h.update(s.as_bytes());
        format!("{:x}", h.finalize())
    }

    /// The SINGLE canonical description of what a run step will execute. Every
    /// consumer derives from this one object so the confirmed payload, the request
    /// digest, and the actual provider prompt cannot diverge (T-011 audit): the
    /// native dialog shows `dialog_text()`, the digest binds every field, and the AI
    /// execution prompt is `provider_json()` — all from `run_execution_scope`.
    pub struct RunExecutionScope {
        pub run_id: String,
        pub intent: String,
        pub plan: String,
        pub step_id: String,
        pub step_title: String,
        pub step_detail: String,
        pub requires_approval: bool,
    }

    impl RunExecutionScope {
        /// The exact JSON payload sent to the provider (values are data, not
        /// instructions). Includes `step_detail`, so a safety condition shown to the
        /// confirmer actually reaches the agent.
        pub fn provider_json(&self) -> serde_json::Value {
            serde_json::json!({
                "intent": self.intent,
                "plan": self.plan,
                "step": self.step_title,
                "step_detail": self.step_detail,
            })
        }
        /// Human-readable payload for the native confirmation dialog — the same
        /// fields the digest binds and the prompt sends.
        pub fn dialog_text(&self) -> String {
            format!(
                "Run intent:\n{}\n\nRun plan:\n{}\n\nStep:\n{}\n\nStep detail:\n{}",
                self.intent, self.plan, self.step_title, self.step_detail
            )
        }
    }

    /// Load the canonical execution scope for a run step from current state.
    pub fn run_execution_scope(conn: &Connection, step_id: &str) -> CoreResult<RunExecutionScope> {
        let step = super::runs::get_step(conn, step_id)?;
        let run = super::runs::get(conn, &step.run_id)?;
        Ok(RunExecutionScope {
            run_id: run.id,
            intent: run.intent,
            plan: run.plan,
            step_id: step.id,
            step_title: step.title,
            step_detail: step.detail,
            requires_approval: step.requires_approval,
        })
    }

    #[derive(serde::Serialize)]
    struct RunPart {
        run_id: String,
        run_intent_sha256: String,
        // The full execution plan is part of the AI execution payload and is
        // renderer-supplied at run creation — it MUST be bound, or a benign
        // intent/title could hide a malicious plan from the confirmer.
        run_plan_sha256: String,
        step_id: String,
        step_title_sha256: String,
        step_detail_sha256: String,
        requires_approval: bool,
    }

    /// The canonical request envelope hashed into `request_digest` (T-011, design
    /// §6.3). Field order is fixed (struct order), and there are no maps, so
    /// `serde_json::to_string` is deterministic — the digest binds the decision to
    /// the exact request AND the exact execution scope. `target` (UI display text)
    /// is deliberately excluded.
    #[derive(serde::Serialize)]
    struct RequestEnvelope<'a> {
        schema_version: u32,
        approval_id: &'a str,
        action_type: &'a str,
        entity_type: Option<&'a str>,
        entity_id: Option<&'a str>,
        risk_level: &'a str,
        approval_level: &'a str,
        requested_by: &'a str,
        origin_principal: Option<&'a str>,
        requested_at: &'a str,
        run: Option<RunPart>,
    }

    /// Recompute the request digest for `a` from the CURRENT entity state. Used at
    /// creation (to store) and at decision (to compare) — if the underlying run/step
    /// changed after the approval was raised, the digest differs and the decision is
    /// refused.
    pub fn request_digest(conn: &Connection, a: &Approval) -> CoreResult<String> {
        // Derive from the ONE canonical scope, so the digest binds exactly what the
        // dialog shows and the provider prompt sends.
        let run = if a.entity_type.as_deref() == Some(RUN_STEP_ENTITY_TYPE) {
            if let Some(step_id) = a.entity_id.as_deref() {
                let scope = run_execution_scope(conn, step_id)?;
                Some(RunPart {
                    run_id: scope.run_id.clone(),
                    run_intent_sha256: sha256_hex(&scope.intent),
                    run_plan_sha256: sha256_hex(&scope.plan),
                    step_id: scope.step_id.clone(),
                    step_title_sha256: sha256_hex(&scope.step_title),
                    step_detail_sha256: sha256_hex(&scope.step_detail),
                    requires_approval: scope.requires_approval,
                })
            } else {
                None
            }
        } else {
            None
        };
        let envelope = RequestEnvelope {
            schema_version: 1,
            approval_id: &a.id,
            action_type: &a.action_type,
            entity_type: a.entity_type.as_deref(),
            entity_id: a.entity_id.as_deref(),
            risk_level: &a.risk_level,
            approval_level: &a.level,
            requested_by: &a.requested_by,
            origin_principal: a.origin_principal.as_deref(),
            requested_at: &a.requested_at,
            run,
        };
        let json = serde_json::to_string(&envelope)
            .map_err(|e| CoreError::Invalid { field: "request_envelope", value: e.to_string() })?;
        Ok(sha256_hex(&json))
    }

    /// The FULL execution payload the confirmer must see — the exact text that will
    /// reach the AI provider. Derived from the SAME canonical scope the digest binds
    /// and the provider prompt sends, so the three cannot diverge. `None` for non-run
    /// entities.
    pub fn execution_payload(conn: &Connection, a: &Approval) -> CoreResult<Option<String>> {
        if a.entity_type.as_deref() != Some(RUN_STEP_ENTITY_TYPE) {
            return Ok(None);
        }
        let Some(step_id) = a.entity_id.as_deref() else { return Ok(None) };
        Ok(Some(run_execution_scope(conn, step_id)?.dialog_text()))
    }

    /// Bind the confirmation to the exact request + nonce + method, so the recorded
    /// `confirmation_digest` provably matches the confirmed envelope.
    fn confirmation_digest(request_digest: &str, nonce: &str, method: &str) -> String {
        sha256_hex(&format!("{request_digest}:{nonce}:{method}"))
    }

    /// The ONE principal that may confirm an approval: the renderer-independent native
    /// OS authority. Any `webview:*` principal — the requester's own or another
    /// window's — is refused.
    ///
    /// **Why this constant exists (independent audit F-30, remediation round 2).** The
    /// self-approval defence used to be a single equality: refuse when
    /// `origin_principal == confirmer_principal`. That comparison could not fail on the
    /// only production path. `confirm_approval` passes the literal `"native"`, and the
    /// only writer of `origin_principal` writes `format!("webview:{label}")`, so
    /// `Some("webview:main") == Some("native")` was evaluated on every approval and was
    /// never true. Worse, the two tests that claimed to lock the property drove it with
    /// `"webview:main"` as the confirmer — a value no shipped caller emits — so they
    /// stayed green while the production path was unguarded, and a mutation of the
    /// production call site killed nothing.
    ///
    /// The equality is replaced by two checks that CAN fail, at the two ends:
    ///
    ///   * [`approve_confirmed`] accepts this principal and no other, so no webview
    ///     principal can confirm ANYTHING — strictly stronger than the old check, which
    ///     still let `webview:a` confirm `webview:b`'s request;
    ///   * [`create`] refuses to record this principal as an `origin_principal`, so a
    ///     requester cannot borrow the native authority's name.
    ///
    /// Composed, no row can exist whose origin equals the only accepted confirmer, so
    /// "the requester cannot approve its own request" still holds — and it holds because
    /// two checks enforce it, not because a third was computed and could not fire.
    pub const NATIVE_CONFIRMER_PRINCIPAL: &str = "native";

    /// Create a pending approval, optionally linked to the entity that needs it.
    /// T-011: the caller supplies the durable `origin_principal` (stable enforcement
    /// identity, restart-safe), a forensic `origin_session_id`, and a one-time
    /// `nonce`; the `request_digest` is computed from the just-created state and
    /// stored so a later decision can detect a mutated request.
    #[allow(clippy::too_many_arguments)]
    pub fn create(
        conn: &Connection,
        action_type: &str,
        target: &str,
        level: &str,
        risk_level: &str,
        entity_type: Option<&str>,
        entity_id: Option<&str>,
        origin_principal: &str,
        origin_session_id: &str,
        nonce: &str,
        // Who is asking. Its id is what lands in the `requested_by` column, so the
        // row and the audit record can never name two different requesters.
        actor: audit::Actor<'_>,
    ) -> CoreResult<Approval> {
        let requested_by = actor.id;
        // F-30: the requester may not record itself under the native authority's name.
        // This is one half of the composition that replaced the unsatisfiable
        // self-approval equality; see [`NATIVE_CONFIRMER_PRINCIPAL`]. It is checked
        // BEFORE the transaction because it depends on nothing in the database.
        if origin_principal == NATIVE_CONFIRMER_PRINCIPAL {
            return Err(CoreError::Invalid {
                field: "origin_principal",
                value: "a requester may not claim the native confirmation authority".into(),
            });
        }
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
                "INSERT INTO approvals(id, action_type, target, level, risk_level, status, requested_by, entity_type, entity_id, requested_at, origin_principal, origin_session_id, nonce)
                 VALUES (?1, ?2, ?3, ?4, ?5, 'pending', ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
                rusqlite::params![id, action_type, target, level, risk_level, requested_by, entity_type, entity_id, now(), origin_principal, origin_session_id, nonce],
            )?;
            // Bind the digest to the request, in the same transaction.
            let created: Approval = tx.query_row("SELECT * FROM approvals WHERE id = ?1", [id.clone()], map)?;
            let digest = request_digest(tx, &created)?;
            tx.execute("UPDATE approvals SET request_digest = ?1 WHERE id = ?2", rusqlite::params![digest, id])?;
            super::audit::record(tx, "approval.requested", actor, "approval", &id)?;
            Ok(())
        })?;
        conn.query_row("SELECT * FROM approvals WHERE id = ?1", [id.clone()], map).map_err(not_found(&id))
    }

    /// Fetch a single approval by id.
    pub fn get(conn: &Connection, id: &str) -> CoreResult<Approval> {
        conn.query_row("SELECT * FROM approvals WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    /// T-011 approve: record a native-confirmed approval. It first refuses any
    /// confirmer that is not [`NATIVE_CONFIRMER_PRINCIPAL`] — that, with `create`'s
    /// refusal to store the same name as an origin, is what bars self-approval; the old
    /// `origin == confirmer` equality was unsatisfiable in production and is gone. Then,
    /// in ONE atomic transaction, it enforces pending-only (replay-safe) and
    /// rechecks the `request_digest` against the CURRENT entity state (a request that
    /// changed after it was raised is refused). The caller performs the
    /// renderer-independent native confirmation BEFORE calling this; the nonce is
    /// consumed here. Only *approve* flows through this path — reject is separate.
    pub fn approve_confirmed(
        conn: &Connection,
        id: &str,
        confirmer_principal: &str,
        note: Option<&str>,
        expected_nonce: &str,
        expected_request_digest: &str,
        // Who confirmed. Its id is what lands in the `confirmed_by` column.
        actor: audit::Actor<'_>,
    ) -> CoreResult<Approval> {
        let confirmed_by = actor.id;
        // F-30: only the renderer-independent native authority may confirm. Checked
        // before anything is read, so it depends on no row and therefore cannot be used
        // to probe which approval ids exist. See [`NATIVE_CONFIRMER_PRINCIPAL`].
        if confirmer_principal != NATIVE_CONFIRMER_PRINCIPAL {
            return Err(CoreError::Invalid {
                field: "approver",
                value: "only the native confirmation authority may approve".into(),
            });
        }
        super::atomic(conn, |tx| {
            let a: Approval = tx
                .query_row("SELECT * FROM approvals WHERE id = ?1", [id], map)
                .map_err(|_| CoreError::NotFound(format!("pending approval {id}")))?;
            if a.status != "pending" {
                return Err(CoreError::NotFound(format!("pending approval {id}")));
            }
            // Replay-safe: the nonce loaded before the dialog must still be the
            // unspent nonce on the row now (a concurrent decision would have cleared
            // or changed it). This is a real check, not just the status guard.
            if a.nonce.as_deref() != Some(expected_nonce) {
                return Err(CoreError::Invalid {
                    field: "nonce",
                    value: "approval nonce was spent or changed (replay)".into(),
                });
            }
            // (The self-approval equality that used to sit here compared the persisted
            //  `origin_principal` against `confirmer_principal`. It could not fail on
            //  the only production path — see [`NATIVE_CONFIRMER_PRINCIPAL`] — so it was
            //  deleted rather than shipped, and the property it advertised is now
            //  enforced by the confirmer check above plus the `create` check.)
            // The stored digest must equal the digest confirmed before the dialog…
            if a.request_digest.as_deref() != Some(expected_request_digest) {
                return Err(CoreError::Invalid {
                    field: "request_digest",
                    value: "approval changed since it was presented for confirmation".into(),
                });
            }
            // …and both must equal a fresh recomputation from CURRENT entity state.
            let current = request_digest(tx, &a)?;
            if current != expected_request_digest {
                return Err(CoreError::Invalid {
                    field: "request_digest",
                    value: "the request changed since it was raised".into(),
                });
            }
            // Bound to the principal that actually confirmed, not to a second hardcoded
            // literal. The value is unchanged (the check above proves it is
            // `NATIVE_CONFIRMER_PRINCIPAL`), but the parameter is now load-bearing in
            // the stored evidence instead of being read only by a check that could not
            // fail.
            let conf_digest = confirmation_digest(&current, expected_nonce, confirmer_principal);
            let changed = tx.execute(
                "UPDATE approvals SET status = 'approved', decision_note = ?1, decided_at = ?2, \
                 confirmed_at = ?2, confirmed_by = ?3, confirmation_method = 'native', \
                 confirmation_digest = ?4, nonce = NULL \
                 WHERE id = ?5 AND status = 'pending' AND nonce = ?6",
                rusqlite::params![note, now(), confirmed_by, conf_digest, id, expected_nonce],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(format!("pending approval {id}")));
            }
            super::audit::record(tx, "approval.decided", actor, "approval", id)?;
            Ok(())
        })?;
        conn.query_row("SELECT * FROM approvals WHERE id = ?1", [id], map).map_err(not_found(id))
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
        // T-011: a grant is valid ONLY if it was recorded through the native
        // confirmation path (`approve_confirmed`). Those markers — confirmed_at set,
        // confirmation_method 'native', a confirmation_digest present, and the nonce
        // consumed — are written together and only there; the reject-only `decide`
        // path can never produce them. So the "native confirmation is the only
        // approve path" invariant lives in this authority layer, not just the command.
        let n: i64 = conn.query_row(
            "SELECT COUNT(*) FROM approvals
               WHERE entity_id = ?1 AND entity_type = ?2 AND action_type = ?3
                 AND status = 'approved' AND decided_at IS NOT NULL
                 AND confirmed_at IS NOT NULL AND confirmation_method = 'native'
                 AND confirmation_digest IS NOT NULL AND nonce IS NULL",
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

    /// Reject-only decision path. **Approve does NOT go through here** (T-011): the
    /// only way to reach `status = 'approved'` is `approve_confirmed`, which records
    /// the native-confirmation markers that `approved_for` requires. `decide` refuses
    /// `"approved"` at the authority layer so the invariant cannot be bypassed even if
    /// a command were mis-wired. `decision` must be `"rejected"`.
    pub fn decide(conn: &Connection, id: &str, decision: &str, note: Option<&str>, actor: audit::Actor<'_>) -> CoreResult<Approval> {
        if !is_valid(decision, APPROVAL_DECISIONS) {
            return Err(CoreError::Invalid { field: "decision", value: decision.to_string() });
        }
        if decision == "approved" {
            return Err(CoreError::Invalid {
                field: "decision",
                value: "approve requires native confirmation (approve_confirmed), not decide".into(),
            });
        }
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE approvals SET status = ?1, decision_note = ?2, decided_at = ?3 WHERE id = ?4 AND status = 'pending'",
                rusqlite::params![decision, note, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(format!("pending approval {id}")));
            }
            super::audit::record(tx, "approval.decided", actor, "approval", id)?;
            Ok(())
        })?;
        conn.query_row("SELECT * FROM approvals WHERE id = ?1", [id], map).map_err(not_found(id))
    }

    /// Escalate a pending approval to higher review (tier A3). This is deliberately NOT a
    /// verdict: the approval is neither granted nor denied and authorizes no execution — it is
    /// routed to the highest review tier and the owner is notified. Because it decides nothing,
    /// it needs no engine adjudication, but it is still pending-only + atomic + audited, and the
    /// owner-facing notification makes the escalation visible. Re-escalating a non-pending row is
    /// a no-op error (NotFound), so an already-decided or already-escalated approval cannot move.
    pub fn escalate(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<Approval> {
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE approvals SET status = 'escalated', level = 'A3' WHERE id = ?1 AND status = 'pending'",
                rusqlite::params![id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(format!("pending approval {id}")));
            }
            let target: String =
                tx.query_row("SELECT target FROM approvals WHERE id = ?1", [id], |r| r.get(0))?;
            tx.execute(
                "INSERT INTO notifications(id, type, severity, title, body, read_at, created_at)
                 VALUES (?1, 'approval_required', 'warning', 'Escalated for higher review', ?2, NULL, ?3)",
                rusqlite::params![crate::id(), format!("{target} was escalated to A3 review."), now()],
            )?;
            super::audit::record(tx, "approval.escalated", actor, "approval", id)?;
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

    pub fn create(conn: &Connection, title: &str, owner: &str, rationale: &str, actor: audit::Actor<'_>) -> CoreResult<Decision> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO decisions(id, title, status, owner, rationale, created_at, updated_at)
                 VALUES (?1, ?2, 'proposed', ?3, ?4, ?5, ?5)",
                rusqlite::params![id, title, owner, rationale, now],
            )?;
            super::audit::record(tx, "decision.created", actor, "decision", &id)?;
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

    /// What `repo::seed` writes into `payload_json` on every row it fabricates.
    /// A literal, so the writer and the reader cannot drift apart.
    pub const SEED_SOURCE: &str = r#"{"source":"seed"}"#;

    fn map(r: &Row) -> rusqlite::Result<ActivityEvent> {
        let payload: Option<String> = r.get("payload_json")?;
        Ok(ActivityEvent {
            id: r.get("id")?,
            event_type: r.get("event_type")?,
            actor_type: r.get("actor_type")?,
            actor_id: r.get("actor_id")?,
            entity_type: r.get("entity_type")?,
            entity_id: r.get("entity_id")?,
            // The mark travels to the surface. Marking the row and dropping it
            // here is the defect `actor_type` already carries a paragraph about,
            // and BOTH mappers carry it — `activity::map` and
            // `security::map_event` — or one surface tells the truth and the
            // other does not.
            source: crate::repo::activity::source_of(payload.as_deref()),
            created_at: r.get("created_at")?,
        })
    }

    /// The `source` a row's `payload_json` declares, if any.
    ///
    /// Parsed defensively rather than trusted: anything unreadable returns
    /// `None`, and `None` means "a real audited write". That direction is only
    /// safe because `seed` is the one thing in the tree that writes this key —
    /// if a second writer ever appears, this comment is the place that stops
    /// being true.
    pub(crate) fn source_of(payload: Option<&str>) -> Option<String> {
        let value: serde_json::Value = serde_json::from_str(payload?).ok()?;
        value.get("source")?.as_str().map(str::to_string)
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<ActivityEvent>> {
        let mut s = conn.prepare("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 200")?;
        let rows = s.query_map([], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }
}

#[cfg(test)]
mod t057_seeded_rows_say_so {
    use super::*;

    /// T-057's closure, asserted as the condition was written: a reader of
    /// `audit_events` tells fabricated rows from real ones WITHOUT reading
    /// repo.rs — here, by a query alone.
    #[test]
    fn a_query_alone_separates_the_fabricated_rows_from_the_real_ones() {
        let conn = crate::db::open_in_memory().unwrap();
        seed(&conn).unwrap();
        let fabricated: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM audit_events WHERE json_extract(payload_json,'$.source') = 'seed'",
                [], |r| r.get(0)).unwrap();
        assert_eq!(fabricated, 56, "every fabricated row says so");
        let real: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM audit_events WHERE COALESCE(json_extract(payload_json,'$.source'),'') <> 'seed'",
                [], |r| r.get(0)).unwrap();
        assert!(real > 0, "the seed also makes REAL audited writes; they must not be marked");
    }

    /// And the mark reaches the surface. Marking the row and dropping it before
    /// a reader sees it is the defect `ActivityEvent::actor_type` records.
    #[test]
    fn both_read_surfaces_carry_the_mark() {
        let conn = crate::db::open_in_memory().unwrap();
        seed(&conn).unwrap();
        let rows = activity::list(&conn).unwrap();
        let seeded = rows.iter().filter(|e| e.source.as_deref() == Some("seed")).count();
        assert!(seeded > 0, "activity::list must carry the mark");
        assert!(rows.iter().any(|e| e.source.is_none()),
                "and must not mark a real audited write");

        // The SECOND surface, asserted on ITS OWN rows. Until this existed the
        // test computed the summary, threw it away, and closed on a restatement
        // of the assertion above -- so `security::map_event` could drop `source`
        // entirely with every test still green.
        let summary = security::summary(&conn).unwrap();
        assert!(
            !summary.sensitive_events.is_empty(),
            "the seed must produce sensitive events, or the assertion below asserts nothing"
        );
        let marked = summary
            .sensitive_events
            .iter()
            .filter(|e| e.source.as_deref() == Some("seed"))
            .count();
        assert!(marked > 0, "security::summary must carry the mark too");
    }

    /// A real audited write is never marked, so `None` keeps meaning "real".
    #[test]
    fn a_real_audited_write_carries_no_source() {
        let conn = crate::db::open_in_memory().unwrap();
        audit::record(&conn, "task.created", audit::Actor::local_operator(), "task", "t-1").unwrap();
        let rows = activity::list(&conn).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].source, None);
    }

    /// An unreadable payload must not make a row look real by accident — it
    /// reads as `None`, which is the same as real, and THAT is why the constant
    /// and the parser live next to each other with the caveat written down.
    #[test]
    fn an_unreadable_payload_reads_as_none() {
        assert_eq!(activity::source_of(Some("not json at all")), None);
        assert_eq!(activity::source_of(Some(r#"{"other":"x"}"#)), None);
        assert_eq!(activity::source_of(None), None);
        assert_eq!(activity::source_of(Some(activity::SEED_SOURCE)), Some("seed".to_string()));
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

    /// The badge string the demonstration arm of [`MESSAGE_TRUST_COLUMNS`] emits and
    /// [`substantiated_receipt`] gates. Named once so the SQL and the Rust check cannot drift apart
    /// into a guard that silently matches nothing.
    const DEMONSTRATION_VERIFIED: &str = "demonstration_verified";

    /// The two trust columns every message SELECT must project, aliased `receipt` and
    /// `demonstration_body_sha256`, over `messages` aliased as `m`. [`map_message`] reads both.
    ///
    /// `receipt` = the outcome of the message's accepted verification attempt
    /// (`development_untrusted` | `trusted_verified`); else, as a FALLBACK, the honest
    /// `demonstration_verified` when the reply was produced + verified in-process under the
    /// DEMONSTRATION anchor (a separate additive table — never the production trust records). A real
    /// production receipt always wins (it is the first COALESCE arm). A `blocked` verdict has no
    /// message, so it never appears here.
    ///
    /// The accepted-attempt arm is an AGGREGATE, not `LIMIT 1`. It used to be
    /// `SELECT a.outcome ... LIMIT 1` with no `ORDER BY`, over a `message_id`
    /// column that carried no UNIQUE constraint and no index — so if a message
    /// ever had two accepted attempts, the badge this paints in the shipped chat
    /// was whichever row SQLite happened to return first. A green
    /// `trusted_verified` badge decided by a query plan is not a trust signal.
    /// Migration 0023 makes that state impossible (a partial UNIQUE index on
    /// `message_id`); this query stops depending on it anyway, and where two
    /// accepted attempts disagree it takes the WEAKER answer. Over-claiming
    /// trust is the failure that matters, so ambiguity resolves down, never up.
    ///
    /// `WHEN COUNT(*) = 0 THEN NULL` is load-bearing: an aggregate subquery over
    /// zero rows still returns one row, so without it a message with NO accepted
    /// attempt would fall through to the `ELSE` arm and be painted
    /// `trusted_verified`.
    ///
    /// The demonstration arm is deliberately UNGATED here and its stored digest is projected beside
    /// it, because SQLite cannot hash: the binding is decided in exactly one place,
    /// [`substantiated_receipt`], which [`map_message`] applies to every row this projection
    /// produces. See migration 0024 for why a flag row was not enough.
    ///
    /// This arm briefly also carried `AND d.body_sha256 IS NOT NULL`. It was deleted rather than
    /// shipped: it could not change any outcome — a NULL digest fails the Rust comparison anyway —
    /// and the two guards MASKED each other, so deleting either one on its own left every test green.
    /// Two checks that each hide the other's absence are worth less than one check that can fail, and
    /// `a_flag_row_with_no_body_digest_paints_no_badge` now fails if the remaining one is weakened.
    const MESSAGE_TRUST_COLUMNS: &str = "COALESCE(\
         (SELECT CASE \
                   WHEN COUNT(*) = 0 THEN NULL \
                   WHEN SUM(a.outcome = 'development_untrusted') > 0 \
                     THEN 'development_untrusted' \
                   ELSE 'trusted_verified' \
                 END \
            FROM receipt_verification_attempts a \
            WHERE a.message_id = m.id \
              AND a.outcome IN ('development_untrusted', 'trusted_verified')), \
         (SELECT 'demonstration_verified' \
            FROM demonstration_verified_messages d \
            WHERE d.message_id = m.id)) AS receipt, \
         (SELECT d.body_sha256 FROM demonstration_verified_messages d \
           WHERE d.message_id = m.id) AS demonstration_body_sha256";

    /// Keep a `demonstration_verified` badge only if the row that claims it carries the SHA-256 of
    /// the body it is painted on.
    ///
    /// **What this replaces.** `demonstration_verified_messages` was `(message_id, recorded_at)` —
    /// a flag. `commands::demonstration_verified_reply` runs the in-process governed chain in a temp
    /// directory and then `remove_dir_all`s it, so the receipt, the envelope and the signature that
    /// justified the green were destroyed before the row was written. Nothing connected the badge to
    /// any bytes, so the projection painted it on whatever text the message held: a row pointed at
    /// the wrong message, or a body edited afterwards, kept the green. It is the ONLY green badge the
    /// shipped app can currently display, so "there is a row" was the entire evidence a user had.
    ///
    /// Now the writer records the digest of the exact bytes the chain bound, in the same transaction
    /// as the message, and this recomputes it from the stored body. A mismatch — or an absent digest,
    /// which is every row written before migration 0024 — is not a downgrade to a weaker badge: it is
    /// NO badge, because the claim was that this text was verified and that claim is unsupported.
    ///
    /// Production receipts (`trusted_verified` / `development_untrusted`) are NOT touched here: they
    /// are backed by `receipt_verification_attempts`, which stores the envelope and signature and is
    /// re-verifiable on its own terms.
    fn substantiated_receipt(
        receipt: Option<String>,
        attested_body_sha256: Option<&str>,
        body: &str,
    ) -> Option<String> {
        if receipt.as_deref() != Some(DEMONSTRATION_VERIFIED) {
            return receipt;
        }
        match attested_body_sha256 {
            Some(digest) if digest == crate::governed_message_store::sha256_hex(body.as_bytes()) => receipt,
            _ => None,
        }
    }

    fn map_message(r: &Row) -> rusqlite::Result<Message> {
        let body: String = r.get("body")?;
        let receipt: Option<String> = r.get("receipt")?;
        let attested: Option<String> = r.get("demonstration_body_sha256")?;
        Ok(Message {
            id: r.get("id")?,
            conversation_id: r.get("conversation_id")?,
            role: r.get("role")?,
            author: r.get("author")?,
            receipt: substantiated_receipt(receipt, attested.as_deref(), &body),
            body,
            created_at: r.get("created_at")?,
        })
    }

    // Conversations carry a derived message count and last-activity timestamp so
    // the list view needs a single round trip.
    const CONVERSATION_SELECT: &str = "SELECT c.id, c.kind, c.title, c.created_at, c.updated_at, \
         COUNT(m.id) AS message_count, MAX(m.created_at) AS last_message_at \
         FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id";

    pub fn create_conversation(conn: &Connection, kind: &str, title: &str, actor: audit::Actor<'_>) -> CoreResult<Conversation> {
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
            super::audit::record(tx, "conversation.created", actor, "conversation", &id)?;
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
        let sql = format!(
            "SELECT m.*, {MESSAGE_TRUST_COLUMNS} FROM messages m \
             WHERE m.conversation_id = ?1 \
             ORDER BY m.created_at DESC, m.rowid DESC LIMIT ?2 OFFSET ?3"
        );
        let mut s = conn.prepare(&sql)?;
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
            super::audit::record(tx, "message.posted", super::audit::Actor::from_message(&input.role, &input.author), "conversation", &input.conversation_id)?;
            Ok(())
        })?;
        let sql = format!("SELECT m.*, {MESSAGE_TRUST_COLUMNS} FROM messages m WHERE m.id = ?1");
        conn.query_row(&sql, [id.clone()], map_message)
            .map_err(not_found(&id))
    }

    /// Record that a message's reply was produced + verified IN-PROCESS under the DEMONSTRATION anchor, so
    /// [`MESSAGE_TRUST_COLUMNS`] derives its badge to `demonstration_verified`. Idempotent
    /// (`INSERT OR IGNORE`). This is NEVER production trust — the caller writes it ONLY after the in-process
    /// governed chain returns trusted_verified for THIS exact message, and this demonstration table is separate
    /// from the CHECK-constrained production trust records (`receipt_verification_attempts`).
    ///
    /// `verified_body` is the EXACT reply bytes the chain bound; its SHA-256 is stored with the row and
    /// [`substantiated_receipt`] re-checks it against the persisted body on every read. Passing anything
    /// other than the bytes that were verified produces a row that paints no badge — which is the point:
    /// the caller can no longer assert the badge, only evidence it.
    pub fn record_demonstration_verified(
        conn: &Connection,
        message_id: &str,
        verified_body: &str,
    ) -> CoreResult<()> {
        let now = now();
        let digest = crate::governed_message_store::sha256_hex(verified_body.as_bytes());
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT OR IGNORE INTO demonstration_verified_messages(message_id, recorded_at, body_sha256) \
                 VALUES (?1, ?2, ?3)",
                rusqlite::params![message_id, now, digest],
            )?;
            Ok(())
        })?;
        Ok(())
    }

    /// Post an agent message AND record its DEMONSTRATION anchor in ONE transaction, returning the
    /// message with its derived `demonstration_verified` badge. Doing both atomically means the reply
    /// and its badge land together or not at all — a mid-way failure can never leave a verified reply
    /// persisted as an ordinary un-badged message. Same honesty contract as
    /// [`record_demonstration_verified`]: the caller invokes this ONLY after the in-process governed
    /// chain returned trusted_verified for THESE exact body bytes.
    pub fn post_message_demonstration_verified(conn: &Connection, input: NewMessage) -> CoreResult<Message> {
        if !is_valid(&input.role, MESSAGE_ROLES) {
            return Err(CoreError::Invalid { field: "role", value: input.role });
        }
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
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
            // The digest of the bytes just written, in the SAME transaction as the message — so the
            // badge and the body it attests can never be recorded apart (migration 0024).
            tx.execute(
                "INSERT OR IGNORE INTO demonstration_verified_messages(message_id, recorded_at, body_sha256) \
                 VALUES (?1, ?2, ?3)",
                rusqlite::params![
                    id,
                    now,
                    crate::governed_message_store::sha256_hex(input.body.as_bytes())
                ],
            )?;
            super::audit::record(tx, "message.posted", super::audit::Actor::from_message(&input.role, &input.author), "conversation", &input.conversation_id)?;
            Ok(())
        })?;
        let sql = format!("SELECT m.*, {MESSAGE_TRUST_COLUMNS} FROM messages m WHERE m.id = ?1");
        conn.query_row(&sql, [id.clone()], map_message).map_err(not_found(&id))
    }

    /// Delete a conversation and (via the FK cascade) all of its messages.
    /// Rejects an unknown conversation.
    pub fn delete_conversation(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM conversations WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "conversation.deleted", actor, "conversation", id)?;
            Ok(())
        })
    }

    /// Replace a conversation's participant roster (the explicit set of members in a group
    /// room). Idempotent: clears the existing rows and inserts the given names deduped and
    /// order-insensitive. The FK rejects an unknown conversation id, so callers pass a real one.
    pub fn set_participants(conn: &Connection, conversation_id: &str, names: &[String]) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            tx.execute(
                "DELETE FROM conversation_participants WHERE conversation_id = ?1",
                [conversation_id],
            )?;
            let mut seen = std::collections::HashSet::new();
            for name in names {
                let n = name.trim();
                if n.is_empty() || !seen.insert(n.to_string()) {
                    continue;
                }
                tx.execute(
                    "INSERT INTO conversation_participants (conversation_id, name, added_at) VALUES (?1, ?2, ?3)",
                    rusqlite::params![conversation_id, n, now()],
                )?;
            }
            Ok(())
        })
    }

    /// The participant roster for a conversation, alphabetical. Empty when none were set.
    pub fn list_participants(conn: &Connection, conversation_id: &str) -> CoreResult<Vec<String>> {
        let mut stmt = conn.prepare(
            "SELECT name FROM conversation_participants WHERE conversation_id = ?1 ORDER BY name",
        )?;
        let rows = stmt.query_map([conversation_id], |r| r.get::<_, String>(0))?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r?);
        }
        Ok(out)
    }

    /// Rename a conversation and bump its activity timestamp. Rejects an unknown
    /// conversation.
    pub fn rename_conversation(conn: &Connection, id: &str, title: &str, actor: audit::Actor<'_>) -> CoreResult<Conversation> {
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE conversations SET title = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![title, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "conversation.renamed", actor, "conversation", id)?;
            Ok(())
        })?;
        get_conversation(conn, id)
    }
}

/// Phase 5: every knowledge/memory write appends a LOCAL write record in the same
/// transaction as the write (see `crate::local_write_record`). It is unsigned and
/// host-local — tamper-EVIDENCE against a later out-of-band edit of the database file,
/// **not** a governed receipt and never to be labelled "verified".
use crate::local_write_record::{self as lwr, SubjectKind, WriteOp};

pub mod knowledge {
    use super::*;

    /// Digest of this note's recorded fields.
    fn digest(n: &KnowledgeNote) -> String {
        lwr::knowledge_content_sha256(&n.title, &n.body, &n.source, &n.tags)
    }

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

    pub fn create(conn: &Connection, input: NewKnowledgeNote, actor: audit::Actor<'_>) -> CoreResult<KnowledgeNote> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO knowledge_notes(id, title, body, source, tags, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
                rusqlite::params![id, input.title, input.body, input.source, input.tags, now],
            )?;
            // Same transaction as the INSERT: the note and its write record land
            // together or not at all, so a stored note can never lack its record.
            lwr::append(
                tx,
                SubjectKind::KnowledgeNote,
                &id,
                WriteOp::Created,
                &lwr::knowledge_content_sha256(&input.title, &input.body, &input.source, &input.tags),
                &now,
            )?;
            super::audit::record(tx, "knowledge.created", actor, "knowledge_note", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    /// Where this note stands against its own write record: `Recorded`,
    /// `ContentDiverged` (edited out of band), or `Unrecorded` (written before the
    /// ledger existed — never back-filled).
    pub fn write_record_state(
        conn: &Connection,
        id: &str,
    ) -> CoreResult<lwr::SubjectState> {
        let note = get(conn, id)?;
        lwr::state_of(conn, SubjectKind::KnowledgeNote, id, &digest(&note))
    }

    /// Every write record for this note, oldest first (kept after deletion).
    pub fn write_records(conn: &Connection, id: &str) -> CoreResult<Vec<lwr::WriteRecord>> {
        lwr::records_for(conn, SubjectKind::KnowledgeNote, id)
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

    pub fn delete(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            // Read first so the `deleted` record can pin WHAT was removed. The record
            // carries no FK to the note precisely so it outlives it — the one write
            // that most needs evidence must not erase its own.
            let note = get(tx, id)?;
            let changed = tx.execute("DELETE FROM knowledge_notes WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            lwr::append(
                tx,
                SubjectKind::KnowledgeNote,
                id,
                WriteOp::Deleted,
                &digest(&note),
                &now(),
            )?;
            super::audit::record(tx, "knowledge.deleted", actor, "knowledge_note", id)?;
            Ok(())
        })
    }
}

pub mod memory {
    use super::*;

    /// Digest of this entry's recorded fields.
    fn digest(e: &MemoryEntry) -> String {
        lwr::memory_content_sha256(&e.scope, &e.kind, &e.content, e.pinned)
    }

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

    pub fn create(conn: &Connection, input: NewMemoryEntry, actor: audit::Actor<'_>) -> CoreResult<MemoryEntry> {
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
            // Same transaction as the INSERT (see the module note above).
            lwr::append(
                tx,
                SubjectKind::MemoryEntry,
                &id,
                WriteOp::Created,
                // `pinned` is 0 in the INSERT above; the digest must mirror the row.
                &lwr::memory_content_sha256(&input.scope, &input.kind, &input.content, false),
                &now,
            )?;
            super::audit::record(tx, "memory.created", actor, "memory_entry", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    /// Where this entry stands against its own write record: `Recorded`,
    /// `ContentDiverged` (edited out of band), or `Unrecorded` (written before the
    /// ledger existed — never back-filled).
    pub fn write_record_state(conn: &Connection, id: &str) -> CoreResult<lwr::SubjectState> {
        let entry = get(conn, id)?;
        lwr::state_of(conn, SubjectKind::MemoryEntry, id, &digest(&entry))
    }

    /// Every write record for this entry, oldest first (kept after deletion).
    pub fn write_records(conn: &Connection, id: &str) -> CoreResult<Vec<lwr::WriteRecord>> {
        lwr::records_for(conn, SubjectKind::MemoryEntry, id)
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

    /// Pinning is a real content change (`pinned` is part of the recorded digest), so
    /// it is now atomic and records an `updated` write record — otherwise a pin toggle
    /// would silently leave every entry looking diverged.
    pub fn set_pinned(conn: &Connection, id: &str, pinned: bool) -> CoreResult<MemoryEntry> {
        super::atomic(conn, |tx| {
            let now = now();
            let changed = tx.execute(
                "UPDATE memory_entries SET pinned = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![pinned as i64, now, id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            // Re-read INSIDE the transaction so the digest is of the row as stored,
            // never of what the caller believed it wrote.
            let entry = get(tx, id)?;
            lwr::append(
                tx,
                SubjectKind::MemoryEntry,
                id,
                WriteOp::Updated,
                &digest(&entry),
                &now,
            )?;
            Ok(())
        })?;
        get(conn, id)
    }

    pub fn delete(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            // Read first so the `deleted` record pins WHAT was removed (see
            // `knowledge::delete` for why the record carries no FK to the row).
            let entry = get(tx, id)?;
            let changed = tx.execute("DELETE FROM memory_entries WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            lwr::append(
                tx,
                SubjectKind::MemoryEntry,
                id,
                WriteOp::Deleted,
                &digest(&entry),
                &now(),
            )?;
            super::audit::record(tx, "memory.deleted", actor, "memory_entry", id)?;
            Ok(())
        })
    }
}

pub mod library {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<LibraryItem> {
        Ok(LibraryItem {
            id: r.get("id")?,
            title: r.get("title")?,
            kind: r.get("kind")?,
            body: r.get("body")?,
            tags: r.get("tags")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, input: NewLibraryItem, actor: audit::Actor<'_>) -> CoreResult<LibraryItem> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO library_items(id, title, kind, body, tags, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
                rusqlite::params![id, input.title, input.kind, input.body, input.tags, now],
            )?;
            super::audit::record(tx, "library.created", actor, "library_item", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<LibraryItem> {
        conn.query_row("SELECT * FROM library_items WHERE id = ?1", [id], map)
            .map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<LibraryItem>> {
        let mut s = conn.prepare("SELECT * FROM library_items ORDER BY updated_at DESC LIMIT ?1")?;
        let rows = s.query_map([super::MAX_PAGE], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn delete(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM library_items WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "library.deleted", actor, "library_item", id)?;
            Ok(())
        })
    }
}

pub mod research {
    use super::*;

    fn map(r: &Row) -> rusqlite::Result<ResearchItem> {
        Ok(ResearchItem {
            id: r.get("id")?,
            title: r.get("title")?,
            question: r.get("question")?,
            findings: r.get("findings")?,
            status: r.get("status")?,
            created_at: r.get("created_at")?,
            updated_at: r.get("updated_at")?,
        })
    }

    pub fn create(conn: &Connection, input: NewResearchItem, actor: audit::Actor<'_>) -> CoreResult<ResearchItem> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO research_items(id, title, question, findings, status, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
                rusqlite::params![id, input.title, input.question, input.findings, input.status, now],
            )?;
            super::audit::record(tx, "research.created", actor, "research_item", &id)?;
            Ok(())
        })?;
        get(conn, &id)
    }

    pub fn get(conn: &Connection, id: &str) -> CoreResult<ResearchItem> {
        conn.query_row("SELECT * FROM research_items WHERE id = ?1", [id], map)
            .map_err(not_found(id))
    }

    pub fn list(conn: &Connection) -> CoreResult<Vec<ResearchItem>> {
        let mut s = conn.prepare("SELECT * FROM research_items ORDER BY updated_at DESC LIMIT ?1")?;
        let rows = s.query_map([super::MAX_PAGE], map)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn delete(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM research_items WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "research.deleted", actor, "research_item", id)?;
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

    pub fn create(conn: &Connection, intent: &str, plan: &str, actor: audit::Actor<'_>) -> CoreResult<Run> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO runs(id, intent, status, plan, created_at, updated_at)
                 VALUES (?1, ?2, 'drafted', ?3, ?4, ?4)",
                rusqlite::params![id, intent, plan, now],
            )?;
            super::audit::record(tx, "run.created", actor, "run", &id)?;
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

    pub fn set_status(conn: &Connection, id: &str, status: &str, actor: audit::Actor<'_>) -> CoreResult<Run> {
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
            super::audit::record(tx, "run.status_changed", actor, "run", id)?;
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
            execution_attempt_id: r.get("execution_attempt_id")?,
            execution_owner_session_id: r.get("execution_owner_session_id")?,
            execution_started_at: r.get("execution_started_at")?,
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
    /// T-011: atomically CLAIM a runnable step for execution BEFORE the provider is
    /// called, so one approval starts exactly one execution. In one transaction it
    /// refuses if the run already has a step mid-execution, then claims this step by
    /// writing a fresh one-time `execution_attempt_id` (+ owner session / start time)
    /// under an `execution_attempt_id IS NULL` guard — the status is NOT changed, the
    /// attempt-id is the claim token, and a concurrent claim writes 0 rows and fails —
    /// and, for a gated step, verifies the native-confirmed grant and CONSUMES it now.
    /// A provider failure therefore leaves no reusable grant; a retry needs a fresh
    /// approval. Returns the attempt id the caller presents to complete/fail the step.
    pub fn claim_step_for_execution(conn: &Connection, id: &str, session_id: &str) -> CoreResult<String> {
        let attempt = crate::id();
        super::atomic(conn, |tx| {
            let step = get_step(tx, id)?;
            // At most one step per run may be in-flight (claimed via
            // `execution_attempt_id` but not yet done/failed) — no parallel steps.
            let mid: i64 = tx.query_row(
                "SELECT COUNT(*) FROM run_steps
                   WHERE run_id = ?1 AND id != ?2
                     AND execution_attempt_id IS NOT NULL AND status IN ('active','pending')",
                rusqlite::params![step.run_id, id],
                |r| r.get(0),
            )?;
            if mid > 0 {
                return Err(CoreError::Invalid { field: "status", value: "run already has a step mid-execution".into() });
            }
            // Claim: a runnable step with no attempt yet. The `execution_attempt_id IS
            // NULL` guard is the mutual exclusion — a second concurrent claim writes 0
            // rows and is refused here, before any provider dispatch. The owner session
            // + start time make the claim crash-recoverable (see reconcile_*).
            let n = tx.execute(
                "UPDATE run_steps
                    SET execution_attempt_id = ?1, execution_owner_session_id = ?2,
                        execution_started_at = ?3, updated_at = ?3
                   WHERE id = ?4 AND status IN ('active','pending') AND execution_attempt_id IS NULL",
                rusqlite::params![attempt, session_id, now(), id],
            )?;
            if n == 0 {
                return Err(CoreError::Invalid { field: "status", value: "step is not runnable or already claimed for execution".into() });
            }
            // Gated step: verify + consume the grant now, before dispatch (M-2).
            if step.requires_approval {
                super::approvals::require_and_consume(
                    tx,
                    id,
                    super::approvals::RUN_STEP_ENTITY_TYPE,
                    super::approvals::RUN_STEP_ACTION_TYPE,
                )?;
            }
            Ok(())
        })?;
        Ok(attempt)
    }

    /// Complete a claimed execution -> `done`, storing the result. The grant was
    /// already consumed at claim, so this does not re-gate; only the claiming attempt
    /// (on a still-runnable step) may complete — a stale/duplicate dispatch fails.
    pub fn complete_step_execution(conn: &Connection, id: &str, attempt: &str, result: &str, actor: audit::Actor<'_>) -> CoreResult<RunStep> {
        super::atomic(conn, |tx| {
            let n = tx.execute(
                "UPDATE run_steps SET result = ?1, status = 'done', updated_at = ?2
                   WHERE id = ?3 AND execution_attempt_id = ?4 AND status IN ('active','pending')",
                rusqlite::params![result, now(), id, attempt],
            )?;
            if n == 0 {
                return Err(CoreError::Invalid { field: "attempt", value: "stale or invalid execution attempt".into() });
            }
            super::audit::record(tx, "run_step.executed", actor, "run_step", id)?;
            Ok(())
        })?;
        get_step(conn, id)
    }

    /// Fail a claimed execution -> `failed`. The grant consumed at claim is NOT
    /// restored — a retry needs a fresh approval (safest v1). Only the claiming
    /// attempt on a still-runnable step may fail it; a wrong/stale attempt is refused.
    pub fn fail_step_execution(conn: &Connection, id: &str, attempt: &str) -> CoreResult<RunStep> {
        super::atomic(conn, |tx| {
            let n = tx.execute(
                "UPDATE run_steps SET status = 'failed', updated_at = ?1
                   WHERE id = ?2 AND execution_attempt_id = ?3 AND status IN ('active','pending')",
                rusqlite::params![now(), id, attempt],
            )?;
            if n == 0 {
                return Err(CoreError::Invalid { field: "attempt", value: "stale or invalid execution attempt".into() });
            }
            Ok(())
        })?;
        get_step(conn, id)
    }

    /// Startup reconciliation (T-011 crash recovery): a step claimed for execution by
    /// a PREVIOUS/dead session (owner session != the current one) is settled
    /// fail-closed — step -> `failed`, its run -> `failed`, `execution.abandoned`
    /// audited. The consumed grant is NOT restored: a retry needs a fresh approval.
    /// This unwedges a run whose process crashed mid-provider-call, where the durable
    /// claim would otherwise block every new claim and `advance` forever.
    ///
    /// ASSUMES a single app instance: a claim owned by any other session is treated as
    /// dead. Running multiple instances against one database would need single-instance
    /// enforcement or session-liveness validation before enabling this.
    pub fn reconcile_abandoned_executions(conn: &Connection, current_session_id: &str) -> CoreResult<u32> {
        let mut reconciled = 0u32;
        super::atomic(conn, |tx| {
            let stale: Vec<(String, String)> = {
                let mut s = tx.prepare(
                    "SELECT id, run_id FROM run_steps
                       WHERE execution_attempt_id IS NOT NULL AND status IN ('active','pending')
                         AND (execution_owner_session_id IS NULL OR execution_owner_session_id != ?1)",
                )?;
                let rows = s.query_map([current_session_id], |r| Ok((r.get(0)?, r.get(1)?)))?;
                rows.collect::<rusqlite::Result<Vec<_>>>()?
            };
            for (step_id, run_id) in &stale {
                tx.execute(
                    "UPDATE run_steps SET status = 'failed', updated_at = ?1 WHERE id = ?2",
                    rusqlite::params![now(), step_id],
                )?;
                tx.execute(
                    "UPDATE runs SET status = 'failed', updated_at = ?1 WHERE id = ?2",
                    rusqlite::params![now(), run_id],
                )?;
                super::audit::record(tx, "execution.abandoned", audit::Actor::system(), "run_step", step_id)?;
                reconciled += 1;
            }
            Ok(())
        })?;
        Ok(reconciled)
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
            let step = get_step(tx, id)?;
            // A step with a live execution claim (execution_attempt_id set) is owned by an in-flight
            // attempt — only complete_step_execution / fail_step_execution (both attempt-guarded) may
            // move it. Reject a bare status change here so a renderer cannot side-step the T-011
            // in-flight mutual-exclusion guards (which key off status IN ('active','pending')) by
            // flipping a claimed step to 'skipped'/'failed' mid-execution — which would let a SECOND
            // step in the run be claimed concurrently and could drop the real verified result.
            if step.execution_attempt_id.is_some() {
                return Err(CoreError::Invalid {
                    field: "status",
                    value: "step is executing (claimed) — its status is owned by the execution attempt".to_string(),
                });
            }
            // Enforce the approval gate here too, not just in advance()/stream_run_step:
            // a gated step can never be marked `done` without a matching approval,
            // whichever command sets it. Gate read and UPDATE share one transaction.
            if status == "done" && step.requires_approval {
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

    /// Fail a step AND its run together in ONE transaction. Used when a step's approval was
    /// rejected: previously the step and run were failed by two separate committed writes with both
    /// Results discarded, so a crash (or an error on the second) could leave the step 'failed' while
    /// the run stayed non-terminal. Direct terminal writes — this is an internal outcome, not a
    /// renderer-driven transition, so it does not go through set_status/set_step_status.
    pub fn fail_step_and_run(conn: &Connection, step_id: &str, run_id: &str) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            tx.execute(
                "UPDATE run_steps SET status = 'failed', updated_at = ?1 WHERE id = ?2",
                rusqlite::params![now(), step_id],
            )?;
            tx.execute(
                "UPDATE runs SET status = 'failed', updated_at = ?1 WHERE id = ?2",
                rusqlite::params![now(), run_id],
            )?;
            super::audit::record(tx, "run_step.rejected", audit::Actor::system(), "run_step", step_id)?;
            Ok(())
        })
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
    pub fn advance(conn: &Connection, run_id: &str, actor: audit::Actor<'_>) -> CoreResult<Run> {
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
            // T-011: a step claimed for execution is mid-flight — advancing past it
            // would activate the next step in parallel. Refuse until it settles
            // (complete_step_execution -> done, or fail_step_execution -> failed).
            let executing: i64 = tx.query_row(
                "SELECT COUNT(*) FROM run_steps
                   WHERE run_id = ?1 AND execution_attempt_id IS NOT NULL AND status IN ('active','pending')",
                [run_id],
                |r| r.get(0),
            )?;
            if executing > 0 {
                return Err(CoreError::Invalid { field: "status", value: "a step is mid-execution".to_string() });
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
            // Complete ONLY the single active step we approval-checked above (`active`),
            // not every row in status='active'. A run can transiently hold more than one
            // 'active' step (set_step_status can activate a step directly), and a blanket
            // `WHERE status='active'` UPDATE would silently mark those extra steps `done`
            // WITHOUT their own requires_approval gate — completing an unapproved gated
            // step (M-6 / audit F-12). Bind the completion to the exact step we gated; any
            // other active step stays active and gets its own gate on the next advance().
            if let Some(active) = &active {
                tx.execute(
                    "UPDATE run_steps SET status = 'done', updated_at = ?1 WHERE id = ?2 AND status = 'active'",
                    rusqlite::params![now, active.id],
                )?;
                // The grant that unlocked the just-completed gated step is spent
                // in the same transaction (M-2).
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
                        set_status(tx, run_id, "running", actor)?;
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
                    set_status(tx, run_id, terminal, actor)?;
                }
            }
            super::audit::record(tx, "run.advanced", actor, "run", run_id)?;
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

    pub fn create(conn: &Connection, input: NewEvent, actor: audit::Actor<'_>) -> CoreResult<Event> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO events(id, title, kind, location, starts_at, ends_at, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?7)",
                rusqlite::params![id, input.title, input.kind, input.location, input.starts_at, input.ends_at, now],
            )?;
            super::audit::record(tx, "event.created", actor, "event", &id)?;
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

    pub fn delete(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM events WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "event.deleted", actor, "event", id)?;
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

    /// Declare an automation. It is created **disarmed** (`enabled = 0`).
    ///
    /// It used to be created with `enabled = 1`, which made the T-052 arming gate
    /// on [`set_enabled`] worthless: `create_automation` is itself tier X with
    /// `grant: allow`, so anyone who could reach it could mint an already-armed
    /// automation and never touch the gated path at all. A gate with a one-call
    /// way around it is not a gate. Arming is now reachable only through
    /// [`set_enabled`], which requires a natively confirmed grant.
    pub fn create(conn: &Connection, input: NewAutomation, actor: audit::Actor<'_>) -> CoreResult<Automation> {
        let now = now();
        let id = id();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO automations(id, name, trigger, action, enabled, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, 0, ?5, ?5)",
                rusqlite::params![id, input.name, input.trigger, input.action, now],
            )?;
            super::audit::record(tx, "automation.created", actor, "automation", &id)?;
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

    /// Arm or disarm an automation.
    ///
    /// **The T-052 tier-X gate is asymmetric, deliberately.** ARMING is the
    /// execution-tier act: an enabled automation with an `every: <N>{m|h|d}`
    /// trigger is fired unattended by the 60s scheduler loop and writes tasks and
    /// knowledge notes with nobody present, so it requires a natively confirmed
    /// grant. DISARMING is not gated and must never be: it is the only way to stop
    /// a running automation, and putting an approval ceremony in front of the stop
    /// button would turn this gate into a denial of service on the operator's own
    /// safety control. Gating both directions would have been the symmetrical
    /// answer and the wrong one.
    pub fn set_enabled(conn: &Connection, id: &str, enabled: bool, actor: audit::Actor<'_>) -> CoreResult<Automation> {
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE automations SET enabled = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![enabled as i64, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            if enabled {
                super::approvals::require_and_consume(
                    tx,
                    id,
                    super::approvals::AUTOMATION_ENTITY_TYPE,
                    super::approvals::AUTOMATION_ENABLED_ACTION_TYPE,
                )?;
            }
            super::audit::record(tx, "automation.toggled", actor, "automation", id)?;
            Ok(())
        })?;
        get(conn, id)
    }

    fn map_run(r: &Row) -> rusqlite::Result<AutomationRun> {
        Ok(AutomationRun {
            id: r.get("id")?,
            automation_id: r.get("automation_id")?,
            ran_at: r.get("ran_at")?,
            outcome: r.get("outcome")?,
            detail: r.get("detail")?,
        })
    }

    /// Perform an automation's ACTION locally and return (outcome, human detail). The action is a
    /// small honest `verb: argument` vocabulary that maps to LOCAL effects only — no AI provider is
    /// reached (an AI-touching action would have to route through the governed, fail-closed chain, not
    /// fire unattended). An unrecognized verb is a recorded 'failed' outcome, never a silent no-op.
    ///   notify: <text>  -> raise a notification
    ///   task:   <title> -> create a task
    ///   note:   <title> -> create a knowledge note
    fn execute_action(conn: &Connection, action: &str) -> CoreResult<(&'static str, String)> {
        let trimmed = action.trim();
        let (verb, arg) = match trimmed.split_once(':') {
            Some((v, a)) => (v.trim().to_lowercase(), a.trim().to_string()),
            None => {
                return Ok(("failed", format!("unrecognized action (expected `verb: argument`): {trimmed}")))
            }
        };
        if arg.is_empty() {
            return Ok(("failed", format!("action '{verb}' has no argument")));
        }
        match verb.as_str() {
            "notify" => {
                super::atomic(conn, |tx| {
                    tx.execute(
                        "INSERT INTO notifications(id, type, severity, title, body, read_at, created_at)
                         VALUES (?1, 'automation', 'info', 'Automation', ?2, NULL, ?3)",
                        rusqlite::params![crate::id(), arg, now()],
                    )?;
                    Ok(())
                })?;
                Ok(("ok", format!("notified: {arg}")))
            }
            "task" => {
                tasks::create(
                    conn,
                    NewTask {
                        project_id: None,
                        title: arg.clone(),
                        description: String::new(),
                        priority: "normal".to_string(),
                        assigned_agent_id: None,
                    },
                    // The automation's own action authored this row, whoever set the
                    // automation running. Recording it as a human is what made an
                    // unattended 3am tick indistinguishable from someone typing.
                    audit::Actor::automation(),
                )?;
                Ok(("ok", format!("created task: {arg}")))
            }
            "note" => {
                knowledge::create(
                    conn,
                    NewKnowledgeNote {
                        title: arg.clone(),
                        body: String::new(),
                        source: "automation".to_string(),
                        tags: String::new(),
                    },
                    audit::Actor::automation(),
                )?;
                Ok(("ok", format!("created note: {arg}")))
            }
            other => Ok(("failed", format!("unknown action verb '{other}' (supported: notify, task, note)"))),
        }
    }

    /// Run an automation NOW: perform its action (locally, fail-closed for anything AI) and append a
    /// row to the run log, returning it. A disabled automation refuses to run.
    pub fn run(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<AutomationRun> {
        let automation = get(conn, id)?;
        if !automation.enabled {
            return Err(CoreError::Invalid {
                field: "enabled",
                value: "automation is disabled".to_string(),
            });
        }
        let (outcome, detail) = execute_action(conn, &automation.action)?;
        let run_id = crate::id();
        let now = now();
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT INTO automation_runs(id, automation_id, ran_at, outcome, detail) VALUES (?1, ?2, ?3, ?4, ?5)",
                rusqlite::params![run_id, id, now, outcome, detail],
            )?;
            super::audit::record(tx, "automation.ran", actor, "automation", id)?;
            Ok(())
        })?;
        conn.query_row("SELECT * FROM automation_runs WHERE id = ?1", [&run_id], map_run)
            .map_err(not_found(&run_id))
    }

    /// The run history for one automation, newest first.
    pub fn list_runs(conn: &Connection, automation_id: &str) -> CoreResult<Vec<AutomationRun>> {
        let mut s = conn.prepare(
            "SELECT * FROM automation_runs WHERE automation_id = ?1 ORDER BY ran_at DESC LIMIT ?2",
        )?;
        let rows = s.query_map(rusqlite::params![automation_id, super::MAX_PAGE], map_run)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Parse a time trigger `every: <N>{m|h|d}` into an interval in milliseconds. Anything else
    /// (empty, `manual`, an unrecognized shape) is None — those automations are NOT scheduled and
    /// only run via an explicit "Run now". Keeping the vocabulary tiny + explicit keeps scheduling
    /// honest and predictable.
    pub fn parse_interval_ms(trigger: &str) -> Option<i64> {
        let rest = trigger.trim().to_lowercase();
        let rest = rest.strip_prefix("every:")?.trim().to_string();
        if rest.len() < 2 {
            return None;
        }
        let (num, unit) = rest.split_at(rest.len() - 1);
        let n: i64 = num.trim().parse().ok()?;
        if n <= 0 {
            return None;
        }
        match unit {
            "m" => Some(n * 60_000),
            "h" => Some(n * 3_600_000),
            "d" => Some(n * 86_400_000),
            _ => None,
        }
    }

    /// The local scheduler tick: fire every ENABLED automation whose interval trigger is DUE (never
    /// run, or last run at least one interval ago), running its LOCAL action and logging the run.
    /// Returns the runs fired this tick. Only local, non-AI actions ever fire unattended here — an
    /// AI-reaching action would route through the governed, fail-closed chain, not this loop.
    pub fn run_due(conn: &Connection, now_ms: i64) -> CoreResult<Vec<AutomationRun>> {
        let mut fired = Vec::new();
        for a in list(conn)? {
            if !a.enabled {
                continue;
            }
            let interval = match parse_interval_ms(&a.trigger) {
                Some(i) => i,
                None => continue, // manual / unrecognized → not scheduled
            };
            let last_ms = list_runs(conn, &a.id)?
                .first()
                .and_then(|r| r.ran_at.parse::<i64>().ok());
            let due = match last_ms {
                Some(t) => now_ms.saturating_sub(t) >= interval,
                None => true,
            };
            if due {
                // Unattended: this loop runs on a 60s timer with nobody at the
                // cockpit, so the run is the scheduler's, not a person's.
                fired.push(run(conn, &a.id, audit::Actor::scheduler())?);
            }
        }
        // The produced-agent half of the same tick. It enqueues AND dispatches.
        //
        // Until T-058 it enqueued and performed nothing, and that sentence is no
        // longer true -- so here is the new ceiling, enumerated rather than
        // described. A tick may write: a `flow_runs` row, a `scheduler_ticks`
        // row, a `flow_receipts` row, `audit_events` rows, and whatever a `store`
        // step's `knowledge::create` writes. Nothing else. That is the SAME
        // ceiling the automation half above already sits at -- `execute_action`
        // writes notifications, tasks and knowledge notes on this very tick --
        // so dispatch adds no class of capability. It closes the gap between the
        // two halves in favour of the more restrained one: the produced agent's
        // vocabulary is a closed four-kind type rather than a `verb: arg` string,
        // it is checked against a digest and a grant, it leaves a receipt, and
        // `model` and `call` steps are still REFUSED.
        //
        // Dispatch reaches only bundles that are ARMED, and arming is a separate
        // act behind a natively confirmed grant (`agent_runs::set_active`).
        // Registering a bundle no longer arms it.
        //
        // A store root that is absent is not an error: no agent has been built.
        if let Some(root) = super::agent_runs::default_store_root() {
            super::agent_runs::enqueue_due(conn, now_ms, &root)?;
            // Bounded, so one tick cannot become unbounded work: a backlog is
            // drained across ticks rather than inside one. `claim_and_run`
            // returns None when nothing is queued, which ends the loop early.
            for _ in 0..super::agent_runs::MAX_DISPATCH_PER_TICK {
                if super::agent_runs::claim_and_run(conn, &root, "scheduler", now_ms)?.is_none() {
                    break;
                }
            }
        }
        Ok(fired)
    }

    pub fn delete(conn: &Connection, id: &str, actor: audit::Actor<'_>) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            let changed = tx.execute("DELETE FROM automations WHERE id = ?1", [id])?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            super::audit::record(tx, "automation.deleted", actor, "automation", id)?;
            Ok(())
        })
    }
}

/// The produced-agent scheduler half (T-055). Design: `docs/design/PRODUCTION_HALF_DESIGN.md` §5.
///
/// Two things are deliberate here and both are refusals rather than fallbacks.
///
/// **A tick that finds nothing still writes a row.** `scheduler_ticks` exists
/// because `lib.rs` discarded `run_due`'s result with `let _ =`, which made a
/// poisoned mutex, a failed open and a quiet week look identical. A scheduler
/// that cannot say what it did on a tick cannot be audited unattended.
///
/// **A bad bundle is refused, not skipped.** A skipped fire leaves no row, and
/// "nothing happened" is exactly what a log must not say when something was
/// tampered with. A refusal leaves a row with a typed reason from a closed set.
pub mod agent_runs {
    use super::*;
    use crate::agent_bundle::{self, Refusal, StepKind};
    use std::path::{Path, PathBuf};

    /// Where the store lives when the caller names none. `BROPS_AGENT_STORE` is
    /// read rather than assumed: the desktop's app-data directory is not known
    /// to this crate, and inventing a path here would be a claim about a layout
    /// this module cannot see.
    pub fn default_store_root() -> Option<PathBuf> {
        std::env::var_os("BROPS_AGENT_STORE").map(PathBuf::from).filter(|p| p.is_dir())
    }

    /// The regime a run executed under, recorded ON the receipt. Read once here
    /// rather than at display time, because a receipt that cannot distinguish
    /// "was blocked" from "would have been blocked" is not evidence.
    /// How many queued runs one 60s tick may dispatch.
    ///
    /// A bound, not a tuning knob: without it a backlog makes a single
    /// unattended tick unbounded work. Four is enough that a handful of agents
    /// on one interval all run within a tick, and small enough that the loop
    /// cannot hold the scheduler. What does not fit waits for the next tick.
    pub const MAX_DISPATCH_PER_TICK: usize = 4;

    pub fn enforcement_regime() -> String {
        std::env::var("BRO_ENFORCEMENT").unwrap_or_else(|_| "enforce".to_string())
    }

    /// Record a built bundle. It is created **DISARMED**: no `agent_bundle_active`
    /// row, so the scheduler resolves no trigger to it and nothing dispatches it.
    ///
    /// This function used to write BOTH tables in one call, and to hardcode
    /// `state = 'approved'` while doing it — so building an agent and arming it
    /// were the same act, and the arming path could be skipped entirely. That was
    /// harmless only while the tick performed nothing; the moment the tick
    /// dispatches, a bundle that arms itself at creation is an unattended
    /// executor nobody approved. It is the exact defect `automations::create`
    /// already carries a paragraph about: *"a gate with a one-call way around it
    /// is not a gate"*. Arming is now reachable only through [`set_active`].
    ///
    /// `state` is `'built'`, which is what a freshly written bundle is. Nothing
    /// here decides that it is approved.
    pub fn register(
        conn: &Connection,
        digest: &str,
        bundle_id: &str,
        bundle_version: u64,
        display_name: &str,
    ) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            tx.execute(
                "INSERT OR REPLACE INTO agent_bundles(bundle_digest, bundle_id, bundle_version, \
                 display_name, built_at, state, created_at) VALUES (?1,?2,?3,?4,?5,'built',?6)",
                rusqlite::params![digest, bundle_id, bundle_version as i64, display_name, crate::now(), crate::now()],
            )?;
            super::audit::record(tx, "agent_bundle.registered", audit::Actor::system(), "agent_bundle", digest)?;
            Ok(())
        })
    }

    /// Arm or disarm a bundle — the act the scheduler's dispatch depends on.
    ///
    /// **Asymmetric, and deliberately so, exactly as `automations::set_enabled`
    /// is.** ARMING is the execution-tier act: an armed bundle is claimed and run
    /// by the 60s tick with nobody present, so it requires a natively confirmed
    /// grant and consumes it. DISARMING is NOT gated and must never be — it is
    /// the only way to stop a running agent, and an approval ceremony in front of
    /// the stop button turns this gate into a denial of service on the operator's
    /// own safety control.
    pub fn set_active(
        conn: &Connection,
        bundle_id: &str,
        digest: &str,
        interval_ms: i64,
        active: bool,
        actor: audit::Actor<'_>,
    ) -> CoreResult<()> {
        super::atomic(conn, |tx| {
            if active {
                super::approvals::require_and_consume(
                    tx,
                    digest,
                    super::approvals::AGENT_BUNDLE_ENTITY_TYPE,
                    super::approvals::AGENT_BUNDLE_ARM_ACTION_TYPE,
                )?;
                tx.execute(
                    "INSERT OR REPLACE INTO agent_bundle_active(bundle_id, bundle_digest, interval_ms, updated_at) \
                     VALUES (?1,?2,?3,?4)",
                    rusqlite::params![bundle_id, digest, interval_ms, crate::now()],
                )?;
            } else {
                tx.execute("DELETE FROM agent_bundle_active WHERE bundle_id = ?1", [bundle_id])?;
            }
            super::audit::record(
                tx,
                if active { "agent_bundle.armed" } else { "agent_bundle.disarmed" },
                actor,
                "agent_bundle",
                digest,
            )?;
            Ok(())
        })
    }

    fn last_run_ms(conn: &Connection, bundle_id: &str) -> CoreResult<Option<i64>> {
        let v: Option<String> = conn
            .query_row(
                "SELECT due_at FROM flow_runs WHERE bundle_id = ?1 ORDER BY due_at DESC LIMIT 1",
                [bundle_id],
                |r| r.get(0),
            )
            .optional()?;
        Ok(v.and_then(|s| s.parse::<i64>().ok()))
    }

    /// Detect due bundles and enqueue. Returns `(due_found, enqueued, refused)`.
    ///
    /// THIS function still performs no action, reaches no network, holds no
    /// credential and calls no model — but do not read that as a statement
    /// about the tick, which since T-058 calls `claim_and_run` after this
    /// returns. The enumerated ceiling for the tick is in `automations::run_due`.
    pub fn enqueue_due(
        conn: &Connection,
        now_ms: i64,
        store_root: &Path,
    ) -> CoreResult<(u32, u32, u32)> {
        let mut rows: Vec<(String, String, i64)> = Vec::new();
        {
            let mut st = conn.prepare(
                "SELECT bundle_id, bundle_digest, interval_ms FROM agent_bundle_active",
            )?;
            let it = st.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?;
            for row in it {
                rows.push(row?);
            }
        }
        let (mut due_found, mut enqueued, mut refused) = (0u32, 0u32, 0u32);
        for (bundle_id, digest, interval_ms) in rows {
            let due = match last_run_ms(conn, &bundle_id)? {
                Some(t) => now_ms.saturating_sub(t) >= interval_ms,
                None => true,
            };
            if !due {
                continue;
            }
            due_found += 1;
            // Re-verify before enqueuing: the bytes may have changed since the
            // build, and a mismatch is a refusal with a reason, never a skip.
            let outcome = agent_bundle::verify(&store_root.join(&digest), now_ms / 1000);
            let (state, reason) = match &outcome {
                Ok(_) => ("queued", None),
                Err(r) => ("refused", Some(r.as_str())),
            };
            let id = format!("fr-{}-{}", &digest[..12], now_ms);
            super::atomic(conn, |tx| {
                tx.execute(
                    "INSERT OR IGNORE INTO flow_runs(id, bundle_id, bundle_digest, trigger_kind, \
                     invoked_by, due_at, state, refusal_reason, created_at) \
                     VALUES (?1,?2,?3,'interval','run_due',?4,?5,?6,?7)",
                    rusqlite::params![id, bundle_id, digest, now_ms.to_string(), state, reason, crate::now()],
                )?;
                super::audit::record(tx, "flow_run.enqueued", audit::Actor::scheduler(), "flow_run", &id)?;
                Ok(())
            })?;
            if state == "queued" { enqueued += 1 } else { refused += 1 }
        }
        conn.execute(
            "INSERT OR REPLACE INTO scheduler_ticks(at, due_found, enqueued, refused, error) \
             VALUES (?1,?2,?3,?4,NULL)",
            rusqlite::params![now_ms.to_string(), due_found, enqueued, refused],
        )?;
        Ok((due_found, enqueued, refused))
    }

    /// The one-time claim, on its own so it can be tested on its own.
    ///
    /// It was folded into `claim_and_run` at first, and a mutation sweep showed
    /// why that hid it: by the time a second `claim_and_run` ran, the first had
    /// finished and the row was no longer `queued`, so the test passed on the
    /// empty SELECT and never reached this guard. Deleting the guard left every
    /// test green. It is a separate function now, and the test below races two
    /// claims at one still-queued row.
    ///
    /// `true` means this caller owns the run. `false` means somebody else does,
    /// and the caller must dispatch nothing -- the UPDATE writes 0 rows because
    /// of `state='queued' AND claim_attempt_id IS NULL`, the shape migration 0013
    /// established for run steps.
    pub fn try_claim(
        conn: &Connection,
        run_id: &str,
        session_id: &str,
        now_ms: i64,
    ) -> CoreResult<bool> {
        let attempt = format!("att-{}-{}", session_id, now_ms);
        let claimed = conn.execute(
            "UPDATE flow_runs SET state='running', claim_attempt_id=?1, claim_session_id=?2, \
             claim_started_at=?3 WHERE id=?4 AND state='queued' AND claim_attempt_id IS NULL",
            rusqlite::params![attempt, session_id, crate::now(), run_id],
        )?;
        Ok(claimed == 1)
    }

    /// Claim exactly one queued run and execute its flow. The claim is the
    /// one-time shape migration 0013 established: an `UPDATE ... WHERE state =
    /// 'queued' AND claim_attempt_id IS NULL`, so a second concurrent claim
    /// writes 0 rows and is refused before any dispatch.
    pub fn claim_and_run(
        conn: &Connection,
        store_root: &Path,
        session_id: &str,
        now_ms: i64,
    ) -> CoreResult<Option<String>> {
        let next: Option<(String, String)> = conn
            .query_row(
                "SELECT id, bundle_digest FROM flow_runs WHERE state = 'queued' \
                 AND claim_attempt_id IS NULL ORDER BY due_at LIMIT 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let (run_id, digest) = match next {
            Some(v) => v,
            None => return Ok(None),
        };
        if !try_claim(conn, &run_id, session_id, now_ms)? {
            return Ok(None); // another claimer won; refused before dispatch
        }

        let bundle = match agent_bundle::verify(&store_root.join(&digest), now_ms / 1000) {
            Ok(b) => b,
            Err(r) => {
                finish(conn, &run_id, &digest, "refused", Some(r.as_str()), 0, &[])?;
                return Ok(Some(run_id));
            }
        };

        // Execute. Only `store` steps run at this head: a `model` step is a
        // governed turn and a `call` step needs the §3 enforcement point, and
        // both are refused rather than approximated.
        let mut touched: Vec<String> = Vec::new();
        let mut steps_run = 0u32;
        for step in &bundle.flow.steps {
            match step.kind {
                StepKind::Branch => { steps_run += 1; }
                StepKind::Store => {
                    let note = format!(
                        "{} · step {} · {}",
                        bundle.manifest.display_name,
                        step.id,
                        step.argument.clone().unwrap_or_default()
                    );
                    // `source` names the run, not a person: a reader of
                    // knowledge_notes can tell a produced-agent write from a
                    // human one without reading this file.
                    let id = super::knowledge::create(
                        conn,
                        crate::domain::NewKnowledgeNote {
                            title: note,
                            body: format!(
                                "Written by flow run {run_id} from bundle {digest}, step {}.",
                                step.id
                            ),
                            source: format!("flow_run:{run_id}"),
                            tags: "produced-agent".into(),
                        },
                        audit::Actor::run_executor(),
                    )?;
                    touched.push(format!("knowledge_notes/{}", id.id));
                    steps_run += 1;
                }
                StepKind::Call => {
                    // THE ENFORCEMENT POINT for the produced agent (design SS3.3,
                    // as corrected: this population has no spawn and no `Bash`,
                    // so the kernel namespace built for the build agent is not
                    // the mechanism here — the closed step vocabulary is).
                    let refusal = authorize_call(conn, &run_id, &bundle, step)?;
                    finish(conn, &run_id, &digest, "refused",
                           Some(refusal.as_str()), steps_run, &touched)?;
                    return Ok(Some(run_id));
                }
                _ => {
                    finish(conn, &run_id, &digest, "refused",
                           Some(Refusal::StepKindNotExecutable.as_str()), steps_run, &touched)?;
                    return Ok(Some(run_id));
                }
            }
        }
        finish(conn, &run_id, &digest, "done", None, steps_run, &touched)?;
        Ok(Some(run_id))
    }

    /// Decide one `call` step's destination against the bundle's grant, record
    /// the decision, and return the refusal the run finishes with.
    ///
    /// **Every path returns a refusal, including the authorized one.** That is
    /// not a hedge: nothing in this tree opens a connection, so an authorized
    /// call cannot happen, and pretending otherwise would be the approximation
    /// this slice exists to avoid. The two outcomes are told apart by their
    /// reason — `egress_not_granted` means the grant said no, and
    /// `call_transport_unimplemented` means the grant said YES and the
    /// transport is missing. A reader of `flow_runs.refusal_reason` can see
    /// which, and that difference is what makes the decision observable.
    fn authorize_call(
        conn: &Connection,
        run_id: &str,
        bundle: &agent_bundle::VerifiedBundle,
        step: &agent_bundle::Step,
    ) -> CoreResult<Refusal> {
        // A `call` step that names nothing is not a call to somewhere default.
        let call_ref = match step.call_ref.as_deref() {
            Some(name) => name,
            None => return Ok(Refusal::CallRefMissing),
        };

        // Rebuilt from what is on disk, not carried in memory: a grant that was
        // valid when it was written is judged again every time it is used.
        let allowlist = match bundle.grant.egress_allowlist(&bundle.digest) {
            Ok(allowlist) => allowlist,
            Err(refusal) => return Ok(refusal),
        };

        // ONE decision. The flow may name a ROW of the grant and may not name a
        // destination: a flow is the half a prompt can author, and a destination
        // stated there would be a destination stated in prose (design SS2.3
        // rule 6). Resolution and verdict happen together inside the authorizer
        // — split apart, the verdict could only ever agree with the lookup.
        let decision = allowlist.authorize_ref(call_ref);

        // §4: the step names SLOTS, never a value. Checked only when the
        // destination was allowed — a denied egress makes the credential
        // irrelevant, and asking about one anyway would put a slot name in the
        // record of a call that was never going to happen.
        //
        // `is_bound` and NOT `reference_of`: the only question here is whether
        // the operator has named a reference for the slot. The reference itself
        // is not read, because there is nothing to hand it to yet -- and no
        // VALUE exists on this side of the boundary to read at all.
        let slots = &step.requires.credential_slots;
        let mut missing: Option<&str> = None;
        if decision.allowed() {
            for slot in slots {
                if !crate::credentials::is_bound(conn, &bundle.digest, slot)? {
                    missing = Some(slot.as_str());
                    break;
                }
            }
        }
        // THREE outcomes a reviewer must be able to tell apart, in one record
        // beside the egress verdict: nothing was needed, the operator provided
        // it, or a declared slot has no value bound for THIS digest. The
        // refusal reason distinguishes the two that refuse; the payload
        // distinguishes all three. The slot NAME appears; a value never does,
        // and nothing on this path has read one.
        let credential_state = if !decision.allowed() {
            "not_reached"
        } else if slots.is_empty() {
            "none_required"
        } else if missing.is_some() {
            "absent"
        } else {
            "present"
        };

        record_egress_decision(
            conn, run_id, decision.event_type(),
            &format!(
                "{{\"outcome\":{},\"call_ref\":{},\"destination\":{},\"population\":{},\"grant\":{},\"credential\":{},\"slots\":{},\"missing_slot\":{},\"reason\":{}}}",
                json_string(if decision.allowed() { "allowed" } else { "denied" }),
                json_string(call_ref),
                json_string(&decision.matched.as_ref().map(|d| d.render()).unwrap_or_default()),
                json_string(decision.population.as_str()),
                json_string(decision.grant_id.as_str()),
                json_string(credential_state),
                json_string(&slots.join(",")),
                json_string(missing.unwrap_or("")),
                json_string(&decision.reason),
            ),
        )?;

        if !decision.allowed() {
            return Ok(Refusal::EgressNotGranted);
        }
        if missing.is_some() {
            return Ok(Refusal::CredentialBindingMissing);
        }
        Ok(Refusal::CallTransportUnimplemented)
    }

    /// One record per decision, allow and deny alike. `run_executor` because no
    /// person is present at a scheduled run, and the existing `store` arm names
    /// the same actor for the same reason.
    fn record_egress_decision(
        conn: &Connection,
        run_id: &str,
        event_type: &str,
        payload_json: &str,
    ) -> CoreResult<()> {
        super::audit::record_with_payload(
            conn, event_type, audit::Actor::run_executor(), "flow_run", run_id,
            Some(payload_json),
        )
    }

    /// Minimal JSON string escaping. `serde_json::to_string` would do it, but
    /// this keeps the payload's shape visible at the call site, where a reader
    /// is deciding whether the record says enough.
    fn json_string(value: &str) -> String {
        let mut out = String::with_capacity(value.len() + 2);
        out.push('"');
        for ch in value.chars() {
            match ch {
                '"' => out.push_str("\\\""),
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
                c => out.push(c),
            }
        }
        out.push('"');
        out
    }

    fn finish(
        conn: &Connection,
        run_id: &str,
        digest: &str,
        outcome: &str,
        reason: Option<&str>,
        steps_run: u32,
        touched: &[String],
    ) -> CoreResult<()> {
        let touched_json = serde_json::to_string(touched).unwrap_or_else(|_| "[]".into());
        let regime = enforcement_regime();
        super::atomic(conn, |tx| {
            tx.execute(
                "UPDATE flow_runs SET state=?1, refusal_reason=?2 WHERE id=?3",
                rusqlite::params![outcome, reason, run_id],
            )?;
            tx.execute(
                "INSERT OR REPLACE INTO flow_receipts(run_id, bundle_digest, enforcement_regime, \
                 steps_run, touched, outcome, written_at) VALUES (?1,?2,?3,?4,?5,?6,?7)",
                rusqlite::params![run_id, digest, regime, steps_run, touched_json, outcome, crate::now()],
            )?;
            super::audit::record(tx, "flow_run.finished", audit::Actor::run_executor(), "flow_run", run_id)?;
            Ok(())
        })
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use crate::agent_bundle::{BuildSpec, EgressEntry, Requires, Step, StepKind};

        fn spec(now_s: i64) -> BuildSpec {
            BuildSpec {
                bundle_id: "agt-t".into(), bundle_version: 1,
                display_name: "T".into(), built_for: "c".into(),
                built_at_epoch: now_s, grant_expires_at_epoch: now_s + 3600,
                egress: vec![],
                credential_slots: vec![],
                steps: vec![
                    Step { id: "a".into(), kind: StepKind::Store, verb: Some("knowledge_note".into()),
                           argument: Some("one".into()), call_ref: None,
                           requires: Requires { capabilities: vec!["WRITE_LOCAL".into()], credential_slots: vec![] },
                           next: Some("b".into()) },
                    Step { id: "b".into(), kind: StepKind::Store, verb: Some("knowledge_note".into()),
                           argument: Some("two".into()), call_ref: None,
                           requires: Requires { capabilities: vec!["WRITE_LOCAL".into()], credential_slots: vec![] },
                           next: None },
                ],
            }
        }

        /// A spec whose second step is a `call` naming `call_ref`, with the
        /// grant's egress table set to `granted`.
        fn call_spec_creds(
            now_s: i64, call_ref: Option<&str>, granted: &[(&str, &str)], slots: &[&str],
        ) -> BuildSpec {
            let mut s = call_spec(now_s, call_ref, granted);
            s.credential_slots = slots.iter().map(|x| x.to_string()).collect();
            s.steps[1].requires.credential_slots = slots.iter().map(|x| x.to_string()).collect();
            s
        }

        fn bind_slot(conn: &Connection, digest: &str, slot: &str, auth_ref: &str) {
            let entity = crate::credentials::approval_entity_id(digest, slot);
            let ap = super::super::approvals::create(
                conn, super::super::approvals::CREDENTIAL_BIND_ACTION_TYPE,
                "T", "A2", "medium",
                Some(super::super::approvals::CREDENTIAL_BINDING_ENTITY_TYPE), Some(&entity),
                "webview:test", "sess-test", &crate::id(),
                audit::Actor::local_operator(),
            ).unwrap();
            super::super::approvals::approve_confirmed(
                conn, &ap.id, super::super::approvals::NATIVE_CONFIRMER_PRINCIPAL, None,
                ap.nonce.as_deref().unwrap(), ap.request_digest.as_deref().unwrap(),
                audit::Actor::native_confirmer("native:test"),
            ).unwrap();
            crate::credentials::bind(conn, digest, slot, auth_ref, audit::Actor::local_operator()).unwrap();
        }

        fn call_spec(now_s: i64, call_ref: Option<&str>, granted: &[(&str, &str)]) -> BuildSpec {
            let mut s = spec(now_s);
            s.egress = granted
                .iter()
                .map(|(name, destination)| EgressEntry {
                    name: (*name).into(),
                    destination: (*destination).into(),
                })
                .collect();
            s.steps[1].kind = StepKind::Call;
            s.steps[1].verb = None;
            s.steps[1].argument = None;
            s.steps[1].call_ref = call_ref.map(|r| r.to_string());
            s
        }

        /// Every audit row this run wrote, as `(event_type, payload_json)`.
        fn egress_rows(conn: &Connection, run_id: &str) -> Vec<(String, String)> {
            let mut st = conn
                .prepare("SELECT event_type, COALESCE(payload_json,'') FROM audit_events \
                          WHERE entity_type='flow_run' AND entity_id=?1 AND event_type LIKE 'egress.%' \
                          ORDER BY created_at")
                .unwrap();
            let rows = st.query_map([run_id], |r| Ok((r.get(0)?, r.get(1)?))).unwrap();
            rows.map(|r| r.unwrap()).collect()
        }

        fn run_call(spec: &BuildSpec) -> (Connection, String) {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let digest = agent_bundle::build(dir.path(), spec).unwrap();
            register_and_arm(&conn, &digest);
            enqueue_due(&conn, 1_000_000_000, dir.path()).unwrap();
            let id = claim_and_run(&conn, dir.path(), "s1", 1_000_000_000).unwrap().unwrap();
            // the tempdir must outlive the run
            drop(dir);
            (conn, id)
        }

        fn fixture() -> (Connection, tempfile::TempDir, String) {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let now_ms = 1_000_000_000i64;
            let digest = agent_bundle::build(dir.path(), &spec(now_ms / 1000)).unwrap();
            register_and_arm(&conn, &digest);
            (conn, dir, digest)
        }

        /// Register a bundle and arm it THE ONLY WAY THE PRODUCT ALLOWS: with a
        /// natively confirmed grant. Mirrors `lib.rs`'s `arm` helper for
        /// automations, and for the same reason — nothing here reaches around
        /// the gate, because there is nothing to reach around it with.
        fn register_and_arm(conn: &Connection, digest: &str) {
            register(conn, digest, "agt-t", 1, "T").unwrap();
            let ap = super::super::approvals::create(
                conn,
                super::super::approvals::AGENT_BUNDLE_ARM_ACTION_TYPE,
                "T", "A2", "medium",
                Some(super::super::approvals::AGENT_BUNDLE_ENTITY_TYPE),
                Some(digest),
                "webview:test", "sess-test", &crate::id(),
                audit::Actor::local_operator(),
            )
            .unwrap();
            super::super::approvals::approve_confirmed(
                conn, &ap.id, super::super::approvals::NATIVE_CONFIRMER_PRINCIPAL, None,
                ap.nonce.as_deref().unwrap(), ap.request_digest.as_deref().unwrap(),
                audit::Actor::native_confirmer("native:test"),
            )
            .unwrap();
            set_active(conn, "agt-t", digest, 60_000, true, audit::Actor::local_operator()).unwrap();
        }

        fn state_of(conn: &Connection, id: &str) -> (String, Option<String>) {
            conn.query_row("SELECT state, refusal_reason FROM flow_runs WHERE id=?1", [id],
                           |r| Ok((r.get(0)?, r.get(1)?))).unwrap()
        }

        /// The tick enqueues, and the row says the scheduler's entry point did it.
        #[test]
        fn run_due_enqueues_and_names_itself_as_the_invoker() {
            let (conn, dir, _d) = fixture();
            let (found, enq, ref_) = enqueue_due(&conn, 1_000_000_000, dir.path()).unwrap();
            assert_eq!((found, enq, ref_), (1, 1, 0));
            let by: String = conn.query_row("SELECT invoked_by FROM flow_runs", [], |r| r.get(0)).unwrap();
            assert_eq!(by, "run_due");
        }

        /// A tick that found nothing still writes a row: "nothing was due" and
        /// "the tick did not run" must not look the same. This is the whole
        /// reason `scheduler_ticks` exists -- `lib.rs` discarded the result.
        #[test]
        fn a_tick_that_found_nothing_still_leaves_a_row() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            enqueue_due(&conn, 42, dir.path()).unwrap();
            let n: i64 = conn.query_row("SELECT count(*) FROM scheduler_ticks", [], |r| r.get(0)).unwrap();
            assert_eq!(n, 1);
        }

        /// A tampered bundle is REFUSED with a reason, never skipped. A skipped
        /// fire leaves no row, and "nothing happened" is exactly what the log
        /// must not say when something was tampered with.
        #[test]
        fn a_tampered_bundle_is_refused_with_a_reason_not_skipped() {
            let (conn, dir, digest) = fixture();
            let flow = dir.path().join(&digest).join("flow.json");
            let mut b = std::fs::read(&flow).unwrap();
            b[0] = b' ';
            std::fs::write(&flow, &b).unwrap();
            let (found, enq, refused) = enqueue_due(&conn, 1_000_000_000, dir.path()).unwrap();
            assert_eq!((found, enq, refused), (1, 0, 1));
            let (state, reason): (String, Option<String>) = conn
                .query_row("SELECT state, refusal_reason FROM flow_runs", [], |r| Ok((r.get(0)?, r.get(1)?)))
                .unwrap();
            assert_eq!(state, "refused");
            assert_eq!(reason.as_deref(), Some("file_hash_mismatch"));
        }

        /// The claim is one-time: a second claimer writes 0 rows and is refused
        /// before any dispatch. Reused from migration 0013 rather than invented.
        ///
        /// This races two claims at ONE STILL-QUEUED row on purpose. The earlier
        /// version called `claim_and_run` twice, which passed for the wrong
        /// reason -- the first call finished the run, so the second found no
        /// queued row and never reached the guard at all. Deleting the guard
        /// left it green.
        #[test]
        fn a_second_claim_of_the_same_queued_run_gets_nothing() {
            let (conn, dir, _d) = fixture();
            enqueue_due(&conn, 1_000_000_000, dir.path()).unwrap();
            let id: String = conn
                .query_row("SELECT id FROM flow_runs WHERE state='queued'", [], |r| r.get(0))
                .unwrap();
            assert!(try_claim(&conn, &id, "s1", 1_000_000_000).unwrap(), "the first claim owns it");
            assert!(!try_claim(&conn, &id, "s2", 1_000_000_001).unwrap(),
                    "a second claim on a claimed run must write 0 rows");
            let owner: String = conn
                .query_row("SELECT claim_session_id FROM flow_runs WHERE id=?1", [&id], |r| r.get(0))
                .unwrap();
            assert_eq!(owner, "s1", "the loser must not overwrite the winner's claim");
        }

        /// And a claimed run is not dispatched by the loser either.
        #[test]
        fn claim_and_run_declines_a_run_somebody_else_claimed() {
            let (conn, dir, _d) = fixture();
            enqueue_due(&conn, 1_000_000_000, dir.path()).unwrap();
            let id: String = conn
                .query_row("SELECT id FROM flow_runs WHERE state='queued'", [], |r| r.get(0))
                .unwrap();
            assert!(try_claim(&conn, &id, "other", 1_000_000_000).unwrap());
            assert!(claim_and_run(&conn, dir.path(), "s2", 1_000_000_001).unwrap().is_none());
        }

        /// The run does real, local work and the receipt says what it touched
        /// and under which regime.
        #[test]
        fn a_finished_run_leaves_a_receipt_naming_the_regime_and_what_it_touched() {
            let (conn, dir, _d) = fixture();
            enqueue_due(&conn, 1_000_000_000, dir.path()).unwrap();
            let id = claim_and_run(&conn, dir.path(), "s1", 1_000_000_000).unwrap().unwrap();
            assert_eq!(state_of(&conn, &id).0, "done");
            let (regime, steps, touched): (String, i64, String) = conn
                .query_row("SELECT enforcement_regime, steps_run, touched FROM flow_receipts WHERE run_id=?1",
                           [&id], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
                .unwrap();
            assert!(!regime.is_empty());
            assert_eq!(steps, 2);
            let touched: Vec<String> = serde_json::from_str(&touched).unwrap();
            assert_eq!(touched.len(), 2, "both store steps must be recorded");
            // The write names the run, not a person: a reader of knowledge_notes
            // can tell a produced-agent write from a human one.
            let src: String = conn.query_row("SELECT source FROM knowledge_notes LIMIT 1", [], |r| r.get(0)).unwrap();
            assert_eq!(src, format!("flow_run:{id}"));
        }

        // ---- the tick DISPATCHES (T-058) ----------------------------------

        /// `BROPS_AGENT_STORE` is process-global, so the tests that drive
        /// `run_due` take a lock. Without it they race each other and the
        /// failure looks like a scheduler bug rather than a test bug.
        static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

        fn tick(conn: &Connection, store: &std::path::Path, now_ms: i64) {
            let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
            std::env::set_var("BROPS_AGENT_STORE", store);
            super::super::automations::run_due(conn, now_ms).unwrap();
            std::env::remove_var("BROPS_AGENT_STORE");
        }

        fn arm_grant(conn: &Connection, bundle_id: &str, digest: &str) {
            let ap = super::super::approvals::create(
                conn, super::super::approvals::AGENT_BUNDLE_ARM_ACTION_TYPE,
                "T", "A2", "medium",
                Some(super::super::approvals::AGENT_BUNDLE_ENTITY_TYPE), Some(digest),
                "webview:test", "sess-test", &crate::id(),
                audit::Actor::local_operator(),
            ).unwrap();
            super::super::approvals::approve_confirmed(
                conn, &ap.id, super::super::approvals::NATIVE_CONFIRMER_PRINCIPAL, None,
                ap.nonce.as_deref().unwrap(), ap.request_digest.as_deref().unwrap(),
                audit::Actor::native_confirmer("native:test"),
            ).unwrap();
            set_active(conn, bundle_id, digest, 60_000, true, audit::Actor::local_operator()).unwrap();
        }

        /// BORN DISARMED. Registering a bundle records it and arms nothing, so
        /// the tick resolves no trigger to it and dispatches nothing.
        ///
        /// Before T-058 `register` wrote `agent_bundle_active` in the same call
        /// and hardcoded `state = 'approved'`: building an agent and arming it
        /// were one act. That was survivable only while the tick performed
        /// nothing. It dispatches now.
        #[test]
        fn a_registered_bundle_is_not_armed_and_the_tick_ignores_it() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let digest = agent_bundle::build(dir.path(), &spec(1_000_000)).unwrap();
            register(&conn, &digest, "agt-t", 1, "T").unwrap();

            let active: i64 = conn
                .query_row("SELECT COUNT(*) FROM agent_bundle_active", [], |r| r.get(0)).unwrap();
            assert_eq!(active, 0, "registering must not arm");
            let state: String = conn
                .query_row("SELECT state FROM agent_bundles WHERE bundle_digest=?1", [&digest], |r| r.get(0))
                .unwrap();
            assert_eq!(state, "built", "nothing here decides a bundle is approved");

            tick(&conn, dir.path(), 1_000_000_000);
            let runs: i64 = conn.query_row("SELECT COUNT(*) FROM flow_runs", [], |r| r.get(0)).unwrap();
            assert_eq!(runs, 0, "an unarmed bundle must not be dispatched");
        }

        /// Arming without a natively confirmed grant is refused. A gate with a
        /// one-call way around it is not a gate.
        #[test]
        fn arming_without_a_confirmed_grant_is_refused() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let digest = agent_bundle::build(dir.path(), &spec(1_000_000)).unwrap();
            register(&conn, &digest, "agt-t", 1, "T").unwrap();
            let refused = set_active(&conn, "agt-t", &digest, 60_000, true, audit::Actor::local_operator());
            assert!(refused.is_err(), "arming must require a grant");
            let active: i64 = conn
                .query_row("SELECT COUNT(*) FROM agent_bundle_active", [], |r| r.get(0)).unwrap();
            assert_eq!(active, 0);
        }

        /// DISARMING is not gated, and must never be: it is the only way to stop
        /// a running agent, and an approval ceremony in front of the stop button
        /// is a denial of service on the operator's own safety control.
        #[test]
        fn disarming_needs_no_grant() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let digest = agent_bundle::build(dir.path(), &spec(1_000_000)).unwrap();
            register_and_arm(&conn, &digest);
            set_active(&conn, "agt-t", &digest, 60_000, false, audit::Actor::local_operator()).unwrap();
            let active: i64 = conn
                .query_row("SELECT COUNT(*) FROM agent_bundle_active", [], |r| r.get(0)).unwrap();
            assert_eq!(active, 0, "the stop button must work with no ceremony");
        }

        /// THE POINT OF T-058: the tick RUNS an armed bundle. Before this it
        /// enqueued and performed nothing, so `claim_and_run` had exactly one
        /// non-test caller -- a CI demo binary -- and every piece behind it was
        /// unreachable from the product.
        #[test]
        fn the_tick_dispatches_an_armed_bundle_to_completion() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let digest = agent_bundle::build(dir.path(), &spec(1_000_000)).unwrap();
            register_and_arm(&conn, &digest);

            tick(&conn, dir.path(), 1_000_000_000);

            let (id, state): (String, String) = conn
                .query_row("SELECT id, state FROM flow_runs", [], |r| Ok((r.get(0)?, r.get(1)?)))
                .unwrap();
            assert_eq!(state, "done", "the tick must RUN it, not merely queue it");
            let invoked: String = conn
                .query_row("SELECT invoked_by FROM flow_runs WHERE id=?1", [&id], |r| r.get(0)).unwrap();
            assert_eq!(invoked, "run_due");
        }

        /// Constraint 3: a run the tick performed and no receipt describes is
        /// worse than a run that did not happen.
        #[test]
        fn every_dispatched_run_leaves_a_receipt_naming_the_regime() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let digest = agent_bundle::build(dir.path(), &spec(1_000_000)).unwrap();
            register_and_arm(&conn, &digest);
            tick(&conn, dir.path(), 1_000_000_000);

            let (run_id, regime, outcome): (String, String, String) = conn
                .query_row("SELECT run_id, enforcement_regime, outcome FROM flow_receipts",
                           [], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
                .unwrap();
            assert!(!regime.is_empty());
            assert_eq!(outcome, "done");
            let runs: i64 = conn
                .query_row("SELECT COUNT(*) FROM flow_runs WHERE id=?1", [&run_id], |r| r.get(0)).unwrap();
            assert_eq!(runs, 1, "the receipt must describe a run that exists");
        }

        /// Constraint 2: the tick gains a CALLER, not a capability. A `call`
        /// step dispatched by the scheduler is refused exactly as it is when a
        /// test drives the runner by hand, and the refusal reaches the receipt.
        #[test]
        fn a_dispatched_call_step_is_still_refused() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let s = call_spec(1_000_000, Some("evil"), &[("slack-post", "https://slack.example.com")]);
            let digest = agent_bundle::build(dir.path(), &s).unwrap();
            register_and_arm(&conn, &digest);
            tick(&conn, dir.path(), 1_000_000_000);

            let (state, reason): (String, Option<String>) = conn
                .query_row("SELECT state, refusal_reason FROM flow_runs", [], |r| Ok((r.get(0)?, r.get(1)?)))
                .unwrap();
            assert_eq!((state.as_str(), reason.as_deref()),
                       ("refused", Some("egress_not_granted")));
            let outcome: String = conn
                .query_row("SELECT outcome FROM flow_receipts", [], |r| r.get(0)).unwrap();
            assert_eq!(outcome, "refused", "a refused run is still described by a receipt");
        }

        /// And a `model` step, the other refused kind.
        #[test]
        fn a_dispatched_model_step_is_still_refused() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let mut s = spec(1_000_000);
            s.steps[1].kind = StepKind::Model;
            let digest = agent_bundle::build(dir.path(), &s).unwrap();
            register_and_arm(&conn, &digest);
            tick(&conn, dir.path(), 1_000_000_000);
            let (state, reason): (String, Option<String>) = conn
                .query_row("SELECT state, refusal_reason FROM flow_runs", [], |r| Ok((r.get(0)?, r.get(1)?)))
                .unwrap();
            assert_eq!((state.as_str(), reason.as_deref()),
                       ("refused", Some("step_kind_not_executable")));
        }

        /// Constraint 4, the bound: one tick may not become unbounded work.
        #[test]
        fn one_tick_dispatches_at_most_the_bound() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let n = MAX_DISPATCH_PER_TICK + 2;
            for i in 0..n {
                let mut sp = spec(1_000_000);
                sp.bundle_id = format!("agt-{i}");
                let digest = agent_bundle::build(dir.path(), &sp).unwrap();
                register(&conn, &digest, &sp.bundle_id, 1, "T").unwrap();
                arm_grant(&conn, &sp.bundle_id, &digest);
            }
            tick(&conn, dir.path(), 1_000_000_000);
            let finished: i64 = conn
                .query_row("SELECT COUNT(*) FROM flow_runs WHERE state != 'queued'", [], |r| r.get(0))
                .unwrap();
            assert_eq!(finished as usize, MAX_DISPATCH_PER_TICK,
                       "one tick must dispatch the bound and no more");
            let queued: i64 = conn
                .query_row("SELECT COUNT(*) FROM flow_runs WHERE state = 'queued'", [], |r| r.get(0))
                .unwrap();
            assert_eq!(queued as usize, n - MAX_DISPATCH_PER_TICK, "the rest waits for the next tick");
        }

        // ---- SS4: which slot, never the value -----------------------------

        /// A declared slot with NO value bound for this digest is refused, by a
        /// name of its own -- not `call_transport_unimplemented`, which is what
        /// it would say if the credential were not being checked at all.
        #[test]
        fn a_declared_slot_with_no_binding_is_refused_by_its_own_name() {
            let sp = call_spec_creds(1_000_000, Some("slack-post"),
                                     &[("slack-post", "https://slack.example.com")], &["slack_bot"]);
            let (conn, id) = run_call(&sp);
            assert_eq!(state_of(&conn, &id),
                       ("refused".into(), Some("credential_binding_missing".into())));
            let rows = egress_rows(&conn, &id);
            assert_eq!(rows.len(), 1);
            assert!(rows[0].1.contains("\"credential\":\"absent\""), "{}", rows[0].1);
            assert!(rows[0].1.contains("slack_bot"), "the record must name the SLOT: {}", rows[0].1);
        }

        /// Bound: the grant said yes, the operator named a REFERENCE for the
        /// slot, and the call still does not happen -- for want of a transport,
        /// by that name. The record says `present` and carries neither a value
        /// (none exists on this side) nor the reference.
        #[test]
        fn a_bound_slot_reaches_the_transport_refusal_and_leaks_no_reference() {
            let sp = call_spec_creds(1_000_000, Some("slack-post"),
                                     &[("slack-post", "https://slack.example.com")], &["slack_bot"]);
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let digest = agent_bundle::build(dir.path(), &sp).unwrap();
            register_and_arm(&conn, &digest);
            bind_slot(&conn, &digest, "slack_bot", "engine:slack/bot-token");
            tick(&conn, dir.path(), 1_000_000_000);

            let (state, reason): (String, Option<String>) = conn
                .query_row("SELECT state, refusal_reason FROM flow_runs", [], |r| Ok((r.get(0)?, r.get(1)?)))
                .unwrap();
            assert_eq!((state.as_str(), reason.as_deref()),
                       ("refused", Some("call_transport_unimplemented")));

            let payload: String = conn
                .query_row("SELECT COALESCE(payload_json,'') FROM audit_events WHERE event_type='egress.allowed'",
                           [], |r| r.get(0)).unwrap();
            assert!(payload.contains("\"credential\":\"present\""), "{payload}");
            assert!(payload.contains("slack_bot"), "the SLOT is named: {payload}");
            assert!(!payload.contains("bot-token"),
                    "the REFERENCE must never reach a record: {payload}");

            // and nowhere else either
            let leaks: i64 = conn.query_row(
                "SELECT COUNT(*) FROM audit_events WHERE COALESCE(payload_json,'') LIKE '%bot-token%'",
                [], |r| r.get(0)).unwrap();
            assert_eq!(leaks, 0);
            let receipt_leaks: i64 = conn.query_row(
                "SELECT COUNT(*) FROM flow_receipts WHERE touched LIKE '%bot-token%'", [], |r| r.get(0)).unwrap();
            assert_eq!(receipt_leaks, 0);
            let run_leaks: i64 = conn.query_row(
                "SELECT COUNT(*) FROM flow_runs WHERE COALESCE(refusal_reason,'') LIKE '%bot-token%'",
                [], |r| r.get(0)).unwrap();
            assert_eq!(run_leaks, 0);
        }

        /// The third outcome: nothing was needed. Distinct in the record from
        /// "the operator named a reference", even though both refuse for the same
        /// reason -- the reason distinguishes the refusal, the payload
        /// distinguishes the credential state.
        #[test]
        fn a_call_needing_no_credential_says_none_required() {
            let sp = call_spec(1_000_000, Some("slack-post"),
                               &[("slack-post", "https://slack.example.com")]);
            let (conn, id) = run_call(&sp);
            assert_eq!(state_of(&conn, &id),
                       ("refused".into(), Some("call_transport_unimplemented".into())));
            let rows = egress_rows(&conn, &id);
            assert!(rows[0].1.contains("\"credential\":\"none_required\""), "{}", rows[0].1);
        }

        /// A denied destination must not put a slot name in the record of a
        /// call that was never going to happen.
        #[test]
        fn a_denied_destination_does_not_reach_the_credential_check() {
            let sp = call_spec_creds(1_000_000, Some("evil"),
                                     &[("slack-post", "https://slack.example.com")], &["slack_bot"]);
            let (conn, id) = run_call(&sp);
            assert_eq!(state_of(&conn, &id), ("refused".into(), Some("egress_not_granted".into())));
            let rows = egress_rows(&conn, &id);
            assert!(rows[0].1.contains("\"credential\":\"not_reached\""), "{}", rows[0].1);
            // and the slot NAME must not appear at all. A mutation sweep found
            // this: dropping the `decision.allowed()` guard left every other
            // assertion green, because `credential_state` is computed from the
            // egress verdict first -- but the loop still ran and would have put
            // the slot into `missing_slot`, in the record of a call that was
            // never going to happen.
            assert!(rows[0].1.contains("\"missing_slot\":\"\""),
                    "a denied call must assert nothing about a credential: {}", rows[0].1);
        }

        /// A slot the GRANT does not declare is a different fact, refused
        /// earlier and by a different name -- at LOAD time, so the bundle never
        /// runs at all. "Never allowed one" and "not provided one" must stay
        /// distinguishable.
        #[test]
        fn a_slot_the_grant_does_not_declare_refuses_the_bundle_at_load() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let mut sp = call_spec(1_000_000, Some("slack-post"),
                                   &[("slack-post", "https://slack.example.com")]);
            // the STEP requires it; the grant declares nothing
            sp.steps[1].requires.credential_slots = vec!["slack_bot".into()];
            let digest = agent_bundle::build(dir.path(), &sp).unwrap();
            register_and_arm(&conn, &digest);
            let (_found, enqueued, refused) = enqueue_due(&conn, 1_000_000_000, dir.path()).unwrap();
            assert_eq!((enqueued, refused), (0, 1), "the bundle must be refused before it runs");
            let reason: Option<String> = conn
                .query_row("SELECT refusal_reason FROM flow_runs", [], |r| r.get(0)).unwrap();
            assert_eq!(reason.as_deref(), Some("credential_slot_unbound"));
        }

        // ---- the produced agent's egress enforcement (design SS3.3) --------

        /// THE RED DIRECTION. A `call` step naming a destination the grant does
        /// not hold is refused, and the refusal is `egress_not_granted` -- not
        /// `step_kind_not_executable`, which is what it would say if the
        /// authorizer were not being asked at all.
        #[test]
        fn a_call_to_a_destination_the_grant_does_not_name_is_refused() {
            let s = call_spec(1_000_000, Some("evil"), &[("slack-post", "https://slack.example.com")]);
            let (conn, id) = run_call(&s);
            assert_eq!(
                state_of(&conn, &id),
                ("refused".into(), Some("egress_not_granted".into()))
            );
            let rows = egress_rows(&conn, &id);
            assert_eq!(rows.len(), 1, "one record per decision");
            assert_eq!(rows[0].0, "egress.denied");
            assert!(rows[0].1.contains("\"evil\""), "the record must name what was asked for: {}", rows[0].1);
        }

        /// THE GREEN DIRECTION, so the refusal above is not a check that cannot
        /// pass. The grant says yes and the call still does not happen -- but by
        /// a DIFFERENT name, which is the only way a reader can tell an
        /// authorized call from a denied one at this head.
        #[test]
        fn an_authorized_call_is_refused_by_a_different_name_than_a_denied_one() {
            let s = call_spec(1_000_000, Some("slack-post"), &[("slack-post", "https://slack.example.com")]);
            let (conn, id) = run_call(&s);
            assert_eq!(
                state_of(&conn, &id),
                ("refused".into(), Some("call_transport_unimplemented".into()))
            );
            let rows = egress_rows(&conn, &id);
            assert_eq!(rows.len(), 1);
            assert_eq!(rows[0].0, "egress.allowed");
            assert!(rows[0].1.contains("slack.example.com:443"), "payload: {}", rows[0].1);
            assert!(rows[0].1.contains("\"produced\""), "the record names the population: {}", rows[0].1);
        }

        /// A `call` step that names nothing is not a call to somewhere default.
        #[test]
        fn a_call_step_naming_no_ref_is_refused_by_its_own_name() {
            let s = call_spec(1_000_000, None, &[("slack-post", "https://slack.example.com")]);
            let (conn, id) = run_call(&s);
            assert_eq!(
                state_of(&conn, &id),
                ("refused".into(), Some("call_ref_missing".into()))
            );
            assert!(egress_rows(&conn, &id).is_empty(), "nothing was decided, so nothing is recorded");
        }

        /// An empty egress table admits nothing. This is the state every grant
        /// `for_local_only` writes, and it must not be a hole.
        #[test]
        fn an_empty_egress_table_admits_nothing() {
            let s = call_spec(1_000_000, Some("anything"), &[]);
            let (conn, id) = run_call(&s);
            assert_eq!(
                state_of(&conn, &id),
                ("refused".into(), Some("egress_not_granted".into()))
            );
        }

        /// A step kind this head cannot execute is refused, not approximated.
        #[test]
        fn a_model_step_is_refused_because_a_governed_turn_is_not_available() {
            let conn = crate::db::open(":memory:").unwrap();
            let dir = tempfile::tempdir().unwrap();
            let mut s = spec(1_000_000);
            s.steps[1].kind = StepKind::Model;
            let digest = agent_bundle::build(dir.path(), &s).unwrap();
            register_and_arm(&conn, &digest);
            enqueue_due(&conn, 1_000_000_000, dir.path()).unwrap();
            let id = claim_and_run(&conn, dir.path(), "s1", 1_000_000_000).unwrap().unwrap();
            assert_eq!(state_of(&conn, &id), ("refused".into(), Some("step_kind_not_executable".into())));
        }
    }
}

pub mod integrations {
    use super::*;

    /// Length bounds for an `auth_ref`, mirroring the schema-0022 CHECK exactly. Long
    /// enough to name a vault path, far too short to hold a key blob.
    const AUTH_REF_MIN_LEN: usize = 3;
    const AUTH_REF_MAX_LEN: usize = 160;

    /// The characters a reference may contain — mirroring the schema-0022 CHECK. Excludes
    /// every whitespace character (so a multi-line PEM cannot be stored) and `=` (so
    /// padded base64 material is refused).
    fn is_auth_ref_char(c: char) -> bool {
        c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | ':' | '/' | '@' | '+' | '-')
    }

    /// Prefixes that begin recognisable KEY MATERIAL. Checked against every
    /// `:`-delimited segment after the scheme, case-sensitively, mirroring the
    /// schema-0022 GLOBs.
    ///
    /// This list is a FLOOR, not a filter. It catches a careless paste of a token whose
    /// vendor happens to be on it. It cannot catch a vendor that is not, and it cannot
    /// catch a secret that simply looks like a word — see `normalize_auth_ref`.
    const KEY_MATERIAL_PREFIXES: &[&str] = &[
        "eyJ",                                                  // JWT
        "sk-", "sk_", "pk_", "rk_",                             // OpenAI/Anthropic, Stripe
        "ghp_", "gho_", "ghs_", "ghr_", "ghu_", "github_pat_",  // GitHub
        "glpat-",                                               // GitLab
        "xoxa-", "xoxb-", "xoxc-", "xoxe-", "xoxo-", "xoxp-", "xoxr-", "xoxs-", // Slack
        "AKIA", "ASIA",                                         // AWS
        "AIza", "ya29.",                                        // Google
        "npm_", "shpat_",                                       // npm, Shopify
        "-----BEGIN",                                           // PEM armor
    ];

    /// A rejection that NEVER echoes what was rejected.
    ///
    /// `CoreError::Invalid` renders its `value` into the message, and that message travels
    /// out through the Tauri command layer to the renderer and into logs. If the caller
    /// just handed us a password by mistake, repeating it back is the leak this column
    /// exists to avoid — so the reason travels and the text does not.
    fn refuse_auth_ref(reason: &'static str) -> CoreError {
        CoreError::Invalid { field: "auth_ref", value: format!("<withheld> ({reason})") }
    }

    /// Turn caller input into the value that may be stored, or refuse it.
    ///
    /// `None`, empty, or whitespace-only all mean CLEAR — the record goes back to holding
    /// no reference. Everything else must positively look like `scheme:locator` with a
    /// scheme from `AUTH_REF_SCHEMES`, within the length bound, in the reference alphabet,
    /// and carrying no segment that begins with recognisable key material. This is the
    /// same rule the schema-0022 CHECK states in SQL, stated a second time here so a
    /// refusal reaches the caller as an explanation rather than as a constraint violation.
    ///
    /// WHAT THIS CANNOT DO, stated plainly: it cannot tell a reference from a secret.
    /// `engine:hunter2` is a well-formed reference and also a password; `engine:9f2c…`
    /// is a well-formed reference and also forty characters of entropy. Shape is all that
    /// is checkable here. What actually protects the boundary is this function refusing
    /// anything not positively recognisable as a reference, plus the standing rule that a
    /// credential must never arrive at this process at all.
    /// `pub(crate)` since §4: `credentials::bind` refuses anything this does not
    /// recognise as a reference, calling the SAME function rather than a second
    /// copy of the rule. Two copies of one rule is two things to drift.
    pub(crate) fn normalize_auth_ref(raw: Option<&str>) -> CoreResult<Option<String>> {
        let value = match raw.map(str::trim) {
            None | Some("") => return Ok(None),
            Some(v) => v,
        };
        if !value.chars().all(is_auth_ref_char) {
            return Err(refuse_auth_ref("contains characters no reference uses"));
        }
        // ASCII-only by the check above, so byte length is character length.
        if value.len() < AUTH_REF_MIN_LEN || value.len() > AUTH_REF_MAX_LEN {
            return Err(refuse_auth_ref("length is outside 3..160"));
        }
        let (scheme, locator) = match value.split_once(':') {
            Some(parts) => parts,
            None => return Err(refuse_auth_ref("must be scheme:locator")),
        };
        if !is_valid(scheme, AUTH_REF_SCHEMES) {
            return Err(refuse_auth_ref("unrecognised reference scheme"));
        }
        if locator.is_empty() {
            return Err(refuse_auth_ref("locator after the scheme is empty"));
        }
        for segment in value.split(':').skip(1) {
            if KEY_MATERIAL_PREFIXES.iter().any(|p| segment.starts_with(p)) {
                return Err(refuse_auth_ref("looks like credential material, not a reference"));
            }
        }
        Ok(Some(value.to_string()))
    }

    /// Read the stored reference as the record's honest state.
    ///
    /// SQL NULL and any string that is empty or whitespace-only both collapse to `None` —
    /// "no reference recorded". The empty-string collapse matters because the database
    /// file is not ours alone: something that opened it out of band could have written
    /// `''`, and an empty string surfacing as a *present* reference would make the
    /// Integrations page claim a custody fact it cannot support.
    fn read_auth_ref(r: &Row) -> rusqlite::Result<Option<String>> {
        let raw: Option<String> = r.get("auth_ref")?;
        Ok(raw.filter(|v| !v.trim().is_empty()))
    }

    fn map(r: &Row) -> rusqlite::Result<Integration> {
        Ok(Integration {
            id: r.get("id")?,
            name: r.get("name")?,
            provider: r.get("provider")?,
            status: r.get("status")?,
            auth_ref: read_auth_ref(r)?,
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
    pub fn set_status(conn: &Connection, id: &str, status: &str, actor: audit::Actor<'_>) -> CoreResult<Integration> {
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
            // T-052 tier-X gate: verified and spent inside this transaction, so the
            // status change and the grant it consumed commit or roll back together.
            super::approvals::require_and_consume(
                tx,
                id,
                super::approvals::INTEGRATION_ENTITY_TYPE,
                super::approvals::INTEGRATION_STATUS_ACTION_TYPE,
            )?;
            super::audit::record(tx, "integration.status_changed", actor, "integration", id)?;
            Ok(())
        })?;
        get(conn, id)
    }

    /// Record (or clear) the REFERENCE naming where this connector's credential lives.
    ///
    /// Exactly like `set_status`, this records the desired state; it does not itself reach
    /// any external service, and it does not resolve, fetch, validate, or in any way touch
    /// the secret the reference names — that secret belongs to the engine or the operator,
    /// on the far side of the Phase-9 trust boundary, and must never arrive here.
    ///
    /// `auth_ref = None` (or an empty/whitespace string) clears the reference; the record
    /// returns to "no reference", which is a truthful state and not an error. Anything
    /// else is validated by `normalize_auth_ref` and refused unless it is positively
    /// recognisable as a reference — where it is unclear whether a value is a reference or
    /// a secret, it is treated as a secret and rejected.
    ///
    /// Setting a reference proves nothing about the connector: no probe has run, nothing
    /// was contacted, and the composite verdict is untouched.
    ///
    /// The audit event records only THAT a reference was set or cleared, and for which
    /// connector. The reference text is never written to the audit log, never logged, and
    /// never included in an error.
    pub fn set_auth_ref(
        conn: &Connection,
        id: &str,
        auth_ref: Option<&str>,
        actor: audit::Actor<'_>,
    ) -> CoreResult<Integration> {
        let normalized = normalize_auth_ref(auth_ref)?;
        let event = if normalized.is_some() {
            "integration.auth_ref_set"
        } else {
            "integration.auth_ref_cleared"
        };
        super::atomic(conn, |tx| {
            let changed = tx.execute(
                "UPDATE integrations SET auth_ref = ?1, updated_at = ?2 WHERE id = ?3",
                rusqlite::params![normalized, now(), id],
            )?;
            if changed == 0 {
                return Err(CoreError::NotFound(id.to_string()));
            }
            // T-052 tier-X gate. It covers CLEARING the reference too: dropping a
            // connector's credential locator is as much an execution-tier act as
            // setting one, and an ungated clear would be a silent way to break a
            // connector.
            super::approvals::require_and_consume(
                tx,
                id,
                super::approvals::INTEGRATION_ENTITY_TYPE,
                super::approvals::INTEGRATION_AUTH_REF_ACTION_TYPE,
            )?;
            super::audit::record(tx, event, actor, "integration", id)?;
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
            ("conversations", "Conversations", "SELECT COUNT(*) FROM conversations"),
            ("messages", "Messages", "SELECT COUNT(*) FROM messages"),
            ("decisions", "Decisions", "SELECT COUNT(*) FROM decisions"),
            ("integrations", "Integrations", "SELECT COUNT(*) FROM integrations"),
            ("library_items", "Library items", "SELECT COUNT(*) FROM library_items"),
            ("research_items", "Research items", "SELECT COUNT(*) FROM research_items"),
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
        let payload: Option<String> = r.get("payload_json")?;
        Ok(ActivityEvent {
            id: r.get("id")?,
            event_type: r.get("event_type")?,
            actor_type: r.get("actor_type")?,
            actor_id: r.get("actor_id")?,
            entity_type: r.get("entity_type")?,
            entity_id: r.get("entity_id")?,
            // The mark travels to the surface. Marking the row and dropping it
            // here is the defect `actor_type` already carries a paragraph about,
            // and BOTH mappers carry it — `activity::map` and
            // `security::map_event` — or one surface tells the truth and the
            // other does not.
            source: crate::repo::activity::source_of(payload.as_deref()),
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

        let p1 = projects::create(conn, NewProject { name: "BroPS Desktop Foundation".into(), description: "React + Tauri app shell and core runtime.".into(), priority: "high".into(), workspace_id: None }, audit::Actor::seed())?;
        let p2 = projects::create(conn, NewProject { name: "Localization HY/EN/RU".into(), description: "Trilingual runtime parity.".into(), priority: "high".into(), workspace_id: None }, audit::Actor::seed())?;
        projects::set_status(conn, &p1.id, "active", audit::Actor::seed())?;

        tasks::create(conn, NewTask { project_id: Some(p1.id.clone()), title: "Implement app shell + routing".into(), description: "".into(), priority: "high".into(), assigned_agent_id: None }, audit::Actor::seed())?;
        let t2 = tasks::create(conn, NewTask { project_id: Some(p1.id.clone()), title: "Command palette (Ctrl/Cmd+K)".into(), description: "".into(), priority: "normal".into(), assigned_agent_id: None }, audit::Actor::seed())?;
        tasks::set_status(conn, &t2.id, "active", audit::Actor::seed())?;
        tasks::create(conn, NewTask { project_id: Some(p2.id.clone()), title: "Russian dictionary parity".into(), description: "".into(), priority: "high".into(), assigned_agent_id: None }, audit::Actor::seed())?;

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

        decisions::create(conn, "Trilingual product scope (HY/EN/RU)", "gev", "Newest explicit decision supersedes bilingual wording (D-009).", audit::Actor::seed())?;
        decisions::create(conn, "Foundation v1 is Locked", "gev", "Reviewed, canonicalized, Phase 1 UX added (D-010).", audit::Actor::seed())?;

        let direct = chat::create_conversation(conn, "direct", "Bro", audit::Actor::seed())?;
        chat::post_message(conn, NewMessage { conversation_id: direct.id.clone(), role: "user".into(), author: "gev".into(), body: "Bro, where does the desktop build stand?".into() })?;
        chat::post_message(conn, NewMessage { conversation_id: direct.id.clone(), role: "agent".into(), author: "Bro".into(), body: "Data core is green and CRUD is wired to real SQLite. Chat is now persisted too.".into() })?;

        let room = chat::create_conversation(conn, "group", "Foundation room", audit::Actor::seed())?;
        chat::post_message(conn, NewMessage { conversation_id: room.id.clone(), role: "agent".into(), author: "Mason".into(), body: "Schema reached v3 — conversations and messages added.".into() })?;
        chat::post_message(conn, NewMessage { conversation_id: room.id.clone(), role: "agent".into(), author: "Probe".into(), body: "Chat repository covered by unit tests.".into() })?;

        knowledge::create(conn, NewKnowledgeNote { title: "Typed IPC boundary".into(), body: "React reaches SQLite only through #[tauri::command]s; no raw SQL crosses the boundary.".into(), source: "docs/architecture".into(), tags: "architecture,ipc".into() }, audit::Actor::seed())?;
        knowledge::create(conn, NewKnowledgeNote { title: "Forward-only migrations".into(), body: "Schema advances one numbered migration at a time; runner is idempotent.".into(), source: "src-tauri/core/db.rs".into(), tags: "sqlite,migrations".into() }, audit::Actor::seed())?;

        let m = memory::create(conn, NewMemoryEntry { scope: "global".into(), kind: "preference".into(), content: "Respond in Armenian; work only in menqstudio/BroPS.".into() }, audit::Actor::seed())?;
        memory::set_pinned(conn, &m.id, true)?;
        memory::create(conn, NewMemoryEntry { scope: "global".into(), kind: "fact".into(), content: "Foundation v1 is Locked (D-010).".into() }, audit::Actor::seed())?;

        let r1 = runs::create(conn, "Wire the remaining workspaces to the backend", "schema → repos → commands → UI", audit::Actor::seed())?;
        runs::add_step(conn, &r1.id, "Design schema", "migration 0005")?;
        runs::add_step(conn, &r1.id, "Write repositories", "")?;
        let gated = runs::add_step(conn, &r1.id, "Register commands", "")?;
        runs::set_step_requires_approval(conn, &gated.id, true)?; // demo: this step needs approval to run
        runs::add_step(conn, &r1.id, "Build the screens", "")?;
        runs::advance(conn, &r1.id, audit::Actor::seed())?; // moves the run to running with the first step active
        runs::create(conn, "Draft the Phase 6 verification report", "", audit::Actor::seed())?;

        let start = now();
        events::create(conn, NewEvent { title: "Phase 5 review".into(), kind: "review".into(), location: "Desktop".into(), starts_at: start.clone(), ends_at: None }, audit::Actor::seed())?;
        events::create(conn, NewEvent { title: "Foundation sync".into(), kind: "meeting".into(), location: "Group Chat".into(), starts_at: start, ends_at: None }, audit::Actor::seed())?;

        // Seeded automations are DISARMED. `create` no longer arms them, and arming
        // is gated on a natively confirmed approval the seed cannot produce -- which
        // is the point: a starter workspace must not ship an unattended executor the
        // operator never approved.
        automations::create(conn, NewAutomation { name: "Notify on failed run".into(), trigger: "run.status = failed".into(), action: "create notification".into() }, audit::Actor::seed())?;
        automations::create(conn, NewAutomation { name: "Auto-archive done projects".into(), trigger: "project.status = completed".into(), action: "set archived".into() }, audit::Actor::seed())?;

        // Every seeded connector stays `disconnected`, the state `create` gives it.
        // The seed used to mark GitHub and Linear "connected", which was a claim the
        // product made about itself and could not support: nothing was configured
        // and nothing was ever contacted -- `create_integration`'s own doc comment
        // says so in those words. It is also the state the T-052 gate on
        // `set_status` now requires a natively confirmed grant to leave, and no seed
        // can honestly mint one.
        integrations::create(conn, "GitHub", "github")?;
        integrations::create(conn, "Slack", "slack")?;
        integrations::create(conn, "Linear", "linear")?;
        integrations::create(conn, "PagerDuty", "pagerduty")?;

        // ── Richer starter content ────────────────────────────────────────────
        // Everything below is honest starter data in the real store — real rows
        // read back through the same repositories the UI uses. It never touches
        // the trust chain: no receipt is minted, so message/security trust stays
        // fail-closed (development_untrusted / NoTrustedManifest), exactly as when
        // the store is empty. It only makes the cockpit read as a live network
        // instead of a blank one.
        let now_ms: i64 = now().parse().unwrap_or(0);

        // A fuller agent network for the lattice, with varied live phases (the
        // `status` column is honest free text the UI maps to a node state).
        for (slug, name, role, model) in [
            ("scout", "Scout", "Research", "claude-sonnet"),
            ("relay", "Relay", "Comms", "claude-sonnet"),
            ("ledger", "Ledger", "Finance", "claude-opus"),
            ("sentry", "Sentry", "Monitoring", "claude-sonnet"),
        ] {
            agents::create(conn, slug, name, role, model)?;
        }
        for (slug, status) in [
            ("forge", "working"),
            ("pixel", "working"),
            ("probe", "review"),
            ("shield", "blocked"),
            ("mason", "completed"),
            ("relay", "working"),
            ("sentry", "working"),
        ] {
            conn.execute(
                "UPDATE agents SET status = ?2 WHERE slug = ?1",
                rusqlite::params![slug, status],
            )?;
        }

        // More projects + tasks across statuses so the boards read as active work.
        let p3 = projects::create(conn, NewProject { name: "AI-OS Cockpit Redesign".into(), description: "Adopt the brops-aios HUD across every view.".into(), priority: "high".into(), workspace_id: None }, audit::Actor::seed())?;
        projects::set_status(conn, &p3.id, "active", audit::Actor::seed())?;
        let p4 = projects::create(conn, NewProject { name: "ISP Dispatch Automations".into(), description: "Outage, ONT provisioning and subscriber flows.".into(), priority: "normal".into(), workspace_id: None }, audit::Actor::seed())?;
        projects::set_status(conn, &p4.id, "active", audit::Actor::seed())?;
        for (proj, title, prio, done) in [
            (&p3, "Port the ambient shell", "high", true),
            (&p3, "Reskin the twelve hero views", "high", true),
            (&p3, "Seed a live starter workspace", "normal", false),
            (&p3, "Split per-view instrument CSS", "low", false),
            (&p4, "Outage auto-dispatch pipeline", "high", false),
            (&p4, "ONT auto-provision flow", "normal", false),
            (&p4, "Subscriber welcome sequence", "low", true),
        ] {
            let tk = tasks::create(conn, NewTask { project_id: Some(proj.id.clone()), title: title.into(), description: "".into(), priority: prio.into(), assigned_agent_id: None }, audit::Actor::seed())?;
            tasks::set_status(conn, &tk.id, if done { "done" } else { "active" }, audit::Actor::seed())?;
        }

        // A spread of audit events so the activity ECG has a real heartbeat
        // (varied types + actors, jittered across the last ~44 hours).
        // The human rows carry `LOCAL_OPERATOR`, not a person's name. These are
        // FABRICATED events written straight into the evidence table for the activity
        // ECG, and a fabricated row that names a real person is indistinguishable from
        // a real one that does -- which is the whole reason the 34 call sites above
        // stopped naming him. The agent and system ids are role names, not people.
        let ev_kinds: [(&str, &str, &str, &str); 11] = [
            ("task.created", "agent", "forge", "task"),
            ("task.completed", "agent", "probe", "task"),
            ("run.advanced", "system", "scheduler", "run"),
            ("message.posted", "user", audit::LOCAL_OPERATOR, "message"),
            ("approval.requested", "agent", "lezu", "approval"),
            ("decision.recorded", "user", audit::LOCAL_OPERATOR, "decision"),
            ("agent.dispatched", "system", "conductor", "agent"),
            ("automation.fired", "system", "scheduler", "automation"),
            ("knowledge.added", "agent", "mason", "note"),
            ("verification.blocked", "system", "broker", "receipt"),
            ("event.scheduled", "user", audit::LOCAL_OPERATOR, "event"),
        ];
        {
            // T-057. Every one of these says so IN the row, in a column that
            // already existed. A reviewer running `SELECT * FROM audit_events`
            // can tell them from real ones without reading this file — the
            // closure condition — and `activity::list` and `security::summary`
            // both carry the mark out, which is why a marker nothing surfaces
            // would not have met it.
            let mut stmt = conn.prepare(
                "INSERT INTO audit_events(id, event_type, actor_type, actor_id, entity_type, entity_id, payload_json, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            )?;
            for i in 0..56i64 {
                let k = ev_kinds[(i as usize) % ev_kinds.len()];
                let offset = i * 46 * 60 * 1000 + (i % 5) * 7000;
                let ts = (now_ms - offset).to_string();
                stmt.execute(rusqlite::params![
                    id(), k.0, k.1, k.2, k.3, id(), activity::SEED_SOURCE, ts
                ])?;
            }
        }

        // More approvals for the gate (mix of pending and already-decided history).
        conn.execute(
            "INSERT INTO approvals(id, action_type, target, level, risk_level, status, requested_by, requested_at, decided_at)
             VALUES (?1,'Deploy runtime config','production broker','A2','medium','pending','mason',?2,NULL),
                    (?3,'Rotate signing key','key manifest','A3','high','pending','shield',?4,NULL),
                    (?5,'Restart provisioning worker','ont-provisioner','A1','low','pending','sentry',?6,NULL),
                    (?7,'Publish release notes','changelog','A1','low','approved','pixel',?8,?9)",
            rusqlite::params![
                id(), (now_ms - 3_600_000).to_string(),
                id(), (now_ms - 7_200_000).to_string(),
                id(), (now_ms - 1_800_000).to_string(),
                id(), (now_ms - 90_000_000).to_string(), (now_ms - 86_400_000).to_string()
            ],
        )?;

        // More notifications.
        conn.execute(
            "INSERT INTO notifications(id, type, severity, title, body, read_at, created_at)
             VALUES (?1,'run_completed','success','Provisioning run closed','ONT auto-provision finished with evidence.',NULL,?2),
                    (?3,'approval_required','warning','Key rotation awaits sign-off','A signing-key rotation is queued for your decision.',NULL,?4),
                    (?5,'run_completed','success','Welcome sequence sent','Subscriber welcome messages delivered.',?6,?6)",
            rusqlite::params![
                id(), (now_ms - 600_000).to_string(),
                id(), (now_ms - 5_400_000).to_string(),
                id(), (now_ms - 43_200_000).to_string()
            ],
        )?;

        // More decisions for the chamber + ledger.
        decisions::create(conn, "Adopt the brops-aios HUD design", "gev", "The mockup is the target look; port it view by view onto real IPC.", audit::Actor::seed())?;
        decisions::create(conn, "Seed a live starter workspace", "gev", "Ship honest starter rows so the cockpit reads as a live network, trust stays fail-closed.", audit::Actor::seed())?;
        decisions::create(conn, "Per-view CSS is route-lazy", "mason", "Each view's instrument CSS ships in its own chunk to keep first paint lean.", audit::Actor::seed())?;
        decisions::create(conn, "Fonts are separate assets", "pixel", "Variable fonts moved out of the CSS payload into /fonts.", audit::Actor::seed())?;
        decisions::create(conn, "Windows broker runs non-SYSTEM", "shield", "A dedicated low-privilege principal completes the governed turn.", audit::Actor::seed())?;
        decisions::create(conn, "Approvals stay human-in-the-loop", "gev", "No step auto-runs; A2+ actions gate on a deliberate confirm.", audit::Actor::seed())?;

        // Richer conversations so the chat canvas reads as active.
        let c3 = chat::create_conversation(conn, "direct", "Redesign", audit::Actor::seed())?;
        for (role, author, body) in [
            ("user", "gev", "Bro, the cockpit should look like the aios mockup."),
            ("agent", "Bro", "Porting the ambient shell and every view onto real IPC now — trust badges stay fail-closed."),
            ("user", "gev", "And it must feel full, not empty."),
            ("agent", "Bro", "Seeding a live starter workspace: real rows, honest states, no faked verification."),
            ("agent", "Pixel", "HUD surfaces, brackets and the power mark are in; light and dark both tuned."),
        ] {
            chat::post_message(conn, NewMessage { conversation_id: c3.id.clone(), role: role.into(), author: author.into(), body: body.into() })?;
        }
        let c4 = chat::create_conversation(conn, "group", "Dispatch room", audit::Actor::seed())?;
        for (author, body) in [
            ("Sentry", "NOC alarm cleared on the Kentron node."),
            ("Relay", "Subscriber notifications delivered for the affected block."),
            ("Ledger", "SLA credit draft prepared, waiting on finance approval."),
            ("Scout", "Root cause narrowed to an upstream OLT reset."),
        ] {
            chat::post_message(conn, NewMessage { conversation_id: c4.id.clone(), role: "agent".into(), author: author.into(), body: body.into() })?;
        }

        // More runs + steps for the command reactor.
        let r3 = runs::create(conn, "Outage auto-dispatch: Kentron", "correlate → locate → dispatch → notify", audit::Actor::seed())?;
        runs::add_step(conn, &r3.id, "Correlate NOC alarms", "3 signals crossed")?;
        runs::add_step(conn, &r3.id, "Locate fault node", "OLT-Kentron-04")?;
        let g3 = runs::add_step(conn, &r3.id, "Dispatch nearest crew", "")?;
        runs::set_step_requires_approval(conn, &g3.id, true)?;
        runs::add_step(conn, &r3.id, "Notify subscribers", "")?;
        runs::advance(conn, &r3.id, audit::Actor::seed())?;
        let r4 = runs::create(conn, "ONT auto-provision batch", "detect → bind profile → remote reset", audit::Actor::seed())?;
        runs::add_step(conn, &r4.id, "Detect new ONTs", "12 serials")?;
        runs::add_step(conn, &r4.id, "Bind service profile", "")?;
        runs::add_step(conn, &r4.id, "Remote reset", "")?;
        runs::add_step(conn, &r4.id, "Confirm online", "")?;
        runs::advance(conn, &r4.id, audit::Actor::seed())?;
        runs::create(conn, "Draft the redesign verification report", "", audit::Actor::seed())?;

        // A spread of calendar events (past, today and upcoming) with durations.
        let day = 86_400_000i64;
        let hour = 3_600_000i64;
        let cal: [(&str, &str, &str, i64, i64, i64); 10] = [
            ("Redesign review", "review", "Cockpit", 0, 10 * hour, 60),
            ("Dispatch standup", "meeting", "Dispatch room", 0, 14 * hour, 30),
            ("Key rotation window", "maintenance", "Broker", 1, 2 * hour, 90),
            ("Foundation sync", "meeting", "Group Chat", 1, 11 * hour, 45),
            ("ONT rollout", "ops", "Field", 2, 9 * hour, 120),
            ("Security audit", "review", "Manifest", 3, 15 * hour, 60),
            ("Subscriber webinar", "event", "Online", 5, 18 * hour, 60),
            ("SLA finance review", "meeting", "Finance", -1, 16 * hour, 30),
            ("Post-outage retro", "review", "Dispatch room", -2, 13 * hour, 45),
            ("Release cut", "ops", "CI", 7, 12 * hour, 30),
        ];
        for (title, kind, loc, d, h, dur) in cal {
            let start = now_ms + d * day + h;
            events::create(conn, NewEvent {
                title: title.into(),
                kind: kind.into(),
                location: loc.into(),
                starts_at: start.to_string(),
                ends_at: Some((start + dur * 60_000).to_string()),
            }, audit::Actor::seed())?;
        }

        // More automations for the manifold. The fourth column used to be an
        // "enabled" flag; it is gone rather than left reading `true` next to a row
        // that is disarmed, which is the kind of sentence that is true when written
        // and false when read.
        let extra_autos = [
            ("Outage auto-dispatch", "noc.alarm = critical", "dispatch nearest crew"),
            ("ONT auto-provision", "olt.new_ont detected", "bind profile + remote reset"),
            ("Subscriber welcome", "subscriber.activated", "send welcome sequence"),
            ("SLA breach alert", "downtime > sla_threshold", "draft credit + notify finance"),
        ];
        for (name, trigger, action) in extra_autos {
            automations::create(conn, NewAutomation { name: name.into(), trigger: trigger.into(), action: action.into() }, audit::Actor::seed())?;
        }

        // A little more knowledge + memory depth.
        knowledge::create(conn, NewKnowledgeNote { title: "Fail-closed trust".into(), body: "With no production manifest the store resolves NoTrustedManifest; the UI never shows a verified badge it cannot prove.".into(), source: "core/production_trust.rs".into(), tags: "governance,trust".into() }, audit::Actor::seed())?;
        knowledge::create(conn, NewKnowledgeNote { title: "Ambient layer".into(), body: "Aurora, mesh field, grid, scanline and cursor light render behind every view at negative z-index.".into(), source: "components/Ambient.tsx".into(), tags: "design,ui".into() }, audit::Actor::seed())?;
        memory::create(conn, NewMemoryEntry { scope: "global".into(), kind: "preference".into(), content: "The cockpit must look full and alive, like the aios mockup.".into() }, audit::Actor::seed())?;

        Ok(())
    })
}
