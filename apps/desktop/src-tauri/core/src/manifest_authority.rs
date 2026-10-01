//! Wave 3b — the validated signed-manifest **receipt-key authority** (design §5): the in-crate resolver
//! that [`crate::receipt::ResolvedManifestKey`]'s doc names as the ONLY thing allowed to mint a resolved
//! key. It closes the seam Wave 3a shipped as [`crate::receipt_store::NoTrustedManifest`] (always
//! `Unavailable`): given an operator-provisioned key manifest that has been verified against a
//! **root anchor whose custody supports a production claim** + anti-rollback-checked AND PERSISTED,
//! it resolves a receipt's `key_id` to the pinned production verifying key.
//!
//! # NOT IN SERVICE
//!
//! **Nothing constructs this type outside this file's tests.** The desktop passes
//! [`crate::receipt_store::NoTrustedManifest`] at every call site (`commands.rs`), and the path a
//! governed turn would actually take resolves its keys in the BROKER, in
//! `broker/src/manifest_resolver.rs`, with its own copy of the verify / anti-rollback / resolve
//! sequence. Documents that say "select `GovernedEngine` with a real `ManifestReceiptKeyAuthority`"
//! name a wiring that has not been done.
//!
//! It is kept correct rather than deleted, so that wiring it does not wire a weaker check than the
//! live one. It used not to be: `new` called the bare [`crate::key_manifest::verify_manifest`],
//! which "answers only the arithmetic question" and returns no evidence of WHICH root verified, and
//! `check_and_advance(..).is_err()`, which drops the advanced floor — the two shapes
//! `key_manifest`'s own docs say a production verdict must not rest on — and then minted
//! `TrustClass::Production` regardless of the root's custody.
//!
//! FAIL-CLOSED: [`ManifestReceiptKeyAuthority::new`] verifies the manifest under the anchor, requires
//! that anchor's provenance to support a production claim, and advances AND WRITES the anti-rollback
//! floor at construction; on any failure — or via [`ManifestReceiptKeyAuthority::fail_closed`] — it
//! holds NO keys and every `resolve` returns `Unavailable` (identical to `NoTrustedManifest`). It only
//! ever mints a key that `resolve_production_key` classified as **production-class, in-window,
//! non-revoked, protocol-allowed** — never a development or expired/revoked key — so it cannot turn
//! a non-production key into "Verified".
//!
//! NOTE (scope): this resolves the trusted key; whether the Wave-3a `receipt_store` renders `trusted_verified`
//! for a production key is a SEPARATE, audited Wave-3b store change. On its own this authority does not
//! expose "Verified" — a production key still resolves to `Blocked` in the Wave-3a store.

use std::path::Path;

use crate::domain::CoreResult;
use crate::key_manifest::{
    check_and_persist, decode_hex32, resolve_production_key, verify_manifest_anchored, AntiRollbackFloor,
    KeyManifest, RootAnchor,
};
use crate::receipt::{ResolvedManifestKey, TrustClass};
use crate::receipt_store::{KeyResolution, ReceiptKeyAuthority};

/// A receipt-key authority backed by a root-verified, anti-rollback-checked production key manifest.
pub struct ManifestReceiptKeyAuthority {
    /// `(key_id, 32-byte ed25519 public key)` for every manifest key that resolved as a valid production
    /// key at construction time. Empty ⇒ fail-closed (every resolve is `Unavailable`).
    keys: Vec<(String, Vec<u8>)>,
}

impl ManifestReceiptKeyAuthority {
    /// A fail-closed authority: no trusted manifest ⇒ every `resolve` is `Unavailable`.
    pub fn fail_closed() -> Self {
        ManifestReceiptKeyAuthority { keys: Vec::new() }
    }

    /// Build from a provisioned manifest. In order, each a refusal that returns the fail-closed
    /// authority:
    ///
    /// 1. the root signature verifies under `anchor` ([`verify_manifest_anchored`], which returns the
    ///    evidence of which anchor that was);
    /// 2. that anchor's custody **supports a production claim**. Every key this type mints is
    ///    `TrustClass::Production`, so a manifest verified under a kit-generated or demonstration
    ///    root — or an install-minted one while the Owner's line is closed — mints nothing;
    /// 3. the manifest is not a rollback of `floor`, and the advanced floor is WRITTEN to
    ///    `floor_path` ([`check_and_persist`]). A floor that could not be written refuses.
    ///
    /// Then every manifest key is resolved through `resolve_production_key` (production-class /
    /// in-window / non-revoked / protocol-allowed) at `now_ms`, and only those are held.
    ///
    /// `floor` must be the floor read from durable storage, not one derived from `manifest`: a
    /// floor built from the manifest it is about to be compared with is a predicate that cannot
    /// fail.
    pub fn new(
        manifest: &KeyManifest,
        root_sig_b64: &str,
        anchor: &RootAnchor,
        floor: &AntiRollbackFloor,
        floor_path: &Path,
        protocol: &str,
        now_ms: i64,
    ) -> Self {
        let verified = match verify_manifest_anchored(manifest, root_sig_b64, anchor) {
            Ok(verified) => verified,
            Err(_) => return Self::fail_closed(),
        };
        if !verified.provenance().supports_production_claim() {
            return Self::fail_closed();
        }
        if check_and_persist(floor, manifest, floor_path).is_err() {
            return Self::fail_closed();
        }
        let mut keys = Vec::new();
        for k in &manifest.keys {
            if let Ok(rk) = resolve_production_key(manifest, &k.key_id, protocol, now_ms) {
                if let Some(bytes) = decode_hex32(&rk.public_key_hex) {
                    keys.push((rk.key_id, bytes.to_vec()));
                }
            }
        }
        ManifestReceiptKeyAuthority { keys }
    }

