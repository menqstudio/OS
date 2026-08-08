//! The cross-language proof: the REAL Python verifiers judging REAL Rust output.
//!
//! `provision.rs` proves this crate behaves; it cannot prove that what it writes is
//! byte-compatible with `engine/runtime/bro_signature.py`, because a Rust test that
//! asserts Rust's own encoding round-trips is checking the encoder against itself.
//! This test provisions a real trust store, mints a real `evidence-floor-anchor` with
//! the real operator key, and hands the directory to `verify_provisioning.py`, which
//! imports the engine's own `bro_signature`, `bro_policy` and `bro_deploy_preflight`
//! and makes them accept or refuse it. One byte of divergence in key ordering,
//! separators, string escaping or integer formatting is an Ed25519 signature that does
//! not verify, and this test goes red.
//!
//! **It does not skip.** No Python, no `cryptography`, no engine tree — all of those
//! fail the test with the reason named. A drift proof that quietly disables itself on
//! the machine where the drift happened is not a proof.

use std::path::{Path, PathBuf};
use std::process::Command;

/// The repository root: `<repo>/apps/desktop/src-tauri/provision`.
fn repo_root() -> PathBuf {
    let mut path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for _ in 0..4 {
        path = path
            .parent()
            .unwrap_or_else(|| panic!("CARGO_MANIFEST_DIR is not four levels below the repo root"))
            .to_path_buf();
    }
    path
}

/// The interpreter to use. `BROPS_TEST_PYTHON` wins so a CI job can name a venv.
fn python_candidates() -> Vec<String> {
    if let Ok(explicit) = std::env::var("BROPS_TEST_PYTHON") {
        if !explicit.trim().is_empty() {
            return vec![explicit];
        }
    }
    vec!["python3".to_string(), "python".to_string()]
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
    let mut reasons = Vec::new();
    for candidate in python_candidates() {
        match probe(&candidate) {
            Ok(()) => return candidate,
            Err(reason) => reasons.push(reason),
        }
    }
    panic!(
        "no usable Python for the cross-language byte-compatibility proof. This test does \
         NOT skip: without it, nothing checks that what Rust signs is what \
         engine/runtime/bro_signature.py accepts. Set BROPS_TEST_PYTHON to an interpreter \
         with `cryptography` installed.\n  {}",
        reasons.join("\n  ")
    );
}

/// Give Python a path free of platform surprises. On unix that means resolving symlinks
/// (macOS puts temp dirs under `/var`, a symlink to `/private/var`, and
/// `bro_signature._pin_from_file` refuses a symlink at ANY path component). On Windows
/// `canonicalize` returns a `\\?\` extended-length path, which is absolute but compares
/// unequal to every non-extended form, so the raw path is used there.
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

#[test]
fn the_real_python_verifier_accepts_the_real_rust_output() {
    let python = resolve_python();
    let repo = repo_root();
    let engine = repo.join("engine");
    assert!(
        engine.join("runtime").join("bro_signature.py").is_file(),
        "no engine tree at {} — the cross-language proof has nothing to verify against",
        engine.display()
    );

    let temp = tempfile::tempdir().expect("temp dir");
    let data_dir = python_safe(temp.path());
    let provisioned = brops_provision::provision(&data_dir).expect("provisioning");
    assert!(provisioned.freshly_minted);

    // O-5's artifact is never a startup side effect (see `mint_floor_anchor`), so the
    // proof mints one here, with the same signer and the same canonicalizer.
    brops_provision::mint_floor_anchor(
        &provisioned.trust_dir,
        "t-001",
        3,
        &provisioned.trust_dir.join("artifacts").join("test-floor-anchor.json"),
    )
    .expect("floor anchor");

    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("verify_provisioning.py");
    let output = Command::new(&python)
        .arg("-B") // no bytecode beside the engine runtime (O-1's rule)
        .arg(&script)
        .arg(provisioned.trust_dir.as_os_str())
        .arg(engine.as_os_str())
        .output()
        .unwrap_or_else(|e| panic!("could not run `{python} {}`: {e}", script.display()));

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    println!("{stdout}");
    assert!(
        output.status.success(),
        "the real Python verifiers REFUSED the Rust-generated trust store — the two sides have \
         drifted.\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    );
    assert!(stdout.contains("GREEN:"), "the verifier did not report a green run:\n{stdout}");
}
