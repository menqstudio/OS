//! The named-pipe security descriptor the live-kit servers create their pipes with — as a PURE,
//! host-independent plan (audit **R3**, "`FILE_FLAG_FIRST_PIPE_INSTANCE` is inert under a NULL DACL").
//!
//! ## What was wrong
//!
//! [`crate::pipe::run_server`] used to create every pipe with a **NULL DACL** and justify it as "the
//! trust boundary is the peer SID, not the ACL — like the Linux `0777` socket". That justification is
//! true for *who may CONNECT* and false for *who may CREATE*. A NULL DACL grants **everyone
//! `FILE_ALL_ACCESS`**, which includes `FILE_CREATE_PIPE_INSTANCE` (bit `0x0004`). So any local
//! principal — including the in-scope sidecar-RCE SID and the interactive login — could add a *second
//! instance* of the trusted pipe name at any moment after the server created the first one, and
//! collect the next client connection.
//!
//! `FILE_FLAG_FIRST_PIPE_INSTANCE` only fails the create when an instance **already exists**. It
//! therefore stops a squatter who arrives BEFORE the server and does nothing about one who arrives
//! AFTER — which, under a NULL DACL, anyone could. The flag protected nothing it wasn't already
//! racing for.
//!
//! ## What this module decides
//!
//! An explicit, deny-by-omission DACL: the server's own principal, `SYSTEM` and `BUILTIN\Administrators`
//! get full control (they can create further instances — they are the deployment's TCB), and the
//! provisioned **broker SID** gets exactly [`PIPE_CLIENT_ACCESS_MASK`]: enough to open the pipe and do
//! duplex framed I/O, and **not** `FILE_CREATE_PIPE_INSTANCE`. Every other principal is absent from the
//! DACL and therefore denied — they can no longer even open the pipe, let alone instantiate it.
//!
//! The plan is pure data so the decision is unit-testable on the Linux CI runner; `crate::pipe` is the
//! only consumer and has no other way to build a security descriptor.
//!
//! ## Honest limitation: the same-account deployment
//!
//! When the servers and the broker run as the SAME Windows account (which is exactly what the
//! same-account proof harness does), the broker SID *is* the server principal, so it necessarily keeps
//! full control and the create-instance restriction collapses to nothing for it. That is a property of
//! the deployment, not of this code: only the CROSS-ACCOUNT deployment (distinct service accounts)
//! actually gets the squat resistance. [`PipeDacl::broker_is_server_principal`] reports which case the
//! caller is in so it can say so out loud instead of implying the stronger one.

/// Right to read pipe data.
pub const FILE_READ_DATA: u32 = 0x0000_0001;
/// Right to write pipe data.
pub const FILE_WRITE_DATA: u32 = 0x0000_0002;
/// **The bit this module exists for.** `0x0004` is `FILE_APPEND_DATA` on a file object and
/// `FILE_CREATE_PIPE_INSTANCE` on a named pipe: the right to create ANOTHER instance of an existing
/// pipe name. A NULL DACL grants it to everyone; `GENERIC_WRITE` also maps to it, which is why the
/// client side must request [`PIPE_CLIENT_ACCESS_MASK`] explicitly rather than `GENERIC_READ |
/// GENERIC_WRITE`.
pub const FILE_CREATE_PIPE_INSTANCE: u32 = 0x0000_0004;
/// Right to read pipe attributes.
pub const FILE_READ_ATTRIBUTES: u32 = 0x0000_0080;
/// Right to write pipe attributes.
pub const FILE_WRITE_ATTRIBUTES: u32 = 0x0000_0100;
/// Standard right: delete.
pub const DELETE: u32 = 0x0001_0000;
/// Standard right: read the security descriptor.
pub const READ_CONTROL: u32 = 0x0002_0000;
/// Standard right: rewrite the DACL (an adversary holding this can grant itself everything else).
pub const WRITE_DAC: u32 = 0x0004_0000;
/// Standard right: take ownership (likewise a full compromise of the object's ACL).
pub const WRITE_OWNER: u32 = 0x0008_0000;
/// Standard right: wait on the handle. A pipe client needs this to block in `ReadFile`.
pub const SYNCHRONIZE: u32 = 0x0010_0000;
/// `FILE_ALL_ACCESS` — everything, including [`FILE_CREATE_PIPE_INSTANCE`].
pub const FILE_ALL_ACCESS: u32 = 0x001F_01FF;

/// The mask the broker (pipe CLIENT) is granted, and the exact mask its `CreateFileW` must request.
///
/// Deliberately built bit-by-bit instead of `GENERIC_READ | GENERIC_WRITE`: the generic mapping for a
/// named pipe expands `GENERIC_WRITE` to include `FILE_APPEND_DATA` — the same bit as
/// [`FILE_CREATE_PIPE_INSTANCE`] — so a client asking for `GENERIC_WRITE` against this restricted DACL
/// would be denied, and "fixing" that by granting `0x4` would hand the squat right back. Read/write
/// data + attributes + `SYNCHRONIZE` is everything the framed request/reply transport actually uses.
pub const PIPE_CLIENT_ACCESS_MASK: u32 =
    FILE_READ_DATA | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | FILE_WRITE_ATTRIBUTES | SYNCHRONIZE;

