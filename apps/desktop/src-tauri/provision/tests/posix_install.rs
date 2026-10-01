//! The POSIX installer (`brops_provision::posix_install` and the `brops_install_anchor` binary).
//!
//! # Two kinds of test, and why they are kept apart
//!
//! **The decisions** — who the desktop account is, whether the caller is root, what an
//! already-present anchor means, what one path's owner and mode say about the floor — are pure
//! functions, and they run on every machine in every `cargo test`.
//!
//! **The construction** cannot. There is no unprivileged way to build a root-owned anchor, so
//! the one test that mints for real, as root, and then asks the kernel *as the desktop uid*
//! whether that uid can verify and cannot write, needs root. It is `#[ignore]`d with its reason,
//! because that is the only skip libtest has that a plain run shows and counts (see
//! `prerequisites/mod.rs`: an early return is a PASS, and no output channel survives capture).
//! Run it with:
//!
//! ```text
//! cargo test -p brops-provision --test posix_install --no-run
//! sudo <the test binary cargo printed> --ignored --exact \
//!     root_installs_an_anchor_the_desktop_uid_verifies_and_cannot_touch --nocapture
//! ```
//!
//! Asked for by name without root, it FAILS — through `prerequisites::skip` — rather than
//! return early.
//!
//! It works only inside a directory it creates and removes, under `$BROPS_TEST_ROOT_BASE`
//! (default `/run`: root-owned, `0755`, volatile). It never touches the production machine
//! root and asserts at the end that it did not. It creates no account: the desktop uid is
//! `$BROPS_TEST_DESKTOP_USER`, else `$SUDO_USER`, else `nobody`.
#![cfg(unix)]

mod prerequisites;

use std::ffi::OsStr;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use brops_provision as prov;
use brops_provision::posix_install::{self as install, Invocation, Kind, Role};
use brops_provision::{anchor, ProvisionError};

const INSTALLER: &str = env!("CARGO_BIN_EXE_brops_install_anchor");

fn euid() -> u32 {
    anchor::posix_euid().expect("this process's effective uid")
}

fn strings(args: &[&str]) -> Vec<String> {
    args.iter().map(|a| a.to_string()).collect()
}

fn refusal_text<T: std::fmt::Debug>(result: Result<T, ProvisionError>) -> String {
    result.expect_err("this must be refused").to_string()
}

// =================================================================================================
// Who the desktop account is
// =================================================================================================

const PASSWD: &str = "\
root:x:0:0:root:/root:/bin/bash
# a comment line, and a short one below
short:x:1
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
gev:x:1000:1001:Gev,,,:/home/gev:/bin/bash
twice:x:1500:1500::/home/twice:/bin/sh
twice:x:1501:1500::/home/twice:/bin/sh
same:x:1600:1600::/home/same:/bin/sh
same:x:1600:1600::/home/same:/bin/sh
toor:x:0:0:also root:/root:/bin/sh
broken:x:abc:1000::/home/broken:/bin/sh
";

#[test]
fn a_named_account_resolves_to_exactly_its_passwd_line() {
    let user = install::resolve_user(PASSWD, "gev").expect("gev is listed");
    assert_eq!(user.name, "gev");
    assert_eq!((user.uid, user.gid), (1000, 1001), "uid and gid are fields 3 and 4, not swapped");
    assert_eq!(user.home, PathBuf::from("/home/gev"));
    // A line listed twice with the SAME ids is one account, not an ambiguity.
    assert_eq!(install::resolve_user(PASSWD, "same").expect("same").uid, 1600);
    // A prefix is not a match: `ge` and `gevorg` are different accounts from `gev`.
    for other in ["ge", "gevorg", "Gev"] {
        assert!(install::resolve_user(PASSWD, other).is_err(), "{other} matched `gev`");
    }
}

#[test]
fn an_account_the_installer_cannot_pin_down_is_refused_by_name() {
    let unknown = refusal_text(install::resolve_user(PASSWD, "ghost"));
    assert!(unknown.contains("\"ghost\"") && unknown.contains("/etc/passwd"), "{unknown}");

    let twice = refusal_text(install::resolve_user(PASSWD, "twice"));
    assert!(twice.contains("more than once") && twice.contains("1501"), "{twice}");

    let broken = refusal_text(install::resolve_user(PASSWD, "broken"));
    assert!(broken.contains("not a number"), "{broken}");

    // A truncated line is not an account at all.
    assert!(install::resolve_user(PASSWD, "short").is_err());

    for name in ["", "a:b", "a/b", "a\nb"] {
        let text = refusal_text(install::resolve_user(PASSWD, name));
        assert!(text.contains("not an account name"), "{name:?}: {text}");
    }
}

/// Root as the "desktop account" would report success for a launch that is certain to refuse:
/// `PosixOwnership::RunningAsRoot`. Both spellings of uid 0 are refused.
#[test]
fn uid_zero_is_never_the_desktop_account() {
    for name in ["root", "toor"] {
        let text = refusal_text(install::resolve_user(PASSWD, name));
        assert!(text.contains("uid 0"), "{name}: {text}");
    }
}

// =================================================================================================
// Whether the caller is root
// =================================================================================================

#[test]
fn only_uid_zero_may_install() {
    assert!(install::refuse_unless_root(0).is_ok());
    for uid in [1, 1000, 65534, u32::MAX] {
        let text = refusal_text(install::refuse_unless_root(uid));
        assert!(text.contains("must be run as root"), "{text}");
        assert!(text.contains(&format!("uid {uid}")), "{text}");
        assert!(text.contains("Nothing was created"), "{text}");
    }
}

/// The real thing, from an unprivileged account: the library refuses, the binary exits 1, and
/// neither leaves a machine root behind.
#[test]
fn an_unprivileged_caller_is_refused_and_nothing_is_created() {
    const NAME: &str = "an_unprivileged_caller_is_refused_and_nothing_is_created";
    if prerequisites::running_as_root() {
        prerequisites::skip(
            NAME,
            prerequisites::TAG_NOT_ROOT,
            "this process is root, so there is no unprivileged caller to refuse",
        );
        return;
    }
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let machine_root = tmp.path().join("machine");
    let app_data = tmp.path().join("appdata");

    let request = install::InstallRequest {
        user: install::DesktopUser {
            name: "someone".into(),
            uid: euid(),
            gid: 0,
            home: tmp.path().to_path_buf(),
        },
        app_data_dir: app_data.clone(),
        machine_root: machine_root.clone(),
        helper: PathBuf::from(INSTALLER),
    };
    let text = refusal_text(install::install_anchor(&request, PASSWD));
    assert!(text.contains("must be run as root"), "{text}");
    assert!(!machine_root.exists() && !app_data.exists(), "the refused library call wrote");

    let out = Command::new(INSTALLER)
        .args(["--user", "root", "--app-data"])
        .arg(&app_data)
        .arg("--machine-root")
        .arg(&machine_root)
        .output()
        .expect("run the installer");
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert_eq!(out.status.code(), Some(1), "{stderr}");
    assert!(stderr.contains("must be run as root"), "{stderr}");
    assert!(!machine_root.exists() && !app_data.exists(), "the refused binary wrote");
}

// =================================================================================================
// The arguments
// =================================================================================================

