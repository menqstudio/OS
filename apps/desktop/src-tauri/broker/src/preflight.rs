//! **Provisioning preflight**: which of the governed turn's prerequisites does THIS machine meet?
//!
//! # Why this exists
//!
//! `build_governed_executor` (`broker/src/main.rs`) is a ladder of 15 `return fail_closed()`
//! branches. That is correct — the broker must never serve a governed turn it cannot back — but it
//! is *illegible*: every one of those branches produces the same observable, a `blocked` reply, and
//! several of them produce it before anything is printed. An operator who wants to know **why** a
//! machine cannot run a governed turn has to read Rust and then guess which branch fired first.
//!
//! This module answers the question directly and by name: it walks the SAME requirement set, reports
//! each one as met / not met / not measurable **on this platform**, and says who would have to
//! provision it. It is a REPORT. It writes nothing, provisions nothing, and cannot make any governed
//! surface reachable — see [`Host`], whose whole surface is reads.
//!
//! # What it deliberately does not do
//!
//! * **It does not provision.** Twelve of the requirements below can only be created by a machine
//!   administrator (service accounts, a setuid launcher, a sudoers vector, root-owned TCB material),
//!   one only by the holder of the offline TCB root private key, and one not on a machine at all.
//!   An installer that "provisioned" the other thirteen would produce a config that still ends in
//!   `fail_closed()` — with the gap now hidden behind a file that looks complete.
//! * **It does not weaken anything.** A requirement this machine cannot meet is reported as not met.
//!   There is no "close enough" status and no way to pass a check by declaring it inapplicable.
//! * **It is not a proof that a turn would complete.** Every requirement here is necessary; the set
//!   is not sufficient. `Met` on all of them means the broker would get past `build_governed_executor`
//!   — not that the seven-principal chain behind it answers. Only a real run witnesses that, which
//!   is what `engine/ci/live/run_ladder_turn.sh` is for.
//!
//! # One contract, one implementation
//!
//! The requirement set is not a second opinion about what the broker needs. Every configuration key
//! named here is in [`CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR`], and a test in this module
//! extracts the key literals out of `main.rs`'s own source and fails if the two sets differ in either
//! direction. The §2.5 artifact roster is not copied at all — it is
//! [`brops_core::tcb_integrity::TCB_REQUIRED_ARTIFACTS`] itself.

use std::collections::BTreeSet;

use brops_core::key_manifest::{verify_manifest, KeyManifest, PinnedRoot};
use brops_core::tcb_integrity::{TcbPinManifest, TCB_REQUIRED_ARTIFACTS};
use serde_json::Value;

/// Who, on a real deployment, is able to create a requirement.
///
/// This is the honest split between "an application installer could do this" and "it needs an
/// authority a desktop application does not have and cannot acquire by asking nicely".
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provisioner {
    /// A user-space installer, running as the installing user, can create this.
    Installer,
    /// Only a machine administrator (root, or an installer elevated to it) can create this: OS
    /// accounts, setuid bits, a sudoers vector, root-owned files under a root-owned directory.
    MachineAdministrator,
    /// Only the holder of the OFFLINE TCB root private key, in a signing ceremony. The public half is
    /// compiled into this binary (`crate::tcb`); the private half is deliberately not on any machine
    /// that runs the product.
    OfflineRootCustodian,
    /// Nothing on any machine can create it — it is a property of the shipped BINARY, and changing it
    /// is a code change behind the Owner's gate.
    NotProvisionableOnAMachine,
}

impl Provisioner {
    pub fn as_str(self) -> &'static str {
        match self {
            Provisioner::Installer => "installer",
            Provisioner::MachineAdministrator => "machine-admin",
            Provisioner::OfflineRootCustodian => "offline-root-custodian",
            Provisioner::NotProvisionableOnAMachine => "not-provisionable",
        }
    }
}

/// The verdict for one requirement.
///
/// [`Status::Unmeasurable`] is NOT a pass. It means the preflight refused to guess: either the
/// platform cannot express the question (no `AF_UNIX`, no uid ownership) or witnessing the answer
/// would require an action the preflight will not take (spawning a process under `sudo`). A report
/// containing one is a report that cannot say the machine is ready — see [`Report::exit_code`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Status {
    /// Measured on this machine, and present. `evidence` says what was actually observed.
    Met { evidence: String },
    /// Measured on this machine, and absent or wrong. `because` names the gap.
    NotMet { because: String },
    /// Not measurable here, with the reason. Never a pass.
    Unmeasurable { because: String },
}

impl Status {
    pub fn met(evidence: impl Into<String>) -> Status {
        Status::Met { evidence: evidence.into() }
    }
    pub fn not_met(because: impl Into<String>) -> Status {
        Status::NotMet { because: because.into() }
    }
    pub fn unmeasurable(because: impl Into<String>) -> Status {
        Status::Unmeasurable { because: because.into() }
    }
    pub fn is_met(&self) -> bool {
        matches!(self, Status::Met { .. })
    }
    fn tag(&self) -> &'static str {
        match self {
            Status::Met { .. } => "MET",
            Status::NotMet { .. } => "NOT MET",
            Status::Unmeasurable { .. } => "UNMEASURABLE",
        }
    }
    fn detail(&self) -> &str {
        match self {
            Status::Met { evidence } => evidence,
            Status::NotMet { because } => because,
            Status::Unmeasurable { because } => because,
        }
    }
}

/// One prerequisite of a governed turn.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Requirement {
    /// Stable dotted name. Used in reports and in tests; never localized.
    pub name: &'static str,
    /// What the deployment must actually have.
    pub what: &'static str,
    /// Who can create it (see [`Provisioner`]).
    pub provisioner: Provisioner,
    /// The refusal in the product that fires when this is missing — so a reader can go and check
    /// that the requirement is real rather than believing this table.
    pub refusal: &'static str,
}

