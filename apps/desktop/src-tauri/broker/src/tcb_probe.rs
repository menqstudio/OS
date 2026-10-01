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

/// The two roles that say WHICH process the floor is about, and so must name the process asking.
///
/// `verify_tcb_integrity` measures that each pinned path is TCB-owned, unwritable and at its pinned
/// digest. It never asks whether the path pinned as `trusted-verifier-broker.bin` is the binary that is
/// running. Until 2026-09-30 nothing did: both kits pin that role to their PROOF DRIVER (`bin/live_turn`,
/// `bin/ladder_turn`), so a `brops-broker` handed either kit's manifest passed its own floor while every
/// byte of itself went unmeasured. The same holds for the document that steers it: a manifest pinning
/// some other config under `pinned-manifest-config` measures a file the broker never reads.
pub const BROKER_SELF_ROLES: [&str; 2] =
    ["trusted-verifier-broker.bin", "trusted-verifier-broker.pinned-manifest-config"];

/// `None` iff every manifest entry under [`BROKER_SELF_ROLES`] resolves to THIS broker: the `.bin`
/// role to `exe`, the `.pinned-manifest-config` role to `own_config`. Each role must appear at least
/// once, and EVERY entry under it must match — a second entry naming another file is refused rather
/// than outvoted, because the floor would then vouch for a file that is not this process.
///
/// PURE over an injected `canon` (path -> canonical path, `None` if it does not resolve), so it runs on
/// every host; `exe` and `own_config` are expected already canonical. Coverage of the other roles is
/// not this function's question — `verify_tcb_integrity` asks it.
pub fn broker_identity_violation(
    manifest: &TcbPinManifest,
    exe: &std::path::Path,
    own_config: &std::path::Path,
    canon: impl Fn(&str) -> Option<std::path::PathBuf>,
) -> Option<String> {
    for (role, expected) in BROKER_SELF_ROLES.iter().zip([exe, own_config]) {
        let entries: Vec<&str> = manifest
            .artifacts
            .iter()
            .filter(|a| a.logical_name == *role)
            .map(|a| a.path.as_str())
            .collect();
        if entries.is_empty() {
            return Some(format!("the TCB pin manifest pins nothing as `{role}`"));
        }
        for pinned in entries {
            match canon(pinned) {
                Some(resolved) if resolved == expected => {}
                Some(resolved) => {
                    return Some(format!(
                        "the TCB pin manifest pins `{role}` at {pinned} ({}), which is not this broker's \
                         {} — a floor measuring another file says nothing about this one",
                        resolved.display(),
                        expected.display()
                    ))
                }
                None => {
                    return Some(format!(
                        "the TCB pin manifest pins `{role}` at {pinned}, which does not resolve"
                    ))
                }
            }
        }
    }
    None
}

/// The §2.5 floor as the `brops-broker` PROCESS runs it: [`verify_deployment_tcb`]'s floor, over a
/// manifest that must also name this process ([`broker_identity_violation`]) and the config it was
/// started with.
///
/// Separate from [`verify_deployment_tcb`] rather than a change to it: that function is also the
/// proof drivers' `--verify-tcb` (`proof/src/tcb_verify.rs`), run by root as a one-shot process whose
/// kits are verified in CI and not on a box this change could be measured on.
///
/// ONE checked read. The identity decision and the integrity decision are taken over the same parsed
/// manifest, so they cannot be about two different files.
///
/// `Ok` carries that manifest out as a [`VerifiedBrokerTcb`], and that is how the broker finds the
/// files it then reads: the root anchor comes from the path THIS manifest pinned, never from a path
/// looked up again or named in config.
pub fn verify_broker_tcb(
    manifest_path: Option<&str>,
    login_and_runtime_uids: &[u32],
    login_uid: u32,
    own_config: &str,
) -> Result<VerifiedBrokerTcb, String> {
    let path = manifest_path.ok_or_else(|| {
        format!("no TCB pin manifest configured ({TCB_PIN_MANIFEST_ENV} unset)")
    })?;
    #[cfg(target_os = "linux")]
    {
        let manifest = read_pin_manifest_checked(path, login_and_runtime_uids, login_uid)
            .map_err(|why| format!("TCB pin manifest unreadable or malformed: {why}"))?;
        // `/proc/self/exe` on Linux: the kernel's own record of the image this process was exec'd from.
        // A binary replaced or deleted after exec no longer canonicalizes to a pinned path, and refuses.
        let exe = std::env::current_exe()
            .and_then(std::fs::canonicalize)
            .map_err(|e| format!("cannot resolve this broker's own executable: {e}"))?;
        let config = std::fs::canonicalize(own_config)
            .map_err(|e| format!("cannot resolve this broker's config {own_config}: {e}"))?;
        if let Some(why) = broker_identity_violation(&manifest, &exe, &config, |p| {
            std::fs::canonicalize(p).ok()
        }) {
            return Err(why);
        }
        let probe = LinuxFsProbe { login_and_runtime_uids: login_and_runtime_uids.to_vec() };
        brops_core::tcb_integrity::verify_tcb_integrity(
            &manifest,
            &probe,
            login_and_runtime_uids,
            login_uid,
        )
        .map_err(|v| format!("{v:?}"))?;
        Ok(VerifiedBrokerTcb { manifest })
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (path, login_and_runtime_uids, login_uid, own_config);
        Err("TCB integrity floor requires Linux (owner/mode/O_NOFOLLOW facts)".to_string())
    }
}

