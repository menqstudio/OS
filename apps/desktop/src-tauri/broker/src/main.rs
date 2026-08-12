//! Wave 3b-1B — the trusted **broker service** as a SEPARATE binary crate (design-GREEN rev-30 §0 role #2,
//! §4.10(g)).
//!
//! The broker is the ONLY process that opens the receipt/broker SQLite database and the ONLY process that
//! runs governed turns. It is NOT the renderer: the renderer is a mutually-distrusting client that connects
//! over a single-request/single-response AF_UNIX channel. This binary:
//!
//!   1. opens (or creates) the broker DB and initializes the three rev-30 governed-turn schemas
//!      (`broker_turns`, `governed_message_store`, `supervisor_ledger`) — the idempotency ledger, the
//!      committed-message store and the supervisor lease ledger, all through `brops-core` so there is
//!      exactly one schema authority;
//!   2. on Linux binds the renderer→broker AF_UNIX listener and, for each connection, reads EXACTLY ONE
//!      length-prefixed [`ipc_framing`] request frame, authenticates the peer's OS credentials
//!      (`SO_PEERCRED`) and allowlists EXACTLY the renderer/login UID (denying every other), then drives one
//!      governed turn through [`broker_orchestrator::run_governed_turn`] with a broker-minted [`BrokerIds`]
//!      and a [`GovernedExecutor`], and writes the framed committed/blocked reply.
//!
//! The challenge→authority→supervisor→signer→verification chain is a follow-up slice, so the injected
//! executor here fails closed with [`TurnReason::UpstreamBlocked`]: the broker never fabricates an accepted
//! output it did not actually get from the signed-envelope chain. Every renderer request is therefore
//! answered with a well-formed `blocked` reply — real, correct, and fail-closed — until the real executor
//! lands.
//!
//! The `bind`/`accept`/`recv` + `SO_PEERCRED` read are the only host-specific parts and are gated behind
//! `#[cfg(target_os = "linux")]`. On every other host `main` prints the platform-unsupported banner and
//! exits non-zero (governed real mode disabled — fail closed). The DB-schema init and the governed-turn
//! wiring are pure and unit-tested on any platform.

// Governed-turn orchestration lives in the crate LIBRARY. Since 2026-08-12 there are TWO consumers of
// it and they are not interchangeable:
//
//   * `brops_broker::ladder_executor::LadderChain` -- the rev-30 4.10(g) SIDECAR LADDER, and the only
//     thing this binary can build. Its three artifact digests come from the actual conversation.
//   * `brops_broker::chain_executor::linux::LinuxGovernedTurnChain` -- the DIRECT AF_UNIX chain, now
//     reachable only from the `brops-governed-live` proof driver, which is what proves the 2.5 TCB
//     floor and the 5 five-op lifecycle in `engine/ci/live/run_live_turn.sh`. This binary no longer
//     constructs it, and `build_governed_executor` no longer names it.
//
// The shipped posture is unchanged: with no `$BROPS_BROKER_CONFIG` the fail-closed
// UpstreamBlockedExecutor is what serves the renderer->broker path, and every gap in that config
// returns to it.
use brops_core::broker_orchestrator::{BrokerIds, GovernedExecutor};
use brops_core::governed_message_store::AcceptedOutput;
use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest};
use rusqlite::Connection;

// ---------------------------------------------------------------------------------------------------
// Exit codes (fail-closed). A healthy broker runs its accept loop forever; every early return is an error.
// ---------------------------------------------------------------------------------------------------
const EXIT_PLATFORM_UNSUPPORTED: i32 = 2;
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const EXIT_DB: i32 = 3;
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const EXIT_SOCKET: i32 = 4;

/// Per-read/write deadline armed on every accepted renderer connection (audit F-31). The accept loop
/// is serial by design — one governed turn per connection — so a peer that connects and then stays
/// silent must not be able to hold the only thread. A governed turn is buffered and can take a while
/// upstream, so this is generous; it exists to bound the SILENT case, not to rush a real turn.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const CONN_IO_TIMEOUT_MS: u64 = 120_000;

// ---------------------------------------------------------------------------------------------------
// Broker DB schema init — pure, host-independent, testable on any platform. Creates the three governed-turn
// schemas through brops-core so the broker shares exactly one schema authority with the recorder side.
//
// `governed_output_stream` used to be a FOURTH call here and is gone. The rev-30 §4.10(f) output-stream
// table is SUPERVISOR state — Appendix B's principal/ACL matrix puts `governed_output_streams` in the 0700
// supervisor-only DB beside the acceptance ledger and staging — so it is created by `supervisor_ledger`'s
// canonical DDL and served by the supervisor, which is the party that HOLDS the output bytes. The deleted
// module's own `CREATE TABLE IF NOT EXISTS governed_output_streams` ran on THIS connection one line before
// `supervisor_ledger::create_schema`, so its divergent shape would have won the race and made the canonical
// DDL a silent no-op.
// ---------------------------------------------------------------------------------------------------

/// Initialize the three rev-30 governed-turn schemas on `conn` (idempotent — every `create_schema` uses
/// `CREATE TABLE IF NOT EXISTS`). Fails closed with a stage-tagged message on the first error so a partially
/// migrated DB never advances to serving turns.
pub fn init_broker_schema(conn: &Connection) -> Result<(), String> {
    brops_core::broker_turns::create_schema(conn)
        .map_err(|e| format!("broker_turns schema init failed: {e:?}"))?;
    brops_core::governed_message_store::create_schema(conn)
        .map_err(|e| format!("governed_message_store schema init failed: {e}"))?;
    brops_core::supervisor_ledger::create_schema(conn)
        .map_err(|e| format!("supervisor_ledger schema init failed: {e:?}"))?;
    Ok(())
}

// ---------------------------------------------------------------------------------------------------
// Broker-minted identities. The renderer can NEVER supply these — the broker is the sole authority for the
// `broker_turn_id` and the per-turn `request_nonce`. Production uses `brops_core::id()` (UUID v4).
// ---------------------------------------------------------------------------------------------------