/// Every prerequisite, in the order `build_governed_executor` would meet them.
///
/// `Provisioner` is the column that matters: thirteen `installer`, eleven `machine-admin`, one
/// `offline-root-custodian`, two `not-provisionable`.
pub const REQUIREMENTS: &[Requirement] = &[
    // ---- platform + OS topology -------------------------------------------------------------
    Requirement {
        name: "platform.linux_af_unix_peercred",
        what: "a host with AF_UNIX and SO_PEERCRED, because the renderer→broker trust boundary is a \
               kernel-attested peer credential and nothing else",
        provisioner: Provisioner::NotProvisionableOnAMachine,
        refusal: "broker/src/main.rs `run()` off Linux → EXIT_PLATFORM_UNSUPPORTED; \
                  src/governed_turn.rs `connect_broker` → UnsupportedPlatform",
    },
    Requirement {
        name: "principals.seven_distinct_accounts",
        what: "seven pairwise-distinct OS service accounts (broker, challenge, sidecar, supervisor, \
               recorder, signer, executor) that exist on this machine",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "§2.6; governed_supervisor_server.handle_connection refuses a principal collapse, \
                  and every supervisor surface gates on a strict uid equality",
    },
    Requirement {
        name: "principals.sidecar_distinct_from_broker",
        what: "the sidecar account is not the broker account",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "handle_connection: `principal collapse: sidecar uid equals broker uid`",
    },
    Requirement {
        name: "principals.tcb_floor_covers_the_sidecar",
        what: "the `uids` block names the sidecar's uid, so the §2.5 floor asks whether the SIDECAR \
               can write a TCB artifact",
        provisioner: Provisioner::Installer,
        refusal: "main.rs builds the floor's principal set from `uids` values + the login uid; a uid \
                  absent from that set is never asked about",
    },
    Requirement {
        name: "launcher.setuid_root_binary",
        what: "a setuid-root privileged launcher owned by uid 0",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "§6.1 step 5: the contained execution is entered through the setuid launcher; \
                  without it there is no contained execution to record",
    },
    Requirement {
        name: "sudoers.broker_may_become_the_sidecar",
        what: "a sudoers vector letting the broker principal exec the interpreter AS the sidecar \
               account, with an exact argument vector",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "GovernedSidecar::as_distinct_principal builds that argv; without the grant the \
                  spawn fails and the turn blocks",
    },
    Requirement {
        name: "store.supervisor_private_0700",
        what: "the supervisor's durable ledger directory, owned by the supervisor account and \
               readable by nobody else (0700)",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "F-01: the acceptance/lease/completion state the run attestation is rebuilt from \
                  must not be writable by the party being attested",
    },
    // ---- the deployment config ----------------------------------------------------------------
    Requirement {
        name: "env.brops_broker_config",
        what: "$BROPS_BROKER_CONFIG names a deployment config",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "main.rs: `Ok(p) if !p.is_empty() => p, _ => return fail_closed()`",
    },
    Requirement {
        name: "config.parses_as_json",
        what: "that file is readable and parses as JSON",
        provisioner: Provisioner::Installer,
        refusal: "main.rs: `config unreadable/malformed at {path} — serving fail-closed`",
    },
    Requirement {
        name: "trust.tcb_pin_manifest_path",
        what: "`trust.tcb_pin_manifest_path` (or $BROPS_TCB_PIN_MANIFEST) names a readable §2.5 pin \
               manifest",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "main.rs: `TCB integrity floor REFUSED` → fail_closed()",
    },
    Requirement {
        name: "trust.tcb_pin_manifest_covers_the_required_set",
        what: "that manifest pins every artifact in TCB_REQUIRED_ARTIFACTS — an omitted artifact is \
               never measured, so it must not pass by omission",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "tcb_integrity::TcbViolation::MissingRequired",
    },
    Requirement {
        name: "trust.manifest_path",
        what: "`trust.manifest_path` names a readable key manifest that deserializes as a KeyManifest",
        provisioner: Provisioner::Installer,
        refusal: "main.rs: `let manifest: KeyManifest = ... None => return fail_closed()`",
    },
    Requirement {
        name: "trust.manifest_sig_path",
        what: "`trust.manifest_sig_path` names a readable detached root signature",
        provisioner: Provisioner::Installer,
        refusal: "main.rs: `None => return fail_closed()`",
    },
    Requirement {
        name: "trust.floor_path",
        what: "`trust.floor_path` names a readable, parseable anti-rollback floor",
        provisioner: Provisioner::Installer,
        refusal: "main.rs: `parse_floor_json(&b) ... None => return fail_closed()`",
    },
    Requirement {
        name: "trust.floor_is_broker_owned_0600",
        what: "the floor file is owned by the broker principal and writable by nobody else, because \
               the resolver WRITES the advanced floor back and a persist failure refuses the turn",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "main.rs's own comment: floor_path \"MUST be owned by / writable only by the broker \
                  service principal (file mode 0600, dedicated UID)\"; else \
                  `blocked:keys:floor_not_persisted`",
    },
    Requirement {
        name: "trust.signer_key_id",
        what: "`trust.signer_key_id` names the receipt-signing key to resolve out of the manifest",
        provisioner: Provisioner::Installer,
        refusal: "ProductionResolver::provisioned resolves it per turn; an empty id resolves nothing",
    },
    Requirement {
        name: "trust.supervisor_attestation_key_id",
        what: "`trust.supervisor_attestation_key_id` names the supervisor attestation key",
        provisioner: Provisioner::Installer,
        refusal: "same resolver, second key",
    },
    Requirement {
        name: "sockets.authority",
        what: "`sockets.authority` names the challenge authority's AF_UNIX socket, and it is there",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "main.rs: `None => return fail_closed()`; a named-but-absent socket blocks at the \
                  §4.1 hop instead",
    },
    Requirement {
        name: "content.messages_db",
        what: "`content.messages_db` names the conversation database the three artifact digests are \
               DERIVED from",
        provisioner: Provisioner::Installer,
        refusal: "main.rs: `content.messages_db is not configured - the ladder cannot derive this \
                  conversation's digests, so there is nothing honest to sign`",
    },
    Requirement {
        name: "content.system",
        what: "`content.system` is a non-empty system prompt",
        provisioner: Provisioner::Installer,
        refusal: "main.rs: `Some(v) if !v.is_empty() => v, _ => return fail_closed()`",
    },
    Requirement {
        name: "content.window",
        what: "`content.window` is a positive message window",
        provisioner: Provisioner::Installer,
        refusal: "main.rs: `.filter(|w| *w > 0) ... None => return fail_closed()`",
    },
    Requirement {
        name: "sidecar.spawn_triple",
        what: "`sidecar.python`, `sidecar.script` and `sidecar.cwd` all exist on disk",
        provisioner: Provisioner::Installer,
        refusal: "main.rs: the `(Some, Some, Some)` match arm; anything else → fail_closed()",
    },
    Requirement {
        name: "sidecar.principal_and_invoker",
        what: "`sidecar.principal` names the sidecar account and `sidecar.invoker` is an absolute-\
               program argv prefix that lands the interpreter on it",
        provisioner: Provisioner::Installer,
        refusal: "SidecarPrincipal::from_config — there is no value of it meaning \"as me\", and \
                  main.rs prints the reason before serving fail-closed",
    },
    Requirement {
        name: "resolved.identifiers",
        what: "`resolved.workspace_id`, `install_id`, `run_id`, `task_id` and `requested_at_ms` are \
               populated — they are defaulted rather than refused, so an empty one is signed",
        provisioner: Provisioner::Installer,
        refusal: "none: main.rs uses `.unwrap_or_default()`. This requirement exists BECAUSE there \
                  is no refusal — an unset id becomes an empty string inside a real receipt",
    },
    Requirement {
        name: "db.durable_acceptance_ledger",
        what: "the broker's SQLite file — derived from its socket argv, NOT from config — is \
               openable, so replay defence survives a restart",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "main.rs: `durable acceptance ledger unavailable at {db_path} ({e}) - serving \
                  fail-closed`",
    },
    // ---- custody ------------------------------------------------------------------------------
    Requirement {
        name: "custody.tcb_root_manifest_signature",
        what: "the key manifest verifies under the root PINNED IN THIS BINARY — whose private half is \
               the Owner's offline root, held on no machine that runs the product",
        provisioner: Provisioner::OfflineRootCustodian,
        refusal: "ProductionResolver::provisioned pins crate::tcb::ROOT_KEY_ID; a manifest under any \
                  other root resolves UnknownRoot / RootSignatureInvalid",
    },
    Requirement {
        name: "custody.committed_label_resolver",
        what: "a custody resolver, so a committed reply can carry a custody label",
        provisioner: Provisioner::NotProvisionableOnAMachine,
        refusal: "main.rs builds `ChainExecutor::new`, not `with_custody`, so committed_label() is \
                  None and persist_committed REFUSES under EVERY value of the config. No \
                  provisioning changes this; it is an owner-gated code decision",
    },
];

/// Every configuration key `build_governed_executor` actually reads, dotted.
///
/// A test in this module extracts the key literals from `main.rs`'s own source and fails if this
/// list and that source disagree in either direction. That is the whole anti-drift story: this list
/// is a mirror, and a mirror that cannot be checked is how one contract acquires two implementations.
///
/// `db.path` is deliberately ABSENT: the broker derives its database path from its socket argv
/// (`socket_path.replace(".sock", ".db")`) and never reads a `db` block. The live kit writes one for
/// the proof driver, which is a different consumer.
pub const CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR: &[&str] = &[
    "content.messages_db",
    "content.system",
    "content.window",
    "resolved.author",
    "resolved.generation_config_sha256",
    "resolved.history_sha256",
    "resolved.install_id",
    "resolved.requested_at",
    "resolved.requested_at_ms",
    "resolved.run_id",
    "resolved.system_sha256",
    "resolved.task_id",
    "resolved.workspace_id",
    "sidecar",
    "sidecar.cwd",
    "sidecar.python",
    "sidecar.script",
    "sockets.authority",
    "trust.floor_path",
    "trust.manifest_path",
    "trust.manifest_sig_path",
    "trust.signer_key_id",
    "trust.supervisor_attestation_key_id",
    "trust.tcb_pin_manifest_path",
    "uids",
];

/// Facts about one path. Deliberately the smallest set the requirements are stated in.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PathFacts {
    pub owner_uid: u32,
    /// POSIX mode bits, including the setuid bit.
    pub mode: u32,
    pub is_dir: bool,
}

/// Everything the preflight is allowed to learn about the world. Every method is a READ; there is
/// deliberately no way to write a file, set a variable or spawn a process from here.
pub trait Host {
    /// Is this a host where the governed path's OS primitives exist at all?
    fn platform_is_linux(&self) -> bool;
    /// A short platform name for the report header.
    fn platform_name(&self) -> String;
    fn env(&self, name: &str) -> Option<String>;
    fn read(&self, path: &str) -> Option<Vec<u8>>;
    /// `None` when the path is absent, unreadable, or when the platform has no uid ownership.
    fn stat(&self, path: &str) -> Option<PathFacts>;
    /// Resolve an OS account name to a uid. `None` when there is no such account (or no such
    /// concept on this platform).
    fn account_uid(&self, name: &str) -> Option<u32>;
}

/// The real host.
pub struct RealHost;

impl Host for RealHost {
    fn platform_is_linux(&self) -> bool {
        cfg!(target_os = "linux")
    }

    fn platform_name(&self) -> String {
        std::env::consts::OS.to_string()
    }

    fn env(&self, name: &str) -> Option<String> {
        std::env::var(name).ok().filter(|v| !v.is_empty())
    }

    fn read(&self, path: &str) -> Option<Vec<u8>> {
        std::fs::read(path).ok()
    }

    #[cfg(unix)]
    fn stat(&self, path: &str) -> Option<PathFacts> {
        use std::os::unix::fs::MetadataExt;
        // `symlink_metadata`, not `metadata`: a symlink into a TCB path is exactly the substitution
        // the §2.5 floor opens O_NOFOLLOW to refuse, and a preflight that follows it would report a
        // reassuring owner for a file the broker will not accept.
        let md = std::fs::symlink_metadata(path).ok()?;
        Some(PathFacts {
            owner_uid: md.uid(),
            mode: md.mode(),
            is_dir: md.is_dir(),
        })
    }

    #[cfg(not(unix))]
    fn stat(&self, _path: &str) -> Option<PathFacts> {
        // No uid ownership to report. Every caller of `stat` is gated on `platform_is_linux`, so
        // this never becomes a silent NotMet.
        None
    }

