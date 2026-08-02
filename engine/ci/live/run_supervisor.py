#!/usr/bin/env python3
"""Run the LIVE governed-supervisor server (Wave 3b, rev-30 §5 / §4.6).

Binds the supervisor's AF_UNIX socket and serves ``accept-open`` / ``launch-gate`` / ``attest-run`` forever,
allowlisting ONLY the broker uid via SO_PEERCRED. It:

  * pins the challenge PUBLIC key for ``verify_sig`` (it verifies the challenge document the authority
    signed, over the canonical payload bytes it reassembles itself),
  * pins the launcher/executor executable digests into every lease (from its OWN trusted config),
  * holds the supervisor-attestation PRIVATE key behind ``sign_attestation`` — it builds ``JCS(evidence)``
    itself from the broker's trusted run facts and signs THOSE bytes (never caller bytes).

``now_ms`` is always the supervisor's OWN clock, never from the wire. Fail-closed, Linux-only (SO_PEERCRED).

Run AS the supervisor account:  sudo -u brops-supervisor python3 run_supervisor.py --config <config.json>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "runtime")))

import live_crypto as lc  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
from governed_supervisor import SupervisorConfig, recompute_request_sha256  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    allowed_broker_uid = int(cfg["allowed_broker_uid"])
    sock_path = cfg["sockets"]["supervisor"]
    sup_attest_key_id = cfg["trust"]["supervisor_attestation_key_id"]
    launcher_sha = cfg["supervisor"]["launcher_executable_sha256"]
    executor_sha = cfg["supervisor"]["executor_executable_sha256"]

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

    config = SupervisorConfig(
        launcher_executable_sha256=launcher_sha,
        executor_executable_sha256=executor_sha,
        id_fn=lambda: uuid.uuid4().hex,
    )

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
            sign_attestation=sign_attestation,
            supervisor_attestation_key_id=sup_attest_key_id,
        )
    finally:
        try:
            os.unlink(sock_path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
