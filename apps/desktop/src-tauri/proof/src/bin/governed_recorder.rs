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
//! On a non-Linux host the fork/execve/inherited-fd model does not exist ⇒ exit non-zero (fail closed).

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
    use std::ffi::CString;
    use std::io::Read;
    use std::os::fd::FromRawFd;

    fn flag(args: &[String], name: &str) -> Option<String> {
        args.iter().position(|a| a == name).and_then(|i| args.get(i + 1).cloned())
    }

    fn err(msg: &str) -> i32 {
        eprintln!("governed_recorder: {msg}");
        println!("RESULT: error {msg}");
        1
    }

    /// Read-increment-write the recorder's durable head-sequence counter (audit F-02).
    ///
    /// The supervisor's evidence floor refuses a head at or below the one it already recorded, so this
    /// number has to grow across RUNS — an in-run constant would make every turn of a deployment claim
    /// the same head, which is exactly the defect being removed. A missing counter starts at 1; a
    /// damaged one is `None` (⇒ the caller refuses) rather than silently restarting, because restarting
    /// is indistinguishable from a rollback. Written through a temp file and renamed so a crash cannot
    /// leave a truncated counter behind.
    fn next_head_sequence(dir: &str) -> Option<u64> {
        let path = std::path::Path::new(dir).join("evidence-head-sequence.json");
        let current: u64 = match std::fs::read_to_string(&path) {
            Ok(raw) => serde_json::from_str::<serde_json::Value>(&raw)
                .ok()?
                .get("head_sequence")?
                .as_u64()?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => 0,
            Err(_) => return None,
        };
        let next = current.checked_add(1)?;
        std::fs::create_dir_all(dir).ok()?;
        let temporary = path.with_extension("json.tmp");
        std::fs::write(&temporary, serde_json::json!({"head_sequence": next}).to_string()).ok()?;
        std::fs::rename(&temporary, &path).ok()?;
        Some(next)
    }

    pub fn recorder(args: &[String]) -> i32 {
        let store = match flag(args, "--store") {
            Some(s) => s,
            None => return err("recorder needs --store <dir>"),
        };
        let launcher = match flag(args, "--launcher") {
            Some(s) => s,
            None => return err("recorder needs --launcher <path>"),
        };
        let executor = match flag(args, "--executor") {
            Some(s) => s,
            None => return err("recorder needs --executor <path>"),
        };
        // The VALIDATED lease handle (§4.3): recorder-uid invoker gate, executor drop-target uid/gid, and
        // executor image sha256 pin. A TCB-owned (root, non-writable) file; the launcher fstat-verifies its
        // ownership before trusting the pins.
        let lease = match flag(args, "--lease") {
            Some(s) => s,
            None => return err("recorder needs --lease <path>"),
        };
        let cgroup = flag(args, "--cgroup").unwrap_or_else(|| "cgroup-live".to_string());
        let out_path = flag(args, "--out");
        // Where to write the CONTAINMENT REPORT for this run (audit F-02). Optional so the flag can
        // be added without breaking an older caller, but the broker always passes it and refuses the
        // turn if the file does not appear — so its absence is never silently tolerated.
        let containment_out = flag(args, "--containment-out");
        // Where to write the per-run EVIDENCE CHAIN + its head (audit F-02, second half). The four
        // `evidence_*` values the supervisor's terminal record carries — final_event_hash, event_count,
        // last_sequence, head_sequence — were deployment constants the provisioner wrote once, so every
        // receipt of the deployment claimed the same evidence head and the anti-rollback floor compared
        // a constant against itself. They now come from a chain THIS process builds out of what it
        // actually observed.
        let evidence_out = flag(args, "--evidence-out");
        // A recorder-owned directory holding the monotonic head-sequence counter. The head sequence has
        // to increase across RUNS for the supervisor's evidence floor to mean anything, and only durable
        // state can do that — an in-run value would be the same number every time, which is precisely
        // the constant being replaced.
        let evidence_state = flag(args, "--evidence-state");

        // Keep plain copies for the containment report: the originals are moved into CStrings below.
        let launcher_for_report = launcher.clone();
        let executor_for_report = executor.clone();
        let lease_for_report = lease.clone();
        let cgroup_for_report = cgroup.clone();

        // Pre-build every C string + open the store inputs BEFORE fork (only async-signal-safe libc runs
        // between fork and execve).
        let c_launcher = CString::new(launcher.clone()).unwrap();
        let c_arg0 = CString::new(launcher).unwrap();
        let c_lease = CString::new(lease).unwrap();
        let c_exec = CString::new(executor).unwrap();
        let c_cgroup = CString::new(cgroup).unwrap();

        let open_ro = |p: &str| -> i32 {
            let c = CString::new(format!("{store}/{p}")).unwrap();
            unsafe { libc::open(c.as_ptr(), libc::O_RDONLY) }
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
        if let Some(p) = out_path {
            if exit_code == 0 && !is_execve_fail && !report.is_empty() {
                if std::fs::write(&p, &report).is_err() {
                    return err("recorder: cannot write --out");
                }
                // The broker (a DIFFERENT uid) reads this report to content-address the output; make it
                // group/other-readable regardless of the recorder's umask.
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o644));
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
            if exit_code == 0 && !is_execve_fail && !report.is_empty() {
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
                if std::fs::write(cp, &bytes).is_err() {
                    return err("recorder: cannot write --containment-out");
                }
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(cp, std::fs::Permissions::from_mode(0o644));
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
            if exit_code == 0 && !is_execve_fail && !report.is_empty() {
                let sha = |p: &str| -> String {
                    std::fs::read(p)
                        .map(|b| brops_core::governed_message_store::sha256_hex(&b))
                        .unwrap_or_default()
                };
                let head_sequence = match evidence_state.as_deref() {
                    Some(dir) => match next_head_sequence(dir) {
                        Some(n) => n,
                        None => return err("recorder: cannot advance the evidence head sequence"),
                    },
                    // No durable counter ⇒ no honest head sequence. Refusing beats emitting a constant,
                    // which is the defect this whole block exists to remove.
                    None => return err("recorder needs --evidence-state with --evidence-out"),
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
                if std::fs::write(ep, &bytes).is_err() {
                    return err("recorder: cannot write --evidence-out");
                }
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(ep, std::fs::Permissions::from_mode(0o644));
            } else {
                // A refused run evidences nothing. Remove any stale chain so the broker cannot address a
                // previous run's evidence as this one's.
                let _ = std::fs::remove_file(ep);
            }
        }

        let report_str = String::from_utf8_lossy(&report);
        println!("EXECUTOR_REPORT: {report_str}");
        println!("RESULT: recorder launcher_exit={exit_code} report_bytes={}", report.len());
        if exit_code == 0 && !is_execve_fail && !report.is_empty() {
            0
        } else {
            1
        }
    }
}
