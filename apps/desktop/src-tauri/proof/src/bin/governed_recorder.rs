//! Wave 3b-1B — the §2.7 evidence-recorder as a standalone privileged helper (LINUX-RUN live governed turn).
//!
//! The recorder is the process the trusted broker delegates the privileged execution to. It MUST run under
//! the dedicated recorder UID (the launcher's §2.7 step-1 invoker gate binds the setuid launcher to exactly
//! that real uid/gid), so the broker — a DIFFERENT principal — spawns this helper via the recorder identity
//! (`sudo -u brops-recorder …`) rather than `execve`ing the launcher itself.
//!
//! It prepares the exact §2.7 descriptor table (0=/dev/null RO, 1/2=/dev/null WO, 3/4/5 the read-only store
//! inputs `system`/`history`/`generation_config`, 6 the write-only output pipe), clears `FD_CLOEXEC` on the
//! data FDs so they cross `execve`, then `execve`s the setuid launcher with the fixed closed argv
//! `[launcher, lease, executor, cgroup]` and an EMPTY environment. The launcher drops privilege and
//! `fexecve`s the pinned executor, which writes its reply bytes to fd 6. The parent captures those bytes and
//! writes them to `--out` — those exact bytes are the governed turn's output. Fail-closed: a non-zero
//! launcher exit or an empty capture yields a non-zero exit and an empty/absent `--out`, never a fabricated
//! output.
//!
//! # ARGV DOES NOT STEER THE RECORDER (round-3 P0)
//!
//! The recorder is the trusted identity in this chain: the supervisor reads the evidence chain out of the
//! recorder's private directory precisely *because* the broker cannot write there, and refuses a completion
//! whose `output_handle` disagrees with it. That wall was bypassable, because the caller — the broker uid,
//! which reaches this binary through `sudo -u brops-recorder` — also supplied `--launcher`, `--executor`,
//! `--store`, `--lease`, `--evidence-out` and `--evidence-state` on the command line, and this program
//! `execve`d whatever `--launcher` named. A broker could therefore have the *recorder* write an authentic
//! evidence chain for an execution the *broker* authored, and the supervisor would rightly believe it,
//! because the chain really was written by the recorder.
//!
//! Every one of those values now comes from [`guard::POLICY_PATH`] — a root-owned, root-ancestored file at a
//! COMPILE-TIME path. It is not `--policy`, not `$BROPS_…`: there is no runtime input that can redirect it.
//! Argv may still carry the pinned flags (the broker's spawn is unchanged), but a value that disagrees with
//! the policy is a REFUSAL, not an override, and the pinned launcher/executor images are re-hashed against
//! the policy's digests immediately before the exec. The only thing the caller still chooses is the *file
//! name* of the three per-run outputs, and those must lexically resolve inside the policy's own directories.
//!
//! On a non-Linux host the fork/execve/inherited-fd model does not exist ⇒ exit non-zero (fail closed).

// The custody/steering decisions live here, OUTSIDE the `linux` module, so they compile — and are unit
// tested — on every platform. The syscall half below is Linux-only and cannot be tested on the dev box;
// keeping the decisions pure is what makes "delete the check and a test goes red" achievable at all.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
pub mod guard {
    use std::collections::BTreeMap;

    /// The ONE place the recorder's steering may come from.
    ///
    /// A compile-time constant on purpose. A `--policy <path>` flag would put the choice of policy back in
    /// the caller's hands, and an environment variable would rest on `sudo`'s `env_reset` being configured
    /// the way we hope — the audit finding is specifically that caller-controlled input must not be able to
    /// select what the trusted identity executes.
    pub const POLICY_PATH: &str = "/opt/brops-live/tcb/recorder-policy.json";
    pub const POLICY_PROTOCOL: &str = "brops.recorder-policy.v1";

    /// The flags whose values the ROOT-OWNED POLICY decides. Argv may repeat them; it may not differ.
    pub const PINNED_FLAGS: [&str; 6] =
        ["--store", "--launcher", "--executor", "--lease", "--cgroup", "--evidence-state"];
    /// The flags naming a per-run OUTPUT file. The caller picks the file name; the policy picks the
    /// directory, and the name has to resolve inside it.
    pub const OUTPUT_FLAGS: [&str; 3] = ["--out", "--containment-out", "--evidence-out"];

    /// The subset of `stat(2)` every custody decision below needs.
    ///
    /// Gathered by the Linux half from `fstat` on the descriptor it is about to *use* (so the bytes checked
    /// are the bytes used) or `lstat` for directories (so a symlinked ancestor shows up as "not a
    /// directory" instead of being silently followed), then handed in here.
    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub struct FileFacts {
        pub uid: u32,
        /// Permission bits only (`st_mode & 0o7777`), setuid/setgid/sticky included.
        pub mode: u32,
        pub is_dir: bool,
        pub is_regular: bool,
    }

    #[cfg(test)]
    impl FileFacts {
        pub fn file(uid: u32, mode: u32) -> Self {
            FileFacts { uid, mode, is_dir: false, is_regular: true }
        }
        pub fn dir(uid: u32, mode: u32) -> Self {
            FileFacts { uid, mode, is_dir: true, is_regular: false }
        }
    }

    /// TCB custody: root owns it and NO other principal can write it.
    ///
    /// This is the same rule the §2.5 floor applies to a pinned artifact, restated here because the
    /// recorder must be able to decide it on its own — it runs long after the floor did, on the recorder
    /// uid, and "the floor passed at start-up" is not a statement about this file right now.
    pub fn tcb_custody(what: &str, f: &FileFacts) -> Result<(), String> {
        if f.uid != 0 {
            return Err(format!("{what} is not root-owned (uid={})", f.uid));
        }
        if f.mode & 0o022 != 0 {
            return Err(format!("{what} is group/other-writable (mode={:04o})", f.mode));
        }
        Ok(())
    }

    /// Every directory that has to be crossed to reach `path`, root-first.
    ///
    /// A writable ancestor is a rename/replace vector, so it is treated exactly like a writable artifact.
    pub fn ancestor_dirs(path: &str) -> Vec<String> {
        let mut out = vec!["/".to_string()];
        let components: Vec<&str> = path.split('/').filter(|c| !c.is_empty()).collect();
        let mut current = String::new();
        for c in components.iter().take(components.len().saturating_sub(1)) {
            current.push('/');
            current.push_str(c);
            out.push(current.clone());
        }
        out
    }

    /// Confirm the caller measured EXACTLY the ancestors of `path`, and that each is a TCB-owned directory.
    pub fn check_ancestors(path: &str, measured: &[(String, FileFacts)]) -> Result<(), String> {
        let want = ancestor_dirs(path);
        if measured.len() != want.len() {
            return Err(format!(
                "policy ancestry: measured {} of {} directories on the way to {path}",
                measured.len(),
                want.len()
            ));
        }
        for (expected, (got, facts)) in want.iter().zip(measured.iter()) {
            if got != expected {
                return Err(format!("policy ancestry: measured {got}, expected {expected}"));
            }
            if !facts.is_dir {
                return Err(format!("policy ancestor {got} is not a directory"));
            }
            tcb_custody(&format!("policy ancestor {got}"), facts)?;
        }
        Ok(())
    }

    /// The root-owned steering document.
    #[derive(Clone, Debug, PartialEq, Eq)]
    pub struct Policy {
        /// The uid this helper is required to be running as. A recorder that is not the recorder has no
        /// business writing the directory the supervisor treats as authoritative.
        pub recorder_uid: u32,
        pub store_dir: String,
        pub launcher_path: String,
        pub launcher_sha256: String,
        pub executor_path: String,
        pub executor_sha256: String,
        pub lease_path: String,
        pub cgroup: String,
        pub report_dir: String,
        pub evidence_state_dir: String,
    }

