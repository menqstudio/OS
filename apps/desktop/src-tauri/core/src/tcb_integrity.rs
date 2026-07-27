//! Wave 3b-1B — TCB binary & config integrity floor (implements the design-GREEN rev-30 §2.5
//! "TCB binary & config integrity" P0 code-integrity floor).
//!
//! This module is the **pure, side-effect-free verification core** the supervisor runs at start (before
//! it will issue **any** governed-turn lease). It owns NO filesystem, socket, DB, or clock: every fact
//! about the on-disk world arrives through the injected [`FsProbe`] trait, so the whole rev-30 §2.5
//! floor is unit-testable **without** the OS trust chain — tests inject a fake FS.
//!
//! rev-30 §2.5 rules encoded here (the EXPANDED `TCB_ARTIFACTS` set):
//! - `TCB_ARTIFACTS` = the seven trusted executables (**supervisor**, **evidence-recorder runner**,
//!   **privileged setuid launcher**, **contained model executor**, **isolated receipt signer**,
//!   **trusted desktop verifier/broker service**, **`desktop-challenge-authority`**) PLUS every file
//!   that steers them: each one's **config/policy bundle** (incl. **both** the broker's and the
//!   challenge-authority's), the **broker IPC/peer-auth policy**, the **challenge-authority IPC/peer-auth
//!   policy**, the **broker pinned-manifest configuration**, the **`GOVERNED_EXECUTION_ALLOWLIST`**
//!   source, the **key-manifest/root-anchor**, and **both services' systemd/unit files**.
//! - **Ownership + non-writability floor.** Every artifact **and every ancestor directory up to `/`**
//!   MUST be owned by a dedicated TCB principal (`root` or a dedicated `brops-admin` that is NOT any
//!   runtime principal) and MUST NOT be writable — by mode bits, POSIX ACL, or group — by the login user
//!   or by any runtime UID. A writable ancestor is treated as writable (a rename/replace vector).
//! - **Fail-closed.** [`verify_tcb_integrity`] refuses (returns a [`TcbViolation`] naming the failing
//!   artifact + reason) if ANY artifact or ancestor is **missing**, **wrong-owner**,
//!   **writable-by-login-or-runtime**, or **hash-mismatched** — never a partial/degraded pass. The
//!   supervisor maps any `Err` here to "governed real-mode DISABLED" (platform gate §0.1 unsupported).

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// A dedicated TCB-owning principal (rev-30 §2.5): `root`, or a dedicated `brops-admin` that is **not**
/// any runtime principal. The concrete OS UID each resolves to on this host lives in
/// [`TcbPinManifest::owner_uids`] (the root-owned pin manifest is authoritative, never a path re-lookup).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TcbOwner {
    /// The OS super-user.
    Root,
    /// A dedicated `brops-admin` TCB principal (never a runtime/login UID).
    BropsAdmin,
}

/// One pinned TCB artifact: its logical role, on-disk path, expected content digest, and expected owner.
/// `expected_sha256` is the start-time SHA-256 pin (lowercase hex); for directory-only entries it is not
/// used, but binaries/configs MUST match exactly.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TcbArtifact {
    /// Stable role name (one of [`TCB_REQUIRED_ARTIFACTS`]) — used to name a violation.
    pub logical_name: String,
    /// Absolute path to the artifact (`/`-separated; ancestors are derived from it).
    pub path: String,
    /// Expected lowercase-hex SHA-256 of the exact on-disk bytes.
    pub expected_sha256: String,
    /// Which dedicated TCB principal MUST own the file.
    pub expected_owner: TcbOwner,
}

