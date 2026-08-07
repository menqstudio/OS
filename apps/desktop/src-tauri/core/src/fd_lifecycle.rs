//! Wave 3b-1B — executor file-descriptor lifecycle contract (implements the design-GREEN rev-30 §2.7 P1-2
//! + P0-3: the recorder prepares FDs 3–6 and inert 0/1/2 before `execve(launcher)`; the launcher verifies
//! EXACTLY {0,1,2,3,4,5,6} before `fexecve(executor)` — 0/1/2 the approved inert endpoints (closed or
//! `FD_CLOEXEC` before exec), 3/4/5 read-only store inputs, 6 the write-only output pipe, `FD_CLOEXEC`
//! CLEARED on 3–6 so they survive, and NO descriptor ≥ 7.
//!
//! The actual `dup2`/`fcntl`/`fexecve` syscalls are Linux (a later launcher-crate slice). This module is
//! the PURE, platform-independent DECISION logic — given an observed descriptor table it returns the exact
//! rev-30 fail-closed verdict — so every rule is unit-testable on any host without spawning a process.

/// The role a descriptor must hold in the contained executor's table.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FdRole {
    /// 0/1/2 — a controlled inert endpoint (`/dev/null` or a controlled sink), never interactive/inherited.
    Inert,
    /// 3/4/5 — a read-only (`O_RDONLY`), regular, offset-0 `brops-store` input inode.
    StoreInput,
    /// 6 — the write-only output pipe.
    OutputPipe,
}

/// The kernel-reported identity of the inode behind a HELD descriptor, captured by `fstat` on that
/// descriptor (never by a `stat(path)` re-lookup).
///
/// Audit **IDX-3**: digesting the bytes behind fd 3/4/5 pins the CONTENT at one instant, but it says
/// nothing about WHICH inode produced them, and nothing about whether that inode can still be rewritten
/// underneath the executor. `dev`/`ino` name the inode; `uid`/`gid`/`mode` say who may write it. Both are
/// needed: content alone is a snapshot of an unpinned object.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InodeIdentity {
    /// `st_dev` — the device the inode lives on. Without it, `ino` is ambiguous across mounts, so a
    /// bind-mounted or otherwise substituted filesystem could present the same inode number.
    pub dev: u64,
    /// `st_ino` — the inode number on `dev`.
    pub ino: u64,
    /// `st_uid` — the owning principal. A store input owned outside the TCB is rewritable outside it.
    pub uid: u32,
    /// `st_gid` — the owning group (recorded so a group change is visible as an identity change).
    pub gid: u32,
    /// `st_mode` — type + permission bits. Group/other write on a store input is an in-place-rewrite
    /// vector for a non-TCB principal.
    pub mode: u32,
    /// `st_size` — recorded so a truncate/extend is an identity change even before the bytes are re-read.
    pub size: u64,
}

/// `<sys/stat.h>` masks, as host-independent literals so these predicates compile/test on any OS.
const S_IFMT_MASK: u32 = 0o170000;
const S_IFREG_BITS: u32 = 0o100000;
const GROUP_OTHER_WRITE_BITS: u32 = 0o022;

/// The custody floor a store-input inode must meet (audit **IDX-3**): a **regular file**, owned by a TCB
/// principal (`root(0)` or the provisioned `brops-admin`), with **no group/other write bit**.
///
/// This is the half of IDX-3 that actually CLOSES the rewrite window rather than narrowing it: if no
/// principal outside the TCB may write the inode, no principal outside the TCB can swap prompt A for
/// prompt B between the digest and the executor's own read. Root can still rewrite it — root owns the
/// lease, the launcher and the executor image, so that is inside the trust boundary, not a bypass of it.
pub fn store_inode_custody_ok(id: &InodeIdentity, brops_admin_uid: u32) -> bool {
    let is_regular = (id.mode & S_IFMT_MASK) == S_IFREG_BITS;
    let owner_is_tcb = id.uid == 0 || id.uid == brops_admin_uid;
    let group_or_other_writable = (id.mode & GROUP_OTHER_WRITE_BITS) != 0;
    is_regular && owner_is_tcb && !group_or_other_writable
}

/// A store input as it was measured at ONE instant: which inode it is, and what bytes it held.
///
/// The launcher captures one set at digest time (the PIN) and a second set immediately before `fexecve`
/// (the RECHECK); [`verify_store_inputs_unchanged`] requires them to be identical.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoreInputSnapshot {
    pub fd: i32,
    pub identity: InodeIdentity,
    /// SHA-256 (lowercase hex) of the bytes read positionally from offset 0.
    pub digest: String,
}

