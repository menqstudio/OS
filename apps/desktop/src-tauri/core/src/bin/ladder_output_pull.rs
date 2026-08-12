//! Drive the rev-30 §4.10(f) chunked output PULL against a REAL supervisor, and record the evidence.
//!
//! # Why this is a binary in `brops-core` rather than a Python script beside the ladder
//!
//! The pull loop is Rust. [`brops_core::governed_output_pull::pull_output`] owns the chunk arithmetic,
//! the echo compare, the `eof` check and the §4.6/§7.1 length+digest gate against the SIGNED envelope —
//! and its API deliberately takes a [`ReceiptEnvelope`] rather than an expected length and digest, so
//! that no caller can aim that gate at §4.10(e)'s TRANSPORT-ONLY echo of the same two values. A Python
//! driver would therefore have had to re-implement the loop AND the gate, and a second implementation of
//! one contract is the defect this repository has now found seven separate times: the copy that runs in
//! production is never the copy the tests drive.
//!
//! So the driver is a thin `main` in the crate that already owns the loop. Everything it adds is
//! transport (spawn one one-shot sidecar per chunk, write one request, read one reply) and evidence
//! (what was asked, what came back, which digest was compared against which). Every judgement it reports
//! is made by library code that production would call.
//!
//! # What it proves, and what it cannot
//!
//! It proves that one §4.6 frame produced by the REAL bridge re-framer parses under the REAL strict
//! Rust parser ([`BridgeTurnResult::parse`]), that its transported echoes equal the envelope
//! ([`SignedTurnResult::check_echoes`]), that the 43-character capability it carries is honoured by the
//! REAL supervisor over a REAL socket from the REAL sidecar principal, and that the bytes reassembled
//! from the served ranges satisfy `len == envelope.output_bytes` and
//! `SHA256(bytes) == envelope.output_sha256`.
//!
//! It proves NOTHING about who may read the protected store: this process runs as the ladder's root
//! orchestrator (it must, to `sudo -u` the sidecar account), and on that kit `/opt/brops-live/store` is
//! world-readable anyway. The fact that these bytes came through §4.10(f) rather than off the disk is
//! established by the SUPERVISOR's own hop log — which records `SO_PEERCRED` uids this process cannot
//! write — and `engine/ci/live/ladder_evidence.py --pull-evidence` is what checks the two against each
//! other. This driver's own evidence is one half of that pair and is not self-certifying.
//!
//! # It must be able to fail
//!
//! `--expect` is mandatory and is compared BY NAME. A run that reports `ok` when `--expect` named a
//! refusal exits non-zero, and so does a run that refuses with the wrong reason. The ladder drives four
//! negative modes on every invocation for the reason this repository keeps relearning: both of its
//! PowerShell harnesses shipped checks that could not report PASS at all, through three audit rounds,
//! and a proof that cannot fail is that same defect with the sign flipped.
//!
//! The two transport-side negatives (`tampered-chunk`, `truncated-chunk`) mutate the reply INSIDE this
//! process's fetch closure, after the sidecar answered. That is deliberate and it is the honest place
//! for them: §2.4 declares the sidecar compromised, so a tamper applied at the sidecar boundary is
//! exactly the adversary §4.6/§7.1's whole-output gate exists to defeat. Neither mutation touches the
//! envelope, so both gates remain aimed at the SIGNED values.
//!
//! # A missing prerequisite is fatal
//!
//! Every input this driver needs is one a CI job can provide, so a missing one is a machine to fix and
//! never a reason to return early. [`require_prerequisite`] panics unless a human has named the exact
//! tag in `BROPS_TEST_MISSING_PREREQUISITES` — the same rule, and the same refusal of blanket forms, as
//! `apps/desktop/src-tauri/provision/tests/prerequisites/mod.rs`. There is no configuration of this
//! driver that reports success while the pull quietly did not run.
//!
//! ```text
//! ladder_output_pull --frame reply.json --evidence-out pull.json \
//!     --mode positive --expect ok [--output-out bytes.bin] \
//!     -- sudo -u brops-sidecar env BROPS_SUPERVISOR_SOCKET=/opt/brops-live/sock/supervisor.sock \
//!        python3 /opt/brops-live/bridge/engine_sidecar.py
//! ```

use std::io::{Read, Write};
use std::process::{Command, Stdio};

use brops_core::governed_bridge_result::BridgeTurnResult;
use brops_core::governed_output_pull::{
    expected_chunk_count, pull_output, PullError, OUTPUT_STREAM_ID_LEN,
};
use brops_core::governed_verification::{OwnedReceiptEnvelope, ReceiptEnvelope};
use brops_core::receipt::sha256_hex;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use serde_json::{json, Value};