/// Evidence that the §2.5 floor PASSED, in this process, over one parsed pin manifest — and the
/// only way to ask that manifest where a pinned file is.
///
/// The field is private and there is no public constructor: the one way to hold this value is
/// [`verify_broker_tcb`] returning `Ok`. So "the path the pin manifest pinned for a role" cannot be
/// obtained from a manifest that was not checked, or from a floor that refused.
#[derive(Debug)]
pub struct VerifiedBrokerTcb {
    // Constructed only on Linux (the floor refuses everywhere else), so on other hosts nothing
    // outside the tests ever builds one.
    #[cfg_attr(not(target_os = "linux"), allow(dead_code))]
    manifest: TcbPinManifest,
}

impl VerifiedBrokerTcb {
    /// The ONE artifact the verified manifest pins under `role`. Zero or several is a refusal.
    pub fn pinned(&self, role: &str) -> Result<&brops_core::tcb_integrity::TcbArtifact, String> {
        self.manifest.sole_artifact(role).map_err(|v| format!("{v:?}"))
    }

    /// The bytes of the artifact pinned under `role`, read through ONE `O_NOFOLLOW` descriptor and
    /// REFUSED unless they hash to the digest the floor just verified ([`read_pinned_artifact`]).
    #[cfg(target_os = "linux")]
    pub fn read_pinned(&self, role: &str, max_len: usize) -> Result<Vec<u8>, String> {
        read_pinned_artifact(self.pinned(role)?, max_len)
    }

    /// The deployment's ROOT ANCHOR: the file pinned under
    /// [`ROOT_ANCHOR_ROLE`](brops_core::tcb_integrity::ROOT_ANCHOR_ROLE), read as above and parsed
    /// fail-closed by [`crate::tcb::parse_root_anchor`] (which also holds `external` to the
    /// compiled-in root). Any failure is `Err` with the reason; the broker then serves fail-closed.
    #[cfg(target_os = "linux")]
    pub fn root_anchor(&self) -> Result<FloorPinnedAnchor, String> {
        let role = brops_core::tcb_integrity::ROOT_ANCHOR_ROLE;
        let path = self.pinned(role)?.path.clone();
        let bytes = self.read_pinned(role, crate::tcb::MAX_ROOT_ANCHOR_BYTES)?;
        let anchor = crate::tcb::parse_root_anchor(&bytes)
            .map_err(|why| format!("the root anchor pinned at {path} is refused: {why}"))?;
        Ok(FloorPinnedAnchor { anchor, path })
    }
}

/// A root anchor that was read from the path the §2.5 pin manifest pins, after the floor passed.
///
/// This type — not a bare `RootAnchor` — is what [`crate::manifest_resolver::ProductionResolver::provisioned`]
/// takes, and it has no public constructor. That is what keeps the anchor's PROVENANCE honest now
/// that it is read from a file instead of derived from a compiled-in key id: a caller outside this
/// crate cannot assemble an `install_minted` (or any other) anchor of its own and hand it to the
/// production resolver. *The label is earned by where the file sits and who can write it* — and
/// holding this value is the evidence that the file sat there.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FloorPinnedAnchor {
    anchor: brops_core::key_manifest::RootAnchor,
    path: String,
}

impl FloorPinnedAnchor {
    pub fn anchor(&self) -> &brops_core::key_manifest::RootAnchor {
        &self.anchor
    }
    /// The pinned path the anchor was read from — for the line the broker prints, nothing else.
    pub fn path(&self) -> &str {
        &self.path
    }
    pub(crate) fn into_anchor(self) -> brops_core::key_manifest::RootAnchor {
        self.anchor
    }
}

/// `None` iff `bytes` hash to the digest `art` pins. The floor checked the file at that digest a
/// moment ago; a reader that then parses bytes with a DIFFERENT digest is parsing a file the floor
/// never measured, whatever path it opened.
pub fn pinned_digest_violation(
    art: &brops_core::tcb_integrity::TcbArtifact,
    bytes: &[u8],
) -> Option<String> {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    let actual = format!("{:x}", h.finalize());
    if actual == art.expected_sha256 {
        None
    } else {
        Some(format!(
            "{} at {} hashes to {actual}, not the pinned {} — it changed after the floor measured it",
            art.logical_name, art.path, art.expected_sha256
        ))
    }
}

