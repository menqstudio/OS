#!/usr/bin/env python3
"""Provision the LADDER additions on top of the live kit (Wave 3b, rev-30 §4.10(g)).

``provision_keys.py`` provisions everything the §5 ``op`` lifecycle needs: four keypairs, the
root-signed manifest, the protected store, the per-service IPC policies and the one shared
``config.json``. It provisions **nothing** the §4.10(g) sidecar ladder needs, because until now
nothing served that ladder — ``run_supervisor.py`` constructs no ``OpenService`` /
``StagingService`` / ``EvidenceRequestService`` / ``OutputReadService``, and an engine test
asserts that absence.

This tool writes the seven things the ladder additionally requires, and nothing else. Each is
listed with WHY it did not already exist:

1. **The three artifact byte strings, in their §4.10(g) canonical spellings.** The kit seeds
   ``store/generation_config`` with ``{"engine":"live","temperature":0}`` — the FROZEN
   raw-string form. §4.10(g) uses the OBJECT form, whose canonicalization is a different
   formula over a closed five-field shape, so the two digests differ by construction (the
   engine suite has a test whose whole job is that they must differ). The recorder opens
   ``store/system|history|generation_config`` BY NAME as fds 3/4/5, so the bytes the contained
   execution reads are those files: for the executed bytes to be the STAGED bytes, these three
   files must hold exactly what ``brops_canonical`` derives from the submit frame. They are
   derived here with the client's own public formulas — never re-spelled — and published into
   the content-addressed store as well, because staging addresses them by digest.

2. **``resolved.*_sha256`` in ``config.json``, re-pointed at those bytes.** The setuid launcher
   reads the attested request digests from a compiled-in path (``ATTESTED_REQUEST_PATH``) and
   refuses to exec when they disagree with the lease or with the descriptors it holds. Leaving
   the kit's originals there would mean the launcher pinning bytes the ladder never staged.

3. **A §4.2 challenge-key registry document.** ``OpenService`` resolves the registry from the
   supervisor's OWN state and verifies it under a binary-pinned root anchor; the kit ships no
   such document at all (``challenge_registry_handle`` in the kit config is literally
   ``sha256(pub_hex)``, provenance recorded rather than authority exercised). Signed HERE with
   the kit's root private key, which only root can read, and written into the TCB directory —
   or, when the TCB anchor is EXTERNAL, signed offline by that root over the bytes
   ``--emit-registry`` wrote in phase 1, and verified here under the anchor before anything is
   written (T-126). The anchor is ``tcb/root-anchor.json`` in both modes: one root, two artifacts.

4. **``supervisor-sidecar.ipc-policy.json``.** ``ipc_policy.load_allowed_peer_uid`` returns
   exactly ONE uid and refuses a file carrying two, and the supervisor front door needs two
   disjoint principals on one socket: the broker uid for the §5 ``op`` lifecycle and the
   sidecar uid for the six ``SIDECAR_PROTOCOLS``. A second root-owned policy file is how the
   sidecar's uid gets a custody story of its own rather than being read out of a config a
   service account can write. The loader is reused unchanged — no widening.

5. **``isolated-signer.ipc-policy.json``, re-pointed at the SUPERVISOR uid.** In the §5 chain
   the broker calls the signer, so the kit names the broker. In §6.1 steps 11-12 the
   SUPERVISOR hands the sign-request to the isolated signer (``AcceptanceDriver.sign_result``),
   and the broker is not in the ladder at all. This is a different deployment of the same rule,
   not a loosening of it: the file still names exactly one peer.

6. **``ladder.json``** — the ladder supervisor's own trusted config: the staging root, the
   registry document path, the root anchor in the §4.2 encoding, the epoch floor, the §2
   execution allowlist, the recorder argv template and the sidecar uid. Root-owned and
   non-writable, because the execution allowlist and the registry pin are exactly the kind of
   value a service account must not be able to rewrite.

7. **The turn itself** — the ``system`` / ``history`` / ``generation_config`` the submit frame
   will carry — recorded in ``ladder.json`` so the desktop side and the bytes hashed here have
   ONE source. Two copies of the same three fields is how the staged digest and the pinned
   digest come to disagree.

Run as ROOT, after ``provision_keys.py`` and before anything starts. It only writes bytes;
``run_ladder_turn.sh`` owns ownership and modes.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "runtime")))

import live_crypto as lc  # noqa: E402
import brops_canonical as bc  # noqa: E402
import challenge_key_registry as ckr  # noqa: E402

# ---------------------------------------------------------------------------
# The turn this kit proves. ONE definition; everything below derives from it.
# ---------------------------------------------------------------------------

#: §4.10(g)'s `system`, as the frame carries it (a string).
LADDER_SYSTEM = "you are Bro, a governed assistant"

#: §4.10(g)'s `history`, as the frame carries it (the closed {role, content} shape).
LADDER_HISTORY = [{"role": "user", "content": "hi"}]

#: §4.10(g)'s `generation_config` OBJECT form with the five FROZEN LITERAL defaults. This is
#: NOT the kit's `{"engine":"live","temperature":0}` — that is the frozen RAW-STRING form,
#: which §4.10(g)'s own mandatory test (i) requires to hash differently. The digest of this
#: object is asserted below against the value the design publishes.
LADDER_GENERATION_CONFIG = {
    "engine_id": "brops.governed-engine.sidecar.v1",
    "model": "claude-sonnet-5",
    "max_output_tokens": "4096",
    "temperature": "0.00",
    "top_p": "1.00",
}

#: The digest §4.10(g) prints for exactly those five literals. Asserted rather than trusted:
#: if the canonicalization or the literals move, this kit refuses to provision instead of
#: pinning bytes the design does not describe.
GENERATION_CONFIG_SHA256 = "732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22"

#: The §4.2 registry snapshot this supervisor accepts. The epoch equals the floor, which is
#: the tightest honest setting: a resurrected older snapshot is refused.
REGISTRY_EPOCH = 2
REGISTRY_ISSUED_AT_MS = 1_600_000_000_000
KEY_VALID_FROM_MS = 1
KEY_VALID_TO_MS = 2_000_000_000_000


def b64url_key(raw: bytes) -> str:
    """§4.2's key encoding: base64url of the raw 32 bytes, unpadded -> 43 characters."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def write_file(path: str, data: bytes, mode: int = 0o644) -> None:
    with open(path, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(path, mode)


def artifact_bytes() -> dict:
    """The three §2.4 artifacts, derived with the SUBMIT CLIENT's own public formulas.

    ``brops_canonical.system_bytes`` / ``history_bytes`` /
    ``governed_generation_config_bytes`` are the exact three functions
    ``governed_turn_submit.validate_submit_request`` applies to the frame, so the digest this
    kit pins into the lease and the digest the sidecar declares to §4.10(a) are one value
    computed once, not two spellings that happen to agree today.
    """
    data = {
        "system": bc.system_bytes(LADDER_SYSTEM),
        "history": bc.history_bytes(LADDER_HISTORY),
        "generation_config": bc.governed_generation_config_bytes(LADDER_GENERATION_CONFIG),
    }
    actual = bc.sha256_hex(data["generation_config"])
    if actual != GENERATION_CONFIG_SHA256:
        raise SystemExit(
            "the §4.10(g) generation_config canonicalization moved: %s != the published %s"
            % (actual, GENERATION_CONFIG_SHA256))
    return data


def build_registry_payload(challenge_pub_raw: bytes, root_key_id: str,
                           challenge_key_id: str) -> dict:
    """The §4.2 ``brops.challenge-key-registry.v1`` PAYLOAD — the bytes a root signs.

    The shape is exhaustive in both directions (``additionalProperties:false`` on the
    document, the payload and every key entry), and the revocation invariant is explicit:
    ``revoked == false`` REQUIRES ``revoked_at_ms`` to be ``null``. It is built by naming the
    field tuples the registry module publishes, so a schema change turns this into a
    provisioning failure rather than a runtime ``registry_unknown`` the sidecar cannot act on.
    """
    payload = {
        "artifact_type": ckr.REGISTRY_ARTIFACT_TYPE,
        "root_key_id": root_key_id,
        "registry_epoch": REGISTRY_EPOCH,
        "registry_issued_at_ms": REGISTRY_ISSUED_AT_MS,
        "keys": [{
            "challenge_key_id": challenge_key_id,
            "public_key": b64url_key(challenge_pub_raw),
            "valid_from_ms": KEY_VALID_FROM_MS,
            "valid_to_ms": KEY_VALID_TO_MS,
            "key_epoch": REGISTRY_EPOCH,
            "revoked": False,
            "revoked_at_ms": None,
        }],
    }
    if sorted(payload) != sorted(ckr.REGISTRY_PAYLOAD_FIELDS):
        raise SystemExit("the §4.2 payload field set moved; this provisioner is stale")
    if sorted(payload["keys"][0]) != sorted(ckr.REGISTRY_KEY_FIELDS):
        raise SystemExit("the §4.2 key-entry field set moved; this provisioner is stale")
    return payload


def assemble_registry_document(payload: dict, root_sig_b64url: str) -> dict:
    """The §4.2 document: the payload and a root signature over its canonical bytes."""
    document = {"payload": payload, "root_sig": root_sig_b64url}
    if sorted(document) != sorted(ckr.REGISTRY_DOC_FIELDS):
        raise SystemExit("the §4.2 document field set moved; this provisioner is stale")
    return document


def emit_registry(args) -> int:
    """PHASE 1 of the external-root ceremony for this kit: the registry bytes, and nothing else."""
    if not (args.keys_in and args.root_key_id):
        raise SystemExit("--emit-registry needs --keys-in and --root-key-id")
    if args.registry_sig_in:
        raise SystemExit("--registry-sig-in is phase 2; --emit-registry is phase 1")
    import provision_keys as pk  # the key id the kit config will carry, from its one definition
    with open(os.path.join(args.keys_in, "challenge.pub.hex"), "r", encoding="ascii") as fh:
        challenge_pub_raw = bytes.fromhex(fh.read().strip())
    message = ckr.canonical_bytes(
        build_registry_payload(challenge_pub_raw, args.root_key_id, pk.CHALLENGE_KEY_ID))
    out = os.path.abspath(args.emit_registry)
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    write_file(out, message, 0o644)
    print("PHASE 1 (ladder): the §4.2 registry payload, %d bytes, sha256=%s -> %s"
          % (len(message), bc.sha256_hex(message), out))
    print("  Sign it on the airgapped machine exactly as the manifest:")
    print("    python engine/ci/live/sign_manifest.py --manifest %s \\" % out)
    print("        --root-seed <root.private.seed> --sig-out <registry.sig> --expect-pub <hex>")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision the §4.10(g) ladder additions")
    ap.add_argument("--root-dir", required=True, help="the live kit root, e.g. /opt/brops-live")
    ap.add_argument("--sidecar-uid", type=int)
    ap.add_argument("--supervisor-uid", type=int)
    ap.add_argument("--broker-uid", type=int)
    ap.add_argument("--recorder-user",
                    help="the account the SUPERVISOR sudo's to for the recorder spawn")
    # The external-root ceremony. The §4.2 registry is the SECOND thing the root signs on this kit
    # — the key manifest is the first — and until T-126 only the kit's own `keys/root.priv` could
    # sign it, so a kit whose manifest an offline root had signed still could not provision.
    ap.add_argument("--emit-registry", default=None,
                    help="PHASE 1: write the canonical §4.2 registry payload bytes the offline root "
                         "signs, over the challenge key in --keys-in, and stop")
    ap.add_argument("--keys-in", default=None,
                    help="with --emit-registry: the keys directory `provision_keys.py "
                         "--emit-manifest` minted")
    ap.add_argument("--root-key-id", default=None,
                    help="with --emit-registry: the offline root's key id, as the manifest names it")
    ap.add_argument("--registry-sig-in", default=None,
                    help="PHASE 2: the offline root's detached signature over those bytes, as "
                         "`sign_manifest.py` writes it (standard base64). Required when the kit's "
                         "anchor is external; refused when it is not")
    args = ap.parse_args()

    if args.emit_registry:
        return emit_registry(args)
    missing = [f for f in ("sidecar_uid", "supervisor_uid", "broker_uid", "recorder_user")
               if getattr(args, f) is None]
    if missing:
        ap.error("required: " + ", ".join("--" + f.replace("_", "-") for f in missing))
    if args.keys_in or args.root_key_id:
        ap.error("--keys-in and --root-key-id belong to --emit-registry (phase 1) only")

    root = os.path.abspath(args.root_dir)
    tcb = os.path.join(root, "tcb")
    store = os.path.join(root, "store")
    config_path = os.path.join(root, "config.json")
    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    # §2.6 is not advisory: `handle_connection` refuses outright when the sidecar uid equals
    # the broker uid ("principal collapse"), and every gate below it would mean nothing under
    # that collapse. Refuse at provisioning, where the message is about accounts.
    principals = {
        "broker": args.broker_uid,
        "supervisor": args.supervisor_uid,
        "sidecar": args.sidecar_uid,
    }
    if len(set(principals.values())) != len(principals):
        raise SystemExit("§2.6: broker/supervisor/sidecar must be pairwise-distinct uids, got %r"
                         % principals)

    # ---- (3) the §4.2 registry document — FIRST, because it is the step that can refuse ----
    # An external anchor whose signature does not verify must stop the kit before it writes the
    # store or re-points the config, so "Nothing was written" is true when it is printed.------------------------------------------
    with open(cfg["keys"]["challenge_pub_hex"], "r", encoding="ascii") as fh:
        challenge_pub_raw = bytes.fromhex(fh.read().strip())
    # ONE anchor for both things the root signs: the TCB file `provision_keys.py` wrote, which
    # names the root that verified the key manifest and says whose custody it is.
    with open(os.path.join(tcb, "root-anchor.json"), "r", encoding="utf-8") as fh:
        anchor = json.load(fh)
    root_key_id = cfg["supervisor"]["challenge_registry_root_key_id"]
    if root_key_id != anchor["root_key_id"]:
        raise SystemExit("the config names registry root %r but the TCB anchor is %r"
                         % (root_key_id, anchor["root_key_id"]))
    payload = build_registry_payload(
        challenge_pub_raw, root_key_id, cfg["supervisor"]["challenge_key_id"])
    message = ckr.canonical_bytes(payload)
    if anchor["provenance"] == "external":
        # The kit holds no root private here and must not sign: the offline root already did, over
        # bytes phase 1 emitted from these same inputs. Rebuilding them and verifying is the check
        # that they ARE the same inputs — a signature over another challenge key fails here.
        if not args.registry_sig_in:
            raise SystemExit("the TCB anchor is external, so the §4.2 registry must be signed by that "
                             "root: pass --registry-sig-in (sign the bytes from --emit-registry "
                             "with sign_manifest.py). Nothing was written.")
        with open(args.registry_sig_in, "r", encoding="ascii") as fh:
            sig_std = fh.read().strip()
        if not lc.verify_b64std(lc.load_public_hex(anchor["public_key_hex"]), message, sig_std):
            raise SystemExit("--registry-sig-in does not verify over this kit's §4.2 registry payload "
                             "under the external anchor %s. Nothing was written."
                             % anchor["public_key_hex"])
        root_sig = base64.urlsafe_b64encode(base64.b64decode(sig_std, validate=True)) \
            .rstrip(b"=").decode("ascii")
    else:
        if args.registry_sig_in:
            raise SystemExit("--registry-sig-in given but the TCB anchor is %r, not external: a kit "
                             "that signs its own manifest signs its own registry"
                             % anchor["provenance"])
        with open(os.path.join(root, "keys", "root.priv"), "rb") as fh:
            root_sig = lc.sign_b64url(lc.load_private(fh.read()), message)
    registry_document = assemble_registry_document(payload, root_sig)
    registry_path = os.path.join(tcb, "challenge-key-registry.json")
    write_file(registry_path,
               json.dumps(registry_document, separators=(",", ":")).encode("utf-8"), 0o644)

    # The anchor's key material in §4.2's encoding. `RootAnchor` refuses anything but 43
    # base64url characters, and the kit publishes hex, so the conversion happens once, here.
    root_pub_b64url = b64url_key(bytes.fromhex(anchor["public_key_hex"]))

    # ---- (1) the three artifacts, in the §4.10(g) canonical spellings ----------------
    data = artifact_bytes()
    digests = {}
    for name, blob in data.items():
        digest = bc.sha256_hex(blob)
        digests[name] = digest
        # The NAMED file the recorder opens as fd 3/4/5...
        write_file(os.path.join(store, name), blob, 0o644)
        # ...and the CONTENT-ADDRESSED blob §4.10(c) publishes and the signer reads.
        write_file(os.path.join(store, digest), blob, 0o644)

    # ---- (2) re-point the attested request digests the launcher re-hashes against -----
    cfg["resolved"]["system_sha256"] = digests["system"]
    cfg["resolved"]["history_sha256"] = digests["history"]
    cfg["resolved"]["generation_config_sha256"] = digests["generation_config"]
    write_file(config_path, json.dumps(cfg, indent=2).encode("utf-8"), 0o644)

    # ---- (4)+(5) the two IPC policies -------------------------------------------------
    def ipc_policy(service: str, peer_uid: int) -> str:
        path = os.path.join(tcb, service + ".ipc-policy.json")
        write_file(path, json.dumps({
            "protocol": "brops.ipc-policy.v1",
            "service": service,
            "allowed_peer_uids": [peer_uid],
        }, separators=(",", ":")).encode("utf-8"), 0o644)
        return path

    sidecar_policy = ipc_policy("supervisor-sidecar", args.sidecar_uid)
    signer_policy = ipc_policy("isolated-signer", args.supervisor_uid)
    if signer_policy != cfg["ipc_policies"]["isolated-signer"]:
        raise SystemExit("the isolated-signer policy path moved; the signer would load the old one")

    # ---- (6)+(7) the ladder supervisor's own trusted config ---------------------------
    execution = cfg["execution"]
    recorder_command = list(execution["recorder_command"])
    # The kit builds `sudo -n -u <recorder> <bin>` for the BROKER. The ladder's spawner is the
    # SUPERVISOR, and the account it drops to must be stated here rather than inherited, so the
    # sudoers rule and this vector are generated from one value.
    if recorder_command[:4] != ["sudo", "-n", "-u", args.recorder_user]:
        raise SystemExit("unexpected recorder_command prefix %r" % (recorder_command[:4],))

    ladder = {
        "protocol": "brops.ladder-kit.v1",
        "sidecar_uid": args.sidecar_uid,
        "supervisor_uid": args.supervisor_uid,
        "broker_uid": args.broker_uid,
        "ipc_policies": {
            "supervisor-sidecar": sidecar_policy,
        },
        "registry": {
            "document_path": registry_path,
            "root_key_id": root_key_id,
            "root_public_key_b64url": root_pub_b64url,
            # The floor equals the snapshot's own epoch: an older snapshot — which is exactly
            # how a revoked key comes back to life — is refused rather than accepted as "not
            # newer".
            "epoch_floor": REGISTRY_EPOCH,
        },
        # §2's GOVERNED_EXECUTION_ALLOWLIST, as ONE digest: the generation_config this kit
        # provisioned. An empty allowlist refuses every turn; a wider one would admit configs
        # this deployment never staged.
        "execution_allowlist": [digests["generation_config"]],
        "staging_root": os.path.join(root, "supervisor-staging"),
        "recorder_command": recorder_command,
        "signer_socket": cfg["sockets"]["signer"],
        "hop_log": os.path.join(root, "ladder", "hops.jsonl"),
        # ONE definition of the turn. `ladder_desktop.py` reads these three fields to build the
        # submit frame; the digests beside them are what this tool hashed from exactly them.
        "turn": {
            "system": LADDER_SYSTEM,
            "history": LADDER_HISTORY,
            "generation_config": LADDER_GENERATION_CONFIG,
            "digests": digests,
        },
    }
    ladder_path = os.path.join(tcb, "ladder.json")
    write_file(ladder_path, json.dumps(ladder, indent=2).encode("utf-8"), 0o644)

    print("provisioned the §4.10(g) ladder additions under %s" % root)
    print("  system_sha256            : %s" % digests["system"])
    print("  history_sha256           : %s" % digests["history"])
    print("  generation_config_sha256 : %s" % digests["generation_config"])
    print("  registry document        : %s (epoch %d)" % (registry_path, REGISTRY_EPOCH))
    print("  sidecar ipc policy       : %s (uid %d)" % (sidecar_policy, args.sidecar_uid))
    print("  signer ipc policy        : %s (uid %d)" % (signer_policy, args.supervisor_uid))
    print("  ladder config            : %s" % ladder_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
