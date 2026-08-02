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