#[test]
fn the_arguments_parse_into_exactly_what_was_asked() {
    assert_eq!(
        install::parse_args(&strings(&["--user", "gev", "--app-data", "/d"])),
        Ok(Invocation::Install {
            user: "gev".into(),
            app_data: PathBuf::from("/d"),
            machine_root: None
        })
    );
    // Flag order is not significance, and the override reaches the request.
    assert_eq!(
        install::parse_args(&strings(&[
            "--machine-root", "/m", "--app-data", "/d", "--user", "gev"
        ])),
        Ok(Invocation::Install {
            user: "gev".into(),
            app_data: PathBuf::from("/d"),
            machine_root: Some(PathBuf::from("/m"))
        })
    );
    assert_eq!(
        install::parse_args(&strings(&["verify", "--app-data", "/d", "--machine-root", "/m"])),
        Ok(Invocation::Verify {
            app_data: PathBuf::from("/d"),
            machine_root: Some(PathBuf::from("/m"))
        })
    );
    assert_eq!(
        install::parse_args(&strings(&["deliver", "--from", "/f", "--app-data", "/d"])),
        Ok(Invocation::Deliver { from: PathBuf::from("/f"), app_data: PathBuf::from("/d") })
    );
    assert_eq!(
        install::parse_args(&strings(&["rollback", "--app-data", "/d"])),
        Ok(Invocation::Rollback { app_data: PathBuf::from("/d") })
    );
    assert_eq!(install::parse_args(&strings(&["--help"])), Ok(Invocation::Help));
}

/// An installer that ignored a misspelt `--machine-rooot` would mint into the production path
/// while its caller believed otherwise. Everything it does not recognise is refused.
#[test]
fn arguments_that_could_mean_something_else_are_refused() {
    for (args, needle) in [
        (vec![], "no arguments"),
        (vec!["--user", "gev"], "--app-data is required"),
        (vec!["--app-data", "/d"], "--user is required"),
        (vec!["--user", "gev", "--app-data", "/d", "--machine-rooot", "/m"], "unexpected"),
        (vec!["--user", "gev", "--app-data", "/d", "stray"], "unexpected"),
        (vec!["--user", "gev", "--user", "eve", "--app-data", "/d"], "more than once"),
        (vec!["--user", "gev", "--app-data"], "needs a value"),
        (vec!["--user", "--app-data", "/d"], "needs a value"),
        (vec!["--user", "", "--app-data", "/d"], "needs a value"),
        // `--user` belongs to the installer, not to the as-the-account halves.
        (vec!["verify", "--user", "gev", "--app-data", "/d"], "unexpected"),
        (vec!["deliver", "--app-data", "/d"], "--from is required"),
        (vec!["rollback", "--from", "/f", "--app-data", "/d"], "unexpected"),
    ] {
        let err = install::parse_args(&strings(&args)).expect_err(&format!("{args:?}"));
        assert!(err.contains(needle), "{args:?}: {err}");
    }
}

#[test]
fn a_path_the_application_would_spell_differently_is_refused() {
    assert!(install::refuse_ambiguous_path("--app-data", Path::new("/home/gev/.local/x")).is_ok());
    for bad in ["relative/dir", "/home/gev/../eve", "/home/./gev/..", "/"] {
        assert!(
            install::refuse_ambiguous_path("--app-data", Path::new(bad)).is_err(),
            "{bad} was accepted"
        );
    }
}

// =================================================================================================
// The floor root measures: one path at a time
// =================================================================================================

#[test]
fn the_floor_accepts_only_the_installers_own_tight_paths() {
    // The three shapes the installer leaves behind.
    assert_eq!(install::floor_refusal(Role::AnchorDir, Kind::Dir, 0, 0o40755, 0), None);
    assert_eq!(install::floor_refusal(Role::AnchorFile, Kind::File, 0, 0o100644, 0), None);
    for mode in [0o755, 0o555, 0o700, 0o711] {
        assert_eq!(install::floor_refusal(Role::Ancestor, Kind::Dir, 0, mode, 0), None, "{mode:o}");
    }

    let refused = |role, kind, uid, mode| {
        install::floor_refusal(role, kind, uid, mode, 0)
            .unwrap_or_else(|| panic!("{role:?} {kind:?} uid {uid} mode {mode:o} was accepted"))
    };
    // Owned by somebody else — the desktop account, or any third one.
    assert!(refused(Role::AnchorDir, Kind::Dir, 1000, 0o755).contains("owned by uid 1000"));
    assert!(refused(Role::AnchorFile, Kind::File, 1000, 0o644).contains("owned by uid 1000"));
    assert!(refused(Role::Ancestor, Kind::Dir, 33, 0o755).contains("owned by uid 33"));
    // The wrong mode: looser, and — for the anchor itself — tighter too, because a 0700
    // anchor is one the application cannot read.
    for mode in [0o775, 0o757, 0o777, 0o700, 0o1755] {
        assert!(refused(Role::AnchorDir, Kind::Dir, 0, mode).contains("0755"), "{mode:o}");
    }
    for mode in [0o664, 0o646, 0o666, 0o600, 0o755, 0o4644] {
        assert!(refused(Role::AnchorFile, Kind::File, 0, mode).contains("0644"), "{mode:o}");
    }
    // An ancestor anyone but its owner can add entries to — `/tmp`'s 1777 included: the
    // sticky bit stops a rename of somebody else's entry, not the creation of a new one.
    for mode in [0o775, 0o757, 0o777, 0o1777, 0o2775] {
        assert!(
            refused(Role::Ancestor, Kind::Dir, 0, mode).contains("group or everyone"),
            "{mode:o}"
        );
    }
    // The wrong kind of thing altogether.
    assert!(refused(Role::AnchorFile, Kind::Symlink, 0, 0o777).contains("Symlink"));
    assert!(refused(Role::AnchorFile, Kind::Dir, 0, 0o755).contains("Dir"));
    assert!(refused(Role::AnchorDir, Kind::File, 0, 0o644).contains("File"));
    assert!(refused(Role::Ancestor, Kind::Symlink, 0, 0o777).contains("Symlink"));
}

/// The walk, against a real directory: an anchor under a temporary directory fails the floor
/// whoever is asked to be its owner — its ancestors are this account's, or `/tmp`'s.
#[test]
fn a_real_anchor_under_a_temporary_directory_fails_the_floor() {
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let anchor_dir = tmp.path().join("machine").join(anchor::ANCHOR_DIR_NAME);
    prov::mint_store_without_custody_proof(&tmp.path().join("appdata"), &anchor_dir, None)
        .expect("mint a fixture store");
    for owner in [0, euid(), euid().wrapping_add(1)] {
        let err = install::measure_floor(&anchor_dir, owner);
        assert!(
            matches!(err, Err(ProvisionError::Custody { .. })),
            "owner {owner}: the floor accepted an anchor under a temporary directory: {err:?}"
        );
    }
}

