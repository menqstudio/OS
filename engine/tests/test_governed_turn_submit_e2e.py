"""§4.10(g) end to end — one submit frame in, one §4.6 frame out, through the REAL ladder.

`bridge/tests/test_governed_turn_submit.py` proves the CLIENT: what it accepts on `stdin`,
what it puts on the wire, in what order, and what it refuses to do locally. It does that
against a scripted supervisor, so it can prove shapes and order and nothing about verdicts.

This file proves the other half, and it is the half that has never existed: the orchestrator
driving the REAL `OpenService`, the REAL `StagingService` and the REAL
`EvidenceRequestService` — over a real durable ledger on a real file, a content-addressed
store whose handle IS the digest, four real Ed25519 keypairs, the real
`challenge_authority.issue_challenge`, the real §5 `AcceptanceDriver` and the real
`isolated_signer.IsolatedSigner` — and coming back with a §4.6 frame whose envelope actually
verifies. The fixture is `test_governed_acceptance._Case`, imported rather than rebuilt: a
second copy of four keypairs and a ledger is exactly the duplication the §5 file's own
prior-art rule refuses.

The one double is §6.1 step 5, the CONTAINED EXECUTION, which needs Linux, six service uids
and a setuid launcher. It is a typed seam whose shipped default (`RefusingExecutor`) refuses
`platform_unsupported` **pre-record**, so a stand-in is the only way any test on any platform
reaches step 6, and that is stated here rather than implied by a green run.

**§4.10(g) is PARTIAL.** Everything below is driven from a submit frame this test writes.
As of 2026-08-12 the trusted side CAN write one — `prepare_governed_turn_v1b` and
`governed_turn_submit_prepared` exist in `apps/desktop/src-tauri/core/src/` — but nothing in
production does: that helper has no caller, its subprocess spawn is an injected seam no
production code implements, and the broker's one production `GovernedExecutor` spawns the
recorder rather than a sidecar. Nor is there a counterparty: `engine/ci/live/run_supervisor.py`
constructs none of the three services this file constructs, which its own test asserts. So
this is a proof that the ladder WORKS, not that anything walks it.

No prerequisite here is optional: everything is stdlib plus repo modules imported at module
scope, with no `try`/`except` and no `skipIf`, so a missing prerequisite is a hard error
rather than a green run with a quiet skip. Nothing is declared in
`BROPS_TEST_MISSING_PREREQUISITES` — no declaration exists anywhere in this tree — so
nothing here may be softened.
"""

import hashlib
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
_BRIDGE = ROOT.parent / "bridge"
if str(_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_BRIDGE))
# `discover -s tests` puts this directory on the path; naming the module directly does not,
# and the §5 fixture below is imported by module name either way.
_TESTS = pathlib.Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import brops_canonical as bc  # noqa: E402
import governed_evidence_request as ger  # noqa: E402
import governed_staging_ledger as gstage  # noqa: E402
import governed_staging_upload as gsu  # noqa: E402
import governed_turn_open as gto  # noqa: E402
import governed_turn_result as gtr  # noqa: E402
import governed_turn_result_bridge as gtb  # noqa: E402
import governed_turn_submit as gts  # noqa: E402
from governed_supervisor import SupervisorError, _canonical_bytes  # noqa: E402

from test_governed_acceptance import (  # noqa: E402
    HISTORY_BYTES,
    REPLY_BYTES,
    SIDECAR_UID,
    SYSTEM_BYTES,
    _Case,
    b64u,
    sha,
    unb64u,
)

#: The §4.10(g) OBJECT form of `generation_config`, and the exact five FROZEN LITERAL
#: defaults §4.10(g)'s table locks. Its canonicalization is asserted below against the
#: digest the design publishes, so this fixture cannot drift from the normative document
#: without saying so.
GENERATION_CONFIG = {
    "engine_id": "brops.governed-engine.sidecar.v1",
    "model": "claude-sonnet-5",
    "max_output_tokens": "4096",
    "temperature": "0.00",
    "top_p": "1.00",
}
GENCFG_BYTES = bc.governed_generation_config_bytes(GENERATION_CONFIG)

#: The system/history the §5 fixture already publishes, in the shape §4.10(g)'s frame
#: carries them. The equality assertions in `TheCanonicalBytesAreTheFixturesTests` are what
#: make these two representations one fact rather than two.
SYSTEM = SYSTEM_BYTES.decode("utf-8")
HISTORY = [{"role": "user", "content": "hi"}]


