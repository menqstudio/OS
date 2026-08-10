//! Wave 3b-1B — the DESKTOP half of the rev-30 §4.6 `bridge.governed-turn-result.v1` frame.
//!
//! §4.10(e) is the supervisor's word about a finished governed turn. §4.6 is the shape that word takes
//! when it crosses the sidecar boundary — "the sidecar re-frames it into `bridge.governed-turn-result.v1`
//! (§4.6)" — and it is the ONLY thing that carries an `output_stream_id` to this side. The producing hop
//! lives in `bridge/governed_turn_result_bridge.py`; this module is the consumer.
//!
//! It is **pure**. No socket, no subprocess, no clock, no store, no signature check. It decides one
//! question — *is this document a §4.6 frame, and which arm* — and hands the decoded signed material to
//! the two modules that own the decisions: `governed_verification::verify_and_accept` (both signatures,
//! the attested turn binding, the ledger claim) and `governed_output_pull` (the §4.10(f) loop and the
//! whole-output gate).
//!
//! ## Who is speaking, and what that costs
//!
//! §2.4 declares the sidecar compromised, and §4.10(h) (**NOT IMPLEMENTED**) is explicit that it
//! "originates **no** governed verdict: it may neither mint a `GOVERNED_REFUSAL_REASONS` reason nor
//! emit a `signed` `bridge.governed-turn-result.v1`". So every field here arrives from a party that
//! may lie. Exactly two lies are available to it, and **both only ever end a turn**:
//!
//!  * **Downgrade** — turn a `signed` reply into a `Refused` frame carrying any member of the closed
//!    union, or send nothing at all. The desktop Blocks. Denial is inside a transport proxy's power by
//!    construction and 3b-1B does not claim otherwise (§4.10(f)'s "honest threat scope" says the same
//!    thing about confidentiality).
//!  * **Corrupt an echo** — alter `run_id`/`execution_attempt_id`/`output_bytes`/`output_sha256`/
//!    `supervisor_attestation_key_id` on the way past. [`SignedTurnResult::check_echoes`] catches that
//!    against the VERIFIED envelope, and the outcome is again a Block.
//!
//! What it cannot do is forge a success. A `signed` frame is inert without an `envelope_jcs_b64` that
//! verifies under the pinned isolated-signer key AND an `attestation_evidence_jcs_b64` that verifies
//! under the pinned supervisor-attestation key AND an attested record that is an account of *this* turn
//! (`governed_verification` steps 2/3/4c). §2.3 puts both keys out of the sidecar's reach — "`sidecar`,
//! `executor`, and `desktop` are in NEITHER `brops-store` nor any owner". Nor can it mint an
//! `output_stream_id`: the token is generated server-side and bound in the supervisor's `0700`
//! `governed_output_streams` row to `(receipt_id, execution_attempt_id, …)`, so an invented or
//! cross-turn token is refused `stream_binding_mismatch` before a byte is served (§4.10(f) P1-3).
//!
//! ## The echoes are PRIVATE, and that is the whole design of this type
//!
//! §4.10(e) says of its non-signature fields, twice, that they are **TRANSPORT-ONLY**. §4.6/§7.1 put the
//! real values in the isolated signer's envelope. A pull that gated reassembled bytes against the
//! *transport's* echo of their own digest would be a check a compromised sidecar supplies both sides of.
//!
//! `governed_output_pull` already makes that impossible by having no parameter for an expected digest.
//! This module keeps the property from being re-opened from the other end: `output_bytes` and
//! `output_sha256` are **not readable** off [`SignedTurnResult`]. There is no accessor. The only thing
//! that can be done with them is [`check_echoes`](SignedTurnResult::check_echoes), which takes a
//! [`ReceiptEnvelope`] and compares. A caller that wanted to aim a length or digest gate at the echo
//! would have to add a getter first, and that is a diff a reviewer can see.
//!
//! **What `check_echoes` is worth, precisely.** §7.1 requires it: "every `bridge.governed-turn-result.v1`
//! / `brops.governed-turn-result.v1` echo equals the verified envelope; a mismatch Blocks." It catches a
//! proxy that ALTERED what the supervisor said. It catches nothing at all against a proxy that copies
//! faithfully and lies elsewhere, because the envelope was already the authority — so this is a
//! consistency check on the transport, not a second opinion about the turn. It is not, and must never
//! become, the thing that decides whether the output is the signed output.
//!
//! ## `lease_id` is carried and cannot be checked
//!
//! §4.6 names `lease_id` in the receipt and §4.10(e) supplies it, but no signed artifact that reaches
//! this side carries it: the §4.9 envelope binds `lease_handle`, and the §4.6 attested evidence carries
//! `lease_handle` too. So [`SignedTurnResult::lease_id`] is an **unverifiable transport claim**, exposed
//! for forensics/logging and deliberately absent from `check_echoes` — there is nothing to check it
//! against, and a comparison invented for symmetry would be the exact "check that cannot fail" this file
//! is otherwise built to avoid. Nothing may gate on it.
//!
//! ## The arithmetic, done first
//!
//! The largest §4.6 frame is **74206 bytes** compact and **74236** as `engine_sidecar.run` writes it
//! (`json.dumps` default separators) — every string at its §4.6 encoded-byte cap,
//! `containment_evidence_b64` at its full 65536, `output_bytes` at 8388608. The largest refusal is
//! **296**. Constructed and asserted in this module's tests and in
//! `bridge/tests/test_governed_turn_result_bridge.py`, on both sides of the hop.
//!
//! **No cap on its path can fire.** The frame arrives on a one-shot sidecar's stdout, read under
//! `ai.rs::MAX_STDOUT_BYTES = 9437184`: 74236 against 9437184 is a factor of 127. §4.6 also names
//! `MAX_FRAME_BYTES = 262144`, which it fits 3.5× inside, but that bound belongs to `brops_protocol`'s
//! socket framing and this frame never crosses a socket. So this module ships **no size check** — the
//! same judgement `governed_output_pull` records for its own leg, and the same one that deleted a
//! §4.10(a)/(c) handler cap rather than shipping it.
//!
//! The bounds that would NOT admit it are why this is a subprocess-stdio hop at all:
//! `governed_supervisor_server.MAX_FRAME_BYTES` (broker-facing) and [`ipc_framing::MAX_FRAME_PAYLOAD_BYTES`]
//! are both **8192** — 9.06× too small here, 30× too small for a §4.10(f) chunk. A test pins the
//! comparison so a future "simplification" onto a framed-IPC path fails here rather than at the first
//! large containment blob in production.
//!
//! [`ipc_framing::MAX_FRAME_PAYLOAD_BYTES`]: crate::ipc_framing::MAX_FRAME_PAYLOAD_BYTES
//!
//! ## Where the design and this module disagree — read before assuming §4.6 is done
//!
//! §4.6's `receipt` lists **28** fields. Its only producer is the sidecar re-framer, and its only input
//! is the §4.10(e) `signed` arm, which carries 16 — of which 11 are also §4.6 names. The other **17**
//! have no source in that input, and **seven have no source anywhere the sidecar can reach**:
//! `status`/`exit_code`/`evidence[]` are the frozen `bridge.result.receipt` shape built from a
//! `SupervisorResult` the governed path never produces, and `challenge_registry_handle`/`_hash`/`_epoch`/
//! `_root_key_id` are resolved by the supervisor "from its own supervisor state" (§4.10(a0)) and never
//! returned on any reply the sidecar receives. §4.6 as written is therefore not constructible by its own
//! producer. This module implements the **intersection** — the 11 §4.6 names §4.10(e) supplies — and the
//! Python side carries the other 17 in a named tuple with a test asserting the union is exactly §4.6's
//! 28, so the gap is machine-checked rather than prose. It needs an Architect ruling, not a patch here.
//!
//! ## NOT WIRED — read this before believing the frame arrives
//!
//! Nothing in this tree calls [`BridgeTurnResult::parse`] in production, and the missing piece is again a
//! HOP rather than a hookup. §4.6 is the REPLY to §4.10(g)'s `bridge.governed-turn-submit.v1`, and
//! §4.10(g) is **NOT IMPLEMENTED**: there is no submit branch in `bridge/engine_sidecar.py`, no
//! orchestrator driving §4.10(a0) → §4.10(a)(b)(c) → §4.10(d) inside one one-shot subprocess, and so
//! nothing that ever holds a §4.10(e) reply to re-frame. Both ends of the join exist and are tested — the
//! supervisor produces the §4.10(e) frame (`engine/runtime/governed_acceptance.py`), the sidecar
//! re-frames it (`bridge/governed_turn_result_bridge.py`), and this module reads the result — and the
//! carriage between the desktop and the sidecar does not.
//!
//! A second, larger divergence sits behind that one and would survive fixing it: the broker's Linux
//! execution reads the recorder's output straight off the local filesystem
//! (`broker/src/chain_executor.rs::LinuxGovernedExecution`, `std::fs::read(&report_path)`) instead of
//! through the §4.10(f) egress at all.
//!
//! The dependency is made **typed** rather than described: a `signed` frame's capability token is only
//! useful through `governed_output_pull::OutputPull::start`, which cannot be constructed without a
//! verified [`ReceiptEnvelope`], so the day a §4.10(g) submit delivers one the compiler names every place
//! it has to reach. `config/reachability-declarations.json` carries the matching `rust_symbols`
//! declaration, so the reachability gate reports this as a declared gap with a written reason rather than
//! as green.

