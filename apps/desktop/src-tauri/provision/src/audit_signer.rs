//! The **second principal**: a Windows account that signs the audit ledger's head and
//! cannot write the ledger it attests.
//!
//! # The defect this exists to close (O-2)
//!
//! `engine/runtime/bro_audit_log.py` hash-chains every audit record and keeps a `.head`
//! sidecar. That chain resists a reader; it does not resist the **writer**. Whoever can
//! append can also drop records, recompute the chain, rewrite the plaintext `.head`, and
//! an unkeyed `verify()` stays green. The authority against that forger is an Ed25519
//! anchor over `{ledger, count, last_hash, previous_anchor_sha256, …}` produced by
//! `BRO_AUDIT_ANCHOR_SIGNER` — a command that, in the engine's own words, "MUST run under
//! a principal that cannot write the ledger".
//!
//! On Debian that principal already exists: a `signer` user whose key file the engine's
//! account cannot read. On Windows the app runs entirely as the installing user. One
//! account, one hand — an anchor signed by the account that can rewrite what it attests
//! proves nothing, and shipping it would produce anchors that *look* valid. This module
//! builds the missing principal.
//!
//! # The chosen design, and why the obvious ones do not work
//!
//! **Chosen.** A Windows **service** running under a **virtual service account**
//! (`NT SERVICE\BroPSAuditSigner`), holding the anchor private key in a directory the
//! app's account is absent from, reached by the app through the existing named-pipe
//! transport. `BRO_AUDIT_ANCHOR_SIGNER` points at an unprivileged **relay shim** that
//! holds no key: it forwards one payload down the pipe and copies the reply to stdout.
//!
//! Why a *virtual* service account rather than a real local user
//! ([`SIGNER_SERVICE_NAME`], [`service_account_sid`]):
//!
//! * There is **no password anywhere**. A real local user needs one, and it has to be
//!   retrievable by whatever starts the process — an LSA secret readable by SYSTEM. That
//!   is one more secret with the same custody question, on a box whose whole problem is
//!   custody.
//! * The SID is **derived from the service name**, `S-1-5-80-` + SHA-1 of the uppercased
//!   UTF-16LE name. So the principal the DACLs name can be computed **offline, on any
//!   host, in a unit test** — and an installer can check that the name really resolves to
//!   that SID. If someone pre-creates a *real* account called `BroPSAuditSigner` to be
//!   handed the key, the resolved SID will not match the derived one and provisioning
//!   refuses ([`AnchorRefusal::SignerSidSubstituted`]).
//! * It cannot log on interactively, is not in the logon-screen user list, and is not
//!   subject to password expiry/complexity policy. A real local user needs
//!   `SeDenyInteractiveLogonRight` and a `SpecialAccounts` registry entry to get there.
//! * Cost of the choice, stated: a virtual account exists only while the service is
//!   registered. Delete the service and the ACEs naming its SID become unresolvable. That
//!   is the fail-closed direction — the app then cannot obtain a signature at all — but it
//!   does mean the key file is orphaned rather than portable.
//!
//! **Rejected — scheduled task.** Cheaper than a service (no SCM plumbing), but Task
//! Scheduler will not run a task as a *virtual* account: it demands a real principal or a
//! well-known service account, which drags back the password. It also has no supported way
//! to hold a long-lived pipe server with restart semantics, and its task definition under
//! `%SystemRoot%\System32\Tasks` is Administrators-writable, so an admin could repoint the
//! task at their own binary and inherit the signer's identity. A service's `ImagePath` in
//! `HKLM` has the same exposure — that is not a difference between the two, and neither
//! defends against an administrator (see [`Separation`]).
//!
//! **Rejected — `CreateProcessWithLogonW` / `runas` per signature.** The app would have to
//! hold the signer's credentials to launch it, so the app could sign for itself. This is
//! the option that looks like it works and destroys the only property being bought.
//!
//! **Rejected — point `BRO_AUDIT_ANCHOR_SIGNER` straight at a signer `.exe`.** The engine
//! reaches the signer with `subprocess.run(argv, …)`. A child process inherits the
//! **caller's** token, so an exe named there runs as the *app's* account and its key must
//! be readable by the app. Naming a different executable does not create a different
//! principal. This is precisely why a pre-existing server process plus a relay shim is
//! structurally necessary, and why the transport is the named pipe rather than an exec.
//!
//! **Rejected — TPM / CNG non-exportable key, no second account.** Non-exportability stops
//! the key being copied; it does not stop the app *using* it to sign an arbitrary head.
//! Orthogonal to "cannot sign for itself". Worth combining with this design later (the
//! service can keep its key in its own CNG store); not a substitute for it.
//!
//! # Elevation — what the installer needs versus what the app needs
//!
//! * **Installer: Administrator, once.** `CreateServiceW` requires
//!   `SC_MANAGER_CREATE_SERVICE` on the SCM, which the SCM refuses to a standard user by
//!   design. Creating `%ProgramData%\BroPS\audit-signer` with a protected DACL owned by
//!   `BUILTIN\Administrators` also requires it (`CreateFileW` returns
//!   `ERROR_INVALID_OWNER` otherwise — `provision_custody::create_locked_file` says the
//!   same). **There is no unelevated path.** Any scheme that avoids the UAC prompt also
//!   avoids the second principal. The Owner is entitled to know that this feature costs
//!   one elevation prompt at install and cannot be made to cost zero.
//! * **Running app: nothing.** It opens a client handle to the pipe and reads a public-key
//!   file. It never elevates, and it must never be able to read the private key — that is
//!   the property [`verify_key_custody`] and [`ReadbackProof`] exist to prove.
//! * **Signer service: nothing beyond its own account.** `SERVICE_SID_TYPE_UNRESTRICTED`,
//!   start=auto, no privileges, not a member of Administrators.
//!
//! # How strong the separation actually is
//!
//! `BUILTIN\Administrators` holds full control of the key file, deliberately — withholding
//! the ACE would be theatre, since an administrator can take ownership of any local object
//! regardless of what the DACL says. `provision_custody::custody_file_dacl` grants it for
//! exactly that reason and this module keeps the rule.
//!
//! The consequence has to be said out loud rather than buried: **if the app's account is a
//! local administrator, the separation resists code running as that account without
//! elevation, and does not resist the account's human.** [`Separation`] measures which of
//! those two deployments is in front of us and labels the anchor accordingly. It is never
//! collapsed into a single "separated" claim.
//!
//! # What is reused, and where the existing machinery is wrong for this
//!
//! This module deliberately does not re-implement the Windows kit. Where it does not call
//! into `brops-win-live`, here is why:
//!
//! * **`tcb_floor::WindowsFsProbe` cannot measure these files.** Its `stat` computes a
//!   content digest with `std::fs::read`, so it returns `None` for any file the caller is
//!   denied — which is *every* file this module needs to prove the app cannot read. A probe
//!   that fails exactly on the interesting case cannot be the proof. [`winimpl::dacl_facts`]
//!   asks `GetNamedSecurityInfoW` for the owner, control word and DACL and never opens the
//!   contents.
//! * **`provision_custody::custody_file_dacl` cannot express the ledger's DACL.** By
//!   construction it refuses to grant any non-TCB principal write authority — correct for a
//!   session-0 signing seed, wrong for a per-user ledger the app must append to on every
//!   turn. [`ledger_dacl_plan`] therefore plans that DACL here, and proves the *inverse*
//!   property with the same arithmetic: the signer holds no bit of [`WRITE_ACCESS_BITS`].
//! * **`provision_custody::create_locked_file` is file-only and non-inheritable.** The
//!   ledger is a *directory* whose children (`.jsonl`, `.head`, `.anchor`, the lock) are
//!   created by the engine and must inherit, which needs `AddAccessAllowedAceEx` with
//!   `CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE`. That constructor has no such flag.
//! * The **mask constants** below are the same numbers as `pipe_acl`'s. They are restated
//!   because this crate builds on Linux, where `brops-win-live` is not a dependency, and the
//!   *decisions* must be unit-testable there. They cannot drift silently:
//!   `tests/audit_signer.rs::win_live_constants_have_not_drifted` pins every one of them
//!   against the real `brops_win_live::pipe_acl` on Windows.
//! * The **transport** is `brops-win-broker`'s peer-SID-authenticated named pipe, not a new
//!   one. See [`PIPE_SPEC`].
//!
//! # Shape of this module
//!
//! Same as `pipe_acl` / `provision_custody` / `tcb_floor`, for the same reason: every
//! *decision* — which principals, which mask, whether a read-back proves what it must, what
//! the signer may sign — is a pure function over plain data, unit-tested on any host. Only
//! the syscalls are `#[cfg(windows)]`. The syscalls need Administrator to exercise, and
//! checks that only run under elevation are exactly the ones that rot, so the tests that
//! cannot run **skip with the reason printed**, never pass by default.
//!
//! # Fail closed
//!
//! Every function here returns a refusal rather than a degraded success. There is no path
//! that produces [`AnchorEnv`] without a completed [`ReadbackProof`]. An install that
//! quietly proceeded without the second principal would emit anchors that verify and prove
//! nothing, which is strictly worse than an honestly unanchored ledger — which the engine
//! already reports as its own distinct refusal (`AuditAnchorMissing`).

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use ed25519_dalek::SigningKey;
use serde_json::{json, Map, Value};

use crate::canonical::canonical_bytes;
use crate::{hex, sha256_hex, ProvisionError};

// =================================================================================================
// Names, and the environment the engine reads
// =================================================================================================

/// The Windows service name, which is also the virtual account name after `NT SERVICE\`,
/// which is also what [`service_account_sid`] hashes. One string, so the three can never
/// disagree.
pub const SIGNER_SERVICE_NAME: &str = "BroPSAuditSigner";

/// Named-pipe leaf the signer service listens on. The full path is
/// `\\.\pipe\<SIGNER_PIPE_NAME>`; `brops_win_broker::pipe_path_wide` builds it.
pub const SIGNER_PIPE_NAME: &str = "brops-audit-anchor";

/// `bro_audit_log.SIGNER_ENV`.
pub const SIGNER_ENV: &str = "BRO_AUDIT_ANCHOR_SIGNER";
/// `bro_audit_log.SIGNER_KEY_ID_ENV`.
pub const SIGNER_KEY_ID_ENV: &str = "BRO_AUDIT_ANCHOR_KEY_ID";

/// `bro_audit_log.ANCHOR_ARTIFACT_TYPE`.
pub const ANCHOR_ARTIFACT_TYPE: &str = "audit-head";

/// `bro_audit_log.ANCHOR_PAYLOAD_FIELDS`, as an exact set. The engine checks this too; the
/// signer checks it as well so a malformed payload is refused by the party that owns the
/// key, not only by the party that assembled it.
pub const ANCHOR_PAYLOAD_FIELDS: [&str; 7] = [
    "artifact_type",
    "count",
    "issued_at_epoch",
    "key_id",
    "last_hash",
    "ledger",
    "previous_anchor_sha256",
];

/// `bro_audit_log.ANCHOR_AUTHORITIES` — the registry authorities whose keys may anchor.
///
/// A mirror of a hardcoded Python tuple, so it can drift; it does not drift silently.
/// `audit-signer/tests/anchor_end_to_end.py` is handed this array and fails unless the real
/// `bro_audit_log.ANCHOR_AUTHORITIES` is exactly equal to it.
pub const ANCHOR_AUTHORITIES: [&str; 1] = ["audit-anchor"];

/// The authority the anchor key is minted under: a dedicated type, not `evidence-recorder`
/// and not `operator-root`.
///
/// It used to be `evidence-recorder`, on the reasoning that the operator root is the pin the
/// whole registry hangs from and therefore must not double as the anchor. That reasoning was
/// right and did not go far enough: [`crate::provision`] mints a private half for EVERY
/// authority in [`crate::AUTHORITY_TYPES`] into the app's own trust directory, and
/// `evidence-recorder` is one of them — so the ledger's own writer held a key the engine
/// accepted for an audit head, and could truncate the chain and re-anchor it. `audit-anchor`
/// is deliberately absent from [`crate::AUTHORITY_TYPES`]: nothing in this crate mints it, the
/// signer service mints its own seed under its own account, and only the public half is ever
/// published (`register::register_anchor_key`).
///
/// It binds no artifact type in [`crate::ARTIFACT_AUTHORITY`] either, so its registry entry
/// carries an EMPTY `allowed_artifact_types` and cannot be widened by rewriting the registry:
/// `audit-head` is out-of-registry and the binding is the authority type itself.
pub const ANCHOR_AUTHORITY: &str = "audit-anchor";

