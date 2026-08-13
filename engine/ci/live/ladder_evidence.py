#!/usr/bin/env python3
"""Judge ONE §4.10(g) round trip and RECORD the evidence. Exits non-zero unless it completed.

This is the half of the proof that can fail. Everything before it produces artifacts; this
reads them and decides, independently of every process that produced them:

  * the reply is a §4.6 `bridge.governed-turn-result.v1` frame, checked with the bridge's own
    validator rather than by reading keys;
  * the root-signed key manifest verifies under the anchor in the TCB directory;
  * the §4.9 envelope's `key_id` resolves to a live, unrevoked `production` key IN that
    manifest, and the envelope SIGNATURE verifies over the exact `envelope_jcs_b64` bytes;
  * §7.1's echo check: every field the transport repeats equals the VERIFIED envelope;
  * the envelope's `request_sha256` equals the canonical request envelope RECOMPUTED from the
    three digests this turn staged — which is what binds the signature to these bytes and not
    to some other turn's;
  * `output_sha256` addresses bytes that are actually in the protected store, and those bytes
    are byte-identical to the reply the recorder captured;
  * the supervisor's own durable ledger says the staging row reached `INPUTS_READY` and the
    acceptance row reached `COMPLETED`;
  * the recorder's containment report names a `launcher_exit` of 0 and an `invoker_uid` that
    is the recorder's, not the caller's.

Any one of them failing exits non-zero with a named reason. That matters more than the green
path: both of this repository's PowerShell harnesses shipped checks that could not fail with
the sign flipped, and it survived three audit rounds. The negative control in
`run_ladder_turn.sh` drives this exact tool, in this exact mode, on a deliberately broken
input and REQUIRES a non-zero exit — so the failing branch is exercised on every run rather
than reasoned about.

The evidence bundle it writes is the deliverable Slice 2 asks for by name: the §4.6 frame, the
envelope, the digests, and the uids that ran each hop.

Run as ROOT (it reads the supervisor's 0700 ledger and the recorder's 0750 state).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "runtime")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "..", "bridge")))

import live_crypto as lc  # noqa: E402
import governed_turn_result_bridge as gtb  # noqa: E402
from governed_supervisor import _canonical_bytes  # noqa: E402
from isolated_signer import ENVELOPE_ARTIFACT_TYPE  # noqa: E402
from challenge_authority import recompute_request_sha256  # noqa: E402


class Failed(Exception):
    """A named verdict. The reason token is what the negative control greps for — a check
    that passes on any failure certifies nothing about the property it names."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__("%s: %s" % (reason, detail))
        self.reason = reason
        self.detail = detail


def unb64u(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, reason: str, detail: str) -> None:
    if not condition:
        raise Failed(reason, detail)


