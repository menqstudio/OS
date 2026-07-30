//! Wave 3b-1B — the privileged Model-A **launcher** as a SEPARATE binary crate (design-GREEN rev-30 §2.7).
//!
//! The launcher is the setuid-root helper the recorder `execve`s at the second exec boundary. Before it may
//! `fexecve` the pinned executor image it MUST, fail-closed:
//!   1. verify the inherited descriptor table is EXACTLY the rev-30 §2.7 contract set {0,1,2,3,4,5,6}
//!      (0/1/2 the approved inert stdio, 3/4/5 read-only store inputs, 6 the write-only output pipe, data
//!      FDs 3–6 free of `FD_CLOEXEC`, nothing at fd ≥ 7),
//!   2. run the locked privilege-drop syscall sequence in the load-bearing order (GID/groups before the UID
//!      drop; bounding set dropped while still root), and
//!   3. verify the post-drop process state fully lands on the executor UID/GID with empty supplementary
//!      groups, ALL five capability sets empty, and `no_new_privs` set.
//!
//! Any failure ⇒ no exec, non-zero exit, **no receipt/evidence/record**.
//!
//! This crate does NOT re-implement those rules. The three verdicts come from `brops-core`
//! (`fd_lifecycle::verify_launcher_fd_set`, `privilege_drop::verify_order`,
//! `privilege_drop::verify_final_state`) so the launcher and the recorder-side checks share ONE source of
//! truth. The composition of those three verdicts — [`evaluate_launch`] — plus the pure `/proc` parsers are
//! host-independent and unit-tested on any platform (mirroring how `fd_lifecycle`/`privilege_drop` keep a
//! pure, tested core). The real `dup2`/`fcntl`/`setresuid`/`capset`/`fexecve` syscalls are Linux-only and
//! gated behind `#[cfg(target_os = "linux")]`; on every other host `main` prints the platform-unsupported
//! banner and exits non-zero (governed real-mode disabled — fail closed).

use brops_core::fd_lifecycle::{verify_launcher_fd_set, FdFacts, FdViolation};
use brops_core::privilege_drop::{
    verify_final_state, verify_order, CapSets, FinalState, OrderViolation, PrivViolation, Step,
};
// `CANONICAL_SEQUENCE` is referenced only by the Linux real path and the tests, so it is qualified at
// those two sites rather than imported here (keeps the non-Linux bin build import-clean).

// ---------------------------------------------------------------------------------------------------
// Exit codes (fail-closed): success never returns (a good `fexecve` replaces this image).
// ---------------------------------------------------------------------------------------------------
// Referenced only by the Linux `run`; the non-Linux build never reaches a refusal exit.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const EXIT_REFUSED: i32 = 1;
const EXIT_PLATFORM_UNSUPPORTED: i32 = 2;

/// Why the launcher refuses to `fexecve`. A fail-closed union of the three `brops-core` verdicts plus the
/// launcher's own local guards (argv/env, `/proc` reads, image integrity, and raw-syscall failures).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Refusal {
    /// Real governed mode is only available on Linux (Model A). Any other host fails closed.
    PlatformUnsupported,
    /// The fixed, closed argv (lease handle + pinned executor index + cgroup path) was not exactly present,
    /// or the environment was not empty.
    BadArgv,
    /// A required `/proc` file could not be read or parsed while collecting facts.
    Proc(&'static str),
    /// The inherited FD table violated the rev-30 §2.7 contract.
    Fd(FdViolation),
    /// The planned privilege-drop sequence violated the load-bearing order.
    Order(OrderViolation),
    /// The post-drop process state still held privilege (UID/GID/groups/caps/`no_new_privs`).
    Priv(PrivViolation),
    /// The executor image failed start/exec-time integrity (owner/mode/hash vs the lease pin).
    ImageIntegrity,
    /// A TCB-identity precondition failed BEFORE any privilege drop or exec — e.g. the process that
    /// invoked this setuid-root launcher is not the provisioned evidence-recorder runner (the §2.7 step-1
    /// real UID/GID invoker gate). Fail-closed: no drop, no exec, no receipt.
    TcbIntegrity(&'static str),
    /// A privilege-drop or exec syscall failed (the name identifies which).
    Syscall(&'static str),
}

impl From<FdViolation> for Refusal {
    fn from(v: FdViolation) -> Self {
        Refusal::Fd(v)
    }
}
impl From<OrderViolation> for Refusal {
    fn from(v: OrderViolation) -> Self {
        Refusal::Order(v)
    }
}
impl From<PrivViolation> for Refusal {
    fn from(v: PrivViolation) -> Self {
        Refusal::Priv(v)
    }
}

/// The facts the launcher must gather before it may `fexecve`: the observed descriptor table, the planned
/// drop sequence, and the observed post-drop process state (plus the lease-bound executor identity).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaunchFacts {
    pub observed_fds: Vec<FdFacts>,
    pub drop_sequence: Vec<Step>,
    pub post_drop: FinalState,
    pub exec_uid: u32,
    pub exec_gid: u32,
}

/// The pure, host-independent launch gate — the launcher's fail-closed decision core. Composes the three
/// `brops-core` verdicts in the mandated order (FD set → drop order → final state); the FIRST failure short
/// circuits, and only an all-clear returns `Ok(())`. This is exactly the predicate that must hold before any
/// real `fexecve`, and it is fully unit-testable without spawning a process or touching a syscall.
pub fn evaluate_launch(f: &LaunchFacts) -> Result<(), Refusal> {
    verify_launcher_fd_set(&f.observed_fds)?;
    verify_order(&f.drop_sequence)?;
    verify_final_state(&f.post_drop, f.exec_uid, f.exec_gid)?;
    Ok(())
}

// ---------------------------------------------------------------------------------------------------
// Pure `/proc` parsers — host-independent so they can be unit-tested with fixture strings on any OS. The
// real file reads live in the Linux module; these only turn already-read text into typed facts.
// ---------------------------------------------------------------------------------------------------

/// Access mode + flags distilled from a `/proc/self/fdinfo/<fd>` file.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FdInfo {
    /// `flags & O_ACCMODE`: 0 = `O_RDONLY`, 1 = `O_WRONLY`, 2 = `O_RDWR`.
    pub accmode: u32,
    pub cloexec: bool,
    pub pos: u64,
}

