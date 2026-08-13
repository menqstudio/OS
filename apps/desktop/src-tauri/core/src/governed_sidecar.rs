//! **The one place in this tree that starts the governed bridge sidecar.**
//!
//! # Why it is here and not in the app
//!
//! There used to be exactly one spawn seam, `ai::governed_sidecar_call`, and its own comment said
//! why that mattered: "a half-wired export, where one of the two consults the provisioned trust and
//! the other the stale committed registry, is worse than no export at all, because nothing would
//! say so." It was `async` `tokio` and it lived in `apps/desktop/src-tauri/src/`, the
//! renderer-hosting BINARY crate.
//!
//! §4.10(g) then put the submit hop in the BROKER service (§0 role #2) — a separate, synchronous
//! binary that cannot depend on a binary crate at all — and told it to spawn the sidecar "exactly as
//! `ai.rs::governed_engine` does today". "Exactly as" cannot be satisfied by a second
//! implementation: two spawns drift, and the thing they drift on is `engine_trust`. So the spawn
//! moved DOWN into `brops-core`, the crate both binaries already share, and both callers use it.
//!
//! # What "cannot be bypassed" means here, concretely
//!
//! Both constructors take a [`SidecarTrust`], which says which PROTOCOL FAMILY the spawn will
//! carry — and that is the whole of the rule, because the families are not alike:
//!
//! * [`SidecarTrust::Provisioned`] holds a [`TrustEnvironment`], whose only constructor is
//!   [`crate::engine_trust::apply`]. There is no `Default`, no public field, no second way to make
//!   one. A caller that wants to drive `bridge.task-request` or the `governance.read` op — the two
//!   shapes that reach `bro_signature.load_trusted_keys`, and through it O-3 — has nothing else to
//!   pass and does not compile. That is unchanged, and deliberately: it is a different guarantee
//!   from the shape before it, where `engine_trust::apply(&mut cmd)?` was a LINE, and deleting a
//!   line compiles.
//! * [`SidecarTrust::RelayFramesOnly`] holds nothing, and buys nothing except a NARROWER door.
//!   [`SidecarTrust::admits`] refuses, before any process exists, every request whose own top-level
//!   `protocol` is not one of [`RELAY_PROTOCOLS`] — the two frames whose handlers in
//!   `bridge/engine_sidecar.py` resolve exactly one variable between them
//!   ([`SUPERVISOR_SOCKET_VAR`]) and read none of the provisioned five. The door and the child's
//!   `_dispatch` key on the SAME field, so "pick the weak arm and send a task-request anyway" is
//!   not a thing that can be spelled. [`SidecarTrust`]'s own docs carry the argument in full.
//!
//! [`SidecarPrincipal`] is built the same way and for the same reason; see below. The two axes —
//! which principal, which protocol family — are independent, so neither can be used to obtain the
//! other by a side door.
//!
//! # Which PRINCIPAL the child runs as (§2.6)
//!
//! For a long time this builder was `Command::new(python)` and nothing else, so the sidecar ran as
//! **whatever principal called it**. For the desktop that is correct and is the only thing available:
//! the app is one process and the governed read/pull it drives is its own. For the BROKER it is a
//! defect with a name. §2.6 requires the seven runtime principals to be pairwise distinct, the live
//! kit provisions `brops-sidecar` as a seventh account for exactly that reason, and every supervisor
//! surface the §4.10(g) ladder knocks on — `governed_turn_open`, staging upload, evidence-request and
//! the §4.10(f) output read — gates on `peer_is_sidecar(peer_uid, allowed_sidecar_uid)`, a strict
//! equality against ONE configured uid. A sidecar spawned by the broker carries the broker's uid, so
//! it is refused at the first hop; and a deployment that "fixes" that by configuring the sidecar uid
//! to equal the broker uid is refused at the door instead, by
//! `governed_supervisor_server.handle_connection`'s `principal collapse` reply. There is no third
//! arrangement in which a broker-spawned-as-broker sidecar works.
//!
//! So the principal is now a FIELD, and [`SidecarPrincipal`] has no public constructor other than
//! [`SidecarPrincipal::from_config`], which validates a deployment-provisioned invoker prefix and
//! refuses by name. The two constructors say which principal they start, at every call site:
//!
//! * [`GovernedSidecar::as_calling_principal`] — this process's own principal. The DESKTOP's, and it
//!   builds exactly the command this module built before the principal existed.
//! * [`GovernedSidecar::as_distinct_principal`] — a different OS account, reached through the
//!   validated prefix. There is no value of [`SidecarPrincipal`] that means "the caller", so this
//!   constructor cannot be used to spawn as the broker "for now"; a broker that cannot resolve one
//!   has nothing to pass and serves fail-closed.
//!
//! The mechanism is the one the working reference already uses. `engine/ci/live/run_ladder_turn.sh`
//! — the seven-principal ladder that goes green in CI — becomes the sidecar with
//! `sudo -u brops-sidecar env BROPS_SUPERVISOR_SOCKET=… python3 bridge/engine_sidecar.py`, and this
//! tree's only other Rust cross-principal spawn (`chain_executor::ExecutionConfig::recorder_command`,
//! `["sudo","-n","-u","brops-recorder",…]`) is the same shape: an argv prefix out of the TCB-owned
//! deployment config, fronted by a sudoers vector. That is what [`SidecarPrincipal`] holds.
//!
//! **Why the prefix must end in `env`.** Every mechanism that changes principal also resets the child
//! environment — `sudo` does it by default (`env_reset`), and any launcher worth using does too. So
//! `Command::env()` on the invoker sets variables in the INVOKER's environment, which is exactly the
//! environment being thrown away. Under a distinct principal everything the child must read is
//! therefore materialized as explicit `NAME=VALUE` arguments, which the trailing `env` applies to the
//! interpreter it then execs — the ladder's own shape, for the ladder's own reason. What travels
//! there is whatever the spawn's [`SidecarTrust`] carries (the whole provisioned set, or nothing),
//! plus the configured [`GOVERNANCE_PATH_VARS`] and [`SUPERVISOR_SOCKET_VAR`]. The last of those is
//! why a RELAY spawn still needs the `env` tail even though it carries no trust set at all: the
//! supervisor socket is the one variable its two handlers resolve, and an inherited value is exactly
//! what the principal switch discarded.
//!
//! What that costs is stated rather than buried: those arguments are visible in the child's
//! `/proc/<pid>/cmdline`. Every member of the provisioned set is a filesystem PATH or a session id
//! (see `brops_provision::Provisioned::engine_env`) and none of them is a secret — the
//! conductor-session token is a FILE the path points at, guarded by its own 0700 tree — and the
//! socket path is a path. So this discloses layout, not key material. A set that ever gains a real
//! secret must not travel this way, and this paragraph is where that would have to be argued.
//!
//! # Synchronous, and what that costs
//!
//! `brops-core` has no `tokio` and the broker binary is synchronous, so the implementation is
//! `std::process` + threads, with the same discipline the tokio version had: stdin written on a
//! detached thread so a full stdin pipe cannot deadlock against an unread stdout pipe, both output
//! pipes drained through caps on their own threads, one ABSOLUTE deadline over the whole round
//! trip, and the child reaped on every exit path including an unwind. The app wraps it in
//! `tokio::task::spawn_blocking`.
//!
//! One property is genuinely weaker, and is stated rather than buried: `tokio`'s
//! `kill_on_drop(true)` killed the child the instant the CALLER's future was dropped. A
//! `spawn_blocking` task cannot be cancelled, so an abandoned caller now leaves the child running
//! until its own deadline or EOF. No caller in this tree cancels — `ai::governed_turn` and
//! `ai::governed_sidecar_read` are awaited directly by their commands with no `timeout`/`select!`/
//! `abort` over them, and the streaming path's cancel is a cooperative flag rather than a dropped
//! future — so the difference is not observable today. It is a real difference all the same.

use std::io::{Read, Write};
use std::path::PathBuf;
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::engine_trust::TrustEnvironment;
use crate::governed_submit::SubmitTransport;

/// Hard cap on a child's stdout stream. It TRUNCATES rather than erroring, so it must sit above the
/// largest legal reply — `governed_output_pull`'s §4.10(f) chunk reply is the biggest, and
/// [`tests::the_stdout_cap_admits_a_full_size_chunk_reply`] asserts the margin.
pub const MAX_STDOUT_BYTES: u64 = 9 * 1024 * 1024;

/// 64 KiB of stderr, kept only to quote back in a crash message.
pub const MAX_STDERR_BYTES: u64 = 64 * 1024;

/// One absolute deadline over the whole round trip — spawn to parsed reply — not a per-read one.
pub const SIDECAR_DEADLINE: Duration = Duration::from_secs(120);

/// The self-test activator that must never reach the production sidecar through inherited env.
///
/// The sidecar honours self-test via the `--self-test` CLI flag ONLY (which is never passed), and
/// this legacy variable is stripped as well, so an env-activated fabricated verifier is impossible.
pub const FAKE_SIDECAR_ENV: &str = "BRIDGE_SIDECAR_FAKE";

/// Governance directories the sidecar reads, absolutized against the process's REAL working
/// directory before the cwd override. The child runs with cwd = an empty sandbox, so a relative
/// value here would resolve against that sandbox and the sidecar would refuse a directory the owner
/// can see perfectly well from the repo.
pub const GOVERNANCE_PATH_VARS: [&str; 3] = [
    "BROPS_GOVERNANCE_STATE_DIR",
    "BROPS_GOVERNANCE_EVIDENCE_STORE",
    "BROPS_GOVERNANCE_REGISTRY_ROOT",
];

