//! The relay contract and the signer's custody, as pure decisions — the shape
//! `audit_signer.rs` established, for the same reason: every one of these runs on a host with no
//! SCM, no service account and no named pipe, so the parts that cannot rot are the parts that
//! rot silently.
//!
//! Every clause asserted here was read out of `engine/runtime/bro_audit_log.py`, not inferred:
//! the exit-code handling from `_sign_anchor`, the `{payload, signature}` key set from
//! `verify_signed_payload`, the canonical encoding from `_canonical`, the argv shape from
//! `_signer_argv`.

use std::collections::BTreeMap;
use std::path::Path;

use serde_json::{json, Value};

use brops_audit_signer as shim;
use brops_audit_signer::{custody, register, relay, AnchorCore};
use brops_provision::audit_signer as spec;

const APP: &str = "S-1-5-21-11-22-33-1001";

fn args(list: &[&str]) -> Vec<String> {
    list.iter().map(|s| s.to_string()).collect()
}

fn payload(count: i64, last_hash: &str, previous: Option<&str>, key_id: &str) -> Value {
    json!({
        "artifact_type": spec::ANCHOR_ARTIFACT_TYPE,
        "key_id": key_id,
        "ledger": "bro-audit.jsonl",
        "count": count,
        "last_hash": last_hash,
        "previous_anchor_sha256": previous,
        "issued_at_epoch": 1_700_000_000,
    })
}

const H1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
const H2: &str = "2222222222222222222222222222222222222222222222222222222222222222";

/// A core whose principal check passes, so the tests that are about something else are not all
/// about the principal check.
fn core(dir: &Path, running_as: &str) -> AnchorCore {
    let held = custody::load_or_mint(dir, running_as).expect("mint");
    AnchorCore::new(held, running_as, running_as, &dir.join(spec::STATE_FILE_NAME)).expect("core")
}

// =================================================================================================
// The argv contract — `bro_audit_log._signer_argv`
// =================================================================================================

#[test]
fn the_shim_defaults_to_the_pipe_the_specification_names() {
    // `_signer_argv` accepts a bare absolute path with no extra arguments, so the no-argument
    // invocation has to work and has to reach the right pipe.
    assert_eq!(
        relay::parse_args(&args(&[])),
        relay::Invocation::Relay { pipe: spec::SIGNER_PIPE_NAME.to_string() }
    );
}

#[test]
fn the_pipe_can_be_named_in_argv_because_that_is_the_channel_the_engine_passes_through() {
    // `_signer_argv` returns `[resolved] + argv[1:]` for a JSON array, which is the ONLY way an
    // installer can reach this process without going through the app's environment.
    assert_eq!(
        relay::parse_args(&args(&["--pipe", "some-pipe"])),
        relay::Invocation::Relay { pipe: "some-pipe".to_string() }
    );
}

#[test]
fn an_argument_this_shim_does_not_understand_is_refused_rather_than_ignored() {
    for bad in [args(&["--pipe"]), args(&["--pipe", ""]), args(&["--key", "x"]), args(&["junk"])] {
        assert!(
            matches!(relay::parse_args(&bad), relay::Invocation::BadArgs { .. }),
            "{bad:?} should be refused: a shim that ignored an argument would silently relay to \
             the default pipe when the installer meant another one"
        );
    }
}

// =================================================================================================
// The stdin contract — `_canonical`, and what survives the relay
// =================================================================================================

#[test]
fn the_request_bytes_are_the_ones_python_canonical_produces() {
    // `_canonical` is json.dumps(obj, sort_keys=True, separators=(",", ":")). Sorted keys, no
    // spaces, null spelled `null`. Written out literally so a change to either canonicaliser has
    // to change this string too.
    let bytes = shim::canonical_request_bytes(&payload(1, H1, None, "audit-anchor-abc")).unwrap();
    assert_eq!(
        String::from_utf8(bytes).unwrap(),
        "{\"artifact_type\":\"audit-head\",\"count\":1,\"issued_at_epoch\":1700000000,\
         \"key_id\":\"audit-anchor-abc\",\"last_hash\":\"1111111111111111111111111111111111111111111111111111111111111111\",\
         \"ledger\":\"bro-audit.jsonl\",\"previous_anchor_sha256\":null}"
    );
}

