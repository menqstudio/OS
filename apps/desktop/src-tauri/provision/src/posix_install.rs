//! **The POSIX installer**: root mints the trust anchor the application may only find.
//!
//! # Why this exists
//!
//! [`crate::anchor::preprovision_refusal`] refuses the APPLICATION on POSIX, and it is right to:
//! an owner may always `chmod` what it owns, so an anchor the application's own account built is
//! one that account can rewrite. The anchor therefore has to be created by a DIFFERENT uid,
//! before the application starts. This module is that different uid's half, and
//! `src/bin/brops_install_anchor.rs` is the thin binary over it. Nothing on the application's
//! launch path calls anything here, and no refusal there was relaxed to make room for it.
//!
//! # What it does, in the order it does it
//!
//! 1. refuses unless the effective uid is 0 ([`refuse_unless_root`]);
//! 2. refuses an anchor that is already there unless it VERIFIES for the desktop account — and
//!    never overwrites, repairs or re-mints one ([`settle_existing`]);
//! 3. mints with the crate's one and only `mint` — the same key generation, the same registry
//!    payload, the same destruction of the operator-root private half before it returns — into
//!    a staging directory only root can enter;
//! 4. writes the anchor (pin, floor, registry, manifest) as root, `0755` / `0644`, with the
//!    crate's one and only `write_anchor_files`;
//! 5. hands the app-side store to the desktop account and lets a child **running as that
//!    account** put it in place;
//! 6. and then, as its final act, PROVES it: [`prove_for_desktop_user`].
//!
//! # Root never writes inside the desktop account's tree
//!
//! The obvious construction — root mints into `<app_data>/trust` and `chown -R`s it — is a
//! privilege-escalation primitive. `<app_data>` belongs to the desktop account, so between any
//! two of root's path lookups that account can rename the directory aside and substitute its
//! own; root would then write key files, or change the owner of whatever a planted hard link
//! names, somewhere of the desktop account's choosing.
//!
//! So root touches only what the desktop account cannot: the machine root, and a handoff
//! directory inside it. The store is minted there, hashed there, `lchown`-ed there (children
//! before their parent, so the tree is unreachable until the last call), and a child that has
//! **dropped to the desktop uid** copies it into `<app_data>/trust`. That child can do nothing
//! the desktop account could not already do by hand. The files end up owned by the desktop
//! account because the desktop account created them.
//!
//! # A floor measured by root is not the desktop account's
//!
//! Root can read and write everything, so nothing root observes about the anchor says anything
//! about whether the application will start. `verify_existing` run by root does not even
//! return `Ok` — `PosixOwnership::RunningAsRoot` refuses, correctly. The proof is therefore run
//! by a child process whose uid and gid ARE the desktop account's
//! ([`verify_as_current_account`], reached through [`run_as`]), and it is the application's own
//! launch-time function, not a restatement of it.
//!
//! ## And a floor measured without the account's groups is not the account's either
//!
//! `std::process::Command::uid` drops every supplementary group when it drops root, and stable
//! Rust offers no way to restore the desktop account's real ones (`CommandExt::groups` is
//! unstable; this crate has no `libc`). A group-writable ancestor would therefore be refused to
//! the child and granted to the real desktop session. That gap is closed from the other side,
//! by root, statically: [`measure_floor`] refuses any group- or other-writable bit on the
//! anchor, on anything in it, and on every ancestor up to `/`. With no such bit anywhere on the
//! path, group membership cannot grant a write, so the child's verdict and the real session's
//! are the same verdict. (A POSIX ACL cannot hide from that check: the permissions an ACL
//! grants any named user or group are bounded by its mask, and `stat` reports the mask as the
//! group bits.)
//!
//! # What this does NOT do
//!
//! * It creates no account. The anchor is owned by the installing uid — root.
//! * It installs no audit signer. If one has already published its custody record under the
//!   machine root, the mint admits it, exactly as the application's own call does; otherwise
//!   the registry is sealed without one.
//! * It is not atomic against `kill -9` or power loss. A run that dies between writing the
//!   manifest and delivering the store leaves an anchor that verifies for nobody; the next run
//!   refuses it by name and an administrator has to remove it. A run that FAILS — rather than
//!   dies — removes everything it created under the machine root and any store it delivered;
//!   an application data DIRECTORY the delivery had to create is left, empty and the desktop
//!   account's own.
//! * It does not decide where the application's data directory is. `--app-data` is required
//!   and must be spelled exactly as the application computes it, because the manifest binds
//!   that string; a guessed default would make the installer report success for a launch that
//!   then refuses with "provisioned for a different trust store".

use std::ffi::OsStr;
use std::os::unix::fs::MetadataExt;
use std::os::unix::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Output, Stdio};

use crate::anchor::{self, CUSTODY_REMEDY, INSTALLER_TOOL, MANIFEST_FILE};
use crate::{Exposure, ProvisionError, TRUST_DIR};

/// The first line [`verify_as_current_account`] reports, followed by ` uid=<n>`.
pub const VERIFIED_MARKER: &str = "brops-anchor-verified";

/// The anchor's directories and files, as modes. [`Exposure::WorldReadable`] restated as
/// numbers, because [`floor_refusal`] compares against what `stat` returns.
pub const ANCHOR_DIR_MODE: u32 = Exposure::WorldReadable.dir_mode();
pub const ANCHOR_FILE_MODE: u32 = Exposure::WorldReadable.file_mode();

