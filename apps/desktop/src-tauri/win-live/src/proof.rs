//! In-process full governed-turn proof — the CI-portable heart of the Windows live kit.
//!
//! It assembles ONE real governed turn with the three trusted-principal cores in memory (no sockets, no
//! winapi): the SAME `brops_broker::chain_executor::GovernedChain` + `run_governed_turn` + the SAME
//! `verify_and_accept` the production broker uses, driven over an in-process [`HopConn`] that routes each
//! framed hop to the right core. The only path to `production_verified=true bound=true` is a genuine
//! `verify_and_accept` of the isolated-signer envelope over this exact output under the root-signed
//! manifest's production key. Because everything here is host-independent, this proof runs on the Linux CI
//! runner too — proving the crypto chain end-to-end; the Windows bins then swap only the transport.

use std::path::Path;
use std::sync::Arc;

use rusqlite::Connection;
use serde_json::{json, Value};

use brops_broker::chain_executor::{ChainExecutor, CustodyResolver, ExecutionPlan, GovernedChain};
use brops_broker::chain_hops::{HopConn, HopError, Principal};

use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
use brops_core::governed_turn_ipc::REQUEST_PROTOCOL;
use brops_core::broker_turns::DurableAcceptanceLedger;
use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
use brops_core::key_manifest::{
    check_and_advance, resolve_production_key, verify_manifest_anchored, AntiRollbackFloor, KeyManifest,
    PinnedRoot, RootAnchor, RootProvenance,
};
use brops_core::production_trust::{resolve_trust_state, verifying_key_hex, TrustState};

use crate::crypto;
use crate::execution::{ExecutionParams, GovernedExecutionCore};
use crate::resolver::{ManifestResolver, ResolvedFacts, SharedResolver};

/// This run's custody answer, consulted BY the broker rather than after it. Mirrors `WinCustody` in
/// `win_live_turn`; both exist because the two drivers wire their chains differently and neither
/// should get to decide custody on its own after the fact.
struct ProofCustody {
    manifest: brops_core::key_manifest::KeyManifest,
    verified_root: brops_core::key_manifest::VerifiedManifestRoot,
    signer_key_id: String,
    resolver: std::sync::Arc<ManifestResolver>,
    /// This proof run's fixed clock. Unlike the live drivers, `in_process_turn` is given its `now_ms`
    /// by the caller so a test can pin the manifest token window; reading the real clock here would
    /// make the custody verdict disagree with the rest of the run.
    now_ms: i64,
}

impl CustodyResolver for ProofCustody {
    fn resolve(&self) -> TrustState {
        // F-29: the key the CHAIN verified under, recorded by the resolver — not a second manifest
        // lookup, which made this guard compare a value against itself. No key recorded means the
        // chain bound none, and there is nothing to vouch for.
        let verified_under = match self.resolver.last_verifying_key() {
            Some(k) => verifying_key_hex(&k),
            None => return TrustState::NoTrustedManifest("chain bound no envelope verifying key"),
        };
        resolve_trust_state(
            Some(&self.manifest),
            Some(&self.verified_root),
            &self.signer_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            self.now_ms,
            &verified_under,
        )
    }
}

/// A handle the driver keeps while the broker owns one too. `Arc` alone cannot carry the impl —
/// both `Arc` and the trait are foreign here — so the shared handle is a local newtype, which is also
/// the clearer statement: exactly one resolver exists, and the reported verdict and the committed row
/// are answers from that same object.
struct SharedCustody(std::sync::Arc<ProofCustody>);

impl CustodyResolver for SharedCustody {
    fn resolve(&self) -> TrustState {
        self.0.resolve()
    }
}
use crate::servers::{
    Authority, AuthorityConfig, DispatchCore, Signer, SignerConfig, Supervisor, SupervisorConfig,
};
use crate::tcb;

pub struct ProofOutcome {
    /// TRUE only for a manifest anchored by a root whose custody is EXTERNAL to this kit. This proof
    /// signs with the compiled-in DEMONSTRATION root, so it is always `false` here — see
    /// [`ProofOutcome::chain_bound`], which is the property this proof actually establishes.
    pub production_verified: bool,
    /// The governed chain resolved a production-class key under a verified anchor and bound the turn —
    /// i.e. the whole challenge→lease→attest→sign→verify chain really ran. Separate from, and weaker
    /// than, the custody claim above.
    pub chain_bound: bool,
    pub bound: bool,
    pub trust_str: String,
}

