//! BroPS Tauri host. Opens the local SQLite database via `brops-core`, exposes
//! it as managed state, and registers the typed command surface.

use std::sync::Mutex;
use tauri::Manager;

mod ai;
mod commands;
// `pub` so `tests/o3_conductor_session.rs` can drive the REAL precedence resolver against
// the REAL Python engine. A cross-language proof that re-implements the rule it is proving
// is checking the copy, not the thing the application runs.
pub mod engine_trust;
mod governance;
mod governed_selftest;
mod governed_turn;
mod files;

pub struct AppState {
    pub db: Mutex<rusqlite::Connection>,
    // Held for the whole process lifetime so a second instance cannot run (T-011).
    // Never read — dropping it releases the OS lock, so it lives inside AppState.
    _instance_lock: std::fs::File,
}

/// T-011 single-instance enforcement. Acquire an EXCLUSIVE advisory lock on a lock
/// file in the data dir BEFORE the database is opened or reconciliation runs. A
/// second instance fails to acquire it and must abort — so it can never reach the
/// startup reconciliation and mark the first (live) instance's execution abandoned.
/// The returned handle must be kept alive for the process lifetime (held in AppState).
fn acquire_instance_lock(dir: &std::path::Path) -> std::io::Result<std::fs::File> {
    use fs2::FileExt;
    let path = dir.join("brops.instance.lock");
    let file = std::fs::OpenOptions::new().create(true).write(true).truncate(false).open(&path)?;
    file.try_lock_exclusive().map_err(|e| {
        std::io::Error::new(
            std::io::ErrorKind::WouldBlock,
            format!("another BroPS instance is already running (lock: {}): {e}", path.display()),
        )
    })?;
    Ok(file)
}

/// Restrict the app data directory to the owner (0700). Called BEFORE the DB is
/// opened, so the database is created inside an already-private directory.
/// A failure here aborts startup rather than running with weak permissions.
///
/// The per-OS routine itself now lives in `brops-provision`, so the host and the
/// first-launch trust provisioner restrict directories through ONE implementation
/// rather than two that can drift. It is still a no-op off unix — and
/// `brops_provision::Protection`, recorded in the provisioning manifest, is what says
/// so out loud instead of letting a silent no-op read as "owner only everywhere".
use brops_provision::secure_data_dir;

/// Restrict the SQLite database and its WAL/SHM sidecars to the owner (0600), through
/// the same single file routine that restricts the provisioned private keys.
fn secure_db_files(db_path: &std::path::Path) -> std::io::Result<()> {
    for suffix in ["", "-wal", "-shm"] {
        let p = std::path::PathBuf::from(format!("{}{}", db_path.display(), suffix));
        if p.exists() {
            brops_provision::secure_owner_only_file(&p)?;
        }
    }
    Ok(())
}