    #[cfg(target_os = "linux")]
    fn account_uid(&self, name: &str) -> Option<u32> {
        let c = std::ffi::CString::new(name).ok()?;
        // SAFETY: `getpwnam` reads the passwd database and returns a pointer into a static buffer
        // owned by libc; we only read `pw_uid` out of it before any other libc call can clobber it.
        let pw = unsafe { libc::getpwnam(c.as_ptr()) };
        if pw.is_null() {
            return None;
        }
        Some(unsafe { (*pw).pw_uid })
    }

    #[cfg(not(target_os = "linux"))]
    fn account_uid(&self, _name: &str) -> Option<u32> {
        None
    }
}

/// One requirement and what this machine had to say about it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finding {
    pub requirement: Requirement,
    pub status: Status,
}

/// The whole report: exactly one [`Finding`] per [`REQUIREMENTS`] entry, in table order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Report {
    pub platform: String,
    pub findings: Vec<Finding>,
}

impl Report {
    pub fn met(&self) -> usize {
        self.findings.iter().filter(|f| f.status.is_met()).count()
    }
    pub fn not_met(&self) -> Vec<&Finding> {
        self.findings
            .iter()
            .filter(|f| matches!(f.status, Status::NotMet { .. }))
            .collect()
    }
    pub fn unmeasurable(&self) -> Vec<&Finding> {
        self.findings
            .iter()
            .filter(|f| matches!(f.status, Status::Unmeasurable { .. }))
            .collect()
    }

    /// `0` only when every requirement was MEASURED and MET. `1` when something is not met; `2` when
    /// nothing is not met but something could not be measured — which is still not "ready", and the
    /// distinct code is so a caller cannot collapse the two.
    pub fn exit_code(&self) -> i32 {
        if !self.not_met().is_empty() {
            1
        } else if !self.unmeasurable().is_empty() {
            2
        } else {
            0
        }
    }

    /// A plain-text report. One line per requirement, then the summary.
    pub fn render(&self) -> String {
        let mut out = String::new();
        out.push_str(&format!(
            "BroPS governed-turn provisioning preflight\nplatform: {}\nrequirements: {}\n\n",
            self.platform,
            self.findings.len()
        ));
        for f in &self.findings {
            out.push_str(&format!(
                "[{:<12}] {:<48} ({})\n               {}\n",
                f.status.tag(),
                f.requirement.name,
                f.requirement.provisioner.as_str(),
                f.status.detail()
            ));
        }
        let nm = self.not_met();
        let um = self.unmeasurable();
        out.push_str(&format!(
            "\nmet {} / not met {} / unmeasurable {} of {}\n",
            self.met(),
            nm.len(),
            um.len(),
            self.findings.len()
        ));
        if !nm.is_empty() {
            out.push_str("\nNOT MET, by name:\n");
            for f in &nm {
                out.push_str(&format!(
                    "  - {} [{}]\n",
                    f.requirement.name,
                    f.requirement.provisioner.as_str()
                ));
            }
        }
        if !um.is_empty() {
            out.push_str("\nNOT MEASURABLE here, by name (not a pass):\n");
            for f in &um {
                out.push_str(&format!(
                    "  - {} [{}]\n",
                    f.requirement.name,
                    f.requirement.provisioner.as_str()
                ));
            }
        }
        out.push_str(
            "\nThis is a report over NECESSARY conditions. All-met does not mean a governed turn \
             completes;\nonly a real run witnesses that. Nothing here provisions, flips or weakens \
             anything.\n",
        );
        out
    }
}

// ---------------------------------------------------------------------------------------------
// The evaluation
// ---------------------------------------------------------------------------------------------

/// Small helper over the parsed config, mirroring `main.rs`'s `s` / `i` closures.
struct Cfg(Option<Value>);

impl Cfg {
    fn s(&self, path: &[&str]) -> Option<String> {
        let mut cur = self.0.as_ref()?;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_str().map(|x| x.to_string())
    }
    fn i(&self, path: &[&str]) -> Option<i64> {
        let mut cur = self.0.as_ref()?;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_i64()
    }
    fn get(&self, key: &str) -> Option<&Value> {
        self.0.as_ref()?.get(key)
    }
    fn present(&self) -> bool {
        self.0.is_some()
    }
}

/// Evaluate every requirement against `host`.
///
/// `socket_path` is the broker's listening socket as the launcher would pass it in argv. It is
/// `Option` because the broker's database path is derived from it and from nothing else: without it
/// the ledger requirement is honestly unmeasurable rather than guessed.
pub fn evaluate(host: &dyn Host, socket_path: Option<&str>) -> Report {
    let config_path = host.env("BROPS_BROKER_CONFIG");
    let raw = config_path.as_deref().and_then(|p| host.read(p));
    let cfg = Cfg(raw
        .as_ref()
        .and_then(|b| std::str::from_utf8(b).ok())
        .and_then(|s| serde_json::from_str::<Value>(s).ok()));

    let mut findings = Vec::with_capacity(REQUIREMENTS.len());
    for req in REQUIREMENTS {
        let status = match req.name {
            "platform.linux_af_unix_peercred" => check_platform(host),
            "principals.seven_distinct_accounts" => check_seven_accounts(host, &cfg),
            "principals.sidecar_distinct_from_broker" => check_sidecar_distinct(host, &cfg),
            "principals.tcb_floor_covers_the_sidecar" => check_floor_covers_sidecar(host, &cfg),
            "launcher.setuid_root_binary" => check_setuid_launcher(host, &cfg),
            "sudoers.broker_may_become_the_sidecar" => check_sudoers(host, &cfg),
            "store.supervisor_private_0700" => check_supervisor_store(host, &cfg),
            "env.brops_broker_config" => check_env(config_path.as_deref()),
            "config.parses_as_json" => check_config_parses(config_path.as_deref(), &raw, &cfg),
            "trust.tcb_pin_manifest_path" => check_pin_manifest_path(host, &cfg),
            "trust.tcb_pin_manifest_covers_the_required_set" => check_pin_coverage(host, &cfg),
            "trust.manifest_path" => check_manifest(host, &cfg),
            "trust.manifest_sig_path" => check_manifest_sig(host, &cfg),
            "trust.floor_path" => check_floor(host, &cfg),
            "trust.floor_is_broker_owned_0600" => check_floor_custody(host, &cfg),
            "trust.signer_key_id" => check_str_key(&cfg, &["trust", "signer_key_id"]),
            "trust.supervisor_attestation_key_id" => {
                check_str_key(&cfg, &["trust", "supervisor_attestation_key_id"])
            }
            "sockets.authority" => check_authority_socket(host, &cfg),
            "content.messages_db" => check_messages_db(host, &cfg),
            "content.system" => check_system_prompt(&cfg),
            "content.window" => check_window(&cfg),
            "sidecar.spawn_triple" => check_spawn_triple(host, &cfg),
            "sidecar.principal_and_invoker" => check_sidecar_principal(host, &cfg),
            "resolved.identifiers" => check_resolved(&cfg),
            "db.durable_acceptance_ledger" => check_ledger(host, socket_path),
            "custody.tcb_root_manifest_signature" => check_root_custody(host, &cfg),
            "custody.committed_label_resolver" => check_custody_resolver(),
            other => Status::unmeasurable(format!(
                "no measurement is wired for `{other}` — this is a bug in the preflight, not a \
                 property of the machine"
            )),
        };
        findings.push(Finding { requirement: *req, status });
    }

    Report { platform: host.platform_name(), findings }
}

fn check_platform(host: &dyn Host) -> Status {
    if host.platform_is_linux() {
        Status::met("linux: AF_UNIX + SO_PEERCRED available")
    } else {
        Status::not_met(format!(
            "{} has no AF_UNIX SO_PEERCRED peer authentication, so the renderer→broker trust \
             boundary cannot be enforced at all. There is no configuration of this machine that \
             meets this requirement",
            host.platform_name()
        ))
    }
}

/// The seven §2.6 principals: the six in the `uids` block plus the sidecar named by
/// `sidecar.principal`.
fn uid_set(host: &dyn Host, cfg: &Cfg) -> (BTreeSet<u32>, Option<u32>, usize) {
    let mut uids = BTreeSet::new();
    let mut declared = 0usize;
    if let Some(map) = cfg.get("uids").and_then(|v| v.as_object()) {
        for v in map.values() {
            declared += 1;
            if let Some(u) = v.as_u64() {
                uids.insert(u as u32);
            }
        }
    }
    let sidecar = cfg
        .s(&["sidecar", "principal"])
        .and_then(|a| host.account_uid(&a));
    (uids, sidecar, declared)
}