/// How deep [`measure_floor`] walks. The real anchor is two directories deep.
const MAX_DEPTH: usize = 8;

fn refuse<T>(what: impl Into<String>) -> Result<T, ProvisionError> {
    Err(ProvisionError::Unsupported {
        platform: crate::platform_name().to_string(),
        what: what.into(),
    })
}

fn custody<T>(path: &Path, what: impl Into<String>) -> Result<T, ProvisionError> {
    Err(ProvisionError::Custody {
        path: path.to_path_buf(),
        what: what.into(),
        remedy: CUSTODY_REMEDY.to_string(),
    })
}

// ---------------------------------------------------------------------------
// The pure parts: who, as whom, with what arguments
// ---------------------------------------------------------------------------

/// Refuse unless the installer is root. Pure: the caller measures the uid.
///
/// Not a formality. The whole construction rests on the anchor being owned by a uid the
/// application is not; an installer run by the desktop account would mint an anchor that
/// account owns, which is the application building its own anchor by another name.
pub fn refuse_unless_root(euid: u32) -> Result<(), ProvisionError> {
    if euid == 0 {
        return Ok(());
    }
    refuse(format!(
        "{INSTALLER_TOOL} must be run as root, and this process is uid {euid}. The trust anchor \
         has to be owned by a uid the application is NOT: an anchor minted by the account that \
         will read it is one that account can chmod and rewrite, which is the pin-rewrite \
         attack the anchor exists to close. Nothing was created"
    ))
}

/// The desktop account the application will run as.
///
/// Name and ids, and nothing else. It used to carry `home` as well — passwd field 6, parsed and
/// stored and read by nothing: the application-data path arrives through `--app-data`, and the
/// one decision that is about home directories ([`anchor::home_directory_collision`]) reads the
/// passwd text itself. A field nobody reads is a field somebody will one day trust.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DesktopUser {
    pub name: String,
    pub uid: u32,
    pub gid: u32,
}

/// Resolve `--user <name>` against the CONTENT of `/etc/passwd`. Pure, so it is tested with
/// fixtures wherever this module is compiled — which is every UNIX machine and not Windows:
/// the module is `#[cfg(unix)]` (see `lib.rs`), and so is `tests/posix_install.rs`.
/// [`read_passwd`] is the only part that touches the filesystem.
///
/// Refused, each by name:
///
/// * a name that is empty or could not be a passwd field;
/// * a name `/etc/passwd` does not list — including an account that exists only in LDAP or
///   `systemd-homed`, which this does not consult and says so;
/// * a name listed twice with different ids, because "the first one" is a guess about which
///   account the anchor is being built against;
/// * a line whose uid or gid is not a number;
/// * **uid 0**. An application running as root has no anchor anywhere on the machine
///   (`PosixOwnership::RunningAsRoot`), so minting one "for root" would report success for a
///   launch that is certain to refuse.
pub fn resolve_user(passwd: &str, name: &str) -> Result<DesktopUser, ProvisionError> {
    if name.is_empty() || name.contains([':', '\n', '\r', '/', '\0']) {
        return refuse(format!("--user {name:?} is not an account name"));
    }
    let mut found: Option<DesktopUser> = None;
    for line in passwd.lines() {
        let line = line.trim_end_matches(['\r', '\n']);
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let fields: Vec<&str> = line.split(':').collect();
        // Six fields is a whole passwd line up to the home directory. The home itself is not
        // read here, but a line too short to have one is not an account entry.
        if fields.len() < 6 || fields[0] != name {
            continue;
        }
        let (uid, gid) = match (fields[2].parse::<u32>(), fields[3].parse::<u32>()) {
            (Ok(uid), Ok(gid)) => (uid, gid),
            _ => {
                return refuse(format!(
                    "the passwd entry for {name:?} has a uid or gid that is not a number \
                     ({:?}, {:?})",
                    fields[2], fields[3]
                ))
            }
        };
        let user = DesktopUser { name: name.to_string(), uid, gid };
        match &found {
            Some(first) if first.uid != user.uid || first.gid != user.gid => {
                return refuse(format!(
                    "the account {name:?} is listed more than once with different ids (uid {} \
                     gid {}, then uid {uid} gid {gid}). Choosing one would be guessing which \
                     account the anchor is built against",
                    first.uid, first.gid
                ))
            }
            Some(_) => {}
            None => found = Some(user),
        }
    }
    let Some(user) = found else {
        return refuse(format!(
            "no account named {name:?} is listed in /etc/passwd. This installer reads that file \
             and nothing else — an account that exists only in LDAP, NIS or systemd-homed is \
             not resolved, and no uid is guessed for it"
        ));
    };
    if user.uid == 0 {
        return refuse(format!(
            "--user {name:?} is uid 0. An application running as root has no trust anchor \
             anywhere on this machine — root rewrites any file regardless of owner or mode — so \
             an anchor minted for it would report success for a launch that is certain to refuse"
        ));
    }
    Ok(user)
}

/// `/etc/passwd`, or a refusal. Unlike [`anchor::precheck_location`] this does not shrug at an
/// unreadable file: root can always read it, and both decisions that need it — who the desktop
/// account is, and whether the machine root is somebody's home — must not be skipped.
pub fn read_passwd() -> Result<String, ProvisionError> {
    let path = Path::new("/etc/passwd");
    std::fs::read_to_string(path).map_err(|source| ProvisionError::Io {
        what: "reading the account database".into(),
        path: path.to_path_buf(),
        source,
    })
}

