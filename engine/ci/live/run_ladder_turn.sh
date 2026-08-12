#!/usr/bin/env bash
# Wave 3b — the §4.10(g) LADDER against the REAL supervisor, with the REAL contained execution.
#
# WHY THIS EXISTS BESIDE `run_live_turn.sh`, AND WHY NEITHER REPLACES THE OTHER
# ------------------------------------------------------------------------------
# `run_live_turn.sh` runs a real 7-service governed turn on Linux — six dedicated uids, AF_UNIX +
# SO_PEERCRED, the setuid launcher, the contained executor — and it is a real proof. But it drives
# `broker_orchestrator::run_governed_turn` + `verify_and_accept` over DIRECT AF_UNIX: the five §5
# `op` messages, from the broker uid. It never touches the bridge adapter and never sends a
# §4.10(a0)/(a)(b)(c)/(d) frame. Citing it for "one governed round-trip proven end to end,
# adapter ↔ real supervisor" would be the substitution that made that claim false once already.
#
# `engine/tests/test_governed_turn_submit_e2e.py` drives the REAL §4.10(g) ladder — real
# `OpenService`/`StagingService`/`EvidenceRequestService`, a real durable ledger, four real Ed25519
# keypairs, the real `challenge_authority.issue_challenge`, the real §5 `AcceptanceDriver`, the real
# `IsolatedSigner` — from a submit frame to a §4.6 frame whose envelope verifies. But §6.1 step 5,
# the CONTAINED EXECUTION, is a stand-in there, because it needs Linux, six uids and a setuid
# launcher; that file says so in its own docstring.
#
# THIS script is the intersection: the §4.10(g) ladder, driven by the REAL one-shot sidecar
# subprocess (`bridge/engine_sidecar.py`) from a SEVENTH principal, against the REAL supervisor
# services, reaching the REAL privileged recorder → setuid launcher → contained executor — and it
# RECORDS the evidence and exits non-zero unless the round trip actually completed.
#
# AND, since 2026-08-12, it PULLS THE OUTPUT BACK through §4.10(f). That is a second round trip and
# a different one: §4.10(g)'s submit subprocess deliberately pulls nothing (an engine test asserts
# no output-read protocol appears among its frames), so until now `governed_output_read.py`, the
# sidecar's `bridge.governed-turn-output-read.v1` branch and `brops_core::governed_output_pull`
# were three halves of one hop that had never been driven against each other anywhere. The pull is
# driven by `target/debug/ladder_output_pull`, a driver binary in the crate that OWNS the loop —
# `pull_output`'s API takes a `ReceiptEnvelope` and has no parameter for the expected length or
# digest, precisely so no caller can aim the §4.6/§7.1 gate at §4.10(e)'s transport echo, and a
# Python driver would therefore have had to re-implement both the loop and the gate.
#
# It provisions the SAME `/opt/brops-live` root, and it has to: the setuid launcher pins
# `/opt/brops-live/config.json` as its attested-request path and the recorder pins
# `/opt/brops-live/tcb/recorder-policy.json` as its steering policy, both COMPILED IN so no argv or
# env can redirect them. So the two scripts cannot run concurrently on one box; in CI they are
# separate jobs on separate runners.
#
# AND, since 2026-08-13, it drives the REAL `brops_broker::ladder_executor::LadderChain` — the Rust
# object the desktop product would run — through `target/debug/ladder_turn`. Everything else in this
# script drives the ladder from PYTHON (`ladder_desktop.py` writes the frame, `engine_sidecar.py` is
# fed it on stdin), which proves the SERVERS and proves nothing about the chain object: no Rust in
# this tree had ever run `LadderChain` against a real supervisor. That phase is NOT the
# `brops-broker` binary and its banner says so at length — `build_governed_executor` can only reach
# the Owner's OFFLINE root pin, so the driver anchors its own `KeyResolver` to the kit's TCB
# root-anchor file, whose `kit_generated` provenance can never render `production_verified=true`.
#
# WHAT THIS KIT PROVISIONS THAT THE §5 KIT DOES NOT (each is a finding, not a convenience)
# ----------------------------------------------------------------------------------------
#  * a SEVENTH account, `brops-sidecar`. §2.6 requires pairwise-distinct principals and
#    `handle_connection` refuses outright when the sidecar uid equals the broker uid. The §5 kit
#    provisions six accounts and none of them is the sidecar, so every read/staging/open/evidence
#    gate — all of which demand the SIDECAR uid — was unreachable on that kit by construction.
#  * a §4.2 challenge-key registry document. `OpenService` resolves the registry from the
#    supervisor's own state under a binary-pinned root; the §5 kit ships none.
#  * `supervisor-sidecar.ipc-policy.json`. `ipc_policy.load_allowed_peer_uid` returns exactly one
#    uid, and this socket now serves two disjoint principals.
#  * `isolated-signer.ipc-policy.json` pointed at the SUPERVISOR uid. In §5 the broker calls the
#    signer; in §6.1 steps 11-12 the SUPERVISOR does, and the broker is not in this ladder at all.
#  * a sudoers vector letting the SUPERVISOR spawn the recorder. In §5 the broker spawns it.
#  * the three staged artifacts in their §4.10(g) canonical spellings (the §5 kit seeds the FROZEN
#    raw-string `generation_config`, which hashes differently by design).
#
# WHAT THIS KIT DELIBERATELY DOES NOT DO
# ---------------------------------------
#  * It does NOT run the §2.5 TCB integrity floor. `build_tcb_pin_manifest.py` binds the
#    `supervisor.bin` role to `engine/ci/live/run_supervisor.py` and both `.unit` roles to
#    `run_live_turn.sh` through a hardcoded map, so the manifest it produces here would measure
#    files that are not the ones serving this turn. A floor that pins the wrong artifact is worse
#    than no floor, and widening that role table is an Architect decision. `run_live_turn.sh` still
#    proves the floor; this script states its absence instead of implying coverage.
#  * It flips NO gate. `governed_verification_unconfigured`, `UpstreamBlockedExecutor` and
#    `connect_broker` are untouched; the shipped app's governed path stays shut. This runs in CI
#    against the live kit exactly as the §5 job does and makes nothing reachable in the product.
#
# Requires real root (sudo), the seven service accounts, a Rust toolchain, and python3 with
# `cryptography` + `jsonschema` (engine/requirements-ci.txt).
#
#   sudo engine/ci/live/run_ladder_turn.sh
#
set -u

# ----- accounts ------------------------------------------------------------------------------
BROKER_USER=brops-verifier_broker
CHALLENGE_USER=brops-challenge
SUPERVISOR_USER=brops-supervisor
RECORDER_USER=brops-recorder
SIGNER_USER=brops-signer
EXECUTOR_USER=brops-executor
SIDECAR_USER=brops-sidecar

[ "$(id -u)" = "0" ] || { echo "FAIL: run as root (sudo) — real service accounts + setuid launcher"; exit 1; }
for u in "$BROKER_USER" "$CHALLENGE_USER" "$SUPERVISOR_USER" "$RECORDER_USER" "$SIGNER_USER" \
         "$EXECUTOR_USER" "$SIDECAR_USER"; do
  id -u "$u" >/dev/null 2>&1 || { echo "FAIL: the account $u is not provisioned"; exit 1; }
done

# §2.6, checked before anything is built: the seven principals must be pairwise distinct. A
# collapse here would make every ACL below meaningless, and the supervisor would refuse at the
# door — which is correct and unreadable. Say it where the message is about accounts.
UIDS=$(for u in "$BROKER_USER" "$CHALLENGE_USER" "$SUPERVISOR_USER" "$RECORDER_USER" \
                "$SIGNER_USER" "$EXECUTOR_USER" "$SIDECAR_USER"; do id -u "$u"; done)
[ "$(echo "$UIDS" | sort -u | wc -l)" = "7" ] || {
  echo "FAIL: §2.6 — the seven service accounts are not pairwise-distinct uids"; exit 1; }

umask 022

# ----- locate repo + build ---------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TAURI_DIR="$REPO_ROOT/apps/desktop/src-tauri"
TARGET_DIR="${CARGO_TARGET_DIR:-$TAURI_DIR/target}/debug"
LAUNCHER_BIN="$TARGET_DIR/brops-launcher"
EXECUTOR_BIN="$TARGET_DIR/proof_executor"
RECORDER_BIN="$TARGET_DIR/governed_recorder"
# The §4.10(f) DESKTOP half. A binary in `brops-core` because that crate owns `pull_output`, the
# chunk arithmetic and both output gates; see the header.
PULL_BIN="$TARGET_DIR/ladder_output_pull"
# The rev-30 §4.10(g) LADDER DRIVER: `brops-governed-live`'s `ladder_turn`. It builds the SAME
# `LadderChain` the broker's `build_governed_executor` builds and runs one turn through
# `run_governed_turn`. It is NOT the `brops-broker` binary and the phase below says so in its banner.
DRIVER_BIN="$TARGET_DIR/ladder_turn"

if [ -x "$LAUNCHER_BIN" ] && [ -x "$EXECUTOR_BIN" ] && [ -x "$RECORDER_BIN" ] && [ -x "$PULL_BIN" ] \
   && [ -x "$DRIVER_BIN" ]; then
  echo "== using pre-built launcher/executor/recorder/output-pull/ladder-turn binaries =="
else
  echo "== building the launcher + the governed-live crate (recorder/executor) + the pull driver =="
  CARGO_BIN="$(command -v cargo || true)"
  [ -n "$CARGO_BIN" ] || for u in "${SUDO_USER:-}" gevorg; do
    [ -n "$u" ] && [ -x "/home/$u/.cargo/bin/cargo" ] && { CARGO_BIN="/home/$u/.cargo/bin/cargo"; break; }
  done
  [ -n "$CARGO_BIN" ] || { echo "FAIL: cargo not found (build as the normal user first, then re-run)"; exit 1; }
  # TWO invocations, deliberately. `--bin` is a filter over the WHOLE command, not over the package
  # it follows: naming three packages and `--bin ladder_output_pull` builds ONLY that bin and
  # silently skips the launcher, the recorder and the executor. That is CI run 31617346101 --
  # cargo said "Finished in 0.11s" and the binary check below caught the absence.
  ( cd "$REPO_ROOT" && "$CARGO_BIN" build --manifest-path "$TAURI_DIR/Cargo.toml" \
      -p brops-launcher -p brops-governed-live ) || { echo "FAIL: build (live kit)"; exit 1; }
  ( cd "$REPO_ROOT" && "$CARGO_BIN" build --manifest-path "$TAURI_DIR/Cargo.toml" \
      -p brops-core --bin ladder_output_pull ) || { echo "FAIL: build (pull driver)"; exit 1; }
