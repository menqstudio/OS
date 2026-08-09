//! **Where the trust anchor lives**: a location the policed account cannot write.
//!
//! # The property, stated exactly
//!
//! Three files decide whether a governance chain is genuine, and none of them is a key:
//!
//! * `operator-root.pub` — the out-of-registry pin `bro_signature.resolve_operator_root_pin`
//!   authenticates the trusted-key registry against;
//! * `registry-min` — the anti-rollback floor `bro_signature.resolve_registry_floor` reads;
//! * `PROVISIONING.json` — the manifest recording the sha256 of every other provisioned file,
//!   so a rewritten registry, key or artifact is detected.
//!
//! While those lived in `<app_data>/trust/`, destroying the operator-root PRIVATE half bought
//! nothing against the account that runs the app: it generates a root of its own, writes it
//! over the pin, re-signs the registry under it, raises the floor it also owns, patches the
//! manifest, and the real `bro_audit_log.verify()` accepts a truncated ledger. That attack was
//! not argued, it was run — `audit-signer/tests/anchor_end_to_end.py`, case `pin-rewrite`.
//!
//! So the whole of O-2 reduces to one property, and this module is where it is obtained:
//!
//! > **the account the app runs as cannot write the pin, the floor or the manifest.**
//!
//! # What the property is NOT
//!
//! It is not "a service account owns the file". A second principal is *one* way to reach it;
//! it is not the definition, and it is not what the engine's own rule asks. Both
//! `bro_custody.refuse_windows_writable` and `bro_custody.posix_rewrite_verdict` ask exactly
//! one question — *can the account reading this object rewrite it?* — and neither mentions
//! services. Believing the stronger, wrong definition is what stopped the previous round: it
//! concluded an unelevated session could not close O-2 because it could not create
//! `NT SERVICE\BroPSAuditSigner`. It did not need to.
//!
//! # The unelevated construction, and why it really is a boundary
//!
//! On Windows a file's owner implicitly holds `READ_CONTROL | WRITE_DAC`, which is why "make
//! it read-only" is theatre: the owner rewrites the DACL and then writes. The **OWNER RIGHTS**
//! SID (`S-1-3-4`) is the documented exception — an `ACCESS_ALLOWED` ACE for it *replaces* the
//! owner's implicit rights instead of adding to them. A `PROTECTED` DACL of
//!
//! ```text
//! SYSTEM                    FILE_ALL_ACCESS      (it can take ownership anyway)
//! BUILTIN\Administrators    FILE_ALL_ACCESS      (so can it)
//! OWNER RIGHTS (S-1-3-4)    FILE_GENERIC_READ | FILE_EXECUTE
//! ```
//!
//! therefore grants the creating account read and traverse and **nothing else**: no
//! `FILE_WRITE_DATA`, no `FILE_ADD_FILE`, no `DELETE`, no `WRITE_DAC`, no `WRITE_OWNER`. The
//! account locks itself out, permanently, with no elevation, no service and no second login
//! identity — and `AccessCheck`, the same evaluation the kernel performs on `CreateFile`,
//! reports no write right for it afterwards.
//!
//! This is the same shape `provision/tests/audit_signer.rs` already proved for a *file* whose
//! owner removed its own read access. Here it is a *directory*, and it holds the anchor.
//!
//! ## The ancestor, which is the part that is easy to miss
//!
//! Sealing the directory is necessary and not sufficient. An account that can open any
//! ANCESTOR of the anchor for `DELETE` can rename that ancestor aside and rebuild the whole
//! path with a pin of its own — the sealed directory still exists and nothing reads it any
//! more. This is not a hypothesis: the first construction attempted for this round sealed
//! `…\BroPS\trust-anchor` under a temporary directory, refused every direct write, and was
//! then renamed out of the way in one call because its GRANDparent granted
//! `FILE_DELETE_CHILD`.
//!
//! `bro_custody.posix_rewrite_verdict` asks this on POSIX (its `parent` verdict). The Windows
//! branch of `bro_custody.refuse_windows_writable` does **not** ask it at all — it evaluates
//! one security descriptor, and a security descriptor cannot see its parent. So the chain is
//! walked here, by the OS, one probe per component, up to the volume root.
//!
//! # Where it is, per platform
//!
//! * **Windows** — `%ProgramData%\BroPS\trust-anchor`. `C:\ProgramData` grants
//!   `BUILTIN\Users` `RX` and `WD,AD` (create entries) but neither `DELETE` nor
//!   `FILE_DELETE_CHILD`, so a standard user may create the product's directory there and can
//!   never afterwards delete or rename it once sealed. Measured, not assumed:
//!   [`prove_unwritable`] probes every component including `C:\ProgramData` and `C:\`.
//! * **POSIX** — [`POSIX_MACHINE_ROOT`]`/trust-anchor`, owned by a uid this process is not
//!   (root, or a dedicated `brops-anchor` account), mode `0755`, every ancestor likewise.
//!   **There is no unprivileged POSIX construction**: an owner may always `chmod` a directory
//!   it owns, so mode bits are not a boundary against the owner, and POSIX has no OWNER RIGHTS
//!   equivalent. So on POSIX the anchor must already exist when the application starts, and
//!   [`preprovision_refusal`] refuses — by name, before anything is minted — when it does
//!   not. [`seal`] refuses too, as the second line of the same argument.
//!
//! Nothing here has a permissive branch. A platform this module cannot seal, a location whose
//! custody cannot be measured, and a location that is measured and turns out writable are all
//! the same answer: refuse, name the path, name what must change.

use std::path::{Path, PathBuf};

use crate::ProvisionError;

/// The anchor directory's name under the machine root.
pub const ANCHOR_DIR_NAME: &str = "trust-anchor";

/// The out-of-registry operator-root pin. `BRO_OPERATOR_ROOT_PUBKEY_FILE`.
pub const OPERATOR_PIN_FILE: &str = "operator-root.pub";
/// The registry anti-rollback floor. `BRO_OPERATOR_REGISTRY_MIN_FILE`.
pub const REGISTRY_FLOOR_FILE: &str = "registry-min";
/// The provisioning manifest: the sha256 of every file in the app-side trust store.
pub const MANIFEST_FILE: &str = "PROVISIONING.json";
/// Written beside them, for whoever finds the directory without this source.
pub const CUSTODY_FILE: &str = "CUSTODY.txt";

