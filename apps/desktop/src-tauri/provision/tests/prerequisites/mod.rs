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
//! # The version of this module that came before, and why it did not hold
//!
//! It tried to keep that rule with two mechanisms, and a real Debian run refuted both.
//!
//! 1. It wrote the skip notice to `io::stderr()` directly rather than through `eprintln!`, with
//!    a comment claiming libtest's capture does not intercept the raw handle. **It does.** On
//!    the Debian run the notice appeared only under `--show-output`; a plain `cargo test` never
//!    showed it.
//! 2. It turned the skip into a panic only when `CI`/`GITHUB_ACTIONS` was set, on the reasoning
//!    that the runner is the machine where every prerequisite exists. Off the runner the skip
//!    stayed silent — which is where deployments actually run.
//!
//! What that cost, measured: the suite printed **131 passed, 0 failed, 0 ignored** with the one
//! test that proves the POSIX anchor is genuinely out of the account's reach silently skipped,
//! and the counts were *byte-identical* to a run where it had executed. `cargo test` exiting 0
//! was true and meant nothing. That is precisely the failure this module exists to prevent,
//! reproduced one level down inside the guard itself.
//!
//! Note the asymmetry with the Python side, because it is the whole reason the two modules
//! differ: `unittest.SkipTest` puts an `s` in the progress line and an `(skipped=N)` in the
//! summary, so a Python skip changes the output whether anyone asked for it or not. Rust's
//! libtest has **no runtime skip at all** — a test passes, fails, or is statically `#[ignore]`d
//! — so "skip" here can only mean *return early*, which is a PASS. There is no output channel
//! this module can write to that a plain `cargo test` is guaranteed to show.
//!
//! # So the default is inverted: a missing prerequisite FAILS
//!
//! [`skip`] panics. Everywhere, not only under CI. The only way to turn a missing prerequisite
//! into an early return is for a human to name it, exactly, in
//! [`DECLARATION_ENV`]:
//!
//! ```text
//! BROPS_TEST_MISSING_PREREQUISITES=posix-foreign-anchor,windows-symlink-creation cargo test …
//! ```
//!
//! The property that buys: **no configuration of this suite can report all-green while a
//! decisive test quietly did not run.** Either every prerequisite was present, or somebody
//! typed the name of the one that was not — into a shell, or into a workflow file where it sits
//! in the diff and in the job log. A skip is still a hole, but it is now a hole with a
//! signature on it.
//!
//! Deliberately absent: any blanket form. `all`, `*`, `1`, `true` are refused *as declarations*
//! and the refusal says so, so there is no single value that switches the guard off. Each tag
//! costs its own act of typing, which is the only thing that keeps the list short.
//!
//! And the CI special case is gone. It existed because skips were invisible, so the runner had
//! to be the place that counted them; now every skip is declared or fatal on every machine, and
//! the runner needs no rule of its own. What CI must do instead is *provide* the prerequisites —
//! which is a job-definition problem, where it belongs — and declare, in the workflow, the ones
//! it genuinely cannot.
//!
//! # Platform facts are not environment gaps
//!
//! "This machine has no `/proc`" is something a runner can fix. "Windows has no effective uid"
//! is not, on any machine, ever. Those go through [`not_applicable`], which never fails and
//! never needs declaring — and which refuses any test name that is not in
//! [`PLATFORM_EXEMPTIONS`], a table that is reviewed as a table. The matrix is what makes it
//! honest: every entry names a test that the *other* leg of the `ubuntu-latest`/`windows-latest`
//! matrix runs for real, so the property is measured, just not here.
//!
//! Not a test target: `tests/prerequisites/mod.rs` is a subdirectory module, and Cargo only
//! auto-discovers `tests/*.rs`.
#![allow(dead_code)]

use std::io::Write;
use std::path::{Path, PathBuf};

/// The variable a human types to say "this machine genuinely lacks that, and I know it".
///
/// Comma-separated prerequisite tags, exactly as [`skip`] prints them. Nothing else declares
/// anything: there is no wildcard and no boolean.
pub const DECLARATION_ENV: &str = "BROPS_TEST_MISSING_PREREQUISITES";

/// Values people reach for when they want to turn a guard off wholesale. Refused by name, so
/// the refusal can explain itself instead of silently matching no tag.
const BLANKET_FORMS: [&str; 8] = ["all", "*", "any", "1", "true", "yes", "on", "everything"];

/// What [`skip`] does about a missing prerequisite, decided as a pure function of the tag and
/// the declaration string so it can be tested without a process environment.
#[derive(Debug, PartialEq, Eq)]
pub enum Verdict {
    /// Nobody declared this one: the test must fail. Carries the reason, ready to panic with.
    Fail(String),
    /// A human named this exact tag, so an early return is an act somebody signed for.
    Declared,
}

