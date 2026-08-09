//! The Windows second principal for the audit-head anchor.
//!
//! # What is proved where
//!
//! Every **decision** is a pure function over plain data and is tested on any host, exactly as
//! `pipe_acl` / `provision_custody` / `tcb_floor` do it in the live kit. The **syscalls** need
//! Windows, and creating the service account needs Administrator.
//!
//! Checks that only run under elevation are the ones that rot, so the tests that cannot run here
//! **print a SKIP naming the exact missing capability** and assert whatever they still can. None
//! of them passes by default: a skipped test asserts nothing and says so out loud.
//!
//! # Read the negative results carefully
//!
//! Several tests assert a REFUSAL. That is the point: the value of this module is entirely in what
//! it declines to do. A test that only checked the happy path would stay green after the checks
//! were deleted, so every check below is also exercised by feeding it the input it must reject.

use std::path::{Path, PathBuf};

use brops_provision::audit_signer as anc;
use brops_provision::audit_signer::{
    Ace, AnchorRefusal, AnchorState, AppTokenPosture, DaclFacts, Separation, SignRefusal,
};
use serde_json::{json, Value};

// ---------------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------------

const APP: &str = "S-1-5-21-4143592576-1820857250-2239199907-1002";
const SIGNER: &str = "S-1-5-80-1111111111-2222222222-3333333333-4444444444-5555555555";
const SYSTEM: &str = "S-1-5-18";
const ADMINS: &str = "S-1-5-32-544";

fn ace(sid: &str, mask: u32) -> Ace {
    Ace { sid: sid.to_string(), mask, inheritable: true }
}

/// A read-back that satisfies every rule, so each test can break exactly one thing.
fn healthy_key_facts() -> DaclFacts {
    DaclFacts {
        path: "C:\\ProgramData\\BroPS\\audit-signer\\anchor.key".to_string(),
        owner_sid: ADMINS.to_string(),
        dacl_present: true,
        dacl_protected: true,
        allow_aces: vec![
            ace(SYSTEM, anc::FILE_ALL_ACCESS),
            ace(ADMINS, anc::FILE_ALL_ACCESS),
            ace(SIGNER, anc::FILE_GENERIC_READ | anc::FILE_GENERIC_WRITE | anc::DELETE),
        ],
    }
}

fn healthy_ledger_facts() -> DaclFacts {
    DaclFacts {
        path: "C:\\Users\\gev\\AppData\\Local\\BroPS\\audit".to_string(),
        owner_sid: APP.to_string(),
        dacl_present: true,
        dacl_protected: true,
        allow_aces: vec![
            ace(SYSTEM, anc::FILE_ALL_ACCESS),
            ace(ADMINS, anc::FILE_ALL_ACCESS),
            ace(APP, anc::FILE_GENERIC_READ | anc::FILE_GENERIC_WRITE | anc::DELETE),
        ],
    }
}

fn key_plan() -> anc::DaclPlan {
    anc::key_dacl_plan(APP, SIGNER).expect("the healthy key plan must build")
}

fn ledger_plan() -> anc::DaclPlan {
    anc::ledger_dacl_plan(APP, SIGNER).expect("the healthy ledger plan must build")
}

fn skip(test: &str, why: &str) {
    println!("SKIP {test}: {why}");
}

// ---------------------------------------------------------------------------------------------
// The derived principal
// ---------------------------------------------------------------------------------------------