/// The request/reply contract on the pipe, restated in one place so the shim, the service
/// and the tests cannot each invent their own.
///
/// One connection, one anchor. The client writes the audit-head payload as **one
/// length-prefixed frame** (4-byte big-endian length, `brops_core::ipc_framing`) and then reads
/// one frame back carrying either `{"payload": ..., "signature": ...}` or
/// `{"ok": false, "reason": ...}`. The server then disconnects.
///
/// **Corrected.** This constant used to say "write the payload, then half-close". That is not
/// available on a byte-mode named pipe: there is no `shutdown(SHUT_WR)` equivalent, and
/// `CloseHandle` closes the read direction along with the write direction, so a client that
/// half-closed to signal end-of-request could never receive the reply. The length prefix is
/// what delimits the request, and it is not a new invention - it is the framing
/// `brops_win_live::pipe::run_server` and its `hop_once` client already speak, which is why
/// this design reuses that transport rather than adding a third one.
///
/// The *engine's* contract is unchanged and still stdin-to-stdout: the shim reads the canonical
/// payload from stdin (which `subprocess.run` closes) and writes the document to stdout. The
/// framing exists only on the pipe hop between the shim and the service and adds no semantics
/// the engine cannot see - one payload in, one document out, either way.
pub const PIPE_SPEC: &str = "one connection = one anchor. client -> ONE length-prefixed frame (4-byte big-endian) carrying the audit-head payload JSON; server -> one frame carrying {payload,signature} or {ok:false,reason}, then disconnect. A byte-mode named pipe has NO half-close. Peer SID is authenticated by brops_win_broker::authenticate_pipe_client_sid and must equal the provisioned app SID.";

// =================================================================================================
// Access masks — the same numbers as `brops_win_live::pipe_acl`, pinned by a drift test
// =================================================================================================

pub const FILE_READ_DATA: u32 = 0x0000_0001;
pub const FILE_WRITE_DATA: u32 = 0x0000_0002;
/// `FILE_APPEND_DATA` on a file, `FILE_CREATE_PIPE_INSTANCE` on a pipe. Append is the bit a
/// ledger forger needs least and a ledger *writer* needs most, so it is a write bit here.
pub const FILE_APPEND_DATA: u32 = 0x0000_0004;
pub const FILE_READ_EA: u32 = 0x0000_0008;
pub const FILE_WRITE_EA: u32 = 0x0000_0010;
pub const FILE_READ_ATTRIBUTES: u32 = 0x0000_0080;
pub const FILE_WRITE_ATTRIBUTES: u32 = 0x0000_0100;
pub const DELETE: u32 = 0x0001_0000;
pub const READ_CONTROL: u32 = 0x0002_0000;
pub const WRITE_DAC: u32 = 0x0004_0000;
pub const WRITE_OWNER: u32 = 0x0008_0000;
pub const SYNCHRONIZE: u32 = 0x0010_0000;
pub const FILE_ALL_ACCESS: u32 = 0x001F_01FF;

/// `FILE_GENERIC_READ`, built bit by bit — never the `GENERIC_READ` alias.
///
/// The generic bits are resolved by the kernel at open time, so an ACE carrying
/// `GENERIC_WRITE` (`0x4000_0000`) is **opaque to a DACL read-back**: it contains
/// `FILE_APPEND_DATA` but a mask comparison against [`WRITE_ACCESS_BITS`] will not see it.
/// `provision_custody` documents this trap for its readers; it applies to everything here,
/// which is why [`unmapped_generic_grantees`] refuses any read-back containing a generic bit
/// instead of computing over it.
pub const FILE_GENERIC_READ: u32 =
    READ_CONTROL | FILE_READ_DATA | FILE_READ_ATTRIBUTES | FILE_READ_EA | SYNCHRONIZE;

/// `FILE_GENERIC_WRITE`, spelled out. What the **app** needs on the ledger directory: it
/// creates and appends the `.jsonl`, replaces the `.head`, and takes the `.lock`.
pub const FILE_GENERIC_WRITE: u32 = READ_CONTROL
    | FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_EA
    | FILE_WRITE_ATTRIBUTES
    | SYNCHRONIZE;

/// Every bit that lets a holder change the object or its ACL. Identical to
/// `pipe_acl::WRITE_ACCESS_BITS` and pinned to it by a drift test.
pub const WRITE_ACCESS_BITS: u32 = FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_ATTRIBUTES
    | DELETE
    | WRITE_DAC
    | WRITE_OWNER;

/// Any bit that lets a holder *see* the bytes. Used for the key file, where the question is
/// not "can the app write" but "can the app read at all".
pub const READ_ACCESS_BITS: u32 = FILE_READ_DATA | FILE_READ_EA;

/// The four `GENERIC_*` bits. Present in a read-back ⇒ the mask cannot be reasoned about.
pub const GENERIC_BITS: u32 = 0x8000_0000 | 0x4000_0000 | 0x2000_0000 | 0x1000_0000;

pub const SID_LOCAL_SYSTEM: &str = "S-1-5-18";
pub const SID_ADMINISTRATORS: &str = "S-1-5-32-544";

/// SIDs that stand for "essentially everyone on this box". None may appear in either DACL:
/// granting `BUILTIN\Users` read on the anchor key hands it to the app by group membership,
/// which is the whole point restated.
pub const WORLD_SIDS: &[&str] = &[
    "S-1-1-0",      // Everyone
    "S-1-5-7",      // ANONYMOUS LOGON
    "S-1-5-11",     // Authenticated Users
    "S-1-5-4",      // INTERACTIVE
    "S-1-5-2",      // NETWORK
    "S-1-5-32-545", // BUILTIN\Users
    "S-1-5-32-546", // BUILTIN\Guests
    "S-1-2-0",      // LOCAL
    "S-1-2-1",      // CONSOLE LOGON
    "S-1-5-32-547", // BUILTIN\Power Users
    "S-1-5-113",    // Local account
    "S-1-5-114",    // Local account and member of Administrators group
];

/// Principals that can take ownership of any local object anyway, so an ACE for them is a
/// statement of fact rather than a grant. Same set as `tcb_floor::TCB_OWNER_SIDS`.
pub const TCB_SIDS: &[&str] = &[SID_LOCAL_SYSTEM, SID_ADMINISTRATORS];

// =================================================================================================
// SHA-1, only for deriving a service SID
// =================================================================================================

/// SHA-1 of `data`.
///
/// Here for one reason: a Windows service SID is `S-1-5-80-` followed by the five 32-bit
/// little-endian words of `SHA1(UPPERCASE(service name) as UTF-16LE)`, and that is the
/// algorithm the OS uses whether or not it is a good hash. It is **never** used for
/// integrity in this crate — every digest that means anything is SHA-256 via
/// [`crate::sha256_hex`]. Pinned against the real OS value for `NT SERVICE\TrustedInstaller`
/// in the tests, and cross-checked against `LookupAccountNameW` at install time.
pub fn sha1(data: &[u8]) -> [u8; 20] {
    let mut h: [u32; 5] = [0x6745_2301, 0xEFCD_AB89, 0x98BA_DCFE, 0x1032_5476, 0xC3D2_E1F0];
    let bit_len = (data.len() as u64).wrapping_mul(8);
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in msg.chunks_exact(64) {
        let mut w = [0u32; 80];
        for (i, word) in chunk.chunks_exact(4).enumerate() {
            w[i] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let (mut a, mut b, mut c, mut d, mut e) = (h[0], h[1], h[2], h[3], h[4]);
        for (i, wi) in w.iter().enumerate() {
            let (f, k) = match i {
                0..=19 => ((b & c) | ((!b) & d), 0x5A82_7999u32),
                20..=39 => (b ^ c ^ d, 0x6ED9_EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1B_BCDC),
                _ => (b ^ c ^ d, 0xCA62_C1D6),
            };
            let tmp = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(*wi);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = tmp;
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
    }
    let mut out = [0u8; 20];
    for (i, word) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}

/// The SID Windows gives the service named `service_name`, computed **offline**.
///
/// This is what makes the whole design testable on a host that has no SCM: the principal the
/// DACLs name is a pure function of a string. At install time the derived value is compared
/// with what `LookupAccountNameW("NT SERVICE\\<name>")` returns, and a mismatch is
/// [`AnchorRefusal::SignerSidSubstituted`] — the case where somebody pre-created a real
/// account under that name hoping to be handed the key.
pub fn service_account_sid(service_name: &str) -> String {
    let upper: String = service_name.to_uppercase();
    let utf16le: Vec<u8> = upper.encode_utf16().flat_map(|u| u.to_le_bytes()).collect();
    let digest = sha1(&utf16le);
    let mut parts = String::from("S-1-5-80");
    for word in digest.chunks_exact(4) {
        let v = u32::from_le_bytes([word[0], word[1], word[2], word[3]]);
        parts.push('-');
        parts.push_str(&v.to_string());
    }
    parts
}

/// `true` if `sid` is a service SID (`S-1-5-80-…`). The signer principal must be one: a
/// service SID cannot be a member of `BUILTIN\Administrators` unless somebody deliberately
/// added it, and it cannot log on interactively at all.
pub fn is_service_sid(sid: &str) -> bool {
    sid.starts_with("S-1-5-80-")
}

/// Cheap syntactic SID check — same rule as `provision_custody::looks_like_sid`. The real
/// arbiter is `ConvertStringSidToSidW` on the Windows side; this exists so the pure plan can
/// refuse obviously-wrong input on any host, including in a Linux unit test.
pub fn looks_like_sid(s: &str) -> bool {
    s.starts_with("S-1-")
        && s.len() > 4
        && s.split('-').skip(1).all(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()))
}

// =================================================================================================
// Where things live
// =================================================================================================

/// Every path the design names, derived from the two roots the caller supplies.
///
/// The split is the design: the **key** lives under a machine-wide root the app's account is
/// absent from, and the **ledger** lives under the app's own data directory, which the signer
/// is absent from. Two roots, opposite exclusions.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SignerPaths {
    /// `%ProgramData%\BroPS\audit-signer`. Created by the elevated installer.
    pub signer_dir: PathBuf,
    /// The Ed25519 seed. Readable only by the signer principal and the TCB.
    pub key_file: PathBuf,
    /// Public half + key id + the signer SID that must be running to use the key. Readable by
    /// everyone who needs to verify; writable only by the signer and the TCB.
    pub custody_file: PathBuf,
    /// The signer's own anti-rollback record: highest count and last anchor digest it signed,
    /// per ledger. Must be unreadable/unwritable by the app, or rollback protection is a
    /// suggestion.
    pub state_file: PathBuf,
    /// The relay shim `BRO_AUDIT_ANCHOR_SIGNER` points at. Not inside `engine/` — the engine
    /// refuses a signer path under its own root.
    pub shim_path: PathBuf,
    /// The service executable.
    pub service_exe: PathBuf,
    /// `%LOCALAPPDATA%\<app>\audit`. The engine's ledger, its `.head`, `.anchor` and `.lock`
    /// all live here and inherit its DACL.
    pub ledger_dir: PathBuf,
    /// The ledger itself.
    pub ledger_file: PathBuf,
}

pub const SIGNER_DIR_NAME: &str = "audit-signer";
pub const KEY_FILE_NAME: &str = "anchor.key";
pub const CUSTODY_FILE_NAME: &str = "custody.json";
pub const STATE_FILE_NAME: &str = "anchor-state.json";
pub const SHIM_EXE_NAME: &str = "brops-anchor-relay.exe";
pub const SERVICE_EXE_NAME: &str = "brops-audit-signer.exe";
pub const LEDGER_DIR_NAME: &str = "audit";
pub const LEDGER_FILE_NAME: &str = "bro-audit.jsonl";

