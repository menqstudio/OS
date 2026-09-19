//! The REAL filesystem probe behind the §2.5 TCB-integrity floor (audit **F-10**).
//!
//! `brops_core::tcb_integrity` implements the whole fail-closed decision — owner, writability,
//! content pin, ancestor safety, coverage floor — as a pure function over an injected
//! [`FsProbe`](brops_core::tcb_integrity::FsProbe). It was fully implemented and fully unwired: the
//! only `FsProbe` in the tree was `FakeFs` inside its own `#[cfg(test)]` module, no
//! `TcbPinManifest` was ever constructed, and `verify_tcb_integrity` had no caller anywhere. So at
//! runtime nothing measured the supervisor / launcher / executor / signer / broker binaries, their
//! configs and IPC policies, the pinned-manifest configuration, the allowlist source, the key-manifest
//! root anchor, or the unit files before governed mode was entered — every downstream signature check
//! ran on binaries whose integrity had never been checked.
//!
//! This module is the missing half: a probe that reads the real filesystem, and the loader for the
//! root-owned pin manifest. It is Linux-only because owner/mode/`O_NOFOLLOW` are the facts the floor
//! is stated in; on any other host the caller fails closed instead.

use brops_core::tcb_integrity::TcbPinManifest;

/// Where the deployment's root-owned pin manifest lives. Absent ⇒ the caller stays fail-closed; the
/// floor is never "skipped because unconfigured" without that being the fail-closed branch.
pub const TCB_PIN_MANIFEST_ENV: &str = "BROPS_TCB_PIN_MANIFEST";

/// What the pin manifest FILE itself must be, before a word of it is believed.
///
/// Without this the floor is circular: a manifest an adversary can rewrite lets them re-pin the digests
/// of the binaries they just replaced, and every downstream signature check then runs against a pin the
/// attacker chose. The Windows twin has refused this since it was written
/// (`win-live/src/tcb_floor.rs::check_manifest_custody`); the Linux side read the manifest with a bare
/// `read_to_string` and asked nothing.
///
/// PURE over injected facts, so it runs on every host — the Linux reader below gathers the facts from an
/// `O_NOFOLLOW`-opened descriptor and reads the bytes through that SAME descriptor. `None` means the
/// custody is acceptable; `Some(reason)` is a refusal a caller logs before staying fail-closed.
///
/// The predicate is the floor's own, not a second one: `verify_tcb_integrity` treats an artifact owned
/// by a login or runtime UID as untrusted because an owner can always `chmod` itself write access, so
/// ownership by a measured party IS write access. The manifest is held to the same rule.
pub fn manifest_custody_violation(
    path: &str,
    owner_uid: u32,
    mode: u32,
    is_regular_file: bool,
    login_and_runtime_uids: &[u32],
    login_uid: u32,
) -> Option<String> {
    if !is_regular_file {
        return Some(format!("TCB pin manifest {path} is not a regular file"));
    }
    if owner_uid == login_uid || login_and_runtime_uids.contains(&owner_uid) {
        return Some(format!(
            "TCB pin manifest {path} is owned by uid {owner_uid}, a login or runtime principal — a \
             floor the measured parties can re-pin measures nothing"
        ));
    }
    if mode & 0o022 != 0 {
        return Some(format!(
            "TCB pin manifest {path} is group/other-writable (mode {:o})",
            mode & 0o7777
        ));
    }
    None
}

/// Parse the pin manifest, with NO custody check. `None` on unreadable or malformed.
///
/// Kept separate and named for what it is: the Linux path uses
/// [`read_pin_manifest_checked`] instead, and nothing should enter governed mode on this function's
/// word alone. It exists because the non-Linux branch of [`verify_deployment_tcb`] still has to be able
/// to say "malformed" rather than "platform" when the file is also broken.
pub fn load_pin_manifest(path: &str) -> Option<TcbPinManifest> {
    let raw = std::fs::read_to_string(path).ok()?;
    serde_json::from_str::<TcbPinManifest>(&raw).ok()
}

