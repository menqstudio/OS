//! The `brops-broker` BINARY, actually run. Audit F5.
//!
//! Until this file existed, nothing in the tree executed it. Measured on 2026-09-20: a tree-wide search
//! for the binary name found `cargo test -p brops-broker`, the separate `brops-preflight` bin, and a
//! Windows PowerShell proof that uses the string as a label — and nothing that spawns it. The live kit
//! installs `governed_recorder` and `live_turn` (the proof driver) and says so itself:
//! `run_ladder_turn.sh` states in four places that what it drives "is NOT the `brops-broker` binary".
//!
//! So every claim about the broker's own process — that it opens its database, binds its socket,
//! authenticates the peer from the kernel, frames a reply, and survives a bad one — rested on unit tests
//! of the pieces and on reading. This runs the real executable over a real `AF_UNIX` socket.
//!
//! WHAT IT DELIBERATELY DOES NOT PROVE. With no `$BROPS_BROKER_CONFIG` the broker builds the fail-closed
//! `UpstreamBlockedExecutor` (the first refusal in `build_governed_executor`), so every turn here comes back `blocked` /
//! `upstream_blocked`. That IS the shipped posture on every install, and asserting it is the point: the
//! refusal has never been demonstrated from outside the process. A committed turn needs the deployment
//! `preflight::REQUIREMENTS` lists row by row; the installer that would provide it is designed in
//! `docs/design/DEBIAN_INSTALL_PROVISIONING.md`.
//!
//! Linux-only by nature: `SO_PEERCRED` and `std::os::unix::net` do not exist elsewhere, and the binary
//! itself refuses off Linux with `EXIT_PLATFORM_UNSUPPORTED`.
#![cfg(target_os = "linux")]

use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use brops_core::ipc_framing::{encode_frame, FrameDecoder};

/// Two canonical lowercase UUIDv4 correlation tokens. The request validator refuses anything else, so a
/// typo here would read as `malformed` and quietly stop testing what this file is about.
const CRID_ONE: &str = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";
const CRID_TWO: &str = "7c9e6679-7425-40de-944b-e07fc1f90ae7";

struct Broker {
    child: Child,
    socket: PathBuf,
    dir: PathBuf,
}

impl Drop for Broker {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

/// A private directory for one test. `Instant::now().elapsed()` is always ~0 and would collide between
/// the tests in this file, which run in parallel; the wall clock, the pid and a counter do not.
fn private_dir() -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let dir = std::env::temp_dir().join(format!(
        "brops-broker-e2e-{}-{unique}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::SeqCst)
    ));
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir
}

