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
use std::io::Read;
use std::time::Duration;

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
///
/// "Buffered by design" is a settled decision rather than an accident of this slice, and as of
/// 2026-08-09 the roadmap agrees with it: MASTER_EXECUTION_ROADMAP Phase 1 **descopes** governed
/// delta-streaming. The desktop's sole authority over a governed reply is the isolated signer's
/// envelope, and that envelope binds `output_bytes` + `output_sha256` over the WHOLE output. There
/// is no per-delta signature and no contract that could produce one, so a streamed delta would be
/// unverified content displayed before any verdict exists — the exact inverse of "no verified
/// signature ⇒ no result". The channel underneath says the same thing structurally: one framed
/// request, one framed reply.
///
/// Do not read `brops_core::governed_output_stream` as the streaming that is missing here. That is
/// the rev-30 §4.10(f) ladder for PULLING the completed output of a buffered turn in chunks when it
/// is too large to ride the reply frame; it moves finished bytes, checked against the same
/// whole-output digest. It has no production caller and is declared in
/// `config/reachability-declarations.json`.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const IO_TIMEOUT_MS: u64 = 120_000;

/// Total wall-clock budget for ONE broker exchange, measured from the moment the connection is
/// handed back — the bound [`IO_TIMEOUT_MS`] does not provide.
///
/// **`IO_TIMEOUT_MS` is per SYSCALL, and that is not a bound on the command.** `SO_RCVTIMEO` restarts
/// on every byte that arrives, so a peer that answers one byte every 119 seconds never times out.
/// With [`MAX_REPLY_BYTES`] = 8256 the previous read loop would sit there for 8256 × 120 s ≈ **11.5
/// days**, holding a synchronous Tauri command, and every check in the file was satisfied throughout:
/// the per-read deadline was armed, the ingress cap was armed, and neither could fire. That is the
/// audit's F-32/F-36 remediation being true and not sufficient (remediation audit R-38).
///
/// This is the budget for the whole exchange, not for a step of it, so no number of well-timed
/// dribbles can extend it. It is deliberately the same 120 s: an exchange that has not completed in
/// the time one read was already allowed to take is a transport failure, and a transport failure the
/// renderer renders as `blocked` is the honest outcome. A wedged command is not.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const EXCHANGE_BUDGET_MS: u64 = 120_000;

/// How long the NEXT socket operation may block, given how much of the budget is already spent.
///
/// `None` means the budget is gone and the caller must fail the exchange. **Returning `None` at
/// exactly zero is load-bearing, not a rounding preference:** POSIX `SO_RCVTIMEO` reads a zero
/// timeout as "block forever", and `std` rejects `Duration::ZERO` for that reason — so a caller that
/// armed the remainder without this guard would either error out or, worse, arm no timeout at all at
/// the precise moment the budget ran out. Every `Some` is strictly positive.
///
/// Pure, and deliberately outside the `#[cfg(target_os = "linux")]` module below: the previous
/// version of this bound lived entirely inside that module, where no test on any other platform could
/// reach it, so breaking it changed nothing that any suite could observe.
#[cfg_attr(not(any(target_os = "linux", test)), allow(dead_code))]
fn next_io_timeout(elapsed: Duration, budget: Duration) -> Option<Duration> {
    let remaining = budget.checked_sub(elapsed)?;
    if remaining.is_zero() {
        return None;
    }
    Some(remaining)
}