/// The walk looks INSIDE the anchor, at every level: one loosened file two directories down
/// is found, and so is a symlink standing where a file belongs.
#[test]
fn the_floor_walk_reaches_every_entry_inside_the_anchor() {
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let anchor_dir = tmp.path().join("machine").join(anchor::ANCHOR_DIR_NAME);
    prov::mint_store_without_custody_proof(&tmp.path().join("appdata"), &anchor_dir, None)
        .expect("mint a fixture store");
    let me = euid();
    let floor_text = |anchor: &Path| refusal_text(install::measure_floor(anchor, me));

    // As minted, with this account as the owner asked about, the TREE is clean — so whatever
    // is refused is refused above the anchor, and each case below is refused for its own reason.
    let clean = floor_text(&anchor_dir);
    assert!(!clean.contains(&format!("{}/", anchor_dir.display())), "{clean}");

    let registry = anchor_dir.join(prov::REGISTRY_ROOT_DIR).join("config").join("trusted-keys.json");
    set_mode(&registry, 0o664);
    let loose = floor_text(&anchor_dir);
    assert!(loose.contains("trusted-keys.json") && loose.contains("0664"), "{loose}");
    set_mode(&registry, 0o644);

    let config = registry.parent().expect("config").to_path_buf();
    set_mode(&config, 0o775);
    let loose_dir = floor_text(&anchor_dir);
    assert!(loose_dir.contains("registry/config breaks") && loose_dir.contains("0775"), "{loose_dir}");
    set_mode(&config, 0o755);

    let floor = anchor_dir.join(anchor::REGISTRY_FLOOR_FILE);
    std::fs::remove_file(&floor).expect("remove the floor");
    std::os::unix::fs::symlink(anchor_dir.join(anchor::OPERATOR_PIN_FILE), &floor).expect("link");
    let linked = floor_text(&anchor_dir);
    assert!(linked.contains("registry-min") && linked.contains("Symlink"), "{linked}");
}

/// A symlink on the way TO the anchor leaves its target's real ancestors unmeasured, so the
/// path is refused for that — before, and whatever, the ancestors themselves would say.
#[test]
fn an_anchor_reached_through_a_symlink_is_refused_for_the_symlink() {
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let real = std::fs::canonicalize(tmp.path()).expect("canonical").join("real");
    let anchor_dir = real.join(anchor::ANCHOR_DIR_NAME);
    prov::mint_store_without_custody_proof(&tmp.path().join("appdata"), &anchor_dir, None)
        .expect("mint a fixture store");
    let link = real.parent().expect("parent").join("link");
    std::os::unix::fs::symlink(&real, &link).expect("link");

    let through = refusal_text(install::measure_floor(&link.join(anchor::ANCHOR_DIR_NAME), euid()));
    assert!(through.contains("symlink sits somewhere on the anchor's path"), "{through}");
    // The control: the real path is refused too (this is a temporary directory), but NOT for
    // being a symlink — so the sentence above is about the link and nothing else.
    let direct = refusal_text(install::measure_floor(&anchor_dir, euid()));
    assert!(!direct.contains("symlink sits somewhere"), "{direct}");
}

/// The machine root must not be, contain, or sit inside anybody's home.
#[test]
fn a_machine_root_that_is_somebodys_home_is_refused_by_account_name() {
    for root in ["/home/gev", "/home/gev/anchor", "/home"] {
        let text = refusal_text(install::refuse_home_collision(Path::new(root), PASSWD));
        assert!(text.contains("collides with the home directory"), "{root}: {text}");
        assert!(text.contains("Nothing was created"), "{root}: {text}");
    }
    let named = refusal_text(install::refuse_home_collision(Path::new("/home/gev/x"), PASSWD));
    assert!(named.contains("\"gev\"") && named.contains("/home/gev"), "{named}");
    // `/nonexistent` is Debian's way of saying "this account has no home": not a collision.
    for root in ["/var/lib/brops-trust-anchor", "/nonexistent/x", "/homework"] {
        assert!(install::refuse_home_collision(Path::new(root), PASSWD).is_ok(), "{root}");
    }
}

// =================================================================================================
// The verification child's report
// =================================================================================================

#[test]
fn a_report_is_believed_only_from_the_uid_that_was_asked_about() {
    let report = format!("{} uid=1000\ninstall abc\n", install::VERIFIED_MARKER);
    assert_eq!(install::child_report_refusal(&report, 1000), None);
    // The same report, about the wrong account — including the one that matters most.
    for other in [0, 100, 10000, 1001] {
        assert!(install::child_report_refusal(&report, other).is_some(), "uid {other}");
    }
    assert!(install::child_report_refusal("", 1000).is_some());
    assert!(install::child_report_refusal("all good\n", 1000).is_some());
    // The marker has to be the FIRST line, not somewhere a proof string could put it.
    let buried = format!("noise\n{} uid=1000\n", install::VERIFIED_MARKER);
    assert!(install::child_report_refusal(&buried, 1000).is_some());
}

// =================================================================================================
// An anchor that is already there
// =================================================================================================

#[test]
fn nothing_at_the_anchor_path_means_the_caller_may_mint() {
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let outcome = install::settle_existing(&tmp.path().join("trust-anchor"), || -> Result<(), _> {
        panic!("there is nothing to verify, so nothing may be verified")
    });
    assert!(matches!(outcome, Ok(None)), "{outcome:?}");
}

#[test]
fn a_directory_without_a_manifest_is_refused_and_never_verified() {
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let anchor_dir = tmp.path().join("trust-anchor");
    std::fs::create_dir(&anchor_dir).expect("an occupied anchor path");
    std::fs::write(anchor_dir.join(anchor::OPERATOR_PIN_FILE), "11".repeat(32)).expect("a pin");
    let outcome = install::settle_existing(&anchor_dir, || -> Result<(), _> {
        panic!("a directory with no manifest is not an anchor to verify")
    });
    assert!(matches!(outcome, Err(ProvisionError::Corrupt { .. })), "{outcome:?}");
}

#[test]
fn an_existing_anchor_that_verifies_is_the_whole_install() {
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let anchor_dir = tmp.path().join("trust-anchor");
    std::fs::create_dir(&anchor_dir).expect("anchor dir");
    std::fs::write(anchor_dir.join(anchor::MANIFEST_FILE), "{}").expect("a manifest");
    let outcome = install::settle_existing(&anchor_dir, || Ok::<_, ProvisionError>("proof"));
    assert!(matches!(outcome, Ok(Some("proof"))), "{outcome:?}");
}

/// A manifest-shaped thing that is not a regular file is still "something is installed here":
/// a dangling symlink reads as absent to `is_file`, and minting over it would follow it.
#[test]
fn a_manifest_that_is_a_dangling_symlink_is_not_an_empty_slot() {
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let anchor_dir = tmp.path().join("trust-anchor");
    std::fs::create_dir(&anchor_dir).expect("anchor dir");
    std::os::unix::fs::symlink(tmp.path().join("nowhere"), anchor_dir.join(anchor::MANIFEST_FILE))
        .expect("a dangling manifest");
    let mut asked = false;
    let outcome = install::settle_existing(&anchor_dir, || -> Result<(), _> {
        asked = true;
        Err(ProvisionError::Corrupt { what: "unreadable".into(), detail: "dangling".into() })
    });
    assert!(asked, "a dangling manifest was treated as no manifest");
    assert!(matches!(outcome, Err(ProvisionError::Unsupported { .. })), "{outcome:?}");
}