/// The POSIX machine-wide root, and **why it is not `/var/lib/brops`**.
///
/// It used to be `/var/lib/brops`. On a real Debian box that is already the home directory of
/// the `brops` system account the deployment runbook creates, so following the instructions
/// chowned a service account's home to root. The anchor and a service account's home are two
/// different things that must never be the same directory: one is deliberately owned by a uid
/// the application is not and deliberately never removed, and the other belongs to a daemon
/// whose package may recreate, chown or purge it.
///
/// # Why THIS one cannot collide
///
/// Two reasons, and the second is the one that actually holds:
///
/// 1. Lexically it is neither `/var/lib/brops` (the `brops` account's home, per the runbook)
///    nor `/var/lib/brops-anchor` (what `adduser --system brops-anchor` would give the
///    dedicated account [`CUSTODY_REMEDY`] names). Both of the collisions this product's own
///    instructions can produce are avoided by name.
/// 2. **The name is not the argument.** A runbook can point `--home` anywhere, so no string is
///    safe by construction. [`precheck_location`] therefore ASKS: on POSIX it reads
///    `/etc/passwd` and refuses a machine root that is, contains, or sits inside any account's
///    home directory — naming the account. A future collision is then a refusal that says
///    which account owns the path, not a silent `chown -R root:root` over somebody's home.
///
/// `/var/lib` is right for the parent regardless: the Filesystem Hierarchy Standard, section 5.8 makes it "variable state
/// information ... persists between invocations", which is exactly what a trust anchor is, and
/// it is root-owned `0755` on every distribution, so the ancestor chain [`prove_unwritable`]
/// walks is already out of an unprivileged account's reach without provisioning touching it.
pub const POSIX_MACHINE_ROOT: &str = "/var/lib/brops-trust-anchor";

/// `%ProgramData%\BroPS` / [`POSIX_MACHINE_ROOT`] — the machine-wide root the anchor sits under.
///
/// Returned rather than read from an environment variable on purpose. An anchor location a
/// process can re-point by setting a variable is an anchor that process chooses, which is the
/// property this module exists to remove. A caller may still pass a different root to
/// [`anchor_dir`] — an installer, or a test — but nothing the *app* inherits redirects it.
pub fn default_machine_root() -> Result<PathBuf, ProvisionError> {
    #[cfg(windows)]
    {
        match std::env::var_os("ProgramData") {
            Some(v) if !v.is_empty() => Ok(PathBuf::from(v).join("BroPS")),
            _ => Err(ProvisionError::Unsupported {
                platform: crate::platform_name().to_string(),
                what: "%ProgramData% is not set, so there is no machine-wide root to put the \
                       trust anchor under. The anchor may not live in the application data \
                       directory: an account that can write it can install a trust root of \
                       its own"
                    .to_string(),
            }),
        }
    }
    #[cfg(not(windows))]
    {
        Ok(PathBuf::from(POSIX_MACHINE_ROOT))
    }
}

/// `<machine_root>/trust-anchor`.
pub fn anchor_dir(machine_root: &Path) -> PathBuf {
    machine_root.join(ANCHOR_DIR_NAME)
}

/// Does `machine_root` collide with a POSIX account's home directory? `Some((user, home))`.
///
/// # Why this is asked at all
///
/// The anchor's machine root used to be `/var/lib/brops`, which on a real Debian box is
/// already the home directory of the `brops` system account the deployment runbook creates —
/// so following the instructions chowned a service account's home to root. That is not a
/// naming accident that a better string fixes for good: a runbook can pass `--home` anywhere,
/// so the only durable answer is to ASK before provisioning writes anything.
///
/// A collision in either direction is refused. The machine root INSIDE a home means the anchor
/// sits in a tree its account owns and can rename; a home inside the MACHINE ROOT means
/// sealing or re-permissioning the anchor's path would reach into an account's home.
///
/// # Pure on purpose
///
/// It takes the CONTENT of `/etc/passwd` rather than reading it, so the decision runs — and is
/// tested — on every platform, including the Windows box this file is usually edited on. The
/// POSIX caller in [`precheck_location`] is the only part that touches the filesystem.
///
/// Homes that are not a real place (`/`, `/nonexistent`, `/dev/null`, anything relative) are
/// skipped: `/` would otherwise collide with every possible root, and Debian gives
/// `--no-create-home` system accounts `/nonexistent` precisely to mean "there is none".
pub fn home_directory_collision(machine_root: &Path, passwd: &str) -> Option<(String, PathBuf)> {
    let root = trim_trailing_slash(machine_root);
    for line in passwd.lines() {
        let line = line.trim_end_matches(['\r', '\n']);
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let fields: Vec<&str> = line.split(':').collect();
        if fields.len() < 6 {
            continue;
        }
        let user = fields[0];
        let home_raw = fields[5];
        if !home_raw.starts_with('/')
            || home_raw == "/"
            || home_raw == "/nonexistent"
            || home_raw == "/dev/null"
        {
            continue;
        }
        let home = trim_trailing_slash(Path::new(home_raw));
        if root == home || root.starts_with(&home) || home.starts_with(&root) {
            return Some((user.to_string(), home));
        }
    }
    None
}

fn trim_trailing_slash(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    let trimmed = text.trim_end_matches('/');
    if trimmed.is_empty() {
        PathBuf::from("/")
    } else {
        PathBuf::from(trimmed)
    }
}

/// Whether provisioning can CREATE an anchor on this platform, or must find one already there.
///
/// `None` on Windows, where an unelevated first launch really can establish an anchor it
/// afterwards cannot reach: [`seal`] applies a PROTECTED DACL with an OWNER RIGHTS
/// (`S-1-3-4`) read+execute ACE, which replaces the owner's implicit `WRITE_DAC`, and
/// `%ProgramData%` holds the path in place from above.
///
/// `Some(refusal)` everywhere else, and this is the whole POSIX story in one place:
///
/// * a POSIX owner may always `chmod` a directory it owns, and there is no OWNER RIGHTS
///   equivalent, so **no sequence of syscalls lets a process build a directory it cannot
///   subsequently rewrite**;
/// * therefore any anchor this process creates is one it can rewrite, which is exactly the
///   pin-rewrite attack the whole module exists to close;
/// * therefore the POSIX anchor must be created by a DIFFERENT uid before the application
///   starts, and the application's part is only to find it and measure it.
///
/// # Why this is a refusal at the top and not an error from three frames down
///
/// It used to be neither. `provision_with_anchor` minted the whole store, wrote the anchor
/// files, and only then called [`seal`], which returned `Unsupported` off Windows — so on
/// Linux and macOS the desktop application did not fail to provision, it **failed to launch**,
/// with an error escaping from a function whose job was to seal something. The refusal below
/// is deliberate, arrives before anything is written, and names the directory, the owner and
/// the modes.
///
/// # It does not offer a fallback, and that is the point
///
/// An application that started by provisioning an anchor into a directory it can write would
/// look provisioned and not be, which is strictly worse than one that will not start: every
/// downstream signature would verify against material the application chose. So there is no
/// degraded mode here, on purpose.
///
/// Pure — it takes the platform name rather than asking `cfg!` — so the POSIX decision and its
/// exact wording are exercised by the test suite on every machine, which is what stopped this
/// from being noticed for a whole round.
pub fn preprovision_refusal(platform: &str, anchor_dir: &Path) -> Option<ProvisionError> {
    if platform == "windows" {
        return None;
    }
    Some(ProvisionError::Custody {
        path: anchor_dir.to_path_buf(),
        what: format!(
            "this application cannot CREATE a trust anchor on {platform}, and there is not one \
             here already. A POSIX owner may always chmod a directory it owns and POSIX has no \
             OWNER RIGHTS equivalent, so any anchor this process built would be one this \
             process could rewrite — which is the pin-rewrite attack this anchor exists to \
             close, wearing the costume of a provisioned machine. The anchor must therefore be \
             created by a DIFFERENT uid, before this application starts: {} owned by that uid \
             (root, or a dedicated brops-anchor account), mode 0755, every ancestor owned by it \
             too, holding {OPERATOR_PIN_FILE} / {REGISTRY_FLOOR_FILE} / {MANIFEST_FILE} at mode \
             0644. NOTE, plainly: no shipped tool creates it yet — the installer that mints an \
             anchor as another uid is not written, so this platform is NOT supported for a \
             first launch today, and this refusal is the honest form of that. An anchor already \
             in place IS used: provisioning verifies it and starts",
            anchor_dir.display(),
        ),
        remedy: CUSTODY_REMEDY.to_string(),
    })
}

