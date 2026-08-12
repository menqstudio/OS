//! Wave 3b-1B §4.10(g) — **the thing that writes the submit frame.**
//!
//! `bridge/governed_turn_submit.py` is the CONSUMER: one `bridge.governed-turn-submit.v1` frame on
//! `stdin` drives §4.10(a0) open → §4.10(a)(b)(c) staging → §4.10(d) trigger → the §4.6 re-frame,
//! inside one one-shot subprocess, proven end to end against the real supervisor services. Until
//! this module, nothing in the tree PRODUCED that frame — `governed_turn_submit_prepared` returned
//! zero hits in a whole-tree grep, and that single absence is why all six `rust_symbols` in
//! `config/reachability-declarations.json` were declared caller-less.
//!
//! ## Which process, and why
//!
//! The BROKER service (§0 role #2). §0's LOCKED terminology binding resolves every trusted-actor
//! "the desktop"/"backend" in the normative body to the broker service in its own process, and §4.10(g)'s
//! Principal binding says it again for this hop: "`governed_turn_execute` and every step below
//! execute **inside the trusted desktop verifier/BROKER service process**". So this lives in
//! `brops-core` — the crate the `brops-broker` binary wires, beside `broker_orchestrator` and
//! `governed_verification` — and NOT in `apps/desktop/src-tauri/src/`, which hosts the renderer.
//!
//! ## What is here and what is deliberately NOT
//!
//! Everything that decides BYTES is here: the cross-bindings, the frame, the strict decode of the
//! §4.6 reply. The subprocess spawn is NOT — it is an INJECTED seam ([`SubmitTransport`]), the same
//! shape `chain_executor` uses for `HopConnector`/`GovernedExecution` and the same shape the Python
//! half uses for `request_supervisor`.
//!
//! §4.10(g) says the helper "spawns the one-shot governed sidecar exactly as `ai.rs::governed_engine`
//! does today". **Updated 2026-08-12: "exactly as" is now literal.** That spawn seam used to be
//! `ai::governed_sidecar_call` — `async` `tokio`, in the renderer-hosting app crate, carrying
//! `engine_trust::apply` (the provisioned trust environment without which a governed call is the
//! ungoverned call it exists to prevent) — and the synchronous broker binary could not call it.
//! Writing a second spawn here would have been exactly the "half-wired export" that function's own
//! comment warned about: one path consulting the provisioned trust and the other the stale committed
//! registry, with nothing to say so. So the spawn moved instead. It is now
//! [`crate::governed_sidecar::GovernedSidecar`] — in THIS crate, synchronous, used by the app through
//! `spawn_blocking` and available to the broker directly — and it implements [`SubmitTransport`].
//! There is one spawn, and what it must carry follows the PROTOCOL rather than the caller:
//! [`crate::governed_sidecar::SidecarTrust::Provisioned`] holds a resolved
//! [`crate::engine_trust::TrustEnvironment`] and is required for `bridge.task-request` and the
//! `governance.read` op, while a transport that relays only this frame and the §4.10(f) read carries
//! [`crate::governed_sidecar::SidecarTrust::RelayFramesOnly`] — whose door then refuses, before any
//! process exists, every request whose own `protocol` is not one of those two. The BROKER passes the
//! latter, because it cannot hold the former: the provisioned set's conductor-session token binds the
//! CONDUCTOR's identity and the broker is §0 role #2.
//!
//! What is still true, and is the honest remaining gap: **nothing CALLS
//! [`governed_turn_submit_prepared`]**. Giving the writer a transport did not give it a caller —
//! wiring one would move the shipped broker off its fail-closed executor, which is the owner's
//! decision. Its `declared_unreachable` entry in `config/reachability-declarations.json` stands.
//!
//! ## The three checks this module does NOT make, mirroring the consumer
//!
//! The Python half declines three local checks because writing them would make a SUPERVISOR verdict
//! unreachable through the only client that exists. The same discipline binds the producer:
//!
//! * **The challenge document is carried VERBATIM.** [`ChallengeDocument`] retains the exact bytes it
//!   was given and base64url-encodes *those*; it never re-serializes the parsed value. §4.10(a0)'s
//!   canonicality gate hashes what arrives, so bytes this process chose would be the divergence that
//!   gate exists to refuse, and `noncanonical` would stop being reachable.
//! * **The three artifact digests are not compared against anything the sidecar will compare them
//!   against.** The frame carries `system`/`history`/`generation_config` and the sidecar derives the
//!   digests itself; §4.10(a)'s `digest_mismatch` and §4.10(c)'s `handle_not_challenge` stay the
//!   supervisor's to produce.
//! * **The §4.6 reply's echoes are not checked here.** `SignedTurnResult::check_echoes` needs a
//!   VERIFIED envelope, and verification is §6.1 step 14 / §7.1 — a later stage with a different
//!   owner. Checking a transport echo against another transport value would be a check the sidecar
//!   supplies both sides of.
//!
//! What IS checked is the set §4.10(g) makes a **terminal Block**: the cross-bindings between the
//! orchestration object and the signed challenge. Those are checks about THIS process's own
//! consistency, which no other party can make.

use serde_json::{json, Value};

use crate::governed_bridge_result::{BridgeTurnResult, FrameError, SignedTurnResult};
use crate::governed_prepare::{PreparedGovernedTurnV1B, MAX_ID_LEN};
use crate::governed_turn_ipc::TurnReason;
use crate::receipt::sha256_hex;

/// §2.2/§4.10(g): the ingress frame's own protocol const — the ONE canonical discriminator.
///
/// The frozen `bridge.task-request` is `additionalProperties:false` with no `protocol` key and no
/// `challenge_doc_b64`, and 3b-1A's positive control depends on it byte-for-byte, so it cannot be
/// extended. This const both admits this frame and, by being absent from the frozen family, keeps
/// the two disjoint in both directions.
pub const BRIDGE_SUBMIT_PROTOCOL: &str = "bridge.governed-turn-submit.v1";

/// The exhaustive top-level field set, `additionalProperties:false`. Six names, and the writer emits
/// exactly these — `the_frame_carries_exactly_the_six_designed_fields` asserts it against the
/// consumer's own list.
pub const SUBMIT_REQUEST_FIELDS: [&str; 6] =
    ["challenge_doc_b64", "generation_config", "history", "protocol", "system", "task_id"];

/// §4.10(g): `challenge_doc_b64` is "base64url of the exact signed `{payload,sig}` bytes, decoded
/// ≤ 4096". IMPORTED as a number from §4.10(a0), which is the gate that would otherwise answer
/// `doc_oversize`; applied here so an over-cap document is refused before a frame exists rather than
/// producing one the open hop must reject.
pub const MAX_CHALLENGE_DOC_BYTES: usize = 4096;

// =================================================================================================
// Refusals
// =================================================================================================