fn check_seven_accounts(host: &dyn Host, cfg: &Cfg) -> Status {
    if !host.platform_is_linux() {
        return Status::unmeasurable(
            "OS service accounts with distinct uids are a POSIX concept; this platform has no uid \
             for the preflight to resolve",
        );
    }
    if !cfg.present() {
        return Status::not_met("no readable deployment config, so no principal set is declared");
    }
    let (mut uids, sidecar, declared) = uid_set(host, cfg);
    let sidecar_uid = match sidecar {
        Some(u) => u,
        None => {
            return Status::not_met(format!(
                "`sidecar.principal` does not resolve to an account on this machine (the `uids` \
                 block declares {declared})"
            ))
        }
    };
    uids.insert(sidecar_uid);
    if uids.len() == 7 {
        Status::met(format!("seven distinct uids: {uids:?}"))
    } else {
        Status::not_met(format!(
            "§2.6 needs seven pairwise-distinct principals; this deployment resolves {} distinct \
             uids ({uids:?}) from a `uids` block declaring {declared} entries plus the sidecar",
            uids.len()
        ))
    }
}

fn check_sidecar_distinct(host: &dyn Host, cfg: &Cfg) -> Status {
    if !host.platform_is_linux() {
        return Status::unmeasurable("no uids on this platform to compare");
    }
    let broker = cfg.i(&["uids", "broker"]).map(|u| u as u32);
    let sidecar = cfg
        .s(&["sidecar", "principal"])
        .and_then(|a| host.account_uid(&a));
    match (broker, sidecar) {
        (Some(b), Some(s)) if b != s => {
            Status::met(format!("broker uid {b} ≠ sidecar uid {s}"))
        }
        (Some(b), Some(s)) => Status::not_met(format!(
            "principal collapse: broker and sidecar are both uid {b} (sidecar {s}); \
             handle_connection refuses this outright"
        )),
        (None, _) => Status::not_met("`uids.broker` is not declared, so the collapse cannot be ruled out"),
        (_, None) => Status::not_met("`sidecar.principal` does not resolve to an account"),
    }
}

fn check_floor_covers_sidecar(host: &dyn Host, cfg: &Cfg) -> Status {
    if !host.platform_is_linux() {
        return Status::unmeasurable("no uids on this platform to compare");
    }
    let (uids, sidecar, declared) = uid_set(host, cfg);
    let sidecar_uid = match sidecar {
        Some(u) => u,
        None => return Status::not_met("`sidecar.principal` does not resolve to an account"),
    };
    if uids.contains(&sidecar_uid) {
        Status::met(format!("the `uids` block names the sidecar uid {sidecar_uid}"))
    } else {
        Status::not_met(format!(
            "the sidecar runs as uid {sidecar_uid} and the `uids` block ({declared} entries: \
             {uids:?}) does not name it, so the §2.5 floor never asks whether the SIDECAR can write \
             a TCB artifact"
        ))
    }
}

fn check_setuid_launcher(host: &dyn Host, cfg: &Cfg) -> Status {
    if !host.platform_is_linux() {
        return Status::unmeasurable("there is no setuid bit on this platform");
    }
    // NOTE: `execution.launcher_path` is NOT read by `build_governed_executor` (the ladder moved the
    // privileged spawn to the supervisor). It is used here only to LOCATE the artifact this machine
    // requirement is about.
    let path = match cfg.s(&["execution", "launcher_path"]) {
        Some(p) => p,
        None => {
            return Status::not_met(
                "no deployment key names the privileged launcher (`execution.launcher_path`), so \
                 the preflight cannot find the binary the contained execution is entered through",
            )
        }
    };
    match host.stat(&path) {
        None => Status::not_met(format!("{path} is absent or unreadable")),
        Some(f) if f.owner_uid != 0 => Status::not_met(format!(
            "{path} is owned by uid {} — a setuid binary not owned by root grants that uid, not \
             root",
            f.owner_uid
        )),
        Some(f) if f.mode & 0o4000 == 0 => Status::not_met(format!(
            "{path} is not setuid (mode {:o}); the launcher cannot enter the contained execution",
            f.mode & 0o7777
        )),
        Some(f) => Status::met(format!("{path} is root-owned setuid (mode {:o})", f.mode & 0o7777)),
    }
}

fn check_sudoers(host: &dyn Host, cfg: &Cfg) -> Status {
    let invoker = cfg
        .get("sidecar")
        .and_then(|s| s.get("invoker"))
        .and_then(|v| v.as_array())
        .cloned();
    let program = match invoker.as_ref().and_then(|a| a.first()).and_then(|v| v.as_str()) {
        Some(p) => p.to_string(),
        None => {
            return Status::not_met(
                "`sidecar.invoker` names no program, so there is no argument vector for a grant to \
                 authorize",
            )
        }
    };
    if !host.platform_is_linux() {
        return Status::unmeasurable("there is no sudoers on this platform");
    }
    if host.stat(&program).is_none() {
        return Status::not_met(format!(
            "the invoker program {program} is not on this machine, so no grant can make the \
             principal switch work"
        ));
    }
    Status::unmeasurable(format!(
        "{program} exists, but only an attempted spawn AS the broker principal witnesses the grant \
         itself, and this preflight spawns nothing. Verify by hand with `sudo -n -l -U <broker>`"
    ))
}

fn check_supervisor_store(host: &dyn Host, cfg: &Cfg) -> Status {
    if !host.platform_is_linux() {
        return Status::unmeasurable("no POSIX ownership or mode bits on this platform");
    }
    let ledger = match cfg.s(&["supervisor", "ledger_db"]) {
        Some(p) => p,
        None => {
            return Status::not_met(
                "no deployment key names the supervisor's durable ledger \
                 (`supervisor.ledger_db`)",
            )
        }
    };
    let dir = match ledger.rfind('/') {
        Some(i) if i > 0 => ledger[..i].to_string(),
        _ => return Status::not_met(format!("`supervisor.ledger_db` ({ledger}) has no directory")),
    };
    match host.stat(&dir) {
        None => Status::not_met(format!("{dir} is absent")),
        Some(f) if !f.is_dir => Status::not_met(format!("{dir} is not a directory")),
        Some(f) if f.mode & 0o077 != 0 => Status::not_met(format!(
            "{dir} is mode {:o}: the supervisor's own acceptance/lease state is readable or \
             writable by a principal that is not the supervisor",
            f.mode & 0o7777
        )),
        Some(f) => Status::met(format!(
            "{dir} is 0{:o}, owned by uid {}",
            f.mode & 0o7777,
            f.owner_uid
        )),
    }
}

fn check_env(config_path: Option<&str>) -> Status {
    match config_path {
        Some(p) => Status::met(format!("$BROPS_BROKER_CONFIG={p}")),
        None => Status::not_met(
            "$BROPS_BROKER_CONFIG is unset or empty. Nothing in the shipped product writes it, so \
             this is the state of every shipped install and the fail-closed executor is what serves",
        ),
    }
}

fn check_config_parses(config_path: Option<&str>, raw: &Option<Vec<u8>>, cfg: &Cfg) -> Status {
    match (config_path, raw, cfg.present()) {
        (None, _, _) => Status::not_met("no path to read (see env.brops_broker_config)"),
        (Some(p), None, _) => Status::not_met(format!("{p} is unreadable")),
        (Some(p), Some(_), false) => Status::not_met(format!("{p} does not parse as JSON")),
        (Some(p), Some(b), true) => Status::met(format!("{p} parses ({} bytes)", b.len())),
    }
}

fn pin_manifest_path(host: &dyn Host, cfg: &Cfg) -> Option<String> {
    cfg.s(&["trust", "tcb_pin_manifest_path"])
        .or_else(|| host.env(crate::tcb_probe::TCB_PIN_MANIFEST_ENV))
}

fn check_pin_manifest_path(host: &dyn Host, cfg: &Cfg) -> Status {
    let path = match pin_manifest_path(host, cfg) {
        Some(p) => p,
        None => {
            return Status::not_met(
                "neither `trust.tcb_pin_manifest_path` nor $BROPS_TCB_PIN_MANIFEST names a pin \
                 manifest, so the §2.5 floor has nothing to measure and refuses",
            )
        }
    };
    match host.read(&path) {
        None => Status::not_met(format!("{path} is absent or unreadable")),
        Some(b) => match serde_json::from_slice::<TcbPinManifest>(&b) {
            Ok(m) => Status::met(format!("{path} parses, pinning {} artifacts", m.artifacts.len())),
            Err(e) => Status::not_met(format!("{path} does not deserialize as a pin manifest: {e}")),
        },
    }
}

fn check_pin_coverage(host: &dyn Host, cfg: &Cfg) -> Status {
    let path = match pin_manifest_path(host, cfg) {
        Some(p) => p,
        None => return Status::not_met("no pin manifest to check coverage of"),
    };
    let manifest: TcbPinManifest = match host
        .read(&path)
        .and_then(|b| serde_json::from_slice::<TcbPinManifest>(&b).ok())
    {
        Some(m) => m,
        None => return Status::not_met(format!("{path} is absent or does not deserialize")),
    };
    // The roster is the real constant, not a copy of it.
    let missing = manifest.missing_required();
    if missing.is_empty() {
        Status::met(format!(
            "all {} required artifacts are pinned",
            TCB_REQUIRED_ARTIFACTS.len()
        ))
    } else {
        Status::not_met(format!(
            "{} of {} required artifacts are unpinned and would therefore never be measured: {}",
            missing.len(),
            TCB_REQUIRED_ARTIFACTS.len(),
            missing.join(", ")
        ))
    }
}