use crate::governed_turn_ipc::TurnReason;
use crate::governed_verification::ReceiptEnvelope;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use serde_json::Value;

// =================================================================================================
// §4.6 / §4.10(e) LOCKED literals
// =================================================================================================

/// §4.6/§2.2: the REQUIRED top-level discriminator. It is the one canonical bridge rule in both
/// directions — the frozen `bridge.result` is `additionalProperties:false` with no `protocol` key, so it
/// rejects this document; this shape requires the const, so it rejects a `bridge.result`. §4.6 says in as
/// many words that `receipt.envelope_jcs_b64` MUST NOT be used instead, because it is a REQUIRED key of
/// `bridge.result.receipt` too.
pub const BRIDGE_TURN_RESULT_PROTOCOL: &str = "bridge.governed-turn-result.v1";

/// §4.10(f): the capability is "32 cryptographically-random bytes, base64url no-pad, EXACTLY 43 chars".
/// Restated from `governed_output_pull` rather than imported so this module's parse does not depend on
/// the pull's; a test asserts the two are equal, which is the check that keeps them one number.
const OUTPUT_STREAM_ID_LEN: usize = 43;

/// §4.6/§4.10(e): `signature_b64` is "b64url 86" — a detached Ed25519 signature. 86 canonical base64url
/// characters decode to exactly 64 bytes, so there is no second check on the decoded length: it could
/// not fail.
const SIGNATURE_B64_LEN: usize = 86;

/// §4.6's frozen ENCODED-byte cap on `envelope_jcs_b64` (= `4·⌈2135/3⌉`, the §4.9 payload at schema max).
///
/// **The design's derivation is WRONG for the payload this tree's signer actually builds, and this
/// parser inherits that.** Nine of the §4.9 payload's seventeen string fields are ids capped at 128, so
/// at 125 characters each the encoding is 2852 and at the cap 2888 — 40 over. Established 2026-08-10 by
/// the §5 acceptance work, which refuses the over-cap case as a governed `oversize` verdict in
/// `engine/runtime/governed_acceptance.py` rather than letting it fault a frame validator. That is why
/// this cap can be enforced here without an escape hatch: a legitimate envelope over 2848 never reaches
/// a §4.6 frame, because §4.10(e) refuses to build one. The cap is still the design's number and the
/// design's number is still too small; it needs an Architect ruling, not a local widening.
const MAX_ENVELOPE_JCS_B64_LEN: usize = 2848;

/// §4.6's frozen ENCODED-byte cap on `attestation_evidence_jcs_b64` (= `4·⌈3498/3⌉`, the §4.4 evidence at
/// schema max).
const MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN: usize = 4664;

/// §4.6's frozen ENCODED-byte cap on `containment_evidence_b64`.
const MAX_CONTAINMENT_EVIDENCE_B64_LEN: usize = 65536;

/// §4.6/§4.10(e): every id field is `<string ≤128>`.
const MAX_ID_LEN: usize = 128;

/// §4.6/§4.10(e)/§4.10(f): `output_bytes` is `<int 0..8388608>`.
const MAX_OUTPUT_BYTES: u64 = 8_388_608;

/// The literal maximum §4.6 frame, as the sidecar writes it (`json.dumps` with default separators).
/// Asserted by construction in this module's tests and in `bridge/tests/test_governed_turn_result_bridge.py`,
/// so the two hops agree on one number rather than on two comments.
///
/// It is a constant because it is the number every transport under this hop has to admit — and two in
/// this tree do not: `ipc_framing::MAX_FRAME_PAYLOAD_BYTES` and the supervisor's broker-facing bound are
/// both 8192.
pub const MAX_BRIDGE_TURN_RESULT_BYTES: usize = 74_236;

/// The exhaustive §4.6 top-level key set. Five names, in the design's order.
const FRAME_FIELDS: [&str; 5] = ["protocol", "ok", "output_stream_id", "receipt", "error"];

/// The `receipt` object this hop accepts: the 11 names §4.6 lists that the §4.10(e) `signed` arm actually
/// supplies. See the module docs for the other 17 and why they are a design gap rather than an omission.
const RECEIPT_FIELDS: [&str; 11] = [
    "envelope_jcs_b64",
    "signature_b64",
    "containment_evidence_b64",
    "attestation_evidence_jcs_b64",
    "attestation_signature_b64",
    "supervisor_attestation_key_id",
    "run_id",
    "execution_attempt_id",
    "lease_id",
    "output_sha256",
    "output_bytes",
];

/// The closed §4.5 `GOVERNED_REFUSAL_REASONS` union that §4.6's `error.reason` embeds verbatim: the
/// ratified twelve of the frozen `brops.sign-result.v1` enum, then the seventeen governed additions, in
/// the exact order of `engine/runtime/governed_turn_result.py`, which is the single definition.
///
/// Held as an array rather than as a 29-variant enum on purpose. The desktop does not BRANCH on the
/// reason — §4.10(h) (**NOT IMPLEMENTED**) maps it to one bounded
/// `governed_verdict_refused:{reason}` Block — so the only property that has to hold is closedness,
/// and an array plus a private-field newtype gives exactly that with one place to compare against
/// the Python source of truth.
pub const GOVERNED_REFUSAL_REASONS: [&str; 29] = [
    // The ratified twelve (frozen `engine/contracts/brops-sign-result.v1.schema.json` enum order).
    "attestation_invalid",
    "not_completed",
    "run_binding_invalid",
    "nonce_mismatch",
    "handle_missing",
    "hash_mismatch",
    "policy_mismatch",
    "containment_missing",
    "identity_denied",
    "timestamp_invalid",
    "oversize",
    "malformed",
    // The seventeen governed additions (§4.5, P1-4).
    "challenge_replay",
    "acceptance_conflict",
    "lease_not_ready",
    "output_oversize",
    "output_timeout",
    "evidence_fork",
    "stale_evidence",
    "lease_expired",
    "challenge_invalidated",
    "retry_conflict",
    "stream_unknown",
    "stream_expired",
    "stream_binding_mismatch",
    "seq_out_of_range",
    "model_profile_unknown",
    "tcb_integrity_violation",
    "platform_unsupported",
];

