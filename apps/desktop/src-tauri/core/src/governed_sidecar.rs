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
//! [`GovernedSidecar::new`] requires a [`TrustEnvironment`], and [`crate::engine_trust::apply`] is
//! its only constructor. There is no `Default`, no public field, no second way to make one. A
//! caller that wants to start the sidecar without the provisioned trust material has nothing to
//! pass and does not compile — a different guarantee from the previous shape, where
//! `engine_trust::apply(&mut cmd)?` was a LINE, and deleting a line compiles.
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

fn env_nonempty(key: &str) -> Option<String> {
    std::env::var(key).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
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
    /// The provisioned trust material. Its TYPE is the proof it was resolved.
    trust: TrustEnvironment,
}

impl GovernedSidecar {
    /// Configure the seam. `trust` can only have come from [`crate::engine_trust::apply`].
    pub fn new(python: &str, sidecar: &str, cwd: PathBuf, trust: TrustEnvironment) -> Self {
        Self { python: python.to_string(), sidecar: sidecar.to_string(), cwd, trust }
    }

    /// The fully configured child command, one step short of `spawn()`.
    ///
    /// Separated from [`round_trip`](GovernedSidecar::round_trip) so a test can READ BACK what would
    /// be launched (`Command::get_envs` / `get_current_dir` / `get_args`) without starting a python
    /// interpreter. The trust environment reaching the child is the property that matters most here,
    /// and asserting it on the real builder is the only way to notice it stop happening.
    fn command(&self) -> std::process::Command {
        let mut cmd = std::process::Command::new(&self.python);
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
        cmd.arg(&sidecar_path)
            // Defense in depth (Architect merge-blocker): never let a fake/self-test flag reach the
            // production sidecar via inherited env.
            .env_remove(FAKE_SIDECAR_ENV)
            .current_dir(&self.cwd)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());
        hide_console(&mut cmd);
        cmd
    }

    /// One round trip: spawn a fresh one-shot sidecar, hand it `request` on stdin, read its single
    /// reply. Makes no trust decision — it returns the raw parsed document.
    ///
    /// Every local failure — spawn, read, deadline, unexpected exit, non-JSON output — is an `Err`,
    /// never a document. §6.1 makes a local ingress/transport failure out-of-band, and the sidecar
    /// originates no supervisor or signature verdict; a synthesized reply here would be this process
    /// inventing the one thing §2.4 forbids it to invent.
    pub fn round_trip(&self, request: &str) -> Result<Value, String> {
        let deadline = Instant::now() + SIDECAR_DEADLINE;
        let mut child = Reaped(self.command().spawn().map_err(|e| {
            format!(
                "Could not run the governed engine sidecar (`{} {}`): {e}. Set \
                 BROPS_GOVERNED_PYTHON / BROPS_GOVERNED_SIDECAR, or unset \
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

    /// A `TrustEnvironment` for tests. It has its own constructor in `engine_trust` rather than a
    /// public field here, because `engine_trust::apply` reads a process-global `OnceLock` that other
    /// tests in this binary must be able to find EMPTY — the fail-closed default is itself under
    /// test there.
    fn trust() -> TrustEnvironment {
        crate::engine_trust::test_trust_environment(vec![
            ("BRO_TRUSTED_REGISTRY_ROOT", "/anchor/registry".to_string()),
            ("BRO_CONDUCTOR_SESSION_TOKEN", "/trust/conductor-session.json".to_string()),
        ])
    }

    fn sidecar() -> GovernedSidecar {
        GovernedSidecar::new("python", "bridge/engine_sidecar.py", PathBuf::from("."), trust())
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
        let got = envs(&s.command());
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
        let got = envs(&s.command());
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
        let got = envs(&sidecar().command());
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
        let s = GovernedSidecar::new(
            "python",
            script.to_str().expect("temp path is UTF-8"),
            dir.clone(),
            trust(),
        );
        let cmd = s.command();
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
        let cmd = sidecar().command();
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
        let s = GovernedSidecar::new(
            "brops-no-such-interpreter-does-not-exist",
            "bridge/engine_sidecar.py",
            std::env::temp_dir(),
            trust(),
        );
        let err = s.round_trip("{}").expect_err("a missing interpreter cannot produce a reply");
        assert!(err.contains("Could not run the governed engine sidecar"), "{err}");
        assert!(err.contains("BROPS_GOVERNED_PYTHON"), "{err}");
    }

    /// The transport half of §4.10(g): the frame is serialized and goes through the SAME round trip,
    /// so a submit cannot acquire its own spawn discipline.
    #[test]
    fn the_submit_transport_is_the_same_spawn() {
        let s = GovernedSidecar::new(
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
