//! The broker's production [`TurnResolver`] (rev-30 §4.10(g)) — the trusted per-turn resolution that turns a
//! provisioned, root-signed key manifest into the pinned keys + Expected facts `verify_and_accept` binds to.
//!
//! FAIL-CLOSED BY DEFAULT: constructed with no manifest ([`ProductionResolver::fail_closed`]), every turn
//! returns `UpstreamBlocked` — identical outward behaviour to the interim `UpstreamBlockedExecutor`, so the
//! shipped broker keeps rendering `blocked` until a trusted manifest is provisioned. When a manifest IS
//! provisioned, `resolve` — BEFORE any hop — verifies it against the **TCB-pinned root** ([`crate::tcb`],
//! never config), runs anti-rollback, and resolves the production signer + supervisor-attestation keys
//! (trust-class / validity-window / revocation enforced); any failure ⇒ `UpstreamBlocked` (still fail-closed).
//! Only a fully-resolved manifest yields a `ResolvedTurn`, and only that lets the chain reach a real
//! `verify_and_accept`.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::chain_executor::{ResolvedTurn, TurnResolver};
use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest};
use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
use brops_core::key_manifest::{
    check_and_persist, resolve_production_key, verify_manifest_anchored, AntiRollbackFloor, KeyManifest,
    PinnedRoot, RootAnchor, RootProvenance, VerifiedManifestRoot,
};
use brops_core::production_trust::{resolve_trust_state, TrustState};

use crate::tcb;

/// The broker-owned per-turn Expected facts, as the DIRECT `GovernedChain` path consumes them.
///
/// **Read `system_sha256` / `history_sha256` / `generation_config_sha256` / `requested_at` /
/// `requested_at_ms` / `run_id` / `task_id` with the doubt they deserve: on this struct they are
/// DEPLOYMENT-STATIC.** They are filled from `$BROPS_BROKER_CONFIG`'s `resolved` block by
/// `main.rs::build_governed_executor` and are the same on every turn, so a receipt produced through
/// [`TurnResolver::resolve`] attests what the config says a conversation was, not what the user typed.
/// That is why the rev-30 §4.10(g) ladder exists and why it does not use them: [`KeyResolver`] below
/// returns ONLY the values that are legitimately deployment-wide (the two pinned keys, the install
/// identity, the committed-message author), and
/// [`crate::ladder_executor`] derives all three artifact digests, `requested_at` and the nonce from the
/// actual conversation via `governed_prepare::prepare_governed_turn_v1b`.
#[derive(Clone)]
pub struct ResolvedFacts {
    pub workspace_id: String,
    pub install_id: String,
    pub system_sha256: String,
    pub history_sha256: String,
    pub generation_config_sha256: String,
    pub requested_at: String,
    pub run_id: String,
    pub task_id: String,
    pub requested_at_ms: i64,
    pub author: String,
}

struct Provisioned {
    manifest: KeyManifest,
    root_sig_b64: String,
    floor: Mutex<AntiRollbackFloor>,
    /// Where the advanced floor is WRITTEN BACK. Audit: this resolver used to advance `floor` in memory
    /// and stop there, so the highest accepted epoch reset to the provisioned constant on every broker
    /// restart and the control could not refuse a rollback across processes.
    floor_path: PathBuf,
    signer_key_id: String,
    sup_attest_key_id: String,
    facts: ResolvedFacts,
    /// The root the manifest is verified against — the TCB PRODUCTION anchor (`crate::tcb`, never config) in
    /// production; a demonstration anchor only in unit tests via [`ProductionResolver::provisioned_with_pin`].
    pinned: PinnedRoot,
    /// What THIS turn's verification established: the anchor token and the key the envelope will be
    /// verified with. Written by [`KeyResolver::resolve_keys`], read by [`BrokerCustody`].
    ///
    /// It is a per-turn observation and not deployment state, which is why it is a cell rather than a
    /// constructor argument: `CustodyResolver::resolve` takes no arguments on purpose (custody is a
    /// property of the deployment and the clock, not of the message), and the envelope key is the one
    /// input it still needs. `KitCustody` in `proof/src/bin/ladder_turn.rs` does exactly this, and the
    /// shipped broker now does it the same way rather than a second way.
    custody: Arc<Mutex<Option<(VerifiedManifestRoot, String)>>>,
}