impl ProofOutcome {
    /// May a reply produced by this run be posted to the chat carrying the
    /// `demonstration_verified` badge?
    ///
    /// **Read the field this returns, not [`production_verified`](Self::production_verified).**
    /// `production_verified` is `true` only under a root whose custody is EXTERNAL to this kit,
    /// and every path into this module signs with the compiled-in DEMONSTRATION root, so it is
    /// **always** `false` here — asserted by `produce_drives_the_chain_output`. A caller that
    /// gated on it therefore had a command that could not succeed on any input, which is exactly
    /// what happened: `commands::demonstration_verified_reply` required
    /// `outcome.bound && outcome.production_verified` and so always returned the
    /// "demonstration chain did not verify" error, from a button wired in the shipped UI, for as
    /// long as it existed. Nothing caught it because nothing tested it.
    ///
    /// The honest condition is the one the badge actually claims: the whole
    /// challenge→lease→attest→sign→verify chain ran and resolved a key ([`chain_bound`]), and the
    /// committed row's body digest matches what the envelope bound ([`bound`]). Custody is
    /// demonstration custody, which is what `demonstration_verified` says.
    ///
    /// [`chain_bound`]: Self::chain_bound
    /// [`bound`]: Self::bound
    pub fn may_post_as_demonstration_verified(&self) -> bool {
        self.bound && self.chain_bound
    }
}

struct UuidIds;
impl BrokerIds for UuidIds {
    fn new_broker_turn_id(&self) -> String {
        brops_core::id()
    }
    fn new_request_nonce(&self) -> String {
        brops_core::id()
    }
}

/// One fresh in-process connection to a core: `send_all` decodes the frame, dispatches to the core, and
/// buffers the framed reply; `recv_all` returns it. Mirrors the servers' one-frame-per-connection contract.
struct InProcConn {
    core: Arc<dyn DispatchCore>,
    now: i64,
    reply: Option<Vec<u8>>,
}
impl HopConn for InProcConn {
    fn send_all(&mut self, frame: &[u8]) -> Result<(), HopError> {
        let payload = brops_core::ipc_framing::decode_one(frame).map_err(HopError::from)?;
        let req: Value = serde_json::from_slice(payload).map_err(|_| HopError::BadReply)?;
        let reply = self.core.handle(&req, self.now);
        let bytes = serde_json::to_vec(&reply).map_err(|_| HopError::BadReply)?;
        self.reply = Some(brops_core::ipc_framing::encode_frame(&bytes).map_err(HopError::from)?);
        Ok(())
    }
    fn recv_all(&mut self) -> Result<Vec<u8>, HopError> {
        self.reply.take().ok_or(HopError::Io)
    }
}

fn seed(store: &Path, content: &[u8]) -> String {
    let h = crypto::sha256_hex(content);
    std::fs::write(store.join(&h), content).expect("seed store blob");
    h
}

fn init_schema(conn: &Connection) -> Result<(), String> {
    brops_core::broker_turns::create_schema(conn).map_err(|e| format!("{e:?}"))?;
    brops_core::governed_message_store::create_schema(conn).map_err(|e| format!("{e}"))?;
    brops_core::supervisor_ledger::create_schema(conn).map_err(|e| format!("{e:?}"))?;
    Ok(())
}

/// Run one full governed turn in-process over a fresh content-addressed store at `store_dir`, using `now_ms`
/// as the single wall-clock for every core, with a fixed demonstration output. Self-test entry point.
pub fn in_process_turn(store_dir: &Path, now_ms: i64) -> Result<ProofOutcome, String> {
    in_process_turn_output(store_dir, now_ms, b"BROPS windows governed output v1")
}

/// Same in-process governed chain over a PRE-COMPUTED `output` (the executor re-emits these exact bytes).
/// Thin wrapper over [`in_process_turn_produce`]. NOTE (honesty): pre-computing the output and merely signing
/// it does NOT mean the chain produced it — for a live turn that must render "Verified", prefer
/// [`in_process_turn_produce`], which runs the model INSIDE the chain's execution step. Custody is the
/// compiled-in DEMONSTRATION anchor (`tcb::DEMO_*`) — surface as demonstration custody, never production.
pub fn in_process_turn_output(store_dir: &Path, now_ms: i64, output: &[u8]) -> Result<ProofOutcome, String> {
    let out = output.to_vec();
    in_process_turn_produce(store_dir, now_ms, move || if out.is_empty() { Err(()) } else { Ok(out.clone()) })
}

