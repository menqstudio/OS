//! The one property O-2 reduces to, tested against the operating system rather than against a
//! description of it.
//!
//! `provision.rs` covers the mint and the verifier through the unsealed entry points, because
//! [`brops_provision::anchor::seal`] is **one-way for the account that applies it** and a test
//! that sealed a fresh directory every run would leave one on the machine that nothing running
//! as the test's own account could ever remove. This file covers what that file deliberately
//! does not: whether the location is actually out of reach.
//!
//! One check here needs a genuinely sealed directory, which no platform lets a process
//! manufacture out of nothing: on Windows it is a fixed `%TEMP%` path sealed once ever, and on
//! POSIX it must be a directory owned by another uid, because an owner may always `chmod` what
//! it owns. `tests/prerequisites/mod.rs` supplies whichever exists and SKIPS — visibly, and as
//! a hard failure under CI — naming exactly what is missing when neither does.
//!
//! **Nothing in this file is `#[cfg]`-ed out any more.** Two tests used to be `#[cfg(windows)]`,
//! so on Linux they were not skipped but absent, and the nine that remained all measured a
//! writable directory: they exercised only `prove_unwritable`'s early-return refusal, while
//! `can_delete`'s POSIX branch, `posix_ownership` and `posix_euid` had never executed on any
//! machine. A Linux run went green and told nobody anything. Every decision those functions
//! make is now a pure function tested on every platform, and only the syscalls that feed them
//! need a fixture.
//!
//! The positive end to end — a sealed anchor, the real `bro_signature` accepting its pin with
//! `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` unset, and the real `bro_audit_log.verify()` refusing a
//! forgery built after every write was denied — is `audit-signer/tests/anchor_end_to_end.rs`.

use std::path::{Path, PathBuf};

use brops_provision as prov;
use prov::anchor;

mod prerequisites;

fn is_custody(err: &prov::ProvisionError) -> bool {
    matches!(err, prov::ProvisionError::Custody { .. })
}

/// A location that is definitely writable by this account, with a machine root of its own.
fn writable_root() -> (tempfile::TempDir, PathBuf, PathBuf) {
    let temp = tempfile::tempdir().expect("temp dir");
    let machine_root = temp.path().join("machine");
    let app_data = temp.path().join("app");
    std::fs::create_dir_all(&machine_root).unwrap();
    std::fs::create_dir_all(&app_data).unwrap();
    (temp, machine_root, app_data)
}

// =================================================================================================
// Fail-closed: the three ways a custody question can go wrong
// =================================================================================================

/// An ABSENT anchor must never read as a denied one.
///
/// This is the same defect `an_absent_key_is_unmeasurable_and_never_counts_as_denied` guards in
/// `audit_signer.rs`, in the place it would do the most damage: if a missing directory answered
/// "this account cannot write it", a machine with no anchor at all would produce a *passing*
/// custody proof, and the strongest-looking evidence would come from the least-provisioned box.
#[test]
fn an_absent_anchor_is_unmeasurable_and_never_counts_as_denied() {
    let temp = tempfile::tempdir().unwrap();
    let err = anchor::prove_unwritable(&temp.path().join("nothing-here"))
        .expect_err("an absent anchor must not be reported as unwritable");
    assert!(is_custody(&err), "{err:?}");
    let text = err.to_string();
    assert!(text.contains("does not exist"), "{text}");
    assert!(text.contains("An absent anchor is not a denied one"), "{text}");
}

/// A plain directory this account owns is refused, and the refusal says what to change.
#[test]
fn a_directory_this_account_can_write_is_refused_by_name() {
    let temp = tempfile::tempdir().unwrap();
    let err = anchor::prove_unwritable(temp.path())
        .expect_err("a directory this account can write is not an anchor");
    assert!(is_custody(&err), "{err:?}");
    let text = err.to_string();
    assert!(text.contains("CAN create files in the trust anchor directory"), "{text}");
    // Not just "no": what to do about it.
    assert!(text.contains("OWNER RIGHTS"), "the refusal does not name the mechanism:\n{text}");
    assert!(text.contains("There is no fallback"), "{text}");
}

/// The probe file is removed again. A custody check that littered the anchor with its own
/// evidence would be one whose failure mode is a directory full of `.brops-custody-probe`.
#[test]
fn the_writability_probe_cleans_up_after_itself() {
    let temp = tempfile::tempdir().unwrap();
    let _ = anchor::prove_unwritable(temp.path());
    let left: Vec<_> = std::fs::read_dir(temp.path()).unwrap().map(|e| e.unwrap().path()).collect();
    assert!(left.is_empty(), "the probe left something behind: {left:?}");
}

// =================================================================================================
// The ancestor, which is the part a security descriptor cannot see
// =================================================================================================

