//! Custody of the files `win_provision` writes — the deployment root it adopts, and the explicit
//! security descriptor every secret-bearing file is *created* with (remediation round 3, findings
//! **P1s-1/2/3**).
//!
//! ## The three things this module exists to stop
//!
//! **1. The provisioner adopted whatever deployment root it found.** `create_dir_all(root)` succeeds
//! whether the directory is a fresh TCB-owned one or a directory an unprivileged account pre-created
//! at the well-known path an hour earlier. In the second case that account chose the DACL, and
//! `keys/`, `store/` and `config.json` all inherit it. The root is therefore a *precondition* of every
//! other custody claim in this kit, and it was never checked. [`check_root_custody`] checks it and
//! refuses; it deliberately does **not** fix it (see the note on silent repair below).
//!
//! **2. `config.json` got no ACL at all.** `restrict_to_owner` was only ever called for the seeds.
//! `config.json` carries `allowed_broker_sid`, the identity allowlists, `store_dir`, `executor_path`
//! and — the sharp one — `pubs.attest`, the public key the isolated signer verifies supervisor
//! attestations under. Whoever could write that file could mint attestations the *real* signer key
//! then signed over. (The key half of that is now closed cryptographically as well:
//! [`crate::config::verify_and_bind_pubs`] binds every `pubs.*` entry to the root-signed manifest at
//! load time, so a rewritten `pubs.attest` is refused rather than trusted. The custody here covers the
//! fields that have no manifest to bind to.)
//!
//! **3. Seeds were written plaintext and ACL'd afterwards, by spawning `icacls`.** `fs::write` then
//! `Command::new("icacls")` leaves the two production signing seeds — `attest.seed` and `signer.seed`
//! — on disk under the *inherited* DACL for as long as a process spawn takes, tens of milliseconds.
//! That is not a theoretical window: Windows evaluates access at **open** time, so a handle opened
//! inside it keeps its granted access after `icacls` replaces the DACL. Reading those two files does
//! not defeat the governed chain, it *skips* it — the holder signs whatever they like and every
//! downstream check agrees.
//!
//! [`create_locked_file`] closes it by construction: the file is created by `CreateFileW` with a
//! `SECURITY_ATTRIBUTES` already carrying the finished, **protected** DACL, so the restrictive
//! descriptor exists before the first byte does and there is no interval to race. `icacls` is gone
//! from the seed path entirely.
//!
//! ## Pure decision, Windows effect
//!
//! Same shape as [`crate::pipe_acl`] and [`crate::tcb_floor`], and for the same reason: this crate's
//! Windows-only code is covered by no CI at all, so every *decision* — which trustees, which mask,
//! whether a root directory is acceptable — is a pure function over plain data and is unit-tested on
//! the Linux runner. Only the syscalls are `#[cfg(windows)]`.
//!
//! ## Why refusal instead of silent repair
//!
//! A provisioner that "fixes" a bad root DACL hides the fact that someone pre-created the directory,
//! and re-ACLing a directory does nothing about handles already open on the files inside it. The
//! operator has to know. So the root check is a hard refusal with the exact remediation printed —
//! matching what `win_tcb_pin` already tells operators when the §2.5 floor rejects a deployment.
//!
//! ## Limits, stated plainly
//!
//! * The root check is **start-time and by path**, exactly like [`crate::tcb_floor`]: a directory
//!   junction swapped in after the check is not defended against. Closing that needs a handle-based
//!   probe (`FILE_FLAG_OPEN_REPARSE_POINT` + `GetSecurityInfo`) that this kit does not have anywhere.
//! * A file's **owner** always implicitly holds `READ_CONTROL | WRITE_DAC`, so any DACL is only as
//!   strong as the owner. That is why [`create_locked_file`] can be asked to stamp an explicit owner,
//!   and why `win_provision` asks for `BUILTIN\Administrators`: a run that cannot assign that owner
//!   fails the `CreateFileW` outright instead of producing a file its creator can silently re-open.
//! * This module says nothing about `floor.json`. The driver **rewrites** it on every turn
//!   (`resolver::persist_floor`), so locking it to the TCB principals would break any deployment whose
//!   broker is not itself a TCB principal. Its custody is the deployment-directory ACL the operator
//!   sets, exactly as `crate::tcb` already documents — this module does not improve that and does not
//!   pretend to.

use std::path::Path;

use crate::pipe_acl::{
    world_grantees, FILE_ALL_ACCESS, FILE_READ_ATTRIBUTES, FILE_READ_DATA, READ_CONTROL,
    SID_ADMINISTRATORS, SID_LOCAL_SYSTEM, SYNCHRONIZE, WORLD_SIDS, WRITE_ACCESS_BITS,
};
use crate::tcb_floor::{untrusted_write_grantees, WinFileFacts, TCB_OWNER_SIDS};

/// `FILE_READ_EA` — read a file's extended attributes. Part of `FILE_GENERIC_READ`.
pub const FILE_READ_EA: u32 = 0x0000_0008;

/// The exact mask a provisioned custody file grants a reader: `FILE_GENERIC_READ` (`0x0012_0089`),
/// built bit-by-bit rather than written as `GENERIC_READ`.
///
/// The generic mapping is resolved by the kernel, so an ACE holding the *generic* bit is opaque to a
/// DACL read-back (ours and [`crate::tcb_floor`]'s) — the audit's own rule about `GENERIC_WRITE`
/// silently containing `FILE_APPEND_DATA` is the same trap in the other direction. Spelling the mask
/// out means [`custody_file_dacl`] can prove, arithmetically, that no reader was handed a write bit.
pub const FILE_GENERIC_READ: u32 =
    READ_CONTROL | FILE_READ_DATA | FILE_READ_ATTRIBUTES | FILE_READ_EA | SYNCHRONIZE;

/// One access-allowed ACE of a provisioned file's explicit DACL.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileAce {
    /// String SID of the trustee (`S-1-5-…`), already resolved from whatever the operator typed.
    pub sid: String,
    /// The access mask granted.
    pub mask: u32,
}

/// The planned DACL for one provisioned custody file.
///
/// There is deliberately no way to build one of these that grants a non-TCB principal write authority:
/// [`custody_file_dacl`] is the only constructor and it refuses.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CustodyDacl {
    /// Access-allowed ACEs in the order they must be added.
    pub aces: Vec<FileAce>,
}

