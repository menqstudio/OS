#!/usr/bin/env python3
"""The DESKTOP half of one §4.10(g) turn: obtain a signed challenge, write the submit frame.

§4.10(g) starts with a `bridge.governed-turn-submit.v1` frame the desktop writes and the
sidecar reads off `stdin`. The desktop is the party that holds the turn's actual content and
the party the challenge authority will talk to, so this tool does exactly two things and stops:

  1. Drives the REAL live challenge authority — `create-pending` then `issue`, over its AF_UNIX
     socket, from the uid its root-owned IPC policy names. The authority RECOMPUTES
     `request_sha256` from its own stored row and signs the canonical bytes with the challenge
     private key; nothing here contributes a signature or a digest the authority did not derive.
  2. Writes the submit frame: the exact signed document, base64url'd, beside the three §4.10(g)
     fields.

It does NOT talk to the supervisor. That is the sidecar's job and it runs as a different
principal — which is the whole point of §2.6, and the reason this is a separate process rather
than a flag on the sidecar.

**The three digests are RECOMPUTED here, not copied.** `ladder.json` records both the turn's
three fields and the digests the provisioner hashed from them; this tool re-derives the digests
from the fields with `brops_canonical`'s own formulas and refuses to proceed if the two
disagree. A copied digest would make the challenge commit to whatever the provisioner wrote
down, and §4.10(a)'s `digest_mismatch` — the gate that catches exactly that divergence — would
be answering a question nobody had asked.

Run AS the account the authority's IPC policy names:
    sudo -u brops-verifier_broker python3 ladder_desktop.py --config <config.json> \
        --ladder <tcb/ladder.json> --out <submit.json> [--tamper]
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

import brops_canonical as bc  # noqa: E402
import brops_socket  # noqa: E402
from governed_supervisor import _canonical_bytes  # noqa: E402

#: The §4.10(g) ingress discriminator. Held as a literal here for the same reason
#: `engine_sidecar` holds one: this process must be able to write the frame without importing
#: the whole engine runtime the sidecar imports on the other side of the pipe.
BRIDGE_SUBMIT_PROTOCOL = "bridge.governed-turn-submit.v1"

#: The tamper the negative control applies. It is appended to `system` AFTER the authority has
#: signed a challenge committing to the ORIGINAL system digest, so the frame that reaches the
#: sidecar declares the TRUE digest of bytes the challenge does not commit — which is precisely
#: the §4.10(a) `digest_mismatch` the submit client deliberately does not pre-check locally.
TAMPER_SUFFIX = " (tampered by a compromised sidecar)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--ladder", required=True)
    ap.add_argument("--out", required=True, help="where to write the submit frame")
    ap.add_argument("--document-out", default=None,
                    help="where to write the signed challenge document (evidence)")
    ap.add_argument("--tamper", action="store_true",
                    help="negative control: send a `system` the challenge does not commit")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    with open(args.ladder, "r", encoding="utf-8") as fh:
        ladder = json.load(fh)

    turn = ladder["turn"]
    system = turn["system"]
    history = turn["history"]
    generation_config = turn["generation_config"]

    # Re-derived, then compared. See the module docstring.
    digests = {
        "system": bc.sha256_hex(bc.system_bytes(system)),
        "history": bc.sha256_hex(bc.history_bytes(history)),
        "generation_config": bc.sha256_hex(
            bc.governed_generation_config_bytes(generation_config)),
    }
    if digests != turn["digests"]:
        raise SystemExit(
            "the turn's fields and the provisioned digests disagree: derived %r, provisioned %r"
            % (digests, turn["digests"]))

    resolved = cfg["resolved"]
    for artifact, digest in digests.items():
        pinned = resolved[artifact + "_sha256"]
        if pinned != digest:
            raise SystemExit(
                "config.resolved.%s_sha256 is %s but this turn's %s hashes to %s; the launcher "
                "re-hashes the descriptors it holds against the former"
                % (artifact, pinned, artifact, digest))

    authority = cfg["sockets"]["authority"]
    now_ms = int(time.time() * 1000)
    facts = {
        "run_id": resolved["run_id"],
        "task_id": resolved["task_id"],
        "workspace_id": resolved["workspace_id"],
        "install_id": resolved["install_id"],
        # A FRESH nonce per invocation. The staging ledger and the acceptance ledger both key
        # on `(install_id, request_nonce)`, so reusing one would make the second run a replay —
        # a real refusal, but not the one a negative control is trying to demonstrate.
        "request_nonce": str(uuid.uuid4()),
        "system_sha256": digests["system"],
        "history_sha256": digests["history"],
        "generation_config_sha256": digests["generation_config"],
        # Strictly in the past: the request was made before the challenge was asked for.
        "requested_at_ms": now_ms - 1000,
    }

    pending = brops_socket.request(authority, dict(facts, op="create-pending"), timeout=15.0)
    if not pending.get("ok"):
        raise SystemExit("create-pending refused: %r" % (pending,))
    issued = brops_socket.request(
        authority,
        {"op": "issue", "pending_challenge_id": pending["pending_challenge_id"]},
        timeout=15.0)
    if not issued.get("ok"):
        raise SystemExit("issue refused: %r" % (issued,))
    document = issued["challenge"]

    # The EXACT bytes the authority signed. `_canonical_bytes` over `{payload, sig}` is the
    # same formula §4.10(a0) recomputes the challenge handle from, so the base64url below is
    # the document the supervisor will publish and address — not a re-encoding by this process.
    document_bytes = _canonical_bytes(document)
    frame = {
        "protocol": BRIDGE_SUBMIT_PROTOCOL,
        "task_id": document["payload"]["task_id"],
        "challenge_doc_b64": bc.b64url(document_bytes),
        "system": (system + TAMPER_SUFFIX) if args.tamper else system,
        "history": history,
        "generation_config": generation_config,
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(frame, fh, sort_keys=True)
    if args.document_out:
        with open(args.document_out, "w", encoding="utf-8") as fh:
            json.dump(document, fh, sort_keys=True, indent=2)

    print("RESULT: submit frame written uid=%d nonce=%s challenge_handle=%s tamper=%s"
          % (os.getuid(), document["payload"]["request_nonce"],
             bc.sha256_hex(document_bytes), args.tamper), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
