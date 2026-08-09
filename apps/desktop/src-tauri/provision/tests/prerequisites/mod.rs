//! Test helper: prerequisites a test cannot manufacture for itself.
//!
//! # The rule, and the round that made it necessary
//!
//! `anchor_custody.rs` had two `#[cfg(windows)]` tests. On Linux they were not skipped, they
//! were **absent** — the compiler removed them — so the nine tests that did run all measured a
//! *writable* directory and therefore only ever exercised `prove_unwritable`'s early-return
//! refusal. `can_delete`'s POSIX branch, `posix_ownership` and `posix_euid` had never executed
//! on any machine, and a Linux run went green anyway. Which machine ran the suite decided what
//! got tested, and the green told nobody anything.
//!
//! So, the same rule `engine/tests/_prerequisites.py` settled on:
//!
//! > a test gives the SAME verdict everywhere, or it SKIPS with a reason that names the
//! > missing prerequisite exactly. Never compiled out, and never a silent pass.
//!
//! # Was a Rust equivalent warranted? Yes, with one honest difference
//!
//! The Python side can raise `unittest.SkipTest` and the runner prints `s`. Rust's `libtest`
//! has no runtime skip at all: a test either passes, fails, or is statically `#[ignore]`d. So
//! "skip" here means *return early*, which is a PASS, and a pass that proves nothing is the
//! exact failure mode this module exists to prevent. Two things make it honest anyway:
//!
//! 1. [`skip`] writes to the process's real stderr — `io::stderr()`, not `eprintln!` — which
//!    `libtest`'s output capture does not intercept. The line appears in a plain `cargo test`
//!    run, next to the passing test, whether or not `--nocapture` was passed.
//! 2. Under CI it is not a skip at all: [`skip`] **panics**. A skip is a hole unless somebody
//!    counts them, and the counter is that the CI runner is a machine where the prerequisite
//!    is supposed to exist. If it does not, the test stopped covering something and that is a
//!    RED, not an environment quirk to route around.
//!
//! Point 2 carries a caveat that has to be said out loud, because it is the difference between
//! a guard and the appearance of one: **`brops-provision` and `brops-audit-signer` are not in
//! `.github/workflows/ci.yml` at all today.** No job runs `cargo test -p brops-provision`, on
//! either platform. So the CI branch below is currently latent — it costs nothing and it bites
//! the day those crates are added to a job, which they should be.
//!
//! Not a test target: `tests/prerequisites/mod.rs` is a subdirectory module, and Cargo only
//! auto-discovers `tests/*.rs`.
#![allow(dead_code)]

use std::io::Write;
#[cfg(not(windows))]
use std::path::Path;
use std::path::PathBuf;