/// The variable a human types to say "this machine genuinely lacks that, and I know it".
/// Comma-separated tags, exactly as [`require_prerequisite`] prints them.
const DECLARATION_ENV: &str = "BROPS_TEST_MISSING_PREREQUISITES";

/// Values people reach for when they want the guard off wholesale. Refused BY NAME, so the refusal can
/// explain itself instead of silently matching no tag.
const BLANKET_FORMS: [&str; 8] =
    ["all", "*", "any", "1", "true", "yes", "on", "everything"];

/// The evidence document this driver writes. Its own protocol const so a reader can tell a pull bundle
/// from the round-trip bundle `ladder_evidence.py` writes beside it.
const PULL_EVIDENCE_PROTOCOL: &str = "brops.ladder-output-pull-evidence.v1";

// =================================================================================================
// Prerequisites
// =================================================================================================

/// Fatal unless [`DECLARATION_ENV`] names `tag` exactly.
///
/// `what` says which prerequisite in prose, because "skipped" without it is indistinguishable from
/// "there was nothing to test here".
fn require_prerequisite(present: bool, tag: &str, what: &str) {
    if present {
        return;
    }
    let declaration = std::env::var(DECLARATION_ENV).unwrap_or_default();
    let entries: Vec<&str> =
        declaration.split(',').map(str::trim).filter(|e| !e.is_empty()).collect();
    if let Some(blanket) =
        entries.iter().find(|e| BLANKET_FORMS.contains(&e.to_ascii_lowercase().as_str()))
    {
        panic!(
            "{DECLARATION_ENV} contains `{blanket}`, which declares NOTHING. There is no blanket \
             form and no boolean: every missing prerequisite costs its own tag. Name `{tag}` itself \
             if this machine really lacks it.\n  missing: {what}"
        );
    }
    if entries.iter().any(|e| *e == tag) {
        eprintln!(
            "RESULT: ladder-output-pull SKIPPED — the prerequisite `{tag}` is declared missing in \
             {DECLARATION_ENV}. {what}"
        );
        std::process::exit(0);
    }
    panic!(
        "missing prerequisite: {what}\n  This is a machine to fix, not a result. If this host \
         genuinely cannot provide it, say so by name and this driver will exit 0 instead:\n    \
         {DECLARATION_ENV}={tag}\n  (comma-separate several). A driver that returns early proves \
         nothing, and the exit status would read the same either way."
    );
}

// =================================================================================================
// The five modes, and the expectation vocabulary
// =================================================================================================

/// What this run does to the pull, and therefore what it is entitled to expect.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    /// Nothing is altered: the real token, the real envelope, the replies verbatim.
    Positive,
    /// One character of the capability token is rotated. The supervisor has no such row, so it answers
    /// `stream_unknown` — the same answer it gives a swept, evicted or never-minted token, deliberately,
    /// so a holder cannot learn whether the token it guessed ever existed.
    UnknownStream,
    /// The real token presented with a `receipt_id` that is not this turn's. §4.10(f) P1-3's server-side
    /// three-tuple compare must refuse it `stream_binding_mismatch` — BEFORE a byte is served, not three
    /// steps later by the output digest.
    BindingMismatch,
    /// A compromised sidecar substitutes one byte of one chunk. Length survives; the §4.6/§7.1 digest
    /// gate against the SIGNED `output_sha256` must not.
    TamperedChunk,
    /// A compromised sidecar drops the tail of one chunk. The §4.6/§7.1 length gate must refuse it,
    /// distinctly from the digest gate — the two are separate checks and a short read must not have to
    /// rely on a hash to be caught.
    TruncatedChunk,
}

impl Mode {
    fn parse(value: &str) -> Option<Mode> {
        Some(match value {
            "positive" => Mode::Positive,
            "unknown-stream" => Mode::UnknownStream,
            "binding-mismatch" => Mode::BindingMismatch,
            "tampered-chunk" => Mode::TamperedChunk,
            "truncated-chunk" => Mode::TruncatedChunk,
            _ => return None,
        })
    }

    fn as_str(self) -> &'static str {
        match self {
            Mode::Positive => "positive",
            Mode::UnknownStream => "unknown-stream",
            Mode::BindingMismatch => "binding-mismatch",
            Mode::TamperedChunk => "tampered-chunk",
            Mode::TruncatedChunk => "truncated-chunk",
        }
    }
}