/// Cheap syntactic SID check.
///
/// Duplicated from `pipe_acl` (which is another agent's file in this round and must not be edited) —
/// same rule, and [`custody_file_dacl`] additionally rejects anything `ConvertStringSidToSidW` will
/// not parse on the Windows side, which is the real arbiter. This exists so the pure plan can refuse
/// obviously-wrong input on any host, including in a Linux unit test.
fn looks_like_sid(s: &str) -> bool {
    s.starts_with("S-1-")
        && s.len() > 4
        && s.split('-').skip(1).all(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()))
}

/// Plan the DACL for a file `win_provision` is about to create: SYSTEM and `BUILTIN\Administrators`
/// get full control, every named reader gets exactly [`FILE_GENERIC_READ`], and every other principal
/// is absent and therefore denied.
///
/// SYSTEM and Administrators are in the plan because they can take ownership of any local object
/// anyway — withholding the ACE would be theatre, and naming them explicitly is what makes the DACL
/// readable as a statement of intent. They are also the owner set [`crate::tcb_floor::TCB_OWNER_SIDS`]
/// requires, so a file created this way can satisfy the §2.5 floor.
///
/// Fail-closed. Every rejection below is a case where continuing would produce a file weaker than the
/// inherited DACL it replaced:
/// * a reader that is not a syntactic SID (an unresolved account name would silently become no ACE);
/// * a reader that is a world/group SID — granting `Everyone` read on `signer.seed` is the whole
///   finding, restated;
/// * a mask arithmetic slip that put a write bit in [`FILE_GENERIC_READ`]. That last one is checked at
///   run time, not just in a test, so a future edit to the constant refuses to provision rather than
///   quietly handing readers write access.
pub fn custody_file_dacl(reader_sids: &[String]) -> Result<CustodyDacl, String> {
    if FILE_GENERIC_READ & WRITE_ACCESS_BITS != 0 {
        return Err(format!(
            "FILE_GENERIC_READ ({FILE_GENERIC_READ:#x}) contains write bits \
             ({:#x}); refusing to create a custody file whose readers could rewrite it",
            FILE_GENERIC_READ & WRITE_ACCESS_BITS
        ));
    }

    let mut aces = vec![
        FileAce { sid: SID_LOCAL_SYSTEM.to_string(), mask: FILE_ALL_ACCESS },
        FileAce { sid: SID_ADMINISTRATORS.to_string(), mask: FILE_ALL_ACCESS },
    ];
    let mut seen: Vec<String> = Vec::new();
    for sid in reader_sids {
        if !looks_like_sid(sid) {
            return Err(format!(
                "custody reader {sid:?} is not a SID; a name that did not resolve must abort \
                 provisioning, never silently drop the ACE"
            ));
        }
        if WORLD_SIDS.contains(&sid.as_str()) {
            return Err(format!(
                "custody reader {sid} is a world/group SID; granting it read on a provisioned secret \
                 is indistinguishable from leaving the inherited DACL in place"
            ));
        }
        // SYSTEM / Administrators already hold full control; a second ACE would be noise.
        if TCB_OWNER_SIDS.contains(&sid.as_str()) || seen.iter().any(|s| s == sid) {
            continue;
        }
        seen.push(sid.clone());
        aces.push(FileAce { sid: sid.clone(), mask: FILE_GENERIC_READ });
    }

    // Post-condition over the ACEs actually built, not over the inputs: whatever a future edit does to
    // the masks or to the loop, a DACL that would hand write authority (or a world SID) to anyone
    // outside the TCB never leaves this function.
    let plan = CustodyDacl { aces };
    let leaked = non_tcb_write_grantees(&plan);
    if !leaked.is_empty() {
        return Err(format!("custody DACL would grant write authority to {leaked:?}"));
    }
    let pipe_view = plan.as_pipe_aces();
    let world = world_grantees(&pipe_view);
    if !world.is_empty() {
        return Err(format!("custody DACL contains world SID(s) {world:?}"));
    }
    Ok(plan)
}

/// Which trustees in a planned custody DACL are outside [`TCB_OWNER_SIDS`] and hold any write
/// authority ([`WRITE_ACCESS_BITS`] — write data, append, delete, `WRITE_DAC`, `WRITE_OWNER`).
///
/// Non-empty means the plan is not a custody plan: whoever is listed can rewrite the seed, delete it,
/// or rewrite its DACL and grant themselves the rest. [`custody_file_dacl`] refuses on any hit rather
/// than emitting the descriptor.
pub fn non_tcb_write_grantees(dacl: &CustodyDacl) -> Vec<&str> {
    dacl.aces
        .iter()
        .filter(|a| !TCB_OWNER_SIDS.contains(&a.sid.as_str()) && a.mask & WRITE_ACCESS_BITS != 0)
        .map(|a| a.sid.as_str())
        .collect()
}

impl CustodyDacl {
    /// View the plan as `pipe_acl` ACEs, so the world-SID rule is the SHARED one rather than a second
    /// definition of "open" that could drift from [`crate::pipe_acl::world_grantees`].
    fn as_pipe_aces(&self) -> Vec<crate::pipe_acl::PipeAce> {
        self.aces
            .iter()
            .map(|a| crate::pipe_acl::PipeAce { sid: a.sid.clone(), mask: a.mask })
            .collect()
    }
}

/// Why the deployment root was refused. Any value ⇒ `win_provision` must abort without writing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RootRefusal {
    /// The path could not be measured (absent, or its security descriptor unreadable).
    Unmeasurable { path: String },
    /// A file (or a reparse point resolving to one) is sitting at the deployment root path.
    NotADirectory { path: String },
    /// The root is owned by a principal that is not a compiled-in TCB owner. The owner can rewrite the
    /// DACL at will, so a foreign owner makes every ACL underneath advisory.
    UntrustedOwner { path: String, owner_sid: String },
    /// Some non-TCB principal can write the root — including the NULL-DACL case, which Windows reads
    /// as everyone-full-control. Whoever holds this can replace `keys/`, `store/` or `config.json`
    /// wholesale, so no per-file descriptor underneath means anything.
    WritableByUntrusted { path: String, grantees: Vec<String> },
}

