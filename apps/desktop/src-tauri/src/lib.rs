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
/// applied by `brops_core::engine_trust::apply` to the child process that runs the engine, at
/// the one seam that launches it (`brops_core::governed_sidecar::GovernedSidecar`, which the
/// app reaches through `ai::governed_sidecar_call`). It is still not exported into
/// THIS process: `std::env::set_var` is process-wide and racy, and the host has no
/// business verifying against a trust root it also holds the keys for.
///
/// The second reason the old comment gave is real and survives: `_resolve_operator_root_pin`
/// hard-fails when a file pin and the CI `BRO_OPERATOR_ROOT_PUBKEY` disagree, so the export
/// is not unconditional. `engine_trust` states the precedence rule — whole-set or nothing,
/// agreement permitted, disagreement refused by name in both directions — and that module's
/// documentation is where it is argued rather than here.
/// Move aside a machine anchor whose trust store no longer exists, so a REINSTALL can start.
///
/// The two halves live in different places on purpose — the anchor under `%ProgramData%`, the key
/// store under `%APPDATA%` — and the uninstaller removes only the second. So the next install found
/// the anchor, took it as "this machine is already provisioned", went to verify the store, and
/// aborted on a file that no longer exists:
///
/// ```text
/// trust provisioning failed while re-hashing a provisioned file
/// (…\studio.menq.brops\trust\POSTURE.txt): The system cannot find the path specified
/// ```
///
/// The app then panicked in the setup hook and the window closed before anything could be read, so
/// the only symptom was "it opens and shuts". Every reinstall on every machine hits this.
///
/// **The condition is narrow, and that is the whole of its safety.** An anchor is retired only when
/// the trust directory is **entirely absent** — an uninstall. A store that is PRESENT but whose
/// files were deleted or edited is left exactly as it was, and provisioning still refuses it by
/// name: that is tampering, and `provision.rs` has tests pinning that refusal.
///
/// Nothing is deleted. The anchor is renamed with a timestamp, so a machine that hits this by some
/// other route still has its old material to look at.
fn retire_orphaned_anchor(machine_root: &std::path::Path, app_data_dir: &std::path::Path) {
    let anchor_dir = machine_root.join("trust-anchor");
    let store_dir = app_data_dir.join("trust");
    let has_anchor = anchor_dir.join("PROVISIONING.json").is_file();
    let has_store = store_dir.exists();

    // Both present, or both absent: nothing to reconcile. Both present is the normal case and
    // provisioning verifies it properly; both absent is a genuine first launch and it mints.
    if has_anchor == has_store {
        return;
    }

    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    // Exactly one of the two halves is here, so whichever it is cannot be checked against anything
    // and cannot be used. Move that one aside; the pair is then re-minted together.
    let (from, to, why) = if has_anchor {
        (
            anchor_dir.clone(),
            machine_root.join(format!("trust-anchor.orphaned-{stamp}")),
            "named a key store that no longer exists",
        )
    } else {
        (
            store_dir.clone(),
            app_data_dir.join(format!("trust.orphaned-{stamp}")),
            "has no anchor to verify it against",
        )
    };
    match std::fs::rename(&from, &to) {
        Ok(()) => eprintln!(
            "BroPS: {} {why}, which is what a half-removed install leaves behind. It has been moved \
             to {} and a fresh pair will be minted. Nothing was deleted.",
            from.display(),
            to.display()
        ),
        // Not fatal here: provisioning refuses a moment later with its own message, which names the
        // file and the reason. Failing here would replace a precise refusal with a vague one.
        Err(e) => eprintln!(
            "BroPS: could not retire {}: {e}. Provisioning will refuse below and say why.",
            from.display()
        ),
    }
}

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
    retire_orphaned_anchor(&root, dir);
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

/// Where the development build keeps its one-line project file — beside the app's own data, never
/// inside a repository, so a checkout can never carry somebody else's grant to a different machine.
#[cfg(feature = "dev-ungoverned")]
fn dev_config_dir() -> Option<std::path::PathBuf> {
    std::env::var_os("APPDATA")
        .map(std::path::PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| std::path::PathBuf::from(h).join(".config")))
        .map(|p| p.join("brops"))
}