/// **The regression test for the hole that nearly shipped this round.**
///
/// The first construction attempted here sealed `…\BroPS\trust-anchor` under a temporary
/// directory, refused every direct write to it — and was then renamed out of the way in one
/// call, because its GRANDparent granted `FILE_DELETE_CHILD`. A seal on the leaf is decoration
/// if any component above it can be moved aside and the whole path rebuilt.
///
/// So provisioning refuses the location BEFORE it writes anything, and this asserts it does.
/// `%TEMP%` is exactly the shape that fails: this account can open it for `DELETE`, so nothing
/// beneath it is out of reach.
#[test]
fn a_location_whose_ancestors_this_account_can_rename_is_refused_before_anything_is_written() {
    let (_temp, machine_root, _app) = writable_root();
    let dir = anchor::anchor_dir(&machine_root);
    let err = anchor::precheck_location(&dir, &machine_root)
        .expect_err("a machine root under %TEMP% has no ancestor holding it in place");
    assert!(is_custody(&err), "{err:?}");
    let text = err.to_string();
    assert!(text.contains("can delete or rename"), "{text}");
    assert!(
        text.contains("OUTSIDE the machine root"),
        "the refusal must name WHICH component and why sealing does not reach it:\n{text}"
    );
    assert!(text.contains("%ProgramData%"), "{text}");
}

/// And the production location passes the same check, on this machine, measured.
///
/// `C:\ProgramData` grants `BUILTIN\Users` `RX` and `WD,AD` — enough to create the product's
/// directory, never enough to delete or rename one. `/var/lib` is root-owned `0755` on every
/// distribution, which is the same shape. That is the whole reason the ancestor chain is out
/// of reach without provisioning touching it, so it is measured rather than assumed, and it
/// creates nothing lasting: the check only probes and cleans up.
///
/// **This used to be `#[cfg(windows)]`**, so on Linux it was not skipped, it was absent — and
/// `default_machine_root`'s POSIX answer had never been checked against a real filesystem by
/// anything. It runs everywhere now. The only prerequisite is that this process is not root,
/// for which no location on any machine is out of reach and the question is meaningless.
#[test]
fn the_production_machine_root_has_an_ancestor_this_account_cannot_rename() {
    const NAME: &str = "the_production_machine_root_has_an_ancestor_this_account_cannot_rename";
    if prerequisites::running_as_root() {
        prerequisites::skip(
            NAME,
            "this process is running as root, so every write probe succeeds and no ancestor \
             holds anything in place. Run the suite as an unprivileged account",
        );
        return;
    }
    let machine_root = anchor::default_machine_root().expect("a machine-wide root");
    anchor::precheck_location(&anchor::anchor_dir(&machine_root), &machine_root).unwrap_or_else(
        |e| {
            panic!(
                "the production anchor location {} is refused on this machine, so no first \
                 launch could establish an anchor here: {e}",
                machine_root.display()
            )
        },
    );
}

/// The POSIX machine root is not, and does not contain, and does not sit inside, any account's
/// home directory — decided against a real `/etc/passwd` shape, on every platform.
///
/// `/var/lib/brops` was the previous answer, and on a real Debian box it is already the home of
/// the `brops` system account the deployment runbook creates, so following the instructions
/// chowned a service account's home to root. The fixture below carries both collisions this
/// product's own instructions can produce.
#[test]
fn the_posix_machine_root_is_not_any_accounts_home_directory() {
    let passwd = "\
root:x:0:0:root:/root:/bin/bash\n\
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n\
gev:x:1000:1000:Gev:/home/gev:/bin/bash\n\
brops:x:998:998:BroPS service,,,:/var/lib/brops:/usr/sbin/nologin\n\
brops-anchor:x:997:997:BroPS anchor,,,:/var/lib/brops-anchor:/usr/sbin/nologin\n\
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n";
    let root = Path::new(anchor::POSIX_MACHINE_ROOT);
    assert_eq!(
        anchor::home_directory_collision(root, passwd),
        None,
        "{} collides with an account this deployment's own instructions create",
        root.display()
    );

    // The previous default did, and this is the collision the Debian box hit.
    assert_eq!(
        anchor::home_directory_collision(Path::new("/var/lib/brops"), passwd),
        Some(("brops".to_string(), PathBuf::from("/var/lib/brops"))),
    );
    // So does the account name this module's own remedy suggests.
    assert_eq!(
        anchor::home_directory_collision(Path::new("/var/lib/brops-anchor"), passwd),
        Some(("brops-anchor".to_string(), PathBuf::from("/var/lib/brops-anchor"))),
    );
    // Both directions: a root INSIDE a home, and a home inside the ROOT.
    assert!(anchor::home_directory_collision(Path::new("/home/gev/brops"), passwd).is_some());
    assert!(anchor::home_directory_collision(Path::new("/var/lib"), passwd).is_some());
    // `/nonexistent` means "this account has no home", not "its home is everywhere".
    assert_eq!(anchor::home_directory_collision(Path::new("/nonexistent-x"), passwd), None);
    // And the comparison is by PATH COMPONENT, not by string prefix — which is exactly why the
    // new root does not collide with `/var/lib/brops`.
    assert_eq!(anchor::home_directory_collision(Path::new("/var/lib/bropsX"), passwd), None);
}