/// The decision, pure: is `tag` named — exactly, on its own — in `declaration`?
///
/// Split on commas, whitespace-trimmed, empties ignored. A blanket form anywhere in the list
/// fails **regardless of the tag**, because the alternative is that
/// `BROPS_TEST_MISSING_PREREQUISITES=1` reads as "skip whatever you like" — which is the switch
/// this module exists to not have.
pub fn verdict(tag: &str, declaration: &str) -> Verdict {
    let entries: Vec<&str> =
        declaration.split(',').map(str::trim).filter(|e| !e.is_empty()).collect();

    if let Some(blanket) =
        entries.iter().find(|e| BLANKET_FORMS.contains(&e.to_ascii_lowercase().as_str()))
    {
        return Verdict::Fail(format!(
            "{DECLARATION_ENV} contains `{blanket}`, which declares NOTHING. There is no blanket \
             form and no boolean: every missing prerequisite costs its own tag, because a single \
             value that switches the guard off is a guard nobody has to think about. Name \
             `{tag}` itself if this machine really lacks it."
        ));
    }
    if entries.iter().any(|e| *e == tag) {
        return Verdict::Declared;
    }
    Verdict::Fail(format!(
        "this prerequisite is not declared missing. If this machine genuinely cannot provide it, \
         say so by name and the test will return early instead:\n    \
         {DECLARATION_ENV}={tag}\n  (comma-separate several). Otherwise the machine is what needs \
         fixing — a test that returns early proves nothing, and `cargo test` would report the \
         same counts either way"
    ))
}

/// Report a missing prerequisite: fatal unless [`DECLARATION_ENV`] names `tag` exactly.
///
/// `what` names the prerequisite in prose — the directory, the uid, the privilege — because
/// "skipped" without it is indistinguishable from "there is nothing to test here". `tag` is the
/// stable handle a human types to accept the hole.
pub fn skip(test: &str, tag: &str, what: &str) {
    assert!(!tag.is_empty() && !tag.contains(','), "a prerequisite tag is one comma-free word: {tag:?}");
    let declaration = std::env::var(DECLARATION_ENV).unwrap_or_default();
    match verdict(tag, &declaration) {
        Verdict::Fail(why) => panic!(
            "{test}: MISSING PREREQUISITE `{tag}` — {what}.\n  {why}"
        ),
        Verdict::Declared => {
            // Both channels, because neither is guaranteed on its own: libtest captures raw
            // `io::stderr()` writes as well as `eprintln!` (that is the bug this module was
            // rewritten over), and `--show-output`/`--nocapture` reveal stdout. The line is
            // belt and braces on top of the real guarantee, which is that somebody typed the
            // tag to get here.
            println!("SKIP {test}: declared-missing prerequisite `{tag}` — {what}");
            let _ = writeln!(
                std::io::stderr(),
                "SKIP {test}: declared-missing prerequisite `{tag}` — {what}"
            );
        }
    }
}

// =================================================================================================
// Platform facts, which no runner can supply
// =================================================================================================

/// Every test allowed to return early because the platform it is running on has no such thing.
///
/// Reviewed as a table on purpose: the entries are the complete list of properties this leg of
/// the matrix does not measure, and the other leg does. Adding one is a visible act; it cannot
/// be done by exporting anything.
///
/// `(test, the platform where it does not apply, the counterpart that measures it)`.
pub const PLATFORM_EXEMPTIONS: [(&str, &str, &str); 2] = [
    (
        "the_effective_uid_probe_agrees_with_the_kernel",
        "windows",
        "there is no effective uid on Windows to agree with anything — custody is decided by \
         the token and the DACL, which `the_behavioural_probe_reports_real_denial_and_real_access` \
         measures. The ubuntu-latest leg runs this test for real.",
    ),
    (
        "a_posix_first_launch_refuses_before_it_mints_anything",
        "windows",
        "Windows CAN construct its own anchor, so there is no first-launch refusal to wire; \
         `windows_is_the_only_platform_that_can_construct_its_own_anchor` is the other half of \
         the same decision and runs here. The ubuntu-latest leg runs this test for real.",
    ),
];

