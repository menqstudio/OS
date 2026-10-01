//! The broker's Trusted Computing Base root anchor (Linux production trust root).
//!
//! The production-trust root PUBLIC key is compiled in HERE, never read from the deployment config — an
//! operator who can write the config directory cannot swap the root, because the broker's production resolver
//! pins the public key from this module and refuses any manifest not signed by the corresponding private
//! root. No person holds or carries that private key (Owner decision, #78); see `ROOT_PUBLIC_KEY_HEX`.

pub const ROOT_KEY_ID: &str = "brops-tcb-root-1"; // gitleaks:allow (public key-id)

/// The TCB-pinned PRODUCTION root PUBLIC key hex — the only root material in the broker binary. Nobody
/// holds its private half: the Owner decided on 2026-08-09 (#78) that the install mints trust and no person
/// carries a key, and he does not hold this one (2026-09-20). So the production path is unreachable until
/// the pin is replaced by an install-minted root (T-131).
pub const ROOT_PUBLIC_KEY_HEX: &str =
    "3c83c2bc0e72c068824e2eebf663b6ed4cda337ff806c0b46e534aee19da0df5"; // gitleaks:allow (public key)

/// The DEMONSTRATION root key id — used ONLY by unit tests, never production.
pub const DEMO_ROOT_KEY_ID: &str = "brops-tcb-demo-root-1"; // gitleaks:allow (demo public key-id)

/// The DEMONSTRATION root PUBLIC key hex — a SEPARATE anchor whose private half is a fixed test seed, so it can
/// exercise the resolver in-process. NEVER a production anchor: the production path pins `ROOT_PUBLIC_KEY_HEX`
/// alone, so knowing the demo private cannot forge a production manifest.
pub const DEMO_ROOT_PUBLIC_KEY_HEX: &str =
    "59cfbe7b22c066c63f7c18fc698b58f63215d0705ebab5cd306bc37a49efeede"; // gitleaks:allow (demo public key)

/// Refuse an anchor that DECLARES external custody but is not the root compiled in above.
///
/// `ladder_turn` and `live_turn` read their anchor from a TCB file that states its own provenance, and
/// `resolve_trust_state` renders `Production` for any `External` anchor whose signature verifies. So the
/// word `external` in a file was the whole production claim: a kit that minted a throwaway root, signed
/// its manifest and wrote `"provenance": "external"` beside it — which is exactly what exporting the five
/// `BROPS_*` anchor variables makes `provision_keys.py` write — would get `production_verified=true` from a
/// root whose private half it had just generated itself. Provenance cannot be taken on the file's word;
/// only a root this binary already pins may carry it. A kit-generated or demonstration anchor is not
/// checked here: it can only LOWER the claim, never raise it.
pub fn check_declared_external_anchor(
    provenance: brops_core::key_manifest::RootProvenance,
    root_key_id: &str,
    public_key_hex: &str,
) -> Result<(), &'static str> {
    if provenance != brops_core::key_manifest::RootProvenance::External {
        return Ok(());
    }
    if public_key_hex.trim().to_ascii_lowercase() != ROOT_PUBLIC_KEY_HEX {
        return Err("external_not_the_pinned_root");
    }
    if root_key_id != ROOT_KEY_ID {
        return Err("external_key_id_not_the_pinned_root");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use brops_core::key_manifest::RootProvenance;

    #[test]
    fn external_anchor_equal_to_the_pin_passes() {
        assert_eq!(
            check_declared_external_anchor(RootProvenance::External, ROOT_KEY_ID, ROOT_PUBLIC_KEY_HEX),
            Ok(())
        );
        // Case is not identity: the provisioner lowercases, an operator may not.
        assert_eq!(
            check_declared_external_anchor(
                RootProvenance::External,
                ROOT_KEY_ID,
                &ROOT_PUBLIC_KEY_HEX.to_ascii_uppercase()
            ),
            Ok(())
        );
    }

    #[test]
    fn external_anchor_that_is_not_the_pin_is_refused() {
        // The throwaway-root case: any other key, even the compiled-in demonstration one.
        assert_eq!(
            check_declared_external_anchor(RootProvenance::External, ROOT_KEY_ID, DEMO_ROOT_PUBLIC_KEY_HEX),
            Err("external_not_the_pinned_root")
        );
        assert_eq!(
            check_declared_external_anchor(RootProvenance::External, ROOT_KEY_ID, &"ab".repeat(32)),
            Err("external_not_the_pinned_root")
        );
        assert_eq!(
            check_declared_external_anchor(RootProvenance::External, "brops-kit-root", ROOT_PUBLIC_KEY_HEX),
            Err("external_key_id_not_the_pinned_root")
        );
    }

    #[test]
    fn a_lower_claim_is_never_refused() {
        for p in [RootProvenance::KitGenerated, RootProvenance::Demonstration] {
            assert_eq!(check_declared_external_anchor(p, "any", &"ab".repeat(32)), Ok(()));
        }
    }
}
