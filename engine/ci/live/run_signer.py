#!/usr/bin/env python3
"""Run the LIVE isolated receipt-signer server (Wave 3b, rev-30 §7 / §4.9).

Binds the signer's AF_UNIX socket and serves ``sign-result`` forever, allowlisting ONLY the broker uid via
SO_PEERCRED. It is a RECOMPUTE-then-sign authority, never a ``sign(arbitrary_bytes)`` oracle:

  * it holds the receipt-signing PRIVATE key behind ``sign_fn`` (it signs ONLY its OWN recomputed 23-key
    ``brops.governed-receipt-envelope.v1`` payload, base64url-nopad so the broker verifies with
    URL_SAFE_NO_PAD),
  * it pins the supervisor-attestation PUBLIC key behind ``verify_attestation`` (it acts on nothing until the
    attestation over ``JCS(evidence)`` verifies),
  * its content-addressed store is a FILE-backed store over ``store_dir`` (each blob file is named by its
    own sha256; a read fails closed unless ``sha256(bytes) == handle``), so it RE-DERIVES
    ``output_sha256``/``output_bytes``/``request_sha256`` from the exact bytes THIS run produced.

Fail-closed, Linux-only (SO_PEERCRED).

Run AS the signer account:  sudo -u brops-signer python3 run_signer.py --config <config.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "runtime")))

import ipc_policy
import live_crypto as lc  # noqa: E402
import isolated_signer_server as iss  # noqa: E402
from isolated_signer import ArtifactStore, IsolatedSigner, SignerConfig, SignerError  # noqa: E402


class FileArtifactStore(ArtifactStore):
    """A content-addressed store backed by files under ``store_dir`` named by their sha256 handle. Reads at
    sign time (so the broker-written output blob is visible), and — like the dict store — refuses any blob
    whose bytes do not hash to the handle that names it (content-addressed integrity)."""

    def __init__(self, store_dir: str) -> None:
        super().__init__()  # empty in-memory backing; we override read_verified to hit disk
        self._dir = store_dir

    def read_verified(self, handle):  # type: ignore[override]
        # A handle is a 64-hex content address; reject anything else before touching the filesystem.
        if not isinstance(handle, str) or len(handle) != 64 or any(c not in "0123456789abcdef" for c in handle):
            return None
        path = os.path.join(self._dir, handle)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() != handle:
            raise SignerError("store corruption: blob digest != handle")
        return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # F-10: the peer-auth rule comes from this service's OWN root-owned IPC policy file, not
    # from the shared config the broker also writes its knobs into. That is what gives the
    # §2.5 floor a `isolated-signer.ipc-policy` artifact to measure, and what stops a service
    # account from widening who may talk to it. Fail-closed: no policy, no serving.
    allowed_broker_uid = ipc_policy.load_allowed_peer_uid(
        cfg["ipc_policies"]["isolated-signer"], "isolated-signer")
    sock_path = cfg["sockets"]["signer"]
    signer_key_id = cfg["trust"]["signer_key_id"]
    sup_attest_key_id = cfg["trust"]["supervisor_attestation_key_id"]
    store_dir = cfg["store_dir"]

    with open(cfg["keys"]["signer_priv"], "rb") as f:
        signer_priv = lc.load_private(f.read())
    sup_attest_pub = lc.load_public_hex(cfg["keys"]["supervisor_attest_pub_hex_value"])

    # sign_fn(private_key_handle, message): the signer hands us ONLY its OWN recomputed JCS(payload) bytes.
    # The opaque private_key_handle is the loaded Ed25519 key. base64url-nopad (broker verifies URL_SAFE_NO_PAD).
    def sign_fn(private_key_handle, message: bytes) -> str:
        return lc.sign_b64url(private_key_handle, message)

    # verify_attestation(key_handle, message, sig_b64): the pinned supervisor-attestation public key check.
    def verify_attestation(key_handle, message: bytes, sig_b64: str) -> bool:
        return lc.verify_b64url(key_handle, message, sig_b64)

    def clock_ms() -> int:
        return int(time.time() * 1000)

    store = FileArtifactStore(store_dir)
    config = SignerConfig(
        receipt_key_id=signer_key_id,
        receipt_private_key_handle=signer_priv,
        supervisor_attestation_key_id=sup_attest_key_id,
        supervisor_attestation_key_handle=sup_attest_pub,
        allowed_executor_ids=cfg["signer_allow"]["executor_ids"],
        allowed_builder_ids=cfg["signer_allow"]["builder_ids"],
        allowed_supervisor_ids=cfg["signer_allow"]["supervisor_ids"],
    )
    signer = IsolatedSigner(
        config=config,
        store=store,
        sign_fn=sign_fn,
        verify_attestation=verify_attestation,
        clock_ms=clock_ms,
    )

    if os.path.exists(sock_path):
        os.unlink(sock_path)
    listener = iss.bind_listener(sock_path)
    os.chmod(sock_path, 0o777)
    print("RESULT: signer listening sock=%s broker_uid=%d" % (sock_path, allowed_broker_uid), flush=True)

    def accept_one():
        return iss.accept_socket_conn(listener)

    try:
        iss.serve_forever(accept_one, allowed_broker_uid, signer)
    finally:
        try:
            os.unlink(sock_path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
