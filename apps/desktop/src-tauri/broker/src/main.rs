//! Wave 3b-1B — the trusted **broker service** as a SEPARATE binary crate (design-GREEN rev-30 §0 role #2,
//! §4.10(g)).
//!
//! The broker is the ONLY process that opens the receipt/broker SQLite database and the ONLY process that
//! runs governed turns. It is NOT the renderer: the renderer is a mutually-distrusting client that connects
//! over a single-request/single-response AF_UNIX channel. This binary:
//!
//!   1. opens (or creates) the broker DB and initializes the four rev-30 governed-turn schemas
//!      (`broker_turns`, `governed_message_store`, `governed_output_stream`, `supervisor_ledger`) — the
//!      idempotency ledger, the committed-message store, the output-stream projection, and the supervisor
//!      lease ledger, all through `brops-core` so there is exactly one schema authority;
//!   2. on Linux binds the renderer→broker AF_UNIX listener and, for each connection, reads EXACTLY ONE
//!      length-prefixed [`ipc_framing`] request frame, authenticates the peer's OS credentials
//!      (`SO_PEERCRED`) and allowlists EXACTLY the renderer/login UID (denying every other), then drives one
//!      governed turn through [`broker_orchestrator::run_governed_turn`] with a broker-minted [`BrokerIds`]
//!      and a [`GovernedExecutor`], and writes the framed committed/blocked reply.
//!
//! The challenge→authority→supervisor→signer→verification chain is a follow-up slice, so the injected
//! executor here fails closed with [`TurnReason::UpstreamBlocked`]: the broker never fabricates an accepted
//! output it did not actually get from the signed-envelope chain. Every renderer request is therefore
//! answered with a well-formed `blocked` reply — real, correct, and fail-closed — until the real executor
//! lands.
//!
//! The `bind`/`accept`/`recv` + `SO_PEERCRED` read are the only host-specific parts and are gated behind
//! `#[cfg(target_os = "linux")]`. On every other host `main` prints the platform-unsupported banner and
//! exits non-zero (governed real mode disabled — fail closed). The DB-schema init and the governed-turn
//! wiring are pure and unit-tested on any platform.

// Governed-chain orchestration now lives in the crate LIBRARY (`brops_broker::chain_executor` /
// `brops_broker::chain_hops`) so the Linux live-turn driver wires the SAME real chain. This binary keeps
// the fail-closed UpstreamBlockedExecutor for the renderer→broker path; the live driver is the entry point
// that instantiates the real LinuxGovernedTurnChain end-to-end.
use brops_core::broker_orchestrator::{BrokerIds, GovernedExecutor};
use brops_core::governed_message_store::AcceptedOutput;
use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest};
use rusqlite::Connection;

// ---------------------------------------------------------------------------------------------------
// Exit codes (fail-closed). A healthy broker runs its accept loop forever; every early return is an error.
// ---------------------------------------------------------------------------------------------------
const EXIT_PLATFORM_UNSUPPORTED: i32 = 2;
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const EXIT_DB: i32 = 3;
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const EXIT_SOCKET: i32 = 4;

// ---------------------------------------------------------------------------------------------------
// Broker DB schema init — pure, host-independent, testable on any platform. Creates the four governed-turn
// schemas through brops-core so the broker shares exactly one schema authority with the recorder side.
// ---------------------------------------------------------------------------------------------------

/// Initialize the four rev-30 governed-turn schemas on `conn` (idempotent — every `create_schema` uses
/// `CREATE TABLE IF NOT EXISTS`). Fails closed with a stage-tagged message on the first error so a partially
/// migrated DB never advances to serving turns.
pub fn init_broker_schema(conn: &Connection) -> Result<(), String> {
    brops_core::broker_turns::create_schema(conn)
        .map_err(|e| format!("broker_turns schema init failed: {e:?}"))?;
    brops_core::governed_message_store::create_schema(conn)
        .map_err(|e| format!("governed_message_store schema init failed: {e}"))?;
    brops_core::governed_output_stream::create_schema(conn)
        .map_err(|e| format!("governed_output_stream schema init failed: {e}"))?;
    brops_core::supervisor_ledger::create_schema(conn)
        .map_err(|e| format!("supervisor_ledger schema init failed: {e:?}"))?;
    Ok(())
}

