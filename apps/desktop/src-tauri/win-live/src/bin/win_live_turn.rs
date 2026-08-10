//! The Windows LIVE governed-turn driver — assembles ONE real governed turn over named pipes and prints a
//! single `RESULT: <trust_state> production_verified=<bool> bound=<bool>` line. The Windows twin of
//! `proof/src/bin/live_turn.rs`: the SAME `brops_broker` chain + `run_governed_turn` + `verify_and_accept`,
//! but the transport is the named-pipe `WindowsHopConnector` (peer-SID authed at each server) and the
//! execution spawns the executor + drives the supervisor `attest-run` over its pipe. Trust anchors (pinned
//! root, root-signed manifest, anti-rollback floor, the broker's OWN Expected facts) come from the config —
//! never a hop reply. Any refusal / mismatch / manifest failure ⇒ `blocked`. Windows-only.

fn main() {
    #[cfg(not(windows))]
    {
        eprintln!("win_live_turn is Windows-only (named-pipe governed chain)");
        std::process::exit(2);
    }
    #[cfg(windows)]
    std::process::exit(win::run());
}

#[cfg(windows)]
mod win {
    use rusqlite::Connection;
    use serde_json::{json, Value};
    use std::time::{SystemTime, UNIX_EPOCH};

    use brops_broker::chain_executor::{ChainExecutor, ExecutionPlan, GovernedChain};

    use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
    use brops_core::governed_turn_ipc::{REQUEST_PROTOCOL, TRUSTED_VERIFIED};
    use brops_core::broker_turns::DurableAcceptanceLedger;
    use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
    use brops_core::key_manifest::{
        resolve_production_key, verify_manifest_anchored, KeyManifest, PinnedRoot, RootAnchor,
        RootProvenance,
    };
    use brops_broker::chain_executor::CustodyResolver;
    use brops_core::production_trust::{resolve_trust_state, verifying_key_hex, TrustState};

    /// This deployment's custody answer, wired into the broker. See the construction site for why it
    /// is an input to the turn rather than a comment on it.
    struct WinCustody {
        manifest: KeyManifest,
        verified_root: brops_core::key_manifest::VerifiedManifestRoot,
        signer_key_id: String,
        resolver: std::sync::Arc<ManifestResolver>,
    }

    impl CustodyResolver for WinCustody {
        fn resolve(&self) -> TrustState {
            // No key recorded ⇒ the chain never bound one ⇒ there is nothing to vouch for. Refuse
            // rather than fall back to the manifest, which would be answering with the key we HOPED
            // was used instead of the one that was.
            let verified_under = match self.resolver.last_verifying_key() {
                Some(k) => verifying_key_hex(&k),
                None => {
                    return TrustState::NoTrustedManifest("chain bound no envelope verifying key")
                }
            };
            resolve_trust_state(
                Some(&self.manifest),
                Some(&self.verified_root),
                &self.signer_key_id,
                RECEIPT_ENVELOPE_ARTIFACT_TYPE,
                now_ms(),
                &verified_under,
            )
        }
    }

    /// A handle the driver keeps while the broker owns one too. `Arc` alone cannot carry the impl —
    /// both `Arc` and the trait are foreign here — so the shared handle is a local newtype, which is
    /// also the clearer statement: exactly one resolver exists, and the RESULT line and the committed
    /// row are answers from that same object.
    struct SharedCustody(std::sync::Arc<WinCustody>);

    impl CustodyResolver for SharedCustody {
        fn resolve(&self) -> TrustState {
            self.0.resolve()
        }
    }

    use brops_win_live::config::Config;
    use brops_win_live::execution::{ExecutionParams, GovernedExecutionCore};
    use brops_win_live::pipe::{self, WindowsHopConnector};
    use brops_win_live::resolver::{ManifestResolver, ResolvedFacts, SharedResolver};
    use brops_win_live::tcb;