#[test]
fn the_payload_survives_the_relays_json_round_trip() {
    // The shim parses stdin and forwards the VALUE, not the bytes. `_sign_anchor` then refuses
    // unless `document["payload"] == payload` as Python dicts. Key order is therefore free, but
    // every value must come back identical — which holds because ANCHOR_PAYLOAD_FIELDS carries
    // only strings, integers and null. If a float or a big integer were ever added, this breaks
    // first.
    for previous in [None, Some(H2)] {
        let original = payload(7, H1, previous, "audit-anchor-abc");
        let bytes = shim::canonical_request_bytes(&original).unwrap();
        assert_eq!(shim::parse_request(&bytes).unwrap(), original);
    }
}

#[test]
fn stdin_that_is_not_a_json_object_is_refused_by_the_shim_and_never_reaches_the_key() {
    assert!(shim::parse_request(b"not json").is_err());
    assert!(shim::parse_request(b"[1,2,3]").is_err());
    assert!(shim::parse_request(b"\"a string\"").is_err());
    assert!(shim::parse_request(b"{}").is_ok(), "an empty object is the SIGNER's to refuse");
}

// =================================================================================================
// The stdout contract — `verify_signed_payload`'s exact key set
// =================================================================================================

#[test]
fn only_an_exact_payload_signature_document_is_treated_as_a_document() {
    let good = json!({"payload": {"a": 1}, "signature": "ab"});
    assert!(shim::is_engine_shaped_document(&good));
    for bad in [
        json!({"payload": {"a": 1}}),
        json!({"signature": "ab"}),
        // The trap this exists for: a helpful extra field. `verify_signed_payload` refuses any
        // document whose key set is not exactly {payload, signature}, so attaching a key_id would
        // produce anchors that are signed and then rejected.
        json!({"payload": {"a": 1}, "signature": "ab", "key_id": "k"}),
        json!({"payload": "not an object", "signature": "ab"}),
        json!({"payload": {"a": 1}, "signature": ""}),
        json!({"payload": {"a": 1}, "signature": 7}),
        json!([1, 2]),
    ] {
        assert!(!shim::is_engine_shaped_document(&bad), "{bad} must not pass as a document");
    }
}

#[test]
fn a_refusal_can_never_be_mistaken_for_a_document() {
    let refusal = shim::refusal("nope");
    assert!(shim::is_refusal(&refusal));
    assert!(!shim::is_engine_shaped_document(&refusal));
    assert!(refusal.get("signature").is_none(), "a refusal must carry no signature field at all");
}

// =================================================================================================
// The exit-code contract — `_sign_anchor`
// =================================================================================================

#[test]
fn every_failure_exits_non_zero_with_an_empty_stdout() {
    // `_sign_anchor` reads exit 0 as "there is a document on stdout" and json.loads()es it. A
    // failure that exited 0, or that printed a diagnostic on stdout, would surface as "the signing
    // command did not return a signed document" — sending an operator to look for a crypto fault.
    let good = shim::canonical_request_bytes(&payload(1, H1, None, "k")).unwrap();
    let cases: Vec<(&str, Vec<String>, Vec<u8>, Box<dyn Fn(&str, &Value) -> Result<Value, String>>)> = vec![
        ("bad args", args(&["--nope"]), good.clone(), Box::new(|_, _| unreachable!())),
        ("bad stdin", args(&[]), b"not json".to_vec(), Box::new(|_, _| unreachable!())),
        ("unreachable", args(&[]), good.clone(), Box::new(|_, _| Err("no service".into()))),
        (
            "refused",
            args(&[]),
            good.clone(),
            Box::new(|_, _| Ok(shim::refusal("ANTI-ROLLBACK: no"))),
        ),
        (
            "not a document",
            args(&[]),
            good.clone(),
            Box::new(|_, _| Ok(json!({"payload": {}, "signature": "ab", "extra": 1}))),
        ),
    ];
    for (name, argv, stdin, roundtrip) in cases {
        let (code, stdout, message) = relay::run_with(&argv, &stdin, roundtrip);
        assert_ne!(code, relay::EXIT_OK, "{name} exited 0");
        assert!(stdout.is_empty(), "{name} wrote {} bytes to stdout", stdout.len());
        assert!(!message.trim().is_empty(), "{name} refused without saying why");
    }
}