/// Mint the local trust store on first launch, or verify the existing one.
///
/// Runs immediately after the data directory is made owner-only and BEFORE the
/// database is opened, because the trust store is the thing every governance claim
/// downstream rests on and a database opened over a half-trusted tree is a database
/// whose provenance nobody can state.
///
/// **A failure aborts startup.** There is no degraded mode: `brops_provision` removes
/// anything a failed mint wrote, so the choice at this point is a complete trust store
/// or none, and running with none while pretending otherwise is the failure this whole
/// path exists to prevent.
///
/// # What this now RECORDS, and where it is applied
///
/// **Corrected 2026-08-09; the previous version of this comment was the justification for
/// the O-3 gap.** It said the environment `Provisioned::engine_env()` reports was not
/// exported because "`bro_signature.load_trusted_keys` reads
/// `<engine root>/config/trusted-keys.json` and takes no path override". That stopped
/// being true when O-3's engine half landed: `load_trusted_keys` reads
/// `resolve_registry_root(root)`, not `root`, and `BRO_TRUSTED_REGISTRY_ROOT`
/// (`bro_signature.ENV_REGISTRY_ROOT`) names the deployment's registry root under custody
/// rules at least as strong as the pin's. The comment did not move, so a stale sentence
/// went on justifying a deployment in which every artifact this module minted verified
/// perfectly against a registry nothing consulted.
///
/// So: `Provisioned::engine_env()` — which now includes `BRO_TRUSTED_REGISTRY_ROOT`, and
/// still deliberately excludes `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` — is RECORDED here and
/// applied by `engine_trust::apply` to the child process that runs the engine, at the one
/// seam that launches it (`ai::governed_sidecar_call`). It is still not exported into
/// THIS process: `std::env::set_var` is process-wide and racy, and the host has no
/// business verifying against a trust root it also holds the keys for.
///
/// The second reason the old comment gave is real and survives: `_resolve_operator_root_pin`
/// hard-fails when a file pin and the CI `BRO_OPERATOR_ROOT_PUBKEY` disagree, so the export
/// is not unconditional. `engine_trust` states the precedence rule — whole-set or nothing,
/// agreement permitted, disagreement refused by name in both directions — and that module's
/// documentation is where it is argued rather than here.
fn provision_local_trust(dir: &std::path::Path) -> Result<(), Box<dyn std::error::Error>> {
    // The audit signer's published identity, if this machine has one. It has to be in hand
    // HERE and not later: `provision` destroys the operator root before it returns, which
    // seals the trusted-key registry, so a key not admitted while the registry is being
    // signed can never be admitted at all. That is why the install plan starts the signer
    // service before the app's first launch. An unreadable-but-present record is an error
    // rather than a shrug — see `published_anchor_custody`.
    // The machine-wide root is now REQUIRED, not optional. It used to be looked up only to
    // find the audit signer's published identity, and `None` off Windows was harmless. It is
    // now also where the operator-root pin, the anti-rollback floor and the provisioning
    // manifest live — the three files that decide whether the whole chain is genuine — so a
    // deployment that cannot name one has nowhere to put its trust anchor and must be told so
    // rather than quietly provisioned into a directory it can rewrite.
    let root = machine_root()?;
    let anchor = brops_provision::published_anchor_custody(&root)?;
    let provisioned = brops_provision::provision_with_anchor(dir, &root, anchor.as_ref())?;
    // The wiring line O-3 was open on. Recorded rather than exported: `engine_trust::apply`
    // decides, per spawn and against the live environment, whether the provisioned set may
    // be applied to the child that runs the engine — and refuses by name when an inherited
    // anchor disagrees with it, instead of silently overwriting it or being silently
    // overwritten by it.
    engine_trust::record(&provisioned);
    if provisioned.freshly_minted {
        eprintln!(
            "BroPS provisioned its local trust store at {} (install {}).\n\
             Posture: {}\n\
             Key material protection — {}\n\
             Operator root — {}\n\
             Trust anchor — {}\n\
             Custody, measured on this launch:\n{}",
            provisioned.trust_dir.display(),
            provisioned.install_id,
            brops_provision::POSTURE_SUMMARY,
            provisioned.key_file_protection,
            brops_provision::OPERATOR_ROOT_CUSTODY,
            brops_provision::ANCHOR_CUSTODY,
            provisioned
                .custody
                .as_ref()
                .map(|c| c.to_string())
                .unwrap_or_else(|| "NOT MEASURED".to_string()),
        );
    }
    Ok(())
}

