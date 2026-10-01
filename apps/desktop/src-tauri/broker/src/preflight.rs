//! **Provisioning preflight**: which of the governed turn's prerequisites does THIS machine meet?
//!
//! # Why this exists
//!
//! `build_governed_executor` (`broker/src/main.rs`) is a ladder of `return fail_closed()`
//! branches. (This sentence carried a count — 15 — that the function had outgrown; the number is
//! gone rather than corrected, because nothing held it.) That is correct — the broker must never serve a governed turn it cannot back — but it
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
//! * **It does not provision.** Eleven of the requirements below can only be created by a machine
//!   administrator (service accounts, a setuid launcher, a sudoers vector, root-owned TCB material),
//!   one is a key manifest signed under a root the INSTALL minted and wrote into the floor-pinned
//!   anchor file (no person holds a root — Owner decision #78; T-131), one is not on a machine at
//!   all, and one the shipped build already provides. An installer that "provisioned" the other
//!   thirteen would produce a config that still ends in `fail_closed()` — with the gap now hidden
//!   behind a file that looks complete.
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

use brops_core::key_manifest::{verify_manifest, KeyManifest};
use brops_core::tcb_integrity::{TcbPinManifest, ROOT_ANCHOR_ROLE, TCB_REQUIRED_ARTIFACTS};
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
    /// The privileged INSTALL step, minting a root: it generates the TCB root keypair, signs the key
    /// manifest with it, writes the public half and its provenance into the anchor file the §2.5
    /// pin manifest pins (`key-manifest.root-anchor`), and destroys the private half before it
    /// exits. No person holds or carries a root — the Owner decided on 2026-08-09 (#78) that the
    /// install mints all trust — so this is a step of the install and not of anybody's ceremony
    /// (`docs/design/DEBIAN_INSTALL_PROVISIONING.md`, T-131). The live kits stand in for it with a
    /// `kit_generated` root, which meets the row and can never be production.
    InstallMintedRoot,
    /// Nothing on any machine can create it — it is a property of the shipped BINARY, and changing it
    /// is a code change behind the Owner's gate.
    NotProvisionableOnAMachine,
    /// The shipped binary already provides it: no installer and no administrator has anything
    /// to do. It stays in this table because it is still a PREREQUISITE — a reader asking what makes a
    /// committed row possible should find it here — and because a build that stopped providing it would
    /// otherwise vanish from the list rather than turn red.
    MetByTheBuild,
}

impl Provisioner {
    pub fn as_str(self) -> &'static str {
        match self {
            Provisioner::Installer => "installer",
            Provisioner::MachineAdministrator => "machine-admin",
            Provisioner::InstallMintedRoot => "install-minted-root",
            Provisioner::NotProvisionableOnAMachine => "not-provisionable",
            Provisioner::MetByTheBuild => "met-by-build",
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
/// `install-minted-root` (the root the install mints — see [`Provisioner::InstallMintedRoot`]), one
/// `not-provisionable`, one `met-by-build`. A test holds those five counts.
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
               recorder, signer, executor) that exist on this machine — every uid the `uids` block \
               declares is looked up in the account database, not taken on the config's word",
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
                  ProductionResolver::resolve_keys refuses the turn and the renderer is answered \
                  `upstream_blocked`. (`blocked:keys:floor_not_persisted` is the PROOF DRIVER's name \
                  for the same failure — proof/src/bin/ladder_turn.rs — and the broker emits no \
                  such string)",
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
        what: "the broker's SQLite file — derived from its socket argv (`<stem>.sock` → \
               `<stem>.db`), NOT from config — has a directory the broker account owns and can \
               write, so the ledger can be created and replay defence survives a restart",
        provisioner: Provisioner::MachineAdministrator,
        refusal: "main.rs `serve()`: a socket path not ending in `.sock` → EXIT_BAD_ARGUMENT; \
                  `cannot open broker DB` → EXIT_DB, before the socket is bound; and, if only the \
                  ledger's second open fails, `durable acceptance ledger unavailable at {db_path} \
                  ({e}) - serving fail-closed`",
    },
    // ---- custody ------------------------------------------------------------------------------
    Requirement {
        name: "custody.tcb_root_manifest_signature",
        what: "the key manifest verifies under the root in the FLOOR-PINNED anchor file — the one \
               the §2.5 pin manifest pins as `key-manifest.root-anchor`, never a path the config \
               names — and that file states a known provenance. Meeting this row is not a \
               production claim: the provenance decides the label",
        provisioner: Provisioner::InstallMintedRoot,
        refusal: "main.rs: `root anchor REFUSED ({why}) — serving fail-closed` when the pinned \
                  anchor is absent, changed since the pin, garbled, states no known provenance, or \
                  says `external` for a root that is not the compiled-in one; and \
                  ProductionResolver::resolve_keys → UnknownRoot / RootSignatureInvalid when the \
                  manifest is not signed under it",
    },
    Requirement {
        name: "custody.committed_label_resolver",
        what: "a custody resolver, so a committed reply can carry a custody label. WIRED 2026-09-19 by \
               the Owner's decision (docs/OWNER_ACTION_REQUIRED.md): build_governed_executor passes \
               ProductionResolver::custody() to ChainExecutor::with_custody",
        provisioner: Provisioner::MetByTheBuild,
        refusal: "with no observation recorded — no turn has verified a manifest under the pinned \
                  anchor — BrokerCustody returns NoTrustedManifest and persist_committed still \
                  refuses. What the wiring removed is the case where NO config could ever commit",
    },
];

