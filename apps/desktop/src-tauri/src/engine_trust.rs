//! The one place this deployment hands the engine its provisioned trust material.
//!
//! # The defect this closes (O-3)
//!
//! `brops_provision` mints, on first launch, everything the engine's governance chain
//! needs: the seven authority keypairs, the operator-signed `trusted-key-registry`, the
//! out-of-registry operator-root pin in a machine-wide anchor this account cannot write,
//! an anti-rollback floor, and the operator-signed `conductor-session` artifact. All of
//! it is proven byte-compatible against the REAL Python verifiers by
//! `provision/tests/python_verifier.rs`.
//!
//! **Nothing exported any of it.** `Provisioned::engine_env()` was returned and dropped;
//! its only callers were tests. So `bro_signature.load_trusted_keys` kept reading the
//! registry committed at `engine/config/trusted-keys.json` — `production: false`, carrying
//! a DEVELOPMENT REGISTRY warning, signed by an operator key this machine never minted,
//! and granting `conductor-session` to no key at all. Every artifact provisioning minted
//! verified perfectly against a registry nothing consulted. That is why O-3 stood open on
//! a wiring line rather than on a secret.
//!
//! # The precedence rule, and why it is a refusal rather than an order
//!
//! Exporting unconditionally is not available. `bro_signature._resolve_operator_root_pin`
//! **hard-fails** when the file pin and the CI raw pin `BRO_OPERATOR_ROOT_PUBKEY` name
//! different keys, so stamping `BRO_OPERATOR_ROOT_PUBKEY_FILE` onto an environment that
//! already carries a different raw pin breaks it — and `resolve_registry_floor` fails the
//! same way for the floor. The two directions of "just pick a winner" are both wrong:
//!
//! * *Provisioned wins, silently.* The app overwrites an anchor a deployment configured on
//!   purpose, and the engine then verifies against a trust root its operator did not
//!   choose. That is the application selecting its own trust root — the exact move every
//!   custody rule in `bro_signature` exists to prevent.
//! * *Ambient wins, silently.* The app reports a provisioned, sealed, custody-proved trust
//!   store while the engine consults something else entirely, with nothing saying so.
//!
//! So there is **no precedence order**, exactly as `resolve_operator_root_pin` has none:
//!
//! 1. The provisioned set is applied **whole or not at all**. A subset is the half-wired
//!    state that is worse than no export — some checks on the provisioned trust, others on
//!    the stale committed registry. [`brops_provision::Provisioned::engine_env`] is the
//!    single source of the set, so a variable added there is automatically covered here.
//! 2. An ambient value for one of those variables is fine only when it **agrees** with the
//!    provisioned one; disagreement is a hard, named refusal listing both values. Nothing
//!    is ever removed from the child environment: silently deleting an operator's
//!    deliberate configuration is the same silent precedence, one step further along.
//! 3. `BRO_OPERATOR_ROOT_PUBKEY` (the CI raw pin) is refused unless it is byte-equal to
//!    the operator public key provisioning minted. This is checkable because the pin IS
//!    the key.
//! 4. `BRO_OPERATOR_REGISTRY_MIN` (the CI raw floor) is refused whenever it is present at
//!    all. The asymmetry with (3) is deliberate and is not laziness: the floor this
//!    deployment pins lives in the CONTENTS of `<anchor>/registry-min`, not in a value
//!    this struct holds, so "do they agree?" cannot be answered without reading the anchor
//!    — and a refusal that guesses is worse than one that says it cannot tell.
//! 5. `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` is refused whenever it is present. It does not
//!    weaken one check: `bro_custody` short-circuits EVERY custody rule in the runtime
//!    when it is set — the operator pin, the redirected registry root, the evidence floor
//!    and the evidence store. Exporting a sealed anchor and then letting an inherited
//!    variable switch off the check that it is sealed would leave everything O-2 built in
//!    place with nothing measuring it.
//! 6. Provisioning not having recorded anything is a refusal, not a pass-through. The
//!    alternative is running the engine against the committed development registry, which
//!    is the defect. In the shipped app this cannot happen: `run()` calls
//!    `provision_local_trust` before the database is opened and a failure aborts startup.
//!
//! Every refusal is returned to the caller and surfaces as the governed call failing
//! closed. None of it is applied to THIS process: `std::env::set_var` is process-wide,
//! racy against every other thread, and would make the host's own environment depend on
//! startup order. The variables are set on the child command and nowhere else.

use std::sync::OnceLock;

