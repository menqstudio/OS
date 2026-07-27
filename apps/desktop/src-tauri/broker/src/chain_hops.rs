//! Wave 3b-1B — the broker's per-hop chain protocol clients (design-GREEN rev-30 §2.1/§5/§7). Each trusted
//! principal (challenge-authority, supervisor, isolated-signer) is a single-request/single-response
//! AF_UNIX peer; the broker speaks a bounded, length-prefixed JSON frame to each (reusing
//! `brops_core::ipc_framing`). This module is the PURE roundtrip + message layer — a hop is
//! `serialize(request) -> frame -> send -> recv -> parse(reply)` over an injected [`HopConn`], so every
//! protocol shape is unit-tested without a socket. The real Linux `AF_UNIX` connection is a thin wrapper
//! implementing [`HopConn`]; a lost/refusing hop is a closed error, never a fabricated success.

use brops_core::governed_turn_ipc::TurnReason;
use brops_core::ipc_framing::{decode_one, encode_frame, FrameError};

/// A single-request/single-response connection to one trusted principal.
pub trait HopConn {
    fn send_all(&mut self, frame: &[u8]) -> Result<(), HopError>;
    fn recv_all(&mut self) -> Result<Vec<u8>, HopError>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HopError {
    /// The principal socket was unreachable / reset.
    Unavailable,
    /// A frame could not be encoded/decoded (oversize/truncated).
    Frame(FrameError),
    /// The reply JSON was malformed or carried a refusal.
    BadReply,
    /// The principal returned a typed refusal (its `reason` field).
    Refused(String),
    Io,
}
impl From<FrameError> for HopError {
    fn from(e: FrameError) -> Self {
        HopError::Frame(e)
    }
}
impl HopError {
    /// Map any hop failure to the closed renderer-facing reason (a refusing/lost hop blocks the turn).
    pub fn to_turn_reason(&self) -> TurnReason {
        TurnReason::UpstreamBlocked
    }
}

/// One framed request→reply roundtrip to a principal. `request_json` is the exact request bytes; returns
/// the reply JSON bytes. Frames both directions with the bounded length-prefix; refuses an oversize
/// request before sending anything.
pub fn hop_roundtrip(conn: &mut dyn HopConn, request_json: &[u8]) -> Result<Vec<u8>, HopError> {
    let frame = encode_frame(request_json)?;
    conn.send_all(&frame)?;
    let reply = conn.recv_all()?;
    Ok(decode_one(&reply)?.to_vec())
}

/// Parse a principal reply object, returning its `status` (or `Refused(reason)` when the principal refused,
/// or `BadReply` on a malformed frame). A tiny stdlib-free JSON probe kept deliberately minimal — the
/// broker only needs the `status`/`reason` discriminants here; the full typed payloads are parsed by the
/// specific hop callers with serde_json in the assembly layer.
pub fn reply_status(reply_json: &[u8]) -> Result<String, HopError> {
    let v: serde_json::Value = serde_json::from_slice(reply_json).map_err(|_| HopError::BadReply)?;
    let obj = v.as_object().ok_or(HopError::BadReply)?;
    if let Some(reason) = obj.get("reason").and_then(|r| r.as_str()) {
        return Err(HopError::Refused(reason.to_string()));
    }
    obj.get("status")
        .and_then(|s| s.as_str())
        .map(|s| s.to_string())
        .ok_or(HopError::BadReply)
}

/// The three trusted principals of the governed chain, in order (§2.1 → §5 → §7). Used to label a hop
/// failure and to select the socket in the Linux transport.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Principal {
    ChallengeAuthority,
    Supervisor,
    IsolatedSigner,
}

impl Principal {
    pub fn as_str(self) -> &'static str {
        match self {
            Principal::ChallengeAuthority => "challenge_authority",
            Principal::Supervisor => "supervisor",
            Principal::IsolatedSigner => "isolated_signer",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use brops_core::ipc_framing::MAX_FRAME_PAYLOAD_BYTES;

    struct FakeHop {
        received: Vec<u8>,
        reply: Vec<u8>,
        fail: bool,
    }
    impl HopConn for FakeHop {
        fn send_all(&mut self, frame: &[u8]) -> Result<(), HopError> {
            if self.fail {
                return Err(HopError::Unavailable);
            }
            self.received = frame.to_vec();
            Ok(())
        }
        fn recv_all(&mut self) -> Result<Vec<u8>, HopError> {
            Ok(encode_frame(&self.reply).unwrap())
        }
    }

    #[test]
    fn roundtrips_a_hop_request_and_reply() {
        let req = br#"{"protocol":"brops.governed-turn-open.v1"}"#;
        let reply = br#"{"status":"lease_ready","lease_id":"L1"}"#;
        let mut hop = FakeHop { received: vec![], reply: reply.to_vec(), fail: false };
        let got = hop_roundtrip(&mut hop, req).unwrap();
        assert_eq!(got, reply);
        assert_eq!(decode_one(&hop.received).unwrap(), &req[..]);
        assert_eq!(reply_status(&got).unwrap(), "lease_ready");
    }

    #[test]
    fn a_refusing_principal_surfaces_its_reason() {
        let reply = br#"{"reason":"challenge_expired"}"#;
        assert_eq!(reply_status(reply), Err(HopError::Refused("challenge_expired".into())));
    }

    #[test]
    fn a_malformed_reply_is_bad_reply() {
        assert_eq!(reply_status(b"not json"), Err(HopError::BadReply));
        assert_eq!(reply_status(b"{}"), Err(HopError::BadReply)); // no status, no reason
    }

    #[test]
    fn an_unavailable_hop_is_surfaced_not_fabricated() {
        let mut hop = FakeHop { received: vec![], reply: vec![], fail: true };
        let err = hop_roundtrip(&mut hop, b"{}").unwrap_err();
        assert_eq!(err, HopError::Unavailable);
        assert_eq!(err.to_turn_reason(), TurnReason::UpstreamBlocked);
    }

    #[test]
    fn an_oversize_request_is_refused_before_send() {
        let big = vec![b'x'; MAX_FRAME_PAYLOAD_BYTES + 1];
        let mut hop = FakeHop { received: vec![], reply: vec![], fail: false };
        assert!(matches!(hop_roundtrip(&mut hop, &big), Err(HopError::Frame(_))));
        assert!(hop.received.is_empty());
    }

    #[test]
    fn principal_labels() {
        assert_eq!(Principal::ChallengeAuthority.as_str(), "challenge_authority");
        assert_eq!(Principal::Supervisor.as_str(), "supervisor");
        assert_eq!(Principal::IsolatedSigner.as_str(), "isolated_signer");
    }
}