/// True on a CI runner, read from the runner's own signals rather than a repository flag —
/// the same two `engine/tests/_prerequisites.py` reads, for the same reason: no workflow edit
/// is needed for the guard to bite, and nobody on a deployed box trips it by exporting a
/// project variable the runbook tells them to export.
pub fn running_under_ci() -> bool {
    ["GITHUB_ACTIONS", "CI"].iter().any(|name| {
        matches!(
            std::env::var(name).unwrap_or_default().trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    })
}

/// Report a missing prerequisite: a visible line off the runner, a hard failure on it.
///
/// `what` names the prerequisite exactly — the directory, the uid, the kernel interface —
/// because "skipped" without it is indistinguishable from "there is nothing to test here".
pub fn skip(test: &str, what: &str) {
    if running_under_ci() {
        panic!(
            "{test}: {what}. CI runs on a machine where this IS available, so this is not an \
             environment quirk to skip past: the test would have stopped covering anything. \
             Fix the runner, not the assertion."
        );
    }
    // Deliberately NOT `eprintln!`: libtest captures that, and a captured skip notice on a
    // passing test is a silent pass.
    let _ = writeln!(std::io::stderr(), "SKIP {test}: {what}");
}

/// Is this process running as uid 0?
///
/// Several POSIX custody properties are simply false for root — it rewrites any file
/// regardless of owner or mode — so a test that asserts a location is out of reach has to
/// name "not running as root" as its prerequisite rather than quietly fail there.
#[cfg(unix)]
pub fn running_as_root() -> bool {
    // `/proc/self` is owned by the process's effective uid on Linux; elsewhere fall back to
    // the same probe-file mechanism the product uses, through the product's own function so a
    // divergence would show up as a test failure rather than be papered over here.
    brops_provision::anchor::posix_euid().map(|uid| uid == 0).unwrap_or(false)
}
#[cfg(not(unix))]
pub fn running_as_root() -> bool {
    false
}

/// An anchor-shaped directory this account genuinely cannot write, or `None`.
///
/// [`SealedAnchor::chain_is_intact`] is the difference between the two platforms' fixtures and
/// it is not cosmetic: it says whether the whole ancestor chain is out of reach as well, which
/// decides whether [`brops_provision::anchor::prove_unwritable`] should SUCCEED on it or
/// refuse at the chain step.
pub struct SealedAnchor {
    pub dir: PathBuf,
    pub pin: PathBuf,
    /// True when every ancestor up to the volume root is also out of this account's reach —
    /// i.e. when this fixture can exercise the full success path rather than only the leaf.
    pub chain_is_intact: bool,
    /// What made this fixture available, for the record the test prints.
    pub provenance: String,
}

/// The environment variable a deployment or a CI job uses to hand the suite a POSIX fixture.
///
/// It must name a directory owned by a uid this process is NOT, with every ancestor likewise —
/// e.g. created by `sudo install -d -o root -g root -m 0755 /var/lib/brops-test-anchor` with a
/// mode-0644 file inside it. Reading it here is not a way for the product to redirect its own
/// anchor: `default_machine_root` deliberately takes no environment variable, and this is test
/// code that never runs inside the application.
pub const POSIX_FIXTURE_ENV: &str = "BROPS_TEST_FOREIGN_ANCHOR";

// =================================================================================================
// The one fixture neither platform can manufacture out of nothing
// =================================================================================================

/// One sealed directory, shared, at a fixed path, created once ever.
///
/// It cannot be a fresh `tempfile::tempdir()` per run: the seal removes this account's
/// `FILE_ADD_FILE`, `DELETE`, `FILE_DELETE_CHILD` and `WRITE_DAC`, so after it returns nothing
/// running as this account can undo it, empty it, or remove it. That is the property. A test
/// that wanted a clean-up would be a test asking for the property not to hold.
///
/// So: one directory, reused, and if it is already sealed it is used as it is. Removing it
/// needs an administrator:
///
/// ```text
/// takeown /f "%TEMP%\brops-o2-sealed-probe" /r /d y
/// icacls  "%TEMP%\brops-o2-sealed-probe" /reset /t
/// rmdir /s /q "%TEMP%\brops-o2-sealed-probe"
/// ```
#[cfg(windows)]
pub fn sealed_anchor(_test: &str) -> Option<SealedAnchor> {
    use brops_provision::{anchor, ProvisionError};

    let root = std::env::temp_dir().join("brops-o2-sealed-probe");
    let dir = root.join("trust-anchor");
    let pin = dir.join("operator-root.pub");
    if !pin.is_file() {
        std::fs::create_dir_all(&dir).expect("create the probe directory");
        std::fs::write(&pin, "11".repeat(32) + "\n").expect("write the pin");
        // `seal` walks upward and REFUSES rather than re-permission a directory outside the
        // machine root it was given — here that is `%TEMP%`, which the rest of the system
        // relies on. It is the right refusal (`a_location_whose_ancestors_...` is the test for
        // it) and it arrives AFTER the leaf and its files have been sealed, because the walk
        // is deepest-first. So the leaf really is sealed at this point; the caller proves that
        // with syscalls rather than taking this helper's word for it.
        match anchor::seal(&dir, &root) {
            Ok(_) => {}
            Err(ProvisionError::Custody { ref path, .. }) if *path == std::env::temp_dir() => {}
            Err(e) => panic!("the probe directory could not be sealed: {e}"),
        }
    }
    Some(SealedAnchor {
        dir,
        pin,
        // %TEMP% can be renamed by this account, so the chain above the leaf is NOT intact and
        // `prove_unwritable` must refuse at the chain step. That is the honest state of this
        // fixture, and asserting it is how `a_location_whose_ancestors_...` fires at its
        // second site.
        chain_is_intact: false,
        provenance: "sealed by `anchor::seal` under %TEMP% (PROTECTED DACL, OWNER RIGHTS RX)"
            .to_string(),
    })
}

/// A directory owned by a uid this process is NOT — which POSIX gives no way to manufacture.
///
/// There is no unprivileged POSIX construction of an anchor: an owner may always `chmod` a
/// directory it owns, so `seal` refuses here by design, and building the fixture in-process
/// would mean building the very thing the module says cannot be built. Under a temporary
/// directory the ancestor chain is writable too, so even a `0555` directory this account owns
/// refuses at the chain step before the ownership question is ever reached.
///
/// So the fixture has to come from outside the process, from one of two places:
///
/// 1. `$BROPS_TEST_FOREIGN_ANCHOR`, which a CI job or an operator points at a directory made
///    with e.g. `sudo install -d -o root -g root -m 0755 /var/lib/brops-test-anchor`;
/// 2. the real anchor at [`brops_provision::anchor::POSIX_MACHINE_ROOT`], if this box has been
///    provisioned — measuring the production article is better than measuring a stand-in.
///
/// Absent both, this SKIPS naming exactly what is missing. It never fabricates a pass.
#[cfg(not(windows))]
pub fn sealed_anchor(test: &str) -> Option<SealedAnchor> {
    use brops_provision::anchor;

    let euid = match anchor::posix_euid() {
        Ok(uid) => uid,
        Err(e) => {
            skip(test, &format!("this process's effective uid could not be measured ({e})"));
            return None;
        }
    };
    if euid == 0 {
        skip(
            test,
            "this process is running as root, which rewrites any file regardless of owner or \
             mode, so no directory on this machine is out of its reach. Run the suite as an \
             unprivileged account",
        );
        return None;
    }

    let from_env = std::env::var_os(POSIX_FIXTURE_ENV).map(PathBuf::from);
    let production = anchor::anchor_dir(Path::new(anchor::POSIX_MACHINE_ROOT));
    let candidates: Vec<(PathBuf, String)> = from_env
        .into_iter()
        .map(|p| (p, format!("${POSIX_FIXTURE_ENV}")))
        .chain(std::iter::once((
            production.clone(),
            "the provisioned production anchor".to_string(),
        )))
        .collect();

    for (dir, provenance) in candidates {
        if !foreign_owned_chain(&dir, euid) {
            continue;
        }
        let Some(pin) = first_regular_file(&dir) else { continue };
        return Some(SealedAnchor {
            dir,
            pin,
            chain_is_intact: true,
            provenance: format!("{provenance}, owned by a uid this process is not"),
        });
    }

    skip(
        test,
        &format!(
            "no trust-anchor directory owned by another uid is available to measure. POSIX has \
             no unprivileged construction of one — an owner may always chmod what it owns — so \
             this needs either ${POSIX_FIXTURE_ENV} pointing at a directory created by another \
             account (`sudo install -d -o root -g root -m 0755 <dir>` plus a mode-0644 file \
             inside it), or a provisioned anchor at {}. Neither is present, and uid {euid} \
             cannot make one",
            production.display()
        ),
    );
    None
}

/// Is `dir` — and every ancestor of it — owned by somebody other than uid `euid`?
#[cfg(not(windows))]
fn foreign_owned_chain(dir: &Path, euid: u32) -> bool {
    use std::os::unix::fs::MetadataExt;
    match std::fs::metadata(dir) {
        Ok(meta) if meta.is_dir() && meta.uid() != euid => {}
        _ => return false,
    }
    let mut component = dir.parent();
    while let Some(path) = component {
        match std::fs::metadata(path) {
            Ok(meta) if meta.uid() != euid => {}
            _ => return false,
        }
        component = path.parent();
    }
    true
}

/// A regular file inside `dir`, so the open-for-write probe has something to be asked about.
#[cfg(not(windows))]
fn first_regular_file(dir: &Path) -> Option<PathBuf> {
    let preferred = dir.join("operator-root.pub");
    if preferred.is_file() {
        return Some(preferred);
    }
    let mut found: Vec<PathBuf> = std::fs::read_dir(dir)
        .ok()?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.is_file())
        .collect();
    found.sort();
    found.into_iter().next()
}

/// Linux's own answer to "what uid is this process?", from procfs rather than from the
/// probe-file mechanism [`brops_provision::anchor::posix_euid`] uses.
///
/// An independent oracle, which is the only reason a test of `posix_euid` proves anything: a
/// test that measured the answer with the same mechanism would be asserting that a function
/// equals itself. `/proc/self` is owned by the process's effective uid.
#[cfg(not(windows))]
pub fn procfs_euid() -> Option<u32> {
    use std::os::unix::fs::MetadataExt;
    std::fs::metadata("/proc/self").ok().map(|m| m.uid())
}