    fn field<'a>(v: &'a serde_json::Value, k: &str) -> Result<&'a serde_json::Value, String> {
        v.get(k).ok_or_else(|| format!("recorder policy: missing field `{k}`"))
    }

    fn text(v: &serde_json::Value, k: &str) -> Result<String, String> {
        field(v, k)?
            .as_str()
            .map(str::to_string)
            .ok_or_else(|| format!("recorder policy: `{k}` must be a string"))
    }

    /// An absolute, already-normalised path with no traversal and no trailing slash — so the string
    /// comparisons the rest of this module makes are exact rather than approximate.
    fn abs_path(v: &serde_json::Value, k: &str) -> Result<String, String> {
        let p = text(v, k)?;
        let bad = !p.starts_with('/')
            || p.contains('\0')
            || p.contains("//")
            || p.split('/').any(|c| c == ".." || c == ".")
            || (p.len() > 1 && p.ends_with('/'));
        if bad {
            return Err(format!("recorder policy: `{k}` must be an absolute normalised path, got {p:?}"));
        }
        Ok(p)
    }

    fn sha256_hex_field(v: &serde_json::Value, k: &str) -> Result<String, String> {
        let h = text(v, k)?;
        if h.len() != 64 || !h.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
            return Err(format!("recorder policy: `{k}` must be a 64-char lowercase sha256 hex"));
        }
        Ok(h)
    }

    pub fn parse_policy(bytes: &[u8]) -> Result<Policy, String> {
        let v: serde_json::Value =
            serde_json::from_slice(bytes).map_err(|e| format!("recorder policy: not JSON ({e})"))?;
        let protocol = text(&v, "protocol")?;
        if protocol != POLICY_PROTOCOL {
            return Err(format!("recorder policy: protocol {protocol:?} is not {POLICY_PROTOCOL:?}"));
        }
        let recorder_uid = field(&v, "recorder_uid")?
            .as_u64()
            .filter(|n| *n <= u32::MAX as u64)
            .ok_or_else(|| "recorder policy: `recorder_uid` must be a uid".to_string())?
            as u32;
        if recorder_uid == 0 {
            // A policy naming root would make the whole privilege-separation argument circular: the point
            // of the recorder identity is that it is NOT root and NOT the broker.
            return Err("recorder policy: `recorder_uid` must not be root".to_string());
        }
        let cgroup = text(&v, "cgroup")?;
        if cgroup.is_empty() || cgroup.contains('\0') {
            return Err("recorder policy: `cgroup` must be a non-empty token".to_string());
        }
        Ok(Policy {
            recorder_uid,
            store_dir: abs_path(&v, "store_dir")?,
            launcher_path: abs_path(&v, "launcher_path")?,
            launcher_sha256: sha256_hex_field(&v, "launcher_sha256")?,
            executor_path: abs_path(&v, "executor_path")?,
            executor_sha256: sha256_hex_field(&v, "executor_sha256")?,
            lease_path: abs_path(&v, "lease_path")?,
            cgroup,
            report_dir: abs_path(&v, "report_dir")?,
            evidence_state_dir: abs_path(&v, "evidence_state_dir")?,
        })
    }

    /// A strict `--flag value` parse of everything after `argv[0]`.
    ///
    /// Unknown flags, repeated flags, bare positionals and a dangling flag are all refused rather than
    /// ignored: "the argument I did not understand" is exactly the crack an argument-parsing trick lives
    /// in, and the sudoers vector that fronts this binary is written against this same fixed set.
    pub fn parse_args(args: &[String]) -> Result<BTreeMap<String, String>, String> {
        let mut out: BTreeMap<String, String> = BTreeMap::new();
        let mut i = 1;
        while i < args.len() {
            let flag = args[i].as_str();
            if !PINNED_FLAGS.contains(&flag) && !OUTPUT_FLAGS.contains(&flag) {
                return Err(format!("recorder: unrecognised argument {flag:?}"));
            }
            let value = match args.get(i + 1) {
                Some(v) => v.clone(),
                None => return Err(format!("recorder: {flag} has no value")),
            };
            if out.insert(flag.to_string(), value).is_some() {
                return Err(format!("recorder: {flag} given more than once"));
            }
            i += 2;
        }
        Ok(out)
    }

    /// `candidate` must be a plain file sitting directly in `dir`.
    ///
    /// Purely lexical and deliberately narrow. The sudoers wildcard that also guards these arguments
    /// matches `/` (sudo does not apply `FNM_PATHNAME` to command arguments), so `…/report/*` there would
    /// happily match `…/report/../../etc/x` — this is the wall that does not have that hole.
    /// (Verified against `fnmatch`: that traversal really does satisfy the sudoers pattern.)
    ///
    /// Deliberately ONE rule rather than a list of forbidden shapes: the candidate's lexical parent must
    /// equal the policy's directory character for character. Every escape — a relative path, a `..` walk,
    /// a doubled slash, a nested subdirectory — then falls out of that single comparison instead of each
    /// needing its own special case. A redundant special case is worse than none: it looks like a wall,
    /// and deleting it breaks no test.
    pub fn contained_in(dir: &str, candidate: &str) -> Result<(), String> {
        let (parent, name) = candidate
            .rsplit_once('/')
            .ok_or_else(|| format!("{candidate:?} has no parent directory"))?;
        if parent != dir {
            return Err(format!("{candidate:?} is not directly inside {dir}"));
        }
        if name.is_empty() || name.starts_with('.') {
            return Err(format!("{candidate:?} does not name a plain file"));
        }
        if !name.bytes().all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'-' | b'_')) {
            return Err(format!("{candidate:?} has a file name outside [A-Za-z0-9._-]"));
        }
        Ok(())
    }

    /// Everything this run will do, decided by the policy — not by argv.
    #[derive(Clone, Debug, PartialEq, Eq)]
    pub struct Plan {
        pub store: String,
        pub launcher: String,
        pub launcher_sha256: String,
        pub executor: String,
        pub executor_sha256: String,
        pub lease: String,
        pub cgroup: String,
        pub evidence_state: String,
        pub out: Option<String>,
        pub containment_out: Option<String>,
        pub evidence_out: Option<String>,
    }

    /// Reconcile argv against the root-owned policy.
    ///
    /// A pinned flag that argv sets to something else is refused OUTRIGHT. Silently preferring the policy
    /// would be safe too, but a caller trying to steer the trusted identity is a security event, not a
    /// typo, and a refusal is the only response that says so.
    pub fn plan(policy: &Policy, args: &[String], euid: u32) -> Result<Plan, String> {
        if euid != policy.recorder_uid {
            return Err(format!(
                "recorder: running as uid {euid}, but the root-owned policy pins the recorder uid to {}",
                policy.recorder_uid
            ));
        }
        let given = parse_args(args)?;
        let pinned = [
            ("--store", &policy.store_dir),
            ("--launcher", &policy.launcher_path),
            ("--executor", &policy.executor_path),
            ("--lease", &policy.lease_path),
            ("--cgroup", &policy.cgroup),
            ("--evidence-state", &policy.evidence_state_dir),
        ];
        for (flag, want) in pinned {
            if let Some(got) = given.get(flag) {
                if got.as_str() != want.as_str() {
                    return Err(format!(
                        "recorder: argv {flag} names {got:?}, but the root-owned policy pins {want:?} \
                         — argv does not steer the recorder"
                    ));
                }
            }
        }
        let in_dir = |flag: &str, dir: &str| -> Result<Option<String>, String> {
            match given.get(flag) {
                None => Ok(None),
                Some(p) => contained_in(dir, p)
                    .map(|()| Some(p.clone()))
                    .map_err(|e| format!("recorder: {flag} {e}")),
            }
        };
        Ok(Plan {
            store: policy.store_dir.clone(),
            launcher: policy.launcher_path.clone(),
            launcher_sha256: policy.launcher_sha256.clone(),
            executor: policy.executor_path.clone(),
            executor_sha256: policy.executor_sha256.clone(),
            lease: policy.lease_path.clone(),
            cgroup: policy.cgroup.clone(),
            evidence_state: policy.evidence_state_dir.clone(),
            out: in_dir("--out", &policy.report_dir)?,
            containment_out: in_dir("--containment-out", &policy.report_dir)?,
            evidence_out: in_dir("--evidence-out", &policy.evidence_state_dir)?,
        })
    }

    /// The image about to be run really is the TCB-owned, root-pinned one.
    ///
    /// The path already came from the policy, so this is the second wall rather than the first: it means a
    /// swapped or rebuilt binary at the pinned path is refused too, and it is the check that makes a
    /// broker-named binary impossible to reach even if the path plumbing were ever loosened again.
    pub fn check_image(
        what: &str,
        facts: &FileFacts,
        actual_sha256: &str,
        pinned_sha256: &str,
        require_setuid: bool,
    ) -> Result<(), String> {
        if !facts.is_regular {
            return Err(format!("{what} is not a regular file"));
        }
        tcb_custody(what, facts)?;
        if require_setuid && facts.mode & 0o4000 == 0 {
            return Err(format!("{what} is not setuid (mode={:04o})", facts.mode));
        }
        if actual_sha256 != pinned_sha256 {
            return Err(format!(
                "{what} is sha256 {actual_sha256}, but the root-owned policy pins {pinned_sha256}"
            ));
        }
        Ok(())
    }

    /// The evidence head-sequence counter's directory must be RECORDER-PRIVATE.
    ///
    /// The head sequence is what makes the evidence head monotonic across runs, so it is the number the
    /// supervisor's anti-rollback floor compares against. `next_head_sequence` used to read-increment-write
    /// it with no check on who owns the directory at all — so any directory the caller could name, or any
    /// directory another principal could write, would have supplied the "monotonic" counter.
    pub fn check_state_dir(facts: &FileFacts, euid: u32) -> Result<(), String> {
        if !facts.is_dir {
            return Err("evidence state: not a directory".to_string());
        }
        if facts.uid != euid {
            return Err(format!(
                "evidence state directory is owned by uid {}, not by the recorder uid {euid}",
                facts.uid
            ));
        }
        if facts.mode & 0o022 != 0 {
            return Err(format!(
                "evidence state directory is group/other-writable (mode={:04o}) — another principal \
                 could rewind the head sequence",
                facts.mode
            ));
        }
        Ok(())
    }

    /// Same rule for the counter FILE: recorder-owned, writable by nobody else.
    pub fn check_counter_file(facts: &FileFacts, euid: u32) -> Result<(), String> {
        if !facts.is_regular {
            return Err("evidence head-sequence counter is not a regular file".to_string());
        }
        if facts.uid != euid {
            return Err(format!(
                "evidence head-sequence counter is owned by uid {}, not by the recorder uid {euid}",
                facts.uid
            ));
        }
        if facts.mode & 0o022 != 0 {
            return Err(format!(
                "evidence head-sequence counter is group/other-writable (mode={:04o})",
                facts.mode
            ));
        }
        Ok(())
    }
}

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("governed_recorder: platform unsupported (Linux-only setuid/inherited-fd model)");
    std::process::exit(2);
}

