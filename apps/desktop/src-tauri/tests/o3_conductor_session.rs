//! O-3, end to end and in both directions, across the language boundary.
//!
//! `provision/tests/python_verifier.rs` proves the bytes: the real `bro_signature` accepts
//! what the Rust installer signs. It could not prove that the ENGINE ever sees them,
//! because nothing exported the environment that decides which registry the engine reads —
//! so its O-3 section had to copy `trusted-keys.json` into a staged root and verify against
//! that, which is exactly the gap ("the registry has to BE at the engine root for the
//! engine to see it") rather than its closure.
//!
//! This test removes the staging. It mints a real trust store, runs the REAL precedence
//! resolver the application runs (`brops_lib::engine_trust::resolve` — the one
//! `ai::governed_sidecar_call` calls before every engine spawn), puts exactly what it
//! returns on a real Python child, and has `bro_policy.verify_conductor_session_token`
//! judge the installer-minted `conductor-session` with `root` = the engine's own tree.
//! Then it takes the redirect away and points it at a second, equally valid install, and
//! requires a refusal both times.
//!
//! **It does not skip.** No Python, no `cryptography`, no engine tree — each of those fails
//! the test with the reason named, for the reason `python_verifier.rs` states: a proof that
//! disables itself on the machine where the drift happened is not a proof.

use std::path::{Path, PathBuf};
use std::process::Command;

/// The repository root: `<repo>/apps/desktop/src-tauri`.
fn repo_root() -> PathBuf {
    let mut path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for _ in 0..3 {
        path = path
            .parent()
            .unwrap_or_else(|| panic!("CARGO_MANIFEST_DIR is not three levels below the repo root"))
            .to_path_buf();
    }
    path
}

fn probe(python: &str) -> Result<(), String> {
    let out = Command::new(python)
        .args(["-c", "import cryptography, sys; print(sys.version)"])
        .output()
        .map_err(|e| format!("could not run `{python}`: {e}"))?;
    if out.status.success() {
        Ok(())
    } else {
        Err(format!(
            "`{python}` cannot import `cryptography`, which `bro_signature` requires: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ))
    }
}

fn resolve_python() -> String {
    let mut candidates = Vec::new();
    if let Ok(explicit) = std::env::var("BROPS_TEST_PYTHON") {
        if !explicit.trim().is_empty() {
            candidates.push(explicit);
        }
    }
    if candidates.is_empty() {
        candidates = vec!["python3".to_string(), "python".to_string()];
    }
    let mut reasons = Vec::new();
    for candidate in candidates {
        match probe(&candidate) {
            Ok(()) => return candidate,
            Err(reason) => reasons.push(reason),
        }
    }
    panic!(
        "no usable Python for the O-3 cross-language proof. This test does NOT skip: without \
         it, nothing checks that the environment this application exports is the environment \
         that makes the engine read the provisioned registry. Set BROPS_TEST_PYTHON to an \
         interpreter with `cryptography` installed.\n  {}",
        reasons.join("\n  ")
    );
}

/// Give Python a path free of platform surprises — the same reasoning, and the same
/// platform split, as `provision/tests/python_verifier.rs::python_safe`.
fn python_safe(path: &Path) -> PathBuf {
    #[cfg(not(windows))]
    {
        std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
    }
    #[cfg(windows)]
    {
        path.to_path_buf()
    }
}

/// Mint an UNSEALED store under `dir` and return it. Unsealed because the seal is one-way
/// for the account that applies it; what this test is about is the wiring, and custody has
/// its own proofs (`anchor_custody.rs`, `audit-signer/tests/anchor_end_to_end.py`).
fn mint(dir: &Path) -> brops_provision::Provisioned {
    let data = python_safe(dir);
    std::fs::create_dir_all(&data).expect("data dir");
    brops_provision::mint_store_without_custody_proof(&data, &data.join("anchor"), None)
        .expect("provisioning")
}

#[test]
fn the_exported_environment_closes_o3_against_the_real_engine_and_nothing_else_does() {
    let python = resolve_python();
    let repo = repo_root();
    let engine = repo.join("engine");
    assert!(
        engine.join("runtime").join("bro_policy.py").is_file(),
        "no engine tree at {} — this proof has nothing to verify against",
        engine.display()
    );

    let this_install = tempfile::tempdir().expect("temp dir");
    let another_install = tempfile::tempdir().expect("temp dir");
    let provisioned = mint(this_install.path());
    // A second, equally valid deployment: operator-signed, production, current, and not
    // this one. "Some registry accepted it" is not "this deployment accepted it".
    let elsewhere = mint(another_install.path());

    // THE THING UNDER TEST. Not a list assembled here — the application's own resolver,
    // against an ambient environment with none of these set, which is what a desktop
    // launch looks like. If `Provisioned::engine_env()` stops returning
    // `BRO_TRUSTED_REGISTRY_ROOT`, or the resolver drops a member, the Python side goes red.
    let exported = brops_lib::engine_trust::resolve(
        &provisioned.engine_env(),
        &provisioned.operator_public_key,
        &|_| None,
    )
    .expect("a clean ambient environment must yield the whole provisioned set");
    assert!(
        exported.iter().any(|(name, _)| *name == "BRO_TRUSTED_REGISTRY_ROOT"),
        "the variable O-3 turns on is not in what the application exports: {exported:?}"
    );

    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("o3_conductor_session.py");
    let mut command = Command::new(&python);
    command.arg("-B").arg(&script).arg(engine.as_os_str()).arg(elsewhere.registry_root.as_os_str());
    // Nothing but what the application would set. In particular the harness does NOT set
    // BRO_OPERATOR_ROOT_PIN_SELF_OWNED here — the script asserts its absence first and then
    // sets it for itself, because the store under test is unsealed. See the script's header.
    for name in [
        "BRO_TRUSTED_REGISTRY_ROOT",
        "BRO_OPERATOR_ROOT_PUBKEY_FILE",
        "BRO_OPERATOR_REGISTRY_MIN_FILE",
        "BRO_CONDUCTOR_SESSION_TOKEN",
        "BRO_SESSION_ID",
        "BRO_OPERATOR_ROOT_PIN_SELF_OWNED",
        "BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE",
        "BRO_OPERATOR_ROOT_PUBKEY",
        "BRO_OPERATOR_REGISTRY_MIN",
        "BRO_ENV",
    ] {
        command.env_remove(name);
    }
    for (name, value) in &exported {
        command.env(name, value);
    }
    let output = command
        .output()
        .unwrap_or_else(|e| panic!("could not run `{python} {}`: {e}", script.display()));

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    println!("{stdout}");
    assert!(
        output.status.success(),
        "O-3 did not close on the environment the application exports.\n--- stdout ---\n\
         {stdout}\n--- stderr ---\n{stderr}"
    );
    assert!(stdout.contains("GREEN:"), "the proof did not report a green run:\n{stdout}");
}
