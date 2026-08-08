//! The second principal as a running process: the **signer service**, the **relay shim**, and the
//! custody of the anchor key on disk.
//!
//! `brops_provision::audit_signer` is the specification and holds every *decision* — which
//! principals, which DACL, which payload shape, what may be signed, what a rollback is. This crate
//! adds only what a decision cannot be: a process that owns the key, a transport that carries one
//! request, and the file custody in between. Nothing here re-decides anything there.
//!
//! # The relay contract, derived from `engine/runtime/bro_audit_log.py`
//!
//! Not guessed. Every clause below is a line of the module that has to accept us:
//!
//! * **argv** — `anchor_custody()` reads `BRO_AUDIT_ANCHOR_SIGNER` and passes it to `_signer_argv`,
//!   which accepts either a bare absolute path or a **JSON array of strings** whose element 0 is
//!   that path. It `resolve()`s element 0, requires `is_file()`, and *refuses a path lexically
//!   inside the engine tree*. The result is `[str(resolved)] + argv[1:]` — so the shim may carry
//!   extra arguments, and [`relay::PIPE_ARG`] is how the pipe name is chosen without an environment
//!   variable the ledger's own writer could repoint.
//! * **stdin** — `_sign_anchor` calls `subprocess.run(argv, input=_canonical(payload), text=True,
//!   timeout=_SIGNER_TIMEOUT)`. `_canonical` is `json.dumps(obj, sort_keys=True,
//!   separators=(",", ":"))`, i.e. exactly the bytes
//!   [`brops_provision::canonical::canonical_bytes`] produces. One JSON object, no trailing
//!   newline, and **the stream is closed** — there is no length prefix and no second request.
//! * **stdout** — `json.loads(proc.stdout)` must yield a `dict`, and `verify_signed_payload`
//!   refuses any document whose key set is not exactly `{"payload", "signature"}`. So stdout
//!   carries **one JSON object and nothing else**. Every diagnostic goes to stderr, which the
//!   engine only surfaces on a non-zero exit (truncated to 400 characters).
//! * **the payload may not be changed** — `_sign_anchor` refuses unless
//!   `document.get("payload") == payload`, compared as Python dicts. Key order is therefore free
//!   but the value set is not: the signer signs the head the ledger assembled, or nothing.
//! * **exit code** — non-zero is a refusal the engine reports with our stderr attached. `0` with
//!   unparseable stdout is a *worse* failure mode (it reads as "the signer returned garbage"), so
//!   every path in [`relay`] that has no document to print exits non-zero.
//! * **the budget is 10 seconds** — `_SIGNER_TIMEOUT`, and it is spent *inside the ledger's
//!   exclusive append lock*. See [`relay::CONNECT_DEADLINE`] for why the reused client's own retry
//!   loop does not fit inside it.
//!
//! # Why the shim cannot be the signer, restated in one line
//!
//! `subprocess.run` gives the child the **caller's** token. A signer named in
//! `BRO_AUDIT_ANCHOR_SIGNER` therefore runs as the app, and a key it can open is a key the app can
//! open. The shim holds nothing; the key lives in a process that was already running under a
//! different account before the app asked for anything.
//!
//! # What is reused, and where the existing machinery is wrong for this
//!
//! * **The pipe server is `brops_win_live::pipe::run_server`**, unchanged: it builds the
//!   restrictive descriptor from `pipe_acl::pipe_dacl_plan`, refuses to serve on a pipe it cannot
//!   restrict, authenticates the peer SID with `brops_win_broker::syscall`, and never releases the
//!   pipe name to a successor. This deployment is the *cross-account* case that module says it
//!   wants: `broker_is_server_principal` is false, so the create-instance restriction is real here
//!   rather than collapsed.
//! * **The pipe client is `brops_win_live::pipe::hop_once`**, whose `open_client` retries for
//!   ~9 seconds. That is **wrong for this caller** and is the one place the reuse does not fit:
//!   the engine's whole budget is 10 seconds and it is holding the ledger lock, so a shim that
//!   spent 9 of them connecting would be killed mid-call and strand the append. [`relay`] bounds
//!   it externally rather than forking a second client — see [`relay::CONNECT_DEADLINE`].
//! * **`audit_signer::PIPE_SPEC` was wrong** and is corrected in that module: it described
//!   "write, then half-close". A byte-mode named pipe has no half-close — `CloseHandle` closes the
//!   read direction too, so a client that half-closed could never receive the reply. The real
//!   framing is the live kit's 4-byte big-endian length prefix, which is what both ends already
//!   speak.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use brops_provision::audit_signer as spec;

pub mod custody;
pub mod relay;
pub mod register;

#[cfg(windows)]
pub mod win;

// =================================================================================================
// The reply document
// =================================================================================================

/// The exact key set `bro_audit_log.verify_signed_payload` accepts:
/// `set(document) != {"payload", "signature"}` is an outright refusal there, so a signer that
/// helpfully attached a `key_id` or a `note` would produce documents the engine rejects *after*
/// signing them.
pub const DOCUMENT_FIELDS: [&str; 2] = ["payload", "signature"];