/// The broker's production resolver. `None` inner ⇒ no trusted manifest ⇒ fail-closed (every turn Blocks).
pub struct ProductionResolver {
    inner: Option<Provisioned>,
}

impl ProductionResolver {
    /// Fail-closed: no trusted manifest provisioned — every turn returns `UpstreamBlocked`.
    pub fn fail_closed() -> Self {
        ProductionResolver { inner: None }
    }

    /// Provisioned: a root-signed manifest + its root signature + the anti-rollback floor + the resolved key
    /// ids + the broker-owned Expected facts. `resolve` verifies + resolves per turn (fail-closed on any gap).
    #[allow(clippy::too_many_arguments)]
    pub fn provisioned(
        manifest: KeyManifest,
        root_sig_b64: String,
        floor: AntiRollbackFloor,
        floor_path: PathBuf,
        signer_key_id: String,
        sup_attest_key_id: String,
        facts: ResolvedFacts,
    ) -> Self {
        // Production: the manifest is pinned to the TCB PRODUCTION root (`crate::tcb`), never a config value.
        let pinned = PinnedRoot {
            root_key_id: tcb::ROOT_KEY_ID.to_string(),
            public_key_hex: tcb::ROOT_PUBLIC_KEY_HEX.to_string(),
        };
        Self::provisioned_with_pin(pinned, manifest, root_sig_b64, floor, floor_path, signer_key_id, sup_attest_key_id, facts)
    }

    /// Provisioned against an explicit pinned root — production uses [`ProductionResolver::provisioned`] (TCB
    /// PRODUCTION anchor); unit tests pass the DEMONSTRATION anchor so they can sign with an in-code private.
    /// `pub(crate)`: external code can only reach `provisioned` (production pin), so the public demo private
    /// can never be pinned onto a live turn.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn provisioned_with_pin(
        pinned: PinnedRoot,
        manifest: KeyManifest,
        root_sig_b64: String,
        floor: AntiRollbackFloor,
        floor_path: PathBuf,
        signer_key_id: String,
        sup_attest_key_id: String,
        facts: ResolvedFacts,
    ) -> Self {
        ProductionResolver {
            inner: Some(Provisioned {
                manifest,
                root_sig_b64,
                floor: Mutex::new(floor),
                floor_path,
                signer_key_id,
                sup_attest_key_id,
                facts,
                pinned,
                custody: Arc::new(Mutex::new(None)),
            }),
        }
    }

    pub fn is_provisioned(&self) -> bool {
        self.inner.is_some()
    }

    /// What the pinned anchor's custody IS, derived from which anchor the binary pinned.
    ///
    /// NOT a config value, and that is the point. `broker/src/tcb.rs` compiles in one production root and
    /// says of it: the private half "is held OFFLINE by the operator ... never appears in a deployed
    /// binary or on the serving box". An operator who can write the config directory cannot swap it. Any
    /// other pinned root reached this resolver through `provisioned_with_pin`, which is `pub(crate)` and
    /// exists for tests — so it is a demonstration anchor and says so.
    ///
    /// The LIMIT is the one `key_manifest` already states and it is not weakened here: this establishes
    /// which anchor verified the manifest, not that the Owner's custody ceremony was actually honoured.
    fn root_provenance(pinned: &PinnedRoot) -> RootProvenance {
        if pinned.root_key_id == tcb::ROOT_KEY_ID {
            RootProvenance::External
        } else {
            RootProvenance::Demonstration
        }
    }

    /// A custody resolver bound to this resolver's per-turn observation, or `None` when nothing is
    /// provisioned — in which case the executor keeps refusing the commit exactly as before.
    pub fn custody(&self) -> Option<BrokerCustody> {
        let p = self.inner.as_ref()?;
        Some(BrokerCustody {
            cell: Arc::clone(&p.custody),
            manifest: p.manifest.clone(),
            signer_key_id: p.signer_key_id.clone(),
        })
    }
}

