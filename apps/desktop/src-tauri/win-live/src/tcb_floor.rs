//! The §2.5 **TCB binary & config integrity floor** for the Windows live kit (audit **R2**).
//!
//! ## Why this exists
//!
//! The Linux leg has a §2.5 floor: `brops_core::tcb_integrity` decides it as a pure function over an
//! injected FS probe, `broker/src/tcb_probe.rs` supplies the real probe, and
//! `engine/ci/live/build_tcb_pin_manifest.py` emits the root-owned pin manifest. Nothing serves a
//! governed turn until every pinned artifact has been re-measured.
//!
//! The Windows kit had **none of it**. Every server bin loaded `config.json`, read its seed and started
//! serving; the driver read the manifest and ran the chain. The ed25519 checks downstream are only as
//! good as the binaries that perform them, and nothing had ever measured those binaries — an adversary
//! who could replace `win_signer.exe` or edit `config.json` between provisioning and start-up faced no
//! check at all.
//!
//! This module is the Windows equivalent. Windows has no uid/mode, so ownership and the DACL replace
//! them: an artifact must be owned by a compiled-in TCB principal ([`TCB_OWNER_SIDS`]) and its DACL
//! must grant **no write authority to any non-TCB principal** — including the NULL-DACL case, which
//! Windows treats as *everyone full control* (see [`crate::pipe_acl::dacl_is_open`]).
//!
//! ## Shape, deliberately mirroring the Linux side
//!
//! * [`verify_win_tcb_integrity`] is **pure**: every filesystem fact arrives through [`WinFsProbe`], so
//!   the whole decision is unit-testable on the Linux CI runner (this kit's Windows-only code is
//!   covered by no CI, which is itself an audit finding — keeping the decision host-independent is the
//!   only way any of it is guarded).
//! * [`WindowsFsProbe`] is the real `GetNamedSecurityInfoW` + DACL-walk + SHA-256 probe.
//! * `win_tcb_pin` (the bin) is the twin of `build_tcb_pin_manifest.py`.
//! * Callers map any `Err` to "do not serve" — never a partial pass.
//!
//! ## What this floor does NOT cover (stated, not implied away)
//!
//! This is the **measurable core**, not a full port of the Linux §2.5 set. Specifically:
//!
//! * **No TOCTOU-proof path handle.** The Linux probe stats an `O_NOFOLLOW|O_PATH` fd so the measured
//!   object cannot be swapped by a symlink. [`WindowsFsProbe`] measures by PATH
//!   (`GetNamedSecurityInfoW` + `std::fs::read`), so a directory junction or a rename inserted between
//!   the measurement and the later use is NOT defended against. Closing this needs
//!   `CreateFileW(FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS)` + `GetSecurityInfo` on
//!   the handle, and re-opening every consumer by handle — not done here.
//! * **No Authenticode requirement.** `brops_win_broker::syscall::image_authenticode_valid` exists, but
//!   the kit's own bins are unsigned dev builds, so requiring it would make the floor unsatisfiable and
//!   pretending to check it would be worse. Only the content digest is pinned.
//! * **No inherited-ACE / effective-access resolution.** The DACL walk reads ACCESS_ALLOWED ACEs and
//!   ignores ACCESS_DENIED ACEs. Ignoring denies can only make the probe report MORE writers than
//!   reality, which is the fail-closed direction; group membership is NOT expanded, so an ACE granting
//!   write to a custom group whose members include an untrusted principal is reported by its group SID
//!   and (unless that group SID is a [`crate::pipe_acl::WORLD_SIDS`] entry) counted as untrusted —
//!   again the safe direction, but it means the floor cannot be satisfied by a deployment that grants
//!   write to any non-TCB group, deliberately.
//! * **The key seed files are not content-pinned.** They are DPAPI-sealed in place on first read
//!   (`config::read_seed`), so their bytes legitimately change; a digest pin would be a false check.
//!   Their custody is the ACL `win_provision` applies. They are therefore outside this floor.
//! * **No service/unit definition is pinned.** The Linux manifest pins the orchestrator; the Windows
//!   servers are started by scheduled tasks whose XML lives in the Task Scheduler store, which this
//!   floor does not read.
//! * **The floor is start-time only**, exactly like the Linux one: a swap performed after the
//!   measurement and before the next start is not detected.

use serde::{Deserialize, Serialize};

use crate::pipe_acl::{dacl_is_open, PipeAce, SID_ADMINISTRATORS, SID_LOCAL_SYSTEM, WRITE_ACCESS_BITS};

/// Env var naming the deployment's pin manifest. Unset ⇒ the caller refuses to serve; "unconfigured"
/// is never the same as "satisfied" (the Linux `BROPS_TCB_PIN_MANIFEST` rule).
pub const WIN_TCB_PIN_MANIFEST_ENV: &str = "BROPS_WIN_TCB_PIN_MANIFEST";

