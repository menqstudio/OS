//! Wave 3b-1B — the DESKTOP half of the rev-30 §4.10(f) chunked output pull.
//!
//! The supervisor half of §4.10(f) lives in the engine (`engine/runtime/governed_output_read.py` +
//! `governed_output_stream.py`): it owns the `governed_output_streams` table, mints the capability at
//! completion, and serves one immutable byte range per request to the SIDECAR principal. This module is
//! the other end of that round trip — the loop that drives it, the reassembly, and the §4.6/§7.1
//! whole-output gate that decides whether the reassembled bytes are the bytes the isolated signer signed.
//!
//! It is **pure**. No socket, no subprocess, no clock, no store. The one round trip is an injected
//! `fetch` closure, exactly as `governed_verification` injects its ledger and its clock, so the whole
//! ordered loop is unit-testable on any host and the transport adapter above it has no logic of its own.
//!
//! ## The one thing this module exists to make impossible
//!
//! §4.10(e)'s frame carries `output_bytes` and `output_sha256`, and §4.10(e) says of them, twice, that
//! they are **TRANSPORT-ONLY**. §4.6/§7.1 put the real values in the isolated signer's envelope. A pull
//! that reassembled bytes and then compared them against the *transport's* echo of their own digest would
//! be a check that cannot fail — a compromised sidecar supplies both sides of it — and "a check that
//! reads as protection while protecting nothing" is the defect class this repository keeps producing.
//!
//! So the expected length and the expected digest are **not parameters of this API**. [`pull_output`]
//! takes a [`ReceiptEnvelope`] and reads them off it, and [`OutputStreamCapability::from_envelope`] takes
//! the same envelope for `receipt_id`/`execution_attempt_id`. The only value that enters from the wire is
//! the 43-character capability token itself — which §4.10(f) binds server-side, so presenting the wrong
//! one yields `stream_binding_mismatch` from the supervisor rather than a silent cross-turn read. There
//! is deliberately no constructor that accepts a bare `output_bytes: u64`, so the transport echo cannot
//! be passed here even by mistake.
//!
//! ## What the loop is driven BY, and why it matters
//!
//! The chunk count comes from the **signed** `envelope.output_bytes`:
//! `max(1, ceil(output_bytes / 184320))`. The `max(1)` is §4.10(f)'s zero-byte contract, not defensive
//! habit — "when `output_bytes == 0` … a read with `seq == 0` returns `ok:true, bytes_b64:"", eof:true`" —
//! so an empty output is one legal read rather than a special path a caller might get wrong. Empty is a
//! contract, never an absence.
//!
//! Driving on a signed count rather than on the proxy's `eof` flag means the transport cannot decide how
//! long the loop runs. `eof` is then *checked* against the expected last `seq` instead of trusted: a
//! sidecar that flips it early or late is a disagreement with a signed value, and it Blocks.
//!
//! ## The checks that can fire, and the ones deliberately absent
//!
//! Every gate below was kept because a legal-looking reply can trip it, and the ones that could not fire
//! were not written:
//!
//!  * `output_bytes > 8388608` ⇒ [`PullError::OutputTooLarge`], **before any allocation**. The envelope is
//!    signed, but a signature makes a value authentic, not sane; §4.10(f) bounds the output at 8 MiB and
//!    a signer that emitted more would otherwise get this process to reserve it.
//!  * echo mismatch on `output_stream_id`/`seq` ⇒ [`PullError::EchoMismatch`]. The supervisor echoes the
//!    request; a proxy that answered `seq 3` to a request for `seq 5` would otherwise be reassembling a
//!    different output that happened to hash correctly only if it were the same output.
//!  * a chunk over the 184320 stride ⇒ [`PullError::ChunkOversize`]. This is what keeps the buffer bound
//!    real: 46 chunks × 184320 = 8478720, so with the count bound above the reassembly cannot exceed the
//!    ceiling by more than one stride even before the length gate.
//!  * `eof` disagreeing with the expected last `seq` ⇒ [`PullError::EofMismatch`].
//!  * **length gate** — `reassembled.len() == envelope.output_bytes` ⇒ [`PullError::LengthMismatch`].
//!    Live: chunks are only bounded ABOVE by the stride, so a short final chunk, a short middle chunk, or
//!    a full-stride chunk answered for a 20-byte output all land here.
//!  * **digest gate** — `SHA256(reassembled) == envelope.output_sha256` ⇒ [`PullError::DigestMismatch`],
//!    over the RAW bytes with no trim/NFC/NFKC/CRLF/lossy decode (§4.6 P0-3). Live and distinct from the
//!    length gate: a one-byte substitution keeps the length and fails here.
//!
//! What is NOT here: no frame-size cap. §4.10(f)'s largest reply is 245941 bytes on this leg against
//! [`crate::governed_sidecar::MAX_STDOUT_BYTES`]` = 9437184`, so a cap in this module could never fire
//! on a legal instance —
//! the same reasoning that deleted a §4.10(a)/(c) handler cap rather than shipping it. The bound that IS
//! load-bearing is the per-chunk stride, and it is checked. And no decode of the assembled output: §4.6
//! orders "only then strict-UTF8 decode for UI display", and that decode belongs to the acceptance
//! predicate that also owns the invalid-UTF-8 Block, not to the transport that produced the bytes.
//!
//! ## Where this sits relative to `governed_verification::verify_and_accept`
//!
//! §7.1 puts the fetch/reassemble/hash **FIRST, OUTSIDE the DB transaction** ("the §4.10(f) pull loop is
//! network/subprocess I/O and must never run while holding `BEGIN IMMEDIATE`"), and then opens the tx
//! with the verified bytes in hand. This module is that first step. `verify_and_accept` then applies its
//! own step-5 length+digest gate to the bytes it is handed.
//!
//! The two are not one check written twice. `verify_and_accept` is the acceptance predicate and must gate
//! whatever bytes it is given, from any source; this gate is what makes the *pull* fail at the chunk that
//! broke rather than after 8 MiB of it, and it is the gate §7.1 places outside the lock. Each is
//! independently reachable and independently tested, and deleting either one is caught by that half's own
//! named tests.
//!
//! ## NOT WIRED — read this before believing the loop runs
//!
//! Nothing in this tree calls [`pull_output`] in production, and the missing piece is a HOP, not a
//! hookup. Two of the three links now exist:
//!
//!  * The pull needs an `output_stream_id`. §4.10(f) permits exactly one source — the §4.10(e)
//!    `brops.governed-turn-result.v1` `signed` frame — and that frame now HAS a supervisor-side
//!    producer: `engine/runtime/governed_acceptance.py::AcceptanceDriver`, which requires an
//!    `OutputReadService` and puts the minted token in the frame. (It landed in this same tree, from a
//!    concurrent change, while this module was being written; it was uncommitted at the time of
//!    writing, so treat the citation as of that moment rather than as a permanent fact.)
//!  * The supervisor serves the reads. That half shipped first.
//!
//!  * §4.6's `bridge.governed-turn-result.v1` — the frame in which the sidecar re-frames a §4.10(e)
//!    result for the desktop, and the ONLY thing that carries `output_stream_id` across the sidecar
//!    boundary — now exists on BOTH hops (2026-08-10): the re-framer in
//!    `bridge/governed_turn_result_bridge.py` and the strict parser in
//!    [`crate::governed_bridge_result`], whose `SignedTurnResult::output_stream_id` is the value
//!    [`OutputPull::start`] is waiting for.
//!
//! **What is missing is one hop further out, and it MOVED on 2026-08-10.** §4.6 is the REPLY to
//! §4.10(g)'s `bridge.governed-turn-submit.v1`, and §4.10(g)'s SIDECAR half now exists: the submit
//! branch in `bridge/engine_sidecar.py` and the orchestrator in `bridge/governed_turn_submit.py` drive
//! §4.10(a0) → §4.10(a)(b)(c) → §4.10(d) inside one one-shot subprocess and re-frame the §4.10(e)
//! reply, proven end to end against the real supervisor services in
//! `engine/tests/test_governed_turn_submit_e2e.py`. **Updated 2026-08-12: the PRODUCER of the submit
//! frame now exists** — `crate::governed_prepare::prepare_governed_turn_v1b` and
//! `crate::governed_submit::governed_turn_submit_prepared`, which returns exactly the
//! `SignedTurnResult` whose `output_stream_id` [`OutputPull::start`] is waiting for. This module is
//! STILL caller-less, and the reason is now two hops rather than one: (1) `governed_turn_submit_prepared`
//! itself has no caller — the broker's one production `GovernedExecutor`
//! (`broker/src/chain_executor.rs::ChainExecutor`) drives the same hops over DIRECT AF_UNIX and spawns
//! the recorder rather than a sidecar; and (2) even given a token, the §4.10(g) step-5 pull loop that
//! would drive this on the BROKER side does not exist. The only pull adapter in the tree,
//! `ai::governed_pull_output`, is in the renderer-hosting app crate — the wrong process under §0's
//! LOCKED terminology binding — and the synchronous broker binary cannot call an `async` `tokio`
//! function in a crate it does not depend on. So a caller written today would still have to invent a
//! token, which is precisely what §4.10(f) forbids.
//!
//! A second, larger divergence sits behind that one and would survive fixing it: the broker's Linux
//! execution reads the recorder's output straight off the local filesystem
//! (`broker/src/chain_executor.rs::LinuxGovernedExecution`, `std::fs::read(&report_path)`) instead of
//! through this egress at all, so even a delivered token would not by itself put the pull on the live
//! path. See the report accompanying this change.
//!
//! The dependency is therefore made **typed** rather than described: [`OutputStreamCapability`] cannot be
//! built without a verified envelope and a well-formed token, so the day a §4.6 frame delivers one the
//! compiler names every place it has to reach. `config/reachability-declarations.json` carries the
//! matching `rust_symbols` declaration, so the reachability gate reports this as a declared gap with a
//! written reason rather than as green.

