//! The Windows half: the pipe both ends already speak.
//!
//! There is no new transport here. The server is `brops_win_live::pipe::run_server` and the client
//! is its `hop_once`, so the restrictive pipe DACL (`pipe_acl::pipe_dacl_plan`), the
//! never-unowned-name successor logic, the `SECURITY_IDENTIFICATION` client SQOS and the
//! kernel-attested peer SID (`brops_win_broker::syscall::authenticate_pipe_client_sid`) are the
//! same code the live kit's audit already went over, not a second copy of it.
//!
//! # Is that machinery right for this use? Two answers.
//!
//! **The server: yes, and this is the deployment it wanted.** `pipe_acl` says out loud that its
//! create-instance restriction "buys nothing" when the client is the server principal — the
//! same-account case. Here the server is `NT SERVICE\BroPSAuditSigner` and the client is the
//! installing user, so `PipeDacl::broker_is_server_principal` is **false** and the restriction is
//! real: the app holds `PIPE_CLIENT_ACCESS_MASK` without `FILE_CREATE_PIPE_INSTANCE`, so it can
//! talk on the pipe and cannot stand up a second instance of the name to answer as the signer.
//!
//! **The client: no, in one respect, and it is bounded rather than forked.** `open_client` retries
//! for roughly nine seconds; the engine's entire budget is ten and it holds the ledger's exclusive
//! append lock while it waits. See [`crate::relay::CONNECT_DEADLINE`].
//!
//! # What the peer SID does and does not prove
//!
//! It proves the connecting process runs as the app's account. It does **not** prove *which*
//! program that account is running — any process of that user can open the pipe and ask for a
//! signature over any payload it likes. That is not a hole in this design; it is the boundary the
//! design draws. The signer's job is that the ledger's writer cannot sign a head *the signer has
//! not agreed to*: the count may not go backwards, the head may not fork at a count, and the
//! anchor chain may not be broken (`audit_signer::check_monotonic`). A caller who asks for an
//! honest next anchor gets one whoever they are; a caller who asks for a truncation is refused
//! whoever they are. Authenticating the peer keeps *other* local accounts out of the queue — it
//! was never the thing that resists the writer.

#![cfg(windows)]

use serde_json::Value;

use brops_win_live::pipe;
use brops_win_live::servers::DispatchCore;

use crate::AnchorCore;

impl DispatchCore for AnchorCore {
    /// `now_ms` is deliberately unused: the anchor's `issued_at_epoch` is the *engine's* clock,
    /// carried in the payload it assembled and signed as part of it. A signer that stamped its own
    /// time would produce a document whose payload differs from the one the ledger assembled, and
    /// `bro_audit_log._sign_anchor` refuses exactly that.
    fn handle(&self, req: &Value, _now_ms: i64) -> Value {
        self.decide(req)
    }
}

/// Serve anchor requests forever. Never returns; `run_server` exits the process rather than
/// degrade if it cannot build a restrictive descriptor or cannot hold the pipe name.
pub fn serve(pipe_name: &str, allowed_app_sid: &str, core: &AnchorCore) -> ! {
    pipe::run_server(pipe_name, allowed_app_sid, core)
}

/// One request → one reply, bounded by [`crate::relay::CONNECT_DEADLINE`].
///
/// The roundtrip runs on a worker thread so the deadline can be enforced against a blocking
/// `CreateFileW` retry loop this crate does not own. On timeout the caller exits the process,
/// which is what releases the abandoned thread — acceptable precisely because the shim is a
/// one-shot process with no state to unwind and no key to zeroise.
pub fn roundtrip(pipe_name: &str, request: &Value) -> Result<Value, String> {
    let (tx, rx) = std::sync::mpsc::channel();
    let name = pipe_name.to_string();
    let req = request.clone();
    std::thread::spawn(move || {
        let _ = tx.send(pipe::hop_once(&name, &req));
    });
    match rx.recv_timeout(crate::relay::CONNECT_DEADLINE) {
        Ok(Ok(reply)) => Ok(reply),
        Ok(Err(())) => Err(format!(
            "could not complete a request to the audit-anchor signer on \\\\.\\pipe\\{pipe_name}. \
             The {} service is registered but not answering, or this account is not the peer SID \
             its pipe DACL admits",
            brops_provision::audit_signer::SIGNER_SERVICE_NAME
        )),
        Err(_) => Err(format!(
            "the audit-anchor signer did not answer on \\\\.\\pipe\\{pipe_name} within {:?}. The \
             {} service is not running, so this ledger stays HONESTLY UNANCHORED — \
             bro_audit_log.verify(keys=...) will report AuditAnchorMissing, which is a refusal, \
             not 'intact'",
            crate::relay::CONNECT_DEADLINE,
            brops_provision::audit_signer::SIGNER_SERVICE_NAME
        )),
    }
}