impl SignerPaths {
    /// `machine_root` is `%ProgramData%\BroPS` (or its POSIX equivalent); `app_data_dir` is
    /// the per-user directory `provision()` already owns; `install_dir` is where the two
    /// binaries were laid down.
    pub fn new(machine_root: &Path, app_data_dir: &Path, install_dir: &Path) -> SignerPaths {
        let signer_dir = machine_root.join(SIGNER_DIR_NAME);
        let ledger_dir = app_data_dir.join(LEDGER_DIR_NAME);
        SignerPaths {
            key_file: signer_dir.join(KEY_FILE_NAME),
            custody_file: signer_dir.join(CUSTODY_FILE_NAME),
            state_file: signer_dir.join(STATE_FILE_NAME),
            signer_dir,
            shim_path: install_dir.join(SHIM_EXE_NAME),
            service_exe: install_dir.join(SERVICE_EXE_NAME),
            ledger_file: ledger_dir.join(LEDGER_FILE_NAME),
            ledger_dir,
        }
    }
}

// =================================================================================================
// The planned DACLs
// =================================================================================================

/// One ACCESS_ALLOWED ACE of a planned DACL.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ace {
    pub sid: String,
    pub mask: u32,
    /// `CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE`. Only meaningful on a directory; the
    /// ledger's children are created by the *engine*, so they can only be protected by
    /// inheritance.
    pub inheritable: bool,
}

/// A planned DACL plus the two SIDs the plan is *about*, so a verifier never has to be told
/// separately who it is checking.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DaclPlan {
    pub aces: Vec<Ace>,
    /// The account the app runs as.
    pub app_sid: String,
    /// The account the signer service runs as.
    pub signer_sid: String,
    /// Owner to stamp on the object. Always `BUILTIN\Administrators`: a file's owner
    /// implicitly holds `READ_CONTROL | WRITE_DAC`, so any DACL is only as strong as its
    /// owner, and leaving the creating account as owner would let it re-grant itself.
    pub owner_sid: String,
}

/// The DACL for the signer's private key, its custody record and its anti-rollback state.
///
/// SYSTEM and `BUILTIN\Administrators` get full control — they can take ownership regardless,
/// so the ACE is a statement of fact and its absence would be theatre (this is
/// `provision_custody::custody_file_dacl`'s reasoning and it is kept). The **signer** gets
/// read+write, because it mints its own key on first start and rewrites its own rollback
/// state. The **app is absent**, and absence from a protected DACL is denial.
///
/// Fail-closed. Every rejection is a case where continuing would produce a file weaker than
/// the inherited DACL it replaced.
pub fn key_dacl_plan(app_sid: &str, signer_sid: &str) -> Result<DaclPlan, AnchorRefusal> {
    let plan = DaclPlan {
        aces: vec![
            Ace { sid: SID_LOCAL_SYSTEM.to_string(), mask: FILE_ALL_ACCESS, inheritable: true },
            Ace { sid: SID_ADMINISTRATORS.to_string(), mask: FILE_ALL_ACCESS, inheritable: true },
            Ace {
                sid: signer_sid.to_string(),
                mask: FILE_GENERIC_READ | FILE_GENERIC_WRITE | DELETE,
                inheritable: true,
            },
        ],
        app_sid: app_sid.to_string(),
        signer_sid: signer_sid.to_string(),
        owner_sid: SID_ADMINISTRATORS.to_string(),
    };
    check_principals(&plan)?;
    // Post-condition over the ACEs actually built, not over the inputs. Whatever a future
    // edit does to the masks or the list, a key DACL that grants the app anything never
    // leaves this function.
    let facts = plan_as_facts(&plan, SID_ADMINISTRATORS, true);
    verify_key_custody(&plan, &facts)?;
    Ok(plan)
}

/// The DACL for the ledger directory (and, by inheritance, for the `.jsonl`, `.head`,
/// `.anchor` and `.lock` the engine creates inside it).
///
/// The app gets read+write: it appends a record on every governed turn, and a ledger it
/// cannot write is not a ledger. The **signer is absent**, which is the property the anchor's
/// whole meaning rests on — a signer that could write the ledger could write a chain to match
/// any head it fancied signing.
///
/// `provision_custody::custody_file_dacl` cannot express this: it refuses by construction to
/// grant a non-TCB principal write authority. Correct for a session-0 signing seed, wrong
/// here, so the plan is built in this module and proved with the same arithmetic inverted.
pub fn ledger_dacl_plan(app_sid: &str, signer_sid: &str) -> Result<DaclPlan, AnchorRefusal> {
    let plan = DaclPlan {
        aces: vec![
            Ace { sid: SID_LOCAL_SYSTEM.to_string(), mask: FILE_ALL_ACCESS, inheritable: true },
            Ace { sid: SID_ADMINISTRATORS.to_string(), mask: FILE_ALL_ACCESS, inheritable: true },
            Ace {
                sid: app_sid.to_string(),
                mask: FILE_GENERIC_READ | FILE_GENERIC_WRITE | DELETE,
                inheritable: true,
            },
        ],
        app_sid: app_sid.to_string(),
        signer_sid: signer_sid.to_string(),
        owner_sid: SID_ADMINISTRATORS.to_string(),
    };
    check_principals(&plan)?;
    // Post-condition against BOTH owners the rule permits, so neither branch can rot.
    for owner in [SID_ADMINISTRATORS, app_sid] {
        let facts = plan_as_facts(&plan, owner, true);
        verify_ledger_custody(&plan, &facts)?;
    }
    Ok(plan)
}

/// Rules that hold for both plans, checked before either is emitted.
fn check_principals(plan: &DaclPlan) -> Result<(), AnchorRefusal> {
    for (what, sid) in [("app", &plan.app_sid), ("signer", &plan.signer_sid)] {
        if !looks_like_sid(sid) {
            return Err(AnchorRefusal::NotASid { what: what.to_string(), value: sid.clone() });
        }
        if WORLD_SIDS.contains(&sid.as_str()) {
            return Err(AnchorRefusal::WorldPrincipal { what: what.to_string(), sid: sid.clone() });
        }
    }
    if plan.app_sid == plan.signer_sid {
        return Err(AnchorRefusal::SamePrincipal { sid: plan.app_sid.clone() });
    }
    if !is_service_sid(&plan.signer_sid) {
        return Err(AnchorRefusal::SignerNotAServiceAccount { sid: plan.signer_sid.clone() });
    }
    if TCB_SIDS.contains(&plan.signer_sid.as_str()) {
        return Err(AnchorRefusal::SignerNotAServiceAccount { sid: plan.signer_sid.clone() });
    }
    Ok(())
}

// =================================================================================================
// Read-back facts, and the proofs computed over them
// =================================================================================================

/// What a DACL read-back reports about one path. Deliberately the same shape as
/// `tcb_floor::WinFileFacts` minus the content digest — the digest is what makes that type
/// unusable here, because computing it requires read access to a file we are proving we do
/// not have read access to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DaclFacts {
    pub path: String,
    pub owner_sid: String,
    /// `false` ⇒ **NULL DACL**, which Windows reads as everyone-full-control. Never "no access".
    pub dacl_present: bool,
    /// `SE_DACL_PROTECTED` was set, so no inheritable ACE from a parent was merged in and the
    /// listed ACEs really are the whole story.
    pub dacl_protected: bool,
    /// ACCESS_ALLOWED ACEs only.
    ///
    /// ACCESS_DENIED ACEs are deliberately not modelled, exactly as `tcb_floor` does it and
    /// for the same reason: ignoring a deny ACE can only make a principal look *more*
    /// privileged than it is, so both questions asked here ("can the app read the key",
    /// "can the signer write the ledger") stay fail-closed under the omission.
    pub allow_aces: Vec<Ace>,
}

/// Render a plan as the facts a perfect read-back would produce. Used for the post-conditions
/// above, so the pure plan is checked by the *same* predicate that later checks the real disk.
pub fn plan_as_facts(plan: &DaclPlan, owner_sid: &str, protected: bool) -> DaclFacts {
    DaclFacts {
        path: "<planned>".to_string(),
        owner_sid: owner_sid.to_string(),
        dacl_present: true,
        dacl_protected: protected,
        allow_aces: plan.aces.clone(),
    }
}

/// Trustees whose ACE carries a `GENERIC_*` bit.
///
/// A read-back containing one cannot be reasoned about: the kernel maps generics at open
/// time, so `GENERIC_WRITE` silently contains `FILE_APPEND_DATA` and a mask comparison
/// against [`WRITE_ACCESS_BITS`] misses it. Non-empty ⇒ refuse rather than compute.
pub fn unmapped_generic_grantees(facts: &DaclFacts) -> Vec<String> {
    let mut v: Vec<String> = facts
        .allow_aces
        .iter()
        .filter(|a| a.mask & GENERIC_BITS != 0)
        .map(|a| a.sid.clone())
        .collect();
    v.sort();
    v.dedup();
    v
}

/// World SIDs holding any access at all in this DACL.
pub fn world_grantees(facts: &DaclFacts) -> Vec<String> {
    let mut v: Vec<String> = facts
        .allow_aces
        .iter()
        .filter(|a| WORLD_SIDS.contains(&a.sid.as_str()) && a.mask != 0)
        .map(|a| a.sid.clone())
        .collect();
    v.sort();
    v.dedup();
    v
}

/// The total mask a single SID is granted by its own ACEs (group membership is **not**
/// resolved here — that is what [`Separation`] is for).
pub fn direct_mask(facts: &DaclFacts, sid: &str) -> u32 {
    facts.allow_aces.iter().filter(|a| a.sid == sid).fold(0, |acc, a| acc | a.mask)
}

/// The evidence that one DACL really has the property claimed of it, produced by *reading the
/// descriptor back and computing*, never by remembering what was asked for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReadbackProof {
    pub path: String,
    /// The SID the property is about (the app, for the key; the signer, for the ledger).
    pub excluded_sid: String,
    /// The bits that had to be absent.
    pub forbidden_mask: u32,
    /// The bits actually found for `excluded_sid` — recorded so the proof states the number
    /// it computed, not merely that it was happy.
    pub observed_mask: u32,
    /// The bits that had to be present for the object to be usable at all (0 when none).
    pub required_mask: u32,
    pub required_sid: String,
    pub observed_required_mask: u32,
    pub owner_sid: String,
    pub dacl_protected: bool,
}

impl ReadbackProof {
    /// One line an auditor can re-derive by hand from `icacls`.
    pub fn summary(&self) -> String {
        format!(
            "{}: owner={} protected={} | {} observed={:#010x} & forbidden={:#010x} = {:#010x} \
             (must be 0) | {} observed={:#010x} & required={:#010x} = {:#010x} (must equal required)",
            self.path,
            self.owner_sid,
            self.dacl_protected,
            self.excluded_sid,
            self.observed_mask,
            self.forbidden_mask,
            self.observed_mask & self.forbidden_mask,
            self.required_sid,
            self.observed_required_mask,
            self.required_mask,
            self.observed_required_mask & self.required_mask,
        )
    }
}