/// Is this directory fit to be the deployment root?
///
/// The predicate is **deliberately identical** to the one [`crate::tcb_floor`] applies to the ancestor
/// directories of every pinned artifact (TCB owner + [`untrusted_write_grantees`] empty). That is the
/// point: a root this function accepts is a root the runtime §2.5 floor will also accept, so
/// provisioning cannot hand an operator a deployment that is guaranteed to refuse to serve later. The
/// `it_agrees_with_the_runtime_floor_ancestor_rule` test pins the two together so they cannot drift.
///
/// `facts == None` means "could not measure", which is refused rather than assumed benign.
pub fn check_root_custody(path: &str, facts: Option<&WinFileFacts>) -> Result<(), RootRefusal> {
    let f = facts.ok_or_else(|| RootRefusal::Unmeasurable { path: path.to_string() })?;
    if !f.is_dir {
        return Err(RootRefusal::NotADirectory { path: path.to_string() });
    }
    if !TCB_OWNER_SIDS.contains(&f.owner_sid.as_str()) {
        return Err(RootRefusal::UntrustedOwner {
            path: path.to_string(),
            owner_sid: f.owner_sid.clone(),
        });
    }
    let writers = untrusted_write_grantees(f);
    if !writers.is_empty() {
        return Err(RootRefusal::WritableByUntrusted { path: path.to_string(), grantees: writers });
    }
    Ok(())
}

/// Operator-facing text for a refusal: what is wrong and the exact command that fixes it. The
/// remediation matches the one `win_tcb_pin` prints for the same condition, so an operator does not
/// get two different stories about the same directory.
pub fn explain_root_refusal(r: &RootRefusal) -> String {
    let (path, why) = match r {
        RootRefusal::Unmeasurable { path } => (
            path,
            "the deployment root could not be measured (absent, or its owner/DACL is unreadable)"
                .to_string(),
        ),
        RootRefusal::NotADirectory { path } => {
            (path, "the deployment root path is not a directory".to_string())
        }
        RootRefusal::UntrustedOwner { path, owner_sid } => (
            path,
            format!(
                "the deployment root is owned by {owner_sid}, which is not a TCB principal \
                 ({TCB_OWNER_SIDS:?}). Its owner can rewrite the DACL at any time, so every ACL this \
                 provisioner would apply underneath it is advisory only"
            ),
        ),
        RootRefusal::WritableByUntrusted { path, grantees } => (
            path,
            format!(
                "the deployment root grants access to non-TCB principal(s) {grantees:?} \
                 (`<null-dacl:everyone>` means it has NO DACL, which Windows reads as everyone-full-\
                 control). They can replace keys\\, store\\ or config.json wholesale"
            ),
        ),
    };
    format!(
        "win_provision: REFUSING to provision into {path}\n  {why}\n  \
         This provisioner does NOT repair the directory: a root someone else created is evidence, not \
         a misconfiguration, and re-ACLing it would not revoke handles already open on files inside \
         it.\n  Fix it yourself, from an ELEVATED shell, and re-run:\n    \
         icacls \"{path}\" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F /grant:r *S-1-5-32-544:(OI)(CI)F\n    \
         icacls \"{path}\" /setowner *S-1-5-32-544\n  \
         (or delete it and let win_provision create it). This is the SAME condition the runtime §2.5 \
         floor enforces on config.json's ancestors, so a root that fails here would make every server \
         exit 5 later."
    )
}

// =================================================================================================
// Windows effect
// =================================================================================================

/// Verify the deployment root's custody, creating it first if it does not exist.
///
/// Order matters and is the whole finding: the check happens **before** `keys/`, `store/` or
/// `config.json` are written, because those inherit whatever DACL the root carries.
///
/// * Root absent → we create it, so the DACL is inherited from a parent the operator chose rather
///   than from a directory an adversary pre-created — and then it is measured like any other, because
///   inheriting from a bad parent is no better than adopting a bad root. A root we created and that
///   then fails the check is removed again, so a refusal leaves nothing behind.
/// * Root present → measured and either accepted or refused. Never repaired.
///
/// Known limit: the measurement is by path, so a junction swapped between this call and the writes
/// below is not defended against. That is the same TOCTOU gap [`crate::tcb_floor`] documents for the
/// runtime floor; closing it needs a handle-based probe this kit does not have.
#[cfg(windows)]
pub fn verify_or_create_deployment_root(root: &Path) -> Result<(), String> {
    use crate::tcb_floor::{WinFsProbe, WindowsFsProbe};

    let p = root.to_string_lossy().to_string();
    // `create_dir` (not `create_dir_all`): if the PARENT is missing we refuse rather than materialise
    // a chain of directories whose custody nobody has looked at. Its Err also tells us, without a
    // racy `exists()` probe, whether this process is the creator.
    let created = match std::fs::create_dir(root) {
        Ok(()) => true,
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => false,
        Err(e) => {
            return Err(format!(
                "win_provision: cannot create deployment root {p}: {e}\n  \
                 Create its PARENT first, with an ACL you control."
            ))
        }
    };

    match check_root_custody(&p, WindowsFsProbe.stat(&p).as_ref()) {
        Ok(()) => Ok(()),
        Err(r) => {
            if created {
                // Only ever removes the empty directory this call just made.
                let _ = std::fs::remove_dir(root);
            }
            Err(explain_root_refusal(&r))
        }
    }
}

/// On a non-Windows host the custody model does not exist: there are no owner SIDs and no DACLs, so
/// the root cannot be evaluated — and a check that cannot be evaluated must never report satisfied.
///
/// This makes `win_provision` refuse to run on Linux, which is a deliberate change: it used to
/// "succeed" there with `restrict_to_owner` compiled out to a no-op, i.e. it printed a provisioned
/// deployment whose seeds had no custody whatsoever. The crate still builds and its pure decisions
/// still run on the Linux CI runner; only the effectful binary refuses.
#[cfg(not(windows))]
pub fn verify_or_create_deployment_root(root: &Path) -> Result<(), String> {
    Err(format!(
        "win_provision: REFUSING to provision {} from a non-Windows host — deployment-root custody is \
         stated in owner SIDs and DACLs that do not exist here, and this tool would otherwise write \
         two production signing seeds with no custody at all.",
        root.display()
    ))
}

