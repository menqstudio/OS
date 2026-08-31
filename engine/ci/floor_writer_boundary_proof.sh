#!/usr/bin/env bash
# FW-1 — machine-prove the Floor Writer's principal boundary with REAL accounts over a REAL
# kernel IPC boundary. Nothing here passes a uid as a parameter: every verdict below is one the
# kernel produced from SO_PEERCRED or from a filesystem permission check.
#
# Modelled on engine/ci/isolation_proof.sh, including its meta-controls, because a proof whose
# probes cannot report the opposite answer is not a proof.
#
# THREE properties, each with its own principal (§1.8):
#   1. the authorized caller SUCCEEDS                     -- fwproof-ok, on floor.advance
#   2. the wrong principal is DENIED                      -- fwproof-none, on the same socket
#   3. the authorized-but-wrong-op caller is DENIED       -- fwproof-get, admitted to floor.get
#                                                            and refused floor.advance
# All three reach the endpoint: every one is in the caller group and can traverse to the socket,
# so a denial here is the ALLOWLIST's and never the filesystem's. Property 3 is the one a union
# allowlist would pass and a per-op allowlist must fail.
#
# FOUR provisioning negatives -- what the completion principal must not be able to do:
#   4. replace the socket endpoint
#   5. read or write the authoritative floor state
#   6. rewrite the TCB-owned Floor Writer config
#   7. create any other file in the socket directory
#
# THREE meta-controls, each proving a probe above can report the answer it did not report.
#
# Requires Linux, passwordless sudo, useradd/groupadd. Creates four accounts and one group under
# the fwproof- prefix and removes them on exit, whatever the outcome.
set -euo pipefail

if [ "$(uname -s)" != "Linux" ]; then
  echo "SKIP: the Floor Writer is Linux-only in FW-1 (SO_PEERCRED); Windows is FW-2." >&2
  exit 0
fi
if ! sudo -n true 2>/dev/null; then
  echo "SKIP: this proof creates real accounts and needs passwordless sudo." >&2
  echo "      A same-uid substitute would be green and would model nothing." >&2
  exit 0
fi

ENGINE_SRC="$(cd "$(dirname "$0")/.." && pwd)"
PYBIN="$(command -v python3)"
GROUP="fwproof"
SVC="fwproof-svc"; OKU="fwproof-ok"; GETU="fwproof-get"; NONEU="fwproof-none"
DIGEST_A="$(printf 'a%.0s' $(seq 1 64))"
DIGEST_B="$(printf 'b%.0s' $(seq 1 64))"
FAILURES=0
SERVICE_PIDS=()

# /var/tmp, not /tmp: the store must sit on a real filesystem, and the service accounts cannot
# traverse a checkout under /home.
WORK="$(sudo mktemp -d /var/tmp/fwproof.XXXXXX)"
B="$WORK/box"

cleanup() {
  local rc=$?
  set +e
  for pid in "${SERVICE_PIDS[@]:-}"; do [ -n "$pid" ] && sudo kill "$pid" 2>/dev/null; done
  sleep 0.3
  for pid in "${SERVICE_PIDS[@]:-}"; do [ -n "$pid" ] && sudo kill -9 "$pid" 2>/dev/null; done
  for u in "$OKU" "$GETU" "$NONEU" "$SVC"; do
    id "$u" >/dev/null 2>&1 && sudo /usr/sbin/userdel "$u" 2>/dev/null
  done
  getent group "$GROUP" >/dev/null 2>&1 && sudo /usr/sbin/groupdel "$GROUP" 2>/dev/null
  sudo rm -rf "$WORK"
  echo
  echo "== CLEANUP =="
  local dirty=0
  for u in "$SVC" "$OKU" "$GETU" "$NONEU"; do
    if getent passwd "$u" >/dev/null 2>&1; then echo "  STILL PRESENT: user $u"; dirty=1
    else echo "  removed: user $u"; fi
  done
  if getent group "$GROUP" >/dev/null 2>&1; then echo "  STILL PRESENT: group $GROUP"; dirty=1
  else echo "  removed: group $GROUP"; fi
  if [ -e "$WORK" ]; then echo "  STILL PRESENT: $WORK"; dirty=1
  else echo "  removed: $WORK"; fi
  [ "$dirty" -eq 0 ] || { echo "CLEANUP INCOMPLETE"; [ "$rc" -eq 0 ] && rc=1; }
  exit "$rc"
}
trap cleanup EXIT

