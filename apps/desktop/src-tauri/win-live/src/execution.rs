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
#[derive(Clone)]
pub struct ExecutionParams {
    pub store_dir: PathBuf,
    /// What containment this kit actually applied, named honestly in the per-run containment
    /// evidence (audit F-02). The Windows kit has no §2.7 setuid launcher: its cross-account
    /// session-0 containment is proven separately (win-live/proof/CROSS_ACCOUNT_PROOF.md), so the
    /// report must not imply the Linux model.
    pub containment_mode: String,
    /// Where this execution writes its per-run evidence chain (audit **F-02**/**F-01**). The
    /// four `evidence_*` deployment constants that used to live here are GONE: they made every
    /// receipt of the deployment name the same evidence head, so the supervisor's anti-rollback
    /// floor compared a constant against itself, and the remediation audit found the defect alive
    /// on this platform after it had been marked CLOSED on the strength of the Linux fix alone.
    ///
    /// In the cross-account deployment this directory belongs to the executor principal and the
    /// broker cannot write it, which is the property the Linux kit gets from the recorder's 0750
    /// state directory. In the in-process proof both sides are one process, so there it checks
    /// the SHAPE of the protocol, not containment — said plainly rather than left to be assumed.
    pub evidence_dir: PathBuf,
    /// The monotonic head sequence for this run. A deployment must advance it across runs or the
    /// supervisor's evidence floor has nothing to order; the caller owns that counter because
    /// only it knows how many governed turns this install has completed.
    pub head_sequence: i64,
}

/// Build the per-run evidence chain (audit **F-02**): hash-linked events describing what this
/// execution observed, then a head over them. The link is `previous_event_hash`, so dropping or
/// reordering an event changes every hash after it and the head stops matching — the property the
/// four constants could not have, because they described nothing.
///
/// Byte-compatible with the Linux recorder's `brops.run-evidence-chain.v1`, so ONE supervisor
/// implementation can derive the head on either platform.
pub fn build_run_evidence(
    attempt: &str,
    output_handle: &str,
    output_bytes: usize,
    head_sequence: i64,
) -> Vec<u8> {
    let mut previous: Option<String> = None;
    let mut events = Vec::new();
    for (sequence, event_type, payload) in [
        (1u64, "lease-validated", json!({ "execution_attempt_id": attempt })),
        (2, "execution-launched", json!({ "containment_mode": "win-live" })),
        (3, "output-captured", json!({
            "launcher_exit": 0,
            "output_bytes": output_bytes,
            "output_sha256": output_handle,
        })),
    ] {
        // serde_json's Map is a BTreeMap: `to_vec` emits sorted keys with compact separators, the
        // same canonical form the Python supervisor hashes.
        let payload_bytes = match serde_json::to_vec(&payload) {
            Ok(b) => b,
            Err(_) => return Vec::new(),
        };
        let event = json!({
            "event_type": event_type,
            "payload": payload,
            "payload_sha256": crypto::sha256_hex(&payload_bytes),
            "previous_event_hash": previous,
            "sequence": sequence,
        });
        let event_bytes = match serde_json::to_vec(&event) {
            Ok(b) => b,
            Err(_) => return Vec::new(),
        };
        previous = Some(crypto::sha256_hex(&event_bytes));
        events.push(event);
    }
    let doc = json!({
        "event_count": events.len(),
        "events": events,
        "final_event_hash": previous,
        "head_sequence": head_sequence,
        "last_sequence": events.len(),
        "protocol": "brops.run-evidence-chain.v1",
    });
    serde_json::to_vec(&doc).unwrap_or_default()
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

        // (2b) F-02: a per-run CONTAINMENT REPORT, content-addressed into the protected store. This
        //      replaces a provisioner stub whose handle every receipt of the deployment named, which
        //      made the isolated signer's §1.5 containment gate a check on a constant. It states only
        //      what this kit observed — including, in `containment_mode`, that this is NOT the Linux
        //      §2.7 recorder → setuid launcher → contained executor model.
        let containment = {
            let doc = json!({
                "protocol": "brops.containment-evidence.v1",
                "containment_mode": cfg.containment_mode,
                "execution_attempt_id": plan.lease.execution_attempt_id,
                "run_id": r.run_id,
                "output_handle": output_handle,
                "output_bytes": output.len(),
                "completed_at_ms": self.now_ms,
            });
            // serde_json's Map is a BTreeMap: sorted keys + compact separators, so identical facts
            // always content-address identically.
            serde_json::to_vec(&doc).map_err(|_| TurnReason::UpstreamBlocked)?
        };
        let containment_handle = crypto::sha256_hex(&containment);
        std::fs::write(cfg.store_dir.join(&containment_handle), &containment)
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

        // (3b) audit **F-02**, the half the remediation missed on THIS platform, and **F-01**:
        //      the four evidence values were `cfg.evidence_*` — deployment constants, so every
        //      receipt this kit ever produced named the same evidence head and the anti-rollback
        //      floor compared a constant against itself. They are gone. The execution now writes a
        //      hash-linked chain of what it observed, and the SUPERVISOR derives the head from it
        //      and refuses a completion whose `output_handle` is not the digest recorded here.
        //
        //      The chain is written to the executor's own evidence directory. In the cross-account
        //      deployment that directory belongs to the executor principal and the broker cannot
        //      write it, which is the property the Linux kit gets from the recorder's 0750 state
        //      dir. In the in-process proof both sides are one process, so this is a shape check
        //      there, not a containment proof — stated rather than implied.
        let evidence = build_run_evidence(
            &plan.lease.execution_attempt_id,
            &output_handle,
            output.len(),
            self.params.head_sequence,
        );
        std::fs::create_dir_all(&cfg.evidence_dir).map_err(|_| TurnReason::UpstreamBlocked)?;
        std::fs::write(
            cfg.evidence_dir.join(format!("{}.evidence.json", plan.lease.execution_attempt_id)),
            &evidence,
        )
        .map_err(|_| TurnReason::UpstreamBlocked)?;

        (self.supervisor)(&json!({
            "op": "complete-run",
            "execution_attempt_id": attempt,
            "produced": {
                "output_handle": output_handle,
                "containment_evidence_handle": containment_handle,
                // F-02: record/lease/execution-receipt handles are supervisor-derived now, and so
                // is the evidence head — it is read from the chain above, not sent from here.
                "completed_at_ms": now,
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
