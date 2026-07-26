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
# §2.3: the dedicated evidence-recorder OS principal that owns/writes store/rec/ (a group member,
# so the signer can read what it publishes; NOT the same thing as the governed-turn-recorder key).
id brops-recorder   >/dev/null 2>&1 || sudo useradd -r -M -s /usr/sbin/nologin -G brops-store brops-recorder
SIGUID="$(id -u brops-signer)"
SUPUID="$(id -u brops-supervisor)"
MYUSER="$(id -un)"

B="$(mktemp -d /tmp/brops-iso.XXXXXX)"
chmod 755 "$B"
mkdir -p "$B"/{signerkeys,attkeys,store,state,registry/config,signer-sock,sup-sock,wt}

# 1) Generate keys + a signed registry + a VALID signed run record (as the login user,
#    before we tighten ownership).
"$PYBIN" "$ENGINE/ci/gen_isolation_fixture.py" "$B"
ATT_PUB="$(cat "$B/att-pub")"
OP_PIN="$(cat "$B/operator-pin")"
POLICY_SHA="$(cat "$B/policy-bundle-sha")"

# 2) Custody (rev-26 §2.3): private-key dirs owner-only to their principals; the store is
#    group-shared and SETGID at **2750** — owner (supervisor) rwx, group (brops-store) r-x =
#    read+traverse ONLY, NO group-write, no world. Setgid so artifacts the supervisor publishes
#    inherit the brops-store group (the signer, also in brops-store, can read the 0640 files) but
#    a group member canNOT create/rename/unlink (that needs group-write on the dir, which 2750
#    denies). The login user is in NEITHER service context and NOT in brops-store. Each service
#    owns its OWN socket dir (world-traversable) so it can bind() there; SO_PEERCRED is the gate.
sudo chown -R brops-signer:brops-signer "$B/signerkeys";     sudo chmod 700 "$B/signerkeys"
sudo chown -R brops-supervisor:brops-supervisor "$B/attkeys"; sudo chmod 700 "$B/attkeys"
sudo chown -R brops-supervisor:brops-store "$B/store"
sudo chmod -R g+r "$B/store"          # evidence artifacts written before chown stay group-READABLE
sudo chmod 2750 "$B/store"            # dir: setgid + owner rwx + group r-x, group-write bit CLEAR
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
  "$PYBIN" "$ENGINE/tools/brops_signer_service.py" &
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

# 7) Run the PROVER as the login (attacker) user — every attack must be denied.
BROPS_SIGNER_SOCKET="$SIGNER_SOCK" BROPS_SUPERVISOR_SOCKET="$SUP_SOCK" \
BROPS_PROVE_SIGNER_KEY="$B/signerkeys/brops-receipt-signer.json" \
BROPS_PROVE_ATTESTATION_KEY="$B/attkeys/brops-supervisor-attestation.json" \
BROPS_PROVE_STORE_DIR="$B/store" \
"$PYBIN" "$ENGINE/tools/brops_isolation_prover.py"

# 8) rev-26 §2.3 COMPLETE two-namespace store-custody principal matrix. The governed store has
#    store/sup/ (owned+written ONLY by the supervisor) and store/rec/ (owned+written ONLY by the
#    dedicated brops-recorder principal), both 2750 (group read-traverse, NO group-write), files
#    0640, umask 0027. The signer (a brops-store group member) gets read/traverse in BOTH but
#    write in NEITHER; the login user / sidecar / executor (NOT in brops-store, other=---) get no
#    read/list/write in either. Proven with REAL principals for every operation × namespace.
GS="$B/gstore"
sudo mkdir -p "$GS/sup" "$GS/rec"
sudo chown brops-supervisor:brops-store "$GS" "$GS/sup"
sudo chown brops-recorder:brops-store   "$GS/rec"
sudo chmod 2750 "$GS" "$GS/sup" "$GS/rec"       # setgid + owner rwx + group r-x, group-write CLEAR
# Seed a 0640 artifact in each namespace, written BY its owner under umask 0027 (so a non-owner
# group member cannot even overwrite an existing artifact — it lacks file write).
sudo -u brops-supervisor sh -c "umask 0027; printf sup > '$GS/sup/a.json'"
sudo -u brops-recorder   sh -c "umask 0027; printf rec > '$GS/rec/a.json'"
# The recorder actually writes the signed bro_evidence chain into rec/evidence/ (the exact subtree the
# signer reads and the Q1/Q3 no-forge argument rests on): prove its custody too — owned by the
# recorder at 2750, a 0640 head file, no supervisor/login write, signer read-only.
sudo -u brops-recorder sh -c "umask 0027; mkdir -m 2750 '$GS/rec/evidence' && printf head > '$GS/rec/evidence/task.head.json'"

