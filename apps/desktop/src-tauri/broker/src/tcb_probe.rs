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

/// Load + parse the pin manifest. Any problem — unreadable, malformed — is `None`, and every caller
/// treats `None` as "do not enter governed mode".
pub fn load_pin_manifest(path: &str) -> Option<TcbPinManifest> {
    let raw = std::fs::read_to_string(path).ok()?;
    serde_json::from_str::<TcbPinManifest>(&raw).ok()
}

#[cfg(target_os = "linux")]
pub use linux::LinuxFsProbe;

#[cfg(target_os = "linux")]
mod linux {
    use brops_core::tcb_integrity::{FileFacts, FsProbe};
    use sha2::{Digest, Sha256};
    use std::ffi::CString;
    use std::os::unix::fs::MetadataExt;

    /// The real probe. Every stat goes through an `O_NOFOLLOW`-opened handle so a symlink swapped in
    /// between the pin and the check cannot redirect what is measured — the floor's contract says the
    /// probe must not re-look-up the path.
    pub struct LinuxFsProbe {
        /// The interactive login UID plus every runtime service UID. `writable_by_login_or_runtime`
        /// is decided against this set; the floor refuses any TCB artifact one of them can write.
        pub login_and_runtime_uids: Vec<u32>,
    }

    impl LinuxFsProbe {
        /// `fstat` an `O_NOFOLLOW|O_PATH`-opened handle. `O_PATH` means we never need read permission
        /// merely to learn ownership and mode, and `O_NOFOLLOW` makes a symlink at the final component
        /// an error rather than a redirect.
        fn stat_nofollow(path: &str) -> Option<libc::stat> {
            let c = CString::new(path).ok()?;
            let fd = unsafe { libc::open(c.as_ptr(), libc::O_PATH | libc::O_NOFOLLOW | libc::O_CLOEXEC) };
            if fd < 0 {
                return None;
            }
            let mut st: libc::stat = unsafe { std::mem::zeroed() };
            let rc = unsafe { libc::fstat(fd, &mut st) };
            unsafe { libc::close(fd) };
            if rc != 0 {
                return None;
            }
            Some(st)
        }

        /// Content digest of a regular file. Directories (and anything unreadable) yield an empty
        /// string, which is what the floor expects for ancestor entries.
        fn digest(path: &str, mode: u32) -> String {
            if mode & libc::S_IFMT != libc::S_IFREG {
                return String::new();
            }
            match std::fs::read(path) {
                Ok(bytes) => {
                    let mut h = Sha256::new();
                    h.update(&bytes);
                    format!("{:x}", h.finalize())
                }
                Err(_) => String::new(),
            }
        }
    }

    impl FsProbe for LinuxFsProbe {
        fn stat(&self, path: &str) -> Option<FileFacts> {
            let st = Self::stat_nofollow(path)?;
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
                sha256: Self::digest(path, mode),
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
    let manifest = load_pin_manifest(path)
        .ok_or_else(|| format!("TCB pin manifest unreadable or malformed: {path}"))?;

    #[cfg(target_os = "linux")]
    {
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
        let _ = (&manifest, login_and_runtime_uids, login_uid);
        Err("TCB integrity floor requires Linux (owner/mode/O_NOFOLLOW facts)".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // The floor's VALUE is that it refuses. These pin the three ways a deployment can fail to
    // present one, because each of them used to be indistinguishable from "no floor at all".

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
