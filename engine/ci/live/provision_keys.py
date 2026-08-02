#!/usr/bin/env python3
"""Provision the LIVE governed-turn trust material (Wave 3b).

Generates the four Ed25519 keypairs of the live chain, writes the ROOT-SIGNED production ``KeyManifest`` the
Rust broker pins, seeds the content-addressed protected store the isolated signer reads, and emits the ONE
shared ``config.json`` both the Python service runners and the Rust ``live_turn`` driver read. Private keys
stay server-side (each written under ``keys/`` for the owning service to load); only public-key hex + the
root-signed manifest + the anti-rollback floor cross to the broker's side.

Key topology (who holds what):

  * challenge          — authority SIGNS challenges (private); supervisor VERIFIES (public, pinned).
  * supervisor-attest  — supervisor SIGNS attestations (private); signer VERIFIES (public);
                         broker PINS (public, in the manifest as ``supervisor_attestation``).
  * receipt-signer     — signer SIGNS the §4.9 envelope (private); broker PINS (public, the Production
                         ``receipt_signing`` manifest key resolved by ``resolve_production_key``).
  * root               — this tool SIGNS the manifest (private, discarded/unused at runtime); broker PINS
                         the root PUBLIC key as the binary trust anchor (``PinnedRoot``).

The manifest bytes are built BYTE-IDENTICAL to ``key_manifest::KeyManifest::canonical_bytes`` (serde
``to_vec``: declaration field order, compact separators, snake_case enum, bare ints), so
``verify_manifest`` + ``resolve_production_key`` accept exactly this file.

Usage:
  provision_keys.py --root-dir /opt/brops-live --launcher-sha <hex> --executor-sha <hex>

``--launcher-sha`` / ``--executor-sha`` are the real digests of the provisioned setuid launcher + executor
image (the supervisor pins them into every lease). The caller (``run_live_turn.sh``) computes them from the
installed binaries and passes them here. File ownership/permissions are set by ``run_live_turn.sh`` (root);
this tool only writes the bytes so it is runnable/inspectable without root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_crypto as lc

# ---------------------------------------------------------------------------
# Fixed identities (mirror the constants the servers + driver agree on).
# ---------------------------------------------------------------------------
ROOT_KEY_ID = "brops-live-root-1"
CHALLENGE_KEY_ID = "brops-live-challenge-1"
SIGNER_KEY_ID = "brops-live-signer-1"
SUP_ATTEST_KEY_ID = "brops-live-sup-attest-1"

# MUST equal governed_verification.rs::RECEIPT_ENVELOPE_ARTIFACT_TYPE and isolated_signer.ENVELOPE_ARTIFACT_TYPE.
RECEIPT_ENVELOPE_ARTIFACT_TYPE = "brops.governed-receipt-envelope.v1"

MANIFEST_EPOCH = 2
KEY_VALID_FROM_MS = 1
KEY_VALID_TO_MS = 9_999_999_999_999
KEY_EPOCH = 2

# The identities the challenge/evidence carry + the signer allowlists gate on.
WORKSPACE_ID = "ws-live-1"
INSTALL_ID = "install-live-1"
RUN_ID = "run-live-1"
TASK_ID = "task-live-1"
SUPERVISOR_ID = "brops-live-supervisor"
EXECUTOR_ID = "brops-live-executor"
BUILDER_ID = "brops-live-builder"
POLICY_ID = "brops.live.policy"
POLICY_VERSION = "1"
AUTHOR = "Bro"
CONVERSATION_ID = "conv-live-1"
REQUESTED_AT_MS = 1_735_689_600_000  # fixed past epoch-ms; requested_at string is its decimal.

# The content-addressed store inputs (the isolated signer RE-DERIVES every *_sha256 from these bytes).
STORE_INPUTS = {
    "system": b"you are Bro, a governed assistant",
    "history": b"[]",
    "generation_config": b'{"engine":"live","temperature":0}',
    "policy_bundle": b'{"policy":"brops.live.policy.v1","rules":[]}',
    "containment_evidence": b'{"containment":"ok","namespace":"live"}',
    "record": b'{"record":"brops.live.record.v1"}',
    "lease": b'{"lease":"brops.live.store-lease.v1"}',
    "execution_receipt": b'{"execution_receipt":"brops.live.exec-receipt.v1"}',
}

EVIDENCE_FINAL_EVENT_HASH = "77" * 32
EVIDENCE_EVENT_COUNT = 3
EVIDENCE_LAST_SEQUENCE = 12
EVIDENCE_HEAD_SEQUENCE = 12

# Service account uids (already provisioned on the box; overridable for a test harness).
DEFAULT_UIDS = {
    "broker": 5001,
    "challenge": 5002,
    "supervisor": 5004,
    "recorder": 5005,
    "signer": 5006,
    "executor": 5007,
}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest_bytes(signer_pub_hex: str, sup_pub_hex: str) -> bytes:
    """Build the manifest JSON BYTE-IDENTICAL to ``serde_json::to_vec(&KeyManifest)``.

    serde serializes struct fields in declaration order with compact separators; the ``TrustClass`` enum is
    ``#[serde(rename_all = "snake_case")]`` so ``Production`` -> ``"production"``; bools are bare
    ``true``/``false`` and ints are bare. Python ``json.dumps`` with ``separators=(",",":")`` over an
    insertion-ordered dict reproduces those exact bytes (all values are ASCII).
    """

    def key(key_id: str, pub_hex: str) -> dict:
        # Field order MUST match struct ManifestKey.
        return {
            "key_id": key_id,
            "public_key_hex": pub_hex,
            "trust_class": "production",
            "valid_from_ms": KEY_VALID_FROM_MS,
            "valid_to_ms": KEY_VALID_TO_MS,
            "key_epoch": KEY_EPOCH,
            "revoked": False,
            "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE],
        }

    manifest = {
        # Field order MUST match struct KeyManifest.
        "manifest_epoch": MANIFEST_EPOCH,
        "root_key_id": ROOT_KEY_ID,
        "keys": [
            key(SIGNER_KEY_ID, signer_pub_hex),
            key(SUP_ATTEST_KEY_ID, sup_pub_hex),
        ],
    }
    return json.dumps(manifest, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_file(path: str, data: bytes, mode: int = 0o644) -> None:
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, mode)


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision LIVE governed-turn keys + manifest + store + config")
    ap.add_argument("--root-dir", required=True, help="e.g. /opt/brops-live")
    ap.add_argument("--launcher-sha", required=True, help="sha256 hex of the provisioned setuid launcher")
    ap.add_argument("--executor-sha", required=True, help="sha256 hex of the provisioned executor image")
    ap.add_argument("--recorder-bin", default=None, help="path to governed_recorder (for recorder_command)")
    ap.add_argument("--sudo-recorder-user", default="brops-recorder",
                    help="account the broker sudo's to for the recorder spawn")
    args = ap.parse_args()

    root = os.path.abspath(args.root_dir)
    keys_dir = os.path.join(root, "keys")
    store_dir = os.path.join(root, "store")
    sock_dir = os.path.join(root, "sock")
    report_dir = os.path.join(root, "report")
    tcb_dir = os.path.join(root, "tcb")
    bin_dir = os.path.join(root, "bin")
    for d in (keys_dir, store_dir, sock_dir, report_dir, tcb_dir, bin_dir):
        os.makedirs(d, exist_ok=True)

    # ---- (1) generate the four keypairs; write private (owner-loaded) + public hex ----
    challenge = lc.gen_private()
    sup_attest = lc.gen_private()
    signer = lc.gen_private()
    root_key = lc.gen_private()

    for name, k in (
        ("challenge", challenge),
        ("supervisor_attest", sup_attest),
        ("signer", signer),
        ("root", root_key),
    ):
        write_file(os.path.join(keys_dir, name + ".priv"), lc.priv_raw(k), 0o600)
        write_file(os.path.join(keys_dir, name + ".pub.hex"), lc.pub_hex(k).encode("ascii"), 0o644)

    signer_pub_hex = lc.pub_hex(signer)
    sup_pub_hex = lc.pub_hex(sup_attest)
    root_pub_hex = lc.pub_hex(root_key)

    # ---- (2) root-signed production KeyManifest (+ anti-rollback floor) ----
    manifest_bytes = build_manifest_bytes(signer_pub_hex, sup_pub_hex)
    manifest_sig_std = lc.sign_b64std(root_key, manifest_bytes)
    manifest_hash = sha256_hex(manifest_bytes)  # == KeyManifest::content_hash()

    manifest_path = os.path.join(root, "manifest.json")
    manifest_sig_path = os.path.join(root, "manifest.sig")
    floor_path = os.path.join(root, "floor.json")
    write_file(manifest_path, manifest_bytes, 0o644)
    write_file(manifest_sig_path, manifest_sig_std.encode("ascii"), 0o644)
    write_file(
        floor_path,
        json.dumps({"highest_epoch": MANIFEST_EPOCH, "highest_hash": manifest_hash}).encode("ascii"),
        0o644,
    )

    # ---- (3) seed the store: named fd inputs (recorder) + content-addressed blobs (signer) ----
    handles = {}
    for name, data in STORE_INPUTS.items():
        digest = sha256_hex(data)
        handles[name] = digest
        # content-addressed blob (the isolated signer reads store/<handle>)
        write_file(os.path.join(store_dir, digest), data, 0o644)
        # named file (the recorder opens store/system|history|generation_config as fd 3/4/5)
        if name in ("system", "history", "generation_config"):
            write_file(os.path.join(store_dir, name), data, 0o644)

    system_sha256 = handles["system"]
    history_sha256 = handles["history"]
    generation_config_sha256 = handles["generation_config"]

    recorder_bin = args.recorder_bin or os.path.join(bin_dir, "governed_recorder")
    recorder_command = ["sudo", "-n", "-u", args.sudo_recorder_user, recorder_bin]

    # ---- (4) the ONE shared config both sides read ----
    config = {
        "allowed_broker_uid": DEFAULT_UIDS["broker"],
        "uids": DEFAULT_UIDS,
        "sockets": {
            "authority": os.path.join(sock_dir, "authority.sock"),
            "supervisor": os.path.join(sock_dir, "supervisor.sock"),
            "signer": os.path.join(sock_dir, "signer.sock"),
        },
        "keys": {
            "challenge_priv": os.path.join(keys_dir, "challenge.priv"),
            "challenge_pub_hex": os.path.join(keys_dir, "challenge.pub.hex"),
            "supervisor_attest_priv": os.path.join(keys_dir, "supervisor_attest.priv"),
            "supervisor_attest_pub_hex": os.path.join(keys_dir, "supervisor_attest.pub.hex"),
            "signer_priv": os.path.join(keys_dir, "signer.priv"),
            "signer_pub_hex": signer_pub_hex,
            "supervisor_attest_pub_hex_value": sup_pub_hex,
        },
        "store_dir": store_dir,
        "trust": {
            "manifest_path": manifest_path,
            "manifest_sig_path": manifest_sig_path,
            "floor_path": floor_path,
            "root_key_id": ROOT_KEY_ID,
            "root_pub_hex": root_pub_hex,
            "signer_key_id": SIGNER_KEY_ID,
            "supervisor_attestation_key_id": SUP_ATTEST_KEY_ID,
        },
        "supervisor": {
            "launcher_executable_sha256": args.launcher_sha,
            "executor_executable_sha256": args.executor_sha,
            "challenge_key_id": CHALLENGE_KEY_ID,
        },
        "execution": {
            "recorder_command": recorder_command,
            "recorder_store_dir": store_dir,
            "launcher_path": os.path.join(tcb_dir, "privileged-launcher.bin"),
            "executor_path": os.path.join(tcb_dir, "contained-executor.bin"),
            "lease_file": os.path.join(tcb_dir, "executor.lease"),
            "cgroup_arg": "cgroup-live",
            "store_dir": store_dir,
            "report_dir": report_dir,
        },
        "facts": {
            "receipt_id": "receipt-live-" + uuid.uuid4().hex,
            "supervisor_id": SUPERVISOR_ID,
            "executor_id": EXECUTOR_ID,
            "builder_id": BUILDER_ID,
            "policy_id": POLICY_ID,
            "policy_version": POLICY_VERSION,
            "supervisor_attestation_key_id": SUP_ATTEST_KEY_ID,
            "policy_bundle_handle": handles["policy_bundle"],
            "containment_evidence_handle": handles["containment_evidence"],
            "record_handle": handles["record"],
            "lease_handle": handles["lease"],
            "execution_receipt_handle": handles["execution_receipt"],
            "evidence_final_event_hash": EVIDENCE_FINAL_EVENT_HASH,
            "evidence_event_count": EVIDENCE_EVENT_COUNT,
            "evidence_last_sequence": EVIDENCE_LAST_SEQUENCE,
            "evidence_head_sequence": EVIDENCE_HEAD_SEQUENCE,
        },
        "resolved": {
            "workspace_id": WORKSPACE_ID,
            "install_id": INSTALL_ID,
            "system_sha256": system_sha256,
            "history_sha256": history_sha256,
            "generation_config_sha256": generation_config_sha256,
            "requested_at": str(REQUESTED_AT_MS),
            "requested_at_ms": REQUESTED_AT_MS,
            "run_id": RUN_ID,
            "task_id": TASK_ID,
            "author": AUTHOR,
            "conversation_id": CONVERSATION_ID,
        },
        # Signer identity allowlists (the signer refuses an executor/builder/supervisor id it does not pin).
        "signer_allow": {
            "executor_ids": [EXECUTOR_ID],
            "builder_ids": [BUILDER_ID],
            "supervisor_ids": [SUPERVISOR_ID],
        },
    }
    config_path = os.path.join(root, "config.json")
    write_file(config_path, json.dumps(config, indent=2).encode("utf-8"), 0o644)

    print("provisioned live governed-turn material under %s" % root)
    print("  manifest bytes    : %d (sha256=%s)" % (len(manifest_bytes), manifest_hash))
    print("  signer pub hex    : %s" % signer_pub_hex)
    print("  sup-attest pub hex: %s" % sup_pub_hex)
    print("  root pub hex      : %s" % root_pub_hex)
    print("  config            : %s" % config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