/// Prove, from a read-back, that the **app cannot read the signer's key**.
///
/// The computation, in order: the DACL exists (a NULL DACL is everyone-full-control, not
/// "no access"); it is protected, so nothing inherited in behind our back; no `GENERIC_*`
/// bit makes the masks unreadable; no world SID hands the app access by group membership;
/// the owner is a TCB principal, because an owner can rewrite the DACL at will; the app's own
/// ACE grants **zero** bits; and the signer really can read and write, or the design is
/// broken in the other direction and the service will fail at first start.
pub fn verify_key_custody(
    plan: &DaclPlan,
    facts: &DaclFacts,
) -> Result<ReadbackProof, AnchorRefusal> {
    common_dacl_checks(facts)?;
    check_owner(facts, TCB_SIDS)?;
    let app_mask = direct_mask(facts, &plan.app_sid);
    // Nothing at all, not merely no read: WRITE_DAC alone would let the app grant itself read.
    if app_mask != 0 {
        return Err(AnchorRefusal::KeyReachableByApp {
            path: facts.path.clone(),
            app_sid: plan.app_sid.clone(),
            observed_mask: app_mask,
        });
    }
    let signer_mask = direct_mask(facts, &plan.signer_sid);
    let need = FILE_READ_DATA | FILE_WRITE_DATA;
    if signer_mask & need != need {
        return Err(AnchorRefusal::SignerCannotUseItsOwnKey {
            path: facts.path.clone(),
            signer_sid: plan.signer_sid.clone(),
            observed_mask: signer_mask,
        });
    }
    Ok(ReadbackProof {
        path: facts.path.clone(),
        excluded_sid: plan.app_sid.clone(),
        forbidden_mask: READ_ACCESS_BITS | WRITE_ACCESS_BITS | READ_CONTROL,
        observed_mask: app_mask,
        required_mask: need,
        required_sid: plan.signer_sid.clone(),
        observed_required_mask: signer_mask,
        owner_sid: facts.owner_sid.clone(),
        dacl_protected: facts.dacl_protected,
    })
}

/// Prove, from a read-back, that the **signer cannot write the audit ledger**.
///
/// Same order, inverted: the signer's ACE must carry no bit of [`WRITE_ACCESS_BITS`], and the
/// app's must carry write, or the engine cannot append and the ledger is useless.
pub fn verify_ledger_custody(
    plan: &DaclPlan,
    facts: &DaclFacts,
) -> Result<ReadbackProof, AnchorRefusal> {
    common_dacl_checks(facts)?;
    let mut allowed: Vec<&str> = TCB_SIDS.to_vec();
    allowed.push(plan.app_sid.as_str());
    check_owner(facts, &allowed)?;
    let signer_mask = direct_mask(facts, &plan.signer_sid);
    if signer_mask & WRITE_ACCESS_BITS != 0 {
        return Err(AnchorRefusal::LedgerWritableBySigner {
            path: facts.path.clone(),
            signer_sid: plan.signer_sid.clone(),
            observed_mask: signer_mask,
        });
    }
    let app_mask = direct_mask(facts, &plan.app_sid);
    let need = FILE_WRITE_DATA | FILE_APPEND_DATA;
    if app_mask & need != need {
        return Err(AnchorRefusal::LedgerNotWritableByApp {
            path: facts.path.clone(),
            app_sid: plan.app_sid.clone(),
            observed_mask: app_mask,
        });
    }
    Ok(ReadbackProof {
        path: facts.path.clone(),
        excluded_sid: plan.signer_sid.clone(),
        forbidden_mask: WRITE_ACCESS_BITS,
        observed_mask: signer_mask,
        required_mask: need,
        required_sid: plan.app_sid.clone(),
        observed_required_mask: app_mask,
        owner_sid: facts.owner_sid.clone(),
        dacl_protected: facts.dacl_protected,
    })
}

fn common_dacl_checks(facts: &DaclFacts) -> Result<(), AnchorRefusal> {
    if !facts.dacl_present {
        return Err(AnchorRefusal::NullDacl { path: facts.path.clone() });
    }
    if !facts.dacl_protected {
        return Err(AnchorRefusal::DaclNotProtected { path: facts.path.clone() });
    }
    let generics = unmapped_generic_grantees(facts);
    if !generics.is_empty() {
        return Err(AnchorRefusal::UnmappedGenericRights {
            path: facts.path.clone(),
            grantees: generics,
        });
    }
    let world = world_grantees(facts);
    if !world.is_empty() {
        return Err(AnchorRefusal::WorldInDacl { path: facts.path.clone(), grantees: world });
    }
    Ok(())
}

/// Who may own each object - and they are **not** the same rule, because the two DACLs defend
/// against opposite principals.
///
/// An owner implicitly holds `READ_CONTROL | WRITE_DAC`, so a DACL is only ever as strong as
/// its owner. Therefore:
///
/// * The **key** defends against the app, so the app must not own it. Only SYSTEM or
///   `BUILTIN\\Administrators` may - which is why stamping that owner needs the ELEVATED
///   installer, and why a key file owned by the app's account is a hard refusal rather than a
///   warning.
/// * The **ledger** defends against the *signer*, and it is per-user application data the app
///   creates. Requiring a TCB owner there would be impossible without elevation on every
///   launch and pointless besides: the app rewriting its own ledger's DACL cannot buy the app
///   anything it does not already hold. What must never own it is the **signer**, which is the
///   principal that DACL is about. Written down rather than assumed, so nobody later
///   "tightens" this into a rule that cannot hold.
fn check_owner(facts: &DaclFacts, allowed: &[&str]) -> Result<(), AnchorRefusal> {
    if !allowed.contains(&facts.owner_sid.as_str()) {
        return Err(AnchorRefusal::UntrustedOwner {
            path: facts.path.clone(),
            owner_sid: facts.owner_sid.clone(),
        });
    }
    Ok(())
}

// =================================================================================================
// How strong the separation actually is on THIS box
// =================================================================================================

/// The app's token, as far as the question "can this account reach the signer's key by some
/// route other than the DACL" is concerned.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppTokenPosture {
    /// `BUILTIN\Administrators` is absent from the token entirely.
    StandardUser,
    /// Present but marked `SE_GROUP_USE_FOR_DENY_ONLY` — a filtered admin token. The *process*
    /// is denied; the *human* can elevate at any time without a credential.
    FilteredAdministrator,
    /// Present and enabled: the process is already running elevated.
    ElevatedAdministrator,
}

/// What the anchor may honestly be said to prove.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Separation {
    /// The app's account is not an administrator in any form. The signer's key is
    /// unreachable from the app's account without a credential the app does not have. This is
    /// the shape the O-2 requirement actually asks for.
    Separated,
    /// The app's account is a local administrator. The anchor resists any code running as that
    /// account **without elevation** — which is most of what "the ledger's writer forged its
    /// own anchor" means in practice, since the engine runs unelevated — and does **not**
    /// resist the account's human, who can elevate and take ownership of the key. Reported,
    /// never silently upgraded to [`Separation::Separated`].
    SeparatedUntilElevation { posture: AppTokenPosture },
}

impl Separation {
    pub fn from_posture(posture: AppTokenPosture) -> Separation {
        match posture {
            AppTokenPosture::StandardUser => Separation::Separated,
            other => Separation::SeparatedUntilElevation { posture: other },
        }
    }

    /// The exact sentence that may be written next to an anchor. Nothing downstream may
    /// paraphrase it upwards.
    pub fn claim(&self) -> &'static str {
        match self {
            Separation::Separated => {
                "the audit-head anchor is signed by NT SERVICE\\BroPSAuditSigner, a principal \
                 that cannot write the ledger, and whose key this app's account cannot read \
                 (its account holds no administrative membership)"
            }
            Separation::SeparatedUntilElevation { .. } => {
                "the audit-head anchor is signed by NT SERVICE\\BroPSAuditSigner, a principal \
                 that cannot write the ledger. This app's account IS a local administrator, so \
                 the separation holds against unelevated code running as that account and does \
                 NOT hold against that account's human, who can take ownership of the signer's \
                 key by elevating. The anchor is not evidence against the machine's owner."
            }
        }
    }
}

// =================================================================================================
// Refusals
// =================================================================================================

/// Why the second principal is not usable. Any value ⇒ no [`AnchorEnv`], no anchoring, and the
/// engine keeps reporting the ledger as honestly `AuditAnchorMissing`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AnchorRefusal {
    NotASid { what: String, value: String },
    WorldPrincipal { what: String, sid: String },
    SamePrincipal { sid: String },
    SignerNotAServiceAccount { sid: String },
    /// `LookupAccountNameW("NT SERVICE\\<name>")` did not return the SID derived from the
    /// service name — somebody put a different principal behind that name.
    SignerSidSubstituted { name: String, derived: String, resolved: String },
    NullDacl { path: String },
    DaclNotProtected { path: String },
    UnmappedGenericRights { path: String, grantees: Vec<String> },
    WorldInDacl { path: String, grantees: Vec<String> },
    UntrustedOwner { path: String, owner_sid: String },
    KeyReachableByApp { path: String, app_sid: String, observed_mask: u32 },
    SignerCannotUseItsOwnKey { path: String, signer_sid: String, observed_mask: u32 },
    LedgerWritableBySigner { path: String, signer_sid: String, observed_mask: u32 },
    LedgerNotWritableByApp { path: String, app_sid: String, observed_mask: u32 },
    /// The app opened the key file and read bytes. Whatever the DACL says, the property is
    /// false. This is the check that survives every DACL-parsing subtlety.
    KeyActuallyReadable { path: String },
    /// The security descriptor could not be read back at all, so nothing was proved.
    Unmeasurable { path: String, why: String },
    /// The service is not registered / not running / the pipe is absent.
    SignerAbsent { why: String },
    /// Off Windows, or the platform refused to answer.
    Unsupported { platform: String, what: String },
    /// The installer is not elevated, so it cannot create the service or the protected root.
    ElevationRequired { step: String },
}

impl std::fmt::Display for AnchorRefusal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.explain())
    }
}

impl std::error::Error for AnchorRefusal {}