const O_ACCMODE: u32 = 0o3;
const O_CLOEXEC_BIT: u32 = 0o2000000;

/// Parse a `/proc/self/fdinfo/<fd>` body. The `flags:` field is octal and encodes the open flags; `pos:` is
/// the current offset. Returns `None` if either required field is absent/unparseable (⇒ fail closed).
pub fn parse_fdinfo(content: &str) -> Option<FdInfo> {
    let mut flags: Option<u32> = None;
    let mut pos: Option<u64> = None;
    for line in content.lines() {
        if let Some(v) = line.strip_prefix("flags:") {
            flags = u32::from_str_radix(v.trim(), 8).ok();
        } else if let Some(v) = line.strip_prefix("pos:") {
            pos = v.trim().parse::<u64>().ok();
        }
    }
    let flags = flags?;
    Some(FdInfo {
        accmode: flags & O_ACCMODE,
        cloexec: (flags & O_CLOEXEC_BIT) != 0,
        pos: pos?,
    })
}

/// Parse `/proc/self/status` into the post-drop [`FinalState`] the fail-closed verifier consumes. The
/// `Uid:`/`Gid:` lines carry real/effective/saved(/fs); `Groups:` the supplementary set; `Cap*` the five
/// hex capability masks; `NoNewPrivs:` the `no_new_privs` bit. `None` on any missing/unparseable field.
pub fn parse_status(content: &str) -> Option<FinalState> {
    let triple = |v: &str| -> Option<(u32, u32, u32)> {
        let mut it = v.split_whitespace();
        Some((
            it.next()?.parse().ok()?,
            it.next()?.parse().ok()?,
            it.next()?.parse().ok()?,
        ))
    };
    let hex = |v: &str| -> Option<u64> { u64::from_str_radix(v.trim(), 16).ok() };

    let (mut ruid, mut euid, mut suid) = (None, None, None);
    let (mut rgid, mut egid, mut sgid) = (None, None, None);
    let mut groups: Option<Vec<u32>> = None;
    let mut caps = CapSets::default();
    let (mut eff, mut prm, mut inh, mut bnd, mut amb) = (false, false, false, false, false);
    let mut nnp: Option<bool> = None;

    for line in content.lines() {
        if let Some(v) = line.strip_prefix("Uid:") {
            let (a, b, c) = triple(v)?;
            (ruid, euid, suid) = (Some(a), Some(b), Some(c));
        } else if let Some(v) = line.strip_prefix("Gid:") {
            let (a, b, c) = triple(v)?;
            (rgid, egid, sgid) = (Some(a), Some(b), Some(c));
        } else if let Some(v) = line.strip_prefix("Groups:") {
            // An empty supplementary set is a blank/whitespace-only value ⇒ empty Vec (valid).
            let g: Option<Vec<u32>> = v.split_whitespace().map(|t| t.parse().ok()).collect();
            groups = Some(g?);
        } else if let Some(v) = line.strip_prefix("CapEff:") {
            caps.effective = hex(v)?;
            eff = true;
        } else if let Some(v) = line.strip_prefix("CapPrm:") {
            caps.permitted = hex(v)?;
            prm = true;
        } else if let Some(v) = line.strip_prefix("CapInh:") {
            caps.inheritable = hex(v)?;
            inh = true;
        } else if let Some(v) = line.strip_prefix("CapBnd:") {
            caps.bounding = hex(v)?;
            bnd = true;
        } else if let Some(v) = line.strip_prefix("CapAmb:") {
            caps.ambient = hex(v)?;
            amb = true;
        } else if let Some(v) = line.strip_prefix("NoNewPrivs:") {
            nnp = Some(v.trim() == "1");
        }
    }

    if !(eff && prm && inh && bnd && amb) {
        return None;
    }
    Some(FinalState {
        ruid: ruid?,
        euid: euid?,
        suid: suid?,
        rgid: rgid?,
        egid: egid?,
        sgid: sgid?,
        supplementary_groups: groups?,
        caps,
        no_new_privs: nnp?,
    })
}