/// Refuse a path that could mean two things. `label` is the flag it arrived under.
///
/// The manifest binds `<app_data>/trust` as a STRING and `verify_store` compares it, on every
/// launch, with the string the application computes for itself. So a path that is relative, or
/// carries `.` / `..`, or is not UTF-8, is not merely untidy: it is an anchor bound to a
/// spelling the application will never produce.
pub fn refuse_ambiguous_path(label: &str, path: &Path) -> Result<(), ProvisionError> {
    if path.to_str().is_none() {
        return refuse(format!("{label} is not valid UTF-8: {}", path.display()));
    }
    if !path.is_absolute() {
        return refuse(format!("{label} must be an absolute path, got {}", path.display()));
    }
    if path.components().any(|c| matches!(c, Component::CurDir | Component::ParentDir)) {
        return refuse(format!(
            "{label} must not contain `.` or `..` components, got {}",
            path.display()
        ));
    }
    if path.parent().is_none() {
        return refuse(format!("{label} must not be the filesystem root"));
    }
    Ok(())
}

/// Refuse a machine root that is, contains, or sits inside an account's home directory.
///
/// [`anchor::precheck_location`] asks the same question for the application and shrugs when
/// `/etc/passwd` cannot be read. The installer does not get to shrug: it is root, it is about
/// to create directories, and the first real Debian box showed what the unasked version does —
/// it left a service account's home owned by root.
pub fn refuse_home_collision(machine_root: &Path, passwd: &str) -> Result<(), ProvisionError> {
    match anchor::home_directory_collision(machine_root, passwd) {
        None => Ok(()),
        Some((account, home)) => custody(
            machine_root,
            format!(
                "the machine root {} collides with the home directory of the account \
                 {account:?} ({}). A trust anchor and an account's home must never be the same \
                 tree. Nothing was created",
                machine_root.display(),
                home.display()
            ),
        ),
    }
}

/// What the binary was asked to do.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Invocation {
    /// `--user NAME --app-data DIR [--machine-root DIR]` — the installer proper. Root only.
    Install { user: String, app_data: PathBuf, machine_root: Option<PathBuf> },
    /// `verify --app-data DIR [--machine-root DIR]` — the application's launch-time check, run
    /// as whoever invokes it. The installer runs this as the desktop account; an operator may
    /// run it by hand to ask the same question.
    Verify { app_data: PathBuf, machine_root: Option<PathBuf> },
    /// `deliver --from DIR --app-data DIR` — internal: the desktop-uid child that puts the
    /// app-side store in place.
    Deliver { from: PathBuf, app_data: PathBuf },
    /// `rollback --app-data DIR` — internal: the desktop-uid child that removes a store this
    /// same run delivered, when the run then fails.
    Rollback { app_data: PathBuf },
    Help,
}

pub const USAGE: &str = "\
usage:
  brops_install_anchor --user <desktop account> --app-data <dir> [--machine-root <dir>]
      Run ONCE, AS ROOT, at install time. Mints the trust anchor under the machine root
      (default /var/lib/brops-trust-anchor), owned by root, and delivers the application's
      retained keys to <dir>/trust as the desktop account. Refuses an anchor that is already
      there unless it verifies for that account; never overwrites one.
      <dir> must be EXACTLY the application data directory the application computes for
      itself: the anchor binds that string.

  brops_install_anchor verify --app-data <dir> [--machine-root <dir>]
      Run the application's own launch-time verification as the invoking account.
";

/// Parse the arguments after the program name. Pure.
///
/// Strict on purpose: an unknown flag, a repeated flag, a flag without a value and a stray
/// positional are all refused. An installer that ignored `--machine-rooot /x` would mint into
/// the production path while its caller believed otherwise.
pub fn parse_args(args: &[String]) -> Result<Invocation, String> {
    if args.is_empty() {
        return Err("no arguments".to_string());
    }
    if args.iter().any(|a| a == "--help" || a == "-h") {
        return Ok(Invocation::Help);
    }
    let (mode, rest) = match args[0].as_str() {
        "verify" | "deliver" | "rollback" => (args[0].as_str(), &args[1..]),
        _ => ("install", args),
    };
    let allowed: &[&str] = match mode {
        "install" => &["--user", "--app-data", "--machine-root"],
        "verify" => &["--app-data", "--machine-root"],
        "deliver" => &["--from", "--app-data"],
        _ => &["--app-data"],
    };
    let mut values: Vec<(&str, &str)> = Vec::new();
    let mut i = 0;
    while i < rest.len() {
        let flag = rest[i].as_str();
        if !allowed.contains(&flag) {
            return Err(format!("unexpected argument {flag:?} for `{mode}`"));
        }
        if values.iter().any(|(f, _)| *f == flag) {
            return Err(format!("{flag} was given more than once"));
        }
        let Some(value) = rest.get(i + 1) else {
            return Err(format!("{flag} needs a value"));
        };
        if value.is_empty() || value.starts_with("--") {
            return Err(format!("{flag} needs a value, got {value:?}"));
        }
        values.push((flag, value.as_str()));
        i += 2;
    }
    let get = |flag: &str| values.iter().find(|(f, _)| *f == flag).map(|(_, v)| *v);
    let need = |flag: &str| get(flag).ok_or_else(|| format!("{flag} is required for `{mode}`"));
    Ok(match mode {
        "install" => Invocation::Install {
            user: need("--user")?.to_string(),
            app_data: PathBuf::from(need("--app-data")?),
            machine_root: get("--machine-root").map(PathBuf::from),
        },
        "verify" => Invocation::Verify {
            app_data: PathBuf::from(need("--app-data")?),
            machine_root: get("--machine-root").map(PathBuf::from),
        },
        "deliver" => Invocation::Deliver {
            from: PathBuf::from(need("--from")?),
            app_data: PathBuf::from(need("--app-data")?),
        },
        _ => Invocation::Rollback { app_data: PathBuf::from(need("--app-data")?) },
    })
}