impl AnchorRefusal {
    /// What failed, what it means, and what to do — in that order, because an installer that
    /// prints only the first leaves the operator guessing whether to care.
    pub fn explain(&self) -> String {
        let head = "brops audit-anchor: REFUSING to enable audit-head anchoring";
        let body = match self {
            AnchorRefusal::NotASid { what, value } => format!(
                "the {what} principal {value:?} is not a SID. An account name that failed to \
                 resolve would silently become NO ace, i.e. a DACL that says nothing"
            ),
            AnchorRefusal::WorldPrincipal { what, sid } => format!(
                "the {what} principal is the world SID {sid}. Naming it is indistinguishable \
                 from leaving the inherited DACL in place"
            ),
            AnchorRefusal::SamePrincipal { sid } => format!(
                "the app and the signer are the SAME principal ({sid}). That is exactly the \
                 condition O-2 names: an anchor signed by the account that can rewrite what it \
                 attests proves nothing. This is not a warning to acknowledge; there is nothing \
                 to enable"
            ),
            AnchorRefusal::SignerNotAServiceAccount { sid } => format!(
                "the signer SID {sid} is not a service account (S-1-5-80-...). This design \
                 requires a virtual service account so that no password exists and the principal \
                 cannot log on interactively"
            ),
            AnchorRefusal::SignerSidSubstituted { name, derived, resolved } => format!(
                "`NT SERVICE\\{name}` resolves to {resolved} but the service name derives \
                 {derived}. Something other than the service this installer registers is \
                 answering to that name, and it would be handed the anchor key. Remove the \
                 impostor account/service before re-running"
            ),
            AnchorRefusal::NullDacl { path } => format!(
                "{path} has a NULL DACL, which Windows reads as EVERYONE-FULL-CONTROL. That is \
                 the most permissive state Windows has, not 'no access'"
            ),
            AnchorRefusal::DaclNotProtected { path } => format!(
                "{path} does not carry SE_DACL_PROTECTED, so inheritable ACEs from its parent \
                 are merged into it. The explicit ACEs are then a floor rather than the whole \
                 story, and nothing about who is ABSENT can be concluded"
            ),
            AnchorRefusal::UnmappedGenericRights { path, grantees } => format!(
                "{path} grants GENERIC_* rights to {grantees:?}. The kernel maps those at open \
                 time, so GENERIC_WRITE silently contains FILE_APPEND_DATA and this read-back \
                 cannot compute what anyone actually holds. Refusing to guess"
            ),
            AnchorRefusal::WorldInDacl { path, grantees } => format!(
                "{path} grants access to world SID(s) {grantees:?}, which hands it to every \
                 account on the box by group membership regardless of the per-account ACEs"
            ),
            AnchorRefusal::UntrustedOwner { path, owner_sid } => format!(
                "{path} is owned by {owner_sid}, which may not own it. An owner implicitly holds \
                 READ_CONTROL|WRITE_DAC and can rewrite the DACL at will, so every ACE on it is \
                 advisory. The signer's key may be owned ONLY by a TCB principal ({TCB_SIDS:?}) \
                 — stamping that owner needs the ELEVATED installer, and a key owned by the \
                 app's own account would let the app grant itself read. The ledger may be owned \
                 by the app or the TCB, but never by the signer"
            ),
            AnchorRefusal::KeyReachableByApp { path, app_sid, observed_mask } => format!(
                "the DACL read back from {path} grants the app's account {app_sid} \
                 {observed_mask:#010x}. It must grant ZERO — not merely no read: WRITE_DAC alone \
                 would let the app grant itself read and then sign its own anchors"
            ),
            AnchorRefusal::SignerCannotUseItsOwnKey { path, signer_sid, observed_mask } => format!(
                "the DACL read back from {path} grants the signer {signer_sid} \
                 {observed_mask:#010x}, which lacks read and/or write. The service would fail at \
                 first start and the ledger would be silently unanchored"
            ),
            AnchorRefusal::LedgerWritableBySigner { path, signer_sid, observed_mask } => format!(
                "the DACL read back from {path} grants the signer {signer_sid} \
                 {observed_mask:#010x}, which contains write bits ({:#010x}). A signer that can \
                 write the ledger can write a chain to match any head it feels like signing, so \
                 its signature would prove nothing",
                observed_mask & WRITE_ACCESS_BITS
            ),
            AnchorRefusal::LedgerNotWritableByApp { path, app_sid, observed_mask } => format!(
                "the DACL read back from {path} grants the app {app_sid} {observed_mask:#010x}, \
                 which cannot append. The engine could not write the ledger at all"
            ),
            AnchorRefusal::KeyActuallyReadable { path } => format!(
                "this process OPENED {path} and read bytes. Whatever the DACL says, the app can \
                 reach the signer's private key, so it can sign its own anchors. This check is \
                 the one that cannot be fooled by ACE ordering, generic mappings, deny ACEs or \
                 ownership, and it says the separation does not exist"
            ),
            AnchorRefusal::Unmeasurable { path, why } => format!(
                "the security descriptor of {path} could not be read back ({why}), so NOTHING \
                 was proved about it. Note that a process denied all access to a file is also \
                 denied READ_CONTROL on it: the read-back proof must be run by the installer \
                 (elevated) or by the signer, not by the app"
            ),
            AnchorRefusal::SignerAbsent { why } => {
                format!("the signer service is not usable: {why}")
            }
            AnchorRefusal::Unsupported { platform, what } => {
                format!("on {platform}: {what}")
            }
            AnchorRefusal::ElevationRequired { step } => format!(
                "{step} requires Administrator. The SCM refuses service creation to a standard \
                 user by design, and a protected root owned by BUILTIN\\Administrators cannot be \
                 created by a token that may not assign that owner (ERROR_INVALID_OWNER, \
                 0x8007051B). There is no unelevated path to a second principal: any scheme that \
                 skips this prompt also skips the separation"
            ),
        };
        format!(
            "{head}\n  {body}\n  Consequence: the audit ledger stays HONESTLY UNANCHORED. \
             `bro_audit_log.verify()` will report AuditAnchorMissing, which is a refusal, not \
             'intact'. Nothing here degrades to a self-signed anchor."
        )
    }
}

// =================================================================================================
// The environment — emitted only against a completed proof
// =================================================================================================

/// The two variables `bro_audit_log` needs, plus the evidence that emitting them is honest.
///
/// There is deliberately no constructor that takes the paths alone. The only way to obtain one
/// is [`AnchorEnv::from_proofs`], which requires both [`ReadbackProof`]s — so the code path
/// that says "anchoring is on" cannot exist without the code path that proved it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnchorEnv {
    pub signer_command: String,
    pub key_id: String,
    pub separation: Separation,
    pub key_proof: ReadbackProof,
    pub ledger_proof: ReadbackProof,
}

impl AnchorEnv {
    pub fn from_proofs(
        shim_path: &Path,
        key_id: &str,
        separation: Separation,
        key_proof: ReadbackProof,
        ledger_proof: ReadbackProof,
    ) -> Result<AnchorEnv, AnchorRefusal> {
        if !shim_path.is_absolute() {
            return Err(AnchorRefusal::NotASid {
                what: "shim path".to_string(),
                value: shim_path.display().to_string(),
            });
        }
        if key_id.trim().is_empty() {
            return Err(AnchorRefusal::SignerAbsent {
                why: "no anchor key id was recorded, so the engine could not name the key in the \
                      trusted registry"
                    .to_string(),
            });
        }
        Ok(AnchorEnv {
            signer_command: shim_path.display().to_string(),
            key_id: key_id.to_string(),
            separation,
            key_proof,
            ledger_proof,
        })
    }

    /// Exactly what a deployment exports. Returned rather than applied, matching
    /// `Provisioned::engine_env`.
    pub fn engine_env(&self) -> Vec<(&'static str, String)> {
        vec![
            (SIGNER_ENV, self.signer_command.clone()),
            (SIGNER_KEY_ID_ENV, self.key_id.clone()),
        ]
    }

    /// The auditor-facing record: the claim, and the two computations behind it.
    pub fn evidence(&self) -> String {
        format!(
            "{}\n  key custody   {}\n  ledger custody {}",
            self.separation.claim(),
            self.key_proof.summary(),
            self.ledger_proof.summary()
        )
    }
}

// =================================================================================================
// The installer's plan
// =================================================================================================

/// The exact elevated steps, in order, that create the second principal.
///
/// Emitted as data so an installer can run them, a test can assert on them, and an operator
/// who prefers to do it by hand can read them. Every step is idempotent-safe to re-run except
/// the key mint, which the **service performs on its own first start** — see the note below.
pub fn install_steps(paths: &SignerPaths, app_sid: &str) -> Vec<String> {
    let signer_sid = service_account_sid(SIGNER_SERVICE_NAME);
    vec![
        format!(
            "sc.exe create {SIGNER_SERVICE_NAME} binPath= \"{}\" obj= \"NT SERVICE\\{SIGNER_SERVICE_NAME}\" \
             start= auto DisplayName= \"BroPS audit-head anchor signer\"",
            paths.service_exe.display()
        ),
        format!("sc.exe sidtype {SIGNER_SERVICE_NAME} unrestricted"),
        format!(
            "sc.exe description {SIGNER_SERVICE_NAME} \"Signs the BroPS audit ledger head. Runs as a \
             virtual account with no password so the application's account cannot sign for itself.\""
        ),
        format!(
            "mkdir \"{}\"  # then apply the protected DACL: SYSTEM:F, Administrators:F, {signer_sid}:RW, \
             owner=Administrators, inheritance broken",
            paths.signer_dir.display()
        ),
        format!(
            "# the app's account {app_sid} is granted NOTHING here and must not appear in the DACL"
        ),
        format!("sc.exe start {SIGNER_SERVICE_NAME}   # the service MINTS ITS OWN KEY on first start"),
    ]
}

/// Why the installer does not mint the key itself.
///
/// The installer runs elevated, as a human's admin token. If it minted the keypair it would
/// have **witnessed the private half** — the same "an attacker who is already on the machine
/// at install time witnesses the mint" boundary `lib.rs` states for the operator root, except
/// here it is avoidable. The service mints its own seed on first start, inside the directory
/// only it and the TCB can open, and publishes only the public half plus the key id into
/// [`SignerPaths::custody_file`]. The installer therefore never holds the key, and the app
/// never could.
pub const MINT_LOCATION_NOTE: &str = "\
the signer service mints its own Ed25519 seed on first start; neither the installer nor the app \
ever holds the private half. The installer creates only the directory and the service.";

// =================================================================================================
// The signer's own logic — pure, so it is testable everywhere
// =================================================================================================

/// The signer's record of the highest anchor it has signed for one ledger.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnchorState {
    pub ledger: String,
    pub count: i64,
    pub last_hash: String,
    /// SHA-256 of the anchor document this signer last emitted for this ledger. The engine
    /// carries the digest of the anchor file on disk as `previous_anchor_sha256`, so the
    /// signer can check that the file it is being told about is the one it last produced.
    pub anchor_sha256: String,
}

/// The anchor payload's fields, once checked.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnchorFields {
    pub key_id: String,
    pub ledger: String,
    pub count: i64,
    pub last_hash: String,
    pub previous_anchor_sha256: Option<String>,
    pub issued_at_epoch: i64,
}

/// Why the signer refused to sign. Distinct from [`AnchorRefusal`]: this is the *signer*
/// declining a request, not provisioning declining to exist.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SignRefusal {
    NotAnObject,
    WrongFieldSet { extra: Vec<String>, missing: Vec<String> },
    WrongArtifactType { got: String },
    WrongKeyId { expected: String, got: String },
    BadFieldType { field: &'static str },
    NotSha256 { field: &'static str, value: String },
    /// Anti-rollback. The engine's contract requires the signer to refuse this, and the signer
    /// is the only party that can: the app can rewrite its own copy of any state it keeps.
    CountRollback { ledger: String, last_signed: i64, requested: i64 },
    /// Same count, different chain — a rewritten ledger presented at the same length.
    HeadForked { ledger: String, count: i64, last_signed_hash: String, requested_hash: String },
    /// The anchor file the engine measured is not the one this signer last emitted.
    AnchorChainBroken { ledger: String, expected: Option<String>, got: Option<String> },
    /// The process asking to sign is not running as the signer principal.
    WrongPrincipal { expected: String, actual: String },
}

impl std::fmt::Display for SignRefusal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SignRefusal::NotAnObject => write!(f, "the anchor payload is not a JSON object"),
            SignRefusal::WrongFieldSet { extra, missing } => write!(
                f,
                "the anchor payload's field set is wrong (extra={extra:?} missing={missing:?}); \
                 checked as an EXACT set so no field can be smuggled into a document the verifier \
                 then treats as authoritative"
            ),
            SignRefusal::WrongArtifactType { got } => write!(
                f,
                "artifact_type is {got:?}, not {ANCHOR_ARTIFACT_TYPE:?}; this key signs audit heads \
                 and nothing else, so it can never be turned into a registry-artifact oracle"
            ),
            SignRefusal::WrongKeyId { expected, got } => {
                write!(f, "the payload names key_id {got:?}; this signer holds {expected:?}")
            }
            SignRefusal::BadFieldType { field } => write!(f, "field {field} has the wrong type"),
            SignRefusal::NotSha256 { field, value } => {
                write!(f, "field {field} = {value:?} is not 64 lowercase hex characters")
            }
            SignRefusal::CountRollback { ledger, last_signed, requested } => write!(
                f,
                "ANTI-ROLLBACK: this signer last anchored {ledger} at count {last_signed} and is \
                 being asked to anchor count {requested}. Signing it would let a party who can \
                 write the ledger truncate it and obtain a matching anchor"
            ),
            SignRefusal::HeadForked { ledger, count, last_signed_hash, requested_hash } => write!(
                f,
                "FORKED HEAD: {ledger} at count {count} was anchored with last_hash \
                 {last_signed_hash} and is now presented as {requested_hash}. The ledger was \
                 rewritten in place"
            ),
            SignRefusal::AnchorChainBroken { ledger, expected, got } => write!(
                f,
                "the anchor on disk for {ledger} digests to {got:?}, but this signer last emitted \
                 {expected:?}. The previous anchor was replaced or removed"
            ),
            SignRefusal::WrongPrincipal { expected, actual } => write!(
                f,
                "this signer is running as {actual}, not as {expected}. Refusing to use the anchor \
                 key: running it under the ledger writer's own account is the defect the key \
                 exists to close, and would produce anchors that verify and prove nothing"
            ),
        }
    }
}

impl std::error::Error for SignRefusal {}

