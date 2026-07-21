fn main() {
    // T-010: declare EVERY app IPC command in the application manifest so the
    // capability system actually governs all of them. Tauri v2 capabilities only
    // gate PLUGIN commands by default — app commands registered in
    // `generate_handler!` but absent from this manifest are invokable by the
    // webview with no permission entry at all. Listing a command here makes
    // tauri-build generate `allow-<command>` / `deny-<command>` permissions for it,
    // which `capabilities/default.json` must then grant explicitly; a command with
    // no `allow-*` grant is uninvokable from the window (deny-by-default).
    //
    // INVARIANT (enforced by tools/check_capabilities.py in CI): this list must be
    // exactly the set of commands registered in `src/lib.rs` generate_handler!, and
    // exactly the set classified in `command-policy.json`. Adding a
    // command in one place without the others fails CI — no manual-count drift.
    const COMMANDS: &[&str] = &[
        // projects
        "list_projects",
        "create_project",
        "set_project_status",
        "update_project",
        // tasks
        "list_tasks_by_project",
        "list_tasks_by_status",
        "create_task",
        "set_task_status",
        "list_tasks",
        "update_task",
        "list_task_dependencies",
        "add_task_dependency",
        "remove_task_dependency",
        // agents
        "list_agents",
        // approvals
        "list_approvals",
        "decide_approval",
        "reject_approval",
        // notifications
        "list_notifications",
        "mark_notification_read",
        // decisions
        "list_decisions",
        "create_decision",
        // activity
        "list_activity",
        // chat
        "list_conversations",
        "create_conversation",
        "list_messages",
        "post_message",
        "post_user_message",
        "save_ask_to_chat",
        "delete_conversation",
        "rename_conversation",
        // knowledge
        "list_knowledge",
        "search_knowledge",
        "create_knowledge",
        "delete_knowledge",
        // memory
        "list_memory",
        "create_memory",
        "set_memory_pinned",
        "delete_memory",
        // runs
        "list_runs",
        "create_run",
        "set_run_status",
        "list_run_steps",
        "add_run_step",
        "set_run_step_status",
        "advance_run",
        // events
        "list_events",
        "create_event",
        "delete_event",
        // automations
        "list_automations",
        "create_automation",
        "set_automation_enabled",
        "delete_automation",
        // integrations
        "list_integrations",
        "set_integration_status",
        // search / analytics / security / ai status
        "search_all",
        "get_analytics",
        "get_security_summary",
        "ai_status",
        // AI (live agent replies)
        "reply_in_conversation",
        "stream_reply",
        "stream_ask",
        "stream_run_step",
        // filesystem surface (M-8)
        "list_dir",
        "read_file",
        "write_file",
    ];
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to run tauri-build");
}
