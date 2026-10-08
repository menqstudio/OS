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
//! anchor — a public constant whose private half is in this source tree — so the
//! crypto really verifies, but the custody posture is demonstration-grade. Both facts
//! are carried back to the UI verbatim so nothing is overclaimed.
//!
//! WHAT PRODUCTION TRUST IS NOT (T-145). This file, the note it shows on screen and its
//! two frontend mirrors used to contrast the demonstration anchor with a secret key held
//! off the machine, and to say production was waiting on custody of that kind. There is
//! no such key and there will not be one: Owner decision #78 (2026-08-09) is that the
//! INSTALL mints trust and no person holds, carries or signs with a root
//! (`docs/OWNER_ACTION_REQUIRED.md` §0). What production is waiting on is stated in
//! [`CUSTODY_NOTE`], and `tools/check_no_owner_key_ceremony.py` now refuses the old
//! wording wherever it reappears.

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
    /// True when the root of trust is the compiled-in DEMONSTRATION anchor (a public constant), NOT a
    /// manifest verified under an install-minted root. The in-process self-test always uses the demonstration
    /// anchor, so this is ALWAYS true for this command — it is the explicit, un-missable flag that pairs with
    /// `production_verified` so the boolean can never be read as production trust on its own.
    pub demonstration_custody: bool,
    /// The committed body read back as `trusted_verified`.
    pub bound: bool,
    /// The whole challenge→lease→attest→sign→verify chain ran and resolved a key under a verified
    /// anchor (`ProofOutcome::chain_bound`). THIS is what a self-test pass means, together with
    /// `bound` — not `production_verified`, which is `false` on every path into the in-process kit.
    /// The panel gated its PASSED verdict on `production_verified`, so a good run rendered nothing
    /// at all for as long as the panel existed; this field is what it reads now.
    pub chain_bound: bool,
    /// The kit's own trust string (e.g. `trusted_verified(production key=… epoch=…)`).
    pub detail: String,
    /// The reply the chain's executor produced INSIDE the governed turn and which the receipt then bound +
    /// verified — the honest end-to-end artifact. With `BROPS_SELFTEST_MODEL_CMD` set this is a real model
    /// answer; otherwise a fixed demonstration string. Always demonstration custody (see `demonstration_custody`).
    pub answer: String,
    /// Whether a model produced `answer`, or the built-in placeholder was bound instead — and
    /// which of the two reasons (remediation audit, honesty finding).
    pub answer_source: AnswerSource,
    /// The same fact as a plain bool, so a UI cannot render the verdict without it.
    pub answer_is_from_a_model: bool,
    /// The honest custody posture — the crypto is real, the root is a demonstration anchor.
    pub custody_note: String,
    /// Which build produced this (windows / non-windows).
    pub platform_note: String,
}

/// The custody posture, shown to the owner word for word beside every self-test result.
///
/// Three claims, each of which is checkable: the anchor is a compiled-in public constant whose
/// private half is in the source tree; live turns are fail-closed; and the route to production is
/// an INSTALL-minted root, which commits `demonstration_custody` until the Owner's
/// `INSTALL_MINTED_CUSTODY_ACCEPTED` is flipped after an independent audit. It names no key a
/// person holds, because there is none (#78).
const CUSTODY_NOTE: &str = "The crypto is real: a full challenge→lease→attest→sign→verify chain with \
ed25519 + JCS + SHA-256 that genuinely verifies. But the root of trust is the compiled-in TCB demonstration \
anchor — a public constant whose private half is in the source tree — so this proves the machinery, at \
demonstration-grade custody. Live AI turns still run fail-closed (NoTrustedManifest). No person holds a \
production key and none ever will: trust is minted by the install. A root minted that way commits \
demonstration_custody, not trusted_verified, until the Owner accepts install-minted custody after an \
independent audit — which has not happened — and real turns also need a live supervisor/signer sidecar.";