/// Return early because this platform has no such concept. Never fails, never needs declaring —
/// and refuses outright if `test` is not in the reviewed [`PLATFORM_EXEMPTIONS`] table.
pub fn not_applicable(test: &str) {
    let Some((_, platform, why)) = PLATFORM_EXEMPTIONS.iter().find(|(name, ..)| *name == test)
    else {
        panic!(
            "{test} tried to exempt itself as a platform fact, but it is not in \
             prerequisites::PLATFORM_EXEMPTIONS. That table is the complete list of properties \
             this platform does not measure; an exemption that is not in it is an environment \
             gap wearing a platform's clothes — use `skip` with a tag instead."
        );
    };
    println!("PLATFORM-N/A {test} on {platform}: {why}");
    let _ = writeln!(std::io::stderr(), "PLATFORM-N/A {test} on {platform}: {why}");
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

/// The tag for "the suite is running as root, where no location is out of reach".
pub const TAG_NOT_ROOT: &str = "unprivileged-posix-account";

/// The tag for the POSIX fixture no unprivileged process can build.
pub const TAG_POSIX_FOREIGN_ANCHOR: &str = "posix-foreign-anchor";

/// The tag for `/proc`, the only independent oracle for this process's own uid.
pub const TAG_PROCFS: &str = "procfs";

/// The tag for a Windows token that is NOT an elevated administrator.
///
/// Every O-2 custody property is a claim about what *this account* cannot reach. An elevated
/// administrator holds `SeTakeOwnershipPrivilege`/`SeRestorePrivilege` and sits in an
/// `BUILTIN\Administrators` ACE that every one of these descriptors grants, so on that token the
/// claim is FALSE — which the product already reports as
/// `Separation::SeparatedUntilElevation` rather than pretending otherwise. A test that measured
/// custody there would be measuring nothing.
pub const TAG_UNELEVATED_TOKEN: &str = "windows-unelevated-token";

/// The tag for creating a symlink on Windows, which needs `SeCreateSymbolicLinkPrivilege` or
/// Developer Mode.
pub const TAG_WINDOWS_SYMLINK: &str = "windows-symlink-creation";

/// The tag for stamping an owner other than this account, which needs `SeRestorePrivilege`.
pub const TAG_OWNER_ASSIGNMENT: &str = "windows-owner-assignment";

/// The tag for applying a security descriptor at all.
pub const TAG_DACL_APPLICATION: &str = "windows-dacl-application";

/// The tag for an installed `NT SERVICE\BroPSAuditSigner`.
pub const TAG_INSTALLED_SIGNER_SERVICE: &str = "installed-signer-service";

/// The tag for actually running the elevated registration path against a live SCM.
///
/// Distinct from [`TAG_UNELEVATED_TOKEN`] and its exact opposite: that one says a test needs a
/// token WITHOUT administrator rights, this one says a test needs a token WITH them. No single
/// process can satisfy both, which is why they are two tags and not one.
pub const TAG_ELEVATED_REGISTRATION: &str = "windows-elevated-registration";

/// Is this Windows token an elevated administrator — the posture on which no custody claim in
/// this suite is measurable?
///
/// Measured through the product's own `app_token_posture`, so a divergence between what the
/// tests believe about this box and what the product believes shows up as a test failure rather
/// than being papered over with a second implementation here.
#[cfg(windows)]
pub fn running_elevated() -> bool {
    matches!(
        brops_provision::audit_signer::winimpl::app_token_posture(),
        Ok(brops_provision::audit_signer::AppTokenPosture::ElevatedAdministrator)
    )
}
#[cfg(not(windows))]
pub fn running_elevated() -> bool {
    false
}

/// Prose for the elevation gap, shared by every caller so the remedy is stated once.
pub const ELEVATION_GAP: &str = "this session is an ELEVATED administrator. It holds \
     SeTakeOwnershipPrivilege/SeRestorePrivilege and is granted by the BUILTIN\\Administrators \
     ACE these descriptors carry, so it genuinely can rewrite anything measured here and the \
     custody question has no content on it — the product reports that as \
     Separation::SeparatedUntilElevation rather than claiming a separation it does not have. \
     Run the suite from a standard or UAC-filtered token (the CI job creates a standard local \
     account for exactly this)";

// =================================================================================================
// The one fixture neither platform can manufacture out of nothing
// =================================================================================================

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
/// It must name a directory owned by a uid this process is NOT, with every ancestor likewise,
/// **and containing at least one regular file** — the open-for-write probe needs something to be
/// asked about, and an empty root-owned directory passes the ownership walk and then falls
/// through to the skip, which is how a Debian run found this paragraph missing:
///
/// ```text
/// sudo install -d -o root -g root -m 0755 /var/lib/brops-trust-anchor/trust-anchor
/// printf '%064d\n' 0 | sudo install -o root -g root -m 0644 /dev/stdin \
///     /var/lib/brops-trust-anchor/trust-anchor/operator-root.pub
/// ```
///
/// Reading it here is not a way for the product to redirect its own anchor:
/// `default_machine_root` deliberately takes no environment variable, and this is test code that
/// never runs inside the application.
pub const POSIX_FIXTURE_ENV: &str = "BROPS_TEST_FOREIGN_ANCHOR";

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
pub fn sealed_anchor(test: &str) -> Option<SealedAnchor> {
    use brops_provision::{anchor, ProvisionError};

    // An elevated token is granted by the BUILTIN\Administrators ACE the seal writes, so the
    // seal would deny it nothing and "sealed" would be a word about a directory this session can
    // still rewrite. Name it rather than measure a fixture that is not one.
    if running_elevated() {
        skip(test, TAG_UNELEVATED_TOKEN, ELEVATION_GAP);
        return None;
    }

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
///    with e.g. `sudo install -d -o root -g root -m 0755 /var/lib/brops-test-anchor`, **with a
///    regular file inside it**;
/// 2. the real anchor at [`brops_provision::anchor::POSIX_MACHINE_ROOT`], if this box has been
///    provisioned — measuring the production article is better than measuring a stand-in.
///
/// Absent both, this fails naming exactly what is missing, unless the tag is declared.
#[cfg(not(windows))]
pub fn sealed_anchor(test: &str) -> Option<SealedAnchor> {
    use brops_provision::anchor;

    let euid = match anchor::posix_euid() {
        Ok(uid) => uid,
        Err(e) => {
            skip(
                test,
                TAG_POSIX_FOREIGN_ANCHOR,
                &format!("this process's effective uid could not be measured ({e})"),
            );
            return None;
        }
    };
    if euid == 0 {
        skip(
            test,
            TAG_NOT_ROOT,
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

    // What each candidate failed on, so the refusal can say "you built the directory and left
    // out the file" rather than "no fixture" — the exact confusion a Debian run hit.
    let mut rejected: Vec<String> = Vec::new();
    for (dir, provenance) in candidates {
        if !dir.exists() {
            rejected.push(format!("{} ({provenance}): does not exist", dir.display()));
            continue;
        }
        if !foreign_owned_chain(&dir, euid) {
            rejected.push(format!(
                "{} ({provenance}): it or one of its ancestors is owned by uid {euid}, which is \
                 this process — an owner may always chmod what it owns",
                dir.display()
            ));
            continue;
        }
        let Some(pin) = first_regular_file(&dir) else {
            rejected.push(format!(
                "{} ({provenance}): owned by another uid, but it contains NO regular file, so \
                 the open-for-write probe has nothing to be asked about. Put a mode-0644 \
                 root-owned `operator-root.pub` inside it",
                dir.display()
            ));
            continue;
        };
        return Some(SealedAnchor {
            dir,
            pin,
            chain_is_intact: true,
            provenance: format!("{provenance}, owned by a uid this process is not"),
        });
    }

    skip(
        test,
        TAG_POSIX_FOREIGN_ANCHOR,
        &format!(
            "no trust-anchor directory owned by another uid is available to measure. POSIX has \
             no unprivileged construction of one — an owner may always chmod what it owns — so \
             this needs either ${POSIX_FIXTURE_ENV} pointing at a directory created by another \
             account, or a provisioned anchor at {}. Both need a regular file inside:\n    \
             sudo install -d -o root -g root -m 0755 <dir>\n    printf '%064d\\n' 0 | sudo \
             install -o root -g root -m 0644 /dev/stdin <dir>/operator-root.pub\n  uid {euid} \
             cannot make one. What was tried:\n    {}",
            production.display(),
            rejected.join("\n    ")
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

// =================================================================================================
// A directory this account can list but cannot add entries to, without sealing it forever
// =================================================================================================

/// A directory whose contents this account can enumerate and whose entries it cannot create —
/// applied so it can be UNDONE, unlike [`brops_provision::anchor::seal`].
///
/// `seal` is one-way by design: it removes `WRITE_DAC`, so the account that applied it can never
/// restore the directory. That is right for the product and wrong for a fixture that two tests
/// need afresh — which is why those two tests used to have no Windows branch at all, and the
/// walk they measure (`probe_tree` descending into a subdirectory, and refusing a symlink rather
/// than following it) had never run against a Windows descriptor.
///
/// So this grants the account everything EXCEPT the bits named in `removed`, and keeps
/// `READ_CONTROL`/`WRITE_DAC` so [`restore_full_control`] can put it back. It is not a seal and
/// it is not offered as one: it isolates exactly the access bits `probe_tree` asks about, which
/// is what lets a Windows fixture reproduce what `chmod 0555` on a directory and `chmod 0444`
/// on the pin do on POSIX.
///
/// The bits are named in [`deny`], and all three matter — the first version of this helper
/// removed only `ADD_FILE`, and the fixture it built was refused for *deletability* long before
/// the walk reached what it was built to demonstrate:
///
/// * [`deny::ADD_FILE`] (`FILE_WRITE_DATA`, 0x2) — on a directory, "create an entry here"; on a
///   file, "overwrite the contents".
/// * [`deny::DELETE`] (0x1_0000) — an entry's own right to be removed.
/// * [`deny::DELETE_CHILD`] (`FILE_DELETE_CHILD`, 0x40) — a DIRECTORY's grant of the right to
///   remove what is inside it, which an entry's own descriptor does not mention at all.
///   `probe_tree` asks `can_delete` of every entry precisely because of this bit. `chmod 0555`
///   removes the POSIX equivalent as a side effect of one number; a DACL has to say so.
#[cfg(windows)]
pub mod deny {
    /// Create an entry in this directory / overwrite this file's contents.
    pub const ADD_FILE: u32 = 0x0000_0002;
    /// Remove the things inside this directory.
    pub const DELETE_CHILD: u32 = 0x0000_0040;
    /// Remove this object.
    pub const DELETE: u32 = 0x0001_0000;
}

#[cfg(windows)]
pub fn deny_access(path: &Path, removed: u32) -> Result<String, String> {
    use brops_provision::audit_signer as spec;
    let me = spec::winimpl::current_user_sid().map_err(|e| e.to_string())?;
    let plan = spec::DaclPlan {
        aces: vec![
            spec::Ace {
                sid: me.clone(),
                mask: spec::FILE_ALL_ACCESS & !removed,
                inheritable: false,
            },
            spec::Ace {
                sid: spec::SID_LOCAL_SYSTEM.to_string(),
                mask: spec::FILE_ALL_ACCESS,
                inheritable: false,
            },
        ],
        app_sid: me.clone(),
        signer_sid: spec::service_account_sid(spec::SIGNER_SERVICE_NAME),
        owner_sid: me.clone(),
    };
    spec::winimpl::apply_dacl(path, &plan, None).map_err(|e| e.to_string())?;
    Ok(me)
}

/// Create a symlink at `link` pointing at `target`, through whichever door this account has.
///
/// `std::os::windows::fs::symlink_file` calls `CreateSymbolicLinkW` **without**
/// `SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE` (0x2), so on a machine whose only permission
/// to make links comes from Developer Mode rather than from `SeCreateSymbolicLinkPrivilege`, the
/// standard-library call fails `ERROR_PRIVILEGE_NOT_HELD` (1314) and the flag would have
/// succeeded. Which of the two a given box offers is not something a test should have an opinion
/// about — the fixture is a symlink either way, and the assertion is about what `probe_tree` does
/// with one.
///
/// So: try the standard library, then the flag, and report the FIRST error if neither works,
/// because that is the one that names the privilege an operator would grant.
#[cfg(windows)]
pub fn create_symlink(target: &Path, link: &Path) -> Result<(), std::io::Error> {
    const ALLOW_UNPRIVILEGED_CREATE: u32 = 0x2;
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateSymbolicLinkW(symlink: *const u16, target: *const u16, flags: u32) -> u8;
    }
    fn wide(path: &Path) -> Vec<u16> {
        use std::os::windows::ffi::OsStrExt;
        path.as_os_str().encode_wide().chain(std::iter::once(0)).collect()
    }

    let first = match std::os::windows::fs::symlink_file(target, link) {
        Ok(()) => return Ok(()),
        Err(e) => e,
    };
    let ok = unsafe {
        CreateSymbolicLinkW(wide(link).as_ptr(), wide(target).as_ptr(), ALLOW_UNPRIVILEGED_CREATE)
    };
    if ok != 0 {
        return Ok(());
    }
    Err(first)
}

/// Undo [`deny_access`] so the fixture's `TempDir` can remove itself.
#[cfg(windows)]
pub fn restore_full_control(path: &Path, me: &str) -> Result<(), String> {
    use brops_provision::audit_signer as spec;
    let plan = spec::DaclPlan {
        aces: vec![spec::Ace {
            sid: me.to_string(),
            mask: spec::FILE_ALL_ACCESS,
            inheritable: true,
        }],
        app_sid: me.to_string(),
        signer_sid: spec::service_account_sid(spec::SIGNER_SERVICE_NAME),
        owner_sid: me.to_string(),
    };
    spec::winimpl::apply_dacl(path, &plan, None).map_err(|e| e.to_string())
}
