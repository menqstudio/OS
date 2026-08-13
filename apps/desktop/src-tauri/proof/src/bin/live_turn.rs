//! Wave 3b — the LIVE production governed-turn driver (LINUX-RUN).
//!
//! This is the entry point that assembles ONE real governed turn end-to-end and prints a single
//! `RESULT: <trust_state> production_verified=<bool> bound=<bool>` line (or a closed `blocked` reason). It
//! wires the SAME [`brops_broker::chain_executor::linux::LinuxGovernedTurnChain`] the broker binary would
//! use — the real AF_UNIX challenge-authority / supervisor / isolated-signer hops + the real privileged
//! recorder → setuid launcher → executor spawn — over the deployment's `/opt/brops-live` provisioning.
//!
//! It NEVER fabricates a `trusted_verified`: the only path to a committed message is
//! `governed_verification::verify_and_accept` (driven inside `run_governed_turn`), and the production trust
//! verdict is `production_trust::resolve_trust_state` bound to the isolated-signer key the root-signed
//! manifest resolved AND that the envelope was cryptographically verified under AND the custody provenance
//! of the root anchor that verified the manifest. Any hop refusal, launcher/executor refusal,
//! signature/binding mismatch, manifest failure, or anti-rollback failure ⇒ `blocked`.
//!
//! The two printed booleans mean different things and neither is decoration. `production_verified` is the
//! core `TrustState::Production` verdict, which a demonstration- or kit-anchored root cannot reach at all.
//! `bound` is a delivery check: the committed row backing the reported projection was re-read here and its
//! body re-hashed against the envelope digest the row stores.
//!
//! Trust anchors (pinned root public key, the root-signed production key manifest, the anti-rollback floor,
//! and the broker's OWN `Expected` request facts) are read from `/opt/brops-live` — the broker's own side —
//! never from any hop reply. On a non-Linux host the socket + setuid model does not exist ⇒ exit non-zero.

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("live_turn: platform unsupported (Linux-only governed chain: AF_UNIX + setuid launcher)");
    std::process::exit(2);
}

#[cfg(target_os = "linux")]
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let config_path = match args.iter().position(|a| a == "--config").and_then(|i| args.get(i + 1)) {
        Some(p) => p.clone(),
        None => {
            eprintln!("live_turn: usage: live_turn --config <path>");
            std::process::exit(2);
        }
    };
    if args.iter().any(|a| a == "--verify-tcb") {
        std::process::exit(linux::verify_tcb(&config_path));
    }
    std::process::exit(linux::run(&config_path));
}

#[cfg(target_os = "linux")]
mod linux {
    use rusqlite::Connection;
    use serde_json::Value;
    use std::time::{SystemTime, UNIX_EPOCH};

    use brops_broker::chain_executor::linux::{
        ChainSockets, ExecutionConfig, LinuxGovernedExecution, LinuxGovernedTurnChain,
    };
    use brops_broker::chain_executor::{ChainExecutor, CustodyResolver, ResolvedTurn, TurnResolver};