/// Observed facts about a single open descriptor (what the launcher learns via `fstat`/`fcntl`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FdFacts {
    pub fd: i32,
    /// The `fstat`-reported identity of the inode behind this descriptor. `None` means the launcher did
    /// NOT capture one — for a store input (3/4/5) that is fatal (audit IDX-3: an uncaptured identity is
    /// an unpinned inode), so the verifier refuses rather than treating "unknown" as "fine".
    pub identity: Option<InodeIdentity>,
    /// True iff this is one of the approved inert endpoints (for 0/1/2).
    pub is_inert_endpoint: bool,
    pub is_interactive_or_inherited: bool,
    pub read_only: bool,
    pub is_regular_store_inode: bool,
    pub offset_zero: bool,
    pub is_output_pipe: bool,
    /// True iff this descriptor was opened `O_WRONLY` — required for the fd-6 output pipe (§2.7: fd 6 is
    /// the WRITE-ONLY output pipe). Set from `fdinfo` accmode (== 1), NOT from the `pipe:` link prefix alone.
    pub write_only: bool,
    /// True iff `FD_CLOEXEC` is set — for data FDs 3–6 that is fatal (they must survive exec).
    pub cloexec: bool,
}

/// Why the launcher refuses (rev-30 §2.7: every failure ⇒ refuse before signing any receipt).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FdViolation {
    /// A descriptor outside the exact set {0,1,2,3,4,5,6} is present.
    UnexpectedFd(i32),
    /// A required descriptor 0..=6 is missing.
    MissingFd(i32),
    /// 0/1/2 is not the approved inert endpoint (interactive/inherited/unexpected stdio).
    BadStdio(i32),
    /// 3/4/5 is not a read-only regular offset-0 store input.
    BadStoreInput(i32),
    /// 6 is not the write-only output pipe.
    BadOutput,
    /// A data FD 3–6 arrived `FD_CLOEXEC` and would close at exec.
    DataFdCloexec(i32),
    /// IDX-3: a store input (3/4/5) reached the verifier with NO captured inode identity — its content
    /// digest would be a snapshot of an object nothing names. Fail closed.
    StoreInputUnpinnedInode(i32),
    /// IDX-3: a store input's inode is not a regular file, is owned outside the TCB, or is group/other
    /// writable — i.e. a principal outside the TCB can rewrite it under the executor.
    StoreInputCustody(i32),
    /// IDX-3: between the digest-time pin and the pre-`fexecve` recheck the descriptor stopped naming the
    /// same inode (dev/ino/uid/gid/mode/size changed).
    StoreInputInodeChanged(i32),
    /// IDX-3: the inode is the same, but its BYTES changed between the pin and the pre-`fexecve` recheck —
    /// an in-place rewrite of a broker-visible store input.
    StoreInputContentChanged(i32),
}

/// The exact expected role of each descriptor in the executor table.
pub fn expected_role(fd: i32) -> Option<FdRole> {
    match fd {
        0 | 1 | 2 => Some(FdRole::Inert),
        3 | 4 | 5 => Some(FdRole::StoreInput),
        6 => Some(FdRole::OutputPipe),
        _ => None,
    }
}