// =================================================================================================
// The closed refusal
// =================================================================================================

/// A governed verdict the SUPERVISOR or the ISOLATED SIGNER reached, relayed by the sidecar.
///
/// The inner `&'static str` is a member of [`GOVERNED_REFUSAL_REASONS`] and the field is private,
/// so the only way to hold one is [`parse`](GovernedRefusal::parse) — a literal outside the closed
/// union cannot become a thirtieth reason, it is [`FrameError::MalformedFrame`].
/// §4.10(h) (**NOT IMPLEMENTED**) routes reasons to Blocks BY NAME, and an unmapped string would
/// fall through to whatever the default happens to be.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GovernedRefusal(&'static str);

impl GovernedRefusal {
    /// Parse a relayed reason. `None` for anything outside the closed union.
    pub fn parse(reason: &str) -> Option<GovernedRefusal> {
        GOVERNED_REFUSAL_REASONS
            .iter()
            .find(|known| **known == reason)
            .map(|known| GovernedRefusal(known))
    }

    /// The wire literal — the `{reason}` of §4.10(h) (**NOT IMPLEMENTED**)'s bounded
    /// `governed_verdict_refused:{reason}`.
    pub fn as_str(self) -> &'static str {
        self.0
    }
}

/// Why a §4.6 document did not yield a usable governed result.
///
/// [`Refused`](FrameError::Refused) is a VERDICT somebody with authority reached; the other two are this
/// parser's opinion about a shape. They are kept apart because a `lease_expired` in a log is worth
/// reading precisely when the other cases cannot produce one — the same distinction
/// `governed_output_pull` draws between `Refused` and `Transport`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FrameError {
    /// The document is not a §4.6 frame at all: wrong/absent protocol const, wrong key set, a value
    /// of the wrong kind or over its §4.6 cap, a non-canonical base64url field, or a reason outside
    /// the closed union. §4.10(h) (**NOT IMPLEMENTED**) item 4 turns this into
    /// `governed_transport_failure:{detail}` — it grants no authority and is never confusable with
    /// a verdict.
    MalformedFrame,
    /// A well-formed `ok:false` frame: the closed §4.5 verdict, relayed verbatim.
    Refused(GovernedRefusal),
}

impl FrameError {
    /// The closed renderer-facing reason. Both variants Block; a governed verdict and an unreadable
    /// document are both "an upstream stage refused this turn" as far as the renderer is concerned,
    /// and the distinction that matters lives in the durable Block reason
    /// §4.10(h) (**NOT IMPLEMENTED**) writes, not here.
    pub fn to_turn_reason(&self) -> TurnReason {
        TurnReason::UpstreamBlocked
    }
}

// =================================================================================================
// The signed arm
// =================================================================================================

/// A well-formed `ok:true` §4.6 frame, decoded.
///
/// Owned, because the base64url fields are decoded here: the bytes do not exist in the source document
/// and cannot be borrowed from it.
///
/// **Note what has no accessor.** `output_bytes` and `output_sha256` are stored and are not readable.
/// They exist solely for [`check_echoes`](SignedTurnResult::check_echoes), which compares them against a
/// verified envelope. §4.10(e) calls them TRANSPORT-ONLY and §4.6/§7.1 put the authority in the signed
/// envelope; a getter would be the first step in aiming an output gate at the transport's echo of its own
/// digest, which is a check a compromised sidecar supplies both sides of.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SignedTurnResult {
    /// §4.10(f)'s capability token: 43 base64url characters. The ONE member of this frame the desktop
    /// cannot obtain from the signed envelope, and the reason §4.6 exists rather than the envelope
    /// travelling alone.
    output_stream_id: String,
    /// The exact `JCS(payload)` bytes of the §4.9 receipt envelope. The isolated signer's signature is
    /// over these; `governed_verification` reconstructs and re-verifies it.
    envelope_jcs: Vec<u8>,
    /// base64url of the detached Ed25519 signature over the envelope payload — passed to
    /// `verify_and_accept` as `envelope_signature_b64`, which decodes it itself.
    envelope_signature_b64: String,
    /// The exact `JCS(evidence)` bytes the supervisor attested (§4.4/§4.6).
    attestation_evidence_jcs: Vec<u8>,
    /// base64url of the supervisor's detached signature over those bytes.
    attestation_signature_b64: String,
    /// The exact containment-evidence bytes, when the turn produced any (§4.6: nullable).
    containment_evidence: Option<Vec<u8>>,
    /// The forensic-only lease id — see the module docs: nothing signed carries it, so it can be checked
    /// against nothing and must gate nothing.
    lease_id: String,
    // ---- TRANSPORT-ONLY echoes. Private, and readable only through `check_echoes`. ----
    echo_run_id: String,
    echo_execution_attempt_id: String,
    echo_supervisor_attestation_key_id: String,
    echo_output_sha256: String,
    echo_output_bytes: u64,
}

impl SignedTurnResult {
    /// The §4.10(f) capability token.
    ///
    /// A bare `&str`, and it stays useless on its own: the only consumer is
    /// `governed_output_pull::OutputPull::start`, which pairs it with a [`ReceiptEnvelope`] via
    /// `OutputStreamCapability::from_envelope`, so the `receipt_id`/`execution_attempt_id` presented to
    /// the supervisor can only ever be the SIGNED ones (§4.10(f) P1-3). This module deliberately does not
    /// offer a second binding constructor — one would be a copy of that one, and the copy that runs in
    /// production is the one no test drives.
    pub fn output_stream_id(&self) -> &str {
        &self.output_stream_id
    }

    /// The §4.9 envelope's canonical payload bytes, for the caller to strict-parse into a
    /// [`ReceiptEnvelope`] and hand to `governed_verification::verify_and_accept`.
    pub fn envelope_jcs(&self) -> &[u8] {
        &self.envelope_jcs
    }

    /// The isolated-signer signature over [`envelope_jcs`](SignedTurnResult::envelope_jcs).
    pub fn envelope_signature_b64(&self) -> &str {
        &self.envelope_signature_b64
    }

    /// The exact bytes the supervisor attested, for `SupervisorAttestation::evidence_jcs`.
    pub fn attestation_evidence_jcs(&self) -> &[u8] {
        &self.attestation_evidence_jcs
    }

    /// The supervisor's signature over those bytes, for `SupervisorAttestation::signature_b64`.
    pub fn attestation_signature_b64(&self) -> &str {
        &self.attestation_signature_b64
    }

    /// The containment-evidence bytes, when the turn produced any (§4.6 makes this the one nullable
    /// member of the receipt). Not verified here: §4.9 binds its digest and the isolated signer's
    /// `LiveRunStateProvider` (§7) is what checks it.
    pub fn containment_evidence(&self) -> Option<&[u8]> {
        self.containment_evidence.as_deref()
    }

    /// The lease id, for logs and forensics ONLY.
    ///
    /// **Unverifiable.** No signed artifact reaching this side carries a `lease_id` — the §4.9 envelope
    /// and the §4.6 attested evidence both bind `lease_handle` instead — so this value is a transport
    /// claim with nothing to compare it against, and it is deliberately absent from
    /// [`check_echoes`](SignedTurnResult::check_echoes). Gate nothing on it.
    pub fn lease_id(&self) -> &str {
        &self.lease_id
    }