#[test]
fn sha1_matches_the_published_vectors() {
    // Not for integrity — SHA-1 is here only because Windows derives service SIDs with it.
    assert_eq!(
        brops_provision::hex(&anc::sha1(b"")),
        "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    );
    assert_eq!(
        brops_provision::hex(&anc::sha1(b"abc")),
        "a9993e364706816aba3e25717850c26c9cd0d89d"
    );
    assert_eq!(
        brops_provision::hex(&anc::sha1(
            b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
        )),
        "84983e441c3bd26ebaae4aa1f95129e5e54670f1"
    );
}

/// The whole design rests on being able to name the signer principal *offline*. If this drifts,
/// every DACL this module writes names a principal that does not exist, and Windows would store
/// an unresolvable SID rather than refuse.
#[test]
fn the_service_sid_is_the_one_windows_really_derives() {
    // `NT SERVICE\TrustedInstaller`, cross-checked against this machine's own LSA in
    // `resolve_service_sid_agrees_with_the_derived_sid` below.
    assert_eq!(
        anc::service_account_sid("TrustedInstaller"),
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    );
}

#[test]
fn the_service_sid_derivation_is_case_insensitive_like_windows() {
    let a = anc::service_account_sid("TrustedInstaller");
    assert_eq!(a, anc::service_account_sid("trustedinstaller"));
    assert_eq!(a, anc::service_account_sid("TRUSTEDINSTALLER"));
}

#[test]
fn our_own_service_name_derives_a_service_sid() {
    let sid = anc::service_account_sid(anc::SIGNER_SERVICE_NAME);
    assert!(anc::is_service_sid(&sid), "{sid}");
    assert!(anc::looks_like_sid(&sid), "{sid}");
    assert!(!anc::WORLD_SIDS.contains(&sid.as_str()));
}

// ---------------------------------------------------------------------------------------------
// The plans refuse to be built wrong
// ---------------------------------------------------------------------------------------------

#[test]
fn the_app_and_the_signer_may_never_be_the_same_principal() {
    // The literal O-2 condition. Not a warning to acknowledge — there is nothing to enable.
    let same = anc::service_account_sid(anc::SIGNER_SERVICE_NAME);
    assert!(matches!(
        anc::key_dacl_plan(&same, &same),
        Err(AnchorRefusal::SamePrincipal { .. })
    ));
    assert!(matches!(
        anc::ledger_dacl_plan(&same, &same),
        Err(AnchorRefusal::SamePrincipal { .. })
    ));
}

#[test]
fn a_signer_that_is_not_a_virtual_service_account_is_refused() {
    // A plain local user would need a password, could log on, and could be added to
    // Administrators — which would silently hand it write on the ledger through the
    // Administrators ACE.
    let local_user = "S-1-5-21-4143592576-1820857250-2239199907-1050";
    assert!(matches!(
        anc::key_dacl_plan(APP, local_user),
        Err(AnchorRefusal::SignerNotAServiceAccount { .. })
    ));
    assert!(matches!(
        anc::key_dacl_plan(APP, ADMINS),
        Err(AnchorRefusal::SignerNotAServiceAccount { .. })
    ));
}

#[test]
fn a_world_principal_is_refused_on_either_side() {
    for world in ["S-1-1-0", "S-1-5-11", "S-1-5-32-545"] {
        assert!(
            matches!(
                anc::key_dacl_plan(world, SIGNER),
                Err(AnchorRefusal::WorldPrincipal { .. })
            ),
            "{world} was accepted as the app principal"
        );
    }
}

#[test]
fn an_unresolved_account_name_is_refused_rather_than_silently_dropped() {
    // A name that did not resolve would become NO ace, i.e. a DACL that says nothing while
    // looking like it says something.
    assert!(matches!(
        anc::key_dacl_plan("OFFICE\\gev", SIGNER),
        Err(AnchorRefusal::NotASid { .. })
    ));
}

#[test]
fn the_key_plan_grants_the_app_nothing_at_all() {
    let plan = key_plan();
    assert!(
        plan.aces.iter().all(|a| a.sid != APP),
        "the app appears in the key DACL: {:?}",
        plan.aces
    );
    // And the arithmetic, not just the absence.
    let facts = anc::plan_as_facts(&plan, ADMINS, true);
    assert_eq!(anc::direct_mask(&facts, APP), 0);
}

#[test]
fn the_ledger_plan_grants_the_signer_no_write_bit() {
    let plan = ledger_plan();
    let facts = anc::plan_as_facts(&plan, APP, true);
    let signer_mask = anc::direct_mask(&facts, SIGNER);
    assert_eq!(
        signer_mask & anc::WRITE_ACCESS_BITS,
        0,
        "signer mask {signer_mask:#010x} carries write bits"
    );
    // The app must still be able to append, or the engine cannot write the ledger at all.
    let app_mask = anc::direct_mask(&facts, APP);
    assert_eq!(
        app_mask & (anc::FILE_WRITE_DATA | anc::FILE_APPEND_DATA),
        anc::FILE_WRITE_DATA | anc::FILE_APPEND_DATA
    );
}

#[test]
fn the_masks_this_module_grants_readers_carry_no_write_bit() {
    // The same arithmetic `provision_custody::custody_file_dacl` runs at run time, kept here so
    // an edit to the constants fails a test rather than quietly widening a DACL.
    assert_eq!(anc::FILE_GENERIC_READ & anc::WRITE_ACCESS_BITS, 0);
    assert_ne!(anc::FILE_GENERIC_WRITE & anc::WRITE_ACCESS_BITS, 0);
    // FILE_APPEND_DATA is 0x4 and MUST be counted as write: it is the only bit an audit-ledger
    // forger strictly needs, and the bit `GENERIC_WRITE` hides.
    assert_ne!(anc::WRITE_ACCESS_BITS & anc::FILE_APPEND_DATA, 0);
}

// ---------------------------------------------------------------------------------------------
// The read-back proofs — one test per way of breaking them
// ---------------------------------------------------------------------------------------------

#[test]
fn a_healthy_readback_proves_both_properties_and_records_the_numbers() {
    let kp = anc::verify_key_custody(&key_plan(), &healthy_key_facts()).expect("key custody");
    assert_eq!(kp.observed_mask, 0);
    assert_eq!(kp.excluded_sid, APP);
    assert!(kp.summary().contains("0x00000000"), "{}", kp.summary());

    let lp =
        anc::verify_ledger_custody(&ledger_plan(), &healthy_ledger_facts()).expect("ledger custody");
    assert_eq!(lp.excluded_sid, SIGNER);
    assert_eq!(lp.observed_mask & anc::WRITE_ACCESS_BITS, 0);
    // The proof states the number it computed, so an auditor can re-derive it from `icacls`.
    assert!(lp.summary().contains("must be 0"), "{}", lp.summary());
}

#[test]
fn a_null_dacl_is_refused_and_never_read_as_no_access() {
    // The single most dangerous misreading on Windows: no DACL means EVERYONE FULL CONTROL.
    let mut facts = healthy_key_facts();
    facts.dacl_present = false;
    facts.allow_aces.clear();
    assert!(matches!(
        anc::verify_key_custody(&key_plan(), &facts),
        Err(AnchorRefusal::NullDacl { .. })
    ));
}

#[test]
fn an_unprotected_dacl_is_refused_because_absence_would_prove_nothing() {
    // Without SE_DACL_PROTECTED the parent's inheritable ACEs are merged in, so "the app is not
    // in this DACL" stops being a statement about the app's access.
    let mut facts = healthy_key_facts();
    facts.dacl_protected = false;
    assert!(matches!(
        anc::verify_key_custody(&key_plan(), &facts),
        Err(AnchorRefusal::DaclNotProtected { .. })
    ));
    let mut lfacts = healthy_ledger_facts();
    lfacts.dacl_protected = false;
    assert!(matches!(
        anc::verify_ledger_custody(&ledger_plan(), &lfacts),
        Err(AnchorRefusal::DaclNotProtected { .. })
    ));
}

#[test]
fn a_generic_right_in_a_readback_is_refused_rather_than_computed_over() {
    // GENERIC_WRITE (0x40000000) expands to include FILE_APPEND_DATA at open time, so a mask
    // comparison would report "no write bits" about an ACE that grants exactly the write bit an
    // audit forger needs. Refuse rather than guess.
    let mut facts = healthy_ledger_facts();
    facts.allow_aces.push(ace(SIGNER, 0x4000_0000));
    match anc::verify_ledger_custody(&ledger_plan(), &facts) {
        Err(AnchorRefusal::UnmappedGenericRights { grantees, .. }) => {
            assert_eq!(grantees, vec![SIGNER.to_string()]);
        }
        other => panic!("a GENERIC_WRITE ace was computed over: {other:?}"),
    }
    // And the naive check really would have missed it, which is why this refusal exists.
    assert_eq!(0x4000_0000u32 & anc::WRITE_ACCESS_BITS, 0);
}

#[test]
fn a_world_sid_in_the_key_dacl_is_refused_even_when_it_only_grants_read() {
    // BUILTIN\Users read on the anchor key hands it to the app by group membership; the
    // per-account ACEs would still look perfect.
    let mut facts = healthy_key_facts();
    facts.allow_aces.push(ace("S-1-5-32-545", anc::FILE_GENERIC_READ));
    assert!(matches!(
        anc::verify_key_custody(&key_plan(), &facts),
        Err(AnchorRefusal::WorldInDacl { .. })
    ));
}

#[test]
fn a_key_the_app_owns_is_refused_because_an_owner_can_rewrite_the_dacl() {
    let mut facts = healthy_key_facts();
    facts.owner_sid = APP.to_string();
    match anc::verify_key_custody(&key_plan(), &facts) {
        Err(AnchorRefusal::UntrustedOwner { owner_sid, .. }) => assert_eq!(owner_sid, APP),
        other => panic!("an app-owned key was accepted: {other:?}"),
    }
}

#[test]
fn the_ledger_may_be_owned_by_the_app_but_never_by_the_signer() {
    // Deliberately NOT the key's rule. The ledger defends against the signer, and it is per-user
    // application data the app creates; demanding a TCB owner would be impossible unelevated and
    // would buy nothing.
    let mut facts = healthy_ledger_facts();
    facts.owner_sid = APP.to_string();
    assert!(anc::verify_ledger_custody(&ledger_plan(), &facts).is_ok());
    facts.owner_sid = ADMINS.to_string();
    assert!(anc::verify_ledger_custody(&ledger_plan(), &facts).is_ok());
    facts.owner_sid = SIGNER.to_string();
    assert!(matches!(
        anc::verify_ledger_custody(&ledger_plan(), &facts),
        Err(AnchorRefusal::UntrustedOwner { .. })
    ));
}

#[test]
fn write_dac_alone_is_enough_to_refuse_the_key() {
    // The subtle one. WRITE_DAC grants no read, so a check that only looked for read bits would
    // pass — and the holder could then grant itself read and sign its own anchors.
    let mut facts = healthy_key_facts();
    facts.allow_aces.push(ace(APP, anc::WRITE_DAC));
    match anc::verify_key_custody(&key_plan(), &facts) {
        Err(AnchorRefusal::KeyReachableByApp { observed_mask, .. }) => {
            assert_eq!(observed_mask, anc::WRITE_DAC);
            assert_eq!(observed_mask & anc::READ_ACCESS_BITS, 0, "no read bit was granted");
        }
        other => panic!("WRITE_DAC for the app was accepted: {other:?}"),
    }
}

#[test]
fn read_attributes_alone_is_enough_to_refuse_the_key() {
    // "Zero, not merely no read." Anything at all is a foothold and a signal that the DACL was
    // not built by this module.
    let mut facts = healthy_key_facts();
    facts.allow_aces.push(ace(APP, anc::FILE_READ_ATTRIBUTES));
    assert!(matches!(
        anc::verify_key_custody(&key_plan(), &facts),
        Err(AnchorRefusal::KeyReachableByApp { .. })
    ));
}

#[test]
fn append_only_for_the_signer_is_enough_to_refuse_the_ledger() {
    // FILE_APPEND_DATA is the *only* right a ledger forger strictly needs, and the one hidden
    // inside GENERIC_WRITE. A check that looked for FILE_WRITE_DATA alone would miss it.
    let mut facts = healthy_ledger_facts();
    facts.allow_aces.push(ace(SIGNER, anc::FILE_APPEND_DATA));
    match anc::verify_ledger_custody(&ledger_plan(), &facts) {
        Err(AnchorRefusal::LedgerWritableBySigner { observed_mask, .. }) => {
            assert_eq!(observed_mask, anc::FILE_APPEND_DATA);
        }
        other => panic!("append-only for the signer was accepted: {other:?}"),
    }
}

#[test]
fn delete_for_the_signer_is_enough_to_refuse_the_ledger() {
    let mut facts = healthy_ledger_facts();
    facts.allow_aces.push(ace(SIGNER, anc::DELETE));
    assert!(matches!(
        anc::verify_ledger_custody(&ledger_plan(), &facts),
        Err(AnchorRefusal::LedgerWritableBySigner { .. })
    ));
}

#[test]
fn a_ledger_the_app_cannot_append_to_is_refused_rather_than_quietly_broken() {
    let mut facts = healthy_ledger_facts();
    facts.allow_aces.retain(|a| a.sid != APP);
    facts.allow_aces.push(ace(APP, anc::FILE_GENERIC_READ));
    assert!(matches!(
        anc::verify_ledger_custody(&ledger_plan(), &facts),
        Err(AnchorRefusal::LedgerNotWritableByApp { .. })
    ));
}

#[test]
fn a_signer_that_cannot_use_its_own_key_is_refused_at_provisioning_not_at_first_anchor() {
    let mut facts = healthy_key_facts();
    facts.allow_aces.retain(|a| a.sid != SIGNER);
    facts.allow_aces.push(ace(SIGNER, anc::FILE_GENERIC_READ));
    assert!(matches!(
        anc::verify_key_custody(&key_plan(), &facts),
        Err(AnchorRefusal::SignerCannotUseItsOwnKey { .. })
    ));
}

#[test]
fn every_refusal_says_what_failed_and_that_the_ledger_stays_unanchored() {
    let refusals = vec![
        AnchorRefusal::SamePrincipal { sid: APP.to_string() },
        AnchorRefusal::NullDacl { path: "x".into() },
        AnchorRefusal::DaclNotProtected { path: "x".into() },
        AnchorRefusal::KeyActuallyReadable { path: "x".into() },
        AnchorRefusal::ElevationRequired { step: "creating the service".into() },
        AnchorRefusal::SignerSidSubstituted {
            name: "X".into(),
            derived: "S-1-5-80-1".into(),
            resolved: "S-1-5-21-9".into(),
        },
    ];
    for r in refusals {
        let text = r.explain();
        assert!(text.contains("REFUSING"), "{text}");
        assert!(text.contains("UNANCHORED"), "{text}");
        assert!(text.contains("AuditAnchorMissing"), "{text}");
        // Never suggests a degraded mode.
        assert!(!text.to_lowercase().contains("proceeding anyway"), "{text}");
    }
}

// ---------------------------------------------------------------------------------------------
// Honesty about how strong the separation is
// ---------------------------------------------------------------------------------------------

#[test]
fn an_administrator_app_account_is_never_upgraded_to_full_separation() {
    assert_eq!(
        Separation::from_posture(AppTokenPosture::StandardUser),
        Separation::Separated
    );
    for weak in [AppTokenPosture::FilteredAdministrator, AppTokenPosture::ElevatedAdministrator] {
        let s = Separation::from_posture(weak);
        assert!(matches!(s, Separation::SeparatedUntilElevation { .. }));
        let claim = s.claim();
        assert!(claim.contains("does NOT hold"), "{claim}");
        assert!(claim.contains("not evidence against the machine's owner"), "{claim}");
    }
    // A filtered admin token is DENIED today and one consent away from full control. It must not
    // be reported as a standard user just because CheckTokenMembership says "not elevated".
    assert_ne!(
        Separation::from_posture(AppTokenPosture::FilteredAdministrator),
        Separation::Separated
    );
}

#[test]
fn the_anchor_environment_cannot_exist_without_both_proofs() {
    let kp = anc::verify_key_custody(&key_plan(), &healthy_key_facts()).unwrap();
    let lp = anc::verify_ledger_custody(&ledger_plan(), &healthy_ledger_facts()).unwrap();

    // A relative signer path would make `bro_audit_log._signer_argv` refuse anyway; refuse here
    // so the failure names the real cause.
    assert!(anc::AnchorEnv::from_proofs(
        Path::new("relay.exe"),
        "audit-anchor-0011223344556677",
        Separation::Separated,
        kp.clone(),
        lp.clone(),
    )
    .is_err());

    // No key id ⇒ the engine could not name the key in the trusted registry.
    assert!(anc::AnchorEnv::from_proofs(
        Path::new("C:\\Program Files\\BroPS\\brops-anchor-relay.exe"),
        "  ",
        Separation::Separated,
        kp.clone(),
        lp.clone(),
    )
    .is_err());

    let env = anc::AnchorEnv::from_proofs(
        Path::new("C:\\Program Files\\BroPS\\brops-anchor-relay.exe"),
        "audit-anchor-0011223344556677",
        Separation::Separated,
        kp,
        lp,
    )
    .expect("a fully proved install must produce the env");
    let vars: Vec<&str> = env.engine_env().iter().map(|(k, _)| *k).collect();
    assert_eq!(vars, vec!["BRO_AUDIT_ANCHOR_SIGNER", "BRO_AUDIT_ANCHOR_KEY_ID"]);
    // Both halves of the engine's contract, or it is a half-configuration the engine refuses.
    assert!(env.evidence().contains("must be 0"), "{}", env.evidence());
}

#[test]
fn the_install_steps_name_the_virtual_account_and_never_a_password() {
    let paths = anc::SignerPaths::new(
        Path::new("C:\\ProgramData\\BroPS"),
        Path::new("C:\\Users\\gev\\AppData\\Local\\BroPS"),
        Path::new("C:\\Program Files\\BroPS"),
    );
    let steps = anc::install_steps(&paths, APP).join("\n");
    assert!(steps.contains("obj= \"NT SERVICE\\BroPSAuditSigner\""), "{steps}");
    assert!(steps.contains("sidtype"), "{steps}");
    // The point of a virtual account: no password exists, so no step may carry one. `sc.exe`
    // takes a real account's password as `password= <value>`; its total absence is the property.
    // (The service DESCRIPTION says the words "no password" on purpose, so a naive substring
    // check on "password" would be testing the prose rather than the command line.)
    assert!(!steps.contains("password= "), "{steps}");
    assert!(!steps.contains("/pass"), "{steps}");
    assert!(!steps.to_lowercase().contains("net user"), "{steps}");
    assert!(steps.contains("no password"), "the rationale must survive into the service description");
    // And the key is not minted by the elevated installer, which would have witnessed it.
    assert!(steps.contains("MINTS ITS OWN KEY"), "{steps}");
    assert!(anc::MINT_LOCATION_NOTE.contains("neither the installer nor the app"));
}

#[test]
fn the_two_roots_are_separate_and_the_shim_is_not_inside_the_engine() {
    let paths = anc::SignerPaths::new(
        Path::new("C:\\ProgramData\\BroPS"),
        Path::new("C:\\Users\\gev\\AppData\\Local\\BroPS"),
        Path::new("C:\\Program Files\\BroPS"),
    );
    // The key lives under a machine root; the ledger under the per-user root. Opposite
    // exclusions, so they cannot share a DACL by accident.
    assert!(!paths.key_file.starts_with(&paths.ledger_dir));
    assert!(!paths.ledger_dir.starts_with(&paths.signer_dir));
    // `bro_audit_log._signer_argv` refuses a signer path inside the engine root.
    let engine_root = PathBuf::from("C:\\Program Files\\BroPS\\engine");
    assert!(!paths.shim_path.starts_with(&engine_root));
}

// ---------------------------------------------------------------------------------------------
// What the signer will and will not sign
// ---------------------------------------------------------------------------------------------

const KEY_ID: &str = "audit-anchor-0011223344556677";
const LEDGER: &str = "C:\\Users\\gev\\AppData\\Local\\BroPS\\audit\\bro-audit.jsonl";
// Deliberately full of hex LETTERS: an all-digit digest is unchanged by `to_uppercase()`,
// so a case-sensitivity test built on one would pass without the check existing.
const H1: &str = "11aabb11ccdd11eeff11aabb11ccdd11eeff11aabb11ccdd11eeff11aabb11cc";
const H2: &str = "22bbcc22ddee22ffaa22bbcc22ddee22ffaa22bbcc22ddee22ffaa22bbcc22dd";

fn payload(count: i64, last_hash: &str, previous: Option<&str>) -> Value {
    json!({
        "artifact_type": "audit-head",
        "key_id": KEY_ID,
        "ledger": LEDGER,
        "count": count,
        "last_hash": last_hash,
        "previous_anchor_sha256": previous,
        "issued_at_epoch": 1_770_000_000i64,
    })
}

fn a_key() -> ed25519_dalek::SigningKey {
    ed25519_dalek::SigningKey::from_bytes(&[7u8; 32])
}

#[test]
fn the_payload_field_set_is_checked_as_an_exact_set() {
    // Subset checking would let a signing command smuggle an extra field into a document the
    // verifier then treats as authoritative — `bro_audit_log` says so, and the signer must not
    // rely on the engine to be the only one checking.
    let mut extra = payload(1, H1, None);
    extra["mode"] = json!("relaxed");
    assert!(matches!(
        anc::check_anchor_payload(&extra, KEY_ID),
        Err(SignRefusal::WrongFieldSet { .. })
    ));

    let mut missing = payload(1, H1, None);
    missing.as_object_mut().unwrap().remove("previous_anchor_sha256");
    match anc::check_anchor_payload(&missing, KEY_ID) {
        Err(SignRefusal::WrongFieldSet { missing, .. }) => {
            assert_eq!(missing, vec!["previous_anchor_sha256".to_string()]);
        }
        other => panic!("a missing field was accepted: {other:?}"),
    }
}

#[test]
fn this_key_signs_audit_heads_and_nothing_else() {
    // The anchor key is registered under the dedicated audit-anchor authority. If it could be made
    // to sign some other artifact_type, it would become an oracle for the governed chain.
    let mut p = payload(1, H1, None);
    p["artifact_type"] = json!("execution-lease");
    assert!(matches!(
        anc::check_anchor_payload(&p, KEY_ID),
        Err(SignRefusal::WrongArtifactType { .. })
    ));
    assert_eq!(anc::ANCHOR_ARTIFACT_TYPE, "audit-head");
    assert!(anc::ANCHOR_AUTHORITIES.contains(&anc::ANCHOR_AUTHORITY));
    // The narrowing itself: exactly one authority may anchor, and it is a type this crate never
    // mints a private half for. `provision()` walks `AUTHORITY_TYPES`; if the anchor authority
    // ever appeared there, the app's own account would hold the seed again and O-2 would reopen.
    assert_eq!(anc::ANCHOR_AUTHORITIES, ["audit-anchor"]);
    assert!(
        !brops_provision::AUTHORITY_TYPES.contains(&anc::ANCHOR_AUTHORITY),
        "provision() would mint a private half for the anchor authority"
    );
    // And it can be granted nothing in the registry: no artifact type binds to it, so its entry
    // carries an empty grant that cannot be widened by rewriting the registry.
    assert!(brops_provision::artifacts_for(anc::ANCHOR_AUTHORITY).is_empty());
}

#[test]
fn a_payload_naming_another_key_is_refused() {
    let p = payload(1, H1, None);
    assert!(matches!(
        anc::check_anchor_payload(&p, "audit-anchor-ffffffffffffffff"),
        Err(SignRefusal::WrongKeyId { .. })
    ));
}

#[test]
fn a_last_hash_that_is_not_a_sha256_is_refused() {
    let mut p = payload(1, "not-a-hash", None);
    assert!(matches!(
        anc::check_anchor_payload(&p, KEY_ID),
        Err(SignRefusal::NotSha256 { field: "last_hash", .. })
    ));
    // Uppercase hex is not the engine's encoding either.
    p["last_hash"] = json!(H1.to_uppercase());
    assert!(matches!(
        anc::check_anchor_payload(&p, KEY_ID),
        Err(SignRefusal::NotSha256 { .. })
    ));
}

#[test]
fn the_signer_refuses_a_count_below_the_last_one_it_signed() {
    // The engine's contract makes this the SIGNER's job, and it has to be: the app can rewrite
    // any state the app keeps, so only a principal the app cannot touch can remember a floor.
    let state = AnchorState {
        ledger: LEDGER.to_string(),
        count: 40,
        last_hash: H1.to_string(),
        anchor_sha256: H2.to_string(),
    };
    let fields = anc::check_anchor_payload(&payload(12, H1, Some(H2)), KEY_ID).unwrap();
    match anc::check_monotonic(&fields, Some(&state)) {
        Err(SignRefusal::CountRollback { last_signed, requested, .. }) => {
            assert_eq!((last_signed, requested), (40, 12));
        }
        other => panic!("a truncation was signed: {other:?}"),
    }
}

#[test]
fn the_signer_refuses_the_same_count_with_a_different_head() {
    // A rewritten ledger presented at the same length. The count check alone would pass it.
    let state = AnchorState {
        ledger: LEDGER.to_string(),
        count: 40,
        last_hash: H1.to_string(),
        anchor_sha256: H2.to_string(),
    };
    let fields = anc::check_anchor_payload(&payload(40, H2, Some(H2)), KEY_ID).unwrap();
    assert!(matches!(anc::check_monotonic(&fields, Some(&state)), Err(SignRefusal::HeadForked { .. })));

    // The same head at the same count is idempotent and allowed — re-signing an unchanged head
    // must not brick the ledger.
    let same = anc::check_anchor_payload(&payload(40, H1, Some(H2)), KEY_ID).unwrap();
    assert!(anc::check_monotonic(&same, Some(&state)).is_ok());
}

#[test]
fn removing_the_anchor_file_does_not_escape_the_rollback_check() {
    // `previous_anchor_sha256` is the digest of the anchor on disk. Deleting the anchor makes it
    // null, which would otherwise look like a fresh ledger.
    let state = AnchorState {
        ledger: LEDGER.to_string(),
        count: 40,
        last_hash: H1.to_string(),
        anchor_sha256: H2.to_string(),
    };
    let fields = anc::check_anchor_payload(&payload(41, H1, None), KEY_ID).unwrap();
    assert!(matches!(
        anc::check_monotonic(&fields, Some(&state)),
        Err(SignRefusal::AnchorChainBroken { .. })
    ));
}

#[test]
fn a_first_anchor_may_not_claim_a_predecessor_this_signer_never_wrote() {
    let fields = anc::check_anchor_payload(&payload(1, H1, Some(H2)), KEY_ID).unwrap();
    assert!(matches!(
        anc::check_monotonic(&fields, None),
        Err(SignRefusal::AnchorChainBroken { expected: None, .. })
    ));
    let clean = anc::check_anchor_payload(&payload(1, H1, None), KEY_ID).unwrap();
    assert!(anc::check_monotonic(&clean, None).is_ok());
}

#[test]
fn the_signer_refuses_to_run_as_the_ledgers_own_writer() {
    // The footgun guard. Pointing BRO_AUDIT_ANCHOR_SIGNER straight at the signer binary makes the
    // engine `subprocess.run` it under the APP's token — a different executable, the same
    // principal, and an anchor that proves nothing. This refuses before a key is touched.
    let err = anc::anchor_request(
        payload(1, H1, None),
        KEY_ID,
        SIGNER,
        APP,
        &a_key(),
        None,
    )
    .unwrap_err();
    match &err {
        SignRefusal::WrongPrincipal { expected, actual } => {
            assert_eq!(expected, SIGNER);
            assert_eq!(actual, APP);
        }
        other => panic!("the signer signed under the app's token: {other:?}"),
    }
    assert!(err.to_string().contains("prove nothing"), "{err}");
}

#[test]
fn a_signed_anchor_verifies_under_the_published_key_over_canonical_bytes() {
    // Real crypto, and specifically over `canonical_bytes` — the encoding
    // `bro_signature.verify_detached` recomputes. A signature over anything else would verify
    // here and be rejected by the engine, i.e. an anchor that silently never works.
    use ed25519_dalek::Verifier;

    let key = a_key();
    let (doc, state) = anc::anchor_request(
        payload(7, H1, None),
        KEY_ID,
        SIGNER,
        SIGNER,
        &key,
        None,
    )
    .expect("a well-formed first anchor must be signed");

    let bytes = brops_provision::canonical::canonical_bytes(&doc["payload"]).unwrap();
    let sig_hex = doc["signature"].as_str().unwrap();
    let sig_bytes = brops_provision::unhex(sig_hex).unwrap();
    let sig = ed25519_dalek::Signature::from_slice(&sig_bytes).unwrap();
    key.verifying_key().verify(&bytes, &sig).expect("the anchor must verify");

    // The state handed back is what the signer must persist to resist the next rollback.
    assert_eq!(state.count, 7);
    assert_eq!(state.last_hash, H1);
    // CORRECTED. This used to assert the digest was over `serde_json::to_vec(&doc)` - the
    // compact encoding - and it passed, because it was checking this crate's encoder against
    // itself. The engine digests the anchor FILE, and `bro_audit_log._install_anchor` writes
    // that file with `json.dumps(document, sort_keys=True)`: Python's DEFAULT separators, a
    // space after every `,` and `:`. The two differ, so the first anchor of a ledger installed
    // and the SECOND append was refused forever as AnchorChainBroken. Nothing in Rust could
    // find that; `audit-signer/tests/anchor_end_to_end.py` found it on its first run, and
    // `provision/tests/anchor_file_encoding.rs` now pins the encoder against the real
    // `json.dumps` so it cannot come back.
    assert_eq!(
        state.anchor_sha256,
        brops_provision::sha256_hex(&anc::installed_anchor_bytes(&doc).unwrap())
    );
    assert_ne!(
        state.anchor_sha256,
        brops_provision::sha256_hex(&serde_json::to_vec(&doc).unwrap()),
        "the compact encoding is NOT what the engine digests; if these ever coincide, this test          has stopped distinguishing the two encodings"
    );

    // And the chain closes: the next anchor must carry that digest.
    let next = anc::check_anchor_payload(&payload(8, H2, Some(&state.anchor_sha256)), KEY_ID).unwrap();
    assert!(anc::check_monotonic(&next, Some(&state)).is_ok());
    let wrong = anc::check_anchor_payload(&payload(8, H2, Some(H1)), KEY_ID).unwrap();
    assert!(matches!(
        anc::check_monotonic(&wrong, Some(&state)),
        Err(SignRefusal::AnchorChainBroken { .. })
    ));
}

#[test]
fn the_key_id_is_derived_from_the_public_half_and_cannot_be_chosen() {
    let a = anc::anchor_key_id("aa".repeat(32).as_str());
    let b = anc::anchor_key_id("bb".repeat(32).as_str());
    assert_ne!(a, b);
    assert!(a.starts_with("audit-anchor-"));
    assert_eq!(anc::anchor_key_id("aa".repeat(32).as_str()), a);
}

#[test]
fn the_custody_record_publishes_the_public_half_and_the_principal_but_no_secret() {
    let (key, public, key_id) = anc::mint_anchor_key().expect("mint");
    let record = anc::custody_record(&key_id, &public, SIGNER);
    let text = serde_json::to_string(&record).unwrap();
    assert!(text.contains(&public));
    assert!(text.contains(SIGNER));
    assert_eq!(record["authority"], "audit-anchor");
    // The seed must not be anywhere in what the app can read.
    let seed_hex = brops_provision::hex(&key.to_bytes());
    assert!(!text.contains(&seed_hex), "the custody record leaked the private half");
}

// ---------------------------------------------------------------------------------------------
// Real syscalls — Windows only, and honest about what needs Administrator
// ---------------------------------------------------------------------------------------------

/// Every access mask and world SID in `audit_signer` is a restatement of `pipe_acl`'s, because
/// this crate builds on Linux where `brops-win-live` is not in the graph. They cannot be allowed
/// to drift silently, so on Windows they are pinned against the real thing.
#[test]
#[cfg(windows)]
fn win_live_constants_have_not_drifted() {
    use brops_win_live::pipe_acl as pa;
    assert_eq!(anc::FILE_READ_DATA, pa::FILE_READ_DATA);
    assert_eq!(anc::FILE_WRITE_DATA, pa::FILE_WRITE_DATA);
    assert_eq!(anc::FILE_APPEND_DATA, pa::FILE_CREATE_PIPE_INSTANCE, "0x4 is one bit, two names");
    assert_eq!(anc::FILE_READ_ATTRIBUTES, pa::FILE_READ_ATTRIBUTES);
    assert_eq!(anc::FILE_WRITE_ATTRIBUTES, pa::FILE_WRITE_ATTRIBUTES);
    assert_eq!(anc::DELETE, pa::DELETE);
    assert_eq!(anc::READ_CONTROL, pa::READ_CONTROL);
    assert_eq!(anc::WRITE_DAC, pa::WRITE_DAC);
    assert_eq!(anc::WRITE_OWNER, pa::WRITE_OWNER);
    assert_eq!(anc::SYNCHRONIZE, pa::SYNCHRONIZE);
    assert_eq!(anc::FILE_ALL_ACCESS, pa::FILE_ALL_ACCESS);
    assert_eq!(anc::WRITE_ACCESS_BITS, pa::WRITE_ACCESS_BITS);
    assert_eq!(anc::SID_LOCAL_SYSTEM, pa::SID_LOCAL_SYSTEM);
    assert_eq!(anc::SID_ADMINISTRATORS, pa::SID_ADMINISTRATORS);
    assert_eq!(anc::FILE_READ_EA, brops_win_live::provision_custody::FILE_READ_EA);
    assert_eq!(anc::FILE_GENERIC_READ, brops_win_live::provision_custody::FILE_GENERIC_READ);
    // Every world SID pipe_acl knows must be one this module also refuses.
    for w in pa::WORLD_SIDS {
        assert!(anc::WORLD_SIDS.contains(w), "{w} is a world SID here but not there");
    }
    assert_eq!(anc::TCB_SIDS, brops_win_live::tcb_floor::TCB_OWNER_SIDS);
}

#[test]
#[cfg(windows)]
fn this_process_token_is_measured_and_the_verdict_is_reported_not_assumed() {
    let sid = anc::winimpl::current_user_sid().expect("own SID");
    assert!(anc::looks_like_sid(&sid), "{sid}");
    let posture = anc::winimpl::app_token_posture().expect("posture");
    let sep = Separation::from_posture(posture);
    println!("INFO app sid={sid} posture={posture:?} separation={sep:?}");
    println!("INFO claim: {}", sep.claim());
    // Whichever this box is, the claim must match the posture. This is the check that stops a
    // future edit from printing the strong sentence on a machine that has not earned it.
    //
    // Found while writing this, and worth keeping: on the box this was developed on,
    // `CheckTokenMembership(BUILTIN\Administrators)` answers FALSE and .NET's
    // `WindowsIdentity.IsInRole(Administrator)` agrees — while `whoami /groups` shows
    // `S-1-5-32-544` present as "Group used for deny only" and `net localgroup Administrators`
    // lists the account. A posture derived from `CheckTokenMembership` alone would therefore have
    // printed the STRONG claim on a machine whose human is one UAC consent away from the signer's
    // key. The deny-only scan is precisely why `app_token_posture` does not stop at that call.
    match posture {
        AppTokenPosture::StandardUser => assert_eq!(sep, Separation::Separated),
        _ => assert!(sep.claim().contains("does NOT hold")),
    }
}

#[test]
#[cfg(windows)]
fn resolve_service_sid_agrees_with_the_derived_sid() {
    // TrustedInstaller exists on every Windows install, so the SHA-1 derivation is checked
    // against this machine's own LSA without needing to create anything.
    let resolved = anc::winimpl::resolve_service_sid("TrustedInstaller")
        .expect("TrustedInstaller must resolve on any Windows box");
    assert_eq!(resolved, anc::service_account_sid("TrustedInstaller"));
    println!("INFO LSA and the offline derivation agree: {resolved}");
}

/// The behavioural half of the key proof, demonstrated for real — and it needs no privilege.
///
/// A file's owner may always rewrite its DACL, so this test can create a file and then remove
/// its own read access. Opening it must then fail with ERROR_ACCESS_DENIED. That is exactly the
/// syscall path a thief would take, so it is immune to ACE ordering, generic mappings, deny ACEs,
/// inheritance and ownership — the things a DACL read-back has to reason carefully about.
#[test]
#[cfg(windows)]
fn the_behavioural_probe_reports_real_denial_and_real_access() {
    let dir = tempfile::tempdir().unwrap();
    let readable = dir.path().join("readable.bin");
    std::fs::write(&readable, b"x").unwrap();
    assert_eq!(
        anc::winimpl::app_can_read(&readable),
        Ok(true),
        "a file this account can open must be reported as readable"
    );

    let me = anc::winimpl::current_user_sid().unwrap();
    let locked = dir.path().join("locked.bin");
    std::fs::write(&locked, b"secret").unwrap();
    // Grant ONLY Administrators. This account keeps the owner's implicit READ_CONTROL|WRITE_DAC
    // and loses FILE_READ_DATA, which is precisely the shape of the signer's key file.
    let plan = anc::DaclPlan {
        aces: vec![Ace {
            sid: anc::SID_ADMINISTRATORS.to_string(),
            mask: anc::FILE_ALL_ACCESS,
            inheritable: false,
        }],
        app_sid: me.clone(),
        signer_sid: anc::service_account_sid(anc::SIGNER_SERVICE_NAME),
        owner_sid: anc::SID_ADMINISTRATORS.to_string(),
    };
    // Owner is deliberately NOT stamped here: assigning BUILTIN\Administrators needs elevation.
    match anc::winimpl::apply_dacl(&locked, &plan, None) {
        Ok(()) => {}
        Err(e) => {
            skip(
                "the_behavioural_probe_reports_real_denial_and_real_access",
                &format!("SetNamedSecurityInfoW refused on this box: {e}"),
            );
            return;
        }
    }

    // 1. The behavioural proof: the kernel denies this account.
    assert_eq!(
        anc::winimpl::app_can_read(&locked),
        Ok(false),
        "a file with no ACE for this account must not open"
    );

    // 2. The read-back proof, computed rather than asserted. The owner keeps READ_CONTROL, so the
    //    descriptor is still measurable from here — which is exactly why the *installer* can prove
    //    the key file the app cannot even open.
    let facts = anc::winimpl::dacl_facts(&locked).expect("the owner can still read the descriptor");
    println!("INFO real read-back: {facts:?}");
    assert!(facts.dacl_present, "a NULL DACL would mean everyone-full-control");
    assert!(facts.dacl_protected, "PROTECTED_DACL_SECURITY_INFORMATION did not take effect");
    assert_eq!(
        anc::direct_mask(&facts, &me),
        0,
        "the DACL read back from disk still grants this account something"
    );
    assert_eq!(anc::unmapped_generic_grantees(&facts), Vec::<String>::new());
    assert_eq!(anc::world_grantees(&facts), Vec::<String>::new());

    // 3. The full key-custody verdict still refuses, because the OWNER could not be stamped
    //    without elevation — and an owner can rewrite the DACL at will.
    let key_plan_here = anc::key_dacl_plan(&me, &plan.signer_sid).unwrap();
    match anc::verify_key_custody(&key_plan_here, &facts) {
        Err(AnchorRefusal::UntrustedOwner { owner_sid, .. }) => {
            assert_eq!(owner_sid, me);
            skip(
                "the_behavioural_probe_reports_real_denial_and_real_access (owner half)",
                "assigning BUILTIN\\Administrators as owner needs SeRestorePrivilege, which an \
                 unelevated token does not hold, so only the DACL half of the key proof ran here",
            );
        }
        other => panic!("a file this account owns was accepted as key custody: {other:?}"),
    }
}

/// An ABSENT key must never be reported as "the app cannot read it".
///
/// `verify_installed` uses this probe as the app's half of the key proof. If a missing file
/// answered `Ok(false)`, then a box where the service had never started — and therefore had no key
/// at all — would produce a *passing* separation proof. The strongest-looking evidence would come
/// from the least-provisioned machine.
#[test]
#[cfg(windows)]
fn an_absent_key_is_unmeasurable_and_never_counts_as_denied() {
    let dir = tempfile::tempdir().unwrap();
    let missing = dir.path().join("never-created.key");
    match anc::winimpl::app_can_read(&missing) {
        Err(AnchorRefusal::Unmeasurable { why, .. }) => {
            assert!(why.contains("neither access nor denial"), "{why}");
        }
        other => panic!("an absent file was treated as a proof of denial: {other:?}"),
    }
}

/// The ledger half, for real, with no privilege at all — because the ledger is *meant* to be the
/// app's own directory.
#[test]
#[cfg(windows)]
fn the_ledger_directory_really_excludes_the_signer_when_locked() {
    let dir = tempfile::tempdir().unwrap();
    let ledger = dir.path().join("audit");
    std::fs::create_dir(&ledger).unwrap();
    let me = anc::winimpl::current_user_sid().unwrap();
    let signer = anc::service_account_sid(anc::SIGNER_SERVICE_NAME);
    let plan = anc::ledger_dacl_plan(&me, &signer).expect("ledger plan");

    if let Err(e) = anc::winimpl::apply_dacl(&ledger, &plan, None) {
        skip("the_ledger_directory_really_excludes_the_signer_when_locked", &format!("{e}"));
        return;
    }
    let facts = anc::winimpl::dacl_facts(&ledger).expect("read back the ledger dir");
    println!("INFO ledger read-back: {facts:?}");

    // Computed from the descriptor on disk, not from the plan that was submitted.
    let proof = anc::verify_ledger_custody(&plan, &facts).expect("the signer must hold no write");
    println!("INFO {}", proof.summary());
    assert_eq!(proof.observed_mask & anc::WRITE_ACCESS_BITS, 0);
    assert_eq!(proof.excluded_sid, signer);
    // The engine must still be able to create the ledger inside it.
    std::fs::write(ledger.join("bro-audit.jsonl"), b"{}\n").expect("the app must be able to append");
    // And the child really INHERITED the plan, which is the only way the engine's own files are
    // covered at all — the `.jsonl`, `.head`, `.anchor` and `.lock` are created by the engine,
    // not by this module, so inheritance is the entire mechanism protecting them.
    //
    // Note the trap this assertion is written around: if the ACEs carried no inheritance flags,
    // the child would be created with an EMPTY DACL, and "the signer holds nothing" would still
    // be true — of a file nobody can open. Checking only the signer's absence would therefore
    // pass on a completely broken applier. So check that the app's grant arrived as well.
    let child = anc::winimpl::dacl_facts(&ledger.join("bro-audit.jsonl")).unwrap();
    println!("INFO ledger child read-back: {child:?}");
    //
    // A second trap, found by mutation: dropping the inherit flags does NOT leave the child with
    // an empty DACL. Windows falls back to the creating token's DEFAULT DACL, which also grants
    // this account write and also omits the signer — so "the app can write and the signer cannot"
    // is true of a child that inherited nothing. The only assertion that distinguishes the two is
    // that the child's ACEs are EXACTLY the planned ones.
    let observed: Vec<(String, u32)> =
        child.allow_aces.iter().map(|a| (a.sid.clone(), a.mask)).collect();
    let expected: Vec<(String, u32)> =
        plan.aces.iter().map(|a| (a.sid.clone(), a.mask)).collect();
    assert_eq!(
        observed, expected,
        "the ledger file did not inherit the planned DACL; this is what a token-default DACL          looks like when the directory's ACEs carry no inheritance flags"
    );
    assert_eq!(anc::direct_mask(&child, &signer), 0, "the ledger file did not inherit the plan");
    assert_ne!(anc::direct_mask(&child, &me) & anc::FILE_WRITE_DATA, 0);
}

/// The end-to-end verdict cannot be produced on a box where the service was never installed, and
/// installing it needs Administrator. Assert the refusal names that, and SKIP the rest loudly.
#[test]
#[cfg(windows)]
fn without_the_installed_service_the_whole_thing_refuses() {
    let paths = anc::SignerPaths::new(
        Path::new("C:\\ProgramData\\BroPS"),
        Path::new("C:\\Users\\gev\\AppData\\Local\\BroPS"),
        Path::new("C:\\Program Files\\BroPS"),
    );
    match anc::verify_installed(&paths, KEY_ID) {
        Err(AnchorRefusal::SignerAbsent { why }) => {
            assert!(why.contains("BroPSAuditSigner"), "{why}");
            skip(
                "without_the_installed_service_the_whole_thing_refuses (install half)",
                "creating the NT SERVICE\\BroPSAuditSigner virtual account requires \
                 SC_MANAGER_CREATE_SERVICE, i.e. an ELEVATED token. This session runs at medium \
                 integrity with BUILTIN\\Administrators present DENY-ONLY, so the SCM refuses, the \
                 service does not exist, and the syscall path through verify_installed past step \
                 2 was NOT exercised. Steps 3-5 (the behavioural probe and both read-back proofs) \
                 are covered instead by the two tests above, against real descriptors on disk",
            );
        }
        Err(AnchorRefusal::SignerSidSubstituted { derived, resolved, .. }) => {
            panic!("something is impersonating the signer service: {derived} vs {resolved}");
        }
        Ok(status) => {
            // The service IS installed on this box; then the full proof must hold.
            println!("INFO {}", status.env.evidence());
            assert_ne!(status.app_sid, status.signer_sid);
        }
        Err(other) => panic!("unexpected refusal shape: {other}"),
    }
}

#[test]
#[cfg(not(windows))]
fn off_windows_every_syscall_entry_point_refuses_rather_than_pretending() {
    assert!(matches!(
        anc::winimpl::current_user_sid(),
        Err(AnchorRefusal::Unsupported { .. })
    ));
    assert!(matches!(
        anc::winimpl::dacl_facts(Path::new("/tmp/x")),
        Err(AnchorRefusal::Unsupported { .. })
    ));
    assert!(matches!(
        anc::winimpl::app_can_read(Path::new("/tmp/x")),
        Err(AnchorRefusal::Unsupported { .. })
    ));
    // ...and the pure decisions above still ran on this host, which is the whole point of the
    // pure/effect split.
    assert!(anc::key_dacl_plan(APP, SIGNER).is_ok());
}
