//! The reusable governed-execution core — the platform-independent half of the Linux `LinuxGovernedExecution`.
//!
//! Given the lease-authorized plan it: (1) obtains the executor's exact output bytes (via an injected
//! producer — a spawned executor on Windows, a fixed buffer in the in-process proof), (2) content-addresses
//! them into the isolated-signer's protected store so the signer RE-DERIVES `output_sha256`/`output_bytes`,
//! (3) builds the 28 §4.9 run facts, (4) drives the supervisor `attest-run` (via an injected attester — a
//! named-pipe hop on Windows, a direct core call in the proof), and (5) assembles the `sign-request`. It
//! returns exactly the [`ExecutionArtifacts`] the pure `GovernedChain` hands the isolated-signer + the final
//! `verify_and_accept`. It never fabricates output or an attestation — a producer/attester failure is a
//! closed `TurnReason`.

use brops_broker::chain_executor::{ExecutionArtifacts, ExecutionPlan, GovernedExecution};
use brops_core::governed_turn_ipc::TurnReason;
use serde_json::{json, Value};
use std::path::PathBuf;

use crate::crypto;

/// The store location + the §4.9 facts the RUN produces, which the execution reports once.
///
/// **F-01:** `receipt_id`, `supervisor_id`, `executor_id`, `builder_id`, `policy_id`,
/// `policy_version` and `policy_bundle_handle` are gone from here. They are the identities the
/// isolated signer allowlists, so the party being constrained was choosing the values it would be
/// checked against; they now live in the supervisor's own config. What remains is what only the
/// executing chain can know.
///
/// (Still deployment-static and tracked as audit **F-02**: the containment/record/execution-receipt
/// handles and the four evidence counters are constants rather than measurements of this run.)
#[derive(Clone)]
pub struct ExecutionParams {
    pub store_dir: PathBuf,
    pub containment_evidence_handle: String,
    pub evidence_final_event_hash: String,
    pub evidence_event_count: i64,
    pub evidence_last_sequence: i64,
    pub evidence_head_sequence: i64,
}

/// `produce`: run the executor, returning its EXACT reply bytes (or Err to fail closed).
/// `supervisor`: send one §5 lifecycle op to the supervisor, returning its success reply object or
/// Err. The execution drives `execution-started` → `complete-run` → `attest-run` through it.
pub struct GovernedExecutionCore<P, A>
where
    P: Fn(&ExecutionPlan) -> Result<Vec<u8>, ()>,
    A: Fn(&Value) -> Result<Value, ()>,
{
    params: ExecutionParams,
    produce: P,
    supervisor: A,
    now_ms: i64,
}

impl<P, A> GovernedExecutionCore<P, A>
where
    P: Fn(&ExecutionPlan) -> Result<Vec<u8>, ()>,
    A: Fn(&Value) -> Result<Value, ()>,
{
    pub fn new(params: ExecutionParams, produce: P, supervisor: A, now_ms: i64) -> Self {
        GovernedExecutionCore { params, produce, supervisor, now_ms }
    }
}

impl<P, A> GovernedExecution for GovernedExecutionCore<P, A>
where
    P: Fn(&ExecutionPlan) -> Result<Vec<u8>, ()>,
    A: Fn(&Value) -> Result<Value, ()>,
{
    fn execute(&self, plan: &ExecutionPlan) -> Result<ExecutionArtifacts, TurnReason> {
        let cfg = &self.params;
        let r = plan.resolved;

        // (1) Executor output (fail closed on refusal / empty).
        let output = (self.produce)(plan).map_err(|_| TurnReason::UpstreamBlocked)?;
        if output.is_empty() {
            return Err(TurnReason::UpstreamBlocked);
        }

        // (2) Content-address into the signer's protected store (<store>/<sha256hex>).
        let output_handle = crypto::sha256_hex(&output);
        std::fs::write(cfg.store_dir.join(&output_handle), &output)
            .map_err(|_| TurnReason::UpstreamBlocked)?;

        // (3) Tell the supervisor the run is up, then report ONLY what it produced. Every id, nonce
        //     and identity is deliberately absent: the supervisor holds those from the challenge it
        //     accepted, and supplying them here would re-open F-01 through a second door.
        let now = self.now_ms;
        let attempt = &plan.lease.execution_attempt_id;
        (self.supervisor)(&json!({
            "op": "execution-started",
            "execution_attempt_id": attempt,
            "process_group_id": std::process::id().to_string(),
            "cgroup_id": "win-live",
            "execution_started_marker": Value::Null,
        }))
        .map_err(|_| TurnReason::UpstreamBlocked)?;

        (self.supervisor)(&json!({
            "op": "complete-run",
            "execution_attempt_id": attempt,
            "produced": {
                "output_handle": output_handle,
                "containment_evidence_handle": cfg.containment_evidence_handle,
                // F-02: record/lease/execution-receipt handles are supervisor-derived now.
                "completed_at_ms": now,
                "evidence_final_event_hash": cfg.evidence_final_event_hash,
                "evidence_event_count": cfg.evidence_event_count,
                "evidence_last_sequence": cfg.evidence_last_sequence,
                "evidence_head_sequence": cfg.evidence_head_sequence,
            },
        }))
        .map_err(|_| TurnReason::UpstreamBlocked)?;

        // (4) Supervisor attest-run: it NAMES the run and the supervisor builds + signs the evidence
        //     from its OWN terminal record (it stamps decision=completed and JCS-signs those bytes).
        let attn = (self.supervisor)(&json!({
            "op": "attest-run",
            "run_id": r.run_id,
            "execution_attempt_id": attempt,
        }))
        .map_err(|_| TurnReason::UpstreamBlocked)?;
        let attestation = attn.get("attestation").cloned().ok_or(TurnReason::UpstreamBlocked)?;
        let evidence_jcs_b64 = attn
            .get("evidence_jcs_b64")
            .and_then(Value::as_str)
            .ok_or(TurnReason::UpstreamBlocked)?;
        let attestation_evidence_jcs = {
            use base64::engine::general_purpose::URL_SAFE_NO_PAD;
            use base64::Engine as _;
            URL_SAFE_NO_PAD.decode(evidence_jcs_b64.as_bytes()).map_err(|_| TurnReason::UpstreamBlocked)?
        };
        let attestation_signature_b64 = attestation
            .get("sig")
            .and_then(Value::as_str)
            .ok_or(TurnReason::UpstreamBlocked)?
            .to_string();

        // (5) sign-request = protocol + attestation + the evidence PARSED FROM the attested bytes.
        //     The execution no longer rebuilds the object, so what the signer validates is exactly
        //     what the supervisor signed — its re-hash and the final acceptance's
        //     attestation_evidence_sha256 check are over identical bytes by construction.
        let evidence: Value = serde_json::from_slice(&attestation_evidence_jcs)
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        if !evidence.is_object() {
            return Err(TurnReason::UpstreamBlocked);
        }
        let sign_request = json!({
            "protocol": "brops.sign-request.v1",
            "attestation": attestation,
            "evidence": evidence,
        });

        Ok(ExecutionArtifacts {
            output,
            sign_request,
            attestation_evidence_jcs,
            attestation_signature_b64,
        })
    }
}
