//! Wave 3b-1B — governed-chain IPC framing + peer authentication (design-GREEN rev-30 §2.1/§4.10(g)
//! transport layer). The trusted-principal AF_UNIX channels (renderer→broker, broker→authority,
//! broker→supervisor→signer) all share ONE bounded, length-prefixed frame format and ONE peer-auth rule:
//! authenticate the connecting peer's OS credentials (`SO_PEERCRED` on Linux) and allowlist EXACTLY the
//! expected principal UID, denying every other — the renderer/login UID and the sidecar UID in particular.
//!
//! This module is the PURE, host-independent framing + peer-auth core (fully unit-tested). The real socket
//! `bind`/`accept`/`recv` + the `SO_PEERCRED` read are a thin Linux-gated wrapper that populates
//! [`PeerCred`] from the kernel and calls [`authorize_peer`]; keeping the decision logic pure means every
//! bound/malformed/wrong-peer rule is testable without a socket.

/// The maximum accepted frame payload (bytes). A frame declaring more is refused before allocation — a
/// bounded ingress that cannot be used to exhaust memory. Matches the renderer↔broker 8 KiB cap and the
/// authority reply cap; the larger staged inputs travel as store handles, never inline (rev-30 §2.4).
pub const MAX_FRAME_PAYLOAD_BYTES: usize = 8192;

/// The fixed length-prefix width (bytes, big-endian u32).
pub const LENGTH_PREFIX_BYTES: usize = 4;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FrameError {
    /// The payload exceeds [`MAX_FRAME_PAYLOAD_BYTES`].
    Oversize(usize),
    /// The buffer is shorter than the declared frame (need more bytes / truncated).
    Truncated,
    /// The length prefix declares a payload over the cap (rejected before allocation).
    DeclaredOversize(usize),
    /// Bytes remain after a complete frame where exactly one was expected.
    TrailingBytes,
}

/// Encode `payload` as a length-prefixed frame: `u32 big-endian length || payload`. Fails closed if the
/// payload exceeds the cap.
pub fn encode_frame(payload: &[u8]) -> Result<Vec<u8>, FrameError> {
    if payload.len() > MAX_FRAME_PAYLOAD_BYTES {
        return Err(FrameError::Oversize(payload.len()));
    }
    let mut out = Vec::with_capacity(LENGTH_PREFIX_BYTES + payload.len());
    out.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    out.extend_from_slice(payload);
    Ok(out)
}

/// Decode EXACTLY ONE frame from `buf`, returning its payload slice. The buffer must contain exactly the
/// length prefix + that many payload bytes and nothing more (a single-request/single-response channel).
/// The declared length is validated against the cap BEFORE any read, so an attacker-declared huge length
/// is refused without allocation.
pub fn decode_one(buf: &[u8]) -> Result<&[u8], FrameError> {
    if buf.len() < LENGTH_PREFIX_BYTES {
        return Err(FrameError::Truncated);
    }
    let declared = u32::from_be_bytes([buf[0], buf[1], buf[2], buf[3]]) as usize;
    if declared > MAX_FRAME_PAYLOAD_BYTES {
        return Err(FrameError::DeclaredOversize(declared));
    }
    let end = LENGTH_PREFIX_BYTES + declared;
    if buf.len() < end {
        return Err(FrameError::Truncated);
    }
    if buf.len() > end {
        return Err(FrameError::TrailingBytes);
    }
    Ok(&buf[LENGTH_PREFIX_BYTES..end])
}

/// A streaming frame accumulator for a real socket read loop: feed it received bytes; it yields complete
/// frame payloads one at a time and buffers the remainder. Fails closed on a declared-oversize length.
#[derive(Debug, Default)]
pub struct FrameDecoder {
    buf: Vec<u8>,
}

impl FrameDecoder {
    pub fn new() -> Self {
        FrameDecoder { buf: Vec::new() }
    }

    /// Append received bytes.
    pub fn feed(&mut self, bytes: &[u8]) {
        self.buf.extend_from_slice(bytes);
    }

    /// Pop the next complete frame payload, or None if not yet complete. `Err` on a declared-oversize
    /// length (fail closed — the caller must drop the connection).
    pub fn next_frame(&mut self) -> Result<Option<Vec<u8>>, FrameError> {
        if self.buf.len() < LENGTH_PREFIX_BYTES {
            return Ok(None);
        }
        let declared = u32::from_be_bytes([self.buf[0], self.buf[1], self.buf[2], self.buf[3]]) as usize;
        if declared > MAX_FRAME_PAYLOAD_BYTES {
            return Err(FrameError::DeclaredOversize(declared));
        }
        let end = LENGTH_PREFIX_BYTES + declared;
        if self.buf.len() < end {
            return Ok(None);
        }
        let payload = self.buf[LENGTH_PREFIX_BYTES..end].to_vec();
        self.buf.drain(..end);
        Ok(Some(payload))
    }
}

