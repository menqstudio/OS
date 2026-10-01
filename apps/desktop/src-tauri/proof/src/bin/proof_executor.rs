//! Wave 3b-1B — the §2.7 contained executor image (LINUX-RUN live governed turn).
//!
//! This is the tiny, pinned image the privileged launcher `fexecve`s at the second exec boundary. On
//! entry it:
//!   (a) enumerates `/proc/self/fd` and REPORTS the descriptors it found. rev-30 §2.7 says that set is
//!       exactly {3,4,5,6} by the time an executor runs (0/1/2 neutralized by the launcher, every fd ≥ 7
//!       closed);
//!   (b) REPORTS its post-drop identity — euid/egid, whether all five capability sets are zero, and
//!       `no_new_privs`;
//!   (c) reads the three read-only inputs (fd 3 `system`, 4 `history`, 5 `generation_config`) to EOF and
//!       binds them deterministically (the same SHA-256 convention `executor/` uses), then
//!   (d) writes ONE JSON report to the write-only output pipe (fd 6) — those exact bytes ARE the governed
//!       turn's output, which the broker's `verify_and_accept` then binds by length+digest.
//!
//! **It reports; it enforces nothing, and nothing reads the report.** This header used to say the
//! descriptor set "MUST be EXACTLY {3,4,5,6}" and that (a) and (b) were "proving" the launcher's work.
//! Neither is checked anywhere:
//!
//!  * `run()` returns 0 whatever it observed. Its one non-zero exit is a failed write to fd 6. A
//!    descriptor set that is not {3,4,5,6}, non-zero capabilities and an unset `no_new_privs` all
//!    exit 0; an unreadable `/proc/self/status` is reported as euid/egid `4294967295`, and an input
//!    that could not be read as `"reply_binding": null`.
//!  * No code in this tree parses `observed_fds`, `caps_all_zero`, `no_new_privs` or `reply_binding`
//!    out of the report — not the recorder, not the broker, not either proof driver, not the live
//!    kits. The broker binds the report's BYTES (length and digest); what they say is read by nobody.
//!  * The enumeration is not a complete account either: it skips every descriptor whose
//!    `/proc/self/fd` link points under `/proc/` (to drop its own readdir handle) and every one whose
//!    link it cannot read. `launcher/src/main.rs::collect_fd_facts` removed exactly that filter as a
//!    §2.7 bypass and excludes only the enumeration handle, by number.
//!
//! The §2.7 enforcement that does exist is the LAUNCHER's, before it `fexecve`s this image: the
//! descriptor contract, the privilege drop and the post-drop capability state are verified there and a
//! failure means no exec. Turning this report into a refusal (non-zero unless the set is exactly
//! {3,4,5,6}, the capabilities are zero, `no_new_privs` is set and all three inputs were read) is not
//! done here because what the live kit actually observes has never been looked at by anything: it
//! would make a CI job fail or pass on values nobody has measured.
//!
//! It holds no key, opens no socket, and touches nothing but the four inherited descriptors. On a non-Linux
//! host it exits non-zero (the inherited-fd model does not exist there).

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("proof_executor: platform unsupported (Linux-only inherited-fd model)");
    std::process::exit(2);
}

#[cfg(target_os = "linux")]
fn main() {
    std::process::exit(linux::run());
}

#[cfg(target_os = "linux")]
mod linux {
    use brops_core::governed_message_store::sha256_hex;
    use std::fs;
    use std::io::{Read, Write};
    use std::os::fd::FromRawFd;