    fn now_ms() -> i64 {
        SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
    }
    fn blocked(reason: &str) -> i32 {
        println!("RESULT: blocked reason={reason} production_verified=false bound=false");
        1
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

    fn init_schema(conn: &Connection) -> Result<(), String> {
        brops_core::broker_turns::create_schema(conn).map_err(|e| format!("{e:?}"))?;
        brops_core::governed_message_store::create_schema(conn).map_err(|e| format!("{e}"))?;
        brops_core::supervisor_ledger::create_schema(conn).map_err(|e| format!("{e:?}"))?;
        Ok(())
    }

    fn arg(flag: &str) -> Option<String> {
        let a: Vec<String> = std::env::args().collect();
        a.iter().position(|x| x == flag).and_then(|i| a.get(i + 1)).cloned()
    }

    pub fn run() -> i32 {
        let now = now_ms();
        let cfg_path = match arg("--config") {
            Some(p) => p,
            None => {
                eprintln!("win_live_turn: --config required");
                return 2;
            }
        };
        let cfg = match Config::load(&cfg_path) {
            Ok(c) => c,
            Err(e) => return blocked(&format!("config:{e}")),
        };

        // ---- (0) §2.5 TCB integrity floor (audit R2) ----
        // Before ANY trust anchor is read. The manifest/floor/config this driver is about to pin its whole
        // verdict on are themselves pinned artifacts; if they or the four binaries have moved since the
        // deployment was measured, the turn is `blocked`, not `trusted_verified`. Fail-closed: an
        // unconfigured or unreadable pin manifest blocks too.
        if let Err(why) =
            brops_win_live::tcb_floor::verify_deployment_tcb(cfg.tcb_pin_manifest_path().as_deref())
        {
            eprintln!("win_live_turn: §2.5 TCB integrity floor not satisfied: {why}");
            return blocked("tcb_integrity_floor");
        }

        // ---- (A) pin root, verify manifest, anti-rollback, resolve keys ----
        let manifest_bytes = match std::fs::read_to_string(&cfg.trust.manifest_path) {
            Ok(b) => b,
            Err(_) => return blocked("manifest_unreadable"),
        };
        let manifest: KeyManifest = match serde_json::from_str(&manifest_bytes) {
            Ok(m) => m,
            Err(_) => return blocked("manifest_malformed"),
        };
        let root_sig = match std::fs::read_to_string(&cfg.trust.manifest_sig_path) {
            Ok(s) => s.trim().to_string(),
            Err(_) => return blocked("manifest_sig_unreadable"),
        };
        // Audit P1-a: pin the root from the TCB (crate::tcb), NEVER from config. A config-supplied root that
        // disagrees with the compiled-in anchor is refused (an adversary who writes config cannot swap root).
        let pinned_root = PinnedRoot {
            root_key_id: tcb::ROOT_KEY_ID.to_string(),
            public_key_hex: tcb::root_public_key_hex(),
        };
        if !cfg.trust.root_pub_hex.is_empty() && cfg.trust.root_pub_hex != pinned_root.public_key_hex {
            return blocked("config_root_disagrees_with_tcb");
        }
        // The anchor's CUSTODY provenance is the operator's declaration from provisioning. It is typed
        // and closed: absent, empty or misspelled is a REFUSAL, never a silent fall-back to `external`.
        // The key itself is still pinned by the TCB — provenance answers a different question (who could
        // have produced a manifest under this anchor), and no signature check can answer it.
        let anchor_provenance = match RootProvenance::parse(&cfg.trust.root_provenance) {
            Some(p) => p,
            None => return blocked("root_anchor_provenance_unknown"),
        };
        let root_anchor = RootAnchor { pinned: pinned_root.clone(), provenance: anchor_provenance };
        // `verify_manifest_anchored` (not `verify_manifest`): it returns the evidence of WHICH anchor the
        // signature verified under, and that evidence is what `resolve_trust_state` requires before it
        // will render a production verdict.
        let verified_root = match verify_manifest_anchored(&manifest, &root_sig, &root_anchor) {
            Ok(v) => v,
            Err(_) => return blocked("manifest_root_signature_invalid"),
        };
        // Load + TCB-integrity-verify the anti-rollback floor (audit R1): a reset/tampered floor.json is
        // rejected because floor.sig will not verify under the TCB floor key.
        let floor = match brops_win_live::resolver::load_verified_floor(std::path::Path::new(&cfg.trust.floor_path)) {
            Ok(f) => f,
            Err(e) => return blocked(&format!("floor:{e}")),
        };
        // Resolve the production key once for the final trust classification (the resolver re-resolves per
        // turn and is the enforcement path). A keep-alive clone of the manifest backs the classification.
        let manifest_for_trust = manifest.clone();
        // Kept as an EARLY fail-closed check that the production signer key resolves at all; the
        // production VERDICT no longer reads it (F-29 — it now uses the key the chain verified under).
        let _signer_pub_hex =
            match resolve_production_key(&manifest, &cfg.trust.signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now) {
                Ok(k) => k.public_key_hex,
                Err(_) => return blocked("key_resolution"),
            };
        if !manifest.keys.iter().any(|k| k.key_id == cfg.trust.supervisor_attestation_key_id) {
            return blocked("supervisor_attestation_key_missing");
        }

        // ---- (B) production manifest resolver (audit P1-b + P2): verify-manifest-vs-TCB + anti-rollback +
        //         PERSIST floor + resolve keys INSIDE the chain resolution, feeding the pinned keys that
        //         verify_and_accept verifies under. Replaces the inline "verify beside acceptance". ----
        let r = &cfg.resolved;
        let facts = ResolvedFacts {
            workspace_id: r.workspace_id.clone(),
            install_id: r.install_id.clone(),
            system_sha256: r.system_sha256.clone(),
            history_sha256: r.history_sha256.clone(),
            generation_config_sha256: r.generation_config_sha256.clone(),
            requested_at: r.requested_at.clone(),
            run_id: r.run_id.clone(),
            task_id: r.task_id.clone(),
            requested_at_ms: r.requested_at_ms,
            author: r.author.clone(),
        };
        let resolver = ManifestResolver::new(
            manifest,
            root_sig,
            floor,
            std::path::PathBuf::from(&cfg.trust.floor_path),
            cfg.trust.signer_key_id.clone(),
            cfg.trust.supervisor_attestation_key_id.clone(),
            facts,
        );

        // ---- (C) transport + execution ----
        let connector = WindowsHopConnector {
            authority_pipe: cfg.pipes.authority.clone(),
            supervisor_pipe: cfg.pipes.supervisor.clone(),
            signer_pipe: cfg.pipes.signer.clone(),
        };
        let executor_path = cfg.executor_path.clone();
        let produce = move |_plan: &ExecutionPlan| -> Result<Vec<u8>, ()> {
            let mut cmd = std::process::Command::new(&executor_path);
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW — no console flash on spawn
            }
            let out = cmd.output().map_err(|_| ())?;
            if !out.status.success() || out.stdout.is_empty() {
                return Err(());
            }
            Ok(out.stdout)
        };
        let sup_pipe = cfg.pipes.supervisor.clone();
        // One named-pipe hop per §5 lifecycle op (execution-started / complete-run / attest-run).
        let supervisor_op = move |req: &Value| -> Result<Value, ()> {
            let reply = pipe::hop_once(&sup_pipe, req)?;
            if reply.get("ok").and_then(Value::as_bool) == Some(true) {
                Ok(reply)
            } else {
                Err(())
            }
        };
        let params = ExecutionParams {
            store_dir: std::path::PathBuf::from(&cfg.store_dir),
            containment_mode: "windows-live-kit:spawned executor, session-0 containment proven separately"
                .to_string(),
            // F-02/F-01: the four `facts.evidence_*` deployment constants are gone. The execution
            // measures its own chain and the supervisor derives the head from it, so the evidence
            // head describes THIS run instead of naming the same value for every run of the kit.
            evidence_dir: std::path::PathBuf::from(&cfg.store_dir).join("run-evidence"),
            head_sequence: cfg.facts.evidence_head_sequence,
        };
        // IDX-19: this kit declares `windows-live-kit:` — it SPAWNS an executor — so the
        // execution must measure that image against the lease's `executor_executable_sha256`
        // before anything is reported or attested. Without this the core refuses
        // (`executor_image_unmeasured`), which is the honest state: the Windows twin had zero
        // comparison sites anywhere while the Linux launcher genuinely compared and fexecve'd
        // the fd it hashed.
        let exec = GovernedExecutionCore::new(params, produce, supervisor_op, now)
            .with_executor_image(std::path::PathBuf::from(&cfg.executor_path));

        // ---- (D) run ONE governed turn ----
        // Keep a handle to the SAME resolver the chain drives (F-29).
        let resolver_handle = std::sync::Arc::new(resolver);
        // The turn database is a real FILE now. A durable ledger over a store that vanishes is
        // not durable — it would give back exactly the weakness it exists to remove.
        let db_path = std::path::Path::new(&cfg.store_dir).join("win-live-turns.db");
        let ledger = match DurableAcceptanceLedger::open(&db_path.to_string_lossy()) {
            Ok(l) => l,
            Err(e) => {
                eprintln!("win_live_turn: replay ledger unavailable ({e:?}) — refusing");
                return 1;
            }
        };
        // (audit IDX-67/86/94) The replay defences — global receipt-id uniqueness and the
        // one-time nonce consume — were an `InMemoryLedger` here, which its own doc calls a
        // test double. They lived for the lifetime of a process, so the same signed receipt
        // and the same one-time nonce were accepted again after a restart. This is the
        // Windows PRODUCTION trusted_verified path, so it was the worst place for that.
        let chain = GovernedChain::new(connector, SharedResolver(resolver_handle.clone()), exec, ledger);
        // Custody goes IN, not on afterwards. This driver used to call `resolve_trust_state` only
        // after `run_governed_turn` returned, so the verdict was a line it printed while the row the
        // broker had already committed said `trusted_verified` regardless. The resolver below is the
        // one the broker consults to decide what to store, so the RESULT line and the durable row
        // are the same answer rather than two.
        //
        // F-29 survives the move: the key comes from `resolver_handle.last_verifying_key()` — what
        // the chain actually verified envelopes under — read lazily at resolve time, which is after
        // the chain has run and recorded it.
        let custody = std::sync::Arc::new(WinCustody {
            manifest: manifest_for_trust.clone(),
            verified_root: verified_root.clone(),
            signer_key_id: cfg.trust.signer_key_id.clone(),
            resolver: resolver_handle.clone(),
        });
        let executor = ChainExecutor::with_custody(chain, Box::new(SharedCustody(custody.clone())));

        let conn = match Connection::open(&db_path) {
            Ok(c) => c,
            Err(_) => return blocked("db_open"),
        };
        if init_schema(&conn).is_err() {
            return blocked("db_schema");
        }
        let request = json!({
            "protocol": REQUEST_PROTOCOL,
            "conversation_id": cfg.resolved.conversation_id,
            "agent": "Bro",
            "client_request_id": brops_core::id(),
        })
        .to_string();

        let result = run_governed_turn(&conn, &request, &UuidIds, &executor, now);
        if result.status != "committed" {
            let reason = result.reason.map(|r| format!("{r:?}")).unwrap_or_else(|| "unknown".into());
            return blocked(&format!("chain:{reason}"));
        }
        let message = match result.message {
            Some(m) => m,
            None => return blocked("committed_without_message"),
        };
        // `bound` used to be `message.trust_state == TRUSTED_VERIFIED`, which could not be false:
        // the projection hardcoded that string. It now re-reads the durable row and recomputes the
        // body digest against what the envelope committed to — false for a rolled-back turn, a
        // projection no commit produced, or bytes substituted after `persist_committed`.
        let bound = brops_core::governed_message_store::verify_committed_binding(&conn, &message).is_ok();

        let ts = custody.resolve();
        // The printed verdict and the committed row must agree. If they do not, something between
        // the commit and here is not what it claims, and no chain result makes that acceptable.
        if Some(message.trust_state.as_str()) != ts.committed_label() {
            return blocked("custody_row_mismatch");
        }
        let production_verified = ts.is_production_verified();
        let ts_str = match &ts {
            TrustState::Production { key_id, key_epoch, root_key_id } => {
                format!("trusted_verified(production key={key_id} epoch={key_epoch} root={root_key_id})")
            }
            TrustState::DemonstrationCustody { key_id, key_epoch, root_key_id, root_provenance } => {
                format!(
                    "trusted_verified(demonstration_custody key={key_id} epoch={key_epoch} \
                     root={root_key_id} root_provenance={})",
                    root_provenance.as_str()
                )
            }
            TrustState::NoTrustedManifest(r) => format!("no_trusted_manifest({r})"),
        };
        println!(
            "RESULT: {ts_str} production_verified={production_verified} bound={bound} root_anchor={}",
            anchor_provenance.as_str()
        );
        if production_verified && bound {
            0
        } else {
            1
        }
    }
}
