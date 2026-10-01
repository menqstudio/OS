//! The broker's production [`TurnResolver`] (rev-30 §4.10(g)) — the trusted per-turn resolution that turns a
//! provisioned, root-signed key manifest into the pinned keys + Expected facts `verify_and_accept` binds to.
//!
//! FAIL-CLOSED BY DEFAULT: constructed with no manifest ([`ProductionResolver::fail_closed`]), every turn
//! returns `UpstreamBlocked` — identical outward behaviour to the interim `UpstreamBlockedExecutor`, so the
//! shipped broker keeps rendering `blocked` until a trusted manifest is provisioned. When a manifest IS
//! provisioned, `resolve` — BEFORE any hop — verifies it against the **floor-pinned root anchor** (the
//! file the §2.5 pin manifest pins under `key-manifest.root-anchor`, read after that floor passed —
//! [`crate::tcb_probe::FloorPinnedAnchor`], never config), runs anti-rollback, and resolves the
//! production signer + supervisor-attestation keys
//! (trust-class / validity-window / revocation enforced); any failure ⇒ `UpstreamBlocked` (still fail-closed).
//! Only a fully-resolved manifest yields a `ResolvedTurn`, and only that lets the chain reach a real
//! `verify_and_accept`.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use crate::chain_executor::{ResolvedTurn, SystemWallClock, TurnResolver, WallClock};
use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest};
use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
use brops_core::key_manifest::{
    check_and_persist, resolve_production_key, verify_manifest_anchored, AntiRollbackFloor, KeyManifest,
    ResolvedManifestKey, RootAnchor, VerifiedManifestRoot,
};
use crate::tcb_probe::FloorPinnedAnchor;
use brops_core::production_trust::{resolve_trust_state, TrustState};

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
    /// The root the manifest is verified against, WITH its custody provenance — the floor-pinned
    /// anchor file's in the shipped broker ([`ProductionResolver::provisioned`]); a demonstration
    /// anchor only in unit tests via `ProductionResolver::provisioned_with_pin`.
    ///
    /// **The provenance is the anchor's own, and nothing else decides custody.** NOT a config value,
    /// and no longer derived from the key ID. It used to be `External` whenever
    /// `root_key_id == tcb::ROOT_KEY_ID` — safe only while the root itself was a compiled constant,
    /// because then nothing else could carry that id. An anchor read from a file can call itself
    /// anything, so an id-derived answer would let a kit root NAMED `brops-tcb-root-1` read as
    /// external custody.
    ///
    /// The LIMIT is the one `key_manifest` already states and it is not weakened here: this
    /// establishes which anchor verified the manifest and what that anchor's file stated, not that
    /// the statement is true. What makes it worth anything is the §2.5 floor over that file.
    anchor: RootAnchor,
    /// What THIS turn's verification established: the anchor token and the key the envelope will be
    /// verified with. Written by [`KeyResolver::resolve_keys`], read by [`BrokerCustody`].
    ///
    /// It is a per-turn observation and not deployment state, which is why it is a cell rather than a
    /// constructor argument: `CustodyResolver::resolve` takes no arguments on purpose (custody is a
    /// property of the deployment and the clock, not of the message), and the envelope key is the one
    /// input it still needs. `KitCustody` in `proof/src/bin/ladder_turn.rs` does exactly this, and the
    /// shipped broker now does it the same way rather than a second way.
    custody: Arc<Mutex<Option<(VerifiedManifestRoot, String)>>>,
    /// The clock the key validity windows are evaluated against. Every construction installs
    /// [`SystemWallClock`]; only the test-only `with_clock` replaces it. It is a seam for the reason
    /// `chain_executor` gives for its own: a reading of `None` must REFUSE, and that refusal cannot
    /// be tested against the host's real clock.
    clock: Arc<dyn WallClock>,
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

    /// Provisioned: the FLOOR-PINNED root anchor + a manifest signed under it + its root signature +
    /// the anti-rollback floor + the resolved key ids + the broker-owned Expected facts. `resolve`
    /// verifies + resolves per turn (fail-closed on any gap).
    ///
    /// **The anchor is the first argument and its type is the control.** Until T-131 slice C this
    /// function took no anchor at all: it built its `PinnedRoot` from the constants compiled into
    /// `crate::tcb`, and answered "what is this root's custody?" from the key ID. Both are gone. The
    /// root is whatever the anchor file says, and the custody is what that file states — which is
    /// only safe because a [`FloorPinnedAnchor`] cannot be built outside `tcb_probe`: it exists only
    /// as the result of reading the path the §2.5 pin manifest pins, after that floor passed, with
    /// the bytes bound to the pinned digest and `external` held to the compiled-in root. A caller in
    /// another crate cannot write `RootProvenance::InstallMinted` next to a key of its choosing and
    /// reach this resolver with it.
    #[allow(clippy::too_many_arguments)]
    pub fn provisioned(
        anchor: FloorPinnedAnchor,
        manifest: KeyManifest,
        root_sig_b64: String,
        floor: AntiRollbackFloor,
        floor_path: PathBuf,
        signer_key_id: String,
        sup_attest_key_id: String,
        facts: ResolvedFacts,
    ) -> Self {
        Self::build(
            anchor.into_anchor(),
            manifest,
            root_sig_b64,
            floor,
            floor_path,
            signer_key_id,
            sup_attest_key_id,
            facts,
        )
    }

    /// Provisioned against an explicit pinned root that is, by this function's own definition, a
    /// DEMONSTRATION anchor — the shipped broker uses [`ProductionResolver::provisioned`]; unit tests
    /// pass the demonstration root so they can sign with an in-code private.
    ///
    /// It takes a bare `PinnedRoot` and assigns the provenance ITSELF, so there is no key a caller
    /// can pass here that comes out as anything but `Demonstration`. `#[cfg(test)]` since T-131
    /// slice C — `provisioned` used to delegate to it and no longer does, so nothing outside the
    /// tests has a reason to call it and it is not compiled into any binary: the public demo private
    /// can never be pinned onto a live turn.
    #[cfg(test)]
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn provisioned_with_pin(
        pinned: brops_core::key_manifest::PinnedRoot,
        manifest: KeyManifest,
        root_sig_b64: String,
        floor: AntiRollbackFloor,
        floor_path: PathBuf,
        signer_key_id: String,
        sup_attest_key_id: String,
        facts: ResolvedFacts,
    ) -> Self {
        let anchor = RootAnchor {
            pinned,
            provenance: brops_core::key_manifest::RootProvenance::Demonstration,
        };
        Self::build(
            anchor,
            manifest,
            root_sig_b64,
            floor,
            floor_path,
            signer_key_id,
            sup_attest_key_id,
            facts,
        )
    }

    /// The one place a `Provisioned` is assembled. PRIVATE: the two functions above are the only
    /// ways in, and each decides where the anchor's provenance comes from.
    #[allow(clippy::too_many_arguments)]
    fn build(
        anchor: RootAnchor,
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
                anchor,
                custody: Arc::new(Mutex::new(None)),
                clock: Arc::new(SystemWallClock),
            }),
        }
    }

    /// Replace the validity-window clock. Test-only: no binary can hand the resolver a clock.
    #[cfg(test)]
    pub(crate) fn with_clock(mut self, clock: Arc<dyn WallClock>) -> Self {
        if let Some(p) = self.inner.as_mut() {
            p.clock = clock;
        }
        self
    }

    pub fn is_provisioned(&self) -> bool {
        self.inner.is_some()
    }

    /// A custody resolver bound to this resolver's per-turn observation, or `None` when nothing is
    /// provisioned — in which case the executor keeps refusing the commit exactly as before.
    pub fn custody(&self) -> Option<BrokerCustody> {
        let p = self.inner.as_ref()?;
        Some(BrokerCustody {
            cell: Arc::clone(&p.custody),
            manifest: p.manifest.clone(),
            signer_key_id: p.signer_key_id.clone(),
            clock: Arc::clone(&p.clock),
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

/// Resolve the deployment's pinned keys for ONE turn: root-verify the manifest against the root anchor, run
/// anti-rollback and persist the advanced floor, then resolve both production keys (trust-class /
/// validity-window / revocation enforced). Any gap ⇒ `UpstreamBlocked`.
///
/// Per-turn, not cached, for the reason [`crate::chain_executor::CustodyResolver`] states: a manifest key
/// has a validity window and a revocation flag, so an expired or revoked key must stop resolving without
/// anything having to notice and invalidate a cache.
pub trait KeyResolver {
    fn resolve_keys(&self) -> Result<ResolvedKeys, TurnReason>;
}

/// Both production keys of ONE turn, resolved out of an already root-verified manifest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedKeyPair {
    pub signer: ResolvedManifestKey,
    pub signer_public_key: [u8; 32],
    pub supervisor_attestation: ResolvedManifestKey,
    pub supervisor_attestation_public_key: [u8; 32],
}

/// Why [`resolve_production_key_pair`] refused. Every variant is a refusal; [`as_str`](Self::as_str)
/// is the stage name the proof drivers report, so a kit can tell WHICH key did not resolve.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyPairRefusal {
    SignerKeyUnresolved,
    SupervisorAttestationKeyUnresolved,
    SignerPubkeyMalformed,
    SupervisorPubkeyMalformed,
    /// The receipt signer and the supervisor attestation resolved to the same key id or the same
    /// public key.
    KeysNotDistinct,
}

impl KeyPairRefusal {
    pub fn as_str(self) -> &'static str {
        match self {
            KeyPairRefusal::SignerKeyUnresolved => "signer_key_unresolved",
            KeyPairRefusal::SupervisorAttestationKeyUnresolved => {
                "supervisor_attestation_key_unresolved"
            }
            KeyPairRefusal::SignerPubkeyMalformed => "signer_pubkey_malformed",
            KeyPairRefusal::SupervisorPubkeyMalformed => "supervisor_pubkey_malformed",
            KeyPairRefusal::KeysNotDistinct => "signer_and_supervisor_keys_not_distinct",
        }
    }
}