/// The stable name of one outcome, for `--expect` and for the evidence.
///
/// A refusal the SUPERVISOR reached keeps its published §4.10(f) literal, prefixed `refused:` so it can
/// never be confused with a verdict this side reached about bytes it already holds. The distinction is
/// the point of the whole vocabulary: `refused:stream_unknown` means a supervisor decided, and
/// `digest_mismatch` means the desktop did.
fn outcome_name(result: &Result<Vec<u8>, PullError>) -> String {
    match result {
        Ok(_) => "ok".to_string(),
        Err(PullError::Refused(reason)) => format!("refused:{}", reason.as_str()),
        Err(PullError::Transport(_)) => "transport".to_string(),
        Err(PullError::MalformedReply) => "malformed_reply".to_string(),
        Err(PullError::EchoMismatch) => "echo_mismatch".to_string(),
        Err(PullError::ChunkOversize) => "chunk_oversize".to_string(),
        Err(PullError::EofMismatch) => "eof_mismatch".to_string(),
        Err(PullError::OutputTooLarge) => "output_too_large".to_string(),
        Err(PullError::InvalidCapability) => "invalid_capability".to_string(),
        Err(PullError::LengthMismatch) => "length_mismatch".to_string(),
        Err(PullError::DigestMismatch) => "digest_mismatch".to_string(),
    }
}

/// Every name `--expect` accepts, so a typo is refused at the door rather than becoming a run that can
/// never match and therefore can never pass.
///
/// It is EXHAUSTIVE over what [`outcome_name`] can produce, and `every_outcome_name_is_an_accepted_
/// expectation` walks every [`PullError`] variant to keep it that way. That test earns its place: the
/// first version of this table omitted `length_mismatch`, which made the `truncated-chunk` negative
/// unrunnable — a proof that could not be written rather than one that could not fail, but the same
/// hole from the other side.
const EXPECTATIONS: [&str; 15] = [
    "ok",
    "refused:stream_unknown",
    "refused:stream_expired",
    "refused:stream_binding_mismatch",
    "refused:seq_out_of_range",
    "refused:malformed",
    "transport",
    "malformed_reply",
    "echo_mismatch",
    "chunk_oversize",
    "eof_mismatch",
    "output_too_large",
    "invalid_capability",
    "length_mismatch",
    "digest_mismatch",
];

// =================================================================================================
// The mutation a hostile capability token needs
// =================================================================================================

/// Rotate one character of a 43-character base64url token, staying inside the alphabet.
///
/// It stays 43 characters and stays base64url on purpose. A token of the wrong LENGTH is refused by
/// `OutputStreamCapability::from_envelope` before anything is sent, and a token with an out-of-alphabet
/// character is refused by the supervisor's parser as `malformed` — both are real refusals about a
/// SHAPE, and neither reaches the row lookup this negative exists to exercise. Only a well-formed token
/// that no row matches produces `stream_unknown`.
fn rotate_token(token: &str) -> String {
    let mut chars: Vec<char> = token.chars().collect();
    let last = chars.len() - 1;
    chars[last] = match chars[last] {
        'A' => 'B',
        'a' => 'b',
        '0' => '1',
        '-' => '_',
        '_' => '-',
        c if c.is_ascii_uppercase() => 'A',
        c if c.is_ascii_lowercase() => 'a',
        c if c.is_ascii_digit() => '0',
        _ => 'A',
    };
    chars.into_iter().collect()
}

// =================================================================================================
// One round trip
// =================================================================================================

/// Spawn one one-shot sidecar, write ONE request to its stdin, read ONE reply from its stdout.
///
/// §4.10(f)'s transport is one-request/one-response in both directions and the sidecar is stateless by
/// construction — it reads stdin to EOF, writes one document and exits — so the loop is driven by
/// re-invoking a FRESH process per chunk rather than by holding a session. Doing anything else here
/// would be inventing a transport §4.10(f) does not have.
///
/// A spawn failure, a non-UTF8 reply or an unparseable body is a LOCAL failure and becomes
/// [`PullError::Transport`]: no supervisor decided anything, and §4.10(f) P1-5 requires that fact to
/// survive. It is NOT turned into one of the five stream reasons.
fn round_trip(argv: &[String], request: &Value) -> Result<(Value, Option<i32>), PullError> {
    let mut child = Command::new(&argv[0])
        .args(&argv[1..])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| PullError::Transport(format!("could not spawn the sidecar: {e}")))?;
    {
        let stdin = child
            .stdin
            .as_mut()
            .ok_or_else(|| PullError::Transport("the sidecar has no stdin".to_string()))?;
        let body = serde_json::to_vec(request)
            .map_err(|e| PullError::Transport(format!("could not encode the request: {e}")))?;
        stdin
            .write_all(&body)
            .map_err(|e| PullError::Transport(format!("could not write the request: {e}")))?;
    }
    // Dropped so the sidecar's `stdin.read()` reaches EOF; without this it blocks forever.
    drop(child.stdin.take());
    let mut raw = Vec::new();
    child
        .stdout
        .as_mut()
        .ok_or_else(|| PullError::Transport("the sidecar has no stdout".to_string()))?
        .read_to_end(&mut raw)
        .map_err(|e| PullError::Transport(format!("could not read the reply: {e}")))?;
    let status = child
        .wait()
        .map_err(|e| PullError::Transport(format!("could not reap the sidecar: {e}")))?;
    let reply: Value = serde_json::from_slice(&raw).map_err(|e| {
        PullError::Transport(format!(
            "the sidecar wrote {} bytes that are not a JSON document ({e}): {:?}",
            raw.len(),
            String::from_utf8_lossy(&raw[..raw.len().min(200)])
        ))
    })?;
    Ok((reply, status.code()))
}

