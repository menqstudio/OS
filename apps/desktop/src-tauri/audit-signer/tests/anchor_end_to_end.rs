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
    anchor_dir: PathBuf,
    /// The app-side store as it was before the case ran, so a case that mutates it (they all
    /// do) cannot poison the next one or the next RUN. Restored by `Drop`.
    snapshot: PathBuf,
    work: PathBuf,
    pipe: String,
    key_id: String,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        // The anchor is sealed and nothing here could restore it if a case had damaged it — but
        // nothing can damage it either, which is the point. What DOES need restoring is the
        // app-side half: every case below rewrites the registry, deletes private halves, or
        // both, and the fixture is shared and permanent.
        let _ = std::fs::remove_dir_all(&self.trust_dir);
        copy_tree(&self.snapshot, &self.trust_dir).expect("restore the app-side trust store");
    }
}

fn copy_tree(from: &Path, to: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(to)?;
    for entry in std::fs::read_dir(from)? {
        let entry = entry?;
        let target = to.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

/// The ONE permanent fixture this suite has, and the reason it is permanent.
///
/// `brops_provision::provision` seals the anchor: a PROTECTED DACL whose OWNER RIGHTS ACE
/// leaves the creating account read and execute and nothing else. That is **one-way for the
/// account that applies it** — after it, this account cannot write the directory, delete what
/// is inside it, rewrite its permissions, or remove it. It is the property under test, so it
/// cannot be softened for the convenience of a test that wants to clean up.
///
/// It also cannot live in a temporary directory. `anchor::precheck_location` refuses one, and
/// correctly: `%TEMP%` can be opened for `DELETE` by this account, so a sealed anchor beneath
/// it can be renamed aside in one call and the whole path rebuilt with a pin of this account's
/// choosing. That is not a hypothesis — it is what the first construction for this round did.
///
/// So the suite uses ONE anchor, at a fixed path under `%ProgramData%`, created the first time
/// this suite is ever run on a machine and reused by every case and every run afterwards
/// (`provision` is idempotent: a second call VERIFIES). It is deliberately not
/// `%ProgramData%\BroPS`, so it can never be confused with a real installation.
///
/// **Removing it needs an administrator**, and that is stated here rather than discovered:
///
/// ```text
/// takeown /f "%ProgramData%\BroPS-o2-anchor" /r /d y
/// icacls  "%ProgramData%\BroPS-o2-anchor" /reset /t
/// rmdir /s /q "%ProgramData%\BroPS-o2-anchor"
/// ```
fn fixture_machine_root() -> PathBuf {
    PathBuf::from(std::env::var_os("ProgramData").expect("%ProgramData%"))
        .join("BroPS-o2-anchor")
}

/// The app-side half, also fixed: the manifest inside the sealed anchor records the absolute
/// path of the store it is the anchor FOR, so the pair has to be stable together.
fn fixture_app_data() -> PathBuf {
    PathBuf::from(std::env::var_os("LOCALAPPDATA").expect("%LOCALAPPDATA%"))
        .join("BroPS-o2-anchor")
}

fn stand_up(tag: &str) -> Fixture {
    let temp = tempfile::tempdir().expect("temp dir");
    let app_data = fixture_app_data();
    let machine_root = fixture_machine_root();
    let signer_dir = app_data.join("signer");
    let work = temp.path().join("work");
    std::fs::create_dir_all(&app_data).unwrap();
    std::fs::create_dir_all(&work).unwrap();

    // THE ORDER HERE IS THE PRODUCTION ORDER, and it has to be. The signer mints its seed
    // first, under its own account; only then does the app provision, admitting the published
    // PUBLIC half while the registry is being signed. There is no later step: `mint` destroys
    // the operator root before it returns, so the registry is sealed from that moment and no
    // key can be added to it afterwards by anybody — including this fixture.
    //
    // The service's own account, as far as this unelevated session can get: the key is minted by
    // THIS process, in a directory of its own, exactly as the service would on first start.
    let me = spec::winimpl::current_user_sid().expect("own SID");
    let held = custody::load_or_mint(&signer_dir, &me).expect("mint the anchor key");
    let key_id = held.key_id.clone();

    // The seed never leaves the service: what provisioning is handed is the published record.
    let published = custody::read_custody(&signer_dir).expect("custody record");
    let provisioned = brops_provision::provision_with_anchor(
        &app_data,
        &machine_root,
        Some(&published),
    )
    .unwrap_or_else(|e| {
        panic!(
            "provisioning the shared O-2 fixture failed: {e}
             The anchor at {} is SEALED and this account cannot remove it — that is the              property, not a bug. If the app-side half at {} was deleted or its layout              changed, the pair can only be cleared by an administrator:
                takeown /f \"{}\" /r /d y
                icacls  \"{}\" /reset /t
                rmdir /s /q \"{}\"",
            machine_root.display(),
            app_data.display(),
            machine_root.display(),
            machine_root.display(),
            machine_root.display(),
        )
    });

    // `register_anchor_key` can no longer register anything; it CONFIRMS. Running it here
    // proves the confirmation agrees with what provisioning actually wrote.
    let confirmed =
        register::register_anchor_key(&provisioned.anchor_dir, &published).expect("confirm");
    assert_eq!(confirmed, key_id);

    // The store must verify through the SAME code a later launch runs — and that code now
    // begins by asking the OPERATING SYSTEM whether this account can rewrite the anchor. A
    // fixture that could would fail here, before any case ran.
    let verified = brops_provision::verify_existing(&provisioned.trust_dir, &provisioned.anchor_dir)
        .expect("the provisioned trust store must verify");
    let proof = verified.custody.expect("verify_existing always measures custody");
    println!("--- anchor custody, measured on this run ---\n{proof}");
    assert!(
        proof.refusals.len() >= 4,
        "the custody proof ran no write probes at all: {proof}"
    );

    // Snapshot the app-side half. The anchor cannot be damaged by anything below; the app-side
    // store can, and it is permanent, so it is put back by `Fixture::drop`.
    let snapshot = temp.path().join("trust-snapshot");
    copy_tree(&provisioned.trust_dir, &snapshot).expect("snapshot the app-side trust store");

    let state_path = signer_dir.join(spec::STATE_FILE_NAME);
    let core = AnchorCore::new(held, &me, &me, &state_path).expect("core");

    let pipe = format!("brops-anchor-{tag}-{}", std::process::id());
    let leaked: &'static AnchorCore = Box::leak(Box::new(core));
    let served = pipe.clone();
    let peer = me.clone();
    std::thread::spawn(move || brops_audit_signer::win::serve(&served, &peer, leaked));

    Fixture {
        _temp: temp,
        trust_dir: provisioned.trust_dir,
        anchor_dir: provisioned.anchor_dir,
        snapshot,
        work,
        pipe,
        key_id,
    }
}

/// `register_anchor_key` is a CONFIRMATION now, and a confirmation that only checked the key id
/// would report success for a key `bro_audit_log` is going to refuse.
///
/// Each of these guards was found untested by mutation: breaking the authority check and breaking
/// the public-key check both left the suite green, because every other test presents a custody
/// record that agrees with the registry in every field. They are exercised here directly.
#[test]
fn confirming_the_anchor_key_checks_more_than_the_key_id() {
    let temp = tempfile::tempdir().expect("temp dir");
    let app_data = temp.path().join("app");
    let signer_dir = temp.path().join("signer");
    std::fs::create_dir_all(&app_data).unwrap();

    let me = spec::winimpl::current_user_sid().expect("own SID");
    custody::load_or_mint(&signer_dir, &me).expect("mint the anchor key");
    let published = custody::read_custody(&signer_dir).expect("custody record");
    // The UNSEALED entry point: this test is about `register_anchor_key`'s field checks, it
    // rewrites the registry to reach one of them, and sealing an anchor for it would leave a
    // permanent directory on the machine for no proof it does not already have.
    let provisioned = brops_provision::mint_store_without_custody_proof(
        &app_data,
        &app_data.join("anchor"),
        Some(&published),
    )
    .expect("provisioning");
    let trust = &provisioned.anchor_dir;

    // The honest positive first, so every refusal below is about the field it varies.
    register::register_anchor_key(trust, &published).expect("the genuine record confirms");

    // A record naming the right id against a DIFFERENT public half. The registry entry is
    // untouched and real; what is wrong is that the signer this record describes is not the
    // signer the registry trusts, so its anchors would not verify.
    let mut wrong_key = published.clone();
    wrong_key["public_key"] = serde_json::json!("cd".repeat(32));
    let err = register::register_anchor_key(trust, &wrong_key)
        .expect_err("a record whose public half disagrees with the registry must be refused");
    assert!(err.to_string().contains("DIFFERENT public key"), "{err}");

    // A record claiming an authority its own publisher did not: refused before anything is
    // looked up, so a custody file that had been edited cannot borrow the anchor's standing.
    let mut wrong_authority = published.clone();
    wrong_authority["authority"] = serde_json::json!("operator-root");
    let err = register::register_anchor_key(trust, &wrong_authority)
        .expect_err("a record claiming another authority must be refused");
    assert!(err.to_string().contains("does not claim the audit-anchor authority"), "{err}");

    // And the registry naming the key under an authority that cannot anchor. Reached by
    // rewriting the registry entry — which no longer verifies, but this function's job is to
    // answer "is the anchor resolvable", and a yes here for a non-anchor authority would be a
    // green light for a ledger `bro_audit_log` will refuse.
    let registry_path = trust
        .join(brops_provision::REGISTRY_ROOT_DIR)
        .join("config")
        .join("trusted-keys.json");
    let mut document: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&registry_path).unwrap()).unwrap();
    for entry in document["payload"]["keys"].as_array_mut().unwrap() {
        if entry["key_id"] == published["key_id"] {
            entry["authority_type"] = serde_json::json!("evidence-recorder");
        }
    }
    std::fs::write(&registry_path, serde_json::to_vec(&document).unwrap()).unwrap();
    let err = register::register_anchor_key(trust, &published)
        .expect_err("a key registered under a non-anchor authority must be refused");
    assert!(err.to_string().contains("an authority that cannot anchor"), "{err}");

    // A store whose registry never carried the key at all: refused, naming the remedy rather
    // than quietly amending — there is no key left that could amend it.
    let bare = temp.path().join("bare");
    std::fs::create_dir_all(&bare).unwrap();
    let bare_store =
        brops_provision::mint_store_without_custody_proof(&bare, &bare.join("anchor"), None)
            .expect("provisioning without an anchor");
    let err = register::register_anchor_key(&bare_store.anchor_dir, &published)
        .expect_err("a store with no anchor key must be refused");
    let text = err.to_string();
    assert!(text.contains("does not carry the audit signer's key"), "{text}");
    assert!(text.contains("cannot be amended"), "{text}");
    assert!(text.contains("BEFORE the app's first launch"), "{text}");
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
        .arg(&fixture.anchor_dir)
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

/// **The inverse of the test this replaces.**
///
/// `the_operator_root_the_app_still_holds_can_register_its_own_anchor_key` asserted a defect that
/// was open: `provision()` left the `operator-root` private half in the app's own trust directory,
/// that key is what the trusted-key registry is *signed with*, and the app could therefore mint an
/// `audit-anchor` keypair of its own, admit it, re-sign the registry, raise the anti-rollback
/// floor it also owns, and anchor any head it liked. Its own doc said it should go RED "the day
/// the app stops holding the operator root". That day is this change: `brops_provision::mint`
/// generates the root in memory, signs the registry and the conductor session with it, and drops
/// it before returning.
///
/// So the case asserts the closure, run rather than argued, exactly the way its predecessor ran
/// the attack:
///
/// * the app's whole data directory is enumerated on the FILESYSTEM and every 32-byte window and
///   64-character hex run in every file is tried as an Ed25519 seed — the operator root's private
///   half is nowhere, and the same search finds every key that IS there, so a null result is not
///   the search being broken;
/// * the attack is then attempted anyway with each private half the app DOES hold: re-sign the
///   registry, add a rogue `audit-anchor` key, raise the floor, fix the manifest. The real
///   `bro_signature.load_trusted_keys` must refuse every one of them at the external pin;
/// * and the positive control still passes in the same run.
#[test]
fn the_registry_can_no_longer_be_re_signed_because_the_root_no_longer_exists() {
    let fixture = stand_up("residual");
    let (success, stdout, stderr) = run_case(&fixture, "registry-resign");
    assert!(success, "the registry-resign case did not complete:\n{stdout}\n{stderr}");
    assert!(
        stdout.contains("O2-RESIDUAL-GONE"),
        "re-signing the registry still buys an accepted anchor. If provision() has started \
         leaving an operator-root private half in the app's trust directory again, the whole \
         round is undone:\n{stdout}"
    );
    assert!(
        !stdout.contains("O2-RESIDUAL-OPERATOR-ROOT"),
        "the old defect marker came back:\n{stdout}"
    );
}

/// **The inverse of the test this replaces**, and the one that decides whether O-2 is closed.
///
/// `rewriting_the_operator_pin_still_installs_a_root_of_the_apps_own_choosing` asserted a
/// defect that was open, and its own doc said what would make it go RED: "the day the operator
/// pin (or the anchor key\'s identity) lives somewhere the app\'s account cannot write". That
/// day is this change. The pin, the anti-rollback floor and the provisioning manifest moved out
/// of `<app_data>/trust/pin/` into `brops_provision::anchor`, a directory sealed with a
/// PROTECTED DACL whose OWNER RIGHTS (S-1-3-4) entry replaces the owner\'s implicit
/// `READ_CONTROL | WRITE_DAC` with read and execute — no elevation, no service account, no
/// second login identity, and every ancestor of it proved undeletable by the same account.
///
/// The predecessor ran the attack rather than arguing it, and so does this. The Python case
/// attempts **the same attack, step for step** — delete every private half, generate an
/// operator root of its own, write it over the pin, re-sign the registry under it with a rogue
/// `audit-anchor` key, raise the floor — and asserts two different things about it:
///
/// 1. **the operating system refuses the writes.** Not "provisioning refuses", not "the engine
///    refuses": `open(pin, "w")`, `os.remove(pin)`, creating a new file in the anchor
///    directory, renaming the anchor directory, and renaming its parent all come back
///    `PermissionError`, and the pin\'s bytes are read back afterwards and are unchanged. A
///    refusal by intent would be a refusal some future edit could remove; this one is the
///    kernel\'s.
/// 2. **and the forgery fails anyway.** The attack is then carried as far as it can go —
///    the registry IS app-writable, so it really is re-signed under the rogue root, and a
///    rogue anchor is really installed over the truncated ledger — and the REAL
///    `bro_signature.load_trusted_keys` refuses the re-signed registry against the untouched
///    pin, the REAL `bro_audit_log.verify()` refuses the forged head, and the positive control
///    still passes in the same run so "refused" cannot mean "everything is refused now".
///
/// The second assertion is what makes the first worth having, and vice versa. Either alone is
/// the failure mode this item keeps landing in: a boundary nobody tried to cross, or a check
/// that fires for a reason unrelated to the boundary.
///
/// It also proves the acknowledgement is gone. `anchor_end_to_end.py` **unsets**
/// `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` before importing anything, so `bro_custody` runs its
/// full rule rather than short-circuiting it, and the engine accepts this pin on its merits.
/// The same script asserts that the OLD location — a pin in the app\'s own data directory — is
/// refused by that same unacknowledged rule, so the acceptance is about custody and not about
/// the check having been disabled.
#[test]
fn rewriting_the_operator_pin_is_refused_by_the_operating_system_and_the_forgery_fails() {
    let fixture = stand_up("pinroute");
    let (success, stdout, stderr) = run_case(&fixture, "pin-rewrite");
    assert!(success, "the pin-rewrite case did not complete:\n{stdout}\n{stderr}");
    assert!(
        stdout.contains("O2-PIN-CUSTODY-CLOSED"),
        "the pin-rewrite attack was not refused end to end:\n{stdout}"
    );
    assert!(
        stdout.contains("PermissionError"),
        "nothing was refused BY THE OPERATING SYSTEM — the case cannot have attempted the \
         write, and a pass here would be about the attack not being tried:\n{stdout}"
    );
    assert!(
        !stdout.contains("O2-RESIDUAL-PIN-REWRITE"),
        "the old defect marker came back: the app installed a trust root of its own and \
         anchored a truncation under it:\n{stdout}"
    );
    assert!(stdout.contains("GREEN:"), "no green run reported:\n{stdout}");
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