use crate::governed_turn_ipc::TurnReason;
use crate::governed_verification::ReceiptEnvelope;
use crate::receipt::sha256_hex;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use serde_json::{json, Value};

// =================================================================================================
// §4.10(f) LOCKED literals
// =================================================================================================

/// The desktop→sidecar request (§4.10(f) "Desktop hop"). One stdin request of a fresh one-shot sidecar.
pub const BRIDGE_OUTPUT_READ_PROTOCOL: &str = "bridge.governed-turn-output-read.v1";

/// Its reply. The sidecar relays the supervisor's verdict verbatim under this discriminator, so the
/// refusal enum below is IDENTICAL to the supervisor's rather than a superset of it.
pub const BRIDGE_OUTPUT_READ_RESULT_PROTOCOL: &str = "bridge.governed-turn-output-read-result.v1";

/// §4.10(f): "Chunk size = **184320** decoded (= 245760 b64url + a small JSON envelope ≤ 262144)". The
/// exact stride of the ranges served OUT — `output[seq·184320 : (seq+1)·184320]`.
pub const OUTPUT_CHUNK_BYTES: u64 = 184_320;

/// §4.10(e)/§4.10(f): `output_bytes` is `<int 0..8388608>`. The ceiling on one governed reply.
pub const MAX_OUTPUT_BYTES: u64 = 8_388_608;

/// `ceil(8388608 / 184320) = 46`, so `seq` runs 0..45 and the last chunk is 94208 bytes. Computed from
/// the two constants above rather than typed, so it cannot fall out of step with them.
pub const MAX_OUTPUT_CHUNKS: u64 = MAX_OUTPUT_BYTES.div_ceil(OUTPUT_CHUNK_BYTES);

/// §4.10(f): the capability is "32 cryptographically-random bytes, base64url no-pad, EXACTLY 43 chars".
pub const OUTPUT_STREAM_ID_LEN: usize = 43;

/// The literal maximum bridge reply: a full 184320-byte range as 245760 base64url characters plus the
/// JSON envelope. Asserted by construction in this module's tests, not left as a comment.
///
/// It exists as a constant because it is the number every transport under this hop has to admit, and two
/// of them do not: `ipc_framing::MAX_FRAME_PAYLOAD_BYTES` and the supervisor's broker-facing frame bound
/// are both 8192. That is why §4.10(f) is a subprocess stdio hop and not a framed-IPC one, and a test
/// pins the comparison so a future "simplification" onto either fails here rather than at the first full
/// chunk in production.
pub const MAX_BRIDGE_OUTPUT_READ_REPLY_BYTES: usize = 245_941;

// =================================================================================================
// The closed §4.10(f) refusal set — the supervisor's, relayed
// =================================================================================================

/// A verdict the SUPERVISOR reached about the stream, relayed verbatim by the sidecar.
///
/// §4.10(f) gives the bridge reply an enum "IDENTICAL to the supervisor's (NOT a superset)" precisely
/// because the sidecar "originates NO supervisor/signature verdict of its own". Parsing into a closed
/// enum is how that stays true on this side: an unrecognised literal is not admitted as a sixth reason,
/// it is [`PullError::MalformedReply`] — a reply that is not a §4.10(f) frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamRefusal {
    /// The row is absent: swept past retention, quota-evicted, or never minted. One answer for all
    /// three, so an unauthorized holder cannot learn whether a token it guessed ever existed.
    StreamUnknown,
    /// Past `expires_at_ms` with the tombstone still present. Checked BEFORE the binding compare, so an
    /// expired token presented with the wrong receipt learns only that it is expired.
    StreamExpired,
    /// A valid token presented with a different turn's `receipt_id`/`execution_attempt_id`. The P1-3
    /// server-side compare — caught before any byte is served, not three steps later by the digest.
    StreamBindingMismatch,
    /// `seq` beyond the last legal range for this stream's `output_bytes`.
    SeqOutOfRange,
    /// The forwarded frame was not a well-formed request. Produced by the supervisor, never by the
    /// proxy: the sidecar forwards the caller's fields unchanged precisely so it never answers for them.
    Malformed,
}