/// The remedy every custody refusal ends with, so a reader is never told only what is wrong.
pub const CUSTODY_REMEDY: &str = "\
The operator-root pin, the registry anti-rollback floor and the provisioning manifest must \
live where the account running this application cannot write them; otherwise that account \
generates a trust root of its own, writes it over the pin, re-signs the registry under it and \
raises the floor it also owns, and the whole chain then verifies against material it chose. On \
Windows the location is %ProgramData%\\BroPS\\trust-anchor, sealed with a PROTECTED DACL whose \
OWNER RIGHTS (S-1-3-4) ACE grants read and execute only — that needs no elevation and no second \
account, but every ancestor must also be one this account cannot open for DELETE. On POSIX the \
location must be owned by a uid this process is not (root, or a dedicated brops-anchor \
account), mode 0755, with every ancestor likewise; an owner can always chmod a directory it \
owns, so POSIX has no unprivileged construction and the deployment must create the directory \
and run provisioning once as that account. There is no fallback: a deployment that cannot \
provide the location has no trust anchor, and provisioning refuses rather than pretend \
otherwise.";

// ---------------------------------------------------------------------------
// The proof
// ---------------------------------------------------------------------------

/// What was measured, so a caller states the probes it ran rather than that it was happy.
///
/// Every string in here is an OS answer — the error a real syscall returned — not a summary of
/// an intention. [`crate::Provisioned`] carries one so a deployment can log what its anchor's
/// custody actually is, and `CUSTODY.txt` beside the anchor prints it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CustodyProof {
    pub dir: PathBuf,
    pub platform: &'static str,
    /// The mechanism, in one line.
    pub mechanism: String,
    /// One entry per behavioural write/delete probe, with the OS error it was refused with.
    pub refusals: Vec<String>,
    /// One entry per path component from the anchor directory up to the volume root.
    pub chain: Vec<String>,
}

impl std::fmt::Display for CustodyProof {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{} — {}\n  refused writes ({}):\n    {}\n  ancestor chain ({}):\n    {}",
            self.dir.display(),
            self.mechanism,
            self.refusals.len(),
            self.refusals.join("\n    "),
            self.chain.len(),
            self.chain.join("\n    ")
        )
    }
}

fn writable<T>(path: &Path, what: impl Into<String>) -> Result<T, ProvisionError> {
    Err(ProvisionError::Custody {
        path: path.to_path_buf(),
        what: what.into(),
        remedy: CUSTODY_REMEDY.to_string(),
    })
}

/// Refuse a location that cannot become an anchor, **before** anything is written to it.
///
/// [`seal`] is one-way for the account that applies it: afterwards this account cannot delete
/// the directory, cannot delete what is inside it, and cannot rewrite its permissions. So
/// discovering only at [`prove_unwritable`] that the path can be renamed aside from above
/// would leave a sealed directory nothing running as this account can clear — the deployment
/// would be wedged by its own failed provisioning.
///
/// The question is cheap and decisive. [`seal`] will protect every component from
/// `machine_root` down; what it will not touch is anything above `machine_root`. So find the
/// deepest EXISTING ancestor that is outside the machine root, and require that this account
/// already cannot delete or rename it. On Windows that ancestor is `C:\ProgramData`, which
/// grants `BUILTIN\Users` `RX` and `WD,AD` — enough to create the product's directory, never
/// enough to remove one. Under a temporary directory or anywhere else in the user's own tree
/// it is not, and this refuses there.
pub fn precheck_location(anchor: &Path, machine_root: &Path) -> Result<(), ProvisionError> {
    if !anchor.starts_with(machine_root) {
        return writable(
            anchor,
            format!(
                "the trust anchor {} is not inside the machine root {}, so sealing the machine \
                 root would not protect it",
                anchor.display(),
                machine_root.display()
            ),
        );
    }
    // Before any probe: is this somebody's home directory? Refuse by NAME rather than let a
    // deployment chown a service account's home to root, which is what `/var/lib/brops` did on
    // the first real Debian box. An unreadable `/etc/passwd` is not treated as a refusal —
    // this guard exists to stop a collision, and the custody probes below are the security
    // boundary — but it is the reason the default root moved. See [`POSIX_MACHINE_ROOT`].
    #[cfg(not(windows))]
    {
        if let Ok(passwd) = std::fs::read_to_string("/etc/passwd") {
            if let Some((user, home)) = home_directory_collision(machine_root, &passwd) {
                return writable(
                    machine_root,
                    format!(
                        "the machine root {} collides with the home directory of the account \
                         {user:?} ({}). A trust anchor and an account's home are two different \
                         things: the anchor is owned by a uid the application is not and is \
                         never removed, and a home belongs to a daemon whose package may \
                         recreate, chown or purge it. Provisioning here would either put the \
                         anchor inside a tree that account can rename, or re-permission \
                         somebody's home. Point the machine root somewhere no account lives",
                        machine_root.display(),
                        home.display(),
                    ),
                );
            }
        }
    }
    let mut component: Option<&Path> = machine_root.parent();
    while let Some(path) = component {
        if !path.exists() {
            component = path.parent();
            continue;
        }
        // The deepest existing ancestor outside the machine root. `seal` stops at the machine
        // root by design, so this one has to already be out of reach on its own.
        return match can_delete(path)? {
            None => Ok(()),
            Some(why) => writable(
                path,
                format!(
                    "{} is an ancestor of the trust anchor that this account can delete or \
                     rename ({why}), and it is OUTSIDE the machine root {}, which is as far as \
                     provisioning will re-permission. Whatever is sealed below it can be \
                     renamed aside in one call and the whole path rebuilt with a pin of this \
                     account's choosing. The machine root must sit under a directory this \
                     account cannot remove — %ProgramData% on Windows, which grants a standard \
                     user the right to create entries and not the right to delete them; a \
                     temporary directory or anywhere in the user's own profile is not such a \
                     place",
                    path.display(),
                    machine_root.display()
                ),
            ),
        };
    }
    // No existing ancestor outside the machine root at all. That means the machine root is (or
    // is above) the volume root, which is not a place to seal.
    writable(
        machine_root,
        format!(
            "no existing directory above the machine root {} could be found to check, so there \
             is nothing that could hold the anchor's path in place",
            machine_root.display()
        ),
    )
}