/// Read a pinned artifact for USE: one `O_NOFOLLOW` open, a regular file no larger than `max_len`,
/// and bytes that hash to the pinned digest.
///
/// The floor and this read are two opens of one path, so without the digest comparison a file
/// swapped between them would be parsed on the strength of a measurement of its predecessor. With
/// it, the bytes returned are bytes the pin manifest names, or nothing is returned.
#[cfg(target_os = "linux")]
pub fn read_pinned_artifact(
    art: &brops_core::tcb_integrity::TcbArtifact,
    max_len: usize,
) -> Result<Vec<u8>, String> {
    use std::io::Read;
    use std::os::unix::fs::OpenOptionsExt;

    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(&art.path)
        .map_err(|e| format!("{} at {} cannot be opened (O_NOFOLLOW): {e}", art.logical_name, art.path))?;
    let md = file
        .metadata()
        .map_err(|e| format!("{} at {}: fstat failed: {e}", art.logical_name, art.path))?;
    if !md.is_file() {
        return Err(format!("{} at {} is not a regular file", art.logical_name, art.path));
    }
    // `take(max_len + 1)`: one byte past the cap is enough to know the cap was exceeded, and the
    // read is bounded whatever the file's size says.
    let mut bytes = Vec::new();
    file.take(max_len as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| format!("{} at {} unreadable: {e}", art.logical_name, art.path))?;
    if bytes.len() > max_len {
        return Err(format!(
            "{} at {} is larger than the {max_len} bytes a reader will accept",
            art.logical_name, art.path
        ));
    }
    match pinned_digest_violation(art, &bytes) {
        Some(why) => Err(why),
        None => Ok(bytes),
    }
}

/// For a reader that did NOT obtain its anchor through [`VerifiedBrokerTcb`] — the proof drivers,
/// whose anchor path comes from their own config and whose whole floor is evaluated by root before
/// the services start: are these the bytes of the floor-pinned root anchor?
///
/// It reads the pin manifest through the custody-checked reader, runs the per-artifact floor for the
/// ONE role [`ROOT_ANCHOR_ROLE`](brops_core::tcb_integrity::ROOT_ANCHOR_ROLE) — owner, writability,
/// digest, every ancestor — reads the pinned file digest-bound, and compares. It is NOT the §2.5
/// floor (`verify_pinned_role` says why) and it is never the broker's check; it is what stops the
/// word `install_minted` in a driver's anchor file from being taken on the file's word
/// (`tcb::check_declared_install_minted_anchor`).
#[cfg(target_os = "linux")]
pub fn anchor_bytes_are_floor_pinned(
    manifest_path: Option<&str>,
    login_and_runtime_uids: &[u32],
    login_uid: u32,
    anchor_bytes: &[u8],
) -> Result<(), String> {
    let path = manifest_path.ok_or_else(|| {
        format!("no TCB pin manifest configured ({TCB_PIN_MANIFEST_ENV} unset)")
    })?;
    let manifest = read_pin_manifest_checked(path, login_and_runtime_uids, login_uid)
        .map_err(|why| format!("TCB pin manifest unreadable or malformed: {why}"))?;
    let probe = LinuxFsProbe { login_and_runtime_uids: login_and_runtime_uids.to_vec() };
    anchor_bytes_match_the_pinned_role(
        &manifest,
        &probe,
        login_and_runtime_uids,
        login_uid,
        anchor_bytes,
        |art| read_pinned_artifact(art, crate::tcb::MAX_ROOT_ANCHOR_BYTES),
    )
}

/// The decision inside [`anchor_bytes_are_floor_pinned`], over an injected probe and reader so it is
/// tested on every host and without a root-owned tree: the manifest pins exactly ONE root anchor,
/// that artifact passes the per-artifact floor, and the bytes read from the pinned path — `read`
/// binds them to the pinned digest — are the bytes the caller was given. Three ways to refuse and
/// each is its own: not pinned / fails the floor, unreadable or changed since the pin, and a
/// different file from the pinned one.
pub fn anchor_bytes_match_the_pinned_role(
    manifest: &TcbPinManifest,
    probe: &dyn brops_core::tcb_integrity::FsProbe,
    login_and_runtime_uids: &[u32],
    login_uid: u32,
    anchor_bytes: &[u8],
    read: impl FnOnce(&brops_core::tcb_integrity::TcbArtifact) -> Result<Vec<u8>, String>,
) -> Result<(), String> {
    let art = brops_core::tcb_integrity::verify_pinned_role(
        manifest,
        brops_core::tcb_integrity::ROOT_ANCHOR_ROLE,
        probe,
        login_and_runtime_uids,
        login_uid,
    )
    .map_err(|v| format!("{v:?}"))?;
    let pinned = read(art)?;
    if pinned != anchor_bytes {
        return Err(format!(
            "the anchor this reader was given is not the one pinned at {}",
            art.path
        ));
    }
    Ok(())
}

