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

use brops_broker::chain_executor::{ChainExecutor, ExecutionPlan, GovernedChain};
use brops_broker::chain_hops::{HopConn, HopError, Principal};

use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
use brops_core::governed_turn_ipc::{REQUEST_PROTOCOL, TRUSTED_VERIFIED};
use brops_core::governed_verification::{InMemoryLedger, RECEIPT_ENVELOPE_ARTIFACT_TYPE};
use brops_core::key_manifest::{
    check_and_advance, resolve_production_key, verify_manifest, AntiRollbackFloor, KeyManifest, PinnedRoot,
};
use brops_core::production_trust::{resolve_trust_state, TrustState};

use crate::crypto;
use crate::execution::{ExecutionParams, GovernedExecutionCore};
use crate::resolver::{ManifestResolver, ResolvedFacts};
use crate::servers::{
    Authority, AuthorityConfig, DispatchCore, Signer, SignerConfig, Supervisor, SupervisorConfig,
};
use crate::tcb;

pub struct ProofOutcome {
    pub production_verified: bool,
    pub bound: bool,
    pub trust_str: String,
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
    brops_core::governed_output_stream::create_schema(conn).map_err(|e| format!("{e}"))?;
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
    let containment_evidence_handle = seed(store_dir, b"brops-containment-evidence-v1");
    let record_handle = seed(store_dir, b"brops-record-v1");
    let lease_handle = seed(store_dir, b"brops-lease-v1");
    let execution_receipt_handle = seed(store_dir, b"brops-execution-receipt-v1");
    let evidence_final_event_hash = crypto::sha256_hex(b"brops-final-event-v1");
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
    let pinned_root = PinnedRoot {
        root_key_id: tcb::DEMO_ROOT_KEY_ID.to_string(),
        public_key_hex: tcb::demo_root_public_key_hex(),
    };
    verify_manifest(&manifest, &root_sig, &pinned_root).map_err(|e| format!("verify_manifest: {e:?}"))?;
    let floor = AntiRollbackFloor { highest_epoch: 2, highest_hash: manifest.content_hash() };
    check_and_advance(&floor, &manifest).map_err(|e| format!("anti_rollback: {e:?}"))?;
    // Keep-alive clone + resolved signer pubkey for the final trust classification (the resolver, below, is
    // the enforcement path that re-verifies the manifest + anti-rollback + resolves keys INSIDE the chain).
    let manifest_for_trust = manifest.clone();
    let signer_pub_hex = resolve_production_key(&manifest, &signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now_ms)
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
        containment_evidence_handle,
        record_handle,
        lease_handle,
        execution_receipt_handle,
        evidence_final_event_hash,
        evidence_event_count: 3,
        evidence_last_sequence: 3,
        evidence_head_sequence: 3,
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
        PinnedRoot {
            root_key_id: tcb::DEMO_ROOT_KEY_ID.to_string(),
            public_key_hex: tcb::demo_root_public_key_hex(),
        },
        manifest,
        root_sig,
        floor,
        store_dir.join("floor.json"),
        signer_key_id.clone(),
        sup_attest_key_id.clone(),
        facts,
    );

    let chain = GovernedChain::new(connector, resolver, exec, InMemoryLedger::new());
    let executor = ChainExecutor::new(chain);

    // ---- run ONE governed turn ----
    let conn = Connection::open_in_memory().map_err(|e| format!("db_open: {e}"))?;
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
    let bound = message.trust_state == TRUSTED_VERIFIED;

    let ts = resolve_trust_state(
        Some(&manifest_for_trust),
        &signer_key_id,
        RECEIPT_ENVELOPE_ARTIFACT_TYPE,
        now_ms,
        &signer_pub_hex,
    );
    let production_verified = ts.is_production_verified();
    let trust_str = match &ts {
        TrustState::Production { key_id, key_epoch } => {
            format!("trusted_verified(production key={key_id} epoch={key_epoch})")
        }
        TrustState::NoTrustedManifest(r) => format!("no_trusted_manifest({r})"),
    };
    Ok(ProofOutcome { production_verified, bound, trust_str })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn full_governed_turn_reaches_trusted_verified_in_process() {
        let dir = std::env::temp_dir().join(format!("brops-winlive-proof-{}", brops_core::id()));
        let now = 1_900_000_000_000i64; // a fixed, plausible wall clock
        let outcome = in_process_turn(&dir, now).expect("governed turn must commit");
        let _ = std::fs::remove_dir_all(&dir);
        assert!(outcome.bound, "committed body must be trusted_verified: {}", outcome.trust_str);
        assert!(
            outcome.production_verified,
            "production trust must resolve under the root-signed manifest: {}",
            outcome.trust_str
        );
    }

    #[test]
    fn live_output_is_signed_and_bound_by_the_chain() {
        // The live seam: an arbitrary reply (what a model produced) is what gets signed and bound —
        // trusted_verified is over the REAL answer, not a fixed demo string. (Custody is still demo.)
        let dir = std::env::temp_dir().join(format!("brops-winlive-live-{}", brops_core::id()));
        let now = 1_900_000_000_000i64;
        let reply = b"Bro: here is the verified live answer to your question.";
        let outcome = in_process_turn_output(&dir, now, reply).expect("live governed turn must commit");
        let _ = std::fs::remove_dir_all(&dir);
        assert!(outcome.bound, "the real reply bytes must be bound: {}", outcome.trust_str);
        assert!(outcome.production_verified, "chain must verify the live output: {}", outcome.trust_str);
    }

    #[test]
    fn empty_live_output_fails_closed() {
        let dir = std::env::temp_dir().join(format!("brops-winlive-empty-{}", brops_core::id()));
        let now = 1_900_000_000_000i64;
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
        let now = 1_900_000_000_000i64;
        let called = AtomicBool::new(false);
        let outcome = in_process_turn_produce(&dir, now, || {
            called.store(true, Ordering::SeqCst);
            Ok(b"Bro (produced inside the chain): the live answer.".to_vec())
        })
        .expect("a produce-driven governed turn must commit");
        let _ = std::fs::remove_dir_all(&dir);
        assert!(called.load(Ordering::SeqCst), "the chain must invoke produce during execution");
        assert!(
            outcome.bound && outcome.production_verified,
            "the reply produced inside the chain must be bound + verified: {}",
            outcome.trust_str
        );
    }

    #[test]
    fn produce_failure_fails_closed() {
        // If the executor closure fails (e.g. the model invocation errored), the turn must NOT commit.
        let dir = std::env::temp_dir().join(format!("brops-winlive-pfail-{}", brops_core::id()));
        let now = 1_900_000_000_000i64;
        let r = in_process_turn_produce(&dir, now, || Err(()));
        let _ = std::fs::remove_dir_all(&dir);
        assert!(r.is_err(), "a failed produce must never yield a committed/verified turn");
    }
}
