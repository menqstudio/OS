//! Domain types shared across repositories. Mirrors the frontend enums in
//! `src/domain/enums.ts` and `docs/architecture/DATA_MODEL.md`.

use serde::{Deserialize, Serialize};

pub const TASK_STATUSES: &[&str] =
    &["inbox", "planned", "active", "blocked", "review", "done", "cancelled"];
pub const PROJECT_STATUSES: &[&str] =
    &["planned", "active", "blocked", "completed", "archived"];
pub const PRIORITIES: &[&str] = &["low", "normal", "high", "critical"];
pub const APPROVAL_STATUSES: &[&str] =
    &["pending", "approved", "rejected", "expired", "cancelled"];

pub fn is_valid(value: &str, allowed: &[&str]) -> bool {
    allowed.contains(&value)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewProject {
    pub name: String,
    pub description: String,
    pub priority: String,
    pub workspace_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
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

#[derive(Debug, Clone, Serialize, Deserialize)]
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
