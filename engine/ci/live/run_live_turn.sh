#!/usr/bin/env bash
# Wave 3b — LIVE production governed-turn orchestrator (LINUX-RUN, REAL root + REAL service accounts).
#
# Assembles ONE genuine production `trusted_verified` end-to-end on a Debian box: it provisions the setuid
# launcher + executor image + protected store + the four Ed25519 keypairs + the root-signed production key
# manifest, starts the THREE live Python service servers (challenge-authority, governed-supervisor,
# isolated-signer) as their dedicated service accounts, then runs the Rust `live_turn` driver as the broker
# account. The driver drives the real broker chain (challenge -> supervisor(+lease) -> privileged
# recorder->setuid launcher->executor -> supervisor attest-run -> isolated-signer sign-result ->
# verify_and_accept -> production trust) and prints ONE `RESULT:` line. It NEVER fakes a trusted_verified.
#
# Requires: real root (sudo), the pre-created service accounts (brops-verifier_broker 5001, brops-challenge
# 5002, brops-supervisor 5004, brops-recorder 5005, brops-signer 5006, brops-executor 5007), a Rust
# toolchain, and python3 with `cryptography` (engine/requirements-ci.txt). Run as a user with sudo:
#
#   sudo engine/ci/live/run_live_turn.sh
#
set -u

# ----- accounts (already provisioned on the box) --------------------------------------------------
BROKER_USER=brops-verifier_broker
CHALLENGE_USER=brops-challenge
SUPERVISOR_USER=brops-supervisor
RECORDER_USER=brops-recorder
SIGNER_USER=brops-signer
EXECUTOR_USER=brops-executor

[ "$(id -u)" = "0" ] || { echo "FAIL: run as root (sudo) — real service accounts + setuid launcher"; exit 1; }

# A predictable file mode for the cross-uid store/report/output files (content-addressed integrity holds
# regardless, but 0644 keeps a reader on a different uid able to open them).
umask 022

# ----- locate repo + built binaries ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TAURI_DIR="$REPO_ROOT/apps/desktop/src-tauri"
TARGET_DIR="${CARGO_TARGET_DIR:-$TAURI_DIR/target}/debug"
LAUNCHER_BIN="$TARGET_DIR/brops-launcher"
EXECUTOR_BIN="$TARGET_DIR/proof_executor"
RECORDER_BIN="$TARGET_DIR/governed_recorder"
DRIVER_BIN="$TARGET_DIR/live_turn"

echo "== building the live-turn crates (launcher + governed-live: recorder/executor/driver) =="
( cd "$REPO_ROOT" && cargo build --manifest-path "$TAURI_DIR/Cargo.toml" \
    -p brops-launcher -p brops-governed-live ) || { echo "FAIL: build"; exit 1; }
for b in "$LAUNCHER_BIN" "$EXECUTOR_BIN" "$RECORDER_BIN" "$DRIVER_BIN"; do
  [ -x "$b" ] || { echo "FAIL: missing built binary $b"; exit 1; }
done

# ----- layout /opt/brops-live ---------------------------------------------------------------------
LIVE=/opt/brops-live
STORE="$LIVE/store"; SOCK="$LIVE/sock"; REPORT="$LIVE/report"; TCB="$LIVE/tcb"; BIN="$LIVE/bin"; KEYS="$LIVE/keys"
rm -rf "$LIVE"
mkdir -p "$STORE" "$SOCK" "$REPORT" "$TCB" "$BIN" "$KEYS" "$LIVE/engine"

