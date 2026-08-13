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
//! (`fd_lifecycle::verify_launcher_fd_set`, `privilege_drop::verify_performed_drop`,
//! `privilege_drop::verify_final_state`) so the launcher and the recorder-side checks share ONE source of
//! truth. The pure `/proc` parsers are host-independent and unit-tested on any platform (mirroring how
//! `fd_lifecycle`/`privilege_drop` keep a pure, tested core). The real
//! `dup2`/`fcntl`/`setresuid`/`capset`/`fexecve` syscalls are Linux-only and gated behind
//! `#[cfg(target_os = "linux")]`; on every other host `main` prints the platform-unsupported banner and
//! exits non-zero (governed real-mode disabled — fail closed).
//!
//! **On step 2 and what checks it.** The drop order used to be "checked" by
//! `verify_order(CANONICAL_SEQUENCE)` — the checker fed the constant it is written against, which cannot
//! fail — while `drop_privileges` issued the real syscalls and recorded nothing. The order is now
//! executed by the single recording driver `privilege_drop::perform_drop`, which appends each step to a
//! [`brops_core::privilege_drop::DropJournal`] as it COMPLETES, and the JOURNAL is what
//! `verify_performed_drop` judges immediately before `fexecve`. Reordering or deleting a syscall changes
//! the recorded trace, and `brops-core`'s unit tests read that trace through a recording fake — so the
//! drop's order is testable on any host, not only on a privileged Linux box.
//!
//! **[`evaluate_launch`] is reachable only from tests.** It composes the three verdicts, but the real
//! `run()` calls `verify_launcher_fd_set`, `verify_performed_drop` and `verify_final_state` directly and
//! at the points in the sequence where each is meaningful (the FD set before any drop; the journal only
//! once there IS a journal). It is retained as the host-independent statement of the composed predicate;
//! do not mistake a green `evaluate_launch` test for evidence about a real launch.

use brops_core::fd_lifecycle::{
    verify_launcher_fd_set, verify_store_inputs_unchanged, FdFacts, FdViolation, InodeIdentity,
    StoreInputSnapshot,
};
use brops_core::privilege_drop::{
    verify_final_state, verify_order, CapSets, FinalState, OrderViolation, PrivViolation, Step,
};
// `CANONICAL_SEQUENCE` is referenced only by the tests, so it is qualified there rather than imported
// here (keeps the non-Linux bin build import-clean). The REAL path deliberately no longer names it: a
// check fed the constant it checks against cannot fail — see `privilege_drop::perform_drop`.

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
    /// The provisioned `brops-admin` TCB principal (besides root) permitted to own a store-input inode —
    /// the boundary value the §2.7 store-input custody floor is evaluated against (audit IDX-3).
    pub brops_admin_uid: u32,
}

/// The pure, host-independent launch gate — the launcher's fail-closed decision core. Composes the three
/// `brops-core` verdicts in the mandated order (FD set → drop order → final state); the FIRST failure short
/// circuits, and only an all-clear returns `Ok(())`. This is exactly the predicate that must hold before any
/// real `fexecve`, and it is fully unit-testable without spawning a process or touching a syscall.
pub fn evaluate_launch(f: &LaunchFacts) -> Result<(), Refusal> {
    verify_launcher_fd_set(&f.observed_fds, f.brops_admin_uid)?;
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
// The validated lease (§4.3) — the launch parameters the launcher TAKES (never chooses): the recorder
//
// PARTIAL vs the spec (audit round 3): §4.3 describes a SIGNED 25-field artifact. What this is, is an
// unsigned 8-field key=value blob. Its integrity comes from root ownership and file mode — a real
// property, and a different one from a signature: it survives a hostile non-root principal and does
// NOT survive anything that can write as root. Cited here because a reader who sees `§4.3` and stops
// there will assume the signature exists.
// principal permitted to invoke it, the unprivileged executor identity to drop to, and the executor image
// hash pin. Parsed from the lease handle (argv[0]). A strict std-only `key=value` body — NO serde in a
// setuid-root binary (minimal attack surface). Pure + host-independent so it is unit-tested on any OS.
// ---------------------------------------------------------------------------------------------------
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Lease {
    /// The ONLY principal permitted to invoke the setuid launcher — matched against the launcher's REAL
    /// uid/gid at §2.7 step 1. In production the supervisor issues (and signs) this lease.
    pub recorder_uid: u32,
    pub recorder_gid: u32,
    /// The unprivileged identity the launcher drops to before `fexecve` (§2.7).
    pub executor_uid: u32,
    pub executor_gid: u32,
    /// The pinned SHA-256 (lowercase hex) of the executor image bytes — the launcher re-hashes the OPENED
    /// image fd and refuses on any mismatch (§2.5 content pin / §2.7 image identity).
    pub executor_executable_sha256: String,
    /// The pinned SHA-256 (lowercase hex) of the three governed REQUEST inputs the executor is handed on
    /// fds 3/4/5 (audit **F-08**). The attested `request_sha256` is built from exactly these three digests;
    /// until they were pinned here, nothing anywhere compared them to the bytes the executor actually read
    /// — the recorder opened `<recorder_store_dir>/system|history|generation_config` BY NAME, so the model
    /// could run on prompt A while the signed receipt attested prompt B. The launcher re-hashes the HELD
    /// fds against these pins and refuses on any mismatch (§2.7 store-input identity).
    pub system_sha256: String,
    pub history_sha256: String,
    pub generation_config_sha256: String,
}

/// Parse a strict `key=value` lease body. Fail-closed: EXACTLY the eight required keys, each present once,
/// uids/gids base-10 `u32`, every digest 64 lowercase-hex chars; any missing / duplicate / unknown key or
/// malformed value ⇒ `None`. Blank/whitespace-only lines are ignored.
pub fn parse_lease(content: &str) -> Option<Lease> {
    let mut recorder_uid: Option<u32> = None;
    let mut recorder_gid: Option<u32> = None;
    let mut executor_uid: Option<u32> = None;
    let mut executor_gid: Option<u32> = None;
    let mut sha: Option<String> = None;
    let mut system_sha: Option<String> = None;
    let mut history_sha: Option<String> = None;
    let mut generation_config_sha: Option<String> = None;

    fn set_u32(slot: &mut Option<u32>, v: &str) -> Option<()> {
        if slot.is_some() {
            return None; // duplicate key ⇒ fail closed
        }
        *slot = Some(v.parse::<u32>().ok()?);
        Some(())
    }

    fn set_hex(slot: &mut Option<String>, v: &str) -> Option<()> {
        if slot.is_some()
            || v.len() != 64
            || !v.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        {
            return None; // duplicate or non-canonical digest ⇒ fail closed
        }
        *slot = Some(v.to_string());
        Some(())
    }

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let (k, v) = line.split_once('=')?;
        let (k, v) = (k.trim(), v.trim());
        match k {
            "recorder_uid" => set_u32(&mut recorder_uid, v)?,
            "recorder_gid" => set_u32(&mut recorder_gid, v)?,
            "executor_uid" => set_u32(&mut executor_uid, v)?,
            "executor_gid" => set_u32(&mut executor_gid, v)?,
            "executor_executable_sha256" => set_hex(&mut sha, v)?,
            "system_sha256" => set_hex(&mut system_sha, v)?,
            "history_sha256" => set_hex(&mut history_sha, v)?,
            "generation_config_sha256" => set_hex(&mut generation_config_sha, v)?,
            _ => return None, // unknown key ⇒ fail closed
        }
    }

    let recorder_uid = recorder_uid?;
    let recorder_gid = recorder_gid?;
    let executor_uid = executor_uid?;
    let executor_gid = executor_gid?;

    // The executor MUST land on a dedicated UNPRIVILEGED principal, distinct from root and from the
    // recorder that invokes the launcher. Reject uid/gid 0 (a "drop" to root is a no-op) and reject
    // executor == recorder (would run the executor as the invoker principal). A misprovisioned lease
    // value can therefore never yield a root/confused executor — fail closed at the lease boundary (the
    // §2.7 post-drop floor in privilege_drop::verify_final_state enforces the same uid/gid != 0 rule).
    if executor_uid == 0
        || executor_gid == 0
        || executor_uid == recorder_uid
        || executor_gid == recorder_gid
    {
        return None;
    }

    Some(Lease {
        recorder_uid,
        recorder_gid,
        executor_uid,
        executor_gid,
        executor_executable_sha256: sha?,
        system_sha256: system_sha?,
        history_sha256: history_sha?,
        generation_config_sha256: generation_config_sha?,
    })
}

