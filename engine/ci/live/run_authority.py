#!/usr/bin/env python3
"""Run the LIVE desktop-challenge-authority server (Wave 3b, rev-30 §2.1).

Binds the authority's AF_UNIX socket, builds its config with the challenge SIGNING key (the authority signs
each ``brops.governed-turn-challenge.v1`` document with the challenge private key), allowlists ONLY the
broker uid via SO_PEERCRED, and serves ``create-pending`` / ``issue`` forever. Fail-closed: Linux-only
(SO_PEERCRED), the signing key is loaded from the owner-only ``keys/challenge.priv``.

Run AS the challenge service account:  sudo -u brops-challenge python3 run_authority.py --config <config.json>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# engine/runtime holds the pure cores + the AF_UNIX front doors; this dir holds the crypto helpers.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "runtime")))

import live_crypto as lc  # noqa: E402
import challenge_authority_server as cas  # noqa: E402
from challenge_authority import AuthorityConfig, PendingStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    allowed_broker_uid = int(cfg["allowed_broker_uid"])
    sock_path = cfg["sockets"]["authority"]
    challenge_key_id = cfg["supervisor"]["challenge_key_id"]
    # SINGLE source: the supervisor block. The challenge names which supervisor may lease and
    # attest the turn, and that supervisor refuses a challenge addressed to anyone else
    # (governed_supervisor `supervisor_mismatch`), so the two must not be able to drift.
    supervisor_id = cfg["supervisor"]["supervisor_id"]

    with open(cfg["keys"]["challenge_priv"], "rb") as f:
        challenge_priv = lc.load_private(f.read())

    # The authority signs the canonical challenge bytes with the challenge private key (never any caller
    # bytes — issue_challenge hands sign_fn only the bytes it assembled from its own row).
    def sign_fn(message: bytes) -> str:
        return lc.sign_b64url(challenge_priv, message)

    def clock_ms() -> int:
        return int(time.time() * 1000)

    store = PendingStore()
    config = AuthorityConfig(
        challenge_key_id=challenge_key_id,
        supervisor_id=supervisor_id,
    )

    if os.path.exists(sock_path):
        os.unlink(sock_path)
    listener = cas.bind_listener(sock_path)
    # SO_PEERCRED is the trust gate (§2.1); make the socket connectable so the broker uid reaches accept().
    os.chmod(sock_path, 0o777)
    print("RESULT: authority listening sock=%s broker_uid=%d" % (sock_path, allowed_broker_uid), flush=True)

    def accept_one():
        return cas.accept_socket_conn(listener)

    try:
        cas.serve_forever(accept_one, allowed_broker_uid, store, config, sign_fn, clock_ms)
    finally:
        try:
            os.unlink(sock_path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
