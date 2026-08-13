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

impl Step {
    /// The syscall (or gate) this step names — used in refusal messages and journal diffs.
    pub fn name(self) -> &'static str {
        match self {
            Step::VerifyEntry => "verify-entry",
            Step::CgroupSetup => "cgroup-setup",
            Step::SetGroupsEmpty => "setgroups([])",
            Step::SetResGidExec => "setresgid",
            Step::DropBoundingAmbientCaps => "PR_CAPBSET_DROP + PR_CAP_AMBIENT_CLEAR_ALL",
            Step::SetResUidExec => "setresuid",
            Step::ClearAllCapSets => "capset",
            Step::VerifyUnprivileged => "verify-unprivileged",
            Step::SetNoNewPrivs => "PR_SET_NO_NEW_PRIVS",
            Step::Fexecve => "fexecve",
        }
    }
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
    /// The same step appears twice in a RECORDED trace. A journal is a record of what happened;
    /// a step that happened twice means the trace is not a faithful record of the drop.
    DuplicateStep(&'static str),
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

// ---------------------------------------------------------------------------------------------------
// Recorded drop — the sequence the process ACTUALLY performed
// ---------------------------------------------------------------------------------------------------
//
// AUDIT (this file, and launcher/src/main.rs step 3): the launcher used to call
// `verify_order(CANONICAL_SEQUENCE)` — it fed the checker the very constant the checker is written
// against, so the call could not fail — and then ran the real syscalls in a hand-written
// `drop_privileges` that RECORDED NOTHING. Every `Step::` outside this module lived in `#[cfg(test)]`.
// Reordering or deleting a real syscall changed no checked value and failed no test, while the comment
// beside the drop said "Order matches CANONICAL_SEQUENCE (verified in step 3)".
//
// The fix has two halves, both here so they are host-independent and testable on any OS:
//
//   * [`DropJournal`] — an append-only record of the steps that COMPLETED, and
//   * [`perform_drop`] — the single driver that issues the drop through the [`DropSyscalls`] seam and
//     appends each step ONLY after that syscall reported success.
//
// The launcher supplies the real Linux syscalls behind the seam and verifies the JOURNAL. There is now
// exactly one call site per syscall, inside a function whose order is the thing under test, so a
// reorder or a deletion changes the recorded trace — which is what [`verify_performed_drop`] reads.

/// An append-only record of the drop steps this process actually completed.
///
/// Append-only on purpose: there is no way to remove, reorder or rewrite an entry, so the journal
/// handed to [`verify_performed_drop`] is the order things happened in, not an order someone declared.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DropJournal {
    steps: Vec<Step>,
}

impl DropJournal {
    pub fn new() -> Self {
        Self { steps: Vec::new() }
    }

    /// Record a step that has JUST completed. Call sites must appear immediately after the operation
    /// they name — recording ahead of the work turns this back into a declaration.
    pub fn record(&mut self, step: Step) {
        self.steps.push(step);
    }

    pub fn steps(&self) -> &[Step] {
        &self.steps
    }

    pub fn is_empty(&self) -> bool {
        self.steps.is_empty()
    }
}

/// The privilege-drop syscalls, as a seam. Each method performs exactly ONE operation and reports
/// whether it succeeded; it must never perform another step's work, because [`perform_drop`] records a
/// step the moment the corresponding method returns `true`.
///
/// The Linux launcher implements this with the real `setgroups`/`setresgid`/`prctl`/`setresuid`/`capset`
/// syscalls; tests implement it with a recorder, which is what makes the ORDER testable on any host.
pub trait DropSyscalls {
    /// `setgroups(0, NULL)` — clear every supplementary group.
    fn set_groups_empty(&mut self) -> bool;
    /// `setresgid(gid, gid, gid)`.
    fn set_res_gid(&mut self, gid: u32) -> bool;
    /// `PR_CAPBSET_DROP` across the bounding set + `PR_CAP_AMBIENT_CLEAR_ALL`. Needs root/`CAP_SETPCAP`.
    fn drop_bounding_and_ambient_caps(&mut self) -> bool;
    /// `setresuid(uid, uid, uid)` — after this the process can no longer change groups/GID or caps.
    fn set_res_uid(&mut self, uid: u32) -> bool;
    /// `capset` with all-zero effective/permitted/inheritable.
    fn clear_all_cap_sets(&mut self) -> bool;
    /// `prctl(PR_SET_NO_NEW_PRIVS, 1)`.
    fn set_no_new_privs(&mut self) -> bool;
}

