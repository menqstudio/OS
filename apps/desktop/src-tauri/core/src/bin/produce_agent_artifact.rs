//! Produce the evidence `tools/check_produced_artifact.py` measures, from the
//! real code path — not from a fixture.
//!
//! This binary builds one agent bundle, registers it, lets `repo::automations::
//! run_due` detect it and enqueue a run, claims that run, executes it, and writes
//! the run row and the receipt out as JSONL. Everything it emits is a byproduct
//! of the same functions the desktop calls; nothing here fabricates a row.
//!
//! It writes under a target directory that is NOT tracked in git, because a
//! committed store is a fixture and the gate refuses one.
//!
//!     cargo run -p brops-core --bin produce_agent_artifact -- <out_dir>

use std::path::PathBuf;

use brops_core::agent_bundle::{BuildSpec, Requires, Step, StepKind};
use brops_core::{db, repo};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let out = PathBuf::from(
        std::env::args().nth(1).unwrap_or_else(|| "target/produced-artifact".to_string()),
    );
    let store = out.join("agents");
    std::fs::create_dir_all(&store)?;

    let now_ms: i64 = 1_756_600_000_000;
    let spec = BuildSpec {
        bundle_id: "agt-invoice-chaser".into(),
        bundle_version: 1,
        display_name: "Invoice chaser".into(),
        built_for: "customer-demo".into(),
        built_at_epoch: now_ms / 1000,
        // The grant outlives this build by a week and no longer. An expiry the
        // scheduler refuses to fire past is the point; a grant with no expiry is
        // a grant nobody ever has to look at again.
        grant_expires_at_epoch: now_ms / 1000 + 7 * 24 * 3600,
        // This agent may not leave the box. Stated, not omitted.
        egress: vec![],
        steps: vec![
            Step {
                id: "summarise".into(),
                kind: StepKind::Store,
                verb: Some("knowledge_note".into()),
                argument: Some("read the local invoice list and write what is overdue".into()),
                call_ref: None,
                requires: Requires {
                    capabilities: vec!["READ_LOCAL".into(), "WRITE_LOCAL".into()],
                    credential_slots: vec![],
                },
                next: Some("record".into()),
            },
            Step {
                id: "record".into(),
                kind: StepKind::Store,
                verb: Some("knowledge_note".into()),
                argument: Some("record that the chase ran".into()),
                call_ref: None,
                requires: Requires {
                    capabilities: vec!["WRITE_LOCAL".into()],
                    credential_slots: vec![],
                },
                next: None,
            },
        ],
    };

    let digest = brops_core::agent_bundle::build(&store, &spec)
        .map_err(|r| format!("build refused: {}", r.as_str()))?;

    // The same in-process database the desktop opens, migrated the same way.
    let db_path = out.join("produced.sqlite3");
    let conn = db::open(&db_path.to_string_lossy())?;
    repo::agent_runs::register(&conn, &digest, &spec.bundle_id, 1, &spec.display_name, 60_000)?;

    // The scheduler's own entry point. `run_due` is what the 60s tick calls, and
    // it is what writes the run row: nothing here inserts one by hand.
    std::env::set_var("BROPS_AGENT_STORE", &store);
    let _ = repo::automations::run_due(&conn, now_ms)?;

    let run_id = repo::agent_runs::claim_and_run(&conn, &store, "producer", now_ms)?
        .ok_or("no queued run was claimed -- run_due enqueued nothing")?;

    // Export the two JSONL files the gate reads. These are SELECTs over what the
    // code above wrote; the shape is a projection, not a second source of truth.
    let mut runs = String::new();
    {
        let mut st = conn.prepare(
            "SELECT id, bundle_id, bundle_digest, invoked_by, state, refusal_reason FROM flow_runs",
        )?;
        let rows = st.query_map([], |r| {
            Ok(serde_json::json!({
                "run_id": r.get::<_, String>(0)?,
                // `artifact_id` is the AGENT's identity, which is what a run
                // references and what the manifest declares; the digest is the
                // version and travels beside it, never instead of it.
                "artifact_id": r.get::<_, String>(1)?,
                "bundle_digest": r.get::<_, String>(2)?,
                "invoked_by": r.get::<_, String>(3)?,
                "state": r.get::<_, String>(4)?,
                "refusal_reason": r.get::<_, Option<String>>(5)?,
            }))
        })?;
        for row in rows {
            runs.push_str(&row?.to_string());
            runs.push('\n');
        }
    }
    std::fs::write(out.join("runs.jsonl"), runs)?;

    let mut receipts = String::new();
    {
        let mut st = conn.prepare(
            "SELECT run_id, bundle_digest, enforcement_regime, steps_run, touched, outcome \
             FROM flow_receipts",
        )?;
        let rows = st.query_map([], |r| {
            Ok(serde_json::json!({
                "run_id": r.get::<_, String>(0)?,
                "bundle_digest": r.get::<_, String>(1)?,
                "enforcement_regime": r.get::<_, String>(2)?,
                "steps_run": r.get::<_, i64>(3)?,
                "touched": serde_json::from_str::<serde_json::Value>(&r.get::<_, String>(4)?)
                    .unwrap_or(serde_json::Value::Null),
                "outcome": r.get::<_, String>(5)?,
            }))
        })?;
        for row in rows {
            receipts.push_str(&row?.to_string());
            receipts.push('\n');
        }
    }
    std::fs::write(out.join("receipts.jsonl"), receipts)?;

    println!("bundle  {digest}");
    println!("run     {run_id}");
    println!("store   {}", store.display());
    Ok(())
}