/// Production [`BrokerIds`]: fresh UUID v4 broker-turn ids and request nonces.
pub struct UuidBrokerIds;
impl BrokerIds for UuidBrokerIds {
    fn new_broker_turn_id(&self) -> String {
        brops_core::id()
    }
    fn new_request_nonce(&self) -> String {
        brops_core::id()
    }
}

// ---------------------------------------------------------------------------------------------------
// Governed executor. The real challenge→authority→supervisor→signer→verification chain is a follow-up
// slice; until it lands the broker fails closed: it refuses every turn with UpstreamBlocked rather than
// fabricate an accepted output. This is the correct fail-closed behavior, not a stub that lies.
// ---------------------------------------------------------------------------------------------------

/// The interim [`GovernedExecutor`]: no real upstream chain is wired yet, so every turn is refused closed.
pub struct UpstreamBlockedExecutor;
impl GovernedExecutor for UpstreamBlockedExecutor {
    fn execute_and_verify(
        &self,
        _req: &ValidatedRequest,
        _broker_turn_id: &str,
        _request_nonce: &str,
    ) -> Result<(AcceptedOutput, brops_core::production_trust::TrustState), TurnReason> {
        Err(TurnReason::UpstreamBlocked)
    }
}

// ---------------------------------------------------------------------------------------------------
// Entry point.
// ---------------------------------------------------------------------------------------------------

fn main() {
    std::process::exit(run());
}

#[cfg(not(target_os = "linux"))]
fn run() -> i32 {
    // No AF_UNIX SO_PEERCRED peer authentication off Linux ⇒ the renderer→broker trust boundary cannot be
    // enforced ⇒ governed real mode is unavailable. Fail closed.
    eprintln!("brops-broker: platform unsupported (governed real-mode disabled)");
    EXIT_PLATFORM_UNSUPPORTED
}

#[cfg(target_os = "linux")]
fn run() -> i32 {
    match linux::serve() {
        Ok(()) => EXIT_SOCKET, // serve() only returns on a fatal listener error
        Err(code) => code,
    }
}