/// The principals allowed to OWN a TCB artifact, **compiled in** — the same pinning argument as
/// `crate::tcb::ROOT_PUBLIC_KEY_HEX`. If the trusted-owner set came from the manifest, an adversary who
/// could write the manifest could name themselves as the trusted owner and the floor would agree.
///
/// `SYSTEM` and `BUILTIN\Administrators` are the local TCB: a member of either can already take
/// ownership of any object on the box, so they are the strongest ownership statement Windows offers
/// without a dedicated domain-managed principal. A deployment that wants a narrower dedicated
/// `brops-admin` principal cannot express it here yet — that would need this constant to become a
/// build-time configured value, which is a change to the trust anchor and is left for the operator
/// ceremony rather than invented.
pub const TCB_OWNER_SIDS: &[&str] = &[SID_LOCAL_SYSTEM, SID_ADMINISTRATORS];

/// The logical artifacts a conforming Windows pin manifest MUST cover. An artifact that is not listed
/// is never measured, so an under-specified manifest fails closed (the Linux coverage floor's rule).
///
/// This is the set that actually serves a governed turn in THIS kit — the four processes plus the
/// files that steer them. It is smaller than the Linux `TCB_REQUIRED_ARTIFACTS` because this kit has no
/// privileged setuid launcher and no separate evidence-recorder binary; naming roles that do not exist
/// here would make the manifest describe a deployment that isn't this one.
pub const WIN_TCB_REQUIRED_ARTIFACTS: &[&str] = &[
    // ---- the processes ----
    "challenge-authority.bin",     // win_authority.exe
    "governed-supervisor.bin",     // win_supervisor.exe
    "isolated-signer.bin",         // win_signer.exe
    "trusted-verifier-broker.bin", // win_live_turn.exe (the driver/broker)
    "contained-executor.bin",      // win_executor.exe
    // ---- what steers them ----
    "kit.config",                   // config.json — all four load it
    "key-manifest.root-anchor",     // manifest.json
    "key-manifest.root-signature",  // manifest.sig
    "anti-rollback-floor",          // floor.json
];

/// One pinned artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WinTcbArtifact {
    /// One of [`WIN_TCB_REQUIRED_ARTIFACTS`].
    pub logical_name: String,
    /// Absolute local path (`C:\…`). UNC and relative paths are refused — the floor cannot reason
    /// about an ancestor chain it cannot name.
    pub path: String,
    /// Lowercase-hex SHA-256 of the exact on-disk bytes at pin time.
    pub expected_sha256: String,
    /// String SID that MUST own the file. Checked for membership of [`TCB_OWNER_SIDS`], so a manifest
    /// cannot nominate an attacker-controlled owner.
    pub expected_owner_sid: String,
}

/// The deployment's pin manifest.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WinTcbPinManifest {
    pub artifacts: Vec<WinTcbArtifact>,
}

impl WinTcbPinManifest {
    /// Required logical names this manifest does not cover.
    pub fn missing_required(&self) -> Vec<&'static str> {
        WIN_TCB_REQUIRED_ARTIFACTS
            .iter()
            .copied()
            .filter(|req| !self.artifacts.iter().any(|a| a.logical_name == *req))
            .collect()
    }
}

/// What a [`WinFsProbe`] reports about one path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WinFileFacts {
    /// Owning principal's string SID.
    pub owner_sid: String,
    /// `false` ⇒ the object has a **NULL DACL**, which Windows reads as everyone-full-control.
    pub dacl_present: bool,
    /// The ACCESS_ALLOWED ACEs of the DACL (deny ACEs are deliberately not modelled; see the module
    /// docs — ignoring them over-reports writers, which is the fail-closed direction).
    pub allow_aces: Vec<PipeAce>,
    /// Lowercase-hex SHA-256 of the bytes; empty for a directory.
    pub sha256: String,
    /// Directory or file.
    pub is_dir: bool,
}

/// The only way [`verify_win_tcb_integrity`] learns about the on-disk world.
pub trait WinFsProbe {
    /// Facts about `path`, or `None` when it does not exist / cannot be read.
    fn stat(&self, path: &str) -> Option<WinFileFacts>;
}