/// Demonstration model seam (Windows). The chain's executor calls this DURING the governed execution step to
/// produce the reply. If the operator points `BROPS_SELFTEST_MODEL_CMD` at a model CLI (e.g. `claude -p -`),
/// its stdout (over a fixed demo prompt on stdin) is what the chain binds + verifies — a REAL answer flowing
/// through the full governed chain, end to end. Unset (and in CI) it returns a fixed demonstration string so
/// the chain still exercises with no external dependency. Either way this is DEMONSTRATION custody, never
/// production; on any spawn/exit/empty error it falls back to the demo bytes (the turn never fails on the
/// model seam — the chain's own fail-closed still governs).
///
/// That fallback is legitimate — the self-test exists to prove the CHAIN works, with or without a model —
/// but it must never be invisible. `AnswerSource` travels with the answer so a UI cannot show a placeholder
/// beside `trusted_verified` without saying which one it is (remediation audit, honesty finding).
#[cfg(windows)]
const SELFTEST_DEMO_OUTPUT: &[u8] = b"BROPS windows governed output v1";

/// Where the self-test's answer came from (remediation audit, honesty finding).
///
/// The chain signs whatever the executor closure produces, and it signs it honestly — that part
/// was never in doubt. What was wrong is that a FAILED or ABSENT model was indistinguishable
/// from a real one in everything the user could see: no `BROPS_SELFTEST_MODEL_CMD` (the default
/// case), a spawn failure, a non-zero exit or empty output all silently became a built-in
/// constant, which the chain then bound and the UI presented beside `trusted_verified`. A
/// verified receipt over a placeholder is a true statement about custody and a false impression
/// about what answered.
#[derive(serde::Serialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum AnswerSource {
    /// A configured model ran and produced these exact bytes.
    Model,
    /// No model was configured — the built-in placeholder was bound instead.
    BuiltinPlaceholderNoModelConfigured,
    /// A model was configured but did not run, or produced nothing usable.
    BuiltinPlaceholderModelFailed,
}

#[cfg(windows)]
fn run_selftest_model(cmd: Option<&str>) -> (Vec<u8>, AnswerSource) {
    let cmd = match cmd {
        Some(c) if !c.trim().is_empty() => c,
        _ => {
            return (
                SELFTEST_DEMO_OUTPUT.to_vec(),
                AnswerSource::BuiltinPlaceholderNoModelConfigured,
            )
        }
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
        Err(_) => {
            return (SELFTEST_DEMO_OUTPUT.to_vec(), AnswerSource::BuiltinPlaceholderModelFailed)
        }
    };
    if let Some(mut si) = child.stdin.take() {
        use std::io::Write;
        let _ = si.write_all(prompt.as_bytes());
    }
    match child.wait_with_output() {
        Ok(o) if o.status.success() && !o.stdout.is_empty() => (o.stdout, AnswerSource::Model),
        _ => (SELFTEST_DEMO_OUTPUT.to_vec(), AnswerSource::BuiltinPlaceholderModelFailed),
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
        let source = std::cell::Cell::new(AnswerSource::BuiltinPlaceholderNoModelConfigured);
        let produce = || -> Result<Vec<u8>, ()> {
            let (out, from) = run_selftest_model(cmd_env.as_deref());
            if out.is_empty() {
                return Err(());
            }
            source.set(from);
            *captured.borrow_mut() = out.clone();
            Ok(out)
        };
        // Bind, clean up, THEN propagate: with `?` on the call itself an erroring chain returned
        // before the removal and left its proof store behind (the kit creates the directory first).
        let outcome = brops_win_live::proof::in_process_turn_produce(&dir, now_ms, produce);
        let _ = std::fs::remove_dir_all(&dir);
        let outcome = outcome?;
        let answer = String::from_utf8_lossy(&captured.into_inner()).chars().take(4000).collect::<String>();
        Ok(TrustSelftest {
            available: true,
            trust_state: if outcome.bound { "trusted_verified".to_string() } else { String::new() },
            production_verified: outcome.production_verified,
            demonstration_custody: true, // the in-process self-test always runs under the TCB demonstration anchor
            bound: outcome.bound,
            chain_bound: outcome.chain_bound,
            detail: outcome.trust_str,
            answer,
            // The user is told WHAT answered, beside the verdict about custody. A verified
            // receipt over a placeholder is honest about the chain and silent about the model
            // unless this says so.
            answer_source: source.get(),
            answer_is_from_a_model: source.get() == AnswerSource::Model,
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
            chain_bound: false,
            detail: "The in-process governed trust self-test is compiled only for the Windows build.".to_string(),
            answer: String::new(),
            answer_source: AnswerSource::BuiltinPlaceholderNoModelConfigured,
            answer_is_from_a_model: false,
            custody_note: CUSTODY_NOTE.to_string(),
            platform_note: "non-windows".to_string(),
        })
    }
}