/// The root-owned pin manifest: the full pinned `TCB_ARTIFACTS` set plus the resolved OS UID for each
/// dedicated TCB owner. Construction is data-only; the manifest carries NO live FS handle.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TcbPinManifest {
    /// Every pinned artifact (see [`TcbPinManifest::missing_required`] to assert full rev-30 coverage).
    pub artifacts: Vec<TcbArtifact>,
    /// The OS UID each dedicated TCB owner resolves to on this host (e.g. `root -> 0`,
    /// `brops_admin -> 500`). These MUST be distinct from every runtime/login UID.
    pub owner_uids: BTreeMap<TcbOwner, u32>,
}

impl TcbPinManifest {
    /// `true` iff `uid` is one of the resolved dedicated-TCB owner UIDs.
    pub fn is_tcb_owner(&self, uid: u32) -> bool {
        self.owner_uids.values().any(|u| *u == uid)
    }

    /// The subset of [`TCB_REQUIRED_ARTIFACTS`] not present (by `logical_name`) in this manifest. Empty
    /// ⇒ the manifest covers the full rev-30 §2.5 EXPANDED set. Callers SHOULD refuse start on non-empty.
    pub fn missing_required(&self) -> Vec<&'static str> {
        TCB_REQUIRED_ARTIFACTS
            .iter()
            .copied()
            .filter(|req| !self.artifacts.iter().any(|a| a.logical_name == *req))
            .collect()
    }
}

/// The facts a [`FsProbe`] reports about one path. In production these come from an `fstat` of an
/// `O_NOFOLLOW`-opened `fd` (never a path re-lookup — no TOCTOU) plus an ACL/group scan; in tests they
/// are injected directly. `sha256` is the lowercase-hex digest of the opened bytes (ignored for
/// directory ancestors).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileFacts {
    /// Owning OS UID.
    pub owner_uid: u32,
    /// Any world/group write bit is set (mode `0o022` region) — untrusted-writable.
    pub is_world_or_group_writable: bool,
    /// Writable — by mode bit, POSIX ACL, or group membership — by the interactive login UID or any
    /// runtime service UID. The probe resolves this against the login/runtime principal set.
    pub writable_by_login_or_runtime: bool,
    /// Lowercase-hex SHA-256 of the on-disk bytes (empty for directory ancestors).
    pub sha256: String,
}

/// Injected filesystem probe: the ONLY way the verifier learns about the on-disk world. Implementations
/// MUST stat an `O_NOFOLLOW`-opened handle (no symlink/path re-lookup). Returns `None` iff the path is
/// absent.
pub trait FsProbe {
    /// Stat `path`, or `None` if it does not exist.
    fn stat(&self, path: &str) -> Option<FileFacts>;
}

/// A TCB-integrity floor violation (rev-30 §2.5) — names the failing artifact and the exact reason. Any
/// value here ⇒ the supervisor DISABLES governed real-mode (fail-closed, never partial).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TcbViolation {
    /// The pinned artifact is absent from disk.
    Missing { logical_name: String, path: String },
    /// The manifest has no resolved UID for the artifact's expected owner (mis-provisioned pin manifest).
    UnknownOwner { logical_name: String, owner: TcbOwner },
    /// The owner is not the expected dedicated TCB principal (or is a runtime/login UID).
    WrongOwner {
        logical_name: String,
        path: String,
        expected_uid: u32,
        actual_uid: u32,
    },
    /// The artifact is writable by the login user or a runtime UID (mode/ACL/group).
    WritableByUntrusted { logical_name: String, path: String },
    /// The on-disk digest does not match the start-time pin.
    HashMismatch {
        logical_name: String,
        path: String,
        expected_sha256: String,
        actual_sha256: String,
    },
    /// An ancestor directory of the artifact is absent (a rename/replace vector).
    AncestorMissing { logical_name: String, ancestor: String },
    /// An ancestor directory is not TCB-owned (or is owned by a runtime/login UID).
    AncestorWrongOwner {
        logical_name: String,
        ancestor: String,
        actual_uid: u32,
    },
    /// An ancestor directory is writable by the login user or a runtime UID (a rename/replace vector).
    AncestorWritable { logical_name: String, ancestor: String },
}