/// A §2.5 violation. Any value ⇒ the caller must refuse to serve.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WinTcbViolation {
    /// The manifest omits required artifacts, so they would never be measured.
    MissingRequired { missing: Vec<String> },
    /// The pin manifest file itself is absent, foreign-owned, or writable by a non-TCB principal.
    ManifestCustody { path: String, why: String },
    /// A pinned path is not an absolute local path (relative, UNC, or driveless).
    NonAbsolutePath { logical_name: String, path: String },
    /// The artifact is not on disk.
    Missing { logical_name: String, path: String },
    /// The manifest names an owner that is not a compiled-in TCB principal.
    UntrustedExpectedOwner { logical_name: String, expected_owner_sid: String },
    /// The on-disk owner is not the pinned owner.
    WrongOwner { logical_name: String, path: String, expected: String, actual: String },
    /// Some non-TCB principal holds write authority (or the DACL is NULL).
    WritableByUntrusted { logical_name: String, path: String, grantees: Vec<String> },
    /// The bytes changed since the pin.
    HashMismatch { logical_name: String, path: String, expected: String, actual: String },
    /// An ancestor directory is absent (a rename/replace vector).
    AncestorMissing { logical_name: String, ancestor: String },
    /// An ancestor directory is not TCB-owned.
    AncestorWrongOwner { logical_name: String, ancestor: String, actual: String },
    /// An ancestor directory is writable by a non-TCB principal — replace-the-parent beats any digest
    /// pin on the child, so ancestors are part of the floor.
    AncestorWritable { logical_name: String, ancestor: String, grantees: Vec<String> },
}

/// Which non-TCB principals hold write authority over an object with these facts.
///
/// A NULL DACL yields a single synthetic grantee rather than an empty list: "no DACL" is the most
/// permissive state Windows has, and reporting it as "no writers" is precisely the bug this floor and
/// [`crate::pipe_acl`] were both written to kill.
pub fn untrusted_write_grantees(facts: &WinFileFacts) -> Vec<String> {
    if !facts.dacl_present {
        return vec!["<null-dacl:everyone>".to_string()];
    }
    let mut out: Vec<String> = facts
        .allow_aces
        .iter()
        .filter(|a| a.mask & WRITE_ACCESS_BITS != 0)
        .filter(|a| !TCB_OWNER_SIDS.contains(&a.sid.as_str()))
        .map(|a| a.sid.clone())
        .collect();
    // A world SID with even read access is still an open descriptor by the shared rule; surface it so
    // the two modules cannot drift apart on what "open" means.
    if dacl_is_open(facts.dacl_present, &facts.allow_aces) {
        for w in crate::pipe_acl::world_grantees(&facts.allow_aces) {
            if !out.iter().any(|s| s == w) {
                out.push(w.to_string());
            }
        }
    }
    out.sort();
    out.dedup();
    out
}

/// Custody check for the pin manifest FILE itself. Without this the floor is circular: a manifest an
/// adversary can rewrite lets them re-pin the digests of the binaries they just replaced.
pub fn check_manifest_custody(path: &str, facts: Option<&WinFileFacts>) -> Result<(), WinTcbViolation> {
    let facts = facts.ok_or_else(|| WinTcbViolation::ManifestCustody {
        path: path.to_string(),
        why: "pin manifest absent or unreadable".to_string(),
    })?;
    if !TCB_OWNER_SIDS.contains(&facts.owner_sid.as_str()) {
        return Err(WinTcbViolation::ManifestCustody {
            path: path.to_string(),
            why: format!("pin manifest owner {} is not a TCB principal", facts.owner_sid),
        });
    }
    let writers = untrusted_write_grantees(facts);
    if !writers.is_empty() {
        return Err(WinTcbViolation::ManifestCustody {
            path: path.to_string(),
            why: format!("pin manifest is writable by {writers:?}"),
        });
    }
    Ok(())
}

/// Verify the §2.5 floor. Fail-closed at the FIRST failing artifact or ancestor; `Ok(())` means every
/// pinned artifact and every ancestor directory up to the drive root is TCB-owned, non-writable by any
/// non-TCB principal, and byte-identical to the pin. Pure — all FS facts come through `probe`.
pub fn verify_win_tcb_integrity(
    manifest: &WinTcbPinManifest,
    probe: &dyn WinFsProbe,
) -> Result<(), WinTcbViolation> {
    // Coverage first: the per-artifact loop only inspects LISTED entries, so an omitted artifact would
    // otherwise pass by never being looked at.
    let missing = manifest.missing_required();
    if !missing.is_empty() {
        return Err(WinTcbViolation::MissingRequired {
            missing: missing.into_iter().map(str::to_string).collect(),
        });
    }
    for art in &manifest.artifacts {
        verify_artifact(art, probe)?;
    }
    Ok(())
}