/// Why a governed submit did not produce a usable §4.6 result.
///
/// Four disjoint classes, and they are separate members rather than one string because they have
/// different OWNERS: a cross-binding failure is this broker disagreeing with itself, a challenge
/// fault is the authority's document being unusable, a transport failure is the subprocess, and a
/// [`Frame`](SubmitError::Frame) `Refused` is a governed verdict somebody with authority reached.
/// Collapsing them would put "the supervisor refused" and "the spawn failed" in one bucket, which is
/// the exact distinction §4.10(f) and §4.10(h) (**NOT IMPLEMENTED**) spend their length preserving.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SubmitError {
    /// A §4.10(g) cross-binding did not hold. **Terminal Block**, never retried: the orchestration
    /// object and the signed challenge describe different turns, and no amount of retrying makes
    /// them agree.
    CrossBinding(CrossBinding),
    /// The challenge document cannot be carried: over [`MAX_CHALLENGE_DOC_BYTES`], not a strict JSON
    /// object, or missing the §4.1 payload fields the cross-bindings compare against.
    ChallengeDocument(&'static str),
    /// `task_id`/`run_id`/`conversation_id` is empty or over [`MAX_ID_LEN`].
    IdInvalid(&'static str),
    /// `prepared.self_check()` failed — the prepared object's JCS and its committed digest disagree.
    /// Unreachable while [`PreparedGovernedTurnV1B`] has exactly one constructor; see that method.
    PreparedSelfCheck,
    /// The sidecar could not be reached, timed out, crashed, or answered with something that is not
    /// JSON. NOT a verdict: §6.1 makes a local ingress/transport failure out-of-band, and the sidecar
    /// originates no supervisor or signature verdict.
    Transport(String),
    /// The reply was a §4.6 document: either malformed, or a well-formed governed REFUSAL relayed
    /// verbatim from the supervisor or the isolated signer.
    Frame(FrameError),
}

/// Which §4.10(g) cross-binding failed. Each is produced by a test.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CrossBinding {
    /// `submit.task_id == execution.task_id == challenge_document.payload.task_id`.
    TaskId,
    /// `challenge_document.payload.run_id == execution.run_id`.
    RunId,
    /// `SHA256(JCS(execution.prepared.generation_config)) ==
    /// challenge_document.payload.generation_config_sha256`.
    GenerationConfigSha256,
    /// `execution.prepared.request_sha256() == challenge_document.payload.request_sha256`.
    ///
    /// **Not one of §4.10(g)'s three, and named as an addition.** §4.10(g) requires the pre-submit
    /// assert `prepared.issued_request().request_sha256() == the pre-stored
    /// receipt_challenges.request_sha256`; that comparison needs the receipt DB, which the frame
    /// writer neither holds nor should, so it belongs to `governed_turn_execute` (step 2 pre-store).
    /// What IS available here is the §4.1 payload's own `request_sha256`, which the authority derived
    /// from the create-pending facts. It is the same §2.2 envelope digest over the same eight fields,
    /// so equality must hold for a legitimate turn and a mismatch means the authority signed a
    /// different request from the one being submitted. It can fire, and a test fires it.
    RequestSha256,
}

impl SubmitError {
    /// The stable machine name.
    pub fn as_str(&self) -> &'static str {
        match self {
            SubmitError::CrossBinding(CrossBinding::TaskId) => "cross_binding_task_id",
            SubmitError::CrossBinding(CrossBinding::RunId) => "cross_binding_run_id",
            SubmitError::CrossBinding(CrossBinding::GenerationConfigSha256) => {
                "cross_binding_generation_config_sha256"
            }
            SubmitError::CrossBinding(CrossBinding::RequestSha256) => "cross_binding_request_sha256",
            SubmitError::ChallengeDocument(_) => "challenge_document_unusable",
            SubmitError::IdInvalid(_) => "id_invalid",
            SubmitError::PreparedSelfCheck => "prepared_self_check",
            SubmitError::Transport(_) => "transport_failure",
            SubmitError::Frame(FrameError::MalformedFrame) => "malformed_result_frame",
            SubmitError::Frame(FrameError::Refused(_)) => "governed_verdict_refused",
        }
    }

    /// The closed renderer-facing reason.
    ///
    /// Every arm is `UpstreamBlocked`, and that is not laziness: `TurnReason` is the RENDERER's closed
    /// enum, and none of its six members can express "the broker's own cross-binding failed" or "the
    /// supervisor refused with `lease_expired`". The distinction that matters lives in the durable
    /// Block reason — which §4.10(h)'s (**NOT IMPLEMENTED**) `bridge.governed-turn-diagnostic.v1` carrier would supply and
    /// which this tree does NOT build. `governed_bridge_result::FrameError::to_turn_reason` makes the
    /// same collapse for the same reason.
    pub fn to_turn_reason(&self) -> TurnReason {
        TurnReason::UpstreamBlocked
    }
}

impl std::fmt::Display for SubmitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SubmitError::ChallengeDocument(d) | SubmitError::IdInvalid(d) => {
                write!(f, "{}:{}", self.as_str(), d)
            }
            SubmitError::Transport(d) => write!(f, "{}:{}", self.as_str(), d),
            SubmitError::Frame(FrameError::Refused(r)) => {
                write!(f, "{}:{}", self.as_str(), r.as_str())
            }
            _ => f.write_str(self.as_str()),
        }
    }
}

// =================================================================================================
// The signed challenge document
// =================================================================================================

/// The §4.1 `brops.governed-turn-challenge.v1` document, as the authority returned it to the broker.
///
/// **It holds the EXACT bytes.** The parsed payload is kept beside them, never instead of them:
/// `doc_b64()` encodes `bytes()`, so the value the §4.10(a0) canonicality gate hashes is the value
/// the authority signed. Re-serializing the parsed JSON would produce bytes THIS process chose, and
/// §4.10(a0)'s `noncanonical` exists precisely to refuse that.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChallengeDocument {
    bytes: Vec<u8>,
    task_id: String,
    run_id: String,
    generation_config_sha256: String,
    request_sha256: String,
    install_id: String,
    request_nonce: String,
}

fn payload_string(payload: &Value, field: &'static str) -> Result<String, SubmitError> {
    let value = payload
        .get(field)
        .and_then(Value::as_str)
        .ok_or(SubmitError::ChallengeDocument(field))?;
    if value.is_empty() || value.len() > MAX_ID_LEN {
        return Err(SubmitError::ChallengeDocument(field));
    }
    Ok(value.to_string())
}

fn payload_hex64(payload: &Value, field: &'static str) -> Result<String, SubmitError> {
    let value = payload
        .get(field)
        .and_then(Value::as_str)
        .ok_or(SubmitError::ChallengeDocument(field))?;
    // Lowercase only. Two spellings of one digest, in a field an equality check is run against, is
    // the ambiguity §4.10(a0)'s canonicality gate exists for.
    if value.len() != 64 || !value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(SubmitError::ChallengeDocument(field));
    }
    Ok(value.to_string())
}

