//! Wave 3b — drive the REAL [`brops_broker::ladder_executor::LadderChain`] end to end on the live kit.
//!
//! # WHAT THIS IS
//!
//! A driver that builds the same §4.10(g) ladder object `brops-broker`'s `build_governed_executor`
//! builds — the same `LadderChain`, the same `LinuxHopConnector`, the same `SqliteTurnContent`, the
//! same `GovernedSidecar::as_distinct_principal`, the same `UuidTurnIds`, the same
//! `DurableAcceptanceLedger` — and runs one turn through
//! [`brops_core::broker_orchestrator::run_governed_turn`]. Every hop, every digest, every signature
//! and every §7.1 check is library code the shipped product would call. This binary re-implements
//! none of them.
//!
//! # WHAT THIS IS **NOT**, stated first because the substitution has been made before
//!
//! **It is not the `brops-broker` binary, and it must never be cited as one.** The differences are
//! not cosmetic and each one is here because the binary genuinely cannot be driven in CI:
//!
//!  * `build_governed_executor` is not called, and cannot be. It reaches only
//!    `ProductionResolver::provisioned`, which hard-pins the Owner's offline root
//!    `brops-tcb-root-1` / `3c83c2bc…`; the one constructor that accepts another anchor is
//!    `pub(crate)` IN THE LIBRARY, so no binary outside `brops-broker` can reach it (measured:
//!    `error[E0624]`). Satisfying it in CI would mean an Owner ceremony with the offline key on
//!    every run, or committing the production signer's private half — which would make forging a
//!    production-class §4.9 envelope trivial against every shipped install. This driver therefore
//!    supplies its OWN `KeyResolver` over the kit's TCB root-anchor file, carrying that file's
//!    DECLARED provenance. That is honest for exactly one reason, and it is the same reason
//!    `proof/src/bin/live_turn.rs` is honest: **a `kit_generated` anchor may never render
//!    `production_verified=true`** — `production_trust::resolve_trust_state` will not build a
//!    `TrustState::Production` from it, so this driver cannot report production custody no matter
//!    what it prints.
//!  * There is no renderer socket, no `SO_PEERCRED` on a renderer→broker hop, and no `handle_conn`.
//!    The request is constructed in-process. The peer-authentication boundary the broker binary
//!    enforces on ITS front door is not exercised here at all.
//!  * `persist_committed` still runs (it is inside `run_governed_turn`), but the custody resolver
//!    that lets it commit is wired HERE, by this driver, with `ChainExecutor::with_custody`. The
//!    shipped broker calls `ChainExecutor::new` and therefore commits nothing. **That difference is
//!    deliberate and this driver does not change it**: nothing in this file touches
//!    `build_governed_executor`, `UpstreamBlockedExecutor`, `connect_broker` or
//!    `governed_verification_unconfigured`, and nothing here makes any of them reachable.
//!  * `$BROPS_BROKER_CONFIG` is NOT read. The deployment config arrives as `--config`, so no
//!    environment this driver runs under can be confused with the one that arms the broker.
//!  * The §2.5 TCB integrity floor is NOT evaluated. `build_tcb_pin_manifest.py` binds
//!    `bin/live_turn` to the `trusted-verifier-broker.bin` role through a hardcoded map, so a
//!    manifest built for this kit would measure files that are not the ones serving this turn —
//!    the same reason `run_ladder_turn.sh` states the floor's absence rather than implying
//!    coverage. A floor that pins the wrong artifact is worse than no floor.
//!
//! # The two recorders, and why neither is a change to the chain
//!
//! `RecordingHops` and `RecordingTransport` wrap the real connector and the real transport. Each
//! forwards its argument verbatim and returns its inner result verbatim; neither inspects, retries,
//! rewrites or substitutes anything. They exist because the chain deliberately collapses every
//! refusal to `TurnReason::UpstreamBlocked` (`HopError::to_turn_reason` and `SubmitError`'s mapping
//! both do), so without them a RED run could not say WHICH party refused, and the evidence bundle
//! could not carry the frames. The named refusal this driver prints is therefore read out of the
//! peer's OWN reply, never invented.
//!
//! # It must be able to fail, and `--expect` is how
//!
//! `--expect` is mandatory and compared BY NAME. A run that commits when a refusal was expected
//! exits non-zero, and so does a run refused with the wrong name. `run_ladder_turn.sh` drives both
//! directions of that comparison on every invocation, because both of this repository's PowerShell
//! harnesses shipped checks that could not report PASS at all, through three audit rounds.
//!
//! ```text
//! ladder_turn --config /opt/brops-live/tcb/ladder-driver.json \
//!             --evidence-dir /opt/brops-live/ladder/driver/positive \
//!             --expect committed
//! ```

#[cfg(not(target_os = "linux"))]
fn main() {
    // AF_UNIX + SO_PEERCRED + the seven service accounts + the setuid launcher do not exist off
    // Linux, so there is no deployment here to drive. Fail closed rather than print a verdict about
    // a chain that never ran.
    eprintln!("ladder_turn: LINUX-ONLY (AF_UNIX hops, §2.6 principals, setuid launcher)");
    std::process::exit(2);
}