def read_json(path: str, reason: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        raise Failed(reason, "cannot read %s: %s" % (path, exc))


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def check_frame(reply) -> dict:
    """Is this a §4.6 frame that says the turn completed?

    An `ok:false` frame is a GOVERNED verdict — the supervisor decided and said so — and it is
    still a failure of this proof, because Slice 2 asks for a completed round trip. The reason
    is surfaced rather than flattened so the negative control can name the gate that fired.
    """
    require(isinstance(reply, dict), "not_a_frame", "the sidecar reply is not a JSON object")
    protocol = reply.get("protocol")
    if protocol != gtb.BRIDGE_TURN_RESULT_PROTOCOL:
        # `engine_sidecar` renders every out-of-band failure — ingress error, transport
        # failure, or a well-formed upstream internal refusal — as the protocol-less
        # `bridge.op.v1` document. §4.10(h) (**NOT IMPLEMENTED**) is the diagnostic frame that
        # would let the third be told apart from the first two; this tree builds no such frame
        # and no classifier for it, so the stage and the reason travel only in the `error`
        # text. That is as far as the provenance can honestly go today, and it is why the
        # negative control greps the reason token rather than reading a typed field.
        raise Failed("no_governed_frame",
                     "the sidecar returned %r, not a §4.6 frame: %s"
                     % (protocol, reply.get("error") if isinstance(reply, dict) else reply))
    try:
        gtb.validate_bridge_turn_result(reply)
    except Exception as exc:  # noqa: BLE001
        raise Failed("invalid_frame", "the §4.6 validator refused the reply: %s" % exc)
    if reply.get("ok") is not True:
        error = reply.get("error") or {}
        raise Failed("governed_refusal",
                     "the supervisor refused the turn: %s" % error.get("reason"))
    require(reply.get("output_stream_id"), "no_output_stream",
            "an ok §4.6 frame must carry an output_stream_id (§4.10(f))")
    receipt = reply.get("receipt")
    require(isinstance(receipt, dict), "no_receipt", "an ok §4.6 frame must carry a receipt")
    return receipt


def check_manifest(live_root: str, key_id: str) -> str:
    """Verify the root-signed manifest under the TCB anchor and resolve the receipt key.

    This is §7.1's trust resolution done by a process that produced none of it. It is
    deliberately NOT satisfied by "the signature verifies under whatever key came with it":
    the anchor is read from the root-owned TCB file, the manifest signature is checked under
    THAT key, and only then is `key_id` looked up inside the verified manifest.
    """
    anchor = read_json(os.path.join(live_root, "tcb", "root-anchor.json"), "no_anchor")
    with open(os.path.join(live_root, "manifest.json"), "rb") as fh:
        manifest_bytes = fh.read()
    with open(os.path.join(live_root, "manifest.sig"), "r", encoding="ascii") as fh:
        manifest_sig = fh.read().strip()
    root_pub = lc.load_public_hex(anchor["public_key_hex"])
    try:
        # The manifest signature is standard base64 WITH padding (`base64::STANDARD`), unlike
        # every `*_b64` on the wire. Verified directly rather than through `verify_b64url`.
        root_pub.verify(base64.b64decode(manifest_sig), manifest_bytes)
    except Exception as exc:  # noqa: BLE001
        raise Failed("manifest_unsigned", "the key manifest does not verify under the anchor: %s"
                     % exc)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    require(manifest.get("root_key_id") == anchor.get("root_key_id"), "manifest_root_mismatch",
            "the manifest names root %r, the anchor pins %r"
            % (manifest.get("root_key_id"), anchor.get("root_key_id")))
    for entry in manifest.get("keys", []):
        if entry.get("key_id") != key_id:
            continue
        require(entry.get("revoked") is False, "key_revoked", "%s is revoked" % key_id)
        require(entry.get("trust_class") == "production", "key_not_production",
                "%s is trust_class %r" % (key_id, entry.get("trust_class")))
        require(ENVELOPE_ARTIFACT_TYPE in (entry.get("allowed_protocols") or []),
                "key_protocol_denied",
                "%s may not sign %s" % (key_id, ENVELOPE_ARTIFACT_TYPE))
        return entry["public_key_hex"]
    raise Failed("key_unknown", "the envelope names key_id %r, which the manifest does not carry"
                 % key_id)


def check_envelope(receipt: dict, live_root: str) -> dict:
    envelope_b64 = receipt.get("envelope_jcs_b64")
    signature_b64 = receipt.get("signature_b64")
    require(isinstance(envelope_b64, str) and isinstance(signature_b64, str),
            "no_envelope", "the receipt carries no signed envelope")
    envelope_bytes = unb64u(envelope_b64)
    envelope = json.loads(envelope_bytes.decode("utf-8"))
    require(envelope.get("artifact_type") == ENVELOPE_ARTIFACT_TYPE, "not_an_envelope",
            "the signed payload is artifact_type %r" % envelope.get("artifact_type"))
    public_key_hex = check_manifest(live_root, envelope.get("key_id"))
    ok = lc.verify_b64url(lc.load_public_hex(public_key_hex), envelope_bytes, signature_b64)
    require(ok, "signature_invalid",
            "the §4.9 envelope signature does not verify under the manifest-resolved key")

    # §7.1's echo check, run as the desktop would: every echo the transport carries must equal
    # the VERIFIED envelope. A re-framer that altered one is caught here and nowhere else.
    for field in ("output_sha256", "run_id", "execution_attempt_id"):
        require(receipt.get(field) == envelope.get(field), "echo_mismatch",
                "receipt.%s=%r but the signed envelope says %r"
                % (field, receipt.get(field), envelope.get(field)))
    require(int(receipt.get("output_bytes", -1)) == int(envelope.get("output_bytes", -2)),
            "echo_mismatch", "receipt.output_bytes disagrees with the signed envelope")
    return envelope


def check_request_binding(envelope: dict, document: dict) -> None:
    """The signature is about THIS turn's bytes.

    `request_sha256` is the SHA-256 of the canonical `brops.request.v1` envelope over the
    workspace/install/nonce and the three artifact digests. Recomputing it here from the
    signed challenge payload and comparing it with the value inside the signed §4.9 envelope
    is what makes "the receipt is for the turn we submitted" a checked fact rather than a
    hopeful reading of two documents that both look plausible.
    """
    payload = document["payload"]
    expected = recompute_request_sha256({
        "workspace_id": payload["workspace_id"],
        "install_id": payload["install_id"],
        "request_nonce": payload["request_nonce"],
        "system_sha256": payload["system_sha256"],
        "history_sha256": payload["history_sha256"],
        "generation_config_sha256": payload["generation_config_sha256"],
        "requested_at_ms": payload["requested_at_ms"],
    })
    require(envelope.get("request_sha256") == expected, "request_binding",
            "the envelope's request_sha256 %r is not the recomputation over this turn's three "
            "staged digests (%r)" % (envelope.get("request_sha256"), expected))
    require(envelope.get("request_nonce") == payload["request_nonce"], "nonce_binding",
            "the envelope names request_nonce %r, this turn used %r"
            % (envelope.get("request_nonce"), payload["request_nonce"]))
    require(envelope.get("task_id") == payload["task_id"], "task_binding",
            "the envelope names task_id %r, this turn used %r"
            % (envelope.get("task_id"), payload["task_id"]))


def check_output(envelope: dict, live_root: str, report_path) -> dict:
    """`output_sha256` addresses bytes that exist, and they are the bytes the recorder wrote."""
    handle = envelope["output_sha256"]
    store_path = os.path.join(live_root, "store", handle)
    try:
        with open(store_path, "rb") as fh:
            blob = fh.read()
    except OSError as exc:
        raise Failed("output_unresolvable",
                     "the signed output handle %s addresses nothing in the store: %s"
                     % (handle, exc))
    require(sha(blob) == handle, "store_corruption",
            "store/%s does not hash to its own name" % handle)
    require(len(blob) == int(envelope["output_bytes"]), "output_length",
            "the envelope claims %s bytes, the stored blob is %d"
            % (envelope["output_bytes"], len(blob)))
    captured = None
    if report_path and os.path.exists(report_path):
        with open(report_path, "rb") as fh:
            captured = fh.read()
        require(captured == blob, "capture_divergence",
                "the recorder's captured reply is not the blob the envelope addresses")
    return {
        "output_handle": handle,
        "output_bytes": len(blob),
        "output_utf8_preview": blob[:512].decode("utf-8", "replace"),
        "recorder_report_matches_store": captured is not None and captured == blob,
    }


def check_ledger(live_root: str, document: dict, challenge_handle: str) -> dict:
    """What the SUPERVISOR's own durable state says happened.

    Read-only, over a URI connection, so this tool cannot write into the supervisor's private
    directory while the service that owns it is still running.
    """
    path = os.path.join(live_root, "supervisor-state", "supervisor-ledger.db")
    require(os.path.exists(path), "no_ledger", "the supervisor ledger is absent at %s" % path)
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except sqlite3.Error:
        # The ledger runs in WAL mode and its writer is still live, so a `mode=ro` connection
        # depends on the `-shm` file already existing and being readable. It normally is; the
        # fallback is a plain connection (SQLite is happy with a second process on a WAL
        # database) rather than a RED, because "the reader could not open it" is not evidence
        # about the turn. Nothing here writes: every statement below is a SELECT.
        conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        payload = document["payload"]
        staging = conn.execute(
            "SELECT state, system_handle, history_handle, generation_config_handle "
            "FROM governed_turn_staging WHERE install_id = ? AND request_nonce = ?",
            (payload["install_id"], payload["request_nonce"])).fetchone()
        require(staging is not None, "no_staging_row",
                "the supervisor has no §4.10(a0) staging row for this turn")
        require(staging["state"] == "INPUTS_READY", "staging_state",
                "the staging row is %r, not INPUTS_READY" % staging["state"])
        acceptance = conn.execute(
            "SELECT state, execution_attempt_id, receipt_id, lease_id, request_sha256, "
            "system_handle, history_handle, generation_config_handle "
            "FROM governed_turn_acceptance WHERE challenge_handle = ?",
            (challenge_handle,)).fetchone()
        require(acceptance is not None, "no_acceptance_row",
                "the supervisor has no §5 acceptance row for this challenge")
        require(acceptance["state"] == "COMPLETED", "acceptance_state",
                "the acceptance row is %r, not COMPLETED" % acceptance["state"])
        # The three handles the acceptance leased must be the three the staging published.
        for column in ("system_handle", "history_handle", "generation_config_handle"):
            require(acceptance[column] == staging[column], "handle_divergence",
                    "the acceptance row's %s is not the staged one" % column)
        return {
            "staging_state": staging["state"],
            "acceptance_state": acceptance["state"],
            "execution_attempt_id": acceptance["execution_attempt_id"],
            "receipt_id": acceptance["receipt_id"],
            "lease_id": acceptance["lease_id"],
            "staged_handles": {c: staging[c] for c in (
                "system_handle", "history_handle", "generation_config_handle")},
        }
    finally:
        conn.close()


#: The six protocols the sidecar's grant on the supervisor socket is exactly as wide as
#: (``governed_supervisor_server.SIDECAR_PROTOCOLS``). Restated here rather than imported so
#: this verifier does not depend on the module it is checking the behaviour of.
SIDECAR_PROTOCOLS = (
    "brops.governed-turn-open.v1",
    "brops.governed-staging-open.v1",
    "brops.governed-staging-chunk.v1",
    "brops.governed-staging-final.v1",
    "brops.governed-evidence-request.v1",
    "brops.governed-turn-output-read.v1",
)


def check_hops(hops: list, uids: dict) -> dict:
    """The uids that ran each hop — checked, not merely recorded.

    "Record the uids that ran each hop" is one of Slice 2's own words, and a log nobody reads
    is a file rather than evidence. Every uid here is ``conn.peer_uid``, which
    ``SocketPeerConn`` read from the kernel with ``SO_PEERCRED``; it is not a value any peer
    sent and not one the supervisor chose. Two properties are asserted over it:

      * every §4.10 hop was served to the SIDECAR uid — so the ladder really was walked by the
        seventh principal and not by whoever happened to be convenient;
      * that uid is not the broker's — the §2.6 collapse, which would make every ACL in this
        design mean nothing, did not silently happen.

    An absent or empty log is a RED. If the uids cannot be shown, they were not recorded.
    """
    sidecar = uids.get("sidecar")
    broker = uids.get("desktop_broker")
    require(isinstance(sidecar, int) and isinstance(broker, int), "no_uids",
            "the orchestrator recorded no sidecar/broker uids")
    require(sidecar != broker, "principal_collapse",
            "§2.6: the sidecar uid equals the broker uid (%r)" % sidecar)
    served = [h for h in hops if isinstance(h, dict) and h.get("protocol") in SIDECAR_PROTOCOLS]
    require(bool(served), "no_hops_recorded",
            "the supervisor's hop log records no §4.10 frame; the uids that ran each hop "
            "cannot be shown")
    for hop in served:
        require(hop.get("peer_uid") == sidecar, "hop_principal",
                "a %s frame was served to uid %r, not the sidecar uid %r"
                % (hop.get("protocol"), hop.get("peer_uid"), sidecar))
    return {"sidecar_uid": sidecar, "broker_uid": broker,
            "sidecar_frames_served": len(served),
            "protocols": sorted({h["protocol"] for h in served})}


def check_containment(live_root: str, attempt: str) -> dict:
    """The recorder's own account of the contained execution, for THIS attempt."""
    report_dir = os.path.join(live_root, "report")
    path = os.path.join(report_dir, "ladder-%s.out.containment.json" % attempt)
    document = read_json(path, "no_containment")
    require(document.get("protocol") == "brops.containment-evidence.v1", "not_containment",
            "%s is not a containment-evidence document" % path)
    require(document.get("launcher_exit") == 0, "launcher_refused",
            "the launcher exited %r; no contained execution completed"
            % document.get("launcher_exit"))
    require(document.get("launcher_gate") == "passed", "launcher_gate",
            "the launcher gate did not pass")
    return document


#: The §4.10(f) supervisor hop, as it appears in the hop log. Restated here for the same reason
#: ``SIDECAR_PROTOCOLS`` is: this verifier must not depend on the module whose behaviour it checks.
OUTPUT_READ_PROTOCOL = "brops.governed-turn-output-read.v1"


def check_pull(paths: list, envelope: dict, hops: list, uids: dict) -> dict:
    """Judge the §4.10(f) output PULL, from the driver's evidence and the SUPERVISOR's hop log.

    The pull driver (``apps/desktop/src-tauri/core/src/bin/ladder_output_pull.rs``) records what
    it asked and what came back. On its own that document proves nothing: it is written by the
    process under test, and on this kit the store is readable by anyone who can traverse it, so
    "I have the bytes and they hash correctly" is a claim a driver could make with no supervisor
    in the picture at all.

    What makes it evidence is the PAIRING. The hop log is written by the SUPERVISOR, into a file
    no other principal can write, and every uid in it is ``conn.peer_uid`` — read from the kernel
    with SO_PEERCRED, not a value any peer sent. So this function checks five things the driver
    could not have fabricated:

      * the supervisor actually served §4.10(f) reads, and served every one of them to the
        SIDECAR uid — the seventh principal, not the broker and not root;
      * it served exactly as many reads as the driver says it drove;
      * the positive pull's ranges are ``seq`` 0..n-1, in order, as the supervisor recorded them;
      * the digest the pull gated against is the ``output_sha256`` inside the envelope whose
        SIGNATURE this tool verified above — never §4.10(e)'s TRANSPORT-ONLY echo of the same
        value, which a compromised sidecar supplies both sides of;
      * every negative control refused, and refused for the reason it names.

    A set of pulls with no completed one is a RED, and so is a set with no failing one. The first
    would prove the egress refuses everything; the second would be a check that cannot fail.
    """
    documents = []
    for path in paths:
        document = read_json(path, "no_pull_evidence")
        require(document.get("protocol") == "brops.ladder-output-pull-evidence.v1",
                "not_pull_evidence", "%s is not a pull-evidence document" % path)
        require(document.get("ok") is True, "pull_expectation",
                "the %r pull expected %r and observed %r"
                % (document.get("mode"), document.get("expected"), document.get("observed")))
        documents.append(document)

    positives = [d for d in documents if d.get("observed") == "ok"]
    negatives = [d for d in documents if d.get("observed") != "ok"]
    require(len(positives) == 1, "no_pull_positive",
            "exactly one pull must have completed; %d did" % len(positives))
    require(bool(negatives), "no_pull_negative",
            "a pull proof with no failing control is a check that cannot fail - the defect both "
            "of this repository's PowerShell harnesses shipped through three audit rounds")
    positive = positives[0]

    # The gate was aimed at the SIGNED value. `envelope` is the one whose signature verified under
    # the manifest-resolved production key a few checks above.
    signed = positive.get("signed") or {}
    require(signed.get("output_sha256") == envelope.get("output_sha256"), "pull_digest_provenance",
            "the pull gated against %r; the VERIFIED envelope says %r"
            % (signed.get("output_sha256"), envelope.get("output_sha256")))
    require(int(signed.get("output_bytes", -1)) == int(envelope.get("output_bytes", -2)),
            "pull_length_provenance", "the pull's expected length is not the signed one")
    require(signed.get("receipt_id") == envelope.get("receipt_id")
            and signed.get("execution_attempt_id") == envelope.get("execution_attempt_id"),
            "pull_identity_provenance",
            "the pull presented an identity that is not the signed envelope's")
    require(positive.get("reassembled_sha256") == envelope.get("output_sha256"),
            "pull_reassembly", "the reassembled bytes do not hash to the signed output_sha256")
    require(int(positive.get("reassembled_bytes", -1)) == int(envelope.get("output_bytes", -2)),
            "pull_reassembly_length", "the reassembled length is not the signed output_bytes")

    # ---- the half the driver cannot write ------------------------------------------------
    sidecar = uids.get("sidecar")
    served = [h for h in hops
              if isinstance(h, dict) and h.get("protocol") == OUTPUT_READ_PROTOCOL]
    require(bool(served), "no_output_read_hops",
            "the supervisor's hop log records no %s frame: whatever the driver reports, no range "
            "was served through the §4.10(f) egress" % OUTPUT_READ_PROTOCOL)
    for hop in served:
        require(hop.get("peer_uid") == sidecar, "output_read_principal",
                "a %s frame was served to uid %r, not the sidecar uid %r"
                % (OUTPUT_READ_PROTOCOL, hop.get("peer_uid"), sidecar))
    driven = sum(int(d.get("reads_driven", 0)) for d in documents)
    require(len(served) == driven, "output_read_count",
            "the driver drove %d reads; the supervisor served %d" % (driven, len(served)))

    expected_chunks = int(positive.get("expected_chunks", 0))
    ok_hops = [h for h in served if (h.get("detail") or {}).get("ok") is True]
    require(len(ok_hops) >= expected_chunks, "output_read_ranges",
            "the signed length needs %d served ranges; the supervisor served %d ok reads"
            % (expected_chunks, len(ok_hops)))
    seqs = [(h.get("detail") or {}).get("seq") for h in ok_hops[:expected_chunks]]
    require(seqs == list(range(expected_chunks)), "output_read_sequence",
            "the served seqs are %r, not 0..%d" % (seqs, expected_chunks - 1))

    return {
        "runs": [{"mode": d.get("mode"), "expected": d.get("expected"),
                  "observed": d.get("observed"), "reads_driven": d.get("reads_driven")}
                 for d in documents],
        "expected_chunks": expected_chunks,
        "reassembled_bytes": positive.get("reassembled_bytes"),
        "reassembled_sha256": positive.get("reassembled_sha256"),
        "output_read_frames_served": len(served),
        "served_seqs": seqs,
        "served_to_uid": sidecar,
        "negatives_refused_by_name": sorted(d.get("observed") for d in negatives),
    }


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-root", required=True)
    ap.add_argument("--submit", required=True, help="the §4.10(g) frame the desktop wrote")
    ap.add_argument("--document", required=True, help="the signed challenge document")
    ap.add_argument("--reply", required=True, help="the sidecar's reply on stdout")
    ap.add_argument("--hop-log", required=True)
    ap.add_argument("--uids", required=True,
                    help="JSON map of hop -> uid, as the orchestrator invoked each one")
    ap.add_argument("--bundle", required=True, help="directory to write the evidence into")
    ap.add_argument("--pull-evidence", action="append", default=[],
                    help="a §4.10(f) pull-evidence document written by the Rust pull driver "
                         "(repeatable: the positive plus every negative control). Optional, "
                         "because the NEGATIVE ladder run never gets an ok frame and so has no "
                         "token to pull with - but when any is given, a set without exactly one "
                         "completed pull and at least one refused control is a RED.")
    args = ap.parse_args()

    os.makedirs(args.bundle, exist_ok=True)
    submit = read_json(args.submit, "no_submit_frame")
    document = read_json(args.document, "no_document")
    reply = read_json(args.reply, "no_reply")
    challenge_handle = sha(_canonical_bytes(document))

    bundle = {
        "protocol": "brops.ladder-proof-evidence.v1",
        "challenge_handle": challenge_handle,
        "submit_frame": submit,
        "challenge_document": document,
        "result_frame": reply,
        "uids": read_json(args.uids, "no_uids"),
        "hops": _read_hop_log(args.hop_log),
    }
    verdict = {"ok": False, "reason": None, "detail": None}
    try:
        receipt = check_frame(reply)
        envelope = check_envelope(receipt, args.live_root)
        check_request_binding(envelope, document)
        ledger = check_ledger(args.live_root, document, challenge_handle)
        containment = check_containment(args.live_root, ledger["execution_attempt_id"])
        output = check_output(
            envelope, args.live_root,
            os.path.join(args.live_root, "report",
                         "ladder-%s.out" % ledger["execution_attempt_id"]))
        # The acceptance row and the signed envelope must name ONE attempt. Without this the
        # ledger evidence above could describe a different run than the receipt does.
        require(envelope.get("execution_attempt_id") == ledger["execution_attempt_id"],
                "attempt_divergence",
                "the envelope names attempt %r, the ledger row %r"
                % (envelope.get("execution_attempt_id"), ledger["execution_attempt_id"]))
        principals = check_hops(bundle["hops"], bundle["uids"])
        # The §4.10(f) egress, judged only after the envelope it is gated against has been
        # verified: `check_pull` compares the pull's expected digest with `envelope`, and that
        # comparison is worth nothing until the signature over `envelope` has been checked.
        pull = check_pull(args.pull_evidence, envelope, bundle["hops"], bundle["uids"]) \
            if args.pull_evidence else None
        bundle.update({
            "envelope": envelope,
            "principals": principals,
            "ledger": ledger,
            "containment_evidence": containment,
            "output": output,
            "output_pull": pull,
            "digests": {
                "challenge_document_sha256": challenge_handle,
                "envelope_jcs_sha256": sha(unb64u(receipt["envelope_jcs_b64"])),
                "staged": ledger["staged_handles"],
                "output_sha256": envelope["output_sha256"],
                "attestation_evidence_sha256": envelope.get("attestation_evidence_sha256"),
            },
        })
        verdict = {"ok": True, "reason": None, "detail": None}
    except Failed as failure:
        verdict = {"ok": False, "reason": failure.reason, "detail": failure.detail}
    except Exception as exc:  # noqa: BLE001 — an unexpected fault is a RED, never a green
        verdict = {"ok": False, "reason": "verifier_fault", "detail": repr(exc)}

    bundle["verdict"] = verdict
    with open(os.path.join(args.bundle, "ladder-evidence.json"), "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, sort_keys=True, default=str)
    # The frame and the envelope also go out as their own files: a reader checking a signature
    # should not have to extract it from a wrapper first.
    _dump(args.bundle, "result-frame.json", reply)
    _dump(args.bundle, "submit-frame.json", submit)
    _dump(args.bundle, "challenge-document.json", document)
    if "envelope" in bundle:
        _dump(args.bundle, "receipt-envelope.json", bundle["envelope"])

    if verdict["ok"]:
        pull_note = "pull=not-driven"
        if bundle.get("output_pull"):
            pull_note = ("pull=ok chunks=%s served_to_uid=%s negatives=%s"
                         % (bundle["output_pull"]["expected_chunks"],
                            bundle["output_pull"]["served_to_uid"],
                            ",".join(bundle["output_pull"]["negatives_refused_by_name"])))
        print("RESULT: ladder-round-trip ok=true reason=none attempt=%s output_sha256=%s %s"
              % (bundle["ledger"]["execution_attempt_id"], bundle["digests"]["output_sha256"],
                 pull_note),
              flush=True)
        return 0
    print("RESULT: ladder-round-trip ok=false reason=%s detail=%s"
          % (verdict["reason"], verdict["detail"]), flush=True)
    return 1


def _dump(bundle_dir: str, name: str, value) -> None:
    with open(os.path.join(bundle_dir, name), "w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2, sort_keys=True, default=str)


def _read_hop_log(path: str) -> list:
    """The supervisor's per-frame record: protocol + the SO_PEERCRED uid the kernel reported.

    Absent or unreadable is recorded as such rather than raising: the hop log is EVIDENCE, and
    the verdict must not depend on the presence of a convenience file. Every property the
    verdict rests on is checked against the ledger, the store and the signature instead.
    """
    records = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except ValueError:
                        records.append({"unparsed": line})
    except OSError as exc:
        records.append({"hop_log_unavailable": str(exc)})
    return records


if __name__ == "__main__":
    raise SystemExit(main())
