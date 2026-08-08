//! The relay shim: what `BRO_AUDIT_ANCHOR_SIGNER` actually points at.
//!
//! It holds no key, needs no privilege, and makes no decision. It reads one canonical payload from
//! stdin, hands it to a process that was already running under a different account, and copies the
//! reply to stdout. Everything that matters happened before it started: the service was registered
//! by an elevated installer, minted its own seed under its own account, and is listening on a pipe
//! whose DACL names exactly one client SID.
//!
//! # Exit codes
//!
//! The engine reports a non-zero exit as
//! `"audit-head signing command refused (exit N): <stderr, 400 chars>"`, and treats exit 0 with
//! unparseable stdout as a different, vaguer failure. So every path that has no document to print
//! exits non-zero with a specific code, and stdout stays empty unless it carries the document.
//!
//! | code | meaning |
//! |------|---------|
//! | 0    | one `{payload, signature}` document is on stdout |
//! | 2    | the shim was invoked wrongly (bad arguments) |
//! | 3    | stdin did not carry a JSON object |
//! | 4    | the signer service could not be reached at all |
//! | 5    | the signer service refused to sign |
//! | 6    | the signer service answered with something that is not a document |
//! | 7    | this platform has no signer service |

use std::io::Read;

use serde_json::Value;

/// The argument that names the pipe, so the pipe is chosen by the **installer's** argv rather than
/// by an environment variable.
///
/// `bro_audit_log._signer_argv` accepts a JSON array whose element 0 is the executable and passes
/// the rest through verbatim, which is the only channel that reaches this process without passing
/// through the app's environment. `BRO_AUDIT_ANCHOR_SIGNER` itself is app-visible either way — a
/// forger who can rewrite it can point the engine at their own binary — but that gains them
/// nothing they did not already have, because the *key* is not on this side of the pipe. What it
/// would gain them, if the pipe name came from the environment, is the ability to point a
/// legitimately-installed shim at a pipe they control and collect a payload; naming it in argv
/// makes the shim's target a property of the install rather than of the running environment.
pub const PIPE_ARG: &str = "--pipe";

/// How long the shim will spend trying to reach the service before refusing.
///
/// `bro_audit_log._SIGNER_TIMEOUT` is 10 seconds **and it is spent inside the ledger's exclusive
/// append lock**, so overrunning it does not merely fail this anchor: it starves every other
/// writer up to their own lock timeout, and `subprocess.run` kills the shim mid-call leaving the
/// record written and the anchor stale.
///
/// The reused client (`brops_win_live::pipe::open_client`) retries for ~9 s, which was right for
/// the live kit — its servers are session-0 services that may still be starting when the broker
/// first calls — and is wrong here, where the caller holds a lock and has 10 s total. Rather than
/// fork a second pipe client to change one constant, the shim bounds the whole call externally:
/// the roundtrip runs on a worker thread and the shim exits when this deadline passes, well
/// inside the engine's budget, with a refusal the engine can print.
pub const CONNECT_DEADLINE: std::time::Duration = std::time::Duration::from_secs(6);

pub const EXIT_OK: i32 = 0;
pub const EXIT_BAD_ARGS: i32 = 2;
pub const EXIT_BAD_STDIN: i32 = 3;
pub const EXIT_UNREACHABLE: i32 = 4;
pub const EXIT_REFUSED: i32 = 5;
pub const EXIT_BAD_REPLY: i32 = 6;
pub const EXIT_UNSUPPORTED: i32 = 7;

/// What the shim decided to do, before any I/O has happened.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Invocation {
    /// Relay to this pipe.
    Relay { pipe: String },
    /// Refuse: the argv is not one this shim understands.
    BadArgs { why: String },
}

/// Parse the shim's own argv (excluding argv\[0\]).
///
/// Deliberately tiny and total: an unrecognised argument is a refusal, not an ignored token. The
/// installer writes this argv once; anything else reaching it means the environment is not the one
/// the install produced.
pub fn parse_args(args: &[String]) -> Invocation {
    let mut pipe = brops_provision::audit_signer::SIGNER_PIPE_NAME.to_string();
    let mut i = 0;
    while i < args.len() {
        if args[i] == PIPE_ARG {
            match args.get(i + 1) {
                Some(name) if !name.trim().is_empty() => {
                    pipe = name.clone();
                    i += 2;
                }
                _ => {
                    return Invocation::BadArgs {
                        why: format!("{PIPE_ARG} needs a pipe name"),
                    }
                }
            }
        } else {
            return Invocation::BadArgs {
                why: format!(
                    "unrecognised argument {:?}. This shim takes only [{PIPE_ARG} <name>] — it \
                     relays one payload and holds no key, so there is nothing else to configure",
                    args[i]
                ),
            };
        }
    }
    Invocation::Relay { pipe }
}

/// Read every byte of stdin. `subprocess.run(input=...)` writes the payload and closes the stream,
/// so EOF is the end of the request and there is no framing to parse.
pub fn read_stdin() -> Result<Vec<u8>, String> {
    let mut buf = Vec::new();
    std::io::stdin()
        .read_to_end(&mut buf)
        .map_err(|e| format!("could not read the payload from stdin: {e}"))?;
    if buf.is_empty() {
        return Err("stdin was empty; bro_audit_log always writes one canonical payload".to_string());
    }
    Ok(buf)
}

/// The whole shim, minus the platform call. `roundtrip` is the only impure part, so the
/// argument-handling, parsing, interpretation and exit-code mapping are testable on any host.
pub fn run_with<F>(args: &[String], stdin: &[u8], roundtrip: F) -> (i32, Vec<u8>, String)
where
    F: FnOnce(&str, &Value) -> Result<Value, String>,
{
    let pipe = match parse_args(args) {
        Invocation::Relay { pipe } => pipe,
        Invocation::BadArgs { why } => return (EXIT_BAD_ARGS, Vec::new(), why),
    };
    let request = match crate::parse_request(stdin) {
        Ok(v) => v,
        Err(why) => return (EXIT_BAD_STDIN, Vec::new(), why),
    };
    let reply = match roundtrip(&pipe, &request) {
        Ok(v) => v,
        Err(why) => return (EXIT_UNREACHABLE, Vec::new(), why),
    };
    match crate::interpret_reply(&reply) {
        Ok(document) => (EXIT_OK, crate::document_stdout_bytes(&document), String::new()),
        Err(why) if why.contains("REFUSED") => (EXIT_REFUSED, Vec::new(), why),
        Err(why) => (EXIT_BAD_REPLY, Vec::new(), why),
    }
}