// ---------------------------------------------------------------------------------------------------
// Linux real path (§4.10(g) renderer→broker channel). Gated so the Windows/other-host build stays pure-std;
// the CI Linux job exercises the real renderer → broker → committed/blocked reply path. The socket bind /
// accept use std::os::unix::net; the SO_PEERCRED read is the one libc call. Every step is fail-closed.
// ---------------------------------------------------------------------------------------------------
#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use brops_core::ipc_framing::{authorize_peer, encode_frame, FrameDecoder, PeerCred};
    use std::io::{Read, Write};
    use std::os::unix::io::AsRawFd;
    use std::os::unix::net::{UnixListener, UnixStream};

    pub fn serve() -> Result<(), i32> {
        // argv: [socket_path] [allowed_renderer_uid?]. Defaults: a fixed runtime path and the broker's own
        // login uid stand in for the pinned renderer identity until the launcher passes them explicitly.
        let mut args = std::env::args().skip(1);
        let socket_path = args
            .next()
            .unwrap_or_else(|| "/run/brops/broker.sock".to_string());
        let allowed_uid = args
            .next()
            .and_then(|s| s.parse::<u32>().ok())
            // SAFETY: getuid never fails and touches no memory.
            .unwrap_or_else(|| unsafe { libc::getuid() });

        // Open the broker DB and initialize the four governed-turn schemas before accepting a single peer.
        let db_path = socket_path.replace(".sock", ".db");
        let conn = Connection::open(&db_path).map_err(|e| {
            eprintln!("brops-broker: cannot open broker DB: {e}");
            EXIT_DB
        })?;
        // The durable acceptance ledger opens a SECOND connection to this same file (it is owned by the
        // chain, which outlives any single turn). Arm a busy timeout here so an overlapping write from
        // that connection makes this one wait its turn instead of failing instantly with SQLITE_BUSY.
        if let Err(e) = conn.busy_timeout(std::time::Duration::from_secs(5)) {
            eprintln!("brops-broker: cannot arm DB busy timeout: {e}");
            return Err(EXIT_DB);
        }
        init_broker_schema(&conn).map_err(|e| {
            eprintln!("brops-broker: {e}");
            EXIT_DB
        })?;

        // A stale socket file blocks bind; remove it first (the broker owns this path exclusively).
        let _ = std::fs::remove_file(&socket_path);
        let listener = UnixListener::bind(&socket_path).map_err(|e| {
            eprintln!("brops-broker: cannot bind {socket_path}: {e}");
            EXIT_SOCKET
        })?;

        let ids = UuidBrokerIds;
        // Config-driven, FAIL-CLOSED executor: if `BROPS_BROKER_CONFIG` points at a valid deployment config
        // with a TCB-root-signed manifest, serve real governed turns through the live chain; otherwise (no
        // config / malformed / no trusted manifest) fall back to the fail-closed default that Blocks every
        // turn — the shipped posture is unchanged until a trusted manifest is provisioned.
        let executor: Box<dyn GovernedExecutor> = build_governed_executor(allowed_uid, &db_path);

        // One governed turn per connection (single-request/single-response). A bad peer or malformed frame
        // fails that ONE connection closed; the listener keeps serving.
        for stream in listener.incoming() {
            match stream {
                Ok(mut s) => {
                    // Audit F-31: this loop is strictly serial, so ONE peer that connects and then
                    // sends nothing used to hold `read_one_frame`'s blocking read open forever and
                    // no further connection was ever accepted — a permanent, self-sustaining denial
                    // of the governed path from any process sharing the renderer's uid, which the
                    // design treats as untrusted. A deadline turns that into a refused connection.
                    let deadline = std::time::Duration::from_millis(CONN_IO_TIMEOUT_MS);
                    if s.set_read_timeout(Some(deadline)).is_err()
                        || s.set_write_timeout(Some(deadline)).is_err()
                    {
                        eprintln!("brops-broker: could not arm connection deadline; refusing");
                        continue;
                    }
                    if let Err(e) = handle_conn(&conn, &mut s, allowed_uid, &ids, executor.as_ref()) {
                        eprintln!("brops-broker: connection refused: {e}");
                    }
                }
                Err(e) => eprintln!("brops-broker: accept error: {e}"),
            }
        }
        Ok(())
    }

    /// Build the broker's [`GovernedExecutor`], FAIL-CLOSED by default.
    ///
    /// Reads the optional deployment config at `$BROPS_BROKER_CONFIG`: if it parses, passes the 2.5 TCB
    /// integrity floor, and carries `[trust]` (manifest + signature + floor + both key ids),
    /// `[sockets].authority`, `[content]` (the conversation source) and `[sidecar]` (the one-shot bridge
    /// spawn -- `python`/`script`/`cwd` AND the 2.6 `principal`/`invoker` that make the child the
    /// SIDECAR account rather than this one), the 4.10(g) `LadderChain` is served. ANY problem -- no env var, unreadable/malformed
    /// config, a TCB violation, a missing manifest, an
    /// unresolved 2.6 sidecar PRINCIPAL, an
    /// unconfigured conversation source, or an acceptance ledger that will not open -- returns the
    /// fail-closed `UpstreamBlockedExecutor`, so the broker keeps rendering `blocked` (never a
    /// fabricated acceptance).
    ///
    /// **What it deliberately no longer builds.** The direct `LinuxGovernedTurnChain` and its
    /// `[sockets].supervisor` / `[sockets].signer` / `[execution]` config are gone from this function.
    /// That chain resolved `system_sha256` / `history_sha256` / `generation_config_sha256` from
    /// `[resolved]` -- deployment-static values identical on every turn -- so its receipts attested what
    /// the config said a conversation was. The ladder derives all three from the conversation. There is
    /// no flag that selects between them and no fallback from one to the other: a fallback would leave
    /// the old behaviour live while looking replaced.
    ///
    /// `db_path` is the broker's own database file; the §7.1(c)(d) replay ledger is opened against it so
    /// accepted `receipt_id`s and spent `request_nonce`s survive a restart of this process.
    fn build_governed_executor(login_uid: u32, db_path: &str) -> Box<dyn GovernedExecutor> {
        use brops_broker::chain_executor::linux::{ChainSockets, LinuxHopConnector};
        use brops_broker::chain_executor::ChainExecutor;
        use brops_broker::ladder_executor::{LadderChain, SqliteTurnContent, UuidTurnIds};
        use brops_broker::manifest_resolver::{ProductionResolver, ResolvedFacts};
        use brops_core::broker_turns::DurableAcceptanceLedger;
        use brops_core::governed_sidecar::{GovernedSidecar, SidecarTrust};
        use brops_core::key_manifest::{AntiRollbackFloor, KeyManifest};
        use serde_json::Value;

        let fail_closed = || -> Box<dyn GovernedExecutor> { Box::new(UpstreamBlockedExecutor) };

        let path = match std::env::var("BROPS_BROKER_CONFIG") {
            Ok(p) if !p.is_empty() => p,
            _ => return fail_closed(),
        };
        let cfg: Value = match std::fs::read_to_string(&path).ok().and_then(|s| serde_json::from_str(&s).ok())
        {
            Some(v) => v,
            None => {
                eprintln!("brops-broker: config unreadable/malformed at {path} — serving fail-closed");
                return fail_closed();
            }
        };

        let s = |p: &[&str]| -> Option<String> {
            let mut cur = &cfg;
            for k in p {
                cur = cur.get(*k)?;
            }
            cur.as_str().map(|x| x.to_string())
        };
        let i = |p: &[&str]| -> Option<i64> {
            let mut cur = &cfg;
            for k in p {
                cur = cur.get(*k)?;
            }
            cur.as_i64()
        };

        // ---- §2.5 TCB INTEGRITY FLOOR (audit F-10) ----
        //
        // Before ANY governed mode is entered, the pinned TCB set — the seven trusted executables,
        // their configs and IPC policies, the pinned-manifest configuration, the allowlist source,
        // the key-manifest root anchor, and both unit files — must be TCB-owned, non-writable by any
        // login/runtime principal, and hash-match its start-time pin. `verify_tcb_integrity` had
        // implemented exactly that decision and had NO caller and no non-test `FsProbe`, so every
        // downstream signature check ran on binaries whose integrity was never measured.
        //
        // Fail-closed in every direction: no manifest configured, unreadable, malformed, or ANY
        // violation ⇒ keep the blocking executor rather than serve real governed turns.
        let runtime_uids: Vec<u32> = cfg
            .get("uids")
            .and_then(|v| v.as_object())
            .map(|m| m.values().filter_map(|v| v.as_u64().map(|u| u as u32)).collect())
            .unwrap_or_default();
        let mut principals = runtime_uids.clone();
        if !principals.contains(&login_uid) {
            principals.push(login_uid);
        }
        let pin_manifest_path = s(&["trust", "tcb_pin_manifest_path"]).or_else(|| {
            std::env::var(brops_broker::tcb_probe::TCB_PIN_MANIFEST_ENV)
                .ok()
                .filter(|p| !p.is_empty())
        });
        if let Err(why) = brops_broker::tcb_probe::verify_deployment_tcb(
            pin_manifest_path.as_deref(),
            &principals,
            login_uid,
        ) {
            eprintln!("brops-broker: TCB integrity floor REFUSED ({why}) — serving fail-closed");
            return fail_closed();
        }

        // The presence of a manifest path is the switch: absent ⇒ no trusted manifest ⇒ fail-closed.
        let manifest_path = match s(&["trust", "manifest_path"]) {
            Some(p) => p,
            None => return fail_closed(),
        };
        let manifest: KeyManifest = match std::fs::read_to_string(&manifest_path)
            .ok()
            .and_then(|b| serde_json::from_str(&b).ok())
        {
            Some(m) => m,
            None => return fail_closed(),
        };
        let root_sig = match s(&["trust", "manifest_sig_path"]).and_then(|p| std::fs::read_to_string(p).ok())
        {
            Some(sig) => sig.trim().to_string(),
            None => return fail_closed(),
        };
        // Anti-rollback floor (audit P0, honest note): this Linux broker path reads only {highest_epoch,
        // highest_hash} and does NOT verify a signature. The anti-rollback boundary here is the OS
        // write-protection on the deployment dir: floor_path MUST be owned by / writable only by the broker
        // service principal (file mode 0600, dedicated UID; the in-scope sidecar runs as a DIFFERENT UID and
        // cannot write it). See WINDOWS_ANTIROLLBACK_HARDENING.md (the Windows twin) + the TPM/monotonic-counter
        // roadmap item for a same-principal-compromise defense. An absent or malformed floor fails CLOSED —
        // it is never read as "no floor required".
        //
        // The path is kept: the resolver WRITES the advanced floor back to it after every accepted manifest
        // (audit — the advance used to live only in memory and reset on restart).
        let floor_path = match s(&["trust", "floor_path"]) {
            Some(p) => std::path::PathBuf::from(p),
            None => return fail_closed(),
        };
        let floor = match std::fs::read(&floor_path)
            .ok()
            .and_then(|b| brops_core::key_manifest::parse_floor_json(&b))
        {
            Some(f) => f,
            None => return fail_closed(),
        };
        let facts = ResolvedFacts {
            workspace_id: s(&["resolved", "workspace_id"]).unwrap_or_default(),
            install_id: s(&["resolved", "install_id"]).unwrap_or_default(),
            system_sha256: s(&["resolved", "system_sha256"]).unwrap_or_default(),
            history_sha256: s(&["resolved", "history_sha256"]).unwrap_or_default(),
            generation_config_sha256: s(&["resolved", "generation_config_sha256"]).unwrap_or_default(),
            requested_at: s(&["resolved", "requested_at"]).unwrap_or_default(),
            run_id: s(&["resolved", "run_id"]).unwrap_or_default(),
            task_id: s(&["resolved", "task_id"]).unwrap_or_default(),
            requested_at_ms: i(&["resolved", "requested_at_ms"]).unwrap_or(0),
            author: s(&["resolved", "author"]).unwrap_or_else(|| "Bro".to_string()),
        };
        let resolver = ProductionResolver::provisioned(
            manifest,
            root_sig,
            floor,
            floor_path,
            s(&["trust", "signer_key_id"]).unwrap_or_default(),
            s(&["trust", "supervisor_attestation_key_id"]).unwrap_or_default(),
            facts,
        );

        // ---- 2.6: on the LADDER the broker speaks to ONE principal ----
        //
        // Only the challenge authority. `accept-open`, `launch-gate`, the privileged spawn, `complete-run`,
        // `attest-run` and `sign-result` all belong to the SIDECAR and the SUPERVISOR now, over the
        // 4.10(a0)/(a)(b)(c)/(d) hops inside the one-shot subprocess -- which is the point of 2.6's
        // pairwise-distinct principals. So `sockets.supervisor` / `sockets.signer` and the whole
        // `execution` block (recorder command, launcher/executor paths, lease file, cgroup, report and
        // evidence dirs) are no longer read here. A broker that still held those paths would still be a
        // party that could spawn the setuid chain, and the config is the place that stops being true.
        let sockets = match s(&["sockets", "authority"]) {
            Some(authority) => ChainSockets {
                authority,
                // Unused by this path and deliberately not read from config: a value here would be a
                // path the broker holds and must not use. The transport only ever selects
                // `Principal::ChallengeAuthority`, so these two are never dialled.
                supervisor: String::new(),
                signer: String::new(),
            },
            None => return fail_closed(),
        };

        // ---- The turn's actual CONTENT -- the whole reason this path replaced the direct one ----
        //
        // `content.messages_db` is the desktop's `messages` table (migration 0003); `content.system` is
        // the agent's system prompt; `content.window` is how many of the most recent messages are sent.
        // The three artifact DIGESTS are not read from config at all any more -- `prepare_governed_turn_v1b`
        // computes each one from the bytes this turn actually sends. `resolved.{system,history,
        // generation_config}_sha256` are therefore dead on this path; they remain in `ResolvedFacts` only
        // for the direct chain the proof driver wires, and that type's doc says so.
        let messages_db = match s(&["content", "messages_db"]) {
            Some(p) => p,
            None => {
                eprintln!(
                    "brops-broker: content.messages_db is not configured - the ladder cannot derive \
                     this conversation's digests, so there is nothing honest to sign. Serving fail-closed."
                );
                return fail_closed();
            }
        };
        let system_prompt = match s(&["content", "system"]) {
            Some(v) if !v.is_empty() => v,
            _ => return fail_closed(),
        };
        let window = match i(&["content", "window"]).filter(|w| *w > 0) {
            Some(w) => w as usize,
            None => return fail_closed(),
        };

        // ---- The 4.10(g) submit transport: the tree's ONE bridge spawn ----
        //
        // This used to resolve `engine_trust::apply()` and fail closed when it could not. That refusal
        // was permanent rather than provisional and it was aimed at the wrong thing.
        //
        // Permanent: the broker CANNOT hold the provisioned set, and not for want of provisioning. The
        // set's `BRO_CONDUCTOR_SESSION_TOKEN` binds `agent_id: bro-000`, `role: bro` -- the CONDUCTOR's
        // identity -- and the broker is 0 role #2. A broker that never claims that identity holds an
        // inert file; a broker that claims it has made the trusted broker service the conductor. No
        // second token can be minted (the operator root signs one offline and the key is zeroized
        // inside the minting scope), and the 0700 tree holding it also holds eight retained private
        // authority seeds, so no grant yields one without the others.
        //
        // Aimed at the wrong thing: this transport relays exactly two frames --
        // `bridge.governed-turn-submit.v1` (below, through `governed_turn_submit_prepared`) and
        // `bridge.governed-turn-output-read.v1` (the 4.10(f) pull, through the same `SubmitTransport`)
        // -- and NOTHING downstream of either reads one of the five provisioned variables. In the
        // child, `_bridge_governed_turn_submit` and `_bridge_output_read` resolve
        // `BROPS_SUPERVISOR_SOCKET` and nothing else, and no module in either import closure reads the
        // five or calls a function that does. The two shapes that DO read them --
        // `bridge.task-request` and the `governance.read` op -- are driven by the DESKTOP, which
        // carries the set and still cannot be built without it.
        //
        // So the requirement now follows the protocol. `SidecarTrust::RelayFramesOnly` buys this
        // binary no licence: `SidecarTrust::admits` refuses, before any process exists, every request
        // whose own top-level `protocol` is not one of the two above, and the child's `_dispatch`
        // routes on that same field -- so there is no frame this transport can send that the sidecar
        // then runs as a governed turn. See `brops_core::governed_sidecar::SidecarTrust`.
        //
        // What this does NOT do is open a governed surface. The refusals that hold that line are
        // untouched: `$BROPS_BROKER_CONFIG` is absent on every shipped install (nothing in the product
        // writes it), the 2.5 TCB floor, the pinned key manifest, the 2.6 sidecar principal below, the
        // socket, the conversation source and the durable ledger each return `fail_closed()`, and
        // `commands.rs::governed_verification_unconfigured` still blocks every user-facing governed
        // surface before the model is invoked.
        let (python, script, sandbox) = match (
            s(&["sidecar", "python"]),
            s(&["sidecar", "script"]),
            s(&["sidecar", "cwd"]),
        ) {
            (Some(python), Some(script), Some(cwd)) => {
                (python, script, std::path::PathBuf::from(cwd))
            }
            _ => return fail_closed(),
        };

        // ---- 2.6: the sidecar this broker starts must BE the sidecar principal ----
        //
        // `GovernedSidecar` used to build a plain `Command::new(python)`, so the child it started
        // carried the BROKER's uid. 2.6 requires the seven runtime principals to be pairwise distinct,
        // `engine/ci/live/run_ladder_turn.sh` provisions `brops-sidecar` as a seventh account for
        // exactly that reason, and all four supervisor surfaces this transport knocks on
        // (`governed_turn_open`, staging upload, evidence-request, 4.10(f) output read) gate on
        // `peer_is_sidecar(peer_uid, allowed_sidecar_uid)` -- a strict equality against ONE configured
        // uid. So a broker-spawned-as-broker sidecar is refused at the first hop; and a deployment that
        // "fixes" it by configuring the sidecar uid to the broker's is refused at the door instead, by
        // `handle_connection`'s `principal collapse: sidecar uid equals broker uid`. There is no third
        // arrangement, which is why there is no fallback here.
        //
        // `SidecarPrincipal::from_config` is the only constructor of the type, it validates the
        // deployment's invoker prefix, and no value of it means "as me". A broker that cannot resolve
        // one therefore has nothing to pass to `as_distinct_principal` and must refuse -- BY NAME, so
        // an operator is told which key is missing rather than left reading a `blocked` reply.
        let principal = match brops_core::governed_sidecar::SidecarPrincipal::from_config(
            cfg.get("sidecar"),
        ) {
            Ok(p) => p,
            Err(why) => {
                eprintln!(
                    "brops-broker: this deployment cannot start the sidecar AS the sidecar \
                     principal ({why}). 2.6 requires the broker and the sidecar to be distinct \
                     principals and the supervisor refuses the collapse outright, so there is no \
                     arrangement in which spawning it as the broker would work. Serving fail-closed."
                );
                return fail_closed();
            }
        };
        let transport = GovernedSidecar::as_distinct_principal(
            &python,
            &script,
            sandbox,
            SidecarTrust::RelayFramesOnly,
            principal,
        );

        // ---- 7.1(c)(d) DURABLE replay ledger (audit IDX-67 / IDX-86 / IDX-94) ----
        //
        // This used to be `InMemoryLedger::new()`. Its two HashSets died with the process, so the
        // receipt-id uniqueness and one-time-nonce guarantees the chain advertises held only until the
        // next restart: the same signed envelope and the same nonce were accepted again afterwards.
        // The ledger now writes to the broker's own SQLite file, so both defences are on disk.
        // If it cannot be opened there is no replay defence at all -- refuse to serve governed turns.
        let ledger = match DurableAcceptanceLedger::open(db_path) {
            Ok(l) => l,
            Err(e) => {
                eprintln!(
                    "brops-broker: durable acceptance ledger unavailable at {db_path} ({e}) - serving fail-closed"
                );
                return fail_closed();
            }
        };

        eprintln!("brops-broker: trusted manifest provisioned - serving the 4.10(g) governed ladder");
        let chain = LadderChain::new(
            Box::new(resolver),
            Box::new(LinuxHopConnector { sockets }),
            Box::new(SqliteTurnContent::new(messages_db, system_prompt, window)),
            Box::new(transport),
            Box::new(UuidTurnIds),
            Box::new(ledger),
        );
        // `ChainExecutor::new` -- NOT `with_custody`. Unchanged from the direct wiring, and unchanged
        // deliberately: with no custody resolver every turn resolves to `NoTrustedManifest` and
        // `persist_committed` REFUSES the commit. Wiring custody is a separate, owner-gated decision and
        // is not a side effect of replacing the execution path.
        Box::new(ChainExecutor::new(chain))
    }

    /// Read the peer's OS credentials via `SO_PEERCRED` (kernel-attested at connect time — unforgeable by the
    /// renderer). Returns `None` if the option read fails.
    fn peer_cred(stream: &UnixStream) -> Option<PeerCred> {
        let mut cred = libc::ucred {
            pid: 0,
            uid: 0,
            gid: 0,
        };
        let mut len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
        // SAFETY: getsockopt writes a ucred of exactly `len` bytes into `cred`; fd is a live connected socket.
        let rc = unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_PEERCRED,
                &mut cred as *mut libc::ucred as *mut libc::c_void,
                &mut len,
            )
        };
        if rc != 0 {
            return None;
        }
        Some(PeerCred {
            uid: cred.uid,
            gid: cred.gid,
            pid: cred.pid,
        })
    }

    /// Handle one renderer connection: authenticate the peer, read one framed request, run one governed
    /// turn, and write the framed reply. Every failure fails this connection closed.
    fn handle_conn(
        conn: &Connection,
        stream: &mut UnixStream,
        allowed_uid: u32,
        ids: &dyn BrokerIds,
        executor: &dyn GovernedExecutor,
    ) -> Result<(), String> {
        // 1. Peer authentication BEFORE reading any request bytes (rev-30 §2.1): the renderer/login UID is
        //    the broker's only client here; deny every other principal.
        let peer = peer_cred(stream).ok_or_else(|| "SO_PEERCRED read failed".to_string())?;
        authorize_peer(&peer, allowed_uid, &[])
            .map_err(|e| format!("peer not authorized: {e:?}"))?;

        // 2. Read EXACTLY ONE bounded frame. The decoder fails closed on a declared-oversize length; a read
        //    ceiling caps a slow/greedy peer without allocating on its say-so.
        let raw = read_one_frame(stream)?;
        let raw_str =
            std::str::from_utf8(&raw).map_err(|_| "request frame is not valid UTF-8".to_string())?;

        // 3. Drive one governed turn. run_governed_turn never panics: a malformed request or an upstream
        //    refusal both come back as a closed `blocked` reply.
        let result =
            brops_core::broker_orchestrator::run_governed_turn(conn, raw_str, ids, executor, brops_core_now());

        // 4. Serialize + frame the reply and write it back on the same connection.
        let body = serde_json::to_vec(&result).map_err(|e| format!("reply serialize failed: {e}"))?;
        let frame =
            encode_frame(&body).map_err(|e| format!("reply frame encode failed: {e:?}"))?;
        stream
            .write_all(&frame)
            .map_err(|e| format!("reply write failed: {e}"))?;
        stream.flush().map_err(|e| format!("reply flush failed: {e}"))?;
        Ok(())
    }

    /// Read from the stream until the [`FrameDecoder`] yields exactly one complete frame payload. Bounded:
    /// never buffers more than the frame cap + one length prefix, and fails closed on EOF-before-frame or a
    /// declared-oversize length.
    fn read_one_frame(stream: &mut UnixStream) -> Result<Vec<u8>, String> {
        let mut decoder = FrameDecoder::new();
        let mut chunk = [0u8; 1024];
        loop {
            if let Some(frame) = decoder
                .next_frame()
                .map_err(|e| format!("frame decode failed: {e:?}"))?
            {
                return Ok(frame);
            }
            let n = stream
                .read(&mut chunk)
                .map_err(|e| format!("frame read failed: {e}"))?;
            if n == 0 {
                return Err("peer closed before a complete frame".to_string());
            }
            // The FrameDecoder enforces the payload cap on the length prefix itself (fail closed on a
            // declared-oversize length), so feeding raw chunks cannot be used to force an unbounded alloc.
            decoder.feed(&chunk[..n]);
        }
    }

    /// Wall-clock milliseconds for the turn's `now_ms`. Kept here (not in the pure init path) so the tested
    /// core stays deterministic.
    fn brops_core_now() -> i64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0)
    }
}