fn is_sha256_hex(v: &str) -> bool {
    v.len() == 64 && v.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// Check an incoming anchor payload against the engine's own contract, without any key in
/// scope. The field set is checked as an **exact** set, matching
/// `bro_audit_log.ANCHOR_PAYLOAD_FIELDS`.
pub fn check_anchor_payload(payload: &Value, expected_key_id: &str) -> Result<AnchorFields, SignRefusal> {
    let obj: &Map<String, Value> = payload.as_object().ok_or(SignRefusal::NotAnObject)?;
    let want: BTreeSet<&str> = ANCHOR_PAYLOAD_FIELDS.iter().copied().collect();
    let got: BTreeSet<&str> = obj.keys().map(|k| k.as_str()).collect();
    if want != got {
        return Err(SignRefusal::WrongFieldSet {
            extra: got.difference(&want).map(|s| s.to_string()).collect(),
            missing: want.difference(&got).map(|s| s.to_string()).collect(),
        });
    }
    let artifact_type =
        obj["artifact_type"].as_str().ok_or(SignRefusal::BadFieldType { field: "artifact_type" })?;
    if artifact_type != ANCHOR_ARTIFACT_TYPE {
        return Err(SignRefusal::WrongArtifactType { got: artifact_type.to_string() });
    }
    let key_id = obj["key_id"].as_str().ok_or(SignRefusal::BadFieldType { field: "key_id" })?;
    if key_id != expected_key_id {
        return Err(SignRefusal::WrongKeyId {
            expected: expected_key_id.to_string(),
            got: key_id.to_string(),
        });
    }
    let ledger = obj["ledger"].as_str().ok_or(SignRefusal::BadFieldType { field: "ledger" })?;
    let count = obj["count"].as_i64().ok_or(SignRefusal::BadFieldType { field: "count" })?;
    let last_hash = obj["last_hash"].as_str().ok_or(SignRefusal::BadFieldType { field: "last_hash" })?;
    if !is_sha256_hex(last_hash) {
        return Err(SignRefusal::NotSha256 { field: "last_hash", value: last_hash.to_string() });
    }
    let issued_at_epoch =
        obj["issued_at_epoch"].as_i64().ok_or(SignRefusal::BadFieldType { field: "issued_at_epoch" })?;
    let previous = match &obj["previous_anchor_sha256"] {
        Value::Null => None,
        Value::String(s) if is_sha256_hex(s) => Some(s.clone()),
        Value::String(s) => {
            return Err(SignRefusal::NotSha256 {
                field: "previous_anchor_sha256",
                value: s.clone(),
            })
        }
        _ => return Err(SignRefusal::BadFieldType { field: "previous_anchor_sha256" }),
    };
    Ok(AnchorFields {
        key_id: key_id.to_string(),
        ledger: ledger.to_string(),
        count,
        last_hash: last_hash.to_string(),
        previous_anchor_sha256: previous,
        issued_at_epoch,
    })
}

/// The anti-rollback decision, in full.
///
/// * A **lower** count than the last one signed is refused outright — the engine's contract
///   names this as the signer's job, and it is the signer's job because the app can rewrite
///   any state the app keeps.
/// * The **same** count is allowed only if the head is byte-identical; re-signing an unchanged
///   head is idempotent, while the same length with a different tail is a rewritten ledger.
/// * The `previous_anchor_sha256` the engine measured must be the digest of the anchor this
///   signer last emitted. Removing or replacing the anchor file to escape the check is
///   therefore itself refused.
pub fn check_monotonic(fields: &AnchorFields, last: Option<&AnchorState>) -> Result<(), SignRefusal> {
    let Some(prev) = last else {
        // First anchor for this ledger. `previous_anchor_sha256` must be absent: a value there
        // would mean an anchor exists that this signer did not produce.
        return match &fields.previous_anchor_sha256 {
            None => Ok(()),
            Some(got) => Err(SignRefusal::AnchorChainBroken {
                ledger: fields.ledger.clone(),
                expected: None,
                got: Some(got.clone()),
            }),
        };
    };
    if fields.count < prev.count {
        return Err(SignRefusal::CountRollback {
            ledger: fields.ledger.clone(),
            last_signed: prev.count,
            requested: fields.count,
        });
    }
    if fields.count == prev.count && fields.last_hash != prev.last_hash {
        return Err(SignRefusal::HeadForked {
            ledger: fields.ledger.clone(),
            count: fields.count,
            last_signed_hash: prev.last_hash.clone(),
            requested_hash: fields.last_hash.clone(),
        });
    }
    if fields.previous_anchor_sha256.as_deref() != Some(prev.anchor_sha256.as_str()) {
        return Err(SignRefusal::AnchorChainBroken {
            ledger: fields.ledger.clone(),
            expected: Some(prev.anchor_sha256.clone()),
            got: fields.previous_anchor_sha256.clone(),
        });
    }
    Ok(())
}

/// The anchor sidecar's bytes **exactly as `bro_audit_log` writes them to disk**.
///
/// # Why this is not `serde_json::to_vec`
///
/// The signer's anti-rollback state records the digest of the anchor it last emitted, and the
/// engine tells it, in the next payload's `previous_anchor_sha256`, the digest of the anchor
/// file it found. Those two numbers must be the same number or every anchor after the first is
/// refused as [`SignRefusal::AnchorChainBroken`].
///
/// The engine's digest is over the FILE, and `_install_anchor` writes that file with
/// `json.dumps(document, sort_keys=True)` — Python's **default** separators, `", "` and `": "`,
/// with `ensure_ascii=True`. `serde_json::to_vec` writes the compact form with no spaces and
/// raw UTF-8. The two differ on the first anchor and every one after it.
///
/// This was not a hypothetical: `sign_anchor` used `serde_json::to_vec`, every Rust test agreed
/// with itself, and the real `bro_audit_log` refused the **second** append of every ledger. Only
/// running the module that has to accept the anchor could find it, which is the whole argument
/// for `audit-signer/tests/anchor_end_to_end.py`.
///
/// Note the asymmetry, because it is deliberate and not a mistake: the bytes that are **signed**
/// are [`crate::canonical::canonical_bytes`] (compact, `bro_signature.canonical_bytes`), and the
/// bytes that are **digested for the rollback chain** are these (spaced, `json.dumps` default).
/// Two different encodings of the same document, because the engine uses two different ones.
///
/// Fail-closed on anything it cannot reproduce exactly. A float has no agreed shortest
/// representation between Python's `repr` and Rust's, so rather than emit a digest that might be
/// right, this refuses — no anchor payload contains one, and if one is ever added the refusal is
/// what makes that visible.
pub fn installed_anchor_bytes(document: &Value) -> Result<Vec<u8>, ProvisionError> {
    let mut out = Vec::new();
    write_python_json(document, &mut out)?;
    Ok(out)
}

fn write_python_json(value: &Value, out: &mut Vec<u8>) -> Result<(), ProvisionError> {
    match value {
        Value::Null => out.extend_from_slice(b"null"),
        Value::Bool(true) => out.extend_from_slice(b"true"),
        Value::Bool(false) => out.extend_from_slice(b"false"),
        Value::Number(n) => {
            if n.is_f64() {
                return Err(ProvisionError::Corrupt {
                    what: "an anchor document contains a floating-point number".to_string(),
                    detail: format!(
                        "{n} cannot be re-encoded byte-identically to Python's json.dumps, so the \
                         digest this signer records would not match the digest the engine \
                         computes over the anchor FILE, and every later anchor would be refused \
                         as AnchorChainBroken. Refusing rather than emitting a digest that might \
                         be right"
                    ),
                });
            }
            out.extend_from_slice(n.to_string().as_bytes());
        }
        Value::String(s) => write_python_json_string(s, out),
        Value::Array(items) => {
            out.push(b'[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.extend_from_slice(b", ");
                }
                write_python_json(item, out)?;
            }
            out.push(b']');
        }
        Value::Object(map) => {
            // `serde_json::Map` is a `BTreeMap` here, so iteration is already `sort_keys=True`.
            out.push(b'{');
            for (i, (k, v)) in map.iter().enumerate() {
                if i > 0 {
                    out.extend_from_slice(b", ");
                }
                write_python_json_string(k, out);
                out.extend_from_slice(b": ");
                write_python_json(v, out)?;
            }
            out.push(b'}');
        }
    }
    Ok(())
}

/// `json.encoder.py_encode_basestring_ascii`: escape `"` and `\`, use the short forms for the
/// five control characters that have them, and `\uXXXX` for **everything outside `0x20..=0x7E`** —
/// which includes `0x7F` and every non-ASCII character, as surrogate pairs above `0xFFFF`.
fn write_python_json_string(s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    for ch in s.chars() {
        match ch {
            '"' => out.extend_from_slice(b"\\\""),
            '\\' => out.extend_from_slice(b"\\\\"),
            '\u{8}' => out.extend_from_slice(b"\\b"),
            '\u{c}' => out.extend_from_slice(b"\\f"),
            '\n' => out.extend_from_slice(b"\\n"),
            '\r' => out.extend_from_slice(b"\\r"),
            '\t' => out.extend_from_slice(b"\\t"),
            c if (' '..='~').contains(&c) => out.push(c as u8),
            c => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.extend_from_slice(format!("\\u{unit:04x}").as_bytes());
                }
            }
        }
    }
    out.push(b'"');
}

/// Sign a checked anchor payload and return both the `{payload, signature}` document the
/// engine expects and the state to record.
///
/// Uses [`crate::sign_document`], so the bytes signed are exactly
/// [`crate::canonical::canonical_bytes`] — the same encoding `bro_signature.verify_detached`
/// recomputes. There is no second signing path in this crate.
///
/// The recorded `anchor_sha256` is over [`installed_anchor_bytes`], **not** over the signed
/// bytes: the engine digests the sidecar file, and that file is written by `json.dumps` with
/// Python's default separators. See that function for why the two encodings differ on purpose.
pub fn sign_anchor(
    key: &SigningKey,
    payload: Value,
    fields: &AnchorFields,
) -> Result<(Value, AnchorState), ProvisionError> {
    // Recompute the canonical bytes here as well as inside `sign_document`, so a payload the
    // canonicaliser rejects fails before any signature exists.
    let _ = canonical_bytes(&payload)?;
    let document = crate::sign_document(key, payload)?;
    let bytes = installed_anchor_bytes(&document)?;
    Ok((
        document,
        AnchorState {
            ledger: fields.ledger.clone(),
            count: fields.count,
            last_hash: fields.last_hash.clone(),
            anchor_sha256: sha256_hex(&bytes),
        },
    ))
}

/// The whole signer decision in one call: check, refuse rollback, sign, hand back new state.
///
/// `running_as` / `expected_principal` are the guard that makes it impossible to use this as
/// a same-account signing oracle: the caller must be running as the signer principal. Pointing
/// `BRO_AUDIT_ANCHOR_SIGNER` directly at the signer binary — which would run it under the
/// app's token — fails here, by construction, before a key is touched.
#[allow(clippy::too_many_arguments)]
pub fn anchor_request(
    payload: Value,
    expected_key_id: &str,
    expected_principal: &str,
    running_as: &str,
    key: &SigningKey,
    last: Option<&AnchorState>,
) -> Result<(Value, AnchorState), SignRefusal> {
    if running_as != expected_principal {
        return Err(SignRefusal::WrongPrincipal {
            expected: expected_principal.to_string(),
            actual: running_as.to_string(),
        });
    }
    let fields = check_anchor_payload(&payload, expected_key_id)?;
    check_monotonic(&fields, last)?;
    let (document, state) = sign_anchor(key, payload, &fields).map_err(|e| {
        // A canonicalisation/serialisation failure is not a policy refusal; surface it as a
        // field-type problem rather than inventing a success.
        SignRefusal::BadFieldType {
            field: Box::leak(format!("<canonicalisation failed: {e}>").into_boxed_str()),
        }
    })?;
    Ok((document, state))
}

/// The custody record the service publishes beside its key. The app reads it to learn the key
/// id and the public half; it can never write it.
pub fn custody_record(key_id: &str, public_key_hex: &str, signer_sid: &str) -> Value {
    json!({
        "schema": 1,
        "key_id": key_id,
        "public_key": public_key_hex,
        "authority": ANCHOR_AUTHORITY,
        "allowed_artifact_types": [ANCHOR_ARTIFACT_TYPE],
        "signer_principal_sid": signer_sid,
        "service_name": SIGNER_SERVICE_NAME,
        "note": MINT_LOCATION_NOTE,
    })
}