#[cfg(target_os = "linux")]
fn main() {
    std::process::exit(linux::recorder(&std::env::args().collect::<Vec<_>>()));
}

#[cfg(target_os = "linux")]
mod linux {
    use crate::guard::{self, FileFacts, Plan, Policy};
    use std::ffi::CString;
    use std::io::{Read, Write};
    use std::os::fd::FromRawFd;

    fn err(msg: &str) -> i32 {
        eprintln!("governed_recorder: {msg}");
        println!("RESULT: error {msg}");
        1
    }

    fn facts_from_stat(st: &libc::stat) -> FileFacts {
        FileFacts {
            uid: st.st_uid,
            mode: st.st_mode & 0o7777,
            is_dir: st.st_mode & libc::S_IFMT == libc::S_IFDIR,
            is_regular: st.st_mode & libc::S_IFMT == libc::S_IFREG,
        }
    }

    fn fstat_facts(fd: i32) -> Option<FileFacts> {
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::fstat(fd, &mut st) } != 0 {
            return None;
        }
        Some(facts_from_stat(&st))
    }

    /// `lstat`, not `stat`: a symlinked ancestor must surface as "not a directory" rather than being
    /// followed to wherever the caller pointed it.
    fn lstat_facts(path: &str) -> Option<FileFacts> {
        let c = CString::new(path).ok()?;
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::lstat(c.as_ptr(), &mut st) } != 0 {
            return None;
        }
        Some(facts_from_stat(&st))
    }

    /// Open, `fstat` and read a file through ONE descriptor, refusing a symlink at the final component.
    /// The facts returned describe the very bytes returned beside them — no second lookup to race.
    fn read_measured(path: &str) -> Result<(FileFacts, Vec<u8>), String> {
        let c = CString::new(path).map_err(|_| format!("{path:?} contains a NUL byte"))?;
        let fd = unsafe { libc::open(c.as_ptr(), libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_CLOEXEC) };
        if fd < 0 {
            return Err(format!("cannot open {path}: {}", std::io::Error::last_os_error()));
        }
        let mut file = unsafe { std::fs::File::from_raw_fd(fd) };
        let facts = fstat_facts(fd).ok_or_else(|| format!("cannot fstat {path}"))?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes).map_err(|e| format!("cannot read {path}: {e}"))?;
        Ok((facts, bytes))
    }

    /// Create/truncate and write a file, refusing to follow a symlink at the final component.
    ///
    /// `--out` and `--containment-out` land in a directory the BROKER shares (it reads the reply there), so
    /// a symlink planted at the caller-chosen name would otherwise have the recorder write the executor's
    /// bytes through it. `O_NOFOLLOW` is the fix; `fchmod` states the mode regardless of umask.
    fn write_measured(path: &str, bytes: &[u8], mode: u32) -> Result<(), String> {
        let c = CString::new(path).map_err(|_| format!("{path:?} contains a NUL byte"))?;
        let fd = unsafe {
            libc::open(
                c.as_ptr(),
                libc::O_WRONLY | libc::O_CREAT | libc::O_TRUNC | libc::O_NOFOLLOW | libc::O_CLOEXEC,
                mode as libc::c_uint,
            )
        };
        if fd < 0 {
            return Err(format!("cannot open {path} for writing: {}", std::io::Error::last_os_error()));
        }
        let mut file = unsafe { std::fs::File::from_raw_fd(fd) };
        file.write_all(bytes).map_err(|e| format!("cannot write {path}: {e}"))?;
        file.flush().map_err(|e| format!("cannot flush {path}: {e}"))?;
        if unsafe { libc::fchmod(fd, mode as libc::mode_t) } != 0 {
            return Err(format!("cannot set the mode of {path}"));
        }
        Ok(())
    }

    /// Load the ROOT-OWNED policy from the compile-time path, refusing anything whose custody is not
    /// root's — including a writable directory anywhere on the way to it.
    fn load_policy() -> Result<Policy, String> {
        let path = guard::POLICY_PATH;
        let mut measured = Vec::new();
        for dir in guard::ancestor_dirs(path) {
            let facts =
                lstat_facts(&dir).ok_or_else(|| format!("cannot stat policy ancestor {dir}"))?;
            measured.push((dir, facts));
        }
        guard::check_ancestors(path, &measured)?;
        let (facts, bytes) = read_measured(path)?;
        if !facts.is_regular {
            return Err(format!("recorder policy {path} is not a regular file"));
        }
        guard::tcb_custody(&format!("recorder policy {path}"), &facts)?;
        guard::parse_policy(&bytes)
    }

    /// Re-hash the image at a policy-pinned path and compare it to the policy's digest.
    fn verify_image(what: &str, path: &str, pinned: &str, require_setuid: bool) -> Result<(), String> {
        let (facts, bytes) = read_measured(path)?;
        let actual = brops_core::governed_message_store::sha256_hex(&bytes);
        guard::check_image(&format!("{what} {path}"), &facts, &actual, pinned, require_setuid)
    }

    /// Read-increment-write the recorder's durable head-sequence counter (audit F-02).
    ///
    /// The supervisor's evidence floor refuses a head at or below the one it already recorded, so this
    /// number has to grow across RUNS — an in-run constant would make every turn of a deployment claim
    /// the same head, which is exactly the defect being removed. A missing counter starts at 1; a
    /// damaged one is an error (⇒ the caller refuses) rather than a silent restart, because restarting
    /// is indistinguishable from a rollback. Written through a temp file and renamed so a crash cannot
    /// leave a truncated counter behind.
    ///
    /// (round-3 P0, second half) The directory and the counter file are checked to be RECORDER-PRIVATE
    /// first. Without that, this function incremented whatever it was pointed at, in a directory anyone
    /// might have been able to write — which would have made "monotonic" a claim about a number the
    /// attacker chose. The directory is never created here either: a missing state directory is a
    /// provisioning failure, and creating one would hand it default ownership and defeat the check.
    fn next_head_sequence(dir: &str, euid: u32) -> Result<u64, String> {
        let dir_facts = lstat_facts(dir)
            .ok_or_else(|| format!("cannot stat the evidence state directory {dir}"))?;
        guard::check_state_dir(&dir_facts, euid)?;

        let path = std::path::Path::new(dir).join("evidence-head-sequence.json");
        let path_str = path.to_str().ok_or("evidence counter path is not UTF-8")?.to_string();
        let current: u64 = match read_measured(&path_str) {
            Ok((facts, raw)) => {
                guard::check_counter_file(&facts, euid)?;
                serde_json::from_slice::<serde_json::Value>(&raw)
                    .ok()
                    .and_then(|v| v.get("head_sequence").and_then(serde_json::Value::as_u64))
                    .ok_or_else(|| format!("the evidence head-sequence counter at {path_str} is damaged"))?
            }
            Err(_) if !path.exists() => 0,
            Err(e) => return Err(e),
        };
        let next = current.checked_add(1).ok_or("the evidence head sequence overflowed")?;
        let temporary = format!("{path_str}.tmp");
        write_measured(&temporary, serde_json::json!({"head_sequence": next}).to_string().as_bytes(), 0o600)?;
        std::fs::rename(&temporary, &path)
            .map_err(|e| format!("cannot install the evidence head-sequence counter: {e}"))?;
        Ok(next)
    }

    pub fn recorder(args: &[String]) -> i32 {
        // ---- (0) custody FIRST: what this process will do is decided by root, not by the caller ----
        let policy = match load_policy() {
            Ok(p) => p,
            Err(e) => return err(&e),
        };
        let euid = unsafe { libc::geteuid() };
        let plan: Plan = match guard::plan(&policy, args, euid) {
            Ok(p) => p,
            Err(e) => return err(&e),
        };
        // The two images this chain is about to run, re-hashed against the root-owned pin immediately
        // before the exec. `--launcher` used to be whatever the caller typed and was `execve`d unchecked.
        if let Err(e) = verify_image("launcher", &plan.launcher, &plan.launcher_sha256, true) {
            return err(&e);
        }
        if let Err(e) = verify_image("executor", &plan.executor, &plan.executor_sha256, false) {
            return err(&e);
        }
        // The lease is the launcher's §4.3 configuration (invoker uid, drop-target uids, the executor
        // image pin and the three request digests). It carries no digest of its own in the policy — root
        // rewrites it every provisioning — so what is asserted is its custody.
        match read_measured(&plan.lease) {
            Ok((facts, _)) => {
                if let Err(e) = guard::tcb_custody(&format!("lease {}", plan.lease), &facts) {
                    return err(&e);
                }
            }
            Err(e) => return err(&e),
        }

        let store = plan.store.clone();
        let out_path = plan.out.clone();
        // Where to write the CONTAINMENT REPORT for this run (audit F-02). Optional so the flag can
        // be added without breaking an older caller, but the broker always passes it and refuses the
        // turn if the file does not appear — so its absence is never silently tolerated.
        let containment_out = plan.containment_out.clone();
        // Where to write the per-run EVIDENCE CHAIN + its head (audit F-02, second half). The four
        // `evidence_*` values the supervisor's terminal record carries — final_event_hash, event_count,
        // last_sequence, head_sequence — were deployment constants the provisioner wrote once, so every
        // receipt of the deployment claimed the same evidence head and the anti-rollback floor compared
        // a constant against itself. They now come from a chain THIS process builds out of what it
        // actually observed.
        let evidence_out = plan.evidence_out.clone();
        // A recorder-owned directory holding the monotonic head-sequence counter, named by the policy —
        // never by argv, because a caller who picks the counter picks the "monotonic" number too.
        let evidence_state = plan.evidence_state.clone();

        // Keep plain copies for the containment report: the originals are moved into CStrings below.
        let launcher_for_report = plan.launcher.clone();
        let executor_for_report = plan.executor.clone();
        let lease_for_report = plan.lease.clone();
        let cgroup_for_report = plan.cgroup.clone();

        // Pre-build every C string + open the store inputs BEFORE fork (only async-signal-safe libc runs
        // between fork and execve).
        let c_launcher = CString::new(plan.launcher.clone()).unwrap();
        let c_arg0 = CString::new(plan.launcher).unwrap();
        let c_lease = CString::new(plan.lease).unwrap();
        let c_exec = CString::new(plan.executor).unwrap();
        let c_cgroup = CString::new(plan.cgroup).unwrap();

        // `O_NOFOLLOW`: the store directory is shared with the broker (it publishes content-addressed
        // blobs there), so the three named inputs must not be reachable through a symlink the broker
        // planted. Their CONTENT is separately pinned by the §4.3 lease and re-hashed by the launcher
        // (F-08); this closes the other half.
        let open_ro = |p: &str| -> i32 {
            let c = CString::new(format!("{store}/{p}")).unwrap();
            unsafe { libc::open(c.as_ptr(), libc::O_RDONLY | libc::O_NOFOLLOW) }
        };
        let sys = open_ro("system");
        let hist = open_ro("history");
        let genc = open_ro("generation_config");
        if sys < 0 || hist < 0 || genc < 0 {
            return err("recorder: cannot open store inputs");
        }
        let devnull = CString::new("/dev/null").unwrap();
        let dnr = unsafe { libc::open(devnull.as_ptr(), libc::O_RDONLY) };
        let dnw = unsafe { libc::open(devnull.as_ptr(), libc::O_WRONLY) };

        // Output pipe: child writes fd 6, parent reads.
        let mut pipefd = [0i32; 2];
        if unsafe { libc::pipe(pipefd.as_mut_ptr()) } != 0 {
            return err("recorder: pipe() failed");
        }
        let (rfd, wfd) = (pipefd[0], pipefd[1]);

        let pid = unsafe { libc::fork() };
        if pid < 0 {
            return err("recorder: fork() failed");
        }
        if pid == 0 {
            // ---- child: build the exact §2.7 descriptor table, then execve(launcher) ----
            // Move every source to a guaranteed-high fd first so a target never clobbers a still-needed
            // source.
            let dup_high = |fd: i32, min: i32| -> i32 { unsafe { libc::fcntl(fd, libc::F_DUPFD, min) } };
            let hi_dnr = dup_high(dnr, 20);
            let hi_dnw = dup_high(dnw, 21);
            let hi_sys = dup_high(sys, 23);
            let hi_hist = dup_high(hist, 24);
            let hi_genc = dup_high(genc, 25);
            let hi_out = dup_high(wfd, 26);
            // Map onto the exact contract numbers: 0=/dev/null RO, 1/2=/dev/null WO, 3/4/5=inputs, 6=output.
            let map = [
                (hi_dnr, 0),
                (hi_dnw, 1),
                (hi_dnw, 2),
                (hi_sys, 3),
                (hi_hist, 4),
                (hi_genc, 5),
                (hi_out, 6),
            ];
            for (src, dst) in map {
                if src < 0 || unsafe { libc::dup2(src, dst) } != dst {
                    unsafe { libc::_exit(120) };
                }
            }
            // Clear FD_CLOEXEC on 0..=6 so they cross execve(launcher) (the launcher re-sets it on 0/1/2).
            for fd in 0..=6i32 {
                let fl = unsafe { libc::fcntl(fd, libc::F_GETFD) };
                if fl < 0 || unsafe { libc::fcntl(fd, libc::F_SETFD, fl & !libc::FD_CLOEXEC) } < 0 {
                    unsafe { libc::_exit(121) };
                }
            }
            // Close every descriptor >= 7 (the high temporaries, rfd, the originals) so nothing extra
            // survives.
            unsafe {
                libc::close_range(7, u32::MAX, 0);
            }
            // execve with the fixed closed argv and a fully EMPTY environment.
            let argv =
                [c_arg0.as_ptr(), c_lease.as_ptr(), c_exec.as_ptr(), c_cgroup.as_ptr(), std::ptr::null()];
            let envp = [std::ptr::null()];
            unsafe {
                libc::execve(c_launcher.as_ptr(), argv.as_ptr(), envp.as_ptr());
                // execve only returns on failure — surface the errno on the report pipe (fd 6) so the parent
                // sees WHY the setuid launcher could not be exec'd (single-threaded child ⇒ format! is safe).
                let msg = format!("EXECVE_FAIL errno={}", std::io::Error::last_os_error());
                libc::write(6, msg.as_ptr() as *const libc::c_void, msg.len());
                libc::_exit(127);
            }
        }

        // ---- parent: read the executor's fd-6 report, reap the child ----
        unsafe {
            libc::close(wfd);
            libc::close(sys);
            libc::close(hist);
            libc::close(genc);
            libc::close(dnr);
            libc::close(dnw);
        }
        let mut report = Vec::new();
        {
            // SAFETY: rfd is the read end of our own pipe; the File takes ownership + closes on drop.
            let mut f = unsafe { std::fs::File::from_raw_fd(rfd) };
            let _ = f.read_to_end(&mut report);
        }
        let mut status: i32 = 0;
        unsafe {
            libc::waitpid(pid, &mut status, 0);
        }
        let exit_code = if libc::WIFEXITED(status) { libc::WEXITSTATUS(status) } else { -1 };

        // Fail closed: an EXECVE_FAIL report (the launcher refused) is NOT governed output. Never write it as
        // the turn's output — leave --out empty so the broker's `std::fs::read` sees no bytes and blocks.
        let is_execve_fail = report.starts_with(b"EXECVE_FAIL");
        let produced = exit_code == 0 && !is_execve_fail && !report.is_empty();
        if let Some(p) = out_path {
            if produced {
                // The broker (a DIFFERENT uid) reads this report to content-address the output; 0644 so it
                // can, regardless of the recorder's umask.
                if let Err(e) = write_measured(&p, &report, 0o644) {
                    return err(&e);
                }
            } else {
                // Truncate/remove any stale file so the broker cannot mistake old bytes for this run.
                let _ = std::fs::remove_file(&p);
            }
        }
        // ---- containment evidence for THIS run (audit F-02) ----
        //
        // `containment_evidence_handle` used to address a provisioner stub — literal placeholder JSON
        // written once, whose content address every receipt of the deployment then named. The isolated
        // signer refuses to mint an envelope when the containment handle does not resolve (§1.5), so
        // that gate proved only that the stub existed.
        //
        // These are facts THIS process observed. The launcher's own verdicts (the §2.7 FD contract, the
        // privilege-drop order, the post-drop capability state, and the executor image integrity vs the
        // lease pin) are attested here by their CONSEQUENCE: any one of them failing means no `fexecve`
        // and a non-zero exit, so `launcher_exit == 0` is the observable form of "the gate passed". The
        // launcher cannot report them directly without a 4th argv token or a 7th descriptor, and both
        // are fixed by the rev-30 §2.7 closed-argv / FD contract — changing that is an Architect
        // decision, so this report states what it saw and does not overclaim.
        if let Some(cp) = containment_out.as_deref() {
            if produced {
                let sha = |p: &str| -> String {
                    std::fs::read(p)
                        .map(|b| brops_core::governed_message_store::sha256_hex(&b))
                        .unwrap_or_default()
                };
                let (ruid, rgid) = unsafe { (libc::getuid(), libc::getgid()) };
                // Sorted keys + compact separators: the bytes are content-addressed, so the encoding
                // must be deterministic for the same facts.
                let doc = serde_json::json!({
                    "protocol": "brops.containment-evidence.v1",
                    "cgroup": cgroup_for_report,
                    "executor_path": executor_for_report,
                    "executor_sha256": sha(&executor_for_report),
                    "fd_contract": "0=/dev/null:ro,1=/dev/null:wo,2=/dev/null:wo,3=system:ro,4=history:ro,5=generation_config:ro,6=output:wo",
                    "invoker_gid": rgid,
                    "invoker_uid": ruid,
                    "launcher_exit": exit_code,
                    "launcher_gate": "passed",
                    "launcher_path": launcher_for_report,
                    "launcher_sha256": sha(&launcher_for_report),
                    "lease_path": lease_for_report,
                    "lease_sha256": sha(&lease_for_report),
                    "output_bytes": report.len(),
                });
                // serde_json's Map is a BTreeMap by default: `to_vec` emits sorted keys with compact
                // separators, so identical facts always content-address identically.
                let bytes = match serde_json::to_vec(&doc) {
                    Ok(b) => b,
                    Err(_) => return err("recorder: cannot encode containment report"),
                };
                if let Err(e) = write_measured(cp, &bytes, 0o644) {
                    return err(&e);
                }
            } else {
                // A refused/empty run has no containment to evidence. Remove any stale file so the
                // broker cannot address a previous run's report for this one.
                let _ = std::fs::remove_file(cp);
            }
        }

        // ---- the per-run EVIDENCE CHAIN (audit F-02, second half) ----
        //
        // Three hash-linked events describing what this recorder actually did, then a head over them.
        // The link is `previous_event_hash`, so dropping or reordering an event changes every hash from
        // that point on and the head no longer matches — which is the property the four constants could
        // not have, since they described nothing.
        if let Some(ep) = evidence_out.as_deref() {
            if produced {
                let sha = |p: &str| -> String {
                    std::fs::read(p)
                        .map(|b| brops_core::governed_message_store::sha256_hex(&b))
                        .unwrap_or_default()
                };
                let head_sequence = match next_head_sequence(&evidence_state, euid) {
                    Ok(n) => n,
                    Err(e) => return err(&e),
                };
                let mut previous: Option<String> = None;
                let mut events = Vec::new();
                for (sequence, event_type, payload) in [
                    (1u64, "lease-validated", serde_json::json!({
                        "lease_path": lease_for_report, "lease_sha256": sha(&lease_for_report),
                    })),
                    (2, "execution-launched", serde_json::json!({
                        "cgroup": cgroup_for_report,
                        "executor_path": executor_for_report,
                        "executor_sha256": sha(&executor_for_report),
                        "launcher_path": launcher_for_report,
                        "launcher_sha256": sha(&launcher_for_report),
                    })),
                    (3, "output-captured", serde_json::json!({
                        "launcher_exit": exit_code,
                        "output_bytes": report.len(),
                        "output_sha256": brops_core::governed_message_store::sha256_hex(&report),
                    })),
                ] {
                    let payload_bytes = match serde_json::to_vec(&payload) {
                        Ok(b) => b,
                        Err(_) => return err("recorder: cannot encode an evidence event"),
                    };
                    let event = serde_json::json!({
                        "event_type": event_type,
                        // The PAYLOAD travels with the event, not just its digest. The supervisor
                        // reads this chain to derive the evidence head AND to check that the reply
                        // digest the completion reports is the one this recorder captured (audit
                        // F-01); it cannot check a digest whose bytes it never sees.
                        "payload": payload,
                        "payload_sha256": brops_core::governed_message_store::sha256_hex(&payload_bytes),
                        "previous_event_hash": previous,
                        "sequence": sequence,
                    });
                    let event_bytes = match serde_json::to_vec(&event) {
                        Ok(b) => b,
                        Err(_) => return err("recorder: cannot encode an evidence event"),
                    };
                    previous = Some(brops_core::governed_message_store::sha256_hex(&event_bytes));
                    events.push(event);
                }
                let final_event_hash = match previous {
                    Some(h) => h,
                    None => return err("recorder: empty evidence chain"),
                };
                let doc = serde_json::json!({
                    "event_count": events.len(),
                    "events": events,
                    "final_event_hash": final_event_hash,
                    "head_sequence": head_sequence,
                    "last_sequence": events.len(),
                    "protocol": "brops.run-evidence-chain.v1",
                });
                let bytes = match serde_json::to_vec(&doc) {
                    Ok(b) => b,
                    Err(_) => return err("recorder: cannot encode the evidence chain"),
                };
                if let Err(e) = write_measured(ep, &bytes, 0o644) {
                    return err(&e);
                }
            } else {
                // A refused run evidences nothing. Remove any stale chain so the broker cannot address a
                // previous run's evidence as this one's.
                let _ = std::fs::remove_file(ep);
            }
        }

        let report_str = String::from_utf8_lossy(&report);
        println!("EXECUTOR_REPORT: {report_str}");
        println!("RESULT: recorder launcher_exit={exit_code} report_bytes={}", report.len());
        if produced {
            0
        } else {
            1
        }
    }
}