impl StreamRefusal {
    /// The wire literal. These are the exact five §4.10(f) publishes on both hops.
    pub fn as_str(self) -> &'static str {
        match self {
            StreamRefusal::StreamUnknown => "stream_unknown",
            StreamRefusal::StreamExpired => "stream_expired",
            StreamRefusal::StreamBindingMismatch => "stream_binding_mismatch",
            StreamRefusal::SeqOutOfRange => "seq_out_of_range",
            StreamRefusal::Malformed => "malformed",
        }
    }

    /// Parse a relayed reason. `None` for anything outside the closed set — which is a malformed reply,
    /// not a new refusal.
    pub fn parse(reason: &str) -> Option<StreamRefusal> {
        Some(match reason {
            "stream_unknown" => StreamRefusal::StreamUnknown,
            "stream_expired" => StreamRefusal::StreamExpired,
            "stream_binding_mismatch" => StreamRefusal::StreamBindingMismatch,
            "seq_out_of_range" => StreamRefusal::SeqOutOfRange,
            "malformed" => StreamRefusal::Malformed,
            _ => return None,
        })
    }
}

/// Why a pull did not produce the signed output. Every variant Blocks; they are kept apart because they
/// mean different things to whoever reads the log, and because two of them are not this hop's fault.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PullError {
    /// The supervisor decided something about the stream and the sidecar relayed it.
    Refused(StreamRefusal),
    /// A LOCAL failure of the one-shot sidecar — spawn, connect, timeout, unexpected exit. §4.10(f)
    /// P1-5: this "is NOT one of these reasons and produces NO reply frame". No supervisor decided
    /// anything, and this variant exists so that fact survives into the caller's log.
    Transport(String),
    /// Something answered, and it was not a §4.10(f) frame. Same class as [`PullError::Transport`] — a
    /// non-verdict — kept separate because it says the peer spoke and spoke wrongly.
    MalformedReply,
    /// The reply echoed a different `output_stream_id` or `seq` than the request named.
    EchoMismatch,
    /// A served chunk exceeded the §4.10(f) stride.
    ChunkOversize,
    /// `eof` disagreed with the chunk count derived from the SIGNED `output_bytes`.
    EofMismatch,
    /// The envelope's own `output_bytes` is outside `0..=8388608`. Signed, therefore authentic — and
    /// still refused, because authentic is not the same as sane.
    OutputTooLarge,
    /// The token is not a 43-character capability, or the envelope carries no usable identity.
    InvalidCapability,
    /// §4.6/§7.1 length gate: the reassembly is not `envelope.output_bytes` long.
    LengthMismatch,
    /// §4.6/§7.1 digest gate: `SHA256(reassembly) != envelope.output_sha256` over the raw bytes.
    DigestMismatch,
}

impl PullError {
    /// The closed renderer-facing reason. A length/digest disagreement is the same
    /// [`TurnReason::CommitReadbackMismatch`] `verify_and_accept` uses for its own output gates — the
    /// accepted body would not match the envelope's digest — and everything else is an upstream Block.
    pub fn to_turn_reason(&self) -> TurnReason {
        match self {
            PullError::LengthMismatch | PullError::DigestMismatch => {
                TurnReason::CommitReadbackMismatch
            }
            _ => TurnReason::UpstreamBlocked,
        }
    }
}

// =================================================================================================
// The capability
// =================================================================================================

/// The three values §4.10(f) requires a read to present, with the authenticity of each fixed by
/// construction.
///
/// §4.10(f), P1-3: "the supervisor requires the client to present `receipt_id` +
/// `execution_attempt_id` alongside the token and compares all three against the row before serving …
/// The desktop sources `receipt_id`/`execution_attempt_id` from the **verified §4.9 signed envelope**
/// (authenticated values, not transport claims)."
///
/// That sentence is the whole reason this type has no field-by-field constructor.
/// [`from_envelope`](OutputStreamCapability::from_envelope) is the only way to build one, and it takes
/// the envelope, so the two identity values can only ever be the signed ones. A sidecar that swapped in
/// another turn's token would have to also produce that turn's envelope, which it cannot sign.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct OutputStreamCapability<'a> {
    output_stream_id: &'a str,
    receipt_id: &'a str,
    execution_attempt_id: &'a str,
}

impl<'a> OutputStreamCapability<'a> {
    /// Bind a transported `output_stream_id` to the identity of a VERIFIED envelope.
    ///
    /// The token is the one value here that came off the wire, and it is checked for the only property
    /// §4.10(f) fixes about its shape: exactly 43 base64url characters. A value of any other length
    /// cannot be a token this supervisor minted, so it is refused here rather than sent — the same
    /// judgement the supervisor's own parser makes, made early because there is nothing to learn by
    /// asking.
    ///
    /// The envelope must be one `verify_and_accept` would accept — this constructor does not verify a
    /// signature and does not claim to. What it guarantees is narrower and is the part that matters:
    /// the receipt and attempt ids presented to the supervisor are the envelope's, not a caller's.
    pub fn from_envelope(
        output_stream_id: &'a str,
        envelope: &ReceiptEnvelope<'a>,
    ) -> Result<OutputStreamCapability<'a>, PullError> {
        if output_stream_id.len() != OUTPUT_STREAM_ID_LEN
            || !output_stream_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        {
            return Err(PullError::InvalidCapability);
        }
        if envelope.receipt_id.is_empty() || envelope.execution_attempt_id.is_empty() {
            return Err(PullError::InvalidCapability);
        }
        Ok(OutputStreamCapability {
            output_stream_id,
            receipt_id: envelope.receipt_id,
            execution_attempt_id: envelope.execution_attempt_id,
        })
    }

    /// The capability token, for the echo compare.
    pub fn output_stream_id(&self) -> &str {
        self.output_stream_id
    }

    /// The exact `bridge.governed-turn-output-read.v1` request for one range.
    ///
    /// Five fields and nothing else. Most pointedly there is no length, no offset and no chunk size: the
    /// stride is fixed by the protocol, so a caller cannot choose how much of the output one round trip
    /// returns, and the range is a pure function of `seq` — which is what makes a lost reply safe to
    /// retry with no cursor to consume.
    pub fn read_request(&self, seq: u64) -> Value {
        json!({
            "protocol": BRIDGE_OUTPUT_READ_PROTOCOL,
            "output_stream_id": self.output_stream_id,
            "receipt_id": self.receipt_id,
            "execution_attempt_id": self.execution_attempt_id,
            "seq": seq,
        })
    }
}

// =================================================================================================
// Range arithmetic
// =================================================================================================

/// How many reads this output takes: `max(1, ceil(output_bytes / 184320))`.
///
/// The `max(1)` is §4.10(f)'s zero-byte contract. A zero-byte output has zero chunks and exactly one
/// legal read (`seq == 0` ⇒ `ok:true, bytes_b64:"", eof:true`; any `seq > 0` ⇒ `seq_out_of_range`), so
/// the loop is the same loop for every turn and empty is never mistaken for absent.
///
/// Refuses an `output_bytes` above the §4.10(f) ceiling BEFORE any buffer is reserved.
pub fn expected_chunk_count(output_bytes: u64) -> Result<u64, PullError> {
    if output_bytes > MAX_OUTPUT_BYTES {
        return Err(PullError::OutputTooLarge);
    }
    Ok(output_bytes.div_ceil(OUTPUT_CHUNK_BYTES).max(1))
}