/// Prove, by asking the operating system, that this account cannot write the anchor.
///
/// Every check is a real syscall against the real path. Nothing here reasons about a DACL or a
/// mode: a DACL walk has to be right about ACE ordering, generic mappings, deny entries,
/// inheritance and the owner's implicit rights, and rounds of this item have been lost to
/// exactly that kind of reasoning being subtly wrong. A `CreateFile` that comes back
/// `ERROR_ACCESS_DENIED` is the same code path an attacker would take.
///
/// Fail closed everywhere: a probe that cannot be performed, a probe that succeeds, an ancestor
/// that can be opened for `DELETE`, or a token holding a privilege that makes any descriptor
/// irrelevant all refuse.
pub fn prove_unwritable(dir: &Path) -> Result<CustodyProof, ProvisionError> {
    if !dir.is_dir() {
        return writable(
            dir,
            "the trust anchor directory does not exist, so there is nothing whose custody could \
             be proved. An absent anchor is not a denied one — that confusion would make the \
             least-provisioned machine produce the strongest-looking evidence",
        );
    }
    let mut refusals = Vec::new();

    // 1 and 2. The anchor directory and everything BELOW it, recursively: see [`probe_tree`].
    probe_tree(dir, &mut refusals, 0)?;

    // 3. The chain. The anchor directory itself and every ancestor up to the volume root: if
    //    any one of them can be opened for DELETE, it can be renamed aside and the whole path
    //    rebuilt with a pin of this account's choosing, and the seal on the leaf is decoration.
    let mut chain = Vec::new();
    let mut component: Option<&Path> = Some(dir);
    while let Some(path) = component {
        if let Some(why) = can_delete(path)? {
            return writable(
                path,
                format!(
                    "this account CAN delete or rename a component of the trust anchor's path \
                     ({why}). Sealing the anchor directory is not enough: the whole path can be \
                     renamed aside and rebuilt with a pin of this account's choosing, and the \
                     sealed directory is then simply not the one anything reads"
                ),
            );
        }
        chain.push(format!("{} -> cannot be deleted or renamed by this account", path.display()));
        component = path.parent();
    }

    // 4. The rights no descriptor can restrain, and the platform's own precondition.
    let mechanism = platform_precondition(dir)?;

    Ok(CustodyProof {
        dir: dir.to_path_buf(),
        platform: crate::platform_name(),
        mechanism,
        refusals,
        chain,
    })
}

/// The name of the file every write probe creates and immediately removes.
const PROBE_NAME: &str = ".brops-custody-probe";

/// How deep the anchor is allowed to be. The real one is two directories deep
/// (`registry/config/trusted-keys.json`); anything past this is refused rather than walked,
/// so a symlink loop or a hostile tree cannot turn a custody check into a filesystem crawl.
const MAX_ANCHOR_DEPTH: usize = 8;

/// Can this account write anything in `dir`, or anything anywhere below it?
///
/// # Why this recurses, and why the previous version could not have passed on POSIX
///
/// The anchor is not flat. `write_anchor_files` puts the operator-signed trusted-key registry
/// at `<anchor>/registry/config/trusted-keys.json`, because `bro_signature.resolve_registry_root`
/// needs a registry root the reading account cannot write. The previous version listed the
/// anchor directory ONCE, non-recursively, and asked of every entry the same question:
/// "can it be opened for writing?"
///
/// Asked of a DIRECTORY that question is not merely uninformative, it answers differently on
/// the two platforms and is wrong on both:
///
/// * **POSIX** — `open(dir, O_WRONLY)` fails `EISDIR` before the kernel consults permissions
///   at all. `EISDIR` is not `PermissionDenied`, so the old code fell into its
///   "custody cannot be measured" branch and refused. The `registry` subdirectory is always
///   there, so **`prove_unwritable` could never have returned `Ok` on POSIX** — with a
///   correctly sealed, root-owned anchor it would still have refused, naming `Is a directory
///   (os error 21)`. That is the defect the missing POSIX coverage hid.
/// * **Windows** — `CreateFileW(dir, GENERIC_WRITE)` without `FILE_FLAG_BACKUP_SEMANTICS`
///   returns `ERROR_ACCESS_DENIED` for EVERY directory, sealed or wide open. The old code read
///   that as a refusal and moved on, so the registry subdirectory passed the check without
///   being checked, and the files INSIDE it were never looked at at all.
///
/// The question that does mean something about a directory is the one asked of the anchor
/// itself: can this account create an entry in it? So that is what is asked, of every
/// directory in the tree, and "open for writing" is asked only of regular files.
///
/// A symlink is refused rather than followed. Nothing provisioning writes is one, the anchor
/// is by construction not writable by this account, and a link inside it would redirect a read
/// to a file whose custody this walk never measured.
fn probe_tree(
    dir: &Path,
    refusals: &mut Vec<String>,
    depth: usize,
) -> Result<(), ProvisionError> {
    if depth > MAX_ANCHOR_DEPTH {
        return writable(
            dir,
            format!(
                "the trust anchor is nested more than {MAX_ANCHOR_DEPTH} directories deep, so \
                 its custody cannot be measured within a bounded walk"
            ),
        );
    }

    // (a) Can this account add a file here? Adding one is all the attack needs: it does not
    //     have to modify `operator-root.pub` in place, it only has to end up with a file of
    //     that name saying what it chose. On a subdirectory the same is true of the registry.
    let probe = dir.join(PROBE_NAME);
    match std::fs::File::create(&probe) {
        Ok(file) => {
            drop(file);
            let _ = std::fs::remove_file(&probe);
            return writable(
                dir,
                "this account CAN create files in the trust anchor directory, so it can write \
                 an operator-root pin of its own choosing",
            );
        }
        Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
            refusals.push(format!("create {} -> {e}", probe.display()));
        }
        Err(e) => {
            return writable(
                dir,
                format!(
                    "the trust anchor directory's custody cannot be measured: creating a probe \
                     file failed with something other than a permission denial ({e}), so this \
                     check cannot say whether the account can write it"
                ),
            )
        }
    }

    // (b) Every entry: a regular file is opened for write, a directory is descended into, and
    //     BOTH are asked whether they can be deleted. The delete question is not redundant —
    //     DELETE on an entry is granted by FILE_DELETE_CHILD on its DIRECTORY, which the
    //     entry's own descriptor does not mention, and on POSIX by write permission on the
    //     directory, which the entry's own mode does not mention either.
    for path in entries(dir)? {
        let kind = match std::fs::symlink_metadata(&path) {
            Ok(meta) => meta.file_type(),
            Err(e) => {
                return writable(
                    &path,
                    format!("a trust anchor entry's custody cannot be measured: {e}"),
                )
            }
        };
        if kind.is_symlink() {
            return writable(
                &path,
                "a trust anchor entry is a SYMLINK. Provisioning writes none, and a link here \
                 redirects a read to a file whose custody this walk has not measured — the \
                 target could be one this account owns",
            );
        }
        if kind.is_dir() {
            probe_tree(&path, refusals, depth + 1)?;
        } else {
            match std::fs::OpenOptions::new().write(true).open(&path) {
                Ok(_) => {
                    return writable(
                        &path,
                        "this account CAN open a file in the trust anchor directory for writing",
                    )
                }
                Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                    refusals.push(format!("open-for-write {} -> {e}", path.display()));
                }
                Err(e) => {
                    return writable(
                        &path,
                        format!("a trust anchor file's writability cannot be measured: {e}"),
                    )
                }
            }
        }
        if let Some(why) = can_delete(&path)? {
            return writable(
                &path,
                format!(
                    "this account CAN delete a trust anchor file ({why}), so it can remove the \
                     pin and put its own in its place"
                ),
            );
        }
        refusals.push(format!("open-for-delete {} -> refused", path.display()));
    }
    Ok(())
}