/// The folder this build lets the agent work in — chosen automatically on first launch.
///
/// The install has to work the same on the thousandth machine as on the first, so there is no
/// question to answer and no file to edit: the app creates its own workspace and uses that.
///
/// **`~/BroPS`, and it is not an arbitrary pick.** It is the workspace this application already
/// defines for itself — the same default the Files surface is confined to (`BROPS_FILES_ROOT`,
/// `apps/desktop/SECURITY.md`). Using it means the agent's reach and the file browser's reach are
/// the same folder, which is one thing to reason about rather than two, and it is a directory the
/// app made rather than one that already had somebody's work in it.
///
/// The value is written to `project-dir.txt` on first use, so it is visible and editable: point that
/// line anywhere else and the app follows it. `BROPS_PROJECT_DIR` still overrides both.
#[cfg(feature = "dev-ungoverned")]
fn dev_project_dir() -> Option<String> {
    let config = dev_config_dir()?;
    let record = config.join("project-dir.txt");

    // An existing line wins — that is how this gets pointed at a real repository.
    if let Ok(text) = std::fs::read_to_string(&record) {
        if let Some(dir) = text
            .lines()
            .map(str::trim)
            .find(|l| !l.is_empty() && !l.starts_with('#') && std::path::Path::new(l).is_dir())
        {
            return Some(dir.to_string());
        }
    }

    let home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(std::path::PathBuf::from)?;
    let workspace = home.join("BroPS");
    std::fs::create_dir_all(&workspace).ok()?;
    let dir = workspace.to_string_lossy().into_owned();

    let _ = std::fs::create_dir_all(&config);
    let _ = std::fs::write(
        &record,
        format!(
            "# The folder Bro may READ, EDIT, WRITE and run commands in.\r\n\
             #\r\n\
             # Created automatically on first launch. To work somewhere else, replace the path\r\n\
             # below with an absolute path of your own and restart BroPS.\r\n\
             # Blank it to turn the agent off and leave chat working.\r\n\
             {dir}\r\n"
        ),
    );
    Some(dir)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // DEVELOPMENT BUILD ONLY (`--features dev-ungoverned`). Compiled out entirely otherwise.
    //
    // `resolve_provider` is deliberately fail-closed: with nothing set it refuses rather than
    // quietly running an ungoverned model, and that refusal is what the shipped binary does. This
    // does not weaken it -- it supplies the same explicit opt-in the refusal asks for, at the point
    // where the owner chose to install a binary whose file name says `dev-ungoverned`.
    //
    // Set BEFORE the builder, because `provider_env()` reads the process environment on first use.
    // It never selects the metered remote provider: an ambient ANTHROPIC_API_KEY still requires an
    // explicit BROPS_AI_PROVIDER=anthropic, so the default here is the LOCAL sandboxed CLI.
    #[cfg(feature = "dev-ungoverned")]
    // SAFETY: single-threaded startup, before any thread that could read the environment exists.
    unsafe {
        std::env::set_var("BROPS_ALLOW_UNGOVERNED", "1");

        // AGENT MODE. `ai.rs` turns the coding agent on from one fact — `bro_agent_dir().is_some()`,
        // i.e. `BROPS_PROJECT_DIR` naming a real directory — and with it a turn gets
        // Read/Edit/Write/Grep/Glob/Bash/Task under `--permission-mode acceptEdits`.
        //
        // Nothing in the UI sets it (`BROPS_PROJECT_DIR` appears in no `.ts`/`.tsx`), so a fresh
        // install on another machine had nothing at all and the agent stayed off. This build
        // remembers the folder per machine and, when it has none, ASKS (see `setup` below) — so the
        // thousandth install needs the same two clicks as the first and no second setup step.
        //
        // An explicitly-set environment variable still wins: it is how a scripted or headless
        // install points the agent at a tree without a person at the screen.
        if std::env::var_os("BROPS_PROJECT_DIR").is_none() {
            if let Some(dir) = dev_project_dir() {
                std::env::set_var("BROPS_PROJECT_DIR", dir);
            }
        }
    }

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
            commands::save_ask_to_knowledge,
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

/// Half-removed installs — the state an uninstall leaves and the state the first fix for it left.
///
/// The Owner found both of these by installing the app, in that order, minutes apart. Neither is
/// reachable from a test that mounts a component: the first needs an uninstall to have happened, and
/// the second needs the first fix to have run. What makes them testable at all is that
/// `retire_orphaned_anchor` takes both roots as parameters instead of reading `%ProgramData%` and
/// `%APPDATA%` itself — so the pair can be built in a temp directory and driven from either side.
#[cfg(test)]
mod half_removed_install {
    use super::retire_orphaned_anchor;

    /// Build a machine root + app data dir with whichever halves are asked for.
    fn scene(anchor: bool, store: bool) -> (tempfile::TempDir, std::path::PathBuf, std::path::PathBuf) {
        let tmp = tempfile::tempdir().unwrap();
        let machine = tmp.path().join("ProgramData");
        let app = tmp.path().join("AppData");
        std::fs::create_dir_all(&machine).unwrap();
        std::fs::create_dir_all(&app).unwrap();
        if anchor {
            let dir = machine.join("trust-anchor");
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(dir.join("PROVISIONING.json"), b"{}").unwrap();
        }
        if store {
            let dir = app.join("trust");
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(dir.join("POSTURE.txt"), b"posture").unwrap();
        }
        (tmp, machine, app)
    }

    fn names(dir: &std::path::Path, prefix: &str) -> Vec<String> {
        let mut out: Vec<String> = std::fs::read_dir(dir)
            .unwrap()
            .filter_map(Result::ok)
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.starts_with(prefix))
            .collect();
        out.sort();
        out
    }

    /// The uninstall case. The uninstaller removes the key store and leaves the anchor, so the next
    /// launch verified a store that was gone and panicked in the setup hook — the window closed
    /// before the message could be read, and the only symptom was "it opens and shuts".
    #[test]
    fn an_anchor_whose_key_store_is_gone_is_retired_rather_than_verified() {
        let (_tmp, machine, app) = scene(true, false);
        retire_orphaned_anchor(&machine, &app);

        assert!(!machine.join("trust-anchor").exists(), "the orphaned anchor must not still be live");
        let retired = names(&machine, "trust-anchor.orphaned-");
        assert_eq!(retired.len(), 1, "exactly one retired anchor, got {retired:?}");
        // Moved, never deleted: a machine that reached this state by some other route keeps its
        // material to look at.
        assert!(machine.join(&retired[0]).join("PROVISIONING.json").is_file());
    }

    /// The mirror case, which the first fix for the one above created. Retiring the anchor left a
    /// `trust` directory with nothing to verify it against, and provisioning refused THAT instead —
    /// the Owner hit it minutes later. A fix for one direction of a symmetric fault is half a fix.
    #[test]
    fn a_key_store_with_no_anchor_is_retired_too() {
        let (_tmp, machine, app) = scene(false, true);
        retire_orphaned_anchor(&machine, &app);

        assert!(!app.join("trust").exists(), "the orphaned store must not still be live");
        let retired = names(&app, "trust.orphaned-");
        assert_eq!(retired.len(), 1, "exactly one retired store, got {retired:?}");
        assert!(app.join(&retired[0]).join("POSTURE.txt").is_file());
    }

    /// Both halves present is the normal case, and it must be left completely alone — this is where
    /// a real verification happens, and where TAMPERING is caught. A retirement here would turn
    /// "somebody edited a provisioned file" into "mint a fresh one", which is the refusal
    /// `provision.rs` has tests pinning.
    #[test]
    fn a_complete_pair_is_never_touched_even_though_it_may_be_tampered() {
        let (_tmp, machine, app) = scene(true, true);
        // A store whose file was altered still has BOTH halves; deciding it is tamper or not is the
        // verifier's job, not this function's.
        std::fs::write(app.join("trust").join("POSTURE.txt"), b"altered").unwrap();
        retire_orphaned_anchor(&machine, &app);

        assert!(machine.join("trust-anchor").exists(), "anchor must survive");
        assert!(app.join("trust").exists(), "store must survive for the verifier to judge");
        assert!(names(&machine, "trust-anchor.orphaned-").is_empty());
        assert!(names(&app, "trust.orphaned-").is_empty());
    }

    /// Neither half present is a genuine first launch. Nothing to retire, and nothing created — the
    /// mint that follows is what makes the directories.
    #[test]
    fn a_first_launch_is_left_to_mint() {
        let (_tmp, machine, app) = scene(false, false);
        retire_orphaned_anchor(&machine, &app);

        assert!(names(&machine, "trust-anchor").is_empty());
        assert!(names(&app, "trust").is_empty());
    }
}
