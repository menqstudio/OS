//! Domain types shared across repositories. Serialized as camelCase so the
//! TypeScript frontend consumes idiomatic objects. Mirrors `docs/architecture/DATA_MODEL.md`.

use serde::{Deserialize, Serialize};

pub const TASK_STATUSES: &[&str] =
    &["inbox", "planned", "active", "blocked", "review", "done", "cancelled"];
pub const PROJECT_STATUSES: &[&str] =
    &["planned", "active", "blocked", "completed", "archived"];
pub const PRIORITIES: &[&str] = &["low", "normal", "high", "critical"];
pub const APPROVAL_DECISIONS: &[&str] = &["approved", "rejected"];
pub const CONVERSATION_KINDS: &[&str] = &["direct", "group"];
pub const MESSAGE_ROLES: &[&str] = &["user", "agent", "system"];
/// Closed value domain for a message's governed-turn receipt tag. A governed
/// turn stores 'verified' (receipt verified) or 'blocked' (fail-closed); an
/// ungoverned turn stores no tag (`None`). Server-derived, never client-supplied.
pub const MESSAGE_RECEIPTS: &[&str] = &["verified", "blocked"];
pub const MEMORY_KINDS: &[&str] = &["fact", "preference", "note", "reference"];
pub const RUN_STATUSES: &[&str] = &[
    "drafted", "queued", "planning", "awaiting_approval", "running", "paused", "succeeded",
    "failed", "cancelled",
];
pub const INTEGRATION_STATUSES: &[&str] = &["disconnected", "connected", "error"];
pub const STEP_STATUSES: &[&str] = &["pending", "active", "done", "failed", "skipped"];

pub fn is_valid(value: &str, allowed: &[&str]) -> bool {
    allowed.contains(&value)
}

macro_rules! camel {
    ($($item:item)*) => {
        $(#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
          #[serde(rename_all = "camelCase")]
          $item)*
    };
}

camel! {
    pub struct Project {
        pub id: String,
        pub workspace_id: Option<String>,
        pub name: String,
        pub description: String,
        pub status: String,
        pub priority: String,
        pub created_at: String,
        pub updated_at: String,
        pub archived_at: Option<String>,
    }

    pub struct Task {
        pub id: String,
        pub project_id: Option<String>,
        pub title: String,
        pub description: String,
        pub status: String,
        pub priority: String,
        pub assigned_agent_id: Option<String>,
        pub due_at: Option<String>,
        pub position: i64,
        pub created_at: String,
        pub updated_at: String,
        pub completed_at: Option<String>,
    }

    pub struct Agent {
        pub id: String,
        pub slug: String,
        pub display_name: String,
        pub role: String,
        pub status: String,
        pub model: Option<String>,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct Approval {
        pub id: String,
        pub action_type: String,
        pub target: String,
        pub level: String,
        pub risk_level: String,
        pub status: String,
        pub requested_by: String,
        pub decision_note: Option<String>,
        pub entity_type: Option<String>,
        pub entity_id: Option<String>,
        pub requested_at: String,
        pub decided_at: Option<String>,
    }

    pub struct Notification {
        pub id: String,
        pub kind: String,
        pub severity: String,
        pub title: String,
        pub body: String,
        pub entity_type: Option<String>,
        pub entity_id: Option<String>,
        pub read_at: Option<String>,
        pub created_at: String,
    }

    pub struct Decision {
        pub id: String,
        pub title: String,
        pub status: String,
        pub owner: String,
        pub rationale: String,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct ActivityEvent {
        pub id: String,
        pub event_type: String,
        pub actor_id: Option<String>,
        pub entity_type: Option<String>,
        pub entity_id: Option<String>,
        pub created_at: String,
    }

    pub struct Conversation {
        pub id: String,
        pub kind: String,
        pub title: String,
        pub message_count: i64,
        pub last_message_at: Option<String>,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct Message {
        pub id: String,
        pub conversation_id: String,
        pub role: String,
        pub author: String,
        pub body: String,
        pub created_at: String,
        /// Governed-turn receipt tag: 'verified' | 'blocked' | None (ungoverned).
        /// Server-derived from the engine receipt; drives the chat verification badge.
        pub receipt: Option<String>,
    }

    pub struct KnowledgeNote {
        pub id: String,
        pub title: String,
        pub body: String,
        pub source: String,
        pub tags: String,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct MemoryEntry {
        pub id: String,
        pub scope: String,
        pub kind: String,
        pub content: String,
        pub pinned: bool,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct Run {
        pub id: String,
        pub intent: String,
        pub status: String,
        pub plan: String,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct RunStep {
        pub id: String,
        pub run_id: String,
        pub position: i64,
        pub title: String,
        pub detail: String,
        pub status: String,
        pub result: String,
        pub requires_approval: bool,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct Event {
        pub id: String,
        pub title: String,
        pub kind: String,
        pub location: String,
        pub starts_at: String,
        pub ends_at: Option<String>,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct Automation {
        pub id: String,
        pub name: String,
        pub trigger: String,
        pub action: String,
        pub enabled: bool,
        pub created_at: String,
        pub updated_at: String,
    }

    pub struct Integration {
        pub id: String,
        pub name: String,
        pub provider: String,
        pub status: String,
        pub created_at: String,
        pub updated_at: String,
    }

    // Computed at read time — no table of its own.
    pub struct Metric {
        pub key: String,
        pub label: String,
        pub value: i64,
    }

    pub struct SecuritySummary {
        pub pending_approvals: i64,
        pub decided_approvals: i64,
        pub audit_events: i64,
        pub sensitive_events: Vec<ActivityEvent>,
    }

    // A single global-search hit. Computed at read time across many tables; the
    // `route` names the screen the frontend navigates to when it is selected.
    pub struct SearchResult {
        pub kind: String,
        pub id: String,
        pub title: String,
        pub subtitle: String,
        pub route: String,
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewProject {
    pub name: String,
    pub description: String,
    pub priority: String,
    pub workspace_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewTask {
    pub project_id: Option<String>,
    pub title: String,
    pub description: String,
    pub priority: String,
    pub assigned_agent_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewMessage {
    pub conversation_id: String,
    pub role: String,
    pub author: String,
    pub body: String,
    /// Governed-turn receipt tag ('verified' | 'blocked' | None). Set ONLY by
    /// server-side reply paths (stream_reply / reply_in_conversation) from the
    /// engine verdict. The webview `post_message` / `post_user_message` commands
    /// force this to None — the tag is never client-supplied (spec §7). Defaults
    /// to None when absent from a deserialized payload.
    #[serde(default)]
    pub receipt: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewKnowledgeNote {
    pub title: String,
    pub body: String,
    pub source: String,
    pub tags: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewMemoryEntry {
    pub scope: String,
    pub kind: String,
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewEvent {
    pub title: String,
    pub kind: String,
    pub location: String,
    pub starts_at: String,
    pub ends_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewAutomation {
    pub name: String,
    pub trigger: String,
    pub action: String,
}

#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("invalid value for {field}: {value}")]
    Invalid { field: &'static str, value: String },
    #[error("not found: {0}")]
    NotFound(String),
}

pub type CoreResult<T> = Result<T, CoreError>;