fi
for b in "$LAUNCHER_BIN" "$EXECUTOR_BIN" "$RECORDER_BIN" "$PULL_BIN" "$DRIVER_BIN"; do
  [ -x "$b" ] || { echo "FAIL: missing built binary $b"; exit 1; }
done

# ----- layout ----------------------------------------------------------------------------------
LIVE=/opt/brops-live
STORE="$LIVE/store"; SOCK="$LIVE/sock"; REPORT="$LIVE/report"; TCB="$LIVE/tcb"; BIN="$LIVE/bin"; KEYS="$LIVE/keys"
SUPSTATE="$LIVE/supervisor-state"     # the supervisor's PRIVATE durable ledger (F-01), 0700
RECSTATE="$LIVE/recorder-state"       # the recorder's PRIVATE evidence head counter (F-02), 0750
STAGING="$LIVE/supervisor-staging"    # the §4.10(a)(b)(c) staging root — supervisor-private, 0700
LADDER="$LIVE/ladder"                 # this proof's working files + evidence bundle
rm -rf "$LIVE"
mkdir -p "$STORE" "$SOCK" "$REPORT" "$TCB" "$BIN" "$KEYS" "$SUPSTATE" "$RECSTATE" "$STAGING" \
         "$LADDER/evidence" "$LIVE/engine" "$LIVE/broker-state"

