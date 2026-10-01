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
//!
//! It also holds the ONE reader both drivers take their root anchor through
//! ([`read_root_anchor`]). Each driver used to carry its own copy of the custody check, saying it
//! was duplicated because "there is no library here to hold one copy in" — while both already
//! included this file for exactly that purpose.

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
    match floor_verdict(&cfg) {
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

/// The floor's verdict over the deployment `cfg` describes, as a value — [`verify_tcb`] only prints
/// it. The principal set is resolved FIRST and a set the config does not state whole is the refusal:
/// measuring against what was left of it would be a floor asked about fewer parties than the
/// deployment has.
fn floor_verdict(cfg: &Value) -> Result<(), String> {
    let (principals, login_uid) = principals(cfg)?;
    brops_broker::tcb_probe::verify_deployment_tcb(
        pin_manifest_path(cfg).as_deref(),
        &principals,
        login_uid,
    )
}

/// The floor's principal set as the kit's config states it: `(runtime uids + the login uid, the
/// login uid)`. ONE definition, used by the root-side floor above and by
/// [`anchor_is_floor_pinned`] below, so the two cannot test against different principals.
///
/// The floor's question is whether any LOGIN or RUNTIME principal can write a TCB artifact.
/// Root evaluates the whole floor, so `getuid()` there is 0 and would be a meaningless "login
/// uid" — the deployment's real login user is passed in config, and the runtime uids are the
/// service accounts. Root itself is a TCB owner, not an untrusted principal.
///
/// **Every refusal here is a refusal of the floor.** This used to be infallible: a `uids` value
/// that was not an integer was dropped (`filter_map`), a missing `uids` block became the empty set
/// (`unwrap_or_default`), an absent `login_uid` became the sentinel `u32::MAX`, and an
/// out-of-range number was truncated by `as u32`. Each of those REMOVES a principal from the set
/// the floor asks "can this party write a TCB artifact?" about, and a floor asked about nobody
/// passes. The set must be stated whole or the floor is not evaluated at all.
fn principals(cfg: &Value) -> Result<(Vec<u32>, u32), String> {
    /// One uid, as a JSON integer inside the range a real uid can take. `u32::MAX` is `(uid_t)-1`,
    /// which no account has and which this file used to use as "no login uid".
    fn uid(v: &Value, what: &str) -> Result<u32, String> {
        v.as_u64()
            .and_then(|u| u32::try_from(u).ok())
            .filter(|u| *u != u32::MAX)
            .ok_or_else(|| format!("{what} is {v}, which is not a uid"))
    }
    let block = cfg
        .get("uids")
        .and_then(Value::as_object)
        .ok_or_else(|| "the config has no `uids` block naming the runtime principals".to_string())?;
    let mut principals = Vec::with_capacity(block.len() + 1);
    for (name, value) in block {
        let u = uid(value, &format!("`uids.{name}`"))?;
        if !principals.contains(&u) {
            principals.push(u);
        }
    }
    if principals.is_empty() {
        return Err("the config's `uids` block names no runtime principal".to_string());
    }
    let login_uid = uid(
        cfg.get("login_uid")
            .ok_or_else(|| "the config states no `login_uid`".to_string())?,
        "`login_uid`",
    )?;
    if !principals.contains(&login_uid) {
        principals.push(login_uid);
    }
    Ok((principals, login_uid))
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
    let (principals, login_uid) = principals(cfg)?;
    brops_broker::tcb_probe::anchor_bytes_are_floor_pinned(
        pin_manifest_path(cfg).as_deref(),
        &principals,
        login_uid,
        anchor_bytes,
    )
}

/// Read the root trust anchor a driver's config names, under the §2.5 owner/mode floor for that
/// file (audit **F-17**): a regular, root-owned file with no group/other write bit, no larger than
/// an anchor document can be.
///
/// **One descriptor.** The custody facts are an `fstat` of the handle the bytes are then read
/// from, opened `O_NOFOLLOW`. Each driver used to call a checker that opened the file, `fstat`ed
/// it and DROPPED the handle, and then read the anchor with `std::fs::read_to_string(path)` — a
/// second resolution of the path, which follows a symlink at the final component. The check was
/// about one inode and the bytes could be another's, so "checked on the opened fd" was true only
/// of a descriptor nobody read. This is the shape `brops_broker::tcb_probe::read_pin_manifest_checked`
/// already uses for the pin manifest.
///
/// The error is a fixed name: the drivers build `root_anchor_<name>` out of it, and a kit asserts
/// on that string.
pub fn read_root_anchor(path: &str) -> Result<Vec<u8>, &'static str> {
    read_anchor_owned_by(path, 0)
}