/// A refusal, in the shape the pipe carries it. Deliberately **not** the signed-document shape:
/// a refusal must be impossible to mistake for a document, so it carries `ok: false` and no
/// `signature` field at all.
pub fn refusal(reason: impl Into<String>) -> Value {
    json!({ "ok": false, "reason": reason.into() })
}

/// `true` when `v` is a refusal rather than a document.
pub fn is_refusal(v: &Value) -> bool {
    v.get("ok").and_then(Value::as_bool) == Some(false)
}

/// Is this exactly the document the engine will accept — `{payload, signature}` and nothing else?
///
/// Checked on the **producing** side as well as the consuming one, because a document that is
/// signed and then rejected has already spent the anti-rollback state: the signer would have
/// recorded a count it can never be asked to re-sign.
pub fn is_engine_shaped_document(v: &Value) -> bool {
    let Some(obj) = v.as_object() else { return false };
    obj.len() == DOCUMENT_FIELDS.len()
        && DOCUMENT_FIELDS.iter().all(|f| obj.contains_key(*f))
        && obj["payload"].is_object()
        && obj["signature"].as_str().is_some_and(|s| !s.is_empty())
}

// =================================================================================================
// The signer's decision, as one pure function
// =================================================================================================

/// Everything the service knows, minus the syscalls.
///
/// `running_as` is supplied by the caller and is the **only** fact this crate cannot check for
/// itself. There is exactly one production call site — `src/bin/service.rs`, which reads it from
/// `winimpl::current_user_sid()` before any key is touched — and the tests supply it directly, in
/// the shape `audit_signer.rs` already uses for every other decision. It is not an override: the
/// service binary has no flag, environment variable or file that can set it.
pub struct AnchorCore {
    key: ed25519_dalek::SigningKey,
    key_id: String,
    /// `service_account_sid(SIGNER_SERVICE_NAME)` — who this process must BE.
    expected_principal: String,
    /// Who this process actually is.
    running_as: String,
    state_path: PathBuf,
    /// Per-ledger anti-rollback high-water marks, keyed by `payload.ledger`.
    state: std::sync::Mutex<BTreeMap<String, spec::AnchorState>>,
}

impl AnchorCore {
    /// Build the core over an already-loaded custody record.
    ///
    /// Refuses rather than degrades when the principal is wrong: with `running_as !=
    /// expected_principal` every request is answered with
    /// [`spec::SignRefusal::WrongPrincipal`], and the key is never used. The service binary does
    /// not even get this far — it exits before minting — but the core refuses independently so a
    /// future caller cannot reintroduce the defect by forgetting the startup check.
    pub fn new(
        custody: custody::SignerCustody,
        expected_principal: &str,
        running_as: &str,
        state_path: &Path,
    ) -> Result<AnchorCore, custody::CustodyError> {
        let state = custody::load_state(state_path)?;
        Ok(AnchorCore {
            key: custody.key,
            key_id: custody.key_id,
            expected_principal: expected_principal.to_string(),
            running_as: running_as.to_string(),
            state_path: state_path.to_path_buf(),
            state: std::sync::Mutex::new(state),
        })
    }

    pub fn key_id(&self) -> &str {
        &self.key_id
    }

    /// Answer one request: either the engine-shaped signed document, or a refusal.
    ///
    /// The anti-rollback state is written to disk **before** the document is returned. A signer
    /// that replied first and recorded afterwards would, on a crash in between, forget a count it
    /// had already signed — and then happily re-sign a lower one, which is the whole property.
    pub fn decide(&self, request: &Value) -> Value {
        let mut state = match self.state.lock() {
            Ok(s) => s,
            // A poisoned lock means a previous request panicked while holding the high-water
            // marks. The state may be anything; signing on top of "anything" is exactly what
            // anti-rollback forbids.
            Err(_) => {
                return refusal(
                    "the signer's anti-rollback state is poisoned by an earlier failure; refusing \
                     to sign rather than sign over state of unknown provenance",
                )
            }
        };
        let ledger = request.get("ledger").and_then(Value::as_str).unwrap_or_default().to_string();
        let last = state.get(&ledger).cloned();
        match spec::anchor_request(
            request.clone(),
            &self.key_id,
            &self.expected_principal,
            &self.running_as,
            &self.key,
            last.as_ref(),
        ) {
            Ok((document, new_state)) => {
                // NOT REACHABLE TODAY, and said so rather than left to look covered:
                // `sign_anchor` -> `crate::sign_document` always builds `{payload, signature}`,
                // so no input can make this fire and no test can kill it (mutating it away
                // leaves every test green - reported as a surviving mutant). It stays because
                // `sign_document` is a separate function with other callers, and a document that
                // was signed and then rejected has already spent an anti-rollback count: the
                // signer would have recorded a number it can never be asked to re-sign.
                if !is_engine_shaped_document(&document) {
                    return refusal(
                        "the signer produced a document the engine's verify_signed_payload would \
                         refuse; not returning it and not recording its count",
                    );
                }
                state.insert(new_state.ledger.clone(), new_state.clone());
                if let Err(e) = custody::save_state(&self.state_path, &state) {
                    // Undo the in-memory advance so memory and disk cannot disagree.
                    match last {
                        Some(prev) => state.insert(ledger, prev),
                        None => state.remove(&new_state.ledger),
                    };
                    return refusal(format!(
                        "the anchor was signed but its anti-rollback high-water mark could not be \
                         persisted ({e}); discarding the signature, because a signature this \
                         signer cannot remember making is a signature it would make again at a \
                         lower count"
                    ));
                }
                document
            }
            Err(why) => refusal(why.to_string()),
        }
    }
}