/// Read one framed broker reply: bounded in BYTES by `max_bytes` and in TIME by `budget`, with the
/// remaining budget re-armed on the socket before every read.
///
/// Generic over the reader and over both effects (`arm_timeout`, `elapsed`) so the loop that enforces
/// the deadline is ordinary, platform-independent code that a test can drive with a fake clock and a
/// dribbling reader. The Linux socket implementation below is then a three-line adapter with no logic
/// of its own to get wrong.
///
/// A read returning `Ok(0)` is the peer closing the stream, which is how a complete framed reply
/// ends here (one request, one reply, then EOF).
#[cfg_attr(not(any(target_os = "linux", test)), allow(dead_code))]
fn read_bounded<R: Read>(
    reader: &mut R,
    mut arm_timeout: impl FnMut(Duration) -> std::io::Result<()>,
    mut elapsed: impl FnMut() -> Duration,
    budget: Duration,
    max_bytes: u64,
) -> Result<Vec<u8>, TransportError> {
    let mut buf = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        // The budget is checked BEFORE arming, so an expired exchange fails here rather than being
        // handed to the kernel as "no timeout".
        let remaining = next_io_timeout(elapsed(), budget).ok_or(TransportError::Io)?;
        arm_timeout(remaining).map_err(|_| TransportError::Io)?;
        let n = reader.read(&mut chunk).map_err(|_| TransportError::Io)?;
        if n == 0 {
            return Ok(buf);
        }
        if buf.len() as u64 + n as u64 >= max_bytes {
            // At the cap we cannot tell a legal maximal frame from a truncated flood, so refuse:
            // a reply this large is not one the bounded framing can produce.
            return Err(TransportError::Io);
        }
        buf.extend_from_slice(&chunk[..n]);
    }
}

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
        Ok(Box::new(linux::UnixBrokerConn::new(s)) as Box<dyn BrokerConn>)
    }
    #[cfg(not(target_os = "linux"))]
    {
        Err(BrokerAccessError::UnsupportedPlatform)
    }
}

