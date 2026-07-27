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

/// Observed facts about a single open descriptor (what the launcher learns via `fstat`/`fcntl`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FdFacts {
    pub fd: i32,
    /// True iff this is one of the approved inert endpoints (for 0/1/2).
    pub is_inert_endpoint: bool,
    pub is_interactive_or_inherited: bool,
    pub read_only: bool,
    pub is_regular_store_inode: bool,
    pub offset_zero: bool,
    pub is_output_pipe: bool,
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
pub fn verify_launcher_fd_set(observed: &[FdFacts]) -> Result<(), FdViolation> {
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
                if f.cloexec {
                    return Err(FdViolation::DataFdCloexec(fd));
                }
            }
            FdRole::OutputPipe => {
                if !f.is_output_pipe {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn inert(fd: i32) -> FdFacts {
        FdFacts { fd, is_inert_endpoint: true, is_interactive_or_inherited: false, read_only: false,
            is_regular_store_inode: false, offset_zero: false, is_output_pipe: false, cloexec: false }
    }
    fn store(fd: i32) -> FdFacts {
        FdFacts { fd, is_inert_endpoint: false, is_interactive_or_inherited: false, read_only: true,
            is_regular_store_inode: true, offset_zero: true, is_output_pipe: false, cloexec: false }
    }
    fn output() -> FdFacts {
        FdFacts { fd: 6, is_inert_endpoint: false, is_interactive_or_inherited: false, read_only: false,
            is_regular_store_inode: false, offset_zero: false, is_output_pipe: true, cloexec: false }
    }
    fn good() -> Vec<FdFacts> {
        vec![inert(0), inert(1), inert(2), store(3), store(4), store(5), output()]
    }

    #[test]
    fn accepts_the_exact_contract_set() {
        assert!(verify_launcher_fd_set(&good()).is_ok());
    }

    #[test]
    fn rejects_a_descriptor_at_or_above_7() {
        let mut s = good();
        s.push(store(7));
        assert_eq!(verify_launcher_fd_set(&s), Err(FdViolation::UnexpectedFd(7)));
    }

    #[test]
    fn rejects_a_missing_data_fd() {
        let s: Vec<_> = good().into_iter().filter(|f| f.fd != 4).collect();
        assert_eq!(verify_launcher_fd_set(&s), Err(FdViolation::MissingFd(4)));
    }

    #[test]
    fn rejects_interactive_or_non_inert_stdio() {
        let mut s = good();
        s[1].is_interactive_or_inherited = true; // fd 1 inherited a tty
        assert_eq!(verify_launcher_fd_set(&s), Err(FdViolation::BadStdio(1)));
        let mut s2 = good();
        s2[0].is_inert_endpoint = false;
        assert_eq!(verify_launcher_fd_set(&s2), Err(FdViolation::BadStdio(0)));
    }

    #[test]
    fn rejects_cloexec_on_a_data_fd() {
        let mut s = good();
        s[3].cloexec = true; // fd 3 would close at fexecve
        assert_eq!(verify_launcher_fd_set(&s), Err(FdViolation::DataFdCloexec(3)));
        let mut s6 = good();
        s6[6].cloexec = true;
        assert_eq!(verify_launcher_fd_set(&s6), Err(FdViolation::DataFdCloexec(6)));
    }

    #[test]
    fn rejects_a_writable_or_non_store_input() {
        let mut s = good();
        s[3].read_only = false;
        assert_eq!(verify_launcher_fd_set(&s), Err(FdViolation::BadStoreInput(3)));
        let mut s2 = good();
        s2[5].offset_zero = false;
        assert_eq!(verify_launcher_fd_set(&s2), Err(FdViolation::BadStoreInput(5)));
    }

    #[test]
    fn rejects_a_bad_output_pipe() {
        let mut s = good();
        s[6].is_output_pipe = false;
        assert_eq!(verify_launcher_fd_set(&s), Err(FdViolation::BadOutput));
    }
}