// =================================================================================================
// A really sealed directory, and the OS really refusing
// =================================================================================================

/// The seal, as the operating system reports it — not as a DACL read-back describes it.
///
/// A descriptor read has to be right about ACE ordering, generic mappings, deny entries,
/// inheritance and the owner's implicit rights. `CreateFile` returning `ERROR_ACCESS_DENIED`
/// (or `open(2)` returning `EACCES`) is the same code path an attacker takes, and it is immune
/// to all of that.
///
/// **This used to be `#[cfg(windows)]`.** On Linux it was absent, so the only anchor the suite
/// ever measured there was a writable one, and `prove_unwritable`'s SUCCESS path had never run
/// on any machine. It runs on both platforms now, against whatever real out-of-reach directory
/// the platform can supply, and skips by name when there is none — see
/// `tests/prerequisites/mod.rs`.
#[test]
fn a_sealed_anchor_refuses_this_accounts_own_writes() {
    const NAME: &str = "a_sealed_anchor_refuses_this_accounts_own_writes";
    let Some(fixture) = prerequisites::sealed_anchor(NAME) else { return };
    let pin = &fixture.pin;
    let before = std::fs::read(pin).expect("the pin is still READABLE — read is what it keeps");

    for (what, result) in [
        ("overwrite the pin", std::fs::write(pin, b"rogue").err()),
        (
            "create a new file in the anchor",
            std::fs::write(fixture.dir.join("rogue.pub"), b"x").err(),
        ),
        ("delete the pin", std::fs::remove_file(pin).err()),
        ("remove the anchor directory", std::fs::remove_dir_all(&fixture.dir).err()),
    ] {
        let e = result.unwrap_or_else(|| {
            panic!(
                "the operating system ALLOWED this account to {what}: {} is not out of reach \
                 ({})",
                fixture.dir.display(),
                fixture.provenance
            )
        });
        assert_eq!(
            e.kind(),
            std::io::ErrorKind::PermissionDenied,
            "`{what}` failed for a reason other than a permission denial, so this proves \
             nothing about custody: {e}"
        );
    }
    assert_eq!(std::fs::read(pin).unwrap(), before, "the pin's bytes changed after all");

    // And the module's own verdict agrees with the four syscalls above.
    let verdict = anchor::prove_unwritable(&fixture.dir);
    if fixture.chain_is_intact {
        // **The success path.** Everything above the anchor is out of reach too, so this is
        // the whole of `prove_unwritable` — the recursive tree probe, `can_delete` on every
        // component, `posix_euid` and `posix_ownership` on POSIX — returning `Ok`. Nothing in
        // this crate had ever reached this line on any machine before.
        let proof = verdict.unwrap_or_else(|e| {
            panic!(
                "an anchor that refused all four of the writes above was still not proved \
                 unwritable ({}): {e}",
                fixture.provenance
            )
        });
        assert_eq!(proof.dir, fixture.dir);
        assert!(!proof.refusals.is_empty(), "a proof with no measured refusal proves nothing");
        assert!(!proof.chain.is_empty(), "a proof that walked no ancestor chain proves nothing");
        assert!(
            proof.mechanism.contains("posix:") || proof.mechanism.contains("windows:"),
            "the proof does not name a mechanism: {}",
            proof.mechanism
        );
        // Every SUBDIRECTORY was walked into. The real anchor has one — the registry root at
        // `<anchor>/registry` — and the previous probe listed the anchor once and asked each
        // entry whether it could be "opened for writing", which POSIX answers `EISDIR` and
        // Windows answers `ERROR_ACCESS_DENIED` for every directory alike. So on POSIX this
        // could never have returned `Ok`, and on Windows the subdirectory was skipped without
        // being checked. If the fixture has one, the proof has to mention it.
        for entry in std::fs::read_dir(&fixture.dir).unwrap().filter_map(|e| e.ok()) {
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            let named = path.display().to_string();
            assert!(
                proof.refusals.iter().any(|r| r.contains(&named)),
                "the walk never entered the subdirectory {named}: {:?}",
                proof.refusals
            );
        }
    } else {
        // The Windows fixture lives under `%TEMP%`, which this account CAN rename, so the leaf
        // is sealed and the chain is not. That is `a_location_whose_ancestors_...` firing at
        // the second of its two sites.
        let err = verdict
            .expect_err("this fixture's ancestors are renameable, so the chain is not intact");
        assert!(
            err.to_string().contains("component of the trust anchor's path"),
            "the refusal is not the ancestor one: {err}"
        );
    }
}