/// What the owner is told about custody — on every platform, so on every CI runner.
#[cfg(test)]
mod custody_wording {
    use super::*;

    /// The note says what production waits on, and it is not a key somebody keeps.
    ///
    /// It contrasted the demonstration anchor with a secret key in an HSM kept off the machine,
    /// and said production custody of that kind "remain[ed] pending" — on screen, seven weeks
    /// after Owner decision #78 said no person holds a root. The gate that forbids that claim
    /// (`tools/check_no_owner_key_ceremony.py`) passed, because it listed the ceremony's tool
    /// names and not this wording. The phrases are assembled below rather than written out,
    /// here and in this comment: the gate now sweeps for them, and it sweeps this file too.
    #[test]
    fn the_custody_note_names_install_minted_trust_and_no_person_held_key() {
        let note = CUSTODY_NOTE.to_lowercase();
        for gone in [["offline", "-hsm"], ["offline", "-root"], ["offline", " root"]] {
            let phrase = gone.concat();
            assert!(!note.contains(&phrase), "the note still names {phrase:?}");
        }
        assert!(note.contains("minted by the install"), "{CUSTODY_NOTE}");
        assert!(note.contains("demonstration_custody"), "{CUSTODY_NOTE}");
        assert!(note.contains("independent audit"), "{CUSTODY_NOTE}");
        assert!(note.contains("no person holds"), "{CUSTODY_NOTE}");
        // And what it always said, which stays true.
        assert!(note.contains("demonstration anchor"), "{CUSTODY_NOTE}");
        assert!(note.contains("fail-closed"), "{CUSTODY_NOTE}");
    }

    /// The note the command returns is that constant, on the platform this runs on.
    #[test]
    fn the_command_returns_the_custody_note_and_demonstration_custody() {
        // Off Windows the kit is not compiled and the command reports that; on Windows it runs
        // the real chain. Either way the custody fields are the same two facts — and an error is
        // a failure here, not a reason to assert nothing.
        let result = governed_trust_selftest().expect("the self-test command must answer");
        assert_eq!(result.custody_note, CUSTODY_NOTE);
        assert!(result.demonstration_custody, "this command never proves production trust");
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    #[test]
    fn model_seam_defaults_to_the_demonstration_output_and_says_so() {
        // No configured command (and CI) → the fixed demonstration bytes, so the chain still exercises
        // end-to-end without any external model dependency. The SOURCE has to travel with it: a
        // placeholder that reports itself as a model answer is how a verified receipt over a constant
        // became indistinguishable from a verified receipt over a real reply.
        let (out, src) = run_selftest_model(None);
        assert_eq!(out, SELFTEST_DEMO_OUTPUT);
        assert_eq!(src, AnswerSource::BuiltinPlaceholderNoModelConfigured);
        let (out, src) = run_selftest_model(Some("   "));
        assert_eq!(out, SELFTEST_DEMO_OUTPUT, "blank command is treated as unset");
        assert_eq!(src, AnswerSource::BuiltinPlaceholderNoModelConfigured);
    }

    #[test]
    fn a_failing_model_is_reported_as_a_failure_not_as_an_answer() {
        // The case that mattered most: a configured model that does not work. The bytes fall back,
        // and the source says the model FAILED — distinct from never having been configured.
        let (out, src) = run_selftest_model(Some("exit 1"));
        assert_eq!(out, SELFTEST_DEMO_OUTPUT);
        assert_eq!(src, AnswerSource::BuiltinPlaceholderModelFailed);
    }

    #[test]
    fn model_seam_uses_a_configured_command_stdout() {
        // A configured command's stdout is exactly what the chain will bind + verify — proving a real model
        // CLI can be plugged in. `echo` is a cmd.exe builtin, so this needs no external tool.
        let (out, src) = run_selftest_model(Some("echo governed-ok"));
        let text = String::from_utf8_lossy(&out);
        assert!(text.contains("governed-ok"), "the configured command's stdout is the reply: {text:?}");
        assert_ne!(out, SELFTEST_DEMO_OUTPUT, "a working command must not fall back to the demo bytes");
        assert_eq!(src, AnswerSource::Model);
    }
}