#[test]
fn the_exit_codes_distinguish_unreachable_from_refused_from_malformed() {
    let good = shim::canonical_request_bytes(&payload(1, H1, None, "k")).unwrap();
    let code = |r: Box<dyn Fn(&str, &Value) -> Result<Value, String>>| {
        relay::run_with(&args(&[]), &good, r).0
    };
    assert_eq!(code(Box::new(|_, _| Err("gone".into()))), relay::EXIT_UNREACHABLE);
    assert_eq!(code(Box::new(|_, _| Ok(shim::refusal("no")))), relay::EXIT_REFUSED);
    assert_eq!(code(Box::new(|_, _| Ok(json!({"nonsense": 1})))), relay::EXIT_BAD_REPLY);
    assert_eq!(relay::run_with(&args(&["--x"]), &good, |_, _| unreachable!()).0, relay::EXIT_BAD_ARGS);
    assert_eq!(relay::run_with(&args(&[]), b"{", |_, _| unreachable!()).0, relay::EXIT_BAD_STDIN);
}

#[test]
fn a_successful_relay_prints_exactly_the_document_and_exits_zero() {
    let good = shim::canonical_request_bytes(&payload(1, H1, None, "k")).unwrap();
    let document = json!({"payload": payload(1, H1, None, "k"), "signature": "aabb"});
    let reply = document.clone();
    let (code, stdout, message) =
        relay::run_with(&args(&[]), &good, move |_, _| Ok(reply.clone()));
    assert_eq!(code, relay::EXIT_OK);
    assert!(message.is_empty());
    let printed: Value = serde_json::from_slice(&stdout).expect("stdout must parse as JSON");
    assert_eq!(printed, document);
}

#[test]
fn the_shim_gives_up_well_inside_the_engines_ten_second_budget() {
    // `_SIGNER_TIMEOUT` is 10s AND the ledger's exclusive append lock is held throughout. Being
    // killed at the timeout leaves the record written and the anchor stale.
    assert!(
        relay::CONNECT_DEADLINE < std::time::Duration::from_secs(10),
        "the shim's deadline must be strictly inside bro_audit_log._SIGNER_TIMEOUT"
    );
    assert!(
        relay::CONNECT_DEADLINE <= std::time::Duration::from_secs(7),
        "leave the engine room to report the refusal rather than time out on us"
    );
}

// =================================================================================================
// The binaries the install plan promises
// =================================================================================================

#[test]
fn the_binaries_are_named_what_the_install_plan_promises() {
    // `SignerPaths` builds the installer's `binPath=` from these names. A rename here and a stale
    // name there produces a service the SCM starts and a file that is not there.
    for (built, promised) in [
        (env!("CARGO_BIN_EXE_brops-anchor-relay"), spec::SHIM_EXE_NAME),
        (env!("CARGO_BIN_EXE_brops-audit-signer"), spec::SERVICE_EXE_NAME),
    ] {
        let stem = Path::new(built).file_stem().unwrap().to_string_lossy().to_string();
        let promised_stem = promised.trim_end_matches(".exe");
        assert_eq!(stem, promised_stem, "{built} does not match {promised}");
        assert!(Path::new(built).is_file(), "{built} was not built");
    }
}