/// Every access bit that lets a holder change the object or the ACL. Used to decide whether an ACE
/// found on a live object grants *write* authority to an untrusted principal.
pub const WRITE_ACCESS_BITS: u32 = FILE_WRITE_DATA
    | FILE_CREATE_PIPE_INSTANCE
    | FILE_WRITE_ATTRIBUTES
    | DELETE
    | WRITE_DAC
    | WRITE_OWNER;

/// `NT AUTHORITY\SYSTEM`.
pub const SID_LOCAL_SYSTEM: &str = "S-1-5-18";
/// `BUILTIN\Administrators`.
pub const SID_ADMINISTRATORS: &str = "S-1-5-32-544";

/// SIDs that stand for "essentially everyone on this box". None of these may appear in a live-kit
/// pipe DACL, and none may be accepted as a broker SID — granting one is indistinguishable from the
/// NULL DACL this module replaced.
pub const WORLD_SIDS: &[&str] = &[
    "S-1-1-0",      // Everyone
    "S-1-5-7",      // ANONYMOUS LOGON
    "S-1-5-11",     // Authenticated Users
    "S-1-5-4",      // INTERACTIVE
    "S-1-5-2",      // NETWORK
    "S-1-5-32-545", // BUILTIN\Users
    "S-1-5-32-546", // BUILTIN\Guests
    "S-1-2-0",      // LOCAL
    "S-1-2-1",      // CONSOLE LOGON
    "S-1-5-32-547", // BUILTIN\Power Users
];

/// One access-allowed ACE of the planned DACL.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PipeAce {
    /// String SID of the trustee (`S-1-5-…`).
    pub sid: String,
    /// The access mask granted.
    pub mask: u32,
}

/// The planned DACL plus the honest note about which deployment shape produced it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PipeDacl {
    /// Access-allowed ACEs, in the order they must be added.
    pub aces: Vec<PipeAce>,
    /// `true` when the broker runs as the SAME account as the server, so the broker keeps full control
    /// and the create-instance restriction buys nothing against it. Callers MUST report this rather
    /// than claim squat resistance they do not have.
    pub broker_is_server_principal: bool,
}

/// Cheap syntactic SID check. Not a substitute for the OS parse (`ConvertStringSidToSidW` is the real
/// arbiter and its failure is fatal at the call site) — this exists so the pure plan can refuse the
/// obviously-wrong inputs on any host, including in a Linux unit test.
fn looks_like_sid(s: &str) -> bool {
    s.starts_with("S-1-")
        && s.len() > 4
        && s.split('-').skip(1).all(|part| !part.is_empty() && part.chars().all(|c| c.is_ascii_digit()))
}

/// Plan the pipe DACL for a server running as `server_sid` that will accept `allowed_broker_sid`.
///
/// Fail-closed: an unparseable SID, or a broker "SID" that is really a world group, is an `Err`. The
/// caller MUST abort rather than fall back to a permissive descriptor — a broker SID of `S-1-1-0`
/// would silently rebuild the NULL DACL this replaced.
pub fn pipe_dacl_plan(server_sid: &str, allowed_broker_sid: &str) -> Result<PipeDacl, String> {
    if !looks_like_sid(server_sid) {
        return Err(format!("server principal SID is not a SID: {server_sid:?}"));
    }
    if !looks_like_sid(allowed_broker_sid) {
        return Err(format!("allowed_broker_sid is not a SID: {allowed_broker_sid:?}"));
    }
    if WORLD_SIDS.contains(&allowed_broker_sid) {
        return Err(format!(
            "allowed_broker_sid {allowed_broker_sid} is a world/group SID; granting it would reopen \
             the pipe to every local principal"
        ));
    }
    if WORLD_SIDS.contains(&server_sid) {
        return Err(format!("server principal SID {server_sid} is a world/group SID"));
    }

    let mut aces = vec![PipeAce { sid: server_sid.to_string(), mask: FILE_ALL_ACCESS }];
    // SYSTEM and Administrators are the deployment's TCB: they can already take ownership of any local
    // object, so withholding the ACE would be theatre rather than containment. They are named
    // explicitly so the DACL is complete and an operator can read the intent off it.
    for tcb in [SID_LOCAL_SYSTEM, SID_ADMINISTRATORS] {
        if tcb != server_sid {
            aces.push(PipeAce { sid: tcb.to_string(), mask: FILE_ALL_ACCESS });
        }
    }
    let broker_is_server_principal = allowed_broker_sid == server_sid
        || allowed_broker_sid == SID_LOCAL_SYSTEM
        || allowed_broker_sid == SID_ADMINISTRATORS;
    if !broker_is_server_principal {
        aces.push(PipeAce { sid: allowed_broker_sid.to_string(), mask: PIPE_CLIENT_ACCESS_MASK });
    }
    Ok(PipeDacl { aces, broker_is_server_principal })
}