OUT="$WORK/out"
sudo mkdir -p "$OUT"
sudo chown "$(id -u)" "$OUT"

ENGINE="$WORK/engine"
sudo cp -r "$ENGINE_SRC" "$ENGINE"
sudo chmod -R a+rX "$ENGINE"
sudo chmod 755 "$WORK"

sudo mkdir -p "$B" "$B/lib" "$B/etc"
sudo chown root:root "$B" "$B/lib" "$B/etc"
sudo chmod 755 "$B" "$B/lib" "$B/etc"

sudo /usr/sbin/groupadd -f "$GROUP"
for u in "$SVC" "$OKU" "$GETU" "$NONEU"; do
  id "$u" >/dev/null 2>&1 || sudo /usr/sbin/useradd -r -M --no-create-home \
    -s /usr/sbin/nologin -G "$GROUP" "$u"
done
SVC_UID="$(id -u "$SVC")"; OK_UID="$(id -u "$OKU")"
GET_UID="$(id -u "$GETU")"; NONE_UID="$(id -u "$NONEU")"
echo "principals: service=$SVC_UID authorized=$OK_UID get-only=$GET_UID unlisted=$NONE_UID"
[ "$SVC_UID" != "$OK_UID" ] && [ "$OK_UID" != "$GET_UID" ] && [ "$GET_UID" != "$NONE_UID" ] \
  || { echo "the four principals are not distinct"; exit 1; }

# ---------------------------------------------------------------------------
# The probe. Prints ONE token line: "OK <fields>" or "REFUSED <reason>".
# ---------------------------------------------------------------------------
sudo tee "$WORK/probe.py" >/dev/null <<'PYEOF'
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import floor_writer as fw
endpoint = pathlib.Path(sys.argv[2])
try:
    if sys.argv[3] == "get":
        head, digest, known, generation = fw.client_get(endpoint, sys.argv[4])
        print(f"OK head={head} known={known} generation={generation}")
    else:
        reply = fw.client_advance(endpoint, sys.argv[4], int(sys.argv[5]), sys.argv[6])
        print(f"OK outcome={reply['outcome']} head={reply['head_sequence']} "
              f"generation={reply['generation']}")
except fw.FloorWriterError as exc:
    print(f"REFUSED {exc.reason}")
PYEOF
sudo chmod 644 "$WORK/probe.py"

probe() {  # probe <user> <endpoint> <args...>
  local user="$1"; shift
  local endpoint="$1"; shift
  sudo -u "$user" env "PYTHONPATH=$ENGINE/runtime" "BRO_ENV=ci" \
    "$PYBIN" "$WORK/probe.py" "$ENGINE/runtime" "$endpoint" "$@" 2>&1 | tail -1
}

expect() {  # expect <label> <expected-substring> <actual>
  if [[ "$3" == *"$2"* ]]; then
    printf '  PASS  %-58s %s\n' "$1" "$3"
  else
    printf '  FAIL  %-58s got: %s (wanted: %s)\n' "$1" "$3" "$2"
    FAILURES=$((FAILURES + 1))
  fi
}

must_fail() {  # must_fail <label> <user> <shell command>
  local label="$1" user="$2"; shift 2
  local out
  if out="$(sudo -u "$user" sh -c "$*" 2>&1)"; then
    printf '  FAIL  %-58s the action SUCCEEDED\n' "$label"
    FAILURES=$((FAILURES + 1))
  else
    printf '  PASS  %-58s denied: %s\n' "$label" "$(echo "$out" | tail -1 | cut -c1-60)"
  fi
}

must_succeed() {  # must_succeed <label> <user> <shell command>
  local label="$1" user="$2"; shift 2
  if sudo -u "$user" sh -c "$*" >/dev/null 2>&1; then
    printf '  PASS  %-58s the action succeeded, as the control requires\n' "$label"
  else
    printf '  FAIL  %-58s the control could not succeed\n' "$label"
    FAILURES=$((FAILURES + 1))
  fi
}

