//! Wave 3b-1B — renderer→broker IPC client (design-GREEN rev-30 §4.10(g)). The thin Tauri proxy uses this
//! to forward the renderer's closed request frame to the trusted broker service and read back the framed
//! committed/blocked reply. The roundtrip logic is PURE (an injected [`BrokerConn`] transport), so it is
//! unit-tested without a socket; the real AF_UNIX (Linux) / named-pipe (Windows) connection is a thin
//! platform wrapper that implements [`BrokerConn`].

use crate::governed_turn_ipc::TurnReason;
use crate::ipc_framing::{decode_one, encode_frame, FrameError};

/// A single-request/single-response connection to the broker (one framed request out, one framed reply in).
pub trait BrokerConn {
    /// Send the exact bytes of one length-prefixed frame.
    fn send_all(&mut self, frame: &[u8]) -> Result<(), TransportError>;
    /// Receive the full reply (the broker writes exactly one framed reply then closes/half-closes).
    fn recv_all(&mut self) -> Result<Vec<u8>, TransportError>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TransportError {
    /// The connection could not be established or was reset.
    Unavailable,
    /// A frame could not be encoded/decoded (oversize/truncated).
    Frame(FrameError),
    /// The underlying send/recv failed.
    Io,
}

impl From<FrameError> for TransportError {
    fn from(e: FrameError) -> Self {
        TransportError::Frame(e)
    }
}

/// Forward one governed-turn request (the exact renderer request-frame JSON bytes) to the broker over
/// `conn` and return the broker's reply JSON bytes (the committed/blocked frame). Frames both directions
/// with the bounded length-prefix format. Never fabricates a reply — a transport failure is surfaced as
/// `Err` (the caller renders a `blocked` result, it never invents a committed one).
pub fn send_governed_turn(conn: &mut dyn BrokerConn, request_json: &[u8]) -> Result<Vec<u8>, TransportError> {
    let frame = encode_frame(request_json)?;
    conn.send_all(&frame)?;
    let reply = conn.recv_all()?;
    let payload = decode_one(&reply)?;
    Ok(payload.to_vec())
}

/// Map a transport failure to the closed renderer reason (`upstream_blocked`) — the broker's own
/// `record_pre_verification_block` is the durable authority; a lost connection is never a committed turn.
pub fn transport_failure_reason(_e: &TransportError) -> TurnReason {
    TurnReason::UpstreamBlocked
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::governed_turn_ipc::{RESULT_PROTOCOL, REQUEST_PROTOCOL};

    /// A fake broker that echoes a canned framed reply and captures what it received.
    struct FakeBroker {
        received: Vec<u8>,
        reply_payload: Vec<u8>,
        fail_send: bool,
    }
    impl BrokerConn for FakeBroker {
        fn send_all(&mut self, frame: &[u8]) -> Result<(), TransportError> {
            if self.fail_send {
                return Err(TransportError::Unavailable);
            }
            self.received = frame.to_vec();
            Ok(())
        }
        fn recv_all(&mut self) -> Result<Vec<u8>, TransportError> {
            Ok(encode_frame(&self.reply_payload).unwrap())
        }
    }

    #[test]
    fn roundtrips_a_request_and_returns_the_reply_payload() {
        let req = format!(r#"{{"protocol":"{REQUEST_PROTOCOL}"}}"#).into_bytes();
        let reply = format!(r#"{{"protocol":"{RESULT_PROTOCOL}","status":"committed"}}"#).into_bytes();
        let mut broker = FakeBroker { received: vec![], reply_payload: reply.clone(), fail_send: false };
        let got = send_governed_turn(&mut broker, &req).unwrap();
        assert_eq!(got, reply);
        // what the broker received was the length-prefixed request frame
        assert_eq!(decode_one(&broker.received).unwrap(), &req[..]);
    }

    #[test]
    fn a_send_failure_is_surfaced_not_fabricated() {
        let mut broker = FakeBroker { received: vec![], reply_payload: vec![], fail_send: true };
        let err = send_governed_turn(&mut broker, b"{}").unwrap_err();
        assert_eq!(err, TransportError::Unavailable);
        assert_eq!(transport_failure_reason(&err), TurnReason::UpstreamBlocked);
    }

    #[test]
    fn an_oversize_request_is_refused_before_send() {
        let big = vec![b'x'; crate::ipc_framing::MAX_FRAME_PAYLOAD_BYTES + 1];
        let mut broker = FakeBroker { received: vec![], reply_payload: vec![], fail_send: false };
        let err = send_governed_turn(&mut broker, &big).unwrap_err();
        assert!(matches!(err, TransportError::Frame(_)));
        assert!(broker.received.is_empty(), "nothing is sent when the request overflows the frame");
    }
}