    pub fn run() -> i32 {
        // (a) Observed descriptor set — enumerate /proc/self/fd, skipping the transient readdir handle
        // (its link points under /proc/) and, with it, any OTHER descriptor that links there. §2.7
        // says what remains is exactly {3,4,5,6}; this only reports what it found (see the header).
        let observed = observed_fds();

        // (b) Post-drop identity + capabilities + no_new_privs from /proc/self/status.
        let status = fs::read_to_string("/proc/self/status").unwrap_or_default();
        let (euid, egid) = uid_gid(&status);
        let caps_all_zero = caps_all_zero(&status);
        let no_new_privs =
            status.lines().any(|l| l.starts_with("NoNewPrivs:") && l.trim_end().ends_with('1'));

        // (c) Read the three read-only inputs to EOF and bind them (same convention as executor/).
        let system = read_fd(3);
        let history = read_fd(4);
        let generation_config = read_fd(5);
        let reply_binding = match (system, history, generation_config) {
            (Some(s), Some(h), Some(g)) => Some(bind(&s, &h, &g)),
            _ => None,
        };

        // (d) One JSON report to fd 6. This is the governed output the broker will bind.
        let report =
            build_report(&observed, euid, egid, caps_all_zero, no_new_privs, reply_binding.as_deref());
        // SAFETY: fd 6 is the inherited write-only output pipe the launcher verified and handed us.
        let mut out = unsafe { fs::File::from_raw_fd(6) };
        if out.write_all(report.as_bytes()).is_err() || out.flush().is_err() {
            return 1;
        }
        0
    }

    fn observed_fds() -> Vec<i32> {
        let mut fds = Vec::new();
        if let Ok(dir) = fs::read_dir("/proc/self/fd") {
            for e in dir.flatten() {
                let fd: i32 = match e.file_name().to_str().and_then(|s| s.parse().ok()) {
                    Some(n) => n,
                    None => continue,
                };
                match fs::read_link(format!("/proc/self/fd/{fd}")) {
                    // Skip the readdir handle itself (it links under /proc/).
                    Ok(l) if l.to_string_lossy().starts_with("/proc/") => continue,
                    Ok(_) => fds.push(fd),
                    Err(_) => continue,
                }
            }
        }
        fds.sort_unstable();
        fds
    }

    fn read_fd(fd: i32) -> Option<Vec<u8>> {
        // SAFETY: fd is one of the inherited read-only inputs (3/4/5) the launcher verified.
        let mut f = unsafe { fs::File::from_raw_fd(fd) };
        let mut buf = Vec::new();
        f.read_to_end(&mut buf).ok()?;
        // Do not close the fd here (it stays in the observed set we already captured); leak the File.
        std::mem::forget(f);
        Some(buf)
    }

    fn uid_gid(status: &str) -> (u32, u32) {
        let field = |k: &str| -> u32 {
            status
                .lines()
                .find_map(|l| l.strip_prefix(k))
                .and_then(|v| v.split_whitespace().nth(1)) // effective is the 2nd column
                .and_then(|s| s.parse().ok())
                .unwrap_or(u32::MAX)
        };
        (field("Uid:"), field("Gid:"))
    }

    fn caps_all_zero(status: &str) -> bool {
        for key in ["CapEff:", "CapPrm:", "CapInh:", "CapBnd:", "CapAmb:"] {
            let v = status
                .lines()
                .find_map(|l| l.strip_prefix(key))
                .map(|s| s.trim())
                .unwrap_or("ffffffffffffffff");
            if u64::from_str_radix(v, 16).unwrap_or(u64::MAX) != 0 {
                return false;
            }
        }
        true
    }

    /// Deterministic input→output binding (mirrors `executor::build_output`).
    fn bind(system: &[u8], history: &[u8], generation_config: &[u8]) -> String {
        let sh = sha256_hex(system);
        let hh = sha256_hex(history);
        let gh = sha256_hex(generation_config);
        sha256_hex(format!("{sh}\n{hh}\n{gh}").as_bytes())
    }

    fn build_report(
        observed: &[i32],
        euid: u32,
        egid: u32,
        caps_all_zero: bool,
        no_new_privs: bool,
        reply_binding: Option<&str>,
    ) -> String {
        let fds = observed.iter().map(|f| f.to_string()).collect::<Vec<_>>().join(",");
        let rb = reply_binding.map(|s| format!("\"{s}\"")).unwrap_or_else(|| "null".into());
        format!(
            "{{\"proof_executor\":\"v1\",\"observed_fds\":[{fds}],\"euid\":{euid},\"egid\":{egid},\
\"caps_all_zero\":{caps_all_zero},\"no_new_privs\":{no_new_privs},\"reply_binding\":{rb}}}"
        )
    }
}
