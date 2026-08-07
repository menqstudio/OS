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
use std::path::{Path, PathBuf};

use crate::crypto;
use crate::servers::{OBSERVATION_IN_DRIVER, OBSERVATION_UNOBSERVED_CHILD};

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

// ================================================================================================
// The executor image the lease pins (audit IDX-19)
// ================================================================================================

/// WHERE this kit's reply bytes come from, decoded from the kit's own declared `containment_mode`.
/// A CLOSED set: an unrecognised declaration is refused, never assumed benign.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProducerKind {
    /// The producer is a SEPARATE executable this kit spawns. The lease's
    /// `executor_executable_sha256` pins that image, so it has to be measured.
    SpawnedExecutor,
    /// The producer runs inside the driver process. There is no separate image to measure, and
    /// the run says so rather than implying one was checked.
    InDriverProcess,
}

/// PURE. Decode a declared `containment_mode` into what it claims about the producer.
///
/// This is what turns an existing free-text honesty note into a load-bearing claim: a kit that
/// declares it spawns an executor is held to measuring that executor, and a `containment_mode`
/// this function does not recognise fails the execution closed rather than defaulting to the
/// weaker of the two.
pub fn producer_kind(containment_mode: &str) -> Option<ProducerKind> {
    if containment_mode.starts_with("windows-live-kit:") {
        Some(ProducerKind::SpawnedExecutor)
    } else if containment_mode.starts_with("windows-proof-kit:") {
        Some(ProducerKind::InDriverProcess)
    } else {
        None
    }
}

/// What the containment evidence records when there is no separate executor image at all.
pub const IMAGE_BINDING_IN_PROCESS: &str = "none:producer-runs-in-driver-process";

/// PURE. Given what kind of producer this is, the digest the execution actually MEASURED off disk
/// (`None` = it measured nothing) and the digest the lease pins, decide what this execution may
/// honestly claim about the executor image.
///
/// **audit IDX-19.** `executor_executable_sha256` was signed into every lease and compared to
/// nothing, anywhere: the supervisor emitted it, the receipt attested it, and the driver spawned
/// whatever path its config named. `WIRING_LIVE_TRUST.md` stated the missing comparison as a
/// guarantee ("the supervisor refuses to launch it ... that refusal is the guarantee that the
/// signed output came from the exact, pinned executor image"). This is that comparison. A kit that
/// spawns an executor and cannot measure it is REFUSED, not waved through.
pub fn executor_image_binding(
    kind: ProducerKind,
    measured: Option<&str>,
    lease_pin: &str,
) -> Result<String, &'static str> {
    match kind {
        ProducerKind::InDriverProcess => Ok(IMAGE_BINDING_IN_PROCESS.to_string()),
        ProducerKind::SpawnedExecutor => {
            let measured = match measured {
                Some(m) => m,
                // No image was opened, so nothing here binds the pin. Refusing is the only honest
                // outcome: proceeding would attest a lease digest that constrained nothing.
                None => return Err("executor_image_unmeasured"),
            };
            if lease_pin.len() != 64
                || !lease_pin.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
            {
                return Err("lease_executor_pin_malformed");
            }
            if measured != lease_pin {
                return Err("executor_image_digest_mismatch");
            }
            Ok(format!("measured:{measured}"))
        }
    }
}

/// Measure an executor image off disk. `None` when it cannot be read — which
/// [`executor_image_binding`] turns into a refusal for a kit that spawns one.
fn measure_image(path: &Path) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    if bytes.is_empty() {
        return None;
    }
    Some(crypto::sha256_hex(&bytes))
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
    /// The executor image this execution will measure against the lease's
    /// `executor_executable_sha256` (audit **IDX-19**). `None` means it will measure nothing —
    /// which a kit declaring `windows-live-kit:` (a spawned executor) is REFUSED for.
    executor_image: Option<PathBuf>,
}