fn read_manifest(host: &dyn Host, cfg: &Cfg) -> Result<KeyManifest, String> {
    let path = cfg
        .s(&["trust", "manifest_path"])
        .ok_or_else(|| "`trust.manifest_path` is not configured".to_string())?;
    let bytes = host
        .read(&path)
        .ok_or_else(|| format!("{path} is absent or unreadable"))?;
    serde_json::from_slice::<KeyManifest>(&bytes)
        .map_err(|e| format!("{path} does not deserialize as a KeyManifest: {e}"))
}

fn check_manifest(host: &dyn Host, cfg: &Cfg) -> Status {
    match read_manifest(host, cfg) {
        Ok(m) => Status::met(format!(
            "root {} epoch {} with {} keys",
            m.root_key_id,
            m.manifest_epoch,
            m.keys.len()
        )),
        Err(e) => Status::not_met(e),
    }
}

fn check_manifest_sig(host: &dyn Host, cfg: &Cfg) -> Status {
    let path = match cfg.s(&["trust", "manifest_sig_path"]) {
        Some(p) => p,
        None => return Status::not_met("`trust.manifest_sig_path` is not configured"),
    };
    match host.read(&path) {
        None => Status::not_met(format!("{path} is absent or unreadable")),
        Some(b) if b.iter().all(|c| c.is_ascii_whitespace()) => {
            Status::not_met(format!("{path} is empty"))
        }
        Some(b) => Status::met(format!("{path} holds {} bytes of detached signature", b.len())),
    }
}

fn check_floor(host: &dyn Host, cfg: &Cfg) -> Status {
    let path = match cfg.s(&["trust", "floor_path"]) {
        Some(p) => p,
        None => return Status::not_met("`trust.floor_path` is not configured"),
    };
    match host.read(&path) {
        None => Status::not_met(format!("{path} is absent or unreadable")),
        Some(b) => match brops_core::key_manifest::parse_floor_json(&b) {
            Some(f) => Status::met(format!(
                "{path} parses: highest_epoch {}",
                f.highest_epoch
            )),
            None => Status::not_met(format!(
                "{path} does not parse as an anti-rollback floor; an unparseable floor is never \
                 read as \"no floor required\""
            )),
        },
    }
}

fn check_floor_custody(host: &dyn Host, cfg: &Cfg) -> Status {
    if !host.platform_is_linux() {
        return Status::unmeasurable("no POSIX ownership or mode bits on this platform");
    }
    let path = match cfg.s(&["trust", "floor_path"]) {
        Some(p) => p,
        None => return Status::not_met("`trust.floor_path` is not configured"),
    };
    let broker_uid = cfg.i(&["uids", "broker"]).map(|u| u as u32);
    match (host.stat(&path), broker_uid) {
        (None, _) => Status::not_met(format!("{path} is absent")),
        (_, None) => Status::not_met("`uids.broker` is not declared, so ownership cannot be judged"),
        (Some(f), Some(b)) if f.owner_uid != b => Status::not_met(format!(
            "{path} is owned by uid {} but the broker runs as {b}; the resolver writes the advanced \
             floor back by temp-file + rename in that directory, and a persist failure refuses the \
             turn (blocked:keys:floor_not_persisted)",
            f.owner_uid
        )),
        (Some(f), Some(_)) if f.mode & 0o077 != 0 => Status::not_met(format!(
            "{path} is mode {:o}: the anti-rollback boundary here IS the OS write-protection, so a \
             floor another principal can write is no floor",
            f.mode & 0o7777
        )),
        (Some(f), Some(b)) => Status::met(format!(
            "{path} is 0{:o} owned by the broker uid {b}",
            f.mode & 0o7777
        )),
    }
}

fn check_str_key(cfg: &Cfg, path: &[&str]) -> Status {
    match cfg.s(path).filter(|v| !v.trim().is_empty()) {
        Some(v) => Status::met(format!("{} = {v}", path.join("."))),
        None => Status::not_met(format!(
            "`{}` is unset or empty; the resolver would look up a key with no id",
            path.join(".")
        )),
    }
}

fn check_authority_socket(host: &dyn Host, cfg: &Cfg) -> Status {
    let path = match cfg.s(&["sockets", "authority"]) {
        Some(p) => p,
        None => return Status::not_met("`sockets.authority` is not configured"),
    };
    if !host.platform_is_linux() {
        return Status::unmeasurable(format!(
            "`sockets.authority` names {path}, but this platform has no AF_UNIX socket for it to be"
        ));
    }
    match host.stat(&path) {
        Some(_) => Status::met(format!("{path} exists")),
        None => Status::not_met(format!(
            "{path} does not exist, so the §4.1 challenge hop has nothing to dial"
        )),
    }
}

fn check_messages_db(host: &dyn Host, cfg: &Cfg) -> Status {
    let path = match cfg.s(&["content", "messages_db"]) {
        Some(p) => p,
        None => return Status::not_met(
            "`content.messages_db` is not configured; the ladder cannot derive this conversation's \
             digests, so there is nothing honest to sign",
        ),
    };
    match host.stat(&path) {
        Some(f) if !f.is_dir => Status::met(format!("{path} exists")),
        Some(_) => Status::not_met(format!("{path} is a directory, not a database")),
        None => Status::not_met(format!("{path} does not exist")),
    }
}

fn check_system_prompt(cfg: &Cfg) -> Status {
    match cfg.s(&["content", "system"]).filter(|v| !v.is_empty()) {
        Some(v) => Status::met(format!("{} characters", v.chars().count())),
        None => Status::not_met("`content.system` is unset or empty"),
    }
}

fn check_window(cfg: &Cfg) -> Status {
    match cfg.i(&["content", "window"]) {
        Some(w) if w > 0 => Status::met(format!("window = {w}")),
        Some(w) => Status::not_met(format!("`content.window` is {w}; it must be positive")),
        None => Status::not_met("`content.window` is unset or not an integer"),
    }
}

fn check_spawn_triple(host: &dyn Host, cfg: &Cfg) -> Status {
    let mut missing = Vec::new();
    let mut present = Vec::new();
    for key in ["python", "script", "cwd"] {
        match cfg.s(&["sidecar", key]) {
            None => missing.push(format!("`sidecar.{key}` is unset")),
            Some(p) => {
                if host.stat(&p).is_some() {
                    present.push(format!("{key}={p}"));
                } else {
                    missing.push(format!("`sidecar.{key}` names {p}, which is absent"));
                }
            }
        }
    }
    if missing.is_empty() {
        Status::met(present.join(", "))
    } else {
        Status::not_met(missing.join("; "))
    }
}

fn check_sidecar_principal(host: &dyn Host, cfg: &Cfg) -> Status {
    // The ONE constructor, reused rather than re-validated: a second opinion about what a valid
    // principal block is would be exactly the duplicated contract this repository keeps finding.
    match brops_core::governed_sidecar::SidecarPrincipal::from_config(cfg.get("sidecar")) {
        Err(why) => Status::not_met(why),
        Ok(_) => {
            let account = cfg.s(&["sidecar", "principal"]).unwrap_or_default();
            if !host.platform_is_linux() {
                return Status::unmeasurable(format!(
                    "the block is well-formed and names `{account}`, but this platform has no \
                     account to resolve it to"
                ));
            }
            match host.account_uid(&account) {
                Some(u) => Status::met(format!("`{account}` resolves to uid {u}")),
                None => Status::not_met(format!(
                    "the block is well-formed but `{account}` is not an account on this machine"
                )),
            }
        }
    }
}

fn check_resolved(cfg: &Cfg) -> Status {
    let mut empty = Vec::new();
    for key in ["workspace_id", "install_id", "run_id", "task_id"] {
        if cfg.s(&["resolved", key]).filter(|v| !v.is_empty()).is_none() {
            empty.push(format!("resolved.{key}"));
        }
    }
    if cfg.i(&["resolved", "requested_at_ms"]).unwrap_or(0) <= 0 {
        empty.push("resolved.requested_at_ms".to_string());
    }
    if empty.is_empty() {
        Status::met("workspace/install/run/task ids and requested_at_ms are all populated")
    } else {
        Status::not_met(format!(
            "{} would be defaulted rather than refused, so an empty value ends up inside a real \
             receipt: {}",
            empty.len(),
            empty.join(", ")
        ))
    }
}

fn check_ledger(host: &dyn Host, socket_path: Option<&str>) -> Status {
    let socket = match socket_path {
        Some(s) => s,
        None => {
            return Status::unmeasurable(
                "the broker derives its database path from its socket ARGV, not from config, so \
                 without the socket path there is no file to check. Re-run with --socket <path>",
            )
        }
    };
    let db = socket.replace(".sock", ".db");
    let dir = match db.rfind(['/', '\\']) {
        Some(i) if i > 0 => db[..i].to_string(),
        _ => return Status::not_met(format!("{db} has no parent directory")),
    };
    match host.stat(&dir) {
        Some(f) if f.is_dir => Status::met(format!(
            "{dir} exists, so the ledger at {db} has somewhere to live"
        )),
        Some(_) => Status::not_met(format!("{dir} is not a directory")),
        None => Status::not_met(format!(
            "{dir} does not exist, so the durable acceptance ledger cannot be opened at {db} and \
             the broker serves fail-closed"
        )),
    }
}

