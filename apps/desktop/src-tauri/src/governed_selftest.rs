//! Governed trust-chain self-test (owner-visible).
//!
//! This runs the REAL in-process governed turn — challenge → supervisor lease →
//! attest → isolated-signer signature → `verify_and_accept` → `trusted_verified` —
//! with real ed25519 + JCS + SHA-256 crypto, via the Windows LIVE kit's proven
//! `proof::in_process_turn` (the same chain its integration test asserts reaches
//! `trusted_verified`). It exists so the owner can SEE the trust machinery work
//! end-to-end and get a genuine `trusted_verified` receipt — never a faked boolean.
//!
//! HONESTY — read carefully. This does NOT flip live AI turns to "verified": those
//! still run under `NoTrustedManifest` and stay fail-closed (blocked / development-
//! untrusted). And the root of trust here is the compiled-in TCB *demonstration*
//! anchor (a public constant), not a secret offline-HSM key — so the crypto really
//! verifies, but the custody posture is demonstration-grade. Both facts are carried
//! back to the UI verbatim so nothing is overclaimed.

use serde::Serialize;

/// The result of one governed trust-chain self-test.
#[derive(Serialize)]
pub struct TrustSelftest {
    /// True only where the in-process kit is compiled (Windows).
    pub available: bool,
    /// The committed message's trust state: `"trusted_verified"` on a bound run, else empty.
    pub trust_state: String,
    /// The resolved receipt key's `trust_class` is Production. AUDIT NOTE (dim-1 P2): this alone does NOT
    /// mean a real production ROOT signed the manifest — the in-process self-test ALWAYS runs under the
    /// compiled-in DEMONSTRATION anchor, so this is Production-CLASS crypto at demonstration custody. A
    /// consumer MUST NOT render this as real production trust while `demonstration_custody` is true.
    pub production_verified: bool,
    /// True when the root of trust is the compiled-in DEMONSTRATION anchor (a public constant), NOT a real
    /// offline-root-verified production manifest. The in-process self-test always uses the demonstration
    /// anchor, so this is ALWAYS true for this command — it is the explicit, un-missable flag that pairs with
    /// `production_verified` so the boolean can never be read as production trust on its own.
    pub demonstration_custody: bool,
    /// The committed body read back as `trusted_verified`.
    pub bound: bool,
    /// The kit's own trust string (e.g. `trusted_verified(production key=… epoch=…)`).
    pub detail: String,
    /// The reply the chain's executor produced INSIDE the governed turn and which the receipt then bound +
    /// verified — the honest end-to-end artifact. With `BROPS_SELFTEST_MODEL_CMD` set this is a real model
    /// answer; otherwise a fixed demonstration string. Always demonstration custody (see `demonstration_custody`).
    pub answer: String,
    /// The honest custody posture — the crypto is real, the root is a demonstration anchor.
    pub custody_note: String,
    /// Which build produced this (windows / non-windows).
    pub platform_note: String,
}

const CUSTODY_NOTE: &str = "The crypto is real: a full challenge→lease→attest→sign→verify chain with \
ed25519 + JCS + SHA-256 that genuinely verifies. But the root of trust is the compiled-in TCB demonstration \
anchor (a public constant), NOT a secret offline-HSM key — so this proves the machinery, at demonstration-grade \
custody. Live AI turns still run fail-closed (NoTrustedManifest); production offline-root custody + a live \
supervisor/signer sidecar remain pending before real turns can reach trusted_verified.";

/// Demonstration model seam (Windows). The chain's executor calls this DURING the governed execution step to
/// produce the reply. If the operator points `BROPS_SELFTEST_MODEL_CMD` at a model CLI (e.g. `claude -p -`),
/// its stdout (over a fixed demo prompt on stdin) is what the chain binds + verifies — a REAL answer flowing
/// through the full governed chain, end to end. Unset (and in CI) it returns a fixed demonstration string so
/// the chain still exercises with no external dependency. Either way this is DEMONSTRATION custody, never
/// production; on any spawn/exit/empty error it falls back to the demo bytes (the turn never fails on the
/// model seam — the chain's own fail-closed still governs).
#[cfg(windows)]
const SELFTEST_DEMO_OUTPUT: &[u8] = b"BROPS windows governed output v1";