    /// §7.1's echo equality: every transported echo must equal the VERIFIED envelope.
    ///
    /// "every `bridge.governed-turn-result.v1` / `brops.governed-turn-result.v1` echo equals the verified
    /// envelope; a mismatch Blocks. A bare echo never authorizes anything."
    ///
    /// **What this is worth, exactly.** It catches a proxy that ALTERED what the supervisor said. It
    /// catches nothing against one that copies faithfully, because the envelope was already the
    /// authority — so it is a consistency check on the transport, not a second opinion about the turn.
    /// It is emphatically NOT the output gate: that is `governed_output_pull`'s length+digest against the
    /// same envelope, over the reassembled bytes, and this function's existence must never be read as
    /// making the echo authoritative for anything.
    ///
    /// `envelope` must be one `verify_and_accept` would accept — this compares, it does not verify a
    /// signature and does not claim to. Comparing against an unverified envelope proves only that two
    /// unverified documents agree.
    ///
    /// The attestation bytes are NOT checked here: `verify_and_accept` step 3 already requires
    /// `SHA256(evidence_jcs) == envelope.attestation_evidence_sha256` under the supervisor's signature,
    /// and a second copy of that check in this module would be the drift `governed_output_pull`'s docs
    /// warn about.
    pub fn check_echoes(&self, envelope: &ReceiptEnvelope) -> Result<(), TurnReason> {
        let string_pairs: [(&str, &str); 3] = [
            (self.echo_run_id.as_str(), envelope.run_id),
            (self.echo_execution_attempt_id.as_str(), envelope.execution_attempt_id),
            (
                self.echo_supervisor_attestation_key_id.as_str(),
                envelope.supervisor_attestation_key_id,
            ),
        ];
        for (echo, signed) in string_pairs {
            if echo != signed {
                return Err(TurnReason::UpstreamBlocked);
            }
        }
        if self.echo_output_sha256 != envelope.output_sha256 {
            return Err(TurnReason::UpstreamBlocked);
        }
        if self.echo_output_bytes != envelope.output_bytes {
            return Err(TurnReason::UpstreamBlocked);
        }
        Ok(())
    }
}

// =================================================================================================
// The parser
// =================================================================================================

/// A well-formed §4.6 frame: the two arms, told apart by `ok`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BridgeTurnResult {
    /// `ok:true` — a governed success, still worth nothing until both signatures verify.
    Signed(SignedTurnResult),
    /// `ok:false` — a governed verdict from the supervisor or the isolated signer, plus the forensic
    /// `receipt_id` when one had been minted (§4.6 makes it nullable: a turn refused before an id
    /// existed has none).
    Refused {
        reason: GovernedRefusal,
        receipt_id: Option<String>,
    },
}

impl BridgeTurnResult {
    /// Strict-decode one `bridge.governed-turn-result.v1` document.
    ///
    /// Strict in the same direction the producer is: exactly the five top-level keys with the protocol
    /// const, exactly the eleven receipt keys, every §4.6 encoded-byte cap, canonical base64url on every
    /// b64 field, and the closed union on the reason. Anything else is [`FrameError::MalformedFrame`] —
    /// never a refusal, because a refusal is somebody's verdict and this is the parser's opinion about a
    /// shape.
    ///
    /// Note that a `Refused` frame comes back as an `Err`. That is deliberate: there is exactly one
    /// document out of this function that lets a turn continue, so a caller cannot reach the success path
    /// by forgetting to match an arm.
    pub fn parse(doc: &Value) -> Result<SignedTurnResult, FrameError> {
        match Self::parse_frame(doc)? {
            BridgeTurnResult::Signed(signed) => Ok(signed),
            BridgeTurnResult::Refused { reason, .. } => Err(FrameError::Refused(reason)),
        }
    }

    /// The same decode, returning both arms — for a caller that needs the refusal's `receipt_id`, and for
    /// the tests that exercise the refused shape.
    pub fn parse_frame(doc: &Value) -> Result<BridgeTurnResult, FrameError> {
        let obj = doc.as_object().ok_or(FrameError::MalformedFrame)?;
        // Exact key set, both directions: no unknown key, none missing. `bridge.result` has no
        // `protocol` key and is `additionalProperties:false`, so the two shapes reject each other on the
        // discriminator alone — §4.6 forbids discriminating on `receipt.envelope_jcs_b64`, which is a
        // REQUIRED key of `bridge.result.receipt` too.
        if obj.len() != FRAME_FIELDS.len() || !FRAME_FIELDS.iter().all(|k| obj.contains_key(*k)) {
            return Err(FrameError::MalformedFrame);
        }
        if obj.get("protocol").and_then(Value::as_str) != Some(BRIDGE_TURN_RESULT_PROTOCOL) {
            return Err(FrameError::MalformedFrame);
        }
        let ok = obj.get("ok").and_then(Value::as_bool).ok_or(FrameError::MalformedFrame)?;

        if !ok {
            // §4.6's biconditionals, refused half: `output_stream_id`/`receipt` non-null iff ok==true.
            // Both halves are checked — a refusal carrying a capability token would be a Block that
            // still invited a read, and one carrying a receipt would be a Block wearing a success.
            if !obj["output_stream_id"].is_null() || !obj["receipt"].is_null() {
                return Err(FrameError::MalformedFrame);
            }
            let error = obj
                .get("error")
                .and_then(Value::as_object)
                .filter(|e| e.len() == 2)
                .ok_or(FrameError::MalformedFrame)?;
            let reason = error
                .get("reason")
                .and_then(Value::as_str)
                .and_then(GovernedRefusal::parse)
                .ok_or(FrameError::MalformedFrame)?;
            let receipt_id = match error.get("receipt_id").ok_or(FrameError::MalformedFrame)? {
                Value::Null => None,
                Value::String(s) => Some(bounded_id(s)?.to_string()),
                _ => return Err(FrameError::MalformedFrame),
            };
            return Ok(BridgeTurnResult::Refused { reason, receipt_id });
        }

        // §4.6's biconditionals, ok half.
        if !obj["error"].is_null() {
            return Err(FrameError::MalformedFrame);
        }
        let output_stream_id = obj
            .get("output_stream_id")
            .and_then(Value::as_str)
            .ok_or(FrameError::MalformedFrame)?;
        // §4.10(e), quoted by §4.6: a `signed` result REQUIRES `envelope_jcs_b64` + `signature_b64` +
        // `output_stream_id`. All three are members of the exhaustive required sets here, so the
        // predicate can never be PARTLY satisfied.
        exact_b64(output_stream_id, OUTPUT_STREAM_ID_LEN)?;

        let receipt = obj
            .get("receipt")
            .and_then(Value::as_object)
            .ok_or(FrameError::MalformedFrame)?;
        if receipt.len() != RECEIPT_FIELDS.len()
            || !RECEIPT_FIELDS.iter().all(|k| receipt.contains_key(*k))
        {
            return Err(FrameError::MalformedFrame);
        }

        let envelope_jcs = capped_b64(receipt, "envelope_jcs_b64", MAX_ENVELOPE_JCS_B64_LEN)?;
        let envelope_signature_b64 = exact_b64_field(receipt, "signature_b64")?;
        let attestation_evidence_jcs = capped_b64(
            receipt,
            "attestation_evidence_jcs_b64",
            MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN,
        )?;
        let attestation_signature_b64 = exact_b64_field(receipt, "attestation_signature_b64")?;
        let containment_evidence = match &receipt["containment_evidence_b64"] {
            Value::Null => None,
            _ => Some(capped_b64(
                receipt,
                "containment_evidence_b64",
                MAX_CONTAINMENT_EVIDENCE_B64_LEN,
            )?),
        };
        let echo_output_bytes = receipt
            .get("output_bytes")
            .and_then(Value::as_u64)
            .ok_or(FrameError::MalformedFrame)?;
        if echo_output_bytes > MAX_OUTPUT_BYTES {
            return Err(FrameError::MalformedFrame);
        }

        Ok(BridgeTurnResult::Signed(SignedTurnResult {
            output_stream_id: output_stream_id.to_string(),
            envelope_jcs,
            envelope_signature_b64,
            attestation_evidence_jcs,
            attestation_signature_b64,
            containment_evidence,
            lease_id: id_field(receipt, "lease_id")?.to_string(),
            echo_run_id: id_field(receipt, "run_id")?.to_string(),
            echo_execution_attempt_id: id_field(receipt, "execution_attempt_id")?.to_string(),
            echo_supervisor_attestation_key_id: id_field(
                receipt,
                "supervisor_attestation_key_id",
            )?
            .to_string(),
            echo_output_sha256: sha256_field(receipt, "output_sha256")?.to_string(),
            echo_output_bytes,
        }))
    }
}