fn entries(dir: &Path) -> Result<Vec<PathBuf>, ProvisionError> {
    let listing = std::fs::read_dir(dir).map_err(|source| ProvisionError::Io {
        what: "listing the trust anchor directory".into(),
        path: dir.to_path_buf(),
        source,
    })?;
    let mut out = Vec::new();
    for entry in listing {
        let entry = entry.map_err(|source| ProvisionError::Io {
            what: "reading the trust anchor directory".into(),
            path: dir.to_path_buf(),
            source,
        })?;
        out.push(entry.path());
    }
    out.sort();
    Ok(out)
}

// ---------------------------------------------------------------------------
// Windows
// ---------------------------------------------------------------------------

/// `FILE_EXECUTE`, which on a directory is `FILE_TRAVERSE`. Not in [`crate::audit_signer`]'s
/// table because nothing there needed it: the signer's key is never traversed or executed.
#[cfg(windows)]
pub const FILE_EXECUTE: u32 = 0x0000_0020;

/// **OWNER RIGHTS** (`S-1-3-4`) — the whole mechanism in one constant.
///
/// An `ACCESS_ALLOWED` ACE for this SID *replaces* the owner's implicit
/// `READ_CONTROL | WRITE_DAC` rather than adding to it. Without it, "the owner" is a principal
/// no DACL can restrain and the seal below would be decoration.
#[cfg(windows)]
pub const SID_OWNER_RIGHTS: &str = "S-1-3-4";

/// What the owner keeps: read the pin, traverse the directory, read the descriptor. Nothing
/// that can change what any of them says.
#[cfg(windows)]
pub const OWNER_RIGHTS_MASK: u32 = crate::audit_signer::FILE_GENERIC_READ | FILE_EXECUTE;

/// The DACL [`seal`] applies.
///
/// SYSTEM and `BUILTIN\Administrators` keep full control because they can take ownership
/// regardless — an ACE denying them would be theatre, and the same reasoning
/// `audit_signer::key_dacl_plan` states. `OWNER RIGHTS` is the ACE that matters.
///
/// Only `aces` is read by `winimpl::apply_dacl`; `app_sid` and `signer_sid` are the plan's
/// provenance fields and are filled with the real values rather than placeholders so the
/// struct does not state something untrue about who it is a plan for.
#[cfg(windows)]
pub fn sealed_dacl_plan(app_sid: &str) -> crate::audit_signer::DaclPlan {
    use crate::audit_signer::{Ace, DaclPlan, FILE_ALL_ACCESS, SID_ADMINISTRATORS, SID_LOCAL_SYSTEM};
    DaclPlan {
        aces: vec![
            Ace { sid: SID_LOCAL_SYSTEM.to_string(), mask: FILE_ALL_ACCESS, inheritable: true },
            Ace { sid: SID_ADMINISTRATORS.to_string(), mask: FILE_ALL_ACCESS, inheritable: true },
            Ace {
                sid: SID_OWNER_RIGHTS.to_string(),
                mask: OWNER_RIGHTS_MASK,
                inheritable: true,
            },
        ],
        app_sid: app_sid.to_string(),
        signer_sid: crate::audit_signer::service_account_sid(
            crate::audit_signer::SIGNER_SERVICE_NAME,
        ),
        owner_sid: SID_ADMINISTRATORS.to_string(),
    }
}

#[cfg(windows)]
mod win {
    use std::ffi::c_void;
    use std::path::Path;

    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{CloseHandle, HANDLE, LUID};
    use windows::Win32::Security::{
        GetTokenInformation, LookupPrivilegeValueW, TokenPrivileges, TOKEN_PRIVILEGES, TOKEN_QUERY,
    };
    use windows::Win32::Storage::FileSystem::{
        CreateFileW, FILE_FLAG_BACKUP_SEMANTICS, FILE_SHARE_DELETE, FILE_SHARE_READ,
        FILE_SHARE_WRITE, OPEN_EXISTING,
    };
    use windows::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    /// The rights that make a security descriptor irrelevant to their holder: it takes
    /// ownership, or restores over the object, and then rewrites it at will. `AccessCheck`
    /// deliberately does not consider privileges, so they are asked for separately — this is
    /// `bro_custody.WINDOWS_OVERRIDE_PRIVILEGES`, in Rust, over this process's own token.
    /// PRESENCE disqualifies, not enabled state: a token may enable any privilege it holds
    /// without asking anyone.
    pub const OVERRIDE_PRIVILEGES: [&str; 2] = ["SeTakeOwnershipPrivilege", "SeRestorePrivilege"];