/// `%ProgramData%\BroPS` (or its POSIX equivalent) — the machine-wide root that holds both
/// the audit signer's protected directory and, since O-2, the trust ANCHOR.
///
/// It used to return `Option` and `None` off Windows, because the only thing under it was the
/// audit signer and on POSIX that signer is a separate uid provisioned elsewhere. It cannot be
/// optional any more: `<machine_root>/trust-anchor` is where the operator-root pin, the
/// anti-rollback floor and the provisioning manifest live, and a startup with no such location
/// has no trust anchor at all. `brops_provision::anchor::default_machine_root` owns the choice
/// and refuses, by name, on a platform where it cannot make one — which is the whole point of
/// asking it rather than falling back to the application's own directory.
fn machine_root() -> Result<std::path::PathBuf, brops_provision::ProvisionError> {
    brops_provision::anchor::default_machine_root()
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
            // First-launch trust provisioning: mint the operator-signed trusted-key
            // registry, the out-of-registry operator-root pin and the operator-signed
            // artifacts the engine requires, or verify the ones already there. Before
            // the DB opens; a failure aborts startup naming what failed.
            provision_local_trust(&dir)?;
            // T-011 single-instance: take the exclusive lock BEFORE opening the DB or
            // reconciling — a second instance aborts here and never touches the first
            // instance's live execution state.
            let instance_lock = acquire_instance_lock(&dir)?;
            let db_path = dir.join("brops.db");
            let conn = brops_core::db::open(db_path.to_string_lossy().as_ref())?;
            brops_core::repo::seed(&conn)?;
            secure_db_files(&db_path)?; // 0600 on db + WAL + SHM
            // T-011 crash recovery: settle any step execution claimed by a previous
            // (crashed) session fail-closed, so a durable claim can never wedge a run.
            // Safe under the single-instance lock above (no live foreign session).
            brops_core::repo::runs::reconcile_abandoned_executions(&conn, commands::process_session_id())?;
            // Sweep AI sandbox directories left by crashed/killed prior runs.
            ai::cleanup_stale_sandboxes();
            app.manage(AppState { db: Mutex::new(conn), _instance_lock: instance_lock });

            // Phase 8: the local automation scheduler. Once a minute it fires every ENABLED
            // automation whose interval trigger (`every: <N>{m|h|d}`) is due, running its LOCAL
            // action and logging the run. Only local, non-AI actions ever fire unattended — an
            // AI-reaching action routes through the governed, fail-closed chain, never this loop.
            // A poisoned DB mutex is skipped (fail-closed, consistent with `locked`).
            let scheduler_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut ticker = tokio::time::interval(std::time::Duration::from_secs(60));
                ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
                loop {
                    ticker.tick().await;
                    let now_ms = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|d| d.as_millis() as i64)
                        .unwrap_or(0);
                    if let Some(state) = scheduler_handle.try_state::<AppState>() {
                        if let Ok(conn) = state.db.lock() {
                            let _ = brops_core::repo::automations::run_due(&conn, now_ms);
                        }
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            governed_turn::governed_turn_execute,
            // Phase-2 governance mirror (READ-ONLY; mirror, never decide). These
            // commands only READ engine governance surfaces via the sidecar and fail
            // closed to a typed Blocked/Unreachable — they hold no key/lease, touch no
            // DB, and can author no decision.
            governance::read_decision_ledger,
            governance::read_evidence_chain,
            governance::read_verifier_verdicts,
            governance::read_engine_approval_queue,
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
            commands::escalate_approval,
            commands::confirm_approval,
            commands::list_notifications,
            commands::mark_notification_read,
            commands::list_decisions,
            commands::create_decision,
            commands::list_activity,
            commands::list_conversations,
            commands::create_conversation,
            commands::set_conversation_participants,
            commands::list_conversation_participants,
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
            commands::list_library,
            commands::create_library_item,
            commands::delete_library_item,
            commands::list_research,
            commands::create_research_item,
            commands::delete_research_item,
            commands::list_memory,
            commands::create_memory,
            commands::set_memory_pinned,
            commands::delete_memory,
            // READ-ONLY local write records for memory/knowledge (Phase 5). These
            // report what was RECORDED — an unsigned, in-transaction, append-only
            // tamper-evidence record — and never claim verification; see the section
            // header in commands.rs before naming any of this on screen.
            commands::memory_write_record_state,
            commands::memory_write_records,
            commands::knowledge_write_record_state,
            commands::knowledge_write_records,
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
            commands::run_automation,
            commands::list_automation_runs,
            commands::list_integrations,
            commands::create_integration,
            commands::set_integration_status,
            commands::set_integration_auth_ref,
            commands::search_all,
            commands::get_analytics,
            commands::get_security_summary,
            commands::ai_status,
            commands::reply_in_conversation,
            commands::stream_reply,
            commands::demonstration_verified_reply,
            commands::cancel_reply,
            commands::open_window,
            commands::stream_ask,
            commands::stream_run_step,
            // Filesystem surface (M-8): unlike the commands above, these are
            // declared in the app manifest (build.rs) and therefore governed by
            // explicit `allow-*` grants in capabilities/default.json — removing
            // a grant disables the command for the window.
            files::list_dir,
            files::read_file,
            files::write_file,
            // Owner-visible governed trust-chain self-test: runs the REAL in-process
            // challenge→sign→verify→trusted_verified chain (Windows) and reports the
            // honest outcome + custody posture. Never flips live AI turns.
            governed_selftest::governed_trust_selftest,
        ])
        .run(tauri::generate_context!())
        .expect("error while running BroPS");
}

#[cfg(test)]
mod tests {
    use super::acquire_instance_lock;

    // T-011 single-instance enforcement: the first holder takes the exclusive lock;
    // a second acquisition on the same data dir is refused. A second app instance
    // therefore aborts before it can open the DB or run reconciliation and invalidate
    // the first (live) instance's execution.
    #[test]
    fn only_one_instance_can_hold_the_lock() {
        let dir = tempfile::tempdir().unwrap();
        let first = acquire_instance_lock(dir.path()).expect("first instance acquires the lock");
        assert!(
            acquire_instance_lock(dir.path()).is_err(),
            "a second instance must be refused while the first holds the lock",
        );
        // Releasing the first lets a later instance acquire it.
        drop(first);
        assert!(acquire_instance_lock(dir.path()).is_ok());
    }
}