// =================================================================================================
// One reply
// =================================================================================================

/// One served range: the exact bytes and the `eof` flag as the supervisor sent them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OutputChunk {
    pub bytes: Vec<u8>,
    pub eof: bool,
}

/// Parse one `bridge.governed-turn-output-read-result.v1` reply for `seq`.
///
/// Strict in the same direction the sidecar is: a document that is not this frame is
/// [`PullError::MalformedReply`], never a refusal, because a refusal is a supervisor verdict and this is
/// the parser's opinion about a shape. The `ok:false` arm is the one place a verdict is admitted, and
/// only for the five published literals.
///
/// The ECHO compare lives here rather than in the sidecar deliberately. The sidecar is the party §2.4
/// declares compromised; a check it performed over values it chose would be worth nothing. Here the
/// expected values come from a verified envelope and a locally-driven counter.
fn parse_read_reply(
    reply: &Value,
    cap: &OutputStreamCapability,
    seq: u64,
) -> Result<OutputChunk, PullError> {
    let obj = reply.as_object().ok_or(PullError::MalformedReply)?;
    if obj.len() != 7 {
        return Err(PullError::MalformedReply);
    }
    if obj.get("protocol").and_then(Value::as_str) != Some(BRIDGE_OUTPUT_READ_RESULT_PROTOCOL) {
        return Err(PullError::MalformedReply);
    }
    let ok = obj.get("ok").and_then(Value::as_bool).ok_or(PullError::MalformedReply)?;
    if !ok {
        // The refused arm. `output_stream_id`/`seq` are `<same or null>` here, so they are NOT compared:
        // a refusal is allowed to name nothing, and §4.10(f) forbids it to disclose the row's real
        // binding to a caller that failed to present it.
        let reason = obj
            .get("error")
            .and_then(Value::as_object)
            .filter(|e| e.len() == 1)
            .and_then(|e| e.get("reason"))
            .and_then(Value::as_str)
            .ok_or(PullError::MalformedReply)?;
        let refusal = StreamRefusal::parse(reason).ok_or(PullError::MalformedReply)?;
        return Err(PullError::Refused(refusal));
    }
    if !obj.get("error").map(Value::is_null).unwrap_or(false) {
        return Err(PullError::MalformedReply);
    }
    let eof = obj.get("eof").and_then(Value::as_bool).ok_or(PullError::MalformedReply)?;
    let b64 = obj.get("bytes_b64").and_then(Value::as_str).ok_or(PullError::MalformedReply)?;
    // Echo equality on the ok arm: the supervisor serves `output[seq·184320 : …]`, so a reply naming a
    // different `seq` is a different range and a reply naming a different token is a different stream.
    let echoed_id = obj.get("output_stream_id").and_then(Value::as_str);
    let echoed_seq = obj.get("seq").and_then(Value::as_u64);
    if echoed_id != Some(cap.output_stream_id) || echoed_seq != Some(seq) {
        return Err(PullError::EchoMismatch);
    }
    // Base64url, no padding — the §4.10(f) transport convention. `URL_SAFE_NO_PAD` refuses a padded or
    // out-of-alphabet value rather than tolerating it, which is what keeps the bytes the sidecar decoded
    // and the bytes decoded here the same bytes.
    let bytes = URL_SAFE_NO_PAD.decode(b64.as_bytes()).map_err(|_| PullError::MalformedReply)?;
    if bytes.len() as u64 > OUTPUT_CHUNK_BYTES {
        return Err(PullError::ChunkOversize);
    }
    Ok(OutputChunk { bytes, eof })
}

// =================================================================================================
// The loop, and the §4.6/§7.1 gate
// =================================================================================================

/// One §4.10(f) pull in progress: which read is next, what each reply must satisfy, and the §4.6/§7.1
/// gate over the finished reassembly.
///
/// It is a DRIVER rather than a loop for one reason, and it is a load-bearing one. The transport under
/// this hop is a spawned subprocess, so the real adapter is `async`; a closure-driven loop would have
/// forced that adapter to write its own iteration — and with it its own `eof` check, its own chunk
/// bookkeeping and its own length/digest gate. Every gate in this file would then have had a second
/// copy in the crate that actually runs it, which is precisely how two implementations drift until only
/// the unexercised one is correct. Here the ordering and every check live once; [`pull_output`] is the
/// synchronous convenience wrapper and the async adapter is the same three lines.
///
/// Ordering is §7.1's: a pull runs **outside** any DB transaction, and only its `Ok` bytes go on to the
/// acceptance predicate and the `BEGIN IMMEDIATE` commit.
#[derive(Debug)]
pub struct OutputPull<'a> {
    cap: OutputStreamCapability<'a>,
    /// The SIGNED `output_bytes`, copied at construction. It can only have come from the envelope —
    /// there is no constructor that takes it — so the §4.6 length gate cannot be aimed at the §4.10(e)
    /// transport echo.
    expected_bytes: u64,
    /// The SIGNED `output_sha256`, same provenance and same reason.
    expected_sha256: &'a str,
    chunks: u64,
    next_seq: u64,
    assembled: Vec<u8>,
}