/// Key id for the anchor key. Derived from the public half so it cannot be chosen, and
/// prefixed so it is obvious in a registry which key this is.
pub fn anchor_key_id(public_key_hex: &str) -> String {
    let digest = sha256_hex(public_key_hex.as_bytes());
    format!("audit-anchor-{}", &digest[..16])
}

/// Mint a fresh anchor seed. Called by the **service**, under its own account, on first start.
pub fn mint_anchor_key() -> Result<(SigningKey, String, String), ProvisionError> {
    let mut seed = [0u8; 32];
    getrandom::getrandom(&mut seed).map_err(|e| ProvisionError::Unsupported {
        platform: crate::platform_name().to_string(),
        what: format!("the OS CSPRNG is unavailable, so no anchor key can be minted: {e}"),
    })?;
    let key = SigningKey::from_bytes(&seed);
    let public = hex(key.verifying_key().as_bytes());
    let key_id = anchor_key_id(&public);
    Ok((key, public, key_id))
}

// =================================================================================================
// Windows effect
// =================================================================================================

/// Read a security descriptor back and answer the two questions this module asks.
///
/// **Not** `tcb_floor::WindowsFsProbe`: that probe digests the file contents, so it returns
/// `None` for exactly the file whose unreadability is the thing being proved.
#[cfg(windows)]
pub mod winimpl {
    use super::{
        Ace, AnchorRefusal, AppTokenPosture, DaclFacts, DaclPlan, SID_ADMINISTRATORS,
        SIGNER_SERVICE_NAME,
    };
    use std::ffi::c_void;
    use std::path::Path;
    use windows::core::{Error, PCWSTR, PWSTR};
    use windows::Win32::Foundation::{
        CloseHandle, LocalFree, BOOL, ERROR_SUCCESS, HANDLE, HLOCAL,
    };
    use windows::Win32::Security::Authorization::{
        ConvertSidToStringSidW, ConvertStringSidToSidW, GetNamedSecurityInfoW,
        SetNamedSecurityInfoW, SE_FILE_OBJECT,
    };
    use windows::Win32::Security::{
        AclSizeInformation, AddAccessAllowedAceEx, CheckTokenMembership, GetAce,
        GetAclInformation, GetSecurityDescriptorControl, GetTokenInformation, InitializeAcl,
        LookupAccountNameW, ACCESS_ALLOWED_ACE, ACE_FLAGS, ACE_HEADER, ACL, ACL_REVISION,
        ACL_SIZE_INFORMATION, DACL_SECURITY_INFORMATION, OBJECT_SECURITY_INFORMATION,
        OWNER_SECURITY_INFORMATION, PSECURITY_DESCRIPTOR, PSID, SID_NAME_USE, TOKEN_GROUPS,
        TOKEN_QUERY, TOKEN_USER, TokenGroups, TokenUser,
    };
    use windows::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;
    use windows::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    /// `SE_DACL_PROTECTED`.
    const SE_DACL_PROTECTED_BIT: u16 = 0x1000;
    /// `SE_GROUP_USE_FOR_DENY_ONLY` — the bit a filtered admin token carries on
    /// `BUILTIN\Administrators`.
    const SE_GROUP_USE_FOR_DENY_ONLY: u32 = 0x0000_0010;
    /// `SE_GROUP_ENABLED`.
    const SE_GROUP_ENABLED: u32 = 0x0000_0004;

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    unsafe fn sid_string(psid: PSID) -> Option<String> {
        let mut out = PWSTR::null();
        ConvertSidToStringSidW(psid, &mut out).ok()?;
        let s = out.to_string().ok();
        let _ = LocalFree(HLOCAL(out.0 as *mut c_void));
        s
    }

    /// The SID this process is running as.
    pub fn current_user_sid() -> Result<String, AnchorRefusal> {
        unsafe {
            let mut token = HANDLE::default();
            OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token).map_err(|e| {
                AnchorRefusal::Unmeasurable {
                    path: "<own token>".to_string(),
                    why: format!("OpenProcessToken: {e:?}"),
                }
            })?;
            let mut len = 0u32;
            let _ = GetTokenInformation(token, TokenUser, None, 0, &mut len);
            let mut buf = vec![0u8; len.max(1) as usize];
            let res = GetTokenInformation(
                token,
                TokenUser,
                Some(buf.as_mut_ptr() as *mut c_void),
                len,
                &mut len,
            );
            let out = match res {
                Ok(()) => {
                    let tu = &*(buf.as_ptr() as *const TOKEN_USER);
                    sid_string(tu.User.Sid)
                }
                Err(e) => {
                    let _ = CloseHandle(token);
                    return Err(AnchorRefusal::Unmeasurable {
                        path: "<own token>".to_string(),
                        why: format!("GetTokenInformation(TokenUser): {e:?}"),
                    });
                }
            };
            let _ = CloseHandle(token);
            out.ok_or(AnchorRefusal::Unmeasurable {
                path: "<own token>".to_string(),
                why: "could not stringify the token user SID".to_string(),
            })
        }
    }

    /// Where this process's account sits relative to `BUILTIN\Administrators`.
    ///
    /// Three-valued on purpose. `CheckTokenMembership` alone answers "is this token elevated",
    /// which is the wrong question: a *filtered* admin token is denied today and one UAC
    /// consent away from full control of the signer's key. Both are reported as
    /// administrator, distinguished only so the message can be accurate.
    pub fn app_token_posture() -> Result<AppTokenPosture, AnchorRefusal> {
        unsafe {
            let admins = wide(SID_ADMINISTRATORS);
            let mut psid = PSID::default();
            if ConvertStringSidToSidW(PCWSTR(admins.as_ptr()), &mut psid).is_err() {
                return Err(AnchorRefusal::Unmeasurable {
                    path: "<own token>".to_string(),
                    why: "ConvertStringSidToSidW(S-1-5-32-544) failed".to_string(),
                });
            }
            let mut is_member = BOOL(0);
            let enabled = CheckTokenMembership(None, psid, &mut is_member).is_ok()
                && is_member.as_bool();
            let _ = LocalFree(HLOCAL(psid.0));
            if enabled {
                return Ok(AppTokenPosture::ElevatedAdministrator);
            }

            // Not enabled. Look for a deny-only Administrators entry, which means the human
            // behind this token can elevate without a credential.
            let mut token = HANDLE::default();
            OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token).map_err(|e| {
                AnchorRefusal::Unmeasurable {
                    path: "<own token>".to_string(),
                    why: format!("OpenProcessToken: {e:?}"),
                }
            })?;
            let mut len = 0u32;
            let _ = GetTokenInformation(token, TokenGroups, None, 0, &mut len);
            let mut buf = vec![0u8; len.max(1) as usize];
            let res = GetTokenInformation(
                token,
                TokenGroups,
                Some(buf.as_mut_ptr() as *mut c_void),
                len,
                &mut len,
            );
            let mut posture = AppTokenPosture::StandardUser;
            if res.is_ok() {
                let groups = &*(buf.as_ptr() as *const TOKEN_GROUPS);
                let slice =
                    std::slice::from_raw_parts(groups.Groups.as_ptr(), groups.GroupCount as usize);
                for g in slice {
                    if let Some(s) = sid_string(g.Sid) {
                        if s == SID_ADMINISTRATORS {
                            posture = if g.Attributes & SE_GROUP_USE_FOR_DENY_ONLY != 0 {
                                AppTokenPosture::FilteredAdministrator
                            } else if g.Attributes & SE_GROUP_ENABLED != 0 {
                                AppTokenPosture::ElevatedAdministrator
                            } else {
                                AppTokenPosture::FilteredAdministrator
                            };
                            break;
                        }
                    }
                }
            }
            let _ = CloseHandle(token);
            Ok(posture)
        }
    }

    /// Owner + control word + ACCESS_ALLOWED ACEs of `path`, with the contents never opened.
    ///
    /// A caller denied all access to the object is also denied `READ_CONTROL`, so this returns
    /// [`AnchorRefusal::Unmeasurable`] when run by the app against the signer's key. That is
    /// correct and load-bearing: the DACL read-back proof belongs to the installer (elevated)
    /// or to the signer, and the app's half of the proof is the behavioural
    /// [`app_can_read`] probe instead.
    pub fn dacl_facts(path: &Path) -> Result<DaclFacts, AnchorRefusal> {
        let p = path.display().to_string();
        let w = wide(&p);
        unsafe {
            let mut owner = PSID::default();
            let mut dacl: *mut ACL = std::ptr::null_mut();
            let mut psd = PSECURITY_DESCRIPTOR::default();
            let rc = GetNamedSecurityInfoW(
                PCWSTR(w.as_ptr()),
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                Some(&mut owner),
                None,
                Some(&mut dacl),
                None,
                &mut psd,
            );
            if rc != ERROR_SUCCESS {
                return Err(AnchorRefusal::Unmeasurable {
                    path: p,
                    why: format!("GetNamedSecurityInfoW returned {rc:?}"),
                });
            }
            let owner_sid = sid_string(owner).unwrap_or_default();
            let dacl_present = !dacl.is_null();

            // `SECURITY_DESCRIPTOR_CONTROL` is a bare `u16` in this binding.
            let mut control: u16 = 0;
            let mut revision = 0u32;
            let dacl_protected = GetSecurityDescriptorControl(psd, &mut control, &mut revision)
                .is_ok()
                && (control & SE_DACL_PROTECTED_BIT) != 0;

            let mut allow_aces: Vec<Ace> = Vec::new();
            if dacl_present {
                let mut info = ACL_SIZE_INFORMATION::default();
                if GetAclInformation(
                    dacl,
                    &mut info as *mut _ as *mut c_void,
                    std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                    AclSizeInformation,
                )
                .is_ok()
                {
                    for i in 0..info.AceCount {
                        let mut pace: *mut c_void = std::ptr::null_mut();
                        if GetAce(dacl, i, &mut pace).is_err() || pace.is_null() {
                            continue;
                        }
                        let hdr = &*(pace as *const ACE_HEADER);
                        // Deny ACEs are skipped, exactly as `tcb_floor` does: ignoring them can
                        // only over-report a principal's access, which is the fail-closed
                        // direction for both questions asked here.
                        if hdr.AceType as u32 != ACCESS_ALLOWED_ACE_TYPE {
                            continue;
                        }
                        let inheritable = hdr.AceFlags as u32 & 0x03 != 0;
                        let ace = &*(pace as *const ACCESS_ALLOWED_ACE);
                        let psid = PSID(&ace.SidStart as *const u32 as *mut c_void);
                        if let Some(sid) = sid_string(psid) {
                            allow_aces.push(Ace { sid, mask: ace.Mask, inheritable });
                        }
                    }
                }
            }
            if !psd.is_invalid() {
                let _ = LocalFree(HLOCAL(psd.0));
            }
            Ok(DaclFacts { path: p, owner_sid, dacl_present, dacl_protected, allow_aces })
        }
    }

    /// The behavioural half of the key proof, and the only half the **app** can run.
    ///
    /// Opens the file for read as this process. `Ok(false)` means the OS denied it, which is
    /// the property; `Ok(true)` means the separation does not exist regardless of what any
    /// DACL says. Immune to ACE ordering, generic mappings, deny ACEs, inheritance and
    /// ownership, because it asks the same kernel code path a thief would.
    pub fn app_can_read(path: &Path) -> Result<bool, AnchorRefusal> {
        match std::fs::File::open(path) {
            Ok(_) => Ok(true),
            Err(e) => match e.raw_os_error() {
                // ERROR_ACCESS_DENIED / ERROR_SHARING_VIOLATION: denied.
                Some(5) | Some(32) => Ok(false),
                // Absent is NOT proof of anything.
                _ => Err(AnchorRefusal::Unmeasurable {
                    path: path.display().to_string(),
                    why: format!(
                        "open() failed with {e} — neither access nor denial was demonstrated"
                    ),
                }),
            },
        }
    }

    /// Stamp a [`DaclPlan`] onto an existing path as a **protected** DACL, and optionally an
    /// owner.
    ///
    /// `SetNamedSecurityInfoW`, not `provision_custody::create_locked_file`. That constructor
    /// creates a *file* with the descriptor already attached, which is the right shape for a
    /// secret whose plaintext must never exist under a weaker DACL for even a moment; it has no
    /// directory form and no inheritance flags. The ledger is a **directory** whose children
    /// (`.jsonl`, `.head`, `.anchor`, `.lock`) are created by the *engine* and can only be
    /// protected by inheritance, so its ACEs must carry `CONTAINER_INHERIT_ACE |
    /// OBJECT_INHERIT_ACE` and be applied to a container that already exists. The ledger also has
    /// no plaintext window to race — it holds no secret, only a hash chain.
    ///
    /// `PROTECTED_DACL_SECURITY_INFORMATION` is the flag that makes absence mean denial: without
    /// it the parent's inheritable ACEs are merged back in, and every conclusion drawn from "who
    /// is not in this DACL" evaporates.
    ///
    /// Assigning the owner needs `SeRestorePrivilege` (or a token that already carries the target
    /// group), so `owner_sid = Some(SID_ADMINISTRATORS)` fails unelevated. That failure is
    /// returned with the error code spelled out, never swallowed.
    pub fn apply_dacl(
        path: &Path,
        plan: &DaclPlan,
        owner_sid: Option<&str>,
    ) -> Result<(), AnchorRefusal> {
        const CONTAINER_INHERIT_ACE: u32 = 0x02;
        const OBJECT_INHERIT_ACE: u32 = 0x01;
        const PROTECTED_DACL_SECURITY_INFORMATION: u32 = 0x8000_0000;
        const MAX_SID_BYTES: usize = 68;

        let p = path.display().to_string();
        let fail = |why: String| AnchorRefusal::Unmeasurable { path: p.clone(), why };
        unsafe {
            let mut sids: Vec<PSID> = Vec::with_capacity(plan.aces.len() + 1);
            let free = |sids: &Vec<PSID>| {
                for s in sids {
                    let _ = LocalFree(HLOCAL(s.0));
                }
            };
            for ace in &plan.aces {
                let w = wide(&ace.sid);
                let mut psid = PSID::default();
                if ConvertStringSidToSidW(PCWSTR(w.as_ptr()), &mut psid).is_err() {
                    free(&sids);
                    return Err(fail(format!("ConvertStringSidToSidW({}) failed", ace.sid)));
                }
                sids.push(psid);
            }
            let acl_len = std::mem::size_of::<ACL>()
                + plan.aces.len() * (std::mem::size_of::<u32>() * 3 + MAX_SID_BYTES);
            let mut acl = vec![0u8; acl_len];
            let pacl = acl.as_mut_ptr() as *mut ACL;
            if InitializeAcl(pacl, acl_len as u32, ACL_REVISION).is_err() {
                free(&sids);
                return Err(fail(format!("InitializeAcl: {:?}", Error::from_win32())));
            }
            for (ace, psid) in plan.aces.iter().zip(sids.iter()) {
                let flags = if ace.inheritable {
                    CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE
                } else {
                    0
                };
                if AddAccessAllowedAceEx(pacl, ACL_REVISION, ACE_FLAGS(flags), ace.mask, *psid)
                    .is_err()
                {
                    free(&sids);
                    return Err(fail(format!(
                        "AddAccessAllowedAceEx({}): {:?}",
                        ace.sid,
                        Error::from_win32()
                    )));
                }
            }
            let mut owner_psid = PSID::default();
            let mut info = DACL_SECURITY_INFORMATION.0 | PROTECTED_DACL_SECURITY_INFORMATION;
            if let Some(owner) = owner_sid {
                let w = wide(owner);
                if ConvertStringSidToSidW(PCWSTR(w.as_ptr()), &mut owner_psid).is_err() {
                    free(&sids);
                    return Err(fail(format!("ConvertStringSidToSidW(owner {owner}) failed")));
                }
                sids.push(owner_psid);
                info |= OWNER_SECURITY_INFORMATION.0;
            }
            let w = wide(&p);
            let rc = SetNamedSecurityInfoW(
                PCWSTR(w.as_ptr()),
                SE_FILE_OBJECT,
                OBJECT_SECURITY_INFORMATION(info),
                // A null PSID here means "do not change the owner"; the OWNER_SECURITY_INFORMATION
                // bit in `info` is what decides whether it is read at all.
                owner_psid,
                None,
                Some(pacl),
                None,
            );
            free(&sids);
            if rc != ERROR_SUCCESS {
                return Err(fail(format!(
                    "SetNamedSecurityInfoW returned {rc:?}; ERROR_INVALID_OWNER (0x51B) or \
                     ERROR_PRIVILEGE_NOT_HELD (0x522) means this token may not assign the \
                     requested owner, which needs an ELEVATED installer"
                )));
            }
        }
        Ok(())
    }

    /// Resolve `NT SERVICE\<name>` and check it against the SID derived from the name.
    pub fn resolve_service_sid(service_name: &str) -> Result<String, AnchorRefusal> {
        let account = format!("NT SERVICE\\{service_name}");
        let name = wide(&account);
        unsafe {
            let mut sid_len = 0u32;
            let mut dom_len = 0u32;
            let mut use_ = SID_NAME_USE(0);
            let _ = LookupAccountNameW(
                PCWSTR::null(),
                PCWSTR(name.as_ptr()),
                PSID::default(),
                &mut sid_len,
                PWSTR::null(),
                &mut dom_len,
                &mut use_,
            );
            if sid_len == 0 {
                return Err(AnchorRefusal::SignerAbsent {
                    why: format!(
                        "LookupAccountNameW({account}) found no such principal — the \
                         {SIGNER_SERVICE_NAME} service is not registered on this machine"
                    ),
                });
            }
            let mut sid_buf = vec![0u8; sid_len.max(68) as usize];
            let mut dom_buf = vec![0u16; dom_len.max(1) as usize];
            let psid = PSID(sid_buf.as_mut_ptr() as *mut c_void);
            LookupAccountNameW(
                PCWSTR::null(),
                PCWSTR(name.as_ptr()),
                psid,
                &mut sid_len,
                PWSTR(dom_buf.as_mut_ptr()),
                &mut dom_len,
                &mut use_,
            )
            .map_err(|e| AnchorRefusal::SignerAbsent {
                why: format!("LookupAccountNameW({account}): {e:?}"),
            })?;
            sid_string(psid).ok_or(AnchorRefusal::SignerAbsent {
                why: format!("could not stringify the SID for {account}"),
            })
        }
    }
}