/// The real refusal, with the real verifier: an anchor this account minted for itself does not
/// verify — the application's own launch check says so — and the installer's answer to that is
/// to refuse and change nothing. There is no branch that mints over it.
#[test]
fn an_existing_anchor_that_does_not_verify_is_refused_and_left_exactly_as_it_was() {
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let machine_root = tmp.path().join("machine");
    let anchor_dir = anchor::anchor_dir(&machine_root);
    let app_data = tmp.path().join("appdata");
    prov::mint_store_without_custody_proof(&app_data, &anchor_dir, None).expect("mint a fixture");

    let watched: Vec<PathBuf> = vec![
        anchor_dir.join(anchor::MANIFEST_FILE),
        anchor_dir.join(anchor::OPERATOR_PIN_FILE),
        anchor_dir.join(anchor::REGISTRY_FLOOR_FILE),
        app_data.join(prov::TRUST_DIR).join(prov::KEYS_DIR).join("builder.json"),
    ];
    let before: Vec<Vec<u8>> = watched.iter().map(|p| std::fs::read(p).expect("read")).collect();

    let outcome = install::settle_existing(&anchor_dir, || {
        install::verify_as_current_account(&app_data, &machine_root)
    });
    let text = refusal_text(outcome);
    assert!(text.contains("ALREADY installed"), "{text}");
    assert!(text.contains("does not verify"), "{text}");
    assert!(text.contains("NOTHING WAS CHANGED"), "{text}");
    assert!(text.contains(&anchor_dir.display().to_string()), "{text}");
    // And the reason is the CUSTODY one — the launch-time check, not merely the digests: this
    // store's files are all intact, so a verifier that skipped custody would have passed it.
    assert!(
        text.contains("CAN create files") || text.contains("running as root"),
        "the refusal is not about who can write the anchor: {text}"
    );

    let after: Vec<Vec<u8>> = watched.iter().map(|p| std::fs::read(p).expect("read")).collect();
    assert_eq!(before, after, "a refused anchor was modified");
}

// =================================================================================================
// The halves that run as the desktop account
// =================================================================================================

fn mode_of(path: &Path) -> u32 {
    std::fs::symlink_metadata(path).expect("stat").mode() & 0o7777
}

/// Delivery copies exactly the minted store, owner-only, and refuses an occupied destination;
/// rollback takes it away again.
#[test]
fn delivery_copies_the_minted_store_owner_only_and_never_over_an_existing_one() {
    const NAME: &str = "delivery_copies_the_minted_store_owner_only_and_never_over_an_existing_one";
    if prerequisites::running_as_root() {
        prerequisites::skip(
            NAME,
            prerequisites::TAG_NOT_ROOT,
            "delivery is the half that runs as the desktop account and refuses root by design",
        );
        return;
    }
    let tmp = tempfile::tempdir().expect("a temporary directory");
    let source = prov::mint_store_without_custody_proof(
        &tmp.path().join("minted"),
        &tmp.path().join("anchor"),
        None,
    )
    .expect("mint a fixture")
    .trust_dir;
    // Something that is NOT part of a provisioned store must not ride along.
    std::fs::write(source.join(prov::KEYS_DIR).join("operator-root.json"), "{}").expect("plant");
    std::fs::write(source.join("stowaway"), "x").expect("plant");

    // The application data directory does not exist yet: a real install runs before the
    // application has ever started.
    let app_data = tmp.path().join("home").join("data");
    let trust = install::deliver_as_current_account(&source, &app_data).expect("deliver");
    assert_eq!(trust, app_data.join(prov::TRUST_DIR));

    let mut delivered = Vec::new();
    for dir in [trust.clone(), trust.join(prov::KEYS_DIR), trust.join(prov::ARTIFACTS_DIR)] {
        assert_eq!(mode_of(&dir), 0o700, "{}", dir.display());
        for entry in std::fs::read_dir(&dir).expect("list") {
            let path = entry.expect("entry").path();
            if path.is_file() {
                assert_eq!(mode_of(&path), 0o600, "{}", path.display());
                let relative = path.strip_prefix(&trust).expect("inside").to_path_buf();
                assert_eq!(
                    std::fs::read(&path).expect("read"),
                    std::fs::read(source.join(&relative)).expect("read"),
                    "{} differs from what was minted",
                    relative.display()
                );
                delivered.push(relative);
            }
        }
    }
    assert_eq!(delivered.len(), prov::RETAINED_AUTHORITIES.len() + 2, "{delivered:?}");
    assert!(!trust.join("stowaway").exists(), "a file the mint never wrote was delivered");
    assert!(
        !trust.join(prov::KEYS_DIR).join("operator-root.json").exists(),
        "an operator-root key file was delivered"
    );
    let leftovers: Vec<_> = std::fs::read_dir(&app_data)
        .expect("list")
        .map(|e| e.expect("entry").file_name())
        .collect();
    assert_eq!(leftovers, vec![std::ffi::OsString::from(prov::TRUST_DIR)], "staging was left");

    // A second delivery finds the path occupied and refuses, leaving the first intact.
    let again = install::deliver_as_current_account(&source, &app_data);
    assert!(matches!(again, Err(ProvisionError::Corrupt { .. })), "{again:?}");
    assert!(trust.join(prov::POSTURE_FILE).is_file());

    install::rollback_as_current_account(&app_data).expect("rollback");
    assert!(!trust.exists(), "rollback left the store");
    assert!(app_data.is_dir(), "rollback removed more than the store");
}

// =================================================================================================
// The construction, for real — root only
// =================================================================================================

/// Run `program` as `user`: its uid, its gid, nothing else.
fn as_user(user: &install::DesktopUser, program: &Path, args: &[&OsStr]) -> Output {
    Command::new(program)
        .args(args)
        .uid(user.uid)
        .gid(user.gid)
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .current_dir("/")
        .output()
        .unwrap_or_else(|e| panic!("could not run {} as uid {}: {e}", program.display(), user.uid))
}

/// `sh -c <script> sh <args…>` as `user`. Paths travel as positional parameters, never
/// interpolated into the script.
fn sh_as(user: &install::DesktopUser, script: &str, paths: &[&Path]) -> Output {
    let mut args: Vec<&OsStr> = vec![OsStr::new("-c"), OsStr::new(script), OsStr::new("sh")];
    args.extend(paths.iter().map(|p| p.as_os_str()));
    as_user(user, Path::new("/bin/sh"), &args)
}

fn run_installer(helper: &Path, user: &str, app_data: &Path, machine_root: &Path) -> Output {
    Command::new(helper)
        .args(["--user", user, "--app-data"])
        .arg(app_data)
        .arg("--machine-root")
        .arg(machine_root)
        .output()
        .expect("run the installer")
}

/// Identity, owner, mode and content of every path, so "nothing changed" is a comparison.
fn snapshot(paths: &[PathBuf]) -> Vec<String> {
    paths
        .iter()
        .map(|path| match std::fs::symlink_metadata(path) {
            Ok(meta) => {
                let content = if meta.is_file() {
                    prov::sha256_hex(&std::fs::read(path).expect("read"))
                } else {
                    let mut names: Vec<String> = match std::fs::read_dir(path) {
                        Ok(listing) => listing
                            .map(|e| e.expect("entry").file_name().to_string_lossy().to_string())
                            .collect(),
                        Err(_) => Vec::new(),
                    };
                    names.sort();
                    names.join(",")
                };
                format!(
                    "{} ino={} uid={} gid={} mode={:o} content={content}",
                    path.display(),
                    meta.ino(),
                    meta.uid(),
                    meta.gid(),
                    meta.mode(),
                )
            }
            Err(e) => format!("{} MISSING ({e})", path.display()),
        })
        .collect()
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
    out.push(dir.to_path_buf());
    let mut entries: Vec<PathBuf> =
        std::fs::read_dir(dir).expect("list").map(|e| e.expect("entry").path()).collect();
    entries.sort();
    for path in entries {
        if std::fs::symlink_metadata(&path).expect("stat").is_dir() {
            walk(&path, out);
        } else {
            out.push(path);
        }
    }
}

