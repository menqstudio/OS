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

/// Parse a principal reply object against the ONE reply contract the three trusted principals actually
/// speak, and return the success object.
///
/// The contract, as shipped by `engine/runtime/{challenge_authority,governed_supervisor,isolated_signer}
/// _server.py::dispatch` and by their Rust twins in `brops_win_live::servers`:
///
///   * success  ⇒ `{"ok": true,  "op": <the op that was requested>, ...}`
///   * refusal  ⇒ `{"ok": false, "op": <op>, "reason": <typed REFUSE_* string>, ...}`
///   * anything else is malformed.
///
/// This function used to be `reply_status`, and it read a `status` field. **No server has ever emitted
/// one.** It was green because its only callers were its own tests, which hand-built `{"status":
/// "lease_ready"}` — a double whose shape was invented rather than derived from the thing it doubles.
/// That is the same defect class that made the first live ladder run go RED (the isolated-signer
/// transport shipped a reply shape its own tests never used), so the parser is now the shape the servers
/// send, and it is the parser the production path calls — there is no second one to drift from.
///
/// `expected_op` is checked, not merely echoed: every principal returns the op it handled, so a reply
/// belonging to a different op on a single-request/single-response channel is a broken peer, not a
/// success. Nothing enforced that before.
pub fn parse_reply(expected_op: &str, reply_json: &[u8]) -> Result<serde_json::Value, HopError> {
    let v: serde_json::Value = serde_json::from_slice(reply_json).map_err(|_| HopError::BadReply)?;
    let obj = v.as_object().ok_or(HopError::BadReply)?;
    // A reply is a success ONLY if it says so. Missing / non-boolean / false `ok` is never a success.
    if obj.get("ok").and_then(serde_json::Value::as_bool) != Some(true) {
        if let Some(reason) = obj.get("reason").and_then(|r| r.as_str()) {
            return Err(HopError::Refused(reason.to_string()));
        }
        return Err(HopError::BadReply);
    }
    if obj.get("op").and_then(|o| o.as_str()) != Some(expected_op) {
        return Err(HopError::BadReply);
    }
    Ok(v)
}

/// The three trusted principals of the governed chain, in order (§2.1 → §5 → §7). Used to label a hop
/// failure and to select the socket in the Linux transport.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
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

    /// The exact success reply `governed_supervisor_server._op_accept_open` returns:
    /// `{"ok": True, "op": OP_ACCEPT_OPEN, "lease": {...}}`.
    #[test]
    fn roundtrips_a_hop_request_and_reply() {
        let req = br#"{"op":"accept-open","challenge_doc":{}}"#;
        let reply = br#"{"ok":true,"op":"accept-open","lease":{"lease_id":"L1"}}"#;
        let mut hop = FakeHop { received: vec![], reply: reply.to_vec(), fail: false };
        let got = hop_roundtrip(&mut hop, req).unwrap();
        assert_eq!(got, reply);
        assert_eq!(decode_one(&hop.received).unwrap(), &req[..]);
        let parsed = parse_reply("accept-open", &got).unwrap();
        assert_eq!(parsed["lease"]["lease_id"], "L1");
    }

    /// The exact refusal `governed_supervisor_server._refusal` returns.
    #[test]
    fn a_refusing_principal_surfaces_its_reason() {
        let reply = br#"{"ok":false,"op":"accept-open","reason":"challenge_expired","detail":"x","error":"x"}"#;
        assert_eq!(
            parse_reply("accept-open", reply),
            Err(HopError::Refused("challenge_expired".into()))
        );
    }

    /// The pre-2026-08-12 parser read a `status` field. NO server emits one, so a reply carrying
    /// only `status` must now be malformed — this test fails if that parser is ever restored.
    #[test]
    fn the_invented_status_shape_is_not_a_success() {
        assert_eq!(parse_reply("accept-open", br#"{"status":"lease_ready"}"#), Err(HopError::BadReply));
    }

    #[test]
    fn a_malformed_reply_is_bad_reply() {
        assert_eq!(parse_reply("issue", b"not json"), Err(HopError::BadReply));
        assert_eq!(parse_reply("issue", b"{}"), Err(HopError::BadReply)); // no ok, no reason
        // `ok:false` with no typed reason is malformed, never a silent success.
        assert_eq!(parse_reply("issue", br#"{"ok":false,"op":"issue"}"#), Err(HopError::BadReply));
        // A well-formed-looking reply that simply never SAYS it succeeded. `ok` must be
        // present and boolean `true`; absent-or-not-a-bool is not a success, and a check
        // written as "refuse only when ok is literally false" would let both through.
        assert_eq!(parse_reply("issue", br#"{"op":"issue"}"#), Err(HopError::BadReply));
        assert_eq!(parse_reply("issue", br#"{"ok":"true","op":"issue"}"#), Err(HopError::BadReply));
        assert_eq!(parse_reply("issue", br#"{"ok":1,"op":"issue"}"#), Err(HopError::BadReply));
        assert_eq!(parse_reply("issue", br#"{"ok":null,"op":"issue"}"#), Err(HopError::BadReply));
        // A success that is not a JSON object.
        assert_eq!(parse_reply("issue", b"[]"), Err(HopError::BadReply));
    }

    /// A reply that answers a DIFFERENT op is a broken peer on a single-request/single-response
    /// channel, not a success. (Nothing checked this before.)
    #[test]
    fn a_reply_for_another_op_is_refused() {
        let reply = br#"{"ok":true,"op":"launch-gate","proceed":true}"#;
        assert_eq!(parse_reply("accept-open", reply), Err(HopError::BadReply));
        // ... and a success with no `op` at all.
        assert_eq!(parse_reply("accept-open", br#"{"ok":true}"#), Err(HopError::BadReply));
    }

    /// The full set of ops the broker sends, each answered by its own principal's success shape.
    /// Listed here so adding a hop without adding its reply shape is visible.
    #[test]
    fn every_broker_op_parses_its_own_principals_success_reply() {
        for op in [
            "create-pending",
            "issue",
            "accept-open",
            "launch-gate",
            "execution-started",
            "complete-run",
            "attest-run",
            "sign-result",
        ] {
            let reply = format!(r#"{{"ok":true,"op":"{op}"}}"#);
            assert!(parse_reply(op, reply.as_bytes()).is_ok(), "op {op} must parse");
        }
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
