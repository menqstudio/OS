//! Wave 3b-1B — Windows (§0.W) production-mode broker equivalent (design-GREEN rev-30 §0.W + §2.7 Windows
//! mapping). PURE, host-independent verification logic (compiles on ANY host; NO winapi dep) modeling the
//! Windows contract that mirrors the Linux trust boundary:
//!
//! - **Restricted executor token** — the executor's token MUST drop every forbidden privilege and run at a
//!   low integrity level, mirroring the Linux dropped-caps + unprivileged executor UID.
//! - **Named-pipe peer auth** — the challenge-authority pipe allowlists ONLY the broker's token SID and
//!   DENIES the renderer/login SID and the sidecar SID (mirrors the Linux `SO_PEERCRED` broker-UID
//!   allowlist, §2.1).
//! - **Image verification** — hash + Authenticode + NTFS ACL non-writable-by-login/runtime SIDs before
//!   `CreateProcessAsUser` (mirrors the Linux TCB integrity floor + `O_NOFOLLOW`/re-hash, §2.5/§2.7).
//! - **STARTUPINFOEX handle list** — the executor inherits EXACTLY the 3–6 data handles (mirrors the Linux
//!   FD 3–6 survival contract, §2.7 P0-3).
//!
//! Every verifier fails closed on the first violation and returns a [`WindowsBrokerViolation`]. Fully
//! unit-tested offline.

use std::collections::BTreeSet;

/// A Windows security identifier (opaque string form, e.g. `S-1-5-...`).
pub type Sid = String;

/// Privileges that MUST NOT be present on the executor's restricted token (a non-exhaustive forbidden set
/// mirroring the Linux forbidden capabilities). Any of these on the token ⇒ violation.
pub const FORBIDDEN_PRIVILEGES: &[&str] = &[
    "SeDebugPrivilege",
    "SeTcbPrivilege",
    "SeLoadDriverPrivilege",
    "SeImpersonatePrivilege",
    "SeAssignPrimaryTokenPrivilege",
    "SeBackupPrivilege",
    "SeRestorePrivilege",
    "SeTakeOwnershipPrivilege",
];

/// Integrity level of a token (only `Low`/`Untrusted` are acceptable for the contained executor).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntegrityLevel {
    Untrusted,
    Low,
    Medium,
    High,
    System,
}

/// The observed executor token (what the broker inspects before `CreateProcessAsUser`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObservedToken {
    /// Privileges present on the token.
    pub privileges: BTreeSet<String>,
    pub integrity: IntegrityLevel,
    /// True iff the token is a restricted token (`CreateRestrictedToken`) with deny-only/restricted SIDs.
    pub is_restricted: bool,
}

/// The observed executable image facts (before launch).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImageFacts {
    pub sha256: String,
    pub authenticode_valid: bool,
    /// Writable by the login user or any runtime service SID via the NTFS ACL.
    pub writable_by_login_or_runtime: bool,
}

/// The pinned expectation for the executor image (from the root-owned pin).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImageVerificationSpec {
    pub expected_sha256: String,
    pub require_authenticode: bool,
}

/// The named-pipe peer-auth policy for the challenge-authority pipe (§2.1 Windows mapping).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NamedPipePeerAuthPolicy {
    /// The ONLY SID allowed to connect (the trusted broker's token SID).
    pub allowed_broker_sid: Sid,
    /// SIDs explicitly denied (the renderer/login SID and the sidecar SID) — belt-and-suspenders alongside
    /// the single-allow rule.
    pub denied_sids: BTreeSet<Sid>,
}

/// A single inherited handle in the STARTUPINFOEX explicit handle list (the Windows FD-3..6 equivalent).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HandleRole {
    Inert,      // stdio-equivalent, inert
    StoreInput, // read-only store input
    OutputPipe, // write-only output pipe
}

/// The expected handle role by slot index 0..=6 (mirrors the Linux FD 0..=6 contract).
pub fn expected_handle_role(slot: i32) -> Option<HandleRole> {
    match slot {
        0 | 1 | 2 => Some(HandleRole::Inert),
        3 | 4 | 5 => Some(HandleRole::StoreInput),
        6 => Some(HandleRole::OutputPipe),
        _ => None,
    }
}