class _SubmitCase(_Case):
    """`_Case` plus the three REAL services, wired behind one `request_supervisor` seam."""

    def setUp(self):
        super().setUp()
        self.sent = []

    # ---- the supervisor, as the sidecar actually reaches it ---------------------
    def supervisor(self, *, config=None, drive_acceptance=None):
        """One callable that routes a frame to the service that owns its protocol.

        This is the stand-in for `brops_socket.request`, and it is the ONLY thing standing
        in: every handler behind it is the production one, reached with the sidecar's own
        peer uid. A protocol with no route is an assertion failure rather than a refusal,
        because the submit subprocess sending a sixth protocol is a defect in the client and
        not a decision for a supervisor.
        """
        config = config or self.acceptance_config(allowlist={sha(GENCFG_BYTES)})
        open_service = gto.OpenService(
            config=config.open_config,
            allowed_sidecar_uid=SIDECAR_UID,
            publish_document=self.store.publish,
            resolve_registry_document=lambda: self.registry_document,
            verify_root_sig=self.verify_root_sig,
            verify_challenge_sig=self.verify_challenge_sig,
        )
        staging_service = gsu.StagingService(
            allowed_sidecar_uid=SIDECAR_UID,
            staging_root=str(self.staging_root),
            publish_artifact=self.store.publish,
        )
        evidence_service = ger.EvidenceRequestService(
            allowed_sidecar_uid=SIDECAR_UID,
            drive_acceptance=drive_acceptance or self.driver(config=config),
        )

        def call(frame, timeout_s):
            self.sent.append((frame["protocol"], timeout_s))
            protocol = frame["protocol"]
            if protocol == gto.OPEN_PROTOCOL:
                return open_service.handle(frame, peer_uid=SIDECAR_UID, conn=self.conn,
                                           clock_ms=lambda: self.clock)
            if protocol in gsu.STAGING_PROTOCOLS:
                return staging_service.handle(frame, peer_uid=SIDECAR_UID, conn=self.conn,
                                              clock_ms=lambda: self.clock)
            if protocol == ger.EVIDENCE_REQUEST_PROTOCOL:
                return evidence_service.handle(frame, peer_uid=SIDECAR_UID, conn=self.conn)
            raise AssertionError(
                "the submit subprocess sent %r, which is not one of its five hops" % protocol)

        return call

    # ---- the frame the desktop would write --------------------------------------
    def submit_frame(self, document=None, **overrides):
        document = document if document is not None else self.challenge_document(
            gencfg=GENCFG_BYTES)
        frame = {
            "protocol": gts.BRIDGE_SUBMIT_PROTOCOL,
            "task_id": document["payload"]["task_id"],
            "challenge_doc_b64": b64u(_canonical_bytes(document)),
            "system": SYSTEM,
            "history": HISTORY,
            "generation_config": GENERATION_CONFIG,
        }
        frame.update(overrides)
        return document, frame

    def drive(self, frame, **kwargs):
        return gts.drive_governed_turn(
            frame, request_supervisor=self.supervisor(**kwargs), sent=[])

    def protocols(self):
        return [protocol for protocol, _timeout in self.sent]


# ---------------------------------------------------------------------------
# The whole round trip
# ---------------------------------------------------------------------------


