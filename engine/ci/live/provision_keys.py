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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_crypto as lc

# ---------------------------------------------------------------------------
# Fixed identities (mirror the constants the servers + driver agree on).
# ---------------------------------------------------------------------------
# These are PUBLIC key_id label strings (they appear in the manifest/receipt/attestation),
# not secret key material — the private keys are generated at runtime into per-account 0400
# files and never committed. gitleaks' generic-api-key detector trips only because the
# constant names contain "KEY", so each public identifier is annotated as a known-safe value.
ROOT_KEY_ID = "brops-live-root-1"  # gitleaks:allow
CHALLENGE_KEY_ID = "brops-live-challenge-1"  # gitleaks:allow
SIGNER_KEY_ID = "brops-live-signer-1"  # gitleaks:allow
SUP_ATTEST_KEY_ID = "brops-live-sup-attest-1"  # gitleaks:allow

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
    # F-02/F-18: the `containment_evidence`, `record`, `lease` and `execution_receipt` STUBS are gone. They were literal
    # placeholder JSON the provisioner wrote once, whose content addresses every receipt of this
    # deployment then named — so the isolated signer's "deep protected-chain verification" only
    # proved that those constant bytes existed. The SUPERVISOR now builds the governed-turn record
    # and the execution receipt from its own acceptance + completion rows, and addresses the exact
    # canonical lease bytes it persisted at acceptance, publishing all three into this store per run.
    #
    # The RECORDER now writes a per-run containment report (`--containment-out`) which the broker
    # content-addresses into this store, so the containment handle names what this run actually did.
}

