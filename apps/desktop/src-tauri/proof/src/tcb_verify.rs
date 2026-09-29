//! The root-side §2.5 TCB integrity floor entry point (audit **F-10**), shared by BOTH kit drivers.
//!
//! `live_turn --verify-tcb` was the only way either live kit could evaluate the floor, and it was
//! private to that binary. The §4.10(g) ladder kit never installs `live_turn`, so until 2026-09-29 it
//! had no floor at all. This file is included by `live_turn.rs` and `ladder_turn.rs` through
//! `#[path]` rather than copied into each, because two copies of the principal set are how one
//! driver comes to evaluate a weaker floor than the other with nobody saying so.
//!
//! Deliberately a SEPARATE entry point run by root before any service starts, rather than a step
//! inside the turn. The pinned set includes artifacts the serving principals must not be able to
//! read — the setuid launcher is mode 4750 so only the recorder group may execute it, and the sudo
//! allowlist lives in a root-only directory. A broker that could measure those could also read them,
//! so asking it to would mean loosening the very containment the floor exists to confirm. Root can
//! see the whole TCB; it is the only principal that can honestly evaluate it, and it does so once,
//! at deployment time, before anything is started.
//!
//! The floor itself is `brops_broker::tcb_probe::verify_deployment_tcb`. Nothing here re-implements
//! any part of it; this only reads which manifest and which principals from the kit's config.

use serde_json::Value;

/// Evaluate the floor over the deployment `config_path` describes. `driver` names the binary in
/// every line printed, so a refusal in a job log says which kit's floor refused.
pub fn verify_tcb(driver: &str, config_path: &str) -> i32 {
    let cfg: Value = match std::fs::read_to_string(config_path)
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
    {
        Some(v) => v,
        None => {
            eprintln!("{driver} --verify-tcb: config unreadable or malformed");
            return 1;
        }
    };
    // The floor's question is whether any LOGIN or RUNTIME principal can write a TCB artifact.
    // Root evaluates it, so `getuid()` here is 0 and would be a meaningless "login uid" — the
    // deployment's real login user is passed in config, and the runtime uids are the service
    // accounts. Root itself is a TCB owner, not an untrusted principal.
    let runtime_uids: Vec<u32> = cfg
        .get("uids")
        .and_then(|v| v.as_object())
        .map(|m| m.values().filter_map(|v| v.as_u64().map(|u| u as u32)).collect())
        .unwrap_or_default();
    let login_uid = cfg
        .get("login_uid")
        .and_then(Value::as_u64)
        .map(|u| u as u32)
        .unwrap_or(u32::MAX);
    let mut principals = runtime_uids;
    if login_uid != u32::MAX && !principals.contains(&login_uid) {
        principals.push(login_uid);
    }
    let manifest_path = cfg
        .get("trust")
        .and_then(|t| t.get("tcb_pin_manifest_path"))
        .and_then(Value::as_str)
        .map(str::to_string);
    match brops_broker::tcb_probe::verify_deployment_tcb(
        manifest_path.as_deref(),
        &principals,
        login_uid,
    ) {
        Ok(()) => {
            println!("RESULT: tcb_integrity_floor verified artifacts=pinned");
            0
        }
        Err(why) => {
            eprintln!("{driver} --verify-tcb: TCB integrity floor REFUSED: {why}");
            println!("RESULT: tcb_integrity_floor REFUSED {why}");
            1
        }
    }
}