    use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
    use brops_core::governed_message_store::verify_committed_binding;
    use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest, REQUEST_PROTOCOL};
    use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
    use brops_core::key_manifest::{
        check_and_advance, resolve_production_key, verify_manifest_anchored, AntiRollbackFloor,
        KeyManifest, PinnedRoot, RootAnchor, RootProvenance,
    };
    use brops_core::production_trust::{resolve_trust_state, verifying_key_hex, TrustState};

    // ------------------------------------------------------------------------------------------------
    // small helpers
    // ------------------------------------------------------------------------------------------------
    fn now_ms() -> i64 {
        SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
    }

    fn blocked(reason: &str) -> i32 {
        println!("RESULT: blocked reason={reason} production_verified=false bound=false");
        1
    }

    /// The §2.5 owner/mode floor for the root trust anchor file (audit **F-17**): a regular, root-owned
    /// file with no group/other write bit. The anchor is the one input whose forgery makes every
    /// downstream signature meaningless, so it gets the same treatment as the executor image and the
    /// lease — and it is checked on the OPENED fd, never by a `metadata(path)` re-lookup.
    fn anchor_file_is_tcb_owned(path: &str) -> Result<(), &'static str> {
        use std::os::unix::io::AsRawFd;
        let f = std::fs::File::open(path).map_err(|_| "unopenable")?;
        // SAFETY: `f` owns a live descriptor for the whole call; fstat gets a valid out-pointer.
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::fstat(f.as_raw_fd(), &mut st) } != 0 {
            return Err("unstatable");
        }
        if st.st_mode & libc::S_IFMT != libc::S_IFREG {
            return Err("not_regular");
        }
        if st.st_uid != 0 {
            return Err("not_root_owned");
        }
        if st.st_mode & 0o022 != 0 {
            return Err("writable");
        }
        Ok(())
    }

    /// This deployment's answer to "whose keys were these?", wired INTO the broker rather than
    /// computed after it.
    ///
    /// The driver used to call `resolve_trust_state` only once `run_governed_turn` had already
    /// returned — so the custody verdict was a line this binary printed, and the row the broker had
    /// just committed said `trusted_verified` regardless of what that line said. An independent
    /// audit found the consequence: no production path consulted custody at all. Now the same
    /// inputs go in before the turn runs, the broker stores the label this produces, and the line
    /// printed below is a report of what was committed rather than a second opinion about it.
    ///
    /// `resolve()` re-reads the clock every call because a manifest token has a validity window: an
    /// expired one must stop producing `Production` without anything having to notice and expire a
    /// cached verdict.
    struct LiveCustody {
        manifest: KeyManifest,
        verified_root: brops_core::key_manifest::VerifiedManifestRoot,
        signer_key_id: String,
        envelope_verifying_key_hex: String,
    }

    impl CustodyResolver for LiveCustody {
        fn resolve(&self) -> TrustState {
            resolve_trust_state(
                Some(&self.manifest),
                Some(&self.verified_root),
                &self.signer_key_id,
                RECEIPT_ENVELOPE_ARTIFACT_TYPE,
                now_ms(),
                &self.envelope_verifying_key_hex,
            )
        }
    }

    /// A handle the driver keeps while the broker owns one too. `Arc` alone cannot carry the impl —
    /// both `Arc` and the trait are foreign here — so the shared handle is a local newtype, which is
    /// also the clearer statement: exactly one resolver exists, and the RESULT line and the committed
    /// row are answers from that same object.
    struct SharedCustody(std::sync::Arc<LiveCustody>);

    impl CustodyResolver for SharedCustody {
        fn resolve(&self) -> TrustState {
            self.0.resolve()
        }
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

    fn s(v: &Value, path: &[&str]) -> Option<String> {
        let mut cur = v;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_str().map(|x| x.to_string())
    }
    fn i(v: &Value, path: &[&str]) -> Option<i64> {
        let mut cur = v;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_i64()
    }
    fn str_list(v: &Value, path: &[&str]) -> Option<Vec<String>> {
        let mut cur = v;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(str::to_string)).collect())
    }

    // A fixed resolver: the broker's OWN trusted per-turn resolution (pinned keys + Expected facts), read
    // from the root-signed manifest + the deployment config — NEVER from a hop reply.
    struct FixedResolver {
        resolved: ResolvedTurn,
    }
    impl TurnResolver for FixedResolver {
        fn resolve(&self, _r: &ValidatedRequest, _bt: &str, _n: &str) -> Result<ResolvedTurn, TurnReason> {
            Ok(self.resolved.clone())
        }
    }

    // Production broker-minted ids (fresh UUID v4 broker_turn_id + one-time request_nonce).
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

    /// Run the §2.5 TCB integrity floor over the deployment and nothing else (audit **F-10**).
    ///
    /// Deliberately a SEPARATE entry point run by root before any service starts, rather than a step
    /// inside the turn. The pinned set includes artifacts the serving principals must not be able to
    /// read — the setuid launcher is mode 4750 so only the recorder group may execute it, and the
    /// sudo allowlist lives in a root-only directory. A broker that could measure those could also
    /// read them, so asking it to would mean loosening the very containment the floor exists to
    /// confirm. Root can see the whole TCB; it is the only principal that can honestly evaluate it,
    /// and it does so once, at deployment time, before anything is started.
    pub fn verify_tcb(config_path: &str) -> i32 {
        let cfg: Value = match std::fs::read_to_string(config_path)
            .ok()
            .and_then(|raw| serde_json::from_str(&raw).ok())
        {
            Some(v) => v,
            None => {
                eprintln!("live_turn --verify-tcb: config unreadable or malformed");
                return 1;
            }
        };
        // The floor's question is whether any LOGIN or RUNTIME principal can write a TCB artifact.
        // Root evaluates it, so `getuid()` here is 0 and would be a meaningless "login uid" — the
        // deployment's real login user is passed in config, and the runtime uids are the service
        // accounts. Root itself is a TCB owner, not an untrusted principal.
        let runtime_uids: Vec<u32> = cfg
            .get("uids")
            .and_then(|v| v.as_object())
            .map(|m| m.values().filter_map(|v| v.as_u64().map(|u| u as u32)).collect())
            .unwrap_or_default();
        let login_uid = cfg
            .get("login_uid")
            .and_then(Value::as_u64)
            .map(|u| u as u32)
            .unwrap_or(u32::MAX);
        let mut principals = runtime_uids;
        if login_uid != u32::MAX && !principals.contains(&login_uid) {
            principals.push(login_uid);
        }
        match brops_broker::tcb_probe::verify_deployment_tcb(
            s(&cfg, &["trust", "tcb_pin_manifest_path"]).as_deref(),
            &principals,
            login_uid,
        ) {
            Ok(()) => {
                println!("RESULT: tcb_integrity_floor verified artifacts=pinned");
                0
            }
            Err(why) => {
                eprintln!("live_turn --verify-tcb: TCB integrity floor REFUSED: {why}");
                println!("RESULT: tcb_integrity_floor REFUSED {why}");
                1
            }
        }
    }

    pub fn run(config_path: &str) -> i32 {
        let now = now_ms();

        // ---- load the deployment config (the broker's own side) ----
        let raw = match std::fs::read_to_string(config_path) {
            Ok(r) => r,
            Err(_) => return blocked("config_unreadable"),
        };
        let cfg: Value = match serde_json::from_str(&raw) {
            Ok(v) => v,
            Err(_) => return blocked("config_malformed"),
        };

        // ---- (A) pin the root, verify the production key manifest, anti-rollback, resolve keys ----
        let manifest_path = match s(&cfg, &["trust", "manifest_path"]) {
            Some(p) => p,
            None => return blocked("config_missing_manifest_path"),
        };
        let manifest_sig_path = match s(&cfg, &["trust", "manifest_sig_path"]) {
            Some(p) => p,
            None => return blocked("config_missing_manifest_sig_path"),
        };
        let manifest_bytes = match std::fs::read_to_string(&manifest_path) {
            Ok(b) => b,
            Err(_) => return blocked("manifest_unreadable"),
        };
        let manifest: KeyManifest = match serde_json::from_str(&manifest_bytes) {
            Ok(m) => m,
            Err(_) => return blocked("manifest_malformed"),
        };
        let root_sig_b64 = match std::fs::read_to_string(&manifest_sig_path) {
            Ok(sig) => sig.trim().to_string(),
            Err(_) => return blocked("manifest_sig_unreadable"),
        };
        // ---- the root trust anchor (audit F-17) ----
        // `PinnedRoot` is documented as "provisioned in the TCB (root-owned), never taken from the
        // manifest itself" — but it used to be two strings in the same world-readable config the
        // provisioner wrote right after minting the root keypair and signing the manifest with it. The
        // verifier then checked a signature it had supplied both sides of, and reported that as
        // production. Two changes: the anchor is a separate TCB file under the §2.5 owner/mode floor,
        // and it STATES its provenance — a kit-generated anchor can exercise the whole chain but may
        // never render `production_verified=true`.
        if cfg.pointer("/trust/root_pub_hex").is_some() || cfg.pointer("/trust/root_key_id").is_some() {
            // Refused rather than ignored: silently preferring the file would leave the self-certifying
            // arrangement one config edit away from coming back.
            return blocked("config_carries_inline_root_anchor");
        }
        let anchor_path = match s(&cfg, &["trust", "root_anchor_path"]) {
            Some(p) => p,
            None => return blocked("config_missing_root_anchor_path"),
        };
        if let Err(why) = anchor_file_is_tcb_owned(&anchor_path) {
            return blocked(&format!("root_anchor_{why}"));
        }
        let anchor: Value = match std::fs::read_to_string(&anchor_path)
            .ok()
            .and_then(|b| serde_json::from_str(&b).ok())
        {
            Some(v) => v,
            None => return blocked("root_anchor_unreadable"),
        };
        // Provenance is now a TYPED, closed value, not a string the driver compares late. An unknown,
        // misspelled or absent `provenance` is refused outright rather than defaulting to "not
        // external": a deployment whose anchor file cannot say what its custody is has not answered the
        // question, and silently continuing would mean the answer never gets fixed.
        let anchor_provenance = match anchor
            .get("provenance")
            .and_then(Value::as_str)
            .and_then(RootProvenance::parse)
        {
            Some(p) => p,
            None => return blocked("root_anchor_provenance_unknown"),
        };
        let root_anchor = RootAnchor {
            pinned: PinnedRoot {
                root_key_id: anchor
                    .get("root_key_id")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                public_key_hex: anchor
                    .get("public_key_hex")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
            },
            provenance: anchor_provenance,
        };
        // `verify_manifest_anchored` (not `verify_manifest`) — it returns evidence of WHICH anchor the
        // signature verified under, and that evidence is what `resolve_trust_state` requires before it
        // will render production. The driver no longer decides the custody question itself.
        let verified_root = match verify_manifest_anchored(&manifest, &root_sig_b64, &root_anchor) {
            Ok(v) => v,
            Err(_) => return blocked("manifest_root_signature_invalid"),
        };

        // Anti-rollback: accept only an epoch at/above the durable floor (same-epoch requires the same hash).
        let floor_path = s(&cfg, &["trust", "floor_path"]).unwrap_or_default();
        let floor: AntiRollbackFloor = match std::fs::read_to_string(&floor_path)
            .ok()
            .and_then(|b| serde_json::from_str::<Value>(&b).ok())
            .and_then(|v| {
                Some(AntiRollbackFloor {
                    highest_epoch: v.get("highest_epoch")?.as_u64()?,
                    highest_hash: v.get("highest_hash")?.as_str()?.to_string(),
                })
            }) {
            Some(f) => f,
            None => return blocked("floor_unreadable"),
        };
        if check_and_advance(&floor, &manifest).is_err() {
            return blocked("anti_rollback");
        }

        let signer_key_id = s(&cfg, &["trust", "signer_key_id"]).unwrap_or_default();
        let sup_attest_key_id = s(&cfg, &["trust", "supervisor_attestation_key_id"]).unwrap_or_default();
        let iso = match resolve_production_key(&manifest, &signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now)
        {
            Ok(k) => k,
            Err(_) => return blocked("key_resolution"),
        };
        let sup_hex = match manifest.keys.iter().find(|k| k.key_id == sup_attest_key_id) {
            Some(k) => k.public_key_hex.clone(),
            None => return blocked("supervisor_attestation_key_missing"),
        };
        let iso_pub = match hex32(&iso.public_key_hex) {
            Some(b) => b,
            None => return blocked("signer_pubkey_malformed"),
        };
        let sup_pub = match hex32(&sup_hex) {
            Some(b) => b,
            None => return blocked("supervisor_pubkey_malformed"),
        };

        // ---- (B) the broker's OWN trusted Expected + create-pending facts ----
        let resolved = ResolvedTurn {
            isolated_signer_key_id: signer_key_id.clone(),
            isolated_signer_public_key: iso_pub,
            supervisor_attestation_key_id: sup_attest_key_id.clone(),
            supervisor_attestation_public_key: sup_pub,
            workspace_id: s(&cfg, &["resolved", "workspace_id"]).unwrap_or_default(),
            install_id: s(&cfg, &["resolved", "install_id"]).unwrap_or_default(),
            system_sha256: s(&cfg, &["resolved", "system_sha256"]).unwrap_or_default(),
            history_sha256: s(&cfg, &["resolved", "history_sha256"]).unwrap_or_default(),
            generation_config_sha256: s(&cfg, &["resolved", "generation_config_sha256"]).unwrap_or_default(),
            requested_at: s(&cfg, &["resolved", "requested_at"]).unwrap_or_default(),
            run_id: s(&cfg, &["resolved", "run_id"]).unwrap_or_default(),
            task_id: s(&cfg, &["resolved", "task_id"]).unwrap_or_default(),
            requested_at_ms: i(&cfg, &["resolved", "requested_at_ms"]).unwrap_or(0),
            author: s(&cfg, &["resolved", "author"]).unwrap_or_else(|| "Bro".to_string()),
        };

        // ---- (C) the live privileged-execution config (paths + fixed §4.9 facts) ----
        let sockets = ChainSockets {
            authority: match s(&cfg, &["sockets", "authority"]) {
                Some(x) => x,
                None => return blocked("config_missing_authority_sock"),
            },
            supervisor: match s(&cfg, &["sockets", "supervisor"]) {
                Some(x) => x,
                None => return blocked("config_missing_supervisor_sock"),
            },
            signer: match s(&cfg, &["sockets", "signer"]) {
                Some(x) => x,
                None => return blocked("config_missing_signer_sock"),
            },
        };
        let exec_cfg = ExecutionConfig {
            recorder_command: match str_list(&cfg, &["execution", "recorder_command"]) {
                Some(v) if !v.is_empty() => v,
                _ => return blocked("config_missing_recorder_command"),
            },
            recorder_store_dir: s(&cfg, &["execution", "recorder_store_dir"]).unwrap_or_default(),
            launcher_path: s(&cfg, &["execution", "launcher_path"]).unwrap_or_default(),
            executor_path: s(&cfg, &["execution", "executor_path"]).unwrap_or_default(),
            lease_file: s(&cfg, &["execution", "lease_file"]).unwrap_or_default(),
            cgroup_arg: s(&cfg, &["execution", "cgroup_arg"]).unwrap_or_else(|| "cgroup-live".to_string()),
            // `store_dir` is deliberately NOT read (rev-30 §2.3): the recorder publishes the
            // output + containment blobs into the protected store from its own root-owned policy,
            // and the broker identity this driver runs as is in neither `brops-store` nor any
            // owner, so it has no use for the path and must not be handed one.
            report_dir: s(&cfg, &["execution", "report_dir"]).unwrap_or_default(),
            supervisor_sock: sockets.supervisor.clone(),
            // F-01: `receipt_id` and the supervisor/executor/builder/policy identities are no
            // longer read here. They are the values the isolated signer allowlists, so a broker
            // that named them was choosing what it would be checked against; they now come from
            // the SUPERVISOR's own provisioning (`config.supervisor.*`) and never travel the wire.
            // F-02: measured by the recorder per run, not configured. Config supplies only the
            // recorder-owned directory holding its durable head-sequence counter.
            evidence_state_dir: s(&cfg, &["execution", "evidence_state_dir"]).unwrap_or_default(),
        };

        // ---- (D) run ONE governed turn through the real chain ----
        //
        // `db.path` (optional) selects a real database file. When it is set, the committed row AND the
        // §7.1(c)(d) acceptance ledger both live on disk and a replayed receipt/nonce is still refused
        // after this process exits. When it is ABSENT the driver falls back to an in-memory database:
        // the ledger below is still the durable implementation (never the in-memory one), but the store
        // underneath it is thrown away at exit, so the replay defence only covers THIS process. That is
        // audit IDX-82 and it is not silently papered over — the warning below says it out loud.
        let db_path = s(&cfg, &["db", "path"]);
        let conn = match &db_path {
            Some(p) => match Connection::open(p) {
                Ok(c) => c,
                Err(_) => return blocked("db_open"),
            },
            None => {
                eprintln!(
                    "live_turn: WARNING no [db].path configured — running on an in-memory database. \
                     The §7.1(c)(d) receipt-id/nonce replay ledger cannot outlive this process, so a \
                     receipt replayed by a LATER run would not be detected (audit IDX-82)."
                );
                match Connection::open_in_memory() {
                    Ok(c) => c,
                    Err(_) => return blocked("db_open"),
                }
            }
        };
        if let Err(e) = conn.busy_timeout(std::time::Duration::from_secs(5)) {
            eprintln!("live_turn: cannot arm DB busy timeout: {e}");
            return blocked("db_open");
        }
        if let Err(e) = init_schema(&conn) {
            eprintln!("live_turn: schema init failed: {e}");
            return blocked("db_schema");
        }

        // The DURABLE §7.1(c)(d) ledger (audit IDX-67 / IDX-86 / IDX-94). This driver used to pass
        // `InMemoryLedger::new()`, whose HashSets are gone the moment the process exits — so the
        // receipt-id uniqueness and one-time-nonce guarantees that the printed `production_verified=true`
        // rests on did not survive a restart. It now goes through the same SQLite-backed BEGIN IMMEDIATE
        // CAS the broker uses; with `db.path` set it is genuinely durable, without it the DB itself is
        // the ephemeral part (warned about above), not the ledger implementation.
        let ledger = match &db_path {
            Some(p) => brops_core::broker_turns::DurableAcceptanceLedger::open(p),
            None => Connection::open_in_memory()
                .map_err(brops_core::broker_turns::StoreError::Db)
                .and_then(brops_core::broker_turns::DurableAcceptanceLedger::from_connection),
        };
        let ledger = match ledger {
            Ok(l) => l,
            Err(e) => {
                eprintln!("live_turn: acceptance ledger unavailable: {e}");
                return blocked("db_ledger");
            }
        };

        let chain = LinuxGovernedTurnChain::new(
            sockets,
            FixedResolver { resolved: resolved.clone() },
            LinuxGovernedExecution::new(exec_cfg),
            ledger,
        );
        // F-29, in the type: the key handed to the custody resolver is the exact one the chain was
        // pinned to verify envelopes under — `resolved.isolated_signer_public_key` — not a second
        // manifest lookup, which would have made the guard compare a value against itself.
        let custody = std::sync::Arc::new(LiveCustody {
            manifest: manifest.clone(),
            verified_root: verified_root.clone(),
            signer_key_id: signer_key_id.clone(),
            envelope_verifying_key_hex: verifying_key_hex(&resolved.isolated_signer_public_key),
        });
        let executor = ChainExecutor::with_custody(chain, Box::new(SharedCustody(custody.clone())));

        let conversation_id =
            s(&cfg, &["resolved", "conversation_id"]).unwrap_or_else(|| "conv-live-1".to_string());
        let request = serde_json::json!({
            "protocol": REQUEST_PROTOCOL,
            "conversation_id": conversation_id,
            "agent": "Bro",
            "client_request_id": brops_core::id(),
        })
        .to_string();

        let result = run_governed_turn(&conn, &request, &UuidIds, &executor, now);

        // ---- (E) report: production trust is resolved ONLY after a real committed acceptance ----
        if result.status != "committed" {
            let reason = result.reason.map(|r| format!("{r:?}")).unwrap_or_else(|| "unknown".into());
            return blocked(&format!("chain:{reason}"));
        }
        let message = match result.message {
            Some(m) => m,
            None => return blocked("committed_without_message"),
        };
        // `bound` used to be `message.trust_state == TRUSTED_VERIFIED`. That could not be false:
        // `CommittedMessage::new` hardcodes `trust_state`, so every projection ever built carries
        // `trusted_verified` and the comparison was decoration printed next to a real verdict — the
        // most dangerous kind of decoration, because it reads like a check.
        //
        // What the driver can still genuinely ask, holding a projection, is whether that projection is
        // backed by the durable committed row and whether the body it is about to REPORT hashes to the
        // envelope digest that row stores. `verify_committed_binding` re-reads the row and recomputes
        // the digest; it is false for a rolled-back turn, a projection no commit produced, or bytes
        // substituted between `persist_committed` and here. It does NOT re-do the envelope signature or
        // the §7 output gates — those are `verify_and_accept`'s and are not repeatable from here.
        let bound = verify_committed_binding(&conn, &message).is_ok();

        // F-29: pass the key the CHAIN actually verified under — the exact bytes handed to
        // `verify_and_accept` as `PinnedKeys::isolated_signer_public_key` — not a second lookup of the
        // manifest, which made this guard compare a value against itself and never fail.
        //
        // F-17, moved into the type. The anchor's provenance used to be a string this driver compared
        // AFTER the core had already returned `TrustState::Production` — so the core type still said
        // "production" for a demonstration-rooted manifest, and every other consumer of that type had
        // to remember to re-apply the same string check. Now the anchor evidence goes IN and the
        // custody verdict comes OUT: a non-external anchor cannot produce a `Production` value at all.
        let ts = custody.resolve();
        let production_verified = ts.is_production_verified();
        // The report and the durable row must be the SAME verdict. `message.trust_state` is the
        // label re-read out of the committed row inside the commit transaction; if it disagrees
        // with what this resolver says now, something between the two is not what it claims and the
        // run is not a success no matter how the chain went.
        if Some(message.trust_state.as_str()) != ts.committed_label() {
            return blocked("custody_row_mismatch");
        }
        let ts_str = match &ts {
            TrustState::Production { key_id, key_epoch, root_key_id } => {
                format!("trusted_verified(production key={key_id} epoch={key_epoch} root={root_key_id})")
            }
            TrustState::DemonstrationCustody { key_id, key_epoch, root_key_id, root_provenance } => {
                format!(
                    "trusted_verified(demonstration_custody key={key_id} epoch={key_epoch} root={root_key_id} root_provenance={})",
                    root_provenance.as_str()
                )
            }
            TrustState::NoTrustedManifest(r) => format!("no_trusted_manifest({r})"),
        };
        println!(
            "RESULT: {ts_str} production_verified={production_verified} bound={bound} root_anchor={}",
            anchor_provenance.as_str()
        );
        // The RUN succeeded if the chain bound a trusted_verified turn under a manifest-resolved
        // production key. Whether that amounts to a PRODUCTION claim is the separate custody question
        // reported above — a kit-anchored run is a real, complete, honestly-labelled chain run, not a
        // failure, and conflating the two would either fail every CI run or relabel it as production.
        if bound && ts.is_chain_bound() {
            0
        } else {
            1
        }
    }
}
