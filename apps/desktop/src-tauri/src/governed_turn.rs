//! Wave 3b-1B — the renderer→broker thin-proxy Tauri command (design-GREEN rev-30 §4.10(g)).
//!
//! `governed_turn_execute` is the ONE frontend-exposed governed command. It is a THIN PROXY: it carries
//! the renderer's closed request frame (`{conversation_id, agent?, client_request_id}`) to the trusted
//! broker SERVICE over the platform IPC (AF_UNIX on Linux) and returns the broker's committed/blocked
//! reply verbatim. It owns NO key, DB, manifest, prepared object, hash, nonce, or verification verdict —
//! it only forwards the request and relays the broker-produced reply. Only the broker service can create a
//! `trusted_verified` result; a transport failure surfaces as an error the renderer renders as `blocked`,
//! never a fabricated committed turn.

use brops_core::broker_client::{send_governed_turn, BrokerConn, TransportError};

/// The broker service socket path (Linux): a dedicated, non-world-writable runtime path owned by the
/// broker service principal (§0 role #2 / §2.6 provisioning).
#[cfg(target_os = "linux")]
const BROKER_SOCKET_PATH: &str = "/run/brops/broker.sock";

/// Hard ceiling on the bytes this client will buffer from the broker (audit F-32/F-36). The framed
/// protocol's own payload cap is `ipc_framing::MAX_FRAME_PAYLOAD_BYTES`; this allows that plus the
/// 4-byte length prefix and a little slack, so a legal reply always fits and a flood never does.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const MAX_REPLY_BYTES: u64 = (brops_core::ipc_framing::MAX_FRAME_PAYLOAD_BYTES as u64) + 64;

/// Per-read/write deadline on the broker socket (audit F-32/F-36). A governed turn is buffered by
/// design and can legitimately take a while upstream, but a silent socket must eventually surface as
/// a transport failure the renderer renders as `blocked` — never as a wedged command.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const IO_TIMEOUT_MS: u64 = 120_000;

/// Stable machine prefix: **no broker IPC transport exists on this host at all** — the governed
/// broker path is not implemented here. This is a PLATFORM fact, decided at compile time, not a
/// runtime failure and emphatically not a broker decision.
pub const BROKER_UNSUPPORTED: &str = "broker_unsupported_platform";
/// Stable machine prefix: a broker IPC transport IS implemented for this host, but the desktop could
/// not establish a connection to it (socket missing, permission denied, timeout not settable, ...).
/// The broker was never reached, so it neither allowed nor refused anything.
pub const BROKER_UNAVAILABLE: &str = "broker_unavailable";
/// Stable machine prefix: the broker WAS connected to, but the framed exchange failed (I/O, protocol,
/// oversized reply). Still not a broker verdict — a broker verdict arrives as an `Ok` reply value.
pub const BROKER_TRANSPORT_FAILED: &str = "broker_transport_failed";

/// Why `connect_broker` could not hand back a connection. The two arms are deliberately NOT collapsed
/// into one string (audit): a caller must be able to tell "this platform has no broker client compiled
/// in" from "the broker client exists and the connect failed", and both from "the broker answered and
/// blocked the turn" (which is an `Ok(reply)` carrying the broker's own verdict, never an `Err` here).
#[derive(Debug)]
enum BrokerAccessError {
    /// No broker IPC transport is compiled for this target OS.
    #[cfg_attr(target_os = "linux", allow(dead_code))]
    UnsupportedPlatform,
    /// The transport exists; establishing the connection failed. Carries the concrete cause.
    #[cfg_attr(not(target_os = "linux"), allow(dead_code))]
    ConnectFailed(String),
}

impl BrokerAccessError {
    /// The honest, machine-prefixed reason string handed to the renderer.
    fn reason(&self) -> String {
        match self {
            Self::UnsupportedPlatform => format!(
                "{BROKER_UNSUPPORTED}: no governed-broker IPC transport is implemented for this host \
                 (os={os}, arch={arch}). The AF_UNIX broker client is Linux-only, and the Windows §0.W \
                 named-pipe broker is a separately-audited slice that is NOT wired into this command. \
                 Governed real-mode is therefore unavailable on this platform BY CONSTRUCTION — nothing \
                 was contacted, so no broker allowed or refused this turn.",
                os = std::env::consts::OS,
                arch = std::env::consts::ARCH,
            ),
            Self::ConnectFailed(detail) => format!(
                "{BROKER_UNAVAILABLE}: a broker IPC transport is implemented for this host but the \
                 connection to `{BROKER_SOCKET_PATH_DISPLAY}` could not be established ({detail}). The \
                 broker was NOT reached, so this is a transport failure, not a broker decision."
            ),
        }
    }
}