fn set_mode(path: &Path, mode: u32) {
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).expect("chmod");
}

struct Scratch(PathBuf);
impl Drop for Scratch {
    fn drop(&mut self) {
        match std::fs::remove_dir_all(&self.0) {
            Ok(()) => println!("CLEANUP removed {}", self.0.display()),
            Err(e) => println!("CLEANUP FAILED for {}: {e} — remove it by hand", self.0.display()),
        }
    }
}

/// What the engine is asked: resolve the pin and load the registry the production way.
const ENGINE_PROBE: &str = "\
import os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from bro_signature import load_trusted_keys, resolve_operator_root_pin
root = pathlib.Path(sys.argv[2]) / 'registry'
pin = resolve_operator_root_pin(env=os.environ, root=root)
keys = load_trusted_keys(root=root, env=os.environ)
print('ENGINE-ACCEPTED uid=%d pin=%s keys=%d' % (os.geteuid(), pin, len(keys)))
";

/// The reader that matters is not this crate. `engine/runtime/bro_signature.py` is what reads
/// the pin in production, and it has its own custody rule — one the existing cross-language
/// proof has to switch off with `BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE`, because the anchor it
/// tests is one its own account wrote. Here the real engine is run AS THE DESKTOP UID against
/// the root-installed anchor with **no acknowledgement in its environment at all**, and must
/// accept it. Then the same program is run against a copy of that anchor the desktop account
/// made for itself, and must refuse — otherwise the acceptance says nothing.
fn engine_accepts_the_anchor_on_its_merits(
    test: &str,
    user: &install::DesktopUser,
    anchor_dir: &Path,
    home: &Path,
) {
    let mut repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for _ in 0..4 {
        repo = repo.parent().expect("four levels below the repository root").to_path_buf();
    }
    let runtime = repo.join("engine").join("runtime");
    let engine = |anchor: &Path| {
        Command::new("python3")
            .arg("-B")
            .arg("-c")
            .arg(ENGINE_PROBE)
            .arg(&runtime)
            .arg(anchor)
            .uid(user.uid)
            .gid(user.gid)
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("BRO_OPERATOR_ROOT_PUBKEY_FILE", anchor.join(anchor::OPERATOR_PIN_FILE))
            .env("BRO_OPERATOR_REGISTRY_MIN_FILE", anchor.join(anchor::REGISTRY_FLOOR_FILE))
            .current_dir("/")
            .output()
            .expect("run python3 as the desktop account")
    };

    let readable = sh_as(
        user,
        "test -r \"$1/bro_signature.py\" && python3 -c 'import cryptography'",
        &[&runtime],
    );
    if !readable.status.success() {
        prerequisites::skip(
            test,
            prerequisites::TAG_ENGINE_AS_DESKTOP_UID,
            &format!(
                "uid {} cannot read {} or has no python3 with `cryptography`, so the engine \
                 cannot be run as the desktop account against the installed anchor",
                user.uid,
                runtime.display()
            ),
        );
        return;
    }

    let out = engine(anchor_dir);
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    assert!(
        out.status.success(),
        "the ENGINE refused the installed anchor as uid {}:\n{}",
        user.uid,
        String::from_utf8_lossy(&out.stderr)
    );
    let pin = std::fs::read_to_string(anchor_dir.join(anchor::OPERATOR_PIN_FILE)).expect("pin");
    assert!(
        stdout.starts_with(&format!("ENGINE-ACCEPTED uid={} pin={} ", user.uid, pin.trim())),
        "{stdout}"
    );
    println!("{}  (bro_signature, as the desktop uid, no acknowledgement set)", stdout.trim());

    // The control: the same bytes, in a directory the desktop account owns.
    let own = home.join("self-owned-anchor");
    let copy = sh_as(user, "cp -r \"$1\" \"$2\"", &[anchor_dir, &own]);
    assert!(copy.status.success(), "{copy:?}");
    let out = engine(&own);
    let err = String::from_utf8_lossy(&out.stderr).to_string();
    assert!(
        !out.status.success(),
        "the engine accepted an anchor the desktop account owns, with no acknowledgement — so \
         its acceptance of the installed one proves nothing"
    );
    assert!(err.contains("SELF_OWNED"), "the engine refused for some other reason:\n{err}");
    println!(
        "ENGINE REFUSES the same bytes in a directory uid {} owns: {}",
        user.uid,
        err.lines().last().unwrap_or("").chars().take(200).collect::<String>()
    );
    sh_as(user, "rm -rf \"$1\"", &[&own]);
}

#[test]
#[ignore = "needs root: it mints a real root-owned anchor in a temporary directory. Build with \
            --no-run, then run the test binary under sudo with --ignored --exact <this name> \
            --nocapture"]