impl<'a> OutputPull<'a> {
    /// Begin a pull for one verified envelope and one transported capability token.
    ///
    /// Both bounds that must hold before a byte is reserved are applied here: the token's shape, and
    /// the signed `output_bytes` against the §4.10(f) ceiling. A signature makes a value authentic, not
    /// sane, so an envelope claiming more than 8 MiB is refused rather than allocated for.
    pub fn start(
        envelope: &ReceiptEnvelope<'a>,
        output_stream_id: &'a str,
    ) -> Result<OutputPull<'a>, PullError> {
        let cap = OutputStreamCapability::from_envelope(output_stream_id, envelope)?;
        let expected_bytes = envelope.output_bytes;
        let chunks = expected_chunk_count(expected_bytes)?;
        Ok(OutputPull {
            cap,
            expected_bytes,
            expected_sha256: envelope.output_sha256,
            chunks,
            next_seq: 0,
            assembled: Vec::with_capacity(expected_bytes as usize),
        })
    }

    /// The next `bridge.governed-turn-output-read.v1` request, or `None` when the signed length says
    /// every range has been read. The caller performs ONE round trip per request and hands the reply to
    /// [`accept`](OutputPull::accept).
    ///
    /// The count came from a signed value, so the transport never decides how long the loop runs.
    pub fn next_request(&self) -> Option<Value> {
        (self.next_seq < self.chunks).then(|| self.cap.read_request(self.next_seq))
    }

    /// Validate one reply against the request it answers and append its bytes.
    ///
    /// Refuses out of order: a reply handed in when [`next_request`](OutputPull::next_request) has none
    /// left is not a reply to anything this pull asked for.
    pub fn accept(&mut self, reply: &Value) -> Result<(), PullError> {
        if self.next_seq >= self.chunks {
            return Err(PullError::EchoMismatch);
        }
        // A document that does not even name the §4.10(f) reply protocol is the sidecar's
        // protocol-less refusal — a LOCAL failure, not a verdict. It is classified HERE, inside the
        // one function every adapter must call, rather than at the call site: a call-site check is a
        // line the next transport adapter can forget, and forgetting it turns "the supervisor said
        // stream_unknown" into something a failed `connect()` can also say.
        if let Some(local) = transport_failure_from_reply(reply) {
            return Err(local);
        }
        let seq = self.next_seq;
        let chunk = parse_read_reply(reply, &self.cap, seq)?;
        // `eof` is CHECKED, never trusted. A flag that disagrees with the signed length is a
        // disagreement about which output this is.
        if chunk.eof != (seq + 1 == self.chunks) {
            return Err(PullError::EofMismatch);
        }
        self.assembled.extend_from_slice(&chunk.bytes);
        self.next_seq += 1;
        Ok(())
    }

    /// The §4.6/§7.1 whole-output gate, against the SIGNED envelope values.
    ///
    /// On success the returned bytes satisfy `len == envelope.output_bytes` and
    /// `SHA256(bytes) == envelope.output_sha256` over the RAW bytes — no trim, no NFC/NFKC, no CRLF
    /// conversion, no lossy decode. The strict-UTF8 decode §4.6 requires "only then" is the acceptance
    /// predicate's, next to the invalid-UTF-8 Block it belongs with.
    ///
    /// Finishing early is a length failure and not a special case: an unfinished pull is short.
    pub fn finish(self) -> Result<Vec<u8>, PullError> {
        // Length gate. Live: chunks are bounded only ABOVE by the stride, so a short chunk anywhere, a
        // full-stride chunk answered for a 20-byte output, or a loop abandoned early all land here
        // rather than being carried into a digest comparison that would only say "no".
        if self.assembled.len() as u64 != self.expected_bytes {
            return Err(PullError::LengthMismatch);
        }
        // Digest gate. Distinct from the length gate and not implied by it: a one-byte substitution
        // keeps the length.
        if sha256_hex(&self.assembled) != self.expected_sha256 {
            return Err(PullError::DigestMismatch);
        }
        Ok(self.assembled)
    }
}

/// Classify a reply document that is not a §4.10(f) frame at all.
///
/// `Some(Transport)` when the document does not even name
/// [`BRIDGE_OUTPUT_READ_RESULT_PROTOCOL`]; `None` when it does and is therefore the parser's business.
///
/// Private, and reached from exactly one place — [`OutputPull::accept`] — so there is no transport
/// adapter that can be written without it. It started life as a check at the `ai.rs` call site and moved
/// here because mutation testing found the obvious thing: a line at a call site is a line the next
/// adapter forgets, and no test in either crate could reach it there.
///
/// This exists because §4.10(f) P1-5 draws a line that is easy to erase by accident. A local failure of
/// the one-shot sidecar "is NOT one of these reasons and produces NO reply frame" — so the sidecar
/// answers with its protocol-less refusal, which carries prose and no `reason`. Folding that into
/// "malformed reply" would lose the only fact that matters about it: no supervisor decided anything. A
/// `stream_expired` in a log is worth reading precisely because this case cannot produce one.
///
/// The sidecar's own prose is carried through when it has some, because "connect refused" and
/// "BROPS_SUPERVISOR_SOCKET is unset" are different operational problems and the desktop cannot tell
/// them apart by any other means.
fn transport_failure_from_reply(reply: &Value) -> Option<PullError> {
    if reply.get("protocol").and_then(Value::as_str) == Some(BRIDGE_OUTPUT_READ_RESULT_PROTOCOL) {
        return None;
    }
    let detail = reply
        .get("error")
        .and_then(Value::as_str)
        .unwrap_or("the sidecar returned no bridge.governed-turn-output-read-result.v1 frame");
    Some(PullError::Transport(detail.to_string()))
}