# (audit F-02/F-18, CLOSED) The four evidence-head values used to live here as deployment
# constants, so every receipt of the deployment named the same evidence head and the
# supervisor's anti-rollback floor compared a constant against itself. The RECORDER now builds
# a hash-linked chain of what it observed for each run and writes its head to `--evidence-out`;
# the broker reads that file and reports those values to `complete-run`. Nothing about the
# evidence head is configurable any more, which is why there is nothing left here.

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
    # ---- audit F-17: the root trust anchor's PROVENANCE -------------------------------------------
    # A kit that mints its own root, signs its own manifest with it, and then hands the matching public
    # key back to the verifier proves custody of nothing — the verifier checks a signature it supplied
    # both sides of. That is fine for exercising the chain, and NOT fine to report as production. So the
    # anchor is written to a TCB file that STATES which of the two it is, and the driver refuses to
    # print production_verified=true for a kit-generated one. Supplying an external anchor (with the
    # matching pre-signed manifest) is what makes the claim real.
    ap.add_argument("--login-uid", type=int, default=1000,
                    help="the interactive login account the §2.5 floor treats as untrusted (F-10)")
    ap.add_argument("--root-anchor-key-id", default=None,
                    help="EXTERNAL root key id (custody outside this kit); requires the three below")
    ap.add_argument("--root-anchor-pub-hex", default=None,
                    help="EXTERNAL root Ed25519 public key, 64 lowercase hex")
    ap.add_argument("--manifest-in", default=None,
                    help="pre-built KeyManifest JSON signed by the EXTERNAL root")
    ap.add_argument("--manifest-sig-in", default=None,
                    help="detached base64 signature over --manifest-in by the EXTERNAL root")
    args = ap.parse_args()

    external = (args.root_anchor_key_id, args.root_anchor_pub_hex, args.manifest_in, args.manifest_sig_in)
    if any(external) and not all(external):
        ap.error("an external root anchor needs ALL of --root-anchor-key-id/--root-anchor-pub-hex/"
                 "--manifest-in/--manifest-sig-in: a public key without the manifest IT signed would "
                 "leave the kit signing the manifest itself under someone else's name")
    use_external = all(external)
    if use_external:
        pub = args.root_anchor_pub_hex.strip().lower()
        if len(pub) != 64 or any(c not in "0123456789abcdef" for c in pub):
            ap.error("--root-anchor-pub-hex must be 64 lowercase hex characters")

    root = os.path.abspath(args.root_dir)
    keys_dir = os.path.join(root, "keys")
    store_dir = os.path.join(root, "store")
    sock_dir = os.path.join(root, "sock")
    report_dir = os.path.join(root, "report")
    tcb_dir = os.path.join(root, "tcb")
    bin_dir = os.path.join(root, "bin")
    # The supervisor's PRIVATE state directory (F-01). Unlike the deliberately-traversable
    # sock/report/store dirs — whose integrity is cryptographic, not filesystem — this one
    # holds the durable acceptance/lease/completion ledger the run attestation is rebuilt
    # from. It is the supervisor's authority, so run_live_turn.sh chowns it to the supervisor
    # account at mode 0700 and no other uid may read or write it.
    supervisor_state_dir = os.path.join(root, "supervisor-state")
    # The recorder's PRIVATE state (F-02): its monotonic evidence head-sequence counter. Like the
    # supervisor ledger this is an authority, not a shared work area — run_live_turn.sh chowns it
    # to the recorder account at 0700.
    evidence_state_dir = os.path.join(root, "recorder-state")
    for d in (keys_dir, store_dir, sock_dir, report_dir, tcb_dir, bin_dir, supervisor_state_dir,
              evidence_state_dir):
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
    if use_external:
        # The kit holds no root private key in this mode: it consumes a manifest the external root
        # already signed. It must not "fix up" the contents — the bytes signed are the bytes served.
        with open(args.manifest_in, "rb") as f:
            manifest_bytes = f.read()
        with open(args.manifest_sig_in, "r", encoding="utf-8") as f:
            manifest_sig_std = f.read().strip()
        anchor_key_id = args.root_anchor_key_id
        anchor_pub_hex = args.root_anchor_pub_hex.strip().lower()
        anchor_provenance = "external"
    else:
        manifest_bytes = build_manifest_bytes(signer_pub_hex, sup_pub_hex)
        manifest_sig_std = lc.sign_b64std(root_key, manifest_bytes)
        anchor_key_id = ROOT_KEY_ID
        anchor_pub_hex = root_pub_hex
        anchor_provenance = "kit_generated"
    manifest_hash = sha256_hex(manifest_bytes)  # == KeyManifest::content_hash()

    manifest_path = os.path.join(root, "manifest.json")
    manifest_sig_path = os.path.join(root, "manifest.sig")
    floor_path = os.path.join(root, "floor.json")
    # F-17: the anchor lives in the TCB directory beside the launcher and executor image — root-owned
    # and non-writable — NOT inline in the world-readable shared config the broker also reads its own
    # knobs from. `provenance` is load-bearing: the driver will not report production_verified=true
    # unless it says `external`.
    anchor_path = os.path.join(tcb_dir, "root-anchor.json")
    write_file(
        anchor_path,
        json.dumps(
            {
                "root_key_id": anchor_key_id,
                "public_key_hex": anchor_pub_hex,
                "provenance": anchor_provenance,
            },
            separators=(",", ":"),
        ).encode("utf-8"),
        0o644,
    )
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

    # ---- (3b) per-service IPC peer-auth policies (audit F-10) ----
    # These exist so the §2.5 floor's `*.ipc-policy` artifacts have something REAL to measure, and
    # so the peer-auth rule has custody of its own instead of living in the shared config the
    # broker also writes to. Each server loads only its own file, and refuses to serve without it.
    ipc_policies = {}
    for service in ("desktop-challenge-authority", "supervisor", "isolated-signer",
                    "trusted-verifier-broker"):
        path = os.path.join(tcb_dir, service + ".ipc-policy.json")
        write_file(path, json.dumps({
            "protocol": "brops.ipc-policy.v1",
            "service": service,
            # The broker is the CLIENT of every hop; nothing connects TO it. An empty allowlist is
            # the honest statement of that, and it is fail-closed if anything ever loads it.
            "allowed_peer_uids": [] if service == "trusted-verifier-broker"
                                 else [DEFAULT_UIDS["broker"]],
        }, separators=(",", ":")).encode("utf-8"), 0o644)
        ipc_policies[service] = path

    # ---- (4) the ONE shared config both sides read ----
    config = {
        # Kept for the Rust broker's own allowlist; the SERVERS no longer read their peer-auth
        # rule from here (F-10 — see `ipc_policies` below).
        "allowed_broker_uid": DEFAULT_UIDS["broker"],
        "uids": DEFAULT_UIDS,
        # F-10: the interactive login account. The §2.5 floor is evaluated by ROOT (only root can
        # read the whole pinned set — the setuid launcher is 4750 and the sudo allowlist lives in a
        # root-only directory), so `getuid()` there is 0 and says nothing about who is untrusted.
        # The floor's question is whether any LOGIN or RUNTIME principal can write a TCB artifact,
        # so the login uid has to be stated rather than observed.
        "login_uid": args.login_uid,
        "ipc_policies": ipc_policies,
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
            # F-10: the root-owned §2.5 pin manifest. Built by build_tcb_pin_manifest.py AFTER every
            # artifact exists and BEFORE any service starts, because the pin is a start-time
            # measurement of the deployment.
            "tcb_pin_manifest_path": os.path.join(tcb_dir, "tcb-pin-manifest.json"),
            # F-17: the anchor is a TCB FILE, not two config strings. `root_key_id`/`root_pub_hex` are
            # deliberately absent — the driver refuses a config that still carries them, so the
            # self-certifying "verifier reads the anchor out of the same file it reads its own knobs
            # from" arrangement cannot be re-expressed by editing config.
            "root_anchor_path": anchor_path,
            "signer_key_id": SIGNER_KEY_ID,
            "supervisor_attestation_key_id": SUP_ATTEST_KEY_ID,
        },
        "supervisor": {
            "launcher_executable_sha256": args.launcher_sha,
            "executor_executable_sha256": args.executor_sha,
            "challenge_key_id": CHALLENGE_KEY_ID,
            # F-01: the supervisor's OWN durable acceptance/lease/completion state. It is the
            # authority the run attestation is rebuilt from, so it lives in the supervisor
            # principal's private key directory — no other uid writes it.
            "ledger_db": os.path.join(supervisor_state_dir, "supervisor-ledger.db"),
            # F-01: the identity block the isolated signer ALLOWLISTS. These used to reach the
            # signed evidence through `attest-run {facts}` — i.e. the caller copied them out of
            # this world-readable config and named itself an allowed executor/builder. The
            # supervisor now takes them from its own provisioning and the caller cannot
            # contribute them at all.
            "supervisor_id": SUPERVISOR_ID,
            "executor_id": EXECUTOR_ID,
            "builder_id": BUILDER_ID,
            "policy_id": POLICY_ID,
            "policy_version": POLICY_VERSION,
            "policy_bundle_handle": handles["policy_bundle"],
            # Which pinned challenge-key registry snapshot authorized an acceptance, recorded
            # durably so an audit can tell what key material was in force for that turn.
            "challenge_registry_handle": sha256_hex(lc.pub_hex(challenge).encode("ascii")),
            "challenge_registry_hash": manifest_hash,
            "challenge_registry_epoch": KEY_EPOCH,
            "challenge_registry_root_key_id": anchor_key_id,
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
            # F-02: the recorder's OWN durable head-sequence counter. The evidence head has to
            # grow across runs for the supervisor's anti-rollback floor to mean anything, and
            # only durable state can do that — the constant it replaces made every turn of the
            # deployment claim the same head. Recorder-owned, 0700 (run_live_turn.sh).
            "evidence_state_dir": evidence_state_dir,
        },
        # The facts the EXECUTING CHAIN reports (via `complete-run`), and nothing else.
        #
        # F-01: `receipt_id`, `supervisor_id`, `executor_id`, `builder_id`, `policy_id`,
        # `policy_version`, `policy_bundle_handle` and `supervisor_attestation_key_id` used to
        # live here too, and the broker copied them into `attest-run {facts}`. They have moved
        # to the `supervisor` block above, which only the supervisor reads. They are deleted
        # rather than left behind, so nobody reading this config can conclude the broker still
        # supplies the identities the signer allowlists.
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
    print("  root anchor       : %s (%s)" % (anchor_key_id, anchor_provenance))
    print("  config            : %s" % config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