// =================================================================================================
// The entry points: which of them enforce, and which say plainly that they do not
// =================================================================================================

/// The unsealed entry points carry `custody: None`, and nothing else does.
///
/// This is what keeps the split honest. `provision.rs` builds every one of its stores this way,
/// so if `custody` could be `Some` without a measurement having happened, that whole file would
/// silently be reporting a property it never checked.
#[test]
fn the_unsealed_entry_points_report_that_they_measured_nothing() {
    let (_temp, _machine_root, app_data) = writable_root();
    let provisioned =
        prov::mint_store_without_custody_proof(&app_data, &app_data.join("anchor"), None)
            .expect("mint");
    assert!(
        provisioned.custody.is_none(),
        "an unsealed mint claimed a custody proof it never took"
    );
}

/// **The guard that makes the split safe**: the PRODUCTION verifier refuses an unsealed anchor.
///
/// `mint_store_without_custody_proof` exists so the mint and the verifier can be tested without
/// permanently sealing a directory. What must never follow is a deployment running on a store
/// built that way. So the production entry point is pointed at exactly such a store here, and it
/// has to refuse — before it reads the manifest, because everything the manifest says resolves
/// through a pin that would otherwise be one this account wrote a moment ago.
#[test]
fn verify_existing_refuses_a_store_whose_anchor_was_never_sealed() {
    let (_temp, _machine_root, app_data) = writable_root();
    let anchor_dir = app_data.join("anchor");
    let provisioned =
        prov::mint_store_without_custody_proof(&app_data, &anchor_dir, None).expect("mint");
    // The store is otherwise perfect: the unsealed verifier accepts it in the same breath.
    prov::verify_store_without_custody_proof(&provisioned.trust_dir, &anchor_dir)
        .expect("the store itself is sound, so the refusal below is only about custody");

    let err = prov::verify_existing(&provisioned.trust_dir, &anchor_dir)
        .expect_err("the production verifier must refuse an anchor this account can write");
    assert!(is_custody(&err), "{err:?}");
    assert!(err.to_string().contains("CAN create files"), "{err}");
}

/// Provisioning refuses a location it can write, names it, and leaves nothing behind.
///
/// The "leaves nothing behind" half is not decoration. A refusal that had already minted the
/// app-side store would leave a trust directory with no anchor — and the next launch would find
/// it, refuse to mint over it, and the deployment would be wedged by its own failed
/// provisioning with no way back that is not a manual deletion.
#[test]
fn provisioning_refuses_a_writable_location_and_leaves_nothing_behind() {
    let (_temp, machine_root, app_data) = writable_root();
    let err = prov::provision(&app_data, &machine_root)
        .expect_err("a machine root this account can rename is not an anchor location");
    assert!(is_custody(&err), "{err:?}");
    assert!(
        !app_data.join(prov::TRUST_DIR).exists(),
        "a refused provisioning left an app-side trust store with no anchor behind it"
    );
    assert!(
        !anchor::anchor_dir(&machine_root).exists(),
        "a refused provisioning left a half-built anchor behind"
    );
    let staging: Vec<PathBuf> = std::fs::read_dir(&app_data)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.file_name().unwrap().to_string_lossy().starts_with(".trust-staging"))
        .collect();
    assert!(staging.is_empty(), "a refused provisioning left staging behind: {staging:?}");
}

/// An anchor names the store it is the anchor FOR, and refuses to be paired with another.
///
/// Without this the anchor is a floating claim. The manifest is unforgeable and records the
/// digest of every app-side file — but the same account that owns the application data
/// directory can mint a SECOND store somewhere it CAN write, and point the engine at the sealed
/// anchor together with that second store. Every digest in the manifest would then simply be a
/// digest of files nothing is reading. Binding the path into the manifest is enough, precisely
/// because the manifest cannot be rewritten.
#[test]
fn an_anchor_refuses_to_be_paired_with_a_trust_store_it_was_not_minted_for() {
    let (_temp, _machine_root, app_data) = writable_root();
    let anchor_dir = app_data.join("anchor");
    let genuine =
        prov::mint_store_without_custody_proof(&app_data, &anchor_dir, None).expect("mint");

    // A second, perfectly well-formed store, with its own anchor, in a directory this account
    // owns — exactly what an attacker who could not touch the real anchor would build.
    let (_temp2, _mr2, other_app) = writable_root();
    let other = prov::mint_store_without_custody_proof(&other_app, &other_app.join("anchor"), None)
        .expect("mint the second store");

    let err = prov::verify_store_without_custody_proof(&other.trust_dir, &anchor_dir)
        .expect_err("the real anchor must refuse a store it was not minted for");
    let text = err.to_string();
    assert!(text.contains("provisioned for a different trust store"), "{text}");
    // And the honest pairing still works, so the refusal is about the mismatch.
    prov::verify_store_without_custody_proof(&genuine.trust_dir, &anchor_dir)
        .expect("the genuine pairing must still verify");
}