fn verify_artifact(art: &WinTcbArtifact, probe: &dyn WinFsProbe) -> Result<(), WinTcbViolation> {
    if !TCB_OWNER_SIDS.contains(&art.expected_owner_sid.as_str()) {
        return Err(WinTcbViolation::UntrustedExpectedOwner {
            logical_name: art.logical_name.clone(),
            expected_owner_sid: art.expected_owner_sid.clone(),
        });
    }
    let ancestors = ancestor_dirs_win(&art.path).ok_or_else(|| WinTcbViolation::NonAbsolutePath {
        logical_name: art.logical_name.clone(),
        path: art.path.clone(),
    })?;

    let facts = probe.stat(&art.path).ok_or_else(|| WinTcbViolation::Missing {
        logical_name: art.logical_name.clone(),
        path: art.path.clone(),
    })?;
    if facts.owner_sid != art.expected_owner_sid {
        return Err(WinTcbViolation::WrongOwner {
            logical_name: art.logical_name.clone(),
            path: art.path.clone(),
            expected: art.expected_owner_sid.clone(),
            actual: facts.owner_sid,
        });
    }
    let writers = untrusted_write_grantees(&facts);
    if !writers.is_empty() {
        return Err(WinTcbViolation::WritableByUntrusted {
            logical_name: art.logical_name.clone(),
            path: art.path.clone(),
            grantees: writers,
        });
    }
    if facts.sha256 != art.expected_sha256 {
        return Err(WinTcbViolation::HashMismatch {
            logical_name: art.logical_name.clone(),
            path: art.path.clone(),
            expected: art.expected_sha256.clone(),
            actual: facts.sha256,
        });
    }

    for anc in ancestors {
        let af = probe.stat(&anc).ok_or_else(|| WinTcbViolation::AncestorMissing {
            logical_name: art.logical_name.clone(),
            ancestor: anc.clone(),
        })?;
        if !TCB_OWNER_SIDS.contains(&af.owner_sid.as_str()) {
            return Err(WinTcbViolation::AncestorWrongOwner {
                logical_name: art.logical_name.clone(),
                ancestor: anc,
                actual: af.owner_sid,
            });
        }
        let w = untrusted_write_grantees(&af);
        if !w.is_empty() {
            return Err(WinTcbViolation::AncestorWritable {
                logical_name: art.logical_name.clone(),
                ancestor: anc,
                grantees: w,
            });
        }
    }
    Ok(())
}

/// Ancestor directories of an absolute local Windows path, immediate parent first, up to and including
/// the drive root (`C:\`). `None` for anything that is not an absolute `X:\…` path — a relative path
/// has no fixed ancestor chain and a UNC path's ancestors live on another host, so both are refused
/// rather than half-checked.
pub fn ancestor_dirs_win(path: &str) -> Option<Vec<String>> {
    let norm = path.replace('/', "\\");
    let bytes = norm.as_bytes();
    if norm.starts_with("\\\\") {
        return None; // UNC
    }
    if bytes.len() < 3 || !bytes[0].is_ascii_alphabetic() || bytes[1] != b':' || bytes[2] != b'\\' {
        return None;
    }
    let root = norm[..3].to_string(); // "C:\"
    let mut out = Vec::new();
    let mut cur = norm.trim_end_matches('\\').to_string();
    while let Some(i) = cur.rfind('\\') {
        if i < 3 {
            break;
        }
        cur = cur[..i].to_string();
        out.push(cur.clone());
    }
    out.push(root);
    Some(out)
}

// =================================================================================================
// The real probe + the deployment entry point
// =================================================================================================

/// Load + parse the pin manifest. Any problem is `None`; every caller treats `None` as "do not serve".
pub fn load_pin_manifest(path: &str) -> Option<WinTcbPinManifest> {
    let raw = std::fs::read_to_string(path).ok()?;
    serde_json::from_str::<WinTcbPinManifest>(&raw).ok()
}

/// Run the §2.5 floor for a deployment, fail-closed. `Ok(())` ⇒ the kit may serve a governed turn.
///
/// On a non-Windows host this ALWAYS refuses: the floor is stated in owner-SID and DACL facts that do
/// not exist there, and a floor that cannot be evaluated must never be reported as satisfied. (The
/// Linux leg refuses symmetrically on non-Linux.)
pub fn verify_deployment_tcb(manifest_path: Option<&str>) -> Result<(), String> {
    let path = manifest_path.filter(|p| !p.is_empty()).ok_or_else(|| {
        format!("no Windows TCB pin manifest configured ({WIN_TCB_PIN_MANIFEST_ENV} unset and config.tcb_pin_manifest empty)")
    })?;

    #[cfg(windows)]
    {
        let probe = WindowsFsProbe;
        check_manifest_custody(path, probe.stat(path).as_ref()).map_err(|v| format!("{v:?}"))?;
        let manifest = load_pin_manifest(path)
            .ok_or_else(|| format!("TCB pin manifest unreadable or malformed: {path}"))?;
        verify_win_tcb_integrity(&manifest, &probe).map_err(|v| format!("{v:?}"))
    }
    #[cfg(not(windows))]
    {
        let _ = path;
        Err("Windows TCB integrity floor requires Windows (owner-SID + DACL facts)".to_string())
    }
}