class TheGovernedTurnRoundTripTests(_SubmitCase):

    def test_one_submit_frame_becomes_one_signed_bridge_governed_turn_result(self):
        document, frame = self.submit_frame()
        reply = self.drive(frame)

        # It is a §4.6 frame, checked with the §4.6 validator rather than by reading keys.
        gtb.validate_bridge_turn_result(reply)
        self.assertEqual(reply["protocol"], gtb.BRIDGE_TURN_RESULT_PROTOCOL)
        self.assertIs(reply["ok"], True, reply)
        self.assertIsNone(reply["error"])
        self.assertEqual(len(reply["output_stream_id"]), gtr.OUTPUT_STREAM_ID_LEN)

        # And the envelope inside it is a REAL signature over real bytes, verified with the
        # fixture's own receipt key. Without this the test would prove transport only.
        receipt = reply["receipt"]
        self.assertTrue(self.receipt_key.verify(unb64u(receipt["envelope_jcs_b64"]),
                                                receipt["signature_b64"]))
        envelope = json.loads(unb64u(receipt["envelope_jcs_b64"]).decode("utf-8"))
        self.assertEqual(envelope["output_sha256"], sha(REPLY_BYTES))
        self.assertEqual(int(envelope["output_bytes"]), len(REPLY_BYTES))

        # §7.1's echo check, run here as the desktop would: every echo the transport carries
        # equals the VERIFIED envelope. A re-framer that altered one would be caught here.
        self.assertEqual(receipt["output_sha256"], envelope["output_sha256"])
        self.assertEqual(receipt["output_bytes"], int(envelope["output_bytes"]))
        self.assertEqual(receipt["run_id"], envelope["run_id"])
        self.assertEqual(receipt["execution_attempt_id"], envelope["execution_attempt_id"])

        # The turn the signature is about is the turn the frame asked for.
        self.assertEqual(envelope["request_nonce"], document["payload"]["request_nonce"])

    def test_the_hops_are_driven_in_the_locked_order_and_no_output_is_pulled(self):
        _document, frame = self.submit_frame()
        sent = []
        gts.drive_governed_turn(frame, request_supervisor=self.supervisor(), sent=sent)

        # §4.10(g): turn-open FIRST, then per artifact open/chunk/final in the §2.4 order,
        # then exactly one trigger. Written out in full rather than spot-checked, because
        # the ORDER is the contract and a subset assertion would admit a reordering.
        self.assertEqual(sent, [
            gto.OPEN_PROTOCOL,
            gsu.STAGING_OPEN_PROTOCOL, gsu.STAGING_CHUNK_PROTOCOL, gsu.STAGING_FINAL_PROTOCOL,
            gsu.STAGING_OPEN_PROTOCOL, gsu.STAGING_CHUNK_PROTOCOL, gsu.STAGING_FINAL_PROTOCOL,
            gsu.STAGING_OPEN_PROTOCOL, gsu.STAGING_CHUNK_PROTOCOL, gsu.STAGING_FINAL_PROTOCOL,
            ger.EVIDENCE_REQUEST_PROTOCOL,
        ])
        # §4.10(g): "This submit subprocess pulls NO output." Asserted against what went on
        # the wire, not against a reading of the code.
        self.assertNotIn("brops.governed-turn-output-read.v1", sent)

    def test_the_three_artifacts_are_published_under_the_challenges_own_digests(self):
        document, frame = self.submit_frame()
        self.drive(frame)

        row = gstage.load_staging(self.conn, document["payload"]["install_id"],
                                  document["payload"]["request_nonce"])
        self.assertEqual(row["state"], gstage.INPUTS_READY)
        for artifact, data in (("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
                               ("generation_config", GENCFG_BYTES)):
            handle = row[gstage.ARTIFACT_HANDLE_COLUMN[artifact]]
            self.assertEqual(handle, sha(data))
            # The store holds the EXACT bytes the client derived — not a re-encoding.
            self.assertEqual(self.store.read(handle), data)

    def test_the_exact_signed_document_bytes_reach_the_store_unaltered(self):
        """The client forwards `challenge_doc_b64` verbatim, so the bytes §4.10(a0)
        publishes are the bytes the desktop signed — never a re-encoding by this hop."""
        document, frame = self.submit_frame()
        self.drive(frame)
        published = self.store.read(sha(_canonical_bytes(document)))
        self.assertEqual(published, _canonical_bytes(document))

    def test_the_two_hop_budgets_are_applied_to_the_hops_they_name(self):
        _document, frame = self.submit_frame()
        self.drive(frame)
        budgets = {protocol: timeout for protocol, timeout in self.sent}
        self.assertEqual(budgets[gto.OPEN_PROTOCOL], gts.CONTROL_HOP_TIMEOUT_S)
        self.assertEqual(budgets[gsu.STAGING_CHUNK_PROTOCOL], gts.CONTROL_HOP_TIMEOUT_S)
        # The one hop that waits for an execution gets the execution budget.
        self.assertEqual(budgets[ger.EVIDENCE_REQUEST_PROTOCOL], gts.EXECUTION_HOP_TIMEOUT_S)


class TheCanonicalBytesAreTheFixturesTests(_SubmitCase):
    """The frame's three fields and the challenge's three digests are ONE fact."""

    def test_the_governed_generation_config_hashes_to_the_digest_the_design_publishes(self):
        # §4.10(g) prints this digest for exactly these five literals. If either side moves,
        # this is the line that says so.
        self.assertEqual(
            bc.governed_generation_config_sha256(GENERATION_CONFIG),
            "732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22")

    def test_the_object_form_is_not_the_frozen_raw_string_form(self):
        """§4.10(g)'s mandatory test (i): the two formulas MUST differ, so the governed
        chain cannot silently reuse the frozen `prepare_governed_turn(&str)` preparation."""
        frozen = bc.generation_config_sha256(json.dumps(GENERATION_CONFIG))
        self.assertNotEqual(frozen, bc.governed_generation_config_sha256(GENERATION_CONFIG))
        # And the frozen fixture's own literal, which pins the raw-string spelling.
        self.assertEqual(
            bc.generation_config_sha256('{"model":"claude","temperature":0}'),
            hashlib.sha256(b'{"model":"claude","temperature":0}').hexdigest())

    def test_the_frames_system_and_history_are_the_bytes_the_challenge_commits(self):
        _document, frame = self.submit_frame()
        submit = gts.validate_submit_request(frame)
        self.assertEqual(submit.artifact_bytes["system"], SYSTEM_BYTES)
        self.assertEqual(submit.artifact_bytes["history"], HISTORY_BYTES)
        self.assertEqual(submit.artifact_bytes["generation_config"], GENCFG_BYTES)


class UpstreamRefusalsAreProducedByTheSupervisorTests(_SubmitCase):
    """Each named refusal is produced BY THE REAL HANDLER through this client.

    Not a stubbed reply string: every reason below is a decision a production service made
    against its own durable state, reached by the exact frame the client sends.
    """

    def assertRefused(self, frame, stage, reason, **kwargs):
        with self.assertRaises(gts.UpstreamRefusal) as caught:
            self.drive(frame, **kwargs)
        self.assertEqual((caught.exception.stage, caught.exception.reason), (stage, reason))
        self.assertIn(stage, gts.DIAGNOSTIC_STAGES)
        return caught.exception

    def test_the_same_submit_frame_can_never_run_a_second_turn(self):
        """Replay, through the whole ladder rather than at one gate.

        The second drive gets PAST §4.10(a0): a re-open of a live row is idempotent by
        design (P1-6), so it returns `opened` with the same handle. It dies one message
        later, at §4.10(a), because the row it needs in `UPLOADING` has advanced to
        `INPUTS_READY` and never goes back — `trg_governed_turn_staging_transition` has no
        edge for it. So the anti-replay property is a property of the LADDER, and asserting
        it at the open alone would have asserted the wrong thing."""
        _document, frame = self.submit_frame()
        self.drive(frame)
        self.assertRefused(frame, "staging-open", gsu.REFUSE_NO_STAGING_ROW)

    def test_an_expired_challenge_is_refused_by_the_resource_admission_gate(self):
        document, frame = self.submit_frame()
        self.clock = document["payload"]["challenge_expires_at_ms"] + 1
        self.assertRefused(frame, "governed-turn-open", gto.REFUSE_CHALLENGE_EXPIRED)

    def test_a_system_the_challenge_did_not_commit_is_refused_digest_mismatch(self):
        """§4.10(g)'s test list, first half: the client declares the TRUE digest of the
        bytes it derived and the supervisor refuses it. A local pre-check here would make
        this reason unreachable through the only client that exists."""
        document, frame = self.submit_frame()
        frame["system"] = SYSTEM + " (tampered by a compromised sidecar)"
        self.assertRefused(frame, "staging-open", gsu.REFUSE_DIGEST_MISMATCH)

    def test_a_staging_open_before_the_turn_open_is_refused_no_staging_row(self):
        """§4.10(g)'s exact call-order test. The client cannot make this mistake — the
        `challenge_handle` a staging-open needs does not exist until the open returns — so
        the ordering claim is proved by driving the hop OUT of order by hand and showing
        the supervisor refuses it for the reason §4.10(a) publishes."""
        document, _frame = self.submit_frame()
        call = self.supervisor()
        data = SYSTEM_BYTES
        reply = call({
            "protocol": gsu.STAGING_OPEN_PROTOCOL,
            "install_id": document["payload"]["install_id"],
            "challenge_handle": sha(_canonical_bytes(document)),
            "request_nonce": document["payload"]["request_nonce"],
            "artifact": "system",
            "declared_len": len(data),
            "declared_sha256": sha(data),
        }, gts.CONTROL_HOP_TIMEOUT_S)
        self.assertEqual(reply["status"], gsu.STATUS_REFUSED)
        self.assertEqual(reply["reason"], gsu.REFUSE_NO_STAGING_ROW)

    def test_a_turn_whose_inputs_never_became_ready_is_refused_no_inputs_ready(self):
        """The §4.10(d) pre-acceptance arm, told apart from §4.10(e) by its own protocol
        const. Driven by opening a turn and triggering it with nothing staged."""
        document, _frame = self.submit_frame()
        call = self.supervisor()
        opened = call({
            "protocol": gto.OPEN_PROTOCOL,
            "install_id": document["payload"]["install_id"],
            "request_nonce": document["payload"]["request_nonce"],
            "challenge_doc_b64": b64u(_canonical_bytes(document)),
        }, gts.CONTROL_HOP_TIMEOUT_S)
        self.assertEqual(opened["status"], gto.STATUS_OPENED)
        reply = call({
            "protocol": ger.EVIDENCE_REQUEST_PROTOCOL,
            "install_id": document["payload"]["install_id"],
            "challenge_handle": opened["challenge_handle"],
            "request_nonce": document["payload"]["request_nonce"],
        }, gts.EXECUTION_HOP_TIMEOUT_S)
        self.assertEqual(reply["protocol"], ger.EVIDENCE_REQUEST_RESULT_PROTOCOL)
        self.assertEqual(reply["reason"], ger.REFUSE_NO_INPUTS_READY)
        # ...and the CLIENT turns that arm into an UpstreamRefusal rather than trying to
        # re-frame it. Driving the hop by hand proves the supervisor; this proves the half
        # the mutation harness showed was untested by the two assertions above.
        with self.assertRaises(gts.UpstreamRefusal) as caught:
            gts.drive_governed_turn(
                {"protocol": gts.BRIDGE_SUBMIT_PROTOCOL, "task_id": "t",
                 "challenge_doc_b64": b64u(_canonical_bytes(document)),
                 "system": SYSTEM, "history": HISTORY,
                 "generation_config": GENERATION_CONFIG},
                request_supervisor=lambda frame, timeout_s: reply
                if frame["protocol"] == ger.EVIDENCE_REQUEST_PROTOCOL else call(frame, timeout_s))
        self.assertEqual((caught.exception.stage, caught.exception.reason),
                         (ger.DIAGNOSTIC_STAGE, ger.REFUSE_NO_INPUTS_READY))

    def test_a_governed_verdict_refusal_is_relayed_as_a_4_6_frame_not_an_exception(self):
        """A `GOVERNED_REFUSAL_REASONS` member is a VERDICT, not an internal refusal, so it
        comes back as an `ok:false` §4.6 frame and never as an `UpstreamRefusal`. Produced
        by the real §5 driver: a `generation_config` outside the execution allowlist."""
        document, frame = self.submit_frame()
        reply = self.drive(frame, config=self.acceptance_config(allowlist=set()))
        gtb.validate_bridge_turn_result(reply)
        self.assertIs(reply["ok"], False)
        self.assertIsNone(reply["output_stream_id"])
        self.assertIsNone(reply["receipt"])
        self.assertEqual(reply["error"]["reason"], "model_profile_unknown")
        self.assertIn(reply["error"]["reason"], gtr.GOVERNED_REFUSAL_REASONS)


class TheSupervisorValidatesItsOwnSupplierTests(_SubmitCase):
    """A malformed §5 verdict never becomes a §4.6 frame — and it is refused one hop
    EARLIER than this client, which is worth recording rather than assuming.

    §4.10(d)'s own `handle_evidence_request` runs `validate_turn_result` over whatever
    `drive_acceptance` returns, so a supplier that answers with a half-built frame faults
    inside the supervisor and never reaches the wire at all. The client's matching guard is
    therefore exercised in `bridge/tests/test_governed_turn_submit.py`, against a scripted
    supervisor, because no real service can produce the input it refuses.
    """

    def test_a_half_built_verdict_faults_inside_the_supervisor_not_in_the_client(self):
        _document, frame = self.submit_frame()

        def liar(_gated):
            return {"protocol": gtr.GOVERNED_TURN_RESULT_PROTOCOL, "status": "signed"}

        with self.assertRaises(SupervisorError):
            self.drive(frame, drive_acceptance=liar)

    def test_a_reason_outside_the_closed_union_faults_inside_the_supervisor(self):
        _document, frame = self.submit_frame()

        def liar(_gated):
            return {"protocol": ger.EVIDENCE_REQUEST_RESULT_PROTOCOL,
                    "status": "refused", "reason": "a-reason-nobody-published"}

        with self.assertRaises(SupervisorError):
            self.drive(frame, drive_acceptance=liar)


class TheSupervisorIsNotDeployedTests(unittest.TestCase):
    """The ladder above works and NOTHING RUNS IT. This is the declaration, as a test."""

    def test_the_live_supervisor_constructs_none_of_the_three_services(self):
        source = (ROOT / "ci" / "live" / "run_supervisor.py").read_text(encoding="utf-8")
        for absent in ("OpenService", "StagingService", "EvidenceRequestService",
                       "OutputReadService"):
            self.assertNotIn(absent, source,
                             "run_supervisor.py now constructs %s — the §4.10(g) ladder has "
                             "a live counterparty and this declaration is stale" % absent)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