/// Read AND parse the pin manifest through one `O_NOFOLLOW` descriptor, with its custody checked on
/// that same descriptor before any byte is believed.
///
/// One path resolution, then everything through the fd: `File::metadata()` is an `fstat` of the open
/// handle, so the owner and mode belong to the inode whose bytes are then read. `O_NOFOLLOW` makes a
/// symlink at the final component an error rather than a redirect. This is the shape
/// `engine/ci/live/ipc_policy.py` already uses for the IPC peer-auth policy, a lower-authority input.
#[cfg(target_os = "linux")]
pub fn read_pin_manifest_checked(
    path: &str,
    login_and_runtime_uids: &[u32],
    login_uid: u32,
) -> Result<TcbPinManifest, String> {
    use std::io::Read;
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};

    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
        .map_err(|e| format!("TCB pin manifest {path} cannot be opened (O_NOFOLLOW): {e}"))?;
    let md = file
        .metadata()
        .map_err(|e| format!("TCB pin manifest {path}: fstat of the open descriptor failed: {e}"))?;
    if let Some(why) = manifest_custody_violation(
        path,
        md.uid(),
        md.mode(),
        md.is_file(),
        login_and_runtime_uids,
        login_uid,
    ) {
        return Err(why);
    }
    let mut raw = String::new();
    file.read_to_string(&mut raw)
        .map_err(|e| format!("TCB pin manifest {path} unreadable: {e}"))?;
    serde_json::from_str::<TcbPinManifest>(&raw)
        .map_err(|e| format!("TCB pin manifest {path} malformed: {e}"))
}

#[cfg(target_os = "linux")]
pub use linux::LinuxFsProbe;

#[cfg(target_os = "linux")]
mod linux {
    use brops_core::tcb_integrity::{FileFacts, FsProbe};
    use sha2::{Digest, Sha256};
    use std::ffi::CString;
    use std::os::unix::fs::MetadataExt;

    /// The real probe. ONE `O_NOFOLLOW` open per path, and both the owner/mode facts and the content
    /// digest are taken from that single descriptor — so a symlink or a replaced file between the two
    /// decisions cannot make them be about different inodes. This paragraph was here before the code
    /// did it: the digest used to come from a second `std::fs::read(path)`, which re-resolves the path
    /// and follows symlinks, and `FsProbe`'s own contract ("no symlink/path re-lookup — no TOCTOU") was
    /// false for exactly that field.
    pub struct LinuxFsProbe {
        /// The interactive login UID plus every runtime service UID. `writable_by_login_or_runtime`
        /// is decided against this set; the floor refuses any TCB artifact one of them can write.
        pub login_and_runtime_uids: Vec<u32>,
    }

    impl LinuxFsProbe {
        /// Content digest of the file the `O_PATH` descriptor already points at — never a second
        /// resolution of the path.
        ///
        /// This used to be `std::fs::read(path)`, which re-resolves the path AND follows symlinks: the
        /// bytes hashed need not have been the bytes stat'd, so the owner/mode decision and the digest
        /// decision could be about two different inodes. Both this module's own doc and `FsProbe`'s
        /// trait contract promised otherwise ("no symlink/path re-lookup — no TOCTOU").
        ///
        /// `/proc/self/fd/N` re-opens the SAME inode the `O_PATH` handle holds — that is the canonical
        /// way to upgrade an `O_PATH` descriptor to a readable one, and it resolves through the kernel's
        /// reference rather than through the path again. The device and inode are then compared, so
        /// "the same file" is measured rather than assumed; a mismatch yields the empty digest, which
        /// the floor treats as a hash mismatch and refuses.
        fn digest_through(fd: libc::c_int, st: &libc::stat) -> String {
            use std::io::Read;
            if st.st_mode & libc::S_IFMT != libc::S_IFREG {
                return String::new();
            }
            let mut file = match std::fs::File::open(format!("/proc/self/fd/{fd}")) {
                Ok(f) => f,
                Err(_) => return String::new(),
            };
            match file.metadata() {
                Ok(md) if md.dev() == st.st_dev && md.ino() == st.st_ino => {}
                _ => return String::new(),
            }
            let mut bytes = Vec::new();
            if file.read_to_end(&mut bytes).is_err() {
                return String::new();
            }
            let mut h = Sha256::new();
            h.update(&bytes);
            format!("{:x}", h.finalize())
        }
    }