/// The engine is no longer told to switch its own custody rule off.
///
/// `BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged` does not weaken one check: `bro_custody`
/// short-circuits EVERY custody rule in the runtime when it is set — the operator pin, the
/// registry root, the evidence floor and the evidence store. This deployment used to set it,
/// because the pin was a file in a directory the app owned and the honest rule would have
/// refused it. It must never come back: with it set, everything this round built would still be
/// there and nothing would be checking it.
#[test]
fn the_engine_environment_no_longer_acknowledges_a_self_owned_pin() {
    let (_temp, _machine_root, app_data) = writable_root();
    let provisioned =
        prov::mint_store_without_custody_proof(&app_data, &app_data.join("anchor"), None)
            .expect("mint");
    let names: Vec<&str> = provisioned.engine_env().iter().map(|(k, _)| *k).collect();
    assert!(
        !names.contains(&"BRO_OPERATOR_ROOT_PIN_SELF_OWNED"),
        "provisioning still tells the engine to switch its custody rules off: {names:?}"
    );
    // And the two variables it DOES export point into the anchor, not the trust store.
    for (name, value) in provisioned.engine_env() {
        if name == "BRO_OPERATOR_ROOT_PUBKEY_FILE" || name == "BRO_OPERATOR_REGISTRY_MIN_FILE" {
            assert!(
                Path::new(&value).starts_with(&provisioned.anchor_dir),
                "{name} points at {value}, which is not inside the anchor"
            );
        }
    }
}

// =================================================================================================
// The POSIX decisions, run on EVERY machine
//
// Reaching these through the filesystem needs an anchor whose whole ancestor chain is out of
// this account's reach, and POSIX offers no unprivileged construction of one: under a temporary
// directory the chain check refuses first, and as root every probe succeeds and the chain check
// refuses first as well. So inline in `platform_precondition` they were unreachable on any box
// but a correctly deployed production one — which is how three refusals and a mechanism string
// went a whole round without ever executing. Split out as pure functions, they run here.
// =================================================================================================

/// Root is refused whatever the modes say, because root rewrites any file regardless of them.
#[test]
fn a_posix_reader_running_as_root_is_refused_before_any_mode_is_considered() {
    let ancestors = vec![(PathBuf::from("/var/lib"), 0u32), (PathBuf::from("/var"), 0)];
    assert_eq!(
        anchor::posix_ownership(0, 0, &ancestors),
        anchor::PosixOwnership::RunningAsRoot
    );
    // Even with the anchor owned by somebody else entirely: the reader is still root.
    assert_eq!(
        anchor::posix_ownership(0, 997, &ancestors),
        anchor::PosixOwnership::RunningAsRoot
    );
    let err = anchor::posix_ownership(0, 997, &ancestors)
        .resolve(Path::new("/var/lib/brops-trust-anchor/trust-anchor"))
        .expect_err("root is never out of reach");
    assert!(err.to_string().contains("running as root"), "{err}");
}

/// An anchor the reader OWNS is refused even when its mode denies writes, because an owner may
/// always chmod it back. This is the check the behavioural probes cannot make.
#[test]
fn a_posix_anchor_owned_by_the_reader_is_refused_however_it_is_chmodded() {
    let ancestors = vec![(PathBuf::from("/var/lib"), 0u32)];
    assert_eq!(
        anchor::posix_ownership(1000, 1000, &ancestors),
        anchor::PosixOwnership::AnchorOwnedByReader { euid: 1000 }
    );
    let err = anchor::posix_ownership(1000, 1000, &ancestors)
        .resolve(Path::new("/tmp/anchor"))
        .expect_err("an owner may always chmod what it owns");
    let text = err.to_string();
    assert!(text.contains("owned by the very account reading it (uid 1000)"), "{text}");
    assert!(text.contains("may always chmod"), "{text}");
}

