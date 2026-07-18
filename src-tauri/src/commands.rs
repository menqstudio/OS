//! Typed Tauri commands. React reaches the database only through these; no raw
//! SQL crosses the boundary. Every command maps core errors to strings.

use crate::AppState;
use brops_core::{repo, NewProject, NewTask, Project, Task};
use tauri::State;

fn locked<'a>(
    state: &'a State<AppState>,
) -> Result<std::sync::MutexGuard<'a, rusqlite::Connection>, String> {
    state.db.lock().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_projects(state: State<AppState>) -> Result<Vec<Project>, String> {
    let c = locked(&state)?;
    repo::projects::list(&c).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_project(state: State<AppState>, input: NewProject) -> Result<Project, String> {
    let c = locked(&state)?;
    repo::projects::create(&c, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_project_status(
    state: State<AppState>,
    id: String,
    status: String,
) -> Result<Project, String> {
    let c = locked(&state)?;
    repo::projects::set_status(&c, &id, &status).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_tasks_by_project(state: State<AppState>, project_id: String) -> Result<Vec<Task>, String> {
    let c = locked(&state)?;
    repo::tasks::list_by_project(&c, &project_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_task(state: State<AppState>, input: NewTask) -> Result<Task, String> {
    let c = locked(&state)?;
    repo::tasks::create(&c, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_task_status(state: State<AppState>, id: String, status: String) -> Result<Task, String> {
    let c = locked(&state)?;
    repo::tasks::set_status(&c, &id, &status).map_err(|e| e.to_string())
}