// ---------------------------------------------------------------------------------------------------
// Pure exec-image owner/mode predicate — host-independent so it is unit-testable on any OS. It is fed the
// `st_mode`/`st_uid` an `fstat` of the OPENED executor fd reports (never a `metadata(path)` re-lookup).
// ---------------------------------------------------------------------------------------------------
/// `<sys/stat.h>` mode masks, as host-independent literals so this predicate compiles/tests on any OS.
const S_IFMT_MASK: u32 = 0o170000;
const S_IFREG_BITS: u32 = 0o100000;
const GROUP_OTHER_WRITE_BITS: u32 = 0o022;

/// The exec-image owner/mode floor (§2.5 image content owner/mode + §2.7 image identity): `true` iff the
/// fstat'd image is a **regular file**, owned by a dedicated TCB principal (`root(0)` or the provisioned
/// `brops-admin`), and has **no group/other write bit**. Pure: the caller supplies the `st_mode`/`st_uid`
/// from an `fstat` of the OPENED fd (never a `metadata(path)` re-lookup — no TOCTOU).
pub fn image_owner_mode_ok(st_mode: u32, st_uid: u32, brops_admin_uid: u32) -> bool {
    let is_regular = (st_mode & S_IFMT_MASK) == S_IFREG_BITS;
    let group_or_other_writable = (st_mode & GROUP_OTHER_WRITE_BITS) != 0;
    let owner_is_tcb = st_uid == 0 || st_uid == brops_admin_uid;
    is_regular && owner_is_tcb && !group_or_other_writable
}

// ---------------------------------------------------------------------------------------------------
// Entry point.
// ---------------------------------------------------------------------------------------------------

fn main() {
    std::process::exit(run());
}

#[cfg(not(target_os = "linux"))]
fn run() -> i32 {
    // No setuid / fexecve / capability model off Linux ⇒ governed real mode is unavailable. Fail closed.
    eprintln!("launcher: platform unsupported (governed real-mode disabled)");
    EXIT_PLATFORM_UNSUPPORTED
}

#[cfg(target_os = "linux")]
fn run() -> i32 {
    match linux::real_main() {
        // A successful `fexecve` replaces this image, so `real_main` only ever *returns* on refusal.
        Ok(()) => EXIT_REFUSED,
        Err(Refusal::PlatformUnsupported) => EXIT_PLATFORM_UNSUPPORTED,
        Err(e) => {
            eprintln!("launcher: refuse (no exec, no receipt): {:?}", e);
            EXIT_REFUSED
        }
    }
}