/// A violation of the Windows production-mode broker contract (§0.W). Any value ⇒ governed real-mode
/// DISABLED / launch refused, fail-closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WindowsBrokerViolation {
    ForbiddenPrivilege(String),
    TokenIntegrityTooHigh,
    TokenNotRestricted,
    PeerNotBroker(Sid),
    PeerExplicitlyDenied(Sid),
    ImageHashMismatch,
    ImageAuthenticodeInvalid,
    ImageWritableByUntrusted,
    UnexpectedHandleSlot(i32),
    MissingHandleSlot(i32),
    WrongHandleRole(i32),
}

/// Verify the executor's restricted token: no forbidden privilege, low/untrusted integrity, is-restricted.
pub fn verify_restricted_token(t: &ObservedToken) -> Result<(), WindowsBrokerViolation> {
    for p in FORBIDDEN_PRIVILEGES {
        if t.privileges.contains(*p) {
            return Err(WindowsBrokerViolation::ForbiddenPrivilege((*p).to_string()));
        }
    }
    if !matches!(t.integrity, IntegrityLevel::Low | IntegrityLevel::Untrusted) {
        return Err(WindowsBrokerViolation::TokenIntegrityTooHigh);
    }
    if !t.is_restricted {
        return Err(WindowsBrokerViolation::TokenNotRestricted);
    }
    Ok(())
}

/// Authorize a connecting peer on the challenge-authority pipe: it MUST be exactly the broker SID and MUST
/// NOT be in the denied set (renderer/login + sidecar).
pub fn authorize_authority_peer(
    policy: &NamedPipePeerAuthPolicy,
    peer_sid: &str,
) -> Result<(), WindowsBrokerViolation> {
    if policy.denied_sids.contains(peer_sid) {
        return Err(WindowsBrokerViolation::PeerExplicitlyDenied(peer_sid.to_string()));
    }
    if peer_sid != policy.allowed_broker_sid {
        return Err(WindowsBrokerViolation::PeerNotBroker(peer_sid.to_string()));
    }
    Ok(())
}

/// Verify the executor image before `CreateProcessAsUser`: exact hash, valid Authenticode (if required),
/// and NOT writable by the login user or any runtime SID.
pub fn verify_image(spec: &ImageVerificationSpec, facts: &ImageFacts) -> Result<(), WindowsBrokerViolation> {
    if facts.writable_by_login_or_runtime {
        return Err(WindowsBrokerViolation::ImageWritableByUntrusted);
    }
    if facts.sha256 != spec.expected_sha256 {
        return Err(WindowsBrokerViolation::ImageHashMismatch);
    }
    if spec.require_authenticode && !facts.authenticode_valid {
        return Err(WindowsBrokerViolation::ImageAuthenticodeInvalid);
    }
    Ok(())
}