#[cfg(windows)]
fn run_selftest_model(cmd: Option<&str>) -> Vec<u8> {
    let cmd = match cmd {
        Some(c) if !c.trim().is_empty() => c,
        _ => return SELFTEST_DEMO_OUTPUT.to_vec(),
    };
    let prompt = "In one short sentence, confirm the BroPS governed trust chain produced this reply.";
    // `cmd /C <cmd>` so the operator can point it at any model CLI; the prompt rides in on stdin.
    let spawned = std::process::Command::new("cmd")
        .args(["/C", &cmd])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn();
    let mut child = match spawned {
        Ok(c) => c,
        Err(_) => return SELFTEST_DEMO_OUTPUT.to_vec(),
    };
    if let Some(mut si) = child.stdin.take() {
        use std::io::Write;
        let _ = si.write_all(prompt.as_bytes());
    }
    match child.wait_with_output() {
        Ok(o) if o.status.success() && !o.stdout.is_empty() => o.stdout,
        _ => SELFTEST_DEMO_OUTPUT.to_vec(),
    }
}

/// Run the governed trust-chain self-test. On Windows this executes the real
/// in-process turn; elsewhere it reports honestly that the kit isn't compiled.
#[tauri::command]
pub fn governed_trust_selftest() -> Result<TrustSelftest, String> {
    #[cfg(windows)]
    {
        let now_ms: i64 = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0);
        let dir = std::env::temp_dir().join(format!("brops-trust-selftest-{}", brops_core::id()));
        // The reply is produced INSIDE the chain (in_process_turn_produce calls this closure during the
        // governed execution step), so the receipt binds exactly what the chain's executor produced — not a
        // pre-computed value merely signed after the fact. Capture it to surface the honest end-to-end answer.
        let captured = std::cell::RefCell::new(Vec::<u8>::new());
        let cmd_env = std::env::var("BROPS_SELFTEST_MODEL_CMD").ok();
        let produce = || -> Result<Vec<u8>, ()> {
            let out = run_selftest_model(cmd_env.as_deref());
            if out.is_empty() {
                return Err(());
            }
            *captured.borrow_mut() = out.clone();
            Ok(out)
        };
        let outcome = brops_win_live::proof::in_process_turn_produce(&dir, now_ms, produce)?;
        let _ = std::fs::remove_dir_all(&dir);
        let answer = String::from_utf8_lossy(&captured.into_inner()).chars().take(4000).collect::<String>();
        Ok(TrustSelftest {
            available: true,
            trust_state: if outcome.bound { "trusted_verified".to_string() } else { String::new() },
            production_verified: outcome.production_verified,
            demonstration_custody: true, // the in-process self-test always runs under the TCB demonstration anchor
            bound: outcome.bound,
            detail: outcome.trust_str,
            answer,
            custody_note: CUSTODY_NOTE.to_string(),
            platform_note: "windows".to_string(),
        })
    }
    #[cfg(not(windows))]
    {
        Ok(TrustSelftest {
            available: false,
            trust_state: String::new(),
            production_verified: false,
            demonstration_custody: true, // this build never proves production trust
            bound: false,
            detail: "The in-process governed trust self-test is compiled only for the Windows build.".to_string(),
            answer: String::new(),
            custody_note: CUSTODY_NOTE.to_string(),
            platform_note: "non-windows".to_string(),
        })
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    #[test]
    fn model_seam_defaults_to_the_demonstration_output() {
        // No configured command (and CI) → the fixed demonstration bytes, so the chain still exercises
        // end-to-end without any external model dependency.
        assert_eq!(run_selftest_model(None), SELFTEST_DEMO_OUTPUT);
        assert_eq!(run_selftest_model(Some("   ")), SELFTEST_DEMO_OUTPUT, "blank command is treated as unset");
    }

    #[test]
    fn model_seam_uses_a_configured_command_stdout() {
        // A configured command's stdout is exactly what the chain will bind + verify — proving a real model
        // CLI can be plugged in. `echo` is a cmd.exe builtin, so this needs no external tool.
        let out = run_selftest_model(Some("echo governed-ok"));
        let text = String::from_utf8_lossy(&out);
        assert!(text.contains("governed-ok"), "the configured command's stdout is the reply: {text:?}");
        assert_ne!(out, SELFTEST_DEMO_OUTPUT, "a working command must not fall back to the demo bytes");
    }
}