fn check_root_custody(host: &dyn Host, cfg: &Cfg) -> Status {
    let manifest = match read_manifest(host, cfg) {
        Ok(m) => m,
        Err(e) => return Status::not_met(format!("no manifest to verify: {e}")),
    };
    let sig = match cfg
        .s(&["trust", "manifest_sig_path"])
        .and_then(|p| host.read(&p))
        .and_then(|b| String::from_utf8(b).ok())
    {
        Some(s) => s.trim().to_string(),
        None => return Status::not_met("no readable detached root signature to verify"),
    };
    let pinned = PinnedRoot {
        root_key_id: crate::tcb::ROOT_KEY_ID.to_string(),
        public_key_hex: crate::tcb::ROOT_PUBLIC_KEY_HEX.to_string(),
    };
    match verify_manifest(&manifest, &sig, &pinned) {
        Ok(()) => Status::met(format!(
            "the manifest verifies under the binary-pinned production root {}",
            crate::tcb::ROOT_KEY_ID
        )),
        Err(e) => Status::not_met(format!(
            "the manifest names root `{}` and does not verify under the root pinned in this binary \
             (`{}`): {e:?}. The private half of that root is the Owner's OFFLINE key; no \
             provisioning step on this machine can produce this signature",
            manifest.root_key_id,
            crate::tcb::ROOT_KEY_ID
        )),
    }
}

fn check_custody_resolver() -> Status {
    Status::not_met(
        "build_governed_executor constructs `ChainExecutor::new`, not `with_custody`, so \
         committed_label() is None and persist_committed refuses under EVERY value of the config. \
         This is a property of the shipped binary: no machine can provision it, and changing it is \
         an owner-gated code decision",
    )
}

