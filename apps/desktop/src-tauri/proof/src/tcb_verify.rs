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
    let (principals, login_uid) = principals(&cfg);
    let manifest_path = pin_manifest_path(&cfg);
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

/// The floor's principal set as the kit's config states it: `(runtime uids + the login uid, the
/// login uid)`. ONE definition, used by the root-side floor above and by
/// [`anchor_is_floor_pinned`] below, so the two cannot test against different principals.
///
/// The floor's question is whether any LOGIN or RUNTIME principal can write a TCB artifact.
/// Root evaluates the whole floor, so `getuid()` there is 0 and would be a meaningless "login
/// uid" — the deployment's real login user is passed in config, and the runtime uids are the
/// service accounts. Root itself is a TCB owner, not an untrusted principal.
fn principals(cfg: &Value) -> (Vec<u32>, u32) {
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
    (principals, login_uid)
}

fn pin_manifest_path(cfg: &Value) -> Option<String> {
    cfg.get("trust")
        .and_then(|t| t.get("tcb_pin_manifest_path"))
        .and_then(Value::as_str)
        .map(str::to_string)
}

/// Is `anchor_bytes` — the anchor document a driver read from the path ITS CONFIG names — the root
/// anchor the §2.5 pin manifest pins?
///
/// A driver asks this only when the anchor declares `install_minted`
/// (`brops_broker::tcb::check_declared_install_minted_anchor`). That word is the one provenance
/// that can ever support a production claim on Linux, so a driver must not take it from a file it
/// merely found root-owned: the label is earned by where the file sits and who can write it. A
/// driver cannot run the whole floor in a turn (the reason is at the top of this file), but it CAN
/// measure this one artifact — owner, writability, digest, every ancestor — because every serving
/// principal may read the anchor. Nothing here re-implements that check:
/// `brops_broker::tcb_probe::anchor_bytes_are_floor_pinned` is the one implementation.
pub fn anchor_is_floor_pinned(cfg: &Value, anchor_bytes: &[u8]) -> Result<(), String> {
    let (principals, login_uid) = principals(cfg);
    brops_broker::tcb_probe::anchor_bytes_are_floor_pinned(
        pin_manifest_path(cfg).as_deref(),
        &principals,
        login_uid,
        anchor_bytes,
    )
}

// Compiled into BOTH driver binaries (this file is `#[path]`-included by each), so these run once
// per binary. They are here because the principal set decides what the floor refuses, and until
// T-131 slice C nothing tested it: deleting the login uid from it passed every suite.
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn the_login_uid_is_one_of_the_floors_principals_and_is_not_listed_twice() {
        let cfg = json!({"uids": {"broker": 5001, "signer": 5006}, "login_uid": 1000});
        let (mut all, login) = principals(&cfg);
        all.sort_unstable();
        assert_eq!(login, 1000);
        assert_eq!(all, vec![1000, 5001, 5006], "the login uid must be a measured principal");

        // A login uid that is ALSO a runtime uid is one principal, not two.
        let cfg = json!({"uids": {"broker": 5001}, "login_uid": 5001});
        assert_eq!(principals(&cfg), (vec![5001], 5001));
    }

    #[test]
    fn a_config_naming_no_login_uid_adds_no_login_principal() {
        let (all, login) = principals(&json!({"uids": {"broker": 5001}}));
        assert_eq!(all, vec![5001]);
        assert_eq!(login, u32::MAX, "an absent login uid is the sentinel, never uid 0");
        assert_eq!(principals(&json!({})), (vec![], u32::MAX));
    }

    #[test]
    fn the_pin_manifest_is_the_one_the_config_names_or_none() {
        let cfg = json!({"trust": {"tcb_pin_manifest_path": "/opt/brops-live/tcb/pin.json"}});
        assert_eq!(pin_manifest_path(&cfg).as_deref(), Some("/opt/brops-live/tcb/pin.json"));
        assert_eq!(pin_manifest_path(&json!({"trust": {}})), None);
        assert_eq!(pin_manifest_path(&json!({"trust": {"tcb_pin_manifest_path": 7}})), None);
    }

    #[test]
    fn an_anchor_is_not_floor_pinned_when_the_config_names_no_pin_manifest() {
        // The refusal a driver turns into `root_anchor_install_minted_not_floor_pinned`: with
        // nothing to measure against, the answer is no — never "nothing to check, so yes".
        let why = anchor_is_floor_pinned(&json!({"uids": {}}), b"{}").unwrap_err();
        assert!(why.contains("no TCB pin manifest configured"), "{why}");
        let cfg = json!({"trust": {"tcb_pin_manifest_path": "/nonexistent/pin.json"}});
        let why = anchor_is_floor_pinned(&cfg, b"{}").unwrap_err();
        assert!(why.contains("unreadable or malformed"), "{why}");
    }
}
