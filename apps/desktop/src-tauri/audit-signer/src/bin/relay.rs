//! `brops-anchor-relay.exe` — what `BRO_AUDIT_ANCHOR_SIGNER` points at.
//!
//! One canonical audit-head payload in on stdin, one `{payload, signature}` document out on
//! stdout, exit 0. Anything else: nothing on stdout and a non-zero exit with the reason on stderr,
//! which `bro_audit_log._sign_anchor` prints back to the operator.
//!
//! **It holds no key and needs no privilege.** It cannot, because `subprocess.run` hands the child
//! the caller's token: whatever this process could open, the app could open. That is the whole
//! reason the signer is a pre-existing service and this is a shim. `tests/relay_contract.rs`
//! asserts that the compiled binary produces no signature when nothing answers the pipe.
//!
//! Nothing is ever written to stdout except the document. A stray log line there would be parsed
//! by `json.loads(proc.stdout)` and reported as "the signing command did not return a signed
//! document", sending an operator to look for a crypto fault that is a print statement.

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    let stdin = match brops_audit_signer::relay::read_stdin() {
        Ok(bytes) => bytes,
        Err(why) => {
            eprintln!("brops-anchor-relay: {why}");
            std::process::exit(brops_audit_signer::relay::EXIT_BAD_STDIN);
        }
    };

    let (code, stdout, message) =
        brops_audit_signer::relay::run_with(&args, &stdin, |pipe, request| roundtrip(pipe, request));

    if !stdout.is_empty() {
        use std::io::Write;
        let mut out = std::io::stdout();
        if out.write_all(&stdout).and_then(|()| out.flush()).is_err() {
            eprintln!("brops-anchor-relay: could not write the signed document to stdout");
            std::process::exit(brops_audit_signer::relay::EXIT_BAD_REPLY);
        }
    }
    if !message.is_empty() {
        eprintln!("brops-anchor-relay: {message}");
    }
    std::process::exit(code);
}

#[cfg(windows)]
fn roundtrip(pipe: &str, request: &serde_json::Value) -> Result<serde_json::Value, String> {
    brops_audit_signer::win::roundtrip(pipe, request)
}

/// Off Windows there is no second principal to relay to, and pretending otherwise would produce a
/// ledger that looks anchored. POSIX deployments name their own signer command directly — the
/// engine's `signer` user already is the second principal there.
#[cfg(not(windows))]
fn roundtrip(pipe: &str, _request: &serde_json::Value) -> Result<serde_json::Value, String> {
    Err(format!(
        "there is no named-pipe audit-anchor signer on {}: `{pipe}` cannot exist. On POSIX the \
         signer is a separate uid whose key the engine's account cannot read, and \
         BRO_AUDIT_ANCHOR_SIGNER points straight at it — this shim is the Windows-only workaround \
         for a platform where a child process inherits the caller's token.",
        brops_provision::platform_name()
    ))
}
