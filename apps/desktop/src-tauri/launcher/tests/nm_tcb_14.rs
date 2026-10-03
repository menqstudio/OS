//! NM-TCB-14 — the launcher given extra argv, a non-empty environment, or an extra inherited FD
//! refuses, and nothing is executed.
//!
//! The argv and environment limbs run the REAL binary. They can, unprivileged, because that check
//! is the first thing `real_main` does: it refuses before it reads a lease, so no root-owned lease
//! and no setuid bit are needed to reach it.
//!
//! The FD limb cannot be reached that way — `collect_fd_facts` runs after the lease and the invoker
//! gate, which need a root-owned lease file — so it is asserted on the verifier the launcher calls
//! there, `brops_core::fd_lifecycle::verify_launcher_fd_set`. That is a test of the rule and not of
//! a spawn with a stray descriptor; a real one belongs in the root kit and is in none yet.
#![cfg(target_os = "linux")]

use brops_core::fd_lifecycle::{verify_launcher_fd_set, FdFacts, FdViolation, InodeIdentity};
use std::process::Command;

const LAUNCHER: &str = env!("CARGO_BIN_EXE_brops-launcher");

fn run(args: &[&str], env: &[(&str, &str)]) -> (Option<i32>, String, String) {
    let mut cmd = Command::new(LAUNCHER);
    cmd.args(args).env_clear();
    for (k, v) in env {
        cmd.env(k, v);
    }
    let out = cmd.output().expect("the launcher binary runs");
    (
        out.status.code(),
        String::from_utf8_lossy(&out.stdout).into_owned(),
        String::from_utf8_lossy(&out.stderr).into_owned(),
    )
}

fn facts(fd: i32, store: bool, pipe: bool) -> FdFacts {
    FdFacts {
        fd,
        identity: store.then_some(InodeIdentity { dev: 66, ino: 1000 + fd as u64, uid: 0, gid: 0, mode: 0o100644, size: 33 }),
        is_inert_endpoint: !store && !pipe,
        is_interactive_or_inherited: false,
        read_only: store,
        is_regular_store_inode: store,
        offset_zero: store,
        is_output_pipe: pipe,
        write_only: pipe,
        cloexec: false,
    }
}

#[test]
fn nm_tcb_14_extra_argv_a_non_empty_environment_or_an_extra_fd_is_refused() {
    const REFUSED: &str = "launcher: refuse (no exec, no receipt): BadArgv";

    // The control: exactly three arguments and an empty environment get PAST this gate. The launcher
    // still refuses — there is no such lease — but for the next reason, not this one.
    let (code, stdout, stderr) = run(&["/nonexistent/lease", "/nonexistent/image", "/cg"], &[]);
    assert_eq!(code, Some(1), "NM-TCB-14 control: {stderr}");
    assert!(!stderr.contains("BadArgv"), "NM-TCB-14 control: three args and no env were refused as BadArgv: {stderr}");
    assert!(stderr.contains("refuse (no exec, no receipt)"), "NM-TCB-14 control: {stderr}");
    assert_eq!(stdout, "");

    for (what, args, env) in [
        ("an extra argument", &["a", "b", "c", "d"][..], &[][..]),
        ("a missing argument", &["a", "b"][..], &[][..]),
        ("no arguments", &[][..], &[][..]),
        ("a non-empty environment", &["a", "b", "c"][..], &[("LD_PRELOAD", "/tmp/x.so")][..]),
    ] {
        let (code, stdout, stderr) = run(args, env);
        assert_eq!(code, Some(1), "NM-TCB-14: {what} did not exit 1: {stderr}");
        assert!(stderr.contains(REFUSED), "NM-TCB-14: {what} was not refused as BadArgv: {stderr}");
        assert_eq!(stdout, "", "NM-TCB-14: {what} produced output");
    }

    // The FD limb, on the rule itself: the exact set {0..6} is accepted, and one more is refused BY
    // NUMBER.
    let mut set = vec![
        facts(0, false, false), facts(1, false, false), facts(2, false, false),
        facts(3, true, false), facts(4, true, false), facts(5, true, false),
        facts(6, false, true),
    ];
    assert_eq!(verify_launcher_fd_set(&set, 500), Ok(()), "NM-TCB-14 control: the contract set");
    set.push(facts(7, true, false));
    assert_eq!(verify_launcher_fd_set(&set, 500), Err(FdViolation::UnexpectedFd(7)), "NM-TCB-14: an extra inherited FD");
}