// =================================================================================================
// Field validators
// =================================================================================================

/// A `<string ≤128>` id, non-empty.
fn bounded_id(value: &str) -> Result<&str, FrameError> {
    if value.is_empty() || value.len() > MAX_ID_LEN {
        return Err(FrameError::MalformedFrame);
    }
    Ok(value)
}

fn id_field<'a>(
    obj: &'a serde_json::Map<String, Value>,
    field: &str,
) -> Result<&'a str, FrameError> {
    bounded_id(obj.get(field).and_then(Value::as_str).ok_or(FrameError::MalformedFrame)?)
}

/// A lowercase 64-hex digest. Uppercase is refused rather than folded: two spellings of one digest in a
/// field an equality check is later run against is the ambiguity §4.10(a0)'s canonicality gate exists for.
fn sha256_field<'a>(
    obj: &'a serde_json::Map<String, Value>,
    field: &str,
) -> Result<&'a str, FrameError> {
    let value = obj.get(field).and_then(Value::as_str).ok_or(FrameError::MalformedFrame)?;
    if value.len() != 64 || !value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(FrameError::MalformedFrame);
    }
    Ok(value)
}

/// A base64url string of EXACTLY `len` characters, decodable. The length is checked first because §4.6
/// freezes these as ENCODED-byte lengths — an over-length value is over-length whether or not it decodes.
///
/// There is no second check on the DECODED length, because there cannot be one: 43 canonical base64url
/// characters decode to exactly 32 bytes and 86 to exactly 64, so `len == 43` plus the decode already
/// pins the byte count. A `decoded.len() == 32` line would read as protection while being unable to fail.
fn exact_b64(value: &str, len: usize) -> Result<Vec<u8>, FrameError> {
    if value.len() != len {
        return Err(FrameError::MalformedFrame);
    }
    // `URL_SAFE_NO_PAD` refuses padding, out-of-alphabet bytes AND non-canonical trailing bits, so a
    // string that merely decodes but is not the canonical encoding of what it decodes to is refused —
    // the same property `brops_protocol.decode_base64url` gives the producing hop.
    URL_SAFE_NO_PAD.decode(value.as_bytes()).map_err(|_| FrameError::MalformedFrame)
}

fn exact_b64_field(
    obj: &serde_json::Map<String, Value>,
    field: &str,
) -> Result<String, FrameError> {
    let value = obj.get(field).and_then(Value::as_str).ok_or(FrameError::MalformedFrame)?;
    exact_b64(value, SIGNATURE_B64_LEN)?;
    Ok(value.to_string())
}

