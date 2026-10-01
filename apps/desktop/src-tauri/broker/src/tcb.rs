//! The broker's root-anchor rules: the one root that may be called `external`, and the parser for the
//! TCB anchor FILE the broker reads its root from.
//!
//! **The Linux broker no longer pins a compiled-in root** (T-131 slice C). It used to:
//! `ProductionResolver::provisioned` built its `PinnedRoot` from [`ROOT_KEY_ID`] /
//! [`ROOT_PUBLIC_KEY_HEX`], so no manifest signed by anything else could verify — and since no person
//! holds that key's private half (Owner decision #78), no manifest could verify at all. The broker now
//! takes its root from the anchor file the §2.5 pin manifest pins under `key-manifest.root-anchor`,
//! read AFTER that floor has passed (`tcb_probe::VerifiedBrokerTcb::root_anchor`), and parsed by
//! [`parse_root_anchor`] below. It is still never a config value: the path comes from the pin
//! manifest, and an operator who can write the config directory cannot name a different anchor.
//!
//! What the compiled constant is still FOR: it is the only root allowed to say `external`
//! ([`check_declared_external_anchor`]), and `tools/check_root_anchor_custody.py` sweeps the tree for
//! its private half. The Windows kit (`win-live/src/tcb.rs`) still pins its own copy as its root.

use brops_core::key_manifest::{PinnedRoot, RootAnchor, RootProvenance};

pub const ROOT_KEY_ID: &str = "brops-tcb-root-1"; // gitleaks:allow (public key-id)

/// The one root that may DECLARE `external` custody — the only root material in the broker binary.
/// Nobody holds its private half: the Owner decided on 2026-08-09 (#78) that the install mints trust
/// and no person carries a key, and he does not hold this one (2026-09-20). So an `external` anchor
/// can be declared and never satisfied; the reachable custody on Linux is an install-minted root in
/// the floor-pinned anchor file (T-131), which is production only behind
/// `brops_core::key_manifest::INSTALL_MINTED_CUSTODY_ACCEPTED`.
pub const ROOT_PUBLIC_KEY_HEX: &str =
    "3c83c2bc0e72c068824e2eebf663b6ed4cda337ff806c0b46e534aee19da0df5"; // gitleaks:allow (public key)

/// The DEMONSTRATION root key id — used ONLY by unit tests, never production.
pub const DEMO_ROOT_KEY_ID: &str = "brops-tcb-demo-root-1"; // gitleaks:allow (demo public key-id)

/// The DEMONSTRATION root PUBLIC key hex — a SEPARATE anchor whose private half is a fixed test seed, so it can
/// exercise the resolver in-process. NEVER a production anchor: `provisioned_with_pin`, the only route by
/// which it reaches a resolver, is `pub(crate)` and labels whatever it is given `Demonstration`, and an
/// anchor FILE carrying this key can say `external` only if it is `ROOT_PUBLIC_KEY_HEX`, which it is not.
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

/// Refuse an anchor that DECLARES install-minted custody unless the reader can show the bytes it
/// read are the ones the §2.5 pin manifest pins for `key-manifest.root-anchor`.
///
/// The same lesson as [`check_declared_external_anchor`], one provenance over: `install_minted` is
/// the only provenance that can ever support a production claim on Linux (behind the Owner's
/// `INSTALL_MINTED_CUSTODY_ACCEPTED`), so the word in a file must not be the claim. *The label is
/// earned by WHERE the file sits and WHO can write it, never by what the file says.*
///
/// The broker does not need this: it has no other way to obtain an anchor than
/// `tcb_probe::VerifiedBrokerTcb::root_anchor`, which reads the pinned path after the floor passed.
/// The PROOF DRIVERS do — `ladder_turn` and `live_turn` read their anchor from a path their config
/// names, and check only that the file is root-owned. `floor_pinned` is how such a reader answers
/// the question (`tcb_probe::anchor_bytes_are_floor_pinned`); it is a closure so that it is not
/// evaluated, and cannot fail, for the provenances it does not concern. Its error text is the
/// caller's to log — the reason returned here is one fixed name, because the drivers build an
/// outcome string out of it that a kit asserts on. A kit-generated or demonstration anchor is not
/// checked here: it can only LOWER the claim.
pub fn check_declared_install_minted_anchor(
    provenance: RootProvenance,
    floor_pinned: impl FnOnce() -> Result<(), String>,
) -> Result<(), &'static str> {
    if provenance != RootProvenance::InstallMinted {
        return Ok(());
    }
    floor_pinned().map_err(|_| "install_minted_not_floor_pinned")
}