/// [`read_root_anchor`] with the required owner as an argument. Every caller passes root; it is a
/// parameter only so the tests below, which do not run as root, drive the SAME code against a file
/// they own.
fn read_anchor_owned_by(path: &str, owner_uid: u32) -> Result<Vec<u8>, &'static str> {
    use std::io::Read;
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};

    // `O_NONBLOCK` so a FIFO planted at the path is opened (and then refused as not regular)
    // instead of blocking this process until somebody writes to it. It changes nothing for a
    // regular file.
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
        .map_err(|_| "unopenable")?;
    // `File::metadata` is an `fstat` of this descriptor — never a second look at the path.
    let md = file.metadata().map_err(|_| "unstatable")?;
    if !md.is_file() {
        return Err("not_regular");
    }
    if md.uid() != owner_uid {
        return Err("not_root_owned");
    }
    if md.mode() & 0o022 != 0 {
        return Err("writable");
    }
    let limit = brops_broker::tcb::MAX_ROOT_ANCHOR_BYTES;
    let mut bytes = Vec::new();
    file.take(limit as u64 + 1).read_to_end(&mut bytes).map_err(|_| "unreadable")?;
    if bytes.len() > limit {
        return Err("too_large");
    }
    Ok(bytes)
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
        let (mut all, login) = principals(&cfg).expect("a whole principal set");
        all.sort_unstable();
        assert_eq!(login, 1000);
        assert_eq!(all, vec![1000, 5001, 5006], "the login uid must be a measured principal");

        // A login uid that is ALSO a runtime uid is one principal, not two.
        let cfg = json!({"uids": {"broker": 5001}, "login_uid": 5001});
        assert_eq!(principals(&cfg), Ok((vec![5001], 5001)));
        // uid 0 is a uid. (The kits pass it when they are run by root with no `SUDO_USER`.)
        let cfg = json!({"uids": {"broker": 5001}, "login_uid": 0});
        assert_eq!(principals(&cfg), Ok((vec![5001, 0], 0)));
    }

    /// A principal the config fails to state is a party the floor never asks about. Every one of
    /// these used to yield a SMALLER set and a floor that was then evaluated against it — the
    /// last three an empty one.
    #[test]
    fn a_principal_set_that_is_not_stated_whole_is_refused_never_shrunk() {
        for (what, cfg) in [
            ("a string uid", json!({"uids": {"broker": "5001", "signer": 5006}, "login_uid": 1000})),
            ("a negative uid", json!({"uids": {"broker": -1}, "login_uid": 1000})),
            ("a fractional uid", json!({"uids": {"broker": 5001.5}, "login_uid": 1000})),
            ("a uid past u32", json!({"uids": {"broker": 4294967296u64}, "login_uid": 1000})),
            ("(uid_t)-1", json!({"uids": {"broker": 4294967295u64}, "login_uid": 1000})),
            ("a null uid", json!({"uids": {"broker": null}, "login_uid": 1000})),
            ("no login uid", json!({"uids": {"broker": 5001}})),
            ("a string login uid", json!({"uids": {"broker": 5001}, "login_uid": "1000"})),
            ("a login uid past u32", json!({"uids": {"broker": 5001}, "login_uid": 4294967296u64})),
            ("an empty uids block", json!({"uids": {}, "login_uid": 1000})),
            ("uids that is not an object", json!({"uids": [5001], "login_uid": 1000})),
            ("no uids block", json!({"login_uid": 1000})),
        ] {
            assert!(principals(&cfg).is_err(), "{what} produced {:?}", principals(&cfg));
        }
        // The refusal names what is wrong, so a job log says which key to fix.
        let why = principals(&json!({"uids": {"signer": "5006"}, "login_uid": 1000})).unwrap_err();
        assert!(why.contains("`uids.signer`") && why.contains("not a uid"), "{why}");
        let why = principals(&json!({"uids": {"broker": 5001}})).unwrap_err();
        assert!(why.contains("`login_uid`"), "{why}");
    }

    /// The root-side floor refuses on such a config FOR THAT REASON, before it looks for a pin
    /// manifest. Asserted on the reason and not on the exit status: neither config here names a pin
    /// manifest, so a floor that fell through with the shrunken set would refuse too — one line
    /// later, for a reason that says nothing about the principals.
    #[test]
    fn the_root_side_floor_refuses_a_principal_set_that_is_not_whole_by_that_name() {
        let why = floor_verdict(&json!({"uids": {}, "login_uid": 1000})).unwrap_err();
        assert!(why.contains("names no runtime principal"), "{why}");
        let why = floor_verdict(&json!({"uids": {"broker": "5001"}, "login_uid": 1000})).unwrap_err();
        assert!(why.contains("`uids.broker`"), "{why}");
        // The control: a whole set gets as far as the pin manifest, which this config does not name.
        let why = floor_verdict(&json!({"uids": {"broker": 5001}, "login_uid": 1000})).unwrap_err();
        assert!(why.contains("no TCB pin manifest configured"), "{why}");

        // And `verify_tcb` turns any of them into a non-zero exit.
        let dir = scratch_dir("principals");
        let config = dir.join("config.json");
        std::fs::write(&config, br#"{"uids": {}, "login_uid": 1000}"#).unwrap();
        assert_eq!(verify_tcb("test", config.to_str().unwrap()), 1);
        let _ = std::fs::remove_dir_all(&dir);
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
        let whole = json!({"uids": {"broker": 5001}, "login_uid": 1000});
        let why = anchor_is_floor_pinned(&whole, b"{}").unwrap_err();
        assert!(why.contains("no TCB pin manifest configured"), "{why}");
        let cfg = json!({
            "uids": {"broker": 5001}, "login_uid": 1000,
            "trust": {"tcb_pin_manifest_path": "/nonexistent/pin.json"},
        });
        let why = anchor_is_floor_pinned(&cfg, b"{}").unwrap_err();
        assert!(why.contains("cannot be opened"), "{why}");
        // ...and with no principal set to measure against, the answer is no as well.
        let why = anchor_is_floor_pinned(&json!({"uids": {}}), b"{}").unwrap_err();
        assert!(why.contains("names no runtime principal"), "{why}");
    }

    // ---- the anchor reader ---------------------------------------------------------------------

    /// A private scratch directory. This file is compiled into BOTH driver binaries and their test
    /// runs overlap, so the name carries the pid and a per-process counter.
    fn scratch_dir(tag: &str) -> std::path::PathBuf {
        static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
        let n = NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let dir = std::env::temp_dir()
            .join(format!("brops-tcb-verify-{tag}-{}-{n}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write_mode(path: &std::path::Path, bytes: &[u8], mode: u32) {
        use std::os::unix::fs::PermissionsExt;
        std::fs::write(path, bytes).unwrap();
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).unwrap();
    }

    fn me() -> u32 {
        // SAFETY: getuid never fails and touches no memory.
        unsafe { libc::getuid() }
    }

    #[test]
    fn the_reader_returns_the_bytes_of_the_file_whose_custody_it_checked() {
        let dir = scratch_dir("reader-ok");
        let anchor = dir.join("root-anchor.json");
        write_mode(&anchor, br#"{"root_key_id":"r"}"#, 0o644);
        assert_eq!(
            read_anchor_owned_by(anchor.to_str().unwrap(), me()),
            Ok(br#"{"root_key_id":"r"}"#.to_vec())
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// The one that names the defect: a symlink at the anchor path. The old sequence checked the
    /// link's TARGET (`File::open` follows it) and then read through the link again by path; this
    /// reader does not follow it at all.
    #[test]
    fn a_symlink_at_the_anchor_path_is_not_followed() {
        let dir = scratch_dir("reader-symlink");
        let real = dir.join("real.json");
        write_mode(&real, b"{}", 0o644);
        let link = dir.join("root-anchor.json");
        std::os::unix::fs::symlink(&real, &link).unwrap();
        // The control: the target itself is readable under this rule...
        assert!(read_anchor_owned_by(real.to_str().unwrap(), me()).is_ok());
        // ...and the link to it is refused.
        assert_eq!(read_anchor_owned_by(link.to_str().unwrap(), me()), Err("unopenable"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_reader_refuses_by_the_name_of_what_is_wrong() {
        let dir = scratch_dir("reader-refusals");
        let path = |name: &str| dir.join(name).to_str().unwrap().to_string();

        assert_eq!(read_anchor_owned_by(&path("absent.json"), me()), Err("unopenable"));
        // A directory opens read-only and is then not a regular file.
        assert_eq!(read_anchor_owned_by(dir.to_str().unwrap(), me()), Err("not_regular"));

        write_mode(&dir.join("mine.json"), b"{}", 0o644);
        // Owned by somebody other than the required owner. Through the public entry that owner is
        // root, so — run as anyone but root — a file this test wrote is refused by it.
        assert_eq!(
            read_anchor_owned_by(&path("mine.json"), me().wrapping_add(1)),
            Err("not_root_owned")
        );
        if me() != 0 {
            assert_eq!(read_root_anchor(&path("mine.json")), Err("not_root_owned"));
        }

        for mode in [0o664, 0o646, 0o666] {
            write_mode(&dir.join("writable.json"), b"{}", mode);
            assert_eq!(
                read_anchor_owned_by(&path("writable.json"), me()),
                Err("writable"),
                "mode {mode:o}"
            );
        }

        // One byte past what an anchor document can be is refused; exactly at the limit is read.
        let limit = brops_broker::tcb::MAX_ROOT_ANCHOR_BYTES;
        write_mode(&dir.join("big.json"), &vec![b' '; limit + 1], 0o644);
        assert_eq!(read_anchor_owned_by(&path("big.json"), me()), Err("too_large"));
        write_mode(&dir.join("big.json"), &vec![b' '; limit], 0o644);
        assert_eq!(read_anchor_owned_by(&path("big.json"), me()).map(|b| b.len()), Ok(limit));
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ---- both drivers, read as source ----------------------------------------------------------
    //
    // `run()` in each driver needs a root-owned deployment, so no test here can call it. What CAN
    // be decided from the text is which code the drivers call — and the two defects these pin were
    // both a driver doing a step itself instead of calling the shared one.

    /// A driver's code above its first test module, with full-line comments removed, so prose
    /// that describes the old code cannot satisfy or break an assertion about the new.
    fn driver_code(source: &str) -> String {
        let code: String = source
            .lines()
            .filter(|l| !l.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");
        let code = code.split("#[cfg(test)]").next().unwrap_or(&code).to_string();
        assert!(code.contains("pub fn run("), "the stripper removed the driver's run()");
        code
    }

    fn drivers() -> [(&'static str, String); 2] {
        [
            ("ladder_turn", driver_code(include_str!("bin/ladder_turn.rs"))),
            ("live_turn", driver_code(include_str!("bin/live_turn.rs"))),
        ]
    }

    #[test]
    fn both_drivers_take_the_anchor_bytes_from_the_descriptor_whose_custody_was_checked() {
        for (name, code) in drivers() {
            assert_eq!(
                code.matches("tcb_verify::read_root_anchor(&anchor_path)").count(),
                1,
                "{name} does not read its anchor through the one checked reader"
            );
            for second_open in ["read_to_string(&anchor_path)", "fs::read(&anchor_path)", "File::open("] {
                assert!(
                    !code.contains(second_open),
                    "{name} opens a file itself (`{second_open}`): the anchor's custody is checked \
                     on one descriptor and its bytes must come from that same one"
                );
            }
            assert!(
                !code.contains("fn anchor_file_is_tcb_owned"),
                "{name} carries its own copy of the anchor custody check again"
            );
        }
    }

    /// Neither driver resolves a pinned key itself. `live_turn` took the supervisor attestation
    /// key with a bare `manifest.keys.iter().find(..)` on the key id — no trust class, no
    /// revocation, no validity window — while resolving the signer key properly two lines above.
    #[test]
    fn neither_driver_looks_a_pinned_key_up_in_the_manifest_itself() {
        for (name, code) in drivers() {
            assert_eq!(
                code.matches("resolve_production_key_pair(").count(),
                1,
                "{name} does not resolve its two pinned keys through the shared function"
            );
            for own_lookup in [".keys.iter()", "resolve_production_key("] {
                assert!(
                    !code.contains(own_lookup),
                    "{name} resolves a manifest key itself (`{own_lookup}`); both pinned keys go \
                     through `brops_broker::manifest_resolver::resolve_production_key_pair`"
                );
            }
        }
    }
}