// ---------------------------------------------------------------------------
// The floor root can measure: ownership and mode bits, statically
// ---------------------------------------------------------------------------

/// What a path on the anchor's chain is, for [`floor_refusal`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    /// The anchor directory or a directory inside it: exactly `0755`.
    AnchorDir,
    /// A file inside the anchor: exactly `0644`.
    AnchorFile,
    /// A directory above the anchor, up to `/`: no group- or other-write bit.
    Ancestor,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Dir,
    File,
    Symlink,
    Other,
}

/// Does this one path break the anchor's floor? `Some(why)` when it does. Pure.
///
/// `owner` is the installing uid. Every path on the chain must belong to it — "a uid this
/// process is not" is the application's question, and it would be satisfied by an ancestor
/// owned by some third account that can rename the anchor aside whenever it likes. The
/// installer asks the stricter question because it is the one in a position to.
pub fn floor_refusal(role: Role, kind: Kind, uid: u32, mode: u32, owner: u32) -> Option<String> {
    let mode = mode & 0o7777;
    let wanted_kind = if role == Role::AnchorFile { Kind::File } else { Kind::Dir };
    if kind != wanted_kind {
        return Some(format!("it is a {kind:?} where a {wanted_kind:?} belongs"));
    }
    if uid != owner {
        return Some(format!(
            "it is owned by uid {uid}, not by the installing uid {owner}, so an account other \
             than the installer can chmod it"
        ));
    }
    match role {
        Role::AnchorDir if mode != ANCHOR_DIR_MODE => {
            Some(format!("its mode is {mode:04o}, not {ANCHOR_DIR_MODE:04o}"))
        }
        Role::AnchorFile if mode != ANCHOR_FILE_MODE => {
            Some(format!("its mode is {mode:04o}, not {ANCHOR_FILE_MODE:04o}"))
        }
        Role::Ancestor if mode & 0o022 != 0 => Some(format!(
            "its mode is {mode:04o}, which lets a group or everyone create and rename entries \
             in it — including the anchor's own path"
        )),
        _ => None,
    }
}

fn kind_of(meta: &std::fs::Metadata) -> Kind {
    let t = meta.file_type();
    if t.is_symlink() {
        Kind::Symlink
    } else if t.is_dir() {
        Kind::Dir
    } else if t.is_file() {
        Kind::File
    } else {
        Kind::Other
    }
}

fn stat(path: &Path, follow: bool) -> Result<std::fs::Metadata, ProvisionError> {
    let result = if follow { std::fs::metadata(path) } else { std::fs::symlink_metadata(path) };
    result.map_err(|source| ProvisionError::Io {
        what: "stat-ing a component of the trust anchor's path".into(),
        path: path.to_path_buf(),
        source,
    })
}

fn check(path: &Path, role: Role, owner: u32, seen: &mut Vec<String>) -> Result<(), ProvisionError> {
    let meta = stat(path, false)?;
    let (kind, uid, mode) = (kind_of(&meta), meta.uid(), meta.mode());
    if let Some(why) = floor_refusal(role, kind, uid, mode, owner) {
        return custody(path, format!("{} breaks the anchor's floor: {why}", path.display()));
    }
    seen.push(format!("{} -> uid {uid} mode {:04o}", path.display(), mode & 0o7777));
    Ok(())
}

/// Every existing directory above `path`, nearest first, checked as [`Role::Ancestor`].
///
/// Also refuses a path that is not its own canonical form. The walk is lexical, so a symlink
/// anywhere in the path would leave the link target's real ancestors unmeasured — and the
/// engine refuses a symlink at any component of the pin's path for the same reason.
fn check_ancestors(path: &Path, owner: u32, seen: &mut Vec<String>) -> Result<(), ProvisionError> {
    let mut deepest: Option<&Path> = Some(path);
    while let Some(p) = deepest {
        if std::fs::symlink_metadata(p).is_ok() {
            break;
        }
        deepest = p.parent();
    }
    let Some(deepest) = deepest else {
        return custody(path, "no existing directory above the anchor could be found to measure");
    };
    let canonical = std::fs::canonicalize(deepest).map_err(|source| ProvisionError::Io {
        what: "resolving the trust anchor's path".into(),
        path: deepest.to_path_buf(),
        source,
    })?;
    if canonical != deepest {
        return custody(
            deepest,
            format!(
                "{} resolves to {}, so a symlink sits somewhere on the anchor's path and the \
                 directories above its target were never measured. Name the real path",
                deepest.display(),
                canonical.display()
            ),
        );
    }
    let mut component = if deepest == path { path.parent() } else { Some(deepest) };
    while let Some(p) = component {
        check(p, Role::Ancestor, owner, seen)?;
        component = p.parent();
    }
    Ok(())
}

