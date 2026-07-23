#!/usr/bin/env bash
# Wave 3b-1 — machine-prove the four same-login-user isolation denials (design §1.1;
# audit P0-1). Runs on Linux CI with passwordless sudo. Creates two dedicated service
# principals, provisions their keys/store/sockets, starts the real signer + supervisor
# services AS those principals, then runs the prover AS the login (attacker) user and
# requires all four attacks to be denied. No skip/placeholder.
set -euo pipefail

ENGINE="$(cd "$(dirname "$0")/.." && pwd)"
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
python3 "$ENGINE/ci/gen_isolation_fixture.py" "$B"
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
sudo chown -R brops-supervisor:brops-supervisor "$B/state" "$B/registry"; sudo chmod -R 750 "$B/state" "$B/registry"
sudo chown brops-signer:brops-signer "$B/signer-sock";       sudo chmod 755 "$B/signer-sock"
sudo chown brops-supervisor:brops-supervisor "$B/sup-sock";  sudo chmod 755 "$B/sup-sock"

SIGNER_SOCK="$B/signer-sock/signer.sock"
SUP_SOCK="$B/sup-sock/sup.sock"

# 3) Start the SIGNER service AS brops-signer; it admits ONLY the supervisor UID. Its
#    expected policy-bundle digest is the run record's real bundle (positive control).
sudo -u brops-signer env \
  BRO_ENV=ci PYTHONPATH="$PYTHONPATH" \
  BROPS_EVIDENCE_STORE_DIR="$B/store" \
  BROPS_RECEIPT_SIGNER_KEYDIR="$B/signerkeys" \
  BROPS_SUPERVISOR_ATTESTATION_PUBKEY="$ATT_PUB" \
  BROPS_SUPERVISOR_ATTESTATION_KEY_ID="sup-att-1" \
  BROPS_ALLOWED_EXECUTOR_IDS="exec-1" BROPS_ALLOWED_BUILDER_IDS="builder-1" \
  BROPS_ALLOWED_SUPERVISOR_IDS="sup-1" BROPS_EXPECTED_POLICY_ID="policy-1" \
  BROPS_EXPECTED_POLICY_VERSION="1" BROPS_EXPECTED_POLICY_BUNDLE_SHA256="$POLICY_SHA" \
  BROPS_SIGNER_SOCKET="$SIGNER_SOCK" BROPS_ALLOWED_PEER_UIDS="$SUPUID" \
  python3 "$ENGINE/tools/brops_signer_service.py" &
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
  python3 "$ENGINE/tools/brops_supervisor_service.py" &
SUP_PID=$!

cleanup() { sudo kill "$SIGNER_PID" "$SUP_PID" 2>/dev/null || true; }
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
BROPS_POS_SOCK="$SUP_SOCK" python3 - "$ENGINE" <<'PY'
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

# 7) Run the PROVER as the login (attacker) user — every attack must be denied.
BROPS_SIGNER_SOCKET="$SIGNER_SOCK" BROPS_SUPERVISOR_SOCKET="$SUP_SOCK" \
BROPS_PROVE_SIGNER_KEY="$B/signerkeys/brops-receipt-signer.json" \
BROPS_PROVE_ATTESTATION_KEY="$B/attkeys/brops-supervisor-attestation.json" \
BROPS_PROVE_STORE_DIR="$B/store" \
python3 "$ENGINE/tools/brops_isolation_prover.py"
