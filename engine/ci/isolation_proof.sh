#!/usr/bin/env bash
# Wave 3b-1 — machine-prove the four same-login-user isolation denials (design §1.1;
# audit P0-1). Runs on Linux CI with passwordless sudo. Creates two dedicated service
# principals, provisions their keys/store/sockets, starts the real signer + supervisor
# services AS those principals, runs a positive supervisor->signer signed round-trip, and
# then runs the prover AS the login (attacker) user requiring all four attacks to be
# denied. No skip/placeholder.
set -euo pipefail

ENGINE_SRC="$(cd "$(dirname "$0")/.." && pwd)"
# The full path to the deps-bearing python (sudo -u resets PATH, so `python3` alone would
# resolve to /usr/bin/python3 WITHOUT the pip-installed cryptography).
PYBIN="$(command -v python3)"
# Copy the engine to a WORLD-READABLE location: the dedicated service users cannot
# traverse the runner's home ($GITHUB_WORKSPACE under /home/runner), so they could not
# read the source there.
WORK="$(mktemp -d /tmp/brops-eng.XXXXXX)"; chmod 755 "$WORK"
ENGINE="$WORK/engine"
cp -r "$ENGINE_SRC" "$ENGINE"
chmod -R a+rX "$ENGINE"

export BRO_ENV=ci
export PYTHONPATH="$ENGINE/runtime:$ENGINE/tools"

MYUID="$(id -u)"
sudo groupadd -f brops-store
id brops-signer     >/dev/null 2>&1 || sudo useradd -r -M -s /usr/sbin/nologin -G brops-store brops-signer
id brops-supervisor >/dev/null 2>&1 || sudo useradd -r -M -s /usr/sbin/nologin -G brops-store brops-supervisor
SIGUID="$(id -u brops-signer)"
SUPUID="$(id -u brops-supervisor)"

B="$(mktemp -d /tmp/brops-iso.XXXXXX)"
chmod 755 "$B"
mkdir -p "$B"/{signerkeys,attkeys,store,state,registry/config,signer-sock,sup-sock,wt}

# 1) Generate keys + a signed registry + a VALID signed run record (as the login user,
#    before we tighten ownership).
"$PYBIN" "$ENGINE/ci/gen_isolation_fixture.py" "$B"
ATT_PUB="$(cat "$B/att-pub")"
OP_PIN="$(cat "$B/operator-pin")"
POLICY_SHA="$(cat "$B/policy-bundle-sha")"

# 2) Custody: private-key dirs owner-only to their principals; the store is group-shared
#    and SETGID (2770) so artifacts the supervisor publishes inherit the brops-store group
#    (the signer, also in brops-store, can read the 0640 files); the login user is in
#    NEITHER service context and NOT in brops-store. Each service owns its OWN socket dir
#    (world-traversable) so it can bind() there; SO_PEERCRED is the connect-time gate.
sudo chown -R brops-signer:brops-signer "$B/signerkeys";     sudo chmod 700 "$B/signerkeys"
sudo chown -R brops-supervisor:brops-supervisor "$B/attkeys"; sudo chmod 700 "$B/attkeys"
sudo chown -R brops-supervisor:brops-store "$B/store";       sudo chmod 2770 "$B/store"
sudo chmod -R g+r "$B/store"  # the evidence artifacts written before chown stay group-readable
sudo chown -R brops-supervisor:brops-supervisor "$B/state" "$B/registry"; sudo chmod -R 750 "$B/state" "$B/registry"
sudo chown brops-signer:brops-signer "$B/signer-sock";       sudo chmod 755 "$B/signer-sock"
sudo chown brops-supervisor:brops-supervisor "$B/sup-sock";  sudo chmod 755 "$B/sup-sock"

SIGNER_SOCK="$B/signer-sock/signer.sock"
SUP_SOCK="$B/sup-sock/sup.sock"

