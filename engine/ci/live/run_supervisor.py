#!/usr/bin/env python3
"""Run the LIVE governed-supervisor server (Wave 3b, rev-30 §5 v2 / §4.6).

Binds the supervisor's AF_UNIX socket and serves the five §5 lifecycle ops forever —
``accept-open`` / ``launch-gate`` / ``execution-started`` / ``complete-run`` / ``attest-run`` —
allowlisting ONLY the broker uid via SO_PEERCRED. It:

  * pins the challenge PUBLIC key for ``verify_sig`` (it verifies the challenge document the authority
    signed, over the canonical payload bytes it reassembles itself),
  * pins the launcher/executor executable digests into every lease (from its OWN trusted config),
  * opens its DURABLE ledger — the acceptance/lease/completion state that makes one signed challenge
    worth exactly one execution attempt,
  * holds the supervisor-attestation PRIVATE key behind ``sign_attestation`` — it builds ``JCS(evidence)``
    from its OWN terminal run state and signs THOSE bytes (never caller bytes).

**F-01.** This service used to run stateless: it signed whatever ``facts`` arrived with ``attest-run``,
so the broker uid could obtain a signed receipt for a run that never happened. The ledger is now a
hard prerequisite — if it cannot be opened, the supervisor refuses to start rather than serve without
the authority its attestations claim to carry.

``now_ms`` is always the supervisor's OWN clock, never from the wire. Fail-closed, Linux-only (SO_PEERCRED).

Run AS the supervisor account:  sudo -u brops-supervisor python3 run_supervisor.py --config <config.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "runtime")))

import ipc_policy
import live_crypto as lc  # noqa: E402
import governed_supervisor_ledger as gsl  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
from governed_supervisor import SupervisorConfig, recompute_request_sha256  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # F-10: the peer-auth rule comes from this service's OWN root-owned IPC policy file, not
    # from the shared config the broker also writes its knobs into. That is what gives the
    # §2.5 floor a `supervisor.ipc-policy` artifact to measure, and what stops a service
    # account from widening who may talk to it. Fail-closed: no policy, no serving.
    allowed_broker_uid = ipc_policy.load_allowed_peer_uid(
        cfg["ipc_policies"]["supervisor"], "supervisor")
    sock_path = cfg["sockets"]["supervisor"]
    sup_attest_key_id = cfg["trust"]["supervisor_attestation_key_id"]
    sup = cfg["supervisor"]
    launcher_sha = sup["launcher_executable_sha256"]
    executor_sha = sup["executor_executable_sha256"]

    with open(cfg["keys"]["challenge_pub_hex"], "r", encoding="ascii") as f:
        challenge_pub = lc.load_public_hex(f.read().strip())
    with open(cfg["keys"]["supervisor_attest_priv"], "rb") as f:
        sup_attest_priv = lc.load_private(f.read())

    # verify_sig(message, sig): the challenge-key signature over the canonical payload the supervisor
    # reassembled itself. Fail-closed (never raises).
    def verify_sig(message: bytes, sig: str) -> bool:
        return lc.verify_b64url(challenge_pub, message, sig)

    # sign_attestation(message): the supervisor holds the attestation private key behind this seam; it is
    # handed ONLY the JCS(evidence) bytes it assembled. base64url-nopad per §4.1 (the Rust broker decodes
    # with URL_SAFE_NO_PAD).
    def sign_attestation(message: bytes) -> str:
        return lc.sign_b64url(sup_attest_priv, message)

    def clock_ms() -> int:
        return int(time.time() * 1000)

    # publish_artifact(bytes) -> 64-hex handle. The supervisor BUILDS its terminal artifacts
    # (the lease payload, the governed-turn record, the execution receipt) from its own rows and
    # publishes them to the content-addressed protected store, then names those addresses in the
    # signed evidence (audit F-02 — they used to be deployment-static constants the broker copied
    # out of this world-readable config). Writing is atomic-by-rename and idempotent: the content
    # address IS the filename, so republishing identical bytes is a no-op.
    store_dir = cfg["store_dir"]

    # read_run_evidence(attempt) -> the RECORDER's evidence chain bytes, or None (audit F-01).
    # Read from the recorder's OWN directory, which the broker cannot write. That is the whole
    # point: every other input to the attestation either comes from the supervisor's rows or from
    # the caller, and `output_handle` — the digest of the exact reply the desktop commits — was in
    # the second group. Reading the chain here puts it in neither: the recorder is the privileged
    # component that actually captured the executor's bytes, and it is the only writer of this
    # directory. Bounded so a hostile file cannot exhaust the supervisor.
    evidence_dir = cfg["execution"]["evidence_state_dir"]
    MAX_EVIDENCE_BYTES = 1 << 20

    def read_run_evidence(attempt: str):
        # The attempt id reaches the filesystem, so it must not be able to escape the directory.
        # It is a supervisor-minted id, but the supervisor does not get to assume its own inputs.
        if not attempt or not all(c.isalnum() or c in "-_" for c in attempt):
            return None
        path = os.path.join(evidence_dir, attempt + ".evidence.json")
        try:
            with open(path, "rb") as fh:
                data = fh.read(MAX_EVIDENCE_BYTES + 1)
        except OSError:
            return None
        if len(data) > MAX_EVIDENCE_BYTES:
            return None
        return data

    def publish_artifact(data: bytes) -> str:
        handle = hashlib.sha256(data).hexdigest()
        final = os.path.join(store_dir, handle)
        if not os.path.exists(final):
            tmp = final + ".tmp-%d" % os.getpid()
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, final)
            try:
                os.chmod(final, 0o644)  # a different uid (the signer) reads it by handle
            except OSError:
                pass
        return handle

    config = SupervisorConfig(
        launcher_executable_sha256=launcher_sha,
        executor_executable_sha256=executor_sha,
        id_fn=lambda: uuid.uuid4().hex,
        # The identity + registry block the attestation is built from. It is the
        # supervisor's own provisioning, never anything a caller sends (F-01).
        supervisor_id=sup["supervisor_id"],
        executor_id=sup["executor_id"],
        builder_id=sup["builder_id"],
        policy_id=sup["policy_id"],
        policy_version=sup["policy_version"],
        policy_bundle_handle=sup["policy_bundle_handle"],
        challenge_registry_handle=sup["challenge_registry_handle"],
        challenge_registry_hash=sup["challenge_registry_hash"],
        challenge_registry_epoch=int(sup["challenge_registry_epoch"]),
        challenge_registry_root_key_id=sup["challenge_registry_root_key_id"],
    )

    # The durable ledger is a HARD prerequisite: a supervisor that cannot record what it
    # authorized has no authority to attest, so failing to open it aborts startup rather
    # than degrading to the stateless behaviour F-01 exploited.
    ledger_conn = gsl.open_ledger(sup["ledger_db"])

    if os.path.exists(sock_path):
        os.unlink(sock_path)
    listener = gss.bind_listener(sock_path)
    os.chmod(sock_path, 0o777)
    print("RESULT: supervisor listening sock=%s broker_uid=%d" % (sock_path, allowed_broker_uid), flush=True)

    def accept_one():
        return gss.accept_socket_conn(listener)

    try:
        gss.serve_forever(
            accept_one,
            allowed_broker_uid,
            config,
            verify_sig,
            recompute_request_sha256,
            clock_ms,
            ledger_conn=ledger_conn,
            publish_artifact=publish_artifact,
            read_run_evidence=read_run_evidence,
            sign_attestation=sign_attestation,
            supervisor_attestation_key_id=sup_attest_key_id,
        )
    finally:
        try:
            ledger_conn.close()
        except Exception:
            pass
        try:
            os.unlink(sock_path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