/// The socket path named in the `ConnectFailed` reason. On a host with no transport the constant does
/// not exist, and that arm is unreachable there anyway.
#[cfg(target_os = "linux")]
const BROKER_SOCKET_PATH_DISPLAY: &str = BROKER_SOCKET_PATH;
#[cfg(not(target_os = "linux"))]
const BROKER_SOCKET_PATH_DISPLAY: &str = "<no broker socket on this platform>";

/// Forward one governed turn to the broker service and return its committed/blocked reply. The renderer
/// supplies only the closed request; the broker resolves everything else and is the sole author of the
/// reply.
///
/// Error taxonomy (audit): every `Err` here means the broker did NOT decide this turn, and the prefix
/// says which non-decision it was — [`BROKER_UNSUPPORTED`] (no transport on this platform),
/// [`BROKER_UNAVAILABLE`] (transport exists, connect failed), [`BROKER_TRANSPORT_FAILED`] (connected,
/// exchange failed), or a malformed request/reply. A broker that was reached and REFUSED returns
/// `Ok(reply)` carrying the broker's own blocked verdict — which is why it must never share a string
/// with any of these.
#[tauri::command]
pub fn governed_turn_execute(request: serde_json::Value) -> Result<serde_json::Value, String> {
    let request_json = serde_json::to_vec(&request).map_err(|_| "malformed_request".to_string())?;
    let mut conn = connect_broker().map_err(|e| e.reason())?;
    let reply = send_governed_turn(conn.as_mut(), &request_json).map_err(|e: TransportError| {
        format!(
            "{BROKER_TRANSPORT_FAILED}: connected to the broker, but the framed exchange failed \
             ({e:?}). No broker verdict was received."
        )
    })?;
    serde_json::from_slice(&reply).map_err(|_| "malformed_broker_reply".to_string())
}

/// Connect to the broker over the platform IPC. Linux = AF_UNIX; every other host fails closed with
/// [`BrokerAccessError::UnsupportedPlatform`] (the Windows §0.W named-pipe broker is a separately-audited
/// slice), so governed real-mode is unavailable there rather than silently degraded — and, since the
/// audit, rather than masquerading as a broker that was contacted and did not answer.
fn connect_broker() -> Result<Box<dyn BrokerConn>, BrokerAccessError> {
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::net::UnixStream;
        use std::time::Duration;
        let cause = |what: &str, e: std::io::Error| {
            // `io::ErrorKind` is Debug-only, so the kind is formatted with `{:?}`; the full
            // `e` follows in parentheses for the human-readable cause.
            BrokerAccessError::ConnectFailed(format!("{what}: {:?} ({e})", e.kind()))
        };
        let s = UnixStream::connect(BROKER_SOCKET_PATH).map_err(|e| cause("connect", e))?;
        // Audit F-32/F-36: without these the reply read is untimed, so a broker-side endpoint that
        // accepts the connection and then never writes and never closes hangs this Tauri command
        // forever. Fail-closed is a transport error the renderer sees as `blocked`; hanging is not.
        s.set_read_timeout(Some(Duration::from_millis(IO_TIMEOUT_MS)))
            .map_err(|e| cause("set_read_timeout", e))?;
        s.set_write_timeout(Some(Duration::from_millis(IO_TIMEOUT_MS)))
            .map_err(|e| cause("set_write_timeout", e))?;
        Ok(Box::new(linux::UnixBrokerConn(s)) as Box<dyn BrokerConn>)
    }
    #[cfg(not(target_os = "linux"))]
    {
        Err(BrokerAccessError::UnsupportedPlatform)
    }
}