#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use std::io::Write;
    use std::os::unix::net::UnixStream;
    use std::time::Instant;

    /// A `BrokerConn` over a Unix-domain stream: one framed request out, the full framed reply back —
    /// the whole exchange inside a single [`EXCHANGE_BUDGET_MS`] budget started at `opened`.
    pub struct UnixBrokerConn {
        stream: UnixStream,
        opened: Instant,
    }

    impl UnixBrokerConn {
        pub fn new(stream: UnixStream) -> UnixBrokerConn {
            UnixBrokerConn { stream, opened: Instant::now() }
        }

        /// Whatever is left of the exchange budget, or a transport failure.
        fn remaining(&self) -> Result<Duration, TransportError> {
            next_io_timeout(self.opened.elapsed(), Duration::from_millis(EXCHANGE_BUDGET_MS))
                .ok_or(TransportError::Io)
        }
    }

    impl BrokerConn for UnixBrokerConn {
        fn send_all(&mut self, frame: &[u8]) -> Result<(), TransportError> {
            let remaining = self.remaining()?;
            self.stream.set_write_timeout(Some(remaining)).map_err(|_| TransportError::Io)?;
            self.stream.write_all(frame).map_err(|_| TransportError::Io)?;
            self.stream.flush().map_err(|_| TransportError::Io)
        }
        fn recv_all(&mut self) -> Result<Vec<u8>, TransportError> {
            // Audit F-32/F-36: this was an unbounded `read_to_end`. `ipc_framing` documents that the
            // declared length is checked against the cap BEFORE any read, but that check runs in
            // `decode_one` — i.e. AFTER these bytes are already resident — so the bound protected
            // nothing on the direction the desktop actually reads. Cap ingress here, at the read.
            //
            // Remediation audit R-38: the byte cap and the per-read deadline together still allowed a
            // dribbling peer ~11.5 days. The loop, the deadline arithmetic and the cap now live in
            // `read_bounded` / `next_io_timeout` above — outside this Linux-only module, where a test
            // on any platform can drive them — and this is the socket adapter.
            let opened = self.opened;
            let socket = &self.stream;
            let mut reader = &self.stream;
            read_bounded(
                &mut reader,
                |remaining| socket.set_read_timeout(Some(remaining)),
                || opened.elapsed(),
                Duration::from_millis(EXCHANGE_BUDGET_MS),
                MAX_REPLY_BYTES,
            )
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---- The exchange budget (remediation audit R-38) ------------------------------------------
    //
    // These run on EVERY platform. The bound they lock used to live inside `mod linux`, where no
    // suite on any other host could reach it: deleting it there was invisible to `cargo test` on
    // Windows and macOS, and the Linux job that could see it had no test to fail.

    /// A reader that hands back one byte per call, forever — the drip peer R-38 describes.
    struct Dribble;
    impl Read for Dribble {
        fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
            buf[0] = b'x';
            Ok(1)
        }
    }

    /// A reader that returns `body` once and then EOF — a well-behaved broker.
    struct OneShot(Vec<u8>);
    impl Read for OneShot {
        fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
            if self.0.is_empty() {
                return Ok(0);
            }
            let n = self.0.len().min(buf.len());
            buf[..n].copy_from_slice(&self.0[..n]);
            self.0.drain(..n);
            Ok(n)
        }
    }

    /// A clock that advances by `step` every time it is asked — one tick per socket read, so a peer
    /// that answers just before each per-read deadline is exactly the caller who never times out.
    fn ticking_clock(step: Duration) -> impl FnMut() -> Duration {
        let mut now = Duration::ZERO;
        move || {
            let t = now;
            now += step;
            t
        }
    }

    #[test]
    fn a_dribbling_peer_is_cut_off_by_the_exchange_budget_not_after_eleven_days() {
        let budget = Duration::from_millis(EXCHANGE_BUDGET_MS);
        // The peer answers one byte just inside every per-read deadline. Under the per-syscall bound
        // alone this loop runs until MAX_REPLY_BYTES bytes have arrived — 8256 × 120 s ≈ 11.5 days.
        let mut reads = 0usize;
        let mut r = Dribble;
        let out = read_bounded(
            &mut r,
            |_| Ok(()),
            ticking_clock(Duration::from_millis(EXCHANGE_BUDGET_MS / 4)),
            budget,
            MAX_REPLY_BYTES,
        );
        assert!(out.is_err(), "a peer that never finishes must fail the exchange");
        // And it gave up on TIME, long before the byte cap: at a quarter of the budget per read the
        // exchange dies after a handful of reads, not after 8256 of them.
        let mut r = Dribble;
        let _ = read_bounded(
            &mut r,
            |_| {
                reads += 1;
                Ok(())
            },
            ticking_clock(Duration::from_millis(EXCHANGE_BUDGET_MS / 4)),
            budget,
            MAX_REPLY_BYTES,
        );
        assert!(
            reads <= 5,
            "the budget must end the exchange in a few reads, not {reads} (cap is {MAX_REPLY_BYTES})"
        );
    }

    #[test]
    fn a_prompt_broker_reply_is_read_whole() {
        let body = b"{\"status\":\"blocked\"}".to_vec();
        let mut r = OneShot(body.clone());
        let got = read_bounded(
            &mut r,
            |_| Ok(()),
            ticking_clock(Duration::from_millis(1)),
            Duration::from_millis(EXCHANGE_BUDGET_MS),
            MAX_REPLY_BYTES,
        )
        .expect("a broker that answers promptly is not a transport failure");
        assert_eq!(got, body);
    }

    #[test]
    fn a_reply_at_the_ingress_cap_is_refused() {
        let mut r = OneShot(vec![b'x'; (MAX_REPLY_BYTES as usize) + 1]);
        let got = read_bounded(
            &mut r,
            |_| Ok(()),
            ticking_clock(Duration::from_millis(1)),
            Duration::from_millis(EXCHANGE_BUDGET_MS),
            MAX_REPLY_BYTES,
        );
        assert!(got.is_err(), "a reply larger than the framing can produce must be refused");
    }

    /// `SO_RCVTIMEO` reads zero as "block forever", so the one value this must never hand a socket is
    /// `Duration::ZERO` — the exact value naive `budget - elapsed` produces at the instant the budget
    /// runs out, i.e. the moment the bound is most needed.
    #[test]
    fn the_remaining_budget_is_never_armed_as_zero() {
        let budget = Duration::from_millis(EXCHANGE_BUDGET_MS);
        assert_eq!(next_io_timeout(budget, budget), None, "a spent budget must refuse, not arm 0");
        assert_eq!(next_io_timeout(budget + Duration::from_secs(1), budget), None);
        for spent_ms in [0u64, 1, EXCHANGE_BUDGET_MS / 2, EXCHANGE_BUDGET_MS - 1] {
            let left = next_io_timeout(Duration::from_millis(spent_ms), budget)
                .expect("budget remains at {spent_ms}ms spent");
            assert!(!left.is_zero(), "armed a zero timeout at {spent_ms}ms spent");
        }
        let mut armed_zero = false;
        let mut r = Dribble;
        let _ = read_bounded(
            &mut r,
            |remaining| {
                armed_zero |= remaining.is_zero();
                Ok(())
            },
            ticking_clock(Duration::from_millis(EXCHANGE_BUDGET_MS / 3)),
            Duration::from_millis(EXCHANGE_BUDGET_MS),
            MAX_REPLY_BYTES,
        );
        assert!(!armed_zero, "the read loop armed a zero (= infinite) socket timeout");
    }

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
