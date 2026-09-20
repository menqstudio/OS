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
//! `UpstreamBlockedExecutor` (`main.rs:268-270`), so every turn here comes back `blocked` /
//! `upstream_blocked`. That IS the shipped posture on every install, and asserting it is the point: the
//! refusal has never been demonstrated from outside the process. A committed turn needs the deployment
//! the six-piece backlog in `docs/OWNER_ACTION_REQUIRED.md` §0 is about.
//!
//! Linux-only by nature: `SO_PEERCRED` and `std::os::unix::net` do not exist elsewhere, and the binary
//! itself refuses off Linux with `EXIT_PLATFORM_UNSUPPORTED`.
#![cfg(target_os = "linux")]

use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
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

/// Start the real binary on a private socket, admitting this test's own uid as the renderer.
fn start() -> Broker {
    // `Instant::now().elapsed()` is always ~0 and would collide between the tests in this file, which
    // run in parallel; the wall clock plus the pid is unique enough for a temp directory.
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let dir = std::env::temp_dir().join(format!(
        "brops-broker-e2e-{}-{unique}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).expect("temp dir");
    let socket = dir.join("broker.sock");

    // SAFETY: getuid never fails and touches no memory.
    let uid = unsafe { libc::getuid() };

    let child = Command::new(env!("CARGO_BIN_EXE_brops-broker"))
        .arg(&socket)
        .arg(uid.to_string())
        // Explicitly UNSET, so the fail-closed posture under test is the one a shipped install has and
        // not an accident of the runner's environment.
        .env_remove("BROPS_BROKER_CONFIG")
        .spawn()
        .expect("the brops-broker binary must be runnable");

    let deadline = Instant::now() + Duration::from_secs(10);
    while !socket.exists() {
        assert!(
            Instant::now() < deadline,
            "the broker never bound {socket:?}; it opens its DB and binds before accepting"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    Broker { child, socket, dir }
}

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
    // `main.rs` derives the DB path from the socket path by replacing `.sock` with `.db`, and opens it
    // BEFORE binding. A broker that bound without its ledger would accept turns it could not record.
    let broker = start();
    let db = broker.socket.with_extension("db");
    assert!(
        db.exists(),
        "the broker binds only after opening {db:?}, so the socket existing implies this does"
    );
}