/// Apply this run's transport-side mutation to one reply, if it has one.
///
/// Both mutations DECODE the served base64url, alter the bytes, and RE-ENCODE. Editing the base64url
/// text directly is what the first version did, and it was wrong in a way the unit tests could not see:
/// `URL_SAFE_NO_PAD` refuses a value whose final group carries non-zero trailing bits, so chopping four
/// characters off a 70-character encoding (the real ladder output is 52 bytes, not a multiple of three)
/// produced a NON-CANONICAL string. The pull then reported `malformed_reply` — a true verdict about a
/// broken frame — and the negative silently stopped testing the LENGTH gate it names. Round-tripping
/// through the codec makes the mutation a mutation of BYTES, which is what a compromised sidecar would
/// actually be able to do, and keeps each negative aimed at the gate in its own name.
///
/// Returns `true` when the reply was altered, so the evidence records which chunk a compromised sidecar
/// touched rather than leaving the reader to infer it from the mode.
fn mutate_reply(mode: Mode, reply: &mut Value) -> bool {
    if !matches!(mode, Mode::TamperedChunk | Mode::TruncatedChunk) {
        return false;
    }
    // A refused reply carries `bytes_b64: null`; a zero-byte output carries `""`, which decodes to
    // zero bytes. Both fall through to `return false` below, because fabricating a chunk where the
    // supervisor served none would put a tamper in the evidence that never happened.
    //
    // There is deliberately no separate `!s.is_empty()` guard on the STRING. Mutation testing found
    // the one this used to have: deleting it killed no test, and it could not — an empty string
    // decodes to empty bytes and is refused one line later. That is the definition of a check that
    // reads as protection while protecting nothing, and this tree deletes those rather than shipping
    // them (the §4.10(a)/(c) precedent, and `governed_output_read.measure_output`'s own note).
    let b64 = match reply.get("bytes_b64").and_then(Value::as_str) {
        Some(s) => s,
        _ => return false,
    };
    let mut bytes = match URL_SAFE_NO_PAD.decode(b64.as_bytes()) {
        Ok(bytes) if !bytes.is_empty() => bytes,
        // Empty, or something this driver cannot decode. The latter is a finding, not a thing to
        // mutate: leaving it untouched lets the pull's own parser name it.
        _ => return false,
    };
    match mode {
        // One bit of one byte. The length survives, so the length gate cannot fire and the §4.6/§7.1
        // digest gate against the SIGNED `output_sha256` is the only thing left to catch it.
        Mode::TamperedChunk => bytes[0] ^= 0x01,
        // Exactly one byte off the tail — the tightest possible short read, so the length gate is
        // reached by the smallest divergence rather than by an obviously broken frame.
        Mode::TruncatedChunk => {
            bytes.pop();
        }
        _ => unreachable!("guarded above"),
    }
    reply["bytes_b64"] = Value::String(URL_SAFE_NO_PAD.encode(&bytes));
    true
}

// =================================================================================================
// Entry
// =================================================================================================

struct Args {
    frame: String,
    evidence_out: String,
    output_out: Option<String>,
    mode: Mode,
    expect: String,
    sidecar: Vec<String>,
}