// Test-only constructors, kept at the very end of the non-test code on purpose: `code_only` in the
// tests below cuts this file at its first `cfg(test)` attribute.
#[cfg(test)]
impl FloorPinnedAnchor {
    /// For `manifest_resolver`'s tests, which need to hand `ProductionResolver::provisioned` an
    /// anchor without a root-owned TCB directory to read one from. Not compiled into any binary.
    pub(crate) fn for_test(anchor: brops_core::key_manifest::RootAnchor) -> Self {
        FloorPinnedAnchor { anchor, path: "<test>".to_string() }
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

    // ---- the manifest must name THIS broker -------------------------------------------------
    //
    // Both in-tree kits pin `trusted-verifier-broker.bin` to their proof driver. Handed either one,
    // `brops-broker` used to pass its own floor without a byte of itself being measured.

    use brops_core::tcb_integrity::{TcbArtifact, TcbOwner};
    use std::path::{Path, PathBuf};

    const EXE: &str = "/opt/brops/bin/brops-broker";
    const CFG: &str = "/opt/brops/tcb/broker-config.json";

    fn pinned(entries: &[(&str, &str)]) -> TcbPinManifest {
        TcbPinManifest {
            artifacts: entries
                .iter()
                .map(|(role, path)| TcbArtifact {
                    logical_name: role.to_string(),
                    path: path.to_string(),
                    expected_sha256: "00".repeat(32),
                    expected_owner: TcbOwner::Root,
                })
                .collect(),
            owner_uids: Default::default(),
        }
    }

    /// Every path resolves to itself, except the one symlink the tests below need.
    fn canon(p: &str) -> Option<PathBuf> {
        match p {
            "/opt/brops/bin/current" => Some(PathBuf::from(EXE)),
            "/gone" => None,
            _ => Some(PathBuf::from(p)),
        }
    }

    fn violation(entries: &[(&str, &str)]) -> Option<String> {
        broker_identity_violation(&pinned(entries), Path::new(EXE), Path::new(CFG), canon)
    }

    #[test]
    fn a_manifest_naming_this_broker_and_its_config_is_accepted() {
        // The control: without it every refusal below could be the predicate refusing everything.
        assert_eq!(
            violation(&[
                ("trusted-verifier-broker.bin", EXE),
                ("trusted-verifier-broker.pinned-manifest-config", CFG),
                ("supervisor.bin", "/opt/brops/engine/ci/live/run_ladder_supervisor.py"),
            ]),
            None
        );
        // A pinned path that RESOLVES to this binary is this binary.
        assert_eq!(
            violation(&[
                ("trusted-verifier-broker.bin", "/opt/brops/bin/current"),
                ("trusted-verifier-broker.pinned-manifest-config", CFG),
            ]),
            None
        );
    }

    #[test]
    fn a_kit_manifest_pinning_a_proof_driver_is_refused() {
        // The defect, as the two in-tree kits produce it.
        for driver in ["/opt/brops/bin/live_turn", "/opt/brops/bin/ladder_turn"] {
            let why = violation(&[
                ("trusted-verifier-broker.bin", driver),
                ("trusted-verifier-broker.pinned-manifest-config", CFG),
            ])
            .expect("a manifest pinning a proof driver must not vouch for brops-broker");
            assert!(why.contains("trusted-verifier-broker.bin") && why.contains(driver), "{why}");
        }
    }

    #[test]
    fn a_manifest_pinning_another_config_is_refused() {
        let why = violation(&[
            ("trusted-verifier-broker.bin", EXE),
            ("trusted-verifier-broker.pinned-manifest-config", "/opt/brops/config.json"),
        ])
        .expect("a manifest pinning a config this broker does not read must be refused");
        assert!(why.contains("pinned-manifest-config"), "{why}");
    }

    #[test]
    fn a_second_entry_naming_another_file_is_refused_not_outvoted() {
        let why = violation(&[
            ("trusted-verifier-broker.bin", EXE),
            ("trusted-verifier-broker.bin", "/opt/brops/bin/live_turn"),
            ("trusted-verifier-broker.pinned-manifest-config", CFG),
        ])
        .expect("one matching entry must not excuse another");
        assert!(why.contains("live_turn"), "{why}");
    }

    #[test]
    fn an_absent_role_or_an_unresolvable_path_is_refused() {
        let why = violation(&[("trusted-verifier-broker.pinned-manifest-config", CFG)])
            .expect("no `.bin` entry at all");
        assert!(why.contains("pins nothing as `trusted-verifier-broker.bin`"), "{why}");
        let why = violation(&[("trusted-verifier-broker.bin", EXE)]).expect("no config entry");
        assert!(why.contains("pinned-manifest-config"), "{why}");
        let why = violation(&[
            ("trusted-verifier-broker.bin", "/gone"),
            ("trusted-verifier-broker.pinned-manifest-config", CFG),
        ])
        .expect("an unresolvable pin");
        assert!(why.contains("does not resolve"), "{why}");
    }

    #[test]
    fn the_broker_floor_refuses_unconfigured_and_absent_manifests() {
        let e = verify_broker_tcb(None, &[1000], 1000, "/nonexistent").unwrap_err();
        assert!(e.contains("no TCB pin manifest configured"), "{e}");
        let e = verify_broker_tcb(Some("/nonexistent/tcb-pin.json"), &[1000], 1000, "/nonexistent")
            .unwrap_err();
        assert!(e.contains("unreadable or malformed") || e.contains("requires Linux"), "{e}");
    }

    // ---- what the floor hands out: the pinned path, and bytes bound to the pinned digest --------

    use brops_core::tcb_integrity::ROOT_ANCHOR_ROLE;

    fn sha256_hex(bytes: &[u8]) -> String {
        use sha2::{Digest, Sha256};
        let mut h = Sha256::new();
        h.update(bytes);
        format!("{:x}", h.finalize())
    }

    fn artifact(role: &str, path: &str, bytes: &[u8]) -> TcbArtifact {
        TcbArtifact {
            logical_name: role.to_string(),
            path: path.to_string(),
            expected_sha256: sha256_hex(bytes),
            expected_owner: TcbOwner::Root,
        }
    }

    /// A value only `verify_broker_tcb` can build outside this module. Built here from a manifest
    /// the test wrote, to exercise what the broker does AFTER the floor has passed.
    fn verified(artifacts: Vec<TcbArtifact>) -> VerifiedBrokerTcb {
        VerifiedBrokerTcb {
            manifest: TcbPinManifest { artifacts, owner_uids: Default::default() },
        }
    }

    #[test]
    fn the_digest_binding_accepts_the_pinned_bytes_and_names_a_change() {
        let art = artifact(ROOT_ANCHOR_ROLE, "/opt/brops/tcb/root-anchor.json", b"pinned");
        assert_eq!(pinned_digest_violation(&art, b"pinned"), None);
        let why = pinned_digest_violation(&art, b"pinned ").expect("one byte more is another file");
        assert!(why.contains(ROOT_ANCHOR_ROLE) && why.contains("/opt/brops/tcb/root-anchor.json"), "{why}");
        assert!(why.contains(&art.expected_sha256), "{why}");
    }

    #[test]
    fn the_floor_hands_out_exactly_one_path_per_role_or_refuses() {
        let one = verified(vec![artifact(ROOT_ANCHOR_ROLE, "/t/anchor.json", b"a")]);
        assert_eq!(one.pinned(ROOT_ANCHOR_ROLE).unwrap().path, "/t/anchor.json");

        let none = verified(vec![artifact("supervisor.bin", "/t/sup", b"s")]);
        let why = none.pinned(ROOT_ANCHOR_ROLE).unwrap_err();
        assert!(why.contains("MissingRequired") && why.contains(ROOT_ANCHOR_ROLE), "{why}");

        let two = verified(vec![
            artifact(ROOT_ANCHOR_ROLE, "/t/anchor.json", b"a"),
            artifact(ROOT_ANCHOR_ROLE, "/t/substitute.json", b"b"),
        ]);
        let why = two.pinned(ROOT_ANCHOR_ROLE).unwrap_err();
        assert!(why.contains("AmbiguousRole") && why.contains("/t/substitute.json"), "{why}");
    }

    // ---- the drivers' question, over an injected filesystem (every host, no root) --------------

    /// A filesystem in which every path is root-owned and unwritable, except the ones overridden.
    struct Fs(std::collections::HashMap<String, brops_core::tcb_integrity::FileFacts>);
    impl Fs {
        fn clean(art: &TcbArtifact) -> Fs {
            let mut m = std::collections::HashMap::new();
            let facts = |sha: &str| brops_core::tcb_integrity::FileFacts {
                owner_uid: 0,
                is_world_or_group_writable: false,
                writable_by_login_or_runtime: false,
                sha256: sha.to_string(),
            };
            m.insert(art.path.clone(), facts(&art.expected_sha256));
            let mut cur = art.path.as_str();
            while let Some(i) = cur.rfind('/') {
                let parent = if i == 0 { "/" } else { &cur[..i] };
                m.insert(parent.to_string(), facts(""));
                if i == 0 {
                    break;
                }
                cur = &cur[..i];
            }
            Fs(m)
        }
    }
    impl brops_core::tcb_integrity::FsProbe for Fs {
        fn stat(&self, path: &str) -> Option<brops_core::tcb_integrity::FileFacts> {
            self.0.get(path).cloned()
        }
    }

    const PINNED_ANCHOR: &str = "/opt/brops/tcb/root-anchor.json";
    const DOC: &[u8] = br#"{"root_key_id":"r","public_key_hex":"..","provenance":"install_minted"}"#;

    fn pin_with_anchor() -> (TcbPinManifest, TcbArtifact) {
        let art = artifact(ROOT_ANCHOR_ROLE, PINNED_ANCHOR, DOC);
        let manifest = TcbPinManifest {
            artifacts: vec![art.clone()],
            owner_uids: [(TcbOwner::Root, 0)].into_iter().collect(),
        };
        (manifest, art)
    }

    #[test]
    fn the_given_anchor_is_floor_pinned_only_if_it_is_the_pinned_files_bytes() {
        let (m, art) = pin_with_anchor();
        let fs = Fs::clean(&art);
        // The control: the pinned file's own bytes, on a clean filesystem.
        assert_eq!(
            anchor_bytes_match_the_pinned_role(&m, &fs, RUNTIME, LOGIN, DOC, |_| Ok(DOC.to_vec())),
            Ok(())
        );
        // A DIFFERENT file — the throwaway anchor a driver's config names. Same key, same word,
        // one byte apart; the pinned file is untouched and passes the floor. Refused.
        let mut other = DOC.to_vec();
        other.push(b'\n');
        let why = anchor_bytes_match_the_pinned_role(&m, &fs, RUNTIME, LOGIN, &other, |_| Ok(DOC.to_vec()))
            .unwrap_err();
        assert!(why.contains("is not the one pinned at") && why.contains(PINNED_ANCHOR), "{why}");
        // The reader asked for THE PINNED PATH, not for whatever the caller named.
        let mut asked = String::new();
        let _ = anchor_bytes_match_the_pinned_role(&m, &fs, RUNTIME, LOGIN, DOC, |a| {
            asked = a.path.clone();
            Ok(DOC.to_vec())
        });
        assert_eq!(asked, PINNED_ANCHOR);
    }

    #[test]
    fn the_given_anchor_is_not_floor_pinned_when_the_pinned_file_fails_the_floor_or_cannot_be_read() {
        let (m, art) = pin_with_anchor();
        let read_ok = |_: &TcbArtifact| Ok(DOC.to_vec());

        // The pinned anchor is owned by a runtime principal: the reader is never even consulted.
        let mut fs = Fs::clean(&art);
        fs.0.get_mut(PINNED_ANCHOR).unwrap().owner_uid = RUNTIME[0];
        let why = anchor_bytes_match_the_pinned_role(&m, &fs, RUNTIME, LOGIN, DOC, |_| {
            panic!("read a file the floor had refused")
        })
        .unwrap_err();
        assert!(why.contains("WrongOwner"), "{why}");

        // A writable ancestor.
        let mut fs = Fs::clean(&art);
        fs.0.get_mut("/opt/brops/tcb").unwrap().writable_by_login_or_runtime = true;
        let why = anchor_bytes_match_the_pinned_role(&m, &fs, RUNTIME, LOGIN, DOC, read_ok).unwrap_err();
        assert!(why.contains("AncestorWritable"), "{why}");

        // Changed on disk since the pin.
        let mut fs = Fs::clean(&art);
        fs.0.get_mut(PINNED_ANCHOR).unwrap().sha256 = "e".repeat(64);
        let why = anchor_bytes_match_the_pinned_role(&m, &fs, RUNTIME, LOGIN, DOC, read_ok).unwrap_err();
        assert!(why.contains("HashMismatch"), "{why}");

        // No anchor pinned at all.
        let empty = TcbPinManifest { artifacts: vec![], owner_uids: Default::default() };
        let why = anchor_bytes_match_the_pinned_role(&empty, &Fs::clean(&art), RUNTIME, LOGIN, DOC, read_ok)
            .unwrap_err();
        assert!(why.contains("MissingRequired"), "{why}");

        // The floor passes and the digest-bound read refuses: that refusal is carried out as it is.
        let why = anchor_bytes_match_the_pinned_role(&m, &Fs::clean(&art), RUNTIME, LOGIN, DOC, |_| {
            Err("changed after the floor measured it".to_string())
        })
        .unwrap_err();
        assert_eq!(why, "changed after the floor measured it");
    }

    #[cfg(target_os = "linux")]
    mod pinned_reads {
        use super::*;
        use brops_core::key_manifest::RootProvenance;

        fn anchor_json(provenance: &str) -> Vec<u8> {
            format!(
                r#"{{"root_key_id":"brops-live-root-1","public_key_hex":"{}","provenance":"{provenance}"}}"#,
                "ab".repeat(32)
            )
            .into_bytes()
        }

        /// A temp dir holding `anchor.json` with `on_disk`, and a floor result whose manifest pins
        /// that path at the digest of `pinned`.
        fn deployment(on_disk: &[u8], pinned: &[u8]) -> (tempfile::TempDir, VerifiedBrokerTcb) {
            let dir = tempfile::tempdir().unwrap();
            let path = dir.path().join("anchor.json");
            std::fs::write(&path, on_disk).unwrap();
            let v = verified(vec![artifact(ROOT_ANCHOR_ROLE, path.to_str().unwrap(), pinned)]);
            (dir, v)
        }

        #[test]
        fn the_pinned_anchor_is_read_and_carries_its_own_provenance() {
            for (word, want) in [
                ("kit_generated", RootProvenance::KitGenerated),
                ("demonstration", RootProvenance::Demonstration),
                ("install_minted", RootProvenance::InstallMinted),
            ] {
                let doc = anchor_json(word);
                let (dir, v) = deployment(&doc, &doc);
                let got = v.root_anchor().unwrap_or_else(|e| panic!("{word}: {e}"));
                assert_eq!(got.anchor().provenance, want);
                assert_eq!(got.anchor().pinned.root_key_id, "brops-live-root-1");
                assert_eq!(got.path(), dir.path().join("anchor.json").to_str().unwrap());
                // Whatever it says, it is not production: install_minted is behind the Owner's line.
                assert!(!got.anchor().provenance.supports_production_claim(), "{word}");
            }
        }

        #[test]
        fn an_anchor_relabelled_after_the_pin_is_refused_by_its_digest() {
            // THE RELABEL. The floor measured a `kit_generated` anchor; the file now says
            // `install_minted`. The broker must not parse a file the floor never measured.
            let (_dir, v) = deployment(&anchor_json("install_minted"), &anchor_json("kit_generated"));
            let why = v.root_anchor().unwrap_err();
            assert!(why.contains("changed after the floor measured it"), "{why}");
        }

        #[test]
        fn a_missing_garbled_or_unlabelled_pinned_anchor_is_refused_with_the_reason() {
            // Missing.
            let dir = tempfile::tempdir().unwrap();
            let gone = dir.path().join("gone.json");
            let v = verified(vec![artifact(ROOT_ANCHOR_ROLE, gone.to_str().unwrap(), b"x")]);
            let why = v.root_anchor().unwrap_err();
            assert!(why.contains("cannot be opened"), "{why}");

            // Garbled — and PINNED as garbled, so the digest passes and the parser is what refuses.
            let (_d, v) = deployment(b"{ not json", b"{ not json");
            let why = v.root_anchor().unwrap_err();
            assert!(why.contains("is refused: not_json"), "{why}");

            // No provenance, an unknown one, and a kit root calling itself external.
            let no_provenance = format!(
                r#"{{"root_key_id":"brops-live-root-1","public_key_hex":"{}"}}"#,
                "ab".repeat(32)
            )
            .into_bytes();
            for (doc, reason) in [
                (no_provenance, "provenance_unknown"),
                (anchor_json("production"), "provenance_unknown"),
                (anchor_json("external"), "external_not_the_pinned_root"),
            ] {
                let (_d, v) = deployment(&doc, &doc);
                let why = v.root_anchor().unwrap_err();
                assert!(why.contains(&format!("is refused: {reason}")), "{why}");
            }

            // Not pinned at all, or pinned twice: there is no path to read.
            assert!(verified(vec![]).root_anchor().unwrap_err().contains("MissingRequired"));
        }

        #[test]
        fn a_pinned_read_refuses_a_symlink_a_directory_and_an_oversized_file() {
            let dir = tempfile::tempdir().unwrap();
            let real = dir.path().join("real.json");
            std::fs::write(&real, b"0123456789").unwrap();

            // The control: the same bytes at the pinned digest ARE returned.
            let art = artifact(ROOT_ANCHOR_ROLE, real.to_str().unwrap(), b"0123456789");
            assert_eq!(read_pinned_artifact(&art, 64).unwrap(), b"0123456789");
            // Exactly at the cap is accepted; one byte under it is not.
            assert!(read_pinned_artifact(&art, 10).is_ok());
            let why = read_pinned_artifact(&art, 9).unwrap_err();
            assert!(why.contains("larger than the 9 bytes"), "{why}");

            // A symlink at the pinned path — even one pointing at the right bytes.
            let link = dir.path().join("link.json");
            std::os::unix::fs::symlink(&real, &link).unwrap();
            let art = artifact(ROOT_ANCHOR_ROLE, link.to_str().unwrap(), b"0123456789");
            let why = read_pinned_artifact(&art, 64).unwrap_err();
            assert!(why.contains("cannot be opened (O_NOFOLLOW)"), "{why}");

            // A directory.
            let art = artifact(ROOT_ANCHOR_ROLE, dir.path().to_str().unwrap(), b"");
            assert!(read_pinned_artifact(&art, 64).is_err());
        }

        /// The drivers' question, on the real filesystem. An anchor this test's own uid owns is NOT
        /// a TCB-owned file, and a manifest that expects root there refuses it by role — whatever
        /// the file says about itself.
        #[test]
        fn an_anchor_the_tcb_owner_does_not_own_is_not_floor_pinned() {
            // SAFETY: getuid never fails and touches no memory.
            let me = unsafe { libc::getuid() };
            if me == 0 {
                return; // as root every file here IS root-owned; the refusal under test cannot arise
            }
            let dir = tempfile::tempdir().unwrap();
            let doc = anchor_json("install_minted");
            let anchor = dir.path().join("anchor.json");
            std::fs::write(&anchor, &doc).unwrap();
            let manifest = TcbPinManifest {
                artifacts: vec![artifact(ROOT_ANCHOR_ROLE, anchor.to_str().unwrap(), &doc)],
                owner_uids: [(TcbOwner::Root, 0)].into_iter().collect(),
            };
            let pin = dir.path().join("pin.json");
            std::fs::write(&pin, serde_json::to_vec(&manifest).unwrap()).unwrap();
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&pin, std::fs::Permissions::from_mode(0o644)).unwrap();

            // The manifest's own custody is judged against principals that do not include this
            // uid, so the refusal that follows is the ANCHOR's and not the manifest's.
            let other = me.wrapping_add(1);
            let why = anchor_bytes_are_floor_pinned(pin.to_str(), &[other], other, &doc).unwrap_err();
            assert!(why.contains("WrongOwner") && why.contains(ROOT_ANCHOR_ROLE), "{why}");

            // ...and with this uid named as a runtime principal, the manifest itself is refused
            // first: a floor a measured party can re-pin measures nothing.
            let why = anchor_bytes_are_floor_pinned(pin.to_str(), &[me], other, &doc).unwrap_err();
            assert!(why.contains("login or runtime principal"), "{why}");

            // No manifest configured at all.
            let why = anchor_bytes_are_floor_pinned(None, &[other], other, &doc).unwrap_err();
            assert!(why.contains("no TCB pin manifest configured"), "{why}");
        }
    }