// ---------------------------------------------------------------------------------------------------
// Tests — pure, offline, host-independent (run on Windows/macOS/Linux alike). They exercise the broker DB
// schema init and the governed-turn wiring over an in-memory connection with a fake executor; no socket, no
// peer-cred syscall.
// ---------------------------------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use brops_core::broker_orchestrator::run_governed_turn;
    use brops_core::governed_message_store::sha256_hex;

    // =============================================================================================
    // §2.6 — the one thing about `mod linux` that CAN be checked from a non-Linux host
    // =============================================================================================
    //
    // `build_governed_executor` lives inside `#[cfg(target_os = "linux")] mod linux`, so on any other
    // host it is not type-checked at all and no test can call it. That is exactly the region where a
    // regression would be invisible until CI, and "spawns the sidecar as itself" is precisely the
    // class of regression that reads as fine in review.
    //
    // `include_str!` is a COMPILE-TIME read of this same file and is not `cfg`-gated, so the source of
    // the Linux-only region is available to a test on every host. That is a weaker check than a type
    // check and it is honest about which one it is: it pins WHICH constructor the broker names, not
    // that the surrounding code compiles.

    /// This file's own source, read at compile time so the `cfg`-gated region is still inspectable.
    const BROKER_MAIN_SOURCE: &str = include_str!("main.rs");

    /// The marker that separates the broker's CODE from this test module. `include_str!` reads the
    /// whole file, tests included, so a scan that did not cut here would find every string these
    /// tests search for — written by the tests themselves — and pass or fail on its own text. That is
    /// not a hypothetical: all three assertions below tripped on their own source the first time.
    const TEST_MODULE_MARKER: &str = "#[cfg(test)]\nmod tests {";

    /// The broker's executable source: this file up to the test module, with comment lines removed.
    ///
    /// Comments are cut for the same reason the tests are: the prose above `build_governed_executor`
    /// names both constructors and both refusals in order to explain them, so a scan over it would
    /// see a fail-closed return where there is only a description of one.
    fn broker_code() -> String {
        // Normalised first. This repository is checked out with `core.autocrlf=true` on Windows, so
        // the bytes `include_str!` reads carry CRLF there and LF on the Linux CI runner — and a
        // marker containing a newline would match on one host and not the other. That is not a
        // hypothetical either: it is how this guard first failed.
        let source = BROKER_MAIN_SOURCE.replace("\r\n", "\n");
        let code = source
            .split(TEST_MODULE_MARKER)
            .next()
            .expect("split always yields a first part");
        assert!(
            code.len() < source.len(),
            "the test-module marker no longer matches this file, so this scan covers its own source"
        );
        code.lines()
            .filter(|l| {
                let t = l.trim_start();
                !t.starts_with("//")
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    /// The broker must never name the calling-principal constructor.
    ///
    /// `GovernedSidecar::as_calling_principal` builds `Command::new(python)` — a child carrying the
    /// BROKER's uid, which §2.6 forbids and which every sidecar-facing supervisor service refuses by
    /// uid. It is the right constructor for the desktop and the wrong one here, and the two are one
    /// token apart, so the mistake is a plausible one rather than a theatrical one.
    #[test]
    fn the_broker_never_names_the_calling_principal_constructor() {
        let code = broker_code();
        assert!(
            !code.contains("as_calling_principal"),
            "the broker names GovernedSidecar::as_calling_principal, which spawns the sidecar as \
             the BROKER — §2.6 requires them to be distinct principals and the supervisor refuses \
             the collapse outright (`principal collapse: sidecar uid equals broker uid`)"
        );
        // And it DOES name the distinct-principal one, so this test cannot pass by the transport
        // having been deleted.
        assert!(
            code.contains("as_distinct_principal"),
            "the broker no longer builds a sidecar transport at all"
        );
    }

    /// The refusal is a refusal. `SidecarPrincipal::from_config` is resolved in the same function
    /// that serves the ladder, and its error arm returns `fail_closed()` — never a transport built
    /// anyway. Checked textually for the same reason as above, and deliberately narrow: it pins the
    /// pairing of the resolver with `fail_closed`, not the prose around it.
    #[test]
    fn an_unresolved_sidecar_principal_returns_the_fail_closed_executor() {
        let code = broker_code();
        let at = code
            .find("SidecarPrincipal::from_config")
            .expect("the broker resolves the §2.6 sidecar principal");
        let after = &code[at..];
        let build = after.find("as_distinct_principal").expect("the transport is built after it");
        assert!(
            after[..build].contains("return fail_closed();"),
            "there is no fail-closed return between resolving the sidecar principal and building \
             the transport, so an unresolved principal would reach the spawn"
        );
    }

    /// The Linux-only wiring, written ONCE more here so a non-Linux host type-checks it.
    ///
    /// `build_governed_executor` lives in `#[cfg(target_os = "linux")] mod linux`, so on this
    /// developer box and on the Windows CI job its body is never compiled — a wrong argument type or
    /// a renamed constructor there is invisible until the Linux job runs. This function has the same
    /// three lines and the same types, and it compiles everywhere.
    ///
    /// It builds its own `SidecarTrust::RelayFramesOnly` — the same value the Linux function
    /// passes — rather than taking one, because that variant holds nothing and needs nothing
    /// resolved. (It could not take a `TrustEnvironment`: `engine_trust::apply` is that type's only
    /// constructor and reads a process-global that must stay empty in a test binary. That is exactly
    /// the fact that made the old requirement unsatisfiable in this process, here as in the real
    /// one.) What needs proving is that `cfg.get("sidecar")` satisfies `from_config`, and that
    /// `as_distinct_principal` accepts `(&String, &String, PathBuf, SidecarTrust, SidecarPrincipal)`
    /// in that order. It is deliberately NOT a second production path: nothing calls it, it is
    /// inside `#[cfg(test)]`, and the guard tests above are what keep the real one in the shape this
    /// one describes.
    fn broker_sidecar_wiring(
        cfg: &serde_json::Value,
        python: String,
        script: String,
        sandbox: std::path::PathBuf,
    ) -> Result<brops_core::governed_sidecar::GovernedSidecar, String> {
        let principal =
            brops_core::governed_sidecar::SidecarPrincipal::from_config(cfg.get("sidecar"))?;
        Ok(brops_core::governed_sidecar::GovernedSidecar::as_distinct_principal(
            &python,
            &script,
            sandbox,
            brops_core::governed_sidecar::SidecarTrust::RelayFramesOnly,
            principal,
        ))
    }

    /// Names [`broker_sidecar_wiring`] so it is compiled rather than dead — the compile IS the test.
    /// The resolver half is then exercised for real, on the same `cfg.get("sidecar")` expression the
    /// Linux function uses: a config with no `sidecar` block refuses, and the reference shape does not.
    #[test]
    fn the_linux_sidecar_wiring_typechecks_and_its_resolver_refuses_a_config_without_a_sidecar_block() {
        let _typechecked: fn(
            &serde_json::Value,
            String,
            String,
            std::path::PathBuf,
        ) -> Result<brops_core::governed_sidecar::GovernedSidecar, String> = broker_sidecar_wiring;

        use brops_core::governed_sidecar::SidecarPrincipal;
        let empty = serde_json::json!({ "trust": { "manifest_path": "/x" } });
        assert!(
            SidecarPrincipal::from_config(empty.get("sidecar")).is_err(),
            "a config with no `sidecar` block resolved a principal"
        );
        let provisioned = serde_json::json!({
            "sidecar": {
                "python": "/usr/bin/python3",
                "script": "/opt/brops-live/bridge/engine_sidecar.py",
                "cwd": "/opt/brops-live/sandbox",
                "principal": "brops-sidecar",
                "invoker": ["/usr/bin/sudo", "-n", "-u", "brops-sidecar", "/usr/bin/env"],
            }
        });
        let p = SidecarPrincipal::from_config(provisioned.get("sidecar"))
            .expect("the provisioned shape resolves");
        assert_eq!(p.account(), "brops-sidecar");
    }

    /// The broker names the RELAY arm, and does not reach for a trust environment it cannot have.
    ///
    /// Textual for the same reason the two guards above are: `build_governed_executor` lives inside
    /// `#[cfg(target_os = "linux")] mod linux` and is never type-checked on this host. Both halves
    /// are asserted, because either one alone is satisfiable by the wrong edit — naming
    /// `RelayFramesOnly` while still calling `engine_trust::apply` would leave the permanent refusal
    /// in place, and dropping `apply` without naming the arm would not compile there but would look
    /// fine here.
    #[test]
    fn the_broker_names_the_relay_arm_and_never_reaches_for_a_trust_environment() {
        let code = broker_code();
        assert!(
            code.contains("SidecarTrust::RelayFramesOnly"),
            "the broker no longer names the relay arm, so it is passing something else to the spawn"
        );
        assert!(
            !code.contains("engine_trust::apply"),
            "the broker calls engine_trust::apply, which can never succeed in this process: the \
             conductor-session token in the provisioned set binds agent_id bro-000 / role bro, and \
             the broker is §0 role #2"
        );
    }

    /// The door, exercised through the SAME wiring the Linux function uses. This is the mutant the
    /// design has to survive: a `bridge.task-request` driven through the broker's trust-free
    /// transport must be refused, and refused before a child exists — because that request lands on
    /// `_real_callables` and, through it, on `bro_signature.load_trusted_keys`, which without
    /// `BRO_TRUSTED_REGISTRY_ROOT` reads the development registry committed in this tree while the
    /// turn still reports itself as governed.
    ///
    /// The interpreter is deliberately unspawnable, so a door that had been removed would announce
    /// itself as a SPAWN failure rather than as a pass.
    #[test]
    fn the_brokers_transport_cannot_carry_a_task_request() {
        let cfg = serde_json::json!({
            "sidecar": {
                "principal": "brops-sidecar",
                "invoker": ["/usr/bin/sudo", "-n", "-u", "brops-sidecar", "/usr/bin/env"],
            }
        });
        let seam = broker_sidecar_wiring(
            &cfg,
            "brops-no-such-interpreter-does-not-exist".to_string(),
            "/opt/brops-live/bridge/engine_sidecar.py".to_string(),
            std::env::temp_dir(),
        )
        .expect("the reference sidecar block resolves");
        let task_request = serde_json::json!({
            "task_id": "t-1",
            "task_class": "chat",
            "rationale": "because",
            "request": { "prompt": "hello" },
        })
        .to_string();
        let err = seam
            .round_trip(&task_request)
            .expect_err("the broker's transport carried a task-request");
        assert!(
            err.contains("SidecarTrust::RelayFramesOnly"),
            "the refusal is not the protocol door's: {err}"
        );
        assert!(
            !err.contains("Could not run the governed engine sidecar"),
            "the task-request reached a spawn before it was refused: {err}"
        );
        // And the two frames the broker actually sends DO get through the door, so this cannot pass
        // by the transport refusing everything.
        for protocol in brops_core::governed_sidecar::RELAY_PROTOCOLS {
            let frame = serde_json::json!({ "protocol": protocol }).to_string();
            let err = seam.round_trip(&frame).expect_err("the interpreter cannot start");
            assert!(
                err.contains("Could not run the governed engine sidecar"),
                "{protocol} did not reach the spawn: {err}"
            );
        }
    }

    /// `brops-core` is the ONE spawn. A second `Command::new` reaching for an interpreter in the
    /// broker would be the second spawn path the unification exists to prevent, and it would not
    /// have to be wrong to be a problem — two spawns drift, and what they drift on is the trust
    /// environment and now the principal.
    #[test]
    fn the_broker_builds_no_interpreter_command_of_its_own() {
        for line in broker_code().lines() {
            assert!(
                !(line.contains("Command::new")
                    && (line.contains("python") || line.contains("sidecar"))),
                "the broker builds its own sidecar command: {line}"
            );
        }
    }

    // A fake executor that returns a verified accepted output, mirroring the broker_orchestrator test
    // pattern — lets us drive the committed path over our own schema init without the OS trust chain.
    struct OkExecutor {
        body: String,
    }
    impl GovernedExecutor for OkExecutor {
        fn execute_and_verify(
            &self,
            req: &ValidatedRequest,
            bt: &str,
            _n: &str,
        ) -> Result<(AcceptedOutput, brops_core::production_trust::TrustState), TurnReason> {
            Ok((AcceptedOutput {
                broker_turn_id: bt.to_string(),
                message_id: format!("m-{bt}"),
                conversation_id: req.conversation_id.clone(),
                author: "Bro".into(),
                accepted_body: self.body.clone(),
                envelope_body_sha256: sha256_hex(self.body.as_bytes()),
                created_at_ms: 42,
            }, brops_core::production_trust::TrustState::Production {
                key_id: "test-signer".into(),
                key_epoch: 1,
                root_key_id: "test-root".into(),
            }))
        }
    }

    struct FixedIds;
    impl BrokerIds for FixedIds {
        fn new_broker_turn_id(&self) -> String {
            "bt-fixed".into()
        }
        fn new_request_nonce(&self) -> String {
            "nonce-fixed".into()
        }
    }

    const CRID: &str = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

    fn raw(conv: &str, crid: &str) -> String {
        let proto = brops_core::governed_turn_ipc::REQUEST_PROTOCOL;
        format!(
            r#"{{"protocol":"{proto}","conversation_id":"{conv}","agent":"a","client_request_id":"{crid}"}}"#
        )
    }

    #[test]
    fn init_broker_schema_is_idempotent_and_serves_a_turn() {
        let conn = Connection::open_in_memory().unwrap();
        // Idempotent: initializing twice must succeed (every schema is CREATE TABLE IF NOT EXISTS).
        init_broker_schema(&conn).expect("first init");
        init_broker_schema(&conn).expect("second init");

        // A governed turn runs end-to-end over the freshly-initialized schema with a fake OK executor.
        let r = run_governed_turn(
            &conn,
            &raw("conv-1", CRID),
            &FixedIds,
            &OkExecutor {
                body: "hi there".into(),
            },
            1,
        );
        assert_eq!(r.status, "committed");
        let m = r.message.expect("committed message present");
        assert_eq!(m.body, "hi there");
        assert_eq!(r.broker_turn_id, "bt-fixed");
        assert_eq!(r.client_request_id, CRID);
    }

    #[test]
    fn production_executor_fails_closed_with_upstream_blocked() {
        let conn = Connection::open_in_memory().unwrap();
        init_broker_schema(&conn).unwrap();
        // The interim production executor refuses every turn closed — no fabricated accepted output.
        let r = run_governed_turn(
            &conn,
            &raw("conv-1", CRID),
            &UuidBrokerIds,
            &UpstreamBlockedExecutor,
            1,
        );
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::UpstreamBlocked));
        assert!(r.message.is_none());
        // The broker still minted a real (UUID) broker_turn_id for the refused turn.
        assert!(!r.broker_turn_id.is_empty());
    }

    #[test]
    fn malformed_request_is_blocked_not_panicked() {
        let conn = Connection::open_in_memory().unwrap();
        init_broker_schema(&conn).unwrap();
        let r = run_governed_turn(
            &conn,
            r#"{"protocol":"nope"}"#,
            &UuidBrokerIds,
            &UpstreamBlockedExecutor,
            1,
        );
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::Malformed));
    }
}