/// Verify the launcher's observed descriptor table against the rev-30 §2.7 contract, before `fexecve`.
/// `observed` is the full set the launcher sees (e.g. enumerated from `/proc/self/fd`). Fail-closed on the
/// FIRST violation. Ok(()) means exactly {0..=6} are present, each in its required shape, with the data FDs
/// 3–6 free of `FD_CLOEXEC` and nothing at fd ≥ 7.
///
/// `brops_admin_uid` is the provisioned TCB principal that — besides `root` — may own a store-input inode
/// (audit IDX-3); it is a parameter rather than a constant so the boundary value stays with the launcher.
pub fn verify_launcher_fd_set(
    observed: &[FdFacts],
    brops_admin_uid: u32,
) -> Result<(), FdViolation> {
    // 1. no unexpected descriptor (rejects fd >= 7 and any stray).
    for f in observed {
        if expected_role(f.fd).is_none() {
            return Err(FdViolation::UnexpectedFd(f.fd));
        }
    }
    // 2. every required descriptor 0..=6 is present and correctly shaped.
    for fd in 0..=6i32 {
        let f = observed
            .iter()
            .find(|f| f.fd == fd)
            .ok_or(FdViolation::MissingFd(fd))?;
        match expected_role(fd).unwrap() {
            FdRole::Inert => {
                if !f.is_inert_endpoint || f.is_interactive_or_inherited {
                    return Err(FdViolation::BadStdio(fd));
                }
            }
            FdRole::StoreInput => {
                if !(f.read_only && f.is_regular_store_inode && f.offset_zero) {
                    return Err(FdViolation::BadStoreInput(fd));
                }
                // IDX-3: the descriptor must NAME an inode the launcher measured, and that inode must be
                // one only the TCB can write. Without this a store input is a content snapshot of an
                // object that anyone in its directory's group could still be rewriting.
                let id = f
                    .identity
                    .as_ref()
                    .ok_or(FdViolation::StoreInputUnpinnedInode(fd))?;
                if !store_inode_custody_ok(id, brops_admin_uid) {
                    return Err(FdViolation::StoreInputCustody(fd));
                }
                if f.cloexec {
                    return Err(FdViolation::DataFdCloexec(fd));
                }
            }
            FdRole::OutputPipe => {
                // §2.7: fd 6 must be the WRITE-ONLY output pipe — require both the pipe shape AND O_WRONLY
                // (mirrors how StoreInput requires read_only). A read/write or read-only pipe is refused.
                if !(f.is_output_pipe && f.write_only) {
                    return Err(FdViolation::BadOutput);
                }
                if f.cloexec {
                    return Err(FdViolation::DataFdCloexec(fd));
                }
            }
        }
    }
    Ok(())
}