    const DELETE_RIGHT: u32 = 0x0001_0000;
    /// `HRESULT` for `ERROR_ACCESS_DENIED`.
    const E_ACCESS_DENIED: u32 = 0x8007_0005;

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Can this account open `path` with `DELETE`?
    ///
    /// One probe answers two questions, which is why it is the one used: the kernel grants
    /// `DELETE` on an object either from the object's own DACL **or** from `FILE_DELETE_CHILD`
    /// on its parent directory. A descriptor read of the object alone cannot see the second,
    /// and the second is the route that renames a sealed anchor aside.
    ///
    /// `FILE_FLAG_BACKUP_SEMANTICS` is required to open a directory at all. It is also the flag
    /// `SeRestorePrivilege` would use to bypass the DACL — correct here rather than a weakness:
    /// a token holding that privilege genuinely can rewrite the anchor, and this probe saying
    /// so is the honest answer (`prove_unwritable` refuses such a token by name anyway).
    ///
    /// Only `ERROR_ACCESS_DENIED` counts as "no". Anything else is unmeasurable and raises: a
    /// custody question that cannot be answered must never read as "denied".
    pub fn can_open_for_delete(path: &Path) -> Result<bool, String> {
        let name = wide(&path.to_string_lossy());
        unsafe {
            match CreateFileW(
                PCWSTR(name.as_ptr()),
                DELETE_RIGHT,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS,
                HANDLE::default(),
            ) {
                Ok(handle) => {
                    let _ = CloseHandle(handle);
                    Ok(true)
                }
                Err(e) if e.code().0 as u32 == E_ACCESS_DENIED => Ok(false),
                Err(e) => Err(format!("CreateFileW({}, DELETE): {e}", path.display())),
            }
        }
    }

    /// The first ownership-override privilege this process's token holds, or `None`.
    pub fn override_privilege() -> Result<Option<&'static str>, String> {
        unsafe {
            let mut wanted: Vec<(&'static str, LUID)> = Vec::new();
            for name in OVERRIDE_PRIVILEGES {
                let n = wide(name);
                let mut luid = LUID::default();
                LookupPrivilegeValueW(PCWSTR::null(), PCWSTR(n.as_ptr()), &mut luid)
                    .map_err(|e| format!("LookupPrivilegeValueW({name}): {e}"))?;
                wanted.push((name, luid));
            }
            let mut token = HANDLE::default();
            OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token)
                .map_err(|e| format!("OpenProcessToken: {e}"))?;
            let mut len = 0u32;
            let _ = GetTokenInformation(token, TokenPrivileges, None, 0, &mut len);
            let mut buf = vec![0u8; len.max(4) as usize];
            let res = GetTokenInformation(
                token,
                TokenPrivileges,
                Some(buf.as_mut_ptr() as *mut c_void),
                len,
                &mut len,
            );
            let _ = CloseHandle(token);
            res.map_err(|e| format!("GetTokenInformation(TokenPrivileges): {e}"))?;
            let privileges = &*(buf.as_ptr() as *const TOKEN_PRIVILEGES);
            let count = privileges.PrivilegeCount as usize;
            let first = privileges.Privileges.as_ptr();
            for index in 0..count {
                let entry = &*first.add(index);
                for (name, luid) in &wanted {
                    if entry.Luid.LowPart == luid.LowPart && entry.Luid.HighPart == luid.HighPart {
                        return Ok(Some(name));
                    }
                }
            }
            Ok(None)
        }
    }
}

/// Can this account delete (or rename) `path`? `Some(why)` when it can.
fn can_delete(path: &Path) -> Result<Option<String>, ProvisionError> {
    #[cfg(windows)]
    {
        match win::can_open_for_delete(path) {
            Ok(true) => Ok(Some(format!(
                "CreateFileW({}, DELETE) succeeded, which means either its own DACL grants \
                 DELETE or its parent directory grants FILE_DELETE_CHILD",
                path.display()
            ))),
            Ok(false) => Ok(None),
            Err(why) => writable(path, format!("the anchor's custody cannot be measured: {why}")),
        }
    }
    #[cfg(not(windows))]
    {
        // POSIX: unlinking an entry needs write+execute on the DIRECTORY that holds it, not any
        // right on the entry itself. So the question about `path` is a question about its
        // parent, and it is answered behaviourally — by trying to create an entry there, which
        // is the same permission unlinking requires.
        let parent = match path.parent() {
            Some(p) => p,
            None => return Ok(None), // the volume root has no parent to be deleted from
        };
        let probe = parent.join(".brops-custody-probe-parent");
        match std::fs::File::create(&probe) {
            Ok(file) => {
                drop(file);
                let _ = std::fs::remove_file(&probe);
                Ok(Some(format!(
                    "{} is writable by this account, and write permission on a POSIX directory \
                     is exactly the permission to unlink and replace the entries inside it",
                    parent.display()
                )))
            }
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => Ok(None),
            Err(e) => writable(
                parent,
                format!(
                    "the anchor's custody cannot be measured: creating a probe entry in {} \
                     failed with something other than a permission denial ({e})",
                    parent.display()
                ),
            ),
        }
    }
}

/// The per-platform precondition `prove_unwritable` finishes with, and the mechanism string.
fn platform_precondition(dir: &Path) -> Result<String, ProvisionError> {
    #[cfg(windows)]
    {
        match win::override_privilege() {
            Ok(None) => Ok(format!(
                "windows: PROTECTED DACL — SYSTEM and BUILTIN\\Administrators FILE_ALL_ACCESS, \
                 OWNER RIGHTS ({SID_OWNER_RIGHTS}) mask 0x{OWNER_RIGHTS_MASK:08x} \
                 (FILE_GENERIC_READ|FILE_EXECUTE) ONLY, which REPLACES the owner's implicit \
                 READ_CONTROL|WRITE_DAC; and this process's token holds neither \
                 SeTakeOwnershipPrivilege nor SeRestorePrivilege"
            )),
            Ok(Some(privilege)) => writable(
                dir,
                format!(
                    "this process's token holds {privilege}, which lets it take ownership of the \
                     anchor and rewrite its DACL, so no descriptor on it can keep this process \
                     out. An elevated administrator always holds it — the application must run \
                     unelevated, or the anchor must be held by a principal it cannot become"
                ),
            ),
            Err(why) => {
                writable(dir, format!("the anchor's custody cannot be measured: {why}"))
            }
        }
    }
    #[cfg(not(windows))]
    {
        use std::os::unix::fs::MetadataExt;
        let euid = posix_euid()?;
        // The behavioural probes above only report what the CURRENT mode allows. On POSIX an
        // owner may chmod at will, so ownership has to be asked separately or a 0555 directory
        // this account owns would pass every probe and still be one `chmod` from anything.
        let anchor_uid = std::fs::metadata(dir)
            .map_err(|source| ProvisionError::Io {
                what: "stat-ing the trust anchor directory".into(),
                path: dir.to_path_buf(),
                source,
            })?
            .uid();
        let mut ancestors: Vec<(PathBuf, u32)> = Vec::new();
        let mut component: Option<&Path> = dir.parent();
        while let Some(path) = component {
            let uid = std::fs::metadata(path)
                .map_err(|source| ProvisionError::Io {
                    what: "stat-ing an ancestor of the trust anchor directory".into(),
                    path: path.to_path_buf(),
                    source,
                })?
                .uid();
            ancestors.push((path.to_path_buf(), uid));
            component = path.parent();
        }
        posix_ownership(euid, anchor_uid, &ancestors).resolve(dir)
    }
}