# 3) Start the SIGNER service AS brops-signer; it admits ONLY the supervisor UID. Its
#    expected policy-bundle digest is the run record's real bundle (positive control).
# One launcher, two callers: the real signer below and the deliberately-unguarded twin in
# the meta-controls at the end. They differ in EXACTLY one argument — the peer allow-list —
# so "the prover reports BREACH against the twin" is attributable to that one thing.
start_signer() {  # <socket-path> <allowed-peer-uids>
  sudo -u brops-signer env \
    BRO_ENV=ci PYTHONPATH="$PYTHONPATH" \
    BROPS_EVIDENCE_STORE_DIR="$B/store" \
    BROPS_RECEIPT_SIGNER_KEYDIR="$B/signerkeys" \
    BROPS_SUPERVISOR_ATTESTATION_PUBKEY="$ATT_PUB" \
    BROPS_SUPERVISOR_ATTESTATION_KEY_ID="sup-att-1" \
    BROPS_ALLOWED_EXECUTOR_IDS="exec-1" BROPS_ALLOWED_BUILDER_IDS="builder-1" \
    BROPS_ALLOWED_SUPERVISOR_IDS="sup-1" BROPS_EXPECTED_POLICY_ID="policy-1" \
    BROPS_EXPECTED_POLICY_VERSION="1" BROPS_EXPECTED_POLICY_BUNDLE_SHA256="$POLICY_SHA" \
    BROPS_SIGNER_SOCKET="$1" BROPS_ALLOWED_PEER_UIDS="$2" \
    "$PYBIN" "$ENGINE/tools/brops_signer_service.py" &
}
start_signer "$SIGNER_SOCK" "$SUPUID"
SIGNER_PID=$!

# 4) Start the SUPERVISOR service AS brops-supervisor; it admits ONLY the login UID
#    (the sidecar) and is the only peer the signer admits.
sudo -u brops-supervisor env \
  BRO_ENV=ci PYTHONPATH="$PYTHONPATH" BRO_OPERATOR_ROOT_PUBKEY="$OP_PIN" \
  BROPS_SUPERVISOR_SOCKET="$SUP_SOCK" BROPS_SUPERVISOR_ALLOWED_PEER_UIDS="$MYUID" \
  BROPS_SIGNER_SOCKET="$SIGNER_SOCK" \
  BROPS_SUPERVISOR_ATTESTATION_KEYDIR="$B/attkeys" \
  BROPS_EVIDENCE_STORE_DIR="$B/store" BROPS_RUNSTATE_DIR="$B/state" \
  BROPS_REGISTRY_ROOT="$B/registry" BROPS_REQUIRED_CAPABILITIES="EXECUTE_CODE" \
  "$PYBIN" "$ENGINE/tools/brops_supervisor_service.py" &
SUP_PID=$!

UNGUARDED_PID=""
cleanup() { sudo kill "$SIGNER_PID" "$SUP_PID" ${UNGUARDED_PID:+"$UNGUARDED_PID"} 2>/dev/null || true; }
trap cleanup EXIT

# 5) Wait for both services to BIND (guards against a false "denied" from a down service).
for _ in $(seq 1 50); do
  [ -S "$SIGNER_SOCK" ] && [ -S "$SUP_SOCK" ] && break
  sleep 0.2
done
[ -S "$SIGNER_SOCK" ] || { echo "signer service did not bind"; exit 1; }
[ -S "$SUP_SOCK" ]    || { echo "supervisor service did not bind"; exit 1; }