// ---------------------------------------------------------------------------------------------------
// Broker-minted identities. The renderer can NEVER supply these — the broker is the sole authority for the
// `broker_turn_id` and the per-turn `request_nonce`. Production uses `brops_core::id()` (UUID v4).
// ---------------------------------------------------------------------------------------------------

/// Production [`BrokerIds`]: fresh UUID v4 broker-turn ids and request nonces.
pub struct UuidBrokerIds;
impl BrokerIds for UuidBrokerIds {
    fn new_broker_turn_id(&self) -> String {
        brops_core::id()
    }
    fn new_request_nonce(&self) -> String {
        brops_core::id()
    }
}

// ---------------------------------------------------------------------------------------------------
// Governed executor. The real challenge→authority→supervisor→signer→verification chain is a follow-up
// slice; until it lands the broker fails closed: it refuses every turn with UpstreamBlocked rather than
// fabricate an accepted output. This is the correct fail-closed behavior, not a stub that lies.
// ---------------------------------------------------------------------------------------------------

/// The interim [`GovernedExecutor`]: no real upstream chain is wired yet, so every turn is refused closed.
pub struct UpstreamBlockedExecutor;
impl GovernedExecutor for UpstreamBlockedExecutor {
    fn execute_and_verify(
        &self,
        _req: &ValidatedRequest,
        _broker_turn_id: &str,
        _request_nonce: &str,
    ) -> Result<AcceptedOutput, TurnReason> {
        Err(TurnReason::UpstreamBlocked)
    }
}

// ---------------------------------------------------------------------------------------------------
// Entry point.
// ---------------------------------------------------------------------------------------------------

fn main() {
    std::process::exit(run());
}

#[cfg(not(target_os = "linux"))]
fn run() -> i32 {
    // No AF_UNIX SO_PEERCRED peer authentication off Linux ⇒ the renderer→broker trust boundary cannot be
    // enforced ⇒ governed real mode is unavailable. Fail closed.
    eprintln!("brops-broker: platform unsupported (governed real-mode disabled)");
    EXIT_PLATFORM_UNSUPPORTED
}

#[cfg(target_os = "linux")]
fn run() -> i32 {
    match linux::serve() {
        Ok(()) => EXIT_SOCKET, // serve() only returns on a fatal listener error
        Err(code) => code,
    }
}