fn parse_args() -> Args {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let mut frame = None;
    let mut evidence_out = None;
    let mut output_out = None;
    let mut mode = None;
    let mut expect = None;
    let mut sidecar: Vec<String> = Vec::new();
    let mut i = 0;
    while i < argv.len() {
        let flag = argv[i].as_str();
        if flag == "--" {
            sidecar = argv[i + 1..].to_vec();
            break;
        }
        let value = argv.get(i + 1).cloned().unwrap_or_else(|| {
            panic!("{flag} needs a value");
        });
        match flag {
            "--frame" => frame = Some(value),
            "--evidence-out" => evidence_out = Some(value),
            "--output-out" => output_out = Some(value),
            "--mode" => mode = Some(value),
            "--expect" => expect = Some(value),
            other => panic!("unknown flag {other}"),
        }
        i += 2;
    }

    // Each of the five is a prerequisite a CI job supplies, so each is fatal by name rather than
    // defaulted. A driver that invented a default for `--expect` would be a driver that cannot fail.
    require_prerequisite(frame.is_some(), "ladder-pull-frame",
        "--frame <path>: the §4.6 bridge.governed-turn-result.v1 frame the sidecar wrote");
    require_prerequisite(evidence_out.is_some(), "ladder-pull-evidence-out",
        "--evidence-out <path>: where to record what was asked and what came back");
    require_prerequisite(mode.is_some(), "ladder-pull-mode", "--mode <positive|…>");
    require_prerequisite(expect.is_some(), "ladder-pull-expect",
        "--expect <outcome>: the outcome this run must produce, BY NAME");
    require_prerequisite(!sidecar.is_empty(), "ladder-live-sidecar",
        "-- <argv…>: the command that performs ONE desktop→sidecar round trip (the real one-shot \
         bridge/engine_sidecar.py, run as the sidecar principal)");

    let mode = mode.unwrap();
    let expect = expect.unwrap();
    let mode = Mode::parse(&mode)
        .unwrap_or_else(|| panic!("--mode {mode} is not one of positive|unknown-stream|\
                                   binding-mismatch|tampered-chunk|truncated-chunk"));
    assert!(
        EXPECTATIONS.contains(&expect.as_str()),
        "--expect {expect} is not one of {EXPECTATIONS:?}. An expectation this driver cannot \
         produce is an expectation no run can meet, which is a proof that always fails — the mirror \
         of the one that always passes."
    );
    Args {
        frame: frame.unwrap(),
        evidence_out: evidence_out.unwrap(),
        output_out,
        mode,
        expect,
        sidecar,
    }
}