/// The ONE variable `bridge/engine_sidecar.py` resolves on both relay branches.
///
/// `_bridge_output_read` and `_bridge_governed_turn_submit` each call `_supervisor_socket_path`,
/// which reads `BROPS_SUPERVISOR_SOCKET` and nothing else; the frames themselves reach the
/// supervisor over that socket and read no other variable (see [`SidecarTrust`]). Under the §2.6
/// principal switch nothing is inherited, so a relay spawn that did not carry this one could never
/// reach a supervisor at all — which is why `engine/ci/live/run_ladder_turn.sh` spells it out in
/// exactly the same position: `sudo -u brops-sidecar env BROPS_SUPERVISOR_SOCKET=… python3 …`.
///
/// It is carried on the DISTINCT-principal arm only. The calling-principal child inherits this
/// process's environment, so it already has whatever value this process has, and adding an override
/// there would change the desktop's command.
pub const SUPERVISOR_SOCKET_VAR: &str = "BROPS_SUPERVISOR_SOCKET";

/// The two `protocol` values a spawn may carry WITHOUT the provisioned trust environment.
///
/// Taken from the modules that own them rather than re-spelled, so a rename cannot leave this
/// admission list pointing at a protocol nothing speaks any more.
pub const RELAY_PROTOCOLS: [&str; 2] = [
    crate::governed_submit::BRIDGE_SUBMIT_PROTOCOL,
    crate::governed_output_pull::BRIDGE_OUTPUT_READ_PROTOCOL,
];

fn env_nonempty(key: &str) -> Option<String> {
    std::env::var(key).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
}

// =================================================================================================
// Which PROTOCOL FAMILY the spawn will carry, and the trust that follows from it
// =================================================================================================

/// What this spawn is allowed to send, and therefore what trust material it must carry.
///
/// # Why this is not one requirement for every spawn
///
/// It used to be. Both constructors took a [`TrustEnvironment`] outright, which is correct about
/// the DESKTOP and wrong about which SPAWN needs what. `bridge/engine_sidecar.py` serves four
/// disjoint request shapes, and only two of them ever reach a reader of the provisioned set:
///
/// * `bridge.task-request` (no `protocol`, no `op`) — `_governed_turn` → `_real_callables`, the
///   frozen governed-turn path that ends at the engine.
/// * `op: governance.read` — `_op_governance_read` → `_governance_runtime`, which calls
///   `bro_signature.load_trusted_keys`. That function reads `BRO_TRUSTED_REGISTRY_ROOT` (through
///   `resolve_registry_root`), `BRO_OPERATOR_ROOT_PUBKEY_FILE` and `BRO_OPERATOR_REGISTRY_MIN_FILE`
///   (through `_resolve_operator_root_pin` / `resolve_registry_floor`), and the `bro_control_room_api`
///   import closure reaches `bro_policy`, which reads `BRO_SESSION_ID` and
///   `BRO_CONDUCTOR_SESSION_TOKEN`. That is O-3 exactly: unset, `load_trusted_keys` falls back to
///   the registry committed at `engine/config/trusted-keys.json` — `production: false`, granting
///   `conductor-session` to no key — every check passes against a registry nobody chose, and the
///   turn still reports itself as governed.
/// * `bridge.governed-turn-submit.v1` and `bridge.governed-turn-output-read.v1` — the two RELAY
///   frames. `_bridge_governed_turn_submit` and `_bridge_output_read` resolve exactly one variable
///   between them, [`SUPERVISOR_SOCKET_VAR`], and hand the frame to the supervisor over that
///   socket. Neither `bridge/governed_turn_submit.py` nor `governed_output_read.py` — nor any
///   module in either import closure — reads one of the five, and neither calls a function that
///   does. (`brops_canonical` does pull in `bro_signature`, for `canonical_bytes` alone; every env
///   read in that module lives inside `resolve_*`/`load_trusted_keys`, which nothing on these two
///   paths calls.)
///
/// So the requirement now follows the PROTOCOL rather than the caller's word.
///
/// # The escape hatch this deliberately is not
///
/// A caller does name a variant, so the obvious failure would be "the caller says it does not need
/// trust". What closes it is that naming [`SidecarTrust::RelayFramesOnly`] buys **nothing but a
/// narrower door**: [`SidecarTrust::admits`] then refuses every request whose own top-level
/// `protocol` is not one of [`RELAY_PROTOCOLS`], before a process exists.
///
/// The door and the child's dispatch key on the SAME field, which is what makes the pair airtight
/// rather than merely careful. `engine_sidecar._dispatch` tests `request["protocol"]` FIRST — the
/// output read, then the submit — and only then falls through to `op` and to the task-request. So:
///
/// * A `bridge.task-request` cannot be smuggled through this door. It has no `protocol` key and
///   cannot grow one: `bridge/contracts/task-request.schema.json` is `additionalProperties:false`.
/// * A task-request body with a relay `protocol` bolted on is not a smuggled task-request either —
///   the child routes it by that same field, to the relay handler, which is the handler that reads
///   nothing.
/// * A `governance.read` op carries no `protocol` and is refused here for the same reason.
///
/// There is therefore no request that this door admits and the child then executes on a path that
/// reads the provisioned set. The remaining strength is stated honestly rather than overclaimed: the
/// TRUSTED direction is a compile error (there is no way to build [`SidecarTrust::Provisioned`]
/// without [`crate::engine_trust::apply`], which is the only constructor of the only type it holds),
/// and the RELAY direction is a refusal at the door, decided by the frame's own bytes rather than by
/// anything the caller separately asserts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SidecarTrust {
    /// The provisioned set, whole. Required for `bridge.task-request` and for the governance read
    /// op, and harmless on a relay frame — carrying material the path does not read costs nothing.
    ///
    /// The inner value can only have come from [`crate::engine_trust::apply`]: [`TrustEnvironment`]
    /// has no `Default`, no public field and no other constructor, so this variant cannot be spelled
    /// by a caller that did not resolve the set.
    Provisioned(TrustEnvironment),
    /// No trust material, and a door that admits only [`RELAY_PROTOCOLS`].
    ///
    /// The named case is the BROKER (§0 role #2), which cannot obtain the provisioned set at all and
    /// not for want of provisioning: `BRO_CONDUCTOR_SESSION_TOKEN` binds `agent_id: "bro-000"`,
    /// `role: "bro"` — the CONDUCTOR's identity. A broker that never claims it holds an inert file;
    /// a broker that claims it has made the trusted broker service the conductor. No second token
    /// can be minted (the operator root signs one offline and the key is zeroized inside the
    /// minting scope), and the 0700 tree holding it also holds eight retained private authority
    /// seeds, so no grant yields one without the others.
    RelayFramesOnly,
}

/// The variant's own name, spelled once so the refusals below and the tests that pin them cannot
/// drift from the identifier a caller actually types.
pub const RELAY_ONLY_NAME: &str = "SidecarTrust::RelayFramesOnly";

impl SidecarTrust {
    /// The name/value pairs to set on the child. Empty for [`Self::RelayFramesOnly`], and empty is
    /// the WHOLE set there rather than a subset of one — the half-wired state `engine_trust` warns
    /// about does not arise, because there is no member to drop.
    fn pairs(&self) -> &[(&'static str, String)] {
        match self {
            Self::Provisioned(trust) => trust.pairs(),
            Self::RelayFramesOnly => &[],
        }
    }

    /// May this spawn send `request`? Decided from the REQUEST, never from a caller's assertion.
    ///
    /// [`Self::Provisioned`] admits everything: it carries what every path reads, so there is no
    /// frame it could send that would reach a stale registry. [`Self::RelayFramesOnly`] admits only
    /// a JSON object whose top-level `protocol` is one of [`RELAY_PROTOCOLS`] — and an unparseable
    /// request is a refusal, not a pass, because a request this process cannot read is a request it
    /// cannot say anything about.
    pub fn admits(&self, request: &str) -> Result<(), String> {
        match self {
            Self::Provisioned(_) => return Ok(()),
            Self::RelayFramesOnly => {}
        }
        let doc: Value = serde_json::from_str(request).map_err(|e| {
            format!(
                "this sidecar was configured {RELAY_ONLY_NAME}, so the request has to be read \
                 before it can be sent — and this one is not JSON ({e}). Refusing rather than \
                 relaying bytes whose protocol cannot be established: the whole reason this arm may \
                 skip the provisioned trust environment is that the two protocols it carries reach \
                 no reader of it."
            )
        })?;
        let protocol = doc.get("protocol").and_then(Value::as_str).unwrap_or("");
        if RELAY_PROTOCOLS.contains(&protocol) {
            return Ok(());
        }
        Err(format!(
            "this sidecar was configured {RELAY_ONLY_NAME} and carries NO provisioned trust \
             environment, but the request names protocol {protocol:?} rather than one of \
             {RELAY_PROTOCOLS:?}. `engine_sidecar._dispatch` routes anything else to \
             `bridge.task-request` or to an `op`, and both of those reach \
             `bro_signature.load_trusted_keys` — which without BRO_TRUSTED_REGISTRY_ROOT reads the \
             development registry committed at engine/config/trusted-keys.json (production: false, \
             granting conductor-session to no key) while the turn still reports itself as governed. \
             That is O-3, and it is refused here rather than run. Build this seam with \
             SidecarTrust::Provisioned(engine_trust::apply()?) to send this request."
        ))
    }
}

// =================================================================================================
// §2.6 — the principal the child runs as
// =================================================================================================

/// The `sidecar` block's key naming the OS account the child must run as.
pub const PRINCIPAL_KEY: &str = "principal";
/// The `sidecar` block's key holding the argv prefix that lands the interpreter on that account.
pub const INVOKER_KEY: &str = "invoker";
/// The program the invoker prefix must END in, because the provisioned set travels as arguments.
pub const ENV_PROGRAM: &str = "env";
/// The shortest prefix that can both change principal and materialize an environment, e.g.
/// `["/usr/bin/sudo", "-u", "brops-sidecar", "/usr/bin/env"]`.
pub const MIN_INVOKER_TOKENS: usize = 4;

/// A deployment-provisioned way to BECOME a different OS principal before `exec`ing the interpreter.
///
/// There is deliberately no variant, value or `Default` of this type that means "the calling
/// principal". [`GovernedSidecar::as_distinct_principal`] takes one by value, so a caller that could
/// not resolve one has nothing to pass and must refuse — which is the whole point. The collapse this
/// prevents is not theoretical: the supervisor answers it with `principal collapse: sidecar uid
/// equals broker uid` before it reads a frame, and every sidecar-facing service refuses a peer whose
/// uid is not the one configured sidecar uid.
///
/// It holds the account NAME as well as the prefix, and checks that the prefix names it, because an
/// argv vector alone cannot be told apart from one that changes nothing: `["/usr/bin/env"]` is a
/// perfectly well-formed prefix that spawns the sidecar as the broker.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SidecarPrincipal {
    account: String,
    invoker: Vec<String>,
}