/// Audit **IDX-3** — the pre-`fexecve` recheck: require that every store input still names the SAME inode
/// holding the SAME bytes it did when the launcher digested it against the lease pins.
///
/// `pinned` is the measurement taken at digest time; `recheck` the one taken immediately before the exec,
/// after the privilege drop, the `/proc` reads and the image hash. Fail-closed on the first divergence, and
/// on a slot that vanished from the recheck (never on "I could not measure it again").
///
/// What this DOES close: inode substitution — the descriptor is bound to `dev`+`ino`, so a replaced file,
/// a re-created name, or a same-inode-number object on another device is a refusal rather than an
/// undetected swap.
///
/// What this NARROWS but does not close on its own: an in-place rewrite by a principal that can write the
/// inode. The recheck moves the exposed interval from "digest → drop → /proc → image hash → exec" down to
/// "recheck → fexecve → the executor's own read", and that last part cannot be squeezed to zero from
/// inside the launcher, because the executor reads the bytes AFTER the launcher is gone. The rewrite
/// window is closed by the custody floor in [`store_inode_custody_ok`] instead: an inode no principal
/// outside the TCB may write cannot be rewritten in that interval by anyone the model treats as hostile.
pub fn verify_store_inputs_unchanged(
    pinned: &[StoreInputSnapshot],
    recheck: &[StoreInputSnapshot],
) -> Result<(), FdViolation> {
    for p in pinned {
        let r = recheck
            .iter()
            .find(|r| r.fd == p.fd)
            .ok_or(FdViolation::MissingFd(p.fd))?;
        if r.identity != p.identity {
            return Err(FdViolation::StoreInputInodeChanged(p.fd));
        }
        if r.digest != p.digest {
            return Err(FdViolation::StoreInputContentChanged(p.fd));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A TCB-owned, non-writable regular store inode (mode 0644, uid root).
    fn ident(ino: u64) -> InodeIdentity {
        InodeIdentity { dev: 66, ino, uid: 0, gid: 0, mode: 0o100644, size: 33 }
    }
    const ADMIN: u32 = 500;

    fn snap(fd: i32, ino: u64, digest: &str) -> StoreInputSnapshot {
        StoreInputSnapshot { fd, identity: ident(ino), digest: digest.to_string() }
    }

    fn inert(fd: i32) -> FdFacts {
        FdFacts { fd, identity: None, is_inert_endpoint: true, is_interactive_or_inherited: false, read_only: false,
            is_regular_store_inode: false, offset_zero: false, is_output_pipe: false, write_only: false, cloexec: false }
    }
    fn store(fd: i32) -> FdFacts {
        FdFacts { fd, identity: Some(ident(1000 + fd as u64)), is_inert_endpoint: false, is_interactive_or_inherited: false, read_only: true,
            is_regular_store_inode: true, offset_zero: true, is_output_pipe: false, write_only: false, cloexec: false }
    }
    fn output() -> FdFacts {
        FdFacts { fd: 6, identity: None, is_inert_endpoint: false, is_interactive_or_inherited: false, read_only: false,
            is_regular_store_inode: false, offset_zero: false, is_output_pipe: true, write_only: true, cloexec: false }
    }
    fn good() -> Vec<FdFacts> {
        vec![inert(0), inert(1), inert(2), store(3), store(4), store(5), output()]
    }

    #[test]
    fn accepts_the_exact_contract_set() {
        assert!(verify_launcher_fd_set(&good(), ADMIN).is_ok());
    }

    #[test]
    fn rejects_a_descriptor_at_or_above_7() {
        let mut s = good();
        s.push(store(7));
        assert_eq!(verify_launcher_fd_set(&s, ADMIN), Err(FdViolation::UnexpectedFd(7)));
    }

    #[test]
    fn rejects_a_missing_data_fd() {
        let s: Vec<_> = good().into_iter().filter(|f| f.fd != 4).collect();
        assert_eq!(verify_launcher_fd_set(&s, ADMIN), Err(FdViolation::MissingFd(4)));
    }

    #[test]
    fn rejects_interactive_or_non_inert_stdio() {
        let mut s = good();
        s[1].is_interactive_or_inherited = true; // fd 1 inherited a tty
        assert_eq!(verify_launcher_fd_set(&s, ADMIN), Err(FdViolation::BadStdio(1)));
        let mut s2 = good();
        s2[0].is_inert_endpoint = false;
        assert_eq!(verify_launcher_fd_set(&s2, ADMIN), Err(FdViolation::BadStdio(0)));
    }

    #[test]
    fn rejects_cloexec_on_a_data_fd() {
        let mut s = good();
        s[3].cloexec = true; // fd 3 would close at fexecve
        assert_eq!(verify_launcher_fd_set(&s, ADMIN), Err(FdViolation::DataFdCloexec(3)));
        let mut s6 = good();
        s6[6].cloexec = true;
        assert_eq!(verify_launcher_fd_set(&s6, ADMIN), Err(FdViolation::DataFdCloexec(6)));
    }

    #[test]
    fn rejects_a_writable_or_non_store_input() {
        let mut s = good();
        s[3].read_only = false;
        assert_eq!(verify_launcher_fd_set(&s, ADMIN), Err(FdViolation::BadStoreInput(3)));
        let mut s2 = good();
        s2[5].offset_zero = false;
        assert_eq!(verify_launcher_fd_set(&s2, ADMIN), Err(FdViolation::BadStoreInput(5)));
    }

    #[test]
    fn rejects_a_bad_output_pipe() {
        let mut s = good();
        s[6].is_output_pipe = false;
        assert_eq!(verify_launcher_fd_set(&s, ADMIN), Err(FdViolation::BadOutput));
    }

    #[test]
    fn rejects_a_non_write_only_output_pipe() {
        // §2.7: fd 6 must be O_WRONLY. A pipe that is read/write or read-only (write_only=false) is refused
        // even though its link target is a pipe (Finding 3: accmode must be enforced, not just the shape).
        let mut s = good();
        s[6].write_only = false;
        assert_eq!(verify_launcher_fd_set(&s, ADMIN), Err(FdViolation::BadOutput));
    }

    // ---- IDX-3: the store-input pin must name an INODE, not just bytes -----------------------------

    #[test]
    fn a_store_input_with_no_captured_inode_identity_is_refused() {
        // The defect IDX-3 names: the digest is a snapshot of an object nothing pins. "I did not measure
        // the inode" must be a refusal, never an accepted unknown.
        for fd in 3..=5usize {
            let mut s = good();
            s[fd].identity = None;
            assert_eq!(
                verify_launcher_fd_set(&s, ADMIN),
                Err(FdViolation::StoreInputUnpinnedInode(fd as i32)),
                "fd {fd}"
            );
        }
    }

    #[test]
    fn a_store_input_a_non_tcb_principal_could_rewrite_is_refused() {
        // This is the check that closes the rewrite window rather than narrowing it. Each case is one
        // way a principal outside the TCB gets write access to the inode the executor will read.
        let mut owned_elsewhere = good();
        owned_elsewhere[3].identity = Some(InodeIdentity { uid: 5007, ..ident(1003) });
        assert_eq!(
            verify_launcher_fd_set(&owned_elsewhere, ADMIN),
            Err(FdViolation::StoreInputCustody(3))
        );

        let mut group_writable = good();
        group_writable[4].identity = Some(InodeIdentity { mode: 0o100664, ..ident(1004) });
        assert_eq!(
            verify_launcher_fd_set(&group_writable, ADMIN),
            Err(FdViolation::StoreInputCustody(4))
        );

        let mut other_writable = good();
        other_writable[5].identity = Some(InodeIdentity { mode: 0o100646, ..ident(1005) });
        assert_eq!(
            verify_launcher_fd_set(&other_writable, ADMIN),
            Err(FdViolation::StoreInputCustody(5))
        );

        // A non-regular inode (fifo) reaching the StoreInput branch: refused on custody too — the bytes
        // behind it are not a stable object at all.
        let mut fifo = good();
        fifo[3].identity = Some(InodeIdentity { mode: 0o010644, ..ident(1003) });
        assert_eq!(
            verify_launcher_fd_set(&fifo, ADMIN),
            Err(FdViolation::StoreInputCustody(3))
        );

        // The provisioned brops-admin principal is the ONE non-root owner the floor accepts.
        let mut admin_owned = good();
        admin_owned[3].identity = Some(InodeIdentity { uid: ADMIN, ..ident(1003) });
        assert!(verify_launcher_fd_set(&admin_owned, ADMIN).is_ok());
    }

    #[test]
    fn identical_pin_and_recheck_snapshots_pass() {
        let pinned = vec![snap(3, 11, "aa"), snap(4, 12, "bb"), snap(5, 13, "cc")];
        assert_eq!(verify_store_inputs_unchanged(&pinned, &pinned.clone()), Ok(()));
    }

    #[test]
    fn an_inode_that_was_swapped_between_the_pin_and_the_exec_is_refused() {
        // The exact IDX-3 window: the fd still yields readable bytes, but it is no longer the object the
        // launcher measured. One field at a time, because a comparison that only looked at `ino` (or only
        // at the digest) would pass most of these.
        let pinned = vec![snap(3, 11, "aa"), snap(4, 12, "bb"), snap(5, 13, "cc")];
        let mutate: [(&str, fn(&mut InodeIdentity)); 5] = [
            ("dev", |i| i.dev += 1),
            ("ino", |i| i.ino += 1),
            ("uid", |i| i.uid = 5007),
            ("gid", |i| i.gid = 5007),
            ("mode", |i| i.mode = 0o100664),
        ];
        for (name, f) in mutate {
            let mut recheck = pinned.clone();
            f(&mut recheck[1].identity);
            assert_eq!(
                verify_store_inputs_unchanged(&pinned, &recheck),
                Err(FdViolation::StoreInputInodeChanged(4)),
                "{name}"
            );
        }
        // A truncate/extend shows up as a size change even before the bytes are compared.
        let mut resized = pinned.clone();
        resized[2].identity.size = 0;
        assert_eq!(
            verify_store_inputs_unchanged(&pinned, &resized),
            Err(FdViolation::StoreInputInodeChanged(5))
        );
    }

    #[test]
    fn bytes_rewritten_in_place_between_the_pin_and_the_exec_are_refused() {
        // Same inode, same size, different content — an in-place rewrite during the window. Every slot,
        // because a check that only re-read fd 3 would let the other two through.
        let pinned = vec![snap(3, 11, "aa"), snap(4, 12, "bb"), snap(5, 13, "cc")];
        for slot in 0..3usize {
            let mut recheck = pinned.clone();
            recheck[slot].digest = "ff".to_string();
            assert_eq!(
                verify_store_inputs_unchanged(&pinned, &recheck),
                Err(FdViolation::StoreInputContentChanged(recheck[slot].fd))
            );
        }
    }

    #[test]
    fn a_slot_absent_from_the_recheck_is_refused_not_skipped() {
        let pinned = vec![snap(3, 11, "aa"), snap(4, 12, "bb"), snap(5, 13, "cc")];
        let recheck: Vec<_> = pinned.iter().filter(|s| s.fd != 4).cloned().collect();
        assert_eq!(
            verify_store_inputs_unchanged(&pinned, &recheck),
            Err(FdViolation::MissingFd(4))
        );
    }
}