/// The §2.7 store-input identity DECISION (audit **F-08** + **IDX-3**), pure and host-independent.
///
/// `identity_of` supplies the `fstat` identity of the inode behind a held descriptor and `digest_of` the
/// SHA-256 of its bytes; the Linux path passes real `fstat`/`pread`-from-zero readers, tests pass maps.
/// Every input must digest to the lease's pin for its slot: an unreadable descriptor refuses
/// (`store-input-read`), a mismatch refuses (`store-input-digest`), and there is no partial acceptance.
///
/// IDX-3: it now also RETURNS the measurement — which inode, holding which bytes — so the caller can
/// re-run it immediately before `fexecve` and compare the two with
/// [`verify_store_inputs_unchanged`]. A descriptor whose inode cannot be identified refuses
/// (`store-input-identity`) rather than being pinned by content alone.
///
/// It is a separate function precisely so it can be tested. The remediation audit found this
/// check — the whole substance of F-08 — covered by no test at all, while four tests exercised
/// the lease parser around it, so removing the check kept the suite green.
pub fn verify_store_inputs(
    lease: &Lease,
    identity_of: impl Fn(i32) -> Option<InodeIdentity>,
    digest_of: impl Fn(i32) -> Option<String>,
) -> Result<Vec<StoreInputSnapshot>, Refusal> {
    let mut measured = Vec::new();
    for (fd, pin) in store_input_pins(lease) {
        let digest = digest_of(fd).ok_or(Refusal::TcbIntegrity("store-input-read"))?;
        if digest != pin {
            return Err(Refusal::TcbIntegrity("store-input-digest"));
        }
        let identity = identity_of(fd).ok_or(Refusal::TcbIntegrity("store-input-identity"))?;
        measured.push(StoreInputSnapshot {
            fd,
            identity,
            digest,
        });
    }
    Ok(measured)
}

/// The fd→pin map the §2.7 store-input binding checks (audit **F-08**): fd 3 is `system`, fd 4 `history`,
/// fd 5 `generation_config` — the same fixed assignment the recorder opens them in and the same order the
/// attested `request_sha256` is built from. Pure so the mapping itself is testable off Linux.
pub fn store_input_pins(lease: &Lease) -> [(i32, &str); 3] {
    [
        (3, lease.system_sha256.as_str()),
        (4, lease.history_sha256.as_str()),
        (5, lease.generation_config_sha256.as_str()),
    ]
}

// ---------------------------------------------------------------------------------------------------
// The ATTESTED request digests (audit **IDX-4**) — the root-owned declaration of the three digests the
// receipt's `request_sha256` is built from.
//
// The lease pins the bytes the executor is handed; the receipt attests digests taken from `resolved.*_sha256`
// in whatever config the BROKER loaded. Those two were compared only once, by a shell heredoc in
// `engine/ci/live/run_live_turn.sh`, at PROVISIONING time. Nothing at turn time read the lease to compare,
// so the two could diverge afterwards and the receipt's request binding would name bytes that were never
// executed.
//
// The comparison now happens at TURN time, inside the setuid launcher, before any drop or exec — the same
// custody pattern the recorder uses for its root-owned policy (`guard::POLICY_PATH` in
// `proof/src/bin/governed_recorder.rs`): a COMPILE-TIME path, not an argv flag and not an environment
// variable, so there is no runtime input by which the broker can redirect it, and a root-owned,
// non-group/other-writable regular file so a non-TCB principal cannot forge it.
// ---------------------------------------------------------------------------------------------------

/// The deployment's canonical broker config — the file `resolved.*_sha256` is attested from. A compile-time
/// constant on purpose (see the module note above); the deployment must place it exactly here.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
pub const ATTESTED_REQUEST_PATH: &str = "/opt/brops-live/config.json";

/// The three request digests the receipt will attest, read from the root-owned canonical config.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AttestedRequest {
    pub system_sha256: String,
    pub history_sha256: String,
    pub generation_config_sha256: String,
}

/// Extract `"<key>": "<64 lowercase hex>"` from a JSON document, fail-closed.
///
/// Deliberately NOT a JSON parser: this runs in a setuid-root binary, where a full deserializer is attack
/// surface the launcher has consistently refused to take on (the lease is `key=value` for the same reason).
/// It is a strict scanner instead, and its safety comes from being far pickier than a parser would be — the
/// key must occur EXACTLY ONCE in the whole document, so "which object did this come from?" cannot be
/// ambiguous, and a document that mentions the key twice is refused rather than resolved by a rule.
fn scan_json_digest(content: &str, key: &str) -> Option<String> {
    let needle = format!("\"{key}\"");
    let mut hits = content.match_indices(&needle);
    let (idx, _) = hits.next()?;
    if hits.next().is_some() {
        return None; // ambiguous ⇒ fail closed
    }
    let rest = content[idx + needle.len()..].trim_start();
    let rest = rest.strip_prefix(':')?.trim_start();
    let rest = rest.strip_prefix('"')?;
    let value = rest.get(..64)?;
    if !rest[64..].starts_with('"') {
        return None; // not exactly 64 chars of digest
    }
    if !value
        .bytes()
        .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
    {
        return None; // non-canonical digest ⇒ fail closed
    }
    Some(value.to_string())
}

/// Parse the three attested request digests out of the canonical config. Any missing, duplicated or
/// non-canonical digest ⇒ `None` ⇒ the launcher refuses (never "attest whatever was readable").
pub fn parse_attested_request(content: &str) -> Option<AttestedRequest> {
    Some(AttestedRequest {
        system_sha256: scan_json_digest(content, "system_sha256")?,
        history_sha256: scan_json_digest(content, "history_sha256")?,
        generation_config_sha256: scan_json_digest(content, "generation_config_sha256")?,
    })
}