deny() { local p="$1" d="$2"; shift 2
  if sudo -u "$p" sh -c "$*" 2>/dev/null; then echo "SECURITY FAIL: [$p] $d SUCCEEDED (must be DENIED)"; exit 1; fi; }
allow() { local p="$1" d="$2"; shift 2
  sudo -u "$p" sh -c "$*" 2>/dev/null || { echo "SECURITY FAIL: [$p] $d was DENIED (must be ALLOWED)"; exit 1; }; }
deny_login() { local d="$1"; shift
  if sh -c "$*" 2>/dev/null; then echo "SECURITY FAIL: [login] $d SUCCEEDED (must be DENIED)"; exit 1; fi; }

# Mode-regression guard: root + both namespaces stat 2750; both seed artifacts stat 0640. (Run via
# sudo — the login user deliberately cannot traverse the 2750 store to stat inside it.)
for d in "$GS" "$GS/sup" "$GS/rec" "$GS/rec/evidence"; do
  m="$(sudo stat -c '%a' "$d")"; [ "$m" = "2750" ] || { echo "SECURITY FAIL: $d mode $m != 2750"; exit 1; }
done
for f in "$GS/sup/a.json" "$GS/rec/a.json" "$GS/rec/evidence/task.head.json"; do
  m="$(sudo stat -c '%a' "$f")"; [ "$m" = "640" ] || { echo "SECURITY FAIL: $f mode $m != 640"; exit 1; }
done

# supervisor: writes sup/ (create/rename/unlink), reads+lists both, DENIED every write in rec/.
allow brops-supervisor "create sup"      "touch '$GS/sup/s1'"
allow brops-supervisor "rename sup"      "mv '$GS/sup/s1' '$GS/sup/s2'"
allow brops-supervisor "unlink sup"      "rm '$GS/sup/s2'"
allow brops-supervisor "read sup"        "cat '$GS/sup/a.json' >/dev/null"
allow brops-supervisor "list+read rec"   "ls '$GS/rec' >/dev/null && cat '$GS/rec/a.json' >/dev/null"
deny  brops-supervisor "create rec"      "touch '$GS/rec/attack'"
deny  brops-supervisor "rename rec"      "mv '$GS/rec/a.json' '$GS/rec/x'"
deny  brops-supervisor "unlink rec"      "rm '$GS/rec/a.json'"
deny  brops-supervisor "chmod rec"       "chmod 600 '$GS/rec/a.json'"
deny  brops-supervisor "symlink rec"     "ln -s /etc/passwd '$GS/rec/link'"
deny  brops-supervisor "overwrite rec"   "printf x > '$GS/rec/a.json'"

# recorder: writes rec/ (create/rename/unlink), reads+lists both, DENIED every write in sup/.
allow brops-recorder "create rec"        "touch '$GS/rec/r1'"
allow brops-recorder "rename rec"        "mv '$GS/rec/r1' '$GS/rec/r2'"
allow brops-recorder "unlink rec"        "rm '$GS/rec/r2'"
allow brops-recorder "read+list sup"     "ls '$GS/sup' >/dev/null && cat '$GS/sup/a.json' >/dev/null"
deny  brops-recorder "create sup"        "touch '$GS/sup/attack'"
deny  brops-recorder "rename sup"        "mv '$GS/sup/a.json' '$GS/sup/x'"
deny  brops-recorder "unlink sup"        "rm '$GS/sup/a.json'"
deny  brops-recorder "chmod sup"         "chmod 600 '$GS/sup/a.json'"
deny  brops-recorder "symlink sup"       "ln -s /etc/passwd '$GS/sup/link'"
deny  brops-recorder "overwrite sup"     "printf x > '$GS/sup/a.json'"