fn check_tree(dir: &Path, owner: u32, seen: &mut Vec<String>, depth: usize) -> Result<(), ProvisionError> {
    if depth > MAX_DEPTH {
        return custody(dir, format!("the anchor is nested more than {MAX_DEPTH} directories deep"));
    }
    check(dir, Role::AnchorDir, owner, seen)?;
    let listing = std::fs::read_dir(dir).map_err(|source| ProvisionError::Io {
        what: "listing the trust anchor directory".into(),
        path: dir.to_path_buf(),
        source,
    })?;
    let mut entries = Vec::new();
    for entry in listing {
        let entry = entry.map_err(|source| ProvisionError::Io {
            what: "reading the trust anchor directory".into(),
            path: dir.to_path_buf(),
            source,
        })?;
        entries.push(entry.path());
    }
    entries.sort();
    for path in entries {
        if stat(&path, false)?.file_type().is_dir() {
            check_tree(&path, owner, seen, depth + 1)?;
        } else {
            check(&path, Role::AnchorFile, owner, seen)?;
        }
    }
    Ok(())
}

/// The static half of the proof, taken by root: the anchor, everything in it and every
/// ancestor up to `/` belong to `owner` and carry no group- or other-write bit.
///
/// This is NOT the proof that the desktop account cannot write the anchor — root's view of
/// that question is worthless. It is the measurement that makes the desktop-uid child's
/// verdict transferable to the real desktop session: see the module documentation.
pub fn measure_floor(anchor_dir: &Path, owner: u32) -> Result<Vec<String>, ProvisionError> {
    let mut seen = Vec::new();
    check_tree(anchor_dir, owner, &mut seen, 0)?;
    check_ancestors(anchor_dir, owner, &mut seen)?;
    Ok(seen)
}

// ---------------------------------------------------------------------------
// An anchor that is already there
// ---------------------------------------------------------------------------

/// Decide what to do about whatever is already at the anchor path.
///
/// * nothing there → `Ok(None)`: the caller may mint;
/// * a manifest there → `verify` is run, and its verdict is final. `Ok(Some(proof))` when it
///   passes — the install is already done, which is what makes a second run idempotent — and
///   a refusal when it does not. **There is no branch that mints over it.** An anchor that
///   does not verify is damaged, or tampered with, or belongs to a different account, and
///   replacing it would destroy the evidence of which while rotating every key under an
///   application that may be running;
/// * a directory there with no manifest → refused, exactly as `provision_with_anchor` refuses
///   it: a half-removed anchor or somebody else's directory.
///
/// "There" is asked with `symlink_metadata`, not `is_file`: a manifest that is a dangling
/// symlink or a directory is not "no manifest", it is a manifest-shaped thing that must not be
/// minted over.
pub fn settle_existing<T>(
    anchor_dir: &Path,
    verify: impl FnOnce() -> Result<T, ProvisionError>,
) -> Result<Option<T>, ProvisionError> {
    let manifest = anchor_dir.join(MANIFEST_FILE);
    if std::fs::symlink_metadata(&manifest).is_ok() {
        return match verify() {
            Ok(proof) => Ok(Some(proof)),
            Err(why) => refuse(format!(
                "a trust anchor is ALREADY installed at {} and it does not verify: {why} — \
                 NOTHING WAS CHANGED. {INSTALLER_TOOL} never overwrites, repairs or re-mints an \
                 existing anchor: one that fails verification is damaged, tampered with, or \
                 was minted for a different account or data directory, and replacing it would \
                 destroy the evidence of which. An administrator must decide, and remove it by \
                 hand before this can run again",
                anchor_dir.display()
            )),
        };
    }
    if std::fs::symlink_metadata(anchor_dir).is_ok() {
        return Err(ProvisionError::Corrupt {
            what: "the trust anchor path already holds something that is not a provisioned anchor"
                .to_string(),
            detail: format!(
                "{} exists but has no {MANIFEST_FILE}. It is either a half-removed anchor or a \
                 directory something else owns; minting over it would destroy whichever it is",
                anchor_dir.display()
            ),
        });
    }
    Ok(None)
}

// ---------------------------------------------------------------------------
// The halves that run AS the desktop account
// ---------------------------------------------------------------------------

/// The application's launch-time verification, run as whoever calls it, with a report.
///
/// This is `verify_existing` — the function `provision_with_anchor` returns through on every
/// launch — and nothing else. The first line of the report names the uid it was measured AS,
/// read from the kernel by the same probe `prove_unwritable` uses, so the installer can refuse
/// a report that was not produced by the account it asked about ([`child_report_refusal`]).
pub fn verify_as_current_account(
    app_data_dir: &Path,
    machine_root: &Path,
) -> Result<String, ProvisionError> {
    let euid = anchor::posix_euid()?;
    let anchor_dir = anchor::anchor_dir(machine_root);
    let provisioned = crate::verify_existing(&app_data_dir.join(TRUST_DIR), &anchor_dir)?;
    let Some(proof) = provisioned.custody else {
        return custody(&anchor_dir, "the verification returned without a custody measurement");
    };
    Ok(format!(
        "{VERIFIED_MARKER} uid={euid}\ninstall {}\ntrust store {}\n{proof}\n",
        provisioned.install_id,
        provisioned.trust_dir.display()
    ))
}