/// Create `path` containing `contents`, with `dacl` (and optionally `owner_sid`) **already applied at
/// creation**.
///
/// This is finding P1s-3 in one function. `fs::write` + a later ACL change cannot be made safe by
/// shortening the gap, because Windows grants access at `CreateFile` time: a handle opened during the
/// window keeps what it was granted no matter what the DACL becomes afterwards. Handing the finished
/// security descriptor to `CreateFileW` means the restrictive DACL exists before the file does.
///
/// Details that carry weight:
/// * `SE_DACL_PROTECTED` is set on the descriptor, so inheritable ACEs from the parent directory are
///   **not** merged into ours. Without it the deployment directory's ACEs would ride along and the
///   explicit DACL would be a superset, not a replacement.
/// * `CREATE_NEW` + `FILE_SHARE_MODE(0)`: we create, exclusively, or we fail. Re-provisioning removes
///   the previous file first (a legitimate operator action, since re-provisioning mints fresh keys);
///   if anyone wins a race to recreate it in between, `CREATE_NEW` fails and provisioning aborts
///   rather than adopting a file someone else's DACL is on.
/// * `owner_sid`, when given, is stamped into the descriptor. A token that may not assign that owner
///   makes `CreateFileW` fail with `ERROR_INVALID_OWNER` — the intended loud refusal for a
///   non-elevated run, because an owner outside the TCB can rewrite the DACL and the §2.5 floor
///   requires a TCB owner for `config.json` anyway.
#[cfg(windows)]
pub fn create_locked_file(
    path: &Path,
    contents: &[u8],
    dacl: &CustodyDacl,
    owner_sid: Option<&str>,
) -> Result<(), String> {
    winimpl::create_locked_file(path, contents, dacl, owner_sid)
}

/// Non-Windows stand-in so the crate builds and the shared logic is exercisable on the CI runner.
///
/// It creates the file `O_EXCL` with mode `0600` in one syscall — the POSIX analogue of the Windows
/// property this function exists for (no window between creation and restriction). It is **not** a
/// substitute for the Windows path: `dacl` and `owner_sid` have no meaning here, and
/// [`verify_or_create_deployment_root`] refuses on this host anyway, so `win_provision` never reaches
/// this code in a real run. It exists for the unit tests and for build parity.
#[cfg(not(windows))]
pub fn create_locked_file(
    path: &Path,
    contents: &[u8],
    _dacl: &CustodyDacl,
    _owner_sid: Option<&str>,
) -> Result<(), String> {
    use std::io::Write;
    // Same shape as the Windows path: unlink any predecessor, then create exclusively. Never open a
    // file that is already there — an existing file carries someone else's mode/owner, and opening it
    // would keep them.
    let _ = std::fs::remove_file(path);
    let mut opts = std::fs::OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    let mut f = opts.open(path).map_err(|e| format!("create {}: {e}", path.display()))?;
    f.write_all(contents).map_err(|e| format!("write {}: {e}", path.display()))?;
    f.sync_all().map_err(|e| format!("sync {}: {e}", path.display()))
}

#[cfg(windows)]
mod winimpl {
    //! The syscalls. Every decision above this line is pure and tested on Linux; this module only
    //! turns a [`super::CustodyDacl`] into a real security descriptor and a real file.

    use super::CustodyDacl;
    use std::ffi::c_void;
    use std::path::Path;
    use windows::core::{Error, PCWSTR, PWSTR};
    use windows::Win32::Foundation::{CloseHandle, LocalFree, HLOCAL};
    use windows::Win32::Security::Authorization::{ConvertSidToStringSidW, ConvertStringSidToSidW};
    use windows::Win32::Security::{
        AddAccessAllowedAce, InitializeAcl, InitializeSecurityDescriptor, LookupAccountNameW,
        SetSecurityDescriptorControl, SetSecurityDescriptorDacl, SetSecurityDescriptorOwner, ACL,
        ACL_REVISION, PSECURITY_DESCRIPTOR, PSID, SECURITY_ATTRIBUTES, SECURITY_DESCRIPTOR,
        SECURITY_DESCRIPTOR_CONTROL, SID_NAME_USE,
    };
    use windows::Win32::Storage::FileSystem::{
        CreateFileW, FlushFileBuffers, WriteFile, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, FILE_SHARE_MODE,
    };
    use windows::Win32::System::SystemServices::SECURITY_DESCRIPTOR_REVISION;

    /// `GENERIC_WRITE`. Spelled as a literal because `CreateFileW`'s desired-access parameter is a bare
    /// `u32` in this binding and the generic constants live in a different module per crate version.
    const GENERIC_WRITE_ACCESS: u32 = 0x4000_0000;

    /// `SE_DACL_PROTECTED` — "do not merge inheritable ACEs from the parent into this DACL".
    const SE_DACL_PROTECTED_BIT: SECURITY_DESCRIPTOR_CONTROL = SECURITY_DESCRIPTOR_CONTROL(0x1000);

    /// `SECURITY_MAX_SID_SIZE`, used to size buffers generously. Over-allocating is harmless.
    const MAX_SID_BYTES: usize = 68;

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Canonical string SID for `psid`. Caller still owns `psid`.
    unsafe fn sid_to_string(psid: PSID) -> Option<String> {
        let mut out = PWSTR::null();
        ConvertSidToStringSidW(psid, &mut out).ok()?;
        let s = out.to_string().ok();
        let _ = LocalFree(HLOCAL(out.0 as *mut c_void));
        s
    }