// =================================================================================================
// The request the relay puts on the wire
// =================================================================================================

/// Parse the canonical payload the engine wrote to the shim's stdin.
///
/// The shim does **not** re-canonicalise: it parses to confirm the bytes are a JSON object at all
/// (so a truncated write is a clean refusal rather than a mysterious server-side error) and hands
/// the parsed value on. Key order is lost by the parse and that is safe — `_sign_anchor` compares
/// `document["payload"] == payload` as Python dicts, and every value in
/// `ANCHOR_PAYLOAD_FIELDS` is a string, an integer or null, so the round trip is exact.
/// `tests/relay_contract.rs::the_payload_survives_the_relays_json_round_trip` pins that.
pub fn parse_request(stdin_bytes: &[u8]) -> Result<Value, String> {
    let value: Value = serde_json::from_slice(stdin_bytes)
        .map_err(|e| format!("the payload on stdin is not JSON ({e})"))?;
    if !value.is_object() {
        return Err("the payload on stdin is not a JSON object".to_string());
    }
    Ok(value)
}

/// The exact bytes `bro_audit_log._canonical` would have produced for `payload`.
///
/// Used by the tests to prove the wire carries what the engine sent, and by nothing else — the
/// relay forwards the parsed value, and the *signature* is computed by
/// [`brops_provision::audit_signer::sign_anchor`] over its own canonicalisation.
pub fn canonical_request_bytes(payload: &Value) -> Result<Vec<u8>, String> {
    brops_provision::canonical::canonical_bytes(payload).map_err(|e| e.to_string())
}

/// Turn a pipe reply into either the document to print or the message to refuse with.
pub fn interpret_reply(reply: &Value) -> Result<Value, String> {
    if is_refusal(reply) {
        let reason =
            reply.get("reason").and_then(Value::as_str).unwrap_or("no reason given").to_string();
        let peer = reply
            .get("peer_sid")
            .and_then(Value::as_str)
            .map(|s| format!(" (peer SID seen by the signer: {s})"))
            .unwrap_or_default();
        return Err(format!("the audit-anchor signer REFUSED to sign: {reason}{peer}"));
    }
    if !is_engine_shaped_document(reply) {
        let keys: Vec<&str> = reply
            .as_object()
            .map(|o| o.keys().map(String::as_str).collect())
            .unwrap_or_default();
        return Err(format!(
            "the audit-anchor signer returned something that is not a {{payload, signature}} \
             document (fields: {keys:?}). bro_audit_log.verify_signed_payload refuses any other \
             key set, so returning it would be a signature the ledger could never install"
        ));
    }
    Ok(reply.clone())
}

/// The `install_steps` the specification emits, plus the steps that were missing from it:
/// the app SID the service is told to accept, and the ACL on that file.
///
/// Kept next to the service rather than in the spec because they name *this crate's* files.
pub fn additional_install_steps(paths: &spec::SignerPaths, app_sid: &str) -> Vec<String> {
    let allowed = paths.signer_dir.join(register::ALLOWED_APP_SID_FILE);
    vec![
        format!(
            "echo {app_sid} > \"{}\"   # the ONLY peer the signer's pipe will accept",
            allowed.display()
        ),
        format!(
            "# {} inherits the protected DACL of {}: the app must not be able to rewrite the SID \
             the signer trusts, or it could nominate itself twice",
            allowed.display(),
            paths.signer_dir.display()
        ),
        format!(
            "sc.exe failure {} reset= 0 actions= restart/5000   # a signer that is not running \
             leaves the ledger honestly unanchored, never silently unanchored",
            spec::SIGNER_SERVICE_NAME
        ),
    ]
}

/// The `{payload, signature}` document, serialised the way stdout must carry it.
pub fn document_stdout_bytes(document: &Value) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(document).unwrap_or_else(|_| b"{}".to_vec());
    bytes.push(b'\n');
    bytes
}

/// Sorted field names of a JSON object, for diagnostics.
pub fn field_names(v: &Value) -> Vec<String> {
    v.as_object().map(Map::keys).map(|k| k.cloned().collect()).unwrap_or_default()
}