/// Resolve BOTH pinned keys of a turn — the receipt signer and the supervisor attestation — through
/// [`resolve_production_key`], so trust class, revocation, validity window and allowed protocol are
/// enforced on each, and require the two to be different keys.
///
/// This is the ONE implementation of that step. [`ProductionResolver`]'s `resolve_keys` calls it,
/// and so do both proof drivers (`proof/src/bin/{ladder_turn,live_turn}.rs`). It exists because the
/// step used to be written out in each of them, and the copies drifted: `live_turn` took the
/// supervisor key with a bare `manifest.keys.iter().find(..)` on the key id, so a revoked, expired
/// or development-class key verified an attestation there while every other caller refused it.
///
/// **Distinct, by id and by key.** Both keys are resolved under the same allowed protocol — the
/// manifest has no `key_usage` discriminator yet (`config/negative-matrix.json` carries the rows
/// that need one as blocked) — so nothing else stops one manifest entry from being named as both the
/// isolated signer and the supervisor. One key in both roles would let whichever principal holds it
/// produce the attestation AND the envelope that vouches for it, which is the collapse the two
/// signatures exist to prevent. The manifest must not be trusted to keep them apart on its own.
///
/// `manifest` must already be root-verified by the caller; this function reads no signature.
pub fn resolve_production_key_pair(
    manifest: &KeyManifest,
    signer_key_id: &str,
    sup_attest_key_id: &str,
    now_ms: i64,
) -> Result<ResolvedKeyPair, KeyPairRefusal> {
    let signer =
        resolve_production_key(manifest, signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now_ms)
            .map_err(|_| KeyPairRefusal::SignerKeyUnresolved)?;
    let supervisor_attestation =
        resolve_production_key(manifest, sup_attest_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now_ms)
            .map_err(|_| KeyPairRefusal::SupervisorAttestationKeyUnresolved)?;
    let signer_public_key =
        hex32(&signer.public_key_hex).ok_or(KeyPairRefusal::SignerPubkeyMalformed)?;
    let supervisor_attestation_public_key = hex32(&supervisor_attestation.public_key_hex)
        .ok_or(KeyPairRefusal::SupervisorPubkeyMalformed)?;
    // Compared as BYTES, after decoding: two hex spellings of one key are one key.
    if signer.key_id == supervisor_attestation.key_id
        || signer_public_key == supervisor_attestation_public_key
    {
        return Err(KeyPairRefusal::KeysNotDistinct);
    }
    Ok(ResolvedKeyPair {
        signer,
        signer_public_key,
        supervisor_attestation,
        supervisor_attestation_public_key,
    })
}