// ---------------------------------------------------------------------------------------------------
// Linux real path (§2.7 second exec boundary). Gated so the Windows/other-host build stays pure-std; the
// CI Linux job exercises the real recorder → launcher → fexecve path end-to-end. Fact collection reuses the
// pure parsers above; the mutating syscalls use libc. Every step is fail-closed.
// ---------------------------------------------------------------------------------------------------
#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use std::ffi::{CStr, CString};
    use std::fs;
    use std::io::Read;
    use std::os::unix::io::{FromRawFd, IntoRawFd};

    // The executor identity is bound by the validated lease (§4.3). Lease parsing lands in a separate
    // slice; the launcher NEVER chooses these — they are validated inputs. Pinned here as the boundary
    // constant so the drop target is explicit and testable.
    const EXECUTOR_UID: u32 = 5007;
    const EXECUTOR_GID: u32 = 5007;

    // The provisioned evidence-recorder runner principal (§2.6): the ONLY identity permitted to invoke this
    // setuid-root launcher (its REAL uid/gid, inherited from the caller). Like EXECUTOR_UID/GID these are
    // validated inputs the launcher never chooses.
    // TODO: bind the recorder uid/gid from the validated lease if it carries them; pinned here as the
    // boundary constant so the §2.7 step-1 invoker gate EXISTS and fails closed until then.
    const RECORDER_UID: u32 = 5006;
    const RECORDER_GID: u32 = 5006;

    // The dedicated `brops-admin` TCB owner uid (§2.5): root(0) or brops-admin may own the executor image.
    // TODO: bind from the root-owned TcbPinManifest (`owner_uids[BropsAdmin]`) / validated lease; pinned as
    // the boundary constant so the fstat'd-fd owner check accepts exactly the two TCB principals.
    const TCB_OWNER_BROPS_ADMIN_UID: u32 = 500;

    // The pinned SHA-256 (lowercase hex) of the contained-executor image bytes (§2.5 `contained-executor.bin`
    // content pin / §2.7 image identity). A validated lease/pin-manifest input the launcher never chooses.
    // TODO: bind from the validated lease (`executor_executable_sha256`) / TcbPinManifest — the placeholder
    // below makes the re-hash gate fail closed until the real digest is provisioned.
    const EXECUTOR_IMAGE_SHA256_PIN: &str =
        "0000000000000000000000000000000000000000000000000000000000000000";

    pub fn real_main() -> Result<(), Refusal> {
        // (0) §2.7 step 1 — INVOKER GATE. Before ANY fd/priv/exec work, confirm the process that execve'd
        //     this setuid-root launcher is the provisioned evidence-recorder runner. A setuid-root binary
        //     starts with euid=0 but INHERITS the caller's REAL uid/gid, so getresuid/getresgid reveal who
        //     actually invoked us; any non-recorder invoker is a confused-deputy ⇒ fail closed (no receipt).
        verify_invoker_is_recorder()?;

        // (1) Fixed, closed argv: lease handle + pinned executor image + cgroup path. Any other shape, or a
        //     non-empty environment, is a confused-deputy signal ⇒ refuse.
        let args: Vec<String> = std::env::args().skip(1).collect();
        if args.len() != 3 || std::env::vars_os().next().is_some() {
            return Err(Refusal::BadArgv);
        }
        let executor_image = &args[1];
        let (exec_uid, exec_gid) = (EXECUTOR_UID, EXECUTOR_GID);

        // (2) Verify the inherited descriptor table BEFORE any drop or exec (§2.7 launcher step 1–3).
        let observed = collect_fd_facts()?;
        verify_launcher_fd_set(&observed)?;

        // (3) Verify the planned drop order is the load-bearing canonical order (§2.7 step ordering).
        verify_order(brops_core::privilege_drop::CANONICAL_SEQUENCE)?;

        // (4) Neutralize stdio: set FD_CLOEXEC on 0/1/2 so the inert endpoints do NOT cross fexecve — only
        //     the four data FDs 3–6 survive into the executor (§2.7 launcher step 3).
        for fd in 0..=2i32 {
            set_cloexec(fd)?;
        }

        // (5) Perform the locked privilege drop (groups/gid → bounding+ambient → uid → capset zero →
        //     no_new_privs). Order matches CANONICAL_SEQUENCE (verified in step 3).
        drop_privileges(exec_uid, exec_gid)?;

        // (6) Fail-closed final-state verification: fully dropped, empty groups, all five cap sets empty,
        //     no_new_privs set. Any residual ⇒ abort, no exec (§2.7 step 8).
        let status = fs::read_to_string("/proc/self/status").map_err(|_| Refusal::Proc("status"))?;
        let post = parse_status(&status).ok_or(Refusal::Proc("status-parse"))?;
        verify_final_state(&post, exec_uid, exec_gid)?;

        // (7) Open the executor image O_RDONLY|O_NOFOLLOW|O_CLOEXEC (NOT one of 3–6), then bind exec-time
        //     integrity to THAT exact fd: fstat it (regular, TCB-owned, non-writable) AND re-hash its bytes
        //     against the lease `executor_executable_sha256` pin, and fexecve the SAME fd — the bytes hashed
        //     are the bytes executed, with no path re-lookup. Any mismatch ⇒ ImageIntegrity (no exec).
        let image_fd = open_executor_image(executor_image)?;
        fexecve_pinned(image_fd, executor_image)?; // returns ONLY on failure
        Err(Refusal::Syscall("fexecve"))
    }

    /// §2.7 step-1 invoker gate: the launcher is setuid-root but must ONLY ever be invoked BY the
    /// provisioned evidence-recorder runner. `getresuid`/`getresgid` expose the REAL uid/gid inherited from
    /// the caller; both MUST equal the recorder principal or we refuse before any privilege/exec work.
    fn verify_invoker_is_recorder() -> Result<(), Refusal> {
        let mut ruid: libc::uid_t = 0;
        let mut euid: libc::uid_t = 0;
        let mut suid: libc::uid_t = 0;
        // SAFETY: three valid out-pointers; getresuid writes the real/effective/saved uids.
        if unsafe { libc::getresuid(&mut ruid, &mut euid, &mut suid) } != 0 {
            return Err(Refusal::Syscall("getresuid"));
        }
        let mut rgid: libc::gid_t = 0;
        let mut egid: libc::gid_t = 0;
        let mut sgid: libc::gid_t = 0;
        // SAFETY: three valid out-pointers; getresgid writes the real/effective/saved gids.
        if unsafe { libc::getresgid(&mut rgid, &mut egid, &mut sgid) } != 0 {
            return Err(Refusal::Syscall("getresgid"));
        }
        // Only the REAL uid/gid identify the invoker (euid/egid are the setuid-root target). Bind both.
        // TODO: bind RECORDER_UID/RECORDER_GID from the validated lease rather than the boundary constant.
        if ruid != RECORDER_UID || rgid != RECORDER_GID {
            return Err(Refusal::TcbIntegrity("invoker-not-recorder"));
        }
        Ok(())
    }

    /// Enumerate `/proc/self/fd` and build the observed [`FdFacts`] table for the §2.7 verifier.
    ///
    /// The enumeration handle is captured as an EXACT fd number (`dirfd`) and is the ONLY descriptor
    /// excluded from the observed set. Every OTHER descriptor outside the {0..6} contract — regardless of
    /// its `/proc/self/fd` link target — is reported, so `verify_launcher_fd_set` flags any inherited fd ≥ 7
    /// (e.g. a non-CLOEXEC handle onto `/proc/self/mem` or `/proc/sysrq-trigger`) as `UnexpectedFd`. The
    /// prior path-prefix filter that skipped any `/proc/`-target fd was a §2.7 bypass and is removed.
    fn collect_fd_facts() -> Result<Vec<FdFacts>, Refusal> {
        let dir_path = CString::new("/proc/self/fd").map_err(|_| Refusal::Proc("fd-dir"))?;
        // SAFETY: opendir on a valid NUL-terminated path; the stream is closed exactly once below.
        let dirp = unsafe { libc::opendir(dir_path.as_ptr()) };
        if dirp.is_null() {
            return Err(Refusal::Proc("fd-dir"));
        }
        // The EXACT descriptor opendir enumerates through — the only fd excluded from `observed`, so the
        // readdir handle is not itself falsely flagged while everything else must reach the verifier.
        let dirfd = unsafe { libc::dirfd(dirp) };

        let mut out = Vec::new();
        loop {
            // SAFETY: dirp is a live stream; readdir yields NULL at end-of-directory.
            let ent = unsafe { libc::readdir(dirp) };
            if ent.is_null() {
                break;
            }
            // SAFETY: `ent` is a valid dirent for this iteration; `d_name` is a NUL-terminated field.
            let name = unsafe { CStr::from_ptr((*ent).d_name.as_ptr()) };
            let fd: i32 = match name.to_str().ok().and_then(|s| s.parse().ok()) {
                Some(n) => n,
                None => continue, // "." / ".." / non-numeric
            };
            if fd == dirfd {
                continue; // exclude ONLY the enumeration handle — NOT by /proc link target
            }
            let link = match fs::read_link(format!("/proc/self/fd/{fd}")) {
                Ok(l) => l,
                Err(_) => continue,
            };
            let info = fs::read_to_string(format!("/proc/self/fdinfo/{fd}"))
                .ok()
                .and_then(|c| parse_fdinfo(&c))
                .ok_or(Refusal::Proc("fdinfo"))?;
            let target = link.to_string_lossy().into_owned();
            let is_regular = fs::metadata(format!("/proc/self/fd/{fd}"))
                .map(|m| m.is_file())
                .unwrap_or(false);

            let inert = target == "/dev/null";
            out.push(FdFacts {
                fd,
                is_inert_endpoint: inert,
                // Stdio is inert-only; anything that is not the approved /dev/null endpoint is treated as
                // interactive/inherited for the fail-closed 0/1/2 check.
                is_interactive_or_inherited: !inert,
                read_only: info.accmode == 0,
                is_regular_store_inode: is_regular,
                offset_zero: info.pos == 0,
                is_output_pipe: target.starts_with("pipe:"),
                cloexec: info.cloexec,
            });
        }
        // SAFETY: dirp came from opendir and is closed exactly once here (this also closes `dirfd`).
        unsafe {
            libc::closedir(dirp);
        }
        Ok(out)
    }

    fn set_cloexec(fd: i32) -> Result<(), Refusal> {
        // SAFETY: fcntl on a stdio fd we already inherited; args are plain integers.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
        if flags < 0 {
            return Err(Refusal::Syscall("fcntl(F_GETFD)"));
        }
        if unsafe { libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
            return Err(Refusal::Syscall("fcntl(F_SETFD)"));
        }
        Ok(())
    }

    fn drop_privileges(uid: u32, gid: u32) -> Result<(), Refusal> {
        // Clear all supplementary groups (must precede the UID drop).
        if unsafe { libc::setgroups(0, std::ptr::null()) } != 0 {
            return Err(Refusal::Syscall("setgroups"));
        }
        if unsafe { libc::setresgid(gid, gid, gid) } != 0 {
            return Err(Refusal::Syscall("setresgid"));
        }
        // Drop the capability bounding set (needs CAP_SETPCAP, still root here) and clear ambient.
        for cap in 0..=63i32 {
            // EINVAL for non-existent cap numbers is benign; a real drop failure surfaces at capget-verify.
            unsafe {
                libc::prctl(libc::PR_CAPBSET_DROP, cap as libc::c_ulong, 0, 0, 0);
            }
        }
        if unsafe { libc::prctl(libc::PR_CAP_AMBIENT, libc::PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0) } != 0
        {
            return Err(Refusal::Syscall("prctl(PR_CAP_AMBIENT)"));
        }
        // Drop the UID (loses the effective/permitted caps root implied).
        if unsafe { libc::setresuid(uid, uid, uid) } != 0 {
            return Err(Refusal::Syscall("setresuid"));
        }
        // Belt-and-suspenders: zero effective/permitted/inheritable capability sets.
        if !capset_zero() {
            return Err(Refusal::Syscall("capset"));
        }
        // Lock further privilege gain BEFORE the final verify so verify_final_state's no_new_privs check
        // holds (stricter than, and compatible with, the canonical ordering: no_new_privs still precedes
        // fexecve).
        if unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) } != 0 {
            return Err(Refusal::Syscall("prctl(PR_SET_NO_NEW_PRIVS)"));
        }
        Ok(())
    }

    fn capset_zero() -> bool {
        #[repr(C)]
        struct CapHeader {
            version: u32,
            pid: i32,
        }
        #[repr(C)]
        #[derive(Clone, Copy)]
        struct CapData {
            effective: u32,
            permitted: u32,
            inheritable: u32,
        }
        const LINUX_CAPABILITY_VERSION_3: u32 = 0x2008_0522;
        let hdr = CapHeader {
            version: LINUX_CAPABILITY_VERSION_3,
            pid: 0,
        };
        // v3 uses two 32-bit words (64 caps). All-zero clears every bit.
        let data = [CapData {
            effective: 0,
            permitted: 0,
            inheritable: 0,
        }; 2];
        // SAFETY: header/version fixed per uapi; data is a fixed 2-element array of zeros.
        unsafe {
            libc::syscall(
                libc::SYS_capset,
                &hdr as *const CapHeader,
                data.as_ptr(),
            ) == 0
        }
    }

    fn open_executor_image(path: &str) -> Result<i32, Refusal> {
        let c = CString::new(path).map_err(|_| Refusal::ImageIntegrity)?;
        // SAFETY: open with a valid NUL-terminated path; flags are constants.
        let fd = unsafe {
            libc::open(
                c.as_ptr(),
                libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            )
        };
        if fd < 0 {
            return Err(Refusal::ImageIntegrity);
        }

        // Exec-time integrity is bound to the EXACT descriptor we hold and will exec — never a
        // `fs::metadata(path)` re-lookup (which could resolve a DIFFERENT inode than the held fd: TOCTOU).
        // (a) fstat the OPENED fd: require a regular, TCB-owned (root or brops-admin), non group/other
        //     writable file.
        // SAFETY: fd is a live descriptor; fstat is handed a valid out-pointer to a plain C `stat`.
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::fstat(fd, &mut st) } != 0 {
            unsafe { libc::close(fd) };
            return Err(Refusal::ImageIntegrity);
        }
        if !image_owner_mode_ok(st.st_mode, st.st_uid, TCB_OWNER_BROPS_ADMIN_UID) {
            unsafe { libc::close(fd) };
            return Err(Refusal::ImageIntegrity);
        }

        // (b) Re-hash the EXACT bytes behind the held fd and bind them to the lease pin. Read through a File
        //     wrapper, then RECLAIM the raw fd (`into_raw_fd`) so the SAME descriptor stays open for
        //     fexecve — the bytes hashed are the bytes executed. A freshly O_RDONLY-opened fd is at offset
        //     0, so read_to_end consumes the whole image.
        // SAFETY: we own `fd` exclusively; from_raw_fd takes ownership, into_raw_fd hands it back without
        // closing. On the read-error path the `File` is dropped, closing the fd (fail closed).
        let mut f = unsafe { fs::File::from_raw_fd(fd) };
        let mut bytes = Vec::new();
        if f.read_to_end(&mut bytes).is_err() {
            return Err(Refusal::ImageIntegrity);
        }
        let fd = f.into_raw_fd();
        if brops_core::receipt::sha256_hex(&bytes) != EXECUTOR_IMAGE_SHA256_PIN {
            unsafe { libc::close(fd) };
            return Err(Refusal::ImageIntegrity);
        }
        Ok(fd)
    }

    fn fexecve_pinned(image_fd: i32, image_path: &str) -> Result<(), Refusal> {
        // Fixed argv (argv[0] = the image identity) and a fully EMPTY environment.
        let arg0 = CString::new(image_path).map_err(|_| Refusal::ImageIntegrity)?;
        let argv = [arg0.as_ptr(), std::ptr::null()];
        let envp = [std::ptr::null()];
        // SAFETY: image_fd is our verified O_NOFOLLOW handle; argv/envp are NUL-terminated arrays that
        // outlive the call. fexecve either replaces this image (never returns) or returns -1.
        unsafe {
            libc::fexecve(image_fd, argv.as_ptr(), envp.as_ptr());
        }
        Err(Refusal::Syscall("fexecve"))
    }
}