/// Is `stdout` a verification report produced AS `uid`? `Some(why)` when it is not. Pure.
pub fn child_report_refusal(stdout: &str, uid: u32) -> Option<String> {
    let wanted = format!("{VERIFIED_MARKER} uid={uid}");
    match stdout.lines().next() {
        Some(first) if first == wanted => None,
        Some(first) => Some(format!(
            "the verification child reported {first:?}, not {wanted:?}: it did not run as the \
             desktop account, so its verdict is about somebody else"
        )),
        None => Some("the verification child reported nothing".to_string()),
    }
}

fn refuse_root_in_user_half(what: &str) -> Result<(), ProvisionError> {
    if anchor::posix_euid()? == 0 {
        return refuse(format!(
            "`{what}` is the half that runs AS THE DESKTOP ACCOUNT and this process is root. \
             Root must not write inside a directory the desktop account controls: between two \
             path lookups that account can swap the directory for one of its own choosing"
        ));
    }
    Ok(())
}

/// Copy the minted app-side store from the handoff directory into `<app_data>/trust`.
///
/// Runs as the desktop account. Copies exactly the files the mint writes — the list
/// `verify_store` requires the manifest to cover — rather than walking a tree, so nothing that
/// is not part of a provisioned store can ride along. Staged and renamed, like the
/// application's own first launch: `<app_data>/trust` only ever exists complete.
pub fn deliver_as_current_account(
    from: &Path,
    app_data_dir: &Path,
) -> Result<PathBuf, ProvisionError> {
    refuse_root_in_user_half("deliver")?;
    let trust = app_data_dir.join(TRUST_DIR);
    crate::refuse_occupied_trust_path(&trust)?;
    crate::io(
        crate::create_dir_all_mode(app_data_dir, Exposure::OwnerOnly.dir_mode()),
        "creating the application data directory",
        app_data_dir,
    )?;
    let staging = app_data_dir.join(format!(".trust-staging-{}", crate::random_hex(8)?));
    let copy = || -> Result<(), ProvisionError> {
        crate::io(
            crate::create_dir_all_mode(&staging, Exposure::OwnerOnly.dir_mode()),
            "creating the staging directory",
            &staging,
        )?;
        for relative in crate::provisioned_files() {
            let source = crate::under(from, &relative);
            let bytes = crate::io(std::fs::read(&source), "reading a minted file", &source)?;
            crate::write_bytes(&crate::under(&staging, &relative), &bytes, Exposure::OwnerOnly)?;
        }
        crate::refuse_occupied_trust_path(&trust)?;
        crate::io(
            std::fs::rename(&staging, &trust),
            "moving the delivered trust store into place",
            &trust,
        )
    };
    if let Err(e) = copy() {
        let _ = std::fs::remove_dir_all(&staging);
        return Err(e);
    }
    Ok(trust)
}

/// Remove `<app_data>/trust`. Runs as the desktop account, and only ever for a store the same
/// installer run delivered a moment earlier and then could not prove.
pub fn rollback_as_current_account(app_data_dir: &Path) -> Result<(), ProvisionError> {
    refuse_root_in_user_half("rollback")?;
    let trust = app_data_dir.join(TRUST_DIR);
    crate::io(std::fs::remove_dir_all(&trust), "removing a store that could not be proved", &trust)
}

// ---------------------------------------------------------------------------
// Root's half
// ---------------------------------------------------------------------------

/// Everything the installer needs to be told. Nothing here is read from the environment.
#[derive(Debug, Clone)]
pub struct InstallRequest {
    pub user: DesktopUser,
    /// The application data directory, spelled exactly as the application spells it.
    pub app_data_dir: PathBuf,
    /// [`anchor::POSIX_MACHINE_ROOT`] in production; a test passes its own.
    pub machine_root: PathBuf,
    /// The binary to re-run as the desktop account: `brops_install_anchor` itself. It must be
    /// somewhere that account can execute.
    pub helper: PathBuf,
}

/// The measurements a successful install rests on.
#[derive(Debug, Clone)]
pub struct DesktopProof {
    /// Root's static measurement: owner and mode of the anchor, its contents and every ancestor.
    pub floor: Vec<String>,
    /// The desktop-uid child's report: `verify_existing`'s custody proof, verbatim.
    pub report: String,
}

#[derive(Debug, Clone)]
pub struct Installed {
    pub anchor_dir: PathBuf,
    pub trust_dir: PathBuf,
    pub user: DesktopUser,
    /// True when THIS run minted; false when it found an anchor that already verifies.
    pub freshly_minted: bool,
    pub proof: DesktopProof,
}

/// Run the helper as the desktop account: its uid, its gid, no supplementary groups, an empty
/// environment, `/` as the working directory and no stdin.
///
/// The environment is cleared so nothing root's shell exported — `TMPDIR`, `HOME`,
/// `LD_PRELOAD` — reaches a process running as somebody else, and the working directory is
/// moved because root's own may be one the desktop account cannot enter.
pub fn run_as(
    helper: &Path,
    user: &DesktopUser,
    args: &[&OsStr],
) -> Result<Output, ProvisionError> {
    Command::new(helper)
        .args(args)
        .uid(user.uid)
        .gid(user.gid)
        .env_clear()
        .current_dir("/")
        .stdin(Stdio::null())
        .output()
        .map_err(|source| ProvisionError::Io {
            what: format!(
                "running the installer's helper as the desktop account (uid {}); it must be \
                 somewhere that account can execute",
                user.uid
            ),
            path: helper.to_path_buf(),
            source,
        })
}