# rec/evidence/ (the signed bro_evidence chain subtree): recorder owns+writes it; signer read-only;
# supervisor read-only (via group r-x on rec/); login no access.
allow brops-recorder "create evidence"   "touch '$GS/rec/evidence/e1'"
allow brops-recorder "rename evidence"   "mv '$GS/rec/evidence/e1' '$GS/rec/evidence/e2'"
allow brops-recorder "unlink evidence"   "rm '$GS/rec/evidence/e2'"
allow brops-signer   "read+list evidence" "ls '$GS/rec/evidence' >/dev/null && cat '$GS/rec/evidence/task.head.json' >/dev/null"
deny  brops-signer   "create evidence"   "touch '$GS/rec/evidence/attack'"
deny  brops-signer   "overwrite evidence" "printf x > '$GS/rec/evidence/task.head.json'"
deny  brops-signer   "unlink evidence"   "rm '$GS/rec/evidence/task.head.json'"
deny  brops-supervisor "create evidence" "touch '$GS/rec/evidence/attack'"
deny  brops-supervisor "overwrite evidence" "printf x > '$GS/rec/evidence/task.head.json'"

# signer: read/traverse+list BOTH, DENIED EVERY write op (create/overwrite/rename/unlink/chmod/
# symlink) in BOTH namespaces — the signer is group r-x with no group-write, so it must never be
# able to mutate either the supervisor's OR the recorder's evidence. Exhaustive: 6 write ops × 2 ns.
allow brops-signer "read+list sup"       "ls '$GS/sup' >/dev/null && cat '$GS/sup/a.json' >/dev/null"
allow brops-signer "read+list rec"       "ls '$GS/rec' >/dev/null && cat '$GS/rec/a.json' >/dev/null"
deny  brops-signer "create sup"          "touch '$GS/sup/attack'"
deny  brops-signer "create rec"          "touch '$GS/rec/attack'"
deny  brops-signer "overwrite sup"       "printf x > '$GS/sup/a.json'"
deny  brops-signer "overwrite rec"       "printf x > '$GS/rec/a.json'"
deny  brops-signer "rename sup"          "mv '$GS/sup/a.json' '$GS/sup/x'"
deny  brops-signer "rename rec"          "mv '$GS/rec/a.json' '$GS/rec/x'"
deny  brops-signer "unlink sup"          "rm '$GS/sup/a.json'"
deny  brops-signer "unlink rec"          "rm '$GS/rec/a.json'"
deny  brops-signer "chmod sup"           "chmod 600 '$GS/sup/a.json'"
deny  brops-signer "chmod rec"           "chmod 600 '$GS/rec/a.json'"
deny  brops-signer "symlink sup"         "ln -s /etc/passwd '$GS/sup/link'"
deny  brops-signer "symlink rec"         "ln -s /etc/passwd '$GS/rec/link'"

# login user (also the sidecar/executor identity in this harness): NOT in brops-store, other=--- on
# the 2750 namespaces, so cannot even traverse them — no read/list/write of ANY kind in either.
deny_login "list sup (other)"            "ls '$GS/sup'"
deny_login "list rec (other)"            "ls '$GS/rec'"
deny_login "read sup (other)"            "cat '$GS/sup/a.json'"
deny_login "read rec (other)"            "cat '$GS/rec/a.json'"
deny_login "create sup (other)"          "touch '$GS/sup/attack'"
deny_login "create rec (other)"          "touch '$GS/rec/attack'"
deny_login "overwrite rec (other)"       "printf x > '$GS/rec/a.json'"
deny_login "rename sup (other)"          "mv '$GS/sup/a.json' '$GS/sup/x'"
deny_login "chmod rec (other)"           "chmod 600 '$GS/rec/a.json'"
deny_login "symlink sup (other)"         "ln -s /etc/passwd '$GS/sup/link'"
deny_login "traverse+unlink rec (other)" "rm '$GS/rec/a.json'"
deny_login "list rec/evidence (other)"   "ls '$GS/rec/evidence'"
deny_login "read rec/evidence (other)"   "cat '$GS/rec/evidence/task.head.json'"

echo "STORE-CUSTODY MATRIX PASSED — 2750 sup/+rec/; supervisor⇄sup only, recorder⇄rec only, signer read-only both, login/sidecar/executor no access"