impl<P, A> GovernedExecutionCore<P, A>
where
    P: Fn(&ExecutionPlan) -> Result<Vec<u8>, ()>,
    A: Fn(&Value) -> Result<Value, ()>,
{
    pub fn new(params: ExecutionParams, produce: P, supervisor: A, now_ms: i64) -> Self {
        GovernedExecutionCore { params, produce, supervisor, now_ms, executor_image: None }
    }

    /// Bind the executable this kit spawns, so the execution can re-hash it and hold the lease's
    /// `executor_executable_sha256` pin to it (audit **IDX-19**). A kit that spawns an executor and
    /// never calls this refuses at execution time.
    pub fn with_executor_image(mut self, path: PathBuf) -> Self {
        self.executor_image = Some(path);
        self
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
        let attempt = &plan.lease.execution_attempt_id;

        // (0) audit **IDX-19** — the lease's `executor_executable_sha256` gets compared to
        //     something, BEFORE the run happens and therefore before anything about it is
        //     attested. A kit that spawns a separate executor must have opened that image and
        //     matched it; a kit whose producer runs in-process says so, and the statement lands in
        //     the per-run containment evidence the signed chain names.
        let kind = producer_kind(&cfg.containment_mode).ok_or(TurnReason::UpstreamBlocked)?;
        let measured = self.executor_image.as_deref().and_then(measure_image);
        let image_binding =
            executor_image_binding(kind, measured.as_deref(), &plan.lease.executor_executable_sha256)
                .map_err(|_| TurnReason::UpstreamBlocked)?;

        // (0b) audit **IDX-28 / IDX-91** — tell the supervisor the run is starting BEFORE it runs.
        //      This used to be sent after the executor had already exited, reporting the DRIVER's
        //      own pid, so the §5 `EXECUTING` state bracketed nothing and the receipt read as an
        //      account of a supervised child. It is reported at the right moment now, and the
        //      metadata says plainly what this kit can and cannot see: the producer spawns its
        //      executor internally (`Command::output()`), so no process handle ever reaches here
        //      and no process id is claimed. A supervisor refusal now stops the run before the
        //      executor is invoked at all.
        let observation = match kind {
            ProducerKind::SpawnedExecutor => OBSERVATION_UNOBSERVED_CHILD,
            ProducerKind::InDriverProcess => OBSERVATION_IN_DRIVER,
        };
        (self.supervisor)(&json!({
            "op": "execution-started",
            "execution_attempt_id": attempt,
            "process_observation": observation,
            "process_id": "",
            "execution_started_marker": Value::Null,
        }))
        .map_err(|_| TurnReason::UpstreamBlocked)?;

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
                // IDX-19: what this run can say about the image the lease pins — either
                // `measured:<digest>` (opened, hashed, equal to the pin) or a plain statement that
                // no separate image exists. It is recorded rather than implied, so a receipt
                // carrying an `executor_executable_sha256` also carries whether anything held it.
                "executor_image_binding": image_binding,
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

        // (3) Report ONLY what the run produced. Every id, nonce and identity is deliberately
        //     absent: the supervisor holds those from the challenge it accepted, and supplying them
        //     here would re-open F-01 through a second door. (The `execution-started` transition
        //     moved to step 0b — IDX-28: reporting a start after the executor exited was neither
        //     confirmed nor running.)
        let now = self.now_ms;

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

/// (audit **IDX-19**, **IDX-28/IDX-91**) These drive the real [`GovernedExecutionCore::execute`],
/// not just the pure helpers beside it — deleting the check at the call site fails them, which a
/// test of the decision function alone would not. Pure Rust + temp files, so the Linux CI runner
/// covers every one.
#[cfg(test)]
mod tests {
    use super::*;
    use brops_broker::chain_executor::{Lease, ResolvedTurn};
    use brops_core::governed_turn_ipc::ValidatedRequest;
    use std::sync::{Arc, Mutex};

    const LIVE_MODE: &str = "windows-live-kit:spawned executor, session-0 containment proven separately";
    const PROOF_MODE: &str = "windows-proof-kit:in-process, no setuid launcher";

    fn tmp(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("brops-winlive-exec-{tag}-{}", brops_core::id()));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn request() -> ValidatedRequest {
        ValidatedRequest::decode(
            &json!({
                "protocol": brops_core::governed_turn_ipc::REQUEST_PROTOCOL,
                "conversation_id": "conv-1",
                "agent": "Bro",
                "client_request_id": brops_core::id(),
            })
            .to_string(),
        )
        .expect("fixture request")
    }

    fn resolved() -> ResolvedTurn {
        ResolvedTurn {
            isolated_signer_key_id: "sk-1".into(),
            isolated_signer_public_key: [1u8; 32],
            supervisor_attestation_key_id: "ak-1".into(),
            supervisor_attestation_public_key: [2u8; 32],
            workspace_id: "ws-1".into(),
            install_id: "in-1".into(),
            system_sha256: "aa".repeat(32),
            history_sha256: "bb".repeat(32),
            generation_config_sha256: "cc".repeat(32),
            requested_at: "1700000000000".into(),
            run_id: "run-1".into(),
            task_id: "task-1".into(),
            requested_at_ms: 1_700_000_000_000,
            author: "Bro".into(),
        }
    }

    fn lease(executor_pin: &str) -> Lease {
        Lease {
            lease_id: "L-1".into(),
            execution_attempt_id: "EA-1".into(),
            lease_expires_at_ms: 1_700_000_210_000,
            launcher_executable_sha256: "11".repeat(32),
            executor_executable_sha256: executor_pin.into(),
            raw: json!({}),
        }
    }

    /// Run one `execute` against stub principals, returning `(result, op-log, store_dir)`.
    /// The log records every supervisor op AND the moment the producer ran, in order.
    fn run(
        containment_mode: &str,
        executor_pin: &str,
        image: Option<PathBuf>,
    ) -> (Result<ExecutionArtifacts, TurnReason>, Vec<String>, PathBuf) {
        let store = tmp("store");
        let log: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
        let plog = log.clone();
        let produce = move |_p: &ExecutionPlan| -> Result<Vec<u8>, ()> {
            plog.lock().unwrap().push("PRODUCE".into());
            Ok(b"the reply bytes".to_vec())
        };
        let slog = log.clone();
        let supervisor = move |req: &Value| -> Result<Value, ()> {
            let op = req.get("op").and_then(Value::as_str).unwrap_or("?").to_string();
            slog.lock().unwrap().push(op.clone());
            if op == "attest-run" {
                use base64::engine::general_purpose::URL_SAFE_NO_PAD;
                use base64::Engine as _;
                return Ok(json!({
                    "ok": true,
                    "attestation": { "supervisor_key_id": "ak-1", "sig": "c2ln" },
                    "evidence_jcs_b64": URL_SAFE_NO_PAD.encode(b"{}"),
                }));
            }
            Ok(json!({ "ok": true }))
        };
        let params = ExecutionParams {
            store_dir: store.clone(),
            containment_mode: containment_mode.to_string(),
            evidence_dir: store.join("run-evidence"),
            head_sequence: 1,
        };
        let mut core = GovernedExecutionCore::new(params, produce, supervisor, 1_700_000_050_000);
        if let Some(p) = image {
            core = core.with_executor_image(p);
        }
        let req = request();
        let res = resolved();
        let l = lease(executor_pin);
        let plan = ExecutionPlan {
            req: &req,
            broker_turn_id: "bt-1",
            request_nonce: "nonce-1",
            resolved: &res,
            lease: &l,
        };
        let out = core.execute(&plan);
        let ops = log.lock().unwrap().clone();
        (out, ops, store)
    }

    /// The one containment-evidence document `execute` published into `store`.
    fn containment_doc(store: &std::path::Path) -> Value {
        std::fs::read_dir(store)
            .unwrap()
            .flatten()
            .filter_map(|e| std::fs::read(e.path()).ok())
            .filter_map(|b| serde_json::from_slice::<Value>(&b).ok())
            .find(|v| {
                v.get("protocol").and_then(Value::as_str) == Some("brops.containment-evidence.v1")
            })
            .expect("a containment evidence document")
    }

    // ---- IDX-28 / IDX-91: the start is reported at the start -----------------------------------

    #[test]
    fn the_start_is_reported_before_the_producer_runs() {
        let (out, ops, store) = run(PROOF_MODE, &"22".repeat(32), None);
        assert!(out.is_ok(), "in-process kit must still run");
        // THE CHECK. `execution-started` used to be sent AFTER the executor had exited, so the §5
        // machine's EXECUTING state bracketed nothing at all. Move it back and this fails.
        assert_eq!(
            ops,
            vec!["execution-started", "PRODUCE", "complete-run", "attest-run"],
            "the §5 start transition must bracket the execution, not trail it"
        );
        let _ = std::fs::remove_dir_all(&store);
    }

    #[test]
    fn a_supervisor_that_refuses_the_start_stops_the_run_before_it_happens() {
        // Corollary of the ordering: an unrecorded execution must not run to completion behind the
        // supervisor's back. Only reachable because the report now precedes the producer.
        let store = tmp("store");
        let ran = Arc::new(Mutex::new(false));
        let r = ran.clone();
        let produce = move |_p: &ExecutionPlan| -> Result<Vec<u8>, ()> {
            *r.lock().unwrap() = true;
            Ok(b"reply".to_vec())
        };
        let supervisor = |_req: &Value| -> Result<Value, ()> { Err(()) };
        let params = ExecutionParams {
            store_dir: store.clone(),
            containment_mode: PROOF_MODE.to_string(),
            evidence_dir: store.join("run-evidence"),
            head_sequence: 1,
        };
        let core = GovernedExecutionCore::new(params, produce, supervisor, 1_700_000_050_000);
        let req = request();
        let res = resolved();
        let l = lease(&"22".repeat(32));
        let plan = ExecutionPlan {
            req: &req,
            broker_turn_id: "bt-1",
            request_nonce: "nonce-1",
            resolved: &res,
            lease: &l,
        };
        assert!(core.execute(&plan).is_err());
        assert!(!*ran.lock().unwrap(), "the executor ran after the supervisor refused the start");
        let _ = std::fs::remove_dir_all(&store);
    }

    // ---- IDX-19: the lease's executor pin is compared to something -----------------------------

    #[test]
    fn a_kit_that_spawns_an_executor_must_measure_it_against_the_lease_pin() {
        let image_dir = tmp("image");
        let image = image_dir.join("win_executor.exe");
        std::fs::write(&image, b"executor image bytes v1").unwrap();
        let real = crypto::sha256_hex(b"executor image bytes v1");

        // Matches the pin → the run proceeds and the binding is RECORDED, not implied.
        let (ok, _, store) = run(LIVE_MODE, &real, Some(image.clone()));
        assert!(ok.is_ok(), "a measured image equal to the lease pin must be accepted");
        assert_eq!(
            containment_doc(&store)["executor_image_binding"],
            json!(format!("measured:{real}"))
        );
        let _ = std::fs::remove_dir_all(&store);

        // THE CHECK. The lease pins some other image — exactly the case the docs claimed the
        // supervisor "refuses to launch" and nothing anywhere compared.
        let (mismatch, ops, store) = run(LIVE_MODE, &"22".repeat(32), Some(image.clone()));
        assert!(mismatch.is_err(), "a lease pin naming a different image must refuse");
        assert!(ops.is_empty(), "nothing may be reported for a run that must not happen");
        let _ = std::fs::remove_dir_all(&store);

        // A spawning kit that opened no image at all measured nothing, so nothing binds the pin.
        let (unmeasured, _, store) = run(LIVE_MODE, &real, None);
        assert!(unmeasured.is_err(), "a spawning kit that measures nothing must refuse");
        let _ = std::fs::remove_dir_all(&store);

        // An unreadable image is a refusal, never a skipped check.
        let (gone, _, store) = run(LIVE_MODE, &real, Some(image_dir.join("absent.exe")));
        assert!(gone.is_err());
        let _ = std::fs::remove_dir_all(&store);
        let _ = std::fs::remove_dir_all(&image_dir);
    }

    #[test]
    fn an_unrecognised_containment_mode_fails_closed() {
        // The declaration is load-bearing now, so it is a closed set: a kit whose containment_mode
        // this code cannot decode does not get the weaker of the two readings by default.
        for mode in ["", "win-live", "linux-live-kit:whatever", "spawned executor"] {
            let (out, ops, store) = run(mode, &"22".repeat(32), None);
            assert!(out.is_err(), "{mode}");
            assert!(ops.is_empty(), "{mode}");
            let _ = std::fs::remove_dir_all(&store);
        }
        assert_eq!(producer_kind(LIVE_MODE), Some(ProducerKind::SpawnedExecutor));
        assert_eq!(producer_kind(PROOF_MODE), Some(ProducerKind::InDriverProcess));
        assert_eq!(producer_kind("anything else"), None);
    }

    #[test]
    fn the_in_process_kit_says_it_measured_nothing_rather_than_implying_it_did() {
        let (out, _, store) = run(PROOF_MODE, &"22".repeat(32), None);
        assert!(out.is_ok());
        assert_eq!(
            containment_doc(&store)["executor_image_binding"],
            json!(IMAGE_BINDING_IN_PROCESS),
            "a kit with no separate executor must say so in the evidence the chain names"
        );
        let _ = std::fs::remove_dir_all(&store);
    }

    #[test]
    fn the_image_binding_decision_is_pure_and_closed() {
        let pin = "ab".repeat(32);
        assert_eq!(
            executor_image_binding(ProducerKind::SpawnedExecutor, Some(&pin), &pin),
            Ok(format!("measured:{pin}"))
        );
        assert_eq!(
            executor_image_binding(ProducerKind::SpawnedExecutor, Some(&"cd".repeat(32)), &pin),
            Err("executor_image_digest_mismatch")
        );
        assert_eq!(
            executor_image_binding(ProducerKind::SpawnedExecutor, None, &pin),
            Err("executor_image_unmeasured")
        );
        // A pin that is not a digest cannot be satisfied by any measurement.
        for bad in ["", "not-hex", &"AB".repeat(32), &"ab".repeat(31)] {
            assert_eq!(
                executor_image_binding(ProducerKind::SpawnedExecutor, Some(bad), bad),
                Err("lease_executor_pin_malformed"),
                "{bad}"
            );
        }
        assert_eq!(
            executor_image_binding(ProducerKind::InDriverProcess, None, &pin),
            Ok(IMAGE_BINDING_IN_PROCESS.to_string())
        );
    }
}