fn main() {
    let args = parse_args();

    let raw = std::fs::read(&args.frame)
        .unwrap_or_else(|e| panic!("cannot read the §4.6 frame at {}: {e}", args.frame));
    let doc: Value = serde_json::from_slice(&raw)
        .unwrap_or_else(|e| panic!("{} is not a JSON document: {e}", args.frame));

    // The REAL strict parser, not a reading of the JSON. It is the whole §4.6 predicate — exactly five
    // top-level keys, exactly eleven receipt keys, every encoded-byte cap, canonical base64url on every
    // b64 field, the closed reason union, and both `ok` biconditionals — and until now nothing had ever
    // run it over a frame a real bridge re-framer produced.
    let signed = BridgeTurnResult::parse(&doc).unwrap_or_else(|e| {
        panic!(
            "the §4.6 frame at {} is not a signed bridge.governed-turn-result.v1: {e:?}. There is \
             nothing to pull: §4.10(f) permits exactly one source for an output_stream_id and this \
             is it.",
            args.frame
        )
    });

    let envelope_value: Value = serde_json::from_slice(signed.envelope_jcs())
        .unwrap_or_else(|e| panic!("the §4.9 envelope_jcs is not a JSON document: {e}"));
    let owned = OwnedReceiptEnvelope::from_payload(&envelope_value)
        .unwrap_or_else(|e| panic!("the §4.9 envelope is not the flat 23-key payload: {e:?}"));
    let envelope = owned.as_receipt_envelope();

    // §7.1's echo equality, run by the party it protects. It catches a proxy that ALTERED what the
    // supervisor said and nothing against one that copied faithfully — so it is a consistency check on
    // the transport, never a second opinion about the turn, and it is emphatically not the output gate
    // below.
    signed
        .check_echoes(&envelope)
        .unwrap_or_else(|e| panic!("§7.1 echo mismatch: the frame's transport echoes disagree with \
                                    the signed envelope ({e:?})"));

    let token = signed.output_stream_id().to_string();
    assert_eq!(
        token.len(),
        OUTPUT_STREAM_ID_LEN,
        "the strict parser admitted a token of the wrong length"
    );

    // ---- what this run alters, and what it must not ------------------------------------------
    // The token is the ONE value that came off the wire, so a token negative alters it. The envelope's
    // `receipt_id` is altered for the binding negative because §4.10(f) P1-3's compare is server-side
    // and there is no other way to reach it. NOTHING here touches `output_bytes` or `output_sha256`:
    // those are the two values the §4.6/§7.1 gate is aimed at, and a driver that could move them would
    // be a driver that could make the gate agree with anything.
    let presented_token = match args.mode {
        Mode::UnknownStream => rotate_token(&token),
        _ => token.clone(),
    };
    let foreign_receipt_id = format!("{}-x", owned.receipt_id());
    let presented_envelope = match args.mode {
        Mode::BindingMismatch => ReceiptEnvelope { receipt_id: &foreign_receipt_id, ..envelope },
        _ => envelope,
    };

    let expected_chunks = expected_chunk_count(envelope.output_bytes)
        .unwrap_or_else(|e| panic!("the signed envelope's output_bytes is unusable: {e:?}"));

    // ---- drive it ------------------------------------------------------------------------------
    let mut chunks: Vec<Value> = Vec::new();
    let mut transcript_seq: u64 = 0;
    let result = pull_output(&presented_envelope, &presented_token, |request| {
        let seq = transcript_seq;
        transcript_seq += 1;
        let (mut reply, exit) = round_trip(&args.sidecar, request)?;
        let served_b64 = reply.get("bytes_b64").and_then(Value::as_str).map(str::to_string);
        let mutated = mutate_reply(args.mode, &mut reply);
        chunks.push(json!({
            "seq": seq,
            "requested": request,
            "sidecar_exit": exit,
            "reply_protocol": reply.get("protocol"),
            "reply_ok": reply.get("ok"),
            "reply_seq": reply.get("seq"),
            "reply_output_stream_id": reply.get("output_stream_id"),
            "reply_eof": reply.get("eof"),
            "reply_error": reply.get("error"),
            // The digest of the bytes the SIDECAR served, before this driver's own mutation. Recorded
            // so a reader can tell a transport that served the wrong range from a driver that broke a
            // correct one — which is the whole difference between the two negatives below.
            "served_chunk_sha256": served_b64.as_ref().map(|b| sha256_hex(b.as_bytes())),
            "served_chunk_b64_len": served_b64.as_ref().map(|b| b.len()),
            "mutated_by_driver": mutated,
        }));
        Ok(reply)
    });

    let observed = outcome_name(&result);
    let matched = observed == args.expect;

    let mut evidence = json!({
        "protocol": PULL_EVIDENCE_PROTOCOL,
        "mode": args.mode.as_str(),
        "expected": args.expect,
        "observed": observed,
        "ok": matched,
        "frame": args.frame,
        "sidecar_argv": args.sidecar,
        "output_stream_id": token,
        "presented_output_stream_id": presented_token,
        "presented_receipt_id": presented_envelope.receipt_id,
        // Read off the SIGNED envelope. §4.10(e)'s echoes of the same two values are inside
        // `SignedTurnResult` with no accessor at all, so this document cannot be written from them
        // even by mistake.
        "signed": {
            "receipt_id": envelope.receipt_id,
            "execution_attempt_id": envelope.execution_attempt_id,
            "run_id": envelope.run_id,
            "output_sha256": envelope.output_sha256,
            "output_bytes": envelope.output_bytes,
        },
        "expected_chunks": expected_chunks,
        "reads_driven": chunks.len(),
        "chunks": chunks,
    });

    match &result {
        Ok(bytes) => {
            // Recorded only on the success path, and only from bytes that already passed both gates.
            // A "reassembled_sha256" beside a failed verdict would be a digest of something nothing
            // accepted, which is the kind of field a later reader quotes.
            evidence["reassembled_bytes"] = json!(bytes.len());
            evidence["reassembled_sha256"] = json!(sha256_hex(bytes));
            if let Some(path) = &args.output_out {
                std::fs::write(path, bytes)
                    .unwrap_or_else(|e| panic!("cannot write the pulled output to {path}: {e}"));
            }
        }
        Err(err) => {
            evidence["error_debug"] = json!(format!("{err:?}"));
        }
    }

    std::fs::write(
        &args.evidence_out,
        serde_json::to_vec_pretty(&evidence).expect("the evidence document must encode"),
    )
    .unwrap_or_else(|e| panic!("cannot write the pull evidence to {}: {e}", args.evidence_out));

    println!(
        "RESULT: ladder-output-pull ok={} mode={} expected={} observed={} reads={} \
         signed_output_sha256={} output_bytes={}",
        matched,
        args.mode.as_str(),
        args.expect,
        observed,
        chunks.len(),
        envelope.output_sha256,
        envelope.output_bytes
    );
    if !matched {
        eprintln!(
            "  the pull did not produce the outcome this run required. Expected {} and observed \
             {}. A negative that accepts ANY failure certifies nothing about the check it names.",
            args.expect, observed
        );
        std::process::exit(1);
    }
}

