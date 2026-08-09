//! The one property O-2 reduces to, tested against the operating system rather than against a
//! description of it.
//!
//! `provision.rs` covers the mint and the verifier through the unsealed entry points, because
//! [`brops_provision::anchor::seal`] is **one-way for the account that applies it** and a test
//! that sealed a fresh directory every run would leave one on the machine that nothing running
//! as the test's own account could ever remove. This file covers what that file deliberately
//! does not: whether the location is actually out of reach.
//!
//! Two of the checks here need a genuinely sealed directory. They share ONE, at a fixed name
//! under `%TEMP%`, created the first time this file is ever run on a machine and reused
//! afterwards — see [`shared_sealed_probe`]. Everything else needs no side effect at all.
//!
//! The positive end to end — a sealed anchor, the real `bro_signature` accepting its pin with
//! `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` unset, and the real `bro_audit_log.verify()` refusing a
//! forgery built after every write was denied — is `audit-signer/tests/anchor_end_to_end.rs`.

use std::path::{Path, PathBuf};

use brops_provision as prov;
use prov::anchor;

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
/// directory, never enough to delete or rename one. That is the whole reason the anchor can be
/// established by an unelevated first launch, so it is measured rather than assumed, and it
/// creates nothing: the check only reads.
#[test]
#[cfg(windows)]
fn the_production_machine_root_has_an_ancestor_this_account_cannot_rename() {
    let machine_root = anchor::default_machine_root().expect("%ProgramData%");
    anchor::precheck_location(&anchor::anchor_dir(&machine_root), &machine_root).unwrap_or_else(
        |e| {
            panic!(
                "the production anchor location is refused on this machine, so no unelevated \
                 first launch could establish an anchor here: {e}"
            )
        },
    );
}

// =================================================================================================
// A really sealed directory, and the OS really refusing
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
fn shared_sealed_probe() -> PathBuf {
    let root = std::env::temp_dir().join("brops-o2-sealed-probe");
    let dir = root.join("trust-anchor");
    if dir.join("operator-root.pub").is_file() {
        return dir;
    }
    std::fs::create_dir_all(&dir).expect("create the probe directory");
    std::fs::write(dir.join("operator-root.pub"), "11".repeat(32) + "\n").expect("write the pin");
    // `seal` walks upward and REFUSES rather than re-permission a directory outside the machine
    // root it was given — here that is `%TEMP%`, which the rest of the system relies on. It is
    // the right refusal (`a_location_whose_ancestors_...` is the test for it) and it arrives
    // AFTER the leaf and its files have been sealed, because the walk is deepest-first. So the
    // leaf really is sealed at this point; the caller proves that with syscalls rather than
    // taking this helper's word for it.
    match anchor::seal(&dir, &root) {
        Ok(_) => {}
        Err(prov::ProvisionError::Custody { ref path, .. }) if *path == std::env::temp_dir() => {}
        Err(e) => panic!("the probe directory could not be sealed: {e}"),
    }
    dir
}

/// The seal, as the operating system reports it — not as a DACL read-back describes it.
///
/// A descriptor read has to be right about ACE ordering, generic mappings, deny entries,
/// inheritance and the owner's implicit rights. `CreateFile` returning `ERROR_ACCESS_DENIED` is
/// the same code path an attacker takes, and it is immune to all of that.
#[test]
#[cfg(windows)]
fn a_sealed_anchor_refuses_this_accounts_own_writes() {
    let dir = shared_sealed_probe();
    let pin = dir.join("operator-root.pub");
    let before = std::fs::read(&pin).expect("the pin is still READABLE — read is what it keeps");

    for (what, result) in [
        ("overwrite the pin", std::fs::write(&pin, b"rogue").err()),
        ("create a new file in the anchor", std::fs::write(dir.join("rogue.pub"), b"x").err()),
        ("delete the pin", std::fs::remove_file(&pin).err()),
        ("remove the anchor directory", std::fs::remove_dir_all(&dir).err()),
    ] {
        let e = result.unwrap_or_else(|| {
            panic!("the operating system ALLOWED this account to {what}: the anchor is not sealed")
        });
        assert_eq!(
            e.kind(),
            std::io::ErrorKind::PermissionDenied,
            "`{what}` failed for a reason other than a permission denial, so this proves \
             nothing about custody: {e}"
        );
    }
    assert_eq!(std::fs::read(&pin).unwrap(), before, "the pin's bytes changed after all");

    // And the module's own verdict agrees with the four syscalls above. It fails on the
    // ANCESTOR here, not on the directory — %TEMP% can be renamed by this account — which is
    // the check from `a_location_whose_ancestors_...` firing at the second of its two sites.
    let err = anchor::prove_unwritable(&dir)
        .expect_err("%TEMP% is renameable by this account, so the chain is not intact");
    assert!(
        err.to_string().contains("component of the trust anchor's path"),
        "the refusal is not the ancestor one: {err}"
    );
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