fn child_failure(what: &str, user: &DesktopUser, out: &Output) -> String {
    format!(
        "{what}, run as {} (uid {}), refused ({}): {}",
        user.name,
        user.uid,
        out.status,
        String::from_utf8_lossy(&out.stderr).trim()
    )
}

/// **The proof.** The anchor verifies for the DESKTOP account, measured as that account.
///
/// Two measurements, and neither is root's opinion of what the desktop account can do:
///
/// 1. [`measure_floor`], which root takes because it is about ownership and mode bits rather
///    than about access — and which is what lets the second measurement stand for the real
///    desktop session despite the child having no supplementary groups;
/// 2. the application's own launch-time verification, executed by a child whose uid and gid
///    are the desktop account's, whose report must name that uid.
pub fn prove_for_desktop_user(
    request: &InstallRequest,
    owner: u32,
) -> Result<DesktopProof, ProvisionError> {
    let anchor_dir = anchor::anchor_dir(&request.machine_root);
    let floor = measure_floor(&anchor_dir, owner)?;
    let out = run_as(
        &request.helper,
        &request.user,
        &[
            OsStr::new("verify"),
            OsStr::new("--app-data"),
            request.app_data_dir.as_os_str(),
            OsStr::new("--machine-root"),
            request.machine_root.as_os_str(),
        ],
    )?;
    if !out.status.success() {
        return custody(
            &anchor_dir,
            child_failure("the application's launch-time verification", &request.user, &out),
        );
    }
    let report = String::from_utf8_lossy(&out.stdout).to_string();
    if let Some(why) = child_report_refusal(&report, request.user.uid) {
        return custody(&anchor_dir, why);
    }
    Ok(DesktopProof { floor, report })
}

/// What a failed run has to take back. Only ever things THIS run created.
#[derive(Default)]
struct Undo {
    handoff: Option<PathBuf>,
    anchor: Option<PathBuf>,
    /// Directories above the anchor that did not exist before, shallowest first.
    created: Vec<PathBuf>,
    delivered: bool,
}

impl Undo {
    fn run(&self, request: &InstallRequest) -> Vec<String> {
        let mut left = Vec::new();
        if let Some(handoff) = &self.handoff {
            if let Err(e) = std::fs::remove_dir_all(handoff) {
                if e.kind() != std::io::ErrorKind::NotFound {
                    left.push(format!("{} ({e})", handoff.display()));
                }
            }
        }
        if let Some(anchor) = &self.anchor {
            if let Err(e) = std::fs::remove_dir_all(anchor) {
                if e.kind() != std::io::ErrorKind::NotFound {
                    left.push(format!("{} ({e})", anchor.display()));
                }
            }
        }
        // `remove_dir`, not `remove_dir_all`: a directory this run created and something else
        // has since put a file in is no longer only this run's to remove.
        for dir in self.created.iter().rev() {
            let _ = std::fs::remove_dir(dir);
        }
        if self.delivered {
            let trust = request.app_data_dir.join(TRUST_DIR);
            match run_as(
                &request.helper,
                &request.user,
                &[OsStr::new("rollback"), OsStr::new("--app-data"), request.app_data_dir.as_os_str()],
            ) {
                Ok(out) if out.status.success() => {}
                Ok(out) => left.push(format!(
                    "{} ({})",
                    trust.display(),
                    String::from_utf8_lossy(&out.stderr).trim()
                )),
                Err(e) => left.push(format!("{} ({e})", trust.display())),
            }
        }
        left
    }
}

/// `lchown` a tree root has just created, children before their parent.
///
/// The order is the safety argument: the top directory is `0700` and root-owned until the
/// very last call, so the desktop account cannot enter the tree — let alone plant something in
/// it — while its contents are still changing hands. A symlink is refused rather than
/// followed; the mint writes none.
fn chown_tree(path: &Path, user: &DesktopUser, depth: usize) -> Result<(), ProvisionError> {
    if depth > MAX_DEPTH {
        return refuse(format!("{} is nested too deep to hand over", path.display()));
    }
    let meta = stat(path, false)?;
    if meta.file_type().is_symlink() {
        return refuse(format!("{} is a symlink; the mint writes none", path.display()));
    }
    if meta.file_type().is_dir() {
        let listing = crate::io(std::fs::read_dir(path), "listing the handoff directory", path)?;
        for entry in listing {
            let entry = crate::io(entry, "reading the handoff directory", path)?;
            chown_tree(&entry.path(), user, depth + 1)?;
        }
    }
    crate::io(
        std::os::unix::fs::lchown(path, Some(user.uid), Some(user.gid)),
        "handing a minted file to the desktop account",
        path,
    )
}

/// Every component of `dir` that does not exist yet, shallowest first.
fn missing_components(dir: &Path) -> Vec<PathBuf> {
    let mut missing = Vec::new();
    let mut cursor = Some(dir);
    while let Some(path) = cursor {
        if std::fs::symlink_metadata(path).is_ok() {
            break;
        }
        missing.push(path.to_path_buf());
        cursor = path.parent();
    }
    missing.reverse();
    missing
}