/// The part of a turn's trust that IS a property of the deployment: the two pinned manifest keys, the
/// install identity, and the author a committed message is written under.
///
/// It is deliberately a different type from [`ResolvedTurn`] rather than a subset of it. `ResolvedTurn`
/// mixes deployment facts with per-conversation ones, and the mixing is what let a config-supplied
/// `system_sha256` sit in the same struct as a manifest-resolved public key and read as equally
/// authoritative. Nothing per-conversation can be added here without changing the type, and the type is
/// named for what it holds.
#[derive(Clone)]
pub struct ResolvedKeys {
    pub isolated_signer_key_id: String,
    pub isolated_signer_public_key: [u8; 32],
    pub supervisor_attestation_key_id: String,
    pub supervisor_attestation_public_key: [u8; 32],
    pub workspace_id: String,
    pub install_id: String,
    pub author: String,
}

/// Resolve the deployment's pinned keys for ONE turn: root-verify the manifest against the TCB pin, run
/// anti-rollback and persist the advanced floor, then resolve both production keys (trust-class /
/// validity-window / revocation enforced). Any gap ⇒ `UpstreamBlocked`.
///
/// Per-turn, not cached, for the reason [`crate::chain_executor::CustodyResolver`] states: a manifest key
/// has a validity window and a revocation flag, so an expired or revoked key must stop resolving without
/// anything having to notice and invalidate a cache.
pub trait KeyResolver {
    fn resolve_keys(&self) -> Result<ResolvedKeys, TurnReason>;
}

fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

fn hex32(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 {
        return None;
    }
    let b = s.as_bytes();
    let mut out = [0u8; 32];
    for i in 0..32 {
        let hi = (b[2 * i] as char).to_digit(16)?;
        let lo = (b[2 * i + 1] as char).to_digit(16)?;
        out[i] = (hi * 16 + lo) as u8;
    }
    Some(out)
}

impl KeyResolver for ProductionResolver {
    fn resolve_keys(&self) -> Result<ResolvedKeys, TurnReason> {
        // No manifest provisioned ⇒ fail closed (the shipped default; unchanged behaviour).
        let p = self.inner.as_ref().ok_or(TurnReason::UpstreamBlocked)?;
        let now = now_ms();

        // (1) Verify the manifest against the pinned root — the TCB PRODUCTION anchor in production (never a
        //     config-supplied root); a demonstration anchor only under `provisioned_with_pin` in tests.
        //
        //     ANCHORED since the custody wiring (T-088): the same signature check, returning the token that
        //     says WHICH anchor verified this manifest and what that anchor's custody is. The provenance is
        //     derived from the pinned root rather than declared anywhere a deployment could write it — see
        //     `root_provenance` below.
        let anchor = RootAnchor {
            pinned: p.pinned.clone(),
            provenance: Self::root_provenance(&p.pinned),
        };
        let verified = verify_manifest_anchored(&p.manifest, &p.root_sig_b64, &anchor)
            .map_err(|_| TurnReason::UpstreamBlocked)?;

        // (2) Anti-rollback: accept only an epoch at/above the floor, advance it, and WRITE IT BACK.
        //
        //     AUDIT. This block used to end at `*floor = advanced;`. The advance therefore lived in one
        //     broker process and died with it: the next start re-read `trust.floor_path`, which nothing
        //     ever wrote, so the "highest accepted manifest_epoch" was permanently the value the
        //     provisioner had put there. Any genuinely root-signed older manifest — including one whose
        //     production signer key had since been revoked — was accepted again after a restart, which
        //     is the whole attack the floor exists to stop. A persist failure REFUSES: continuing on an
        //     unadvanced floor is the state this fix exists to remove.
        {
            let mut floor = p.floor.lock().map_err(|_| TurnReason::UpstreamBlocked)?;
            let advanced = check_and_persist(&floor, &p.manifest, &p.floor_path)
                .map_err(|_| TurnReason::UpstreamBlocked)?;
            *floor = advanced;
        }

        // (3) Resolve BOTH production keys from the verified manifest (class/window/revocation enforced).
        let iso = resolve_production_key(&p.manifest, &p.signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now)
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let sup = resolve_production_key(&p.manifest, &p.sup_attest_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now)
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let iso_pub = hex32(&iso.public_key_hex).ok_or(TurnReason::UpstreamBlocked)?;
        let sup_pub = hex32(&sup.public_key_hex).ok_or(TurnReason::UpstreamBlocked)?;

        // Record what this turn established, for the custody resolver to read. Written AFTER every check
        // above has passed, so a turn that failed verification leaves no observation behind for the next
        // one to commit on.
        if let Ok(mut cell) = p.custody.lock() {
            *cell = Some((verified, iso.public_key_hex.clone()));
        }

        let f = &p.facts;
        Ok(ResolvedKeys {
            isolated_signer_key_id: p.signer_key_id.clone(),
            isolated_signer_public_key: iso_pub,
            supervisor_attestation_key_id: p.sup_attest_key_id.clone(),
            supervisor_attestation_public_key: sup_pub,
            workspace_id: f.workspace_id.clone(),
            install_id: f.install_id.clone(),
            author: f.author.clone(),
        })
    }
}