/// Start the real binary on a private socket, admitting this test's own uid as the renderer.
fn start() -> Broker {
    let dir = private_dir();
    let socket = dir.join("broker.sock");

    // SAFETY: getuid never fails and touches no memory.
    let uid = unsafe { libc::getuid() };

    let mut child = Command::new(env!("CARGO_BIN_EXE_brops-broker"))
        .arg(&socket)
        .arg(uid.to_string())
        // Explicitly UNSET, so the fail-closed posture under test is the one a shipped install has and
        // not an accident of the runner's environment.
        .env_remove("BROPS_BROKER_CONFIG")
        .spawn()
        .expect("the brops-broker binary must be runnable");

    // Readiness is an EXCHANGE, not a file. The socket path exists from `bind(2)` and accepts only
    // after `listen(2)`, so "the file is there" is true for a moment in which a connect is still
    // refused — this loop used to wait on `socket.exists()` and the first test then did a bare
    // `connect().expect()`. A connection the broker ACCEPTS is the thing being waited for. (The
    // probe connection is closed unused; the broker fails that one connection closed and serves on.)
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if UnixStream::connect(&socket).is_ok() {
            break;
        }
        if let Some(status) = child.try_wait().expect("poll the broker") {
            panic!("the broker exited ({status}) before it accepted a connection on {socket:?}");
        }
        assert!(
            Instant::now() < deadline,
            "the broker never accepted on {socket:?}; it opens its DB and binds before accepting"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    Broker { child, socket, dir }
}

/// Run the binary with `args` and wait for it to EXIT. `None` if it was still running at the
/// deadline — which, for an argument it was supposed to refuse, means it is serving.
fn exit_code(args: &[&std::ffi::OsStr]) -> Option<i32> {
    let mut child = Command::new(env!("CARGO_BIN_EXE_brops-broker"))
        .args(args)
        .env_remove("BROPS_BROKER_CONFIG")
        .spawn()
        .expect("the brops-broker binary must be runnable");
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Some(status) = child.try_wait().expect("poll the broker") {
            return status.code();
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// `main.rs`'s `EXIT_BAD_ARGUMENT`.
const EXIT_BAD_ARGUMENT: i32 = 5;

/// One request, one reply, on one connection — the protocol the broker serves.
fn round_trip(socket: &Path, request: &str) -> serde_json::Value {
    let mut stream = UnixStream::connect(socket).expect("connect to the broker socket");
    stream
        .set_read_timeout(Some(Duration::from_secs(10)))
        .expect("read deadline");
    let frame = encode_frame(request.as_bytes()).expect("encode the request frame");
    stream.write_all(&frame).expect("write the request frame");
    stream.flush().expect("flush");

    let mut decoder = FrameDecoder::new();
    let mut chunk = [0u8; 1024];
    loop {
        if let Some(payload) = decoder.next_frame().expect("decode the reply frame") {
            return serde_json::from_slice(&payload).expect("the reply is JSON");
        }
        let n = stream.read(&mut chunk).expect("read the reply");
        assert!(n > 0, "the broker closed before a complete reply frame");
        decoder.feed(&chunk[..n]);
    }
}

fn request(conversation: &str, crid: &str) -> String {
    format!(
        r#"{{"protocol":"brops.renderer-governed-turn.v1","conversation_id":"{conversation}","client_request_id":"{crid}"}}"#
    )
}

#[test]
fn the_binary_binds_serves_one_governed_turn_and_refuses_it_fail_closed() {
    let broker = start();
    let reply = round_trip(&broker.socket, &request("conv-e2e-1", CRID_ONE));

    // The shipped posture, demonstrated from OUTSIDE the process for the first time: no
    // `$BROPS_BROKER_CONFIG` means `build_governed_executor` returns `UpstreamBlockedExecutor`, and a
    // turn it refuses comes back closed rather than as a fabricated acceptance.
    assert_eq!(reply["status"], "blocked", "reply: {reply}");
    assert_eq!(reply["reason"], "upstream_blocked", "reply: {reply}");
    assert!(reply["message"].is_null(), "a blocked reply carries no message: {reply}");

    // The correlation ids come back, which is what makes a reply attributable to a request.
    assert_eq!(reply["client_request_id"], CRID_ONE);
    assert_eq!(reply["conversation_id"], "conv-e2e-1");
    // The REPLY protocol is not the request's. I assumed it was, and CI's first compile of this file
    // caught it: `REQUEST_PROTOCOL` is `brops.renderer-governed-turn.v1`, `RESULT_PROTOCOL`
    // (governed_turn_ipc.rs:27) is `brops.renderer-governed-turn-result.v1`. They are deliberately
    // distinct so a request frame can never be replayed as a reply, and the assertion is worth keeping
    // for exactly that reason.
    assert_eq!(reply["protocol"], "brops.renderer-governed-turn-result.v1");
    assert!(
        reply["broker_turn_id"].as_str().is_some_and(|s| !s.is_empty()),
        "the broker mints its own turn id: {reply}"
    );
}

#[test]
fn a_malformed_frame_is_refused_and_the_listener_keeps_serving() {
    // The F-31 property, from outside: one bad peer fails ONE connection. The accept loop is strictly
    // serial, so a peer that could wedge it would deny the governed path to everyone sharing the
    // renderer's uid — which the design treats as untrusted.
    let broker = start();

    let bad = round_trip(&broker.socket, r#"{"protocol":"nope","conversation_id":"c"}"#);
    assert_eq!(bad["status"], "blocked", "reply: {bad}");
    assert_eq!(bad["reason"], "malformed", "reply: {bad}");

    let good = round_trip(&broker.socket, &request("conv-e2e-2", CRID_TWO));
    assert_eq!(good["status"], "blocked", "reply: {good}");
    assert_eq!(good["reason"], "upstream_blocked", "reply: {good}");
    assert_eq!(good["client_request_id"], CRID_TWO);
}

#[test]
fn the_broker_opens_its_database_beside_the_socket() {
    // `main.rs` derives the DB path from the socket path with `brops_broker::broker_db_path` — the
    // same function, not this test's own idea of the rule — and opens it BEFORE binding. A broker
    // that bound without its ledger would accept turns it could not record.
    let broker = start();
    let db = brops_broker::broker_db_path(broker.socket.to_str().expect("a UTF-8 temp path"))
        .expect("the test socket ends in .sock");
    assert!(
        Path::new(&db).exists(),
        "the broker accepts only after opening {db:?}, so an accepted connection implies this exists"
    );
}

#[test]
fn a_socket_path_without_the_sock_suffix_is_refused_before_any_file_is_touched() {
    // The old rule was `socket_path.replace(".sock", ".db")`, which hands this path back UNCHANGED:
    // the broker created its ledger AT the socket path, unlinked it as a "stale socket", bound there,
    // and served with a database that no longer had a name.
    let dir = private_dir();
    let socket = dir.join("broker");
    // SAFETY: getuid never fails and touches no memory.
    let uid = unsafe { libc::getuid() }.to_string();
    let code = exit_code(&[socket.as_os_str(), std::ffi::OsStr::new(&uid)]);
    assert_eq!(
        code,
        Some(EXIT_BAD_ARGUMENT),
        "a socket path with no `.sock` suffix must be refused at startup (None = it is serving)"
    );
    assert_eq!(
        std::fs::read_dir(&dir).expect("the test dir").count(),
        0,
        "the refusal comes before any database or socket is created"
    );
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn a_renderer_uid_argument_that_is_not_a_uid_is_refused_at_startup() {
    // An unparsable uid used to become the BROKER'S OWN uid, silently: the peer allowlist then
    // admitted a principal nobody named. An absent argument still defaults (every other test in this
    // file would notice if it stopped); a present one that cannot be read does not.
    for bad in ["10o0", "-1", "", "4294967296", "1000 "] {
        let dir = private_dir();
        let socket = dir.join("broker.sock");
        let code = exit_code(&[socket.as_os_str(), std::ffi::OsStr::new(bad)]);
        assert_eq!(
            code,
            Some(EXIT_BAD_ARGUMENT),
            "the uid argument {bad:?} must be refused at startup (None = it is serving)"
        );
        assert_eq!(
            std::fs::read_dir(&dir).expect("the test dir").count(),
            0,
            "{bad:?}: the refusal comes before any database or socket is created"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}