#[test]
fn the_install_plan_names_the_peer_allowlist_the_specification_left_out() {
    let paths = spec::SignerPaths::new(
        Path::new("C:\\ProgramData\\BroPS"),
        Path::new("C:\\Users\\x\\AppData\\Local\\BroPS"),
        Path::new("C:\\Program Files\\BroPS"),
    );
    let plan = register::install_plan(&paths, APP).join("\n");
    assert!(plan.contains("sc.exe create"), "the SCM steps are still there");
    assert!(plan.contains(register::ALLOWED_APP_SID_FILE), "the peer allowlist file is named");
    assert!(plan.contains(APP), "the app SID the signer will accept is named");
    assert!(
        plan.contains("register_anchor_key"),
        "the plan says how the engine learns to resolve the anchor's key_id"
    );
    // The plan may only ever MENTION a password to say there isn't one. A virtual service
    // account has none; any step that supplied one (`sc.exe create ... password= ...`, `/P`)
    // would mean a secret in the installer's argv, visible in the process list.
    assert!(plan.contains("no password"), "the plan must say the account has no password");
    for supplied in ["password=", "/P ", "-P ", "obj= \".\\\\"] {
        assert!(!plan.contains(supplied), "the plan supplies a credential: {supplied:?}");
    }
}

// =================================================================================================
// The signer's decision, over the real key
// =================================================================================================

#[test]
fn a_signed_anchor_is_engine_shaped_and_advances_the_high_water_mark() {
    let dir = tempfile::tempdir().unwrap();
    let core = core(dir.path(), "S-1-5-80-1-2-3-4-5");
    let key_id = core.key_id().to_string();

    let document = core.decide(&payload(1, H1, None, &key_id));
    assert!(
        shim::is_engine_shaped_document(&document),
        "the signer returned {document}, which verify_signed_payload would refuse"
    );

    // Recorded before the reply, and recorded on DISK: a signer that forgot a count it had signed
    // would sign a lower one after a restart.
    let state = custody::load_state(&dir.path().join(spec::STATE_FILE_NAME)).unwrap();
    assert_eq!(state["bro-audit.jsonl"].count, 1);
    assert_eq!(state["bro-audit.jsonl"].last_hash, H1);
}

#[test]
fn the_signer_refuses_a_count_below_the_one_it_last_signed() {
    let dir = tempfile::tempdir().unwrap();
    let core = core(dir.path(), "S-1-5-80-1-2-3-4-5");
    let key_id = core.key_id().to_string();
    let first = core.decide(&payload(2, H1, None, &key_id));
    assert!(shim::is_engine_shaped_document(&first));

    let rolled_back = core.decide(&payload(1, H2, None, &key_id));
    assert!(shim::is_refusal(&rolled_back), "a rollback was signed: {rolled_back}");
    let reason = rolled_back["reason"].as_str().unwrap();
    assert!(reason.contains("ANTI-ROLLBACK"), "{reason}");
}

#[test]
fn the_signer_refuses_when_it_is_not_running_as_the_principal_it_is_supposed_to_be() {
    // This is what makes "point BRO_AUDIT_ANCHOR_SIGNER at the signer binary" produce nothing:
    // the child would run as the app, and the core refuses before the key is used.
    let dir = tempfile::tempdir().unwrap();
    let held = custody::load_or_mint(dir.path(), APP).unwrap();
    let key_id = held.key_id.clone();
    let core = AnchorCore::new(
        held,
        &spec::service_account_sid(spec::SIGNER_SERVICE_NAME),
        APP,
        &dir.path().join(spec::STATE_FILE_NAME),
    )
    .unwrap();
    let reply = core.decide(&payload(1, H1, None, &key_id));
    assert!(shim::is_refusal(&reply), "the app's own account got a signature: {reply}");
    assert!(reply["reason"].as_str().unwrap().contains("Refusing to use the anchor key"));

    // And nothing was recorded, so the refusal cannot be used to burn a count.
    assert!(custody::load_state(&dir.path().join(spec::STATE_FILE_NAME)).unwrap().is_empty());
}

#[test]
fn the_signer_refuses_a_payload_naming_a_key_it_does_not_hold() {
    let dir = tempfile::tempdir().unwrap();
    let core = core(dir.path(), "S-1-5-80-1-2-3-4-5");
    let reply = core.decide(&payload(1, H1, None, "audit-anchor-somebody-else"));
    assert!(shim::is_refusal(&reply), "{reply}");
}