/// And so is an ANCESTOR the reader owns — the question a mode on the leaf cannot answer,
/// because that ancestor can be chmodded and the anchor then renamed aside.
#[test]
fn a_posix_ancestor_owned_by_the_reader_is_refused_and_the_refusal_names_it() {
    let ancestors = vec![
        (PathBuf::from("/home/gev/brops"), 0u32),
        (PathBuf::from("/home/gev"), 1000),
        (PathBuf::from("/home"), 0),
    ];
    assert_eq!(
        anchor::posix_ownership(1000, 0, &ancestors),
        anchor::PosixOwnership::AncestorOwnedByReader {
            euid: 1000,
            ancestor: PathBuf::from("/home/gev"),
        }
    );
    let err = anchor::posix_ownership(1000, 0, &ancestors)
        .resolve(Path::new("/home/gev/brops/trust-anchor"))
        .expect_err("an ancestor this account owns defeats the leaf");
    let text = err.to_string();
    // The refusal names the ANCESTOR, not the anchor: the reader has to be told which
    // directory to change.
    assert!(text.contains("/home/gev"), "{text}");
    assert!(text.contains("rename the anchor aside"), "{text}");
    // The nearest offending ancestor wins, so the remedy is the smallest one.
    assert!(!text.contains("/home/gev/brops/trust-anchor is"), "{text}");
}

/// The success case, which had never executed anywhere: everything belongs to another uid.
#[test]
fn a_posix_anchor_no_ancestor_of_which_the_reader_owns_is_out_of_reach() {
    let ancestors = vec![
        (PathBuf::from("/var/lib/brops-trust-anchor"), 0u32),
        (PathBuf::from("/var/lib"), 0),
        (PathBuf::from("/var"), 0),
        (PathBuf::from("/"), 0),
    ];
    assert_eq!(
        anchor::posix_ownership(1000, 0, &ancestors),
        anchor::PosixOwnership::OutOfReach { euid: 1000 }
    );
    let mechanism = anchor::posix_ownership(1000, 0, &ancestors)
        .resolve(Path::new("/var/lib/brops-trust-anchor/trust-anchor"))
        .expect("an anchor owned by another uid, with every ancestor likewise, is out of reach");
    assert!(mechanism.starts_with("posix:"), "{mechanism}");
    assert!(mechanism.contains("uid 1000"), "{mechanism}");
    // It reports what was MEASURED, never a claim that the mode bits were inspected.
    assert!(mechanism.contains("refused by the kernel"), "{mechanism}");
}

/// `posix_euid` agrees with the kernel's own answer, asked a different way.
///
/// The product learns its effective uid by creating a file and reading the owner back, because
/// the crate has no `libc` dependency. That is only trustworthy if it agrees with an
/// independent oracle, so this compares it with `/proc/self`'s owner — which the kernel sets
/// from the process's effective uid and no file mode influences.
#[test]
fn the_effective_uid_probe_agrees_with_the_kernel() {
    const NAME: &str = "the_effective_uid_probe_agrees_with_the_kernel";
    #[cfg(not(windows))]
    {
        let Some(kernel) = prerequisites::procfs_euid() else {
            prerequisites::skip(
                NAME,
                "/proc/self is not present, so there is no independent oracle for this \
                 process's effective uid on this platform (procfs is Linux's)",
            );
            return;
        };
        let measured = anchor::posix_euid().expect("the probe must answer or refuse, never guess");
        assert_eq!(
            measured, kernel,
            "the probe-file mechanism and /proc/self disagree about this process's uid, so the \
             number `posix_ownership` compares against the anchor's owner is not this account's"
        );
    }
    #[cfg(windows)]
    {
        // Not a skip that hides anything: Windows has no uid, and the whole POSIX ownership
        // question is answered there by the token/DACL path instead.
        prerequisites::skip(NAME, "windows has no effective uid; custody is decided by the token");
    }
}

// =================================================================================================
// The platform that cannot build its own anchor
// =================================================================================================