/// OS peer credentials of a connected AF_UNIX peer (from `SO_PEERCRED` on Linux). The real read is a
/// thin Linux-gated wrapper; this struct is what the pure auth rule consumes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PeerCred {
    pub uid: u32,
    pub gid: u32,
    pub pid: i32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PeerError {
    /// The peer UID is explicitly on the deny list (e.g. the renderer/login or sidecar UID).
    Denied(u32),
    /// The peer UID is not the single allowed principal UID.
    NotAllowed(u32),
}

/// Authorize a connecting peer: it MUST be exactly `allowed_uid` and MUST NOT be a `denied` UID. This is
/// the rev-30 §2.1 rule — the challenge-authority channel allowlists ONLY the broker UID and DENIES the
/// renderer/login and sidecar UIDs; the same shape guards every trusted-principal channel.
pub fn authorize_peer(peer: &PeerCred, allowed_uid: u32, denied: &[u32]) -> Result<(), PeerError> {
    if denied.contains(&peer.uid) {
        return Err(PeerError::Denied(peer.uid));
    }
    if peer.uid != allowed_uid {
        return Err(PeerError::NotAllowed(peer.uid));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encode_decode_roundtrip() {
        let payload = br#"{"protocol":"brops.renderer-governed-turn.v1"}"#;
        let frame = encode_frame(payload).unwrap();
        assert_eq!(decode_one(&frame).unwrap(), payload);
    }

    #[test]
    fn encode_rejects_oversize_payload() {
        let big = vec![0u8; MAX_FRAME_PAYLOAD_BYTES + 1];
        assert_eq!(encode_frame(&big), Err(FrameError::Oversize(big.len())));
    }

    #[test]
    fn decode_rejects_truncated_and_trailing_and_declared_oversize() {
        let frame = encode_frame(b"hi").unwrap();
        assert_eq!(decode_one(&frame[..3]), Err(FrameError::Truncated)); // short prefix
        assert_eq!(decode_one(&frame[..5]), Err(FrameError::Truncated)); // short payload
        let mut trailing = frame.clone();
        trailing.push(0xff);
        assert_eq!(decode_one(&trailing), Err(FrameError::TrailingBytes));
        // a length prefix claiming a huge payload is refused before allocation
        let mut evil = (u32::MAX).to_be_bytes().to_vec();
        evil.extend_from_slice(b"x");
        assert_eq!(decode_one(&evil), Err(FrameError::DeclaredOversize(u32::MAX as usize)));
    }

    #[test]
    fn streaming_decoder_yields_frames_across_chunks() {
        let f1 = encode_frame(b"first").unwrap();
        let f2 = encode_frame(b"second").unwrap();
        let mut d = FrameDecoder::new();
        d.feed(&f1[..2]); // partial prefix
        assert_eq!(d.next_frame().unwrap(), None);
        d.feed(&f1[2..]); // rest of frame 1
        assert_eq!(d.next_frame().unwrap(), Some(b"first".to_vec()));
        d.feed(&f2);
        assert_eq!(d.next_frame().unwrap(), Some(b"second".to_vec()));
        assert_eq!(d.next_frame().unwrap(), None);
    }

    #[test]
    fn streaming_decoder_fails_closed_on_declared_oversize() {
        let mut d = FrameDecoder::new();
        d.feed(&(u32::MAX).to_be_bytes());
        assert_eq!(d.next_frame(), Err(FrameError::DeclaredOversize(u32::MAX as usize)));
    }

    #[test]
    fn peer_auth_allows_only_broker_denies_renderer_and_sidecar() {
        const BROKER: u32 = 5002;
        const RENDERER: u32 = 1000;
        const SIDECAR: u32 = 5004;
        let denied = [RENDERER, SIDECAR];
        assert!(authorize_peer(&PeerCred { uid: BROKER, gid: 0, pid: 10 }, BROKER, &denied).is_ok());
        assert_eq!(authorize_peer(&PeerCred { uid: RENDERER, gid: 0, pid: 11 }, BROKER, &denied), Err(PeerError::Denied(RENDERER)));
        assert_eq!(authorize_peer(&PeerCred { uid: SIDECAR, gid: 0, pid: 12 }, BROKER, &denied), Err(PeerError::Denied(SIDECAR)));
        assert_eq!(authorize_peer(&PeerCred { uid: 9999, gid: 0, pid: 13 }, BROKER, &denied), Err(PeerError::NotAllowed(9999)));
    }
}