/// Enforce the floor or terminate. The single call every Windows bin makes before it serves anything.
///
/// Exits with code 5 on refusal rather than returning, so there is no path where a caller "handles" a
/// §2.5 failure by continuing.
#[cfg(windows)]
pub fn enforce_or_exit(component: &str, manifest_path: Option<&str>) {
    match verify_deployment_tcb(manifest_path) {
        Ok(()) => println!("TCB: {component} §2.5 integrity floor satisfied"),
        Err(why) => {
            eprintln!("TCB: {component} REFUSING to serve — §2.5 integrity floor not satisfied");
            eprintln!("TCB: {why}");
            eprintln!(
                "TCB: build the pin manifest with `win_tcb_pin --root-dir <deploy> --bin-dir <bins> \
                 --out <deploy>\\tcb-pin.json`, restrict it to SYSTEM/Administrators, then point \
                 {WIN_TCB_PIN_MANIFEST_ENV} (or config.tcb_pin_manifest) at it."
            );
            std::process::exit(5);
        }
    }
}

#[cfg(windows)]
pub use winfs::WindowsFsProbe;

#[cfg(windows)]
mod winfs {
    //! The real probe: owner SID + DACL via `GetNamedSecurityInfoW`, content digest via `std::fs::read`.

    use super::{WinFileFacts, WinFsProbe};
    use crate::pipe_acl::PipeAce;
    use std::ffi::c_void;
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{LocalFree, ERROR_SUCCESS, HLOCAL};
    use windows::Win32::Security::Authorization::{
        ConvertSidToStringSidW, GetNamedSecurityInfoW, SE_FILE_OBJECT,
    };
    use windows::Win32::Security::{
        AclSizeInformation, GetAce, GetAclInformation, ACCESS_ALLOWED_ACE, ACE_HEADER,
        ACL_SIZE_INFORMATION, DACL_SECURITY_INFORMATION, OWNER_SECURITY_INFORMATION,
        PSECURITY_DESCRIPTOR, PSID,
    };
    use windows::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;

    /// The real filesystem probe. Measures by PATH — see the module-level note about the TOCTOU gap
    /// this leaves open relative to the Linux `O_NOFOLLOW` probe.
    pub struct WindowsFsProbe;

    unsafe fn sid_string(psid: PSID) -> Option<String> {
        let mut wide = windows::core::PWSTR::null();
        ConvertSidToStringSidW(psid, &mut wide).ok()?;
        let s = wide.to_string().ok();
        let _ = LocalFree(HLOCAL(wide.0 as *mut c_void));
        s
    }

    /// Owner SID + whether a DACL is present + its ACCESS_ALLOWED ACEs.
    fn security_facts(path: &str) -> Option<(String, bool, Vec<PipeAce>)> {
        let wide: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
        unsafe {
            let mut owner = PSID::default();
            let mut dacl: *mut windows::Win32::Security::ACL = std::ptr::null_mut();
            let mut psd = PSECURITY_DESCRIPTOR::default();
            let rc = GetNamedSecurityInfoW(
                PCWSTR(wide.as_ptr()),
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                Some(&mut owner),
                None,
                Some(&mut dacl),
                None,
                &mut psd,
            );
            if rc != ERROR_SUCCESS {
                return None;
            }
            let owner_sid = sid_string(owner);
            // A NULL `dacl` here is the NULL-DACL case (everyone full control), NOT "no access".
            let dacl_present = !dacl.is_null();
            let mut aces: Vec<PipeAce> = Vec::new();
            if dacl_present {
                let mut info = ACL_SIZE_INFORMATION::default();
                let ok = GetAclInformation(
                    dacl,
                    &mut info as *mut _ as *mut c_void,
                    std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                    AclSizeInformation,
                );
                if ok.is_ok() {
                    for i in 0..info.AceCount {
                        let mut pace: *mut c_void = std::ptr::null_mut();
                        if GetAce(dacl, i, &mut pace).is_err() || pace.is_null() {
                            continue;
                        }
                        let hdr = &*(pace as *const ACE_HEADER);
                        // Deny ACEs are skipped on purpose: ignoring them over-reports writers, which
                        // is the fail-closed direction (see module docs).
                        if hdr.AceType as u32 != ACCESS_ALLOWED_ACE_TYPE {
                            continue;
                        }
                        let ace = &*(pace as *const ACCESS_ALLOWED_ACE);
                        let psid = PSID(&ace.SidStart as *const u32 as *mut c_void);
                        if let Some(sid) = sid_string(psid) {
                            aces.push(PipeAce { sid, mask: ace.Mask });
                        }
                    }
                }
            }
            // `psd` is a LocalAlloc'd block owning both `owner` and `dacl`; free it after we have
            // copied everything out into owned Rust values.
            if !psd.is_invalid() {
                let _ = LocalFree(HLOCAL(psd.0));
            }
            Some((owner_sid?, dacl_present, aces))
        }
    }