/// A POSIX first launch is refused **at the top, by name, before anything is minted** — and the
/// refusal names the directory, the uid, the modes, and the fact that no tool ships to make it.
///
/// This is the decision, taken purely, so this test runs on Windows too. What it replaced: the
/// application minted the entire store, wrote the pin, the floor and the manifest, and only
/// then called `anchor::seal`, which returns `Unsupported` off Windows. So on Linux and macOS
/// the desktop app did not fail to provision, it failed to LAUNCH, with an error escaping from
/// a function whose job was to seal a directory.
#[test]
fn a_platform_that_cannot_seal_refuses_at_the_top_and_says_what_is_missing() {
    let dir = Path::new("/var/lib/brops-trust-anchor/trust-anchor");
    for platform in ["linux", "macos", "unix"] {
        let err = anchor::preprovision_refusal(platform, dir)
            .unwrap_or_else(|| panic!("{platform} cannot build an anchor it cannot rewrite"));
        assert!(is_custody(&err), "{err:?}");
        let text = err.to_string();
        // WHICH directory, WHICH owner, WHICH modes.
        assert!(text.contains("/var/lib/brops-trust-anchor/trust-anchor"), "{text}");
        assert!(text.contains("DIFFERENT uid"), "{text}");
        assert!(text.contains("0755") && text.contains("0644"), "{text}");
        assert!(text.contains("brops-anchor"), "{text}");
        // And the honest part: nothing ships that creates it, so this is not a step to follow.
        assert!(text.contains("no shipped tool creates it yet"), "{text}");
        // Never a fallback. An app that provisioned into a directory it can write would look
        // provisioned and not be, which is strictly worse than one that will not start.
        assert!(!text.to_lowercase().contains("proceeding"), "{text}");
        assert!(!text.to_lowercase().contains("fall back"), "{text}");
        // An anchor already in place is still used — the refusal says so, so an operator with
        // a provisioned box does not read this as "unsupported forever".
        assert!(text.contains("An anchor already in place IS used"), "{text}");
    }
}

/// Windows is the one platform that CAN build an anchor it afterwards cannot reach, so it is
/// the one platform this refusal does not fire on.
#[test]
fn windows_is_the_only_platform_that_can_construct_its_own_anchor() {
    let dir = Path::new("C:\\ProgramData\\BroPS\\trust-anchor");
    assert!(anchor::preprovision_refusal("windows", dir).is_none());
    // And the refusal fires on exactly the platform this build is not Windows on, so the two
    // halves of the decision cannot drift apart from `platform_name()`.
    assert_eq!(
        anchor::preprovision_refusal(prov::platform_name(), dir).is_none(),
        cfg!(windows),
        "preprovision_refusal disagrees with the platform this build is for"
    );
}

// =================================================================================================
// The anchor is a TREE, and a directory inside it is not asked whether it opens for writing
// =================================================================================================

/// A subdirectory of the anchor is descended into, not "opened for write".
///
/// `write_anchor_files` puts the operator-signed registry at
/// `<anchor>/registry/config/trusted-keys.json`. The previous probe listed the anchor once and
/// asked every entry whether it could be opened for writing — a question neither platform
/// answers usefully about a directory:
///
/// * POSIX: `open(dir, O_WRONLY)` is `EISDIR`, which is not `PermissionDenied`, so the old code
///   fell into its "cannot be measured" branch. `prove_unwritable` could therefore **never**
///   have returned `Ok` on POSIX, even against a perfectly sealed root-owned anchor.
/// * Windows: `CreateFileW(dir, GENERIC_WRITE)` is `ERROR_ACCESS_DENIED` for every directory,
///   wide open or not, so the subdirectory passed without being checked and the files inside it
///   were never looked at.
///
/// Building the fixture needs a directory this account can LIST but not ADD to. POSIX makes one
/// with `chmod 0555`; Windows needs a DACL, so it skips by name rather than pretend.
#[test]
fn a_subdirectory_of_the_anchor_is_walked_into_rather_than_opened_for_writing() {
    const NAME: &str = "a_subdirectory_of_the_anchor_is_walked_into_rather_than_opened_for_writing";
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if prerequisites::running_as_root() {
            prerequisites::skip(NAME, "root ignores mode bits, so a 0555 directory denies it nothing");
            return;
        }
        let temp = tempfile::tempdir().unwrap();
        let anchor_dir = temp.path().join("trust-anchor");
        let registry = anchor_dir.join("registry");
        std::fs::create_dir_all(&registry).unwrap();
        let pin = anchor_dir.join("operator-root.pub");
        std::fs::write(&pin, "11".repeat(32) + "\n").unwrap();
        // 0444 so the pin is not itself what refuses: `entries` is sorted, and
        // `operator-root.pub` sorts before `registry`, so an owner-WRITABLE pin would end
        // the walk one entry before the subdirectory this test is about.
        std::fs::set_permissions(&pin, std::fs::Permissions::from_mode(0o444)).unwrap();
        // The anchor denies creation even to its owner; the subdirectory does not.
        std::fs::set_permissions(&anchor_dir, std::fs::Permissions::from_mode(0o555)).unwrap();

        let err = anchor::prove_unwritable(&anchor_dir)
            .expect_err("the registry subdirectory is writable, so the anchor is not out of reach");
        let text = err.to_string();
        // The walk went INTO the subdirectory and refused there, naming it.
        assert!(
            text.contains(&registry.display().to_string()),
            "the probe never entered the subdirectory: {text}"
        );
        assert!(text.contains("CAN create files"), "{text}");
        // And it never asked the directory the question that has no answer.
        assert!(
            !text.contains("cannot be measured"),
            "a directory entry was asked whether it opens for writing: {text}"
        );

        // Restore write so the TempDir can clean itself up.
        std::fs::set_permissions(&anchor_dir, std::fs::Permissions::from_mode(0o755)).unwrap();
        std::fs::set_permissions(&pin, std::fs::Permissions::from_mode(0o644)).unwrap();
    }
    #[cfg(not(unix))]
    {
        prerequisites::skip(
            NAME,
            "a directory this account can list but not add entries to cannot be made with a \
             mode on this platform; it needs a DACL, which is what the sealed fixture in \
             `prerequisites` supplies and `a_sealed_anchor_refuses_this_accounts_own_writes` \
             measures",
        );
    }
}