#[cfg(target_os = "linux")]
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let flag = |name: &str| -> Option<String> {
        args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned()
    };
    let (config, evidence_dir, expect) =
        match (flag("--config"), flag("--evidence-dir"), flag("--expect")) {
            (Some(c), Some(e), Some(x)) => (c, e, x),
            _ => {
                eprintln!(
                    "ladder_turn: usage: ladder_turn --config <path> --evidence-dir <dir> \
                     --expect <outcome>"
                );
                std::process::exit(2);
            }
        };
    std::process::exit(linux::run(&config, &evidence_dir, &expect));
}

#[cfg(target_os = "linux")]
mod linux {
    use std::path::{Path, PathBuf};
    use std::sync::{Arc, Mutex};
    use std::time::{SystemTime, UNIX_EPOCH};

    use rusqlite::Connection;
    use serde_json::{json, Value};

    use brops_broker::chain_executor::linux::{ChainSockets, LinuxHopConnector};
    use brops_broker::chain_executor::{ChainExecutor, CustodyResolver, HopConnector};
    use brops_broker::chain_hops::{HopConn, HopError, Principal};
    use brops_broker::ladder_executor::{LadderChain, SqliteTurnContent, UuidTurnIds};
    use brops_broker::manifest_resolver::{KeyResolver, ResolvedKeys};

    use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
    use brops_core::governed_message_store::verify_committed_binding;
    use brops_core::governed_sidecar::{GovernedSidecar, SidecarPrincipal, SidecarTrust};
    use brops_core::governed_submit::{SubmitTransport, BRIDGE_SUBMIT_PROTOCOL};
    use brops_core::governed_turn_ipc::{TurnReason, REQUEST_PROTOCOL};
    use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
    use brops_core::ipc_framing::decode_one;
    use brops_core::key_manifest::{
        check_and_persist, parse_floor_json, resolve_production_key, verify_manifest_anchored,
        AntiRollbackFloor, FloorPersistError, KeyManifest, PinnedRoot, RootAnchor, RootProvenance,
        VerifiedManifestRoot,
    };
    use brops_core::production_trust::{resolve_trust_state, verifying_key_hex, TrustState};
    use brops_core::receipt::sha256_hex;

    /// The variable a human types to say "this machine genuinely lacks that, and I know it".
    /// Same rule and same refusal of blanket forms as `core/src/bin/ladder_output_pull.rs`.
    const DECLARATION_ENV: &str = "BROPS_TEST_MISSING_PREREQUISITES";
    /// Values people reach for when they want the guard off wholesale. Refused BY NAME.
    const BLANKET_FORMS: [&str; 8] = ["all", "*", "any", "1", "true", "yes", "on", "everything"];
    /// This driver's own evidence document, so a reader can tell it from the bundle
    /// `ladder_evidence.py` writes beside it and from the pull driver's.
    const DRIVER_EVIDENCE_PROTOCOL: &str = "brops.ladder-turn-driver-evidence.v1";

    // =============================================================================================
    // Prerequisites — a missing one is a machine to fix, never a quiet early return
    // =============================================================================================

    fn require_prerequisite(present: bool, tag: &str, what: &str) {
        if present {
            return;
        }
        let declaration = std::env::var(DECLARATION_ENV).unwrap_or_default();
        let entries: Vec<&str> =
            declaration.split(',').map(str::trim).filter(|e| !e.is_empty()).collect();
        if let Some(blanket) =
            entries.iter().find(|e| BLANKET_FORMS.contains(&e.to_ascii_lowercase().as_str()))
        {
            panic!(
                "{DECLARATION_ENV} contains `{blanket}`, which declares NOTHING. There is no \
                 blanket form and no boolean: every missing prerequisite costs its own tag. Name \
                 `{tag}` itself if this machine really lacks it.\n  missing: {what}"
            );
        }
        if entries.iter().any(|e| *e == tag) {
            eprintln!(
                "RESULT: ladder-turn SKIPPED — the prerequisite `{tag}` is declared missing in \
                 {DECLARATION_ENV}. {what}"
            );
            std::process::exit(0);
        }
        panic!(
            "missing prerequisite: {what}\n  This is a machine to fix, not a result. If this host \
             genuinely cannot provide it, say so by name and this driver will exit 0 instead:\n    \
             {DECLARATION_ENV}={tag}\n  (comma-separate several). A driver that returns early \
             proves nothing, and the exit status would read the same either way."
        );
    }

    // =============================================================================================
    // small helpers
    // =============================================================================================

    fn now_ms() -> i64 {
        SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
    }

    fn s(v: &Value, path: &[&str]) -> Option<String> {
        let mut cur = v;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_str().map(str::to_string)
    }

    fn i64_at(v: &Value, path: &[&str]) -> Option<i64> {
        let mut cur = v;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_i64()
    }

    fn hex32(value: &str) -> Option<[u8; 32]> {
        if value.len() != 64 {
            return None;
        }
        let b = value.as_bytes();
        let mut out = [0u8; 32];
        for i in 0..32 {
            let hi = (b[2 * i] as char).to_digit(16)?;
            let lo = (b[2 * i + 1] as char).to_digit(16)?;
            out[i] = (hi * 16 + lo) as u8;
        }
        Some(out)
    }