// ---------------------------------------------------------------------------------------------------
// Linux real path (§4.10(g) renderer→broker channel). Gated so the Windows/other-host build stays pure-std;
// the CI Linux job exercises the real renderer → broker → committed/blocked reply path. The socket bind /
// accept use std::os::unix::net; the SO_PEERCRED read is the one libc call. Every step is fail-closed.
// ---------------------------------------------------------------------------------------------------
#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use brops_core::ipc_framing::{authorize_peer, encode_frame, FrameDecoder, PeerCred};
    use std::io::{Read, Write};
    use std::os::unix::io::AsRawFd;
    use std::os::unix::net::{UnixListener, UnixStream};

    pub fn serve() -> Result<(), i32> {
        // argv: [socket_path] [allowed_renderer_uid?]. Defaults: a fixed runtime path and the broker's own
        // login uid stand in for the pinned renderer identity until the launcher passes them explicitly.
        let mut args = std::env::args().skip(1);
        let socket_path = args
            .next()
            .unwrap_or_else(|| "/run/brops/broker.sock".to_string());
        let allowed_uid = args
            .next()
            .and_then(|s| s.parse::<u32>().ok())
            // SAFETY: getuid never fails and touches no memory.
            .unwrap_or_else(|| unsafe { libc::getuid() });

        // Open the broker DB and initialize the four governed-turn schemas before accepting a single peer.
        let conn = Connection::open(&socket_path.replace(".sock", ".db")).map_err(|e| {
            eprintln!("brops-broker: cannot open broker DB: {e}");
            EXIT_DB
        })?;
        init_broker_schema(&conn).map_err(|e| {
            eprintln!("brops-broker: {e}");
            EXIT_DB
        })?;

        // A stale socket file blocks bind; remove it first (the broker owns this path exclusively).
        let _ = std::fs::remove_file(&socket_path);
        let listener = UnixListener::bind(&socket_path).map_err(|e| {
            eprintln!("brops-broker: cannot bind {socket_path}: {e}");
            EXIT_SOCKET
        })?;

        let ids = UuidBrokerIds;
        let executor = UpstreamBlockedExecutor;

        // One governed turn per connection (single-request/single-response). A bad peer or malformed frame
        // fails that ONE connection closed; the listener keeps serving.
        for stream in listener.incoming() {
            match stream {
                Ok(mut s) => {
                    if let Err(e) = handle_conn(&conn, &mut s, allowed_uid, &ids, &executor) {
                        eprintln!("brops-broker: connection refused: {e}");
                    }
                }
                Err(e) => eprintln!("brops-broker: accept error: {e}"),
            }
        }
        Ok(())
    }

    /// Read the peer's OS credentials via `SO_PEERCRED` (kernel-attested at connect time — unforgeable by the
    /// renderer). Returns `None` if the option read fails.
    fn peer_cred(stream: &UnixStream) -> Option<PeerCred> {
        let mut cred = libc::ucred {
            pid: 0,
            uid: 0,
            gid: 0,
        };
        let mut len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
        // SAFETY: getsockopt writes a ucred of exactly `len` bytes into `cred`; fd is a live connected socket.
        let rc = unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_PEERCRED,
                &mut cred as *mut libc::ucred as *mut libc::c_void,
                &mut len,
            )
        };
        if rc != 0 {
            return None;
        }
        Some(PeerCred {
            uid: cred.uid,
            gid: cred.gid,
            pid: cred.pid,
        })
    }

    /// Handle one renderer connection: authenticate the peer, read one framed request, run one governed
    /// turn, and write the framed reply. Every failure fails this connection closed.
    fn handle_conn(
        conn: &Connection,
        stream: &mut UnixStream,
        allowed_uid: u32,
        ids: &dyn BrokerIds,
        executor: &dyn GovernedExecutor,
    ) -> Result<(), String> {
        // 1. Peer authentication BEFORE reading any request bytes (rev-30 §2.1): the renderer/login UID is
        //    the broker's only client here; deny every other principal.
        let peer = peer_cred(stream).ok_or_else(|| "SO_PEERCRED read failed".to_string())?;
        authorize_peer(&peer, allowed_uid, &[])
            .map_err(|e| format!("peer not authorized: {e:?}"))?;

        // 2. Read EXACTLY ONE bounded frame. The decoder fails closed on a declared-oversize length; a read
        //    ceiling caps a slow/greedy peer without allocating on its say-so.
        let raw = read_one_frame(stream)?;
        let raw_str =
            std::str::from_utf8(&raw).map_err(|_| "request frame is not valid UTF-8".to_string())?;

        // 3. Drive one governed turn. run_governed_turn never panics: a malformed request or an upstream
        //    refusal both come back as a closed `blocked` reply.
        let result =
            brops_core::broker_orchestrator::run_governed_turn(conn, raw_str, ids, executor, brops_core_now());

        // 4. Serialize + frame the reply and write it back on the same connection.
        let body = serde_json::to_vec(&result).map_err(|e| format!("reply serialize failed: {e}"))?;
        let frame =
            encode_frame(&body).map_err(|e| format!("reply frame encode failed: {e:?}"))?;
        stream
            .write_all(&frame)
            .map_err(|e| format!("reply write failed: {e}"))?;
        stream.flush().map_err(|e| format!("reply flush failed: {e}"))?;
        Ok(())
    }

    /// Read from the stream until the [`FrameDecoder`] yields exactly one complete frame payload. Bounded:
    /// never buffers more than the frame cap + one length prefix, and fails closed on EOF-before-frame or a
    /// declared-oversize length.
    fn read_one_frame(stream: &mut UnixStream) -> Result<Vec<u8>, String> {
        let mut decoder = FrameDecoder::new();
        let mut chunk = [0u8; 1024];
        loop {
            if let Some(frame) = decoder
                .next_frame()
                .map_err(|e| format!("frame decode failed: {e:?}"))?
            {
                return Ok(frame);
            }
            let n = stream
                .read(&mut chunk)
                .map_err(|e| format!("frame read failed: {e}"))?;
            if n == 0 {
                return Err("peer closed before a complete frame".to_string());
            }
            // The FrameDecoder enforces the payload cap on the length prefix itself (fail closed on a
            // declared-oversize length), so feeding raw chunks cannot be used to force an unbounded alloc.
            decoder.feed(&chunk[..n]);
        }
    }

    /// Wall-clock milliseconds for the turn's `now_ms`. Kept here (not in the pure init path) so the tested
    /// core stays deterministic.
    fn brops_core_now() -> i64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0)
    }
}

