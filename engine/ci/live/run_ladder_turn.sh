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
# It provisions the SAME `/opt/brops-live` root, and it has to: the setuid launcher pins
# `/opt/brops-live/config.json` as its attested-request path and the recorder pins
# `/opt/brops-live/tcb/recorder-policy.json` as its steering policy, both COMPILED IN so no argv or
# env can redirect them. So the two scripts cannot run concurrently on one box; in CI they are
# separate jobs on separate runners.
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

if [ -x "$LAUNCHER_BIN" ] && [ -x "$EXECUTOR_BIN" ] && [ -x "$RECORDER_BIN" ]; then
  echo "== using pre-built launcher/executor/recorder =="
else
  echo "== building the launcher + the governed-live crate (recorder/executor) =="
  CARGO_BIN="$(command -v cargo || true)"
  [ -n "$CARGO_BIN" ] || for u in "${SUDO_USER:-}" gevorg; do
    [ -n "$u" ] && [ -x "/home/$u/.cargo/bin/cargo" ] && { CARGO_BIN="/home/$u/.cargo/bin/cargo"; break; }
  done
  [ -n "$CARGO_BIN" ] || { echo "FAIL: cargo not found (build as the normal user first, then re-run)"; exit 1; }
  ( cd "$REPO_ROOT" && "$CARGO_BIN" build --manifest-path "$TAURI_DIR/Cargo.toml" \
      -p brops-launcher -p brops-governed-live ) || { echo "FAIL: build"; exit 1; }
fi
for b in "$LAUNCHER_BIN" "$EXECUTOR_BIN" "$RECORDER_BIN"; do
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
  rm -f "$SUDOERS"
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
POS_OUT=$(python3 "$PYLIVE/ladder_evidence.py" --live-root "$LIVE" \
  --submit "$LADDER/submit.json" --document "$LADDER/document.json" \
  --reply "$LADDER/reply.json" --hop-log "$LADDER/hops.jsonl" --uids "$LADDER/uids.json" \
  --bundle "$LADDER/evidence" 2>&1) && POS_RC=0 || POS_RC=$?
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

# ----- evidence out ------------------------------------------------------------------------------
# Copied into the workspace so CI can upload it and a reader can check the signature without root.
EVIDENCE_OUT="${LADDER_EVIDENCE_OUT:-${RUNNER_TEMP:-/tmp}/ladder-evidence}"
rm -rf "$EVIDENCE_OUT"; mkdir -p "$EVIDENCE_OUT"
cp -r "$LADDER/evidence" "$EVIDENCE_OUT/positive" 2>/dev/null || true
cp -r "$LADDER/evidence-negative" "$EVIDENCE_OUT/negative" 2>/dev/null || true
cp "$LADDER/hops.jsonl" "$LADDER/uids.json" "$EVIDENCE_OUT/" 2>/dev/null || true
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