impl ChallengeDocument {
    /// Read the exact signed `{payload, sig}` bytes the authority returned.
    ///
    /// This is EXTRACTION, not verification — the same judgement the consumer records for its own
    /// decode. It is not a signature check (the broker cannot verify a challenge-authority signature
    /// and §4.10(a0) is where that happens), not a canonicality gate, and not a full §4.1 shape
    /// check. It refuses exactly what would make the frame unbuildable or a cross-binding
    /// uncheckable: the §4.10(a0) size cap, a non-object document, an absent `payload`, and the six
    /// payload fields this hop actually reads.
    pub fn from_bytes(bytes: &[u8]) -> Result<ChallengeDocument, SubmitError> {
        if bytes.is_empty() {
            return Err(SubmitError::ChallengeDocument("empty"));
        }
        if bytes.len() > MAX_CHALLENGE_DOC_BYTES {
            return Err(SubmitError::ChallengeDocument("oversize"));
        }
        let document: Value =
            serde_json::from_slice(bytes).map_err(|_| SubmitError::ChallengeDocument("not_json"))?;
        if !document.is_object() {
            return Err(SubmitError::ChallengeDocument("not_object"));
        }
        // `sig` is not read, only required: a document with no signature is not the thing §4.10(a0)
        // is going to verify, and carrying it would move the failure a hop later for no gain.
        if !document.get("sig").is_some_and(Value::is_string) {
            return Err(SubmitError::ChallengeDocument("sig"));
        }
        let payload = document.get("payload").ok_or(SubmitError::ChallengeDocument("payload"))?;
        if !payload.is_object() {
            return Err(SubmitError::ChallengeDocument("payload"));
        }
        Ok(ChallengeDocument {
            bytes: bytes.to_vec(),
            task_id: payload_string(payload, "task_id")?,
            run_id: payload_string(payload, "run_id")?,
            generation_config_sha256: payload_hex64(payload, "generation_config_sha256")?,
            request_sha256: payload_hex64(payload, "request_sha256")?,
            install_id: payload_string(payload, "install_id")?,
            request_nonce: payload_string(payload, "request_nonce")?,
        })
    }

    /// The exact bytes, unchanged.
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    /// `challenge_doc_b64` — base64url no-pad of [`bytes`](ChallengeDocument::bytes), which is what
    /// the frame carries and what §4.10(a0) decodes and re-hashes.
    pub fn doc_b64(&self) -> String {
        use base64::engine::general_purpose::URL_SAFE_NO_PAD;
        use base64::Engine as _;
        URL_SAFE_NO_PAD.encode(&self.bytes)
    }

    /// §4.1 `payload.task_id`.
    pub fn task_id(&self) -> &str {
        &self.task_id
    }
    /// §4.1 `payload.run_id`.
    pub fn run_id(&self) -> &str {
        &self.run_id
    }
    /// §4.1 `payload.generation_config_sha256` — the digest the authority COMMITTED.
    pub fn generation_config_sha256(&self) -> &str {
        &self.generation_config_sha256
    }
    /// §4.1 `payload.request_sha256`.
    pub fn request_sha256(&self) -> &str {
        &self.request_sha256
    }
    /// §4.1 `payload.install_id` — one of the two values the consumer lifts off the document to
    /// build the §4.10(a0) open frame, which the submit frame does not carry.
    pub fn install_id(&self) -> &str {
        &self.install_id
    }
    /// §4.1 `payload.request_nonce` — the other one.
    pub fn request_nonce(&self) -> &str {
        &self.request_nonce
    }
}

// =================================================================================================
// The backend-owned orchestration object
// =================================================================================================

/// §4.10(g)'s backend-owned orchestration object: the routing identities the flow needs, which never
/// cross the Tauri/webview boundary.
///
/// It exists separately from [`PreparedGovernedTurnV1B`] because `task_id` and `run_id` are NOT part
/// of the request binding (§4.10(g) P0-1(A): they are bound into the §4.1 signed challenge and
/// verified open-time, but never into `request_sha256`/`IssuedRequest`/`Expected`) — so the prepared
/// object must not carry them, and the submit helper must take the whole execution rather than the
/// prepared object alone.
///
/// Fields are private for the same reason the prepared object's are: there is one constructor, and
/// it validates.
#[derive(Debug, Clone)]
pub struct GovernedTurnExecutionV1B {
    conversation_id: String,
    run_id: String,
    task_id: String,
    prepared: PreparedGovernedTurnV1B,
}

impl GovernedTurnExecutionV1B {
    /// Build the orchestration object. `conversation_id` is the renderer's active conversation (the
    /// one closed value it supplies); `run_id` and `task_id` are BACKEND-GENERATED — the renderer
    /// cannot inject either.
    pub fn new(
        conversation_id: &str,
        run_id: &str,
        task_id: &str,
        prepared: PreparedGovernedTurnV1B,
    ) -> Result<GovernedTurnExecutionV1B, SubmitError> {
        for (field, value) in
            [("conversation_id", conversation_id), ("run_id", run_id), ("task_id", task_id)]
        {
            if value.is_empty() || value.len() > MAX_ID_LEN {
                return Err(SubmitError::IdInvalid(field));
            }
        }
        Ok(GovernedTurnExecutionV1B {
            conversation_id: conversation_id.to_string(),
            run_id: run_id.to_string(),
            task_id: task_id.to_string(),
            prepared,
        })
    }

    /// The conversation the reply is written into on accept — recovered from the consumed challenge
    /// row, never re-supplied by the renderer.
    pub fn conversation_id(&self) -> &str {
        &self.conversation_id
    }
    /// The backend-generated `run_id` bound into the §4.1 challenge.
    pub fn run_id(&self) -> &str {
        &self.run_id
    }
    /// The backend-generated `task_id` bound into the §4.1 challenge AND carried on the submit frame.
    pub fn task_id(&self) -> &str {
        &self.task_id
    }
    /// The single immutable preparation this turn's bytes and hashes all come from.
    pub fn prepared(&self) -> &PreparedGovernedTurnV1B {
        &self.prepared
    }
}

// =================================================================================================
// The frame
// =================================================================================================