/// A symlink inside the anchor is refused rather than followed.
///
/// Provisioning writes none. One that appeared redirects a read to a file whose custody this
/// walk never measured — possibly one this very account owns — so it fails closed.
#[test]
fn a_symlink_inside_the_anchor_is_refused_rather_than_followed() {
    const NAME: &str = "a_symlink_inside_the_anchor_is_refused_rather_than_followed";
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if prerequisites::running_as_root() {
            prerequisites::skip(NAME, "root ignores mode bits, so a 0555 directory denies it nothing");
            return;
        }
        let temp = tempfile::tempdir().unwrap();
        let anchor_dir = temp.path().join("trust-anchor");
        std::fs::create_dir_all(&anchor_dir).unwrap();
        let elsewhere = temp.path().join("mine.pub");
        std::fs::write(&elsewhere, "22".repeat(32) + "\n").unwrap();
        std::os::unix::fs::symlink(&elsewhere, anchor_dir.join("operator-root.pub")).unwrap();
        std::fs::set_permissions(&anchor_dir, std::fs::Permissions::from_mode(0o555)).unwrap();

        let err = anchor::prove_unwritable(&anchor_dir).expect_err("a symlinked pin is not an anchor");
        assert!(err.to_string().contains("SYMLINK"), "{err}");

        std::fs::set_permissions(&anchor_dir, std::fs::Permissions::from_mode(0o755)).unwrap();
    }
    #[cfg(not(unix))]
    {
        prerequisites::skip(
            NAME,
            "creating a symlink needs SeCreateSymbolicLinkPrivilege or developer mode on this \
             platform, which the test account may not hold",
        );
    }
}

/// And the refusal is WIRED: a POSIX first launch stops at it, before anything is minted.
///
/// The pure test above proves the decision and its wording. This proves `provision` actually
/// asks — which is the part that was missing, because nothing minted the store, wrote the pin,
/// wrote the floor and then died in `anchor::seal` by accident. It needs no privileges: the
/// machine root is a not-yet-existing directory under `/var/lib`, which is root-owned `0755`
/// on every distribution, so `precheck_location` passes and the preflight is what fires.
#[test]
fn a_posix_first_launch_refuses_before_it_mints_anything() {
    const NAME: &str = "a_posix_first_launch_refuses_before_it_mints_anything";
    #[cfg(unix)]
    {
        if prerequisites::running_as_root() {
            prerequisites::skip(
                NAME,
                "root can delete /var/lib, so `precheck_location` refuses first and the \
                 preflight below is never reached. Run the suite as an unprivileged account",
            );
            return;
        }
        let app_data = tempfile::tempdir().unwrap();
        let machine_root = Path::new("/var/lib/brops-preflight-should-never-exist");
        let err = prov::provision(app_data.path(), machine_root)
            .expect_err("a POSIX first launch cannot build an anchor it could not rewrite");
        let text = err.to_string();
        assert!(
            text.contains("cannot CREATE a trust anchor"),
            "provisioning got PAST the preflight and refused for some other reason: {text}"
        );
        // Before anything was written — neither half of the pair exists.
        assert!(!machine_root.exists(), "the refusal still created {}", machine_root.display());
        assert!(
            !app_data.path().join(prov::TRUST_DIR).exists(),
            "the refusal still minted an app-side trust store"
        );
        let leftovers: Vec<PathBuf> =
            std::fs::read_dir(app_data.path()).unwrap().map(|e| e.unwrap().path()).collect();
        assert!(leftovers.is_empty(), "the refusal left staging behind: {leftovers:?}");
    }
    #[cfg(not(unix))]
    {
        // Windows CAN construct its own anchor, so there is no refusal to wire. Running the
        // equivalent here would seal a real directory under %ProgramData% permanently, which
        // is exactly what `provision.rs` uses the unsealed entry points to avoid.
        prerequisites::skip(
            NAME,
            "windows builds its own anchor, so this refusal does not apply; \
             `windows_is_the_only_platform_that_can_construct_its_own_anchor` is its half",
        );
    }
}