# Stage the Python tree so the service accounts can import the cores + front doors + live runners (the repo
# may live under a home dir the service uids cannot traverse). Preserve the engine/ci/live + engine/runtime
# relative layout the runners resolve via __file__.
mkdir -p "$LIVE/engine/ci/live" "$LIVE/engine/runtime"
cp "$REPO_ROOT"/engine/ci/live/*.py "$LIVE/engine/ci/live/"
cp "$REPO_ROOT"/engine/runtime/*.py "$LIVE/engine/runtime/"
chmod -R a+rX "$LIVE/engine"
PYLIVE="$LIVE/engine/ci/live"

# ----- setuid launcher (root-owned, 4750, recorder group) + pinned executor image -----------------
install -m 0755 "$LAUNCHER_BIN" "$TCB/privileged-launcher.bin"
chown "0:$(id -g "$RECORDER_USER")" "$TCB/privileged-launcher.bin"
chmod 4750 "$TCB/privileged-launcher.bin"
install -m 0755 "$EXECUTOR_BIN" "$TCB/contained-executor.bin"
chown 0:0 "$TCB/contained-executor.bin"
install -m 0755 "$RECORDER_BIN" "$BIN/governed_recorder"; chown 0:0 "$BIN/governed_recorder"

LAUNCHER_SHA=$(sha256sum "$TCB/privileged-launcher.bin" | cut -d' ' -f1)
EXECUTOR_SHA=$(sha256sum "$TCB/contained-executor.bin" | cut -d' ' -f1)

# ----- the launcher's §4.3 VALIDATED lease FILE (root-owned, non-writable) -------------------------
RECORDER_GID=$(id -g "$RECORDER_USER"); EXECUTOR_UID=$(id -u "$EXECUTOR_USER"); EXECUTOR_GID=$(id -g "$EXECUTOR_USER")
cat > "$TCB/executor.lease" <<LEASE
recorder_uid=$(id -u "$RECORDER_USER")
recorder_gid=$RECORDER_GID
executor_uid=$EXECUTOR_UID
executor_gid=$EXECUTOR_GID
executor_executable_sha256=$EXECUTOR_SHA
LEASE
chown 0:0 "$TCB/executor.lease"; chmod 0644 "$TCB/executor.lease"

# ----- keys + manifest + store + shared config -----------------------------------------------------
echo "== provisioning keys + root-signed manifest + store + config =="
python3 "$PYLIVE/provision_keys.py" --root-dir "$LIVE" \
  --launcher-sha "$LAUNCHER_SHA" --executor-sha "$EXECUTOR_SHA" \
  --recorder-bin "$BIN/governed_recorder" --sudo-recorder-user "$RECORDER_USER" \
  || { echo "FAIL: provision_keys.py"; exit 1; }

CONFIG="$LIVE/config.json"

# Each private key readable ONLY by the owning service; public hex + manifest + config world-readable.
chown "$CHALLENGE_USER":  "$KEYS/challenge.priv";          chmod 0400 "$KEYS/challenge.priv"
chown "$SUPERVISOR_USER": "$KEYS/supervisor_attest.priv";  chmod 0400 "$KEYS/supervisor_attest.priv"
chown "$SIGNER_USER":     "$KEYS/signer.priv";             chmod 0400 "$KEYS/signer.priv"
chown 0:0 "$KEYS/root.priv";                               chmod 0400 "$KEYS/root.priv"
chmod 0644 "$KEYS"/*.pub.hex "$CONFIG" "$LIVE/manifest.json" "$LIVE/manifest.sig" "$LIVE/floor.json"

# Cross-uid working dirs: the trust boundary is SO_PEERCRED (sockets) + content-addressing (store), NOT the
# filesystem mode — so these are broadly traversable/writable while integrity stays cryptographic.
chmod 1777 "$SOCK" "$REPORT" "$STORE"
chmod 0644 "$STORE"/* 2>/dev/null || true

# ----- sudoers: the broker may spawn ONLY the recorder helper as the recorder account (invoker gate) ----
SUDOERS=/etc/sudoers.d/brops-live-recorder
echo "$BROKER_USER ALL=($RECORDER_USER) NOPASSWD: $BIN/governed_recorder" > "$SUDOERS"
chmod 0440 "$SUDOERS"

# ----- start the three service servers as their accounts ------------------------------------------
PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
  rm -f "$SUDOERS"
}
trap cleanup EXIT

start_server() {  # <user> <script>
  sudo -u "$1" env PYTHONUNBUFFERED=1 python3 "$PYLIVE/$2" --config "$CONFIG" &
  PIDS+=($!)
}
echo "== starting challenge-authority / supervisor / isolated-signer servers =="
start_server "$CHALLENGE_USER"   run_authority.py
start_server "$SUPERVISOR_USER"  run_supervisor.py
start_server "$SIGNER_USER"      run_signer.py

# Wait for all three sockets to appear (fail-closed after a bounded wait).
for s in authority supervisor signer; do
  for _ in $(seq 1 100); do [ -S "$SOCK/$s.sock" ] && break; sleep 0.05; done
  [ -S "$SOCK/$s.sock" ] || { echo "FAIL: $s server did not bind its socket"; exit 1; }
done

# ----- run ONE live governed turn as the broker account -------------------------------------------
echo "== running the live governed turn as $BROKER_USER =="
OUT=$(sudo -u "$BROKER_USER" "$DRIVER_BIN" --config "$CONFIG" 2>&1)
echo "$OUT"
RESULT_LINE=$(echo "$OUT" | grep -E '^RESULT:' | tail -1)

echo
echo "================================ live governed turn ================================"
echo "$RESULT_LINE"
if echo "$RESULT_LINE" | grep -qE 'production_verified=true bound=true'; then
  echo "LIVE GOVERNED TURN: GREEN — genuine production trusted_verified"
  exit 0
else
  echo "LIVE GOVERNED TURN: RED / BLOCKED (fail-closed — no fabricated acceptance)"
  exit 1
fi