/// Drive a whole §4.10(f) pull synchronously and return the exact output bytes.
///
/// `fetch` performs ONE desktop→sidecar round trip: it is handed a request from
/// [`OutputPull::next_request`] and returns the parsed reply document, or a [`PullError::Transport`]
/// naming the local failure. Everything else is [`OutputPull`]'s.
pub fn pull_output(
    envelope: &ReceiptEnvelope,
    output_stream_id: &str,
    mut fetch: impl FnMut(&Value) -> Result<Value, PullError>,
) -> Result<Vec<u8>, PullError> {
    let mut pull = OutputPull::start(envelope, output_stream_id)?;
    while let Some(request) = pull.next_request() {
        let reply = fetch(&request)?;
        pull.accept(&reply)?;
    }
    pull.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A minimal envelope carrying only what the pull reads. Every other field is inert here — this
    /// module never verifies a signature and never claims to; `governed_verification` owns that, and its
    /// own tests own proving it.
    fn envelope<'a>(output: &'a [u8], sha: &'a str) -> ReceiptEnvelope<'a> {
        ReceiptEnvelope {
            artifact_type: "brops.governed-receipt-envelope.v1",
            key_id: "signer-1",
            receipt_id: "rcpt-1",
            run_id: "run-1",
            execution_attempt_id: "attempt-1",
            task_id: "task-1",
            workspace_id: "ws-1",
            install_id: "inst-1",
            request_nonce: "nonce-1",
            request_sha256: "a".repeat(64).leak(),
            record_handle: "b".repeat(64).leak(),
            lease_handle: "c".repeat(64).leak(),
            execution_receipt_handle: "d".repeat(64).leak(),
            output_sha256: sha,
            output_bytes: output.len() as u64,
            challenge_accepted_at_ms: 1_700_000_000_000,
            completed_at_ms: 1_700_000_000_001,
            evidence_final_event_hash: "e".repeat(64).leak(),
            evidence_event_count: 1,
            evidence_last_sequence: 0,
            evidence_head_sequence: 1,
            supervisor_attestation_key_id: "attest-1",
            attestation_evidence_sha256: "f".repeat(64).leak(),
        }
    }

    const TOKEN: &str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"; // 43 chars

    fn ok_reply(token: &str, seq: u64, bytes: &[u8], eof: bool) -> Value {
        json!({
            "protocol": BRIDGE_OUTPUT_READ_RESULT_PROTOCOL,
            "ok": true,
            "output_stream_id": token,
            "seq": seq,
            "bytes_b64": URL_SAFE_NO_PAD.encode(bytes),
            "eof": eof,
            "error": null,
        })
    }

    fn refused_reply(reason: &str) -> Value {
        json!({
            "protocol": BRIDGE_OUTPUT_READ_RESULT_PROTOCOL,
            "ok": false,
            "output_stream_id": null,
            "seq": null,
            "bytes_b64": null,
            "eof": null,
            "error": { "reason": reason },
        })
    }

    /// A supervisor that serves the real ranges of `output`, so the loop under test is driven by the
    /// same arithmetic the engine uses rather than by a canned script.
    fn server(output: Vec<u8>) -> impl FnMut(&Value) -> Result<Value, PullError> {
        move |req: &Value| {
            let seq = req.get("seq").and_then(Value::as_u64).expect("seq");
            let start = (seq * OUTPUT_CHUNK_BYTES) as usize;
            let end = ((seq + 1) * OUTPUT_CHUNK_BYTES).min(output.len() as u64) as usize;
            let slice = if start >= output.len() { &[][..] } else { &output[start..end] };
            let last = output.len().div_ceil(OUTPUT_CHUNK_BYTES as usize).max(1) as u64 - 1;
            Ok(ok_reply(TOKEN, seq, slice, seq == last))
        }
    }

    fn pull(output: &[u8], sha: &str, fetch: impl FnMut(&Value) -> Result<Value, PullError>) -> Result<Vec<u8>, PullError> {
        let env = envelope(output, sha);
        pull_output(&env, TOKEN, fetch)
    }

    // ---- The arithmetic, constructed rather than asserted from a comment -----------------------

    #[test]
    fn the_literal_maximum_bridge_reply_is_the_constant_this_module_publishes() {
        let reply = ok_reply(TOKEN, 44, &vec![b'x'; OUTPUT_CHUNK_BYTES as usize], false);
        let encoded = serde_json::to_vec(&reply).expect("serialize");
        assert_eq!(encoded.len(), MAX_BRIDGE_OUTPUT_READ_REPLY_BYTES);
        // The base64url of a full stride is exact, not an upper bound: 184320 is divisible by 3, so
        // there is no padding and the encoding is 245760 characters.
        assert_eq!(URL_SAFE_NO_PAD.encode(vec![0u8; OUTPUT_CHUNK_BYTES as usize]).len(), 245_760);
    }

    /// The bound that decides this hop's shape. Both framed-IPC caps in the tree are 8192, so neither
    /// could ever carry a full chunk — which is why §4.10(f) rides a one-shot subprocess's stdout.
    /// If someone later "simplifies" the pull onto `ipc_framing`, this is what says no.
    #[test]
    fn no_framed_ipc_path_in_this_tree_could_carry_a_full_chunk() {
        assert_eq!(crate::ipc_framing::MAX_FRAME_PAYLOAD_BYTES, 8192);
        assert!(MAX_BRIDGE_OUTPUT_READ_REPLY_BYTES > crate::ipc_framing::MAX_FRAME_PAYLOAD_BYTES * 29);
    }

    #[test]
    fn the_chunk_count_is_derived_not_typed() {
        assert_eq!(MAX_OUTPUT_CHUNKS, 46);
        assert_eq!(expected_chunk_count(MAX_OUTPUT_BYTES).unwrap(), 46);
        // The last chunk of a maximum output is 94208 bytes — 45 full strides plus the remainder.
        assert_eq!(MAX_OUTPUT_BYTES - 45 * OUTPUT_CHUNK_BYTES, 94_208);
        assert_eq!(expected_chunk_count(OUTPUT_CHUNK_BYTES).unwrap(), 1);
        assert_eq!(expected_chunk_count(OUTPUT_CHUNK_BYTES + 1).unwrap(), 2);
    }

    /// §4.10(f): a zero-byte output is a contract, not an absence. Zero chunks of data, exactly one
    /// legal read — so the loop has no empty special case to get wrong.
    #[test]
    fn a_zero_byte_output_is_one_read_and_verifies() {
        assert_eq!(expected_chunk_count(0).unwrap(), 1);
        let sha = sha256_hex(b"");
        let out = pull(b"", &sha, server(Vec::new())).expect("empty output is a legal turn");
        assert!(out.is_empty());
    }

    #[test]
    fn a_signed_but_absurd_output_length_is_refused_before_any_allocation() {
        assert_eq!(expected_chunk_count(MAX_OUTPUT_BYTES + 1), Err(PullError::OutputTooLarge));
        let mut called = false;
        let empty_sha = sha256_hex(b"");
        let env = ReceiptEnvelope { output_bytes: u64::MAX, ..envelope(b"", &empty_sha) };
        let err = pull_output(&env, TOKEN, |_| {
            called = true;
            Ok(Value::Null)
        })
        .unwrap_err();
        assert_eq!(err, PullError::OutputTooLarge);
        assert!(!called, "the loop reserved a buffer before bounding the signed length");
    }

    // ---- The happy path, across chunk boundaries ------------------------------------------------

    #[test]
    fn a_multi_chunk_output_reassembles_and_verifies() {
        let output: Vec<u8> = (0..(OUTPUT_CHUNK_BYTES * 2 + 7)).map(|i| (i % 251) as u8).collect();
        let sha = sha256_hex(&output);
        let got = pull(&output, &sha, server(output.clone())).expect("a faithful stream verifies");
        assert_eq!(got, output);
    }

    #[test]
    fn the_request_carries_the_envelopes_identity_and_nothing_else() {
        let sha = sha256_hex(b"x");
        let env = envelope(b"x", &sha);
        let cap = OutputStreamCapability::from_envelope(TOKEN, &env).unwrap();
        let req = cap.read_request(3);
        assert_eq!(req, json!({
            "protocol": BRIDGE_OUTPUT_READ_PROTOCOL,
            "output_stream_id": TOKEN,
            "receipt_id": "rcpt-1",
            "execution_attempt_id": "attempt-1",
            "seq": 3,
        }));
    }

    /// The point of the whole type: the two identity values the supervisor compares can only be the
    /// signed ones, because there is no constructor that accepts them separately.
    #[test]
    fn the_capability_can_only_be_built_from_an_envelope() {
        let sha = sha256_hex(b"x");
        let env = envelope(b"x", &sha);
        let cap = OutputStreamCapability::from_envelope(TOKEN, &env).unwrap();
        assert_eq!(cap.read_request(0)["receipt_id"], json!(env.receipt_id));
        assert_eq!(cap.read_request(0)["execution_attempt_id"], json!(env.execution_attempt_id));
    }

    #[test]
    fn a_token_of_the_wrong_shape_is_refused_before_anything_is_sent() {
        let sha = sha256_hex(b"x");
        let env = envelope(b"x", &sha);
        for bad in ["", "short", &"A".repeat(42), &"A".repeat(44), &"A".repeat(42).replace('A', "+")] {
            assert_eq!(
                OutputStreamCapability::from_envelope(bad, &env).unwrap_err(),
                PullError::InvalidCapability,
                "accepted {bad:?} as a 43-char base64url capability"
            );
        }
    }

    // ---- Every gate, one at a time ---------------------------------------------------------------

    #[test]
    fn a_one_byte_substitution_fails_the_digest_gate_and_not_the_length_gate() {
        let output = b"hello governed world".to_vec();
        let sha = sha256_hex(&output);
        let mut tampered = output.clone();
        tampered[0] ^= 0x01;
        assert_eq!(tampered.len(), output.len());
        assert_eq!(pull(&output, &sha, server(tampered)).unwrap_err(), PullError::DigestMismatch);
    }

    #[test]
    fn a_truncated_chunk_fails_the_length_gate() {
        let output = b"hello governed world".to_vec();
        let sha = sha256_hex(&output);
        let short = output[..output.len() - 1].to_vec();
        assert_eq!(pull(&output, &sha, server(short)).unwrap_err(), PullError::LengthMismatch);
    }

    #[test]
    fn an_appended_byte_fails_the_length_gate() {
        let output = b"hello governed world".to_vec();
        let sha = sha256_hex(&output);
        let mut longer = output.clone();
        longer.push(b'!');
        assert_eq!(pull(&output, &sha, server(longer)).unwrap_err(), PullError::LengthMismatch);
    }

    /// A CRLF conversion keeps the text meaningful and changes the bytes — §4.6 forbids exactly this
    /// class of "helpful" normalization, and the raw-byte digest is what notices.
    #[test]
    fn a_crlf_normalized_stream_blocks() {
        let output = b"line one\nline two\n".to_vec();
        let sha = sha256_hex(&output);
        let converted = b"line one\r\nline two\r\n".to_vec();
        assert_eq!(pull(&output, &sha, server(converted)).unwrap_err(), PullError::LengthMismatch);
    }

    /// A Unicode normalization that keeps the LENGTH: NFC of "e\u{0301}" is "\u{e9}" — 3 bytes to 2 —
    /// so this pads to hold the length constant and prove the digest gate is what catches it.
    #[test]
    fn a_normalized_stream_of_the_same_length_blocks_on_the_digest() {
        let output = "cafe\u{0301}".as_bytes().to_vec(); // 6 bytes
        let sha = sha256_hex(&output);
        let normalized = "caf\u{e9} ".as_bytes().to_vec(); // also 6 bytes
        assert_eq!(normalized.len(), output.len());
        assert_eq!(pull(&output, &sha, server(normalized)).unwrap_err(), PullError::DigestMismatch);
    }

    #[test]
    fn a_reordered_stream_blocks() {
        let output: Vec<u8> = (0..(OUTPUT_CHUNK_BYTES * 2)).map(|i| (i % 251) as u8).collect();
        let sha = sha256_hex(&output);
        let reversed: Vec<u8> = {
            let (a, b) = output.split_at(OUTPUT_CHUNK_BYTES as usize);
            b.iter().chain(a.iter()).copied().collect()
        };
        assert_eq!(pull(&output, &sha, server(reversed)).unwrap_err(), PullError::DigestMismatch);
    }

    #[test]
    fn a_reply_for_a_different_seq_is_an_echo_mismatch() {
        let output = vec![b'a'; (OUTPUT_CHUNK_BYTES + 1) as usize];
        let sha = sha256_hex(&output);
        let err = pull(&output, &sha, |req| {
            let seq = req["seq"].as_u64().unwrap();
            // Always answers seq 0 — the replayed-chunk case §4.10(f) names.
            Ok(ok_reply(TOKEN, 0, &vec![b'a'; OUTPUT_CHUNK_BYTES as usize], seq == 1))
        })
        .unwrap_err();
        assert_eq!(err, PullError::EchoMismatch);
    }

    #[test]
    fn a_reply_naming_another_stream_is_an_echo_mismatch() {
        let output = b"x".to_vec();
        let sha = sha256_hex(&output);
        let other = "B".repeat(OUTPUT_STREAM_ID_LEN);
        let err = pull(&output, &sha, |_| Ok(ok_reply(&other, 0, b"x", true))).unwrap_err();
        assert_eq!(err, PullError::EchoMismatch);
    }

    #[test]
    fn a_chunk_over_the_stride_is_refused() {
        let output = vec![b'a'; (OUTPUT_CHUNK_BYTES + 1) as usize];
        let sha = sha256_hex(&output);
        let err = pull(&output, &sha, |req| {
            let seq = req["seq"].as_u64().unwrap();
            Ok(ok_reply(TOKEN, seq, &vec![b'a'; (OUTPUT_CHUNK_BYTES + 1) as usize], seq == 1))
        })
        .unwrap_err();
        assert_eq!(err, PullError::ChunkOversize);
    }

    /// `eof` is checked against a count derived from a SIGNED value, so a proxy cannot end the loop
    /// early — either direction is a disagreement with the envelope.
    #[test]
    fn an_eof_that_disagrees_with_the_signed_length_blocks() {
        let output = vec![b'a'; (OUTPUT_CHUNK_BYTES * 2) as usize];
        let sha = sha256_hex(&output);
        let early = pull(&output, &sha, |req| {
            let seq = req["seq"].as_u64().unwrap();
            Ok(ok_reply(TOKEN, seq, &vec![b'a'; OUTPUT_CHUNK_BYTES as usize], true))
        })
        .unwrap_err();
        assert_eq!(early, PullError::EofMismatch);

        let never = pull(&output, &sha, |req| {
            let seq = req["seq"].as_u64().unwrap();
            Ok(ok_reply(TOKEN, seq, &vec![b'a'; OUTPUT_CHUNK_BYTES as usize], false))
        })
        .unwrap_err();
        assert_eq!(never, PullError::EofMismatch);
    }

    /// The loop is bounded by the signed length, so a proxy that would happily keep answering cannot
    /// make it run forever. 46 is the ceiling for ANY legal output.
    #[test]
    fn the_loop_runs_exactly_the_number_of_reads_the_signed_length_names() {
        let output = vec![b'a'; (OUTPUT_CHUNK_BYTES * 3 + 5) as usize];
        let sha = sha256_hex(&output);
        let mut reads = 0usize;
        let mut serve = server(output.clone());
        pull(&output, &sha, |req| {
            reads += 1;
            serve(req)
        })
        .expect("a faithful stream verifies");
        assert_eq!(reads, 4);
        assert!(reads as u64 <= MAX_OUTPUT_CHUNKS);
    }

    // ---- Refusals and non-verdicts ----------------------------------------------------------------

    #[test]
    fn every_closed_reason_round_trips_and_surfaces_as_that_refusal() {
        let output = b"x".to_vec();
        let sha = sha256_hex(&output);
        for refusal in [
            StreamRefusal::StreamUnknown,
            StreamRefusal::StreamExpired,
            StreamRefusal::StreamBindingMismatch,
            StreamRefusal::SeqOutOfRange,
            StreamRefusal::Malformed,
        ] {
            assert_eq!(StreamRefusal::parse(refusal.as_str()), Some(refusal));
            let err = pull(&output, &sha, |_| Ok(refused_reply(refusal.as_str()))).unwrap_err();
            assert_eq!(err, PullError::Refused(refusal));
            assert_eq!(err.to_turn_reason(), TurnReason::UpstreamBlocked);
        }
    }

    /// §4.10(f): the bridge enum is IDENTICAL to the supervisor's, NOT a superset. A sixth literal is
    /// not a new refusal — it is a reply that is not a §4.10(f) frame.
    #[test]
    fn a_reason_outside_the_closed_set_is_not_admitted_as_a_sixth_refusal() {
        assert_eq!(StreamRefusal::parse("peer_denied"), None);
        let output = b"x".to_vec();
        let sha = sha256_hex(&output);
        let err = pull(&output, &sha, |_| Ok(refused_reply("peer_denied"))).unwrap_err();
        assert_eq!(err, PullError::MalformedReply);
    }

    #[test]
    fn a_document_that_is_not_a_frame_is_never_read_as_a_verdict() {
        let sha = sha256_hex(b"x");
        let env = envelope(b"x", &sha);
        let cap = OutputStreamCapability::from_envelope(TOKEN, &env).unwrap();
        for bad in [
            json!(null),
            json!({}),
            json!({"protocol": "bridge.result", "ok": true, "output_stream_id": TOKEN,
                   "seq": 0, "bytes_b64": "", "eof": true, "error": null}),
            // Right protocol, one extra key: the frame is exhaustive, so this is not it.
            json!({"protocol": BRIDGE_OUTPUT_READ_RESULT_PROTOCOL, "ok": true,
                   "output_stream_id": TOKEN, "seq": 0, "bytes_b64": "", "eof": true,
                   "error": null, "extra": 1}),
            // `ok:true` carrying an error object.
            json!({"protocol": BRIDGE_OUTPUT_READ_RESULT_PROTOCOL, "ok": true,
                   "output_stream_id": TOKEN, "seq": 0, "bytes_b64": "", "eof": true,
                   "error": {"reason": "stream_unknown"}}),
            // Padded base64url: canonical no-pad is the §4.10(f) convention.
            json!({"protocol": BRIDGE_OUTPUT_READ_RESULT_PROTOCOL, "ok": true,
                   "output_stream_id": TOKEN, "seq": 0, "bytes_b64": "YWJjZA==", "eof": true,
                   "error": null}),
        ] {
            assert_eq!(
                parse_read_reply(&bad, &cap, 0).unwrap_err(),
                PullError::MalformedReply,
                "read a verdict out of {bad}"
            );
        }
    }

    /// The sidecar's protocol-less refusal is what "no §4.10(f) frame" is emitted as. It must classify
    /// as a LOCAL failure carrying the sidecar's prose — never as a malformed governed frame, and never
    /// as one of the five reasons.
    #[test]
    fn the_sidecars_out_of_band_document_is_a_transport_failure_with_its_own_reason() {
        let out_of_band = json!({
            "protocol": "bridge.op.v1", "schema": 1, "ok": false, "op": null,
            "error": "the governed output-read hop is not provisioned: BROPS_SUPERVISOR_SOCKET is unset",
        });
        match transport_failure_from_reply(&out_of_band) {
            Some(PullError::Transport(detail)) => {
                assert!(detail.contains("BROPS_SUPERVISOR_SOCKET"), "lost the sidecar's reason: {detail}")
            }
            other => panic!("the out-of-band document classified as {other:?}"),
        }
        // A document with no prose at all still names the class rather than guessing at a verdict.
        match transport_failure_from_reply(&json!({"ok": false})) {
            Some(PullError::Transport(detail)) => assert!(detail.contains("no bridge.governed-turn")),
            other => panic!("a bare document classified as {other:?}"),
        }
        // And a real §4.10(f) frame is NOT a transport failure — it is the parser's business, whether it
        // turns out to be a chunk or a refusal.
        assert!(transport_failure_from_reply(&ok_reply(TOKEN, 0, b"x", true)).is_none());
        assert!(transport_failure_from_reply(&refused_reply("stream_expired")).is_none());

        // Reached through `accept`, which is the only entry point a transport adapter has. Asserting it
        // only on the private helper would leave the WIRING untested — which is how a failed `connect()`
        // ends up wearing a supervisor's verdict.
        let sha = sha256_hex(b"x");
        let env = envelope(b"x", &sha);
        let mut pull = OutputPull::start(&env, TOKEN).unwrap();
        match pull.accept(&out_of_band).unwrap_err() {
            PullError::Transport(detail) => assert!(detail.contains("BROPS_SUPERVISOR_SOCKET")),
            other => panic!("accept read the out-of-band document as {other:?}"),
        }
    }

    /// The §4.10(f) P1-5 out-of-band class: a local sidecar failure yields no frame at all, so it must
    /// never arrive as a stream verdict. `Transport` carries the local cause instead.
    #[test]
    fn a_local_transport_failure_is_not_a_stream_verdict() {
        let output = b"x".to_vec();
        let sha = sha256_hex(&output);
        let err = pull(&output, &sha, |_| {
            Err(PullError::Transport("sidecar exited before writing a reply".into()))
        })
        .unwrap_err();
        match &err {
            PullError::Transport(detail) => assert!(detail.contains("sidecar")),
            other => panic!("a local failure surfaced as {other:?}"),
        }
        assert_eq!(err.to_turn_reason(), TurnReason::UpstreamBlocked);
    }

    // ---- The driver, which is what the async adapter actually uses ------------------------------

    /// The driver and the synchronous wrapper are the same machine. If they ever stop being, the
    /// adapter that runs in production is the one no test drives.
    #[test]
    fn the_driver_hands_out_exactly_the_requests_the_signed_length_names() {
        let output = vec![b'q'; (OUTPUT_CHUNK_BYTES + 3) as usize];
        let sha = sha256_hex(&output);
        let env = envelope(&output, &sha);
        let mut pull = OutputPull::start(&env, TOKEN).unwrap();
        let mut seqs = Vec::new();
        let mut serve = server(output.clone());
        while let Some(request) = pull.next_request() {
            seqs.push(request["seq"].as_u64().unwrap());
            let reply = serve(&request).unwrap();
            pull.accept(&reply).unwrap();
        }
        assert_eq!(seqs, vec![0, 1]);
        assert_eq!(pull.finish().unwrap(), output);
    }

    /// An abandoned pull is SHORT, and short is the length gate — not a separate "incomplete" state
    /// that a caller could forget to check.
    #[test]
    fn a_pull_abandoned_before_the_last_chunk_fails_the_length_gate() {
        let output = vec![b'q'; (OUTPUT_CHUNK_BYTES + 3) as usize];
        let sha = sha256_hex(&output);
        let env = envelope(&output, &sha);
        let mut pull = OutputPull::start(&env, TOKEN).unwrap();
        let mut serve = server(output.clone());
        let first = pull.next_request().unwrap();
        pull.accept(&serve(&first).unwrap()).unwrap();
        assert!(pull.next_request().is_some(), "one chunk short of the signed length");
        assert_eq!(pull.finish().unwrap_err(), PullError::LengthMismatch);
    }

    #[test]
    fn a_reply_handed_in_after_the_last_chunk_is_refused() {
        let output = b"short".to_vec();
        let sha = sha256_hex(&output);
        let env = envelope(&output, &sha);
        let mut pull = OutputPull::start(&env, TOKEN).unwrap();
        pull.accept(&ok_reply(TOKEN, 0, &output, true)).unwrap();
        assert!(pull.next_request().is_none());
        assert_eq!(
            pull.accept(&ok_reply(TOKEN, 1, b"extra", true)).unwrap_err(),
            PullError::EchoMismatch
        );
    }

    /// The length/digest gates are the SAME closed reason `verify_and_accept` uses for its own output
    /// gates, so a caller cannot tell "the pull disagreed" from "the acceptance disagreed" — which is
    /// correct: both mean the bytes are not the signed bytes.
    #[test]
    fn the_output_gates_block_with_the_commit_readback_reason() {
        assert_eq!(PullError::LengthMismatch.to_turn_reason(), TurnReason::CommitReadbackMismatch);
        assert_eq!(PullError::DigestMismatch.to_turn_reason(), TurnReason::CommitReadbackMismatch);
    }
}