    /// True iff at least one production key resolved (i.e. a trusted manifest is active).
    pub fn is_trusted(&self) -> bool {
        !self.keys.is_empty()
    }
}

impl ReceiptKeyAuthority for ManifestReceiptKeyAuthority {
    fn resolve<'a>(&'a self, key_id: &str) -> CoreResult<KeyResolution<'a>> {
        for (kid, bytes) in &self.keys {
            if kid == key_id {
                return Ok(KeyResolution::Trusted(ResolvedManifestKey::manifest_resolved(
                    kid,
                    bytes,
                    TrustClass::Production,
                )));
            }
        }
        Ok(KeyResolution::Unavailable(
            "key_id is not a resolved production key in the trusted manifest",
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::key_manifest::{
        parse_floor_json, ManifestKey, PinnedRoot, RootProvenance, TrustClass as MTrustClass,
    };
    use base64::Engine as _;
    use ed25519_dalek::{Signer, SigningKey};

    fn sk(seed: [u8; 32]) -> SigningKey {
        SigningKey::from_bytes(&seed)
    }
    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{x:02x}")).collect()
    }

    const PROTO: &str = "brops.governed-receipt-envelope.v1";

    fn manifest_with(keys: Vec<ManifestKey>) -> KeyManifest {
        KeyManifest { manifest_epoch: 2, root_key_id: "root-1".into(), keys }
    }
    fn key(id: &str, pk_hex: String, cls: MTrustClass, revoked: bool) -> ManifestKey {
        ManifestKey {
            key_id: id.into(),
            public_key_hex: pk_hex,
            trust_class: cls,
            valid_from_ms: 1,
            valid_to_ms: 9_999_999_999_999,
            key_epoch: 2,
            revoked,
            allowed_protocols: vec![PROTO.to_string()],
        }
    }

    /// One production key under a root, with the root's signature and an anchor of the given
    /// custody. The floor is BELOW the manifest (epoch 1 against the manifest's 2) and its hash is
    /// not the manifest's — a floor that was not derived from the thing it is compared with.
    struct Fixture {
        manifest: KeyManifest,
        root_sig: String,
        anchor: RootAnchor,
        floor: AntiRollbackFloor,
        dir: tempfile::TempDir,
    }

    impl Fixture {
        fn with(keys: Vec<ManifestKey>, provenance: RootProvenance) -> Self {
            let root = sk([9u8; 32]);
            let manifest = manifest_with(keys);
            let root_sig = base64::engine::general_purpose::STANDARD
                .encode(root.sign(&manifest.canonical_bytes()).to_bytes());
            Fixture {
                manifest,
                root_sig,
                anchor: RootAnchor {
                    pinned: PinnedRoot {
                        root_key_id: "root-1".into(),
                        public_key_hex: hex(root.verifying_key().as_bytes()),
                    },
                    provenance,
                },
                floor: AntiRollbackFloor { highest_epoch: 1, highest_hash: "f".repeat(64) },
                dir: tempfile::tempdir().unwrap(),
            }
        }
        fn production(provenance: RootProvenance) -> Self {
            let prod = sk([1u8; 32]);
            Self::with(
                vec![key("prod-1", hex(prod.verifying_key().as_bytes()), MTrustClass::Production, false)],
                provenance,
            )
        }
        fn floor_path(&self) -> std::path::PathBuf {
            self.dir.path().join("floor.json")
        }
        fn authority(&self) -> ManifestReceiptKeyAuthority {
            ManifestReceiptKeyAuthority::new(
                &self.manifest, &self.root_sig, &self.anchor, &self.floor, &self.floor_path(), PROTO, 1000,
            )
        }
    }

    fn trusted(auth: &ManifestReceiptKeyAuthority, key_id: &str) -> bool {
        matches!(auth.resolve(key_id).unwrap(), KeyResolution::Trusted(_))
    }

    #[test]
    fn resolves_a_production_key_and_rejects_everything_else() {
        let prod = sk([1u8; 32]);
        let dev = sk([2u8; 32]);
        let revoked = sk([3u8; 32]);
        let scoped = sk([4u8; 32]);
        let mut scoped_key =
            key("scoped-1", hex(scoped.verifying_key().as_bytes()), MTrustClass::Production, false);
        scoped_key.allowed_protocols = vec!["brops.other.v1".to_string()];
        let f = Fixture::with(
            vec![
                key("prod-1", hex(prod.verifying_key().as_bytes()), MTrustClass::Production, false),
                key("dev-1", hex(dev.verifying_key().as_bytes()), MTrustClass::Development, false),
                key("rev-1", hex(revoked.verifying_key().as_bytes()), MTrustClass::Production, true),
                scoped_key,
            ],
            RootProvenance::External,
        );
        let auth = f.authority();
        assert!(auth.is_trusted());
        // The production key resolves Trusted with its pinned bytes.
        assert!(trusted(&auth, "prod-1"));
        // Development, revoked, out-of-protocol-scope and unknown key ids are all Unavailable.
        for id in ["dev-1", "rev-1", "scoped-1", "nope"] {
            assert!(!trusted(&auth, id), "{id} must be Unavailable");
        }
    }

    #[test]
    fn a_bad_root_signature_is_fail_closed() {
        let mut f = Fixture::production(RootProvenance::External);
        // Garbage root signature ⇒ no keys ⇒ every resolve Unavailable.
        f.root_sig = "bogus".into();
        let auth = f.authority();
        assert!(!auth.is_trusted());
        assert!(!trusted(&auth, "prod-1"));
        // ...and a refused manifest writes no floor.
        assert!(!f.floor_path().exists(), "a manifest that did not verify must not advance the floor");
        // The explicit fail-closed constructor is also always Unavailable.
        assert!(!trusted(&ManifestReceiptKeyAuthority::fail_closed(), "prod-1"));
    }

    /// The custody rule. Everything is right — signature, floor, key class, window, protocol —
    /// except who could have produced the root. This type mints `TrustClass::Production`, so a
    /// root that cannot support a production claim mints nothing. It used to mint under any root
    /// whose signature verified: a demonstration root's own manifest verifies perfectly well.
    #[test]
    fn a_root_whose_custody_cannot_support_production_mints_nothing() {
        for provenance in [
            RootProvenance::Demonstration,
            RootProvenance::KitGenerated,
            // The Owner's line ships closed, so an install-minted root is not production either.
            RootProvenance::InstallMinted,
        ] {
            let f = Fixture::production(provenance);
            let auth = f.authority();
            assert!(!auth.is_trusted(), "{provenance:?} minted a Production key");
            assert!(!trusted(&auth, "prod-1"), "{provenance:?}");
            assert!(!f.floor_path().exists(), "{provenance:?}: nothing was accepted, so nothing advances");
        }
        // Positive control: the same fixture under an external root does mint.
        assert!(Fixture::production(RootProvenance::External).authority().is_trusted());
    }

    /// The anti-rollback floor is ADVANCED AND WRITTEN. `check_and_advance(..).is_err()` compared
    /// and threw the result away, so the "highest accepted epoch" never rose and a restart reset
    /// it. Here the file a new process would read holds the manifest's epoch and hash.
    #[test]
    fn the_accepted_manifest_becomes_the_durable_floor() {
        let f = Fixture::production(RootProvenance::External);
        assert!(f.authority().is_trusted());
        let written = parse_floor_json(&std::fs::read(f.floor_path()).expect("the floor was written"))
            .expect("and it parses");
        assert_eq!(written.highest_epoch, f.manifest.manifest_epoch);
        assert_eq!(written.highest_hash, f.manifest.content_hash());
    }

    #[test]
    fn a_rolled_back_manifest_or_an_unwritable_floor_is_fail_closed() {
        // A floor ABOVE the manifest: a rollback.
        let mut f = Fixture::production(RootProvenance::External);
        f.floor = AntiRollbackFloor { highest_epoch: 3, highest_hash: "f".repeat(64) };
        assert!(!f.authority().is_trusted());
        assert!(!f.floor_path().exists());

        // The same epoch with a different hash: a fork at that epoch.
        let mut f = Fixture::production(RootProvenance::External);
        f.floor = AntiRollbackFloor { highest_epoch: 2, highest_hash: "f".repeat(64) };
        assert!(!f.authority().is_trusted());

        // A floor that cannot be written is a floor that did not advance.
        let f = Fixture::production(RootProvenance::External);
        let nowhere = f.dir.path().join("no-such-directory").join("floor.json");
        let auth = ManifestReceiptKeyAuthority::new(
            &f.manifest, &f.root_sig, &f.anchor, &f.floor, &nowhere, PROTO, 1000,
        );
        assert!(!auth.is_trusted());
    }
}