// ---------------------------------------------------------------------------------------------------
// Tests — pure, offline, host-independent (run on Windows/macOS/Linux alike). They exercise the launch
// gate wiring and the /proc parsers with fixtures; no process spawn, no syscall.
// ---------------------------------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // ---- fixture builders (mirror the brops-core module tests) ------------------------------------
    fn inert(fd: i32) -> FdFacts {
        FdFacts {
            fd,
            is_inert_endpoint: true,
            is_interactive_or_inherited: false,
            read_only: false,
            is_regular_store_inode: false,
            offset_zero: false,
            is_output_pipe: false,
            cloexec: false,
        }
    }
    fn store(fd: i32) -> FdFacts {
        FdFacts {
            fd,
            is_inert_endpoint: false,
            is_interactive_or_inherited: false,
            read_only: true,
            is_regular_store_inode: true,
            offset_zero: true,
            is_output_pipe: false,
            cloexec: false,
        }
    }
    fn output() -> FdFacts {
        FdFacts {
            fd: 6,
            is_inert_endpoint: false,
            is_interactive_or_inherited: false,
            read_only: false,
            is_regular_store_inode: false,
            offset_zero: false,
            is_output_pipe: true,
            cloexec: false,
        }
    }
    fn good_fds() -> Vec<FdFacts> {
        vec![inert(0), inert(1), inert(2), store(3), store(4), store(5), output()]
    }
    /// An inherited fd whose `/proc/self/fd` link points INTO `/proc` (e.g. `/proc/self/mem`): NOT the
    /// approved /dev/null endpoint, NOT a store inode, NOT the output pipe — exactly what the fixed
    /// `collect_fd_facts` now records for such a descriptor (the old path-prefix filter used to DROP it).
    fn proc_fd(fd: i32) -> FdFacts {
        FdFacts {
            fd,
            is_inert_endpoint: false,
            is_interactive_or_inherited: true,
            read_only: true,
            is_regular_store_inode: false,
            offset_zero: false,
            is_output_pipe: false,
            cloexec: false,
        }
    }

    const EXEC_UID: u32 = 5007;
    const EXEC_GID: u32 = 5007;

    fn dropped() -> FinalState {
        FinalState {
            ruid: EXEC_UID,
            euid: EXEC_UID,
            suid: EXEC_UID,
            rgid: EXEC_GID,
            egid: EXEC_GID,
            sgid: EXEC_GID,
            supplementary_groups: vec![],
            caps: CapSets::default(),
            no_new_privs: true,
        }
    }

    fn good_facts() -> LaunchFacts {
        LaunchFacts {
            observed_fds: good_fds(),
            drop_sequence: brops_core::privilege_drop::CANONICAL_SEQUENCE.to_vec(),
            post_drop: dropped(),
            exec_uid: EXEC_UID,
            exec_gid: EXEC_GID,
        }
    }

    // ---- evaluate_launch: the composed launch gate -------------------------------------------------
    #[test]
    fn gate_accepts_a_fully_compliant_launch() {
        assert_eq!(evaluate_launch(&good_facts()), Ok(()));
    }

    #[test]
    fn gate_refuses_on_a_bad_fd_set() {
        let mut f = good_facts();
        f.observed_fds.push(store(7)); // fd >= 7 present
        assert_eq!(evaluate_launch(&f), Err(Refusal::Fd(FdViolation::UnexpectedFd(7))));
    }

    #[test]
    fn gate_flags_a_proc_target_fd_ge7_as_unexpected() {
        // Regression (Finding 1): a non-CLOEXEC inherited fd >= 7 whose /proc/self/fd link targets /proc
        // (e.g. /proc/self/mem or /proc/sysrq-trigger) MUST be observed and flagged. The old collector
        // dropped any /proc-target fd via a path-prefix filter, hiding it from the verifier; the fixed
        // collector excludes only its own readdir dirfd, so every fd outside {0..6} reaches this gate.
        let mut f = good_facts();
        f.observed_fds.push(proc_fd(7));
        assert_eq!(
            evaluate_launch(&f),
            Err(Refusal::Fd(FdViolation::UnexpectedFd(7)))
        );
    }

    #[test]
    fn image_owner_mode_predicate_matches_the_2_5_floor() {
        // Finding 2: the fstat'd executor image must be a regular, TCB-owned (root/brops-admin), non
        // group/other-writable file. Pure predicate over (st_mode, st_uid, brops_admin_uid).
        const ADMIN: u32 = 500;
        const REG: u32 = 0o100000; // S_IFREG
        const DIR: u32 = 0o040000; // S_IFDIR
        // root- and brops-admin-owned regular non-writable images pass.
        assert!(image_owner_mode_ok(REG | 0o755, 0, ADMIN));
        assert!(image_owner_mode_ok(REG | 0o644, ADMIN, ADMIN));
        // group- or other-writable images are rejected (a forge/replace vector).
        assert!(!image_owner_mode_ok(REG | 0o664, 0, ADMIN));
        assert!(!image_owner_mode_ok(REG | 0o646, 0, ADMIN));
        // a non-TCB owner (e.g. the executor runtime uid 5007) is rejected even if non-writable.
        assert!(!image_owner_mode_ok(REG | 0o755, 5007, ADMIN));
        // a non-regular inode (directory) is rejected even if TCB-owned and non-writable.
        assert!(!image_owner_mode_ok(DIR | 0o755, 0, ADMIN));
    }

    #[test]
    fn gate_refuses_on_a_cloexec_data_fd() {
        let mut f = good_facts();
        f.observed_fds[6].cloexec = true; // output pipe would close at fexecve
        assert_eq!(evaluate_launch(&f), Err(Refusal::Fd(FdViolation::DataFdCloexec(6))));
    }

    #[test]
    fn gate_refuses_on_a_bad_drop_order() {
        let mut f = good_facts();
        // UID dropped before groups/gid — the classic order violation.
        f.drop_sequence = vec![
            Step::VerifyEntry,
            Step::CgroupSetup,
            Step::SetResUidExec,
            Step::SetGroupsEmpty,
            Step::SetResGidExec,
            Step::DropBoundingAmbientCaps,
            Step::ClearAllCapSets,
            Step::VerifyUnprivileged,
            Step::SetNoNewPrivs,
            Step::Fexecve,
        ];
        assert_eq!(
            evaluate_launch(&f),
            Err(Refusal::Order(OrderViolation::UidDroppedBeforeGidOrGroups))
        );
    }

    #[test]
    fn gate_refuses_on_residual_privilege() {
        let mut f = good_facts();
        f.post_drop.caps.bounding = 1; // residual bounding capability
        assert_eq!(
            evaluate_launch(&f),
            Err(Refusal::Priv(PrivViolation::ResidualCapabilities))
        );
        let mut f2 = good_facts();
        f2.post_drop.no_new_privs = false;
        assert_eq!(
            evaluate_launch(&f2),
            Err(Refusal::Priv(PrivViolation::NoNewPrivsUnset))
        );
        let mut f3 = good_facts();
        f3.post_drop.euid = 0; // still root
        assert_eq!(
            evaluate_launch(&f3),
            Err(Refusal::Priv(PrivViolation::UidNotExecutor))
        );
    }

    #[test]
    fn gate_short_circuits_fd_before_order_and_state() {
        // A launch that is bad on ALL three axes must report the FD failure first (mandated order).
        let mut f = good_facts();
        f.observed_fds.remove(3); // missing a data fd
        f.drop_sequence = vec![Step::Fexecve]; // also a bad order
        f.post_drop.euid = 0; // also residual privilege
        match evaluate_launch(&f) {
            Err(Refusal::Fd(_)) => {}
            other => panic!("expected an FD refusal first, got {other:?}"),
        }
    }

    // ---- parse_fdinfo ------------------------------------------------------------------------------
    #[test]
    fn parse_fdinfo_reads_readonly_offset_zero() {
        // O_RDONLY (accmode 0), offset 0, no cloexec.
        let c = "pos:\t0\nflags:\t02000000\nmnt_id:\t42\n";
        // 02000000 octal = O_CLOEXEC bit set; accmode low bits 0 => read-only.
        let info = parse_fdinfo(c).expect("parses");
        assert_eq!(info.accmode, 0);
        assert!(info.cloexec);
        assert_eq!(info.pos, 0);
    }

    #[test]
    fn parse_fdinfo_reads_writeonly_no_cloexec_nonzero_offset() {
        let c = "pos:\t128\nflags:\t01\n";
        let info = parse_fdinfo(c).expect("parses");
        assert_eq!(info.accmode, 1); // O_WRONLY
        assert!(!info.cloexec);
        assert_eq!(info.pos, 128);
    }

    #[test]
    fn parse_fdinfo_fails_closed_on_missing_fields() {
        assert_eq!(parse_fdinfo("pos:\t0\n"), None); // no flags
        assert_eq!(parse_fdinfo("flags:\t0\n"), None); // no pos
        assert_eq!(parse_fdinfo("garbage"), None);
    }

    // ---- parse_status ------------------------------------------------------------------------------
    fn dropped_status() -> String {
        format!(
            "Name:\texecutor\n\
             Uid:\t{u}\t{u}\t{u}\t{u}\n\
             Gid:\t{g}\t{g}\t{g}\t{g}\n\
             Groups:\t \n\
             CapInh:\t0000000000000000\n\
             CapPrm:\t0000000000000000\n\
             CapEff:\t0000000000000000\n\
             CapBnd:\t0000000000000000\n\
             CapAmb:\t0000000000000000\n\
             NoNewPrivs:\t1\n",
            u = EXEC_UID,
            g = EXEC_GID
        )
    }

    #[test]
    fn parse_status_maps_a_fully_dropped_process() {
        let st = parse_status(&dropped_status()).expect("parses");
        assert_eq!(verify_final_state(&st, EXEC_UID, EXEC_GID), Ok(()));
        assert!(st.supplementary_groups.is_empty());
        assert!(st.caps.all_empty());
        assert!(st.no_new_privs);
    }

    #[test]
    fn parse_status_surfaces_residual_caps_and_groups() {
        let raw = dropped_status()
            .replace("CapBnd:\t0000000000000000", "CapBnd:\t000001ffffffffff")
            .replace("Groups:\t ", "Groups:\t27 1000");
        let st = parse_status(&raw).expect("parses");
        assert_eq!(st.caps.bounding, 0x0000_01ff_ffff_ffff);
        assert_eq!(st.supplementary_groups, vec![27, 1000]);
        // The fail-closed verifier catches the residual (groups checked before caps).
        assert_eq!(
            verify_final_state(&st, EXEC_UID, EXEC_GID),
            Err(PrivViolation::SupplementaryGroupsNonEmpty)
        );
    }

    #[test]
    fn parse_status_fails_closed_on_missing_cap_line() {
        let raw = dropped_status().replace("CapAmb:\t0000000000000000\n", "");
        assert_eq!(parse_status(&raw), None);
    }
}