    /// Resolve whatever the operator typed — a string SID or an account name (`DOMAIN\user`,
    /// `.\svc-signer`, a UPN) — to the canonical string SID.
    ///
    /// Resolution happens HERE, before the pure planner sees anything, so that the world-SID and
    /// syntactic checks in [`super::custody_file_dacl`] run on the resolved SID. Checking account
    /// *names* would be locale-dependent and trivially bypassed ("Everyone" has a different name in
    /// every localised install); checking the SID is not.
    pub fn resolve_trustee_sid(name_or_sid: &str) -> Result<String, String> {
        if name_or_sid.is_empty() {
            return Err("empty account/SID".to_string());
        }
        unsafe {
            // 1. Already a SID? Round-trip it so the stored form is canonical (uppercase, no aliases),
            //    which is what the DACL read-back and the peer-SID comparisons use.
            let w = wide(name_or_sid);
            let mut psid = PSID::default();
            if ConvertStringSidToSidW(PCWSTR(w.as_ptr()), &mut psid).is_ok() {
                let s = sid_to_string(psid);
                let _ = LocalFree(HLOCAL(psid.0));
                return s.ok_or_else(|| format!("cannot canonicalise SID {name_or_sid}"));
            }

            // 2. An account name. Two-call pattern: ask for the sizes, then fill.
            let name = wide(name_or_sid);
            let mut sid_len: u32 = 0;
            let mut dom_len: u32 = 0;
            let mut use_: SID_NAME_USE = SID_NAME_USE(0);
            let _ = LookupAccountNameW(
                PCWSTR::null(),
                PCWSTR(name.as_ptr()),
                PSID::default(),
                &mut sid_len,
                PWSTR::null(),
                &mut dom_len,
                &mut use_,
            );
            if sid_len == 0 {
                return Err(format!(
                    "LookupAccountNameW({name_or_sid}) found no such account: {:?}",
                    Error::from_win32()
                ));
            }
            let mut sid_buf = vec![0u8; sid_len.max(MAX_SID_BYTES as u32) as usize];
            let mut dom_buf = vec![0u16; dom_len.max(1) as usize];
            let psid = PSID(sid_buf.as_mut_ptr() as *mut c_void);
            LookupAccountNameW(
                PCWSTR::null(),
                PCWSTR(name.as_ptr()),
                psid,
                &mut sid_len,
                PWSTR(dom_buf.as_mut_ptr()),
                &mut dom_len,
                &mut use_,
            )
            .map_err(|e| format!("LookupAccountNameW({name_or_sid}): {e:?}"))?;
            sid_to_string(psid).ok_or_else(|| format!("cannot stringify SID for {name_or_sid}"))
        }
    }

    /// A live security descriptor built from a [`CustodyDacl`]. Owns the ACL buffer and the
    /// `LocalAlloc`'d SIDs the ACEs point at, so it stays valid until the file is created.
    struct CustodySecurity {
        acl: Vec<u8>,
        sids: Vec<PSID>,
        sd: Box<SECURITY_DESCRIPTOR>,
    }

    impl Drop for CustodySecurity {
        fn drop(&mut self) {
            unsafe {
                for s in &self.sids {
                    let _ = LocalFree(HLOCAL(s.0));
                }
            }
            self.acl.clear();
        }
    }

    impl CustodySecurity {
        fn build(dacl: &CustodyDacl, owner_sid: Option<&str>) -> Result<CustodySecurity, String> {
            let mut sids: Vec<PSID> = Vec::with_capacity(dacl.aces.len() + 1);
            unsafe {
                let free = |sids: &Vec<PSID>| {
                    for s in sids {
                        let _ = LocalFree(HLOCAL(s.0));
                    }
                };
                for ace in &dacl.aces {
                    let w = wide(&ace.sid);
                    let mut psid = PSID::default();
                    if ConvertStringSidToSidW(PCWSTR(w.as_ptr()), &mut psid).is_err() {
                        free(&sids);
                        return Err(format!("ConvertStringSidToSidW failed for {}", ace.sid));
                    }
                    sids.push(psid);
                }
                let ace_count = sids.len();

                let acl_len = std::mem::size_of::<ACL>()
                    + ace_count * (std::mem::size_of::<u32>() * 3 + MAX_SID_BYTES);
                let mut acl = vec![0u8; acl_len];
                let pacl = acl.as_mut_ptr() as *mut ACL;
                if InitializeAcl(pacl, acl_len as u32, ACL_REVISION).is_err() {
                    free(&sids);
                    return Err(format!("InitializeAcl: {:?}", Error::from_win32()));
                }
                for (ace, psid) in dacl.aces.iter().zip(sids.iter()) {
                    if AddAccessAllowedAce(pacl, ACL_REVISION, ace.mask, *psid).is_err() {
                        free(&sids);
                        return Err(format!(
                            "AddAccessAllowedAce({}): {:?}",
                            ace.sid,
                            Error::from_win32()
                        ));
                    }
                }

                let mut sd = Box::new(SECURITY_DESCRIPTOR::default());
                let psd = PSECURITY_DESCRIPTOR(sd.as_mut() as *mut SECURITY_DESCRIPTOR as *mut c_void);
                if InitializeSecurityDescriptor(psd, SECURITY_DESCRIPTOR_REVISION).is_err() {
                    free(&sids);
                    return Err(format!("InitializeSecurityDescriptor: {:?}", Error::from_win32()));
                }
                // `true` = a DACL IS present. `None` here would be a NULL DACL, i.e. everyone-full-
                // control — the exact bug pipe_acl was written to kill, in file form.
                if SetSecurityDescriptorDacl(psd, true, Some(acl.as_ptr() as *const ACL), false).is_err()
                {
                    free(&sids);
                    return Err(format!("SetSecurityDescriptorDacl: {:?}", Error::from_win32()));
                }
                // Without SE_DACL_PROTECTED the object manager merges the parent directory's
                // inheritable ACEs into ours, so the explicit DACL would be a floor rather than the
                // whole story. The point of this module is that it IS the whole story.
                if SetSecurityDescriptorControl(psd, SE_DACL_PROTECTED_BIT, SE_DACL_PROTECTED_BIT)
                    .is_err()
                {
                    free(&sids);
                    return Err(format!("SetSecurityDescriptorControl: {:?}", Error::from_win32()));
                }
                if let Some(owner) = owner_sid {
                    let w = wide(owner);
                    let mut opsid = PSID::default();
                    if ConvertStringSidToSidW(PCWSTR(w.as_ptr()), &mut opsid).is_err() {
                        free(&sids);
                        return Err(format!("ConvertStringSidToSidW failed for owner {owner}"));
                    }
                    sids.push(opsid);
                    if SetSecurityDescriptorOwner(psd, opsid, false).is_err() {
                        free(&sids);
                        return Err(format!("SetSecurityDescriptorOwner: {:?}", Error::from_win32()));
                    }
                }
                Ok(CustodySecurity { acl, sids, sd })
            }
        }

        fn attributes(&mut self) -> SECURITY_ATTRIBUTES {
            SECURITY_ATTRIBUTES {
                nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: self.sd.as_mut() as *mut SECURITY_DESCRIPTOR as *mut c_void,
                bInheritHandle: false.into(),
            }
        }
    }

