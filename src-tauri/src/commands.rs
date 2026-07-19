//! Typed Tauri commands. React reaches the database only through these; no raw
//! SQL crosses the boundary. Every command maps core errors to strings.

use crate::AppState;
use brops_core::{
    repo, ActivityEvent, Agent, Approval, Conversation, Decision, KnowledgeNote, MemoryEntry,
    Message, NewKnowledgeNote, NewMemoryEntry, NewMessage, NewProject, NewTask, Notification,
    Project, Task,
};
use tauri::State;

type Conn<'a> = std::sync::MutexGuard<'a, rusqlite::Connection>;

fn locked<'a>(state: &'a State<AppState>) -> Result<Conn<'a>, String> {
    state.db.lock().map_err(|e| e.to_string())
}

// --- projects ---

#[tauri::command]
pub fn list_projects(state: State<AppState>) -> Result<Vec<Project>, String> {
    let conn = locked(&state)?;
    repo::projects::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_project(state: State<AppState>, input: NewProject) -> Result<Project, String> {
    let conn = locked(&state)?;
    repo::projects::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_project_status(state: State<AppState>, id: String, status: String) -> Result<Project, String> {
    let conn = locked(&state)?;
    repo::projects::set_status(&conn, &id, &status).map_err(|e| e.to_string())
}

// --- tasks ---

#[tauri::command]
pub fn list_tasks_by_project(state: State<AppState>, project_id: String) -> Result<Vec<Task>, String> {
    let conn = locked(&state)?;
    repo::tasks::list_by_project(&conn, &project_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_tasks_by_status(state: State<AppState>, status: String) -> Result<Vec<Task>, String> {
    let conn = locked(&state)?;
    repo::tasks::list_by_status(&conn, &status).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_task(state: State<AppState>, input: NewTask) -> Result<Task, String> {
    let conn = locked(&state)?;
    repo::tasks::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_task_status(state: State<AppState>, id: String, status: String) -> Result<Task, String> {
    let conn = locked(&state)?;
    repo::tasks::set_status(&conn, &id, &status).map_err(|e| e.to_string())
}

// --- agents ---

#[tauri::command]
pub fn list_agents(state: State<AppState>) -> Result<Vec<Agent>, String> {
    let conn = locked(&state)?;
    repo::agents::list(&conn).map_err(|e| e.to_string())
}

// --- approvals ---

#[tauri::command]
pub fn list_approvals(state: State<AppState>) -> Result<Vec<Approval>, String> {
    let conn = locked(&state)?;
    repo::approvals::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn decide_approval(
    state: State<AppState>,
    id: String,
    decision: String,
    note: Option<String>,
) -> Result<Approval, String> {
    let conn = locked(&state)?;
    repo::approvals::decide(&conn, &id, &decision, note.as_deref()).map_err(|e| e.to_string())
}

// --- notifications ---

#[tauri::command]
pub fn list_notifications(state: State<AppState>) -> Result<Vec<Notification>, String> {
    let conn = locked(&state)?;
    repo::notifications::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn mark_notification_read(state: State<AppState>, id: String) -> Result<Notification, String> {
    let conn = locked(&state)?;
    repo::notifications::mark_read(&conn, &id).map_err(|e| e.to_string())
}

// --- decisions ---

#[tauri::command]
pub fn list_decisions(state: State<AppState>) -> Result<Vec<Decision>, String> {
    let conn = locked(&state)?;
    repo::decisions::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_decision(state: State<AppState>, title: String, rationale: String) -> Result<Decision, String> {
    let conn = locked(&state)?;
    repo::decisions::create(&conn, &title, "gev", &rationale).map_err(|e| e.to_string())
}

// --- activity ---

#[tauri::command]
pub fn list_activity(state: State<AppState>) -> Result<Vec<ActivityEvent>, String> {
    let conn = locked(&state)?;
    repo::activity::list(&conn).map_err(|e| e.to_string())
}

// --- chat ---

#[tauri::command]
pub fn list_conversations(state: State<AppState>, kind: Option<String>) -> Result<Vec<Conversation>, String> {
    let conn = locked(&state)?;
    repo::chat::list_conversations(&conn, kind.as_deref()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_conversation(state: State<AppState>, kind: String, title: String) -> Result<Conversation, String> {
    let conn = locked(&state)?;
    repo::chat::create_conversation(&conn, &kind, &title).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_messages(state: State<AppState>, conversation_id: String) -> Result<Vec<Message>, String> {
    let conn = locked(&state)?;
    repo::chat::list_messages(&conn, &conversation_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn post_message(state: State<AppState>, input: NewMessage) -> Result<Message, String> {
    let conn = locked(&state)?;
    repo::chat::post_message(&conn, input).map_err(|e| e.to_string())
}

// --- knowledge ---

#[tauri::command]
pub fn list_knowledge(state: State<AppState>) -> Result<Vec<KnowledgeNote>, String> {
    let conn = locked(&state)?;
    repo::knowledge::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn search_knowledge(state: State<AppState>, query: String) -> Result<Vec<KnowledgeNote>, String> {
    let conn = locked(&state)?;
    repo::knowledge::search(&conn, &query).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_knowledge(state: State<AppState>, input: NewKnowledgeNote) -> Result<KnowledgeNote, String> {
    let conn = locked(&state)?;
    repo::knowledge::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_knowledge(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::knowledge::delete(&conn, &id).map_err(|e| e.to_string())
}

// --- memory ---

#[tauri::command]
pub fn list_memory(state: State<AppState>, scope: Option<String>) -> Result<Vec<MemoryEntry>, String> {
    let conn = locked(&state)?;
    repo::memory::list(&conn, scope.as_deref()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_memory(state: State<AppState>, input: NewMemoryEntry) -> Result<MemoryEntry, String> {
    let conn = locked(&state)?;
    repo::memory::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_memory_pinned(state: State<AppState>, id: String, pinned: bool) -> Result<MemoryEntry, String> {
    let conn = locked(&state)?;
    repo::memory::set_pinned(&conn, &id, pinned).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_memory(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::memory::delete(&conn, &id).map_err(|e| e.to_string())
}