/// Every configuration key `build_governed_executor` actually reads, dotted.
///
/// A test in this module extracts the key literals from `main.rs`'s own source and fails if this
/// list and that source disagree in either direction. That is the whole anti-drift story: this list
/// is a mirror, and a mirror that cannot be checked is how one contract acquires two implementations.
///
/// `db.path` is deliberately ABSENT: the broker derives its database path from its socket argv
/// ([`crate::broker_db_path`]) and never reads a `db` block. The live kit writes one for
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
    /// The reverse lookup: the name of the OS account holding `uid`, or `None` when no account does
    /// (or the platform has no such concept). It is how a NUMBER written in a config is told apart
    /// from an account that exists.
    fn uid_account(&self, uid: u32) -> Option<String>;
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
        // this never becomes a silent NotMet — and that is held by a test now
        // (`off_linux_nothing_is_reported_absent_because_stat_could_not_answer`). When this comment
        // was only a comment, three callers were not gated and reported files that exist as absent.
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

    #[cfg(target_os = "linux")]
    fn uid_account(&self, uid: u32) -> Option<String> {
        // SAFETY: `getpwuid` reads the passwd database and returns a pointer into a static buffer
        // owned by libc; `pw_name` is copied out of it before any other libc call can clobber it.
        let pw = unsafe { libc::getpwuid(uid) };
        if pw.is_null() {
            return None;
        }
        let name = unsafe { std::ffi::CStr::from_ptr((*pw).pw_name) };
        Some(name.to_string_lossy().into_owned())
    }

    #[cfg(not(target_os = "linux"))]
    fn uid_account(&self, _uid: u32) -> Option<String> {
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
            "db.durable_acceptance_ledger" => check_ledger(host, &cfg, socket_path),
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
    // The row says the accounts EXIST. The six uids in the `uids` block are numbers the config
    // wrote down, and until this lookup only the sidecar — named by account — was ever resolved:
    // six distinct numbers belonging to nobody read as six accounts.
    let unowned: Vec<u32> = uids.iter().copied().filter(|u| host.uid_account(*u).is_none()).collect();
    if !unowned.is_empty() {
        return Status::not_met(format!(
            "the deployment declares uids that no account on this machine holds: {unowned:?}. A \
             number in the `uids` block is not an account; §2.6 needs seven that exist"
        ));
    }
    if uids.len() == 7 {
        Status::met(format!("seven distinct uids, each held by an account: {uids:?}"))
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
    // Located through the §2.5 pin manifest, not a key of the broker's config. Until 2026-09-29 this
    // read `execution.launcher_path`, which `build_governed_executor` never reads (the ladder moved
    // the privileged spawn to the supervisor) — so a config holding exactly the keys the broker
    // reads, which is what the live kit's broker-config writer (T-111) emits, reported this row NOT MET
    // on a fully provisioned machine. The pinned `privileged-launcher.bin` is the very file the floor
    // measures, which makes it the one honest answer to "which launcher".
    let pin = match read_pin_manifest(host, cfg) {
        Ok(m) => m,
        Err(why) => {
            return Status::not_met(format!(
                "the privileged launcher is located through the §2.5 pin manifest, and {why}"
            ))
        }
    };
    let path = match pin.artifacts.iter().find(|a| a.logical_name == "privileged-launcher.bin") {
        Some(a) => a.path.clone(),
        None => {
            return Status::not_met(
                "the §2.5 pin manifest pins no `privileged-launcher.bin`, so the preflight cannot \
                 find the binary the contained execution is entered through",
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
    // Located through the §2.5 pin manifest's pinned CONFIGURATION documents, not a key of the
    // broker's config. Until 2026-09-29 this read `supervisor.ledger_db` out of the broker's own
    // config — a key only the SUPERVISOR reads — so a config holding exactly the keys the broker
    // reads reported this row NOT MET on a fully provisioned machine. Every pinned `*.config`
    // document is searched rather than `supervisor.config` alone, because the ladder supervisor is
    // started with two (`--config config.json --ladder ladder.json`) and its role pins the second.
    // Two pinned documents naming DIFFERENT ledgers is refused: the preflight will not pick one.
    let pin = match read_pin_manifest(host, cfg) {
        Ok(m) => m,
        Err(why) => {
            return Status::not_met(format!(
                "the supervisor's ledger is located through the §2.5 pin manifest, and {why}"
            ))
        }
    };
    let mut named: BTreeSet<String> = BTreeSet::new();
    for artifact in pin.artifacts.iter().filter(|a| a.logical_name.ends_with(".config")) {
        let ledger = host
            .read(&artifact.path)
            .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
            .and_then(|v| v.get("supervisor")?.get("ledger_db")?.as_str().map(str::to_string));
        if let Some(l) = ledger {
            named.insert(l);
        }
    }
    let ledger = match named.len() {
        1 => named.into_iter().next().unwrap_or_default(),
        0 => {
            return Status::not_met(
                "no configuration document the §2.5 pin manifest pins names the supervisor's \
                 durable ledger (`supervisor.ledger_db`)",
            )
        }
        _ => {
            return Status::not_met(format!(
                "pinned configuration documents name {} different supervisor ledgers ({}); the \
                 preflight will not choose one",
                named.len(),
                named.into_iter().collect::<Vec<_>>().join(", ")
            ))
        }
    };
    let dir = match ledger.rfind('/') {
        Some(i) if i > 0 => ledger[..i].to_string(),
        _ => return Status::not_met(format!("`supervisor.ledger_db` ({ledger}) has no directory")),
    };
    // The requirement says OWNED BY THE SUPERVISOR, and until 2026-09-29 only the mode was checked: a
    // 0700 directory owned by any uid at all passed. `uids.supervisor` is in the block the broker
    // reads, so the owner is measurable against the deployment's own statement of who that is.
    let supervisor_uid = cfg
        .get("uids")
        .and_then(|u| u.get("supervisor"))
        .and_then(Value::as_u64)
        .map(|u| u as u32);
    match host.stat(&dir) {
        None => Status::not_met(format!("{dir} is absent")),
        Some(f) if !f.is_dir => Status::not_met(format!("{dir} is not a directory")),
        Some(_) if supervisor_uid.is_none() => Status::not_met(
            "the `uids` block names no `supervisor`, so the ledger directory's owner cannot be \
             compared with the account that must own it",
        ),
        Some(f) if Some(f.owner_uid) != supervisor_uid => Status::not_met(format!(
            "{dir} is owned by uid {}, not the supervisor (uid {}): the party being attested \
             would not be the one holding its own state",
            f.owner_uid,
            supervisor_uid.unwrap_or_default()
        )),
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

/// The §2.5 pin manifest the broker's config names, parsed, or why it could not be.
fn read_pin_manifest(host: &dyn Host, cfg: &Cfg) -> Result<TcbPinManifest, String> {
    let path = pin_manifest_path(host, cfg).ok_or_else(|| {
        "neither `trust.tcb_pin_manifest_path` nor $BROPS_TCB_PIN_MANIFEST names one".to_string()
    })?;
    let bytes = host.read(&path).ok_or_else(|| format!("{path} is absent or unreadable"))?;
    serde_json::from_slice::<TcbPinManifest>(&bytes)
        .map_err(|e| format!("{path} does not deserialize as a pin manifest: {e}"))
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
             turn (the broker answers `upstream_blocked`)",
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
    if !host.platform_is_linux() {
        return Status::unmeasurable(format!(
            "`content.messages_db` names {path}, but this platform's `stat` answers nothing, so \
             whether it exists is not something the preflight can say here"
        ));
    }
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
    let mut named = Vec::new();
    for key in ["python", "script", "cwd"] {
        match cfg.s(&["sidecar", key]) {
            None => missing.push(format!("`sidecar.{key}` is unset")),
            Some(p) => named.push((key, p)),
        }
    }
    // An unset key is a fact about the config and is NOT MET on any platform. Whether a NAMED path
    // exists is a fact about the filesystem, and off Linux `stat` cannot answer it.
    if missing.is_empty() && !host.platform_is_linux() {
        return Status::unmeasurable(
            "all three of `sidecar.python`, `sidecar.script` and `sidecar.cwd` are named, but this \
             platform's `stat` answers nothing, so whether they exist is not measurable here",
        );
    }
    let mut present = Vec::new();
    if host.platform_is_linux() {
        for (key, p) in named {
            if host.stat(&p).is_some() {
                present.push(format!("{key}={p}"));
            } else {
                missing.push(format!("`sidecar.{key}` names {p}, which is absent"));
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

fn check_ledger(host: &dyn Host, cfg: &Cfg, socket_path: Option<&str>) -> Status {
    let socket = match socket_path {
        Some(s) => s,
        None => {
            return Status::unmeasurable(
                "the broker derives its database path from its socket ARGV, not from config, so \
                 without the socket path there is no file to check. Re-run with --socket <path>",
            )
        }
    };
    // The broker's own rule, not a copy of it. A path with no `.sock` suffix used to come back
    // from a local `replace(".sock", ".db")` UNCHANGED — the "database" was the socket — and this
    // row then reported MET for it.
    let db = match crate::broker_db_path(socket) {
        Some(db) => db,
        None => {
            return Status::not_met(format!(
                "the socket path {socket} does not end in `.sock`, so no database path can be \
                 derived from it that is not the socket itself; the broker refuses to start on it"
            ))
        }
    };
    let dir = match db.rfind(['/', '\\']) {
        Some(i) if i > 0 => db[..i].to_string(),
        _ => return Status::not_met(format!("{db} has no parent directory")),
    };
    if !host.platform_is_linux() {
        return Status::unmeasurable(format!(
            "the ledger would be {db}, but this platform has no ownership or mode for {dir} that \
             the preflight could compare with the broker account"
        ));
    }
    // "A directory exists" is not "the broker can open its ledger there": SQLite has to CREATE the
    // file and its journal in that directory, as the broker account. This row used to stop at
    // `is_dir`, so a root-owned 0755 directory — where the broker's open fails — read as MET.
    let broker_uid = cfg.i(&["uids", "broker"]).map(|u| u as u32);
    match (host.stat(&dir), broker_uid) {
        (None, _) => Status::not_met(format!(
            "{dir} does not exist, so the durable acceptance ledger cannot be opened at {db}: the \
             broker exits with EXIT_DB before it binds its socket, and serves nothing at all"
        )),
        (Some(f), _) if !f.is_dir => Status::not_met(format!("{dir} is not a directory")),
        (Some(_), None) => Status::not_met(format!(
            "`uids.broker` is not declared, so whether the broker account can create {db} in \
             {dir} cannot be judged"
        )),
        (Some(f), Some(b)) if f.owner_uid != b => Status::not_met(format!(
            "{dir} is owned by uid {} but the broker runs as {b}; SQLite must create {db} and its \
             journal there as the broker, and this row does not guess at group or ACL access",
            f.owner_uid
        )),
        (Some(f), Some(_)) if f.mode & 0o300 != 0o300 => Status::not_met(format!(
            "{dir} is mode {:o}: its owner cannot both write and search it, so {db} cannot be \
             created there",
            f.mode & 0o7777
        )),
        (Some(f), Some(b)) => Status::met(format!(
            "{dir} is 0{:o} owned by the broker uid {b}, so the ledger at {db} can be created there",
            f.mode & 0o7777
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
    // The anchor is LOCATED the way the broker locates it: through the §2.5 pin manifest, under the
    // one role that names it. There is no config key for it and this must not invent one — a row
    // that read `trust.root_anchor_path` would report MET for a file the broker never opens.
    let pin = match read_pin_manifest(host, cfg) {
        Ok(m) => m,
        Err(why) => {
            return Status::not_met(format!(
                "the root anchor is located through the §2.5 pin manifest, and {why}"
            ))
        }
    };
    let art = match pin.sole_artifact(ROOT_ANCHOR_ROLE) {
        Ok(a) => a,
        Err(why) => {
            return Status::not_met(format!(
                "the §2.5 pin manifest does not pin exactly one `{ROOT_ANCHOR_ROLE}` ({why:?}), so \
                 there is no anchor file the broker would read"
            ))
        }
    };
    let bytes = match host.read(&art.path) {
        Some(b) => b,
        None => {
            return Status::not_met(format!(
                "the pinned root anchor {} is absent or unreadable",
                art.path
            ))
        }
    };
    // The broker parses the anchor only if its bytes hash to the pinned digest; so does this.
    if let Some(why) = crate::tcb_probe::pinned_digest_violation(art, &bytes) {
        return Status::not_met(why);
    }
    let anchor = match crate::tcb::parse_root_anchor(&bytes) {
        Ok(a) => a,
        Err(why) => {
            return Status::not_met(format!(
                "the root anchor pinned at {} is refused: {why}",
                art.path
            ))
        }
    };
    match verify_manifest(&manifest, &sig, &anchor.pinned) {
        Ok(()) => Status::met(format!(
            "the manifest verifies under root `{}` in the floor-pinned anchor {} (provenance \
             `{}`). What this does NOT establish: production custody — a turn under this anchor \
             commits as `{}` — nor that the §2.5 floor passes over that file, which only the \
             broker, as its own uid, measures",
            anchor.pinned.root_key_id,
            art.path,
            anchor.provenance.as_str(),
            if anchor.provenance.supports_production_claim() {
                brops_core::governed_turn_ipc::TRUSTED_VERIFIED
            } else {
                "demonstration_custody"
            }
        )),
        Err(e) => Status::not_met(format!(
            "the manifest names root `{}` and does not verify under root `{}` in the floor-pinned \
             anchor {}: {e:?}. The install mints that root and signs the manifest with it in one \
             step (T-131); a manifest and an anchor from two different runs do not match",
            manifest.root_key_id, anchor.pinned.root_key_id, art.path
        )),
    }
}

fn check_custody_resolver() -> Status {
    Status::met(
        "build_governed_executor passes `ProductionResolver::custody()` to \
         `ChainExecutor::with_custody`, so a turn that verified a manifest under the pinned anchor can \
         commit. What this does NOT establish: the LABEL on that row. `resolve_trust_state` decides it \
         on the provenance the floor-pinned anchor file states — `kit_generated`, `demonstration` and \
         (while INSTALL_MINTED_CUSTODY_ACCEPTED is false) `install_minted` all give \
         `demonstration_custody` — and a turn that verified nothing still commits nothing",
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
        /// How many times `stat` was asked. A test reads it to hold "off Linux, nobody calls
        /// `stat`" as a measurement instead of a comment.
        stat_calls: std::cell::Cell<usize>,
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
            self.stat_calls.set(self.stat_calls.get() + 1);
            // The real non-unix `stat` answers `None` for every path; so does this one.
            if !self.linux {
                return None;
            }
            self.stats.get(path).cloned()
        }
        fn account_uid(&self, name: &str) -> Option<u32> {
            self.accounts.get(name).copied()
        }
        fn uid_account(&self, uid: u32) -> Option<String> {
            self.accounts.iter().find(|(_, u)| **u == uid).map(|(name, _)| name.clone())
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
    fn a_requirement_no_machine_can_meet_is_named_on_the_owner_page() {
        // The table's `Provisioner` column is the whole point of the table, and one of its values --
        // `NotProvisionableOnAMachine` -- says something no installer and no administrator can fix. A
        // prerequisite like that is not a deployment task; it is either a platform fact or a decision
        // somebody has to take, and a decision nobody has been ASKED is indistinguishable from one
        // nobody has to take.
        //
        // Measured 2026-09-19: `custody.committed_label_resolver` had sat here since the ladder
        // replaced the direct wiring, with "it is an owner-gated code decision" in its own `refusal`
        // field, and appeared nowhere in `docs/OWNER_ACTION_REQUIRED.md` -- the one page whose stated
        // job is that "the answer to 'what is waiting on me' is never reconstructed from a chat log".
        // Two Phase-1 Definition-of-Done rows were reading as blocked by deployment because of it.
        //
        // So the page is read from disk. A new not-provisionable requirement now has to be put in
        // front of the Owner before this test passes, which is the only place that obligation can be
        // enforced rather than remembered.
        let page = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../../docs/OWNER_ACTION_REQUIRED.md");
        let text = std::fs::read_to_string(&page)
            .unwrap_or_else(|e| panic!("cannot read {}: {e}", page.display()));
        let unprovisionable: Vec<&str> = REQUIREMENTS
            .iter()
            .filter(|r| matches!(r.provisioner, Provisioner::NotProvisionableOnAMachine))
            .map(|r| r.name)
            .collect();
        assert!(!unprovisionable.is_empty(), "the filter matched nothing; re-read the table");
        for name in unprovisionable {
            assert!(
                text.contains(name),
                "`{name}` is a prerequisite no machine can provide and it is not named in                  docs/OWNER_ACTION_REQUIRED.md. Either the Owner has not been asked, or the                  provisioner column is wrong -- both are worth stopping for"
            );
        }
    }

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
    /// On a bare Linux machine with nothing provisioned, the only requirements that may come back MET
    /// are the ones no machine provides: the platform itself, and — since 2026-09-19 — the custody
    /// resolver, which the BUILD provides. Every row an installer, an administrator or the
    /// root-minting install step would have to create must be NOT MET or UNMEASURABLE on a machine
    /// where none of them has run.
    #[test]
    fn a_bare_machine_meets_only_what_no_machine_provides() {
        let report = evaluate(&FakeHost::linux(), None);
        let met: Vec<&str> = report
            .findings
            .iter()
            .filter(|f| f.status.is_met())
            .map(|f| f.requirement.name)
            .collect();
        assert_eq!(
            met,
            vec!["platform.linux_af_unix_peercred", "custody.committed_label_resolver"],
            "{}",
            report.render()
        );
        // And neither of them is something this machine did: one is the kernel, one is the binary.
        for name in &met {
            let f = report.findings.iter().find(|f| f.requirement.name == *name).unwrap();
            assert!(matches!(
                f.requirement.provisioner,
                Provisioner::NotProvisionableOnAMachine | Provisioner::MetByTheBuild
            ));
        }
        assert_eq!(report.exit_code(), 1);
    }

    /// And off Linux, the only thing met is the one the binary carries with it.
    ///
    /// This asserted `met() == 0` until the custody wiring landed, which was true and is no longer: the
    /// custody resolver is a property of the build, so it travels to every platform including the one
    /// where the broker refuses to run at all. The platform row is still NOT MET, which is what makes
    /// the report refuse.
    #[test]
    fn a_bare_non_linux_machine_meets_only_what_the_build_carries() {
        let report = evaluate(&FakeHost::default(), None);
        let met: Vec<&str> =
            report.findings.iter().filter(|f| f.status.is_met()).map(|f| f.requirement.name).collect();
        assert_eq!(met, vec!["custody.committed_label_resolver"], "{}", report.render());
        assert!(!status_of(&report, "platform.linux_af_unix_peercred").is_met());
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

    /// The §2.5 roster is the core constant, used through `missing_required()`, and this module
    /// writes NONE of it down a second time.
    ///
    /// Read from the source, because that is the only place a copy could be: the previous body of
    /// this test asserted two things about the imported constant (`contains`, `len() >= 20`) and
    /// would have stayed green with a second roster typed out twenty lines above it. The one role
    /// this module legitimately names as a literal is the launcher it looks up; any other roster
    /// name appearing as a string literal in the production half is a copy starting.
    #[test]
    fn the_tcb_roster_is_the_real_constant_not_a_copy() {
        let source = include_str!("preflight.rs");
        let production = source
            .split_once("#[cfg(test)]")
            .expect("preflight.rs must still delimit its test module")
            .0;
        assert!(production.contains("fn check_pin_coverage("), "the production half is what is scanned");
        assert!(TCB_REQUIRED_ARTIFACTS.len() >= 20, "a scan over a near-empty roster would be vacuous");

        let written_out: Vec<&str> = TCB_REQUIRED_ARTIFACTS
            .iter()
            .copied()
            .filter(|role| production.contains(&format!("\"{role}\"")))
            .collect();
        assert_eq!(
            written_out,
            vec!["privileged-launcher.bin"],
            "roster roles written out as literals in preflight.rs. The roster is \
             `brops_core::tcb_integrity::TCB_REQUIRED_ARTIFACTS`; a second list here is a second \
             contract"
        );
        // And coverage is decided by the constant's own method, not by a loop over names here.
        assert!(production.contains("manifest.missing_required()"));
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

    /// Where the fixture's pin manifest pins the root anchor.
    const ANCHOR: &str = "/opt/brops-live/tcb/key-manifest.root-anchor";

    fn sha256_hex(bytes: &[u8]) -> String {
        use sha2::{Digest, Sha256};
        let mut h = Sha256::new();
        h.update(bytes);
        format!("{:x}", h.finalize())
    }

    /// The fixture's root: a REAL keypair, so the manifest signature below really verifies and a
    /// negative that breaks it is breaking something. Built from a repeated byte, not a literal.
    fn fixture_root() -> ed25519_dalek::SigningKey {
        ed25519_dalek::SigningKey::from_bytes(&[7u8; 32])
    }

    fn anchor_document(root_key_id: &str, public_key_hex: &str, provenance: &str) -> String {
        serde_json::json!({
            "root_key_id": root_key_id, "public_key_hex": public_key_hex, "provenance": provenance,
        })
        .to_string()
    }

    fn fixture_anchor(provenance: &str) -> String {
        let public: String =
            fixture_root().verifying_key().to_bytes().iter().map(|b| format!("{b:02x}")).collect();
        anchor_document("brops-live-root-1", &public, provenance)
    }

    /// Replace the pinned anchor FILE and re-pin it at the new bytes' digest — what a provisioner
    /// that wrote a different anchor before taking the pin would leave behind.
    fn with_anchor(mut host: FakeHost, document: &str) -> FakeHost {
        host.files.insert(ANCHOR.into(), document.as_bytes().to_vec());
        let mut pin: TcbPinManifest =
            serde_json::from_slice(host.files.get("/kit/pin.json").unwrap()).unwrap();
        let mut hit = false;
        for a in pin.artifacts.iter_mut().filter(|a| a.logical_name == ROOT_ANCHOR_ROLE) {
            a.expected_sha256 = sha256_hex(document.as_bytes());
            hit = true;
        }
        assert!(hit, "the fixture pins no root anchor");
        host.files.insert("/kit/pin.json".into(), serde_json::to_vec(&pin).unwrap());
        host
    }

    /// The kit's shape, reduced to what the preflight reads. Every requirement that a machine CAN
    /// meet is met here — which is what makes the negative tests below meaningful.
    fn provisioned() -> FakeHost {
        use base64::Engine as _;
        use ed25519_dalek::Signer as _;
        let manifest = r#"{"manifest_epoch":2,"root_key_id":"brops-live-root-1","keys":[]}"#;
        let parsed: KeyManifest = serde_json::from_str(manifest).unwrap();
        let signature = base64::engine::general_purpose::STANDARD
            .encode(fixture_root().sign(&parsed.canonical_bytes()).to_bytes());
        let anchor = fixture_anchor("kit_generated");
        let pin = serde_json::to_string(&TcbPinManifest {
            artifacts: TCB_REQUIRED_ARTIFACTS
                .iter()
                .map(|n| brops_core::tcb_integrity::TcbArtifact {
                    logical_name: (*n).to_string(),
                    // Two roles point at files this fixture also stats or reads, because the
                    // preflight LOCATES those artifacts through the pin manifest — the broker's
                    // config does not name them, and must not (see
                    // `the_provisioned_broker_config_holds_only_keys_the_broker_reads`).
                    path: match *n {
                        "privileged-launcher.bin" => "/kit/privileged-launcher.bin".to_string(),
                        "supervisor.config" => "/kit/supervisor.json".to_string(),
                        _ => format!("/opt/brops-live/tcb/{n}"),
                    },
                    // The anchor is the one pinned file this module READS, and it holds it to the
                    // pinned digest as the broker does; the others it only locates.
                    expected_sha256: if *n == ROOT_ANCHOR_ROLE {
                        sha256_hex(anchor.as_bytes())
                    } else {
                        "0".repeat(64)
                    },
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
                         "requested_at_ms": 1735689600000i64}
        })
        .to_string();
        // The SUPERVISOR's own configuration, which on both kits is a document the supervisor
        // reads and the broker does not. Here it is a separate file so a test can tell the two
        // readers apart.
        let supervisor_cfg =
            serde_json::json!({"supervisor": {"ledger_db": "/kit/supervisor-state/ledger.db"}})
                .to_string();
        FakeHost::linux()
            .env("BROPS_BROKER_CONFIG", "/kit/config.json")
            .file("/kit/config.json", &cfg)
            .file("/kit/supervisor.json", &supervisor_cfg)
            .file("/kit/pin.json", &pin)
            .file("/kit/manifest.json", manifest)
            .file("/kit/manifest.sig", &signature)
            .file(ANCHOR, &anchor)
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
            .account("brops-broker", 5001)
            .account("brops-challenge", 5002)
            .account("brops-sidecar", 5003)
            .account("brops-supervisor", 5004)
            .account("brops-recorder", 5005)
            .account("brops-signer", 5006)
            .account("brops-executor", 5007)
    }

    #[test]
    fn a_provisioned_deployment_meets_everything_a_machine_can_meet() {
        let report = evaluate(&provisioned(), Some("/kit/broker-state/broker.sock"));
        // NOTHING is left over. Until T-131 slice C one row was: the key manifest had to verify
        // under a root compiled into the binary whose private half nobody holds, so no deployment
        // could meet it. The broker now verifies under the floor-pinned anchor file, and a
        // deployment whose manifest is signed by the root in that file meets the row.
        let unexpected: Vec<&str> = report.not_met().iter().map(|f| f.requirement.name).collect();
        assert!(unexpected.is_empty(), "unexpectedly not met: {unexpected:?}\n{}", report.render());
        // …and meeting it is NOT a production claim, which the evidence says in so many words.
        let custody = status_of(&report, "custody.tcb_root_manifest_signature");
        assert!(custody.is_met(), "{custody:?}");
        let d = custody.detail();
        assert!(d.contains("brops-live-root-1") && d.contains(ANCHOR), "{d}");
        assert!(d.contains("provenance `kit_generated`"), "{d}");
        assert!(d.contains("commits as `demonstration_custody`"), "{d}");
        assert!(!d.contains("trusted_verified"), "{d}");
    }

    #[test]
    fn the_provisioner_column_has_the_five_counts_the_table_claims() {
        let count = |p: Provisioner| REQUIREMENTS.iter().filter(|r| r.provisioner == p).count();
        assert_eq!(count(Provisioner::Installer), 13);
        assert_eq!(count(Provisioner::MachineAdministrator), 11);
        assert_eq!(count(Provisioner::InstallMintedRoot), 1);
        assert_eq!(count(Provisioner::NotProvisionableOnAMachine), 1);
        assert_eq!(count(Provisioner::MetByTheBuild), 1);
        assert_eq!(REQUIREMENTS.len(), 27);
        // The one install-minted-root row is the custody row, and its name in a report is the new one.
        let row = REQUIREMENTS.iter().find(|r| r.provisioner == Provisioner::InstallMintedRoot).unwrap();
        assert_eq!(row.name, "custody.tcb_root_manifest_signature");
        assert_eq!(Provisioner::InstallMintedRoot.as_str(), "install-minted-root");
        assert!(row.what.contains("FLOOR-PINNED anchor file"), "{}", row.what);
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

    /// Rewrite one pinned role's path in the fixture's §2.5 manifest.
    fn repin(mut host: FakeHost, role: &str, path: &str) -> FakeHost {
        let mut pin: TcbPinManifest =
            serde_json::from_slice(host.files.get("/kit/pin.json").unwrap()).unwrap();
        let mut hit = false;
        for a in pin.artifacts.iter_mut().filter(|a| a.logical_name == role) {
            a.path = path.to_string();
            hit = true;
        }
        assert!(hit, "the fixture pins no {role}");
        host.files.insert("/kit/pin.json".into(), serde_json::to_vec(&pin).unwrap());
        host
    }

    /// Every dotted leaf path of a JSON document.
    fn leaf_keys(v: &Value, prefix: &str, out: &mut Vec<String>) {
        match v.as_object() {
            Some(m) => {
                for (k, child) in m {
                    let path = if prefix.is_empty() { k.clone() } else { format!("{prefix}.{k}") };
                    leaf_keys(child, &path, out);
                }
            }
            None => out.push(prefix.to_string()),
        }
    }

    #[test]
    fn the_provisioned_broker_config_holds_only_keys_the_broker_reads() {
        // The defect this pins: the fixture's broker config carried `execution.launcher_path` and
        // `supervisor.ledger_db`, which `build_governed_executor` never reads, so two rows passed
        // here and failed against every config the T-111 writer can produce. A key is
        // covered when it, or a block containing it, is in the list the broker reads.
        let host = provisioned();
        let cfg: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        let mut leaves = Vec::new();
        leaf_keys(&cfg, "", &mut leaves);
        let unread: Vec<&String> = leaves
            .iter()
            .filter(|leaf| {
                !CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR.iter().any(|k| {
                    leaf.as_str() == *k || leaf.starts_with(&format!("{k}."))
                })
            })
            .collect();
        assert!(unread.is_empty(), "the fixture's broker config carries unread keys: {unread:?}");
    }

    #[test]
    fn the_launcher_is_the_one_the_pin_manifest_pins() {
        // Repin the launcher to a path that is not setuid: the row must follow the MANIFEST, so it
        // now reports that file, not the fixture's setuid one.
        let host = repin(provisioned(), "privileged-launcher.bin", "/kit/other-launcher.bin")
            .stat("/kit/other-launcher.bin", 0, 0o100755, false);
        let d = status_of(&evaluate(&host, None), "launcher.setuid_root_binary").detail().to_string();
        assert!(d.contains("/kit/other-launcher.bin") && d.contains("not setuid"), "{d}");
    }

    #[test]
    fn a_pin_manifest_that_pins_no_launcher_is_not_met_by_name() {
        let mut host = provisioned();
        let mut pin: TcbPinManifest =
            serde_json::from_slice(host.files.get("/kit/pin.json").unwrap()).unwrap();
        pin.artifacts.retain(|a| a.logical_name != "privileged-launcher.bin");
        host.files.insert("/kit/pin.json".into(), serde_json::to_vec(&pin).unwrap());
        let r = evaluate(&host, None);
        let status = status_of(&r, "launcher.setuid_root_binary");
        assert!(matches!(status, Status::NotMet { .. }), "{status:?}");
        assert!(status.detail().contains("pins no `privileged-launcher.bin`"), "{status:?}");
    }

    #[test]
    fn without_a_pin_manifest_neither_artifact_can_be_located() {
        let mut host = provisioned();
        host.files.remove("/kit/pin.json");
        let r = evaluate(&host, None);
        for row in ["launcher.setuid_root_binary", "store.supervisor_private_0700"] {
            let status = status_of(&r, row);
            assert!(matches!(status, Status::NotMet { .. }), "{row}: {status:?}");
            let d = status.detail();
            assert!(d.contains("located through the §2.5 pin manifest") && d.contains("absent"), "{row}: {d}");
        }
    }

    #[test]
    fn the_ladder_shape_finds_the_ledger_in_another_pinned_config() {
        // The ladder kit pins `ladder.json` under `supervisor.config`, and that document names no
        // ledger; the supervisor reads its ledger from `config.json`, pinned under the other
        // `.config` roles. That is a met row, not a missing ledger.
        let host = repin(provisioned(), "supervisor.config", "/kit/ladder.json")
            .file("/kit/ladder.json", r#"{"protocol":"brops.ladder-kit.v1"}"#);
        let host = repin(host, "isolated-signer.config", "/kit/supervisor.json");
        assert!(status_of(&evaluate(&host, None), "store.supervisor_private_0700").is_met());
    }

    #[test]
    fn no_pinned_document_naming_a_ledger_is_not_met() {
        let host = provisioned().file("/kit/supervisor.json", r#"{"supervisor":{}}"#);
        let r = evaluate(&host, None);
        let status = status_of(&r, "store.supervisor_private_0700");
        assert!(matches!(status, Status::NotMet { .. }), "{status:?}");
        assert!(status.detail().contains("names the supervisor's durable ledger"), "{status:?}");
    }

    #[test]
    fn two_pinned_documents_naming_different_ledgers_are_refused() {
        let host = repin(provisioned(), "isolated-signer.config", "/kit/elsewhere.json").file(
            "/kit/elsewhere.json",
            r#"{"supervisor":{"ledger_db":"/tmp/elsewhere/ledger.db"}}"#,
        );
        let r = evaluate(&host, None);
        let status = status_of(&r, "store.supervisor_private_0700");
        assert!(matches!(status, Status::NotMet { .. }), "{status:?}");
        let d = status.detail();
        assert!(d.contains("2 different supervisor ledgers") && d.contains("will not choose"), "{d}");
    }

    #[test]
    fn a_supervisor_store_owned_by_another_account_is_not_met() {
        let host = provisioned().stat("/kit/supervisor-state", 5001, 0o40700, true);
        let r = evaluate(&host, None);
        let status = status_of(&r, "store.supervisor_private_0700");
        assert!(matches!(status, Status::NotMet { .. }), "{status:?}");
        assert!(status.detail().contains("owned by uid 5001, not the supervisor (uid 5004)"), "{status:?}");
    }

    #[test]
    fn a_uids_block_naming_no_supervisor_cannot_meet_the_store_row() {
        let mut host = provisioned();
        let mut cfg: Value =
            serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["uids"].as_object_mut().unwrap().remove("supervisor");
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let r = evaluate(&host, None);
        let status = status_of(&r, "store.supervisor_private_0700");
        assert!(matches!(status, Status::NotMet { .. }), "{status:?}");
        assert!(status.detail().contains("names no `supervisor`"), "{status:?}");
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
        // The reason named is the one the BROKER returns. This asserted `floor_not_persisted`,
        // which is `ladder_turn`'s outcome string and appears nowhere in the broker's refusal.
        assert!(d.contains("`upstream_blocked`"), "{d}");
        assert!(!d.contains("floor_not_persisted"), "{d}");
    }

    /// ...and that is read off the resolver itself, so the sentence cannot go stale quietly again:
    /// a persist failure maps to `UpstreamBlocked`, and the broker's resolver holds no
    /// `floor_not_persisted` string to emit.
    #[test]
    fn the_brokers_persist_refusal_is_upstream_blocked_and_it_names_no_stage() {
        // CRLF-normalised: `include_str!` reads the checkout's bytes, and a Windows checkout's line
        // endings would otherwise make the two-line needle below unfindable there.
        let resolver = include_str!("manifest_resolver.rs").replace("\r\n", "\n");
        assert!(
            resolver.contains(
                "check_and_persist(&floor, &p.manifest, &p.floor_path)\n                \
                 .map_err(|_| TurnReason::UpstreamBlocked)?"
            ),
            "the resolver no longer maps a persist failure to UpstreamBlocked; the floor row's \
             `refusal` text and `check_floor_custody`'s message describe that mapping"
        );
        assert!(!resolver.contains("floor_not_persisted"));
        let row = REQUIREMENTS.iter().find(|r| r.name == "trust.floor_is_broker_owned_0600").unwrap();
        assert!(row.refusal.contains("`upstream_blocked`"), "{}", row.refusal);
        assert!(row.refusal.contains("PROOF DRIVER"), "{}", row.refusal);
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
        let d = status_of(&r, "db.durable_acceptance_ledger").detail();
        assert!(d.contains("does not exist"), "{d}");
        // What the broker does there is EXIT, before it binds. This said it "serves fail-closed".
        assert!(d.contains("EXIT_DB") && !d.contains("serves fail-closed"), "{d}");
    }

    const LEDGER: &str = "db.durable_acceptance_ledger";

    /// MET means the broker account can create its ledger there — not that a directory exists.
    #[test]
    fn the_ledger_row_is_met_only_by_a_directory_the_broker_owns_and_can_write() {
        let met = evaluate(&provisioned(), Some("/kit/broker-state/broker.sock"));
        let s = status_of(&met, LEDGER);
        assert!(s.is_met(), "{s:?}");
        assert!(s.detail().contains("/kit/broker-state/broker.db"), "{s:?}");

        // A directory that merely EXISTS — root-owned, where the broker's `Connection::open` fails.
        let host = provisioned().stat("/kit/broker-state", 0, 0o40755, true);
        let s = status_of(&evaluate(&host, Some("/kit/broker-state/broker.sock")), LEDGER).clone();
        assert!(matches!(s, Status::NotMet { .. }), "{s:?}");
        assert!(s.detail().contains("owned by uid 0"), "{s:?}");

        // Owned by the broker and not writable by it.
        let host = provisioned().stat("/kit/broker-state", 5001, 0o40500, true);
        let s = status_of(&evaluate(&host, Some("/kit/broker-state/broker.sock")), LEDGER).clone();
        assert!(matches!(s, Status::NotMet { .. }), "{s:?}");
        assert!(s.detail().contains("mode 500"), "{s:?}");

        // A regular file where the directory should be.
        let host = provisioned().stat("/kit/broker-state", 5001, 0o100600, false);
        let s = status_of(&evaluate(&host, Some("/kit/broker-state/broker.sock")), LEDGER).clone();
        assert!(s.detail().contains("is not a directory"), "{s:?}");

        // No `uids.broker` to compare the owner with.
        let mut host = provisioned();
        let mut cfg: Value = serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["uids"].as_object_mut().unwrap().remove("broker");
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let s = status_of(&evaluate(&host, Some("/kit/broker-state/broker.sock")), LEDGER).clone();
        assert!(matches!(s, Status::NotMet { .. }), "{s:?}");
        assert!(s.detail().contains("`uids.broker` is not declared"), "{s:?}");
    }

    /// A socket path with no `.sock` suffix has no database path — the broker refuses to start on
    /// it — and the row says so instead of measuring the socket's own directory and reporting MET.
    #[test]
    fn a_socket_path_without_the_sock_suffix_cannot_meet_the_ledger_row() {
        for socket in ["/kit/broker-state/broker", "/kit/broker-state/broker.socket"] {
            let s = status_of(&evaluate(&provisioned(), Some(socket)), LEDGER).clone();
            assert!(matches!(s, Status::NotMet { .. }), "{socket}: {s:?}");
            assert!(s.detail().contains("does not end in `.sock`"), "{socket}: {s:?}");
        }
    }

    // ---- the accounts exist ------------------------------------------------------------------

    /// Seven distinct NUMBERS are not seven accounts. Every uid the deployment declares is looked
    /// up; until it was, only the sidecar — the one named by account — had ever been resolved.
    #[test]
    fn a_declared_uid_that_no_account_holds_cannot_meet_the_seven_accounts_row() {
        const ROW: &str = "principals.seven_distinct_accounts";
        assert!(status_of(&evaluate(&provisioned(), None), ROW).is_met());

        let mut host = provisioned();
        host.accounts.remove("brops-signer");
        host.accounts.remove("brops-executor");
        let s = status_of(&evaluate(&host, None), ROW).clone();
        assert!(matches!(s, Status::NotMet { .. }), "{s:?}");
        assert!(s.detail().contains("[5006, 5007]"), "the unowned uids are named: {s:?}");
        assert!(s.detail().contains("no account on this machine holds"), "{s:?}");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn the_real_host_resolves_a_uid_to_its_account_and_an_unheld_uid_to_nothing() {
        assert_eq!(RealHost.uid_account(0).as_deref(), Some("root"));
        // `(uid_t)-2`: not `nobody` (65534) and not `(uid_t)-1`, and no account database holds it.
        assert_eq!(RealHost.uid_account(u32::MAX - 1), None);
    }

    // ---- off Linux --------------------------------------------------------------------------

    /// The fully provisioned deployment, described to a host that is not Linux.
    fn provisioned_off_linux() -> FakeHost {
        let mut host = provisioned();
        host.linux = false;
        host
    }

    /// Off Linux `stat` answers `None` for every path. Three checks called it without asking the
    /// platform first, so files that EXIST were reported "does not exist" / "which is absent" —
    /// NOT MET, a statement about the machine, where the truth is that nothing was measured.
    #[test]
    fn off_linux_nothing_is_reported_absent_because_stat_could_not_answer() {
        let host = provisioned_off_linux();
        let report = evaluate(&host, Some("/kit/broker-state/broker.sock"));
        for row in ["content.messages_db", "sidecar.spawn_triple", "db.durable_acceptance_ledger"] {
            let s = status_of(&report, row);
            assert!(matches!(s, Status::Unmeasurable { .. }), "{row}: {s:?}");
        }
        // The comment on the non-unix `RealHost::stat` — every caller is gated on the platform —
        // as a measurement: across the WHOLE report, nobody asked.
        assert_eq!(host.stat_calls.get(), 0, "a check called `stat` without asking the platform");
        // And no finding at all words a non-answer as an absence.
        for f in &report.findings {
            let d = f.status.detail();
            assert!(
                !(d.contains("does not exist") || d.contains("which is absent") || d.contains("is absent")),
                "{}: {d}",
                f.requirement.name
            );
        }
    }

    /// What IS decidable off Linux stays decided: an unset key is a fact about the config.
    #[test]
    fn off_linux_an_unset_key_is_still_not_met_rather_than_unmeasurable() {
        let mut host = provisioned_off_linux();
        let mut cfg: Value = serde_json::from_slice(host.files.get("/kit/config.json").unwrap()).unwrap();
        cfg["content"].as_object_mut().unwrap().remove("messages_db");
        cfg["sidecar"].as_object_mut().unwrap().remove("script");
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let report = evaluate(&host, Some("/kit/broker-state/broker"));
        assert!(matches!(status_of(&report, "content.messages_db"), Status::NotMet { .. }));
        let triple = status_of(&report, "sidecar.spawn_triple");
        assert!(matches!(triple, Status::NotMet { .. }), "{triple:?}");
        assert!(triple.detail().contains("`sidecar.script` is unset"), "{triple:?}");
        // ...and so is a socket path the broker would refuse on any platform.
        assert!(matches!(status_of(&report, LEDGER), Status::NotMet { .. }));
    }

    const CUSTODY: &str = "custody.tcb_root_manifest_signature";

    fn custody_of(host: &FakeHost) -> Status {
        status_of(&evaluate(host, None), CUSTODY).clone()
    }

    #[test]
    fn a_manifest_under_another_root_cannot_meet_the_custody_requirement() {
        // The anchor file holds a DIFFERENT key under the same id — a manifest and an anchor from
        // two provisioning runs. Pinned honestly, parses, and the signature does not verify.
        let other = anchor_document("brops-live-root-1", &"ab".repeat(32), "kit_generated");
        let s = custody_of(&with_anchor(provisioned(), &other));
        assert!(!s.is_met(), "{s:?}");
        let d = s.detail();
        assert!(d.contains("does not verify under root `brops-live-root-1`"), "{d}");
        assert!(d.contains(ANCHOR), "{d}");

        // ...and the same key under another id: the manifest names a root the anchor is not.
        let public: String =
            fixture_root().verifying_key().to_bytes().iter().map(|b| format!("{b:02x}")).collect();
        let renamed = anchor_document("some-other-root", &public, "kit_generated");
        let s = custody_of(&with_anchor(provisioned(), &renamed));
        assert!(!s.is_met(), "{s:?}");
        assert!(s.detail().contains("UnknownRoot"), "{}", s.detail());

        // A signature that is not one.
        let mut host = provisioned();
        host.files.insert("/kit/manifest.sig".into(), b"AAAA".to_vec());
        let s = custody_of(&host);
        assert!(!s.is_met(), "{s:?}");
    }

    #[test]
    fn the_anchor_is_the_floor_pinned_one_and_no_other_file_can_stand_in() {
        // No pin manifest: there is no anchor to find, and a config key cannot supply one.
        let mut host = provisioned();
        host.files.remove("/kit/pin.json");
        let cfg = String::from_utf8(host.files.get("/kit/config.json").unwrap().clone()).unwrap();
        let mut cfg: Value = serde_json::from_str(&cfg).unwrap();
        cfg["trust"]["root_anchor_path"] = Value::String(ANCHOR.into());
        host.files.insert("/kit/config.json".into(), cfg.to_string().into_bytes());
        let s = custody_of(&host);
        assert!(!s.is_met(), "a config-named anchor met the row: {s:?}");
        assert!(s.detail().contains("located through the §2.5 pin manifest"), "{}", s.detail());

        // The manifest pins NO anchor role.
        let mut host = provisioned();
        let mut pin: TcbPinManifest =
            serde_json::from_slice(host.files.get("/kit/pin.json").unwrap()).unwrap();
        pin.artifacts.retain(|a| a.logical_name != ROOT_ANCHOR_ROLE);
        host.files.insert("/kit/pin.json".into(), serde_json::to_vec(&pin).unwrap());
        let s = custody_of(&host);
        assert!(!s.is_met(), "{s:?}");
        assert!(s.detail().contains("does not pin exactly one"), "{}", s.detail());

        // It pins TWO.
        let mut host = provisioned();
        let mut pin: TcbPinManifest =
            serde_json::from_slice(host.files.get("/kit/pin.json").unwrap()).unwrap();
        let mut second =
            pin.artifacts.iter().find(|a| a.logical_name == ROOT_ANCHOR_ROLE).unwrap().clone();
        second.path = "/kit/substitute-anchor.json".into();
        pin.artifacts.push(second);
        host.files.insert("/kit/pin.json".into(), serde_json::to_vec(&pin).unwrap());
        let s = custody_of(&host);
        assert!(!s.is_met(), "{s:?}");
        assert!(s.detail().contains("AmbiguousRole"), "{}", s.detail());

        // The pinned file is not there.
        let mut host = provisioned();
        host.files.remove(ANCHOR);
        let s = custody_of(&host);
        assert!(!s.is_met(), "{s:?}");
        assert!(s.detail().contains("absent or unreadable"), "{}", s.detail());
    }

    #[test]
    fn an_anchor_changed_since_the_pin_is_not_met_whatever_it_now_says() {
        // The relabel, done AFTER the pin: same key, the word changed to `install_minted`. The
        // broker refuses to parse a file the floor never measured, and so does this row.
        let mut host = provisioned();
        host.files.insert(ANCHOR.into(), fixture_anchor("install_minted").into_bytes());
        let s = custody_of(&host);
        assert!(!s.is_met(), "{s:?}");
        assert!(s.detail().contains("changed after the floor measured it"), "{}", s.detail());
    }

    #[test]
    fn an_anchor_stating_no_known_provenance_or_a_false_external_is_not_met() {
        for (provenance, reason) in [
            ("", "provenance_unknown"),
            ("production", "provenance_unknown"),
            ("external", "external_not_the_pinned_root"),
        ] {
            let s = custody_of(&with_anchor(provisioned(), &fixture_anchor(provenance)));
            assert!(!s.is_met(), "{provenance:?}: {s:?}");
            assert!(s.detail().contains(&format!("is refused: {reason}")), "{}", s.detail());
        }
        let s = custody_of(&with_anchor(provisioned(), "{ not json"));
        assert!(s.detail().contains("is refused: not_json"), "{}", s.detail());
    }

    #[test]
    fn an_install_minted_anchor_meets_the_row_and_the_evidence_says_it_is_not_production() {
        // Pinned AS install_minted (the install wrote it before the pin was taken). The row is
        // met: the manifest verifies under the floor-pinned root. The label is not production,
        // because the Owner's line ships closed — and the evidence must say so rather than leave
        // a reader to infer it from the word MET.
        let s = custody_of(&with_anchor(provisioned(), &fixture_anchor("install_minted")));
        assert!(s.is_met(), "{s:?}");
        let d = s.detail();
        assert!(d.contains("provenance `install_minted`"), "{d}");
        assert!(d.contains("commits as `demonstration_custody`"), "{d}");
        assert!(d.contains("does NOT establish: production custody"), "{d}");
    }

    #[test]
    fn the_custody_resolver_is_wired_in_the_shipped_broker() {
        // This test used to assert the opposite -- that the requirement could NEVER be met, because
        // `main.rs` built `ChainExecutor::new` and no provisioning could change a line of code. The
        // Owner decided on 2026-09-19 to wire it (docs/OWNER_ACTION_REQUIRED.md), so the assertion is
        // inverted rather than deleted: reverting the wiring must fail a test, not quietly restore a
        // refusal that two roadmap rows were waiting on.
        //
        // Read out of `main.rs`'s own source, for the same reason the config-key test is: a status this
        // module PRINTS could agree with itself while the binary did something else.
        let r = evaluate(&provisioned(), None);
        let s = status_of(&r, "custody.committed_label_resolver");
        assert!(s.is_met(), "{s:?}");
        let d = s.detail();
        assert!(d.contains("with_custody"), "{d}");
        assert!(d.contains("does NOT establish"), "the evidence must state its own limit: {d}");

        let main_rs = include_str!("main.rs");
        assert!(
            main_rs.contains("ChainExecutor::with_custody"),
            "the shipped broker no longer wires custody; this requirement is not met by the build"
        );
        assert!(
            main_rs.contains("resolver.custody()"),
            "the custody resolver must come from the key resolver that made the observation"
        );
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