#[test]
fn the_signer_signs_audit_heads_and_nothing_else() {
    let dir = tempfile::tempdir().unwrap();
    let core = core(dir.path(), "S-1-5-80-1-2-3-4-5");
    let key_id = core.key_id().to_string();
    let mut other = payload(1, H1, None, &key_id);
    other["artifact_type"] = json!("execution-lease");
    let reply = core.decide(&other);
    assert!(shim::is_refusal(&reply), "the anchor key became a registry-artifact oracle: {reply}");
}

// =================================================================================================
// Key custody on disk
// =================================================================================================

#[test]
fn the_key_is_minted_once_and_never_replaced_by_a_later_start() {
    let dir = tempfile::tempdir().unwrap();
    let first = custody::load_or_mint(dir.path(), "S-1-5-80-1-2-3-4-5").unwrap();
    assert!(first.freshly_minted);
    let second = custody::load_or_mint(dir.path(), "S-1-5-80-1-2-3-4-5").unwrap();
    assert!(!second.freshly_minted, "a restart re-minted the key");
    assert_eq!(first.key_id, second.key_id);
    assert_eq!(first.public_key, second.public_key);
}

#[test]
fn the_published_custody_record_carries_the_public_half_and_no_secret() {
    let dir = tempfile::tempdir().unwrap();
    let held = custody::load_or_mint(dir.path(), "S-1-5-80-1-2-3-4-5").unwrap();
    let record = custody::read_custody(dir.path()).unwrap();
    assert_eq!(record["public_key"], json!(held.public_key));
    assert_eq!(record["key_id"], json!(held.key_id));
    assert_eq!(record["authority"], json!(spec::ANCHOR_AUTHORITY));

    // Two separate questions. First: is the actual secret in there, anywhere at all?
    let seed = brops_provision::hex(held.key.as_bytes());
    let text = serde_json::to_string(&record).unwrap();
    assert!(!text.contains(&seed), "the published record leaks the seed");
    // Second: is there a FIELD that would carry one? Checked as key names, not as substrings of
    // the whole document, because MINT_LOCATION_NOTE legitimately contains the word "seed" while
    // explaining that this file does not hold it.
    let fields = shim::field_names(&record);
    for field in ["private_key", "seed", "secret", "signing_key"] {
        assert!(!fields.iter().any(|f| f == field), "the published record has a {field} field");
    }
}

#[test]
fn a_custody_record_that_leaked_a_secret_is_refused_by_every_reader() {
    let dir = tempfile::tempdir().unwrap();
    custody::load_or_mint(dir.path(), "S-1-5-80-1-2-3-4-5").unwrap();
    let path = dir.path().join(spec::CUSTODY_FILE_NAME);
    let mut record: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    record["private_key"] = json!("deadbeef");
    std::fs::write(&path, serde_json::to_vec(&record).unwrap()).unwrap();
    assert!(
        custody::read_custody(dir.path()).is_err(),
        "a custody record carrying a secret was accepted; the record is world-readable by design"
    );
}

#[test]
fn a_corrupt_state_file_is_an_error_and_never_an_empty_high_water_mark() {
    // "I cannot read what I signed" must not become "I have signed nothing", which would reset
    // the rollback floor to zero — the exact thing an attacker who can touch the file would want.
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(spec::STATE_FILE_NAME);
    assert!(custody::load_state(&path).unwrap().is_empty(), "a MISSING file is a first start");
    for corrupt in ["not json", "{}", "{\"ledgers\":[{\"ledger\":\"x\"}]}"] {
        std::fs::write(&path, corrupt).unwrap();
        assert!(custody::load_state(&path).is_err(), "{corrupt:?} was read as empty state");
    }
}

