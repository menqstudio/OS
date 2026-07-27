//! Wave 3b-1B — privileged-launcher privilege-drop contract (implements the design-GREEN rev-30 §2.7 P0-2:
//! the Model-A setuid launcher's LOCKED privilege-drop syscall sequence and its fail-closed final-state
//! verification).
//!
//! The syscalls (`setgroups`/`setresgid`/`prctl`/`setresuid`/`capset`/`fexecve`) are Linux (a later
//! launcher-crate slice). This module is the PURE, host-independent contract: (a) the canonical ordered
//! sequence + an order validator (GID/groups MUST change before the UID drop; the bounding set MUST be
//! dropped while still UID-root), and (b) a final-state verifier that fails closed unless the process ends
//! as the executor UID/GID with empty supplementary groups, ALL FIVE capability sets empty, and
//! `no_new_privs` set. Both are unit-testable on any host.

/// One step of the locked drop sequence (rev-30 §2.7, order is load-bearing).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Step {
    VerifyEntry,
    CgroupSetup,
    SetGroupsEmpty,
    SetResGidExec,
    DropBoundingAmbientCaps,
    SetResUidExec,
    ClearAllCapSets,
    VerifyUnprivileged,
    SetNoNewPrivs,
    Fexecve,
}

/// The one canonical, correct sequence (rev-30 §2.7 steps 1–11 collapsed to the security-relevant order).
pub const CANONICAL_SEQUENCE: &[Step] = &[
    Step::VerifyEntry,
    Step::CgroupSetup,
    Step::SetGroupsEmpty,
    Step::SetResGidExec,
    Step::DropBoundingAmbientCaps,
    Step::SetResUidExec,
    Step::ClearAllCapSets,
    Step::VerifyUnprivileged,
    Step::SetNoNewPrivs,
    Step::Fexecve,
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OrderViolation {
    /// The UID was dropped before groups were cleared / GID was set (after the UID drop the process can no
    /// longer change its groups/GID).
    UidDroppedBeforeGidOrGroups,
    /// The capability bounding/ambient set was dropped after the UID drop (it needs root/`CAP_SETPCAP`).
    BoundingDroppedAfterUidDrop,
    /// `fexecve` did not occur strictly last, or `no_new_privs` was not set before it.
    ExecNotLastOrNoNewPrivsMissing,
    /// A required step is missing.
    MissingStep(&'static str),
}

fn pos(seq: &[Step], s: Step) -> Option<usize> {
    seq.iter().position(|x| *x == s)
}

/// Validate that `seq` preserves the load-bearing ordering invariants of the drop (rev-30 §2.7). Does not
/// require byte-identity with [`CANONICAL_SEQUENCE`] — only the security-relevant partial order.
pub fn verify_order(seq: &[Step]) -> Result<(), OrderViolation> {
    let need = |s: Step, name| pos(seq, s).ok_or(OrderViolation::MissingStep(name));
    let groups = need(Step::SetGroupsEmpty, "setgroups([])")?;
    let gid = need(Step::SetResGidExec, "setresgid")?;
    let bounding = need(Step::DropBoundingAmbientCaps, "drop bounding caps")?;
    let uid = need(Step::SetResUidExec, "setresuid")?;
    let nnp = need(Step::SetNoNewPrivs, "PR_SET_NO_NEW_PRIVS")?;
    let exec = need(Step::Fexecve, "fexecve")?;

    if !(groups < uid && gid < uid) {
        return Err(OrderViolation::UidDroppedBeforeGidOrGroups);
    }
    if !(bounding < uid) {
        return Err(OrderViolation::BoundingDroppedAfterUidDrop);
    }
    if !(nnp < exec && exec == seq.len() - 1) {
        return Err(OrderViolation::ExecNotLastOrNoNewPrivsMissing);
    }
    Ok(())
}

/// The five Linux capability sets — all MUST be empty in the executor.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CapSets {
    pub effective: u64,
    pub permitted: u64,
    pub inheritable: u64,
    pub bounding: u64,
    pub ambient: u64,
}

impl CapSets {
    pub fn all_empty(&self) -> bool {
        self.effective == 0
            && self.permitted == 0
            && self.inheritable == 0
            && self.bounding == 0
            && self.ambient == 0
    }
}

/// The observable process state after the drop, right before `fexecve` (what the launcher's fail-closed
/// self-check reads via `getresuid`/`getresgid`/`getgroups`/`capget`/`prctl(PR_GET_NO_NEW_PRIVS)`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FinalState {
    pub ruid: u32,
    pub euid: u32,
    pub suid: u32,
    pub rgid: u32,
    pub egid: u32,
    pub sgid: u32,
    pub supplementary_groups: Vec<u32>,
    pub caps: CapSets,
    pub no_new_privs: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PrivViolation {
    UidNotExecutor,
    GidNotExecutor,
    SupplementaryGroupsNonEmpty,
    ResidualCapabilities,
    NoNewPrivsUnset,
}

/// Fail-closed final-state verification (rev-30 §2.7 step 8): the process MUST have dropped fully to the
/// executor UID/GID (all three of each), cleared every supplementary group, emptied ALL five capability
/// sets, and set `no_new_privs`. Any residual ⇒ abort, no exec.
pub fn verify_final_state(s: &FinalState, exec_uid: u32, exec_gid: u32) -> Result<(), PrivViolation> {
    if !(s.ruid == exec_uid && s.euid == exec_uid && s.suid == exec_uid) {
        return Err(PrivViolation::UidNotExecutor);
    }
    if !(s.rgid == exec_gid && s.egid == exec_gid && s.sgid == exec_gid) {
        return Err(PrivViolation::GidNotExecutor);
    }
    if !s.supplementary_groups.is_empty() {
        return Err(PrivViolation::SupplementaryGroupsNonEmpty);
    }
    if !s.caps.all_empty() {
        return Err(PrivViolation::ResidualCapabilities);
    }
    if !s.no_new_privs {
        return Err(PrivViolation::NoNewPrivsUnset);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const EXEC_UID: u32 = 5007;
    const EXEC_GID: u32 = 5007;

    fn dropped() -> FinalState {
        FinalState {
            ruid: EXEC_UID, euid: EXEC_UID, suid: EXEC_UID,
            rgid: EXEC_GID, egid: EXEC_GID, sgid: EXEC_GID,
            supplementary_groups: vec![],
            caps: CapSets::default(),
            no_new_privs: true,
        }
    }

    #[test]
    fn canonical_sequence_order_is_valid() {
        assert!(verify_order(CANONICAL_SEQUENCE).is_ok());
    }

    #[test]
    fn rejects_uid_dropped_before_groups() {
        let bad = vec![
            Step::VerifyEntry, Step::CgroupSetup, Step::SetResUidExec, // uid too early
            Step::SetGroupsEmpty, Step::SetResGidExec, Step::DropBoundingAmbientCaps,
            Step::ClearAllCapSets, Step::VerifyUnprivileged, Step::SetNoNewPrivs, Step::Fexecve,
        ];
        assert_eq!(verify_order(&bad), Err(OrderViolation::UidDroppedBeforeGidOrGroups));
    }

    #[test]
    fn rejects_bounding_drop_after_uid_drop() {
        let bad = vec![
            Step::VerifyEntry, Step::CgroupSetup, Step::SetGroupsEmpty, Step::SetResGidExec,
            Step::SetResUidExec, Step::DropBoundingAmbientCaps, // bounding too late (no longer root)
            Step::ClearAllCapSets, Step::VerifyUnprivileged, Step::SetNoNewPrivs, Step::Fexecve,
        ];
        assert_eq!(verify_order(&bad), Err(OrderViolation::BoundingDroppedAfterUidDrop));
    }

    #[test]
    fn rejects_missing_no_new_privs() {
        let bad: Vec<_> = CANONICAL_SEQUENCE.iter().copied().filter(|s| *s != Step::SetNoNewPrivs).collect();
        assert_eq!(verify_order(&bad), Err(OrderViolation::MissingStep("PR_SET_NO_NEW_PRIVS")));
    }

    #[test]
    fn accepts_a_fully_dropped_final_state() {
        assert!(verify_final_state(&dropped(), EXEC_UID, EXEC_GID).is_ok());
    }

    #[test]
    fn rejects_residual_uid_gid_groups_caps_nnp() {
        let mut s = dropped(); s.euid = 0;
        assert_eq!(verify_final_state(&s, EXEC_UID, EXEC_GID), Err(PrivViolation::UidNotExecutor));
        let mut s = dropped(); s.sgid = 0;
        assert_eq!(verify_final_state(&s, EXEC_UID, EXEC_GID), Err(PrivViolation::GidNotExecutor));
        let mut s = dropped(); s.supplementary_groups = vec![0];
        assert_eq!(verify_final_state(&s, EXEC_UID, EXEC_GID), Err(PrivViolation::SupplementaryGroupsNonEmpty));
        let mut s = dropped(); s.caps.bounding = 1;
        assert_eq!(verify_final_state(&s, EXEC_UID, EXEC_GID), Err(PrivViolation::ResidualCapabilities));
        let mut s = dropped(); s.caps.effective = 1 << 21; // CAP_SYS_ADMIN-ish residue
        assert_eq!(verify_final_state(&s, EXEC_UID, EXEC_GID), Err(PrivViolation::ResidualCapabilities));
        let mut s = dropped(); s.no_new_privs = false;
        assert_eq!(verify_final_state(&s, EXEC_UID, EXEC_GID), Err(PrivViolation::NoNewPrivsUnset));
    }
}