/// The honest live-turn seam. The chain's EXECUTOR closure `produce` is invoked DURING the governed execution
/// step to generate the reply, so the answer is produced *inside* the chain (not pre-computed and merely
/// signed) and then bound + signed + `verify_and_accept`'d over exactly those bytes. A demonstration-custody
/// live turn passes a `produce` that runs the model (e.g. the local Claude CLI); the receipt binds precisely
/// what the chain's executor produced. Custody is the compiled-in DEMONSTRATION anchor (`tcb::DEMO_*`) and the
/// executor is not session-0-contained here — so the caller MUST surface the result as **demonstration
/// custody**, never production `trusted_verified`, until an operator-rooted manifest + contained executor
/// drive the chain (see WIRING_LIVE_TRUST.md + SECURITY_MODEL.md §5). Fail-closed: an empty produced output
/// can never be signed.
pub fn in_process_turn_produce<F>(store_dir: &Path, now_ms: i64, produce: F) -> Result<ProofOutcome, String>
where
    F: Fn() -> Result<Vec<u8>, ()>,
{
    std::fs::create_dir_all(store_dir).map_err(|e| format!("store dir: {e}"))?;

    // ---- keys (four ed25519 keypairs) ----
    let challenge_seed = crypto::gen_seed();
    let attest_seed = crypto::gen_seed();
    let signer_seed = crypto::gen_seed();
    let challenge_pub = crypto::public_key_hex(&crypto::signing_key(&challenge_seed));
    let attest_pub = crypto::public_key_hex(&crypto::signing_key(&attest_seed));
    let signer_pub = crypto::public_key_hex(&crypto::signing_key(&signer_seed));

    let challenge_key_id = "brops-live-challenge-1".to_string(); // gitleaks:allow (fake public key-id)
    let sup_attest_key_id = "brops-live-sup-attest-1".to_string(); // gitleaks:allow (fake public key-id)
    let signer_key_id = "brops-live-signer-1".to_string(); // gitleaks:allow (fake public key-id)
    // Root anchor is the DEMONSTRATION key (tcb::DEMO_*), NOT the production anchor: this in-process proof
    // signs with an in-code private to exercise the whole crypto chain host-independently. Production trust is
    // pinned to tcb::ROOT_PUBLIC_KEY_HEX alone (operator's offline root), which this proof never touches.
    let root_key_id = tcb::DEMO_ROOT_KEY_ID.to_string();
    let supervisor_id = "brops-supervisor".to_string();
    let executor_id = "brops-executor".to_string();
    let builder_id = "brops-builder".to_string();

    // ---- content-addressed store blobs (resolved component digests + chain handles) ----
    let system_sha256 = seed(store_dir, b"brops-system-prompt-v1");
    let history_sha256 = seed(store_dir, b"brops-history-v1");
    let generation_config_sha256 = seed(store_dir, b"brops-generation-config-v1");
    let policy_bundle_handle = seed(store_dir, b"brops-policy-bundle-v1");
    // F-02: no pre-seeded containment stub either — the execution writes a per-run containment
    // report into this store and names its content address.
    // F-02: no pre-seeded record/lease/execution-receipt blobs. The supervisor BUILDS those
    // documents from its own acceptance + completion rows and publishes them to this store, so the
    // handles the receipt names address artifacts of THIS run rather than provisioner stubs.
    let launcher_sha = crypto::sha256_hex(b"brops-launcher.bin");
    let executor_sha = crypto::sha256_hex(b"brops-executor.bin");

    // ---- root-signed production key manifest + anti-rollback floor ----
    let manifest_json = json!({
        "manifest_epoch": 2u64,
        "root_key_id": root_key_id,
        "keys": [
            { "key_id": signer_key_id, "public_key_hex": signer_pub, "trust_class": "production",
              "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
              "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] },
            { "key_id": sup_attest_key_id, "public_key_hex": attest_pub, "trust_class": "production",
              "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
              "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] }
        ]
    });
    let manifest: KeyManifest =
        serde_json::from_value(manifest_json).map_err(|e| format!("manifest_build: {e}"))?;
    // The DEMONSTRATION root private signs the manifest — an in-code test seed whose public is tcb::DEMO_ROOT_
    // PUBLIC_KEY_HEX. This is exactly why it is NOT production custody: the seed is in the source. The real
    // production root private lives offline and its public (tcb::ROOT_PUBLIC_KEY_HEX) is pinned separately.
    let demo_root_seed =
        "0011223344556677001122334455667700112233445566770011223344556677"; // gitleaks:allow (demo test root)
    let demo_root = crypto::signing_key(&crypto::hex32(demo_root_seed).expect("root seed"));
    let root_sig = crypto::sign_b64std(&demo_root, &manifest.canonical_bytes());
    // The anchor's CUSTODY is `Demonstration` and is declared as such: its private half is the seed two
    // lines above, in this source file. `verify_manifest_anchored` returns the token that carries that
    // fact into `resolve_trust_state`, which is why this proof can never render `Production` however
    // completely the chain runs. That is the correct outcome, not a limitation to work around.
    let root_anchor = RootAnchor {
        pinned: PinnedRoot {
            root_key_id: tcb::DEMO_ROOT_KEY_ID.to_string(),
            public_key_hex: tcb::demo_root_public_key_hex(),
        },
        provenance: RootProvenance::Demonstration,
    };
    let verified_root = verify_manifest_anchored(&manifest, &root_sig, &root_anchor)
        .map_err(|e| format!("verify_manifest: {e:?}"))?;

    let floor = AntiRollbackFloor { highest_epoch: 2, highest_hash: manifest.content_hash() };
    check_and_advance(&floor, &manifest).map_err(|e| format!("anti_rollback: {e:?}"))?;
    // Keep-alive clone + resolved signer pubkey for the final trust classification (the resolver, below, is
    // the enforcement path that re-verifies the manifest + anti-rollback + resolves keys INSIDE the chain).
    let manifest_for_trust = manifest.clone();
    // Kept as an EARLY fail-closed check that the production signer key resolves at all; the
        // production VERDICT no longer reads it (F-29 — it now uses the key the chain verified under).
        let _signer_pub_hex = resolve_production_key(&manifest, &signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now_ms)
        .map_err(|e| format!("key_resolution: {e:?}"))?
        .public_key_hex;

    // ---- the three trusted-principal cores ----
    let authority: Arc<dyn DispatchCore> = Arc::new(Authority::new(AuthorityConfig {
        challenge_key_id: challenge_key_id.clone(),
        supervisor_id: supervisor_id.clone(),
        challenge_signing_seed: challenge_seed,
    }));
    let supervisor: Arc<Supervisor> = Arc::new(Supervisor::new(SupervisorConfig {
        supervisor_id: supervisor_id.clone(),
        supervisor_attestation_key_id: sup_attest_key_id.clone(),
        challenge_public_key_hex: challenge_pub,
        attest_signing_seed: attest_seed,
        launcher_executable_sha256: launcher_sha,
        executor_executable_sha256: executor_sha,
        // F-01: the identities the signer allowlists are the SUPERVISOR's provisioning now, not
        // values the execution hands it alongside the run facts.
        executor_id: executor_id.clone(),
        builder_id: builder_id.clone(),
        policy_id: "brops-policy-1".to_string(),
        policy_version: "1".to_string(),
        policy_bundle_handle: policy_bundle_handle.clone(),
        store_dir: store_dir.to_path_buf(),
            // F-01: where the execution writes its per-run evidence chain.
            evidence_dir: store_dir.to_path_buf().join("run-evidence"),
    }));
    let signer: Arc<dyn DispatchCore> = Arc::new(Signer::new(SignerConfig {
        receipt_key_id: signer_key_id.clone(),
        supervisor_attestation_key_id: sup_attest_key_id.clone(),
        supervisor_attestation_public_key_hex: attest_pub.clone(),
        receipt_signing_seed: signer_seed,
        store_dir: store_dir.to_path_buf(),
        allowed_executors: vec![executor_id.clone()],
        allowed_builders: vec![builder_id.clone()],
        allowed_supervisors: vec![supervisor_id.clone()],
    }));

    // ---- in-process transport: route each Principal to its core ----
    let auth_c = authority.clone();
    let sup_c: Arc<dyn DispatchCore> = supervisor.clone();
    let sign_c = signer.clone();
    let connector = move |p: Principal| -> Result<Box<dyn HopConn>, HopError> {
        let core: Arc<dyn DispatchCore> = match p {
            Principal::ChallengeAuthority => auth_c.clone(),
            Principal::Supervisor => sup_c.clone(),
            Principal::IsolatedSigner => sign_c.clone(),
        };
        Ok(Box::new(InProcConn { core, now: now_ms, reply: None }))
    };

    // ---- execution: produce output + drive the §5 lifecycle ops against the supervisor core ----
    let sup_a = supervisor.clone();
    let supervisor_op = move |req: &Value| -> Result<Value, ()> {
        let reply = sup_a.handle(req, now_ms);
        if reply.get("ok").and_then(Value::as_bool) == Some(true) {
            Ok(reply)
        } else {
            Err(())
        }
    };
    // `produce` (the fn parameter) IS the executor: the chain calls it DURING this execution step, so the
    // reply is generated inside the chain. The signer signs exactly what it returns and verify_and_accept
    // binds those bytes. Fail-closed: `produce` returns Err on empty, and an empty output can never be signed.
    // The GovernedChain executor takes a plan-aware closure; the plan is not needed to produce here (the
    // caller's `produce` already knows its prompt), so wrap and ignore it — this keeps `produce` a simple
    // `Fn()` on the public API without leaking `ExecutionPlan` to callers.
    let exec_produce = |_plan: &ExecutionPlan| -> Result<Vec<u8>, ()> { produce() };
    let params = ExecutionParams {
        store_dir: store_dir.to_path_buf(),
        containment_mode: "windows-proof-kit:in-process, no setuid launcher".to_string(),
        // F-02/F-01: the evidence head is MEASURED by the execution now, not configured. The
        // proof writes its chain beside the store; in the in-process proof that is a shape check,
        // and in the cross-account deployment the directory belongs to the executor principal.
        evidence_dir: store_dir.join("run-evidence"),
        head_sequence: 3,
    };
    let exec = GovernedExecutionCore::new(params, exec_produce, supervisor_op, now_ms);

    // ---- production manifest resolver (audit P1-b + P2): verify-manifest-vs-TCB + anti-rollback + PERSIST
    //      floor + resolve keys INSIDE the chain resolution, feeding the pinned keys verify_and_accept uses. ----
    let facts = ResolvedFacts {
        workspace_id: "ws-live-1".to_string(),
        install_id: "install-live-1".to_string(),
        system_sha256,
        history_sha256,
        generation_config_sha256,
        requested_at: now_ms.to_string(),
        run_id: "run-live-1".to_string(),
        task_id: "task-live-1".to_string(),
        requested_at_ms: now_ms,
        author: "Bro".to_string(),
    };
    let resolver = ManifestResolver::with_pinned_root(
        // The SAME anchor key the token above was issued under — the resolver re-verifies the manifest
        // against it inside the chain, which is the enforcement path.
        root_anchor.pinned.clone(),
        manifest,
        root_sig,
        floor,
        store_dir.join("floor.json"),
        signer_key_id.clone(),
        sup_attest_key_id.clone(),
        facts,
    );

    // Keep a handle to the SAME resolver the chain drives, so the production verdict below is
    // bound to the key it actually verified under (F-29).
    let resolver_handle = std::sync::Arc::new(resolver);
    // A real file under the proof's own directory: the replay ledger has to have something
    // durable underneath it or the receipt-id and nonce defences cover one process and no more
    // (audit IDX-67/86/94, IDX-82).
    let db_path = store_dir.join("win-live-proof-turns.db");
    // (audit IDX-67/86/94) The replay defences — global receipt-id uniqueness and the
    // one-time nonce consume — were an `InMemoryLedger` here, which its own doc calls a
    // test double. They lived for the lifetime of a process, so the same signed receipt
    // and the same one-time nonce were accepted again after a restart. This is the
    // Windows PRODUCTION trusted_verified path, so it was the worst place for that.
    let ledger = DurableAcceptanceLedger::open(&db_path.to_string_lossy())
        .map_err(|e| format!("replay ledger unavailable: {e:?}"))?;
    let chain = GovernedChain::new(connector, SharedResolver(resolver_handle.clone()), exec, ledger);
    // Custody is an INPUT to the turn, not a remark about it afterwards. See `WinCustody` for why:
    // resolving after `run_governed_turn` left the committed row asserting full trust regardless of
    // the verdict this function then printed.
    let custody = std::sync::Arc::new(ProofCustody {
        manifest: manifest_for_trust.clone(),
        verified_root: verified_root.clone(),
        signer_key_id: signer_key_id.clone(),
        resolver: resolver_handle.clone(),
        now_ms,
    });
    let executor = ChainExecutor::with_custody(chain, Box::new(SharedCustody(custody.clone())));

    // ---- run ONE governed turn ----
    let conn = Connection::open(&db_path).map_err(|e| format!("db_open: {e}"))?;
    init_schema(&conn)?;
    let request = json!({
        "protocol": REQUEST_PROTOCOL,
        "conversation_id": "conv-live-1",
        "agent": "Bro",
        "client_request_id": brops_core::id(),
    })
    .to_string();

    let result = run_governed_turn(&conn, &request, &UuidIds, &executor, now_ms);
    if result.status != "committed" {
        let reason = result.reason.map(|r| format!("{r:?}")).unwrap_or_else(|| "unknown".into());
        return Err(format!("chain:{reason}"));
    }
    let message = result.message.ok_or("committed_without_message")?;
    // `bound` was `message.trust_state == TRUSTED_VERIFIED`, which no projection could fail because
    // the constructor hardcoded that string. It now re-reads the durable row and recomputes the body
    // digest against what the envelope committed to.
    let bound = brops_core::governed_message_store::verify_committed_binding(&conn, &message).is_ok();

    let ts = custody.resolve();
    // Printed verdict and durable row, or it is not a result.
    if Some(message.trust_state.as_str()) != ts.committed_label() {
        return Err("custody_row_mismatch".to_string());
    }
    let production_verified = ts.is_production_verified();
    let chain_bound = ts.is_chain_bound();
    let trust_str = match &ts {
        TrustState::Production { key_id, key_epoch, root_key_id } => {
            format!("trusted_verified(production key={key_id} epoch={key_epoch} root={root_key_id})")
        }
        TrustState::DemonstrationCustody { key_id, key_epoch, root_key_id, root_provenance } => format!(
            "trusted_verified(demonstration_custody key={key_id} epoch={key_epoch} root={root_key_id} \
             root_provenance={})",
            root_provenance.as_str()
        ),
        TrustState::NoTrustedManifest(r) => format!("no_trusted_manifest({r})"),
    };
    Ok(ProofOutcome { production_verified, chain_bound, bound, trust_str })
}

#[cfg(test)]
mod tests {
    use super::*;
    use brops_broker::chain_executor::{SystemWallClock, WallClock};

    /// This host's REAL wall clock, in epoch ms.
    ///
    /// These tests used to pin `1_900_000_000_000` ("a fixed, plausible wall clock" — the year 2030).
    /// That worked only while nothing in the chain consulted a clock it did not receive as an argument.
    /// §7.1 freshness now bounds the receipt's signed `_ms` fields against the broker's own reading, so
    /// a run declaring 2030 to every core while the machine says otherwise is exactly the skewed receipt
    /// the check exists to refuse. Using the real clock is also what the two SHIPPED callers of
    /// `in_process_turn_produce` do (`governed_trust_selftest`, the demonstration-chat command), so the
    /// tests now exercise the configuration that ships.
    fn now() -> i64 {
        SystemWallClock.now_ms().expect("this host must have a readable wall clock")
    }

    #[test]
    fn full_governed_turn_reaches_trusted_verified_in_process() {
        let dir = std::env::temp_dir().join(format!("brops-winlive-proof-{}", brops_core::id()));
        let now = now();
        let outcome = in_process_turn(&dir, now).expect("governed turn must commit");
        let _ = std::fs::remove_dir_all(&dir);
        assert!(outcome.bound, "committed body must be trusted_verified: {}", outcome.trust_str);
        assert!(
            outcome.chain_bound,
            "the chain must resolve a production-class key under the verified anchor: {}",
            outcome.trust_str
        );
        // The custody half, asserted in the direction that matters. This proof signs the manifest with
        // the compiled-in demonstration root, so it MUST NOT reach a production verdict — anyone with
        // the source can mint that manifest. The assertion used to be the opposite way round, which is
        // precisely the overclaim the anchor-provenance work removed.
        assert!(
            !outcome.production_verified,
            "a demonstration-anchored manifest must never render production: {}",
            outcome.trust_str
        );
        assert!(outcome.trust_str.contains("demonstration_custody"), "{}", outcome.trust_str);
    }

    #[test]
    fn live_output_is_signed_and_bound_by_the_chain() {
        // The live seam: an arbitrary reply (what a model produced) is what gets signed and bound —
        // trusted_verified is over the REAL answer, not a fixed demo string. (Custody is still demo.)
        let dir = std::env::temp_dir().join(format!("brops-winlive-live-{}", brops_core::id()));
        let now = now();
        let reply = b"Bro: here is the verified live answer to your question.";
        let outcome = in_process_turn_output(&dir, now, reply).expect("live governed turn must commit");
        let _ = std::fs::remove_dir_all(&dir);
        assert!(outcome.bound, "the real reply bytes must be bound: {}", outcome.trust_str);
        assert!(outcome.chain_bound, "chain must verify the live output: {}", outcome.trust_str);
        assert!(!outcome.production_verified, "custody is demo, not production: {}", outcome.trust_str);
    }

    /// §7.1 freshness reaches THIS harness too. `in_process_turn_produce` hands its `now_ms` to every
    /// core, so a caller can stamp the whole turn with any time it likes — but the acceptance clock is
    /// the broker's own [`SystemWallClock`], not that argument. A run declaring a clock the host does
    /// not agree with therefore cannot commit, in either direction.
    #[test]
    fn a_turn_run_under_a_fabricated_clock_cannot_commit() {
        const TEN_YEARS_MS: i64 = 10 * 365 * 24 * 60 * 60 * 1000;
        for (name, now) in [("far future", now() + TEN_YEARS_MS), ("far past", now() - TEN_YEARS_MS)] {
            let dir = std::env::temp_dir().join(format!("brops-winlive-clock-{}", brops_core::id()));
            let r = in_process_turn(&dir, now);
            let _ = std::fs::remove_dir_all(&dir);
            assert!(r.is_err(), "{name}: a fabricated wall clock must not produce a committed turn");
        }
    }

    #[test]
    fn empty_live_output_fails_closed() {
        let dir = std::env::temp_dir().join(format!("brops-winlive-empty-{}", brops_core::id()));
        let now = now();
        let r = in_process_turn_output(&dir, now, b"");
        let _ = std::fs::remove_dir_all(&dir);
        assert!(r.is_err(), "an empty output must never produce a committed/verified turn");
    }

    #[test]
    fn produce_is_invoked_inside_the_chain_and_its_output_is_verified() {
        // The honest live seam: the chain CALLS `produce` during its execution step, so the reply is
        // generated INSIDE the chain (not pre-computed and merely signed). Prove the closure actually ran
        // and that the bytes it produced are what got bound + verified.
        use std::sync::atomic::{AtomicBool, Ordering};
        let dir = std::env::temp_dir().join(format!("brops-winlive-produce-{}", brops_core::id()));
        let now = now();
        let called = AtomicBool::new(false);
        let outcome = in_process_turn_produce(&dir, now, || {
            called.store(true, Ordering::SeqCst);
            Ok(b"Bro (produced inside the chain): the live answer.".to_vec())
        })
        .expect("a produce-driven governed turn must commit");
        let _ = std::fs::remove_dir_all(&dir);
        assert!(called.load(Ordering::SeqCst), "the chain must invoke produce during execution");
        assert!(
            outcome.bound && outcome.chain_bound,
            "the reply produced inside the chain must be bound + verified: {}",
            outcome.trust_str
        );
        assert!(!outcome.production_verified, "custody is demo, not production: {}", outcome.trust_str);
        // The shipped chat button's acceptance condition, on a real completed run. This is the
        // regression guard for the defect described on `may_post_as_demonstration_verified`: a
        // command that gated on `production_verified` could never post, because the assertion on
        // the line above holds for EVERY run this module can produce.
        assert!(
            outcome.may_post_as_demonstration_verified(),
            "a chain-bound demonstration run must be postable: {}",
            outcome.trust_str
        );
        assert!(
            !(outcome.bound && outcome.production_verified),
            "gating a demonstration post on production_verified is unsatisfiable here — that is              the bug this assertion exists to keep fixed"
        );
    }

    #[test]
    fn produce_failure_fails_closed() {
        // If the executor closure fails (e.g. the model invocation errored), the turn must NOT commit.
        let dir = std::env::temp_dir().join(format!("brops-winlive-pfail-{}", brops_core::id()));
        let now = now();
        let r = in_process_turn_produce(&dir, now, || Err(()));
        let _ = std::fs::remove_dir_all(&dir);
        assert!(r.is_err(), "a failed produce must never yield a committed/verified turn");
    }
}