    impl WinFsProbe for WindowsFsProbe {
        fn stat(&self, path: &str) -> Option<WinFileFacts> {
            let meta = std::fs::metadata(path).ok()?;
            let (owner_sid, dacl_present, allow_aces) = security_facts(path)?;
            let is_dir = meta.is_dir();
            let sha256 = if is_dir {
                String::new()
            } else {
                crate::crypto::sha256_hex(&std::fs::read(path).ok()?)
            };
            Some(WinFileFacts { owner_sid, dacl_present, allow_aces, sha256, is_dir })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    const ADMIN: &str = SID_ADMINISTRATORS;
    const LOGIN: &str = "S-1-5-21-11-22-33-1001";

    /// An injected filesystem: the whole §2.5 decision is exercised without touching a real disk or a
    /// single winapi call, which is why these tests run on the Linux CI runner.
    struct FakeFs(BTreeMap<String, WinFileFacts>);

    impl WinFsProbe for FakeFs {
        fn stat(&self, path: &str) -> Option<WinFileFacts> {
            self.0.get(path).cloned()
        }
    }

    fn locked(sha: &str) -> WinFileFacts {
        WinFileFacts {
            owner_sid: ADMIN.to_string(),
            dacl_present: true,
            allow_aces: vec![
                PipeAce { sid: SID_LOCAL_SYSTEM.to_string(), mask: 0x001F_01FF },
                PipeAce { sid: ADMIN.to_string(), mask: 0x001F_01FF },
            ],
            sha256: sha.to_string(),
            is_dir: sha.is_empty(),
        }
    }

    /// A good deployment: five bins + four steering files under `C:\brops\`, all Administrators-owned
    /// with an Administrators/SYSTEM-only DACL.
    fn good_world() -> (WinTcbPinManifest, FakeFs) {
        let mut fs = BTreeMap::new();
        for d in ["C:\\", "C:\\brops", "C:\\brops\\bin"] {
            fs.insert(d.to_string(), locked(""));
        }
        let mut artifacts = Vec::new();
        for (i, name) in WIN_TCB_REQUIRED_ARTIFACTS.iter().enumerate() {
            let path = format!("C:\\brops\\bin\\{name}");
            let sha = format!("{i:064x}");
            fs.insert(path.clone(), locked(&sha));
            artifacts.push(WinTcbArtifact {
                logical_name: (*name).to_string(),
                path,
                expected_sha256: sha,
                expected_owner_sid: ADMIN.to_string(),
            });
        }
        (WinTcbPinManifest { artifacts }, FakeFs(fs))
    }

    #[test]
    fn a_fully_pinned_locked_down_deployment_passes() {
        // The positive case has to hold, or every negative below is vacuous.
        let (m, fs) = good_world();
        assert_eq!(verify_win_tcb_integrity(&m, &fs), Ok(()));
    }

    #[test]
    fn an_under_specified_manifest_is_refused() {
        let (mut m, fs) = good_world();
        m.artifacts.retain(|a| a.logical_name != "isolated-signer.bin");
        match verify_win_tcb_integrity(&m, &fs) {
            Err(WinTcbViolation::MissingRequired { missing }) => {
                assert_eq!(missing, vec!["isolated-signer.bin".to_string()])
            }
            other => panic!("expected coverage refusal, got {other:?}"),
        }
    }

    #[test]
    fn a_replaced_binary_is_caught_by_the_digest_pin() {
        // Swap the signer's bytes: this is the attack the whole floor exists for.
        let (m, mut fs) = good_world();
        let p = "C:\\brops\\bin\\isolated-signer.bin";
        fs.0.insert(p.to_string(), locked(&"ab".repeat(32)));
        assert!(matches!(
            verify_win_tcb_integrity(&m, &fs),
            Err(WinTcbViolation::HashMismatch { .. })
        ));
    }

    #[test]
    fn a_login_owned_artifact_is_refused() {
        let (m, mut fs) = good_world();
        let p = "C:\\brops\\bin\\kit.config";
        let mut f = locked(&format!("{:064x}", 5));
        f.owner_sid = LOGIN.to_string();
        fs.0.insert(p.to_string(), f);
        assert!(matches!(verify_win_tcb_integrity(&m, &fs), Err(WinTcbViolation::WrongOwner { .. })));
    }

    #[test]
    fn a_null_dacl_artifact_is_refused_not_treated_as_locked() {
        // The exact confusion that made FILE_FLAG_FIRST_PIPE_INSTANCE inert: NULL DACL == open.
        let (m, mut fs) = good_world();
        let p = "C:\\brops\\bin\\governed-supervisor.bin";
        let mut f = locked(&format!("{:064x}", 1));
        f.dacl_present = false;
        f.allow_aces.clear();
        fs.0.insert(p.to_string(), f);
        match verify_win_tcb_integrity(&m, &fs) {
            Err(WinTcbViolation::WritableByUntrusted { grantees, .. }) => {
                assert_eq!(grantees, vec!["<null-dacl:everyone>".to_string()])
            }
            other => panic!("expected NULL-DACL refusal, got {other:?}"),
        }
    }

    #[test]
    fn an_artifact_writable_by_a_non_tcb_principal_is_refused() {
        let (m, mut fs) = good_world();
        let p = "C:\\brops\\bin\\trusted-verifier-broker.bin";
        let mut f = locked(&format!("{:064x}", 3));
        f.allow_aces.push(PipeAce { sid: LOGIN.to_string(), mask: crate::pipe_acl::FILE_WRITE_DATA });
        fs.0.insert(p.to_string(), f);
        match verify_win_tcb_integrity(&m, &fs) {
            Err(WinTcbViolation::WritableByUntrusted { grantees, .. }) => {
                assert_eq!(grantees, vec![LOGIN.to_string()])
            }
            other => panic!("expected writable refusal, got {other:?}"),
        }
    }

    #[test]
    fn read_only_access_for_a_non_tcb_principal_is_still_allowed() {
        // The floor forbids WRITE authority, not the ability to execute/read the binaries — the broker
        // account must be able to run them. If this ever fails, the floor became unsatisfiable and a
        // deployment would be pushed toward loosening it.
        let (m, mut fs) = good_world();
        let p = "C:\\brops\\bin\\contained-executor.bin";
        let mut f = locked(&format!("{:064x}", 4));
        f.allow_aces.push(PipeAce {
            sid: LOGIN.to_string(),
            mask: crate::pipe_acl::FILE_READ_DATA | crate::pipe_acl::FILE_READ_ATTRIBUTES,
        });
        fs.0.insert(p.to_string(), f);
        assert_eq!(verify_win_tcb_integrity(&m, &fs), Ok(()));
    }

    #[test]
    fn a_writable_ancestor_directory_is_refused() {
        // Replace-the-parent beats any digest pin on the child.
        let (m, mut fs) = good_world();
        let mut d = locked("");
        d.allow_aces.push(PipeAce { sid: LOGIN.to_string(), mask: crate::pipe_acl::DELETE });
        fs.0.insert("C:\\brops".to_string(), d);
        assert!(matches!(
            verify_win_tcb_integrity(&m, &fs),
            Err(WinTcbViolation::AncestorWritable { .. })
        ));
    }

    #[test]
    fn a_login_owned_ancestor_directory_is_refused() {
        let (m, mut fs) = good_world();
        let mut d = locked("");
        d.owner_sid = LOGIN.to_string();
        fs.0.insert("C:\\brops\\bin".to_string(), d);
        assert!(matches!(
            verify_win_tcb_integrity(&m, &fs),
            Err(WinTcbViolation::AncestorWrongOwner { .. })
        ));
    }

    #[test]
    fn a_missing_artifact_is_refused() {
        let (m, mut fs) = good_world();
        fs.0.remove("C:\\brops\\bin\\kit.config");
        assert!(matches!(verify_win_tcb_integrity(&m, &fs), Err(WinTcbViolation::Missing { .. })));
    }

    #[test]
    fn a_manifest_nominating_a_non_tcb_owner_is_refused() {
        // Without this, an adversary who can write the manifest names themselves the trusted owner and
        // the ownership floor evaporates.
        let (mut m, mut fs) = good_world();
        let p = "C:\\brops\\bin\\kit.config";
        let mut f = locked(&format!("{:064x}", 5));
        f.owner_sid = LOGIN.to_string();
        fs.0.insert(p.to_string(), f);
        for a in m.artifacts.iter_mut() {
            if a.logical_name == "kit.config" {
                a.expected_owner_sid = LOGIN.to_string();
            }
        }
        assert!(matches!(
            verify_win_tcb_integrity(&m, &fs),
            Err(WinTcbViolation::UntrustedExpectedOwner { .. })
        ));
    }

    #[test]
    fn a_relative_or_unc_path_is_refused_rather_than_half_checked() {
        let (mut m, fs) = good_world();
        m.artifacts[0].path = "..\\bin\\win_authority.exe".to_string();
        assert!(matches!(
            verify_win_tcb_integrity(&m, &fs),
            Err(WinTcbViolation::NonAbsolutePath { .. })
        ));
        let (mut m, fs) = good_world();
        m.artifacts[0].path = "\\\\host\\share\\win_authority.exe".to_string();
        assert!(matches!(
            verify_win_tcb_integrity(&m, &fs),
            Err(WinTcbViolation::NonAbsolutePath { .. })
        ));
    }

    #[test]
    fn ancestors_walk_up_to_the_drive_root() {
        assert_eq!(
            ancestor_dirs_win("C:\\ProgramData\\brops\\bin\\x.exe").unwrap(),
            vec!["C:\\ProgramData\\brops\\bin", "C:\\ProgramData\\brops", "C:\\ProgramData", "C:\\"]
        );
        assert_eq!(ancestor_dirs_win("C:\\x.exe").unwrap(), vec!["C:\\"]);
        assert!(ancestor_dirs_win("relative\\x.exe").is_none());
        assert!(ancestor_dirs_win("\\\\srv\\s\\x.exe").is_none());
    }

    #[test]
    fn manifest_custody_refuses_an_absent_foreign_or_writable_manifest() {
        assert!(matches!(
            check_manifest_custody("C:\\brops\\tcb-pin.json", None),
            Err(WinTcbViolation::ManifestCustody { .. })
        ));
        let mut foreign = locked(&"11".repeat(32));
        foreign.owner_sid = LOGIN.to_string();
        assert!(matches!(
            check_manifest_custody("C:\\brops\\tcb-pin.json", Some(&foreign)),
            Err(WinTcbViolation::ManifestCustody { .. })
        ));
        let mut writable = locked(&"11".repeat(32));
        writable.allow_aces.push(PipeAce { sid: LOGIN.to_string(), mask: crate::pipe_acl::WRITE_DAC });
        assert!(matches!(
            check_manifest_custody("C:\\brops\\tcb-pin.json", Some(&writable)),
            Err(WinTcbViolation::ManifestCustody { .. })
        ));
        assert_eq!(
            check_manifest_custody("C:\\brops\\tcb-pin.json", Some(&locked(&"11".repeat(32)))),
            Ok(())
        );
    }

    #[test]
    fn an_unconfigured_floor_refuses_rather_than_passing() {
        // "Unconfigured" must never read as "satisfied" — the single most important property of a
        // floor that is not yet deployed everywhere.
        let e = verify_deployment_tcb(None).unwrap_err();
        assert!(e.contains("no Windows TCB pin manifest configured"), "{e}");
        let e = verify_deployment_tcb(Some("")).unwrap_err();
        assert!(e.contains("no Windows TCB pin manifest configured"), "{e}");
    }

    #[cfg(not(windows))]
    #[test]
    fn on_a_non_windows_host_the_floor_refuses_instead_of_claiming_satisfaction() {
        let e = verify_deployment_tcb(Some("C:\\brops\\tcb-pin.json")).unwrap_err();
        assert!(e.contains("requires Windows"), "{e}");
    }

    // The real probe. Windows-only, so NOT covered by the Linux CI runner — the pure tests above are
    // what CI guards. These exist because the `GetNamedSecurityInfoW` + ACE-walk is unsafe code that
    // would otherwise never execute until a deployment depended on it.
    #[cfg(windows)]
    mod real_probe {
        use super::super::*;

        #[test]
        fn the_probe_reads_a_real_files_owner_dacl_and_digest() {
            let p = std::env::temp_dir().join(format!("brops-tcbprobe-{}.bin", std::process::id()));
            std::fs::write(&p, b"measure me").unwrap();
            let facts = WindowsFsProbe.stat(p.to_str().unwrap()).expect("probe a real file");
            let _ = std::fs::remove_file(&p);

            assert!(facts.owner_sid.starts_with("S-1-"), "owner SID: {}", facts.owner_sid);
            assert!(facts.dacl_present, "a temp file has a real DACL, not a NULL one");
            assert!(!facts.allow_aces.is_empty(), "the DACL walk must find ACEs");
            assert_eq!(facts.sha256, crate::crypto::sha256_hex(b"measure me"));
            assert!(!facts.is_dir);
            // A file in the user's own temp directory is writable by that user, who is not a TCB
            // principal — so the floor must report a writer. If this ever came back empty, the
            // writability check would be passing everything.
            assert!(
                !untrusted_write_grantees(&facts).is_empty(),
                "a user-writable temp file must be reported as untrusted-writable: {:?}",
                facts.allow_aces
            );
        }

        #[test]
        fn the_probe_reports_absence_rather_than_inventing_facts() {
            assert!(WindowsFsProbe.stat("C:\\nonexistent\\brops\\nothing.here").is_none());
        }

        #[test]
        fn a_real_deployment_that_is_user_writable_is_refused_by_the_floor() {
            // End-to-end through the REAL probe: a manifest pinning a genuinely user-writable file must
            // be refused. This is the whole floor, exercised against the live filesystem.
            let dir = std::env::temp_dir().join(format!("brops-tcbfloor-{}", std::process::id()));
            std::fs::create_dir_all(&dir).unwrap();
            let f = dir.join("kit.config");
            std::fs::write(&f, b"{}").unwrap();
            let artifacts = WIN_TCB_REQUIRED_ARTIFACTS
                .iter()
                .map(|n| WinTcbArtifact {
                    logical_name: (*n).to_string(),
                    path: f.to_string_lossy().to_string(),
                    expected_sha256: crate::crypto::sha256_hex(b"{}"),
                    expected_owner_sid: SID_ADMINISTRATORS.to_string(),
                })
                .collect();
            let m = WinTcbPinManifest { artifacts };
            let r = verify_win_tcb_integrity(&m, &WindowsFsProbe);
            let _ = std::fs::remove_dir_all(&dir);
            assert!(r.is_err(), "a user-owned, user-writable deployment must not satisfy the floor");
        }
    }
}