/// The broker's custody resolver: it reads what the key resolution established this turn and ends at
/// [`resolve_trust_state`].
///
/// It constructs NO [`TrustState`] of its own. The trait's own contract says why — "building the enum by
/// hand is how a demonstration root gets to call itself production" — and the split this file cares about
/// is made inside that function, on the anchor's provenance, not here.
///
/// With no observation recorded (no turn has resolved keys yet, or the last one failed a check) it
/// returns `NoTrustedManifest`, so `persist_committed` refuses. That is the same answer the broker gave
/// before this existed; what changed is that a turn which DID verify now has somewhere to say so.
pub struct BrokerCustody {
    cell: Arc<Mutex<Option<(VerifiedManifestRoot, String)>>>,
    manifest: KeyManifest,
    signer_key_id: String,
}

impl crate::chain_executor::CustodyResolver for BrokerCustody {
    fn resolve(&self) -> TrustState {
        let held = self.cell.lock().ok().and_then(|g| g.clone());
        let (verified, envelope_key_hex) = match held {
            Some(pair) => pair,
            None => {
                return TrustState::NoTrustedManifest(
                    "no turn has verified a manifest under a pinned anchor yet",
                )
            }
        };
        resolve_trust_state(
            Some(&self.manifest),
            Some(&verified),
            &self.signer_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            now_ms(),
            &envelope_key_hex,
        )
    }
}

