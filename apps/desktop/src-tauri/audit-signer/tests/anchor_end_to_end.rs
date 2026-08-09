//! The proof that decides whether this is finished: the REAL `bro_audit_log`, accepting an anchor
//! that came through the REAL relay shim, the REAL named pipe and the REAL signer core.
//!
//! A Rust test asserting that Rust's own document round-trips would be checking the encoder
//! against itself. `provision/tests/python_verifier.rs` already established the shape of the
//! honest version for the registry; this is the same shape for the anchor.
//!
//! # It does not skip on a missing Python
//!
//! No interpreter, no `cryptography`, no engine tree — each of those FAILS with the reason named.
//! A drift proof that disables itself on the machine where the drift happened is not a proof.
//!
//! # What IS substituted, stated plainly
//!
//! Exactly one fact: the process serving the pipe is not really running under
//! `NT SERVICE\BroPSAuditSigner`. Registering a service needs `SC_MANAGER_CREATE_SERVICE`, which
//! the SCM refuses to an unelevated token by design, so this session cannot create the second
//! account at all. The test therefore builds `AnchorCore` with `expected_principal == running_as
//! == this test's own SID` and says so here rather than implying a separation it did not
//! demonstrate.
//!
//! Everything else is real: the relay is the compiled `brops-anchor-relay.exe` invoked by Python's
//! own `subprocess.run` through `BRO_AUDIT_ANCHOR_SIGNER`; the transport is
//! `brops_win_live::pipe`'s restrictive-DACL, peer-authenticated named pipe; the signature is
//! `audit_signer::sign_anchor` over `canonical_bytes`; the acceptance is
//! `bro_audit_log.verify(keys=…)` resolving the key through `bro_signature.load_trusted_keys`.
//!
//! And the *guard* on that substituted fact is proved separately and for real, by
//! [`the_real_service_binary_refuses_to_run_as_this_account`]: the shipped binary computes the
//! identity from its own token and exits before touching a key. There is no flag or variable that
//! could have supplied it.

#![cfg(windows)]

use std::path::{Path, PathBuf};
use std::process::Command;

use brops_audit_signer::{custody, register, AnchorCore};
use brops_provision::audit_signer as spec;

/// `<repo>/apps/desktop/src-tauri/audit-signer` -> `<repo>`.
fn repo_root() -> PathBuf {
    let mut path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for _ in 0..4 {
        path = path.parent().expect("CARGO_MANIFEST_DIR is four levels below the repo root").to_path_buf();
    }
    path
}