/// Build the `bridge.governed-turn-submit.v1` frame, asserting every §4.10(g) cross-binding first.
///
/// **The asserts come before the frame, not after it.** §4.10(g): "Before it writes the frame it
/// asserts the exact cross-bindings (P0-1 LOCKED) — else terminal Block." A frame built and then
/// checked would exist, and a value that exists can be sent by the next edit.
///
/// The three §4.10(g) bindings, plus the `request_sha256` binding documented on
/// [`CrossBinding::RequestSha256`]:
///
/// 1. `submit.task_id == execution.task_id == challenge.payload.task_id` — the frame's `task_id` IS
///    `execution.task_id` by construction (there is no other source in scope), so the check that can
///    fire is the comparison against the signed challenge.
/// 2. `challenge.payload.run_id == execution.run_id`.
/// 3. `SHA256(JCS(prepared.generation_config)) == challenge.payload.generation_config_sha256` —
///    recomputed from the OBJECT here rather than read off `prepared.context`, so this compares the
///    formula's output against the authority's commitment rather than comparing one stored copy of a
///    digest against another. A mutation pass proved that distinction is not cosmetic: the re-read
///    form survived every test until
///    `the_config_binding_recomputes_from_the_object_rather_than_re_reading_a_stored_digest` existed.
///
/// **One honest note from that pass, in the same place the Python half records its own.** Replacing
/// the frame's `"task_id": execution.task_id()` with `challenge_document.task_id()` is an EQUIVALENT
/// mutant and SURVIVES — binding (1) has already asserted the two are the same string by the time the
/// frame is built, so both expressions produce identical bytes for every input that reaches here. The
/// orchestration object is used anyway, and not as a check: §4.10(g) says the frame's `task_id` IS
/// `execution.task_id`, so taking it from a wire value would make the frame's provenance depend on
/// the assert above continuing to exist — which is exactly what a future edit would break first.
pub fn submit_frame(
    execution: &GovernedTurnExecutionV1B,
    challenge_document: &ChallengeDocument,
) -> Result<Value, SubmitError> {
    let prepared = execution.prepared();

    // §4.10(g) encapsulation enforcement, first: an object whose committed digest does not match its
    // own canonical bytes has no business producing a frame.
    if !prepared.self_check() {
        return Err(SubmitError::PreparedSelfCheck);
    }
    if execution.task_id() != challenge_document.task_id() {
        return Err(SubmitError::CrossBinding(CrossBinding::TaskId));
    }
    if execution.run_id() != challenge_document.run_id() {
        return Err(SubmitError::CrossBinding(CrossBinding::RunId));
    }
    if prepared.generation_config().sha256() != challenge_document.generation_config_sha256() {
        return Err(SubmitError::CrossBinding(CrossBinding::GenerationConfigSha256));
    }
    if prepared.request_sha256() != challenge_document.request_sha256() {
        return Err(SubmitError::CrossBinding(CrossBinding::RequestSha256));
    }

    let history: Vec<Value> = prepared
        .history()
        .iter()
        .map(|m| json!({ "role": m.role, "content": m.content }))
        .collect();
    Ok(json!({
        "protocol": BRIDGE_SUBMIT_PROTOCOL,
        "task_id": execution.task_id(),
        "challenge_doc_b64": challenge_document.doc_b64(),
        // The EXACT retained bytes — the same `system` string whose SHA-256 is in the context and in
        // the signed challenge. Nothing is re-derived, re-trimmed or re-normalized between the
        // preparation and here; there is no post-prepare input path at all (§4.10(g) LOCKED).
        "system": prepared.system(),
        "history": history,
        // The validated OBJECT, five strings, never a JSON number.
        "generation_config": prepared.generation_config().to_json(),
    }))
}

// =================================================================================================
// The transport seam
// =================================================================================================

/// One `bridge.governed-turn-submit.v1` round trip: write the frame to a fresh one-shot sidecar's
/// `stdin`, read its single `stdout` reply.
///
/// **The production implementation is [`crate::governed_sidecar::GovernedSidecar`]** — the ONE place
/// in the tree that starts the bridge, shared with the desktop app's governed turn, its governance
/// mirror and its §4.10(f) output pull. It is a trait rather than a direct call because the tests in
/// this module drive the writer against fakes, and because the broker's other hops are injected the
/// same way; it is NOT a trait because the implementation is missing.
///
/// Any OTHER implementation MUST map every local failure — spawn, socket, deadline, unexpected exit,
/// oversized or non-JSON output — to `Err`, never to a document. §6.1 makes a local
/// ingress/transport failure out-of-band, and the sidecar originates no supervisor or signature
/// verdict; a synthesized reply here would be this process inventing the one thing §2.4 forbids it to
/// invent.
pub trait SubmitTransport {
    /// Send `frame`, return the sidecar's single parsed reply document.
    fn call(&self, frame: &Value) -> Result<Value, String>;
}

/// Drive ONE governed turn's submit hop and return the strict-decoded §4.6 metadata-only result.
///
/// **An INTERNAL Rust helper — NOT a `#[tauri::command]` and NOT in `generate_handler!`** (§4.10(g)).
/// It takes the WHOLE orchestration object, because `PreparedGovernedTurnV1B` alone does not carry
/// `task_id`/`run_id` (P0-1(A)).
///
/// What comes back is metadata only: the §4.6 frame carries `output_bytes`/`output_sha256` and a
/// transport `output_stream_id`, and **no inline output**. This function pulls nothing — §4.10(g)
/// step 5 gives the §4.10(f) output pull to `governed_turn_execute`'s own internal loop, through
/// FRESH one-shot sidecars, after this subprocess has already exited.
///
/// A well-formed governed REFUSAL comes back as `Err(SubmitError::Frame(FrameError::Refused(_)))`
/// carrying the closed §4.5 reason verbatim, so a caller cannot reach the success path by forgetting
/// to match an arm.
pub fn governed_turn_submit_prepared(
    execution: &GovernedTurnExecutionV1B,
    challenge_document: &ChallengeDocument,
    transport: &dyn SubmitTransport,
) -> Result<SignedTurnResult, SubmitError> {
    let frame = submit_frame(execution, challenge_document)?;
    let reply = transport.call(&frame).map_err(SubmitError::Transport)?;
    // `parse_frame` rather than `parse`: the refused arm carries the forensic `receipt_id` and a
    // caller that needs it should not have to decode the document twice.
    match BridgeTurnResult::parse_frame(&reply).map_err(SubmitError::Frame)? {
        BridgeTurnResult::Signed(signed) => Ok(signed),
        BridgeTurnResult::Refused { reason, .. } => {
            Err(SubmitError::Frame(FrameError::Refused(reason)))
        }
    }
}