/// Which trustees in `aces` are granted [`FILE_CREATE_PIPE_INSTANCE`] — i.e. who can stand up another
/// instance of this pipe name and race for the next connection.
pub fn create_instance_grantees(aces: &[PipeAce]) -> Vec<&str> {
    aces.iter()
        .filter(|a| a.mask & FILE_CREATE_PIPE_INSTANCE != 0)
        .map(|a| a.sid.as_str())
        .collect()
}

/// Which trustees in `aces` are world/everyone groups. Any hit means the DACL is not a restriction.
pub fn world_grantees(aces: &[PipeAce]) -> Vec<&str> {
    aces.iter()
        .filter(|a| WORLD_SIDS.contains(&a.sid.as_str()))
        .map(|a| a.sid.as_str())
        .collect()
}

/// Is this security descriptor effectively open?
///
/// `dacl_present == false` is the **NULL DACL** case, and a NULL DACL is not "no permissions" — Windows
/// treats it as *everyone gets full control*. Encoding that here makes the semantics testable on any
/// host and gives the Windows read-back test (and [`crate::tcb_floor`]) one shared rule.
pub fn dacl_is_open(dacl_present: bool, aces: &[PipeAce]) -> bool {
    !dacl_present || !world_grantees(aces).is_empty()
}

#[cfg(test)]
mod tests {
    use super::*;

    const SERVER: &str = "S-1-5-21-11-22-33-1006";
    const BROKER: &str = "S-1-5-21-11-22-33-1010";

    #[test]
    fn a_null_dacl_is_an_open_descriptor_not_a_closed_one() {
        // The whole finding in one assertion: absent DACL == everyone full control. If this ever
        // reports `false`, every consumer of the rule silently starts calling the old, broken
        // descriptor "restricted".
        assert!(dacl_is_open(false, &[]));
        assert!(!dacl_is_open(true, &pipe_dacl_plan(SERVER, BROKER).unwrap().aces));
    }

    #[test]
    fn the_broker_is_never_granted_create_pipe_instance() {
        // This is the P0-2 property: the broker may talk on the pipe, but may not INSTANTIATE it, so it
        // cannot add a second instance and collect a connection meant for a server.
        let plan = pipe_dacl_plan(SERVER, BROKER).unwrap();
        assert!(!plan.broker_is_server_principal);
        let grantees = create_instance_grantees(&plan.aces);
        assert!(
            !grantees.contains(&BROKER),
            "broker must not hold FILE_CREATE_PIPE_INSTANCE: {grantees:?}"
        );
        assert_eq!(grantees, vec![SERVER, SID_LOCAL_SYSTEM, SID_ADMINISTRATORS]);
        let broker_ace = plan.aces.iter().find(|a| a.sid == BROKER).expect("broker ACE");
        assert_eq!(broker_ace.mask, PIPE_CLIENT_ACCESS_MASK);
        assert_eq!(broker_ace.mask & FILE_CREATE_PIPE_INSTANCE, 0);
    }

    #[test]
    fn the_client_mask_omits_the_create_instance_bit_but_keeps_duplex_io() {
        // If someone "fixes" a client access-denied by switching back to GENERIC_READ|GENERIC_WRITE,
        // the generic mapping re-adds 0x4 and the restriction is gone. Pin the exact mask.
        assert_eq!(PIPE_CLIENT_ACCESS_MASK & FILE_CREATE_PIPE_INSTANCE, 0);
        for needed in [FILE_READ_DATA, FILE_WRITE_DATA, SYNCHRONIZE] {
            assert_ne!(PIPE_CLIENT_ACCESS_MASK & needed, 0, "client still needs {needed:#x}");
        }
    }

    #[test]
    fn no_world_sid_ever_appears_in_the_plan() {
        let plan = pipe_dacl_plan(SERVER, BROKER).unwrap();
        assert!(world_grantees(&plan.aces).is_empty());
    }

    #[test]
    fn a_world_broker_sid_is_refused_rather_than_granted() {
        for world in WORLD_SIDS {
            let e = pipe_dacl_plan(SERVER, world).unwrap_err();
            assert!(e.contains("world/group SID"), "{e}");
        }
    }

    #[test]
    fn a_malformed_sid_is_refused_rather_than_defaulted() {
        assert!(pipe_dacl_plan("", BROKER).is_err());
        assert!(pipe_dacl_plan(SERVER, "not-a-sid").is_err());
        assert!(pipe_dacl_plan(SERVER, "S-1-5-21-abc").is_err());
    }

    #[test]
    fn a_same_account_deployment_is_reported_as_such_not_hidden() {
        // The honest case: broker == server principal, so the broker keeps FILE_ALL_ACCESS and the
        // squat restriction buys nothing against it. The flag must say so.
        let plan = pipe_dacl_plan(SERVER, SERVER).unwrap();
        assert!(plan.broker_is_server_principal);
        assert_eq!(create_instance_grantees(&plan.aces), vec![SERVER, SID_LOCAL_SYSTEM, SID_ADMINISTRATORS]);
    }
}