    /// `root_anchor` reads the pinned path, digest-bound, and parses with the fail-closed parser —
    /// asserted from the source as well, because on a non-Linux host the tests above do not compile.
    #[test]
    fn the_root_anchor_is_read_from_the_pinned_path_and_bound_to_the_pinned_digest() {
        let src = code_only(include_str!("tcb_probe.rs"));
        let body = src
            .split("pub fn root_anchor(&self)")
            .nth(1)
            .expect("root_anchor is gone")
            .split("\n    }")
            .next()
            .unwrap()
            .to_string();
        assert!(body.contains("ROOT_ANCHOR_ROLE"), "{body}");
        assert!(body.contains("self.read_pinned(role"), "{body}");
        assert!(body.contains("crate::tcb::parse_root_anchor(&bytes)"), "{body}");
        // No second source for the path: not a config value, not an environment variable.
        assert!(!body.contains("std::env::var") && !body.contains("cfg"), "{body}");

        let read = src
            .split("pub fn read_pinned_artifact")
            .nth(1)
            .expect("read_pinned_artifact is gone")
            .split("\n}")
            .next()
            .unwrap()
            .to_string();
        assert!(read.contains("libc::O_NOFOLLOW"), "{read}");
        assert!(read.contains("pinned_digest_violation(art, &bytes)"), "{read}");
        assert!(!read.contains("std::fs::read("), "{read}");

        // The drivers' wrapper hands the tested decision the REAL pieces: the custody-checked
        // manifest reader, the real probe, and the digest-bound reader — not a closure that answers.
        let wrapper = src
            .split("pub fn anchor_bytes_are_floor_pinned")
            .nth(1)
            .expect("anchor_bytes_are_floor_pinned is gone")
            .split("\n}")
            .next()
            .unwrap()
            .to_string();
        assert!(
            wrapper.contains("read_pin_manifest_checked(path, login_and_runtime_uids, login_uid)"),
            "{wrapper}"
        );
        assert!(wrapper.contains("LinuxFsProbe {"), "{wrapper}");
        assert!(wrapper.contains("anchor_bytes_match_the_pinned_role("), "{wrapper}");
        assert!(
            wrapper.contains("|art| read_pinned_artifact(art, crate::tcb::MAX_ROOT_ANCHOR_BYTES)"),
            "{wrapper}"
        );

        // And the only construction of the floor's evidence is inside `verify_broker_tcb`, after
        // the integrity floor returned `Ok`.
        assert_eq!(src.matches("VerifiedBrokerTcb { manifest }").count(), 1);
        let verify = src.split("pub fn verify_broker_tcb").nth(1).unwrap();
        let floor = verify.find("verify_tcb_integrity(").unwrap();
        let built = verify.find("Ok(VerifiedBrokerTcb { manifest })").expect("not built by the floor");
        assert!(floor < built);
        assert!(verify[floor..built].contains(".map_err(|v| format!(\"{v:?}\"))?;"), "{verify}");
    }

    /// The Linux branch reads ONCE through the checked reader, asks the identity question of
    /// `current_exe`, and only then runs the integrity floor over that same parsed manifest.
    #[test]
    fn the_broker_floor_checks_identity_over_the_checked_read_before_integrity() {
        let src = code_only(include_str!("tcb_probe.rs"));
        let body = src
            .split("pub fn verify_broker_tcb")
            .nth(1)
            .expect("verify_broker_tcb is gone")
            .split("#[cfg(not(target_os = \"linux\"))]")
            .next()
            .expect("the linux branch is gone")
            .to_string();
        let read = body.find("read_pin_manifest_checked(path").expect("not a checked read");
        let exe = body.find("std::env::current_exe()").expect("identity not taken from the process");
        let identity = body.find("broker_identity_violation(&manifest").expect("identity unchecked");
        let floor = body.find("verify_tcb_integrity(").expect("integrity floor not run");
        assert!(read < exe && exe < identity && identity < floor, "{body}");
        // And the identity verdict is a refusal, not a value computed and dropped.
        assert!(body[identity..floor].contains("return Err(why);"), "{body}");
        assert!(!body.contains("load_pin_manifest("), "{body}");
    }
}