/// Perform the locked drop through `sys`, appending each step to `journal` as it COMPLETES.
///
/// The order below IS the contract. It is not compared against a constant afterwards — the constant
/// cannot observe what happened — it is executed, recorded, and the recording is what
/// [`verify_performed_drop`] judges. Move one of these calls and the journal changes.
///
/// On the first failing syscall this returns `Err(step)` with the step that failed, and the journal is
/// left holding exactly the steps that DID complete (so a partial drop is visible, never mistaken for
/// a complete one).
pub fn perform_drop<S: DropSyscalls + ?Sized>(
    sys: &mut S,
    uid: u32,
    gid: u32,
    journal: &mut DropJournal,
) -> Result<(), Step> {
    // Groups and GID first: after the UID drop the process can no longer change either.
    if !sys.set_groups_empty() {
        return Err(Step::SetGroupsEmpty);
    }
    journal.record(Step::SetGroupsEmpty);

    if !sys.set_res_gid(gid) {
        return Err(Step::SetResGidExec);
    }
    journal.record(Step::SetResGidExec);

    // The bounding/ambient sets need CAP_SETPCAP, which is lost with the UID — so, still root here.
    if !sys.drop_bounding_and_ambient_caps() {
        return Err(Step::DropBoundingAmbientCaps);
    }
    journal.record(Step::DropBoundingAmbientCaps);

    if !sys.set_res_uid(uid) {
        return Err(Step::SetResUidExec);
    }
    journal.record(Step::SetResUidExec);

    if !sys.clear_all_cap_sets() {
        return Err(Step::ClearAllCapSets);
    }
    journal.record(Step::ClearAllCapSets);

    // Lock further privilege gain before the post-drop verification reads `no_new_privs`. Stricter
    // than, and compatible with, CANONICAL_SEQUENCE: `no_new_privs` still precedes `fexecve`.
    if !sys.set_no_new_privs() {
        return Err(Step::SetNoNewPrivs);
    }
    journal.record(Step::SetNoNewPrivs);

    Ok(())
}

/// Steps a compliant drop MUST be able to show it actually performed. `CgroupSetup` is deliberately
/// ABSENT: the launcher does not yet place the process into the lease-authorized leaf cgroup (it is an
/// explicit TODO), and this list states what is required of a real trace — not what a wish list says.
/// Adding the cgroup step to the launcher means adding it here, and the journal proves it ran.
pub const MANDATORY_PERFORMED_STEPS: &[Step] = &[
    Step::SetGroupsEmpty,
    Step::SetResGidExec,
    Step::DropBoundingAmbientCaps,
    Step::SetResUidExec,
    Step::ClearAllCapSets,
    Step::SetNoNewPrivs,
    Step::Fexecve,
];

