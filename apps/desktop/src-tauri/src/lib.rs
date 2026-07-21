//! BroPS Tauri host. Opens the local SQLite database via `brops-core`, exposes
//! it as managed state, and registers the typed command surface.

use std::sync::Mutex;
use tauri::Manager;

mod ai;
mod commands;
mod files;

pub struct AppState {
    pub db: Mutex<rusqlite::Connection>,
}

/// Restrict the app data directory to the owner (0700). Called BEFORE the DB is
/// opened, so the database is created inside an already-private directory.
/// A failure here aborts startup rather than running with weak permissions.
#[cfg(unix)]
fn secure_data_dir(dir: &std::path::Path) -> std::io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700))
}
#[cfg(not(unix))]
fn secure_data_dir(_dir: &std::path::Path) -> std::io::Result<()> {
    Ok(())
}

/// Restrict the SQLite database and its WAL/SHM sidecars to the owner (0600).
#[cfg(unix)]
fn secure_db_files(db_path: &std::path::Path) -> std::io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    for suffix in ["", "-wal", "-shm"] {
        let p = std::path::PathBuf::from(format!("{}{}", db_path.display(), suffix));
        if p.exists() {
            std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o600))?;
        }
    }
    Ok(())
}
#[cfg(not(unix))]
fn secure_db_files(_db_path: &std::path::Path) -> std::io::Result<()> {
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // T-011: renderer-independent native confirmation dialog for privileged
        // approvals (driven from Rust in `confirm_approval`).
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&dir)?;
            // Owner-only (0700) BEFORE opening the DB, so conversation/memory/audit
            // data is never briefly world-readable. A failure aborts startup.
            secure_data_dir(&dir)?;
            let db_path = dir.join("brops.db");
            let conn = brops_core::db::open(db_path.to_string_lossy().as_ref())?;
            brops_core::repo::seed(&conn)?;
            secure_db_files(&db_path)?; // 0600 on db + WAL + SHM
            // Sweep AI sandbox directories left by crashed/killed prior runs.
            ai::cleanup_stale_sandboxes();
            app.manage(AppState { db: Mutex::new(conn) });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_projects,
            commands::create_project,
            commands::set_project_status,
            commands::update_project,
            commands::list_tasks_by_project,
            commands::list_tasks_by_status,
            commands::create_task,
            commands::set_task_status,
            commands::list_tasks,
            commands::update_task,
            commands::list_task_dependencies,
            commands::add_task_dependency,
            commands::remove_task_dependency,
            commands::list_agents,
            commands::list_approvals,
            commands::decide_approval,
            commands::reject_approval,
            commands::confirm_approval,
            commands::list_notifications,
            commands::mark_notification_read,
            commands::list_decisions,
            commands::create_decision,
            commands::list_activity,
            commands::list_conversations,
            commands::create_conversation,
            commands::list_messages,
            commands::post_message,
            commands::post_user_message,
            commands::save_ask_to_chat,
            commands::delete_conversation,
            commands::rename_conversation,
            commands::list_knowledge,
            commands::search_knowledge,
            commands::create_knowledge,
            commands::delete_knowledge,
            commands::list_memory,
            commands::create_memory,
            commands::set_memory_pinned,
            commands::delete_memory,
            commands::list_runs,
            commands::create_run,
            commands::set_run_status,
            commands::list_run_steps,
            commands::add_run_step,
            commands::set_run_step_status,
            commands::advance_run,
            commands::list_events,
            commands::create_event,
            commands::delete_event,
            commands::list_automations,
            commands::create_automation,
            commands::set_automation_enabled,
            commands::delete_automation,
            commands::list_integrations,
            commands::set_integration_status,
            commands::search_all,
            commands::get_analytics,
            commands::get_security_summary,
            commands::ai_status,
            commands::reply_in_conversation,
            commands::stream_reply,
            commands::stream_ask,
            commands::stream_run_step,
            // Filesystem surface (M-8): unlike the commands above, these are
            // declared in the app manifest (build.rs) and therefore governed by
            // explicit `allow-*` grants in capabilities/default.json — removing
            // a grant disables the command for the window.
            files::list_dir,
            files::read_file,
            files::write_file,
        ])
        .run(tauri::generate_context!())
        .expect("error while running BroPS");
}
