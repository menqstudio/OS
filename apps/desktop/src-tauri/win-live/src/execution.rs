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

/// The deployment-static §4.9 facts + store location the execution needs beyond the per-turn plan.
#[derive(Clone)]
pub struct ExecutionParams {
    pub store_dir: PathBuf,
    pub receipt_id: String,
    pub supervisor_id: String,
    pub executor_id: String,
    pub builder_id: String,
    pub policy_id: String,
    pub policy_version: String,
    pub policy_bundle_handle: String,
    pub containment_evidence_handle: String,
    pub record_handle: String,
    pub lease_handle: String,
    pub execution_receipt_handle: String,
    pub evidence_final_event_hash: String,
    pub evidence_event_count: i64,
    pub evidence_last_sequence: i64,
    pub evidence_head_sequence: i64,
}

/// `produce`: run the executor, returning its EXACT reply bytes (or Err to fail closed).
/// `attest`: send the 28-field facts to the supervisor `attest-run`, returning its success reply object
/// (`{attestation, evidence_jcs_b64, attestation_evidence_sha256}`) or Err.
pub struct GovernedExecutionCore<P, A>
where
    P: Fn(&ExecutionPlan) -> Result<Vec<u8>, ()>,
    A: Fn(&Value) -> Result<Value, ()>,
{
    params: ExecutionParams,
    produce: P,
    attest: A,
    now_ms: i64,
}

impl<P, A> GovernedExecutionCore<P, A>
where
    P: Fn(&ExecutionPlan) -> Result<Vec<u8>, ()>,
    A: Fn(&Value) -> Result<Value, ()>,
{
    pub fn new(params: ExecutionParams, produce: P, attest: A, now_ms: i64) -> Self {
        GovernedExecutionCore { params, produce, attest, now_ms }
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

        // (3) The 28 §4.9 run facts (mirrors LinuxGovernedExecution exactly). system/history/generation
        //     handles ARE the broker's resolved component digests (a content address == its sha256).
        let now = self.now_ms;
        let facts = json!({
            "run_id": r.run_id,
            "execution_attempt_id": plan.lease.execution_attempt_id,
            "task_id": r.task_id,
            "request_nonce": plan.request_nonce,
            "receipt_id": cfg.receipt_id,
            "workspace_id": r.workspace_id,
            "install_id": r.install_id,
            "supervisor_id": cfg.supervisor_id,
            "executor_id": cfg.executor_id,
            "builder_id": cfg.builder_id,
            "policy_id": cfg.policy_id,
            "policy_version": cfg.policy_version,
            "policy_bundle_handle": cfg.policy_bundle_handle,
            "generation_config_handle": r.generation_config_sha256,
            "system_handle": r.system_sha256,
            "history_handle": r.history_sha256,
            "output_handle": output_handle,
            "containment_evidence_handle": cfg.containment_evidence_handle,
            "record_handle": cfg.record_handle,
            "lease_handle": cfg.lease_handle,
            "execution_receipt_handle": cfg.execution_receipt_handle,
            "evidence_final_event_hash": cfg.evidence_final_event_hash,
            "requested_at": r.requested_at_ms,
            "completed_at": now,
            "challenge_accepted_at_ms": now,
            "evidence_event_count": cfg.evidence_event_count,
            "evidence_last_sequence": cfg.evidence_last_sequence,
            "evidence_head_sequence": cfg.evidence_head_sequence,
        });

        // (4) Supervisor attest-run (it stamps decision=completed, JCS-signs the evidence).
        let attn = (self.attest)(&facts).map_err(|_| TurnReason::UpstreamBlocked)?;
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

        // (5) sign-request = protocol + attestation + evidence (facts + supervisor-stamped decision). The
        //     signer's own JCS(evidence) is byte-identical to what the supervisor attested.
        let mut evidence = facts;
        evidence
            .as_object_mut()
            .ok_or(TurnReason::UpstreamBlocked)?
            .insert("decision".to_string(), Value::String("completed".to_string()));
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