# 6) POSITIVE CONTROL (before the denials): a real allowed login->supervisor->signer
#    signed round-trip. This proves the signing path is ALIVE, so the denial checks
#    below are real denials, not a dead path silently "passing".
BROPS_POS_SOCK="$SUP_SOCK" "$PYBIN" - "$ENGINE" <<'PY'
import sys, pathlib, os
engine = sys.argv[1]
sys.path.insert(0, str(pathlib.Path(engine) / "runtime"))
sys.path.insert(0, str(pathlib.Path(engine) / "tools"))
import brops_socket
r = brops_socket.request(
    os.environ["BROPS_POS_SOCK"],
    {"protocol": "brops.evidence-request.v1", "run_id": "ci-run-1",
     "execution_attempt_id": "ci-attempt-1"},
    timeout=20,
)
assert isinstance(r, dict) and r.get("status") == "signed", f"POSITIVE CONTROL FAILED: {r}"
rec = r.get("receipt") or {}
assert rec.get("envelope_jcs_b64") and rec.get("signature_b64"), f"missing signed wire: {r}"
print("POSITIVE CONTROL PASSED — supervisor->signer signed round-trip")
PY

# The exact paths the prover is handed. Named ONCE so the sudo-side controls below and the
# prover cannot drift apart — a control that checks a different path than the attack
# attacks is not a control.
SIGNER_KEY="$B/signerkeys/brops-receipt-signer.json"
ATT_KEY="$B/attkeys/brops-supervisor-attestation.json"
STORE_DIR="$B/store"

# 6b) POSITIVE CONTROL the attacker cannot perform. From the attacker's seat "I could not
#     read it" and "there was nothing to read" are the same observation, so only a check
#     with sudo can tell them apart: each secret the denials below are about must EXIST,
#     be non-empty, and be readable BY ITS OWNING PRINCIPAL. Rename a key, mistype a path
#     in the env block below, or let provisioning silently no-op and this aborts here —
#     the prover never gets to report a denial of a file that was never there.
echo
echo "== POSITIVE CONTROL: the secrets the denials are about actually exist =="
owner_can_read() {  # <principal> <path>
  sudo -u "$1" test -r "$2" && sudo -u "$1" test -s "$2" || {
    echo "POSITIVE CONTROL FAILED: $1 cannot read a non-empty $2."
    echo "  There is no secret at that path, so 'the login user could not read it' would"
    echo "  prove nothing about custody."
    exit 1
  }
  echo "  $2 — exists, non-empty, readable by $1"
}
owner_can_read brops-signer     "$SIGNER_KEY"
owner_can_read brops-supervisor "$ATT_KEY"
sudo -u brops-signer sh -c "ls -1 '$STORE_DIR' | grep -q ." || {
  echo "POSITIVE CONTROL FAILED: the brops-store group cannot list a non-empty $STORE_DIR"
  exit 1
}
echo "  $STORE_DIR — holds artifacts the brops-store group can list"

# ----- running the prover: a verdict must name its cause -------------------------------
# The sibling of `expect_blocked()` in engine/ci/live/run_live_turn.sh. The prover's exit
# code alone is not enough: 2 (INCONCLUSIVE) and 0 (PASSED) are both "not a breach", and
# the entire defect this round fixes was a prover that could reach exit 0 for a reason
# that had nothing to do with containment. So every invocation states BOTH the exit code
# it expects and the sentence it expects to see.
PROVER=("$PYBIN" "$ENGINE/tools/brops_isolation_prover.py")
prover_env() {  # <signer-sock> <sup-sock> <signer-key> <att-key> <store>
  PENV=(BROPS_SIGNER_SOCKET="$1" BROPS_SUPERVISOR_SOCKET="$2"
        BROPS_PROVE_SIGNER_KEY="$3" BROPS_PROVE_ATTESTATION_KEY="$4"
        BROPS_PROVE_STORE_DIR="$5")
}
expect_prover() {  # <label> <want-exit> <want-substring>
  local label="$1" want_exit="$2" want="$3" out rc
  out=$(env "${PENV[@]}" "${PROVER[@]}" 2>&1) && rc=0 || rc=$?
  echo "$out" | sed 's/^/    /'
  if [ "$rc" != "$want_exit" ]; then
    echo "$label: RED — the prover exited $rc, wanted $want_exit"
    return 1
  fi
  if ! echo "$out" | grep -qF "$want"; then
    echo "$label: RED — exit $rc was right, but the output never says '$want'."
    echo "  A verdict that does not name its cause certifies nothing."
    return 1
  fi
  echo "$label: GREEN — exit $rc, '$want'"
  return 0
}