#[test]
fn a_key_file_that_is_not_a_seed_is_refused_rather_than_minted_over() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(dir.path()).unwrap();
    std::fs::write(dir.path().join(spec::KEY_FILE_NAME), "hello").unwrap();
    let Err(err) = custody::load_or_mint(dir.path(), "S-1-5-80-1-2-3-4-5") else {
        panic!("a key file that is not a seed was minted over");
    };
    assert!(
        err.to_string().contains("silently invalidates"),
        "a replaced key stops every installed anchor verifying: {err}"
    );
}

#[test]
fn the_state_round_trips_through_disk_unchanged() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(spec::STATE_FILE_NAME);
    let mut state = BTreeMap::new();
    state.insert(
        "a.jsonl".to_string(),
        spec::AnchorState {
            ledger: "a.jsonl".into(),
            count: 42,
            last_hash: H1.into(),
            anchor_sha256: H2.into(),
        },
    );
    custody::save_state(&path, &state).unwrap();
    assert_eq!(custody::load_state(&path).unwrap(), state);
}

// =================================================================================================
// The peer allowlist
// =================================================================================================

#[test]
fn the_signer_will_not_serve_without_an_installer_written_peer_allowlist() {
    let dir = tempfile::tempdir().unwrap();
    let err = register::read_allowed_app_sid(dir.path()).unwrap_err();
    assert!(err.contains("signing oracle"), "{err}");
}

#[test]
fn a_world_sid_in_the_peer_allowlist_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    for sid in ["S-1-1-0", "S-1-5-11", "S-1-5-32-545"] {
        std::fs::write(dir.path().join(register::ALLOWED_APP_SID_FILE), sid).unwrap();
        assert!(
            register::read_allowed_app_sid(dir.path()).is_err(),
            "{sid} would serve every account on the box"
        );
    }
    std::fs::write(dir.path().join(register::ALLOWED_APP_SID_FILE), format!("{APP}\n")).unwrap();
    assert_eq!(register::read_allowed_app_sid(dir.path()).unwrap(), APP);
}

#[test]
fn a_peer_allowlist_that_is_not_a_sid_is_refused_rather_than_treated_as_a_name() {
    let dir = tempfile::tempdir().unwrap();
    for junk in ["BUILTIN\\Users", "", "S-1-", "not a sid"] {
        std::fs::write(dir.path().join(register::ALLOWED_APP_SID_FILE), junk).unwrap();
        assert!(register::read_allowed_app_sid(dir.path()).is_err(), "{junk:?} was accepted");
    }
}

// =================================================================================================
// The caveat is not decoration
// =================================================================================================

/// Re-aimed twice, never deleted. It first asserted that the caveat named the two anchor
/// authorities the app held private halves for; then, once those stopped being anchor
/// authorities, that it named the operator root the app still kept. The root is now destroyed at
/// the end of provisioning, so that sentence would be false too.
///
/// What has to be true in every version is the same thing: the caveat states the limit of what
/// the anchor key buys and names the route that is STILL open, rather than reading as a closure
/// notice. The route moved — it is no longer a key at all, it is the PIN — so that is what is
/// asserted, and a caveat that stopped naming it fails here.
#[test]
fn the_registry_caveat_states_the_residual_route_rather_than_implying_it_is_closed() {
    let caveat = register::REGISTRY_CAVEAT;
    // The narrowing, so the caveat cannot go stale in the other direction either.
    assert!(caveat.contains("ONLY the audit-anchor authority"), "{caveat}");
    // What destroying the root DID buy: a registry nobody can amend.
    assert!(caveat.contains("destroyed before"), "{caveat}");
    assert!(caveat.contains("sealed"), "{caveat}");
    // And the honest remainder, which is now the pin rather than a key.
    assert!(caveat.contains("residual"), "{caveat}");
    assert!(caveat.contains("not a key at all"), "{caveat}");
    assert!(caveat.contains("PIN"), "{caveat}");
    assert!(caveat.contains("trust directory"), "{caveat}");
    assert!(caveat.contains("second principal"), "{caveat}");
    // It must not claim the item is finished.
    assert!(!caveat.to_lowercase().contains("o-2 is closed"), "{caveat}");
}