impl TcbViolation {
    /// The `logical_name` of the artifact whose check failed.
    pub fn logical_name(&self) -> &str {
        match self {
            TcbViolation::Missing { logical_name, .. }
            | TcbViolation::UnknownOwner { logical_name, .. }
            | TcbViolation::WrongOwner { logical_name, .. }
            | TcbViolation::WritableByUntrusted { logical_name, .. }
            | TcbViolation::HashMismatch { logical_name, .. }
            | TcbViolation::AncestorMissing { logical_name, .. }
            | TcbViolation::AncestorWrongOwner { logical_name, .. }
            | TcbViolation::AncestorWritable { logical_name, .. } => logical_name,
        }
    }
}

/// The rev-30 §2.5 EXPANDED `TCB_ARTIFACTS` logical set — the seven trusted executables plus every file
/// that steers the two long-lived trusted services (broker + challenge-authority) and the launch chain.
/// A conforming [`TcbPinManifest`] MUST pin every one of these (see [`TcbPinManifest::missing_required`]).
pub const TCB_REQUIRED_ARTIFACTS: &[&str] = &[
    // ---- the seven trusted executables ----
    "supervisor.bin",
    "evidence-recorder-runner.bin",
    "privileged-launcher.bin",
    "contained-executor.bin",
    "isolated-signer.bin",
    "trusted-verifier-broker.bin",
    "desktop-challenge-authority.bin",
    // ---- each executable's config / policy bundle ----
    "supervisor.config",
    "evidence-recorder-runner.config",
    "privileged-launcher.config",
    "contained-executor.config",
    "isolated-signer.config",
    "trusted-verifier-broker.config",
    "desktop-challenge-authority.config",
    // ---- IPC / peer-auth policies for the two trusted services ----
    "trusted-verifier-broker.ipc-policy",
    "desktop-challenge-authority.ipc-policy",
    // ---- broker pinned-manifest configuration ----
    "trusted-verifier-broker.pinned-manifest-config",
    // ---- launch-steering + trust roots ----
    "governed-execution-allowlist.source",
    "key-manifest.root-anchor",
    // ---- both services' service/unit files ----
    "trusted-verifier-broker.unit",
    "desktop-challenge-authority.unit",
];

/// Verify the rev-30 §2.5 TCB-integrity floor. Fail-closed: returns `Err(TcbViolation)` at the FIRST
/// artifact (or ancestor) that is missing / wrong-owner / writable-by-login-or-runtime / hash-mismatched.
/// `Ok(())` ⇒ every pinned artifact and every ancestor up to `/` is TCB-owned, non-writable, and
/// hash-matched. Pure: all FS facts come through `probe`.
///
/// `runtime_uids` is every runtime service UID (broker, challenge-authority, sidecar, supervisor,
/// recorder, executor, signer); `login_uid` is the interactive login/renderer UID. They are used as
/// defense-in-depth: an artifact or ancestor owned by any of them is a violation even if it happened to
/// pass the writability flag.
pub fn verify_tcb_integrity(
    manifest: &TcbPinManifest,
    probe: &dyn FsProbe,
    runtime_uids: &[u32],
    login_uid: u32,
) -> Result<(), TcbViolation> {
    for art in &manifest.artifacts {
        verify_artifact(manifest, art, probe, runtime_uids, login_uid)?;
    }
    Ok(())
}