fn resolve_python() -> String {
    let mut candidates = Vec::new();
    if let Ok(explicit) = std::env::var("BROPS_TEST_PYTHON") {
        if !explicit.trim().is_empty() {
            candidates.push(explicit);
        }
    }
    candidates.extend(["python3".to_string(), "python".to_string()]);
    let mut reasons = Vec::new();
    for candidate in candidates {
        match Command::new(&candidate)
            .args(["-c", "import cryptography, sys; print(sys.version)"])
            .output()
        {
            Ok(out) if out.status.success() => return candidate,
            Ok(out) => reasons.push(format!(
                "`{candidate}` cannot import `cryptography`, which bro_signature requires: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            )),
            Err(e) => reasons.push(format!("could not run `{candidate}`: {e}")),
        }
    }
    panic!(
        "no usable Python for the audit-anchor cross-language proof. This test does NOT skip: \
         without it, nothing checks that the anchor this Rust signer produces is one the engine \
         module that has to install it will accept. Set BROPS_TEST_PYTHON.\n  {}",
        reasons.join("\n  ")
    );
}

/// A provisioned trust store, a minted signer key registered into it, and a live server.
struct Fixture {
    _temp: tempfile::TempDir,
    trust_dir: PathBuf,
    work: PathBuf,
    pipe: String,
    key_id: String,
}

fn stand_up(tag: &str) -> Fixture {
    let temp = tempfile::tempdir().expect("temp dir");
    let app_data = temp.path().join("app");
    let signer_dir = temp.path().join("signer");
    let work = temp.path().join("work");
    std::fs::create_dir_all(&app_data).unwrap();
    std::fs::create_dir_all(&work).unwrap();

    let provisioned = brops_provision::provision(&app_data).expect("provisioning");

    // The service's own account, as far as this unelevated session can get: the key is minted by
    // THIS process, in a directory of its own, exactly as the service would on first start.
    let me = spec::winimpl::current_user_sid().expect("own SID");
    let held = custody::load_or_mint(&signer_dir, &me).expect("mint the anchor key");
    assert!(held.freshly_minted, "the fixture must mint, not inherit, its key");
    let key_id = held.key_id.clone();

    // The seed never leaves the service: what provisioning is handed is the published record.
    let published = custody::read_custody(&signer_dir).expect("custody record");
    let registered =
        register::register_anchor_key(&provisioned.trust_dir, &published).expect("register");
    assert_eq!(registered, key_id);

    // The store must still verify after the amendment, through the SAME code a later launch runs.
    brops_provision::verify_existing(&provisioned.trust_dir)
        .expect("the amended trust store must still verify");

    let state_path = signer_dir.join(spec::STATE_FILE_NAME);
    let core = AnchorCore::new(held, &me, &me, &state_path).expect("core");

    let pipe = format!("brops-anchor-{tag}-{}", std::process::id());
    let leaked: &'static AnchorCore = Box::leak(Box::new(core));
    let served = pipe.clone();
    let peer = me.clone();
    std::thread::spawn(move || brops_audit_signer::win::serve(&served, &peer, leaked));

    Fixture { _temp: temp, trust_dir: provisioned.trust_dir, work, pipe, key_id }
}

fn run_case(fixture: &Fixture, case: &str) -> (bool, String, String) {
    let python = resolve_python();
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("anchor_end_to_end.py");
    let engine = repo_root().join("engine");
    assert!(
        engine.join("runtime").join("bro_audit_log.py").is_file(),
        "no engine tree at {} — the cross-language proof has nothing to verify against",
        engine.display()
    );
    let output = Command::new(&python)
        .arg("-B")
        .arg(&script)
        .arg(case)
        .arg(&fixture.trust_dir)
        .arg(&engine)
        .arg(&fixture.work)
        .arg(env!("CARGO_BIN_EXE_brops-anchor-relay"))
        .arg(&fixture.pipe)
        .arg(&fixture.key_id)
        // The Rust mirror of `bro_audit_log.ANCHOR_AUTHORITIES`, so the Python side can
        // fail on drift instead of two hardcoded lists quietly disagreeing.
        .arg(spec::ANCHOR_AUTHORITIES.join(","))
        .output()
        .unwrap_or_else(|e| panic!("could not run `{python} {}`: {e}", script.display()));
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    println!("--- {case} stdout ---\n{stdout}");
    if !stderr.trim().is_empty() {
        println!("--- {case} stderr ---\n{stderr}");
    }
    (output.status.success(), stdout, stderr)
}

// =================================================================================================
// The positive
// =================================================================================================

#[test]
fn the_real_bro_audit_log_accepts_an_anchor_produced_through_the_real_path() {
    let fixture = stand_up("positive");
    let (success, stdout, stderr) = run_case(&fixture, "positive");
    assert!(
        success,
        "the real bro_audit_log REFUSED an anchor produced by the real relay + pipe + \
         signer.\n{stdout}\n{stderr}"
    );
    assert!(stdout.contains("GREEN:"), "no green run reported:\n{stdout}");
    assert!(
        stdout.contains("verify(keys=...) returned 3"),
        "the keyed verify() — the authoritative one, which REQUIRES the anchor — did not run:\n{stdout}"
    );
}

// =================================================================================================
// The negatives
// =================================================================================================

#[test]
fn an_append_with_no_signer_service_fails_closed_inside_the_engines_budget() {
    // A pipe name nobody is serving. The shim must refuse in time for the engine to report it,
    // rather than be killed at the 10-second timeout while the ledger's append lock is held.
    let mut fixture = stand_up("unreachable");
    fixture.pipe = format!("brops-anchor-nobody-{}", std::process::id());
    let (success, stdout, stderr) = run_case(&fixture, "unreachable");
    assert!(success, "the fail-closed path did not behave:\n{stdout}\n{stderr}");
    assert!(stdout.contains("GREEN:"), "no green run reported:\n{stdout}");
}

#[test]
fn the_second_principal_refuses_to_bless_a_truncation_its_client_asks_for() {
    let fixture = stand_up("rollback");
    let (success, stdout, stderr) = run_case(&fixture, "rollback");
    assert!(
        success,
        "the signer did NOT refuse an anchor over a truncated chain — the anti-rollback \
         property the engine delegates to the signer is not there:\n{stdout}\n{stderr}"
    );
    assert!(stdout.contains("ANTI-ROLLBACK"), "the refusal did not name the reason:\n{stdout}");
}

/// The guard on the one fact the fixture substitutes.
///
/// The shipped service binary derives its identity from its own process token and compares it with
/// the SID derived from the service name. Run by this account it must refuse — **before** the key
/// file is opened, so "point `BRO_AUDIT_ANCHOR_SIGNER` at the service exe" produces nothing at all
/// rather than a key owned by the wrong account.
#[test]
fn the_real_service_binary_refuses_to_run_as_this_account() {
    let temp = tempfile::tempdir().expect("temp dir");
    let dir = temp.path().join("signer");
    std::fs::create_dir_all(&dir).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_brops-audit-signer"))
        .arg(&dir)
        .output()
        .expect("run the service binary");
    let stderr = String::from_utf8_lossy(&output.stderr);
    println!("{stderr}");
    assert_eq!(
        output.status.code(),
        Some(8),
        "the service binary did not refuse to run as this account:\n{stderr}"
    );
    assert!(
        stderr.contains("Refusing to use the anchor key")
            || stderr.contains("not as NT SERVICE")
            || stderr.contains("refusing BEFORE the key file is opened"),
        "the refusal does not say why:\n{stderr}"
    );
    assert!(
        !dir.join(spec::KEY_FILE_NAME).exists(),
        "the service minted a key while refusing to serve — a key file owned by the account that \
         writes the ledger is exactly what must never come to exist"
    );
}

/// The negative that decides whether any of this bought anything — **its inverse**.
///
/// This replaces `an_anchor_signed_by_the_apps_own_account_is_still_accepted_so_o2_is_not_closed`,
/// which asserted the defect: while `ANCHOR_AUTHORITIES` was `("evidence-recorder",
/// "operator-root")`, `provision()` wrote both of those private halves into the app's own trust
/// directory and the app could truncate the ledger and re-anchor it. The authority narrowed to
/// `audit-anchor`, a type this crate never mints, so the Python side stopped printing `O2-OPEN`
/// and that test went RED. What replaces it asserts the closure directly and in both directions:
///
/// * the app's trust store is enumerated on the FILESYSTEM and must contain no anchor-capable
///   private half (not "the code that writes it looks right");
/// * every private half it does hold is used to sign a self-consistent truncated head, and the
///   real `bro_audit_log.verify()` must refuse each one *naming the authority* — a refusal for
///   the chain would mean the forgery was merely clumsy;
/// * and the positive control still passes in the same run, so "refused" cannot be "everything
///   is refused now".
#[test]
fn an_anchor_signed_by_any_key_the_app_holds_is_refused_by_the_real_verifier() {
    let fixture = stand_up("forgery");
    let (success, stdout, stderr) = run_case(&fixture, "forgery");
    assert!(
        success,
        "a key out of the app's own trust store still anchored a truncated ledger, or the \
         positive control stopped working:\n{stdout}\n{stderr}"
    );
    assert!(stdout.contains("GREEN:"), "no green run reported:\n{stdout}");
    assert!(
        stdout.contains("may not sign audit-head"),
        "nothing was actually refused BY AUTHORITY — the run cannot have exercised the \
         narrowing:\n{stdout}"
    );
    assert!(
        !stdout.contains("O2-OPEN"),
        "the old defect marker came back:\n{stdout}"
    );
}

/// The gap that is **still open**, asserted rather than left to a comment.
///
/// Narrowing `ANCHOR_AUTHORITIES` closed the direct route. It does not close the indirect one:
/// `provision()` leaves the `operator-root` private half in the app's own trust directory, and
/// that key is what the trusted-key registry is *signed with*. The app can therefore mint its own
/// keypair, register it under `audit-anchor`, re-sign the registry, raise the anti-rollback floor
/// it also owns, and anchor any head it likes. The Python case does exactly that against the real
/// `bro_audit_log` and the real provisioned store.
///
/// **This test asserts a DEFECT that is open today**, for the same reason its predecessor did: a
/// tree that stays quiet about a route it knows is open is the failure this whole item exists to
/// end. It goes RED — with the Python side printing `O2-RESIDUAL-GONE` — the day the app stops
/// holding the operator root, or the day the anchor key is bound by something outside the
/// registry. Replace it with its inverse then, and not before.
///
/// It is NOT closeable inside this crate. `bro_audit_log`'s trust root is the registry; on a
/// deployment that provisions its own trust material the registry's signer is the ledger's
/// writer, and no hardcoded authority list can separate a principal from itself.
#[test]
fn the_operator_root_the_app_still_holds_can_register_its_own_anchor_key() {
    let fixture = stand_up("residual");
    let (success, stdout, stderr) = run_case(&fixture, "registry-resign");
    assert!(success, "the residual-route case did not complete:\n{stdout}\n{stderr}");
    assert!(
        stdout.contains("O2-RESIDUAL-OPERATOR-ROOT"),
        "re-signing the registry with the app's own operator root no longer produces an \
         accepted anchor. If provision() has stopped leaving the operator-root private half in \
         the app's trust directory, or the anchor key is now bound outside the registry, then \
         O-2 is closed end to end and this test must be replaced by its inverse:\n{stdout}"
    );
}

/// The elevated registration path, run for real when the session can, and **skipped with the exact
/// reason** when it cannot.
///
/// It never passes by default. An unelevated session cannot call `CreateServiceW` at all
/// (`SC_MANAGER_CREATE_SERVICE` is withheld from a standard user by design) and cannot stamp
/// `BUILTIN\Administrators` as owner (`ERROR_INVALID_OWNER`), so there is nothing here to weaken
/// into something that would run — the choice is a real run or a printed skip.
///
/// What stays UNTESTED on this machine, and is the honest gap: no `NT SERVICE\BroPSAuditSigner`
/// has ever existed here, so the strong `Separation::Separated` branch — the app's account being a
/// non-administrator that genuinely cannot open the key — has never been demonstrated live. Every
/// run of this suite has been a single account playing both parts.
#[test]
fn registration_applies_the_plan_for_real_or_says_why_it_could_not() {
    let posture = match spec::winimpl::app_token_posture() {
        Ok(p) => p,
        Err(why) => {
            println!("SKIP registration: this process's token could not be measured: {why}");
            return;
        }
    };
    if posture != spec::AppTokenPosture::ElevatedAdministrator {
        println!(
            "SKIP registration: this session is {posture:?}, not ElevatedAdministrator. \
             `sc.exe create` needs SC_MANAGER_CREATE_SERVICE, which the SCM refuses to a standard \
             user by design, and a protected root owned by BUILTIN\\Administrators cannot be \
             created by a token that may not assign that owner (ERROR_INVALID_OWNER). There is no \
             unelevated path to a second principal, so this check cannot run here — and the strong \
             Separation::Separated branch has therefore never been demonstrated on real hardware."
        );
        // The refusal itself IS testable everywhere, and is: apply() must name elevation rather
        // than fail somewhere further in.
        let paths = spec::SignerPaths::new(
            Path::new("C:\\ProgramData\\BroPS"),
            Path::new("C:\\Users\\x\\AppData\\Local\\BroPS"),
            Path::new("C:\\Program Files\\BroPS"),
        );
        match register::apply(&paths, "S-1-5-21-11-22-33-1001") {
            Err(spec::AnchorRefusal::ElevationRequired { step }) => {
                println!("  and it refused by name, before creating anything: {step}");
            }
            other => panic!(
                "an unelevated apply() must refuse with ElevationRequired and create nothing; \
                 got {other:?}"
            ),
        }
        return;
    }

    let temp = tempfile::tempdir().expect("temp dir");
    let paths = spec::SignerPaths::new(
        temp.path(),
        &temp.path().join("appdata"),
        Path::new(env!("CARGO_BIN_EXE_brops-audit-signer")).parent().unwrap(),
    );
    let app_sid = spec::winimpl::current_user_sid().expect("own SID");
    let proof = register::apply(&paths, &app_sid).expect("elevated registration");
    println!("registration read-back: {}", proof.summary());
    assert_eq!(proof.observed_mask & proof.forbidden_mask, 0);
}