// -------------------------------------------------------------------------------------------------
// Tests for the decisions that keep argv from steering the trusted identity.
//
// This binary had ZERO tests, which is why an argv-steered `execve` survived several audit rounds. Each
// test below goes RED if the check it names is deleted — they assert refusals, not that a parser parses.
// The syscall wiring that CALLS these decisions is exercised on a real Linux runner by the three
// `NEGATIVE:` cases at the end of `engine/ci/live/run_live_turn.sh`, which is the only place a setuid
// launcher, real service uids and a sudoers rule exist.
// -------------------------------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::guard::*;

    const RECORDER_UID: u32 = 5005;
    // 64-char lowercase sha256 hex, with letters in them so the "uppercase is not lowercase hex" case
    // below is a real case rather than a no-op.
    const LAUNCHER_SHA: &str = "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
    const EXECUTOR_SHA: &str = "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2";

    #[test]
    fn the_test_digests_are_shaped_like_real_ones() {
        for h in [LAUNCHER_SHA, EXECUTOR_SHA] {
            assert_eq!(h.len(), 64);
            assert!(h.chars().any(|c| c.is_ascii_alphabetic()), "{h} has no letters to upper-case");
        }
    }

    /// The exact document `run_live_turn.sh` provisions, as a mutable value so a test can break one
    /// field at a time.
    fn policy_value() -> serde_json::Value {
        serde_json::json!({
            "protocol": "brops.recorder-policy.v1",
            "recorder_uid": RECORDER_UID,
            "store_dir": "/opt/brops-live/store",
            "launcher_path": "/opt/brops-live/tcb/privileged-launcher.bin",
            "launcher_sha256": LAUNCHER_SHA,
            "executor_path": "/opt/brops-live/tcb/contained-executor.bin",
            "executor_sha256": EXECUTOR_SHA,
            "lease_path": "/opt/brops-live/tcb/executor.lease",
            "cgroup": "cgroup-live",
            "report_dir": "/opt/brops-live/report",
            "evidence_state_dir": "/opt/brops-live/recorder-state"
        })
    }

    fn policy() -> Policy {
        parse_policy(policy_value().to_string().as_bytes()).expect("the reference policy must parse")
    }

    /// `policy_value()` with one field replaced (or, with `serde_json::Value::Null`, removed).
    fn policy_with(field: &str, value: serde_json::Value) -> Vec<u8> {
        let mut v = policy_value();
        let map = v.as_object_mut().unwrap();
        if value.is_null() {
            map.remove(field);
        } else {
            map.insert(field.to_string(), value);
        }
        v.to_string().into_bytes()
    }

    fn argv(pairs: &[(&str, &str)]) -> Vec<String> {
        let mut v = vec!["/opt/brops-live/bin/governed_recorder".to_string()];
        for (f, x) in pairs {
            v.push((*f).to_string());
            v.push((*x).to_string());
        }
        v
    }

    /// The exact argv the broker builds (`chain_executor.rs`), with per-run ids of the real shape.
    fn honest_argv() -> Vec<String> {
        argv(&[
            ("--store", "/opt/brops-live/store"),
            ("--launcher", "/opt/brops-live/tcb/privileged-launcher.bin"),
            ("--executor", "/opt/brops-live/tcb/contained-executor.bin"),
            ("--lease", "/opt/brops-live/tcb/executor.lease"),
            ("--cgroup", "cgroup-live"),
            ("--out", "/opt/brops-live/report/live-8b2f-9c1e.out"),
            ("--containment-out", "/opt/brops-live/report/live-8b2f-9c1e.out.containment.json"),
            ("--evidence-out", "/opt/brops-live/recorder-state/9c1e.evidence.json"),
            ("--evidence-state", "/opt/brops-live/recorder-state"),
        ])
    }

    // ---------------------------------------------------------------------------------------------
    // THE FINDING: a caller-named launcher/executor must be refused, and the effective values must
    // come from the policy even when argv omits them entirely.
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn broker_named_launcher_is_refused() {
        let mut a = honest_argv();
        let i = a.iter().position(|x| x == "--launcher").unwrap();
        a[i + 1] = "/tmp/attacker-launcher".to_string();
        let e = plan(&policy(), &a, RECORDER_UID).expect_err("a caller-named launcher must be refused");
        assert!(e.contains("--launcher"), "{e}");
        assert!(e.contains("argv does not steer the recorder"), "{e}");
    }

    #[test]
    fn broker_named_executor_is_refused() {
        let mut a = honest_argv();
        let i = a.iter().position(|x| x == "--executor").unwrap();
        a[i + 1] = "/tmp/attacker-executor".to_string();
        assert!(plan(&policy(), &a, RECORDER_UID).is_err(), "a caller-named executor must be refused");
    }

    #[test]
    fn broker_named_store_lease_cgroup_and_state_are_refused() {
        for (flag, hostile) in [
            ("--store", "/tmp/attacker-store"),
            ("--lease", "/tmp/attacker.lease"),
            ("--cgroup", "attacker-cgroup"),
            ("--evidence-state", "/tmp/attacker-state"),
        ] {
            let mut a = honest_argv();
            let i = a.iter().position(|x| x == flag).unwrap();
            a[i + 1] = hostile.to_string();
            let e = plan(&policy(), &a, RECORDER_UID)
                .expect_err(&format!("a caller-named {flag} must be refused"));
            assert!(e.contains(flag), "{flag}: {e}");
        }
    }

    #[test]
    fn the_plan_comes_from_the_policy_not_from_argv() {
        // argv carries ONLY the per-run output names; everything else is the policy's.
        let a = argv(&[
            ("--out", "/opt/brops-live/report/live-1.out"),
            ("--evidence-out", "/opt/brops-live/recorder-state/1.evidence.json"),
        ]);
        let p = plan(&policy(), &a, RECORDER_UID).expect("the policy alone must be sufficient");
        assert_eq!(p.launcher, "/opt/brops-live/tcb/privileged-launcher.bin");
        assert_eq!(p.executor, "/opt/brops-live/tcb/contained-executor.bin");
        assert_eq!(p.lease, "/opt/brops-live/tcb/executor.lease");
        assert_eq!(p.store, "/opt/brops-live/store");
        assert_eq!(p.cgroup, "cgroup-live");
        assert_eq!(p.evidence_state, "/opt/brops-live/recorder-state");
        assert_eq!(p.launcher_sha256, LAUNCHER_SHA);
        assert_eq!(p.executor_sha256, EXECUTOR_SHA);
    }

    #[test]
    fn the_honest_broker_spawn_is_accepted() {
        // The wall must not break the real caller: the exact argv `chain_executor.rs` builds passes.
        plan(&policy(), &honest_argv(), RECORDER_UID).expect("the broker's real spawn must still work");
    }

    #[test]
    fn a_recorder_that_is_not_the_recorder_refuses() {
        let broker_uid = 5001;
        let e = plan(&policy(), &honest_argv(), broker_uid)
            .expect_err("running as a uid the policy does not pin must be refused");
        assert!(e.contains("5005"), "{e}");
    }

    // ---------------------------------------------------------------------------------------------
    // Output containment: the caller picks a NAME, never a place.
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn evidence_out_cannot_escape_the_state_directory() {
        // This is the shape the sudoers wildcard alone would let through: sudo does not apply
        // FNM_PATHNAME to command arguments, so `…/recorder-state/*` there matches a `..` walk.
        for hostile in [
            "/opt/brops-live/recorder-state/../../etc/x.evidence.json",
            "/opt/brops-live/recorder-state/sub/x.evidence.json",
            "/tmp/x.evidence.json",
            "recorder-state/x.evidence.json",
            "/opt/brops-live/recorder-state//x.evidence.json",
            "/opt/brops-live/recorder-state/.hidden",
            "/opt/brops-live/recorder-state/",
        ] {
            let mut a = honest_argv();
            let i = a.iter().position(|x| x == "--evidence-out").unwrap();
            a[i + 1] = hostile.to_string();
            assert!(
                plan(&policy(), &a, RECORDER_UID).is_err(),
                "--evidence-out {hostile} must be refused"
            );
        }
    }

    #[test]
    fn out_and_containment_out_cannot_escape_the_report_directory() {
        for flag in ["--out", "--containment-out"] {
            for hostile in [
                "/opt/brops-live/tcb/executor.lease",
                "/opt/brops-live/report/../tcb/executor.lease",
                "/etc/passwd",
            ] {
                let mut a = honest_argv();
                let i = a.iter().position(|x| x == flag).unwrap();
                a[i + 1] = hostile.to_string();
                assert!(
                    plan(&policy(), &a, RECORDER_UID).is_err(),
                    "{flag} {hostile} must be refused"
                );
            }
        }
    }

    #[test]
    fn contained_in_accepts_only_a_plain_child() {
        assert!(contained_in("/d", "/d/name.json").is_ok());
        assert!(contained_in("/d", "name.json").is_err(), "no parent at all");
        assert!(contained_in("/d", "").is_err(), "empty");
        assert!(contained_in("/d", "/d/a/name.json").is_err());
        assert!(contained_in("/d", "/d/../d/name.json").is_err());
        assert!(contained_in("/d", "/d/./name.json").is_err());
        assert!(contained_in("/d", "/dd/name.json").is_err());
        assert!(contained_in("/d", "/d/na me.json").is_err());
        assert!(contained_in("/d", "/d/name;rm.json").is_err());
    }

    // ---------------------------------------------------------------------------------------------
    // Strict argv: no unknown flag, no repeat, no bare positional, no dangling value.
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn argv_tricks_are_refused() {
        let base = "/opt/brops-live/bin/governed_recorder".to_string();
        let cases: Vec<Vec<String>> = vec![
            // an unknown flag
            vec![base.clone(), "--policy".into(), "/tmp/p.json".into()],
            // a bare positional
            vec![base.clone(), "/tmp/attacker-launcher".into()],
            // a dangling flag with no value
            vec![base.clone(), "--launcher".into()],
            // the same flag twice — first-wins parsing is how a second value sneaks past a check
            vec![
                base.clone(),
                "--launcher".into(),
                "/opt/brops-live/tcb/privileged-launcher.bin".into(),
                "--launcher".into(),
                "/tmp/attacker-launcher".into(),
            ],
        ];
        for c in cases {
            assert!(parse_args(&c).is_err(), "argv {c:?} must be refused");
            assert!(plan(&policy(), &c, RECORDER_UID).is_err(), "argv {c:?} must be refused");
        }
    }

    // ---------------------------------------------------------------------------------------------
    // Policy custody: root owns it, root owns every directory on the way to it.
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn tcb_custody_refuses_a_non_root_or_writable_file() {
        assert!(tcb_custody("p", &FileFacts::file(0, 0o644)).is_ok());
        assert!(tcb_custody("p", &FileFacts::file(5001, 0o644)).is_err(), "non-root owner");
        assert!(tcb_custody("p", &FileFacts::file(0, 0o664)).is_err(), "group-writable");
        assert!(tcb_custody("p", &FileFacts::file(0, 0o646)).is_err(), "other-writable");
        assert!(tcb_custody("p", &FileFacts::file(0, 0o777)).is_err(), "world-writable");
    }

    #[test]
    fn ancestor_dirs_walks_the_whole_path() {
        assert_eq!(
            ancestor_dirs(POLICY_PATH),
            vec!["/", "/opt", "/opt/brops-live", "/opt/brops-live/tcb"]
        );
    }

    #[test]
    fn a_writable_ancestor_refuses_the_policy() {
        let good = || {
            ancestor_dirs(POLICY_PATH)
                .into_iter()
                .map(|d| (d, FileFacts::dir(0, 0o755)))
                .collect::<Vec<_>>()
        };
        assert!(check_ancestors(POLICY_PATH, &good()).is_ok());

        // /opt world-writable (the hosted runner's default) — a rename/replace vector for the whole tree.
        let mut m = good();
        m[1].1 = FileFacts::dir(0, 0o777);
        assert!(check_ancestors(POLICY_PATH, &m).is_err(), "a world-writable ancestor must refuse");

        // an ancestor owned by a service account
        let mut m = good();
        m[3].1 = FileFacts::dir(5005, 0o755);
        assert!(check_ancestors(POLICY_PATH, &m).is_err(), "a non-root ancestor must refuse");

        // A non-directory on the way to the policy — a regular file, or a symlink, standing where a
        // directory must be. Root-owned and 0644, so ONLY the "is a directory" rule can refuse it.
        let mut m = good();
        m[2].1 = FileFacts::file(0, 0o644);
        assert!(check_ancestors(POLICY_PATH, &m).is_err(), "a non-directory ancestor must refuse");

        // a caller that measured fewer directories than the path has
        let mut m = good();
        m.pop();
        assert!(check_ancestors(POLICY_PATH, &m).is_err(), "an unmeasured ancestor must refuse");
    }

    #[test]
    fn policy_parsing_refuses_a_document_it_cannot_trust() {
        use serde_json::{json, Value};
        assert!(parse_policy(b"not json").is_err());
        assert!(parse_policy(br#"{"protocol":"other"}"#).is_err(), "wrong protocol");

        let cases: Vec<(&str, Value)> = vec![
            // a policy is not a policy of another protocol
            ("protocol", json!("brops.recorder-policy.v2")),
            // root is not the recorder — the privilege separation would be circular
            ("recorder_uid", json!(0)),
            ("recorder_uid", json!("5005")),
            // relative / traversing / trailing-slash paths would make every later string compare a guess
            ("launcher_path", json!("tcb/privileged-launcher.bin")),
            ("launcher_path", json!("/opt/brops-live/tcb/../tcb/privileged-launcher.bin")),
            ("report_dir", json!("/opt/brops-live/report/")),
            ("evidence_state_dir", json!("/opt/brops-live//recorder-state")),
            // JSON can carry a NUL that a C string cannot; refuse it where it is readable rather than
            // as a bare `CString::new` failure deep in the exec path.
            ("store_dir", json!("/opt/brops-live/st\u{0}ore")),
            // a digest that is not a sha256 hex cannot pin anything
            ("launcher_sha256", json!("deadbeef")),
            ("executor_sha256", json!(EXECUTOR_SHA.to_uppercase())),
            ("cgroup", json!("")),
            // a MISSING field is not a default — every one of these steers the recorder
            ("launcher_path", Value::Null),
            ("launcher_sha256", Value::Null),
            ("executor_path", Value::Null),
            ("executor_sha256", Value::Null),
            ("lease_path", Value::Null),
            ("store_dir", Value::Null),
            ("cgroup", Value::Null),
            ("report_dir", Value::Null),
            ("evidence_state_dir", Value::Null),
            ("recorder_uid", Value::Null),
            ("protocol", Value::Null),
        ];
        for (field, bad) in cases {
            assert!(
                parse_policy(&policy_with(field, bad.clone())).is_err(),
                "a policy whose {field} is {bad} must be refused"
            );
        }
    }

    /// The exact bytes `run_live_turn.sh` writes to `$TCB/recorder-policy.json` (compact, sorted keys,
    /// derived from `config.json`), against the exact argv `chain_executor.rs` builds with a real
    /// broker-turn UUID and a real 32-hex attempt id. If the provisioner's wire format ever drifts from
    /// what this parser accepts, the live kit would refuse every turn — this says so at `cargo test`
    /// time instead of on the Linux runner.
    #[test]
    fn the_provisioned_document_drives_the_real_broker_spawn() {
        let provisioned = concat!(
            r#"{"cgroup":"cgroup-live","#,
            r#""evidence_state_dir":"/opt/brops-live/recorder-state","#,
            r#""executor_path":"/opt/brops-live/tcb/contained-executor.bin","#,
            r#""executor_sha256":"b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2","#,
            r#""launcher_path":"/opt/brops-live/tcb/privileged-launcher.bin","#,
            r#""launcher_sha256":"a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1","#,
            r#""lease_path":"/opt/brops-live/tcb/executor.lease","#,
            r#""protocol":"brops.recorder-policy.v1","recorder_uid":5005,"#,
            r#""report_dir":"/opt/brops-live/report","#,
            r#""store_dir":"/opt/brops-live/store"}"#,
        );
        let p = parse_policy(provisioned.as_bytes()).expect("the provisioned policy must parse");
        assert_eq!(p, policy(), "the provisioned document and the test fixture describe the same policy");

        let turn = "3f2a1c9e-77bd-4a11-9f3e-1c2d3e4f5a6b";
        let attempt = "9c1e4b7a2d3f4e5a6b7c8d9e0f1a2b3c";
        let real = argv(&[
            ("--store", "/opt/brops-live/store"),
            ("--launcher", "/opt/brops-live/tcb/privileged-launcher.bin"),
            ("--executor", "/opt/brops-live/tcb/contained-executor.bin"),
            ("--lease", "/opt/brops-live/tcb/executor.lease"),
            ("--cgroup", "cgroup-live"),
            ("--out", &format!("/opt/brops-live/report/live-{turn}-{attempt}.out")),
            (
                "--containment-out",
                &format!("/opt/brops-live/report/live-{turn}-{attempt}.out.containment.json"),
            ),
            ("--evidence-out", &format!("/opt/brops-live/recorder-state/{attempt}.evidence.json")),
            ("--evidence-state", "/opt/brops-live/recorder-state"),
        ]);
        plan(&p, &real, RECORDER_UID).expect("the real broker spawn must be accepted by the real policy");
    }

    // ---------------------------------------------------------------------------------------------
    // The image pin, re-checked immediately before the exec.
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn check_image_refuses_an_unpinned_or_uncustodied_binary() {
        let root_setuid = FileFacts::file(0, 0o4750);
        assert!(check_image("l", &root_setuid, LAUNCHER_SHA, LAUNCHER_SHA, true).is_ok());

        // a DIFFERENT binary at the pinned path
        assert!(
            check_image("l", &root_setuid, EXECUTOR_SHA, LAUNCHER_SHA, true).is_err(),
            "an image that is not the pinned digest must be refused"
        );
        // owned by a service account
        assert!(check_image("l", &FileFacts::file(5001, 0o4750), LAUNCHER_SHA, LAUNCHER_SHA, true).is_err());
        // writable by the group
        assert!(check_image("l", &FileFacts::file(0, 0o4770), LAUNCHER_SHA, LAUNCHER_SHA, true).is_err());
        // the setuid bit is gone — the launcher could not do its §2.7 job, so this is not the launcher
        assert!(check_image("l", &FileFacts::file(0, 0o0750), LAUNCHER_SHA, LAUNCHER_SHA, true).is_err());
        // not a regular file (a directory, a fifo the caller planted, …)
        assert!(check_image("l", &FileFacts::dir(0, 0o755), LAUNCHER_SHA, LAUNCHER_SHA, false).is_err());
        // the executor is not setuid and must not be required to be
        assert!(check_image("e", &FileFacts::file(0, 0o755), EXECUTOR_SHA, EXECUTOR_SHA, false).is_ok());
    }

    // ---------------------------------------------------------------------------------------------
    // The monotonic head-sequence counter's custody (the second half of the finding).
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn head_sequence_state_must_be_recorder_private() {
        assert!(check_state_dir(&FileFacts::dir(RECORDER_UID, 0o750), RECORDER_UID).is_ok());
        assert!(
            check_state_dir(&FileFacts::dir(RECORDER_UID, 0o770), RECORDER_UID).is_err(),
            "a group-writable state dir lets another principal rewind the head"
        );
        assert!(
            check_state_dir(&FileFacts::dir(RECORDER_UID, 0o757), RECORDER_UID).is_err(),
            "an other-writable state dir lets anyone rewind the head"
        );
        assert!(
            check_state_dir(&FileFacts::dir(5001, 0o750), RECORDER_UID).is_err(),
            "a state dir owned by the broker is the whole defect"
        );
        assert!(
            check_state_dir(&FileFacts::file(RECORDER_UID, 0o600), RECORDER_UID).is_err(),
            "not a directory"
        );
    }

    #[test]
    fn head_sequence_counter_file_must_be_recorder_private() {
        assert!(check_counter_file(&FileFacts::file(RECORDER_UID, 0o600), RECORDER_UID).is_ok());
        assert!(check_counter_file(&FileFacts::file(RECORDER_UID, 0o660), RECORDER_UID).is_err());
        assert!(check_counter_file(&FileFacts::file(RECORDER_UID, 0o606), RECORDER_UID).is_err());
        assert!(check_counter_file(&FileFacts::file(0, 0o600), RECORDER_UID).is_err());
        assert!(check_counter_file(&FileFacts::dir(RECORDER_UID, 0o700), RECORDER_UID).is_err());
    }
}