start_service() {  # start_service <config> <socket>; sets SERVICE_PID
  sudo -u "$SVC" env "BROPS_FLOOR_WRITER_CONFIG=$1" "PYTHONPATH=$ENGINE/runtime" "BRO_ENV=ci" \
    "$PYBIN" "$ENGINE/runtime/run_floor_writer.py" >"$OUT/$(basename "$1").log" 2>&1 &
  SERVICE_PID=$!
  SERVICE_PIDS+=("$SERVICE_PID")
  # Waited for AS ROOT: this shell's own uid is not in the caller group, and the socket
  # directory is 0750, so `test -S` from here fails with EACCES even after a good bind.
  # That EACCES is itself the §1.7 property, and it is asserted below rather than assumed.
  for _ in $(seq 1 60); do sudo test -S "$2" && return 0; sleep 0.2; done
  echo "the service never bound $2:"; cat "$OUT/$(basename "$1").log"; exit 1
}

# ---------------------------------------------------------------------------
echo
echo "== B6: provision as root, and read the receipt back off the filesystem =="
# ---------------------------------------------------------------------------
CONFIG="$B/etc/floor-writer.json"
SOCK="$B/run/fw.sock"
sudo "$PYBIN" "$ENGINE/runtime/provision_floor_writer.py" \
  --install-id proof-install --service-user "$SVC" --caller-group "$GROUP" \
  --marks-root "$B/lib/marks" --socket-path "$SOCK" --config "$CONFIG" \
  --peer "floor.get=$OKU" --peer "floor.advance=$OKU" --peer "floor.get=$GETU" \
  | tee "$OUT/receipt.json"
STATE="$B/lib/marks/proof-install/floor-state.json"
GEN1="$($PYBIN -c "import json,sys;print(json.load(open(sys.argv[1]))['generation'])" "$OUT/receipt.json")"
echo "  generation minted: $GEN1"
[ "$GEN1" = "1" ] || { echo "the first provisioning did not mint generation 1"; exit 1; }

echo
echo "== the three boundary properties, over a real AF_UNIX socket =="
start_service "$CONFIG" "$SOCK"

expect "1. authorized caller advances"        "OK outcome=advanced head=5" \
       "$(probe "$OKU" "$SOCK" advance task-1 5 "$DIGEST_A")"
expect "1b. and its floor.get is served"      "OK head=5" \
       "$(probe "$OKU" "$SOCK" get task-1)"
expect "2. the unlisted principal is denied"  "REFUSED peer_denied" \
       "$(probe "$NONEU" "$SOCK" advance task-1 9 "$DIGEST_B")"
expect "2b. and cannot even read the floor"   "REFUSED peer_denied" \
       "$(probe "$NONEU" "$SOCK" get task-1)"
expect "3. the get-only peer cannot advance"  "REFUSED peer_denied" \
       "$(probe "$GETU" "$SOCK" advance task-1 9 "$DIGEST_B")"
expect "3b. control: that same peer CAN get"  "OK head=5" \
       "$(probe "$GETU" "$SOCK" get task-1)"
expect "3c. the refusal changed nothing"      "OK head=5" \
       "$(probe "$OKU" "$SOCK" get task-1)"

echo
echo "== what the completion principal must not be able to do =="
must_fail "4. replace the socket endpoint"        "$OKU" "rm -f '$SOCK'"
must_fail "7. create another file beside it"      "$OKU" "touch '$B/run/evil.sock'"
must_fail "5. read the authoritative floor state" "$OKU" "cat '$STATE'"
must_fail "5b. write the authoritative state"     "$OKU" "echo x > '$STATE'"
must_fail "5c. list the marks directory"          "$OKU" "ls '$B/lib/marks/proof-install'"
must_fail "6. rewrite the TCB-owned config"       "$OKU" "echo x > '$CONFIG'"
must_fail "6b. replace the config by rename"      "$OKU" "mv '$CONFIG' '$CONFIG.bak'"
expect    "and the service still answers"         "OK head=5" \
          "$(probe "$OKU" "$SOCK" get task-1)"

echo
echo "== §1.10: a re-provisioning is VISIBLY new, not silently empty =="
sudo kill "$SERVICE_PID"; wait "$SERVICE_PID" 2>/dev/null || true
sudo "$PYBIN" "$ENGINE/runtime/provision_floor_writer.py" \
  --install-id proof-install --service-user "$SVC" --caller-group "$GROUP" \
  --marks-root "$B/lib/marks" --socket-path "$SOCK" --config "$CONFIG" \
  --peer "floor.get=$OKU" --peer "floor.advance=$OKU" --peer "floor.get=$GETU" \
  >"$OUT/receipt2.json" 2>"$OUT/reprovision-refusal.txt" && {
    echo "  FAIL  provisioning over a live floor was allowed"; FAILURES=$((FAILURES + 1)); }