fn verify_artifact(
    manifest: &TcbPinManifest,
    art: &TcbArtifact,
    probe: &dyn FsProbe,
    runtime_uids: &[u32],
    login_uid: u32,
) -> Result<(), TcbViolation> {
    let facts = probe.stat(&art.path).ok_or_else(|| TcbViolation::Missing {
        logical_name: art.logical_name.clone(),
        path: art.path.clone(),
    })?;

    // Owner must be the exact expected dedicated-TCB principal, and never a runtime/login UID.
    let expected_uid = *manifest
        .owner_uids
        .get(&art.expected_owner)
        .ok_or(TcbViolation::UnknownOwner {
            logical_name: art.logical_name.clone(),
            owner: art.expected_owner,
        })?;
    let owner_is_untrusted =
        runtime_uids.contains(&facts.owner_uid) || facts.owner_uid == login_uid;
    if owner_is_untrusted || facts.owner_uid != expected_uid {
        return Err(TcbViolation::WrongOwner {
            logical_name: art.logical_name.clone(),
            path: art.path.clone(),
            expected_uid,
            actual_uid: facts.owner_uid,
        });
    }

    // Non-writability floor (mode bits, POSIX ACL, or group).
    if facts.is_world_or_group_writable || facts.writable_by_login_or_runtime {
        return Err(TcbViolation::WritableByUntrusted {
            logical_name: art.logical_name.clone(),
            path: art.path.clone(),
        });
    }

    // Content pin.
    if facts.sha256 != art.expected_sha256 {
        return Err(TcbViolation::HashMismatch {
            logical_name: art.logical_name.clone(),
            path: art.path.clone(),
            expected_sha256: art.expected_sha256.clone(),
            actual_sha256: facts.sha256,
        });
    }

    // Every ancestor directory up to `/` must be TCB-owned and non-writable (a writable ancestor is a
    // rename/replace vector and is treated as writable).
    for anc in ancestor_dirs(&art.path) {
        let af = probe.stat(&anc).ok_or_else(|| TcbViolation::AncestorMissing {
            logical_name: art.logical_name.clone(),
            ancestor: anc.clone(),
        })?;
        let anc_owner_untrusted = !manifest.is_tcb_owner(af.owner_uid)
            || runtime_uids.contains(&af.owner_uid)
            || af.owner_uid == login_uid;
        if anc_owner_untrusted {
            return Err(TcbViolation::AncestorWrongOwner {
                logical_name: art.logical_name.clone(),
                ancestor: anc,
                actual_uid: af.owner_uid,
            });
        }
        if af.is_world_or_group_writable || af.writable_by_login_or_runtime {
            return Err(TcbViolation::AncestorWritable {
                logical_name: art.logical_name.clone(),
                ancestor: anc,
            });
        }
    }

    Ok(())
}