    /// The §2.5 owner/mode floor for the root trust anchor file (audit **F-17**), byte-for-byte the
    /// check `live_turn.rs` applies to the same file: a regular, root-owned file with no group/other
    /// write bit, checked on the OPENED fd rather than by a `metadata(path)` re-lookup.
    ///
    /// Duplicated rather than shared because `live_turn`'s copy is a private item of a binary in this
    /// same crate and there is no library here to hold one copy in; the alternative — a new public
    /// helper in `brops-broker` — would widen a SHIPPED crate's surface for a proof binary.
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

    fn write_json(path: &Path, value: &Value) {
        if let Ok(text) = serde_json::to_string_pretty(value) {
            let _ = std::fs::write(path, text.as_bytes());
        }
    }

    fn record_line(path: &Path, value: &Value) {
        use std::io::Write;
        if let Ok(mut fh) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(fh, "{value}");
        }
    }

    // =============================================================================================
    // What refused, by name — recorded by the party that refused, never invented here
    // =============================================================================================

    /// The named refusals the chain itself cannot carry.
    ///
    /// Every field is written by the code that OBSERVED the refusal and is read only once
    /// `run_governed_turn` has already reported `blocked`. Nothing here influences the chain: a
    /// `Refusals` with every field `None` produces exactly the same turn, and the outcome is then
    /// reported as the unnamed `blocked:chain:*`, which is a weaker report rather than a different
    /// one.
    #[derive(Default)]
    struct Refusals {
        /// Which stage of `resolve_keys` refused (this driver's own resolver names its own step).
        keys: Mutex<Option<String>>,
        /// `principal:reason`, from a trusted principal's own `reason` field.
        hop: Mutex<Option<String>>,
        /// The §4.5 `reason` verbatim out of a §4.6 `ok:false` frame.
        governed: Mutex<Option<String>>,
        /// A LOCAL sidecar transport failure (spawn / deadline / non-JSON), which §6.1 makes
        /// out-of-band and which is never a governed verdict.
        transport: Mutex<Option<String>>,
        /// The FREE TEXT of a `bridge.op.v1` op-shaped error — what the sidecar answers when a hop
        /// below §4.6 refused (a §4.10(a0) `governed-turn-open` refusal arrives this way).
        ///
        /// **It is evidence and a diagnostic, never an outcome.** §4.10(g) says the client keeps
        /// only the protocol name from this shape, because it names no protocol of its own and its
        /// text is not a member of any closed union — so building an `--expect` vocabulary on it
        /// would put free text where a checked name has to be. The outcome for this case stays the
        /// chain's own `blocked:chain:*`; this field is what makes the RED legible.
        op_error: Mutex<Option<String>>,
    }

    impl Refusals {
        fn set(slot: &Mutex<Option<String>>, value: String) {
            if let Ok(mut guard) = slot.lock() {
                if guard.is_none() {
                    *guard = Some(value);
                }
            }
        }
        fn get(slot: &Mutex<Option<String>>) -> Option<String> {
            slot.lock().ok().and_then(|g| g.clone())
        }
    }

    // =============================================================================================
    // (0) KEYS — the deployment's trust anchors, over the KIT-generated root anchor
    // =============================================================================================

    /// The same sequence `ProductionResolver::resolve_keys` runs — root-verify, anti-rollback CAS
    /// **and persist**, resolve both production keys — against the anchor file the kit provisioned
    /// instead of the compiled-in production pin.
    ///
    /// It uses [`verify_manifest_anchored`] rather than `verify_manifest` for the reason `live_turn`
    /// does: the anchored form returns evidence of WHICH anchor verified the signature, and
    /// `resolve_trust_state` requires that evidence before it will render any custody verdict at all.
    /// A `kit_generated` anchor therefore cannot produce `TrustState::Production` — which is the
    /// whole reason this shape is honest.
    ///
    /// **A persist failure REFUSES.** That is not softened here: continuing on an unadvanced floor is
    /// the state `check_and_persist` exists to remove, and the kit leaving `trust.floor_path`
    /// root-owned `0644` inside a root-owned directory is a KIT bug this driver reports as a refusal
    /// (`floor_not_persisted`) rather than papers over.
    struct KitAnchoredKeys {
        manifest: KeyManifest,
        root_sig_b64: String,
        anchor: RootAnchor,
        floor: Mutex<AntiRollbackFloor>,
        floor_path: PathBuf,
        signer_key_id: String,
        sup_attest_key_id: String,
        workspace_id: String,
        install_id: String,
        author: String,
        /// Filled by `resolve_keys` on success and read by [`KitCustody`]. `resolve_trust_state`
        /// cannot be asked without it, so a turn whose keys never resolved has no custody verdict —
        /// which is the correct answer, not a missing one.
        verified: Mutex<Option<(VerifiedManifestRoot, String)>>,
        refusals: Arc<Refusals>,
    }

    impl KitAnchoredKeys {
        fn refuse(&self, stage: &str) -> TurnReason {
            Refusals::set(&self.refusals.keys, stage.to_string());
            TurnReason::UpstreamBlocked
        }
    }

    impl KeyResolver for KitAnchoredKeys {
        fn resolve_keys(&self) -> Result<ResolvedKeys, TurnReason> {
            let now = now_ms();

            // (1) The manifest under the PINNED anchor, with the anchor's custody carried out.
            let verified_root =
                verify_manifest_anchored(&self.manifest, &self.root_sig_b64, &self.anchor)
                    .map_err(|_| self.refuse("manifest_root_signature_invalid"))?;

            // (2) Anti-rollback: accept only an epoch at/above the durable floor, advance it, and
            //     WRITE IT BACK. Both limbs refuse, and they refuse by different names because they
            //     are different faults: one is a rollback, the other is a deployment whose broker
            //     principal cannot write its own floor.
            {
                let mut floor = self.floor.lock().map_err(|_| self.refuse("floor_lock"))?;
                let advanced =
                    check_and_persist(&floor, &self.manifest, &self.floor_path).map_err(|e| {
                        self.refuse(match e {
                            FloorPersistError::Rollback(_) => "anti_rollback",
                            FloorPersistError::NotPersisted(_) => "floor_not_persisted",
                        })
                    })?;
                *floor = advanced;
            }

            // (3) Both production keys, class / validity-window / revocation enforced.
            let iso = resolve_production_key(
                &self.manifest,
                &self.signer_key_id,
                RECEIPT_ENVELOPE_ARTIFACT_TYPE,
                now,
            )
            .map_err(|_| self.refuse("signer_key_unresolved"))?;
            let sup = resolve_production_key(
                &self.manifest,
                &self.sup_attest_key_id,
                RECEIPT_ENVELOPE_ARTIFACT_TYPE,
                now,
            )
            .map_err(|_| self.refuse("supervisor_attestation_key_unresolved"))?;
            let iso_pub =
                hex32(&iso.public_key_hex).ok_or_else(|| self.refuse("signer_pubkey_malformed"))?;
            let sup_pub = hex32(&sup.public_key_hex)
                .ok_or_else(|| self.refuse("supervisor_pubkey_malformed"))?;

            // F-29, in the type: the key handed to the custody resolver is the exact one the chain
            // is pinned to verify envelopes under — not a second manifest lookup, which would make
            // the guard compare a value against itself.
            if let Ok(mut slot) = self.verified.lock() {
                *slot = Some((verified_root, verifying_key_hex(&iso_pub)));
            }

            Ok(ResolvedKeys {
                isolated_signer_key_id: self.signer_key_id.clone(),
                isolated_signer_public_key: iso_pub,
                supervisor_attestation_key_id: self.sup_attest_key_id.clone(),
                supervisor_attestation_public_key: sup_pub,
                workspace_id: self.workspace_id.clone(),
                install_id: self.install_id.clone(),
                author: self.author.clone(),
            })
        }
    }

    /// The `Arc` cannot carry the impl — both `Arc` and the trait are foreign here — so the shared
    /// handle is a local newtype. It is also the clearer statement: exactly ONE resolver exists, and
    /// the RESULT line and the committed row are answers from that same object.
    struct SharedKeys(Arc<KitAnchoredKeys>);
    impl KeyResolver for SharedKeys {
        fn resolve_keys(&self) -> Result<ResolvedKeys, TurnReason> {
            self.0.resolve_keys()
        }
    }

    /// The deployment's answer to "whose keys were these?", wired INTO the executor rather than
    /// computed after it — the discipline `live_turn` records as an audit finding.
    ///
    /// It re-reads the clock every call because a manifest token has a validity window: an expired
    /// one must stop producing a verdict without anything having to notice and expire a cache.
    struct KitCustody(Arc<KitAnchoredKeys>);

    impl CustodyResolver for KitCustody {
        fn resolve(&self) -> TrustState {
            let held = self.0.verified.lock().ok().and_then(|g| g.clone());
            let (verified_root, envelope_key_hex) = match held {
                Some(pair) => pair,
                None => {
                    return TrustState::NoTrustedManifest(
                        "the key resolver never produced a verified anchor for this turn",
                    )
                }
            };
            resolve_trust_state(
                Some(&self.0.manifest),
                Some(&verified_root),
                &self.0.signer_key_id,
                RECEIPT_ENVELOPE_ARTIFACT_TYPE,
                now_ms(),
                &envelope_key_hex,
            )
        }
    }

    // =============================================================================================
    // The two recorders. Pass-through: same bytes in, same result out.
    // =============================================================================================

    struct RecordingConn {
        inner: Box<dyn HopConn>,
        principal: Principal,
        sent: Option<Vec<u8>>,
        log: PathBuf,
        refusals: Arc<Refusals>,
    }

    impl HopConn for RecordingConn {
        fn send_all(&mut self, frame: &[u8]) -> Result<(), HopError> {
            // The framed bytes as they go on the wire; the payload is recovered with the framing
            // module's OWN decoder, so this recorder cannot disagree with the encoder about where
            // the payload starts.
            self.sent = decode_one(frame).ok().map(<[u8]>::to_vec);
            self.inner.send_all(frame)
        }

        fn recv_all(&mut self) -> Result<Vec<u8>, HopError> {
            let reply = self.inner.recv_all();
            let payload = reply.as_ref().ok().and_then(|r| decode_one(r).ok().map(<[u8]>::to_vec));
            let as_json = |b: &Option<Vec<u8>>| -> Value {
                b.as_deref()
                    .and_then(|raw| serde_json::from_slice::<Value>(raw).ok())
                    .unwrap_or(Value::Null)
            };
            let request = as_json(&self.sent);
            let response = as_json(&payload);
            // A typed refusal from a trusted principal, read out of ITS reply. `parse_reply` maps
            // this to `HopError::Refused` and the chain then collapses it to `UpstreamBlocked`, so
            // this is the only place the name survives.
            if response.get("ok").and_then(Value::as_bool) != Some(true) {
                if let Some(reason) = response.get("reason").and_then(Value::as_str) {
                    Refusals::set(
                        &self.refusals.hop,
                        format!("{}:{reason}", self.principal.as_str()),
                    );
                }
            }
            record_line(
                &self.log,
                &json!({
                    "principal": self.principal.as_str(),
                    "request": request,
                    "reply": response,
                    "transport_ok": reply.is_ok(),
                }),
            );
            reply
        }
    }

    /// Wraps [`LinuxHopConnector`] and hands back a recording view of the SAME connection. It
    /// selects no socket of its own and alters no byte.
    struct RecordingHops {
        inner: LinuxHopConnector,
        log: PathBuf,
        refusals: Arc<Refusals>,
    }

    impl HopConnector for RecordingHops {
        fn connect(&self, principal: Principal) -> Result<Box<dyn HopConn>, HopError> {
            let inner = match self.inner.connect(principal) {
                Ok(c) => c,
                Err(e) => {
                    Refusals::set(&self.refusals.hop, format!("{}:{e:?}", principal.as_str()));
                    return Err(e);
                }
            };
            Ok(Box::new(RecordingConn {
                inner,
                principal,
                sent: None,
                log: self.log.clone(),
                refusals: Arc::clone(&self.refusals),
            }))
        }
    }

    /// Wraps [`GovernedSidecar`]. It forwards the frame verbatim and returns the inner result
    /// verbatim; the §4.10(g) submit exchange is written out whole, and every §4.10(f) pull exchange
    /// is written as protocol + digests (a pull chunk's body IS the output, and the output belongs
    /// in the protected store rather than duplicated into an evidence file).
    struct RecordingTransport {
        inner: GovernedSidecar,
        dir: PathBuf,
        log: PathBuf,
        refusals: Arc<Refusals>,
    }

    impl SubmitTransport for RecordingTransport {
        fn call(&self, frame: &Value) -> Result<Value, String> {
            let reply = self.inner.call(frame);
            let protocol =
                frame.get("protocol").and_then(Value::as_str).unwrap_or("(none)").to_string();
            let request_bytes = serde_json::to_vec(frame).unwrap_or_default();
            let (reply_sha, reply_ok) = match &reply {
                Ok(v) => (
                    sha256_hex(&serde_json::to_vec(v).unwrap_or_default()),
                    v.get("ok").and_then(Value::as_bool),
                ),
                Err(_) => (String::new(), None),
            };
            record_line(
                &self.log,
                &json!({
                    "protocol": protocol,
                    "request_sha256": sha256_hex(&request_bytes),
                    "reply_sha256": reply_sha,
                    "reply_ok": reply_ok,
                    "transport_ok": reply.is_ok(),
                }),
            );
            match &reply {
                Err(why) => Refusals::set(&self.refusals.transport, why.clone()),
                Ok(document) => {
                    // §4.6's governed verdict, verbatim. `governed_turn_submit_prepared` returns it
                    // as an Err arm and `LadderChain` maps that to `UpstreamBlocked`, so this is the
                    // only place the supervisor's own reason survives.
                    if document.get("ok").and_then(Value::as_bool) == Some(false) {
                        if let Some(reason) = document
                            .get("error")
                            .and_then(|e| e.get("reason"))
                            .and_then(Value::as_str)
                        {
                            Refusals::set(&self.refusals.governed, reason.to_string());
                        }
                        // The op-shaped error a hop BELOW §4.6 produces (`error` is a string here,
                        // not the §4.6 `{reason, receipt_id}` object, so the two arms cannot
                        // collide). Printed the moment it happens: a RED that says
                        // `governed-turn-open refused ... quota_turns` is readable, and one that
                        // says only `UpstreamBlocked` costs a CI round trip to diagnose.
                        if let Some(text) = document.get("error").and_then(Value::as_str) {
                            Refusals::set(&self.refusals.op_error, text.to_string());
                            eprintln!(
                                "ladder_turn: the sidecar answered an op-shaped error rather than \
                                 a §4.6 frame: {text}"
                            );
                        }
                    }
                }
            }
            // The submit exchange, whole: `ladder_evidence.py` reads the frame for the three staged
            // digests and the challenge document, and reads the reply as the §4.6 frame it judges.
            if protocol == BRIDGE_SUBMIT_PROTOCOL {
                write_json(&self.dir.join("submit-frame.json"), frame);
                if let Ok(document) = &reply {
                    write_json(&self.dir.join("result-frame.json"), document);
                }
            }
            reply
        }
    }

    // =============================================================================================
    // Production broker-minted ids (§4.10(g): backend-generated, never renderer-supplied)
    // =============================================================================================

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

    // =============================================================================================
    // The run
    // =============================================================================================

    /// A closed refusal that happened BEFORE the chain could be built. It is reported with the same
    /// `--expect` vocabulary as everything else (`blocked:setup:<name>`) so a misprovisioned kit
    /// cannot satisfy an expectation about a governed refusal.
    fn setup_blocked(evidence: &Path, expect: &str, name: &str, detail: &str) -> i32 {
        let outcome = format!("blocked:setup:{name}");
        finish(evidence, expect, &outcome, json!({ "detail": detail }))
    }

    /// Print the one RESULT line, write the driver's own evidence document, and decide the exit
    /// status by comparing the outcome to `--expect` BY NAME.
    fn finish(evidence: &Path, expect: &str, outcome: &str, extra: Value) -> i32 {
        let matched = outcome == expect;
        let mut document = json!({
            "protocol": DRIVER_EVIDENCE_PROTOCOL,
            "driver": "ladder_turn",
            "is_the_brops_broker_binary": false,
            "outcome": outcome,
            "expected": expect,
            "expectation_met": matched,
            // SAFETY: getuid never fails and touches no memory.
            "driver_uid": unsafe { libc::getuid() },
            "driver_pid": std::process::id(),
            "recorded_at_ms": now_ms(),
        });
        if let (Some(target), Some(source)) = (document.as_object_mut(), extra.as_object()) {
            for (k, v) in source {
                target.insert(k.clone(), v.clone());
            }
        }
        write_json(&evidence.join("ladder-turn.json"), &document);
        println!("RESULT: ladder-turn outcome={outcome} expected={expect} met={matched}");
        if matched {
            0
        } else {
            eprintln!(
                "ladder_turn: the outcome is `{outcome}` and `--expect` named `{expect}`. A driver \
                 that accepted either would prove nothing about the one it named."
            );
            1
        }
    }

    pub fn run(config_path: &str, evidence_dir: &str, expect: &str) -> i32 {
        let evidence = PathBuf::from(evidence_dir);
        require_prerequisite(
            std::fs::create_dir_all(&evidence).is_ok(),
            "ladder-driver-evidence-dir",
            "a writable evidence directory for the ladder driver (--evidence-dir)",
        );
        let hop_log = evidence.join("authority-hops.jsonl");
        let sidecar_log = evidence.join("sidecar-exchanges.jsonl");
        let _ = std::fs::remove_file(&hop_log);
        let _ = std::fs::remove_file(&sidecar_log);

        // ---- the deployment config (this driver's own side; never a hop reply) ----
        require_prerequisite(
            Path::new(config_path).is_file(),
            "ladder-driver-config",
            "the deployment config named by --config",
        );
        let cfg: Value = match std::fs::read_to_string(config_path)
            .ok()
            .and_then(|raw| serde_json::from_str(&raw).ok())
        {
            Some(v) => v,
            None => return setup_blocked(&evidence, expect, "config_malformed", config_path),
        };

        // ---- (A) the root trust anchor: a TCB FILE that STATES its provenance ----
        //
        // Refused rather than ignored, exactly as `live_turn` refuses it: silently preferring the
        // file would leave the self-certifying "the verifier reads the anchor out of the same file
        // it reads its own knobs from" arrangement one config edit away from coming back.
        if cfg.pointer("/trust/root_pub_hex").is_some()
            || cfg.pointer("/trust/root_key_id").is_some()
        {
            return setup_blocked(
                &evidence,
                expect,
                "config_carries_inline_root_anchor",
                "trust.root_pub_hex / trust.root_key_id are present",
            );
        }
        let anchor_path = match s(&cfg, &["trust", "root_anchor_path"]) {
            Some(p) => p,
            None => {
                return setup_blocked(&evidence, expect, "config_missing", "trust.root_anchor_path")
            }
        };
        if let Err(why) = anchor_file_is_tcb_owned(&anchor_path) {
            return setup_blocked(&evidence, expect, &format!("root_anchor_{why}"), &anchor_path);
        }
        let anchor_doc: Value = match std::fs::read_to_string(&anchor_path)
            .ok()
            .and_then(|b| serde_json::from_str(&b).ok())
        {
            Some(v) => v,
            None => return setup_blocked(&evidence, expect, "root_anchor_unreadable", &anchor_path),
        };
        // A typed, closed value. An unknown, misspelled or absent `provenance` is refused outright:
        // a deployment whose anchor cannot say what its custody is has not answered the question.
        let provenance = match anchor_doc
            .get("provenance")
            .and_then(Value::as_str)
            .and_then(RootProvenance::parse)
        {
            Some(p) => p,
            None => {
                return setup_blocked(
                    &evidence,
                    expect,
                    "root_anchor_provenance_unknown",
                    &anchor_path,
                )
            }
        };
        let anchor = RootAnchor {
            pinned: PinnedRoot {
                root_key_id: anchor_doc
                    .get("root_key_id")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                public_key_hex: anchor_doc
                    .get("public_key_hex")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
            },
            provenance,
        };

        // ---- (B) the root-signed key manifest + the anti-rollback floor ----
        let manifest_path = match s(&cfg, &["trust", "manifest_path"]) {
            Some(p) => p,
            None => {
                return setup_blocked(&evidence, expect, "config_missing", "trust.manifest_path")
            }
        };
        let manifest: KeyManifest = match std::fs::read_to_string(&manifest_path)
            .ok()
            .and_then(|b| serde_json::from_str(&b).ok())
        {
            Some(m) => m,
            None => return setup_blocked(&evidence, expect, "manifest_unreadable", &manifest_path),
        };
        let root_sig_b64 = match s(&cfg, &["trust", "manifest_sig_path"])
            .and_then(|p| std::fs::read_to_string(p).ok())
        {
            Some(sig) => sig.trim().to_string(),
            None => {
                return setup_blocked(&evidence, expect, "manifest_sig_unreadable", &manifest_path)
            }
        };
        let floor_path = match s(&cfg, &["trust", "floor_path"]) {
            Some(p) => PathBuf::from(p),
            None => return setup_blocked(&evidence, expect, "config_missing", "trust.floor_path"),
        };
        // An absent or malformed floor fails CLOSED — it is never read as "no floor required".
        let floor = match std::fs::read(&floor_path).ok().as_deref().and_then(parse_floor_json) {
            Some(f) => f,
            None => {
                return setup_blocked(
                    &evidence,
                    expect,
                    "floor_unreadable",
                    &floor_path.display().to_string(),
                )
            }
        };

        let refusals = Arc::new(Refusals::default());
        let keys = Arc::new(KitAnchoredKeys {
            manifest: manifest.clone(),
            root_sig_b64,
            anchor,
            floor: Mutex::new(floor),
            floor_path,
            signer_key_id: s(&cfg, &["trust", "signer_key_id"]).unwrap_or_default(),
            sup_attest_key_id: s(&cfg, &["trust", "supervisor_attestation_key_id"])
                .unwrap_or_default(),
            workspace_id: s(&cfg, &["resolved", "workspace_id"]).unwrap_or_default(),
            install_id: s(&cfg, &["resolved", "install_id"]).unwrap_or_default(),
            author: s(&cfg, &["resolved", "author"]).unwrap_or_else(|| "Bro".to_string()),
            verified: Mutex::new(None),
            refusals: Arc::clone(&refusals),
        });

        // ---- (C) §2.6: the broker side of the ladder speaks to ONE principal ----
        //
        // Only the challenge authority. `accept-open`, the staging uploads, `evidence-request` and
        // the §4.10(f) read all belong to the SIDECAR, over the one-shot subprocess. So the
        // supervisor and signer paths are deliberately left empty here, exactly as
        // `build_governed_executor` leaves them: a value would be a path this principal holds and
        // must not use.
        let sockets = match s(&cfg, &["sockets", "authority"]) {
            Some(authority) => {
                ChainSockets { authority, supervisor: String::new(), signer: String::new() }
            }
            None => return setup_blocked(&evidence, expect, "config_missing", "sockets.authority"),
        };

        // ---- (D) the turn's actual CONTENT — the whole reason the ladder replaced the direct path ----
        //
        // The three artifact DIGESTS are not read from config at all: `prepare_governed_turn_v1b`
        // computes each one from the bytes this turn actually sends.
        let messages_db = match s(&cfg, &["content", "messages_db"]) {
            Some(p) => p,
            None => {
                return setup_blocked(&evidence, expect, "config_missing", "content.messages_db")
            }
        };
        let system_prompt = match s(&cfg, &["content", "system"]).filter(|v| !v.is_empty()) {
            Some(v) => v,
            None => return setup_blocked(&evidence, expect, "config_missing", "content.system"),
        };
        let window = match i64_at(&cfg, &["content", "window"]).filter(|w| *w > 0) {
            Some(w) => w as usize,
            None => return setup_blocked(&evidence, expect, "config_missing", "content.window"),
        };

        // ---- (E) §2.6: the sidecar this driver starts must BE the sidecar principal ----
        let (python, script, sandbox) = match (
            s(&cfg, &["sidecar", "python"]),
            s(&cfg, &["sidecar", "script"]),
            s(&cfg, &["sidecar", "cwd"]),
        ) {
            (Some(python), Some(script), Some(cwd)) => (python, script, PathBuf::from(cwd)),
            _ => {
                return setup_blocked(
                    &evidence,
                    expect,
                    "config_missing",
                    "sidecar.python / sidecar.script / sidecar.cwd",
                )
            }
        };
        let principal = match SidecarPrincipal::from_config(cfg.get("sidecar")) {
            Ok(p) => p,
            Err(why) => {
                return setup_blocked(&evidence, expect, "sidecar_principal_unresolved", &why)
            }
        };
        // `SidecarTrust::RelayFramesOnly` buys this driver no licence: `admits` refuses, before any
        // process exists, every request whose own `protocol` is not one of the two relay frames.
        let transport = RecordingTransport {
            inner: GovernedSidecar::as_distinct_principal(
                &python,
                &script,
                sandbox,
                SidecarTrust::RelayFramesOnly,
                principal,
            ),
            dir: evidence.clone(),
            log: sidecar_log,
            refusals: Arc::clone(&refusals),
        };

        // ---- (F) the broker-side DB + the durable §7.1(c)(d) replay ledger ----
        let db_path = match s(&cfg, &["db", "path"]) {
            Some(p) => p,
            None => return setup_blocked(&evidence, expect, "config_missing", "db.path"),
        };
        let conn = match Connection::open(&db_path) {
            Ok(c) => c,
            Err(e) => return setup_blocked(&evidence, expect, "db_open", &format!("{e}")),
        };
        if let Err(e) = conn.busy_timeout(std::time::Duration::from_secs(5)) {
            return setup_blocked(&evidence, expect, "db_busy_timeout", &format!("{e}"));
        }
        if let Err(e) = init_schema(&conn) {
            return setup_blocked(&evidence, expect, "db_schema", &e);
        }
        let ledger = match brops_core::broker_turns::DurableAcceptanceLedger::open(&db_path) {
            Ok(l) => l,
            Err(e) => return setup_blocked(&evidence, expect, "db_ledger", &format!("{e}")),
        };

        // ---- (G) the SAME LadderChain, the same six seams ----
        let chain = LadderChain::new(
            Box::new(SharedKeys(Arc::clone(&keys))),
            Box::new(RecordingHops {
                inner: LinuxHopConnector { sockets },
                log: hop_log,
                refusals: Arc::clone(&refusals),
            }),
            Box::new(SqliteTurnContent::new(messages_db, system_prompt, window)),
            Box::new(transport),
            Box::new(UuidTurnIds),
            Box::new(ledger),
        );
        let executor = ChainExecutor::with_custody(chain, Box::new(KitCustody(Arc::clone(&keys))));

        let conversation_id = match s(&cfg, &["resolved", "conversation_id"]) {
            Some(c) => c,
            None => {
                return setup_blocked(
                    &evidence,
                    expect,
                    "config_missing",
                    "resolved.conversation_id",
                )
            }
        };
        let request = json!({
            "protocol": REQUEST_PROTOCOL,
            "conversation_id": conversation_id,
            "agent": "Bro",
            "client_request_id": brops_core::id(),
        })
        .to_string();

        let result = run_governed_turn(&conn, &request, &UuidIds, &executor, now_ms());

        // ---- (H) report. The outcome NAMES the party that refused, from that party's own reply. ----
        let custody = KitCustody(Arc::clone(&keys)).resolve();
        let mut facts = json!({
            "root_anchor_provenance": provenance.as_str(),
            "root_anchor_key_id": anchor_doc.get("root_key_id").cloned().unwrap_or(Value::Null),
            "manifest_epoch": manifest.manifest_epoch,
            "manifest_content_sha256": manifest.content_hash(),
            "trust_state": trust_state_label(&custody),
            "production_verified": custody.is_production_verified(),
            "chain_bound": custody.is_chain_bound(),
            "conversation_id": conversation_id,
            "broker_turn_id": result.broker_turn_id,
        });
        if let Some(object) = facts.as_object_mut() {
            for (name, slot) in [
                ("keys_refusal", &refusals.keys),
                ("hop_refusal", &refusals.hop),
                ("governed_refusal", &refusals.governed),
                ("transport_error", &refusals.transport),
                ("sidecar_op_error", &refusals.op_error),
            ] {
                object.insert(
                    name.to_string(),
                    Refusals::get(slot).map(Value::String).unwrap_or(Value::Null),
                );
            }
        }

        if result.status != "committed" {
            let reason =
                result.reason.map(|r| format!("{r:?}")).unwrap_or_else(|| "unknown".into());
            // Most specific first, in the order the chain runs: a keys refusal means no hop
            // happened, a hop refusal means no frame was submitted, and so on. Only a stage nobody
            // named falls through to the chain's own collapsed reason.
            let outcome = if let Some(stage) = Refusals::get(&refusals.keys) {
                format!("blocked:keys:{stage}")
            } else if let Some(named) = Refusals::get(&refusals.hop) {
                format!("blocked:hop:{named}")
            } else if let Some(named) = Refusals::get(&refusals.governed) {
                format!("blocked:governed_refusal:{named}")
            } else if Refusals::get(&refusals.transport).is_some() {
                "blocked:transport".to_string()
            } else {
                format!("blocked:chain:{reason}")
            };
            return finish(&evidence, expect, &outcome, facts);
        }

        let message = match result.message {
            Some(m) => m,
            None => return finish(&evidence, expect, "blocked:committed_without_message", facts),
        };
        // What this driver can genuinely ask, holding a projection: is it backed by the durable
        // committed row, and does the body it is about to report hash to the envelope digest that
        // row stores? `verify_committed_binding` re-reads the row and recomputes the digest.
        let bound = verify_committed_binding(&conn, &message).is_ok();
        if let Some(object) = facts.as_object_mut() {
            object.insert("bound".into(), Value::Bool(bound));
            object
                .insert("committed_trust_state".into(), Value::String(message.trust_state.clone()));
            object.insert("message_id".into(), Value::String(message.message_id.clone()));
        }
        if !bound {
            return finish(&evidence, expect, "blocked:commit_binding", facts);
        }
        // The report and the durable row must be the SAME verdict.
        if Some(message.trust_state.as_str()) != custody.committed_label() {
            return finish(&evidence, expect, "blocked:custody_row_mismatch", facts);
        }
        finish(&evidence, expect, "committed", facts)
    }

    fn trust_state_label(state: &TrustState) -> String {
        match state {
            TrustState::Production { key_id, key_epoch, root_key_id } => format!(
                "trusted_verified(production key={key_id} epoch={key_epoch} root={root_key_id})"
            ),
            TrustState::DemonstrationCustody {
                key_id,
                key_epoch,
                root_key_id,
                root_provenance,
            } => format!(
                "demonstration_custody(key={key_id} epoch={key_epoch} root={root_key_id} \
                 root_provenance={})",
                root_provenance.as_str()
            ),
            TrustState::NoTrustedManifest(why) => format!("no_trusted_manifest({why})"),
        }
    }
}
