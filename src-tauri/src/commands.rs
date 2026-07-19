//! Typed Tauri commands. React reaches the database only through these; no raw
//! SQL crosses the boundary. Every command maps core errors to strings.

use crate::AppState;
use brops_core::{
    repo, ActivityEvent, Agent, Approval, Automation, Conversation, Decision, Event, Integration,
    KnowledgeNote, MemoryEntry, Message, Metric, NewAutomation, NewEvent, NewKnowledgeNote,
    NewMemoryEntry, NewMessage, NewProject, NewTask, Notification, Project, Run, RunStep,
    SecuritySummary, Task,
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

// --- runs (command) ---

#[tauri::command]
pub fn list_runs(state: State<AppState>) -> Result<Vec<Run>, String> {
    let conn = locked(&state)?;
    repo::runs::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_run(state: State<AppState>, intent: String, plan: String) -> Result<Run, String> {
    let conn = locked(&state)?;
    repo::runs::create(&conn, &intent, &plan).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_run_status(state: State<AppState>, id: String, status: String) -> Result<Run, String> {
    let conn = locked(&state)?;
    repo::runs::set_status(&conn, &id, &status).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_run_steps(state: State<AppState>, run_id: String) -> Result<Vec<RunStep>, String> {
    let conn = locked(&state)?;
    repo::runs::list_steps(&conn, &run_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn add_run_step(state: State<AppState>, run_id: String, title: String, detail: String) -> Result<RunStep, String> {
    let conn = locked(&state)?;
    repo::runs::add_step(&conn, &run_id, &title, &detail).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_run_step_status(state: State<AppState>, id: String, status: String) -> Result<RunStep, String> {
    let conn = locked(&state)?;
    repo::runs::set_step_status(&conn, &id, &status).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn advance_run(state: State<AppState>, run_id: String) -> Result<Run, String> {
    let conn = locked(&state)?;
    repo::runs::advance(&conn, &run_id).map_err(|e| e.to_string())
}

// --- events (calendar) ---

#[tauri::command]
pub fn list_events(state: State<AppState>) -> Result<Vec<Event>, String> {
    let conn = locked(&state)?;
    repo::events::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_event(state: State<AppState>, input: NewEvent) -> Result<Event, String> {
    let conn = locked(&state)?;
    repo::events::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_event(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::events::delete(&conn, &id).map_err(|e| e.to_string())
}

// --- automations ---

#[tauri::command]
pub fn list_automations(state: State<AppState>) -> Result<Vec<Automation>, String> {
    let conn = locked(&state)?;
    repo::automations::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_automation(state: State<AppState>, input: NewAutomation) -> Result<Automation, String> {
    let conn = locked(&state)?;
    repo::automations::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_automation_enabled(state: State<AppState>, id: String, enabled: bool) -> Result<Automation, String> {
    let conn = locked(&state)?;
    repo::automations::set_enabled(&conn, &id, enabled).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_automation(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::automations::delete(&conn, &id).map_err(|e| e.to_string())
}

// --- integrations ---

#[tauri::command]
pub fn list_integrations(state: State<AppState>) -> Result<Vec<Integration>, String> {
    let conn = locked(&state)?;
    repo::integrations::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_integration_status(state: State<AppState>, id: String, status: String) -> Result<Integration, String> {
    let conn = locked(&state)?;
    repo::integrations::set_status(&conn, &id, &status).map_err(|e| e.to_string())
}

// --- analytics / security (computed, read-only) ---

#[tauri::command]
pub fn get_analytics(state: State<AppState>) -> Result<Vec<Metric>, String> {
    let conn = locked(&state)?;
    repo::analytics::metrics(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_security_summary(state: State<AppState>) -> Result<SecuritySummary, String> {
    let conn = locked(&state)?;
    repo::security::summary(&conn).map_err(|e| e.to_string())
}