/// Install the trust anchor for `request.user`. Root only.
///
/// Returns `Ok` only when [`prove_for_desktop_user`] has passed — on a fresh mint and on an
/// anchor that was already there alike. On any failure after the first write, what this run
/// created under the machine root is removed again, and so is a store it delivered; the error
/// says so, and names anything that could not be.
///
/// `passwd` is the content of `/etc/passwd` ([`read_passwd`]) — the same text the caller
/// resolved the desktop account from, taken as an argument so the home-directory refusal can
/// be exercised without a real account's home being the thing at stake.
pub fn install_anchor(
    request: &InstallRequest,
    passwd: &str,
) -> Result<Installed, ProvisionError> {
    let euid = anchor::posix_euid()?;
    refuse_unless_root(euid)?;
    if request.user.uid == 0 {
        return refuse("the desktop account is uid 0; see `resolve_user`");
    }
    refuse_ambiguous_path("--app-data", &request.app_data_dir)?;
    refuse_ambiguous_path("--machine-root", &request.machine_root)?;

    let anchor_dir = anchor::anchor_dir(&request.machine_root);
    let trust = request.app_data_dir.join(TRUST_DIR);
    let installed = |freshly_minted: bool, proof: DesktopProof| Installed {
        anchor_dir: anchor_dir.clone(),
        trust_dir: trust.clone(),
        user: request.user.clone(),
        freshly_minted,
        proof,
    };

    refuse_home_collision(&request.machine_root, passwd)?;

    if let Some(proof) = settle_existing(&anchor_dir, || prove_for_desktop_user(request, euid))? {
        return Ok(installed(false, proof));
    }

    // Before anything is written: what is ALREADY above the anchor must be the installer's, and
    // the place the store is going must be empty.
    check_ancestors(&anchor_dir, euid, &mut Vec::new())?;
    crate::refuse_occupied_trust_path(&trust)?;

    let mut undo = Undo { created: missing_components(&anchor_dir), ..Undo::default() };
    // The anchor directory itself is removed as a tree; only what is above it is listed here.
    undo.created.pop();
    match mint_and_deliver(request, euid, &anchor_dir, &trust, &mut undo) {
        Ok(proof) => Ok(installed(true, proof)),
        Err(error) => {
            let left = undo.run(request);
            // Stated exactly: an application data DIRECTORY the delivery created is left, empty
            // and the desktop account's own. Removing a directory in that account's tree is
            // not something a failed install should be doing on its way out.
            let tail = if left.is_empty() {
                "Everything this run created under the machine root was removed again, and so \
                 was any trust store it delivered"
                    .to_string()
            } else {
                format!(
                    "This run could NOT remove everything it created; left behind: {}",
                    left.join("; ")
                )
            };
            refuse(format!(
                "installing the trust anchor at {} FAILED: {error} — {tail}",
                anchor_dir.display()
            ))
        }
    }
}

fn mint_and_deliver(
    request: &InstallRequest,
    euid: u32,
    anchor_dir: &Path,
    trust: &Path,
    undo: &mut Undo,
) -> Result<DesktopProof, ProvisionError> {
    let root = &request.machine_root;
    crate::io(
        crate::create_dir_all_mode(root, ANCHOR_DIR_MODE),
        "creating the machine root",
        root,
    )?;

    // The handoff directory: root-owned and world-traversable, so the desktop-uid child can
    // reach the one directory inside it that will be handed over — and nothing else can,
    // because that directory is 0700.
    let handoff = root.join(format!(".install-handoff-{}", crate::random_hex(8)?));
    undo.handoff = Some(handoff.clone());
    crate::io(
        crate::create_dir_all_mode(&handoff, ANCHOR_DIR_MODE),
        "creating the handoff directory",
        &handoff,
    )?;
    let staged = handoff.join(TRUST_DIR);

    // The mint. The same function the application's first launch calls on Windows: the same
    // key generation, the same registry, and the operator-root private half destroyed before
    // it returns. The audit signer's published key is admitted here if this machine has one,
    // for the reason `provision_with_anchor` gives — the registry is sealed the moment the
    // root is dropped, so there is no later.
    let signer = crate::published_anchor_custody(root)?;
    let minted = crate::mint(&staged, signer.as_ref())?;

    // The anchor, by root: hashed from the staging directory nobody else has been able to
    // enter, bound to the path the store is about to be delivered to.
    undo.anchor = Some(anchor_dir.to_path_buf());
    crate::write_anchor_files_for(anchor_dir, &staged, trust, &minted)?;

    // Hand over, deliver as the desktop account, and take the handoff away again.
    chown_tree(&staged, &request.user, 0)?;
    let out = run_as(
        &request.helper,
        &request.user,
        &[
            OsStr::new("deliver"),
            OsStr::new("--from"),
            staged.as_os_str(),
            OsStr::new("--app-data"),
            request.app_data_dir.as_os_str(),
        ],
    )?;
    if !out.status.success() {
        return refuse(child_failure("delivering the trust store", &request.user, &out));
    }
    undo.delivered = true;
    crate::io(std::fs::remove_dir_all(&handoff), "removing the handoff directory", &handoff)?;
    undo.handoff = None;

    // The final act.
    prove_for_desktop_user(request, euid)
}