/// The DIRECT-path resolver, expressed as [`KeyResolver`] plus the deployment-static facts.
///
/// There is exactly ONE manifest verification / anti-rollback / key-resolution implementation and it is
/// [`KeyResolver::resolve_keys`] above; this only pairs its output with `ResolvedFacts`. Written this way
/// on purpose: the two paths must not be able to drift on WHICH manifest they trusted, and a second copy
/// of `verify_manifest` + `check_and_persist` here is exactly how they would.
impl TurnResolver for ProductionResolver {
    fn resolve(
        &self,
        _req: &ValidatedRequest,
        _broker_turn_id: &str,
        _request_nonce: &str,
    ) -> Result<ResolvedTurn, TurnReason> {
        let keys = self.resolve_keys()?;
        // `inner` is Some: `resolve_keys` already refused a fail-closed resolver.
        let f = &self.inner.as_ref().ok_or(TurnReason::UpstreamBlocked)?.facts;
        Ok(ResolvedTurn {
            isolated_signer_key_id: keys.isolated_signer_key_id,
            isolated_signer_public_key: keys.isolated_signer_public_key,
            supervisor_attestation_key_id: keys.supervisor_attestation_key_id,
            supervisor_attestation_public_key: keys.supervisor_attestation_public_key,
            workspace_id: keys.workspace_id,
            install_id: keys.install_id,
            system_sha256: f.system_sha256.clone(),
            history_sha256: f.history_sha256.clone(),
            generation_config_sha256: f.generation_config_sha256.clone(),
            requested_at: f.requested_at.clone(),
            run_id: f.run_id.clone(),
            task_id: f.task_id.clone(),
            requested_at_ms: f.requested_at_ms,
            author: keys.author,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chain_executor::CustodyResolver as _;
    use base64::Engine as _;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::json;

    fn req() -> ValidatedRequest {
        ValidatedRequest {
            conversation_id: "conv-1".into(),
            agent: Some("Bro".into()),
            client_request_id: "3f2504e0-4f89-41d3-9a0c-0305e82c3301".into(),
        }
    }

    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{x:02x}")).collect()
    }
    fn seed32(h: &str) -> [u8; 32] {
        super::hex32(h).unwrap()
    }
    /// The DEMONSTRATION root private that matches the compiled-in `tcb::DEMO_ROOT_PUBLIC_KEY_HEX`.
    const DEMO_ROOT_SEED_HEX: &str =
        "0011223344556677001122334455667700112233445566770011223344556677"; // gitleaks:allow (demo test key)

    // ---- custody (T-088, the Owner's decision of 2026-09-19) --------------------------------

    /// A demo-pinned, fully provisioned resolver: the only kind a unit test can build, because the
    /// production root's private half is held offline and is not in this tree.
    fn demo_resolver(dir: &std::path::Path, valid_signature: bool) -> (ProductionResolver, String) {
        let root = SigningKey::from_bytes(&seed32(DEMO_ROOT_SEED_HEX));
        let signer = SigningKey::from_bytes(&seed32(&"11".repeat(32)));
        let sup = SigningKey::from_bytes(&seed32(&"22".repeat(32)));
        let signer_pub = hex(signer.verifying_key().as_bytes());
        let sup_pub = hex(sup.verifying_key().as_bytes());
        let manifest: KeyManifest = serde_json::from_value(json!({
            "manifest_epoch": 2u64,
            "root_key_id": tcb::DEMO_ROOT_KEY_ID,
            "keys": [
                { "key_id": "signer-1", "public_key_hex": signer_pub, "trust_class": "production",
                  "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64,
                  "revoked": false, "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] },
                { "key_id": "sup-1", "public_key_hex": sup_pub, "trust_class": "production",
                  "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64,
                  "revoked": false, "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] }
            ]
        })).unwrap();
        let sig = if valid_signature {
            base64::engine::general_purpose::STANDARD
                .encode(root.sign(&manifest.canonical_bytes()).to_bytes())
        } else {
            "bogus".to_string()
        };
        let floor = AntiRollbackFloor { highest_epoch: 2, highest_hash: manifest.content_hash() };
        let facts = ResolvedFacts {
            workspace_id: "ws".into(), install_id: "inst".into(),
            system_sha256: "a".repeat(64), history_sha256: "b".repeat(64),
            generation_config_sha256: "c".repeat(64), requested_at: "1900000000000".into(),
            run_id: "run".into(), task_id: "task".into(), requested_at_ms: 1_900_000_000_000,
            author: "Bro".into(),
        };
        let r = ProductionResolver::provisioned_with_pin(
            demo_pin(), manifest, sig, floor, dir.join("floor.json"),
            "signer-1".into(), "sup-1".into(), facts,
        );
        (r, signer_pub)
    }

    #[test]
    fn an_unprovisioned_resolver_offers_no_custody_at_all() {
        // `build_governed_executor` then falls back to `ChainExecutor::new`, and the commit refuses
        // exactly as it did before the wiring.
        assert!(ProductionResolver::fail_closed().custody().is_none());
    }

    #[test]
    fn custody_says_nothing_until_a_turn_has_verified_something() {
        let dir = tempfile::tempdir().unwrap();
        let (r, _) = demo_resolver(dir.path(), true);
        let custody = r.custody().expect("a provisioned resolver offers custody");
        match custody.resolve() {
            TrustState::NoTrustedManifest(why) => assert!(why.contains("no turn has verified")),
            other => panic!("expected NoTrustedManifest, got {other:?}"),
        }
        assert!(custody.resolve().committed_label().is_none(), "nothing may commit yet");
    }

    #[test]
    fn a_turn_that_fails_verification_leaves_no_observation_behind() {
        // The observation is written AFTER every check passes. A resolver whose root signature is
        // garbage must leave custody exactly where it was, or a failed turn would hand the next one a
        // reason to commit.
        let dir = tempfile::tempdir().unwrap();
        let (r, _) = demo_resolver(dir.path(), false);
        assert!(r.resolve_keys().is_err(), "a bogus root signature must fail closed");
        let custody = r.custody().unwrap();
        assert!(matches!(custody.resolve(), TrustState::NoTrustedManifest(_)));
        assert!(custody.resolve().committed_label().is_none());
    }

    #[test]
    fn a_demo_anchored_turn_commits_as_demonstration_and_never_as_production() {
        // THE load-bearing one. Everything else about this deployment is correct -- a production-class
        // key, inside its window, unrevoked, under a root signature that verifies -- and the verdict is
        // still `demonstration_custody`, because the anchor's private half ships in this tree.
        let dir = tempfile::tempdir().unwrap();
        let (r, signer_pub) = demo_resolver(dir.path(), true);
        let keys = r.resolve_keys().expect("a valid demo manifest resolves");
        assert_eq!(hex(&keys.isolated_signer_public_key), signer_pub);

        let state = r.custody().unwrap().resolve();
        match &state {
            TrustState::DemonstrationCustody { key_id, root_key_id, .. } => {
                assert_eq!(key_id, "signer-1");
                assert_eq!(root_key_id, tcb::DEMO_ROOT_KEY_ID);
            }
            other => panic!("a demo anchor must not produce {other:?}"),
        }
        assert_eq!(state.committed_label(), Some("demonstration_custody"));
        assert_ne!(state.committed_label(), Some("trusted_verified"));
    }

    #[test]
    fn the_provenance_follows_the_pinned_anchor_and_nothing_else() {
        // Not a config value, deliberately: an operator who can write the config directory would
        // otherwise be able to claim the Owner's custody for an anchor the Owner never held.
        let production = PinnedRoot {
            root_key_id: tcb::ROOT_KEY_ID.to_string(),
            public_key_hex: tcb::ROOT_PUBLIC_KEY_HEX.to_string(),
        };
        assert!(matches!(
            ProductionResolver::root_provenance(&production),
            RootProvenance::External
        ));
        assert!(matches!(
            ProductionResolver::root_provenance(&demo_pin()),
            RootProvenance::Demonstration
        ));
        // And the two anchors are genuinely different, so the test above is not comparing a thing to
        // itself.
        assert_ne!(production.root_key_id, demo_pin().root_key_id);
    }

    #[test]
    fn fail_closed_resolver_blocks_every_turn() {
        // No manifest provisioned => every turn is UpstreamBlocked (shipped default; unchanged behaviour).
        let r = ProductionResolver::fail_closed();
        assert!(!r.is_provisioned());
        assert!(matches!(r.resolve(&req(), "bt", "nonce"), Err(TurnReason::UpstreamBlocked)));
    }

    // The DEMONSTRATION root the tests pin — never the production anchor. Its private is the in-code seed
    // below; production trust pins tcb::ROOT_PUBLIC_KEY_HEX (the operator's offline root) alone.
    fn demo_pin() -> PinnedRoot {
        PinnedRoot {
            root_key_id: tcb::DEMO_ROOT_KEY_ID.to_string(),
            public_key_hex: tcb::DEMO_ROOT_PUBLIC_KEY_HEX.to_string(),
        }
    }

    #[test]
    fn provisioned_resolver_resolves_a_root_signed_manifest() {
        // The DEMONSTRATION root private that matches the compiled-in tcb::DEMO_ROOT_PUBLIC_KEY_HEX (59cfbe...).
        let root = SigningKey::from_bytes(&seed32(
            "0011223344556677001122334455667700112233445566770011223344556677", // gitleaks:allow (demo test key)
        ));
        assert_eq!(hex(root.verifying_key().as_bytes()), tcb::DEMO_ROOT_PUBLIC_KEY_HEX);
        // Two production keys (signer + supervisor-attestation).
        let signer = SigningKey::from_bytes(&seed32(
            "1111111111111111111111111111111111111111111111111111111111111111", // gitleaks:allow (test key)
        ));
        let sup = SigningKey::from_bytes(&seed32(
            "2222222222222222222222222222222222222222222222222222222222222222", // gitleaks:allow (test key)
        ));
        let signer_pub = hex(signer.verifying_key().as_bytes());
        let sup_pub = hex(sup.verifying_key().as_bytes());
        let manifest: KeyManifest = serde_json::from_value(json!({
            "manifest_epoch": 2u64,
            "root_key_id": tcb::DEMO_ROOT_KEY_ID,
            "keys": [
                { "key_id": "signer-1", "public_key_hex": signer_pub, "trust_class": "production",
                  "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
                  "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] },
                { "key_id": "sup-1", "public_key_hex": sup_pub, "trust_class": "production",
                  "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
                  "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] }
            ]
        })).unwrap();
        let root_sig = base64::engine::general_purpose::STANDARD.encode(root.sign(&manifest.canonical_bytes()).to_bytes());
        let floor = AntiRollbackFloor { highest_epoch: 2, highest_hash: manifest.content_hash() };
        let facts = ResolvedFacts {
            workspace_id: "ws".into(), install_id: "inst".into(),
            system_sha256: "a".repeat(64), history_sha256: "b".repeat(64),
            generation_config_sha256: "c".repeat(64), requested_at: "1900000000000".into(),
            run_id: "run".into(), task_id: "task".into(), requested_at_ms: 1_900_000_000_000, author: "Bro".into(),
        };
        let dir = tempfile::tempdir().unwrap();
        let floor_path = dir.path().join("floor.json");
        let r = ProductionResolver::provisioned_with_pin(
            demo_pin(), manifest, root_sig, floor, floor_path.clone(), "signer-1".into(), "sup-1".into(), facts,
        );
        let resolved = r.resolve(&req(), "bt", "nonce").expect("valid manifest resolves");
        assert_eq!(resolved.isolated_signer_key_id, "signer-1");
        assert_eq!(hex(&resolved.isolated_signer_public_key), signer_pub);
        assert_eq!(hex(&resolved.supervisor_attestation_public_key), sup_pub);
        // A manifest whose root signature is garbage must fail closed.
        let r2 = ProductionResolver::provisioned_with_pin(
            demo_pin(),
            serde_json::from_value(json!({
                "manifest_epoch": 2u64, "root_key_id": tcb::DEMO_ROOT_KEY_ID, "keys": []
            })).unwrap(),
            "bogus".into(),
            AntiRollbackFloor { highest_epoch: 2, highest_hash: "x".into() },
            dir.path().join("floor2.json"),
            "signer-1".into(), "sup-1".into(),
            ResolvedFacts {
                workspace_id: "ws".into(), install_id: "inst".into(),
                system_sha256: "a".repeat(64), history_sha256: "b".repeat(64),
                generation_config_sha256: "c".repeat(64), requested_at: "1".into(),
                run_id: "r".into(), task_id: "t".into(), requested_at_ms: 1, author: "Bro".into(),
            },
        );
        assert!(matches!(r2.resolve(&req(), "bt", "nonce"), Err(TurnReason::UpstreamBlocked)));
    }

    /// A resolver over a manifest at `epoch`, sharing `floor_path`. The floor it starts from is READ
    /// from that path, exactly as `main.rs` reads it at broker start — so calling this twice models
    /// two broker processes over one deployment, which is the case the in-memory advance never covered.
    fn resolver_at_epoch(epoch: u64, floor_path: &std::path::Path) -> (ProductionResolver, KeyManifest) {
        let root = SigningKey::from_bytes(&seed32(DEMO_ROOT_SEED_HEX));
        let signer = SigningKey::from_bytes(&seed32(
            "1111111111111111111111111111111111111111111111111111111111111111", // gitleaks:allow (test key)
        ));
        let sup = SigningKey::from_bytes(&seed32(
            "2222222222222222222222222222222222222222222222222222222222222222", // gitleaks:allow (test key)
        ));
        let manifest: KeyManifest = serde_json::from_value(json!({
            "manifest_epoch": epoch,
            "root_key_id": tcb::DEMO_ROOT_KEY_ID,
            "keys": [
                { "key_id": "signer-1", "public_key_hex": hex(signer.verifying_key().as_bytes()),
                  "trust_class": "production", "valid_from_ms": 1, "valid_to_ms": 9999999999999i64,
                  "key_epoch": 2u64, "revoked": false, "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] },
                { "key_id": "sup-1", "public_key_hex": hex(sup.verifying_key().as_bytes()),
                  "trust_class": "production", "valid_from_ms": 1, "valid_to_ms": 9999999999999i64,
                  "key_epoch": 2u64, "revoked": false, "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] }
            ]
        })).unwrap();
        let root_sig = base64::engine::general_purpose::STANDARD
            .encode(root.sign(&manifest.canonical_bytes()).to_bytes());
        let floor = brops_core::key_manifest::parse_floor_json(&std::fs::read(floor_path).unwrap())
            .expect("the provisioned floor must parse");
        let facts = ResolvedFacts {
            workspace_id: "ws".into(), install_id: "inst".into(),
            system_sha256: "a".repeat(64), history_sha256: "b".repeat(64),
            generation_config_sha256: "c".repeat(64), requested_at: "1900000000000".into(),
            run_id: "run".into(), task_id: "task".into(), requested_at_ms: 1_900_000_000_000, author: "Bro".into(),
        };
        let r = ProductionResolver::provisioned_with_pin(
            demo_pin(), manifest.clone(), root_sig, floor, floor_path.to_path_buf(),
            "signer-1".into(), "sup-1".into(), facts,
        );
        (r, manifest)
    }

    /// AUDIT: the advanced floor used to be dropped on the floor of `resolve`. It was written to a
    /// `Mutex<AntiRollbackFloor>` and nowhere else, so the "highest accepted manifest_epoch" was reset
    /// to the provisioned constant every time the broker restarted — and a rolled-back but genuinely
    /// root-signed manifest (e.g. one reviving a revoked signer key) resolved again.
    #[test]
    fn a_rollback_is_refused_by_a_broker_that_restarted() {
        let dir = tempfile::tempdir().unwrap();
        let floor_path = dir.path().join("floor.json");
        // Provisioned at epoch 2, exactly as `win_provision` / `provision_keys.py` write it.
        let (_, m2) = {
            std::fs::write(&floor_path, brops_core::key_manifest::floor_json_bytes(
                &AntiRollbackFloor { highest_epoch: 0, highest_hash: String::new() },
            )).unwrap();
            resolver_at_epoch(2, &floor_path)
        };

        // --- broker process 1: serve a turn under epoch 3 ---
        let (r3, _) = resolver_at_epoch(3, &floor_path);
        r3.resolve(&req(), "bt", "nonce").expect("epoch 3 is above the floor");
        drop(r3); // the broker process exits; the Mutex goes with it

        // --- broker process 2: the SAME older manifest, still validly root-signed ---
        let (r2, _) = resolver_at_epoch(2, &floor_path);
        assert!(
            matches!(r2.resolve(&req(), "bt", "nonce"), Err(TurnReason::UpstreamBlocked)),
            "a manifest below the floor a PREVIOUS broker process accepted must be refused"
        );
        assert_eq!(m2.manifest_epoch, 2);
        // And the durable floor really is at 3.
        let on_disk = brops_core::key_manifest::parse_floor_json(&std::fs::read(&floor_path).unwrap()).unwrap();
        assert_eq!(on_disk.highest_epoch, 3);
    }

    /// A floor that cannot be written down is not a floor: the turn refuses rather than serving on an
    /// advance that will be lost.
    #[test]
    fn an_unwritable_floor_blocks_the_turn() {
        let dir = tempfile::tempdir().unwrap();
        let floor_path = dir.path().join("floor.json");
        std::fs::write(&floor_path, brops_core::key_manifest::floor_json_bytes(
            &AntiRollbackFloor { highest_epoch: 0, highest_hash: String::new() },
        )).unwrap();
        let (_, _) = resolver_at_epoch(2, &floor_path);
        // Same starting floor, but the resolver is pointed at a path inside a directory that does not
        // exist, so both the temp write and the rename fail.
        let (r, _) = resolver_at_epoch(2, &floor_path);
        drop(r);
        let unwritable = dir.path().join("no-such-dir").join("floor.json");
        let floor = brops_core::key_manifest::parse_floor_json(&std::fs::read(&floor_path).unwrap()).unwrap();
        let root = SigningKey::from_bytes(&seed32(DEMO_ROOT_SEED_HEX));
        let manifest: KeyManifest = serde_json::from_value(json!({
            "manifest_epoch": 5u64, "root_key_id": tcb::DEMO_ROOT_KEY_ID, "keys": []
        })).unwrap();
        let root_sig = base64::engine::general_purpose::STANDARD
            .encode(root.sign(&manifest.canonical_bytes()).to_bytes());
        let r = ProductionResolver::provisioned_with_pin(
            demo_pin(), manifest, root_sig, floor, unwritable,
            "signer-1".into(), "sup-1".into(),
            ResolvedFacts {
                workspace_id: "ws".into(), install_id: "inst".into(),
                system_sha256: "a".repeat(64), history_sha256: "b".repeat(64),
                generation_config_sha256: "c".repeat(64), requested_at: "1".into(),
                run_id: "r".into(), task_id: "t".into(), requested_at_ms: 1, author: "Bro".into(),
            },
        );
        assert!(matches!(r.resolve(&req(), "bt", "nonce"), Err(TurnReason::UpstreamBlocked)));
    }
}