/// A base64url string of 1..=`max` characters, decoded to its bytes.
fn capped_b64(
    obj: &serde_json::Map<String, Value>,
    field: &str,
    max: usize,
) -> Result<Vec<u8>, FrameError> {
    let value = obj.get(field).and_then(Value::as_str).ok_or(FrameError::MalformedFrame)?;
    if value.is_empty() || value.len() > max {
        return Err(FrameError::MalformedFrame);
    }
    URL_SAFE_NO_PAD.decode(value.as_bytes()).map_err(|_| FrameError::MalformedFrame)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::governed_output_pull::{OutputPull, OUTPUT_STREAM_ID_LEN as PULL_TOKEN_LEN};
    use serde_json::json;

    /// A canonical base64url string of exactly `n` characters — canonical because every b64 field here is
    /// decoded strictly, so padding a string to length with arbitrary alphabet bytes would turn a size
    /// test into a canonicality test by accident.
    fn b64url(n: usize) -> String {
        let raw = n / 4 * 3 + match n % 4 {
            0 => 0,
            2 => 1,
            3 => 2,
            _ => panic!("{n} is not a legal unpadded base64url length"),
        };
        URL_SAFE_NO_PAD.encode(vec![b'x'; raw])
    }

    fn receipt() -> Value {
        json!({
            "envelope_jcs_b64": b64url(120),
            "signature_b64": b64url(86),
            "containment_evidence_b64": b64url(40),
            "attestation_evidence_jcs_b64": b64url(200),
            "attestation_signature_b64": b64url(86),
            "supervisor_attestation_key_id": "attest-1",
            "run_id": "run-1",
            "execution_attempt_id": "attempt-1",
            "lease_id": "lease-1",
            "output_sha256": "a".repeat(64),
            "output_bytes": 11,
        })
    }

    fn signed_frame() -> Value {
        json!({
            "protocol": BRIDGE_TURN_RESULT_PROTOCOL,
            "ok": true,
            "output_stream_id": b64url(43),
            "receipt": receipt(),
            "error": null,
        })
    }

    fn refused_frame(reason: &str, receipt_id: Value) -> Value {
        json!({
            "protocol": BRIDGE_TURN_RESULT_PROTOCOL,
            "ok": false,
            "output_stream_id": null,
            "receipt": null,
            "error": { "reason": reason, "receipt_id": receipt_id },
        })
    }

    fn envelope<'a>(sha: &'a str, output_bytes: u64) -> ReceiptEnvelope<'a> {
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
            request_sha256: "b".repeat(64).leak(),
            record_handle: "c".repeat(64).leak(),
            lease_handle: "d".repeat(64).leak(),
            execution_receipt_handle: "e".repeat(64).leak(),
            output_sha256: sha,
            output_bytes,
            challenge_accepted_at_ms: 1_700_000_000_000,
            completed_at_ms: 1_700_000_000_001,
            evidence_final_event_hash: "f".repeat(64).leak(),
            evidence_event_count: 1,
            evidence_last_sequence: 0,
            evidence_head_sequence: 1,
            supervisor_attestation_key_id: "attest-1",
            attestation_evidence_sha256: "0".repeat(64).leak(),
        }
    }

    // ---- The two arms -------------------------------------------------------------------------

    #[test]
    fn a_signed_frame_yields_the_decoded_signed_material() {
        let signed = BridgeTurnResult::parse(&signed_frame()).expect("a well-formed signed frame");
        assert_eq!(signed.output_stream_id().len(), OUTPUT_STREAM_ID_LEN);
        assert_eq!(signed.envelope_jcs(), &URL_SAFE_NO_PAD.decode(b64url(120)).unwrap()[..]);
        assert_eq!(signed.envelope_signature_b64(), b64url(86));
        assert_eq!(
            signed.attestation_evidence_jcs(),
            &URL_SAFE_NO_PAD.decode(b64url(200)).unwrap()[..]
        );
        assert_eq!(signed.attestation_signature_b64(), b64url(86));
        assert_eq!(signed.containment_evidence(), Some(&URL_SAFE_NO_PAD.decode(b64url(40)).unwrap()[..]));
        assert_eq!(signed.lease_id(), "lease-1");
    }

    #[test]
    fn a_null_containment_evidence_is_a_contract_not_an_absence() {
        let mut frame = signed_frame();
        frame["receipt"]["containment_evidence_b64"] = Value::Null;
        let signed = BridgeTurnResult::parse(&frame).expect("§4.6 makes this member nullable");
        assert_eq!(signed.containment_evidence(), None);
        // ...but the KEY may not go missing: absent and null must not be the same frame.
        frame["receipt"].as_object_mut().unwrap().remove("containment_evidence_b64");
        assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
    }

    #[test]
    fn a_refused_frame_is_an_error_so_no_caller_reaches_success_by_forgetting_an_arm() {
        let err = BridgeTurnResult::parse(&refused_frame("lease_expired", json!("rcpt-9")));
        assert_eq!(
            err,
            Err(FrameError::Refused(GovernedRefusal::parse("lease_expired").unwrap()))
        );
        match BridgeTurnResult::parse_frame(&refused_frame("lease_expired", json!("rcpt-9"))) {
            Ok(BridgeTurnResult::Refused { reason, receipt_id }) => {
                assert_eq!(reason.as_str(), "lease_expired");
                assert_eq!(receipt_id.as_deref(), Some("rcpt-9"));
            }
            other => panic!("expected a refused arm, got {other:?}"),
        }
    }

    #[test]
    fn a_refusal_before_a_receipt_id_existed_carries_an_explicit_null() {
        match BridgeTurnResult::parse_frame(&refused_frame("lease_not_ready", Value::Null)) {
            Ok(BridgeTurnResult::Refused { receipt_id, .. }) => assert_eq!(receipt_id, None),
            other => panic!("expected a refused arm, got {other:?}"),
        }
        // Absent is NOT null: "no receipt id was minted" and "the field was forgotten" are different
        // frames, and §4.6 makes the key REQUIRED and nullable to keep them apart.
        let mut frame = refused_frame("lease_not_ready", Value::Null);
        frame["error"].as_object_mut().unwrap().remove("receipt_id");
        assert_eq!(BridgeTurnResult::parse_frame(&frame), Err(FrameError::MalformedFrame));
    }

    // ---- The closed union ---------------------------------------------------------------------

    #[test]
    fn every_member_of_the_closed_union_is_reachable_by_name() {
        for reason in GOVERNED_REFUSAL_REASONS {
            let err = BridgeTurnResult::parse(&refused_frame(reason, Value::Null));
            match err {
                Err(FrameError::Refused(r)) => assert_eq!(r.as_str(), reason),
                other => panic!("{reason} did not relay: {other:?}"),
            }
        }
        assert_eq!(GOVERNED_REFUSAL_REASONS.len(), 29);
    }

    #[test]
    fn a_reason_outside_the_closed_union_is_a_malformed_frame_not_a_thirtieth_reason() {
        // The literals below are real INTERNAL producer codes from §4.10(a0)/(a)/(d) and §2.1 — a
        // disjoint namespace §4.10(h) (**NOT IMPLEMENTED**) carries on its own diagnostic.
        // Admitting one here would let an internal refusal arrive wearing a governed verdict's
        // clothes.
        for outside in ["no_staging_row", "peer_denied", "challenge_expired", "noncanonical", ""] {
            assert_eq!(GovernedRefusal::parse(outside), None, "{outside}");
            assert_eq!(
                BridgeTurnResult::parse(&refused_frame(outside, Value::Null)),
                Err(FrameError::MalformedFrame)
            );
        }
    }

    #[test]
    fn two_reasons_spelled_the_same_in_both_namespaces_are_still_admitted() {
        // `malformed` and `retry_conflict` are members of BOTH the closed governed union and the
        // internal producer sets. §4.10(h) (**NOT IMPLEMENTED**) calls the internal set disjoint,
        // which is true of the NAMESPACE and false of the strings: what separates them is the
        // protocol const they arrive under, never the spelling.
        for shared in ["malformed", "retry_conflict"] {
            assert_eq!(GovernedRefusal::parse(shared).unwrap().as_str(), shared);
        }
    }

    // ---- Discrimination (§2.2, both directions) ------------------------------------------------

    #[test]
    fn a_frozen_bridge_result_is_rejected_and_not_on_envelope_jcs_b64() {
        // §4.6: "The earlier claim that `receipt.envelope_jcs_b64` is 'absent from bridge.result' was
        // FALSE — it is a REQUIRED key of `bridge.result.receipt` — and MUST NOT be used to
        // discriminate." This document carries one, so a discriminator built on it would admit it.
        let frozen = json!({
            "ok": true,
            "result": "hello",
            "receipt": {
                "task_id": "t", "status": "completed", "exit_code": 0,
                "evidence": ["evidence:1"],
                "envelope_jcs_b64": b64url(120), "signature_b64": b64url(86),
            },
            "error": null,
        });
        assert!(frozen["receipt"]["envelope_jcs_b64"].is_string());
        assert_eq!(BridgeTurnResult::parse(&frozen), Err(FrameError::MalformedFrame));
    }

    #[test]
    fn a_document_under_any_other_protocol_const_is_rejected() {
        for other in [
            "brops.governed-turn-result.v1",
            "bridge.governed-turn-output-read-result.v1",
            "bridge.governed-turn-diagnostic.v1",
            "",
        ] {
            let mut frame = signed_frame();
            frame["protocol"] = json!(other);
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{other}");
        }
    }

    #[test]
    fn a_diagnostic_can_never_satisfy_the_signed_predicate() {
        // §4.10(h) (**NOT IMPLEMENTED**) requires its diagnostic to be unable to satisfy this
        // frame. Pinned from this side too, so the day it lands the two shapes are already proven
        // non-confusable.
        let diagnostic = json!({
            "protocol": "bridge.governed-turn-diagnostic.v1",
            "stage": "staging-open",
            "upstream_reason": "no_staging_row",
        });
        assert_eq!(BridgeTurnResult::parse(&diagnostic), Err(FrameError::MalformedFrame));
    }

    // ---- The strict shape ----------------------------------------------------------------------

    #[test]
    fn an_unknown_key_at_either_level_is_rejected() {
        let mut frame = signed_frame();
        frame["result"] = json!("hello");
        assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
        let mut frame = signed_frame();
        frame["receipt"]["verified"] = json!(true);
        assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
    }

    #[test]
    fn every_required_key_is_required_by_name() {
        for key in FRAME_FIELDS {
            let mut frame = signed_frame();
            frame.as_object_mut().unwrap().remove(key);
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{key}");
        }
        for key in RECEIPT_FIELDS {
            let mut frame = signed_frame();
            frame["receipt"].as_object_mut().unwrap().remove(key);
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{key}");
        }
    }

    #[test]
    fn a_frame_that_is_both_a_success_and_a_refusal_is_rejected() {
        let mut frame = signed_frame();
        frame["error"] = json!({ "reason": "malformed", "receipt_id": null });
        assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
    }

    #[test]
    fn an_error_object_with_an_extra_or_a_wrong_second_key_is_rejected() {
        // The `error` object is `{reason, receipt_id}` and nothing else. Both halves are live and
        // each needs its own fixture: an EXTRA key (a §4.10(h) (**NOT IMPLEMENTED**) `stage`, the
        // most likely thing to arrive here by mistake) and a second key that is not `receipt_id` at
        // all. Mutation testing found the second one masked by the first — a `len == 2` filter hides
        // a missing-key check unless something presents two keys of the wrong names.
        let mut frame = refused_frame("malformed", Value::Null);
        frame["error"]["stage"] = json!("staging-open");
        assert_eq!(BridgeTurnResult::parse_frame(&frame), Err(FrameError::MalformedFrame));

        let frame = json!({
            "protocol": BRIDGE_TURN_RESULT_PROTOCOL,
            "ok": false,
            "output_stream_id": null,
            "receipt": null,
            "error": { "reason": "malformed", "stage": "staging-open" },
        });
        assert_eq!(BridgeTurnResult::parse_frame(&frame), Err(FrameError::MalformedFrame));
    }

    #[test]
    fn a_non_canonical_capability_token_is_refused_rather_than_re_encoded() {
        // `exact_b64` decodes as well as measures, and both halves are live. A 43-character string
        // is the right LENGTH for a capability and can still be three different kinds of wrong:
        // out-of-alphabet, standard-base64 rather than base64url, and non-canonical trailing bits
        // (43 chars carry 2 leftover bits, which must be zero). The supervisor mints only the
        // canonical form, so anything else is a token it never issued.
        let good = b64url(43);
        for bad in [
            format!("{}*", &good[..42]),
            format!("{}+", &good[..42]),
            format!("{}/", &good[..42]),
        ] {
            assert_eq!(bad.len(), 43);
            let mut frame = signed_frame();
            frame["output_stream_id"] = json!(bad);
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{bad}");
        }
        // Trailing bits: `-` is base64url 62 (0b111110), so its low four bits are not zero and a
        // 43-character string ending in it is not the canonical encoding of the 32 bytes it names.
        let mut frame = signed_frame();
        frame["output_stream_id"] = json!(format!("{}-", &good[..42]));
        assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
    }

    #[test]
    fn a_refusal_may_smuggle_neither_a_capability_token_nor_a_receipt() {
        let mut frame = refused_frame("malformed", Value::Null);
        frame["output_stream_id"] = json!(b64url(43));
        assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
        let mut frame = refused_frame("malformed", Value::Null);
        frame["receipt"] = receipt();
        assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
    }

    #[test]
    fn ok_must_be_a_boolean_not_a_truthy_value() {
        for bad in [json!(1), json!("true"), Value::Null] {
            let mut frame = signed_frame();
            frame["ok"] = bad;
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
        }
    }

    #[test]
    fn a_token_of_any_other_length_is_not_a_capability() {
        for token in [b64url(40), b64url(44), String::new()] {
            let mut frame = signed_frame();
            frame["output_stream_id"] = json!(token);
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame));
        }
    }

    #[test]
    fn a_non_canonical_base64url_field_is_refused_rather_than_re_encoded() {
        // Padded, out-of-alphabet, and non-canonical trailing bits: three ways to spell bytes that a
        // lenient decoder would accept and a strict one must not, in a field §7.1 later compares.
        for bad in ["=".to_string() + &b64url(120)[1..], b64url(120)[1..].to_string() + "*", "AB".to_string()] {
            let mut frame = signed_frame();
            frame["receipt"]["envelope_jcs_b64"] = json!(bad);
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{bad}");
        }
    }

    #[test]
    fn each_encoded_byte_cap_is_one_stride_from_refusing() {
        for (field, cap) in [
            ("envelope_jcs_b64", MAX_ENVELOPE_JCS_B64_LEN),
            ("attestation_evidence_jcs_b64", MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN),
            ("containment_evidence_b64", MAX_CONTAINMENT_EVIDENCE_B64_LEN),
        ] {
            let mut frame = signed_frame();
            frame["receipt"][field] = json!(b64url(cap));
            assert!(BridgeTurnResult::parse(&frame).is_ok(), "{field} at its cap must be legal");
            frame["receipt"][field] = json!(b64url(cap + 4));
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{field}");
        }
    }

    #[test]
    fn output_bytes_is_bounded_at_the_eight_mib_ceiling() {
        let mut frame = signed_frame();
        frame["receipt"]["output_bytes"] = json!(MAX_OUTPUT_BYTES);
        assert!(BridgeTurnResult::parse(&frame).is_ok());
        for bad in [json!(MAX_OUTPUT_BYTES + 1), json!(-1), json!("11"), json!(1.5)] {
            frame["receipt"]["output_bytes"] = bad.clone();
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{bad}");
        }
    }

    #[test]
    fn an_id_over_its_cap_or_empty_is_rejected() {
        for field in ["run_id", "execution_attempt_id", "lease_id", "supervisor_attestation_key_id"] {
            let mut frame = signed_frame();
            frame["receipt"][field] = json!("x".repeat(MAX_ID_LEN));
            assert!(BridgeTurnResult::parse(&frame).is_ok(), "{field} at its cap must be legal");
            frame["receipt"][field] = json!("x".repeat(MAX_ID_LEN + 1));
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{field}");
            frame["receipt"][field] = json!("");
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{field}");
        }
    }

    #[test]
    fn an_output_sha256_that_is_not_lowercase_64_hex_is_rejected() {
        for bad in ["A".repeat(64), "a".repeat(63), "a".repeat(65), "g".repeat(64)] {
            let mut frame = signed_frame();
            frame["receipt"]["output_sha256"] = json!(bad);
            assert_eq!(BridgeTurnResult::parse(&frame), Err(FrameError::MalformedFrame), "{bad}");
        }
    }

    // ---- §7.1 echo equality --------------------------------------------------------------------

    #[test]
    fn a_faithful_frame_agrees_with_the_envelope_it_carries() {
        let signed = BridgeTurnResult::parse(&signed_frame()).unwrap();
        assert_eq!(signed.check_echoes(&envelope(&"a".repeat(64), 11)), Ok(()));
    }

    #[test]
    fn each_altered_echo_blocks_by_name() {
        // Every echo, one at a time. This is the check §7.1 requires and it catches exactly one thing:
        // a proxy that altered what the supervisor said. It is worth nothing against one that copies
        // faithfully — the envelope was already the authority.
        let cases: [(&str, Value); 5] = [
            ("run_id", json!("run-2")),
            ("execution_attempt_id", json!("attempt-2")),
            ("supervisor_attestation_key_id", json!("attest-2")),
            ("output_sha256", json!("b".repeat(64))),
            ("output_bytes", json!(12)),
        ];
        for (field, altered) in cases {
            let mut frame = signed_frame();
            frame["receipt"][field] = altered;
            let signed = BridgeTurnResult::parse(&frame).expect("still a well-formed frame");
            assert_eq!(
                signed.check_echoes(&envelope(&"a".repeat(64), 11)),
                Err(TurnReason::UpstreamBlocked),
                "{field}"
            );
        }
    }

    #[test]
    fn the_echoes_have_no_accessor_so_no_gate_can_be_aimed_at_them() {
        // The structural half of "the digest and length come from the SIGNED envelope". There is no
        // `output_bytes()` and no `output_sha256()` on `SignedTurnResult`, so a caller cannot pass the
        // transport's echo of its own digest into a length or digest gate even by mistake; it would
        // have to add a getter first, which is a diff a reviewer can see. This test is a text assertion
        // because the property it pins is the ABSENCE of an API.
        let source = include_str!("governed_bridge_result.rs");
        let api = source.split("#[cfg(test)]").next().expect("the non-test half");
        assert!(!api.contains("pub fn output_bytes"));
        assert!(!api.contains("pub fn output_sha256"));
        // ...and the other half of the same property, one module along: `governed_output_pull`'s
        // entry points take a `ReceiptEnvelope` and read the length and the digest off it, so there is
        // no call shape anywhere in which this frame's echo of them could become the gate.
        let pull = include_str!("governed_output_pull.rs");
        let pull_api = pull.split("#[cfg(test)]").next().expect("the non-test half");
        assert!(pull_api.contains("pub fn pull_output("));
        assert!(pull_api.contains("envelope: &ReceiptEnvelope,"));
        // No constructor or entry point there takes a length or a digest as a parameter, so the
        // only values those gates can read are the envelope's.
        assert!(!pull_api.contains("output_bytes: u64,"));
        assert!(!pull_api.contains("expected_sha256: &str,"));
    }

    #[test]
    fn the_lease_id_is_carried_and_deliberately_unchecked() {
        // Nothing signed that reaches this side carries a `lease_id` — the §4.9 envelope binds
        // `lease_handle` — so there is nothing to compare it against, and a comparison invented for
        // symmetry would be a check that cannot fail. It is forensic, and `check_echoes` ignores it.
        let mut frame = signed_frame();
        frame["receipt"]["lease_id"] = json!("a-completely-different-lease");
        let signed = BridgeTurnResult::parse(&frame).unwrap();
        assert_eq!(signed.lease_id(), "a-completely-different-lease");
        assert_eq!(signed.check_echoes(&envelope(&"a".repeat(64), 11)), Ok(()));
    }

    // ---- The typed dependency ------------------------------------------------------------------

    #[test]
    fn the_token_this_frame_carries_is_the_one_the_pull_binds_to_an_envelope() {
        // The join, exercised end to end without a subprocess: a §4.6 frame yields a token, and the
        // §4.10(f) pull binds it to a VERIFIED envelope — which is the only way a read can present the
        // `receipt_id`/`execution_attempt_id` §4.10(f) P1-3 requires. There is no path from this frame
        // to a read that does not go through that binding.
        assert_eq!(OUTPUT_STREAM_ID_LEN, PULL_TOKEN_LEN);
        let signed = BridgeTurnResult::parse(&signed_frame()).unwrap();
        let sha = "a".repeat(64);
        let env = envelope(&sha, 11);
        let pull = OutputPull::start(&env, signed.output_stream_id()).expect("a legal capability");
        let request = pull.next_request().expect("one read for an 11-byte output");
        assert_eq!(request["output_stream_id"], json!(signed.output_stream_id()));
        // The two ids on the wire came from the ENVELOPE, never from this frame.
        assert_eq!(request["receipt_id"], json!("rcpt-1"));
        assert_eq!(request["execution_attempt_id"], json!("attempt-1"));
    }

    // ---- The arithmetic ------------------------------------------------------------------------

    #[test]
    fn the_literal_maximum_frame_is_the_number_this_module_publishes() {
        let max = json!({
            "protocol": BRIDGE_TURN_RESULT_PROTOCOL,
            "ok": true,
            "output_stream_id": b64url(43),
            "receipt": {
                "envelope_jcs_b64": b64url(MAX_ENVELOPE_JCS_B64_LEN),
                "signature_b64": b64url(86),
                "containment_evidence_b64": b64url(MAX_CONTAINMENT_EVIDENCE_B64_LEN),
                "attestation_evidence_jcs_b64": b64url(MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN),
                "attestation_signature_b64": b64url(86),
                "supervisor_attestation_key_id": "s".repeat(MAX_ID_LEN),
                "run_id": "u".repeat(MAX_ID_LEN),
                "execution_attempt_id": "a".repeat(MAX_ID_LEN),
                "lease_id": "l".repeat(MAX_ID_LEN),
                "output_sha256": "f".repeat(64),
                "output_bytes": MAX_OUTPUT_BYTES,
            },
            "error": null,
        });
        assert!(BridgeTurnResult::parse(&max).is_ok(), "the maximum instance must be LEGAL");
        // `serde_json::to_vec` is compact, which is what the Python side calls its compact number.
        assert_eq!(serde_json::to_vec(&max).unwrap().len(), 74_206);
        // What actually arrives is `json.dumps(reply)` with DEFAULT separators — 30 bytes of spacing
        // more on this shape, and the number a cap would have to admit.
        assert_eq!(MAX_BRIDGE_TURN_RESULT_BYTES, 74_236);
        assert_eq!(MAX_BRIDGE_TURN_RESULT_BYTES - serde_json::to_vec(&max).unwrap().len(), 30);
    }

    #[test]
    fn no_cap_on_this_frames_path_could_fire() {
        // `ai.rs:44` — `const MAX_STDOUT_BYTES: u64 = 9 * 1024 * 1024;`
        const MAX_STDOUT_BYTES: usize = 9 * 1024 * 1024;
        assert_eq!(MAX_STDOUT_BYTES, 9_437_184);
        assert!(MAX_BRIDGE_TURN_RESULT_BYTES < MAX_STDOUT_BYTES);
        assert_eq!(MAX_STDOUT_BYTES - MAX_BRIDGE_TURN_RESULT_BYTES, 9_362_948);
        assert!(MAX_STDOUT_BYTES > MAX_BRIDGE_TURN_RESULT_BYTES * 127);
        // §4.6 also names MAX_FRAME_BYTES = 262144. It fits 3.5x inside, and that bound belongs to
        // `brops_protocol`'s socket framing — this frame never crosses a socket.
        assert!(MAX_BRIDGE_TURN_RESULT_BYTES * 3 < 262_144);
    }

    #[test]
    fn no_framed_ipc_path_in_this_tree_could_carry_this_frame() {
        // The bound that decides this hop's shape, exactly as `governed_output_pull` pins it for its
        // own leg. Both framed-IPC caps in the tree are 8192; a maximum §4.6 frame is 9.06x that. If
        // someone later "simplifies" the result onto `ipc_framing`, this is what says no.
        assert_eq!(crate::ipc_framing::MAX_FRAME_PAYLOAD_BYTES, 8192);
        assert!(MAX_BRIDGE_TURN_RESULT_BYTES > crate::ipc_framing::MAX_FRAME_PAYLOAD_BYTES * 9);
    }

    #[test]
    fn the_largest_refusal_is_under_three_hundred_bytes() {
        // Two members tie at 23 characters (`stream_binding_mismatch`, `tcb_integrity_violation`), so
        // the longest is pinned by NAME and by length rather than by `max_by_key`, whose tie-break
        // differs from Python's `max` and would have made the two hops assert different reasons.
        let longest = GOVERNED_REFUSAL_REASONS.iter().map(|r| r.len()).max().unwrap();
        assert_eq!(longest, 23);
        assert_eq!("stream_binding_mismatch".len(), longest);
        let frame = refused_frame("stream_binding_mismatch", json!("r".repeat(MAX_ID_LEN)));
        assert!(matches!(
            BridgeTurnResult::parse_frame(&frame),
            Ok(BridgeTurnResult::Refused { .. })
        ));
        // 284 compact; the Python hop writes the SAME document with `json.dumps` default separators
        // and asserts 296 as well as this 284, so the two hops agree on one instance rather than on
        // two comments.
        assert_eq!(serde_json::to_vec(&frame).unwrap().len(), 284);
    }

    #[test]
    fn the_module_ships_no_size_check_because_none_could_fire() {
        let source = include_str!("governed_bridge_result.rs");
        let api = source.split("#[cfg(test)]").next().expect("the non-test half");
        // The constant is published for the tests and for the comparison above; nothing in the parser
        // compares a document against it, because a check that cannot fire reads as protection while
        // protecting nothing.
        assert_eq!(api.matches("MAX_BRIDGE_TURN_RESULT_BYTES").count(), 1);
    }
}