/// POSIX-absolute or host-absolute. Spelled out rather than left to [`std::path::Path::is_absolute`]
/// alone because this describes a POSIX deployment and must validate identically when the check runs
/// on a Windows developer box, where `/usr/bin/sudo` is not `is_absolute()`.
fn is_absolute_program(token: &str) -> bool {
    token.starts_with('/') || std::path::Path::new(token).is_absolute()
}

impl SidecarPrincipal {
    /// Resolve the principal from the deployment config's `sidecar` block, or say what is wrong.
    ///
    /// Every arm below is a REFUSAL an operator can act on, and none of them has a permissive
    /// fallback. `None` — no `sidecar` block at all — is the same refusal as a malformed one: a
    /// deployment that has not said how to become the sidecar has not said it, and guessing
    /// `Command::new(python)` there is the exact defect this type exists to remove.
    pub fn from_config(sidecar_block: Option<&Value>) -> Result<Self, String> {
        let block = sidecar_block.ok_or_else(|| {
            "the deployment config has no `sidecar` block, so it never said how to become the \
             sidecar principal"
                .to_string()
        })?;
        let account = block
            .get(PRINCIPAL_KEY)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|a| !a.is_empty())
            .ok_or_else(|| {
                format!(
                    "`sidecar.{PRINCIPAL_KEY}` is not a non-empty string: §2.6 requires the sidecar \
                     to be its own OS account, and an account with no name cannot be checked for"
                )
            })?
            .to_string();
        let raw = block.get(INVOKER_KEY).and_then(Value::as_array).ok_or_else(|| {
            format!(
                "`sidecar.{INVOKER_KEY}` is not an array: it must be the argv prefix that lands the \
                 interpreter on `{account}`, e.g. \
                 [\"/usr/bin/sudo\", \"-n\", \"-u\", \"{account}\", \"/usr/bin/{ENV_PROGRAM}\"]"
            )
        })?;
        if raw.len() < MIN_INVOKER_TOKENS {
            return Err(format!(
                "`sidecar.{INVOKER_KEY}` has {} tokens; the shortest prefix that can both change \
                 principal and materialize an environment has {MIN_INVOKER_TOKENS}",
                raw.len()
            ));
        }
        let mut invoker: Vec<String> = Vec::with_capacity(raw.len());
        for (i, token) in raw.iter().enumerate() {
            let t = token.as_str().ok_or_else(|| {
                format!(
                    "`sidecar.{INVOKER_KEY}[{i}]` is not a string: every token of the invoker \
                     prefix is one argv argument, and there is no rendering of a number or an \
                     object that this could safely be assumed to have meant"
                )
            })?;
            if t.is_empty() {
                return Err(format!(
                    "`sidecar.{INVOKER_KEY}[{i}]` is empty; an empty argv token is an argument the \
                     invoker will still receive, not an absent one"
                ));
            }
            if t.contains('\0') {
                return Err(format!(
                    "`sidecar.{INVOKER_KEY}[{i}]` contains a NUL byte, which no argv token may                      carry: the spawn would then fail with an error about the interpreter rather                      than about this config"
                ));
            }
            invoker.push(t.to_string());
        }
        if !is_absolute_program(&invoker[0]) {
            return Err(format!(
                "`sidecar.{INVOKER_KEY}[0]` is `{}`, which is not an absolute path: a bare program \
                 name is resolved through the BROKER's own $PATH, and the broker's environment is \
                 not a TCB-owned input",
                invoker[0]
            ));
        }
        let last = invoker.len() - 1;
        let ends_in_env = std::path::Path::new(invoker[last].as_str())
            .file_name()
            .map(|f| f == std::ffi::OsStr::new(ENV_PROGRAM))
            .unwrap_or(false)
            || invoker[last].rsplit('/').next() == Some(ENV_PROGRAM);
        if !ends_in_env {
            return Err(format!(
                "`sidecar.{INVOKER_KEY}` ends in `{}` rather than `{ENV_PROGRAM}`: changing principal \
                 resets the child environment, so the provisioned trust set has to travel as explicit \
                 NAME=VALUE arguments, and a trailing `{ENV_PROGRAM}` is what applies them",
                invoker[last]
            ));
        }
        // The prefix must actually CHANGE principal. Position matters: at index 0 the account name
        // would be the program, and at the last index it would be standing where `env` must stand.
        if !invoker[1..last].iter().any(|t| t == &account) {
            return Err(format!(
                "`sidecar.{INVOKER_KEY}` never names the account `{account}`, so it does not change \
                 principal. A sidecar spawned as the broker collapses two §2.6 principals, which the \
                 supervisor refuses outright (`principal collapse: sidecar uid equals broker uid`) \
                 and every sidecar-facing service refuses by uid"
            ));
        }
        Ok(SidecarPrincipal { account, invoker })
    }

    /// The OS account this prefix becomes.
    pub fn account(&self) -> &str {
        &self.account
    }

    /// The validated argv prefix, `env` included.
    pub fn invoker(&self) -> &[String] {
        &self.invoker
    }
}

/// Drain `reader` to EOF or to `cap` bytes, whichever comes first.
///
/// It TRUNCATES at the cap rather than erroring, which is the behaviour the §4.10(f) reply sizing
/// argument depends on — and the reason [`MAX_STDOUT_BYTES`] must sit ABOVE the largest legal reply
/// rather than merely somewhere sensible.
///
/// A free function over `impl Read` rather than an inline `.take(N)`, so that the cap being APPLIED
/// is testable without a subprocess: a test that only pins the NUMBER passes just as well when the
/// `.take()` is gone. The cap is NOT a parameter, deliberately — a parameter is one more place to
/// pass `u64::MAX`, and that mutation survived every test in this crate when it was one.
fn read_stdout_capped<R: Read>(reader: R) -> std::io::Result<Vec<u8>> {
    let mut buf: Vec<u8> = Vec::new();
    reader.take(MAX_STDOUT_BYTES).read_to_end(&mut buf)?;
    Ok(buf)
}

/// Kill and reap the child on EVERY exit path, including an unwind.
///
/// This is the `kill_on_drop(true)` the tokio version set, kept for the scope of the round trip: a
/// read error, a deadline, or a panic must not leave the sidecar running. `std::process::Child`'s
/// own `Drop` does neither — it leaves a zombie on Unix and a live process everywhere.
struct Reaped(std::process::Child);

impl Drop for Reaped {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// A configured, trust-carrying way to run ONE `bridge/engine_sidecar.py` round trip.
///
/// Holds no child and no handle: every [`round_trip`](GovernedSidecar::round_trip) is a FRESH
/// one-shot subprocess, which is what §4.10(f) and §4.10(g) both require.
pub struct GovernedSidecar {
    python: String,
    sidecar: String,
    /// The child's working directory — an empty, owner-only sandbox, so the sidecar cannot pick up a
    /// nearby project's configuration. Supplied by the caller because creating and sweeping that
    /// sandbox is the host's job; REQUIRED, because there is no sensible default and inheriting the
    /// host's cwd is the thing the sandbox exists to prevent.
    cwd: PathBuf,
    /// What this spawn may send, and the trust material that follows from it. A
    /// [`SidecarTrust::Provisioned`] value is the proof the whole set was resolved; a
    /// [`SidecarTrust::RelayFramesOnly`] one is a narrower door rather than a weaker check.
    trust: SidecarTrust,
    /// Which OS principal the child runs as (§2.6). `None` is the CALLING principal and is not a
    /// default: it is only reachable through [`GovernedSidecar::as_calling_principal`], which names
    /// it, and the type of [`GovernedSidecar::as_distinct_principal`]'s parameter has no value that
    /// means it.
    principal: Option<SidecarPrincipal>,
}

impl GovernedSidecar {
    /// Configure the seam to run the sidecar as THIS process's own principal.
    ///
    /// The DESKTOP's constructor, and correct there: the app is one principal and the governed read
    /// and §4.10(f) pull it drives are its own. It is the wrong constructor for the broker, and the
    /// name is what makes that visible at the call site — this used to be `new`, which named nothing
    /// and read as the default.
    ///
    /// `trust` is a [`SidecarTrust`], and the desktop's is
    /// [`SidecarTrust::Provisioned`] — it drives `bridge.task-request` and the governance read op,
    /// both of which reach `bro_signature.load_trusted_keys`. The inner value can only have come
    /// from [`crate::engine_trust::apply`], so that arm is still a compile-time requirement rather
    /// than a line somebody could delete.
    pub fn as_calling_principal(
        python: &str,
        sidecar: &str,
        cwd: PathBuf,
        trust: SidecarTrust,
    ) -> Self {
        Self {
            python: python.to_string(),
            sidecar: sidecar.to_string(),
            cwd,
            trust,
            principal: None,
        }
    }

    /// Configure the seam to run the sidecar as a DIFFERENT OS principal (§2.6).
    ///
    /// The BROKER's constructor. `principal` is taken by value and [`SidecarPrincipal`] has no
    /// constructor but [`SidecarPrincipal::from_config`], so there is nothing a caller can pass here
    /// that means "as me, for now" — a broker whose deployment did not provision the invoker prefix
    /// has to refuse, which is what §2.6 requires of it.
    ///
    /// `trust` is a [`SidecarTrust`], and the broker's is
    /// [`SidecarTrust::RelayFramesOnly`] — it relays `bridge.governed-turn-submit.v1` and
    /// `bridge.governed-turn-output-read.v1`, and nothing downstream of either reads the provisioned
    /// set. That is not the caller being taken at its word: [`SidecarTrust::admits`] then refuses
    /// every request whose own `protocol` is not one of [`RELAY_PROTOCOLS`], and the child's
    /// `_dispatch` routes by that same field. The principal axis and the trust axis stay
    /// independent — a distinct-principal spawn that must drive a task-request passes
    /// [`SidecarTrust::Provisioned`] here and the set travels as arguments exactly as before.
    pub fn as_distinct_principal(
        python: &str,
        sidecar: &str,
        cwd: PathBuf,
        trust: SidecarTrust,
        principal: SidecarPrincipal,
    ) -> Self {
        Self {
            python: python.to_string(),
            sidecar: sidecar.to_string(),
            cwd,
            trust,
            principal: Some(principal),
        }
    }