/// What the POSIX ownership facts mean. Every variant except [`PosixOwnership::OutOfReach`]
/// is a refusal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PosixOwnership {
    /// Root rewrites any file regardless of owner or mode, so nothing is an anchor for it.
    RunningAsRoot,
    /// The reader owns the anchor, and an owner may always `chmod` back.
    AnchorOwnedByReader { euid: u32 },
    /// The reader owns something ABOVE the anchor, so it can `chmod` that and rename the
    /// anchor aside — the ancestor question a mode on the leaf cannot answer.
    AncestorOwnedByReader { euid: u32, ancestor: PathBuf },
    /// The anchor and every ancestor belong to a uid this process is not.
    OutOfReach { euid: u32 },
}

/// The POSIX custody decision, taken as a **pure function of the uids**.
///
/// # Why this is not inline in [`platform_precondition`] any more
///
/// Because inline it had never run. Reaching it needs an anchor whose whole ancestor chain is
/// unwritable by this account, and there is no unprivileged construction of that: under a
/// temporary directory the chain check refuses first, and as root every probe succeeds and the
/// chain check refuses first as well. So on POSIX this decision — including the wording of
/// three refusals — was reachable only on a correctly deployed production box, and the suite
/// went green on Linux without compiling half of it.
///
/// Split out, the DECISION runs on every machine in every run of the test suite, and only the
/// two `stat` calls that feed it need a real fixture. That is the same shape
/// `bro_custody.posix_rewrite_verdict` uses on the engine side.
///
/// `ancestors` is every component above the anchor, nearest first, paired with its owner uid.
pub fn posix_ownership(euid: u32, anchor_uid: u32, ancestors: &[(PathBuf, u32)]) -> PosixOwnership {
    if euid == 0 {
        return PosixOwnership::RunningAsRoot;
    }
    if anchor_uid == euid {
        return PosixOwnership::AnchorOwnedByReader { euid };
    }
    for (path, uid) in ancestors {
        if *uid == euid {
            return PosixOwnership::AncestorOwnedByReader { euid, ancestor: path.clone() };
        }
    }
    PosixOwnership::OutOfReach { euid }
}

impl PosixOwnership {
    /// The mechanism string when the anchor is out of reach, and the named refusal otherwise.
    pub fn resolve(self, dir: &Path) -> Result<String, ProvisionError> {
        match self {
            PosixOwnership::RunningAsRoot => writable(
                dir,
                "this process is running as root, which rewrites any file regardless of owner or \
                 mode, so no location on this machine is an anchor for it",
            ),
            PosixOwnership::AnchorOwnedByReader { euid } => writable(
                dir,
                format!(
                    "the trust anchor directory is owned by the very account reading it (uid \
                     {euid}). A POSIX owner may always chmod a directory it owns, so its mode \
                     bits are not a boundary against it"
                ),
            ),
            PosixOwnership::AncestorOwnedByReader { euid, ancestor } => writable(
                &ancestor,
                format!(
                    "an ancestor of the trust anchor is owned by the very account reading it \
                     (uid {euid}), which may chmod it and then rename the anchor aside"
                ),
            ),
            PosixOwnership::OutOfReach { euid } => Ok(format!(
                "posix: the anchor directory and every ancestor are owned by a uid this process \
                 is not (this process is uid {euid}), and every write and unlink probe above was \
                 refused by the kernel"
            )),
        }
    }
}

/// This process's effective uid, asked of the filesystem rather than of a C binding.
///
/// The crate has no `libc` dependency and gains nothing by growing one for a single number: a
/// file this process creates is owned by its effective uid, so creating one and reading its
/// owner back IS the answer, and it comes from the same kernel that decides the custody
/// question. A failure refuses rather than guesses.
///
/// # Three things the first version got wrong, all of them the same mistake
///
/// It was `File::create` on `<temp>/.brops-euid-<pid>` — a PREDICTABLE name in a
/// world-writable directory, opened `O_CREAT|O_TRUNC|O_WRONLY`, following symlinks:
///
/// 1. a squatter who guessed the pid could pre-create that path as a symlink and have this
///    function TRUNCATE any file the application can write;
/// 2. a squatter who pre-created it as a file THEY own would make `metadata().uid()` report
///    THEIR uid — and a wrong euid is not a cosmetic bug here: [`posix_ownership`] compares it
///    against the anchor's owner, so a spoofed value turns the "the reader owns the anchor"
///    refusal into a pass. The check that decides whether the anchor is genuine would then be
///    reading a number an attacker chose;
/// 3. the file was created at `0666 & ~umask`, which is the umask defect this round is about.
///
/// So: an unpredictable name, `create_new` (`O_EXCL`, which cannot follow a symlink and cannot
/// open a file somebody else made), mode `0600` stated at creation, and `fstat` on the open
/// HANDLE rather than a second look at the path. `AlreadyExists` is retried with a fresh name
/// and then refused — never worked around by using whatever was there.
#[cfg(not(windows))]
pub fn posix_euid() -> Result<u32, ProvisionError> {
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let dir = std::env::temp_dir();
    for _ in 0..8 {
        let probe = dir.join(format!(".brops-euid-{}", crate::random_hex(12)?));
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true).mode(0o600);
        match options.open(&probe) {
            Ok(file) => {
                // fstat on the handle this call opened: there is nothing in between for
                // anyone to swap, so the uid is this process's and no one else's.
                let uid = file.metadata().map(|m| m.uid()).map_err(|source| ProvisionError::Io {
                    what: "reading back the owner of this process's own probe file".into(),
                    path: probe.clone(),
                    source,
                });
                drop(file);
                let _ = std::fs::remove_file(&probe);
                return uid;
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(source) => {
                return Err(ProvisionError::Io {
                    what: "creating a probe file to learn this process's effective uid".into(),
                    path: probe,
                    source,
                })
            }
        }
    }
    Err(ProvisionError::Custody {
        path: dir,
        what: "this process's effective uid could not be measured: eight unpredictable probe \
               names in the temporary directory were all already taken, which is not something \
               that happens by chance. Refusing rather than trusting the owner of a file this \
               process did not create — that number decides whether the anchor is genuine"
            .to_string(),
        remedy: CUSTODY_REMEDY.to_string(),
    })
}

// ---------------------------------------------------------------------------
// The seal
// ---------------------------------------------------------------------------