/// Fail-closed verification of a RECORDED drop trace.
///
/// This is the check [`verify_order`] could not be: `verify_order` answers "is this sequence a legal
/// order", which is trivially true of `CANONICAL_SEQUENCE` itself. This answers "did the process
/// perform every mandatory step, once each, in a legal order" — a question only a journal built from
/// completed operations can answer, and one that goes red if a syscall is reordered or removed.
pub fn verify_performed_drop(performed: &[Step]) -> Result<(), OrderViolation> {
    for (i, step) in performed.iter().enumerate() {
        if performed[i + 1..].contains(step) {
            return Err(OrderViolation::DuplicateStep(step.name()));
        }
    }
    for required in MANDATORY_PERFORMED_STEPS {
        if !performed.contains(required) {
            return Err(OrderViolation::MissingStep(required.name()));
        }
    }
    verify_order(performed)
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
    /// The drop TARGET itself is privileged (uid or gid 0). A "drop" to root is a no-op, so the post-state
    /// would still be root yet compare equal to the (root) target and pass every other check. The floor
    /// rejects the target independent of the post-state, so a misprovisioned/compromised lease claiming
    /// `executor_uid=0` can never be waved through as a clean drop. The executor MUST land on a dedicated
    /// unprivileged principal.
    PrivilegedDropTarget,
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
    // The drop TARGET must be an unprivileged principal — uid/gid 0 (root) is never a valid executor
    // identity. Validate the target itself, not merely the post-state against it, so a lease claiming
    // `executor_uid=0`/`executor_gid=0` cannot make `drop_privileges` a no-op that this self-check (the
    // §2.7 post-drop floor) then passes because the still-root post-state equals the (root) target.
    if exec_uid == 0 || exec_gid == 0 {
        return Err(PrivViolation::PrivilegedDropTarget);
    }
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
        // NOTE: this asserts a property of the CONSTANT, and nothing more. It is not — and was never
        // — evidence about the launcher's syscalls. The tests under "recorded drop" below are the ones
        // that judge what the code performs; see `perform_drop`'s module comment.
        assert!(verify_order(CANONICAL_SEQUENCE).is_ok());
    }

    // ---- recorded drop: the sequence the code ACTUALLY performs ---------------------------------

    /// A `DropSyscalls` that records the calls it receives instead of making them, so the ORDER the
    /// driver issues is observable on any host. `fail_at` makes one call report failure.
    #[derive(Default)]
    struct FakeSyscalls {
        calls: Vec<&'static str>,
        fail_at: Option<&'static str>,
        uid_seen: Option<u32>,
        gid_seen: Option<u32>,
    }

    impl FakeSyscalls {
        fn ok(&mut self, name: &'static str) -> bool {
            self.calls.push(name);
            self.fail_at != Some(name)
        }
        fn failing(name: &'static str) -> Self {
            FakeSyscalls { fail_at: Some(name), ..Default::default() }
        }
    }

    impl DropSyscalls for FakeSyscalls {
        fn set_groups_empty(&mut self) -> bool {
            self.ok("setgroups")
        }
        fn set_res_gid(&mut self, gid: u32) -> bool {
            self.gid_seen = Some(gid);
            self.ok("setresgid")
        }
        fn drop_bounding_and_ambient_caps(&mut self) -> bool {
            self.ok("bounding")
        }
        fn set_res_uid(&mut self, uid: u32) -> bool {
            self.uid_seen = Some(uid);
            self.ok("setresuid")
        }
        fn clear_all_cap_sets(&mut self) -> bool {
            self.ok("capset")
        }
        fn set_no_new_privs(&mut self) -> bool {
            self.ok("no_new_privs")
        }
    }

    fn run_drop() -> (FakeSyscalls, DropJournal, Result<(), Step>) {
        let mut sys = FakeSyscalls::default();
        let mut journal = DropJournal::new();
        let r = perform_drop(&mut sys, EXEC_UID, EXEC_GID, &mut journal);
        (sys, journal, r)
    }

    #[test]
    fn the_driver_issues_the_syscalls_in_the_locked_order() {
        let (sys, _journal, r) = run_drop();
        assert_eq!(r, Ok(()));
        // The ORDER of the real operations, asserted directly. Move a call in `perform_drop` and this
        // is the test that goes red.
        assert_eq!(
            sys.calls,
            vec!["setgroups", "setresgid", "bounding", "setresuid", "capset", "no_new_privs"]
        );
        assert_eq!(sys.uid_seen, Some(EXEC_UID));
        assert_eq!(sys.gid_seen, Some(EXEC_GID));
    }

    #[test]
    fn the_journal_records_exactly_what_was_performed() {
        let (_sys, journal, _r) = run_drop();
        assert_eq!(
            journal.steps(),
            &[
                Step::SetGroupsEmpty,
                Step::SetResGidExec,
                Step::DropBoundingAmbientCaps,
                Step::SetResUidExec,
                Step::ClearAllCapSets,
                Step::SetNoNewPrivs,
            ]
        );
    }

    #[test]
    fn a_completed_drop_plus_the_surrounding_gates_verifies() {
        // What the launcher hands to `verify_performed_drop`: entry gate, the recorded syscalls, the
        // post-drop verification, then `fexecve` recorded immediately before it is issued.
        let (_sys, mut journal, r) = run_drop();
        assert_eq!(r, Ok(()));
        let mut full = DropJournal::new();
        full.record(Step::VerifyEntry);
        for s in journal.steps() {
            full.record(*s);
        }
        full.record(Step::VerifyUnprivileged);
        full.record(Step::Fexecve);
        assert_eq!(verify_performed_drop(full.steps()), Ok(()));
        journal.record(Step::Fexecve); // (journal is append-only; nothing can rewrite the trace)
    }

    #[test]
    fn a_failed_syscall_stops_the_drop_and_leaves_a_partial_journal() {
        // The step that failed is named, the journal shows only what completed, and that partial trace
        // must NOT verify — a half-dropped process is not a dropped process.
        let mut sys = FakeSyscalls::failing("setresuid");
        let mut journal = DropJournal::new();
        assert_eq!(
            perform_drop(&mut sys, EXEC_UID, EXEC_GID, &mut journal),
            Err(Step::SetResUidExec)
        );
        assert_eq!(
            journal.steps(),
            &[Step::SetGroupsEmpty, Step::SetResGidExec, Step::DropBoundingAmbientCaps]
        );
        assert_eq!(
            verify_performed_drop(journal.steps()),
            Err(OrderViolation::MissingStep("setresuid"))
        );
    }

    #[test]
    fn a_failure_in_the_very_first_syscall_records_nothing() {
        let mut sys = FakeSyscalls::failing("setgroups");
        let mut journal = DropJournal::new();
        assert_eq!(
            perform_drop(&mut sys, EXEC_UID, EXEC_GID, &mut journal),
            Err(Step::SetGroupsEmpty)
        );
        assert!(journal.is_empty());
        assert!(verify_performed_drop(journal.steps()).is_err());
    }

    #[test]
    fn a_recorded_trace_missing_any_mandatory_step_is_refused() {
        // Deleting a syscall from the drop deletes its journal entry — this is what that looks like.
        let full = vec![
            Step::VerifyEntry,
            Step::SetGroupsEmpty,
            Step::SetResGidExec,
            Step::DropBoundingAmbientCaps,
            Step::SetResUidExec,
            Step::ClearAllCapSets,
            Step::VerifyUnprivileged,
            Step::SetNoNewPrivs,
            Step::Fexecve,
        ];
        assert_eq!(verify_performed_drop(&full), Ok(()));
        for dropped in MANDATORY_PERFORMED_STEPS {
            let thinned: Vec<Step> = full.iter().copied().filter(|s| s != dropped).collect();
            assert_eq!(
                verify_performed_drop(&thinned),
                Err(OrderViolation::MissingStep(dropped.name())),
                "removing {} must be refused",
                dropped.name()
            );
        }
        // `capset` is required HERE but not by `verify_order` — the exact gap a constant-fed check
        // could never expose, since the constant always contains it.
        let no_capset: Vec<Step> =
            full.iter().copied().filter(|s| *s != Step::ClearAllCapSets).collect();
        assert!(verify_order(&no_capset).is_ok());
        assert!(verify_performed_drop(&no_capset).is_err());
    }

    #[test]
    fn a_recorded_trace_in_the_wrong_order_is_refused() {
        // Reordering a syscall in the drop reorders its journal entry — this is what that looks like.
        let uid_first = vec![
            Step::VerifyEntry,
            Step::SetResUidExec, // moved ahead of groups/gid
            Step::SetGroupsEmpty,
            Step::SetResGidExec,
            Step::DropBoundingAmbientCaps,
            Step::ClearAllCapSets,
            Step::VerifyUnprivileged,
            Step::SetNoNewPrivs,
            Step::Fexecve,
        ];
        assert_eq!(
            verify_performed_drop(&uid_first),
            Err(OrderViolation::UidDroppedBeforeGidOrGroups)
        );

        let late_bounding = vec![
            Step::VerifyEntry,
            Step::SetGroupsEmpty,
            Step::SetResGidExec,
            Step::SetResUidExec,
            Step::DropBoundingAmbientCaps, // no longer root: cannot succeed
            Step::ClearAllCapSets,
            Step::VerifyUnprivileged,
            Step::SetNoNewPrivs,
            Step::Fexecve,
        ];
        assert_eq!(
            verify_performed_drop(&late_bounding),
            Err(OrderViolation::BoundingDroppedAfterUidDrop)
        );

        let nnp_after_exec = vec![
            Step::VerifyEntry,
            Step::SetGroupsEmpty,
            Step::SetResGidExec,
            Step::DropBoundingAmbientCaps,
            Step::SetResUidExec,
            Step::ClearAllCapSets,
            Step::VerifyUnprivileged,
            Step::Fexecve,
            Step::SetNoNewPrivs,
        ];
        assert_eq!(
            verify_performed_drop(&nnp_after_exec),
            Err(OrderViolation::ExecNotLastOrNoNewPrivsMissing)
        );
    }

    #[test]
    fn a_replayed_step_is_not_a_record() {
        let doubled = vec![
            Step::VerifyEntry,
            Step::SetGroupsEmpty,
            Step::SetGroupsEmpty, // recorded twice
            Step::SetResGidExec,
            Step::DropBoundingAmbientCaps,
            Step::SetResUidExec,
            Step::ClearAllCapSets,
            Step::VerifyUnprivileged,
            Step::SetNoNewPrivs,
            Step::Fexecve,
        ];
        assert_eq!(
            verify_performed_drop(&doubled),
            Err(OrderViolation::DuplicateStep("setgroups([])"))
        );
    }

    #[test]
    fn an_empty_journal_never_passes() {
        // The state the launcher was in before this fix: nothing recorded at all.
        assert!(verify_performed_drop(&[]).is_err());
        assert!(verify_performed_drop(DropJournal::new().steps()).is_err());
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
    fn rejects_a_privileged_drop_target() {
        // A lease claiming executor_uid/gid=0 makes drop_privileges a no-op (already root); the floor must
        // reject the TARGET itself independent of the post-state — otherwise a still-root post-state would
        // compare equal to the (root) target and pass. uid 0 OR gid 0 is refused.
        let mut root = dropped();
        root.ruid = 0; root.euid = 0; root.suid = 0; root.rgid = 0; root.egid = 0; root.sgid = 0;
        assert_eq!(verify_final_state(&root, 0, 0), Err(PrivViolation::PrivilegedDropTarget));
        assert_eq!(verify_final_state(&dropped(), 0, EXEC_GID), Err(PrivViolation::PrivilegedDropTarget));
        assert_eq!(verify_final_state(&dropped(), EXEC_UID, 0), Err(PrivViolation::PrivilegedDropTarget));
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