    /// The fully configured child command, one step short of `spawn()`.
    ///
    /// Separated from [`round_trip`](GovernedSidecar::round_trip) so a test can READ BACK what would
    /// be launched (`Command::get_envs` / `get_current_dir` / `get_args`) without starting a python
    /// interpreter. The trust environment reaching the child is the property that matters most here,
    /// and asserting it on the real builder is the only way to notice it stop happening.
    ///
    /// It returns a `Result` because under a DISTINCT principal the provisioned set travels as
    /// `NAME=VALUE` arguments to `env`, and `env` reads the first argument WITHOUT an `=` as the
    /// program to exec — so an interpreter or script path that itself contains an `=` would be
    /// swallowed as an assignment and `env` would exec the wrong thing (or nothing). That is a
    /// refusal, not something to escape: there is no correct child to launch. On the calling-principal
    /// path nothing can fail and the arm is infallible.
    fn command(&self) -> Result<std::process::Command, String> {
        // The child runs with cwd = the empty AI sandbox, so a RELATIVE sidecar path (the default
        // `bridge/engine_sidecar.py`) would not resolve from there and every governed turn would die
        // on a spawn/path error instead of a governance decision (audit F-39). Absolutize against the
        // process's real working directory FIRST — exactly where it resolved before the sandbox-cwd
        // override existed. An absolute `BROPS_GOVERNED_SIDECAR` is used verbatim.
        let sidecar_path = {
            let p = std::path::Path::new(&self.sidecar);
            if p.is_absolute() {
                p.to_path_buf()
            } else {
                std::env::current_dir().map(|c| c.join(p)).unwrap_or_else(|_| p.to_path_buf())
            }
        };
        let mut cmd = match &self.principal {
            // ---- the CALLING principal: byte-for-byte the command this module built before the
            // principal existed. The child inherits this process's environment, so a governance path
            // that is already absolute needs no override and deliberately gets none.
            None => {
                let mut cmd = std::process::Command::new(&self.python);
                // Same trap as the sidecar path, one level along.
                for var in GOVERNANCE_PATH_VARS {
                    if let Some(v) = env_nonempty(var) {
                        let path = std::path::Path::new(&v);
                        if !path.is_absolute() {
                            if let Ok(abs) = std::env::current_dir().map(|c| c.join(path)) {
                                cmd.env(var, abs);
                            }
                        }
                    }
                }
                // O-3: hand the child the trust material first-launch provisioning minted — above all
                // `BRO_TRUSTED_REGISTRY_ROOT`, which decides WHICH trusted-key registry the engine reads.
                // Without it `bro_signature.load_trusted_keys` reads the development registry committed at
                // `engine/config/trusted-keys.json`, so every governed check runs against a registry that is
                // `production: false` and grants `conductor-session` to no key.
                //
                // There is no arm of this function that skips it: the set is a FIELD, and that field's type
                // cannot be constructed without resolving it. That is the whole reason the type exists.
                for (name, value) in self.trust.pairs() {
                    cmd.env(name, value);
                }
                cmd.arg(&sidecar_path);
                cmd
            }
            // ---- a DISTINCT principal (§2.6): the invoker prefix becomes the account and `env`
            // materializes the same set as arguments, because the principal switch discarded the
            // environment this process could otherwise have handed down. See the module docs for why
            // the prefix is required to end in `env` and what putting the set in argv costs.
            Some(principal) => {
                let interpreter = self.python.as_str();
                let script = sidecar_path.to_string_lossy().into_owned();
                for (what, token) in
                    [("sidecar.python", interpreter), ("sidecar.script", script.as_str())]
                {
                    if token.contains('=') {
                        return Err(format!(
                            "`{what}` is `{token}`, which contains `=`. Under the §2.6 principal switch \
                             the provisioned set travels as NAME=VALUE arguments to `{ENV_PROGRAM}`, and \
                             `{ENV_PROGRAM}` would read this as one more assignment rather than as the \
                             program to run"
                        ));
                    }
                }
                let mut cmd = std::process::Command::new(&principal.invoker()[0]);
                cmd.args(&principal.invoker()[1..]);
                // The SAME set as the arm above, by the same iteration over the same field — the
                // difference is only how it is delivered, which is what the principal switch changed.
                for (name, value) in self.trust.pairs() {
                    cmd.arg(format!("{name}={value}"));
                }
                // Under inheritance an already-absolute governance path arrives on its own, so the arm
                // above overrides only relative ones. Nothing is inherited here, so EVERY configured
                // one has to be carried, absolutized on the way.
                //
                // `BROPS_SUPERVISOR_SOCKET` rides with them, and on this arm ONLY. It is the single
                // variable the two relay branches resolve (`_supervisor_socket_path`), so a
                // relay spawn without it reaches no supervisor at all and refuses by name — which
                // would make this whole arm theatre. The calling-principal arm inherits the parent
                // environment and therefore already has whatever value this process has; adding an
                // override there would change the desktop's command, which nothing here may do.
                for var in GOVERNANCE_PATH_VARS.iter().copied().chain([SUPERVISOR_SOCKET_VAR]) {
                    if let Some(v) = env_nonempty(var) {
                        let path = std::path::Path::new(&v);
                        let abs = if path.is_absolute() {
                            path.to_path_buf()
                        } else {
                            std::env::current_dir()
                                .map(|c| c.join(path))
                                .unwrap_or_else(|_| path.to_path_buf())
                        };
                        cmd.arg(format!("{var}={}", abs.display()));
                    }
                }
                cmd.arg(interpreter).arg(&sidecar_path);
                cmd
            }
        };
        cmd
            // Defense in depth (Architect merge-blocker): never let a fake/self-test flag reach the
            // production sidecar via inherited env. Applied on BOTH arms, and it is the stronger half
            // of the pair under a principal switch: removing it from the INVOKER's environment means
            // there is nothing left for a permissive `env_keep`/`!env_reset` sudoers policy to keep.
            .env_remove(FAKE_SIDECAR_ENV)
            .current_dir(&self.cwd)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());
        hide_console(&mut cmd);
        Ok(cmd)
    }

    /// One round trip: spawn a fresh one-shot sidecar, hand it `request` on stdin, read its single
    /// reply. Makes no trust decision — it returns the raw parsed document.
    ///
    /// Every local failure — spawn, read, deadline, unexpected exit, non-JSON output — is an `Err`,
    /// never a document. §6.1 makes a local ingress/transport failure out-of-band, and the sidecar
    /// originates no supervisor or signature verdict; a synthesized reply here would be this process
    /// inventing the one thing §2.4 forbids it to invent.
    pub fn round_trip(&self, request: &str) -> Result<Value, String> {
        // The door, and it is BEFORE the spawn: a request this seam may not carry must not reach a
        // child at all. It is decided from the request's own `protocol` — the same field
        // `engine_sidecar._dispatch` routes on — so there is no frame this admits that the child
        // then executes on a path reading the provisioned set. See [`SidecarTrust`].
        self.trust.admits(request)?;
        let deadline = Instant::now() + SIDECAR_DEADLINE;
        let mut built = self.command()?;
        // The PROGRAM, not `self.python`: under a §2.6 principal switch the thing that failed to
        // start is the invoker (`/usr/bin/sudo`), and an operator told "could not run python3" would
        // go and look at python3. The account is named for the same reason — a permission failure on
        // this spawn is nearly always the sudoers vector for that account, not a missing interpreter.
        let program = built.get_program().to_string_lossy().into_owned();
        let becoming = match &self.principal {
            Some(p) => format!(" as `{}`", p.account()),
            None => String::new(),
        };
        let mut child = Reaped(built.spawn().map_err(|e| {
            format!(
                "Could not run the governed engine sidecar (`{program}` -> `{} {}`{becoming}): {e}. \
                 Set BROPS_GOVERNED_PYTHON / BROPS_GOVERNED_SIDECAR, or unset \
                 BROPS_ALLOW_GOVERNED_ENGINE.",
                self.python, self.sidecar
            )
        })?);

        // Feed the task-request via stdin (never argv → not in /proc/<pid>/cmdline) on a detached
        // thread, so a full stdin pipe cannot deadlock against an unread stdout pipe.
        if let Some(mut stdin) = child.0.stdin.take() {
            let bytes = request.as_bytes().to_vec();
            std::thread::spawn(move || {
                let _ = stdin.write_all(&bytes);
                // Dropping the handle closes it, so the child sees EOF.
            });
        }

        let (etx, erx) = std::sync::mpsc::channel::<String>();
        if let Some(stderr) = child.0.stderr.take() {
            std::thread::spawn(move || {
                let mut buf = String::new();
                let _ = stderr.take(MAX_STDERR_BYTES).read_to_string(&mut buf);
                let _ = etx.send(buf);
            });
        }

        let stdout = child
            .0
            .stdout
            .take()
            .ok_or_else(|| "no stdout from governed engine sidecar".to_string())?;
        let (otx, orx) = std::sync::mpsc::channel::<Result<Vec<u8>, String>>();
        std::thread::spawn(move || {
            let _ = otx.send(read_stdout_capped(stdout).map_err(|e| e.to_string()));
        });

        let obuf = match orx.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
            Ok(Ok(buf)) => buf,
            Ok(Err(e)) => return Err(e),
            Err(_) => return Err("governed engine sidecar timed out".to_string()),
        };
        // The reader returned on EOF or on the cap; the child may still be exiting. Poll to the SAME
        // absolute deadline rather than blocking in `wait()`, so a child that closes stdout and then
        // hangs cannot outlive the bound.
        let status = loop {
            match child.0.try_wait().map_err(|e| e.to_string())? {
                Some(status) => break status,
                None if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(5)),
                None => return Err("governed engine sidecar timed out".to_string()),
            }
        };
        let errbuf =
            erx.recv_timeout(deadline.saturating_duration_since(Instant::now())).unwrap_or_default();
        if !status.success() {
            return Err(format!("governed engine sidecar crashed: {}", errbuf.trim()));
        }
        let stdout = String::from_utf8_lossy(&obuf);
        serde_json::from_str(stdout.trim()).map_err(|e| format!("could not parse bridge-result ({e})"))
    }
}