#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use std::io::{Read, Write};
    use std::os::unix::net::UnixStream;

    /// A `BrokerConn` over a Unix-domain stream: one framed request out, the full framed reply back.
    pub struct UnixBrokerConn(pub UnixStream);

    impl BrokerConn for UnixBrokerConn {
        fn send_all(&mut self, frame: &[u8]) -> Result<(), TransportError> {
            self.0.write_all(frame).map_err(|_| TransportError::Io)?;
            self.0.flush().map_err(|_| TransportError::Io)
        }
        fn recv_all(&mut self) -> Result<Vec<u8>, TransportError> {
            // Audit F-32/F-36: this was an unbounded `read_to_end`. `ipc_framing` documents that the
            // declared length is checked against the cap BEFORE any read, but that check runs in
            // `decode_one` — i.e. AFTER these bytes are already resident — so the bound protected
            // nothing on the direction the desktop actually reads. Cap ingress here, at the read.
            let mut buf = Vec::new();
            let mut limited = (&mut self.0).take(MAX_REPLY_BYTES);
            limited.read_to_end(&mut buf).map_err(|_| TransportError::Io)?;
            if buf.len() as u64 >= MAX_REPLY_BYTES {
                // At the cap we cannot tell a legal maximal frame from a truncated flood, so refuse:
                // a reply this large is not one the bounded framing can produce.
                return Err(TransportError::Io);
            }
            Ok(buf)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Audit finding: `governed_turn_execute` returned the bare string `broker_unavailable` for BOTH
    /// "this platform has no broker client at all" and "the broker client exists and the connect
    /// failed" — so a caller could not tell "not implemented here" from a real transport failure, and
    /// neither from a broker that was reached and refused. On a host with no transport the reason must
    /// now SAY that, and must not be the generic unavailable reason.
    #[cfg(not(target_os = "linux"))]
    #[test]
    fn no_broker_transport_on_this_platform_says_so_and_is_not_broker_unavailable() {
        let err = governed_turn_execute(serde_json::json!({ "conversation_id": "c" }))
            .expect_err("a host with no broker transport cannot produce a broker reply");
        assert!(
            err.starts_with(BROKER_UNSUPPORTED),
            "reason must be prefixed `{BROKER_UNSUPPORTED}`, got: {err}"
        );
        assert!(
            !err.starts_with(BROKER_UNAVAILABLE),
            "`not implemented on this platform` must NOT masquerade as `{BROKER_UNAVAILABLE}`: {err}"
        );
        // It names the platform, so the reason is self-explaining in a log with no build context.
        assert!(err.contains(std::env::consts::OS), "reason must name the host OS: {err}");
        // And it says explicitly that no broker decided this turn.
        assert!(
            err.contains("no broker allowed or refused this turn"),
            "reason must distinguish itself from a broker refusal: {err}"
        );
    }

    /// The Linux counterpart: the transport IS implemented here, so a failure to reach the broker must
    /// report the *connect* failure (naming the socket and the io error kind) and must never claim the
    /// platform is unsupported.
    #[cfg(target_os = "linux")]
    #[test]
    fn linux_connect_failure_reports_the_transport_not_an_unsupported_platform() {
        // Precondition: no broker service is provisioned in a test environment.
        if std::path::Path::new(BROKER_SOCKET_PATH).exists() {
            return;
        }
        let err = governed_turn_execute(serde_json::json!({ "conversation_id": "c" }))
            .expect_err("no broker socket => no broker reply");
        assert!(
            err.starts_with(BROKER_UNAVAILABLE),
            "reason must be prefixed `{BROKER_UNAVAILABLE}`, got: {err}"
        );
        assert!(
            !err.starts_with(BROKER_UNSUPPORTED),
            "a host that HAS the transport must never claim `{BROKER_UNSUPPORTED}`: {err}"
        );
        assert!(err.contains(BROKER_SOCKET_PATH), "reason must name the socket it tried: {err}");
        assert!(err.contains("connect"), "reason must name the failed step: {err}");
    }

    /// The three non-decision prefixes must stay mutually distinguishable — a caller classifies on the
    /// prefix, so none may be a prefix of another.
    #[test]
    fn broker_failure_prefixes_are_mutually_distinguishable() {
        let all = [BROKER_UNSUPPORTED, BROKER_UNAVAILABLE, BROKER_TRANSPORT_FAILED];
        for (i, a) in all.iter().enumerate() {
            for (j, b) in all.iter().enumerate() {
                if i != j {
                    assert!(!a.starts_with(b), "`{a}` must not be classified as `{b}`");
                }
            }
        }
    }
}