/// Off Windows the second principal is not this module's business: POSIX deployments already
/// have a `signer` user and `lib.rs`'s existing `secure_owner_only_file` path is unchanged.
/// Every entry point here refuses rather than pretending.
#[cfg(not(windows))]
pub mod winimpl {
    use super::{AnchorRefusal, AppTokenPosture, DaclFacts};
    use std::path::Path;

    fn unsupported(what: &str) -> AnchorRefusal {
        AnchorRefusal::Unsupported {
            platform: crate::platform_name().to_string(),
            what: format!(
                "{what} is a Windows security-descriptor operation. On POSIX the audit signer is \
                 a separate uid whose key the engine's account cannot read, provisioned outside \
                 this crate; nothing here applies"
            ),
        }
    }

    pub fn current_user_sid() -> Result<String, AnchorRefusal> {
        Err(unsupported("reading the process token's user SID"))
    }
    pub fn app_token_posture() -> Result<AppTokenPosture, AnchorRefusal> {
        Err(unsupported("measuring Administrators membership"))
    }
    pub fn dacl_facts(path: &Path) -> Result<DaclFacts, AnchorRefusal> {
        let _ = path;
        Err(unsupported("reading a DACL back"))
    }
    pub fn app_can_read(path: &Path) -> Result<bool, AnchorRefusal> {
        let _ = path;
        Err(unsupported("probing Windows access"))
    }
    pub fn resolve_service_sid(service_name: &str) -> Result<String, AnchorRefusal> {
        let _ = service_name;
        Err(unsupported("resolving a service account"))
    }
    pub fn apply_dacl(
        path: &Path,
        plan: &super::DaclPlan,
        owner_sid: Option<&str>,
    ) -> Result<(), AnchorRefusal> {
        let _ = (path, plan, owner_sid);
        Err(unsupported("applying a security descriptor"))
    }
}

// =================================================================================================
// The one entry point the host calls
// =================================================================================================

/// Everything that was actually established about the second principal on this machine.
#[derive(Debug, Clone)]
pub struct AnchorStatus {
    pub app_sid: String,
    pub signer_sid: String,
    pub separation: Separation,
    pub env: AnchorEnv,
}

/// Verify an installed second principal and, only if every proof holds, produce the
/// environment that turns anchoring on.
///
/// Runs, in order and all of them:
/// 1. the app's own SID and Administrators posture;
/// 2. `NT SERVICE\BroPSAuditSigner` resolves to the SID derived from the service name;
/// 3. the **behavioural** proof that this process cannot open the signer's key;
/// 4. the **read-back** proof over the ledger directory's real DACL, computing that the
///    signer holds no write bit and the app does;
/// 5. the key file's read-back proof, *if* this process can read the descriptor — which it
///    cannot when the separation is working, so a `Unmeasurable` there is accepted and
///    recorded as "proved behaviourally instead", and anything else is a refusal.
///
/// Any failure returns [`AnchorRefusal`] and the caller must leave the ledger unanchored.
pub fn verify_installed(
    paths: &SignerPaths,
    key_id: &str,
) -> Result<AnchorStatus, AnchorRefusal> {
    let app_sid = winimpl::current_user_sid()?;
    let posture = winimpl::app_token_posture()?;
    let separation = Separation::from_posture(posture);

    let derived = service_account_sid(SIGNER_SERVICE_NAME);
    let resolved = winimpl::resolve_service_sid(SIGNER_SERVICE_NAME)?;
    if resolved != derived {
        return Err(AnchorRefusal::SignerSidSubstituted {
            name: SIGNER_SERVICE_NAME.to_string(),
            derived,
            resolved,
        });
    }
    let signer_sid = derived;

    let key_plan = key_dacl_plan(&app_sid, &signer_sid)?;
    let ledger_plan = ledger_dacl_plan(&app_sid, &signer_sid)?;

    // 3. Behavioural: the app must NOT be able to open the key.
    if winimpl::app_can_read(&paths.key_file)? {
        return Err(AnchorRefusal::KeyActuallyReadable {
            path: paths.key_file.display().to_string(),
        });
    }

    // 4. Ledger read-back — the app owns this directory, so it can read the descriptor.
    let ledger_facts = winimpl::dacl_facts(&paths.ledger_dir)?;
    let ledger_proof = verify_ledger_custody(&ledger_plan, &ledger_facts)?;

    // 5. Key read-back, when available. Being denied here is the expected, healthy case.
    let key_proof = match winimpl::dacl_facts(&paths.key_file) {
        Ok(facts) => verify_key_custody(&key_plan, &facts)?,
        Err(AnchorRefusal::Unmeasurable { path, .. }) => ReadbackProof {
            path: format!("{path} (descriptor unreadable by this account — which is the property)"),
            excluded_sid: app_sid.clone(),
            forbidden_mask: READ_ACCESS_BITS | WRITE_ACCESS_BITS | READ_CONTROL,
            // Denied READ_CONTROL means denied everything measured here; the behavioural probe
            // above is what established it, and this records that rather than claiming a
            // read-back that did not happen.
            observed_mask: 0,
            required_mask: 0,
            required_sid: signer_sid.clone(),
            observed_required_mask: 0,
            owner_sid: "<unreadable>".to_string(),
            dacl_protected: false,
        },
        Err(other) => return Err(other),
    };

    let env = AnchorEnv::from_proofs(
        &paths.shim_path,
        key_id,
        separation.clone(),
        key_proof,
        ledger_proof,
    )?;
    Ok(AnchorStatus { app_sid, signer_sid, separation, env })
}