/// The §4.10(g) submit hop's production transport — the same spawn, reached through the seam the
/// writer was always designed to be handed.
///
/// This closes `governed_submit`'s "**No production code implements it**". What it does NOT do is
/// give `governed_turn_submit_prepared` a CALLER: the writer stays declared unreachable in
/// `config/reachability-declarations.json`, because wiring it would move the shipped broker off its
/// fail-closed executor — a decision for the owner, not a side effect of giving a trait an
/// implementation.
impl SubmitTransport for GovernedSidecar {
    fn call(&self, frame: &Value) -> Result<Value, String> {
        let body = serde_json::to_string(frame)
            .map_err(|e| format!("the submit frame could not be serialized: {e}"))?;
        self.round_trip(&body)
    }
}

/// Windows: mark the console subprocess with CREATE_NO_WINDOW so a GUI host never flashes a console
/// window per turn. No-op elsewhere.
fn hide_console(cmd: &mut std::process::Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(not(windows))]
    {
        let _ = cmd;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsStr;

    /// The PROVISIONED arm for tests. The inner `TrustEnvironment` has its own constructor in
    /// `engine_trust` rather than a public field here, because `engine_trust::apply` reads a
    /// process-global `OnceLock` that other tests in this binary must be able to find EMPTY — the
    /// fail-closed default is itself under test there.
    fn trust() -> SidecarTrust {
        SidecarTrust::Provisioned(crate::engine_trust::test_trust_environment(vec![
            ("BRO_TRUSTED_REGISTRY_ROOT", "/anchor/registry".to_string()),
            ("BRO_CONDUCTOR_SESSION_TOKEN", "/trust/conductor-session.json".to_string()),
        ]))
    }

    /// A `bridge.task-request` — the frozen governed-turn envelope. No `protocol` key, and it cannot
    /// grow one: `bridge/contracts/task-request.schema.json` is `additionalProperties:false`.
    fn task_request() -> String {
        serde_json::json!({
            "task_id": "t-1",
            "task_class": "chat",
            "rationale": "because",
            "request": { "prompt": "hello" },
        })
        .to_string()
    }

    /// A `governance.read` op — the other shape that reaches `bro_signature.load_trusted_keys`.
    fn governance_read_op() -> String {
        serde_json::json!({
            "op": "governance.read",
            "surface": "decisionLedger",
            "read_only": true,
        })
        .to_string()
    }

    fn submit_frame() -> String {
        serde_json::json!({
            "protocol": crate::governed_submit::BRIDGE_SUBMIT_PROTOCOL,
            "run_id": "run-1",
        })
        .to_string()
    }

    fn output_read_frame() -> String {
        serde_json::json!({
            "protocol": crate::governed_output_pull::BRIDGE_OUTPUT_READ_PROTOCOL,
            "seq": 0,
        })
        .to_string()
    }

    fn sidecar() -> GovernedSidecar {
        GovernedSidecar::as_calling_principal("python", "bridge/engine_sidecar.py", PathBuf::from("."), trust())
    }

    fn envs(cmd: &std::process::Command) -> Vec<(String, Option<String>)> {
        cmd.get_envs()
            .map(|(k, v)| {
                (k.to_string_lossy().into_owned(), v.map(|v| v.to_string_lossy().into_owned()))
            })
            .collect()
    }

    /// THE property. The whole provisioned set reaches the child command, read back off the real
    /// builder rather than asserted about a copy of it. Deleting the export loop in `command()`
    /// leaves every `engine_trust` unit test green — this is what notices.
    #[test]
    fn every_provisioned_variable_reaches_the_child_command() {
        let s = sidecar();
        let got = envs(&s.command().expect("the calling-principal arm cannot fail"));
        for (name, value) in s.trust.pairs() {
            assert!(
                got.iter().any(|(k, v)| k == name && v.as_deref() == Some(value.as_str())),
                "{name} never reached the child: {got:?}"
            );
        }
    }

    /// The set is exported WHOLE. A loop that stopped early — or a `command()` that exported the
    /// registry root and dropped the session token — is the half-wired state `engine_trust`'s own
    /// docs call worse than no export at all, and a test that only looked for the interesting
    /// variable would have passed for the wrong reason.
    #[test]
    fn the_exported_set_is_whole_rather_than_its_most_interesting_member() {
        let s = sidecar();
        let got = envs(&s.command().expect("the calling-principal arm cannot fail"));
        let exported = s
            .trust
            .pairs()
            .iter()
            .filter(|(name, value)| {
                got.iter().any(|(k, v)| k == name && v.as_deref() == Some(value.as_str()))
            })
            .count();
        assert!(s.trust.pairs().len() > 1, "a one-element set cannot detect a partial export");
        assert_eq!(exported, s.trust.pairs().len(), "a proper subset was exported: {got:?}");
    }

    /// The self-test activator is REMOVED, not merely unset — `env_remove` on a command that
    /// inherits the parent environment is the only thing that stops an inherited value.
    #[test]
    fn the_fake_sidecar_activator_is_removed_from_the_child_environment() {
        let got = envs(&sidecar().command().expect("the calling-principal arm cannot fail"));
        assert!(
            got.iter().any(|(k, v)| k == FAKE_SIDECAR_ENV && v.is_none()),
            "{FAKE_SIDECAR_ENV} is not removed from the child environment: {got:?}"
        );
    }

    /// An ALREADY-absolute script path, spelled the way THIS platform spells one. `/abs/x.py` is
    /// not absolute on Windows (no drive prefix), so a hard-coded POSIX path would have taken the
    /// relative branch here and quietly tested the other case — the "bound inside a platform branch"
    /// class, in a test rather than in the code.
    fn absolute_script() -> PathBuf {
        let p = std::env::temp_dir().join("brops-abs").join("engine_sidecar.py");
        assert!(p.is_absolute(), "this platform's temp dir is not absolute: {p:?}");
        p
    }

    /// The child is contained in the directory it was given, and the script is its only argument.
    #[test]
    fn the_child_runs_in_the_supplied_sandbox_with_the_script_as_its_only_argument() {
        let dir = std::env::temp_dir().join("brops-sidecar-cwd-probe");
        let script = absolute_script();
        let s = GovernedSidecar::as_calling_principal(
            "python",
            script.to_str().expect("temp path is UTF-8"),
            dir.clone(),
            trust(),
        );
        let cmd = s.command().expect("the calling-principal arm cannot fail");
        assert_eq!(cmd.get_current_dir(), Some(dir.as_path()));
        let args: Vec<&OsStr> = cmd.get_args().collect();
        // Used VERBATIM: an absolute path is never re-joined against the process cwd.
        assert_eq!(args, vec![script.as_os_str()]);
        assert_eq!(cmd.get_program(), OsStr::new("python"));
    }

    /// A RELATIVE script path is absolutized against the process's real cwd, because the child's cwd
    /// is the sandbox and a relative path would not resolve from there (audit F-39).
    #[test]
    fn a_relative_script_path_is_absolutized_before_the_sandbox_cwd_applies() {
        let cmd = sidecar().command().expect("the calling-principal arm cannot fail");
        let args: Vec<&OsStr> = cmd.get_args().collect();
        let script = std::path::Path::new(args[0]);
        assert!(script.is_absolute(), "the script stayed relative: {script:?}");
        assert!(
            script.ends_with("engine_sidecar.py"),
            "the absolutized script is not the one that was asked for: {script:?}"
        );
        assert!(
            script.parent().is_some_and(|p| p.ends_with("bridge")),
            "the absolutized script lost its directory: {script:?}"
        );
    }

    /// The bound on this leg of the transport, stated where the bound now lives. It TRUNCATES rather
    /// than erroring, so a cap below a full §4.10(f) chunk reply would have produced a silently
    /// half-read reply rather than a failure.
    #[test]
    fn the_stdout_cap_admits_a_full_size_chunk_reply() {
        assert_eq!(MAX_STDOUT_BYTES, 9_437_184);
        assert!(
            (crate::governed_output_pull::MAX_BRIDGE_OUTPUT_READ_REPLY_BYTES as u64)
                < MAX_STDOUT_BYTES,
            "a full §4.10(f) chunk reply does not fit the child stdout cap"
        );
    }

    /// The cap is APPLIED, not merely declared. An endless reader is truncated at exactly the bound
    /// and returns rather than exhausting memory — which is what a mutation that deletes the
    /// `.take()` breaks, and what a test asserting only the NUMBER would go on passing through.
    #[test]
    fn the_stdout_cap_is_applied_to_an_endless_reader_rather_than_only_declared() {
        let endless = std::io::repeat(b'x');
        assert_eq!(read_stdout_capped(endless).unwrap().len() as u64, MAX_STDOUT_BYTES);
        // And a short reader is returned whole, so the cap is a bound and not a fixed-size read.
        assert_eq!(read_stdout_capped(&b"hi"[..]).unwrap(), b"hi");
    }

    /// A spawn that cannot happen is an `Err`, never a document — and the message names both the
    /// interpreter and the variables an operator would fix.
    #[test]
    fn an_unspawnable_interpreter_is_a_transport_error_naming_what_to_set() {
        let s = GovernedSidecar::as_calling_principal(
            "brops-no-such-interpreter-does-not-exist",
            "bridge/engine_sidecar.py",
            std::env::temp_dir(),
            trust(),
        );
        let err = s.round_trip("{}").expect_err("a missing interpreter cannot produce a reply");
        assert!(err.contains("Could not run the governed engine sidecar"), "{err}");
        assert!(err.contains("BROPS_GOVERNED_PYTHON"), "{err}");
    }

    // =============================================================================================
    // §2.6 — the principal the child runs as
    // =============================================================================================

    /// A well-formed `sidecar` block, spelled the way the working reference spells the same thing:
    /// `sudo -u brops-sidecar env … python3 bridge/engine_sidecar.py`
    /// (`engine/ci/live/run_ladder_turn.sh`, the seven-principal ladder that goes green in CI).
    fn sidecar_block() -> Value {
        serde_json::json!({
            "principal": "brops-sidecar",
            "invoker": ["/usr/bin/sudo", "-n", "-u", "brops-sidecar", "/usr/bin/env"],
        })
    }

    fn principal() -> SidecarPrincipal {
        SidecarPrincipal::from_config(Some(&sidecar_block())).expect("the reference shape resolves")
    }

    /// The sidecar script, spelled the way THIS platform spells an absolute path. `/opt/...` is not
    /// absolute on Windows (no drive prefix), so hard-coding the POSIX form would silently exercise
    /// the RELATIVE branch of the builder and every assertion below would be about a path nobody
    /// asked for. The same trap `absolute_script` exists for, one test module along.
    fn distinct_script() -> PathBuf {
        let p = std::env::temp_dir().join("brops-ladder").join("engine_sidecar.py");
        assert!(p.is_absolute(), "this platform's temp dir is not absolute: {p:?}");
        p
    }

    fn as_sidecar() -> GovernedSidecar {
        GovernedSidecar::as_distinct_principal(
            "/usr/bin/python3",
            distinct_script().to_str().expect("temp path is UTF-8"),
            PathBuf::from("."),
            trust(),
            principal(),
        )
    }

    fn args_of(cmd: &std::process::Command) -> Vec<String> {
        cmd.get_args().map(|a| a.to_string_lossy().into_owned()).collect()
    }

    /// The shape that was wrong: the calling-principal command runs the INTERPRETER, so the child
    /// carries the caller's uid. Stated as a test rather than as a comment, because it is the exact
    /// property the broker must not have — and the desktop legitimately does.
    #[test]
    fn the_calling_principal_command_runs_the_interpreter_itself() {
        let cmd = sidecar().command().expect("the calling-principal arm cannot fail");
        assert_eq!(cmd.get_program(), OsStr::new("python"));
    }

    /// THE property this round exists for. Under a distinct principal the program is the INVOKER,
    /// the account is named in the argv, and the interpreter has moved behind it — so the child's uid
    /// is the sidecar account's rather than the broker's, and `peer_is_sidecar` can succeed at all.
    #[test]
    fn the_distinct_principal_command_runs_the_invoker_and_names_the_account() {
        let cmd = as_sidecar().command().expect("the reference shape builds");
        assert_eq!(cmd.get_program(), OsStr::new("/usr/bin/sudo"));
        let args = args_of(&cmd);
        assert_eq!(&args[..4], ["-n", "-u", "brops-sidecar", "/usr/bin/env"]);
        assert_ne!(
            cmd.get_program(),
            OsStr::new("/usr/bin/python3"),
            "the interpreter is still the program, so the child would run as the broker"
        );
        assert!(
            args.contains(&"/usr/bin/python3".to_string()),
            "the interpreter never reaches the argv: {args:?}"
        );
    }

    /// The provisioned set survives the principal switch. `Command::env` would have set it on
    /// `sudo`, whose `env_reset` throws it away, so under a distinct principal every pair has to
    /// appear as a `NAME=VALUE` ARGUMENT — and it has to be the same whole set as the other arm.
    #[test]
    fn the_whole_trust_set_crosses_the_principal_switch_as_arguments() {
        let s = as_sidecar();
        let args = args_of(&s.command().expect("the reference shape builds"));
        assert!(s.trust.pairs().len() > 1, "a one-element set cannot detect a partial export");
        for (name, value) in s.trust.pairs() {
            assert!(
                args.contains(&format!("{name}={value}")),
                "{name} did not cross the principal switch: {args:?}"
            );
        }
    }

    /// Order is load-bearing in a way a set-membership assertion cannot see: `env` reads leading
    /// `NAME=VALUE` arguments and then execs the FIRST argument without an `=`. So every assignment
    /// must sit after the `env` token and before the interpreter — an assignment emitted after the
    /// interpreter would be an argument to the sidecar script instead.
    #[test]
    fn every_assignment_sits_between_the_env_token_and_the_interpreter() {
        let s = as_sidecar();
        let args = args_of(&s.command().expect("the reference shape builds"));
        let env_at = args.iter().position(|a| a == "/usr/bin/env").expect("the env token");
        let py_at = args.iter().position(|a| a == "/usr/bin/python3").expect("the interpreter");
        assert!(env_at < py_at, "the interpreter precedes `env`: {args:?}");
        for (name, value) in s.trust.pairs() {
            let at = args
                .iter()
                .position(|a| a == &format!("{name}={value}"))
                .unwrap_or_else(|| panic!("{name} is absent: {args:?}"));
            assert!(at > env_at && at < py_at, "{name} is outside env's assignment run: {args:?}");
        }
        // And nothing between them is anything BUT an assignment: one stray non-assignment token
        // there and `env` would exec it instead of the interpreter.
        for a in &args[env_at + 1..py_at] {
            assert!(a.contains('='), "a non-assignment token reached env's argument run: {a}");
        }
    }

    /// The interpreter is the last thing before the script, so `env` execs python and python runs
    /// the sidecar — not the other way round, and with no argument between them.
    #[test]
    fn the_interpreter_is_followed_only_by_the_script() {
        let s = as_sidecar();
        let args = args_of(&s.command().expect("the reference shape builds"));
        let py_at = args.iter().position(|a| a == "/usr/bin/python3").expect("the interpreter");
        assert_eq!(
            &args[py_at..],
            [
                "/usr/bin/python3".to_string(),
                distinct_script().to_string_lossy().into_owned()
            ],
            "{args:?}"
        );
    }

    /// The self-test activator is removed from the INVOKER's environment too, which is the stronger
    /// half: a permissive `env_keep`/`!env_reset` sudoers policy can only keep what `sudo` was
    /// handed, and this hands it nothing.
    #[test]
    fn the_fake_activator_is_removed_under_a_principal_switch_as_well() {
        let cmd = as_sidecar().command().expect("the reference shape builds");
        assert!(
            envs(&cmd).iter().any(|(k, v)| k == FAKE_SIDECAR_ENV && v.is_none()),
            "{FAKE_SIDECAR_ENV} is not removed from the invoker's environment"
        );
    }

    /// The sandbox cwd still applies: `sudo` inherits it and the interpreter it execs keeps it.
    #[test]
    fn the_sandbox_cwd_still_applies_under_a_principal_switch() {
        let dir = std::env::temp_dir().join("brops-sidecar-principal-cwd");
        let s = GovernedSidecar::as_distinct_principal(
            "/usr/bin/python3",
            distinct_script().to_str().expect("temp path is UTF-8"),
            dir.clone(),
            trust(),
            principal(),
        );
        let cmd = s.command().expect("the reference shape builds");
        assert_eq!(cmd.get_current_dir(), Some(dir.as_path()));
    }

    /// An interpreter path containing `=` would be eaten by `env` as one more assignment, so it is a
    /// refusal rather than a command that execs something else. There is no such hazard on the
    /// calling-principal arm, where the interpreter is the program.
    #[test]
    fn an_interpreter_path_that_env_would_read_as_an_assignment_is_refused() {
        let s = GovernedSidecar::as_distinct_principal(
            "PYTHON=/usr/bin/python3",
            distinct_script().to_str().expect("temp path is UTF-8"),
            PathBuf::from("."),
            trust(),
            principal(),
        );
        let err = s.command().expect_err("`=` in the interpreter cannot build a command");
        assert!(err.contains("sidecar.python"), "{err}");
        assert!(err.contains("env"), "{err}");
        // The same path is fine when the interpreter IS the program.
        assert!(GovernedSidecar::as_calling_principal(
            "PYTHON=/usr/bin/python3",
            distinct_script().to_str().expect("temp path is UTF-8"),
            PathBuf::from("."),
            trust(),
        )
        .command()
        .is_ok());
    }

    /// A prefix that changes no principal is the collapse in disguise, and it is well-formed argv, so
    /// only the ACCOUNT check can catch it. The refusal names the supervisor's own words.
    #[test]
    fn an_invoker_that_never_names_the_account_is_refused_by_name() {
        let block = serde_json::json!({
            "principal": "brops-sidecar",
            "invoker": ["/usr/bin/sudo", "-n", "-u", "brops-broker", "/usr/bin/env"],
        });
        let err = SidecarPrincipal::from_config(Some(&block)).expect_err("no account, no principal");
        assert!(err.contains("brops-sidecar"), "{err}");
        assert!(err.contains("principal collapse"), "{err}");
    }

    /// The account may not sit at index 0 (it would be the program) nor at the last index (it would
    /// be standing where `env` must stand) — both are prefixes that do not change principal.
    #[test]
    fn the_account_token_must_sit_inside_the_prefix_rather_than_at_either_end() {
        for invoker in [
            serde_json::json!(["brops-sidecar", "-n", "-u", "/usr/bin/env"]),
            serde_json::json!(["/usr/bin/sudo", "-n", "-u", "brops-sidecar"]),
        ] {
            let block = serde_json::json!({ "principal": "brops-sidecar", "invoker": invoker });
            assert!(
                SidecarPrincipal::from_config(Some(&block)).is_err(),
                "an end-positioned account was accepted: {invoker}"
            );
        }
    }

    /// A prefix that does not end in `env` cannot carry the provisioned set across the switch, and a
    /// silently environment-less sidecar is the half-wired state `engine_trust` calls worse than no
    /// export at all.
    #[test]
    fn an_invoker_that_does_not_end_in_env_is_refused_by_name() {
        let block = serde_json::json!({
            "principal": "brops-sidecar",
            "invoker": ["/usr/bin/sudo", "-n", "-u", "brops-sidecar", "/usr/bin/python3"],
        });
        let err = SidecarPrincipal::from_config(Some(&block)).expect_err("no env, no environment");
        assert!(err.contains(ENV_PROGRAM), "{err}");
        assert!(err.contains("/usr/bin/python3"), "{err}");
        // A bare `env` (no directory) is the same program and is accepted.
        let bare = serde_json::json!({
            "principal": "brops-sidecar",
            "invoker": ["/usr/bin/sudo", "-n", "-u", "brops-sidecar", "env"],
        });
        assert!(SidecarPrincipal::from_config(Some(&bare)).is_ok());
    }

    /// A relative `invoker[0]` is resolved through the BROKER's own `$PATH`, which is not a
    /// TCB-owned input — so the program that becomes the sidecar would be chosen by the environment
    /// of the process being constrained.
    #[test]
    fn a_relative_invoker_program_is_refused() {
        let block = serde_json::json!({
            "principal": "brops-sidecar",
            "invoker": ["sudo", "-n", "-u", "brops-sidecar", "/usr/bin/env"],
        });
        let err = SidecarPrincipal::from_config(Some(&block)).expect_err("$PATH is not TCB");
        assert!(err.contains("absolute"), "{err}");
    }

    /// Absent, malformed and empty are ONE refusal, not a spectrum: a deployment that did not say
    /// how to become the sidecar did not say it, and there is no shape here that yields a usable
    /// default. `None` is the case that matters most — it is what a config with no `sidecar` block
    /// at all produces, and the old code's answer to it was `Command::new(python)`.
    #[test]
    fn every_missing_or_malformed_shape_refuses_rather_than_defaulting() {
        let cases: Vec<(&str, Option<Value>)> = vec![
            ("no block at all", None),
            ("no principal", Some(serde_json::json!({ "invoker": ["/usr/bin/sudo", "-n", "-u", "x", "/usr/bin/env"] }))),
            ("empty principal", Some(serde_json::json!({ "principal": "   ", "invoker": ["/usr/bin/sudo", "-n", "-u", "x", "/usr/bin/env"] }))),
            ("no invoker", Some(serde_json::json!({ "principal": "brops-sidecar" }))),
            ("invoker is a string", Some(serde_json::json!({ "principal": "brops-sidecar", "invoker": "sudo -u brops-sidecar env" }))),
            ("invoker is empty", Some(serde_json::json!({ "principal": "brops-sidecar", "invoker": [] }))),
            ("invoker is too short", Some(serde_json::json!({ "principal": "brops-sidecar", "invoker": ["/usr/bin/sudo", "brops-sidecar", "/usr/bin/env"] }))),
            ("a non-string token", Some(serde_json::json!({ "principal": "brops-sidecar", "invoker": ["/usr/bin/sudo", "-u", 7, "brops-sidecar", "/usr/bin/env"] }))),
            ("an empty token", Some(serde_json::json!({ "principal": "brops-sidecar", "invoker": ["/usr/bin/sudo", "", "-u", "brops-sidecar", "/usr/bin/env"] }))),
            ("a NUL in a token", Some(serde_json::json!({ "principal": "brops-sidecar", "invoker": ["/usr/bin/sudo", "-u\u{0}", "-u", "brops-sidecar", "/usr/bin/env"] }))),
        ];
        for (what, block) in cases {
            let got = SidecarPrincipal::from_config(block.as_ref());
            let err = got.err().unwrap_or_else(|| panic!("`{what}` was accepted"));
            assert!(err.len() > 40, "`{what}` refused without saying anything useful: {err}");
        }
    }

    /// The reference shape resolves, and it keeps BOTH halves — the account is not thrown away after
    /// it is checked, because the spawn-failure message names it.
    #[test]
    fn the_reference_invocation_resolves_and_keeps_the_account() {
        let p = principal();
        assert_eq!(p.account(), "brops-sidecar");
        assert_eq!(p.invoker().len(), 5);
        assert_eq!(p.invoker()[0], "/usr/bin/sudo");
    }

    /// A spawn that cannot happen under a principal switch names the INVOKER and the ACCOUNT, not
    /// the interpreter: the interpreter is fine and looking at it is a wasted afternoon.
    #[test]
    fn a_failed_principal_switch_names_the_invoker_and_the_account() {
        let block = serde_json::json!({
            "principal": "brops-sidecar",
            "invoker": [
                "/brops-no-such-invoker-does-not-exist", "-n", "-u", "brops-sidecar", "/usr/bin/env"
            ],
        });
        let s = GovernedSidecar::as_distinct_principal(
            "python",
            "bridge/engine_sidecar.py",
            std::env::temp_dir(),
            trust(),
            SidecarPrincipal::from_config(Some(&block)).expect("well-formed"),
        );
        let err = s.round_trip("{}").expect_err("a missing invoker cannot produce a reply");
        assert!(err.contains("/brops-no-such-invoker-does-not-exist"), "{err}");
        assert!(err.contains("brops-sidecar"), "{err}");
    }

    // =============================================================================================
    // The arm is chosen by the PROTOCOL — `SidecarTrust`
    // =============================================================================================

    /// An interpreter that cannot possibly start. It is the discriminator every test below turns on:
    /// if the door were removed, the failure would be a SPAWN error naming this path, and if the door
    /// holds, the failure names the refusal and no process was ever created.
    const UNSPAWNABLE: &str = "brops-no-such-interpreter-does-not-exist";

    fn relay_seam() -> GovernedSidecar {
        GovernedSidecar::as_distinct_principal(
            UNSPAWNABLE,
            distinct_script().to_str().expect("temp path is UTF-8"),
            std::env::temp_dir(),
            SidecarTrust::RelayFramesOnly,
            principal(),
        )
    }

    /// THE test this whole round exists for. A `bridge.task-request` driven through the trust-free
    /// arm must be REFUSED, and refused before a child exists — because that path ends at
    /// `_real_callables` and, through the engine, at `bro_signature.load_trusted_keys`, which without
    /// `BRO_TRUSTED_REGISTRY_ROOT` reads the development registry committed in the tree while the
    /// turn still reports itself as governed. If this ever passes a task-request, the trust-free arm
    /// IS the escape hatch the whole design exists to prevent.
    #[test]
    fn a_task_request_cannot_be_driven_through_the_trust_free_arm() {
        let err = relay_seam()
            .round_trip(&task_request())
            .expect_err("a task-request went out through a sidecar carrying no trust environment");
        assert!(err.contains(RELAY_ONLY_NAME), "the refusal is not the door's: {err}");
        assert!(err.contains("BRO_TRUSTED_REGISTRY_ROOT"), "{err}");
        assert!(
            !err.contains("Could not run the governed engine sidecar"),
            "the request reached a SPAWN before it was refused, so the door is downstream of the \
             child rather than in front of it: {err}"
        );
        assert!(
            !err.contains(UNSPAWNABLE),
            "the failure names the interpreter, so a process was attempted: {err}"
        );
    }

    /// The other trust-reading shape, and it is a different branch of the child's dispatch: an `op`
    /// carries no `protocol` at all, so it falls through to `_OPS` and `_op_governance_read` ->
    /// `_governance_runtime` -> `load_trusted_keys`. A door that only knew about task-requests would
    /// pass this one.
    #[test]
    fn a_governance_read_op_cannot_be_driven_through_the_trust_free_arm() {
        let err = relay_seam()
            .round_trip(&governance_read_op())
            .expect_err("a governance read went out through a sidecar carrying no trust environment");
        assert!(err.contains(RELAY_ONLY_NAME), "{err}");
        assert!(
            !err.contains("Could not run the governed engine sidecar"),
            "the op reached a spawn before it was refused: {err}"
        );
    }

    /// Both relay frames ARE admitted — so the tests above cannot pass by the arm refusing
    /// everything, which is a refusal that would look identical from a distance.
    ///
    /// The second half deliberately does NOT assert which transport error fires. It used to assert
    /// "Could not run the governed engine sidecar", and that passed on Windows and failed on Linux
    /// CI: Windows has no `sudo`, so the distinct-principal invoker cannot start; Linux has one, so
    /// it starts and dies at `unknown user brops-sidecar` — a CRASH rather than a spawn failure.
    /// Same admission, different transport error. What this test owns is that the DOOR let the frame
    /// through, so all that is asserted is that the refusal is not the door's — the same shape the
    /// sibling test above already uses in the other direction.
    #[test]
    fn both_relay_frames_are_admitted_by_the_trust_free_arm() {
        for frame in [submit_frame(), output_read_frame()] {
            SidecarTrust::RelayFramesOnly
                .admits(&frame)
                .unwrap_or_else(|e| panic!("a relay frame was refused by the relay arm: {e}"));
            // And it got past the door: whatever failed next, it was the transport, not `admits`.
            let err = relay_seam().round_trip(&frame).expect_err("the interpreter cannot start");
            assert!(
                !err.contains(RELAY_ONLY_NAME),
                "a relay frame was refused by the door rather than reaching the transport: {err}"
            );
        }
    }

    /// The provisioned arm admits every shape, including the relay frames. Carrying material a path
    /// does not read costs nothing, and the desktop legitimately drives all four through one seam.
    #[test]
    fn the_provisioned_arm_admits_every_request_shape() {
        for request in
            [task_request(), governance_read_op(), submit_frame(), output_read_frame()]
        {
            trust().admits(&request).unwrap_or_else(|e| {
                panic!("the provisioned arm refused a request it carries the material for: {e}")
            });
        }
    }

    /// A request this process cannot parse is refused rather than relayed. The arm's licence to skip
    /// the trust environment rests entirely on knowing which protocol is being sent, so bytes whose
    /// protocol cannot be established are exactly the case that may not be waved through.
    #[test]
    fn a_request_that_is_not_json_is_refused_by_the_trust_free_arm() {
        let err = SidecarTrust::RelayFramesOnly.admits("not json at all").unwrap_err();
        assert!(err.contains(RELAY_ONLY_NAME), "{err}");
        assert!(err.contains("not JSON"), "{err}");
    }

    /// Near-misses, one per way of not being a relay frame. Each of them lands on a child branch that
    /// reads the provisioned set, and each is well-formed JSON, so only the protocol check catches it.
    #[test]
    fn every_near_miss_is_refused_rather_than_relayed() {
        let cases = [
            ("no protocol key", serde_json::json!({ "task_id": "t" })),
            ("a null protocol", serde_json::json!({ "protocol": serde_json::Value::Null })),
            ("a non-string protocol", serde_json::json!({ "protocol": 7 })),
            ("an empty protocol", serde_json::json!({ "protocol": "" })),
            (
                "a protocol that only starts the same",
                serde_json::json!({ "protocol": "bridge.governed-turn-submit.v1.evil" }),
            ),
            (
                "the reply protocol rather than the request one",
                serde_json::json!({ "protocol": "bridge.governed-turn-result.v1" }),
            ),
            ("a JSON array", serde_json::json!([{ "protocol": submit_frame() }])),
            ("a bare string", serde_json::json!("bridge.governed-turn-submit.v1")),
        ];
        for (what, frame) in cases {
            let Err(err) = SidecarTrust::RelayFramesOnly.admits(&frame.to_string()) else {
                panic!("`{what}` was admitted by the relay arm");
            };
            assert!(err.contains(RELAY_ONLY_NAME), "`{what}`: {err}");
        }
    }

    /// The admitted list is exactly the two protocols the CHILD dispatches by, read out of the
    /// child's own source. A drift here is the failure mode that matters: an admitted protocol the
    /// child does not route to a relay handler would fall through to the task-request branch.
    #[test]
    fn the_admitted_protocols_are_the_two_the_child_dispatches_before_anything_else() {
        let sidecar = repo_file("bridge/engine_sidecar.py");
        for protocol in RELAY_PROTOCOLS {
            assert!(
                sidecar.contains(&format!("= \"{protocol}\"")),
                "{protocol} is admitted here but is not a dispatch const in bridge/engine_sidecar.py"
            );
        }
        // Both are recognised BEFORE the `op` branch and before the task-request fall-through, which
        // is what makes "admitted here" mean "relayed there" rather than "run as a governed turn".
        let dispatch = sidecar
            .split("def _dispatch(")
            .nth(1)
            .expect("bridge/engine_sidecar.py no longer defines _dispatch");
        let submit_at = dispatch
            .find("BRIDGE_SUBMIT_PROTOCOL")
            .expect("_dispatch no longer routes the submit protocol");
        let read_at = dispatch
            .find("BRIDGE_OUTPUT_READ_PROTOCOL")
            .expect("_dispatch no longer routes the output-read protocol");
        let op_at = dispatch.find("if \"op\" not in request").expect("the op fall-through");
        assert!(
            submit_at < op_at && read_at < op_at,
            "a relay protocol is now recognised AFTER the task-request fall-through, so a frame this \
             door admits could be run as a governed turn"
        );
    }

    /// The frozen task-request cannot acquire a `protocol` key, which is what makes "no protocol ->
    /// refused" a complete rule rather than a rule with a hole in it.
    #[test]
    fn the_frozen_task_request_schema_can_never_grow_a_protocol_key() {
        let schema: Value = serde_json::from_str(&repo_file("bridge/contracts/task-request.schema.json"))
            .expect("the task-request schema is JSON");
        assert_eq!(
            schema.get("additionalProperties"),
            Some(&Value::Bool(false)),
            "the task-request schema admits extra properties, so it could grow a `protocol` key and \
             a task-request could then be admitted by the relay door"
        );
        assert!(
            schema.get("properties").and_then(|p| p.get("protocol")).is_none(),
            "the task-request schema now declares a `protocol` property"
        );
    }

    /// A file from the repository, or a PANIC. There is no skip: every path read here is committed,
    /// so an absent one is a moved file rather than an unavailable prerequisite.
    fn repo_file(rel: &str) -> String {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("..")
            .join("..");
        let path = root.join(rel);
        std::fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("{} could not be read ({e})", path.display()))
    }

    /// The relay arm carries NO trust material onto the child — not a subset, none. Read back off the
    /// real builder, because that is where a stray `env()` would live.
    #[test]
    fn a_relay_spawn_carries_no_trust_material_at_all() {
        let s = relay_seam();
        assert!(s.trust.pairs().is_empty(), "the relay arm produced trust pairs");
        let cmd = s.command().expect("the reference shape builds");
        let args = args_of(&cmd);
        for (name, _) in trust().pairs() {
            assert!(
                !args.iter().any(|a| a.starts_with(&format!("{name}="))),
                "{name} crossed the principal switch on a spawn that carries no trust: {args:?}"
            );
        }
        assert!(
            !envs(&cmd).iter().any(|(k, v)| k.starts_with("BRO_") && v.is_some()),
            "a BRO_* variable was set on the relay child's environment"
        );
    }

    /// `std::env::set_var` is process-wide and these two tests drive the SAME variable in opposite
    /// directions, so they must not interleave. Held across the whole set/build/remove window rather
    /// than around the write, which is the only span in which a concurrent reader could see it.
    static SOCKET_ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    /// The one variable the relay branches DO read has to cross the principal switch, or the arm is
    /// theatre: `sudo`'s `env_reset` discards the broker's environment, and
    /// `_supervisor_socket_path` refuses by name when the value is absent.
    #[test]
    fn the_supervisor_socket_crosses_the_principal_switch() {
        let _guard = SOCKET_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let probe = std::env::temp_dir().join("brops-supervisor-socket-probe");
        std::env::set_var(SUPERVISOR_SOCKET_VAR, &probe);
        let cmd = relay_seam().command().expect("the reference shape builds");
        std::env::remove_var(SUPERVISOR_SOCKET_VAR);
        let args = args_of(&cmd);
        let assignment = format!("{SUPERVISOR_SOCKET_VAR}={}", probe.display());
        assert!(
            args.contains(&assignment),
            "{SUPERVISOR_SOCKET_VAR} did not cross the principal switch, so the relay sidecar could \
             never reach a supervisor: {args:?}"
        );
        // And it sits inside `env`'s assignment run, or `env` would exec it.
        let env_at = args.iter().position(|a| a == "/usr/bin/env").expect("the env token");
        let py_at = args.iter().position(|a| a == UNSPAWNABLE).expect("the interpreter");
        let at = args.iter().position(|a| a == &assignment).expect("the assignment");
        assert!(at > env_at && at < py_at, "{SUPERVISOR_SOCKET_VAR} is outside env's run: {args:?}");
    }

    /// The CALLING-principal arm is untouched by that addition: it inherits the parent environment,
    /// so an override there would be a change to the desktop's command and there is none.
    ///
    /// The probe value is RELATIVE, and that is the whole force of this test. The calling-principal
    /// arm overrides only paths that are not already absolute — so an absolute probe would be
    /// invisible to the very mutation this exists to catch (extending that loop to carry the socket
    /// too), and the test would pass for a reason that is not the one it claims. That is exactly how
    /// it first failed to notice: mutant M5 survived a version of this test that used an absolute
    /// temp path.
    #[test]
    fn the_calling_principal_command_gains_no_supervisor_socket_override() {
        let _guard = SOCKET_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var(SUPERVISOR_SOCKET_VAR, "brops-relative-supervisor.sock");
        let cmd = sidecar().command().expect("the calling-principal arm cannot fail");
        std::env::remove_var(SUPERVISOR_SOCKET_VAR);
        assert!(
            !envs(&cmd).iter().any(|(k, _)| k == SUPERVISOR_SOCKET_VAR),
            "the desktop's command now overrides {SUPERVISOR_SOCKET_VAR}, which it did not before"
        );
        assert!(
            !args_of(&cmd).iter().any(|a| a.starts_with(SUPERVISOR_SOCKET_VAR)),
            "the desktop's argv gained a supervisor-socket assignment"
        );
        // The three governance variables ARE overridden when relative, and always were — so this
        // test cannot pass by the calling arm having stopped overriding anything at all.
        std::env::set_var(GOVERNANCE_PATH_VARS[0], "brops-relative-state-dir");
        let cmd = sidecar().command().expect("the calling-principal arm cannot fail");
        std::env::remove_var(GOVERNANCE_PATH_VARS[0]);
        assert!(
            envs(&cmd).iter().any(|(k, _)| k == GOVERNANCE_PATH_VARS[0]),
            "the calling arm no longer absolutizes a relative governance path either, so the \
             assertion above proves nothing"
        );
    }

    /// The self-test activator is stripped on the relay arm too. It is the one defence that is not
    /// about trust material and therefore not covered by anything above.
    #[test]
    fn the_fake_activator_is_removed_on_the_relay_arm_as_well() {
        let cmd = relay_seam().command().expect("the reference shape builds");
        assert!(
            envs(&cmd).iter().any(|(k, v)| k == FAKE_SIDECAR_ENV && v.is_none()),
            "{FAKE_SIDECAR_ENV} is not removed from a relay spawn's environment"
        );
    }

    /// The transport trait goes through the same door: `SubmitTransport::call` serializes and calls
    /// `round_trip`, so it cannot become a second way in that skips the protocol check.
    #[test]
    fn the_submit_transport_cannot_carry_a_task_request_on_the_relay_arm() {
        let frame: Value = serde_json::from_str(&task_request()).expect("the fixture is JSON");
        let err = SubmitTransport::call(&relay_seam(), &frame)
            .expect_err("a task-request went out through the transport trait");
        assert!(err.contains(RELAY_ONLY_NAME), "{err}");
        assert!(
            !err.contains("Could not run the governed engine sidecar"),
            "the transport trait reaches a spawn before the door: {err}"
        );
    }

    /// The transport half of §4.10(g): the frame is serialized and goes through the SAME round trip,
    /// so a submit cannot acquire its own spawn discipline.
    #[test]
    fn the_submit_transport_is_the_same_spawn() {
        let s = GovernedSidecar::as_calling_principal(
            "brops-no-such-interpreter-does-not-exist",
            "bridge/engine_sidecar.py",
            std::env::temp_dir(),
            trust(),
        );
        let err = SubmitTransport::call(&s, &serde_json::json!({ "protocol": "x" }))
            .expect_err("a missing interpreter cannot produce a reply");
        assert!(err.contains("Could not run the governed engine sidecar"), "{err}");
    }
}