fn root_installs_an_anchor_the_desktop_uid_verifies_and_cannot_touch() {
    const NAME: &str = "root_installs_an_anchor_the_desktop_uid_verifies_and_cannot_touch";
    if euid() != 0 {
        prerequisites::skip(
            NAME,
            prerequisites::TAG_ROOT_INSTALLER,
            &format!(
                "this process is uid {}, and only root can create an anchor owned by a uid the \
                 desktop account is not",
                euid()
            ),
        );
        return;
    }

    // ---- the fixture: a desktop account that already exists, and a directory of our own ----
    let name = std::env::var("BROPS_TEST_DESKTOP_USER")
        .ok()
        .or_else(|| std::env::var("SUDO_USER").ok())
        .filter(|n| !n.is_empty() && n != "root")
        .unwrap_or_else(|| "nobody".to_string());
    let user = install::resolve_user(&install::read_passwd().expect("passwd"), &name)
        .unwrap_or_else(|e| panic!("the desktop account for this test: {e}"));
    println!("DESKTOP ACCOUNT {} uid={} gid={}", user.name, user.uid, user.gid);

    let production = PathBuf::from(anchor::POSIX_MACHINE_ROOT);
    let mut production_paths = vec![production.clone()];
    if production.is_dir() {
        production_paths.clear();
        walk(&production, &mut production_paths);
    }
    let production_before = snapshot(&production_paths);

    let base = PathBuf::from(
        std::env::var("BROPS_TEST_ROOT_BASE").unwrap_or_else(|_| "/run".to_string()),
    );
    let base_meta = std::fs::metadata(&base).expect("the base directory");
    assert!(
        base_meta.uid() == 0 && base_meta.mode() & 0o022 == 0,
        "{} must be root-owned and not group/other-writable to hold a test anchor",
        base.display()
    );
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock")
        .subsec_nanos();
    let scratch = base.join(format!("brops-posix-install-test-{}-{nanos}", std::process::id()));
    assert!(!scratch.starts_with(&production) && !production.starts_with(&scratch));
    assert!(!scratch.exists(), "{} already exists", scratch.display());
    prov::create_dir_all_mode(&scratch, 0o755).expect("create the scratch directory");
    let _cleanup = Scratch(scratch.clone());
    println!("SCRATCH {}", scratch.display());

    // The installer has to be somewhere the desktop account can execute. Prefer a copy inside
    // the scratch directory (what a package does: /usr/bin); fall back to the build output
    // when the base is mounted noexec, as /run is.
    let copied = scratch.join("bin").join("brops_install_anchor");
    prov::create_dir_all_mode(copied.parent().expect("bin"), 0o755).expect("bin dir");
    std::fs::copy(INSTALLER, &copied).expect("copy the installer");
    set_mode(&copied, 0o755);
    let runs_as_user = |exe: &Path| {
        Command::new(exe)
            .arg("--help")
            .uid(user.uid)
            .gid(user.gid)
            .current_dir("/")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    };
    let helper = if runs_as_user(&copied) {
        copied.clone()
    } else if runs_as_user(Path::new(INSTALLER)) {
        PathBuf::from(INSTALLER)
    } else {
        panic!(
            "uid {} can execute neither {} (is {} mounted noexec?) nor {}. Set \
             BROPS_TEST_ROOT_BASE to a root-owned 0755 directory on an exec filesystem, or \
             BROPS_TEST_DESKTOP_USER to an account that can reach the build output",
            user.uid,
            copied.display(),
            base.display(),
            INSTALLER
        );
    };
    println!("HELPER {}", helper.display());

    let home = scratch.join("home");
    std::fs::create_dir(&home).expect("home");
    std::os::unix::fs::chown(&home, Some(user.uid), Some(user.gid)).expect("chown home");
    let app_data = home.join("share").join("studio.menq.brops");
    let machine_root = scratch.join("machine");
    let anchor_dir = anchor::anchor_dir(&machine_root);
    let trust = app_data.join(prov::TRUST_DIR);

    // The harness itself, controlled: this uid really is running, really has no extra groups,
    // and really CAN write where it is allowed to. Without this every "denied" below could be
    // a shell that never started.
    let control = sh_as(&user, "id -u; id -G; : > \"$1/control\" && echo wrote", &[&home]);
    let control_out = String::from_utf8_lossy(&control.stdout).to_string();
    assert!(control.status.success(), "the control write failed: {control:?}");
    assert_eq!(
        control_out.lines().map(str::to_string).collect::<Vec<_>>(),
        vec![user.uid.to_string(), user.gid.to_string(), "wrote".to_string()],
        "the child is not exactly uid {} with the single group {}",
        user.uid,
        user.gid
    );
    assert_eq!(std::fs::metadata(home.join("control")).expect("control").uid(), user.uid);
    std::fs::remove_file(home.join("control")).expect("remove the control file");
    println!("CONTROL uid {} wrote where it is allowed to; groups: {}", user.uid, user.gid);

    // ---- refusals that must write nothing ---------------------------------------------------
    // (1) a machine root under a directory the desktop account owns.
    let reachable_root = home.join("machine");
    let out = run_installer(&helper, &user.name, &app_data, &reachable_root);
    let err = String::from_utf8_lossy(&out.stderr).to_string();
    println!("REFUSED (machine root under the account's own directory): {}", err.trim());
    assert_eq!(out.status.code(), Some(1), "{err}");
    assert!(err.contains(&format!("owned by uid {}", user.uid)), "{err}");
    assert!(!reachable_root.exists() && !app_data.exists(), "a refused install wrote");

    // (2) a store that cannot be delivered: the data directory's parent is root's, so the
    //     desktop-uid child cannot create it. The mint has happened by then, so this is the
    //     rollback: nothing may be left of it.
    let undeliverable = scratch.join("rootonly").join("data");
    prov::create_dir_all_mode(undeliverable.parent().expect("parent"), 0o755).expect("rootonly");
    let out = run_installer(&helper, &user.name, &undeliverable, &machine_root);
    let err = String::from_utf8_lossy(&out.stderr).to_string();
    println!("REFUSED (undeliverable store, rolled back): {}", err.trim());
    assert_eq!(out.status.code(), Some(1), "{err}");
    assert!(err.contains("FAILED") && err.contains("was removed again"), "{err}");
    assert!(!machine_root.exists(), "a failed install left its machine root behind");
    assert!(!undeliverable.exists(), "a failed install left a data directory behind");

    // (3) the library called directly, for the refusals the binary cannot be steered into
    //     without a real account's home being at stake: a machine root that is somebody's
    //     home (a fictional somebody, appended to the real account list), and uid 0 as the
    //     "desktop account".
    let request = |desktop: &install::DesktopUser| install::InstallRequest {
        user: desktop.clone(),
        app_data_dir: app_data.clone(),
        machine_root: machine_root.clone(),
        helper: helper.clone(),
    };
    let squatted = format!(
        "{}\nsquatter:x:4242:4242::{}:/bin/sh\n",
        install::read_passwd().expect("passwd"),
        machine_root.display()
    );
    let text = refusal_text(install::install_anchor(&request(&user), &squatted));
    println!(
        "REFUSED (machine root is an account's home): {}…",
        text.chars().take(300).collect::<String>()
    );
    assert!(text.contains("\"squatter\"") && text.contains("collides with the home"), "{text}");
    assert!(!machine_root.exists() && !app_data.exists(), "a refused install wrote");

    let root_as_desktop =
        install::DesktopUser { name: "root".into(), uid: 0, gid: 0, home: "/root".into() };
    let passwd = install::read_passwd().expect("passwd");
    let text = refusal_text(install::install_anchor(&request(&root_as_desktop), &passwd));
    println!("REFUSED (uid 0 as the desktop account): {text}");
    assert!(text.contains("the desktop account is uid 0"), "{text}");
    assert!(!machine_root.exists() && !app_data.exists(), "a refused install wrote");

    // (4) a data directory the application would spell differently.
    let out = run_installer(&helper, &user.name, Path::new("relative/data"), &machine_root);
    let err = String::from_utf8_lossy(&out.stderr).to_string();
    println!("REFUSED (relative --app-data): {}", err.trim());
    assert_eq!(out.status.code(), Some(1), "{err}");
    assert!(err.contains("--app-data must be an absolute path"), "{err}");
    assert!(!machine_root.exists(), "a refused install wrote");

    // (5) the halves that run AS the desktop account refuse to run as root: root must never
    //     be the one writing inside that account's tree.
    let never = scratch.join("root-must-not-deliver-here");
    for args in [
        vec![OsStr::new("deliver"), OsStr::new("--from"), home.as_os_str(), OsStr::new("--app-data"), never.as_os_str()],
        vec![OsStr::new("rollback"), OsStr::new("--app-data"), never.as_os_str()],
    ] {
        let out = Command::new(&helper).args(&args).output().expect("run the helper as root");
        let err = String::from_utf8_lossy(&out.stderr).to_string();
        assert_eq!(out.status.code(), Some(1), "{err}");
        assert!(err.contains("AS THE DESKTOP ACCOUNT and this process is root"), "{err}");
        assert!(!never.exists(), "root ran `{}` and wrote", args[0].to_string_lossy());
        println!("REFUSED (root running `{}`): … runs AS THE DESKTOP ACCOUNT …", args[0].to_string_lossy());
    }

    // (6) the data directory already holds a `trust` that no anchor vouches for. Refused
    //     BEFORE the mint — not minted, failed at delivery and rolled back — and left alone.
    let occupied = home.join("occupied");
    let stray = occupied.join(prov::TRUST_DIR).join("somebody-elses-file");
    let made = sh_as(
        &user,
        "mkdir -p \"$1/trust\" && printf kept > \"$1/trust/somebody-elses-file\"",
        &[&occupied],
    );
    assert!(made.status.success(), "{made:?}");
    let out = run_installer(&helper, &user.name, &occupied, &machine_root);
    let err = String::from_utf8_lossy(&out.stderr).to_string();
    println!("REFUSED (occupied trust path): {}", err.trim());
    assert_eq!(out.status.code(), Some(1), "{err}");
    assert!(err.contains("already holds something that is not a provisioned store"), "{err}");
    assert!(!err.contains("FAILED"), "it was refused only after the mint: {err}");
    assert!(!machine_root.exists(), "a refused install wrote");
    assert_eq!(std::fs::read(&stray).expect("the stray file"), b"kept");

    // (7) a store that IS delivered and then cannot be proved. No correct build produces this
    //     — which is exactly why it needs a helper that lies: one that delivers for real and
    //     then fails the verification. The delivered store must be taken back, as the desktop
    //     account, along with the anchor.
    let liar_dir = tempfile::tempdir().expect("a directory for the lying helper");
    set_mode(liar_dir.path(), 0o755);
    let liar = liar_dir.path().join("lying-helper");
    std::fs::write(
        &liar,
        format!(
            "#!/bin/sh\ncase \"$1\" in\n  verify) echo 'the lying helper refuses' >&2; exit 1 ;;\n  \
             *) exec '{}' \"$@\" ;;\nesac\n",
            helper.display()
        ),
    )
    .expect("write the lying helper");
    set_mode(&liar, 0o755);
    let unproved_data = home.join("unproved");
    let unproved = install::InstallRequest {
        user: user.clone(),
        app_data_dir: unproved_data.clone(),
        machine_root: machine_root.clone(),
        helper: liar.clone(),
    };
    let text = refusal_text(install::install_anchor(&unproved, &passwd));
    println!("REFUSED (delivered, then unprovable): {}…", text.chars().take(420).collect::<String>());
    assert!(text.contains("the lying helper refuses"), "{text}");
    assert!(text.contains("was removed again"), "{text}");
    assert!(!machine_root.exists(), "an unproved install left its anchor behind");
    assert!(
        !unproved_data.join(prov::TRUST_DIR).exists(),
        "an unproved install left the delivered store behind"
    );

    // ---- the install ------------------------------------------------------------------------
    let out = run_installer(&helper, &user.name, &app_data, &machine_root);
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    assert!(
        out.status.success(),
        "the install failed: {}\n{stdout}",
        String::from_utf8_lossy(&out.stderr)
    );
    println!("INSTALL OUTPUT\n{stdout}");
    assert!(stdout.contains("MINTED a new trust anchor"), "{stdout}");
    assert!(stdout.contains(&format!("{} uid={}", install::VERIFIED_MARKER, user.uid)), "{stdout}");

    // Root's side: everything under the machine root is root's, 0755 / 0644, and the handoff
    // directory is gone.
    let mut machine_paths = Vec::new();
    walk(&machine_root, &mut machine_paths);
    for path in &machine_paths {
        let meta = std::fs::symlink_metadata(path).expect("stat");
        assert!(!meta.file_type().is_symlink(), "{}", path.display());
        assert_eq!((meta.uid(), meta.gid()), (0, 0), "{} is not root's", path.display());
        let wanted = if meta.is_dir() { 0o755 } else { 0o644 };
        assert_eq!(meta.mode() & 0o7777, wanted, "{}", path.display());
    }
    let top: Vec<_> = std::fs::read_dir(&machine_root)
        .expect("list")
        .map(|e| e.expect("entry").file_name())
        .collect();
    assert_eq!(top, vec![std::ffi::OsString::from(anchor::ANCHOR_DIR_NAME)], "handoff was left");
    for file in [anchor::OPERATOR_PIN_FILE, anchor::REGISTRY_FLOOR_FILE, anchor::MANIFEST_FILE] {
        assert!(anchor_dir.join(file).is_file(), "{file} is missing");
    }
    // The operator-root private half is nowhere: not in the store, not under the machine root.
    assert!(!trust.join(prov::KEYS_DIR).join("operator-root.json").exists());
    for path in &machine_paths {
        let name = path.file_name().expect("name").to_string_lossy().to_string();
        assert!(!name.contains("operator-root.json"), "{}", path.display());
    }

    // The desktop account's side: the store is the account's own, owner-only.
    let mut store_paths = Vec::new();
    walk(&home.join("share"), &mut store_paths);
    assert!(store_paths.len() > prov::RETAINED_AUTHORITIES.len() + 4, "{store_paths:?}");
    for path in &store_paths {
        let meta = std::fs::symlink_metadata(path).expect("stat");
        assert_eq!((meta.uid(), meta.gid()), (user.uid, user.gid), "{}", path.display());
        let wanted = if meta.is_dir() { 0o700 } else { 0o600 };
        assert_eq!(meta.mode() & 0o7777, wanted, "{}", path.display());
    }
    println!(
        "OWNERSHIP {} paths under the machine root are root:root 0755/0644; {} paths under the \
         data directory are {}:{} 0700/0600",
        machine_paths.len(),
        store_paths.len(),
        user.uid,
        user.gid
    );

    // ---- (a) launch-time verification passes AS the desktop uid ------------------------------
    let verify_args: Vec<&OsStr> = vec![
        OsStr::new("verify"),
        OsStr::new("--app-data"),
        app_data.as_os_str(),
        OsStr::new("--machine-root"),
        machine_root.as_os_str(),
    ];
    let verified = as_user(&user, &helper, &verify_args);
    let report = String::from_utf8_lossy(&verified.stdout).to_string();
    assert!(
        verified.status.success(),
        "launch-time verification FAILED as uid {}: {}",
        user.uid,
        String::from_utf8_lossy(&verified.stderr)
    );
    assert_eq!(install::child_report_refusal(&report, user.uid), None, "{report}");
    println!("VERIFIED AS uid {}\n{report}", user.uid);

    // The same question asked by ROOT is refused — which is why root's answer was never used.
    let as_root = Command::new(&helper).args(&verify_args).output().expect("verify as root");
    let root_err = String::from_utf8_lossy(&as_root.stderr).to_string();
    assert_eq!(as_root.status.code(), Some(1), "{root_err}");
    assert!(
        root_err.contains("CAN create files") || root_err.contains("running as root"),
        "{root_err}"
    );
    let shown: String = root_err.chars().take(220).collect();
    println!("VERIFY AS ROOT is refused: {shown}…");

    // A helper that exits 0 is not a proof. `/bin/true` says nothing and `/bin/echo` says
    // something that is not a report from this uid; the installer believes neither, even
    // though the anchor they were asked about is the good one installed above.
    for (fake, needle) in [("/bin/true", "reported nothing"), ("/bin/echo", "did not run as")] {
        let believed = install::prove_for_desktop_user(
            &install::InstallRequest { helper: PathBuf::from(fake), ..request(&user) },
            0,
        );
        let text = refusal_text(believed.map(|proof| proof.report));
        assert!(text.contains(needle), "{fake}: {text}");
        println!("NOT BELIEVED: a helper that is {fake} — … {needle} …");
    }

    // ---- (a′) the ENGINE accepts it as the desktop uid, with no acknowledgement ---------------
    engine_accepts_the_anchor_on_its_merits(NAME, &user, &anchor_dir, &home);

    // ---- (b) the desktop uid cannot write, rename or replace any of it ----------------------
    let pin = anchor_dir.join(anchor::OPERATOR_PIN_FILE);
    let floor = anchor_dir.join(anchor::REGISTRY_FLOOR_FILE);
    let manifest = anchor_dir.join(anchor::MANIFEST_FILE);
    let registry_dir = anchor_dir.join(prov::REGISTRY_ROOT_DIR);
    let registry = registry_dir.join("config").join("trusted-keys.json");
    assert!(registry.is_file(), "the registry is not where the engine reads it");
    let mut guarded = machine_paths.clone();
    guarded.push(scratch.clone());
    let before = snapshot(&guarded);

    let mut attempts: Vec<(&str, &str, Vec<&Path>)> = Vec::new();
    for file in [pin.as_path(), floor.as_path(), manifest.as_path(), registry.as_path()] {
        attempts.push(("overwrite", ": > \"$1\"", vec![file]));
        attempts.push(("append to", "printf x >> \"$1\"", vec![file]));
        attempts.push(("delete", "rm -f \"$1\"", vec![file]));
        attempts.push(("rename aside", "mv \"$1\" \"$1.aside\"", vec![file]));
        attempts.push((
            "replace by rename",
            "printf forged > \"$2/forged\" && mv -f \"$2/forged\" \"$1\"",
            vec![file, home.as_path()],
        ));
        attempts.push(("replace by symlink", "ln -sf /etc/hostname \"$1\"", vec![file]));
        attempts.push(("chmod", "chmod 0666 \"$1\"", vec![file]));
    }
    for dir in [anchor_dir.as_path(), registry_dir.as_path(), machine_root.as_path()] {
        attempts.push(("create a file in", ": > \"$1/planted\"", vec![dir]));
        attempts.push(("create a directory in", "mkdir \"$1/planted.d\"", vec![dir]));
        attempts.push(("rename aside", "mv \"$1\" \"$1.aside\"", vec![dir]));
        attempts.push(("delete", "rm -rf \"$1\"", vec![dir]));
        attempts.push(("chmod", "chmod 0777 \"$1\"", vec![dir]));
        attempts.push((
            "replace by rename",
            "rm -rf \"$2/forged.d\"; mkdir \"$2/forged.d\" && mv -T \"$2/forged.d\" \"$1\"",
            vec![dir, home.as_path()],
        ));
    }
    // And the directory that HOLDS the machine root: where the anchor's whole path could be
    // rebuilt if the real one were renamed.
    attempts.push(("create a file in", ": > \"$1/planted\"", vec![scratch.as_path()]));
    attempts.push(("create a directory in", "mkdir \"$1/machine2\"", vec![scratch.as_path()]));

    for (what, script, paths) in &attempts {
        let out = sh_as(&user, script, paths);
        let err = String::from_utf8_lossy(&out.stderr).to_string();
        assert!(
            !out.status.success(),
            "uid {} COULD {what} {}: `{script}` succeeded",
            user.uid,
            paths[0].display()
        );
        assert!(
            err.contains("Permission denied") || err.contains("Operation not permitted"),
            "uid {} failed to {what} {} for a reason that is not a denial: {err}",
            user.uid,
            paths[0].display()
        );
        println!("DENIED uid {} {what} {} -> {}", user.uid, paths[0].display(), err.trim());
    }
    println!("{} attempts as uid {}, every one denied by the kernel", attempts.len(), user.uid);
    assert_eq!(before, snapshot(&guarded), "an attempt was denied and still changed something");
    let _ = std::fs::remove_dir_all(home.join("forged.d"));
    let _ = std::fs::remove_file(home.join("forged"));

    // ---- a second run is idempotent: it verifies, and changes nothing ------------------------
    let mut all_paths = machine_paths.clone();
    all_paths.extend(store_paths.iter().cloned());
    let settled = snapshot(&all_paths);
    let out = run_installer(&helper, &user.name, &app_data, &machine_root);
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    assert!(stdout.contains("ALREADY installed and it verifies"), "{stdout}");
    assert_eq!(settled, snapshot(&all_paths), "a second run changed the install");
    println!("SECOND RUN: {}", stdout.lines().next().unwrap_or(""));

    // ---- an existing anchor that does NOT verify is refused and never overwritten -----------
    let must_refuse = |label: &str, needle: &str| {
        let frozen = snapshot(&all_paths);
        let out = run_installer(&helper, &user.name, &app_data, &machine_root);
        let err = String::from_utf8_lossy(&out.stderr).to_string();
        assert_eq!(out.status.code(), Some(1), "{label}: the installer accepted it\n{err}");
        assert!(err.contains("ALREADY installed") && err.contains("does not verify"), "{err}");
        assert!(err.contains("NOTHING WAS CHANGED"), "{label}: {err}");
        assert!(err.contains(needle), "{label}: expected {needle:?} in\n{err}");
        assert_eq!(frozen, snapshot(&all_paths), "{label}: a refused anchor was modified");
        println!("REFUSED ({label}): … {needle} …");
    };

    // (i) the store was edited after install: the manifest's digest catches it, as the uid.
    let posture = trust.join(prov::POSTURE_FILE);
    let original = std::fs::read(&posture).expect("posture");
    let mut edited = original.clone();
    edited.push(b'!');
    std::fs::write(&posture, &edited).expect("tamper");
    must_refuse("a store file edited after install", "no longer matches the digest");
    std::fs::write(&posture, &original).expect("restore");

    // (ii) the anchor directory was loosened to group-writable. The desktop-uid child has no
    //      supplementary groups, so only root's static measurement can see this one.
    set_mode(&anchor_dir, 0o775);
    must_refuse("a group-writable anchor directory", "its mode is 0775");
    set_mode(&anchor_dir, 0o755);

    // (iii) the anchor directory was opened to everyone. Asked of the desktop-uid child
    //       directly, so this is the child's own verdict and not root's static one.
    set_mode(&anchor_dir, 0o777);
    let open = as_user(&user, &helper, &verify_args);
    let open_err = String::from_utf8_lossy(&open.stderr).to_string();
    assert_eq!(open.status.code(), Some(1), "a world-writable anchor verified: {open:?}");
    assert!(open_err.contains("CAN create files"), "{open_err}");
    println!("VERIFY AS uid {} on a 0777 anchor is refused: … CAN create files …", user.uid);
    set_mode(&anchor_dir, 0o755);

    // (iv) the pin was handed to the desktop account.
    std::os::unix::fs::chown(&pin, Some(user.uid), Some(user.gid)).expect("chown pin");
    must_refuse("a pin owned by the desktop account", &format!("owned by uid {}", user.uid));
    std::os::unix::fs::chown(&pin, Some(0), Some(0)).expect("chown pin back");

    // Every tamper undone, the same anchor verifies again — so each refusal above was about
    // the tamper and nothing else.
    let out = run_installer(&helper, &user.name, &app_data, &machine_root);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    assert_eq!(settled, snapshot(&all_paths), "restoring the tampers did not restore the install");
    println!("RESTORED: the anchor verifies again, identical to the install");

    assert_eq!(
        production_before,
        snapshot(&production_paths),
        "the production machine root was touched"
    );
    println!("PRODUCTION ROOT {} untouched", production.display());
}
