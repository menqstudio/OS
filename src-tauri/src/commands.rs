//! Typed Tauri commands. React reaches the database only through these; no raw
//! SQL crosses the boundary. Every command maps core errors to strings.

use crate::AppState;
use brops_core::{
    repo, ActivityEvent, Agent, Approval, Decision, NewProject, NewTask, Notification, Project,
    Task,
};
use tauri::State;

type Conn<'a> = std::sync::MutexGuard<'a, rusqlite::Connection>;

fn locked<'a>(state: &'a State<AppState>) -> Result<Conn<'a>, String> {
    state.db.lock().map_err(|e| e.to_string())
}

// --- projects ---

#[tauri::command]
pub fn list_projects(state: State<AppState>) -> Result<Vec<Project>, String> {
    repo::projects::list(&locked(&state)?).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_project(state: State<AppState>, input: NewProject) -> Result<Project, String> {
    repo::projects::create(&locked(&state)?, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_project_status(state: State<AppState>, id: String, status: String) -> Result<Project, String> {
    repo::projects::set_status(&locked(&state)?, &id, &status).map_err(|e| e.to_string())
}

// --- tasks ---

#[tauri::command]
pub fn list_tasks_by_project(state: State<AppState>, project_id: String) -> Result<Vec<Task>, String> {
    repo::tasks::list_by_project(&locked(&state)?, &project_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_tasks_by_status(state: State<AppState>, status: String) -> Result<Vec<Task>, String> {
    repo::tasks::list_by_status(&locked(&state)?, &status).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_task(state: State<AppState>, input: NewTask) -> Result<Task, String> {
    repo::tasks::create(&locked(&state)?, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_task_status(state: State<AppState>, id: String, status: String) -> Result<Task, String> {
    repo::tasks::set_status(&locked(&state)?, &id, &status).map_err(|e| e.to_string())
}

// --- agents ---

#[tauri::command]
pub fn list_agents(state: State<AppState>) -> Result<Vec<Agent>, String> {
    repo::agents::list(&locked(&state)?).map_err(|e| e.to_string())
}

// --- approvals ---

#[tauri::command]
pub fn list_approvals(state: State<AppState>) -> Result<Vec<Approval>, String> {
    repo::approvals::list(&locked(&state)?).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn decide_approval(
    state: State<AppState>,
    id: String,
    decision: String,
    note: Option<String>,
) -> Result<Approval, String> {
    repo::approvals::decide(&locked(&state)?, &id, &decision, note.as_deref()).map_err(|e| e.to_string())
}

// --- notifications ---

#[tauri::command]
pub fn list_notifications(state: State<AppState>) -> Result<Vec<Notification>, String> {
    repo::notifications::list(&locked(&state)?).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn mark_notification_read(state: State<AppState>, id: String) -> Result<Notification, String> {
    repo::notifications::mark_read(&locked(&state)?, &id).map_err(|e| e.to_string())
}

// --- decisions ---

#[tauri::command]
pub fn list_decisions(state: State<AppState>) -> Result<Vec<Decision>, String> {
    repo::decisions::list(&locked(&state)?).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_decision(
    state: State<AppState>,
    title: String,
    rationale: String,
) -> Result<Decision, String> {
    repo::decisions::create(&locked(&state)?, &title, "gev", &rationale).map_err(|e| e.to_string())
}

// --- activity ---

#[tauri::command]
pub fn list_activity(state: State<AppState>) -> Result<Vec<ActivityEvent>, String> {
    repo::activity::list(&locked(&state)?).map_err(|e| e.to_string())
}