/// Verify the STARTUPINFOEX explicit handle list: exactly slots {0..=6}, each in its required role, and
/// nothing beyond slot 6 (the Windows equivalent of the FD 3–6 survival + no-extra-FD rule).
pub fn verify_startupinfo_handle_list(
    handles: &[(i32, HandleRole)],
) -> Result<(), WindowsBrokerViolation> {
    for (slot, _) in handles {
        if expected_handle_role(*slot).is_none() {
            return Err(WindowsBrokerViolation::UnexpectedHandleSlot(*slot));
        }
    }
    for slot in 0..=6i32 {
        let found = handles.iter().find(|(s, _)| *s == slot);
        match found {
            None => return Err(WindowsBrokerViolation::MissingHandleSlot(slot)),
            Some((_, role)) => {
                if Some(*role) != expected_handle_role(slot) {
                    return Err(WindowsBrokerViolation::WrongHandleRole(slot));
                }
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ok_token() -> ObservedToken {
        ObservedToken { privileges: BTreeSet::new(), integrity: IntegrityLevel::Low, is_restricted: true }
    }
    fn policy() -> NamedPipePeerAuthPolicy {
        NamedPipePeerAuthPolicy {
            allowed_broker_sid: "S-1-5-broker".into(),
            denied_sids: ["S-1-5-login".to_string(), "S-1-5-sidecar".to_string()].into_iter().collect(),
        }
    }
    fn handles() -> Vec<(i32, HandleRole)> {
        vec![(0, HandleRole::Inert), (1, HandleRole::Inert), (2, HandleRole::Inert),
             (3, HandleRole::StoreInput), (4, HandleRole::StoreInput), (5, HandleRole::StoreInput),
             (6, HandleRole::OutputPipe)]
    }

    #[test]
    fn accepts_a_correct_restricted_token() {
        assert!(verify_restricted_token(&ok_token()).is_ok());
    }

    #[test]
    fn rejects_forbidden_privilege_high_integrity_unrestricted() {
        let mut t = ok_token(); t.privileges.insert("SeDebugPrivilege".into());
        assert_eq!(verify_restricted_token(&t), Err(WindowsBrokerViolation::ForbiddenPrivilege("SeDebugPrivilege".into())));
        let mut t = ok_token(); t.integrity = IntegrityLevel::High;
        assert_eq!(verify_restricted_token(&t), Err(WindowsBrokerViolation::TokenIntegrityTooHigh));
        let mut t = ok_token(); t.is_restricted = false;
        assert_eq!(verify_restricted_token(&t), Err(WindowsBrokerViolation::TokenNotRestricted));
    }

    #[test]
    fn authority_pipe_allows_only_broker_denies_renderer_and_sidecar() {
        assert!(authorize_authority_peer(&policy(), "S-1-5-broker").is_ok());
        assert_eq!(authorize_authority_peer(&policy(), "S-1-5-login"), Err(WindowsBrokerViolation::PeerExplicitlyDenied("S-1-5-login".into())));
        assert_eq!(authorize_authority_peer(&policy(), "S-1-5-sidecar"), Err(WindowsBrokerViolation::PeerExplicitlyDenied("S-1-5-sidecar".into())));
        assert_eq!(authorize_authority_peer(&policy(), "S-1-5-other"), Err(WindowsBrokerViolation::PeerNotBroker("S-1-5-other".into())));
    }

    #[test]
    fn image_verification_fails_closed() {
        let spec = ImageVerificationSpec { expected_sha256: "abc".into(), require_authenticode: true };
        assert!(verify_image(&spec, &ImageFacts { sha256: "abc".into(), authenticode_valid: true, writable_by_login_or_runtime: false }).is_ok());
        assert_eq!(verify_image(&spec, &ImageFacts { sha256: "abc".into(), authenticode_valid: true, writable_by_login_or_runtime: true }), Err(WindowsBrokerViolation::ImageWritableByUntrusted));
        assert_eq!(verify_image(&spec, &ImageFacts { sha256: "WRONG".into(), authenticode_valid: true, writable_by_login_or_runtime: false }), Err(WindowsBrokerViolation::ImageHashMismatch));
        assert_eq!(verify_image(&spec, &ImageFacts { sha256: "abc".into(), authenticode_valid: false, writable_by_login_or_runtime: false }), Err(WindowsBrokerViolation::ImageAuthenticodeInvalid));
    }

    #[test]
    fn handle_list_requires_exactly_0_to_6_in_role() {
        assert!(verify_startupinfo_handle_list(&handles()).is_ok());
        let mut extra = handles(); extra.push((7, HandleRole::StoreInput));
        assert_eq!(verify_startupinfo_handle_list(&extra), Err(WindowsBrokerViolation::UnexpectedHandleSlot(7)));
        let missing: Vec<_> = handles().into_iter().filter(|(s, _)| *s != 4).collect();
        assert_eq!(verify_startupinfo_handle_list(&missing), Err(WindowsBrokerViolation::MissingHandleSlot(4)));
        let mut wrong = handles(); wrong[3] = (3, HandleRole::OutputPipe);
        assert_eq!(verify_startupinfo_handle_list(&wrong), Err(WindowsBrokerViolation::WrongHandleRole(3)));
    }
}