/// The ancestor directories of `path`, from its immediate parent up to and including `/`. Paths are
/// treated as `/`-separated absolute strings (trailing slashes ignored). A path with no `/` yields no
/// ancestors.
fn ancestor_dirs(path: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = path.trim_end_matches('/');
    while let Some(i) = cur.rfind('/') {
        let parent = if i == 0 { "/" } else { &cur[..i] };
        out.push(parent.to_string());
        if i == 0 {
            break;
        }
        cur = &cur[..i];
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    // Principal fixture: root=0, brops-admin=500 own the TCB; the seven runtime UIDs are 1001..1007;
    // the interactive login/renderer is 1000. All disjoint (rev-30 §2.6 precondition).
    const ROOT: u32 = 0;
    const ADMIN: u32 = 500;
    const LOGIN: u32 = 1000;
    fn runtime_uids() -> Vec<u32> {
        vec![1001, 1002, 1003, 1004, 1005, 1006, 1007]
    }

    /// A fake filesystem: a path -> facts map implementing [`FsProbe`].
    #[derive(Default)]
    struct FakeFs {
        files: HashMap<String, FileFacts>,
    }

    impl FakeFs {
        fn good_dir(&mut self, path: &str, owner: u32) {
            self.files.insert(
                path.to_string(),
                FileFacts {
                    owner_uid: owner,
                    is_world_or_group_writable: false,
                    writable_by_login_or_runtime: false,
                    sha256: String::new(),
                },
            );
        }

        /// Insert a good (TCB-owned, non-writable, hash-matched) file plus every ancestor dir as a good
        /// root-owned directory.
        fn good_file(&mut self, path: &str, owner: u32, sha: &str) {
            self.files.insert(
                path.to_string(),
                FileFacts {
                    owner_uid: owner,
                    is_world_or_group_writable: false,
                    writable_by_login_or_runtime: false,
                    sha256: sha.to_string(),
                },
            );
            for anc in ancestor_dirs(path) {
                // Only create if absent so a test can later corrupt a specific ancestor.
                self.files.entry(anc).or_insert(FileFacts {
                    owner_uid: ROOT,
                    is_world_or_group_writable: false,
                    writable_by_login_or_runtime: false,
                    sha256: String::new(),
                });
            }
        }
    }

    impl FsProbe for FakeFs {
        fn stat(&self, path: &str) -> Option<FileFacts> {
            self.files.get(path).cloned()
        }
    }

    // Two representative artifacts: the broker binary (owner root) and the challenge-authority config
    // (owner brops-admin). Enough to exercise every code path; the required-set coverage is checked
    // separately by `manifest_missing_required_reports_the_gap`.
    const BROKER_PATH: &str = "/opt/brops/bin/trusted-verifier-broker";
    const BROKER_SHA: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const CA_CFG_PATH: &str = "/etc/brops/challenge-authority/policy.json";
    const CA_CFG_SHA: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    fn manifest() -> TcbPinManifest {
        let mut owner_uids = BTreeMap::new();
        owner_uids.insert(TcbOwner::Root, ROOT);
        owner_uids.insert(TcbOwner::BropsAdmin, ADMIN);
        TcbPinManifest {
            artifacts: vec![
                TcbArtifact {
                    logical_name: "trusted-verifier-broker.bin".into(),
                    path: BROKER_PATH.into(),
                    expected_sha256: BROKER_SHA.into(),
                    expected_owner: TcbOwner::Root,
                },
                TcbArtifact {
                    logical_name: "desktop-challenge-authority.config".into(),
                    path: CA_CFG_PATH.into(),
                    expected_sha256: CA_CFG_SHA.into(),
                    expected_owner: TcbOwner::BropsAdmin,
                },
            ],
            owner_uids,
        }
    }

    /// A fully-clean FS: both artifacts present, TCB-owned, non-writable, hash-matched, all ancestors good.
    fn clean_fs() -> FakeFs {
        let mut fs = FakeFs::default();
        fs.good_file(BROKER_PATH, ROOT, BROKER_SHA);
        fs.good_file(CA_CFG_PATH, ADMIN, CA_CFG_SHA);
        fs
    }

    #[test]
    fn all_tcb_owned_nonwritable_hashmatched_is_ok() {
        let m = manifest();
        let fs = clean_fs();
        assert_eq!(verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN), Ok(()));
    }

    #[test]
    fn login_writable_broker_binary_is_violation() {
        let m = manifest();
        let mut fs = clean_fs();
        // Sidecar/login could overwrite the broker image on disk => forge path (rev-30 §2.5).
        fs.files.get_mut(BROKER_PATH).unwrap().writable_by_login_or_runtime = true;
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        assert!(matches!(err, TcbViolation::WritableByUntrusted { .. }));
        assert_eq!(err.logical_name(), "trusted-verifier-broker.bin");
    }

    #[test]
    fn modified_challenge_authority_config_hash_mismatch_is_violation() {
        let m = manifest();
        let mut fs = clean_fs();
        fs.files.get_mut(CA_CFG_PATH).unwrap().sha256 =
            "ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc".into();
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        assert!(matches!(err, TcbViolation::HashMismatch { .. }));
        assert_eq!(err.logical_name(), "desktop-challenge-authority.config");
    }

    #[test]
    fn wrong_owner_is_violation() {
        let m = manifest();
        let mut fs = clean_fs();
        // Broker binary owned by the login user instead of root.
        fs.files.get_mut(BROKER_PATH).unwrap().owner_uid = LOGIN;
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        match err {
            TcbViolation::WrongOwner { expected_uid, actual_uid, .. } => {
                assert_eq!(expected_uid, ROOT);
                assert_eq!(actual_uid, LOGIN);
            }
            other => panic!("expected WrongOwner, got {other:?}"),
        }
    }

    #[test]
    fn wrong_owner_runtime_uid_is_violation() {
        let m = manifest();
        let mut fs = clean_fs();
        // Owned by a runtime service UID (e.g. the broker's own service UID) — still not a TCB owner.
        fs.files.get_mut(BROKER_PATH).unwrap().owner_uid = 1001;
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        assert!(matches!(err, TcbViolation::WrongOwner { .. }));
    }

    #[test]
    fn missing_artifact_is_violation() {
        let m = manifest();
        let mut fs = clean_fs();
        fs.files.remove(BROKER_PATH);
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        assert!(matches!(err, TcbViolation::Missing { .. }));
        assert_eq!(err.logical_name(), "trusted-verifier-broker.bin");
    }

    #[test]
    fn writable_ancestor_is_violation() {
        let m = manifest();
        let mut fs = clean_fs();
        // A writable parent dir lets an attacker rename/replace the broker binary.
        fs.files
            .get_mut("/opt/brops/bin")
            .unwrap()
            .writable_by_login_or_runtime = true;
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        match err {
            TcbViolation::AncestorWritable { ancestor, .. } => {
                assert_eq!(ancestor, "/opt/brops/bin");
            }
            other => panic!("expected AncestorWritable, got {other:?}"),
        }
    }

    #[test]
    fn wrong_owner_ancestor_is_violation() {
        let m = manifest();
        let mut fs = clean_fs();
        fs.good_dir("/opt/brops", LOGIN); // ancestor now login-owned
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        assert!(matches!(err, TcbViolation::AncestorWrongOwner { .. }));
    }

    #[test]
    fn missing_ancestor_is_violation() {
        let m = manifest();
        let mut fs = clean_fs();
        fs.files.remove("/opt/brops");
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        assert!(matches!(err, TcbViolation::AncestorMissing { .. }));
    }

    #[test]
    fn unknown_owner_in_manifest_is_violation() {
        let mut m = manifest();
        m.owner_uids.remove(&TcbOwner::Root); // pin manifest can no longer resolve root's UID
        let fs = clean_fs();
        let err = verify_tcb_integrity(&m, &fs, &runtime_uids(), LOGIN).unwrap_err();
        assert!(matches!(err, TcbViolation::UnknownOwner { owner: TcbOwner::Root, .. }));
    }

    #[test]
    fn ancestor_dirs_walks_up_to_root() {
        assert_eq!(
            ancestor_dirs("/opt/brops/bin/broker"),
            vec!["/opt/brops/bin", "/opt/brops", "/opt", "/"]
        );
        assert_eq!(ancestor_dirs("/x"), vec!["/"]);
        assert!(ancestor_dirs("noslash").is_empty());
    }

    #[test]
    fn manifest_missing_required_reports_the_gap() {
        // The 2-artifact test manifest is intentionally partial: coverage check must flag the rest.
        let gap = manifest().missing_required();
        assert!(gap.contains(&"supervisor.bin"));
        assert!(gap.contains(&"privileged-launcher.bin"));
        assert!(gap.contains(&"trusted-verifier-broker.pinned-manifest-config"));
        // A manifest listing every required name has no gap.
        let full = TcbPinManifest {
            artifacts: TCB_REQUIRED_ARTIFACTS
                .iter()
                .map(|n| TcbArtifact {
                    logical_name: (*n).to_string(),
                    path: format!("/opt/brops/{n}"),
                    expected_sha256: BROKER_SHA.into(),
                    expected_owner: TcbOwner::Root,
                })
                .collect(),
            owner_uids: BTreeMap::new(),
        };
        assert!(full.missing_required().is_empty());
    }
}