# Stage the Python tree the service accounts import from. The repo may live under a home dir the
# service uids cannot traverse, so the runners resolve everything relative to `__file__` inside
# here. The BRIDGE is staged too — it is not staged by the §5 kit, because that kit's turn never
# involves a sidecar — and `engine_sidecar` resolves `../engine/runtime` from its own location, so
# the two relative layouts must be preserved exactly.
mkdir -p "$LIVE/engine/ci/live" "$LIVE/engine/runtime" "$LIVE/bridge/contracts"
cp "$REPO_ROOT"/engine/ci/live/*.py "$LIVE/engine/ci/live/"
cp "$REPO_ROOT"/engine/runtime/*.py "$LIVE/engine/runtime/"
# The ledger loads its schema from the canonical .sql beside the runtime modules. Staged
# explicitly rather than by widening the glob, so a future non-code file has to be considered
# rather than swept into the TCB.
cp "$REPO_ROOT"/engine/runtime/supervisor_ledger.sql "$LIVE/engine/runtime/"
cp "$REPO_ROOT"/bridge/*.py "$LIVE/bridge/"
# `engine_adapter` (imported at `engine_sidecar` module scope) reads `task-request.schema.json`
# from this directory at import time, so the sidecar cannot start without it.
cp "$REPO_ROOT"/bridge/contracts/*.json "$LIVE/bridge/contracts/"
chmod -R a+rX "$LIVE/engine" "$LIVE/bridge"
PYLIVE="$LIVE/engine/ci/live"

# ----- setuid launcher + pinned executor image + recorder --------------------------------------
install -m 0755 "$LAUNCHER_BIN" "$TCB/privileged-launcher.bin"
chown "0:$(id -g "$RECORDER_USER")" "$TCB/privileged-launcher.bin"
chmod 4750 "$TCB/privileged-launcher.bin"
install -m 0755 "$EXECUTOR_BIN" "$TCB/contained-executor.bin"; chown 0:0 "$TCB/contained-executor.bin"
install -m 0755 "$RECORDER_BIN" "$BIN/governed_recorder"; chown 0:0 "$BIN/governed_recorder"

LAUNCHER_SHA=$(sha256sum "$TCB/privileged-launcher.bin" | cut -d' ' -f1)
EXECUTOR_SHA=$(sha256sum "$TCB/contained-executor.bin" | cut -d' ' -f1)

# ----- keys + manifest + store + shared config -------------------------------------------------
echo "== provisioning keys + root-signed manifest + store + config =="
python3 "$PYLIVE/provision_keys.py" --root-dir "$LIVE" \
  --launcher-sha "$LAUNCHER_SHA" --executor-sha "$EXECUTOR_SHA" \
  --recorder-bin "$BIN/governed_recorder" --sudo-recorder-user "$RECORDER_USER" \
  --login-uid "$(id -u "${SUDO_USER:-root}")" \
  || { echo "FAIL: provision_keys.py"; exit 1; }

CONFIG="$LIVE/config.json"
# The launcher compiles in this exact path as ATTESTED_REQUEST_PATH. Assert the coupling here,
# where the message is about provisioning, rather than discovering it as a cryptic store-input
# refusal in the middle of a turn.
[ "$CONFIG" = "/opt/brops-live/config.json" ] || {
  echo "FAIL: the launcher pins /opt/brops-live/config.json; this kit is at $CONFIG"; exit 1; }

# ----- the LADDER additions --------------------------------------------------------------------
echo "== provisioning the §4.10(g) ladder additions =="
python3 "$PYLIVE/provision_ladder.py" --root-dir "$LIVE" \
  --sidecar-uid "$(id -u "$SIDECAR_USER")" \
  --supervisor-uid "$(id -u "$SUPERVISOR_USER")" \
  --broker-uid "$(id -u "$BROKER_USER")" \
  --recorder-user "$RECORDER_USER" \
  || { echo "FAIL: provision_ladder.py"; exit 1; }
LADDER_CONFIG="$TCB/ladder.json"

# ----- the launcher's §4.3 VALIDATED lease FILE (root-owned, non-writable) ----------------------
# Written AFTER the ladder provisioning, because it pins the three governed REQUEST inputs and
# those are now the §4.10(g) canonical bytes rather than the §5 kit's. The digests are taken from
# the very files the recorder opens as fds 3/4/5, and the launcher re-hashes those held
# descriptors before it will exec.
RECORDER_GID=$(id -g "$RECORDER_USER"); EXECUTOR_UID=$(id -u "$EXECUTOR_USER"); EXECUTOR_GID=$(id -g "$EXECUTOR_USER")
SYSTEM_SHA=$(sha256sum "$STORE/system" | cut -d' ' -f1)
HISTORY_SHA=$(sha256sum "$STORE/history" | cut -d' ' -f1)
GENCFG_SHA=$(sha256sum "$STORE/generation_config" | cut -d' ' -f1)
# Three-way agreement, asserted rather than assumed: the bytes on disk, the digests the config
# attests, and the digests the ladder provisioner recorded as the turn's own. A divergence here
# would surface much later as an unattributable launcher refusal or a §4.10(a) `digest_mismatch`.
python3 - "$CONFIG" "$LADDER_CONFIG" "$SYSTEM_SHA" "$HISTORY_SHA" "$GENCFG_SHA" <<'PYCHECK' \
  || { echo "FAIL: the attested/staged/on-disk digests diverge"; exit 1; }
import json, sys
cfg = json.load(open(sys.argv[1]))["resolved"]
turn = json.load(open(sys.argv[2]))["turn"]["digests"]
names = ("system", "history", "generation_config")
disk = dict(zip(names, sys.argv[3:6]))
bad = {n: (cfg.get(n + "_sha256"), turn.get(n), disk[n]) for n in names
       if not (cfg.get(n + "_sha256") == turn.get(n) == disk[n])}
if bad:
    print("attested/staged/on-disk digest mismatch (config, ladder, disk):", bad, file=sys.stderr)
    sys.exit(1)
PYCHECK
cat > "$TCB/executor.lease" <<LEASE
recorder_uid=$(id -u "$RECORDER_USER")
recorder_gid=$RECORDER_GID
executor_uid=$EXECUTOR_UID
executor_gid=$EXECUTOR_GID
executor_executable_sha256=$EXECUTOR_SHA
system_sha256=$SYSTEM_SHA
history_sha256=$HISTORY_SHA
generation_config_sha256=$GENCFG_SHA
LEASE
chown 0:0 "$TCB/executor.lease"; chmod 0644 "$TCB/executor.lease"

# ----- the recorder's ROOT-OWNED steering policy -----------------------------------------------
# The recorder is the trusted identity of this chain: the supervisor reads each run's evidence
# chain out of $RECSTATE precisely BECAUSE no caller can write there. It reads every path from
# THIS file, at a path compiled into the binary (`guard::POLICY_PATH`), and refuses any argv value
# that disagrees — which is what stops the SUPERVISOR (the invoker here, as the broker is in the
# §5 kit) from having the recorder write an authentic chain for an execution it authored.
RECORDER_POLICY="$TCB/recorder-policy.json"
[ "$RECORDER_POLICY" = "/opt/brops-live/tcb/recorder-policy.json" ] || {
  echo "FAIL: \$LIVE moved; the recorder policy must live at guard::POLICY_PATH"; exit 1; }
python3 - "$CONFIG" "$LAUNCHER_SHA" "$EXECUTOR_SHA" "$(id -u "$RECORDER_USER")" "$RECORDER_POLICY" \
  <<'PYPOLICY' || { echo "FAIL: could not provision the recorder policy"; exit 1; }
import json, sys
cfg = json.load(open(sys.argv[1]))
ex = cfg["execution"]
policy = {
    "protocol": "brops.recorder-policy.v1",
    "recorder_uid": int(sys.argv[4]),
    "store_dir": ex["recorder_store_dir"],
    "launcher_path": ex["launcher_path"],
    "launcher_sha256": sys.argv[2],
    "executor_path": ex["executor_path"],
    "executor_sha256": sys.argv[3],
    "lease_path": ex["lease_file"],
    "cgroup": ex["cgroup_arg"],
    "report_dir": ex["report_dir"],
    "evidence_state_dir": ex["evidence_state_dir"],
}
for key in ("store_dir", "launcher_path", "executor_path", "lease_path", "report_dir",
            "evidence_state_dir"):
    value = policy[key]
    if not value.startswith("/") or "//" in value or value.rstrip("/") != value \
            or any(c in (".", "..") for c in value.split("/")[1:]):
        print("policy %s is not an absolute normalised path: %r" % (key, value), file=sys.stderr)
        sys.exit(1)
if policy["recorder_uid"] == 0:
    print("the recorder account must not be root", file=sys.stderr)
    sys.exit(1)
with open(sys.argv[5], "w", encoding="utf-8") as fh:
    json.dump(policy, fh, separators=(",", ":"), sort_keys=True)
PYPOLICY
chown 0:0 "$RECORDER_POLICY"; chmod 0644 "$RECORDER_POLICY"

# ----- key custody ------------------------------------------------------------------------------
chown "$CHALLENGE_USER":  "$KEYS/challenge.priv";          chmod 0400 "$KEYS/challenge.priv"
chown "$SUPERVISOR_USER": "$KEYS/supervisor_attest.priv";  chmod 0400 "$KEYS/supervisor_attest.priv"
chown "$SIGNER_USER":     "$KEYS/signer.priv";             chmod 0400 "$KEYS/signer.priv"
# The root key SIGNED the §4.2 registry document during provisioning and is never read again. It
# stays root-only: a service account that could read it could mint a registry naming its own key.
chown 0:0 "$KEYS/root.priv";                               chmod 0400 "$KEYS/root.priv"
chmod 0644 "$KEYS"/*.pub.hex "$CONFIG" "$LIVE/manifest.json" "$LIVE/manifest.sig" "$LIVE/floor.json"
chown 0:0 "$TCB/root-anchor.json"; chmod 0644 "$TCB/root-anchor.json"
# The registry document, the ladder config and both IPC policies are TCB: the supervisor refuses
# to load any of them unless they are root-owned and non-writable by anyone else.
chown 0:0 "$TCB"/*.ipc-policy.json "$TCB/challenge-key-registry.json" "$LADDER_CONFIG"
chmod 0644 "$TCB"/*.ipc-policy.json "$TCB/challenge-key-registry.json" "$LADDER_CONFIG"

# ----- cross-uid working dirs: least privilege --------------------------------------------------
# Same topology as the §5 kit, plus the sidecar in `brops-ipc` (it connects to the supervisor
# socket and to nothing else — it is deliberately in NEITHER `brops-store` NOR `brops-report`,
# because §2.4 declares it compromised and it has no business reading a governed reply).
add_group() {  # <group> <members...>
  local g="$1"; shift
  getent group "$g" >/dev/null || groupadd --system "$g" || return 1
  for m in "$@"; do usermod -aG "$g" "$m" || return 1; done
}
add_group brops-store  "$SUPERVISOR_USER" "$RECORDER_USER" || { echo "FAIL: brops-store group";  exit 1; }
add_group brops-report "$RECORDER_USER"   "$SUPERVISOR_USER" || { echo "FAIL: brops-report group"; exit 1; }
add_group brops-ipc    "$CHALLENGE_USER" "$SUPERVISOR_USER" "$SIGNER_USER" "$BROKER_USER" \
  "$SIDECAR_USER" || { echo "FAIL: brops-ipc group"; exit 1; }
chgrp brops-store  "$STORE";  chmod 2775 "$STORE"
# In the §5 kit the BROKER reads the report directory, because the broker content-addresses the
# reply. Here the SUPERVISOR does, because the §4.10(d) hop owns the completion. The broker and
# the sidecar are both absent, which is the tighter arrangement of the two.
chgrp brops-report "$REPORT"; chmod 2770 "$REPORT"
chgrp brops-ipc    "$SOCK";   chmod 2770 "$SOCK"
chmod 0644 "$STORE"/* 2>/dev/null || true
chgrp brops-store "$STORE"/* 2>/dev/null || true

chown -R "$SUPERVISOR_USER": "$SUPSTATE"; chmod 0700 "$SUPSTATE"
# The §4.10(a)(b)(c) staging root holds partially-uploaded caller bytes before they are re-hashed
# against the challenge. Supervisor-private, 0700: nothing else may read a half-staged artifact
# and nothing else may write one.
chown -R "$SUPERVISOR_USER": "$STAGING"; chmod 0700 "$STAGING"
# Recorder-owned, SUPERVISOR-readable: the supervisor reads each run's evidence chain from here to
# derive the evidence head and to check the reply digest the completion reports. Nothing that can
# call the supervisor can write it — that is the whole property.
chown -R "$RECORDER_USER":"$SUPERVISOR_USER" "$RECSTATE"; chmod 0750 "$RECSTATE"

# ----- this proof's working files, one owner each ------------------------------------------------
# $LIVE is root-owned 0755 so no service account can create files there. Each participant gets
# exactly the one file it writes, pre-created by root — rather than a shared 1777 directory, which
# is the arrangement audit F-07/F-28 removed from the §5 kit.
chown 0:0 "$LADDER" "$LADDER/evidence"; chmod 0755 "$LADDER" "$LADDER/evidence"
for f in hops.jsonl; do : > "$LADDER/$f"; chown "$SUPERVISOR_USER": "$LADDER/$f"; chmod 0644 "$LADDER/$f"; done
for f in submit.json submit-tampered.json document.json document-tampered.json; do
  : > "$LADDER/$f"; chown "$BROKER_USER": "$LADDER/$f"; chmod 0644 "$LADDER/$f"; done
for f in reply.json reply-tampered.json; do
  : > "$LADDER/$f"; chown "$SIDECAR_USER": "$LADDER/$f"; chmod 0644 "$LADDER/$f"; done
# The §4.10(f) pull driver runs as this script's own root orchestrator — it must, because it spawns
# the sidecar with `sudo -u` and only root may. Its outputs stay root-owned in the root-owned
# $LADDER, so no service account can write a pull-evidence document. That is the property that
# matters here: `ladder_evidence.py` reads these files, and it must not be reading something the
# principals under test could have authored.
mkdir -p "$LADDER/pull"; chown 0:0 "$LADDER/pull"; chmod 0755 "$LADDER/pull"

# ----- sudoers: the SUPERVISOR may spawn the recorder with ONE argument vector -------------------
# In the §5 kit this grant belongs to the broker, because the broker drives the lifecycle and
# spawns the recorder. In §4.10(d) the supervisor owns the whole of §5 internally, so the spawn is
# its `AcceptanceDriver.execution` seam and the grant moves with it. It is NOT widened: the five
# deployment-static arguments are exact and only the three per-run FILE NAMES are wildcarded.
#
# The wildcards are not the wall. `sudo` does not apply FNM_PATHNAME to command arguments, so `*`
# there matches `/`. The wall is the recorder's own root-owned policy, which pins every path and
# requires the three output names to resolve DIRECTLY inside its own directories. This rule is the
# outer layer: it stops a hostile vector before the trusted binary is entered.
SUDOERS=/etc/sudoers.d/brops-ladder-recorder
# The LADDER DRIVER's own vector (provisioned much later, in its own phase): the BROKER principal
# spawning the one-shot sidecar as the SIDECAR account. Named here so `cleanup` removes it on every
# exit path, including the ones that happen before the phase that writes it.
DRIVER_SUDOERS=/etc/sudoers.d/brops-ladder-driver-sidecar
python3 - "$CONFIG" "$SUPERVISOR_USER" "$RECORDER_USER" "$SUDOERS" \
  <<'PYSUDO' || { echo "FAIL: could not build the recorder sudoers vector"; exit 1; }
import json, sys
cfg = json.load(open(sys.argv[1]))
ex = cfg["execution"]
invoker_user, recorder_user, out_path = sys.argv[2], sys.argv[3], sys.argv[4]
command = ex["recorder_command"]
if command[:1] != ["sudo"] or command[1:4] != ["-n", "-u", recorder_user] or len(command) != 5:
    print("unexpected recorder_command %r" % (command,), file=sys.stderr)
    sys.exit(1)
recorder_bin = command[4]
report_dir = ex["report_dir"]
state_dir = ex["evidence_state_dir"]
for name, d in (("report_dir", report_dir), ("evidence_state_dir", state_dir)):
    if not d.startswith("/") or d.endswith("/") or "//" in d:
        print("%s is not an absolute normalised directory: %r" % (name, d), file=sys.stderr)
        sys.exit(1)
args = [
    "--store", ex["recorder_store_dir"],
    "--launcher", ex["launcher_path"],
    "--executor", ex["executor_path"],
    "--lease", ex["lease_file"],
    "--cgroup", ex["cgroup_arg"],
    # `run_ladder_supervisor.RecorderExecutor` builds these as `<report_dir>/ladder-<attempt>.out`,
    # `<that>.containment.json` and `<state_dir>/<attempt>.evidence.json`. The `ladder-` token is
    # what keeps this grant from also matching the §5 kit's `live-` names.
    "--out", report_dir + "/ladder-*.out",
    "--containment-out", report_dir + "/ladder-*.out.containment.json",
    "--evidence-out", state_dir + "/*.evidence.json",
    "--evidence-state", state_dir,
]
for a in [recorder_bin] + args:
    if any(c in a for c in ",:=\\ \t"):
        print("sudoers argument needs escaping: %r" % a, file=sys.stderr)
        sys.exit(1)
with open(out_path, "w", encoding="utf-8") as fh:
    fh.write("%s ALL=(%s) NOPASSWD: %s %s\n"
             % (invoker_user, recorder_user, recorder_bin, " ".join(args)))
PYSUDO
chmod 0440 "$SUDOERS"
if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$SUDOERS" >/dev/null || { echo "FAIL: the recorder sudoers vector is not valid sudoers"; exit 1; }
fi
echo "== recorder sudo vector (invoker: $SUPERVISOR_USER) =="; cat "$SUDOERS"

# The §2.5 floor's requirement that every ancestor of a pinned artifact be root-owned and
# non-writable is applied even though the floor itself is not evaluated here (see the header): the
# launcher and the recorder both re-check the custody of their own inputs, and /opt is
# drwxrwxrwx on the hosted runner image.
chown 0:0 "$LIVE" "$TCB" "$BIN"; chmod 0755 "$LIVE" "$TCB" "$BIN"
chown -R 0:0 "$LIVE/engine" "$LIVE/bridge"
find "$LIVE/engine" "$LIVE/bridge" -type d -exec chmod 0755 {} +
chown 0:0 /opt; chmod 0755 /opt
if command -v setfacl >/dev/null 2>&1; then setfacl -Rb /opt "$LIVE" 2>/dev/null || true; fi
echo "== TCB ancestor modes =="
ls -ld / /opt "$LIVE" "$TCB" "$BIN" "$LIVE/bridge" "$LIVE/engine/ci/live" /etc /etc/sudoers.d

# ----- start the three service servers -----------------------------------------------------------
PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
  rm -f "$SUDOERS" "$DRIVER_SUDOERS"
}
trap cleanup EXIT

# Each service's stdout+stderr is TEE'd into the evidence directory as well as the job log.
# A supervisor-side fault answers the peer with an op-shaped `{"ok": false, "error": ...}` that
# names no protocol, and the §4.10(g) client keeps only the protocol name from it — so the
# supervisor's own stderr is the account of what actually happened. The first live run of this
# kit had that account nowhere at all: `handle_connection` printed nothing for a caught
# `SupervisorError` (now fixed in engine/runtime/governed_supervisor_server.py), and diagnosing
# it cost a CI round trip. Keeping it in the BUNDLE, not only in the job log, is this script's
# half of that fix.
echo "== starting challenge-authority / LADDER supervisor / isolated-signer =="
# `> >(tee ...)` rather than `| tee ...`: in a pipeline `$!` is the PID of `tee`, so `cleanup`
# would kill the tee and leave the SERVICE running -- holding a socket the next run has already
# unlinked. Process substitution keeps `$!` the service' own PID while still writing both the
# job log and the bundle copy.
start_service() {  # <user> <logfile> <script> <args...>
  local user="$1" log="$2"; shift 2
  sudo -u "$user" env PYTHONUNBUFFERED=1 python3 "$@" > >(tee "$log") 2>&1 &
  PIDS+=($!)
}
start_service "$CHALLENGE_USER"  "$LADDER/authority.log"  "$PYLIVE/run_authority.py" --config "$CONFIG"
start_service "$SUPERVISOR_USER" "$LADDER/supervisor.log" "$PYLIVE/run_ladder_supervisor.py" --config "$CONFIG" --ladder "$LADDER_CONFIG"
start_service "$SIGNER_USER"     "$LADDER/signer.log"     "$PYLIVE/run_signer.py" --config "$CONFIG"

for s in authority supervisor signer; do
  for _ in $(seq 1 200); do [ -S "$SOCK/$s.sock" ] && break; sleep 0.05; done
  [ -S "$SOCK/$s.sock" ] || { echo "FAIL: the $s server did not bind its socket"; exit 1; }
done

# The uids the orchestrator hands each hop, recorded as evidence beside the uids the KERNEL
# reported to the supervisor. The two agreeing is the point; either alone could be a claim.
cat > "$LADDER/uids.json" <<UIDS
{
  "root": 0,
  "challenge_authority": $(id -u "$CHALLENGE_USER"),
  "supervisor": $(id -u "$SUPERVISOR_USER"),
  "signer": $(id -u "$SIGNER_USER"),
  "desktop_broker": $(id -u "$BROKER_USER"),
  "sidecar": $(id -u "$SIDECAR_USER"),
  "recorder": $(id -u "$RECORDER_USER"),
  "executor": $(id -u "$EXECUTOR_USER")
}
UIDS

# ----- one governed round trip: desktop -> sidecar -> supervisor -> contained execution ---------
# `run_turn <submit> <document> <reply> [--tamper]`
#
# Three processes, three principals, and the split is the property under test:
#   * the DESKTOP (broker uid) is the only one the challenge authority's IPC policy admits;
#   * the SIDECAR (its own uid) is the only one the supervisor's four services admit, and it
#     never reaches the authority, the signer or the store;
#   * the SUPERVISOR reaches the recorder, the signer and the store, and nothing reaches it
#     except those two principals on their two disjoint protocol surfaces.
run_turn() {
  local submit="$1" document="$2" reply="$3" tamper="${4:-}"
  echo "-- desktop ($BROKER_USER): obtaining a signed challenge and writing the submit frame"
  sudo -u "$BROKER_USER" python3 "$PYLIVE/ladder_desktop.py" --config "$CONFIG" \
    --ladder "$LADDER_CONFIG" --out "$submit" --document-out "$document" $tamper \
    || { echo "  desktop hop failed"; return 1; }
  echo "-- sidecar ($SIDECAR_USER): driving the §4.10(g) ladder through bridge/engine_sidecar.py"
  # `engine_sidecar.run` ALWAYS exits 0 — the verdict travels in the payload, never in the exit
  # status — so this deliberately does not test `$?`. `ladder_evidence.py` judges the FRAME.
  sudo -u "$SIDECAR_USER" env BROPS_SUPERVISOR_SOCKET="$SOCK/supervisor.sock" \
    python3 "$LIVE/bridge/engine_sidecar.py" < "$submit" > "$reply"
  return 0
}

echo
echo "== POSITIVE: one §4.10(g) round trip, adapter -> real supervisor -> real contained execution =="
run_turn "$LADDER/submit.json" "$LADDER/document.json" "$LADDER/reply.json" \
  || { echo "LADDER ROUND TRIP: RED — the turn could not be driven"; exit 1; }
# ----- the §4.10(f) PULL: the egress half of the turn that just completed ----------------------
# Five runs of ONE driver, each naming the outcome it requires. The driver compares the outcome BY
# NAME and exits non-zero on any other, so a negative cannot be satisfied by a deployment that is
# merely broken and the positive cannot be satisfied by a refusal.
#
#   positive          the real token, the real envelope, replies verbatim          -> ok
#   unknown-stream    one character of the 43-char capability rotated              -> stream_unknown
#   binding-mismatch  the real token with a receipt_id that is not this turn's     -> stream_binding_mismatch
#   tampered-chunk    a compromised sidecar flips one bit of one served chunk      -> digest_mismatch
#   truncated-chunk   a compromised sidecar drops one byte off one served chunk    -> length_mismatch
#
# The first two refusals are the SUPERVISOR's, by their published §4.10(f) literals. The last two
# are the DESKTOP's §4.6/§7.1 whole-output gate against the SIGNED envelope — which is the pair
# that matters, because §2.4 declares the sidecar compromised and the tamper is applied exactly
# where a compromised sidecar sits.
PULL_SIDECAR=(sudo -u "$SIDECAR_USER" env "BROPS_SUPERVISOR_SOCKET=$SOCK/supervisor.sock" \
              python3 "$LIVE/bridge/engine_sidecar.py")
PULL_ARGS=()
PULL_RC=0
run_pull() {  # <mode> <expected-outcome> [extra args...]
  local mode="$1" expect="$2"; shift 2
  echo "-- §4.10(f) pull: mode=$mode expect=$expect"
  if "$PULL_BIN" --frame "$LADDER/reply.json" --evidence-out "$LADDER/pull/$mode.json" \
       --mode "$mode" --expect "$expect" "$@" -- "${PULL_SIDECAR[@]}"; then
    PULL_ARGS+=(--pull-evidence "$LADDER/pull/$mode.json")
  else
    echo "  PULL $mode: RED — it did not produce $expect"
    PULL_RC=1
  fi
}

echo
echo "== §4.10(f) OUTPUT PULL: the signed bytes, chunk by chunk, back through the sidecar =="
if [ "$(python3 -c 'import json,sys; print("1" if json.load(open(sys.argv[1])).get("ok") is True else "0")' \
        "$LADDER/reply.json" 2>/dev/null || echo 0)" = "1" ]; then
  run_pull positive         ok                              --output-out "$LADDER/pulled-output.bin"
  run_pull unknown-stream   refused:stream_unknown
  run_pull binding-mismatch refused:stream_binding_mismatch
  run_pull tampered-chunk   digest_mismatch
  run_pull truncated-chunk  length_mismatch
else
  # No `ok` frame means no minted capability, and §4.10(f) permits exactly one source for one.
  # Inventing a token here is the single thing §4.10(f) says may never happen, so the pull is not
  # driven and this run is RED for the round trip rather than green for a pull that never ran.
  echo "  the round trip produced no ok §4.6 frame: there is no capability to pull with"
  PULL_RC=1
fi

# ONE verifier judges both halves. `ladder_evidence.py` verifies the §4.9 signature FIRST and only
# then compares the pull's expected digest against the envelope it just verified — so "the pull
# gated against the signed value" is a checked fact rather than the driver's own account of itself.
# It also pairs the driver's transcript with the SUPERVISOR's hop log, which records the
# SO_PEERCRED uid of every served range and which the driver cannot write.
POS_OUT=$(python3 "$PYLIVE/ladder_evidence.py" --live-root "$LIVE" \
  --submit "$LADDER/submit.json" --document "$LADDER/document.json" \
  --reply "$LADDER/reply.json" --hop-log "$LADDER/hops.jsonl" --uids "$LADDER/uids.json" \
  --bundle "$LADDER/evidence" ${PULL_ARGS[@]+"${PULL_ARGS[@]}"} 2>&1) && POS_RC=0 || POS_RC=$?
echo "$POS_OUT"

# ----- NEGATIVE: the same harness, a deliberately broken input, and it MUST go RED --------------
# A proof that cannot report PASS is a check that cannot fail with the sign flipped, and BOTH of
# this repository's PowerShell harnesses shipped exactly that defect through three audit rounds.
# So the failing branch is exercised on every run, by the SAME verifier in the SAME mode.
#
# The break is the one §4.10(g) is written against: a `system` the signed challenge does not
# commit to. The submit client deliberately does NOT pre-check the staged digests against the
# challenge — a local pre-check there would make §4.10(a)'s `digest_mismatch` unreachable through
# the only client that exists — so the refusal must come from the SUPERVISOR, by name.
echo
echo "== NEGATIVE: a system the challenge does not commit must not complete a round trip =="
run_turn "$LADDER/submit-tampered.json" "$LADDER/document-tampered.json" \
  "$LADDER/reply-tampered.json" "--tamper" \
  || { echo "NEGATIVE: RED — the tampered turn could not even be driven"; exit 1; }
NEG_OUT=$(python3 "$PYLIVE/ladder_evidence.py" --live-root "$LIVE" \
  --submit "$LADDER/submit-tampered.json" --document "$LADDER/document-tampered.json" \
  --reply "$LADDER/reply-tampered.json" --hop-log "$LADDER/hops.jsonl" --uids "$LADDER/uids.json" \
  --bundle "$LADDER/evidence-negative" 2>&1) && NEG_RC=0 || NEG_RC=$?
echo "$NEG_OUT"


# =================================================================================================
# THE REAL `LadderChain`, DRIVEN FROM RUST — and it is NOT the `brops-broker` binary
# =================================================================================================
#
# Everything above drives the §4.10(g) ladder from PYTHON: `ladder_desktop.py` obtains the challenge
# and writes the submit frame, and `engine_sidecar.py` is fed that frame on stdin. That proves the
# SERVERS. It proves nothing about `brops_broker::ladder_executor::LadderChain` — the object the
# desktop product would actually run — because no Rust in this tree had ever driven it against a
# real supervisor.
#
# This phase does. `target/debug/ladder_turn` builds the SAME chain `build_governed_executor`
# builds — the same `LadderChain`, `LinuxHopConnector`, `SqliteTurnContent`,
# `GovernedSidecar::as_distinct_principal`, `UuidTurnIds` and `DurableAcceptanceLedger` — and runs
# one turn through `run_governed_turn`.
#
# IT IS NOT THE `brops-broker` BINARY, and this banner exists so nobody can cite it as one.
# `build_governed_executor` can only reach `ProductionResolver::provisioned`, which hard-pins the
# Owner's OFFLINE root `brops-tcb-root-1` / `3c83c2bc…`; the one constructor that accepts another
# anchor is `pub(crate)` IN THE LIBRARY, so no binary outside `brops-broker` can reach it (measured:
# `error[E0624]`). Satisfying that pin in CI would need an Owner ceremony with the offline key on
# every run, or the production signer's private half committed to this repository — which would make
# forging a production-class §4.9 envelope trivial against every shipped install. So the driver
# supplies its OWN `KeyResolver` over the kit's TCB root-anchor FILE, carrying that file's DECLARED
# provenance, exactly as `proof/src/bin/live_turn.rs` already does. That is honest for one reason
# and one only: a `kit_generated` anchor may never render `production_verified=true` —
# `resolve_trust_state` will not build a `TrustState::Production` from it — so this phase cannot
# report production custody however it is read.
#
# Four more things it is not: there is no renderer socket and no `SO_PEERCRED` on a renderer→broker
# hop (the request is built in-process); `$BROPS_BROKER_CONFIG` is never read (the config arrives as
# `--config`); the §2.5 TCB floor is not evaluated, for the reason this script's header already
# gives about `build_tcb_pin_manifest.py`; and the custody resolver that lets `persist_committed`
# commit is wired by the DRIVER. The shipped broker calls `ChainExecutor::new`, gets
# `UnresolvedCustody`, and commits nothing. **Nothing in this phase changes that.** No gate is
# flipped: `governed_verification_unconfigured`, `UpstreamBlockedExecutor` and `connect_broker` are
# untouched, and nothing here makes any of them reachable in the product.
echo
echo "================================================================================"
echo "== LADDER DRIVER: the REAL LadderChain, from Rust — NOT the brops-broker binary =="
echo "================================================================================"

DRIVER_RC=0
# The driver runs AS THE BROKER PRINCIPAL, so it has to live somewhere that principal can traverse
# and execute. The build tree does not qualify: on a runner it sits under a home directory the
# service accounts have no path into, and the first live run of this phase died there with
# `env: '.../target/debug/ladder_turn': Permission denied`. Installed root-owned and non-writable
# inside the kit, exactly as the launcher, the executor image and the recorder are.
install -m 0755 "$DRIVER_BIN" "$BIN/ladder_turn"; chown 0:0 "$BIN/ladder_turn"
DRIVER_EXE="$BIN/ladder_turn"
DRIVERDIR="$LADDER/driver"
mkdir -p "$DRIVERDIR"; chown 0:0 "$DRIVERDIR"; chmod 0755 "$DRIVERDIR"
# The child's working directory. `GovernedSidecar` requires an empty sandbox so the sidecar cannot
# pick up a nearby project's configuration; ROOT-owned is the tighter reading of "owner-only" here,
# because then no service account can plant one. World-executable because two principals enter it:
# the broker `chdir`s before the principal switch and the sidecar's interpreter `getcwd`s after it.
SANDBOX="$DRIVERDIR/sandbox"
mkdir -p "$SANDBOX"; chown 0:0 "$SANDBOX"; chmod 0755 "$SANDBOX"
mkdir -p "$DRIVERDIR/evidence"; chown 0:0 "$DRIVERDIR/evidence"; chmod 0755 "$DRIVERDIR/evidence"
# One evidence directory per run, owned by the principal that writes it (the same "one owner each"
# discipline audit F-07/F-28 imposed on the rest of this kit).
for d in positive rollback rollback-sign-flip floor-unwritable floor-sign-flip \
         no-authority; do
  mkdir -p "$DRIVERDIR/$d"; chown "$BROKER_USER": "$DRIVERDIR/$d"; chmod 0755 "$DRIVERDIR/$d"
done

# ----- INHERITED FINDING, fixed in the KIT rather than papered over in the code -----------------
# `provision_keys.py` writes `trust.floor_path` as $LIVE/floor.json — root-owned 0644, inside a
# root-owned 0755 directory. `check_and_persist` advances the anti-rollback floor and WRITES IT BACK
# by temp-file + rename in that same directory, and a persist failure REFUSES the turn. That refusal
# is correct and is NOT weakened here. What is wrong is the ownership: `broker/src/main.rs` already
# states the requirement this kit violates — floor_path "MUST be owned by / writable only by the
# broker service principal (file mode 0600, dedicated UID)". So the driver's floor moves into the
# broker's own 0700 state directory, and the `floor-unwritable` control below drives the ORIGINAL
# root-owned path and REQUIRES `blocked:keys:floor_not_persisted` — which makes the finding a
# measured fact on every run rather than a sentence in a report.
BROKERSTATE="$LIVE/broker-state"
chown -R "$BROKER_USER": "$BROKERSTATE"; chmod 0700 "$BROKERSTATE"
BROKER_FLOOR="$BROKERSTATE/floor.json"
ROLLED_FLOOR="$BROKERSTATE/floor-rolled-forward.json"
BROKER_DB="$BROKERSTATE/ladder-driver.db"
MESSAGES_DB="$BROKERSTATE/messages.db"
cp "$LIVE/floor.json" "$BROKER_FLOOR"
chown "$BROKER_USER": "$BROKER_FLOOR"; chmod 0600 "$BROKER_FLOOR"

# ----- the conversation, as ONE row in the desktop's own schema --------------------------------
# `SqliteTurnContent` reads `messages` (migration 0003). The fixture is a real row in the real
# schema — the migration file is applied verbatim, never re-spelled here — and it carries exactly
# what this kit already stages: one `user` message whose body is `hi`. NOTHING about a digest is
# written into it or into the driver's config: `prepare_governed_turn_v1b` derives all three from
# the bytes this turn actually sends, which is the whole reason the ladder replaced the direct path.
SCHEMA="$REPO_ROOT/apps/desktop/src-tauri/core/schema/0003_conversations.sql"
[ -f "$SCHEMA" ] || { echo "FAIL: the conversations migration is missing at $SCHEMA"; exit 1; }
python3 - "$SCHEMA" "$MESSAGES_DB" "$CONFIG" "$LADDER_CONFIG" <<'PYFIXTURE' \
  || { echo "FAIL: could not stage the conversation fixture"; exit 1; }
import json, os, sqlite3, sys

schema_path, db_path, config_path, ladder_path = sys.argv[1:5]
cfg = json.load(open(config_path, encoding="utf-8"))
ladder = json.load(open(ladder_path, encoding="utf-8"))
conversation_id = cfg["resolved"]["conversation_id"]
history = ladder["turn"]["history"]
# ONE definition of the turn (`provision_ladder.py` wrote it). A second copy here is exactly how a
# staged digest and a pinned digest come to disagree.
if len(history) != 1 or history[0]["role"] != "user":
    raise SystemExit("this fixture stages ONE user message; ladder.json's turn is %r" % (history,))
try:
    os.unlink(db_path)
except OSError:
    pass
conn = sqlite3.connect(db_path)
conn.executescript(open(schema_path, encoding="utf-8").read())
conn.execute(
    "INSERT INTO conversations (id, kind, title, created_at, updated_at) VALUES (?,?,?,?,?)",
    (conversation_id, "direct", "the ladder driver's governed turn",
     "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
conn.execute(
    "INSERT INTO messages (id, conversation_id, role, author, body, created_at) VALUES (?,?,?,?,?,?)",
    ("m-ladder-driver-1", conversation_id, history[0]["role"], "gev", history[0]["content"],
     "2026-01-01T00:00:01Z"))
conn.commit()
conn.close()
print("staged 1 conversation + 1 message (%s / role=%s) in %s"
      % (conversation_id, history[0]["role"], db_path))
PYFIXTURE
chown "$BROKER_USER": "$MESSAGES_DB"; chmod 0600 "$MESSAGES_DB"

# The fixture and the STAGED bytes must be one conversation, asserted here rather than discovered
# as a §4.10(a) `digest_mismatch` in the middle of a turn. The digests are re-derived from the DB
# ROWS with the submit client's own public formulas (`brops_canonical`) and compared against the
# digests the launcher's lease pins. Nothing is copied into the driver's config from this check.
python3 - "$MESSAGES_DB" "$CONFIG" "$LADDER_CONFIG" <<'PYAGREE' \
  || { echo "FAIL: the conversation fixture and the staged bytes are different turns"; exit 1; }
import json, os, sqlite3, sys
sys.path.insert(0, "/opt/brops-live/engine/runtime")
import brops_canonical as bc

db_path, config_path, ladder_path = sys.argv[1:4]
cfg = json.load(open(config_path, encoding="utf-8"))
ladder = json.load(open(ladder_path, encoding="utf-8"))
conn = sqlite3.connect(db_path)
rows = conn.execute(
    "SELECT role, body FROM messages WHERE conversation_id = ? ORDER BY created_at DESC, id DESC "
    "LIMIT 8", (cfg["resolved"]["conversation_id"],)).fetchall()
conn.close()
rows.reverse()  # chronological — the order `SqliteTurnContent` sends, and therefore hashes
derived = {
    "system": bc.sha256_hex(bc.system_bytes(ladder["turn"]["system"])),
    "history": bc.sha256_hex(bc.history_bytes([{"role": r, "content": b} for r, b in rows])),
    "generation_config": bc.sha256_hex(
        bc.governed_generation_config_bytes(ladder["turn"]["generation_config"])),
}
bad = {name: (value, ladder["turn"]["digests"].get(name),
              cfg["resolved"].get(name + "_sha256"))
       for name, value in derived.items()
       if not (value == ladder["turn"]["digests"].get(name)
               == cfg["resolved"].get(name + "_sha256"))}
if bad:
    print("derived / staged / launcher-pinned digests disagree: %r" % (bad,), file=sys.stderr)
    raise SystemExit(1)
print("the fixture derives the STAGED digests: system=%s history=%s generation_config=%s"
      % (derived["system"], derived["history"], derived["generation_config"]))
PYAGREE

# ----- the driver's own deployment config -------------------------------------------------------
# A SEPARATE file, root-owned and non-writable, rather than an edit to `config.json`: the three
# services are already running against that one, and a proof phase must not be able to move ground
# under the phases that ran before it. The three variants below differ in exactly ONE key each, so
# what a negative demonstrates cannot be confused with a second change.
PYTHON_BIN="$(command -v python3)"
SUDO_BIN="$(command -v sudo)"
ENV_BIN="$(command -v env)"
for b in "$PYTHON_BIN" "$SUDO_BIN" "$ENV_BIN"; do
  case "$b" in /*) ;; *) echo "FAIL: python3/sudo/env must resolve to absolute paths (got '$b')"; exit 1;; esac
done
DRIVER_CONFIG="$TCB/ladder-driver.json"
DRIVER_CONFIG_ROLLBACK="$TCB/ladder-driver-rolled-forward-floor.json"
DRIVER_CONFIG_ROOTFLOOR="$TCB/ladder-driver-root-owned-floor.json"
DRIVER_CONFIG_NOAUTH="$TCB/ladder-driver-no-authority.json"
python3 - "$CONFIG" "$LADDER_CONFIG" "$MESSAGES_DB" "$SANDBOX" "$SIDECAR_USER" \
  "$PYTHON_BIN" "$SUDO_BIN" "$ENV_BIN" "$LIVE/bridge/engine_sidecar.py" \
  "$BROKER_FLOOR" "$ROLLED_FLOOR" "$LIVE/floor.json" "$BROKER_DB" \
  "$DRIVER_CONFIG" "$DRIVER_CONFIG_ROLLBACK" "$DRIVER_CONFIG_ROOTFLOOR" \
  "$DRIVER_CONFIG_NOAUTH" \
  <<'PYCFG' || { echo "FAIL: could not build the ladder-driver configs"; exit 1; }
import json, sys

(config_path, ladder_path, messages_db, sandbox, sidecar_user, python_bin, sudo_bin, env_bin,
 sidecar_script, broker_floor, rolled_floor, root_floor, broker_db,
 out_main, out_rollback, out_rootfloor, out_noauth) = sys.argv[1:18]

cfg = json.load(open(config_path, encoding="utf-8"))
ladder = json.load(open(ladder_path, encoding="utf-8"))

# `content.system` is the agent's system prompt and it is CONFIGURED; `history` is the user's
# conversation and it is NOT. That asymmetry is the point: the defect the ladder replaced was not
# "a value came from config", it was that `system_sha256` was itself a config value. Here the
# string is configured and the digest is computed from it, so the two cannot diverge — and the
# string is taken from `ladder.json`, so this kit still has ONE definition of the turn.
cfg["content"] = {
    "messages_db": messages_db,
    "system": ladder["turn"]["system"],
    # More than the fixture holds, deliberately: a window pinned to the row count would make
    # `read_window`'s LIMIT untestable, and a window that reaches past the conversation must
    # return the conversation rather than an error.
    "window": 8,
}
# §2.6. `SidecarPrincipal::from_config` validates every one of these and has no value meaning "as
# me": absolute program, a prefix that NAMES the account, and a trailing `env` (the principal
# switch resets the environment, so `BROPS_SUPERVISOR_SOCKET` has to travel as an argument).
cfg["sidecar"] = {
    "python": python_bin,
    "script": sidecar_script,
    "cwd": sandbox,
    "principal": sidecar_user,
    "invoker": [sudo_bin, "-n", "-u", sidecar_user, env_bin],
}
cfg["trust"]["floor_path"] = broker_floor
cfg["db"] = {"path": broker_db}
# The anchor is a TCB FILE and must stay one: `trust.root_pub_hex` / `trust.root_key_id` inline in
# the config is refused by the driver outright, so assert their absence where the message is about
# provisioning rather than reading it as `blocked:setup:config_carries_inline_root_anchor`.
if "root_pub_hex" in cfg["trust"] or "root_key_id" in cfg["trust"]:
    raise SystemExit("the kit config carries an inline root anchor; the driver refuses that")

def write(path, document):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, sort_keys=True)

write(out_main, cfg)

# Variant 1 — the anti-rollback floor rolled FORWARD past the manifest. `check_and_advance` refuses
# `EpochBelowFloor` before a single hop is made.
manifest = json.load(open(cfg["trust"]["manifest_path"], encoding="utf-8"))
floor = json.load(open(broker_floor, encoding="utf-8"))
with open(rolled_floor, "w", encoding="ascii") as fh:
    json.dump({"highest_epoch": manifest["manifest_epoch"] + 1,
               "highest_hash": floor["highest_hash"]}, fh)
rollback = json.loads(json.dumps(cfg))
rollback["trust"]["floor_path"] = rolled_floor
write(out_rollback, rollback)

# Variant 2 — the kit's ORIGINAL root-owned floor. The CAS passes (same epoch, same hash) and the
# PERSIST cannot: the broker principal may not create a temp file in a root-owned 0755 directory.
rootfloor = json.loads(json.dumps(cfg))
rootfloor["trust"]["floor_path"] = root_floor
write(out_rootfloor, rootfloor)

# Variant 3 — an authority socket that is not there. The §4.1 hop must fail and must be
# attributed to the CHALLENGE AUTHORITY by name.
noauth = json.loads(json.dumps(cfg))
noauth["sockets"]["authority"] = cfg["sockets"]["authority"] + ".absent"
write(out_noauth, noauth)

print("driver configs: %s (+ rolled-forward floor, + root-owned floor, + absent authority)"
      % out_main)
PYCFG
chown 0:0 "$DRIVER_CONFIG" "$DRIVER_CONFIG_ROLLBACK" "$DRIVER_CONFIG_ROOTFLOOR" \
         "$DRIVER_CONFIG_NOAUTH"
chmod 0644 "$DRIVER_CONFIG" "$DRIVER_CONFIG_ROLLBACK" "$DRIVER_CONFIG_ROOTFLOOR" \
          "$DRIVER_CONFIG_NOAUTH"
chown "$BROKER_USER": "$ROLLED_FLOOR"; chmod 0600 "$ROLLED_FLOOR"

# ----- sudoers: the BROKER may become the SIDECAR with ONE exact argument vector ----------------
# §2.6 requires the seven principals to be pairwise distinct, and every supervisor surface the
# submit and the §4.10(f) pull knock on gates on the SIDECAR uid — so a broker-spawned-as-broker
# sidecar is refused at the first hop, and a deployment that "fixes" that by naming the broker uid
# as the sidecar is refused at the door by `handle_connection`'s principal-collapse check. There is
# no third arrangement, which is why this grant exists and why it is EXACT: no wildcard, because
# `GovernedSidecar::command` builds a fully determined argv for a relay spawn (the trust set is
# empty under `SidecarTrust::RelayFramesOnly`, so the only assignment is the supervisor socket).
python3 - "$BROKER_USER" "$SIDECAR_USER" "$ENV_BIN" "$SOCK/supervisor.sock" "$PYTHON_BIN" \
  "$LIVE/bridge/engine_sidecar.py" "$DRIVER_SUDOERS" \
  <<'PYDRVSUDO' || { echo "FAIL: could not build the driver's sidecar sudoers vector"; exit 1; }
import sys

invoker_user, sidecar_user, env_bin, socket_path, python_bin, script, out_path = sys.argv[1:8]

def escape(token: str) -> str:
    # sudoers(5): these characters must be escaped with a backslash when they appear inside a word.
    out = []
    for ch in token:
        if ch in ",:=\\":
            out.append("\\")
        out.append(ch)
    return "".join(out)

args = ["BROPS_SUPERVISOR_SOCKET=" + socket_path, python_bin, script]
for token in [env_bin] + args:
    if any(c in token for c in " \t\n"):
        raise SystemExit("a sudoers command token contains whitespace: %r" % token)
with open(out_path, "w", encoding="utf-8") as fh:
    fh.write("%s ALL=(%s) NOPASSWD: %s %s\n"
             % (invoker_user, sidecar_user, escape(env_bin),
                " ".join(escape(a) for a in args)))
PYDRVSUDO
chmod 0440 "$DRIVER_SUDOERS"
if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$DRIVER_SUDOERS" >/dev/null \
    || { echo "FAIL: the driver's sidecar sudoers vector is not valid sudoers"; exit 1; }
fi
echo "== ladder-driver sudo vector (invoker: $BROKER_USER) =="; cat "$DRIVER_SUDOERS"

# ----- the runs ---------------------------------------------------------------------------------
# `env -u` on the three governance path variables: `GovernedSidecar::command` forwards any that are
# SET as further `NAME=VALUE` arguments, and the sudoers vector above is exact. Unsetting them keeps
# a stray value in the runner's environment from turning a governed verdict into a sudo refusal.
DRIVER_ENV=(env -u BROPS_GOVERNANCE_STATE_DIR -u BROPS_GOVERNANCE_EVIDENCE_STORE \
            -u BROPS_GOVERNANCE_REGISTRY_ROOT "BROPS_SUPERVISOR_SOCKET=$SOCK/supervisor.sock")

# §2.4 caps LIVE `governed_turn_staging` rows at MAX_CONCURRENT_GOVERNED_TURNS = 2 PER INSTALL,
# where LIVE means `challenge_expires_at_ms >= now`. It is a real gate and it fired on the first
# live run of this phase: the two Python-driven turns above were still inside their 30 s challenge
# TTL, so §4.10(a0) refused `quota_turns` and the driver never reached the supervisor's own verdict.
#
# Waiting for a slot is the honest response. These turns are SEQUENTIAL, not concurrent — the
# earlier ones have completed and only their TTL is still running — and the two alternatives are
# both arrangements for the gate not to apply: a second `install_id` (a different installation,
# which this is not) or a wider cap (editing the rule the control exists to respect). The count is
# read from the SUPERVISOR's own 0700 ledger, by root, with the ledger's own LIVE predicate.
SUP_LEDGER=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["supervisor"]["ledger_db"])' "$CONFIG")
INSTALL_ID=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["resolved"]["install_id"])' "$CONFIG")
live_turn_count() {
  python3 - "$SUP_LEDGER" "$INSTALL_ID" <<'PYSLOT'
import sqlite3, sys, time
try:
    conn = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
    row = conn.execute(
        "SELECT COUNT(*) FROM governed_turn_staging "
        "WHERE install_id = ? AND challenge_expires_at_ms >= ?",
        (sys.argv[2], int(time.time() * 1000))).fetchone()
    conn.close()
    print(int(row[0]))
except Exception:
    # Unreadable is NOT "zero": say so, and let the caller decide rather than proceed on a guess.
    print(-1)
PYSLOT
}
wait_for_turn_slot() {  # <label>
  local label="$1" waited=0 live
  while :; do
    live=$(live_turn_count)
    if [ "$live" = "-1" ]; then
      echo "  (the supervisor ledger is unreadable from here; not waiting before $label)"
      return 0
    fi
    [ "$live" -lt 2 ] && return 0
    if [ "$waited" -ge 70 ]; then
      echo "  SLOT $label: RED — still $live LIVE §2.4 turns for $INSTALL_ID after ${waited}s"
      return 1
    fi
    echo "  waiting for a §2.4 turn slot before $label ($live LIVE staging rows for $INSTALL_ID)"
    sleep 5; waited=$((waited + 5))
  done
}

run_driver() {  # <label> <config> <expect> [NAME=VALUE ...]
  local label="$1" cfg="$2" expect="$3"; shift 3
  echo
  echo "-- driver: $label  (expect=$expect)"
  if sudo -u "$BROKER_USER" "${DRIVER_ENV[@]}" "$@" "$DRIVER_EXE" \
       --config "$cfg" --evidence-dir "$DRIVERDIR/$label" --expect "$expect"; then
    return 0
  fi
  echo "  DRIVER $label: RED — it did not produce $expect"
  DRIVER_RC=1
}

# The SIGN FLIP, in both directions. Same driver, same deployment, the expectation inverted: the run
# MUST exit non-zero AND the outcome it recorded must be the one this control names. A control that
# accepted any non-zero exit would pass on a deployment that is merely broken, which is the defect
# that made three of the §5 kit's negatives report GREEN while the property was never reached.
run_driver_sign_flip() {  # <label> <config> <wrong-expectation> <outcome-it-must-record> [NAME=VALUE ...]
  local label="$1" cfg="$2" expect="$3" want="$4"; shift 4
  echo
  echo "-- driver SIGN-FLIP: $label  (expect=$expect, which must NOT be met)"
  if sudo -u "$BROKER_USER" "${DRIVER_ENV[@]}" "$@" "$DRIVER_EXE" \
       --config "$cfg" --evidence-dir "$DRIVERDIR/$label" --expect "$expect"; then
    echo "  SIGN-FLIP $label: RED — the driver exited 0 for an expectation it did not meet."
    echo "    A harness that cannot report failure has not reported success either."
    DRIVER_RC=1
    return
  fi
  local got
  got=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["outcome"])' \
        "$DRIVERDIR/$label/ladder-turn.json" 2>/dev/null || echo "(unreadable)")
  if [ "$got" = "$want" ]; then
    echo "  SIGN-FLIP $label: GREEN — non-zero, and it recorded outcome=$got against expect=$expect"
  else
    echo "  SIGN-FLIP $label: RED — non-zero, but it recorded outcome=$got, not $want"
    DRIVER_RC=1
  fi
}

# POSITIVE: one governed turn, all the way to a committed row. It goes FIRST because §2.4's
# staging budget is finite and this is what the budget is for — see the note below.
wait_for_turn_slot positive || DRIVER_RC=1
run_driver positive "$DRIVER_CONFIG" committed

# ----- the CUSTODY line, ASSERTED rather than printed --------------------------------------------
# The entire justification for a kit-anchored driver is that a `kit_generated` anchor CANNOT render
# production custody: `resolve_trust_state` will not build a `TrustState::Production` from one, so
# `committed_label()` is `demonstration_custody` and `production_verified` is false. Everything this
# phase claims rests on that, and a claim nothing checks is the class of defect this repository has
# now found more than once. So it is checked, on the driver's own recorded evidence, against three
# values at once — and a run that reported production here is a RED, not a note, because it would be
# exactly the substitution this shape exists to make impossible.
DRIVER_CUSTODY_RC=1
python3 - "$DRIVERDIR/positive/ladder-turn.json" <<'PYCUSTODY' && DRIVER_CUSTODY_RC=0 || DRIVER_CUSTODY_RC=$?
import json, sys
document = json.load(open(sys.argv[1], encoding="utf-8"))
required = {
    "outcome": "committed",
    "bound": True,
    "chain_bound": True,
    # The three that carry the honesty of the whole phase.
    "production_verified": False,
    "root_anchor_provenance": "kit_generated",
    "committed_trust_state": "demonstration_custody",
    # ...and the driver's own statement about what it is.
    "is_the_brops_broker_binary": False,
}
bad = {k: (document.get(k), v) for k, v in required.items() if document.get(k) != v}
if bad:
    print("the driver's committed turn is not honestly labelled (got, required): %r" % (bad,),
          file=sys.stderr)
    raise SystemExit(1)
print("  CUSTODY: committed as `demonstration_custody` under a kit_generated anchor; "
      "production_verified=false, bound=true — a complete chain run, not a production claim")
PYCUSTODY

# ----- MEASURED LIMIT, and why there is exactly ONE opening run above ---------------------------
# §2.4 caps `governed_turn_staging_session` rows at MAX_STAGING_SESSIONS_PER_INSTALL = 6 per
# install, and `count_install_sessions` counts them through the parent staging row with NO liveness
# predicate. `governed_staging_ledger.py` contains no `DELETE` at all — §2.4 makes staging recovery
# "operator-sweep only" and no sweeper is implemented anywhere in this tree — so a session is
# consumed for the LIFE of the deployment. A completing turn stages three artifacts, so this kit
# supports exactly TWO completing governed turns per install, ever.
#
# That was measured here, not read: the second live run of this phase reported
# `staging-open refused the governed turn: quota_sessions` on its second opening run, with the
# supervisor's ledger holding 6 ARTIFACT_READY sessions under two challenge handles — the Python
# POSITIVE above, and the driver POSITIVE. (The Python NEGATIVE consumes none: `staging-open` refuses
# the tampered `system` before a session row exists.)
#
# So the driver's remaining controls are the ones that do NOT open a turn. A §4.5 supervisor verdict
# reached through the whole ladder — `model_profile_unknown`, via §4.10(g)'s trusted-host
# `BROPS_GOVERNED_*` override putting a `generation_config` outside this supervisor's §2 execution
# allowlist — was written, driven, and reached `quota_sessions` instead. It is NOT in this script,
# because there is no honest way to run it here: a second `install_id` would be a claim that another
# installation ran the turn, and raising the LOCKED §2.4 literal would edit the rule the control
# exists to respect. Naming what cannot run beats a control that quietly proves something else.
#
# What that costs, stated rather than left to be discovered: nothing in this phase drives a §4.6
# `ok:false` frame, so `ladder_turn`'s `governed_refusal` extractor is UNEXERCISED here. A mutation
# pass confirmed it — deleting that extractor survives every control in this script. It is the one
# seam of the driver whose behaviour rests on the engine suite rather than on this kit.
python3 -c 'import sqlite3,sys
c = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
n = c.execute("SELECT COUNT(*) FROM governed_turn_staging_session s JOIN governed_turn_staging t"
              " ON t.challenge_handle = s.challenge_handle WHERE t.install_id = ?",
              (sys.argv[2],)).fetchone()[0]
print("  §2.4 staging sessions consumed by %s: %d of 6 (never swept: the ledger has no DELETE)"
      % (sys.argv[2], n))' "$SUP_LEDGER" "$INSTALL_ID" || true

# NEGATIVE 1 — anti-rollback. A floor above the manifest's epoch. `check_and_advance` refuses before
# a hop is made, and the refusal is named by the stage that made it.
run_driver rollback "$DRIVER_CONFIG_ROLLBACK" blocked:keys:anti_rollback

# NEGATIVE 2 — the inherited kit finding, measured. The CAS passes and the PERSIST cannot, because
# the broker principal may not write the kit's root-owned floor. `check_and_persist` refuses, and
# this control is what stops that refusal from being "fixed" by weakening the persist.
run_driver floor-unwritable "$DRIVER_CONFIG_ROOTFLOOR" blocked:keys:floor_not_persisted

# NEGATIVE 3 — the §4.1 hop is REAL. Point the driver at an authority socket that is not there and
# the turn must die naming the CHALLENGE AUTHORITY, not "something upstream": `LadderChain` collapses
# every hop failure to `UpstreamBlocked`, so an unattributed Block here would be indistinguishable
# from a supervisor refusal, a sidecar crash or a bad key. It costs no §2.4 staging session.
run_driver no-authority "$DRIVER_CONFIG_NOAUTH" blocked:hop:challenge_authority:Unavailable

# The two sign flips, and they test DIFFERENT failures of the same comparator.
#
#   (a) a run that BLOCKED must not satisfy `--expect committed`. That is the direction that makes a
#       harness report PASS while the property failed, and it is the one both of this repository's
#       PowerShell harnesses got wrong through three audit rounds.
#   (b) a run that blocked for reason A must not satisfy `--expect blocked:<reason B>`. That is the
#       realistic near-miss: a comparator that matched any refusal against any refusal would pass
#       every negative in this phase while proving none of them.
run_driver_sign_flip rollback-sign-flip "$DRIVER_CONFIG_ROLLBACK" \
  committed blocked:keys:anti_rollback
run_driver_sign_flip floor-sign-flip "$DRIVER_CONFIG_ROOTFLOOR" \
  blocked:keys:anti_rollback blocked:keys:floor_not_persisted

# ----- ONE verifier judges the driver's turn too -------------------------------------------------
# The same `ladder_evidence.py`, in the same mode, on the frames the DRIVER recorded. It verifies
# the §4.9 signature under the manifest-resolved production key, recomputes `request_sha256` from
# this turn's three staged digests, reads the SUPERVISOR's own durable ledger for `COMPLETED`, reads
# the RECORDER's containment report for `launcher_exit=0`, and pairs all of it with the supervisor's
# hop log — which records the `SO_PEERCRED` uid of every served frame and which the driver cannot
# write. That last part is the half the driver could never author.
DRIVER_EV_RC=1
if [ -s "$DRIVERDIR/positive/submit-frame.json" ] && [ -s "$DRIVERDIR/positive/result-frame.json" ]; then
  # `challenge_doc_b64` is the EXACT bytes the authority signed — `ChallengeDocument` holds them and
  # the frame carries them verbatim — so this is a transport decode of the driver's own evidence,
  # not a re-encoding by a third party.
  python3 - "$DRIVERDIR/positive/submit-frame.json" "$DRIVERDIR/positive/challenge-document.json" \
    <<'PYDOC' || echo "  could not decode the challenge document from the driver's submit frame"
import base64, json, sys
frame = json.load(open(sys.argv[1], encoding="utf-8"))
raw = frame["challenge_doc_b64"]
document = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(document, fh, indent=2, sort_keys=True)
PYDOC
  DRV_OUT=$(python3 "$PYLIVE/ladder_evidence.py" --live-root "$LIVE" \
    --submit "$DRIVERDIR/positive/submit-frame.json" \
    --document "$DRIVERDIR/positive/challenge-document.json" \
    --reply "$DRIVERDIR/positive/result-frame.json" \
    --hop-log "$LADDER/hops.jsonl" --uids "$LADDER/uids.json" \
    --bundle "$DRIVERDIR/evidence" 2>&1) && DRIVER_EV_RC=0 || DRIVER_EV_RC=$?
  echo "$DRV_OUT"
else
  echo "  the driver recorded no submit/result frame: there is nothing to verify"
fi

# ----- the digests were DERIVED, and here is the arithmetic that says so -------------------------
# Re-hash the three fields the driver's frame actually carried and require each to equal the digest
# the kit staged and the launcher's lease pins. This is the property the ladder exists for: on the
# direct path `system_sha256` IS a config value and this comparison would be vacuous, because the
# config would be both sides of it. Here the frame's bytes came out of a SQLite row and two frozen
# Rust literals, and this is the first time anything compares them to the staged bytes.
DRIVER_DERIVE_RC=1
if [ -s "$DRIVERDIR/positive/submit-frame.json" ]; then
  python3 - "$DRIVERDIR/positive/submit-frame.json" "$LADDER_CONFIG" "$CONFIG" <<'PYDERIVE' \
    && DRIVER_DERIVE_RC=0 || DRIVER_DERIVE_RC=$?
import json, sys
sys.path.insert(0, "/opt/brops-live/engine/runtime")
import brops_canonical as bc

frame = json.load(open(sys.argv[1], encoding="utf-8"))
ladder = json.load(open(sys.argv[2], encoding="utf-8"))
cfg = json.load(open(sys.argv[3], encoding="utf-8"))
derived = {
    "system": bc.sha256_hex(bc.system_bytes(frame["system"])),
    "history": bc.sha256_hex(bc.history_bytes(frame["history"])),
    "generation_config": bc.sha256_hex(
        bc.governed_generation_config_bytes(frame["generation_config"])),
}
ok = True
for name, value in derived.items():
    staged = ladder["turn"]["digests"].get(name)
    pinned = cfg["resolved"].get(name + "_sha256")
    if not (value == staged == pinned):
        print("RED %s: the frame hashes to %s, the kit staged %s, the lease pins %s"
              % (name, value, staged, pinned), file=sys.stderr)
        ok = False
# The Rust `generation_config` literals and the kit's object are the same five strings, asserted on
# the bytes that were actually sent rather than on two constants that happen to agree today.
if frame["generation_config"] != ladder["turn"]["generation_config"]:
    print("RED generation_config: the frame carried %r, the kit staged %r"
          % (frame["generation_config"], ladder["turn"]["generation_config"]), file=sys.stderr)
    ok = False
if not ok:
    raise SystemExit(1)
print("DERIVED: the driver's frame hashes to the staged, launcher-pinned digests "
      "(system=%s history=%s generation_config=%s)"
      % (derived["system"], derived["history"], derived["generation_config"]))
PYDERIVE
else
  echo "  no submit frame: the derivation check has nothing to hash"
fi

# ----- evidence out ------------------------------------------------------------------------------
# Copied into the workspace so CI can upload it and a reader can check the signature without root.
EVIDENCE_OUT="${LADDER_EVIDENCE_OUT:-${RUNNER_TEMP:-/tmp}/ladder-evidence}"
rm -rf "$EVIDENCE_OUT"; mkdir -p "$EVIDENCE_OUT"
cp -r "$LADDER/evidence" "$EVIDENCE_OUT/positive" 2>/dev/null || true
cp -r "$LADDER/evidence-negative" "$EVIDENCE_OUT/negative" 2>/dev/null || true
cp "$LADDER/hops.jsonl" "$LADDER/uids.json" "$EVIDENCE_OUT/" 2>/dev/null || true
cp -r "$LADDER/pull" "$EVIDENCE_OUT/pull" 2>/dev/null || true
# The LADDER DRIVER's bundle: the frames it recorded, its own evidence document per run, the
# authority hop transcript, and the verdict `ladder_evidence.py` returned on its turn.
cp -r "$LADDER/driver" "$EVIDENCE_OUT/driver" 2>/dev/null || true
cp "$DRIVER_CONFIG" "$EVIDENCE_OUT/ladder-driver-config.json" 2>/dev/null || true
cp "$DRIVER_SUDOERS" "$EVIDENCE_OUT/ladder-driver-sudoers" 2>/dev/null || true
cp "$LADDER/pulled-output.bin" "$EVIDENCE_OUT/" 2>/dev/null || true
cp "$LADDER"/authority.log "$LADDER"/supervisor.log "$LADDER"/signer.log "$EVIDENCE_OUT/" 2>/dev/null || true
cp "$TCB/challenge-key-registry.json" "$LADDER_CONFIG" "$EVIDENCE_OUT/" 2>/dev/null || true
chmod -R a+rX "$EVIDENCE_OUT"
echo
echo "== evidence recorded under $EVIDENCE_OUT =="
ls -R "$EVIDENCE_OUT" | head -40

# ----- verdict -----------------------------------------------------------------------------------
RC=0
echo
echo "=========================== §4.10(g) ladder round trip ==========================="
if [ "$POS_RC" = "0" ]; then
  echo "POSITIVE: GREEN — one submit frame became one §4.6 frame whose envelope verifies,"
  echo "  through the real services, with the real contained execution."
else
  echo "POSITIVE: RED — the governed round trip did not complete (fail-closed, nothing fabricated)"
  RC=1
fi

# The §4.10(f) egress, reported separately from the round trip: a turn can complete and its output
# still be unreachable, and one verdict covering both would hide which of the two happened.
if [ "$PULL_RC" = "0" ]; then
  echo "PULL: GREEN — the signed output was pulled through §4.10(f), chunk by chunk, from the"
  echo "  supervisor through the sidecar; and four controls were refused BY NAME"
  echo "  (stream_unknown, stream_binding_mismatch, digest_mismatch, length_mismatch)."
else
  echo "PULL: RED — the §4.10(f) pull did not produce the outcomes it required (see above)."
  RC=1
fi

# The LADDER DRIVER, reported separately from the Python-driven ladder above. They prove different
# halves — the servers, and the Rust object the product would run — and one verdict covering both
# would hide which of the two happened.
if [ "$DRIVER_RC" = "0" ] && [ "$DRIVER_EV_RC" = "0" ] && [ "$DRIVER_DERIVE_RC" = "0" ] \
   && [ "$DRIVER_CUSTODY_RC" = "0" ]; then
  echo "DRIVER: GREEN — the REAL brops_broker::ladder_executor::LadderChain (driven by"
  echo "  brops-governed-live/ladder_turn, which is NOT the brops-broker binary) took one governed"
  echo "  turn to a committed row through the real services and the real contained execution;"
  echo "  its three artifact digests were DERIVED from a SQLite conversation row and two frozen"
  echo "  literals and hash to the bytes this kit staged and the launcher's lease pins; three"
  echo "  negatives were refused BY NAME (anti_rollback, floor_not_persisted, and the §4.1 hop"
  echo "  attributed to challenge_authority) and both sign-flip controls reported failure with the"
  echo "  outcome they named."
  echo "  Custody is kit_generated, so production_verified is FALSE by construction — this is a"
  echo "  complete, honestly-labelled chain run and it is NOT a production trust claim."
else
  echo "DRIVER: RED — runs=$DRIVER_RC verifier=$DRIVER_EV_RC derivation=$DRIVER_DERIVE_RC"
  echo "  custody=$DRIVER_CUSTODY_RC"
  echo "  (0 = green for each). Nothing was fabricated; see the per-run RESULT lines above."
  RC=1
fi

# The negative must fail, and it must fail for the reason it names. A negative that passes on any
# failure certifies nothing about the check it exists to test — a misplaced turn database once
# made three of the §5 kit's negatives report GREEN while the property was never reached.
if [ "$NEG_RC" = "0" ]; then
  echo "NEGATIVE: RED — a turn whose system the challenge never committed COMPLETED."
  echo "  That is §4.10(a) digest_mismatch, live, and it means this harness cannot fail."
  RC=1
elif echo "$NEG_OUT" | grep -q 'digest_mismatch'; then
  echo "NEGATIVE: GREEN — refused with digest_mismatch, and the harness exited non-zero ($NEG_RC)"
else
  echo "NEGATIVE: RED — the tampered turn failed, but not with digest_mismatch."
  echo "  A negative that accepts any failure passes when the deployment is merely broken."
  RC=1
fi
echo "================================================================================"
exit "$RC"