    impl FsProbe for LinuxFsProbe {
        fn stat(&self, path: &str) -> Option<FileFacts> {
            // ONE path resolution, held open while both decisions are taken from it.
            let c = CString::new(path).ok()?;
            let fd = unsafe {
                libc::open(c.as_ptr(), libc::O_PATH | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            };
            if fd < 0 {
                return None;
            }
            let mut st: libc::stat = unsafe { std::mem::zeroed() };
            let rc = unsafe { libc::fstat(fd, &mut st) };
            if rc != 0 {
                unsafe { libc::close(fd) };
                return None;
            }
            let sha256 = Self::digest_through(fd, &st);
            unsafe { libc::close(fd) };
            let mode = st.st_mode;
            let world_or_group_writable = (mode & 0o022) != 0;
            // Writable by a login/runtime principal: either the world/group bits are open, or one of
            // those principals OWNS it (an owner can always chmod itself write access, so ownership by
            // an untrusted principal IS write access — the floor's question is authority, not the
            // current bit). POSIX ACLs beyond the mode bits are not read here; that is a known
            // narrowing, and it can only make the probe MORE permissive than reality, so it is stated
            // rather than hidden.
            let owner_uid = st.st_uid;
            let writable_by_login_or_runtime = world_or_group_writable
                || self.login_and_runtime_uids.iter().any(|u| *u == owner_uid);
            Some(FileFacts {
                owner_uid,
                is_world_or_group_writable: world_or_group_writable,
                writable_by_login_or_runtime,
                sha256,
            })
        }
    }
}

/// Run the §2.5 floor for a deployment, fail-closed. `Ok(())` means governed mode may be entered;
/// every other outcome — no manifest configured, unreadable, malformed, or any violation — is `Err`
/// with a human-readable reason the caller logs before refusing.
///
/// On a non-Linux host this always refuses: the floor is stated in owner/mode/`O_NOFOLLOW` facts that
/// do not exist there, and a floor that cannot be evaluated must not be reported as satisfied.
pub fn verify_deployment_tcb(
    manifest_path: Option<&str>,
    login_and_runtime_uids: &[u32],
    login_uid: u32,
) -> Result<(), String> {
    let path = manifest_path.ok_or_else(|| {
        format!("no TCB pin manifest configured ({TCB_PIN_MANIFEST_ENV} unset)")
    })?;
    #[cfg(target_os = "linux")]
    {
        // Read it through its own `O_NOFOLLOW` descriptor with its custody checked on that descriptor:
        // the manifest decides what the floor measures, so believing it before checking who owns it
        // would make the whole floor circular.
        let manifest = read_pin_manifest_checked(path, login_and_runtime_uids, login_uid)
            .map_err(|why| format!("TCB pin manifest unreadable or malformed: {why}"))?;
        let probe = LinuxFsProbe { login_and_runtime_uids: login_and_runtime_uids.to_vec() };
        brops_core::tcb_integrity::verify_tcb_integrity(
            &manifest,
            &probe,
            login_and_runtime_uids,
            login_uid,
        )
        .map_err(|v| format!("{v:?}"))
    }
    #[cfg(not(target_os = "linux"))]
    {
        // Parsed only so a broken file is reported as broken rather than as a platform problem; the
        // custody check needs `O_NOFOLLOW` and uid facts that do not exist here, so this host refuses
        // either way.
        let manifest = load_pin_manifest(path)
            .ok_or_else(|| format!("TCB pin manifest unreadable or malformed: {path}"))?;
        let _ = (&manifest, login_and_runtime_uids, login_uid);
        Err("TCB integrity floor requires Linux (owner/mode/O_NOFOLLOW facts)".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // The floor's VALUE is that it refuses. These pin the three ways a deployment can fail to
    // present one, because each of them used to be indistinguishable from "no floor at all".

    // ---- the pin manifest's own custody -----------------------------------------------------
    //
    // The floor is circular without this: a manifest an adversary can rewrite lets them re-pin the
    // digests of the binaries they just replaced. The Windows twin refuses it
    // (`win-live/src/tcb_floor.rs::check_manifest_custody`); the Linux side used to read the file with
    // `std::fs::read_to_string` and ask nothing at all.

    const ROOT: u32 = 0;
    const ADMIN: u32 = 500;
    const LOGIN: u32 = 1000;
    const RUNTIME: &[u32] = &[5001, 5004, 5006];

    #[test]
    fn a_tcb_owned_unwritable_manifest_is_accepted() {
        // 0o644: owner-writable only. The control case, or every refusal below could be an artefact of
        // the predicate refusing everything.
        assert_eq!(
            manifest_custody_violation("/opt/brops/tcb/pin.json", ROOT, 0o100644, true, RUNTIME, LOGIN),
            None
        );
        // A dedicated non-root TCB admin is equally acceptable: the rule is "not a measured party",
        // not "root".
        assert_eq!(
            manifest_custody_violation("/opt/brops/tcb/pin.json", ADMIN, 0o100600, true, RUNTIME, LOGIN),
            None
        );
    }

    #[test]
    fn a_manifest_owned_by_the_login_user_is_refused() {
        let why = manifest_custody_violation("/p", LOGIN, 0o100644, true, RUNTIME, LOGIN)
            .expect("a login-owned manifest must be refused");
        assert!(why.contains("login or runtime principal"), "{why}");
        assert!(why.contains(&LOGIN.to_string()), "{why}");
    }

    #[test]
    fn a_manifest_owned_by_any_runtime_service_is_refused() {
        // Each measured principal, not just the first: a rule that only checked one would leave the
        // other six able to re-pin themselves.
        for uid in RUNTIME {
            let why = manifest_custody_violation("/p", *uid, 0o100600, true, RUNTIME, LOGIN)
                .unwrap_or_else(|| panic!("uid {uid} was accepted as a manifest owner"));
            assert!(why.contains("login or runtime principal"), "{why}");
        }
    }

    #[test]
    fn a_group_or_other_writable_manifest_is_refused_even_when_tcb_owned() {
        // Ownership is not the only way to write a file.
        for mode in [0o100664u32, 0o100646, 0o100666, 0o100622] {
            let why = manifest_custody_violation("/p", ROOT, mode, true, RUNTIME, LOGIN)
                .unwrap_or_else(|| panic!("mode {mode:o} was accepted"));
            assert!(why.contains("group/other-writable"), "{why}");
        }
        // And the sticky/setuid bits are not write bits — a rule that masked too widely would refuse
        // an ordinary deployment and be switched off.
        assert_eq!(
            manifest_custody_violation("/p", ROOT, 0o104755, true, RUNTIME, LOGIN),
            None
        );
    }

    #[test]
    fn a_manifest_that_is_not_a_regular_file_is_refused() {
        // A directory, a fifo or a device at that path is not a manifest, and reading one is not a
        // thing to attempt before saying so.
        let why = manifest_custody_violation("/p", ROOT, 0o040755, false, RUNTIME, LOGIN)
            .expect("a non-regular manifest must be refused");
        assert!(why.contains("not a regular file"), "{why}");
    }

    #[test]
    fn the_refusal_always_names_the_path() {
        // A refusal that does not say WHICH file sends an operator to check the wrong one.
        for (uid, mode, regular) in [(LOGIN, 0o100600u32, true), (ROOT, 0o100666, true), (ROOT, 0o040755, false)] {
            let why = manifest_custody_violation("/opt/brops/tcb/pin.json", uid, mode, regular, RUNTIME, LOGIN)
                .expect("this case must refuse");
            assert!(why.contains("/opt/brops/tcb/pin.json"), "{why}");
        }
    }

    #[test]
    fn the_predicate_agrees_with_the_floor_it_guards() {
        // The floor treats ownership by a measured party as write access because an owner can chmod
        // itself write access (`core/src/tcb_integrity.rs`, the `owner_is_untrusted` arm). If the
        // manifest were held to a weaker rule than the artifacts it pins, the weakest link would be
        // the file that decides everything.
        assert!(manifest_custody_violation("/p", LOGIN, 0o100600, true, RUNTIME, LOGIN).is_some());
        assert!(manifest_custody_violation("/p", RUNTIME[0], 0o100600, true, RUNTIME, LOGIN).is_some());
        // ...and an empty principal set does not make everything acceptable: the login uid still is.
        assert!(manifest_custody_violation("/p", LOGIN, 0o100600, true, &[], LOGIN).is_some());
    }

    /// This file, with every full-line comment removed.
    ///
    /// The three tests below assert what the CODE does, and a first draft of them asserted what the
    /// prose says instead: `!contains("std::fs::read(path)")` failed on a doc comment explaining that
    /// the code no longer does that, and a call count counted the function's own signature. An
    /// assertion a comment can satisfy is an assertion about comments, so the comments are taken away
    /// before it is made.
    fn code_only(src: &str) -> String {
        // Everything before the test module, and then without full-line comments. Both narrowings are
        // there because a first draft was satisfied by its own text: once by a doc comment explaining
        // what the code no longer does, and once by the `assert!` line that forbids a literal and
        // therefore contains it. An assertion that can pass on itself asserts nothing.
        // ORDER MATTERS, and getting it wrong is the third way a draft of this was satisfied by its own
        // text: the module's opening doc comment contains the literal `#[cfg(test)]`, so splitting
        // before stripping cut the file at line 6 and left nothing to assert about. Comments first,
        // then the cut.
        let code: String = src
            .lines()
            .filter(|l| !l.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");
        code.split("#[cfg(test)]").next().unwrap_or(&code).to_string()
    }

    /// THE CHECKED READER IS ON THE PATH — asserted from the source, because this host cannot compile
    /// the `cfg(target_os = "linux")` block that contains it.
    ///
    /// Without this the custody predicate above could pass every test while nothing called it, which is
    /// the exact shape of a control that prevents nothing. `main.rs` already reads its own source this
    /// way for the same reason.
    #[test]
    fn the_linux_branch_reads_the_manifest_through_the_checked_reader() {
        let src = code_only(include_str!("tcb_probe.rs"));
        let verify = src
            .split("pub fn verify_deployment_tcb")
            .nth(1)
            .expect("verify_deployment_tcb is gone")
            .to_string();
        let linux = verify
            .split("#[cfg(not(target_os = \"linux\"))]")
            .next()
            .expect("the linux branch is gone")
            .to_string();

        assert!(
            linux.contains("read_pin_manifest_checked(path, login_and_runtime_uids, login_uid)"),
            "the Linux branch does not read the manifest through the checked reader:\n{linux}"
        );
        assert!(
            !linux.contains("load_pin_manifest("),
            "the Linux branch still calls the UNCHECKED loader, so the custody check can be bypassed \
             by the only caller that matters:\n{linux}"
        );

        // The unchecked loader still exists, and only for the host that refuses anyway.
        let non_linux = verify
            .split("#[cfg(not(target_os = \"linux\"))]")
            .nth(1)
            .expect("the non-linux branch is gone")
            .to_string();
        assert!(non_linux.contains("load_pin_manifest("), "{non_linux}");

        // Exactly one CALL SITE, counted over code with the definition line excluded. If it ever grows
        // a second caller, this fails and the reason has to be argued for in a diff.
        let calls = src
            .lines()
            .filter(|l| l.contains("load_pin_manifest(path)") && !l.contains("pub fn "))
            .count();
        assert_eq!(calls, 1, "the unchecked loader has {calls} call site(s), want 1");
    }

    /// The predicate is not merely defined: the checked reader hands it the facts from the SAME
    /// descriptor it read, and hands it all six arguments.
    #[test]
    fn the_checked_reader_takes_its_facts_from_the_descriptor_it_read() {
        let src = code_only(include_str!("tcb_probe.rs"));
        let body = src
            .split("pub fn read_pin_manifest_checked")
            .nth(1)
            .expect("the checked reader is gone")
            .split("\n}")
            .next()
            .expect("the checked reader has no body")
            .to_string();

        // Opened without following a final symlink...
        assert!(body.contains("libc::O_NOFOLLOW"), "{body}");
        // ...facts from an fstat of THAT handle, never a second `metadata(path)`...
        assert!(body.contains(".metadata()"), "{body}");
        assert!(!body.contains("std::fs::metadata("), "{body}");
        // ...the predicate consulted with those facts...
        assert!(body.contains("manifest_custody_violation("), "{body}");
        assert!(
            body.contains("md.uid()") && body.contains("md.mode()") && body.contains("md.is_file()"),
            "{body}"
        );
        // ...and the bytes read through the same handle rather than the path.
        assert!(body.contains("file.read_to_string("), "{body}");
        assert!(!body.contains("read_to_string(path)"), "{body}");
    }

    /// And the probe's digest comes through the descriptor it stat'ed, not a second path lookup.
    #[test]
    fn the_probe_digests_the_descriptor_it_stated_and_not_the_path_again() {
        let src = code_only(include_str!("tcb_probe.rs"));
        assert!(
            src.contains("fn digest_through(fd: libc::c_int, st: &libc::stat)"),
            "the helper is gone"
        );
        assert!(src.contains("/proc/self/fd/{fd}"), "the descriptor is not re-opened through /proc");
        // The same-inode comparison is what makes "the same file" measured rather than assumed.
        assert!(
            src.contains("md.dev() == st.st_dev && md.ino() == st.st_ino"),
            "the inode is not compared"
        );
        // The old second resolution is gone, in both spellings — over CODE, so the doc comment that
        // explains its removal cannot keep this test red.
        assert!(!src.contains("std::fs::read(path)"), "the path is still read a second time");
        assert!(!src.contains("Self::digest(path"), "the old digest(path, mode) call survives");
    }

    #[test]
    fn an_unconfigured_floor_refuses_rather_than_passing() {
        let e = verify_deployment_tcb(None, &[1000], 1000).unwrap_err();
        assert!(e.contains("no TCB pin manifest configured"), "{e}");
    }

    #[test]
    fn an_absent_manifest_file_refuses() {
        let e = verify_deployment_tcb(Some("/nonexistent/tcb-pin.json"), &[1000], 1000).unwrap_err();
        assert!(e.contains("unreadable or malformed"), "{e}");
    }

    #[test]
    fn a_malformed_manifest_refuses() {
        let dir = std::env::temp_dir().join(format!("brops-tcb-probe-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("tcb-pin.json");
        std::fs::write(&p, b"{ not json").unwrap();
        let e = verify_deployment_tcb(Some(p.to_str().unwrap()), &[1000], 1000).unwrap_err();
        assert!(e.contains("unreadable or malformed"), "{e}");
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn a_manifest_missing_required_artifacts_refuses() {
        // A syntactically valid but UNDER-SPECIFIED manifest must not pass by omission: an artifact
        // that is not listed is never integrity-checked, which is exactly the hole the coverage floor
        // exists to close. (On a non-Linux host the caller refuses earlier, for the stated reason —
        // either way the outcome is a refusal, which is the property under test.)
        let dir = std::env::temp_dir().join(format!("brops-tcb-probe-min-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("tcb-pin-min.json");
        std::fs::write(&p, br#"{"artifacts":[],"owner_uids":{}}"#).unwrap();
        assert!(verify_deployment_tcb(Some(p.to_str().unwrap()), &[1000], 1000).is_err());
        let _ = std::fs::remove_file(&p);
    }
}