// =================================================================================================
// Tests — the parts that are this driver's own rather than the library's
// =================================================================================================
//
// The loop, the echo compare, the `eof` check and both output gates belong to
// `governed_output_pull` and are tested there; re-testing them here would be the duplication this
// file exists to avoid. What is tested here is exactly what this file adds: the outcome vocabulary
// (because `--expect` is compared against it BY NAME, so a name this driver can never produce is a
// run that can never pass), and the two mutations (because a mutation that did not survive base64url
// canonicalization would turn a digest negative into a malformed-reply negative and quietly test the
// wrong gate).

#[cfg(test)]
mod tests {
    use super::*;
    use brops_core::governed_output_pull::StreamRefusal;

    #[test]
    fn every_outcome_name_is_an_accepted_expectation() {
        // Every name `outcome_name` can produce must be spellable in `--expect`. A name it can produce
        // and `--expect` refuses is an outcome no run could ever be written to require.
        let produced = [
            outcome_name(&Ok(Vec::new())),
            outcome_name(&Err(PullError::Refused(StreamRefusal::StreamUnknown))),
            outcome_name(&Err(PullError::Refused(StreamRefusal::StreamExpired))),
            outcome_name(&Err(PullError::Refused(StreamRefusal::StreamBindingMismatch))),
            outcome_name(&Err(PullError::Refused(StreamRefusal::SeqOutOfRange))),
            outcome_name(&Err(PullError::Refused(StreamRefusal::Malformed))),
            outcome_name(&Err(PullError::Transport("x".into()))),
            outcome_name(&Err(PullError::MalformedReply)),
            outcome_name(&Err(PullError::EchoMismatch)),
            outcome_name(&Err(PullError::ChunkOversize)),
            outcome_name(&Err(PullError::EofMismatch)),
            outcome_name(&Err(PullError::OutputTooLarge)),
            outcome_name(&Err(PullError::InvalidCapability)),
            outcome_name(&Err(PullError::LengthMismatch)),
            outcome_name(&Err(PullError::DigestMismatch)),
        ];
        // Exhaustive in BOTH directions: every variant produces an accepted name, and every accepted
        // name is produced by some variant. Without the second half a stale entry could sit in the
        // table forever naming an outcome nothing can reach.
        assert_eq!(produced.len(), EXPECTATIONS.len());
        for name in &produced {
            assert!(EXPECTATIONS.contains(&name.as_str()), "{name} is not an expectation");
        }
        for expectation in EXPECTATIONS {
            assert!(
                produced.iter().any(|n| n == expectation),
                "{expectation} is accepted by --expect but no PullError produces it"
            );
        }
    }

    #[test]
    fn a_supervisor_verdict_is_never_confusable_with_a_local_one() {
        // `refused:` is the prefix that separates "a supervisor decided" from "this side decided about
        // bytes it already holds". Without it a log could not tell `stream_unknown` (nobody served the
        // range) from `digest_mismatch` (the range was served and was wrong).
        assert!(outcome_name(&Err(PullError::Refused(StreamRefusal::StreamUnknown)))
            .starts_with("refused:"));
        assert!(!outcome_name(&Err(PullError::DigestMismatch)).starts_with("refused:"));
        assert!(!outcome_name(&Err(PullError::Transport("x".into()))).starts_with("refused:"));
    }

    #[test]
    fn a_rotated_token_stays_a_well_formed_capability() {
        // The point of the `unknown-stream` negative is to reach the ROW LOOKUP. A token of the wrong
        // length never leaves this process, and one outside the base64url alphabet is refused by the
        // supervisor's parser as `malformed` — either way the negative would be testing a shape check
        // rather than the absent-row verdict it names.
        // Every arm of `rotate_token`, including the three GENERIC ones. Mutation testing found the
        // gap: the first fixture only ever ended in 'A', 'z', '0', '-' or '_', so `c if
        // c.is_ascii_uppercase()`, `c if c.is_ascii_lowercase()` and `c if c.is_ascii_digit()` were
        // never reached, and a mutant that made the uppercase arm emit '=' — straight out of the
        // base64url alphabet — survived. A token outside the alphabet is refused by the supervisor's
        // parser as `malformed`, so that mutant would have turned the `unknown-stream` negative into
        // a shape-check negative wearing the absent-row negative's name.
        for token in [
            "A".repeat(OUTPUT_STREAM_ID_LEN),
            "Z".repeat(OUTPUT_STREAM_ID_LEN),
            "a".repeat(OUTPUT_STREAM_ID_LEN),
            "z".repeat(OUTPUT_STREAM_ID_LEN),
            "0".repeat(OUTPUT_STREAM_ID_LEN),
            "9".repeat(OUTPUT_STREAM_ID_LEN),
            format!("{}-", "b".repeat(OUTPUT_STREAM_ID_LEN - 1)),
            format!("{}_", "b".repeat(OUTPUT_STREAM_ID_LEN - 1)),
        ] {
            let rotated = rotate_token(&token);
            assert_eq!(rotated.len(), OUTPUT_STREAM_ID_LEN, "{token} changed length");
            assert_ne!(rotated, token, "{token} was not actually rotated");
            assert!(
                rotated.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'),
                "{rotated} left the base64url alphabet"
            );
        }
    }