# 7) Run the PROVER as the login (attacker) user — every attack must be DENIED, and the
#    proof must say so in the one sentence that only the all-denied path prints.
echo
echo "== the four denials, as the login (attacker) user =="
prover_env "$SIGNER_SOCK" "$SUP_SOCK" "$SIGNER_KEY" "$ATT_KEY" "$STORE_DIR"
expect_prover "ISOLATION PROOF" 0 "ISOLATION PROOF PASSED" || exit 1

# 8) META-CONTROLS on the prover itself. Three audit rounds here were lost to checks that
#    stayed green with the check removed, and the prover WAS that failure mode: with five
#    nonexistent paths and no services at all it used to print PASSED and exit 0. Each
#    case below breaks exactly one thing and requires the prover to notice. If any of them
#    goes green-when-it-should-be-red, the four denials above mean nothing.
echo
echo "== META-CONTROL A: a mistyped key-store path must be INCONCLUSIVE, never proven =="
prover_env "$SIGNER_SOCK" "$SUP_SOCK" "$B/signerkeys-TYPO/brops-receipt-signer.json" \
           "$ATT_KEY" "$STORE_DIR"
expect_prover "META-A" 2 "ISOLATION PROOF INCONCLUSIVE" || {
  echo "  The prover treats an unreachable path as a denial. That is the defect itself."
  exit 1
}

echo
echo "== META-CONTROL B: a signer WITHOUT the peer allow-list must read as a BREACH =="
# The same service, started the same way, with one argument changed: it admits the login
# UID. If the prover still says DENIED here, then its DENIED above was never earned by
# SO_PEERCRED — it would have said DENIED with the ACL deleted too. (The old bar,
# `status != "signed"`, did exactly that: the twin refuses the attacker's garbage frame on
# input validation, so the old prover scored an admitted peer as a denial.)
UNGUARDED_SOCK="$B/signer-sock/unguarded.sock"
start_signer "$UNGUARDED_SOCK" "$MYUID"
UNGUARDED_PID=$!
for _ in $(seq 1 50); do [ -S "$UNGUARDED_SOCK" ] && break; sleep 0.2; done
[ -S "$UNGUARDED_SOCK" ] || { echo "META-B: the unguarded signer never bound"; exit 1; }
prover_env "$UNGUARDED_SOCK" "$SUP_SOCK" "$SIGNER_KEY" "$ATT_KEY" "$STORE_DIR"
expect_prover "META-B" 1 "the signer ANSWERED the login user" || {
  echo "  The prover cannot see an admitted peer, so its SO_PEERCRED denial is unearned."
  exit 1
}
sudo kill "$UNGUARDED_PID" 2>/dev/null || true
UNGUARDED_PID=""

echo
echo "== META-CONTROL C: a store the login user owns must read as a BREACH =="
# Proves the filesystem half of the prover can still fail: point it at a directory this
# uid owns and the custody control must call it what it is.
OWN_STORE="$B/attacker-owned-store"
mkdir -p "$OWN_STORE"
prover_env "$SIGNER_SOCK" "$SUP_SOCK" "$SIGNER_KEY" "$ATT_KEY" "$OWN_STORE"
expect_prover "META-C" 1 "OWNED by the attacking uid" || {
  echo "  The prover cannot see a store it owns, so its custody denial is unearned."
  exit 1
}

echo
echo "ISOLATION PROOF COMPLETE — four denials, each attributable, each with a live target,"
echo "and a prover proven able to report INCONCLUSIVE and BREACH when they are true."
