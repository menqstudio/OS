//! Domain types shared across repositories. Serialized as camelCase so the
//! TypeScript frontend consumes idiomatic objects. Mirrors `docs/architecture/DATA_MODEL.md`.

use serde::{Deserialize, Serialize};

pub const TASK_STATUSES: &[&str] =
    &["inbox", "planned", "active", "blocked", "review", "done", "cancelled"];
pub const PROJECT_STATUSES: &[&str] =
    &["planned", "active", "blocked", "completed", "archived"];
pub const PRIORITIES: &[&str] = &["low", "normal", "high", "critical"];
pub const APPROVAL_DECISIONS: &[&str] = &["approved", "rejected"];

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
