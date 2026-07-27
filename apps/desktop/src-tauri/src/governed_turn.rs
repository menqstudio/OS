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

/// Forward one governed turn to the broker service and return its committed/blocked reply. The renderer
/// supplies only the closed request; the broker resolves everything else and is the sole author of the
/// reply.
#[tauri::command]
pub fn governed_turn_execute(request: serde_json::Value) -> Result<serde_json::Value, String> {
    let request_json = serde_json::to_vec(&request).map_err(|_| "malformed_request".to_string())?;
    let mut conn = connect_broker().map_err(|_| "broker_unavailable".to_string())?;
    let reply = send_governed_turn(conn.as_mut(), &request_json)
        .map_err(|e: TransportError| format!("{:?}", e))?;
    serde_json::from_slice(&reply).map_err(|_| "malformed_broker_reply".to_string())
}

/// Connect to the broker over the platform IPC. Linux = AF_UNIX; every other host fails closed (the
/// Windows §0.W named-pipe broker is a separately-audited slice), so governed real-mode is unavailable
/// there rather than silently degraded.
fn connect_broker() -> Result<Box<dyn BrokerConn>, ()> {
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::net::UnixStream;
        UnixStream::connect(BROKER_SOCKET_PATH)
            .map(|s| Box::new(linux::UnixBrokerConn(s)) as Box<dyn BrokerConn>)
            .map_err(|_| ())
    }
    #[cfg(not(target_os = "linux"))]
    {
        Err(())
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
            let mut buf = Vec::new();
            self.0.read_to_end(&mut buf).map_err(|_| TransportError::Io)?;
            Ok(buf)
        }
    }
}