    /// EVERY residue class mod 3, because that is the axis the first version of these mutations broke
    /// on. 52 is the real ladder output's length and is 1 mod 3; 96 (0 mod 3) was the only length the
    /// original tests used, and it is the one length at which editing the base64url text happens to
    /// stay canonical. A fixture that only ever tries the easy case is how a negative control comes to
    /// test a different gate than the one in its name.
    const MUTATION_LENGTHS: [usize; 6] = [1, 2, 3, 52, 95, 96];

    #[test]
    fn the_tamper_keeps_the_length_and_moves_the_bytes() {
        // Length-preserving is the whole property: if it changed the length, the LENGTH gate would
        // fire first and the `tampered-chunk` negative would silently stop testing the digest gate.
        for n in MUTATION_LENGTHS {
            let original = vec![7u8; n];
            let mut reply = json!({"bytes_b64": URL_SAFE_NO_PAD.encode(&original)});
            assert!(mutate_reply(Mode::TamperedChunk, &mut reply), "n={n}");
            let decoded = URL_SAFE_NO_PAD
                .decode(reply["bytes_b64"].as_str().unwrap())
                .unwrap_or_else(|e| panic!("n={n}: the tamper left canonical base64url: {e}"));
            assert_eq!(decoded.len(), original.len(), "n={n}");
            assert_ne!(decoded, original, "n={n}");
        }
    }

    #[test]
    fn the_truncation_shortens_the_bytes_and_stays_canonical() {
        // One byte, and still canonical at every residue. A ragged truncation decodes under no
        // canonical decoder, and the run would report `malformed_reply` instead of reaching the LENGTH
        // gate this negative names — which is exactly what the first version of this driver did against
        // the real 52-byte ladder output while these tests were green.
        for n in MUTATION_LENGTHS {
            let original = vec![9u8; n];
            let mut reply = json!({"bytes_b64": URL_SAFE_NO_PAD.encode(&original)});
            assert!(mutate_reply(Mode::TruncatedChunk, &mut reply), "n={n}");
            let decoded = URL_SAFE_NO_PAD
                .decode(reply["bytes_b64"].as_str().unwrap())
                .unwrap_or_else(|e| panic!("n={n}: the truncation left canonical base64url: {e}"));
            assert_eq!(decoded.len(), original.len() - 1, "n={n}");
        }
    }

    #[test]
    fn neither_mutation_touches_a_reply_that_carries_no_bytes() {
        // A refused reply has `bytes_b64: null`. Mutating it would fabricate a chunk where the
        // supervisor served none, and the evidence would record a tamper that never happened.
        let mut refused = json!({"bytes_b64": Value::Null, "ok": false});
        assert!(!mutate_reply(Mode::TamperedChunk, &mut refused));
        assert!(!mutate_reply(Mode::TruncatedChunk, &mut refused));
        // The zero-byte output contract: `seq 0` returns `bytes_b64: ""`, and there is nothing there to
        // truncate or flip either.
        let mut empty = json!({"bytes_b64": "", "ok": true});
        assert!(!mutate_reply(Mode::TamperedChunk, &mut empty));
        assert!(!mutate_reply(Mode::TruncatedChunk, &mut empty));
    }

    #[test]
    fn the_positive_mode_alters_nothing() {
        let mut reply = json!({"bytes_b64": URL_SAFE_NO_PAD.encode([1u8, 2, 3])});
        let before = reply.clone();
        assert!(!mutate_reply(Mode::Positive, &mut reply));
        assert_eq!(reply, before);
        assert!(!mutate_reply(Mode::UnknownStream, &mut reply));
        assert!(!mutate_reply(Mode::BindingMismatch, &mut reply));
        assert_eq!(reply, before);
    }

    #[test]
    fn every_mode_round_trips_its_name() {
        for mode in [
            Mode::Positive,
            Mode::UnknownStream,
            Mode::BindingMismatch,
            Mode::TamperedChunk,
            Mode::TruncatedChunk,
        ] {
            assert_eq!(Mode::parse(mode.as_str()), Some(mode));
        }
        assert_eq!(Mode::parse("whatever"), None);
    }
}