/// Audit **IDX-4**, the DECISION: the lease's three request pins — the bytes the launcher will actually
/// let the executor read — must equal the three digests the receipt will attest. A divergence means the
/// receipt would name a request that was never executed, so it is a refusal before the drop and the exec.
///
/// Pure and slot-by-slot: an equality over the triple as a set, or one that stopped at the first slot,
/// would accept a transposed or partially-substituted request.
pub fn verify_lease_matches_attested_request(
    lease: &Lease,
    attested: &AttestedRequest,
) -> Result<(), Refusal> {
    if lease.system_sha256 != attested.system_sha256 {
        return Err(Refusal::TcbIntegrity("attested-request-system"));
    }
    if lease.history_sha256 != attested.history_sha256 {
        return Err(Refusal::TcbIntegrity("attested-request-history"));
    }
    if lease.generation_config_sha256 != attested.generation_config_sha256 {
        return Err(Refusal::TcbIntegrity("attested-request-generation-config"));
    }
    Ok(())
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
    // The recorded-drop machinery is used only by the real path, so it is imported here rather than at
    // the crate root (keeps the non-Linux bin build import-clean).
    use brops_core::privilege_drop::{verify_performed_drop, DropJournal, DropSyscalls};
    use std::ffi::{CStr, CString};
    use std::fs;
    use std::io::Read;
    use std::os::unix::io::{FromRawFd, IntoRawFd};

    // The dedicated `brops-admin` TCB owner uid (§2.5): root(0) or brops-admin may own the executor image
    // AND the lease file. TODO: bind from the root-owned TcbPinManifest (`owner_uids[BropsAdmin]`); pinned
    // as the boundary constant so the fstat'd-fd owner check accepts exactly the two TCB principals.
    const TCB_OWNER_BROPS_ADMIN_UID: u32 = 500;

    // §4.7 per-artifact ceiling: a store-input inode (fd 3/4/5) must be a regular file no larger than this.
    // An over-ceiling inode is NOT accepted as a valid store input (the fail-closed gate refuses it), which
    // bounds the bytes the executor can be handed as a single artifact. 8 MiB is a sane §4.7-style ceiling
    // for a proof/artifact inode; small proof inputs pass unchanged. TODO: source the exact ceiling from the
    // lease/store policy once that field is plumbed through.
    const MAX_STORE_INPUT_BYTES: u64 = 8 * 1024 * 1024;

    pub fn real_main() -> Result<(), Refusal> {
        // (1) Fixed, closed argv: lease handle + pinned executor image + cgroup path. Any other shape, or a
        //     non-empty environment, is a confused-deputy signal ⇒ refuse.
        let args: Vec<String> = std::env::args().skip(1).collect();
        if args.len() != 3 || std::env::vars_os().next().is_some() {
            return Err(Refusal::BadArgv);
        }
        let lease_handle = &args[0];
        let executor_image = &args[1];
        // args[2] is the cgroup path. TODO(§2.7 step-2, deferred Linux-run slice): while still root, place
        // the process into this lease-authorized leaf cgroup and apply rlimits, and validate args[2]
        // against the lease-authorized cgroup path (refuse on mismatch). Currently NOT performed —
        // containment/reap of a runaway executor is therefore not yet enforced by the launcher; this is a
        // tracked containment gap (P2, not trust-forgery), not a silent omission.

        // (2) Read + integrity-verify the VALIDATED lease (§4.3). The launcher takes the invoker identity,
        //     the executor drop-target identity, and the executor image hash pin FROM the lease — it never
        //     chooses them. The lease file must be a regular, TCB-owned (root/brops-admin), non-writable
        //     file so a non-TCB principal cannot forge those pins (same §2.5 floor as the image; the
        //     supervisor-signed lease that also binds turn/nonce freshness is the documented next slice).
        let lease = read_and_verify_lease(lease_handle)?;
        let (exec_uid, exec_gid) = (lease.executor_uid, lease.executor_gid);

        // (2b) IDX-4 — the lease's request pins MUST equal the digests the receipt will attest. Read the
        //      root-owned canonical config from the COMPILE-TIME path (no argv, no env: the broker has no
        //      runtime input that redirects it) and compare, at TURN time, before any drop or exec. Until
        //      now this comparison existed only as a provisioning-time shell assertion, so a receipt could
        //      name a request that was never executed.
        let attested = read_and_verify_attested_request()?;
        verify_lease_matches_attested_request(&lease, &attested)?;

        // (3) §2.7 step 1 — INVOKER GATE, bound to the lease's recorder principal. Before ANY drop/exec,
        //     confirm the process that execve'd this setuid-root launcher is the recorder the lease names. A
        //     setuid-root binary starts euid=0 but INHERITS the caller's REAL uid/gid, so getresuid/
        //     getresgid reveal who actually invoked us; any other invoker is a confused-deputy ⇒ fail closed.
        verify_invoker_is_recorder(lease.recorder_uid, lease.recorder_gid)?;

        // (4) Verify the inherited descriptor table BEFORE any drop or exec (§2.7 launcher step 1–3).
        //     IDX-3: this now also enforces the store-input CUSTODY floor — each of fds 3/4/5 must name a
        //     regular inode owned by root/brops-admin with no group/other write bit, so no principal
        //     outside the TCB can rewrite the bytes under the executor at any point.
        let observed = collect_fd_facts()?;
        verify_launcher_fd_set(&observed, TCB_OWNER_BROPS_ADMIN_UID)?;

        // (4b) §2.7 store-input identity (audit F-08). The three read-only inputs on fds 3/4/5 ARE the
        //      governed request; the attested `request_sha256` is built from exactly their three digests.
        //      Nothing compared the two: the recorder opens `<recorder_store_dir>/system|history|
        //      generation_config` BY NAME while the attestation carries digests from a separate config key,
        //      so the executor could run on prompt A while the signed receipt attested prompt B. Re-hash the
        //      HELD descriptors against the root-owned lease pins here — before the drop, before the exec,
        //      and without a path re-lookup — so the bytes hashed are the bytes the executor reads.
        //
        //      IDX-3: keep the measurement. It records WHICH inode (dev/ino/uid/gid/mode/size) produced
        //      each digest, so step (9b) can require that the descriptors still name the same inodes
        //      holding the same bytes after the drop, the `/proc` reads and the image hash.
        let pinned_inputs = verify_store_input_bindings(&lease)?;

        // (5a) Open the drop JOURNAL. From here on every step this process completes is appended to it,
        //      and the journal — not a constant — is what step (9c) verifies.
        //
        //      AUDIT: this used to be `verify_order(CANONICAL_SEQUENCE)?` right here, which handed the
        //      checker the very constant the checker is written against, so it could not fail (indeed
        //      `privilege_drop.rs` asserts exactly that in a unit test). `drop_privileges` then issued
        //      the real syscalls and recorded NOTHING, so reordering or deleting one changed no checked
        //      value and failed no test, while the comment beside it claimed the order was "verified in
        //      step 3". Nothing was verified about this process.
        //
        //      NOTE the honest gap this exposes: `Step::CgroupSetup` is NOT recorded, because the
        //      launcher does not perform it — placing the process into the lease-authorized leaf cgroup
        //      is still the explicit TODO at step (1). The constant claimed that step; the journal does
        //      not, because it happened. `MANDATORY_PERFORMED_STEPS` therefore does not require it yet.
        let mut journal = DropJournal::new();
        journal.record(Step::VerifyEntry);

        // (4) Neutralize stdio: set FD_CLOEXEC on 0/1/2 so the inert endpoints do NOT cross fexecve — only
        //     the four data FDs 3–6 survive into the executor (§2.7 launcher step 3).
        for fd in 0..=2i32 {
            set_cloexec(fd)?;
        }

        // (5) Perform the locked privilege drop (groups/gid → bounding+ambient → uid → capset zero →
        //     no_new_privs) through the single recording driver in `brops-core`. There is exactly one
        //     call site per syscall, in a function whose order IS the contract, and each step lands in
        //     the journal only after its syscall reported success.
        drop_privileges(exec_uid, exec_gid, &mut journal)?;

        // (6) Fail-closed final-state verification: fully dropped, empty groups, all five cap sets empty,
        //     no_new_privs set. Any residual ⇒ abort, no exec (§2.7 step 8).
        let status = fs::read_to_string("/proc/self/status").map_err(|_| Refusal::Proc("status"))?;
        let post = parse_status(&status).ok_or(Refusal::Proc("status-parse"))?;
        verify_final_state(&post, exec_uid, exec_gid)?;
        journal.record(Step::VerifyUnprivileged);

        // (9) Open the executor image O_RDONLY|O_NOFOLLOW|O_CLOEXEC (NOT one of 3–6), then bind exec-time
        //     integrity to THAT exact fd: fstat it (regular, TCB-owned, non-writable) AND re-hash its bytes
        //     against the lease `executor_executable_sha256` pin, and fexecve the SAME fd — the bytes hashed
        //     are the bytes executed, with no path re-lookup. Any mismatch ⇒ ImageIntegrity (no exec).
        let image_fd = open_executor_image(executor_image, &lease.executor_executable_sha256)?;

        // (9b) IDX-3 — the LAST thing before the exec: re-measure fds 3/4/5 and require they still name the
        //      SAME inodes holding the SAME bytes they did at step (4b). Between those two points the
        //      launcher dropped privilege, read `/proc/self/status` and hashed the executor image; an
        //      in-place rewrite in that interval would have made the model run prompt A under a receipt
        //      attesting prompt B. Re-running the lease comparison as well means the recheck is bound to
        //      the same root-owned pins, not merely self-consistent.
        let recheck = verify_store_input_bindings(&lease)?;
        verify_store_inputs_unchanged(&pinned_inputs, &recheck)?;

        // (9c) §2.7 step ordering, judged against what THIS process did. `fexecve` is recorded here
        //      because the very next statement issues it and nothing can intervene — every other entry
        //      in the journal was appended after its operation completed. `verify_performed_drop`
        //      requires every mandatory step, once each, in the load-bearing order; a syscall that was
        //      reordered, deleted, or that failed leaves a journal that does not satisfy it, and the
        //      launcher refuses with no exec. This is the check the old `verify_order(CANONICAL_SEQUENCE)`
        //      pretended to be.
        //
        //      `Fexecve` is the ONE entry recorded before its operation rather than after, because the
        //      operation never returns on success — it replaces this image. It is recorded here, with
        //      the verification and the exec as the next two statements and nothing between them, so
        //      "recorded" and "issued" cannot come apart. Because the journal is append-only and
        //      `verify_performed_drop` requires `Fexecve` to be strictly last, no step can be recorded
        //      after it either.
        journal.record(Step::Fexecve);
        verify_performed_drop(journal.steps())?;

        fexecve_pinned(image_fd, executor_image)?; // returns ONLY on failure
        Err(Refusal::Syscall("fexecve"))
    }

    /// Read + integrity-verify the validated lease at `path` (§4.3). Opens `O_RDONLY|O_NOFOLLOW|O_CLOEXEC`,
    /// fstats the OPENED fd, and requires a regular, TCB-owned (root/brops-admin), non group/other-writable
    /// file (so a non-TCB principal cannot forge the pins — same floor as the executor image), then parses
    /// the strict `key=value` body. Any open/stat/ownership/parse failure ⇒ fail closed (no exec).
    fn read_and_verify_lease(path: &str) -> Result<Lease, Refusal> {
        let c = CString::new(path).map_err(|_| Refusal::TcbIntegrity("lease-path"))?;
        // SAFETY: open with a valid NUL-terminated path; flags are constants.
        let fd = unsafe {
            libc::open(
                c.as_ptr(),
                libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            )
        };
        if fd < 0 {
            return Err(Refusal::TcbIntegrity("lease-open"));
        }
        // fstat the EXACT opened fd (never a metadata(path) re-lookup): regular, TCB-owned, non-writable.
        // SAFETY: fd is a live descriptor; fstat gets a valid out-pointer to a plain C `stat`.
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::fstat(fd, &mut st) } != 0 {
            unsafe { libc::close(fd) };
            return Err(Refusal::TcbIntegrity("lease-fstat"));
        }
        if !image_owner_mode_ok(st.st_mode, st.st_uid, TCB_OWNER_BROPS_ADMIN_UID) {
            unsafe { libc::close(fd) };
            return Err(Refusal::TcbIntegrity("lease-owner-mode"));
        }
        // SAFETY: we own `fd` exclusively; the File takes ownership and closes it on drop (we do NOT exec
        // the lease, so — unlike the image path — we let it close here).
        let mut f = unsafe { fs::File::from_raw_fd(fd) };
        let mut body = String::new();
        if f.read_to_string(&mut body).is_err() {
            return Err(Refusal::TcbIntegrity("lease-read"));
        }
        parse_lease(&body).ok_or(Refusal::TcbIntegrity("lease-parse"))
    }

    /// §2.7 store-input identity binding (audit **F-08**): re-hash the bytes behind the HELD fds 3/4/5 and
    /// require each to equal the root-owned lease's pin for that slot.
    ///
    /// Read with `pread` from absolute offset 0 so the file offset the §2.7 verifier already certified as
    /// zero is NOT disturbed — the executor still starts each input at byte 0. Never re-opens by path: the
    /// bytes hashed are the bytes the executor will read from the same open file description. The §4.7
    /// per-artifact ceiling already bounds how much can be read (`collect_fd_facts` refuses a larger inode).
    fn verify_store_input_bindings(lease: &Lease) -> Result<Vec<StoreInputSnapshot>, Refusal> {
        // The DECISION lives in the pure `verify_store_inputs` (host-independent, unit-tested);
        // this only supplies the real `fstat` + `pread`. The remediation audit found the previous
        // shape had zero tests over the digest-and-compare — the four "F-08 tests" covered the lease
        // parser and the fd→pin map, so deleting this whole check left the suite green. A parser test
        // is not a test of the thing the parser feeds.
        verify_store_inputs(lease, fd_inode_identity, digest_fd_at_zero)
    }

    /// The `fstat` identity of the inode behind a HELD descriptor (audit IDX-3). Never a `stat(path)`
    /// re-lookup: the point is to name the object the executor will actually read. `None` on a failed
    /// `fstat` ⇒ the caller fails closed rather than pinning content alone.
    fn fd_inode_identity(fd: i32) -> Option<InodeIdentity> {
        // SAFETY: `fd` is a live inherited descriptor; fstat gets a valid out-pointer to a plain C stat.
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::fstat(fd, &mut st) } != 0 {
            return None;
        }
        Some(inode_identity_from_stat(&st))
    }

    /// Widen a platform `stat` into the host-independent [`InodeIdentity`]. A negative `st_size` (which
    /// the kernel does not produce for a regular file) is not silently coerced — it is folded to `u64::MAX`
    /// so it can never compare equal to a plausible size, and the §4.7 ceiling in `collect_fd_facts`
    /// rejects the descriptor as a store input in the first place.
    fn inode_identity_from_stat(st: &libc::stat) -> InodeIdentity {
        InodeIdentity {
            dev: st.st_dev as u64,
            ino: st.st_ino as u64,
            uid: st.st_uid,
            gid: st.st_gid,
            mode: st.st_mode as u32,
            size: if st.st_size < 0 {
                u64::MAX
            } else {
                st.st_size as u64
            },
        }
    }

    /// Read + custody-verify the ROOT-OWNED canonical config the receipt's request digests come from
    /// (audit **IDX-4**), from the COMPILE-TIME [`ATTESTED_REQUEST_PATH`].
    ///
    /// Same §2.5 floor as the lease and the executor image: opened `O_RDONLY|O_NOFOLLOW|O_CLOEXEC`, the
    /// OPENED fd is `fstat`ed (regular, root/brops-admin owned, no group/other write), and the body is read
    /// from that same descriptor — a non-TCB principal cannot forge the digests the lease is measured
    /// against. Any open/stat/ownership/size/parse failure is a refusal, not a fallback.
    fn read_and_verify_attested_request() -> Result<AttestedRequest, Refusal> {
        // A config far larger than any plausible deployment config is refused rather than read: the
        // scanner is bounded work over bytes this setuid-root process must not be made to buffer.
        const MAX_ATTESTED_CONFIG_BYTES: u64 = 1024 * 1024;

        let c = CString::new(ATTESTED_REQUEST_PATH)
            .map_err(|_| Refusal::TcbIntegrity("attested-request-path"))?;
        // SAFETY: open with a valid NUL-terminated path; flags are constants.
        let fd = unsafe {
            libc::open(
                c.as_ptr(),
                libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            )
        };
        if fd < 0 {
            return Err(Refusal::TcbIntegrity("attested-request-open"));
        }
        // SAFETY: fd is a live descriptor; fstat gets a valid out-pointer to a plain C `stat`.
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::fstat(fd, &mut st) } != 0 {
            unsafe { libc::close(fd) };
            return Err(Refusal::TcbIntegrity("attested-request-fstat"));
        }
        if !image_owner_mode_ok(st.st_mode, st.st_uid, TCB_OWNER_BROPS_ADMIN_UID) {
            unsafe { libc::close(fd) };
            return Err(Refusal::TcbIntegrity("attested-request-owner-mode"));
        }
        if st.st_size < 0 || st.st_size as u64 > MAX_ATTESTED_CONFIG_BYTES {
            unsafe { libc::close(fd) };
            return Err(Refusal::TcbIntegrity("attested-request-size"));
        }
        // SAFETY: we own `fd` exclusively; the File takes ownership and closes it on drop.
        let mut f = unsafe { fs::File::from_raw_fd(fd) };
        let mut body = String::new();
        if f.read_to_string(&mut body).is_err() {
            return Err(Refusal::TcbIntegrity("attested-request-read"));
        }
        parse_attested_request(&body).ok_or(Refusal::TcbIntegrity("attested-request-parse"))
    }

    /// SHA-256 (lowercase hex) of a held descriptor's contents, read positionally from offset 0. `None` on
    /// any read error or if the content exceeds the §4.7 ceiling (⇒ the caller fails closed).
    fn digest_fd_at_zero(fd: i32) -> Option<String> {
        let mut buf = Vec::new();
        let mut chunk = [0u8; 64 * 1024];
        let mut off: i64 = 0;
        loop {
            // SAFETY: `fd` is a live inherited descriptor; the buffer/len pair is valid for the call and
            // `pread` does not move the descriptor's file offset.
            let n = unsafe {
                libc::pread(
                    fd,
                    chunk.as_mut_ptr() as *mut libc::c_void,
                    chunk.len(),
                    off as libc::off_t,
                )
            };
            if n < 0 {
                return None;
            }
            if n == 0 {
                break;
            }
            let n = n as usize;
            if buf.len() + n > MAX_STORE_INPUT_BYTES as usize {
                return None; // over the §4.7 ceiling ⇒ fail closed rather than hash a partial input
            }
            buf.extend_from_slice(&chunk[..n]);
            off += n as i64;
        }
        Some(brops_core::governed_message_store::sha256_hex(&buf))
    }

    /// §2.7 step-1 invoker gate: the launcher is setuid-root but must ONLY ever be invoked BY the recorder
    /// principal the validated lease names. `getresuid`/`getresgid` expose the REAL uid/gid inherited from
    /// the caller; both MUST equal `recorder_uid`/`recorder_gid` or we refuse before any privilege/exec work.
    fn verify_invoker_is_recorder(recorder_uid: u32, recorder_gid: u32) -> Result<(), Refusal> {
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
        // Only the REAL uid/gid identify the invoker (euid/egid are the setuid-root target). Bind both to
        // the recorder principal the validated lease authorizes.
        if ruid != recorder_uid || rgid != recorder_gid {
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
            // Finding 1 (fail CLOSED on an un-inspectable inherited fd): a numeric fd that is NOT the
            // excluded dirfd whose `/proc/self/fd` symlink cannot be read must ABORT the launch — never
            // `continue` (that silently DROPPED an inherited fd >= 7 so it escaped the exact-{0..6} gate: a
            // fail-open). The "." / ".." / non-numeric parse skip above stays a `continue`; only these
            // post-numeric read errors fail closed, mirroring how the fdinfo read below fails closed.
            let link = fs::read_link(format!("/proc/self/fd/{fd}"))
                .map_err(|_| Refusal::Proc("fd-readlink"))?;
            let info = fs::read_to_string(format!("/proc/self/fdinfo/{fd}"))
                .ok()
                .and_then(|c| parse_fdinfo(&c))
                .ok_or(Refusal::Proc("fdinfo"))?;
            let target = link.to_string_lossy().into_owned();

            // Finding 2 (honest store-inode fact, no path re-lookup): determine "regular store inode" by
            // `fstat` of the HELD fd (never `fs::metadata(path)` — that is a TOCTOU re-lookup that only
            // checked is_file()) AND bound it by the §4.7 per-artifact ceiling. A store input must be a
            // regular file (S_ISREG) whose size is <= MAX_STORE_INPUT_BYTES; a non-regular or over-ceiling
            // inode yields is_regular_store_inode=false, so the pure verifier's StoreInput branch refuses it.
            // Small proof inputs pass unchanged. (O_RDONLY + offset-0 are supplied by the other fields.)
            //
            // IDX-3: the SAME fstat now also yields the inode IDENTITY (`st_dev`/`st_ino` plus the
            // owner/mode/size that say who may rewrite it). `st_dev` is carried because an inode number
            // alone is only unique within a device — this is the "bind st_dev" the previous TODO deferred.
            // The verifier's StoreInput branch requires the identity to be present AND TCB-custodied.
            // SAFETY: `fd` is a live inherited descriptor; fstat gets a valid out-pointer to a plain C stat.
            let mut st: libc::stat = unsafe { std::mem::zeroed() };
            if unsafe { libc::fstat(fd, &mut st) } != 0 {
                return Err(Refusal::Proc("fd-fstat"));
            }
            let is_regular_store_inode = (st.st_mode & S_IFMT_MASK) == S_IFREG_BITS
                && st.st_size >= 0
                && (st.st_size as u64) <= MAX_STORE_INPUT_BYTES;

            let inert = target == "/dev/null";
            out.push(FdFacts {
                fd,
                identity: Some(inode_identity_from_stat(&st)),
                is_inert_endpoint: inert,
                // Stdio is inert-only; anything that is not the approved /dev/null endpoint is treated as
                // interactive/inherited for the fail-closed 0/1/2 check.
                is_interactive_or_inherited: !inert,
                read_only: info.accmode == 0,
                is_regular_store_inode,
                offset_zero: info.pos == 0,
                is_output_pipe: target.starts_with("pipe:"),
                // Finding 3: fd 6 must be the WRITE-ONLY output pipe — set write_only from the parsed
                // fdinfo accmode (1 == O_WRONLY), NOT from the `pipe:` link prefix. The verifier's
                // OutputPipe branch now requires this (mirroring read_only for StoreInput).
                write_only: info.accmode == 1,
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

    /// The real Linux privilege-drop syscalls behind `brops_core`'s [`DropSyscalls`] seam.
    ///
    /// Each method performs EXACTLY ONE operation and reports success. It must stay that way: the
    /// driver (`privilege_drop::perform_drop`) records a step the moment the corresponding method
    /// returns `true`, so a method that quietly did a second step's work would put a false entry in the
    /// journal. The ORDER lives in the driver, which is host-independent and unit-tested — that is what
    /// makes reordering the drop something a test can see, on any machine.
    struct RealDropSyscalls;

    impl DropSyscalls for RealDropSyscalls {
        fn set_groups_empty(&mut self) -> bool {
            // Clear all supplementary groups (must precede the UID drop).
            // SAFETY: setgroups with count 0 and a NULL list is the documented "clear" form.
            unsafe { libc::setgroups(0, std::ptr::null()) == 0 }
        }

        fn set_res_gid(&mut self, gid: u32) -> bool {
            // SAFETY: plain integer arguments.
            unsafe { libc::setresgid(gid, gid, gid) == 0 }
        }

        fn drop_bounding_and_ambient_caps(&mut self) -> bool {
            // Drop the capability bounding set (needs CAP_SETPCAP, still root here) and clear ambient.
            for cap in 0..=63i32 {
                // EINVAL for non-existent cap numbers is benign; a real drop failure surfaces at the
                // capget-verify in `verify_final_state`.
                // SAFETY: prctl with constant options and an integer capability number.
                unsafe {
                    libc::prctl(libc::PR_CAPBSET_DROP, cap as libc::c_ulong, 0, 0, 0);
                }
            }
            // SAFETY: prctl with constant options.
            unsafe {
                libc::prctl(libc::PR_CAP_AMBIENT, libc::PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0) == 0
            }
        }

        fn set_res_uid(&mut self, uid: u32) -> bool {
            // Drop the UID (loses the effective/permitted caps root implied).
            // SAFETY: plain integer arguments.
            unsafe { libc::setresuid(uid, uid, uid) == 0 }
        }

        fn clear_all_cap_sets(&mut self) -> bool {
            // Belt-and-suspenders: zero effective/permitted/inheritable capability sets.
            capset_zero()
        }

        fn set_no_new_privs(&mut self) -> bool {
            // Locks further privilege gain BEFORE the final verify, so `verify_final_state`'s
            // no_new_privs check holds. Stricter than, and compatible with, the canonical ordering:
            // no_new_privs still precedes fexecve.
            // SAFETY: prctl with constant options.
            unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0 }
        }
    }

    /// Run the locked drop and RECORD what it performed into `journal`.
    ///
    /// The ordering is not written here any more — it is `privilege_drop::perform_drop`'s, which is the
    /// only place it exists, is exercised by a recording fake in `brops-core`'s unit tests, and appends
    /// to the journal that step (9c) verifies before any exec.
    fn drop_privileges(uid: u32, gid: u32, journal: &mut DropJournal) -> Result<(), Refusal> {
        brops_core::privilege_drop::perform_drop(&mut RealDropSyscalls, uid, gid, journal)
            .map_err(|failed| Refusal::Syscall(failed.name()))
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

    fn open_executor_image(path: &str, expected_sha256: &str) -> Result<i32, Refusal> {
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
        if brops_core::receipt::sha256_hex(&bytes) != expected_sha256 {
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
    const ADMIN_UID: u32 = 500;

    /// A TCB-owned (root), non-writable regular store inode — what the §2.5/IDX-3 custody floor accepts.
    fn ident(fd: i32) -> InodeIdentity {
        InodeIdentity {
            dev: 66,
            ino: 1000 + fd as u64,
            uid: 0,
            gid: 0,
            mode: 0o100644,
            size: 33,
        }
    }

    fn inert(fd: i32) -> FdFacts {
        FdFacts {
            fd,
            identity: None,
            is_inert_endpoint: true,
            is_interactive_or_inherited: false,
            read_only: false,
            is_regular_store_inode: false,
            offset_zero: false,
            is_output_pipe: false,
            write_only: false,
            cloexec: false,
        }
    }
    fn store(fd: i32) -> FdFacts {
        FdFacts {
            fd,
            identity: Some(ident(fd)),
            is_inert_endpoint: false,
            is_interactive_or_inherited: false,
            read_only: true,
            is_regular_store_inode: true,
            offset_zero: true,
            is_output_pipe: false,
            write_only: false,
            cloexec: false,
        }
    }
    fn output() -> FdFacts {
        FdFacts {
            fd: 6,
            identity: None,
            is_inert_endpoint: false,
            is_interactive_or_inherited: false,
            read_only: false,
            is_regular_store_inode: false,
            offset_zero: false,
            is_output_pipe: true,
            write_only: true,
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
            identity: None,
            is_inert_endpoint: false,
            is_interactive_or_inherited: true,
            read_only: true,
            is_regular_store_inode: false,
            offset_zero: false,
            is_output_pipe: false,
            write_only: false,
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
            brops_admin_uid: ADMIN_UID,
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

    // ---- parse_lease -------------------------------------------------------------------------------
    fn good_lease_body() -> String {
        format!(
            "recorder_uid=5005\nrecorder_gid=5005\nexecutor_uid=5007\nexecutor_gid=5007\n\
             executor_executable_sha256={}\nsystem_sha256={}\nhistory_sha256={}\n\
             generation_config_sha256={}\n",
            "ab".repeat(32), // 64 lowercase-hex chars
            "11".repeat(32),
            "22".repeat(32),
            "33".repeat(32),
        )
    }

    #[test]
    fn parse_lease_reads_a_well_formed_lease() {
        let l = parse_lease(&good_lease_body()).expect("parses");
        assert_eq!(l.recorder_uid, 5005);
        assert_eq!(l.recorder_gid, 5005);
        assert_eq!(l.executor_uid, 5007);
        assert_eq!(l.executor_gid, 5007);
        assert_eq!(l.executor_executable_sha256, "ab".repeat(32));
        assert_eq!(l.system_sha256, "11".repeat(32));
        assert_eq!(l.history_sha256, "22".repeat(32));
        assert_eq!(l.generation_config_sha256, "33".repeat(32));
        // blank lines + surrounding whitespace around key/value are tolerated
        let padded = format!(
            "\n  recorder_uid = 5005 \nrecorder_gid=5005\n\nexecutor_uid=5007\nexecutor_gid=5007\n  executor_executable_sha256 = {}  \nsystem_sha256={}\nhistory_sha256={}\ngeneration_config_sha256={}\n",
            "ab".repeat(32),
            "11".repeat(32),
            "22".repeat(32),
            "33".repeat(32),
        );
        assert_eq!(parse_lease(&padded), parse_lease(&good_lease_body()));
    }

    #[test]
    fn parse_lease_fails_closed_on_missing_dup_unknown_or_bad_fields() {
        // missing a required key (no executor_gid)
        let missing = "recorder_uid=5005\nrecorder_gid=5005\nexecutor_uid=5007\n\
                       executor_executable_sha256=".to_string()
            + &"ab".repeat(32);
        assert_eq!(parse_lease(&missing), None);
        // duplicate key
        let dup = format!("{}recorder_uid=6000\n", good_lease_body());
        assert_eq!(parse_lease(&dup), None);
        // unknown key
        let unknown = format!("{}rogue_key=1\n", good_lease_body());
        assert_eq!(parse_lease(&unknown), None);
        // non-numeric uid
        assert_eq!(parse_lease(&good_lease_body().replace("5005", "root")), None);
        // digest wrong length
        assert_eq!(parse_lease(&good_lease_body().replace(&"ab".repeat(32), "abcd")), None);
        // digest non-hex / uppercase (must be lowercase hex)
        assert_eq!(parse_lease(&good_lease_body().replace(&"ab".repeat(32), &"AB".repeat(32))), None);
        // a line without '='
        assert_eq!(parse_lease(&format!("{}garbage\n", good_lease_body())), None);
    }

    #[test]
    fn parse_lease_rejects_privileged_or_recorder_executor_target() {
        // The executor must be a dedicated UNPRIVILEGED principal, distinct from root and the recorder.
        // (good_lease_body: recorder_uid/gid=5005, executor_uid/gid=5007.)
        assert_eq!(parse_lease(&good_lease_body().replace("executor_uid=5007", "executor_uid=0")), None);
        assert_eq!(parse_lease(&good_lease_body().replace("executor_gid=5007", "executor_gid=0")), None);
        // executor == recorder (would run the executor as the invoking recorder principal)
        assert_eq!(parse_lease(&good_lease_body().replace("executor_uid=5007", "executor_uid=5005")), None);
        assert_eq!(parse_lease(&good_lease_body().replace("executor_gid=5007", "executor_gid=5005")), None);
    }

    // ---- F-08: the governed request must be PINNED, not merely named ------------------------------

    #[test]
    fn a_lease_without_the_request_pins_is_refused() {
        // The whole point of F-08 is that the executed bytes are checked. A lease that omits any of the
        // three pins would leave that slot unchecked, so it must not parse at all — "unpinned" has to be
        // impossible to express, not merely discouraged.
        for key in ["system_sha256", "history_sha256", "generation_config_sha256"] {
            let without: String = good_lease_body()
                .lines()
                .filter(|l| !l.trim_start().starts_with(key))
                .map(|l| format!("{l}\n"))
                .collect();
            assert_eq!(parse_lease(&without), None, "{key} must be required");
        }
    }

    #[test]
    fn the_request_pins_are_digest_shaped_and_single_valued() {
        // Same canonical-digest floor as the image pin: 64 lowercase hex, exactly once.
        assert_eq!(parse_lease(&good_lease_body().replace(&"11".repeat(32), "beef")), None);
        assert_eq!(
            parse_lease(&good_lease_body().replace(&"22".repeat(32), &"AB".repeat(32))),
            None
        );
        let dup = format!("{}history_sha256={}\n", good_lease_body(), "44".repeat(32));
        assert_eq!(parse_lease(&dup), None);
    }

    // ---- the F-08 DECISION itself, not the parser around it -------------------------------

    fn good_lease() -> Lease {
        parse_lease(&good_lease_body()).expect("parses")
    }

    /// The honest digest for each slot, as the lease pins them.
    fn honest_digest(fd: i32) -> String {
        match fd {
            3 => "11".repeat(32),
            4 => "22".repeat(32),
            _ => "33".repeat(32),
        }
    }

    #[test]
    fn matching_inputs_are_accepted() {
        let l = good_lease();
        let ok = verify_store_inputs(&l, |fd| Some(ident(fd)), |fd| Some(honest_digest(fd)));
        // IDX-3: acceptance now MEASURES — which inode produced each pinned digest — so the
        // pre-fexecve recheck has something to compare against.
        assert_eq!(
            ok,
            Ok(vec![
                StoreInputSnapshot { fd: 3, identity: ident(3), digest: "11".repeat(32) },
                StoreInputSnapshot { fd: 4, identity: ident(4), digest: "22".repeat(32) },
                StoreInputSnapshot { fd: 5, identity: ident(5), digest: "33".repeat(32) },
            ])
        );
    }

    #[test]
    fn any_single_input_that_differs_from_its_pin_refuses() {
        // The attack F-08 exists for: the executor runs on bytes the receipt does not attest.
        // One slot at a time, because a check that only looks at the first would pass two of these.
        let l = good_lease();
        for bad in [3, 4, 5] {
            let r = verify_store_inputs(
                &l,
                |fd| Some(ident(fd)),
                |fd| {
                    Some(if fd == bad {
                        "ff".repeat(32) // whatever the attacker substituted
                    } else {
                        honest_digest(fd)
                    })
                },
            );
            assert_eq!(r, Err(Refusal::TcbIntegrity("store-input-digest")), "fd {bad}");
        }
    }

    #[test]
    fn transposed_inputs_are_refused() {
        // system's bytes presented on the history descriptor. Every digest is a REAL digest of a
        // real store input, so a check that merely asked "is this one of the pinned digests?"
        // would accept it.
        let l = good_lease();
        let r = verify_store_inputs(
            &l,
            |fd| Some(ident(fd)),
            |fd| {
                Some(match fd {
                    3 => "22".repeat(32),
                    4 => "11".repeat(32),
                    _ => "33".repeat(32),
                })
            },
        );
        assert_eq!(r, Err(Refusal::TcbIntegrity("store-input-digest")));
    }

    #[test]
    fn an_unreadable_input_refuses_rather_than_being_skipped() {
        let l = good_lease();
        let r = verify_store_inputs(
            &l,
            |fd| Some(ident(fd)),
            |fd| if fd == 4 { None } else { Some("11".repeat(32)) },
        );
        assert_eq!(r, Err(Refusal::TcbIntegrity("store-input-read")));
    }

    #[test]
    fn an_input_whose_inode_cannot_be_identified_refuses() {
        // IDX-3: the digest alone is a snapshot of an object nothing names. If the launcher cannot say
        // WHICH inode produced the bytes, it must refuse — not pin content and hope.
        let l = good_lease();
        for missing in [3, 4, 5] {
            let r = verify_store_inputs(
                &l,
                |fd| if fd == missing { None } else { Some(ident(fd)) },
                |fd| Some(honest_digest(fd)),
            );
            assert_eq!(
                r,
                Err(Refusal::TcbIntegrity("store-input-identity")),
                "fd {missing}"
            );
        }
    }

    // ---- IDX-3: the launch gate refuses a store inode the TCB does not exclusively own ------------

    #[test]
    fn gate_refuses_a_store_input_a_non_tcb_principal_could_rewrite() {
        // The composed gate — not just the core predicate — must carry the custody floor, because that
        // is what makes the pre-exec recheck meaningful: a group-writable or foreign-owned inode can be
        // rewritten in the interval no launcher-side check can shrink to zero.
        let mut foreign = good_facts();
        foreign.observed_fds[3].identity = Some(InodeIdentity { uid: 5007, ..ident(3) });
        assert_eq!(
            evaluate_launch(&foreign),
            Err(Refusal::Fd(FdViolation::StoreInputCustody(3)))
        );

        let mut writable = good_facts();
        writable.observed_fds[5].identity = Some(InodeIdentity { mode: 0o100666, ..ident(5) });
        assert_eq!(
            evaluate_launch(&writable),
            Err(Refusal::Fd(FdViolation::StoreInputCustody(5)))
        );

        let mut unpinned = good_facts();
        unpinned.observed_fds[4].identity = None;
        assert_eq!(
            evaluate_launch(&unpinned),
            Err(Refusal::Fd(FdViolation::StoreInputUnpinnedInode(4)))
        );
    }

    #[test]
    fn gate_refuses_when_an_input_is_rewritten_between_the_pin_and_the_exec() {
        // The IDX-3 window itself, expressed over the two measurements the launcher takes: pin at digest
        // time, recheck immediately before fexecve. Both flavours — a swapped inode and an in-place
        // rewrite of the same inode — must refuse.
        let l = good_lease();
        let pinned = verify_store_inputs(&l, |fd| Some(ident(fd)), |fd| Some(honest_digest(fd)))
            .expect("the honest measurement is accepted");

        let mut swapped = pinned.clone();
        swapped[0].identity.ino += 1; // fd 3 now names a different inode
        assert_eq!(
            verify_store_inputs_unchanged(&pinned, &swapped),
            Err(FdViolation::StoreInputInodeChanged(3))
        );

        let mut rewritten = pinned.clone();
        rewritten[2].digest = "ff".repeat(32); // fd 5 same inode, different bytes
        assert_eq!(
            verify_store_inputs_unchanged(&pinned, &rewritten),
            Err(FdViolation::StoreInputContentChanged(5))
        );

        assert_eq!(verify_store_inputs_unchanged(&pinned, &pinned), Ok(()));
    }

    // ---- IDX-4: the lease's request pins vs the digests the receipt attests -----------------------

    fn attested_config(system: &str, history: &str, generation_config: &str) -> String {
        // The shape of the real `/opt/brops-live/config.json` `resolved` block.
        format!(
            "{{\n\
             \x20 \"execution\": {{ \"cgroup_arg\": \"/brops.slice\" }},\n\
             \x20 \"resolved\": {{\n\
             \x20   \"workspace_id\": \"ws\",\n\
             \x20   \"system_sha256\": \"{system}\",\n\
             \x20   \"history_sha256\": \"{history}\",\n\
             \x20   \"generation_config_sha256\": \"{generation_config}\",\n\
             \x20   \"requested_at\": \"1700000000000\"\n\
             \x20 }}\n}}\n"
        )
    }

    fn honest_config() -> String {
        attested_config(&"11".repeat(32), &"22".repeat(32), &"33".repeat(32))
    }

    #[test]
    fn the_lease_pins_must_equal_the_digests_the_receipt_attests() {
        let l = good_lease();
        let a = parse_attested_request(&honest_config()).expect("parses");
        assert_eq!(verify_lease_matches_attested_request(&l, &a), Ok(()));
    }

    #[test]
    fn a_lease_pin_that_diverges_from_the_attested_digest_refuses() {
        // The defect IDX-4 names: the receipt's request binding naming bytes that were never executed.
        // One slot at a time and with a distinct reason per slot, because a check that stopped at the
        // first comparison — or compared the triple as a set — would let two of these through.
        let l = good_lease();
        let cases = [
            (
                attested_config(&"ff".repeat(32), &"22".repeat(32), &"33".repeat(32)),
                "attested-request-system",
            ),
            (
                attested_config(&"11".repeat(32), &"ff".repeat(32), &"33".repeat(32)),
                "attested-request-history",
            ),
            (
                attested_config(&"11".repeat(32), &"22".repeat(32), &"ff".repeat(32)),
                "attested-request-generation-config",
            ),
        ];
        for (cfg, reason) in cases {
            let a = parse_attested_request(&cfg).expect("parses");
            assert_eq!(
                verify_lease_matches_attested_request(&l, &a),
                Err(Refusal::TcbIntegrity(reason))
            );
        }
    }

    #[test]
    fn transposed_attested_digests_refuse() {
        // Every digest is a REAL digest of a real store input; only the slots are swapped. A comparison
        // that asked "is this one of the three?" would accept it and the receipt would attest the wrong
        // prompt on the wrong descriptor.
        let l = good_lease();
        let a = parse_attested_request(&attested_config(
            &"22".repeat(32),
            &"11".repeat(32),
            &"33".repeat(32),
        ))
        .expect("parses");
        assert_eq!(
            verify_lease_matches_attested_request(&l, &a),
            Err(Refusal::TcbIntegrity("attested-request-system"))
        );
    }

    #[test]
    fn an_unreadable_or_ambiguous_attested_config_refuses() {
        // Fail closed on anything that is not exactly one canonical digest per key. In particular a
        // document that mentions a key TWICE is refused rather than resolved by a precedence rule — the
        // launcher must not be the component that decides which of two `system_sha256` values counts.
        assert_eq!(parse_attested_request("not json at all"), None);
        // missing key
        assert_eq!(
            parse_attested_request(&honest_config().replace("\"history_sha256\"", "\"other_key\"")),
            None
        );
        // duplicated key
        let dup = honest_config().replace(
            "\"requested_at\": \"1700000000000\"",
            &format!("\"system_sha256\": \"{}\"", "44".repeat(32)),
        );
        assert_eq!(parse_attested_request(&dup), None);
        // non-canonical digest: wrong length, then uppercase hex
        assert_eq!(
            parse_attested_request(&attested_config("beef", &"22".repeat(32), &"33".repeat(32))),
            None
        );
        assert_eq!(
            parse_attested_request(&attested_config(
                &"AB".repeat(32),
                &"22".repeat(32),
                &"33".repeat(32)
            )),
            None
        );
        // a digest that is not a JSON string value at all
        assert_eq!(
            parse_attested_request(&honest_config().replace(
                &format!("\"system_sha256\": \"{}\"", "11".repeat(32)),
                "\"system_sha256\": null"
            )),
            None
        );
    }

    #[test]
    fn the_attested_config_is_read_from_a_compile_time_path() {
        // IDX-4's whole point is that the broker cannot steer this. If the path ever becomes an argv flag
        // or an environment lookup, the check reduces to "compare the lease against a file the attacker
        // chose". The launcher takes exactly three argv tokens (lease, image, cgroup) and an EMPTY
        // environment, so pinning the constant here is what keeps the source out of the broker's reach.
        assert!(ATTESTED_REQUEST_PATH.starts_with('/'));
        assert!(!ATTESTED_REQUEST_PATH.contains(".."));
    }

    #[test]
    fn the_pins_are_mapped_to_the_fds_the_recorder_opens() {
        // fd 3 = system, 4 = history, 5 = generation_config — the same fixed order the recorder opens them
        // in AND the order the attested request_sha256 is built from. A transposition here would bind the
        // right bytes to the wrong slot and silently accept a swapped system/history pair.
        let l = parse_lease(&good_lease_body()).expect("parses");
        assert_eq!(
            store_input_pins(&l),
            [
                (3, "11".repeat(32).as_str()),
                (4, "22".repeat(32).as_str()),
                (5, "33".repeat(32).as_str()),
            ]
        );
    }
}