// ---------------------------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    /// A host whose every answer is injected — so every requirement can be driven to MET, NOT MET
    /// and (where it exists) UNMEASURABLE without root, without accounts and without a kit.
    #[derive(Default)]
    struct FakeHost {
        linux: bool,
        env: BTreeMap<String, String>,
        files: BTreeMap<String, Vec<u8>>,
        stats: BTreeMap<String, PathFacts>,
        accounts: BTreeMap<String, u32>,
    }

    impl FakeHost {
        fn linux() -> FakeHost {
            FakeHost { linux: true, ..Default::default() }
        }
        fn env(mut self, k: &str, v: &str) -> Self {
            self.env.insert(k.into(), v.into());
            self
        }
        fn file(mut self, path: &str, body: &str) -> Self {
            self.files.insert(path.into(), body.as_bytes().to_vec());
            self.stats.entry(path.into()).or_insert(PathFacts {
                owner_uid: 0,
                mode: 0o100644,
                is_dir: false,
            });
            self
        }
        fn stat(mut self, path: &str, owner_uid: u32, mode: u32, is_dir: bool) -> Self {
            self.stats.insert(path.into(), PathFacts { owner_uid, mode, is_dir });
            self
        }
        fn account(mut self, name: &str, uid: u32) -> Self {
            self.accounts.insert(name.into(), uid);
            self
        }
    }

    impl Host for FakeHost {
        fn platform_is_linux(&self) -> bool {
            self.linux
        }
        fn platform_name(&self) -> String {
            if self.linux { "linux".into() } else { "windows".into() }
        }
        fn env(&self, name: &str) -> Option<String> {
            self.env.get(name).cloned()
        }
        fn read(&self, path: &str) -> Option<Vec<u8>> {
            self.files.get(path).cloned()
        }
        fn stat(&self, path: &str) -> Option<PathFacts> {
            self.stats.get(path).cloned()
        }
        fn account_uid(&self, name: &str) -> Option<u32> {
            self.accounts.get(name).copied()
        }
    }

    fn status_of<'a>(report: &'a Report, name: &str) -> &'a Status {
        &report
            .findings
            .iter()
            .find(|f| f.requirement.name == name)
            .unwrap_or_else(|| panic!("no finding for {name}"))
            .status
    }

    // ---- structure -------------------------------------------------------------------------

    #[test]
    fn every_requirement_name_is_unique() {
        let names: BTreeSet<&str> = REQUIREMENTS.iter().map(|r| r.name).collect();
        assert_eq!(names.len(), REQUIREMENTS.len(), "duplicate requirement name");
    }

    #[test]
    fn the_report_carries_exactly_one_finding_per_requirement_in_table_order() {
        let report = evaluate(&FakeHost::default(), None);
        assert_eq!(report.findings.len(), REQUIREMENTS.len());
        for (f, r) in report.findings.iter().zip(REQUIREMENTS.iter()) {
            assert_eq!(f.requirement.name, r.name);
        }
    }

    /// The defect this whole module exists to prevent: a measurement that is wired for no
    /// requirement, or a requirement that falls through to the catch-all arm. The catch-all returns
    /// a status whose text names itself as a preflight bug, so assert no finding carries it.
    #[test]
    fn no_requirement_falls_through_to_the_unwired_arm() {
        for host in [FakeHost::default(), FakeHost::linux()] {
            let report = evaluate(&host, None);
            for f in &report.findings {
                assert!(
                    !f.status.detail().contains("no measurement is wired"),
                    "{} has no measurement",
                    f.requirement.name
                );
            }
        }
    }

    /// A preflight that cannot report a failure is the defect this repository is named for finding.
    /// On a bare Linux machine with nothing provisioned, the ONLY requirement that may come back MET
    /// is the platform itself — every other row must be NOT MET or UNMEASURABLE.
    #[test]
    fn a_bare_machine_meets_nothing_but_the_platform() {
        let report = evaluate(&FakeHost::linux(), None);
        let met: Vec<&str> = report
            .findings
            .iter()
            .filter(|f| f.status.is_met())
            .map(|f| f.requirement.name)
            .collect();
        assert_eq!(met, vec!["platform.linux_af_unix_peercred"], "{}", report.render());
        assert_eq!(report.exit_code(), 1);
    }

    /// And on a bare NON-Linux machine, nothing at all is met.
    #[test]
    fn a_bare_non_linux_machine_meets_nothing_at_all() {
        let report = evaluate(&FakeHost::default(), None);
        assert_eq!(report.met(), 0, "something passed off Linux: {}", report.render());
        assert_eq!(report.exit_code(), 1);
    }

    #[test]
    fn an_unmeasurable_report_is_not_a_pass() {
        // Not-met=0 but unmeasurable>0 must not be exit 0.
        let report = Report {
            platform: "windows".into(),
            findings: vec![Finding {
                requirement: REQUIREMENTS[0],
                status: Status::unmeasurable("no"),
            }],
        };
        assert_eq!(report.exit_code(), 2);
        assert!(report.render().contains("NOT MEASURABLE here"));
    }

    // ---- the drift gate --------------------------------------------------------------------

    /// Extract every configuration key `build_governed_executor` reads, out of its OWN source, and
    /// require it to be exactly [`CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR`].
    ///
    /// This is the anti-duplication gate. A new `s(&["trust","something"])` in `main.rs` fails this
    /// test until the preflight is told about it, and a key removed from `main.rs` fails it until
    /// the preflight stops claiming it.
    #[test]
    fn the_config_key_mirror_does_not_drift_from_main_rs() {
        let src = include_str!("main.rs");
        let mut found: BTreeSet<String> = BTreeSet::new();

        // `s(&["a", "b"])` / `i(&["a", "b"])`
        for marker in ["s(&[", "i(&["] {
            let mut rest = src;
            while let Some(i) = rest.find(marker) {
                let after = &rest[i + marker.len()..];
                let end = after.find(']').expect("unterminated key path in main.rs");
                let parts: Vec<String> = after[..end]
                    .split(',')
                    .map(|p| p.trim().trim_matches('"').to_string())
                    .filter(|p| !p.is_empty())
                    .collect();
                if !parts.is_empty() {
                    found.insert(parts.join("."));
                }
                rest = &after[end..];
            }
        }
        // `cfg.get("a")` — including the form `cfg` NEWLINE `.get("a")`, which is how `uids` is
        // actually written. Matching only the one-line spelling is how a drift gate silently stops
        // covering a key.
        let mut scan = 0usize;
        while let Some(rel) = src[scan..].find(".get(\"") {
            let at = scan + rel;
            let before = src[..at].trim_end();
            let after = &src[at + ".get(\"".len()..];
            let end = after.find('"').expect("unterminated .get( in main.rs");
            if before.ends_with("cfg") {
                found.insert(after[..end].to_string());
            }
            scan = at + ".get(\"".len() + end;
        }

        let declared: BTreeSet<String> = CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR
            .iter()
            .map(|k| k.to_string())
            .collect();
        let unknown: Vec<&String> = found.difference(&declared).collect();
        let stale: Vec<&String> = declared.difference(&found).collect();
        assert!(
            unknown.is_empty(),
            "main.rs reads config keys the preflight does not know about: {unknown:?}"
        );
        assert!(
            stale.is_empty(),
            "the preflight claims config keys main.rs does not read: {stale:?}"
        );
    }

    #[test]
    fn main_rs_still_gates_on_the_two_environment_variables_this_module_reports() {
        let src = include_str!("main.rs");
        assert!(src.contains("std::env::var(\"BROPS_BROKER_CONFIG\")"));
        assert!(src.contains("tcb_probe::TCB_PIN_MANIFEST_ENV"));
    }

    #[test]
    fn the_tcb_roster_is_the_real_constant_not_a_copy() {
        // If this ever needs updating, the roster was copied. It is referenced directly.
        assert!(TCB_REQUIRED_ARTIFACTS.contains(&"privileged-launcher.bin"));
        assert!(TCB_REQUIRED_ARTIFACTS.len() >= 20);
    }

    // ---- platform ---------------------------------------------------------------------------

    #[test]
    fn a_non_linux_host_cannot_meet_the_platform_requirement_and_says_so() {
        let report = evaluate(&FakeHost::default(), None);
        match status_of(&report, "platform.linux_af_unix_peercred") {
            Status::NotMet { because } => {
                assert!(because.contains("no AF_UNIX"), "{because}");
                assert!(because.contains("no configuration of this machine"), "{because}");
            }
            other => panic!("expected NotMet, got {other:?}"),
        }
        // and the POSIX-shaped requirements are UNMEASURABLE rather than silently not-met
        assert!(matches!(
            status_of(&report, "principals.seven_distinct_accounts"),
            Status::Unmeasurable { .. }
        ));
        assert!(matches!(
            status_of(&report, "launcher.setuid_root_binary"),
            Status::Unmeasurable { .. }
        ));
    }

    #[test]
    fn a_linux_host_meets_the_platform_requirement() {
        let report = evaluate(&FakeHost::linux(), None);
        assert!(status_of(&report, "platform.linux_af_unix_peercred").is_met());
    }

    // ---- env + config ------------------------------------------------------------------------

    #[test]
    fn an_absent_config_variable_is_reported_by_name() {
        let report = evaluate(&FakeHost::linux(), None);
        match status_of(&report, "env.brops_broker_config") {
            Status::NotMet { because } => assert!(because.contains("$BROPS_BROKER_CONFIG is unset")),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn a_present_but_unreadable_config_is_distinguished_from_an_unparseable_one() {
        let unreadable = FakeHost::linux().env("BROPS_BROKER_CONFIG", "/nope.json");
        let r = evaluate(&unreadable, None);
        assert!(status_of(&r, "env.brops_broker_config").is_met());
        // The STATUS, not only the text: a mutant that reported "unreadable" as MET survived an
        // assertion that only read the message.
        let s = status_of(&r, "config.parses_as_json");
        assert!(matches!(s, Status::NotMet { .. }), "{s:?}");
        assert!(s.detail().contains("unreadable"));

        let garbage = FakeHost::linux()
            .env("BROPS_BROKER_CONFIG", "/cfg.json")
            .file("/cfg.json", "{ not json");
        let r = evaluate(&garbage, None);
        let s = status_of(&r, "config.parses_as_json");
        assert!(matches!(s, Status::NotMet { .. }), "{s:?}");
        assert!(s.detail().contains("does not parse"));
    }

    // ---- a fully provisioned fake deployment --------------------------------------------------

    /// The kit's shape, reduced to what the preflight reads. Every requirement that a machine CAN
    /// meet is met here — which is what makes the negative tests below meaningful.
    fn provisioned() -> FakeHost {
        let manifest = r#"{"manifest_epoch":2,"root_key_id":"brops-live-root-1","keys":[]}"#;
        let pin = serde_json::to_string(&TcbPinManifest {
            artifacts: TCB_REQUIRED_ARTIFACTS
                .iter()
                .map(|n| brops_core::tcb_integrity::TcbArtifact {
                    logical_name: (*n).to_string(),
                    path: format!("/opt/brops-live/tcb/{n}"),
                    expected_sha256: "0".repeat(64),
                    expected_owner: brops_core::tcb_integrity::TcbOwner::Root,
                })
                .collect(),
            owner_uids: [(brops_core::tcb_integrity::TcbOwner::Root, 0)].into_iter().collect(),
        })
        .unwrap();
        let cfg = serde_json::json!({
            "uids": {"broker":5001,"challenge":5002,"sidecar":5003,"supervisor":5004,
                     "recorder":5005,"signer":5006,"executor":5007},
            "trust": {
                "tcb_pin_manifest_path": "/kit/pin.json",
                "manifest_path": "/kit/manifest.json",
                "manifest_sig_path": "/kit/manifest.sig",
                "floor_path": "/kit/floor.json",
                "signer_key_id": "brops-live-signer-1", // gitleaks:allow (fake public key-id)
                "supervisor_attestation_key_id": "brops-live-sup-attest-1" // gitleaks:allow (fake public key-id)
            },
            "sockets": {"authority": "/kit/authority.sock"},
            "content": {"messages_db": "/kit/messages.db", "system": "you are Bro", "window": 8},
            "sidecar": {
                "python": "/usr/bin/python3",
                "script": "/kit/engine_sidecar.py",
                "cwd": "/kit/sandbox",
                "principal": "brops-sidecar",
                "invoker": ["/usr/bin/sudo", "-n", "-u", "brops-sidecar", "/usr/bin/env"]
            },
            "resolved": {"workspace_id":"w","install_id":"i","run_id":"r","task_id":"t",
                         "requested_at_ms": 1735689600000i64},
            "execution": {"launcher_path": "/kit/privileged-launcher.bin"},
            "supervisor": {"ledger_db": "/kit/supervisor-state/ledger.db"}
        })
        .to_string();
        FakeHost::linux()
            .env("BROPS_BROKER_CONFIG", "/kit/config.json")
            .file("/kit/config.json", &cfg)
            .file("/kit/pin.json", &pin)
            .file("/kit/manifest.json", manifest)
            .file("/kit/manifest.sig", "AAAA")
            .file("/kit/floor.json", r#"{"highest_epoch":2,"highest_hash":"abc"}"#)
            .stat("/kit/floor.json", 5001, 0o100600, false)
            .stat("/kit/authority.sock", 5002, 0o140660, false)
            .stat("/kit/messages.db", 5001, 0o100600, false)
            .stat("/usr/bin/python3", 0, 0o100755, false)
            .stat("/usr/bin/sudo", 0, 0o104755, false)
            .stat("/kit/engine_sidecar.py", 0, 0o100644, false)
            .stat("/kit/sandbox", 0, 0o40755, true)
            .stat("/kit/privileged-launcher.bin", 0, 0o104750, false)
            .stat("/kit/supervisor-state", 5004, 0o40700, true)
            .stat("/kit/broker-state", 5001, 0o40700, true)
            .account("brops-sidecar", 5003)
    }

    #[test]
    fn a_provisioned_deployment_meets_everything_a_machine_can_meet() {
        let report = evaluate(&provisioned(), Some("/kit/broker-state/broker.sock"));
        let unexpected: Vec<&str> = report
            .not_met()
            .iter()
            .map(|f| f.requirement.name)
            .filter(|n| {
                // The two custody rows are the honest residue: an offline key and a code decision.
                *n != "custody.tcb_root_manifest_signature" && *n != "custody.committed_label_resolver"
            })
            .collect();
        assert!(unexpected.is_empty(), "unexpectedly not met: {unexpected:?}\n{}", report.render());
        // …and the two that remain are exactly the two whose provisioner is not a machine.
        assert_eq!(report.not_met().len(), 2);
        for f in report.not_met() {
            assert!(matches!(
                f.requirement.provisioner,
                Provisioner::OfflineRootCustodian | Provisioner::NotProvisionableOnAMachine
            ));
        }
    }

    // ---- one negative per measured requirement ----------------------------------------------

    #[test]
    fn a_missing_pin_manifest_is_not_met_by_name() {
        let mut host = provisioned();
        host.files.remove("/kit/pin.json");
        let r = evaluate(&host, None);
        assert!(status_of(&r, "trust.tcb_pin_manifest_path").detail().contains("absent"));
        assert!(status_of(&r, "trust.tcb_pin_manifest_covers_the_required_set")
            .detail()
            .contains("absent"));
    }

    #[test]
    fn an_under_covering_pin_manifest_names_the_unpinned_artifacts() {
        let mut host = provisioned();
        let thin = serde_json::to_string(&TcbPinManifest {
            artifacts: vec![],
            owner_uids: BTreeMap::new(),
        })
        .unwrap();
        host.files.insert("/kit/pin.json".into(), thin.into_bytes());
        let r = evaluate(&host, None);
        let detail = status_of(&r, "trust.tcb_pin_manifest_covers_the_required_set").detail();
        assert!(detail.contains("privileged-launcher.bin"), "{detail}");
        assert!(detail.contains("unpinned"), "{detail}");
    }

    #[test]
    fn a_sidecar_uid_absent_from_the_uids_block_is_reported() {
        let mut host = provisioned();
        let mut cfg: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["uids"].as_object_mut().unwrap().remove("sidecar");
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let r = evaluate(&host, None);
        let d = status_of(&r, "principals.tcb_floor_covers_the_sidecar").detail();
        assert!(d.contains("does not name it"), "{d}");
        // The SEVEN ACCOUNTS still exist and are still distinct — that is a different question, and
        // the two rows must not be collapsed. This is the live kit's actual state: seven real
        // accounts, and a `uids` block (hardcoded DEFAULT_UIDS in provision_keys.py) that names six.
        assert!(status_of(&r, "principals.seven_distinct_accounts").is_met());
    }

    #[test]
    fn a_principal_collapse_is_refused_by_name() {
        let mut host = provisioned();
        let mut cfg: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["uids"]["broker"] = serde_json::json!(5003);
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let r = evaluate(&host, None);
        assert!(status_of(&r, "principals.sidecar_distinct_from_broker")
            .detail()
            .contains("principal collapse"));
    }

    #[test]
    fn a_launcher_without_the_setuid_bit_is_not_met() {
        let host = provisioned().stat("/kit/privileged-launcher.bin", 0, 0o100755, false);
        let r = evaluate(&host, None);
        assert!(status_of(&r, "launcher.setuid_root_binary").detail().contains("not setuid"));
    }

    #[test]
    fn a_setuid_launcher_owned_by_a_service_account_is_not_met() {
        let host = provisioned().stat("/kit/privileged-launcher.bin", 5001, 0o104750, false);
        let r = evaluate(&host, None);
        let d = status_of(&r, "launcher.setuid_root_binary").detail();
        assert!(d.contains("owned by uid 5001"), "{d}");
    }

    #[test]
    fn a_world_readable_supervisor_store_is_not_met() {
        let host = provisioned().stat("/kit/supervisor-state", 5004, 0o40755, true);
        let r = evaluate(&host, None);
        assert!(status_of(&r, "store.supervisor_private_0700").detail().contains("mode 755"));
    }

    #[test]
    fn a_root_owned_floor_is_not_met_and_names_the_persist_refusal() {
        let host = provisioned().stat("/kit/floor.json", 0, 0o100644, false);
        let r = evaluate(&host, None);
        let d = status_of(&r, "trust.floor_is_broker_owned_0600").detail();
        assert!(d.contains("owned by uid 0"), "{d}");
        assert!(d.contains("floor_not_persisted"), "{d}");
    }

    #[test]
    fn a_group_writable_floor_is_not_met() {
        let host = provisioned().stat("/kit/floor.json", 5001, 0o100660, false);
        let r = evaluate(&host, None);
        assert!(status_of(&r, "trust.floor_is_broker_owned_0600").detail().contains("mode 660"));
    }

    #[test]
    fn an_unparseable_floor_is_never_read_as_no_floor_required() {
        let mut host = provisioned();
        host.files.insert("/kit/floor.json".into(), b"{}".to_vec());
        let r = evaluate(&host, None);
        assert!(status_of(&r, "trust.floor_path").detail().contains("does not parse"));
    }

    #[test]
    fn an_absent_authority_socket_is_not_met() {
        let mut host = provisioned();
        host.stats.remove("/kit/authority.sock");
        let r = evaluate(&host, None);
        assert!(status_of(&r, "sockets.authority").detail().contains("nothing to dial"));
    }

    #[test]
    fn an_unconfigured_conversation_source_is_not_met() {
        let mut host = provisioned();
        let mut cfg: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["content"].as_object_mut().unwrap().remove("messages_db");
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let r = evaluate(&host, None);
        assert!(status_of(&r, "content.messages_db")
            .detail()
            .contains("nothing honest to sign"));
    }

    #[test]
    fn an_empty_system_prompt_and_a_zero_window_are_both_not_met() {
        let mut host = provisioned();
        let mut cfg: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["content"]["system"] = serde_json::json!("");
        cfg["content"]["window"] = serde_json::json!(0);
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let r = evaluate(&host, None);
        assert!(matches!(status_of(&r, "content.system"), Status::NotMet { .. }));
        assert!(status_of(&r, "content.window").detail().contains("must be positive"));
    }

    #[test]
    fn a_relative_invoker_program_is_refused_by_the_real_constructor() {
        let mut host = provisioned();
        let mut cfg: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["sidecar"]["invoker"] = serde_json::json!(["sudo", "-n", "-u", "brops-sidecar", "env"]);
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let r = evaluate(&host, None);
        let s = status_of(&r, "sidecar.principal_and_invoker");

        // Assert the BEHAVIOUR (it is refused), and then that the preflight relays the
        // constructor's OWN words rather than inventing a second wording. Matching a substring of
        // brops-core's message would be an assertion about HOW another module phrases a refusal —
        // the pattern that has broken tests in this repository five times — and it would also pass
        // if the preflight re-spelled the reason itself, which is the thing worth forbidding.
        assert!(matches!(s, Status::NotMet { .. }), "{s:?}");
        let cfg_value: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        let expected = brops_core::governed_sidecar::SidecarPrincipal::from_config(
            cfg_value.get("sidecar"),
        )
        .expect_err("a relative invoker program must be refused");
        assert_eq!(s.detail(), expected);
    }

    #[test]
    fn a_sidecar_account_that_does_not_exist_is_not_met() {
        let mut host = provisioned();
        host.accounts.remove("brops-sidecar");
        let r = evaluate(&host, None);
        assert!(status_of(&r, "sidecar.principal_and_invoker")
            .detail()
            .contains("not an account on this machine"));
    }

    #[test]
    fn an_absent_interpreter_is_not_met() {
        let mut host = provisioned();
        host.stats.remove("/usr/bin/python3");
        let r = evaluate(&host, None);
        assert!(status_of(&r, "sidecar.spawn_triple").detail().contains("which is absent"));
    }

    #[test]
    fn empty_resolved_identifiers_are_reported_because_nothing_refuses_them() {
        let mut host = provisioned();
        let mut cfg: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["resolved"]["run_id"] = serde_json::json!("");
        cfg["resolved"].as_object_mut().unwrap().remove("task_id");
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let r = evaluate(&host, None);
        let d = status_of(&r, "resolved.identifiers").detail();
        assert!(d.contains("resolved.run_id"), "{d}");
        assert!(d.contains("resolved.task_id"), "{d}");
    }

    #[test]
    fn the_ledger_requirement_needs_the_socket_argv_not_the_config() {
        let host = provisioned();
        assert!(matches!(
            status_of(&evaluate(&host, None), "db.durable_acceptance_ledger"),
            Status::Unmeasurable { .. }
        ));
        let r = evaluate(&host, Some("/nowhere/broker.sock"));
        assert!(status_of(&r, "db.durable_acceptance_ledger")
            .detail()
            .contains("does not exist"));
    }

    #[test]
    fn a_manifest_under_another_root_cannot_meet_the_custody_requirement() {
        let r = evaluate(&provisioned(), None);
        let d = status_of(&r, "custody.tcb_root_manifest_signature").detail();
        assert!(d.contains("brops-live-root-1"), "{d}");
        assert!(d.contains("OFFLINE"), "{d}");
        assert!(d.contains(crate::tcb::ROOT_KEY_ID), "{d}");
    }

    #[test]
    fn the_custody_resolver_requirement_can_never_be_met_by_provisioning() {
        let r = evaluate(&provisioned(), None);
        let d = status_of(&r, "custody.committed_label_resolver").detail();
        assert!(d.contains("with_custody"), "{d}");
        assert!(d.contains("no machine can provision it"), "{d}");
    }

    #[test]
    fn an_empty_or_whitespace_key_id_is_not_met() {
        for value in ["", "   "] {
            let mut host = provisioned();
            let mut cfg: Value =
                serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
            cfg["trust"]["signer_key_id"] = serde_json::json!(value);
            host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
            let r = evaluate(&host, None);
            let s = status_of(&r, "trust.signer_key_id");
            assert!(matches!(s, Status::NotMet { .. }), "{value:?} passed: {s:?}");
            assert!(s.detail().contains("a key with no id"), "{s:?}");
        }
    }

    /// The one requirement the fake host cannot reach: `RealHost::stat` must report the LINK, not
    /// what it points at. A symlink swapped into a TCB path is exactly the substitution the §2.5
    /// floor opens `O_NOFOLLOW` to refuse, and a preflight that followed it would report a
    /// reassuring owner for a file the broker will not accept.
    #[cfg(unix)]
    #[test]
    fn real_host_stat_does_not_follow_a_symlink() {
        let dir = tempfile::tempdir().expect("tempdir");
        let target = dir.path().join("target");
        std::fs::write(&target, b"x").expect("write target");
        let link = dir.path().join("link");
        std::os::unix::fs::symlink(&target, &link).expect("symlink");

        let facts = RealHost
            .stat(link.to_str().unwrap())
            .expect("the link itself is there");
        // S_IFLNK — the link, not the regular file it points at.
        assert_eq!(facts.mode & 0o170000, 0o120000, "stat followed the symlink");
        let direct = RealHost.stat(target.to_str().unwrap()).expect("target");
        assert_eq!(direct.mode & 0o170000, 0o100000);
    }

    #[test]
    fn the_render_names_every_unmet_requirement_in_its_summary() {
        let text = evaluate(&FakeHost::linux(), None).render();
        for r in REQUIREMENTS {
            assert!(text.contains(r.name), "{} missing from the report", r.name);
        }
        assert!(text.contains("NOT MET, by name:"));
        assert!(text.contains("Nothing here provisions, flips or weakens anything."));
    }
}