    pub fn create_locked_file(
        path: &Path,
        contents: &[u8],
        dacl: &CustodyDacl,
        owner_sid: Option<&str>,
    ) -> Result<(), String> {
        let mut security = CustodySecurity::build(dacl, owner_sid)?;
        let sa = security.attributes();
        // Re-provisioning legitimately replaces these files (it mints fresh keys), and CREATE_NEW
        // would otherwise refuse. Removing first and then insisting on CREATE_NEW keeps the property
        // that matters: we never open a file someone else created, and the file we do create carries
        // our descriptor from byte zero.
        let _ = std::fs::remove_file(path);
        let w = wide(&path.to_string_lossy());
        unsafe {
            let h = CreateFileW(
                PCWSTR(w.as_ptr()),
                GENERIC_WRITE_ACCESS,
                FILE_SHARE_MODE(0), // exclusive: nobody reads a half-written seed either
                Some(&sa as *const SECURITY_ATTRIBUTES),
                CREATE_NEW,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            .map_err(|e| {
                format!(
                    "CreateFileW({}) with an explicit security descriptor failed: {e:?}\n  \
                     ERROR_INVALID_OWNER (0x8007051B) means this token may not assign the requested \
                     owner — run provisioning ELEVATED. ERROR_FILE_EXISTS means something recreated \
                     the file after we removed it.",
                    path.display()
                )
            })?;
            let mut written = 0u32;
            let w_res = WriteFile(h, Some(contents), Some(&mut written), None);
            let flushed = FlushFileBuffers(h);
            let _ = CloseHandle(h);
            w_res.map_err(|e| format!("WriteFile({}): {e:?}", path.display()))?;
            flushed.map_err(|e| format!("FlushFileBuffers({}): {e:?}", path.display()))?;
            if written as usize != contents.len() {
                return Err(format!(
                    "short write to {}: {written} of {} bytes",
                    path.display(),
                    contents.len()
                ));
            }
        }
        Ok(())
    }
}

#[cfg(windows)]
pub use winimpl::resolve_trustee_sid;

/// Resolving an account name to a SID needs the Windows LSA. On any other host there is nothing to
/// resolve against, so this refuses instead of inventing a SID.
#[cfg(not(windows))]
pub fn resolve_trustee_sid(name_or_sid: &str) -> Result<String, String> {
    Err(format!("cannot resolve {name_or_sid:?} to a SID off Windows"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipe_acl::PipeAce;

    const SIGNER_SVC: &str = "S-1-5-21-11-22-33-1101";
    const BROKER_SVC: &str = "S-1-5-21-11-22-33-1102";
    const INTRUDER: &str = "S-1-5-21-11-22-33-1999";

    fn dir_facts(owner: &str, aces: Vec<PipeAce>) -> WinFileFacts {
        WinFileFacts {
            owner_sid: owner.to_string(),
            dacl_present: true,
            allow_aces: aces,
            sha256: String::new(),
            is_dir: true,
        }
    }

    /// A reader the running test process can actually be: its own SID on Windows, a fixture SID
    /// elsewhere (where `create_locked_file` falls back to `O_EXCL` + `0600` and SIDs mean nothing).
    fn self_reader() -> String {
        #[cfg(windows)]
        {
            brops_win_broker::syscall::current_process_user_sid().expect("own SID")
        }
        #[cfg(not(windows))]
        {
            SIGNER_SVC.to_string()
        }
    }

    fn tcb_only_aces() -> Vec<PipeAce> {
        vec![
            PipeAce { sid: SID_LOCAL_SYSTEM.to_string(), mask: FILE_ALL_ACCESS },
            PipeAce { sid: SID_ADMINISTRATORS.to_string(), mask: FILE_ALL_ACCESS },
        ]
    }

    // ---------------------------------------------------------------------------------------------
    // P1s-1 / P1s-3: the DACL a provisioned custody file is CREATED with
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn a_reader_is_granted_read_and_never_a_write_bit() {
        // The property the whole module rests on: `signer.seed`'s owning service account can read its
        // seed and cannot rewrite it, cannot delete it, and cannot rewrite its DACL.
        let d = custody_file_dacl(&[SIGNER_SVC.to_string()]).expect("plan");
        let ace = d.aces.iter().find(|a| a.sid == SIGNER_SVC).expect("reader ACE");
        assert_eq!(ace.mask, FILE_GENERIC_READ);
        assert_eq!(ace.mask & WRITE_ACCESS_BITS, 0, "reader holds write bits: {:#x}", ace.mask);
        // and it can still actually open and read the file
        for needed in [FILE_READ_DATA, READ_CONTROL, SYNCHRONIZE] {
            assert_ne!(ace.mask & needed, 0, "reader still needs {needed:#x}");
        }
    }

    #[test]
    fn the_tcb_principals_are_the_only_full_control_trustees() {
        let d = custody_file_dacl(&[SIGNER_SVC.to_string(), BROKER_SVC.to_string()]).expect("plan");
        let full: Vec<&str> = d
            .aces
            .iter()
            .filter(|a| a.mask == FILE_ALL_ACCESS)
            .map(|a| a.sid.as_str())
            .collect();
        assert_eq!(full, vec![SID_LOCAL_SYSTEM, SID_ADMINISTRATORS]);
        // Nobody outside the TCB holds ANY write authority — the arithmetic, not a spot check.
        let writers: Vec<&str> = d
            .aces
            .iter()
            .filter(|a| !TCB_OWNER_SIDS.contains(&a.sid.as_str()) && a.mask & WRITE_ACCESS_BITS != 0)
            .map(|a| a.sid.as_str())
            .collect();
        assert!(writers.is_empty(), "non-TCB writers in the custody DACL: {writers:?}");
    }

    #[test]
    fn a_world_sid_reader_is_refused_rather_than_granted() {
        // "Everyone: read" on attest.seed IS the finding. There is no path from a world SID to an ACE.
        for w in WORLD_SIDS {
            let e = custody_file_dacl(&[w.to_string()]).unwrap_err();
            assert!(e.contains("world/group SID"), "{w} -> {e}");
        }
    }

    #[test]
    fn an_unresolved_account_name_aborts_instead_of_dropping_the_ace() {
        // If a name failed to resolve and we simply skipped it, the file would end up TCB-only and the
        // service account could not read its own seed — which someone would then "fix" by loosening
        // the ACL. Fail loudly at plan time instead.
        for bad in ["", "CORP\\svc-signer", "not-a-sid", "S-1-5-21-abc"] {
            assert!(
                custody_file_dacl(&[bad.to_string()]).is_err(),
                "{bad:?} must not become an ACE"
            );
        }
    }

    #[test]
    fn a_tcb_reader_is_not_duplicated_and_duplicates_collapse() {
        let d = custody_file_dacl(&[
            SID_LOCAL_SYSTEM.to_string(),
            SIGNER_SVC.to_string(),
            SIGNER_SVC.to_string(),
        ])
        .expect("plan");
        assert_eq!(d.aces.len(), 3, "{:?}", d.aces);
        assert_eq!(d.aces.iter().filter(|a| a.sid == SID_LOCAL_SYSTEM).count(), 1);
        assert_eq!(d.aces.iter().filter(|a| a.sid == SIGNER_SVC).count(), 1);
    }

    #[test]
    fn the_post_condition_catches_a_dacl_that_leaks_write_authority() {
        // Directly exercises the scan `custody_file_dacl` ends with — the check that survives a future
        // edit to FILE_GENERIC_READ or to the ACE loop. A hand-built plan standing in for such an edit:
        let leaky = CustodyDacl {
            aces: vec![
                FileAce { sid: SID_LOCAL_SYSTEM.to_string(), mask: FILE_ALL_ACCESS },
                FileAce { sid: SIGNER_SVC.to_string(), mask: FILE_GENERIC_READ | 0x0004 }, // +APPEND
            ],
        };
        assert_eq!(non_tcb_write_grantees(&leaky), vec![SIGNER_SVC]);
        // A DELETE or WRITE_DAC grant counts too — both let the holder undo the custody.
        for bit in [crate::pipe_acl::DELETE, crate::pipe_acl::WRITE_DAC] {
            let d = CustodyDacl {
                aces: vec![FileAce { sid: SIGNER_SVC.to_string(), mask: FILE_GENERIC_READ | bit }],
            };
            assert_eq!(non_tcb_write_grantees(&d), vec![SIGNER_SVC], "bit {bit:#x}");
        }
        // And the plan the real constructor produces has none.
        assert!(non_tcb_write_grantees(&custody_file_dacl(&[SIGNER_SVC.to_string()]).unwrap())
            .is_empty());
    }

    #[test]
    fn the_read_mask_is_pinned_to_the_exact_value_with_no_write_bits() {
        // FILE_GENERIC_READ == 0x00120089. If a future edit adds FILE_WRITE_DATA/APPEND/WRITE_DAC to
        // it, custody_file_dacl refuses at RUN time (not only here), so provisioning stops rather than
        // silently handing every reader write access.
        assert_eq!(FILE_GENERIC_READ, 0x0012_0089);
        assert_eq!(FILE_GENERIC_READ & WRITE_ACCESS_BITS, 0);
    }

    // ---------------------------------------------------------------------------------------------
    // P1s-2: the deployment root
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn a_tcb_owned_locked_root_is_accepted() {
        assert!(check_root_custody(
            "C:\\ProgramData\\brops-live",
            Some(&dir_facts(SID_ADMINISTRATORS, tcb_only_aces()))
        )
        .is_ok());
    }

    #[test]
    fn a_root_owned_by_an_unprivileged_account_is_refused() {
        // THE finding: an unprivileged account pre-creates the well-known path. It owns the directory,
        // so it can rewrite the DACL whenever it likes — even a DACL that looks perfect right now.
        let facts = dir_facts(INTRUDER, tcb_only_aces());
        let e = check_root_custody("C:\\ProgramData\\brops-live", Some(&facts)).unwrap_err();
        assert_eq!(
            e,
            RootRefusal::UntrustedOwner {
                path: "C:\\ProgramData\\brops-live".to_string(),
                owner_sid: INTRUDER.to_string()
            }
        );
        assert!(explain_root_refusal(&e).contains("not a TCB principal"));
    }

    #[test]
    fn a_root_writable_by_a_non_tcb_principal_is_refused() {
        let mut aces = tcb_only_aces();
        aces.push(PipeAce { sid: INTRUDER.to_string(), mask: FILE_ALL_ACCESS });
        let facts = dir_facts(SID_ADMINISTRATORS, aces);
        match check_root_custody("C:\\deploy", Some(&facts)) {
            Err(RootRefusal::WritableByUntrusted { grantees, .. }) => {
                assert!(grantees.contains(&INTRUDER.to_string()), "{grantees:?}")
            }
            other => panic!("must refuse a writable root, got {other:?}"),
        }
    }

    #[test]
    fn a_root_with_a_null_dacl_is_refused_because_that_is_everyone_full_control() {
        let mut facts = dir_facts(SID_ADMINISTRATORS, vec![]);
        facts.dacl_present = false;
        match check_root_custody("C:\\deploy", Some(&facts)) {
            Err(RootRefusal::WritableByUntrusted { grantees, .. }) => {
                assert_eq!(grantees, vec!["<null-dacl:everyone>".to_string()])
            }
            other => panic!("a NULL DACL is not a closed one, got {other:?}"),
        }
    }

    #[test]
    fn a_root_readable_by_a_world_group_is_refused() {
        // BUILTIN\Users with read-only is still an open descriptor by the kit's shared rule, and this
        // is the default a directory under C:\ProgramData inherits.
        let mut aces = tcb_only_aces();
        aces.push(PipeAce { sid: "S-1-5-32-545".to_string(), mask: FILE_GENERIC_READ });
        let e = check_root_custody("C:\\deploy", Some(&dir_facts(SID_ADMINISTRATORS, aces)));
        assert!(matches!(e, Err(RootRefusal::WritableByUntrusted { .. })), "{e:?}");
    }

    #[test]
    fn an_unmeasurable_or_missing_root_is_refused_not_assumed_fine() {
        assert_eq!(
            check_root_custody("C:\\deploy", None).unwrap_err(),
            RootRefusal::Unmeasurable { path: "C:\\deploy".to_string() }
        );
    }

    #[test]
    fn a_file_at_the_root_path_is_refused() {
        let mut facts = dir_facts(SID_ADMINISTRATORS, tcb_only_aces());
        facts.is_dir = false;
        assert_eq!(
            check_root_custody("C:\\deploy", Some(&facts)).unwrap_err(),
            RootRefusal::NotADirectory { path: "C:\\deploy".to_string() }
        );
    }

    #[test]
    fn it_agrees_with_the_runtime_floor_ancestor_rule() {
        // The provisioning gate and the runtime §2.5 ancestor gate must accept exactly the same set of
        // directories. If they drift, provisioning either blesses a deployment that will refuse to
        // serve, or refuses one that would have served — and the operator gets two stories.
        let candidates = vec![
            dir_facts(SID_ADMINISTRATORS, tcb_only_aces()),
            dir_facts(SID_LOCAL_SYSTEM, tcb_only_aces()),
            dir_facts(INTRUDER, tcb_only_aces()),
            dir_facts(
                SID_ADMINISTRATORS,
                vec![PipeAce { sid: INTRUDER.to_string(), mask: FILE_ALL_ACCESS }],
            ),
            dir_facts(
                SID_ADMINISTRATORS,
                vec![PipeAce { sid: "S-1-1-0".to_string(), mask: FILE_GENERIC_READ }],
            ),
            WinFileFacts {
                owner_sid: SID_ADMINISTRATORS.to_string(),
                dacl_present: false,
                allow_aces: vec![],
                sha256: String::new(),
                is_dir: true,
            },
        ];
        for f in &candidates {
            let floor_ok = TCB_OWNER_SIDS.contains(&f.owner_sid.as_str())
                && untrusted_write_grantees(f).is_empty();
            assert_eq!(
                check_root_custody("C:\\deploy", Some(f)).is_ok(),
                floor_ok,
                "provisioning gate disagrees with the runtime floor for {f:?}"
            );
        }
    }

    // ---------------------------------------------------------------------------------------------
    // create_locked_file — the host-independent half (no window between create and restrict)
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn a_custody_file_is_created_never_opened_in_place() {
        // The property that holds on every host, and the reason the seed path no longer looks like
        // `fs::write` + a later restriction: we UNLINK any predecessor and CREATE the file, so the
        // restrictive descriptor (Windows) or mode (POSIX) is attached before the first byte exists.
        // Opening a file that is already there would inherit whatever custody its creator chose, which
        // is the same defect as inheriting the directory's DACL.
        let dir = std::env::temp_dir().join(format!("brops-custody-{}", brops_core::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("seed");
        // The reader must be THIS process on Windows, because the DACL genuinely works: a file whose
        // only reader is some other principal is one this test could not read back. (That is the
        // property, observed — a seed provisioned for `svc-signer` is unreadable by anyone else.)
        let d = custody_file_dacl(&[self_reader()]).unwrap();
        create_locked_file(&p, b"deadbeef", &d, None).expect("first create");
        assert_eq!(std::fs::read(&p).unwrap(), b"deadbeef");

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(std::fs::metadata(&p).unwrap().permissions().mode() & 0o777, 0o600);
            // Re-provisioning legitimately replaces the file. A hard link to the ORIGINAL inode proves
            // which way it did so: if the implementation had opened + truncated the existing path, the
            // link would show the new bytes (and the old, loosely-permissioned inode would live on).
            // It must show the old ones, i.e. the predecessor was unlinked and a fresh file created.
            let link = dir.join("witness");
            std::fs::hard_link(&p, &link).unwrap();
            create_locked_file(&p, b"replaced", &d, None).expect("re-provision");
            assert_eq!(std::fs::read(&p).unwrap(), b"replaced");
            assert_eq!(
                std::fs::read(&link).unwrap(),
                b"deadbeef",
                "the pre-existing file was opened in place instead of being replaced"
            );
            assert_eq!(std::fs::metadata(&p).unwrap().permissions().mode() & 0o777, 0o600);
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ---------------------------------------------------------------------------------------------
    // Windows-only: read the descriptor back off a real file. Does NOT run on the Linux CI runner.
    // ---------------------------------------------------------------------------------------------

    #[cfg(windows)]
    #[test]
    fn a_created_file_carries_the_explicit_dacl_and_no_untrusted_writer() {
        use crate::tcb_floor::{WinFsProbe, WindowsFsProbe};
        // The reader is this process's own account, because that is the only principal a
        // non-elevated test run can name. `owner_sid: None` for the same reason — win_provision asks
        // for BUILTIN\Administrators, which needs an elevated token; see the module docs.
        let me = self_reader();
        let dir = std::env::temp_dir().join(format!("brops-custody-win-{}", brops_core::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("attest.seed");
        let d = custody_file_dacl(&[me.clone()]).expect("plan");
        create_locked_file(&p, b"00", &d, None).expect("create with explicit descriptor");

        let facts = WindowsFsProbe
            .stat(&p.to_string_lossy())
            .expect("read back the created file's security descriptor");
        assert!(facts.dacl_present, "the created file must not have a NULL DACL");
        assert!(
            untrusted_write_grantees(&facts).is_empty(),
            "non-TCB writers on a freshly created custody file: {facts:?}"
        );
        let mine = facts.allow_aces.iter().find(|a| a.sid == me).expect("reader ACE survived");
        assert_eq!(mine.mask & WRITE_ACCESS_BITS, 0, "reader got write bits: {mine:?}");
        // SE_DACL_PROTECTED: nothing inherited from the temp directory rode along.
        assert_eq!(facts.allow_aces.len(), d.aces.len(), "inherited ACEs merged in: {facts:?}");

        // And a file that ALREADY exists with the directory's inherited (permissive) DACL is replaced,
        // not adopted — the Windows half of "never opened in place". Written with plain `fs::write`
        // first, i.e. exactly what the old provisioner produced.
        let q = dir.join("config.json");
        std::fs::write(&q, b"{}").unwrap();
        let before = WindowsFsProbe.stat(&q.to_string_lossy()).expect("pre-existing file facts");
        create_locked_file(&q, b"{\"v\":1}", &d, None).expect("replace under custody");
        let after = WindowsFsProbe.stat(&q.to_string_lossy()).expect("replaced file facts");
        assert_ne!(before.allow_aces, after.allow_aces, "the inherited DACL survived provisioning");
        assert_eq!(after.allow_aces.len(), d.aces.len(), "not the explicit DACL: {after:?}");
        assert!(untrusted_write_grantees(&after).is_empty(), "{after:?}");

        let _ = std::fs::remove_dir_all(&dir);
    }
}