grep -q "Pass --reprovision" "$OUT/reprovision-refusal.txt" \
  && echo "  PASS  provisioning over a live floor refuses by name" \
  || { echo "  FAIL  the refusal did not name --reprovision"; FAILURES=$((FAILURES + 1)); }
sudo "$PYBIN" "$ENGINE/runtime/provision_floor_writer.py" --reprovision \
  --install-id proof-install --service-user "$SVC" --caller-group "$GROUP" \
  --marks-root "$B/lib/marks" --socket-path "$SOCK" --config "$CONFIG" \
  --peer "floor.get=$OKU" --peer "floor.advance=$OKU" --peer "floor.get=$GETU" \
  >"$OUT/receipt2.json"
GEN2="$($PYBIN -c "import json,sys;print(json.load(open(sys.argv[1]))['generation'])" "$OUT/receipt2.json")"
DROPPED="$($PYBIN -c "import json,sys;print(','.join(json.load(open(sys.argv[1]))['discarded_roster']))" "$OUT/receipt2.json")"
[ "$GEN2" = "2" ] && echo "  PASS  the generation moved $GEN1 -> $GEN2" \
  || { echo "  FAIL  the generation did not advance"; FAILURES=$((FAILURES + 1)); }
[ "$DROPPED" = "task-1" ] && echo "  PASS  the receipt names the floor it discarded: $DROPPED" \
  || { echo "  FAIL  the discarded roster was not reported"; FAILURES=$((FAILURES + 1)); }
start_service "$CONFIG" "$SOCK"
expect "the re-provisioned floor reports the NEW generation" "generation=2" \
       "$(probe "$OKU" "$SOCK" get task-1)"
expect "and it is empty rather than pretending to be old"    "OK head=0 known=False" \
       "$(probe "$OKU" "$SOCK" get task-1)"
sudo kill "$SERVICE_PID"; wait "$SERVICE_PID" 2>/dev/null || true

echo
echo "== META-CONTROL A: an admitted peer must be ANSWERED, or the denials are unearned =="
# Same accounts, a second install whose advance list names the principal denied above. If the
# probe cannot see an admission, its "REFUSED peer_denied" was not evidence of a boundary.
sudo mkdir -p "$B/etc2"; sudo chown root:root "$B/etc2"; sudo chmod 755 "$B/etc2"
OPEN_CONFIG="$B/etc2/floor-writer.json"
OPEN_SOCK="$B/run2/fw.sock"
sudo "$PYBIN" "$ENGINE/runtime/provision_floor_writer.py" \
  --install-id open-install --service-user "$SVC" --caller-group "$GROUP" \
  --marks-root "$B/lib/marks" --socket-path "$OPEN_SOCK" --config "$OPEN_CONFIG" \
  --peer "floor.get=$NONEU" --peer "floor.advance=$NONEU" >/dev/null
start_service "$OPEN_CONFIG" "$OPEN_SOCK"
expect "META-A: the same principal is served where it IS listed" "OK outcome=advanced" \
       "$(probe "$NONEU" "$OPEN_SOCK" advance task-1 3 "$DIGEST_A")"
sudo kill "$SERVICE_PID"; wait "$SERVICE_PID" 2>/dev/null || true

echo
echo "== META-CONTROL B: a directory the caller OWNS must let it place an endpoint =="
sudo mkdir -p "$B/caller-owned"; sudo chown "$OKU" "$B/caller-owned"; sudo chmod 755 "$B/caller-owned"
must_succeed "META-B: the caller can create a socket where it owns the directory" \
             "$OKU" "touch '$B/caller-owned/evil.sock'"

echo
echo "== META-CONTROL C: a store the caller owns must be readable BY it =="
sudo mkdir -p "$B/caller-store"; sudo chown "$OKU" "$B/caller-store"; sudo chmod 700 "$B/caller-store"
must_succeed "META-C: the read probe can succeed when custody is absent" \
             "$OKU" "echo x > '$B/caller-store/floor-state.json' && cat '$B/caller-store/floor-state.json'"

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "FLOOR WRITER BOUNDARY PROOF COMPLETE — three per-op properties over a real kernel"
  echo "boundary, four provisioning negatives, and three meta-controls that can fail."
else
  echo "FLOOR WRITER BOUNDARY PROOF FAILED: $FAILURES check(s)"
  exit 1
fi