/// The CI raw operator-root pin. Never exported here; see rule (3).
pub const RAW_CI_PIN: &str = "BRO_OPERATOR_ROOT_PUBKEY";
/// The CI raw anti-rollback floor. Never exported here; see rule (4).
pub const RAW_CI_FLOOR: &str = "BRO_OPERATOR_REGISTRY_MIN";
/// The acknowledgement that disables every custody rule at once. See rule (5).
pub const SELF_OWNED_ACK: &str = "BRO_OPERATOR_ROOT_PIN_SELF_OWNED";
/// The production FILE form of the same acknowledgement, and refused on the same terms.
///
/// `bro_custody` gained it when the raw variable was brought under the `BRO_ENV=ci` gate its
/// two sibling anchors already had; outside CI the posture is declared in a file. Knowing only
/// the raw name would have left this rule with a hole exactly the shape of the thing it
/// refuses: a deployment could switch off every custody rule in the engine runtime through the
/// file form while the blanket refusal below saw nothing.
pub const SELF_OWNED_ACK_FILE: &str = "BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE";

/// Refusal text when nothing was recorded. Named as a constant so the test that proves
/// the fail-closed default cannot drift from the message an operator actually sees.
pub const NOT_PROVISIONED: &str =
    "the engine's trust environment was never recorded, so this deployment cannot say \
     which trusted-key registry the engine would read. Refusing rather than running it \
     against the development registry committed at engine/config/trusted-keys.json \
     (production: false, and it grants conductor-session to no key). First-launch \
     provisioning records it; a startup that reached here without provisioning is a bug, \
     not a configuration.";