/// `SHA256` of the exact frame bytes as they go on the wire — for a caller that logs what it sent.
///
/// Deliberately NOT used as a check anywhere: there is no counterpart to compare it against, and a
/// digest with nothing on the other side is the "reads as protection while protecting nothing" class.
pub fn submit_frame_sha256(frame: &Value) -> String {
    sha256_hex(&serde_json::to_vec(frame).unwrap_or_default())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::governed_prepare::{
        prepare_governed_turn_v1b, resolve_governed_generation_config_from, GovernedChatMsg,
        GovernedGenerationConfig, PreparedGovernedTurnV1B, MAX_SYSTEM_BYTES,
    };

    fn prepared() -> PreparedGovernedTurnV1B {
        let config = resolve_governed_generation_config_from(|_| None).unwrap();
        prepare_governed_turn_v1b(
            "You are Bro.",
            &[GovernedChatMsg::new("user", "hi")],
            config,
            1_700_000_000_000,
            "ws-1",
            "install-1",
        )
        .unwrap()
    }

    /// A §4.1 document that AGREES with `p` on every cross-binding — the legitimate case.
    fn agreeing_doc(p: &PreparedGovernedTurnV1B, run_id: &str, task_id: &str) -> ChallengeDocument {
        let document = json!({
            "payload": {
                "protocol": "brops.governed-turn-challenge.v1",
                "challenge_key_id": "challenge-key-1",
                "run_id": run_id,
                "task_id": task_id,
                "workspace_id": p.context().workspace_id,
                "install_id": p.context().install_id,
                "supervisor_id": "sup-1",
                "request_nonce": p.context().request_nonce,
                "system_sha256": p.context().system_sha256,
                "history_sha256": p.context().history_sha256,
                "generation_config_sha256": p.context().generation_config_sha256,
                "request_sha256": p.request_sha256(),
                "requested_at_ms": 1_700_000_000_000i64,
                "challenge_issued_at_ms": 1_700_000_000_001i64,
                "challenge_expires_at_ms": 1_700_000_030_001i64,
            },
            "sig": "c2ln",
        });
        ChallengeDocument::from_bytes(&serde_json::to_vec(&document).unwrap()).unwrap()
    }

    fn execution(p: PreparedGovernedTurnV1B) -> GovernedTurnExecutionV1B {
        GovernedTurnExecutionV1B::new("conv-1", "run-1", "t-1", p).unwrap()
    }

    // ---------------------------------------------------------------------------------------------
    // The frame
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn the_frame_carries_exactly_the_six_designed_fields() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let frame = submit_frame(&execution(p), &doc).unwrap();
        let object = frame.as_object().unwrap();
        let mut keys: Vec<&str> = object.keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(keys, SUBMIT_REQUEST_FIELDS);
        assert_eq!(object["protocol"], BRIDGE_SUBMIT_PROTOCOL);
        // The discriminator is absent from the frozen family in BOTH directions: `bridge.result` and
        // `bridge.task-request` have no `protocol` key at all and are `additionalProperties:false`.
        assert_ne!(BRIDGE_SUBMIT_PROTOCOL, "bridge.result");
    }

    #[test]
    fn the_frame_carries_the_exact_prepared_bytes_and_the_verbatim_document() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let system = p.system().to_string();
        let history_role = p.history()[0].role.clone();
        let history_content = p.history()[0].content.clone();
        let exec = execution(p);
        let frame = submit_frame(&exec, &doc).unwrap();

        assert_eq!(frame["system"], system);
        assert_eq!(frame["history"][0]["role"], history_role);
        assert_eq!(frame["history"][0]["content"], history_content);
        assert_eq!(frame["task_id"], "t-1");

        // The document travels VERBATIM: decoding `challenge_doc_b64` yields the exact bytes the
        // authority signed, not a re-serialization of the parsed value.
        use base64::engine::general_purpose::URL_SAFE_NO_PAD;
        use base64::Engine as _;
        let round_tripped = URL_SAFE_NO_PAD.decode(frame["challenge_doc_b64"].as_str().unwrap());
        assert_eq!(round_tripped.unwrap(), doc.bytes());
    }

    /// The document is carried VERBATIM, and this proves it with bytes a re-serializer would change.
    ///
    /// The earlier version of this test used a `json!` fixture, whose `serde_json::Map` is a
    /// `BTreeMap` — so re-encoding the parsed value produced the SAME bytes and a "re-serialize the
    /// document" mutation SURVIVED. The document here is written by hand with its keys out of
    /// lexicographic order and a space after a colon, exactly as an authority that is not obliged to
    /// emit canonical JSON might: any round trip through a parser normalizes both, and the assertion
    /// then fails. §4.10(a0)'s canonicality gate hashes what ARRIVES, so bytes this process chose
    /// would be the divergence that gate exists to refuse — `noncanonical` has to stay the
    /// supervisor's verdict to produce.
    #[test]
    fn the_document_is_carried_byte_for_byte_even_when_it_is_not_canonically_ordered() {
        use base64::engine::general_purpose::URL_SAFE_NO_PAD;
        use base64::Engine as _;
        let p = prepared();
        let raw = format!(
            "{{\"sig\": \"c2ln\",\"payload\":{{\"task_id\":\"t-1\",\"run_id\":\"run-1\",\
             \"install_id\":\"{install}\",\"request_nonce\":\"{nonce}\",\
             \"generation_config_sha256\":\"{cfg}\",\"request_sha256\":\"{req}\"}}}}",
            install = p.context().install_id,
            nonce = p.context().request_nonce,
            cfg = p.context().generation_config_sha256,
            req = p.request_sha256(),
        );
        // The fixture is genuinely non-canonical in BOTH ways, or it would prove nothing.
        assert!(raw.starts_with("{\"sig\""), "keys must be out of lexicographic order");
        assert!(raw.contains("\"sig\": "), "there must be whitespace a parser would drop");
        let doc = ChallengeDocument::from_bytes(raw.as_bytes()).unwrap();
        assert_eq!(doc.bytes(), raw.as_bytes());
        let frame = submit_frame(&execution(p), &doc).unwrap();
        let carried = URL_SAFE_NO_PAD.decode(frame["challenge_doc_b64"].as_str().unwrap()).unwrap();
        assert_eq!(carried, raw.as_bytes(), "the frame must carry the authority's exact bytes");
    }

    #[test]
    fn the_generation_config_rides_as_five_strings_and_hashes_to_the_committed_digest() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let committed = doc.generation_config_sha256().to_string();
        let config_jcs = p.generation_config_jcs().to_vec();
        let frame = submit_frame(&execution(p), &doc).unwrap();
        let config = &frame["generation_config"];
        for (key, value) in config.as_object().unwrap() {
            assert!(value.is_string(), "{key} must be a STRING on the wire");
        }
        // What the sidecar will canonicalize out of the frame is byte-identical to what was hashed,
        // and that is the digest the challenge committed. If these three ever disagree the turn dies
        // at `handle_not_challenge` with nothing to point at.
        assert_eq!(serde_json::to_vec(config).unwrap(), config_jcs);
        assert_eq!(crate::receipt::sha256_hex(&config_jcs), committed);
        assert_eq!(
            committed,
            "732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22"
        );
    }

    // ---------------------------------------------------------------------------------------------
    // The cross-bindings — each produced BY NAME
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn a_task_id_the_challenge_did_not_sign_is_a_terminal_cross_binding_block() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-OTHER");
        assert_eq!(
            submit_frame(&execution(p), &doc).unwrap_err(),
            SubmitError::CrossBinding(CrossBinding::TaskId)
        );
    }

    #[test]
    fn a_run_id_the_challenge_did_not_sign_is_a_terminal_cross_binding_block() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-OTHER", "t-1");
        assert_eq!(
            submit_frame(&execution(p), &doc).unwrap_err(),
            SubmitError::CrossBinding(CrossBinding::RunId)
        );
    }

    #[test]
    fn a_config_digest_the_challenge_did_not_commit_is_a_terminal_cross_binding_block() {
        // The realistic shape of this failure: the authority committed the FROZEN raw-string digest
        // while the broker prepared the governed OBJECT digest. That is exactly the split authority
        // §4.10(g) says makes every legitimate turn Block, and this is the gate that names it.
        let p = prepared();
        let frozen = crate::receipt::sha256_hex(br#"{"model":"claude","temperature":0}"#);
        let document = json!({
            "payload": {
                "run_id": "run-1", "task_id": "t-1",
                "install_id": p.context().install_id,
                "request_nonce": p.context().request_nonce,
                "generation_config_sha256": frozen,
                "request_sha256": p.request_sha256(),
            },
            "sig": "c2ln",
        });
        let doc = ChallengeDocument::from_bytes(&serde_json::to_vec(&document).unwrap()).unwrap();
        assert_eq!(
            submit_frame(&execution(p), &doc).unwrap_err(),
            SubmitError::CrossBinding(CrossBinding::GenerationConfigSha256)
        );
    }

    #[test]
    fn a_request_binding_the_challenge_did_not_sign_is_a_terminal_cross_binding_block() {
        let p = prepared();
        let document = json!({
            "payload": {
                "run_id": "run-1", "task_id": "t-1",
                "install_id": p.context().install_id,
                "request_nonce": p.context().request_nonce,
                "generation_config_sha256": p.context().generation_config_sha256,
                // A legitimate-looking digest over a DIFFERENT request envelope.
                "request_sha256": "f".repeat(64),
            },
            "sig": "c2ln",
        });
        let doc = ChallengeDocument::from_bytes(&serde_json::to_vec(&document).unwrap()).unwrap();
        assert_eq!(
            submit_frame(&execution(p), &doc).unwrap_err(),
            SubmitError::CrossBinding(CrossBinding::RequestSha256)
        );
    }

    #[test]
    fn a_desynchronized_prepared_object_cannot_reach_the_frame() {
        // §4.10(g)'s encapsulation precondition, made REACHABLE BY NAME. Within the public API this
        // cannot fail — one constructor, private fields, no setter — and a mutation pass proved the
        // consequence: deleting the guard survived every test. `desynced_for_test` is the
        // `#[cfg(test)]` seam that produces the state the guard exists for, so the guard is now a
        // check somebody can watch fail rather than a line that reads like one.
        let base = prepared();
        let doc = agreeing_doc(&base, "run-1", "t-1");
        let broken = PreparedGovernedTurnV1B::desynced_for_test(
            base,
            b"{}".to_vec(),
            // A committed digest that is NOT the digest of the JCS beside it.
            Some("0".repeat(64)),
        );
        let exec = GovernedTurnExecutionV1B::new("conv-1", "run-1", "t-1", broken).unwrap();
        assert_eq!(submit_frame(&exec, &doc).unwrap_err(), SubmitError::PreparedSelfCheck);
    }

    #[test]
    fn the_config_binding_recomputes_from_the_object_rather_than_re_reading_a_stored_digest() {
        // The distinction this pins is the whole point of the binding. What rides the frame is the
        // OBJECT; what the challenge committed is a digest. Comparing the challenge against
        // `context.generation_config_sha256` — a value copied at preparation time — would compare
        // two stored numbers and never look at the bytes actually being sent, which is the split
        // authority §4.10(g) exists to close. A mutation pass caught it: swapping the recompute for
        // that re-read SURVIVED until this test existed.
        //
        // The fixture is a prepared turn whose stored JCS and stored digest AGREE with each other
        // (so `self_check` passes) but describe a DIFFERENT object from the one it carries.
        let base = prepared();
        let other = GovernedGenerationConfig::validate(
            &[("engine_id", crate::governed_prepare::GOVERNED_ENGINE_ID),
              ("max_output_tokens", "8192"),
              ("model", "claude-sonnet-5"),
              ("temperature", "0.00"),
              ("top_p", "1.00")]
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
        )
        .unwrap();
        let doc_digest = other.sha256();
        // Self-consistent: jcs and digest are each other's. Only the OBJECT disagrees.
        let skewed = PreparedGovernedTurnV1B::desynced_for_test(base, other.jcs(), None);
        assert!(skewed.self_check(), "the fixture must pass the encapsulation check");
        assert_ne!(skewed.generation_config().sha256(), doc_digest);

        let document = json!({
            "payload": {
                "run_id": "run-1", "task_id": "t-1",
                "install_id": skewed.context().install_id,
                "request_nonce": skewed.context().request_nonce,
                // The authority committed the digest of the OTHER object — the one the stored copy
                // agrees with and the carried object does not.
                "generation_config_sha256": doc_digest,
                "request_sha256": skewed.request_sha256(),
            },
            "sig": "c2ln",
        });
        let doc = ChallengeDocument::from_bytes(&serde_json::to_vec(&document).unwrap()).unwrap();
        let exec = GovernedTurnExecutionV1B::new("conv-1", "run-1", "t-1", skewed).unwrap();
        assert_eq!(
            submit_frame(&exec, &doc).unwrap_err(),
            SubmitError::CrossBinding(CrossBinding::GenerationConfigSha256)
        );
    }

    #[test]
    fn an_empty_payload_id_is_refused_by_field_name() {
        // Absence and emptiness are different inputs and both have to be refused: a challenge whose
        // `run_id` is `""` would sail through a presence-only check and then fail the cross-binding
        // for a reason that names the wrong thing.
        for field in ["run_id", "task_id", "install_id", "request_nonce"] {
            let mut payload = json!({
                "run_id": "r", "task_id": "t", "install_id": "i", "request_nonce": "n",
                "generation_config_sha256": "a".repeat(64), "request_sha256": "b".repeat(64),
            });
            payload[field] = json!("");
            let doc = json!({ "payload": payload, "sig": "c2ln" });
            assert_eq!(
                ChallengeDocument::from_bytes(&serde_json::to_vec(&doc).unwrap()).unwrap_err(),
                SubmitError::ChallengeDocument(field)
            );
        }
    }

    #[test]
    fn history_content_rides_the_frame_byte_for_byte_with_no_normalization() {
        // The same rule as `system`, one field along, and the same failure mode if it is broken: the
        // digest was taken over the untrimmed content, so a frame carrying a trimmed copy would be
        // refused `digest_mismatch` at §2.4 staging — a tampering verdict for a turn nobody
        // tampered with. A mutation pass caught this one: `.trim()` on the way out survived.
        let padded = "  keep   my   spaces  \r\n";
        let config = resolve_governed_generation_config_from(|_| None).unwrap();
        let p = prepare_governed_turn_v1b(
            "sys",
            &[GovernedChatMsg::new("user", padded)],
            config,
            1,
            "ws-1",
            "install-1",
        )
        .unwrap();
        let committed = p.context().history_sha256.clone();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let frame = submit_frame(&execution(p), &doc).unwrap();
        assert_eq!(frame["history"][0]["content"], padded);
        // And the bytes on the frame re-canonicalize to the digest the challenge committed, which is
        // the equality the whole hop turns on.
        let sent = [GovernedChatMsg::new(
            frame["history"][0]["role"].as_str().unwrap(),
            frame["history"][0]["content"].as_str().unwrap(),
        )];
        assert_eq!(
            crate::receipt::sha256_hex(&crate::governed_prepare::history_jcs(&sent)),
            committed
        );
    }

    #[test]
    fn every_submit_error_has_a_distinct_stable_machine_name() {
        use crate::governed_bridge_result::GovernedRefusal;
        let all = [
            SubmitError::CrossBinding(CrossBinding::TaskId),
            SubmitError::CrossBinding(CrossBinding::RunId),
            SubmitError::CrossBinding(CrossBinding::GenerationConfigSha256),
            SubmitError::CrossBinding(CrossBinding::RequestSha256),
            SubmitError::ChallengeDocument("oversize"),
            SubmitError::IdInvalid("run_id"),
            SubmitError::PreparedSelfCheck,
            SubmitError::Transport("spawn".into()),
            SubmitError::Frame(FrameError::MalformedFrame),
            SubmitError::Frame(FrameError::Refused(GovernedRefusal::parse("lease_expired").unwrap())),
        ];
        let mut names: Vec<&str> = all.iter().map(SubmitError::as_str).collect();
        names.sort_unstable();
        names.dedup();
        assert_eq!(names.len(), all.len(), "two refusals share a machine name");
        // Every one Blocks, and every one says WHICH block it is in its own string.
        for e in &all {
            assert_eq!(e.to_turn_reason(), TurnReason::UpstreamBlocked);
        }
        assert_eq!(
            SubmitError::Frame(FrameError::Refused(
                GovernedRefusal::parse("lease_expired").unwrap()
            ))
            .to_string(),
            "governed_verdict_refused:lease_expired"
        );
    }

    // ---------------------------------------------------------------------------------------------
    // The challenge document
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn the_challenge_document_cap_is_the_4096_from_section_4_10_a0() {
        // A document at the cap is accepted; one byte over is refused HERE, so an unbuildable
        // 8192-byte open frame is never attempted. `doc_oversize` stays reachable in the engine suite
        // from a sender that does not apply this cap — which is the hostile sidecar §4.10(a0) is
        // written against.
        let p = prepared();
        let build = |pad: usize| {
            let document = json!({
                "payload": {
                    "run_id": "run-1", "task_id": "t-1",
                    "install_id": p.context().install_id,
                    "request_nonce": p.context().request_nonce,
                    "generation_config_sha256": p.context().generation_config_sha256,
                    "request_sha256": p.request_sha256(),
                    "pad": "x".repeat(pad),
                },
                "sig": "c2ln",
            });
            serde_json::to_vec(&document).unwrap()
        };
        // Find the pad that lands exactly on the cap, then step one past it.
        let base = build(0).len();
        let at_cap = build(MAX_CHALLENGE_DOC_BYTES - base);
        assert_eq!(at_cap.len(), MAX_CHALLENGE_DOC_BYTES);
        assert!(ChallengeDocument::from_bytes(&at_cap).is_ok());
        let over = build(MAX_CHALLENGE_DOC_BYTES - base + 1);
        assert_eq!(over.len(), MAX_CHALLENGE_DOC_BYTES + 1);
        assert_eq!(
            ChallengeDocument::from_bytes(&over).unwrap_err(),
            SubmitError::ChallengeDocument("oversize")
        );
    }

    #[test]
    fn a_document_missing_what_the_cross_bindings_read_is_refused_by_field_name() {
        let full = json!({
            "payload": {
                "run_id": "run-1", "task_id": "t-1", "install_id": "i", "request_nonce": "n",
                "generation_config_sha256": "a".repeat(64), "request_sha256": "b".repeat(64),
            },
            "sig": "c2ln",
        });
        assert!(ChallengeDocument::from_bytes(&serde_json::to_vec(&full).unwrap()).is_ok());
        for field in
            ["run_id", "task_id", "install_id", "request_nonce", "generation_config_sha256", "request_sha256"]
        {
            let mut doc = full.clone();
            doc["payload"].as_object_mut().unwrap().remove(field);
            assert_eq!(
                ChallengeDocument::from_bytes(&serde_json::to_vec(&doc).unwrap()).unwrap_err(),
                SubmitError::ChallengeDocument(field)
            );
        }
        // A missing `sig` and a missing `payload` are each their own refusal.
        let mut no_sig = full.clone();
        no_sig.as_object_mut().unwrap().remove("sig");
        assert_eq!(
            ChallengeDocument::from_bytes(&serde_json::to_vec(&no_sig).unwrap()).unwrap_err(),
            SubmitError::ChallengeDocument("sig")
        );
        let mut no_payload = full.clone();
        no_payload.as_object_mut().unwrap().remove("payload");
        assert_eq!(
            ChallengeDocument::from_bytes(&serde_json::to_vec(&no_payload).unwrap()).unwrap_err(),
            SubmitError::ChallengeDocument("payload")
        );
        assert_eq!(
            ChallengeDocument::from_bytes(b"not json").unwrap_err(),
            SubmitError::ChallengeDocument("not_json")
        );
        assert_eq!(
            ChallengeDocument::from_bytes(b"[]").unwrap_err(),
            SubmitError::ChallengeDocument("not_object")
        );
        assert_eq!(
            ChallengeDocument::from_bytes(b"").unwrap_err(),
            SubmitError::ChallengeDocument("empty")
        );
    }

    #[test]
    fn an_uppercase_digest_is_refused_rather_than_folded() {
        let doc = json!({
            "payload": {
                "run_id": "r", "task_id": "t", "install_id": "i", "request_nonce": "n",
                "generation_config_sha256": "A".repeat(64), "request_sha256": "b".repeat(64),
            },
            "sig": "c2ln",
        });
        assert_eq!(
            ChallengeDocument::from_bytes(&serde_json::to_vec(&doc).unwrap()).unwrap_err(),
            SubmitError::ChallengeDocument("generation_config_sha256")
        );
    }

    #[test]
    fn an_unbounded_orchestration_id_is_refused_by_name() {
        let long = "x".repeat(MAX_ID_LEN + 1);
        for field in ["conversation_id", "run_id", "task_id"] {
            let (c, r, t) = match field {
                "conversation_id" => (long.as_str(), "run-1", "t-1"),
                "run_id" => ("conv-1", long.as_str(), "t-1"),
                _ => ("conv-1", "run-1", long.as_str()),
            };
            assert_eq!(
                GovernedTurnExecutionV1B::new(c, r, t, prepared()).unwrap_err(),
                SubmitError::IdInvalid(field)
            );
        }
        assert_eq!(
            GovernedTurnExecutionV1B::new("", "run-1", "t-1", prepared()).unwrap_err(),
            SubmitError::IdInvalid("conversation_id")
        );
    }

    // ---------------------------------------------------------------------------------------------
    // The round trip, over the injected transport
    // ---------------------------------------------------------------------------------------------

    struct Canned(Value);
    impl SubmitTransport for Canned {
        fn call(&self, _frame: &Value) -> Result<Value, String> {
            Ok(self.0.clone())
        }
    }
    struct Failing;
    impl SubmitTransport for Failing {
        fn call(&self, _frame: &Value) -> Result<Value, String> {
            Err("spawn failed: No such file or directory".into())
        }
    }
    /// Records what actually went on the wire, so the ordering/omission claims below are tested
    /// against the bytes rather than against a reading of the code.
    struct Recording(std::cell::RefCell<Vec<Value>>, Value);
    impl SubmitTransport for Recording {
        fn call(&self, frame: &Value) -> Result<Value, String> {
            self.0.borrow_mut().push(frame.clone());
            Ok(self.1.clone())
        }
    }

    fn b64(raw: usize) -> String {
        use base64::engine::general_purpose::URL_SAFE_NO_PAD;
        use base64::Engine as _;
        URL_SAFE_NO_PAD.encode(vec![b'x'; raw])
    }

    fn signed_reply() -> Value {
        json!({
            "protocol": "bridge.governed-turn-result.v1",
            "ok": true,
            // §4.6 puts the capability at the TOP level, not inside `receipt`, and its two
            // biconditionals are enforced: `output_stream_id`/`receipt` are non-null iff `ok`.
            "output_stream_id": b64(32),
            "error": null,
            "receipt": {
                "envelope_jcs_b64": b64(120),
                "signature_b64": b64(64),
                "attestation_evidence_jcs_b64": b64(200),
                "attestation_signature_b64": b64(64),
                "containment_evidence_b64": b64(40),
                "lease_id": "lease-1",
                "run_id": "run-1",
                "execution_attempt_id": "attempt-1",
                "supervisor_attestation_key_id": "sup-key-1",
                "output_sha256": "a".repeat(64),
                "output_bytes": 11,
            },
        })
    }

    #[test]
    fn a_signed_reply_yields_the_metadata_only_result_and_its_output_stream_token() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let result =
            governed_turn_submit_prepared(&execution(p), &doc, &Canned(signed_reply())).unwrap();
        assert_eq!(result.output_stream_id().len(), 43);
        assert!(!result.envelope_jcs().is_empty());
        // The §4.10(f) capability arrives ONLY here. Nothing in the reply is the output itself.
    }

    #[test]
    fn this_hop_writes_exactly_one_frame_and_it_is_the_submit_frame() {
        // §4.10(g): "This submit subprocess pulls NO output". The producer's half of that claim is
        // that it makes exactly ONE call and it is not an output-read.
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let recorder = Recording(std::cell::RefCell::new(Vec::new()), signed_reply());
        governed_turn_submit_prepared(&execution(p), &doc, &recorder).unwrap();
        let sent = recorder.0.borrow();
        assert_eq!(sent.len(), 1);
        assert_eq!(sent[0]["protocol"], BRIDGE_SUBMIT_PROTOCOL);
        assert_ne!(sent[0]["protocol"], "bridge.governed-turn-output-read.v1");
    }

    #[test]
    fn a_governed_refusal_is_relayed_verbatim_and_never_becomes_a_success() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let refused = json!({
            "protocol": "bridge.governed-turn-result.v1",
            "ok": false,
            // A refusal carrying a capability token would be a Block that still invited a read, and
            // one carrying a receipt would be a Block wearing a success. §4.6 forbids both.
            "output_stream_id": null,
            "error": { "reason": "lease_expired", "receipt_id": null },
            "receipt": null,
        });
        let err = governed_turn_submit_prepared(&execution(p), &doc, &Canned(refused)).unwrap_err();
        match err {
            SubmitError::Frame(FrameError::Refused(r)) => assert_eq!(r.as_str(), "lease_expired"),
            other => panic!("expected the closed §4.5 verdict, got {other:?}"),
        }
    }

    #[test]
    fn a_local_spawn_failure_is_a_transport_error_and_never_a_verdict() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let err = governed_turn_submit_prepared(&execution(p), &doc, &Failing).unwrap_err();
        assert_eq!(err.as_str(), "transport_failure");
        // NOT confusable with a governed verdict: it is a different member, and a reader can tell.
        assert!(!matches!(err, SubmitError::Frame(_)));
    }

    #[test]
    fn a_reply_that_is_not_a_section_4_6_frame_is_malformed_not_refused() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        // The frozen `bridge.result` document: no `protocol` key at all. The two families reject each
        // other on the discriminator alone.
        let frozen = json!({ "ok": true, "task_id": "t-1", "receipt": {} });
        let err = governed_turn_submit_prepared(&execution(p), &doc, &Canned(frozen)).unwrap_err();
        assert_eq!(err, SubmitError::Frame(FrameError::MalformedFrame));
    }

    #[test]
    fn a_cross_binding_failure_produces_no_frame_and_makes_no_call() {
        let p = prepared();
        let doc = agreeing_doc(&p, "run-OTHER", "t-1");
        let recorder = Recording(std::cell::RefCell::new(Vec::new()), signed_reply());
        let err = governed_turn_submit_prepared(&execution(p), &doc, &recorder).unwrap_err();
        assert_eq!(err, SubmitError::CrossBinding(CrossBinding::RunId));
        assert!(recorder.0.borrow().is_empty(), "the asserts run BEFORE the frame is written");
    }

    // ---------------------------------------------------------------------------------------------
    // The arithmetic
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn the_frame_overhead_is_measured_and_the_ceiling_is_stdin_only() {
        // Measured through `serde_json::to_vec` — the serializer the transport uses — never
        // estimated. The MINIMUM frame: empty system, empty history, the 137-byte default config,
        // a 1-char task_id and the smallest well-formed challenge document.
        let config = resolve_governed_generation_config_from(|_| None).unwrap();
        let p = prepare_governed_turn_v1b("", &[], config, 1, "ws-1", "install-1").unwrap();
        let doc = agreeing_doc(&p, "run-1", "t-1");
        let exec = GovernedTurnExecutionV1B::new("c", "run-1", "t-1", p).unwrap();
        let frame = submit_frame(&exec, &doc).unwrap();
        let minimum = serde_json::to_vec(&frame).unwrap().len();

        // The ceiling this writer can produce, by construction rather than by building 8.4 MiB in a
        // test: the two caller-sized artifacts at their §4.10(g) caps, with no JSON escaping (the
        // worst case for escaping is 6x on `system` and is a separate, larger number).
        let ceiling = minimum + MAX_SYSTEM_BYTES + MAX_CONVERSATION_BYTES_FOR_ARITHMETIC;

        // **The load-bearing statement, and it is about the CEILING, not the minimum.** A minimum
        // frame is small and fits everything; what decides the transport is the largest frame this
        // writer can legally emit:
        //  * `8651985` against the renderer↔broker framed IPC's `MAX_FRAME_PAYLOAD_BYTES = 8192` is
        //    **1056x** — so a submit frame could never ride the channel the renderer reaches the
        //    broker on, which is why §4.10(g) puts it on a sidecar's `stdin` instead;
        //  * and **116x** the §4.6 REPLY's own `MAX_BRIDGE_TURN_RESULT_BYTES = 74236`, which is the
        //    asymmetry that makes the reply metadata-only and the output a separate §4.10(f) pull.
        // **The gap this measurement exposes, reported rather than patched.** NEITHER side bounds
        // this frame: `ai::governed_sidecar_call` writes `stdin` with no cap, and
        // `engine_sidecar.run` does a bare `stdin.read()`. §4.10(g) caps the three ARTIFACTS and
        // never the frame. A cap invented in this module would be a bound the consumer does not
        // enforce — a refusal on one side of a wire the other side would have accepted — so the
        // number is measured and named here and the decision is left to an Architect.
        assert_eq!(minimum, 1233, "the minimum frame, measured through the real serializer");
        assert_eq!(ceiling, 8_651_985);
        assert!(minimum < crate::ipc_framing::MAX_FRAME_PAYLOAD_BYTES);
        assert_eq!(ceiling / crate::ipc_framing::MAX_FRAME_PAYLOAD_BYTES, 1056);
        assert_eq!(
            ceiling / crate::governed_bridge_result::MAX_BRIDGE_TURN_RESULT_BYTES,
            116
        );

        // The digest helper is over the wire bytes, so it moves when the frame does.
        assert_eq!(
            submit_frame_sha256(&frame),
            crate::receipt::sha256_hex(&serde_json::to_vec(&frame).unwrap())
        );
    }

    /// §4.10(g)'s `MAX_CONVERSATION_BYTES`, restated locally ONLY so the arithmetic above reads as
    /// one expression. `the_caps_that_can_fire_are_the_two_caller_sized_ones` in `governed_prepare`
    /// is what pins the value.
    const MAX_CONVERSATION_BYTES_FOR_ARITHMETIC: usize =
        crate::governed_prepare::MAX_CONVERSATION_BYTES;
}