// The 64-hex decoder is `brops_core::key_manifest::decode_hex32`; this file carried a copy of it.
use brops_core::key_manifest::decode_hex32 as hex32;

impl KeyResolver for ProductionResolver {
    fn resolve_keys(&self) -> Result<ResolvedKeys, TurnReason> {
        // No manifest provisioned ⇒ fail closed (the shipped default; unchanged behaviour).
        let p = self.inner.as_ref().ok_or(TurnReason::UpstreamBlocked)?;
        // Fail-closed, not zero: a clock this host cannot read is a refusal. It used to be
        // `unwrap_or(0)`, which evaluated every key's validity window at the epoch — the shape
        // `chain_executor`'s clock note records as the defect, in the same crate.
        let now = p.clock.now_ms().ok_or(TurnReason::UpstreamBlocked)?;

        // (1) Verify the manifest against the root anchor — the floor-pinned anchor file's in the shipped
        //     broker (never a config-supplied root); a demonstration anchor only under
        //     `provisioned_with_pin` in tests.
        //
        //     ANCHORED since the custody wiring (T-088): the same signature check, returning the token that
        //     says WHICH anchor verified this manifest and what that anchor's custody is. The provenance is
        //     the anchor's own — carried here from the file the §2.5 floor pinned — and is not derived
        //     from the key id or from anything in the deployment config. See `Provisioned::anchor`.
        let verified = verify_manifest_anchored(&p.manifest, &p.root_sig_b64, &p.anchor)
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

        // (3) Resolve BOTH production keys from the verified manifest (class/window/revocation enforced),
        //     and require them to be two different keys. One implementation, shared with the drivers.
        let pair = resolve_production_key_pair(&p.manifest, &p.signer_key_id, &p.sup_attest_key_id, now)
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let (iso, iso_pub, sup_pub) =
            (pair.signer, pair.signer_public_key, pair.supervisor_attestation_public_key);

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
    /// The same clock the key resolution read (see `Provisioned::clock`).
    clock: Arc<dyn WallClock>,
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
        // An unreadable clock has no opinion about a validity window, and "no opinion" must not read
        // as "inside it": no label, so `persist_committed` refuses.
        let now = match self.clock.now_ms() {
            Some(now) => now,
            None => {
                return TrustState::NoTrustedManifest(
                    "the wall clock is unreadable, so no key validity window can be evaluated",
                )
            }
        };
        resolve_trust_state(
            Some(&self.manifest),
            Some(&verified),
            &self.signer_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            now,
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
    use crate::tcb;
    use brops_core::key_manifest::{PinnedRoot, RootProvenance};

    /// The provenance the resolver holds for its anchor, or `None` when nothing is provisioned.
    fn held_provenance(r: &ProductionResolver) -> Option<RootProvenance> {
        r.inner.as_ref().map(|p| p.anchor.provenance)
    }
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

    /// How a test hands the resolver its anchor.
    enum Via {
        /// `provisioned_with_pin`: a bare pin, which that function labels `Demonstration` itself.
        Pin,
        /// `provisioned`, the shipped broker's entry, with an anchor STATING this provenance under
        /// this key id — as a floor-pinned anchor file would.
        Anchor(&'static str, RootProvenance),
    }

    /// A demo-pinned, fully provisioned resolver: the only kind a unit test can build, because
    /// nobody holds the private half of the compiled-in root and it is not in this tree.
    fn demo_resolver(dir: &std::path::Path, valid_signature: bool) -> (ProductionResolver, String) {
        resolver_via(dir, valid_signature, Via::Pin)
    }

    fn resolver_via(dir: &std::path::Path, valid_signature: bool, via: Via) -> (ProductionResolver, String) {
        let root_key_id = match &via {
            Via::Pin => tcb::DEMO_ROOT_KEY_ID,
            Via::Anchor(id, _) => *id,
        };
        let root = SigningKey::from_bytes(&seed32(DEMO_ROOT_SEED_HEX));
        let signer = SigningKey::from_bytes(&seed32(&"11".repeat(32)));
        let sup = SigningKey::from_bytes(&seed32(&"22".repeat(32)));
        let signer_pub = hex(signer.verifying_key().as_bytes());
        let sup_pub = hex(sup.verifying_key().as_bytes());
        let manifest: KeyManifest = serde_json::from_value(json!({
            "manifest_epoch": 2u64,
            "root_key_id": root_key_id,
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
        let r = match via {
            Via::Pin => ProductionResolver::provisioned_with_pin(
                demo_pin(), manifest, sig, floor, dir.join("floor.json"),
                "signer-1".into(), "sup-1".into(), facts,
            ),
            Via::Anchor(id, provenance) => ProductionResolver::provisioned(
                FloorPinnedAnchor::for_test(RootAnchor {
                    pinned: PinnedRoot {
                        root_key_id: id.to_string(),
                        public_key_hex: tcb::DEMO_ROOT_PUBLIC_KEY_HEX.to_string(),
                    },
                    provenance,
                }),
                manifest, sig, floor, dir.join("floor.json"),
                "signer-1".into(), "sup-1".into(), facts,
            ),
        };
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

    /// Drive one turn's key resolution and return the custody verdict it leaves behind.
    fn custody_after_a_turn(via: Via) -> TrustState {
        let dir = tempfile::tempdir().unwrap();
        let (r, _) = resolver_via(dir.path(), true, via);
        r.resolve_keys().expect("a validly signed manifest resolves");
        r.custody().unwrap().resolve()
    }

    #[test]
    fn the_provenance_follows_the_anchor_and_nothing_else() {
        // The custody verdict is what the ANCHOR stated — for each provenance an anchor file can
        // carry — and the committed label follows it. Not a config value, and not the key id.
        for provenance in [RootProvenance::KitGenerated, RootProvenance::Demonstration, RootProvenance::InstallMinted] {
            let dir = tempfile::tempdir().unwrap();
            let (r, _) = resolver_via(dir.path(), true, Via::Anchor("brops-live-root-1", provenance));
            assert_eq!(held_provenance(&r), Some(provenance));
            r.resolve_keys().unwrap();
            let state = r.custody().unwrap().resolve();
            match &state {
                TrustState::DemonstrationCustody { root_key_id, root_provenance, .. } => {
                    assert_eq!(root_key_id, "brops-live-root-1");
                    assert_eq!(*root_provenance, provenance);
                }
                other => panic!("{provenance:?} must not produce {other:?}"),
            }
            assert_eq!(state.committed_label(), Some("demonstration_custody"));
            assert!(!state.is_production_verified());
        }
        // `provisioned_with_pin` states the provenance ITSELF: whatever pin it is handed.
        let dir = tempfile::tempdir().unwrap();
        let (r, _) = demo_resolver(dir.path(), true);
        assert_eq!(held_provenance(&r), Some(RootProvenance::Demonstration));
        assert_eq!(held_provenance(&ProductionResolver::fail_closed()), None);
    }

    /// THE REGRESSION THIS SLICE COULD HAVE INTRODUCED. The resolver used to answer `External` for
    /// any pin whose id was `brops-tcb-root-1` — harmless while the key behind that id was a
    /// compiled constant. Now the anchor comes from a file, and a file can carry any id it likes: a
    /// kit root that NAMES itself after the compiled root must still be exactly as trusted as its
    /// provenance says, which is not production.
    #[test]
    fn a_kit_root_named_after_the_compiled_root_is_still_only_what_its_provenance_says() {
        let state = custody_after_a_turn(Via::Anchor(tcb::ROOT_KEY_ID, RootProvenance::KitGenerated));
        match &state {
            TrustState::DemonstrationCustody { root_key_id, root_provenance, .. } => {
                assert_eq!(root_key_id, tcb::ROOT_KEY_ID);
                assert_eq!(*root_provenance, RootProvenance::KitGenerated);
            }
            other => panic!("a key id bought {other:?}"),
        }
        assert_eq!(state.committed_label(), Some("demonstration_custody"));
        assert_ne!(state.committed_label(), Some("trusted_verified"));
    }

    /// An INSTALL-MINTED anchor, read from the floor-pinned file, with everything else about the
    /// deployment correct: the turn binds and commits, and it is NOT production, because the
    /// Owner's line (`INSTALL_MINTED_CUSTODY_ACCEPTED`) ships closed.
    #[test]
    fn an_install_minted_anchor_commits_as_demonstration_custody_and_never_as_production() {
        let state = custody_after_a_turn(Via::Anchor("brops-install-root-1", RootProvenance::InstallMinted));
        assert!(state.is_chain_bound());
        assert!(!state.is_production_verified());
        assert_eq!(
            state.root_provenance(),
            Some(RootProvenance::InstallMinted),
            "the row's custody must say WHICH non-production custody it was"
        );
        assert_eq!(state.committed_label(), Some("demonstration_custody"));
        assert_ne!(state.committed_label(), Some("trusted_verified"));
    }

    /// The control for the three tests above: the verdict really is a function of the provenance.
    /// An anchor carrying `External` DOES reach production through this resolver — which is why
    /// `tcb::parse_root_anchor` refuses that word for every key but the compiled-in one, and why a
    /// `FloorPinnedAnchor` cannot be built outside `tcb_probe`. (`for_test` is how this test gets
    /// one; no binary can.)
    #[test]
    fn the_verdict_is_a_function_of_the_provenance_so_an_external_anchor_would_be_production() {
        let state = custody_after_a_turn(Via::Anchor("brops-live-root-1", RootProvenance::External));
        assert!(state.is_production_verified());
        assert_eq!(state.committed_label(), Some("trusted_verified"));
    }

    #[test]
    fn a_manifest_signed_by_another_root_than_the_anchor_resolves_nothing() {
        // The anchor is the floor-pinned one; the manifest names a different root id. `UnknownRoot`
        // inside, `UpstreamBlocked` outside, and no custody observation left behind.
        let dir = tempfile::tempdir().unwrap();
        let (good, _) = resolver_via(dir.path(), true, Via::Anchor("brops-live-root-1", RootProvenance::KitGenerated));
        let inner = good.inner.as_ref().unwrap();
        let other = ProductionResolver::provisioned(
            FloorPinnedAnchor::for_test(RootAnchor {
                pinned: PinnedRoot {
                    root_key_id: "some-other-root".into(),
                    public_key_hex: tcb::DEMO_ROOT_PUBLIC_KEY_HEX.to_string(),
                },
                provenance: RootProvenance::KitGenerated,
            }),
            inner.manifest.clone(),
            inner.root_sig_b64.clone(),
            AntiRollbackFloor { highest_epoch: 2, highest_hash: inner.manifest.content_hash() },
            dir.path().join("floor-other.json"),
            "signer-1".into(),
            "sup-1".into(),
            inner.facts.clone(),
        );
        assert!(matches!(other.resolve_keys(), Err(TurnReason::UpstreamBlocked)));
        assert!(matches!(other.custody().unwrap().resolve(), TrustState::NoTrustedManifest(_)));

        // And the right id over the WRONG key: the signature does not verify.
        let wrong_key = ProductionResolver::provisioned(
            FloorPinnedAnchor::for_test(RootAnchor {
                pinned: PinnedRoot {
                    root_key_id: "brops-live-root-1".into(),
                    public_key_hex: tcb::ROOT_PUBLIC_KEY_HEX.to_string(),
                },
                provenance: RootProvenance::KitGenerated,
            }),
            inner.manifest.clone(),
            inner.root_sig_b64.clone(),
            AntiRollbackFloor { highest_epoch: 2, highest_hash: inner.manifest.content_hash() },
            dir.path().join("floor-wrong.json"),
            "signer-1".into(),
            "sup-1".into(),
            inner.facts.clone(),
        );
        assert!(matches!(wrong_key.resolve_keys(), Err(TurnReason::UpstreamBlocked)));
    }

    #[test]
    fn fail_closed_resolver_blocks_every_turn() {
        // No manifest provisioned => every turn is UpstreamBlocked (shipped default; unchanged behaviour).
        let r = ProductionResolver::fail_closed();
        assert!(!r.is_provisioned());
        assert!(matches!(r.resolve(&req(), "bt", "nonce"), Err(TurnReason::UpstreamBlocked)));
    }

    // The DEMONSTRATION root the tests pin — never a production anchor. Its private is the in-code seed
    // above. The shipped broker pins no compiled root any more (T-131 slice C): it reads the
    // floor-pinned anchor file, and `provisioned_with_pin` labels whatever it is handed `Demonstration`.
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
        resolver_at_epoch_persisting_to(epoch, floor_path, floor_path)
    }

    /// The same resolver, with the floor READ from one path and WRITTEN BACK to another — so a test
    /// can make the persist fail while everything else about the deployment stays resolvable.
    fn resolver_at_epoch_persisting_to(
        epoch: u64,
        floor_path: &std::path::Path,
        persist_to: &std::path::Path,
    ) -> (ProductionResolver, KeyManifest) {
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
            demo_pin(), manifest.clone(), root_sig, floor, persist_to.to_path_buf(),
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
    ///
    /// The manifest here carries BOTH production keys, on purpose. This test used to build its own
    /// with `"keys": []` while asking for `signer-1`, so the turn blocked on `KeyNotFound` whether or
    /// not the persist refused, and deleting the refusal left it green. The control below is what
    /// makes the unwritable path the only reason left to block.
    #[test]
    fn an_unwritable_floor_blocks_the_turn() {
        let dir = tempfile::tempdir().unwrap();
        let floor_path = dir.path().join("floor.json");
        std::fs::write(&floor_path, brops_core::key_manifest::floor_json_bytes(
            &AntiRollbackFloor { highest_epoch: 0, highest_hash: String::new() },
        )).unwrap();

        // The control: this exact deployment, persisting to a writable path, RESOLVES.
        let (writable, _) =
            resolver_at_epoch_persisting_to(5, &floor_path, &dir.path().join("floor-written.json"));
        writable
            .resolve(&req(), "bt", "nonce")
            .expect("with a writable floor this manifest and these keys resolve");

        // The same deployment, pointed at a path inside a directory that does not exist, so both
        // the temp write and the rename fail.
        let unwritable = dir.path().join("no-such-dir").join("floor.json");
        let (r, _) = resolver_at_epoch_persisting_to(5, &floor_path, &unwritable);
        assert!(matches!(r.resolve(&req(), "bt", "nonce"), Err(TurnReason::UpstreamBlocked)));
        // And a turn refused there leaves no custody observation for the next one to commit on.
        assert!(matches!(r.custody().unwrap().resolve(), TrustState::NoTrustedManifest(_)));
    }

    // ---- the key pair (the one implementation the drivers share) -----------------------------

    /// A manifest with the two keys a turn pins, each field overridable, and NO signature: the
    /// pair resolution reads none — root verification is the caller's, before it.
    fn pair_manifest(signer: serde_json::Value, supervisor: serde_json::Value) -> KeyManifest {
        serde_json::from_value(json!({
            "manifest_epoch": 2u64, "root_key_id": "any-root", "keys": [signer, supervisor]
        }))
        .unwrap()
    }

    fn key(key_id: &str, public_key_hex: &str) -> serde_json::Value {
        json!({
            "key_id": key_id, "public_key_hex": public_key_hex, "trust_class": "production",
            "valid_from_ms": 1000, "valid_to_ms": 9000, "key_epoch": 2u64, "revoked": false,
            "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE]
        })
    }

    fn with(mut key: serde_json::Value, field: &str, value: serde_json::Value) -> serde_json::Value {
        key[field] = value;
        key
    }

    #[test]
    fn two_distinct_production_keys_in_their_window_resolve_as_a_pair() {
        let m = pair_manifest(key("signer-1", &"11".repeat(32)), key("sup-1", &"22".repeat(32)));
        let pair = resolve_production_key_pair(&m, "signer-1", "sup-1", 5000).expect("resolves");
        assert_eq!(pair.signer.key_id, "signer-1");
        assert_eq!(pair.signer_public_key, [0x11; 32]);
        assert_eq!(pair.supervisor_attestation.key_id, "sup-1");
        assert_eq!(pair.supervisor_attestation_public_key, [0x22; 32]);
    }

    /// THE `live_turn` DEFECT, as the function that replaced it. The supervisor attestation key is
    /// held to everything the signer key is: a key that is merely PRESENT under the right id is not
    /// enough.
    #[test]
    fn the_supervisor_key_is_held_to_class_revocation_window_and_protocol() {
        let signer = || key("signer-1", &"11".repeat(32));
        let sup = || key("sup-1", &"22".repeat(32));
        let refused = KeyPairRefusal::SupervisorAttestationKeyUnresolved;
        for (what, supervisor, now) in [
            ("revoked", with(sup(), "revoked", json!(true)), 5000),
            ("development class", with(sup(), "trust_class", json!("development")), 5000),
            ("not yet valid", sup(), 999),
            ("expired", sup(), 9000),
            ("another protocol", with(sup(), "allowed_protocols", json!(["brops.other.v1"])), 5000),
        ] {
            // `now` is inside the SIGNER's window in every case, so the signer is not what refuses.
            let signer = with(with(signer(), "valid_from_ms", json!(1)), "valid_to_ms", json!(99_999));
            let m = pair_manifest(signer, supervisor);
            assert_eq!(
                resolve_production_key_pair(&m, "signer-1", "sup-1", now),
                Err(refused),
                "{what}"
            );
        }
        // Absent altogether is the same refusal, and the signer is held to the same rule.
        let m = pair_manifest(signer(), sup());
        assert_eq!(resolve_production_key_pair(&m, "signer-1", "sup-9", 5000), Err(refused));
        let m = pair_manifest(with(signer(), "revoked", json!(true)), sup());
        assert_eq!(
            resolve_production_key_pair(&m, "signer-1", "sup-1", 5000),
            Err(KeyPairRefusal::SignerKeyUnresolved)
        );
    }

    #[test]
    fn a_key_that_is_not_32_bytes_of_hex_is_refused_by_the_name_of_which_one() {
        let m = pair_manifest(key("signer-1", "zz"), key("sup-1", &"22".repeat(32)));
        assert_eq!(
            resolve_production_key_pair(&m, "signer-1", "sup-1", 5000),
            Err(KeyPairRefusal::SignerPubkeyMalformed)
        );
        let m = pair_manifest(key("signer-1", &"11".repeat(32)), key("sup-1", &"22".repeat(31)));
        assert_eq!(
            resolve_production_key_pair(&m, "signer-1", "sup-1", 5000),
            Err(KeyPairRefusal::SupervisorPubkeyMalformed)
        );
    }

    /// One key must not be both the receipt signer and the supervisor attestation — named twice by
    /// one id, or entered twice under two ids, or under two spellings of one hex string.
    #[test]
    fn one_key_cannot_be_both_the_signer_and_the_supervisor_attestation() {
        let m = pair_manifest(key("signer-1", &"11".repeat(32)), key("sup-1", &"22".repeat(32)));
        assert_eq!(
            resolve_production_key_pair(&m, "signer-1", "signer-1", 5000),
            Err(KeyPairRefusal::KeysNotDistinct)
        );
        let m = pair_manifest(key("signer-1", &"ab".repeat(32)), key("sup-1", &"ab".repeat(32)));
        assert_eq!(
            resolve_production_key_pair(&m, "signer-1", "sup-1", 5000),
            Err(KeyPairRefusal::KeysNotDistinct)
        );
        let m = pair_manifest(key("signer-1", &"ab".repeat(32)), key("sup-1", &"AB".repeat(32)));
        assert_eq!(
            resolve_production_key_pair(&m, "signer-1", "sup-1", 5000),
            Err(KeyPairRefusal::KeysNotDistinct)
        );
    }

    /// The shipped resolver goes THROUGH that function: a config naming one key for both roles
    /// resolves nothing, and leaves no custody observation behind.
    #[test]
    fn the_broker_resolver_refuses_one_key_in_both_roles() {
        let dir = tempfile::tempdir().unwrap();
        let (good, _) = demo_resolver(dir.path(), true);
        let inner = good.inner.as_ref().unwrap();
        let collapsed = ProductionResolver::provisioned_with_pin(
            demo_pin(),
            inner.manifest.clone(),
            inner.root_sig_b64.clone(),
            AntiRollbackFloor { highest_epoch: 2, highest_hash: inner.manifest.content_hash() },
            dir.path().join("floor-collapsed.json"),
            "signer-1".into(),
            "signer-1".into(),
            inner.facts.clone(),
        );
        assert!(matches!(collapsed.resolve_keys(), Err(TurnReason::UpstreamBlocked)));
        assert!(matches!(collapsed.custody().unwrap().resolve(), TrustState::NoTrustedManifest(_)));
        // The control: the same deployment naming the two keys it has does resolve.
        good.resolve_keys().expect("two distinct keys resolve");
    }

    // ---- the clock ------------------------------------------------------------------------------

    struct UnreadableClock;
    impl WallClock for UnreadableClock {
        fn now_ms(&self) -> Option<i64> {
            None
        }
    }
    struct FixedClock(i64);
    impl WallClock for FixedClock {
        fn now_ms(&self) -> Option<i64> {
            Some(self.0)
        }
    }

    /// A clock the host cannot read is a refusal, never a window evaluated at 0.
    #[test]
    fn an_unreadable_clock_blocks_key_resolution_and_custody() {
        let dir = tempfile::tempdir().unwrap();
        let (r, _) = demo_resolver(dir.path(), true);
        let r = r.with_clock(Arc::new(UnreadableClock));
        assert!(matches!(r.resolve_keys(), Err(TurnReason::UpstreamBlocked)));
        assert!(matches!(r.custody().unwrap().resolve(), TrustState::NoTrustedManifest(_)));

        // Custody reads the clock itself, per call: a turn that resolved while the clock worked
        // stops producing a label the moment it does not. `custody()` hands out a view of the SAME
        // observation cell, so the one taken after the clock is swapped still holds the turn.
        let (ok, _) = demo_resolver(dir.path(), true);
        ok.resolve_keys().expect("the real clock is inside the fixture's validity window");
        assert!(ok.custody().unwrap().resolve().committed_label().is_some());
        let ok = ok.with_clock(Arc::new(UnreadableClock));
        match ok.custody().unwrap().resolve() {
            TrustState::NoTrustedManifest(why) => assert!(why.contains("clock"), "{why}"),
            other => panic!("an unreadable clock produced {other:?}"),
        }
    }

    /// The seam is the clock the window is evaluated against, not decoration: the fixture's keys
    /// are valid from 1 ms, so a reading of 0 is BEFORE the window and must refuse.
    #[test]
    fn the_injected_clock_is_the_one_the_validity_window_is_evaluated_against() {
        let dir = tempfile::tempdir().unwrap();
        let (r, _) = demo_resolver(dir.path(), true);
        let r = r.with_clock(Arc::new(FixedClock(0)));
        assert!(matches!(r.resolve_keys(), Err(TurnReason::UpstreamBlocked)));
        let (r, _) = demo_resolver(dir.path(), true);
        let r = r.with_clock(Arc::new(FixedClock(5_000)));
        r.resolve_keys().expect("5000 ms is inside the fixture's window");
    }
}