/// What provisioning recorded, kept as INPUTS rather than as a decision.
///
/// The decision is recomputed on every spawn instead of once at startup, because the
/// ambient environment is mutable and a verdict cached at startup would be a claim about
/// the past — the same reason `anchor::CustodyProof` is re-measured per launch rather
/// than read from a file.
struct Recorded {
    pairs: Vec<(&'static str, String)>,
    operator_public_key: String,
}

static RECORDED: OnceLock<Recorded> = OnceLock::new();

/// Record what first-launch provisioning produced. Called once, from startup.
///
/// A second call is ignored rather than panicking: provisioning runs once per process by
/// construction, and a startup path that somehow called twice must not take the app down
/// after the trust store is already established.
pub fn record(provisioned: &brops_provision::Provisioned) {
    let _ = RECORDED.set(Recorded {
        pairs: provisioned.engine_env(),
        operator_public_key: provisioned.operator_public_key.clone(),
    });
}

/// An ambient reader that treats an empty/whitespace value as absent — which is how
/// `bro_signature` reads every one of these (`(env.get(X) or "").strip()`, `if raw_file:`).
/// A variable set to the empty string selects nothing there, so it must not count as a
/// conflicting configuration here either.
fn ambient_env(name: &str) -> Option<String> {
    std::env::var(name).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
}

/// The pure decision: what to set on the child, or why nothing may be set.
///
/// No environment reads, no filesystem, no globals — the whole rule is a function of its
/// arguments, so every branch is unit-testable without mutating a process-wide
/// environment that other tests are reading concurrently.
pub fn resolve(
    provisioned: &[(&'static str, String)],
    operator_public_key: &str,
    ambient: &dyn Fn(&str) -> Option<String>,
) -> Result<Vec<(&'static str, String)>, String> {
    if provisioned.is_empty() {
        return Err(NOT_PROVISIONED.to_string());
    }
    for name in [SELF_OWNED_ACK, SELF_OWNED_ACK_FILE] {
        if let Some(value) = ambient(name) {
            return Err(format!(
                "{name}={value:?} is set in this process's environment. It does not weaken one \
                 check — bro_custody short-circuits EVERY custody rule in the engine runtime \
                 when the acknowledgement is declared, including the one that proves the \
                 redirected registry root cannot be rewritten by the account reading it. This \
                 deployment's anchor is sealed precisely so that acknowledgement is not needed, \
                 so exporting the provisioned trust under it would put everything back in place \
                 with nothing measuring it. Unset it, or run the engine from an environment that \
                 does not carry it."
            ));
        }
    }
    if let Some(value) = ambient(RAW_CI_PIN) {
        if value != operator_public_key {
            return Err(format!(
                "{RAW_CI_PIN} is set to {value:?}, but this machine provisioned the \
                 operator-root key {operator_public_key:?}. \
                 bro_signature._resolve_operator_root_pin refuses a file pin and a raw pin \
                 that name different keys, so exporting the provisioned anchor over this \
                 would break the engine with a mismatch instead of wiring it. There is no \
                 precedence order between the two anchors, by design: unset {RAW_CI_PIN}, or \
                 run against the deployment it belongs to."
            ));
        }
    }
    if let Some(value) = ambient(RAW_CI_FLOOR) {
        return Err(format!(
            "{RAW_CI_FLOOR} is set to {value:?}, and this deployment pins its anti-rollback \
             floor from the anchor file instead. bro_signature.resolve_registry_floor refuses \
             a file floor and a raw floor that disagree; whether these two agree cannot be \
             decided here, because the provisioned floor is the CONTENT of the anchor file and \
             not a value this process holds. Refusing rather than guessing: unset \
             {RAW_CI_FLOOR}."
        ));
    }
    for (name, value) in provisioned {
        if let Some(existing) = ambient(name) {
            if &existing != value {
                return Err(format!(
                    "{name} is already set to {existing:?} in this process's environment, but \
                     first-launch provisioning produced {value:?}. The provisioned trust \
                     environment is exported whole or not at all — a deployment where some \
                     engine checks consult the provisioned registry and others consult a \
                     different one, with nothing saying so, is the failure the redirect \
                     exists to prevent. Neither value silently wins: unset {name} to use the \
                     provisioned trust store, or point every one of these at the same \
                     deployment."
                ));
            }
        }
    }
    Ok(provisioned.to_vec())
}

/// Apply the provisioned trust environment to a child that is about to run the engine.
///
/// The ONLY caller is `ai::governed_sidecar_call`, which is the one seam in this
/// application that launches `python bridge/engine_sidecar.py` — both the governed AI turn
/// and the read-only governance mirror go through it. An `Err` must fail the spawn: a
/// governed call that proceeds without this reaches the development registry.
pub fn apply(cmd: &mut tokio::process::Command) -> Result<(), String> {
    let recorded = RECORDED.get().ok_or_else(|| NOT_PROVISIONED.to_string())?;
    for (name, value) in
        resolve(&recorded.pairs, &recorded.operator_public_key, &|n| ambient_env(n))?
    {
        cmd.env(name, value);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    const PIN: &str = "1f8b0c00000000000000ff0000000000000000000000000000000000000000ab";

    fn provisioned() -> Vec<(&'static str, String)> {
        vec![
            ("BRO_TRUSTED_REGISTRY_ROOT", "/anchor/registry".into()),
            ("BRO_OPERATOR_ROOT_PUBKEY_FILE", "/anchor/operator-root.pub".into()),
            ("BRO_OPERATOR_REGISTRY_MIN_FILE", "/anchor/registry-min".into()),
            ("BRO_CONDUCTOR_SESSION_TOKEN", "/trust/artifacts/conductor-session.json".into()),
            ("BRO_SESSION_ID", "brops-install-1".into()),
        ]
    }

    fn ambient(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: BTreeMap<String, String> =
            pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        move |name: &str| map.get(name).cloned()
    }

    #[test]
    fn a_clean_environment_gets_the_whole_provisioned_set() {
        let got = resolve(&provisioned(), PIN, &ambient(&[])).expect("clean env");
        assert_eq!(got, provisioned(), "the set is exported whole and unaltered");
    }

    #[test]
    fn the_registry_root_is_in_the_set_and_is_the_variable_o3_turns_on() {
        // The one that decides WHICH registry the engine trusts. Its absence was O-3.
        let got = resolve(&provisioned(), PIN, &ambient(&[])).unwrap();
        assert!(
            got.iter().any(|(k, _)| *k == "BRO_TRUSTED_REGISTRY_ROOT"),
            "without BRO_TRUSTED_REGISTRY_ROOT the engine reads the committed development \
             registry no matter what else is exported: {got:?}"
        );
    }

    #[test]
    fn nothing_recorded_refuses_rather_than_falling_back_to_the_committed_registry() {
        let err = resolve(&[], PIN, &ambient(&[])).unwrap_err();
        assert_eq!(err, NOT_PROVISIONED);
        assert!(err.contains("engine/config/trusted-keys.json"), "{err}");
    }

    #[test]
    fn an_ambient_value_that_agrees_is_not_a_conflict() {
        let got = resolve(
            &provisioned(),
            PIN,
            &ambient(&[("BRO_TRUSTED_REGISTRY_ROOT", "/anchor/registry")]),
        )
        .expect("an identical value is the same configuration, not a competing one");
        assert_eq!(got, provisioned());
    }

    #[test]
    fn an_ambient_value_that_disagrees_refuses_and_names_both() {
        let err = resolve(
            &provisioned(),
            PIN,
            &ambient(&[("BRO_TRUSTED_REGISTRY_ROOT", "/somewhere/else")]),
        )
        .unwrap_err();
        assert!(err.contains("BRO_TRUSTED_REGISTRY_ROOT"), "{err}");
        assert!(err.contains("/somewhere/else"), "the ambient value is named: {err}");
        assert!(err.contains("/anchor/registry"), "the provisioned value is named: {err}");
    }

    /// Every variable in the set is guarded, not just the interesting one — a guard that
    /// covered only the registry root would let the pin, the floor, the token or the
    /// session id be silently overridden, and each of those alone breaks the chain.
    #[test]
    fn every_variable_in_the_set_is_guarded_against_a_conflicting_ambient_value() {
        for (name, _) in provisioned() {
            let err = resolve(&provisioned(), PIN, &ambient(&[(name, "conflicting-value")]))
                .unwrap_err();
            assert!(err.contains(name), "{name} is not guarded: {err}");
            assert!(err.contains("conflicting-value"), "{name}: {err}");
        }
    }

    /// `bro_signature` treats an empty value as unset everywhere these are read, so an
    /// empty ambient value must not be reported as a conflicting configuration. Asked of
    /// the real reader, because that is where the rule has to hold.
    #[test]
    fn an_empty_ambient_value_reads_as_absent_exactly_as_the_engine_reads_it() {
        std::env::set_var("BROPS_ENGINE_TRUST_EMPTY_PROBE", "   ");
        assert_eq!(ambient_env("BROPS_ENGINE_TRUST_EMPTY_PROBE"), None);
        std::env::remove_var("BROPS_ENGINE_TRUST_EMPTY_PROBE");
    }

    #[test]
    fn a_raw_ci_pin_naming_another_key_refuses_instead_of_breaking_the_engine() {
        let err = resolve(&provisioned(), PIN, &ambient(&[(RAW_CI_PIN, "00".repeat(32).as_str())]))
            .unwrap_err();
        assert!(err.contains(RAW_CI_PIN), "{err}");
        assert!(err.contains("_resolve_operator_root_pin"), "the engine rule is named: {err}");
    }

    #[test]
    fn a_raw_ci_pin_naming_the_same_key_is_not_a_conflict() {
        resolve(&provisioned(), PIN, &ambient(&[(RAW_CI_PIN, PIN)]))
            .expect("the same anchor spelled two ways is one anchor");
    }

    #[test]
    fn a_raw_ci_floor_refuses_because_agreement_cannot_be_decided_here() {
        let err = resolve(&provisioned(), PIN, &ambient(&[(RAW_CI_FLOOR, "7")])).unwrap_err();
        assert!(err.contains(RAW_CI_FLOOR), "{err}");
        assert!(err.contains("cannot be decided here"), "the refusal is honest about why: {err}");
    }

    #[test]
    fn the_self_owned_acknowledgement_refuses_even_though_it_would_make_everything_pass() {
        let err = resolve(&provisioned(), PIN, &ambient(&[(SELF_OWNED_ACK, "acknowledged")]))
            .unwrap_err();
        assert!(err.contains(SELF_OWNED_ACK), "{err}");
        assert!(err.contains("EVERY custody rule"), "{err}");
    }

    /// The file form is the SAME acknowledgement, so it must meet the same blanket refusal.
    /// `bro_custody` honours the raw variable only under `BRO_ENV=ci` and takes the file form
    /// in production; a rule that knew only the raw name would have let a deployment disable
    /// every custody rule in the engine runtime with this refusal none the wiser.
    #[test]
    fn the_file_form_of_the_acknowledgement_refuses_on_the_same_terms() {
        let err = resolve(
            &provisioned(),
            PIN,
            &ambient(&[(SELF_OWNED_ACK_FILE, "/etc/brops/self-owned")]),
        )
        .unwrap_err();
        assert!(err.contains(SELF_OWNED_ACK_FILE), "{err}");
        assert!(err.contains("EVERY custody rule"), "{err}");
    }

    /// The half-wired state, stated as a test: exporting the registry root without the
    /// anchor that authenticates it is not a partial win, it is a different trust root.
    /// The `resolve` contract is all-or-nothing, so there is no code path that returns a
    /// proper subset of what provisioning recorded.
    #[test]
    fn resolve_never_returns_a_subset_of_the_recorded_set() {
        let full = provisioned();
        let got = resolve(&full, PIN, &ambient(&[])).unwrap();
        assert_eq!(got.len(), full.len());
        for (name, value) in &full {
            assert!(got.iter().any(|(k, v)| k == name && v == value), "{name} was dropped");
        }
    }
}