/// The largest anchor document a reader will look at. The real one is three short strings.
pub const MAX_ROOT_ANCHOR_BYTES: usize = 4096;

/// Parse a root-anchor document — `{"root_key_id", "public_key_hex", "provenance"}` — fail-closed.
///
/// Every refusal is a named reason and none of them defaults: an anchor that cannot say which key
/// it is, or what that key's custody is, has not answered the question, and "empty key id" or "not
/// external, presumably" are both answers the reader would be inventing. `external` is then held to
/// [`check_declared_external_anchor`], so the returned [`RootAnchor`] never carries `External` for
/// any key but the compiled-in one.
///
/// What this CANNOT establish is where `bytes` came from — it is a pure function. An
/// `install_minted` result is only as good as the reader's evidence that it read the floor-pinned
/// file; see [`check_declared_install_minted_anchor`] and `tcb_probe::FloorPinnedAnchor`.
pub fn parse_root_anchor(bytes: &[u8]) -> Result<RootAnchor, &'static str> {
    if bytes.len() > MAX_ROOT_ANCHOR_BYTES {
        return Err("too_large");
    }
    let doc: serde_json::Value = serde_json::from_slice(bytes).map_err(|_| "not_json")?;
    let doc = doc.as_object().ok_or("not_an_object")?;
    let text = |key: &str| doc.get(key).and_then(serde_json::Value::as_str);

    let root_key_id = text("root_key_id").ok_or("root_key_id_missing")?;
    if root_key_id.is_empty() || root_key_id.trim() != root_key_id {
        return Err("root_key_id_malformed");
    }
    let public_key_hex = text("public_key_hex").ok_or("public_key_hex_missing")?;
    if public_key_hex.len() != 64 || !public_key_hex.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("public_key_hex_malformed");
    }
    // Absent, a non-string, misspelled, or a near-miss: all `provenance_unknown`. Never a default.
    let provenance =
        text("provenance").and_then(RootProvenance::parse).ok_or("provenance_unknown")?;
    check_declared_external_anchor(provenance, root_key_id, public_key_hex)?;
    Ok(RootAnchor {
        pinned: PinnedRoot {
            root_key_id: root_key_id.to_string(),
            public_key_hex: public_key_hex.to_string(),
        },
        provenance,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

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
        // `install_minted` is not this check's question either — it has its own, below.
        assert_eq!(
            check_declared_external_anchor(RootProvenance::InstallMinted, "any", &"ab".repeat(32)),
            Ok(())
        );
    }

    // ---- install_minted is earned by where the file sits, not by the word in it ----------------

    #[test]
    fn an_install_minted_anchor_is_refused_unless_it_is_the_floor_pinned_one() {
        assert_eq!(
            check_declared_install_minted_anchor(RootProvenance::InstallMinted, || {
                Err("the pin manifest pins another file".to_string())
            }),
            Err("install_minted_not_floor_pinned")
        );
        assert_eq!(
            check_declared_install_minted_anchor(RootProvenance::InstallMinted, || Ok(())),
            Ok(())
        );
    }

    #[test]
    fn the_floor_question_is_not_even_asked_for_the_other_provenances() {
        // A kit_generated or demonstration anchor can only lower the claim, and `external` is held
        // to the compiled pin instead. None of them may be refused HERE — and the closure must not
        // run, so a kit with no pin manifest at all still completes an honestly-labelled turn.
        for p in [RootProvenance::External, RootProvenance::KitGenerated, RootProvenance::Demonstration] {
            assert_eq!(
                check_declared_install_minted_anchor(p, || panic!("asked the floor about {p:?}")),
                Ok(())
            );
        }
    }

    // ---- the anchor document ------------------------------------------------------------------

    fn anchor_doc(key_id: &str, public_key_hex: &str, provenance: &str) -> Vec<u8> {
        serde_json::json!({
            "root_key_id": key_id, "public_key_hex": public_key_hex, "provenance": provenance,
        })
        .to_string()
        .into_bytes()
    }
    /// Sixty-four hex characters that are nobody’s key: built, not written, so no 32-byte literal is added
    /// to the tree for `tools/check_root_anchor_custody.py` to derive.
    fn kit_key() -> String {
        "ab".repeat(32)
    }

    #[test]
    fn a_well_formed_anchor_parses_with_the_provenance_it_states() {
        let kit = kit_key();
        let kit = kit.as_str();
        for (word, want) in [
            ("kit_generated", RootProvenance::KitGenerated),
            ("demonstration", RootProvenance::Demonstration),
            ("install_minted", RootProvenance::InstallMinted),
        ] {
            let a = parse_root_anchor(&anchor_doc("brops-live-root-1", kit, word))
                .unwrap_or_else(|e| panic!("{word}: {e}"));
            assert_eq!(a.provenance, want);
            assert_eq!(a.pinned.root_key_id, "brops-live-root-1");
            assert_eq!(a.pinned.public_key_hex, kit);
        }
        // `external` parses only for the compiled-in root.
        let a = parse_root_anchor(&anchor_doc(ROOT_KEY_ID, ROOT_PUBLIC_KEY_HEX, "external")).unwrap();
        assert_eq!(a.provenance, RootProvenance::External);
    }

    #[test]
    fn an_anchor_with_no_or_unknown_provenance_is_refused_never_defaulted() {
        let kit = kit_key();
        let kit = kit.as_str();
        for word in ["", "External", "production", "install-minted", "kit", "true"] {
            assert_eq!(
                parse_root_anchor(&anchor_doc("brops-live-root-1", kit, word)),
                Err("provenance_unknown"),
                "{word:?}"
            );
        }
        // Absent, and present as something that is not a string.
        let absent = format!(r#"{{"root_key_id":"r","public_key_hex":"{kit}"}}"#);
        assert_eq!(parse_root_anchor(absent.as_bytes()), Err("provenance_unknown"));
        let not_a_string =
            format!(r#"{{"root_key_id":"r","public_key_hex":"{kit}","provenance":true}}"#);
        assert_eq!(parse_root_anchor(not_a_string.as_bytes()), Err("provenance_unknown"));
        let null = format!(r#"{{"root_key_id":"r","public_key_hex":"{kit}","provenance":null}}"#);
        assert_eq!(parse_root_anchor(null.as_bytes()), Err("provenance_unknown"));
    }

    #[test]
    fn a_garbled_anchor_is_refused_by_the_name_of_what_is_wrong() {
        let kit = kit_key();
        let kit = kit.as_str();
        assert_eq!(parse_root_anchor(b""), Err("not_json"));
        assert_eq!(parse_root_anchor(b"{ not json"), Err("not_json"));
        assert_eq!(parse_root_anchor(b"[]"), Err("not_an_object"));
        assert_eq!(parse_root_anchor(b"\"install_minted\""), Err("not_an_object"));
        assert_eq!(
            parse_root_anchor(format!(r#"{{"public_key_hex":"{kit}","provenance":"kit_generated"}}"#).as_bytes()),
            Err("root_key_id_missing")
        );
        for id in ["", " ", " r", "r "] {
            assert_eq!(
                parse_root_anchor(&anchor_doc(id, kit, "kit_generated")),
                Err("root_key_id_malformed"),
                "{id:?}"
            );
        }
        assert_eq!(
            parse_root_anchor(br#"{"root_key_id":"r","provenance":"kit_generated"}"#),
            Err("public_key_hex_missing")
        );
        for key in ["", "ab", &kit[..63], &format!("{}0", kit_key()), &"zz".repeat(32), &format!(" {}", &kit[1..])] {
            assert_eq!(
                parse_root_anchor(&anchor_doc("r", key, "kit_generated")),
                Err("public_key_hex_malformed"),
                "{key:?}"
            );
        }
        // Oversized: refused before it is parsed.
        let mut big = anchor_doc("r", kit, "kit_generated");
        big.extend(std::iter::repeat(b' ').take(MAX_ROOT_ANCHOR_BYTES));
        assert_eq!(parse_root_anchor(&big), Err("too_large"));
    }

    #[test]
    fn an_anchor_file_cannot_say_external_for_a_root_that_is_not_the_compiled_one() {
        let kit = kit_key();
        let kit = kit.as_str();
        // The T-126 refusal, now inside the parser the broker itself uses: a kit's own root
        // relabelled `external`, and the compiled key under another id.
        assert_eq!(
            parse_root_anchor(&anchor_doc(ROOT_KEY_ID, kit, "external")),
            Err("external_not_the_pinned_root")
        );
        assert_eq!(
            parse_root_anchor(&anchor_doc("brops-live-root-1", ROOT_PUBLIC_KEY_HEX, "external")),
            Err("external_key_id_not_the_pinned_root")
        );
    }

    #[test]
    fn the_key_id_confers_nothing_the_provenance_did_not_state() {
        let kit = kit_key();
        let kit = kit.as_str();
        // A kit anchor may NAME itself `brops-tcb-root-1`. It parses, and it is still what it says
        // it is. (The resolver used to derive `External` from this id.)
        let a = parse_root_anchor(&anchor_doc(ROOT_KEY_ID, kit, "kit_generated")).unwrap();
        assert_eq!(a.provenance, RootProvenance::KitGenerated);
        assert!(!a.provenance.supports_production_claim());
    }
}