// ---------------------------------------------------------------------------------------------------
// Tests — pure, offline, host-independent (run on Windows/macOS/Linux alike). They exercise the broker DB
// schema init and the governed-turn wiring over an in-memory connection with a fake executor; no socket, no
// peer-cred syscall.
// ---------------------------------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use brops_core::broker_orchestrator::run_governed_turn;
    use brops_core::governed_message_store::sha256_hex;

    // A fake executor that returns a verified accepted output, mirroring the broker_orchestrator test
    // pattern — lets us drive the committed path over our own schema init without the OS trust chain.
    struct OkExecutor {
        body: String,
    }
    impl GovernedExecutor for OkExecutor {
        fn execute_and_verify(
            &self,
            req: &ValidatedRequest,
            bt: &str,
            _n: &str,
        ) -> Result<AcceptedOutput, TurnReason> {
            Ok(AcceptedOutput {
                broker_turn_id: bt.to_string(),
                message_id: format!("m-{bt}"),
                conversation_id: req.conversation_id.clone(),
                author: "Bro".into(),
                accepted_body: self.body.clone(),
                envelope_body_sha256: sha256_hex(self.body.as_bytes()),
                created_at_ms: 42,
            })
        }
    }

    struct FixedIds;
    impl BrokerIds for FixedIds {
        fn new_broker_turn_id(&self) -> String {
            "bt-fixed".into()
        }
        fn new_request_nonce(&self) -> String {
            "nonce-fixed".into()
        }
    }

    const CRID: &str = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

    fn raw(conv: &str, crid: &str) -> String {
        let proto = brops_core::governed_turn_ipc::REQUEST_PROTOCOL;
        format!(
            r#"{{"protocol":"{proto}","conversation_id":"{conv}","agent":"a","client_request_id":"{crid}"}}"#
        )
    }

    #[test]
    fn init_broker_schema_is_idempotent_and_serves_a_turn() {
        let conn = Connection::open_in_memory().unwrap();
        // Idempotent: initializing twice must succeed (every schema is CREATE TABLE IF NOT EXISTS).
        init_broker_schema(&conn).expect("first init");
        init_broker_schema(&conn).expect("second init");

        // A governed turn runs end-to-end over the freshly-initialized schema with a fake OK executor.
        let r = run_governed_turn(
            &conn,
            &raw("conv-1", CRID),
            &FixedIds,
            &OkExecutor {
                body: "hi there".into(),
            },
            1,
        );
        assert_eq!(r.status, "committed");
        let m = r.message.expect("committed message present");
        assert_eq!(m.body, "hi there");
        assert_eq!(r.broker_turn_id, "bt-fixed");
        assert_eq!(r.client_request_id, CRID);
    }

    #[test]
    fn production_executor_fails_closed_with_upstream_blocked() {
        let conn = Connection::open_in_memory().unwrap();
        init_broker_schema(&conn).unwrap();
        // The interim production executor refuses every turn closed — no fabricated accepted output.
        let r = run_governed_turn(
            &conn,
            &raw("conv-1", CRID),
            &UuidBrokerIds,
            &UpstreamBlockedExecutor,
            1,
        );
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::UpstreamBlocked));
        assert!(r.message.is_none());
        // The broker still minted a real (UUID) broker_turn_id for the refused turn.
        assert!(!r.broker_turn_id.is_empty());
    }

    #[test]
    fn malformed_request_is_blocked_not_panicked() {
        let conn = Connection::open_in_memory().unwrap();
        init_broker_schema(&conn).unwrap();
        let r = run_governed_turn(
            &conn,
            r#"{"protocol":"nope"}"#,
            &UuidBrokerIds,
            &UpstreamBlockedExecutor,
            1,
        );
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::Malformed));
    }
}