/// Remove this account's own write access to the anchor, and to every ancestor that would
/// otherwise let it rename the anchor aside.
///
/// The order is load-bearing and was arrived at by watching it go wrong: children are sealed
/// **before** their parents. Applying a protected DACL to a directory propagates the change
/// into descendants whose own DACLs are not protected, so sealing the parent first strips the
/// `WRITE_DAC` this process needs in order to seal the children — and the second call then
/// fails with `ERROR_ACCESS_DENIED` on a file it created moments earlier.
///
/// The upward walk stops at the first ancestor this account already cannot delete or rename;
/// on Windows that is `C:\ProgramData`, which grants `BUILTIN\Users` `RX` and `WD,AD` but
/// neither `DELETE` nor `FILE_DELETE_CHILD`. It never seals a directory outside `machine_root`
/// — the anchor's protection may not be bought by re-permissioning a directory the rest of the
/// system relies on. If the walk leaves `machine_root` itself still deletable, that is a
/// refusal, not something to seal past.
///
/// **This is one-way for the account that applies it.** After it returns, this account cannot
/// undo it, cannot delete the directory and cannot delete what is inside it. That is the
/// property, not an oversight; removing the anchor afterwards needs an administrator.
pub fn seal(dir: &Path, machine_root: &Path) -> Result<String, ProvisionError> {
    #[cfg(windows)]
    {
        let app_sid = crate::audit_signer::winimpl::current_user_sid().map_err(|e| {
            ProvisionError::Custody {
                path: dir.to_path_buf(),
                what: format!("this process's own SID could not be read, so the seal cannot be \
                               recorded against a principal: {e}"),
                remedy: CUSTODY_REMEDY.to_string(),
            }
        })?;
        let plan = sealed_dacl_plan(&app_sid);
        let apply = |path: &Path| -> Result<(), ProvisionError> {
            // The owner is deliberately NOT stamped: assigning BUILTIN\Administrators needs
            // SeRestorePrivilege, which an unelevated token does not hold, and the OWNER RIGHTS
            // ACE is exactly what makes stamping it unnecessary — it restrains whoever the
            // owner happens to be.
            crate::audit_signer::winimpl::apply_dacl(path, &plan, None).map_err(|e| {
                ProvisionError::Custody {
                    path: path.to_path_buf(),
                    what: format!("the trust anchor path could not be sealed: {e}"),
                    remedy: CUSTODY_REMEDY.to_string(),
                }
            })
        };
        // 1. The files, before their directory.
        for path in entries(dir)? {
            apply(&path)?;
        }
        // 2. The directory, then every ancestor inside the machine root that this account can
        //    still delete or rename.
        let mut component: Option<&Path> = Some(dir);
        while let Some(path) = component {
            match can_delete(path)? {
                None => break, // already out of reach: stop, and never touch what is above it
                Some(_) => {
                    if !path.starts_with(machine_root) {
                        return writable(
                            path,
                            format!(
                                "{} can be deleted or renamed by this account, and it is not \
                                 inside the machine root {}. Sealing it would mean this \
                                 application re-permissioning a directory the rest of the system \
                                 relies on, which it must not do — so the trust anchor cannot be \
                                 established at this location",
                                path.display(),
                                machine_root.display()
                            ),
                        );
                    }
                    apply(path)?;
                }
            }
            component = path.parent();
        }
        Ok(
            "windows: PROTECTED DACL with an OWNER RIGHTS (S-1-3-4) read+execute ACE applied to \
             the anchor's files, the anchor directory, and every ancestor up to the machine root"
                .to_string(),
        )
    }
    #[cfg(not(windows))]
    {
        let _ = machine_root;
        // There is no POSIX construction by which an account removes its own write access to
        // something it owns: chmod is always available to the owner, and there is no OWNER
        // RIGHTS equivalent. Say so, name what the deployment must do, and refuse. Anything
        // else here would be the fallback that silently restores the behaviour this whole
        // change exists to remove.
        Err(ProvisionError::Unsupported {
            platform: crate::platform_name().to_string(),
            what: format!(
                "this account cannot seal {} against itself. On POSIX an owner may always chmod \
                 a directory it owns, and there is no OWNER RIGHTS equivalent, so the trust \
                 anchor must be created by a DIFFERENT uid — root, or a dedicated brops-anchor \
                 account — at {} (mode 0755), with every ancestor owned by that uid too, and \
                 provisioning must be run once as that account (the installer's job) before the \
                 application runs as its own unprivileged uid. {CUSTODY_REMEDY}",
                dir.display(),
                dir.display(),
            ),
        })
    }
}

/// What `CUSTODY.txt` says beside the anchor, for whoever finds it without this source.
///
/// Deliberately **not** a copy of a [`CustodyProof`]. The proof is a live measurement — every
/// launch re-runs [`prove_unwritable`] and refuses if it no longer holds — and a proof written
/// into a file would be a claim about the past that an administrator's `icacls` could falsify
/// without touching it. The file states the mechanism and where to look; the measurement is
/// on [`crate::Provisioned::custody`], taken fresh, every time.
pub fn custody_text() -> String {
    format!(
        "BroPS trust anchor\n\
         ==================\n\
         \n\
         WHAT IS IN HERE\n\
         {OPERATOR_PIN_FILE}  the operator-root public key the engine pins the trusted-key\n\
         \x20                 registry against (BRO_OPERATOR_ROOT_PUBKEY_FILE).\n\
         {REGISTRY_FLOOR_FILE}         the anti-rollback floor: the lowest registry_version the\n\
         \x20                 engine will accept (BRO_OPERATOR_REGISTRY_MIN_FILE).\n\
         {MANIFEST_FILE}     the sha256 of every file in the application's trust store.\n\
         \n\
         WHY IT IS HERE AND NOT IN THE APPLICATION'S OWN DIRECTORY\n\
         Because the account the application runs as must not be able to write these three\n\
         files. An account that can rewrite the pin needs no private key at all: it generates\n\
         an operator root of its own, writes it over the pin, re-signs the registry under it,\n\
         raises the floor it also owns, and every downstream check then passes against\n\
         material it chose. Destroying the operator-root private half removed a key. It did\n\
         not move the anchor. This directory is where the anchor moved to.\n\
         \n\
         HOW THAT IS OBTAINED HERE\n\
         On Windows: a PROTECTED DACL whose OWNER RIGHTS (S-1-3-4) entry grants read and\n\
         execute only. That entry REPLACES the owner's implicit READ_CONTROL|WRITE_DAC, so\n\
         the account that created this directory cannot rewrite its permissions and give\n\
         itself write access back. The same DACL is on every ancestor up to the machine root.\n\
         On POSIX: a uid the application is not, with every ancestor owned by that uid.\n\
         \n\
         PROVED, NOT ASSUMED, AND NOT PROVED HERE\n\
         There is deliberately no stored proof in this file. Every launch RE-MEASURES the\n\
         property -- it tries to create a file here, tries to open each file here for\n\
         writing, and tries to open this directory and every ancestor of it for DELETE -- and\n\
         refuses to start unless the operating system refuses all of them. A proof written\n\
         into a file would be a claim about the past that one `icacls` could falsify without\n\
         touching it.\n\
         \n\
         IF YOU DELETE THIS DIRECTORY\n\
         The application has no trust anchor and refuses to start. It cannot rebuild one: the\n\
         directory above this one is sealed too, so nothing running as the application's\n\
         account can recreate the path. Removing it needs an administrator, and afterwards the\n\
         whole trust store has to be re-minted from scratch.\n"
    )
}
