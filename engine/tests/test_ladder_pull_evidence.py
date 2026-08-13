"""The §4.10(f) live-pull VERDICT, tested where it can be tested: offline.

`engine/ci/live/run_ladder_turn.sh` drives the real §4.10(f) output pull on Linux — real service
uids, a real socket, the real one-shot sidecar, the real supervisor — and it is the only thing that
can. But the piece that DECIDES whether that run passed is
`engine/ci/live/ladder_evidence.py::check_pull`, and a verdict function whose only exercise is the
run it judges is exactly the arrangement this repository keeps getting caught by: both of its
PowerShell harnesses shipped checks that could not report PASS at all, and it took three audit
rounds to notice, because nothing ever ran them against an input they were supposed to refuse.

So every refusal `check_pull` can reach is driven here, by name, against a fixture that is a real
pull-evidence document in every other respect. The green path is driven too — a check that only
ever fails is the same defect wearing the other sign.

What is NOT claimed: none of this proves the pull works. It proves the JUDGE works. The pull itself
is proven only by a green `ladder-governed-turn` job on a real runner, and this file exists so that
a green one means something.

`HopLogged._read_detail` is tested beside it because the two are one mechanism: `check_pull` reads
`seq` and `ok` out of the hop log, and the supervisor's recorder is what puts them there. Before
2026-08-12 it recorded `{status: null, reason: null}` for every §4.10(f) frame — the §4.10(a0)/(d)
shape, which that protocol does not use — so the log said WHO was served and never WHICH range.

No prerequisite here is optional: everything is stdlib plus repo modules imported at module scope,
with no `try`/`except` and no `skipIf`, so a missing one is a hard error rather than a green run
with a quiet skip. Nothing is declared in ``BROPS_TEST_MISSING_PREREQUISITES`` — no declaration
exists anywhere in this tree — so nothing here may be softened.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_ROOT = os.path.dirname(TESTS_DIR)
for path in (os.path.join(ENGINE_ROOT, "ci", "live"), os.path.join(ENGINE_ROOT, "runtime"),
             os.path.join(os.path.dirname(ENGINE_ROOT), "bridge")):
    if path not in sys.path:
        sys.path.insert(0, path)

import ladder_evidence as le  # noqa: E402
import run_ladder_supervisor as rls  # noqa: E402
from governed_output_read import OUTPUT_READ_PROTOCOL, OUTPUT_READ_RESULT_PROTOCOL  # noqa: E402

SIDECAR_UID = 5003
BROKER_UID = 5001
OUTPUT = b"brops-exec-output.v1\nsystem=%s\n" % (b"a" * 64)
OUTPUT_SHA = hashlib.sha256(OUTPUT).hexdigest()
TOKEN = "T" * 43
RECEIPT_ID = "rcpt-0001"
ATTEMPT_ID = "attempt-0001"


def envelope(**overrides) -> dict:
    """The §4.9 envelope fields `check_pull` compares against. In the live tool this dict is the
    one whose SIGNATURE `check_envelope` verified two checks earlier — which is the whole reason
    comparing the pull's expectations against it is worth anything."""
    return dict({
        "output_sha256": OUTPUT_SHA,
        "output_bytes": len(OUTPUT),
        "receipt_id": RECEIPT_ID,
        "execution_attempt_id": ATTEMPT_ID,
    }, **overrides)


def pull_document(mode: str, observed: str, *, reads: int = 1, ok: bool = True,
                  **overrides) -> dict:
    """One `brops.ladder-output-pull-evidence.v1`, as the Rust driver writes it."""
    document = {
        "protocol": "brops.ladder-output-pull-evidence.v1",
        "mode": mode,
        "expected": observed,
        "observed": observed,
        "ok": ok,
        "output_stream_id": TOKEN,
        "presented_output_stream_id": TOKEN,
        "presented_receipt_id": RECEIPT_ID,
        "signed": {
            "receipt_id": RECEIPT_ID,
            "execution_attempt_id": ATTEMPT_ID,
            "run_id": "run-1",
            "output_sha256": OUTPUT_SHA,
            "output_bytes": len(OUTPUT),
        },
        "expected_chunks": 1,
        "reads_driven": reads,
        "chunks": [],
    }
    if observed == "ok":
        document["reassembled_bytes"] = len(OUTPUT)
        document["reassembled_sha256"] = OUTPUT_SHA
    document.update(overrides)
    return document


def hop(*, served_ok: bool, seq, protocol: str = OUTPUT_READ_PROTOCOL,
        peer_uid: int = SIDECAR_UID) -> dict:
    return {"ts_ms": 0, "protocol": protocol, "peer_uid": peer_uid, "supervisor_euid": 5004,
            "detail": {"status": None, "reason": None, "ok": served_ok, "seq": seq,
                       "eof": True, "requested_seq": seq}}


class _PullCase(unittest.TestCase):
    """Writes each pull document to a real file, because `check_pull` takes PATHS — and a fixture
    that bypassed the read would not exercise the `no_pull_evidence` arm at all."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.uids = {"sidecar": SIDECAR_UID, "desktop_broker": BROKER_UID}

    def write(self, *documents) -> list:
        paths = []
        for index, document in enumerate(documents):
            path = os.path.join(self.tmp.name, "pull-%d.json" % index)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(document, fh)
            paths.append(path)
        return paths

    def default_set(self):
        """One completed pull plus the four controls `run_ladder_turn.sh` drives."""
        return [
            pull_document("positive", "ok"),
            pull_document("unknown-stream", "refused:stream_unknown"),
            pull_document("binding-mismatch", "refused:stream_binding_mismatch"),
            pull_document("tampered-chunk", "digest_mismatch"),
            pull_document("truncated-chunk", "length_mismatch"),
        ]

    def default_hops(self, count: int = 5):
        """One served range per read the five runs drove. Only the first is `ok`: the two token
        negatives are refused before a byte is served, and the two tamper negatives are served a
        correct range that the DRIVER then breaks — so from the supervisor's side four of the five
        look like one ok read and two refusals, which is what the fixture below encodes."""
        hops = [hop(served_ok=True, seq=0)]
        hops.append(hop(served_ok=False, seq=0))
        hops.append(hop(served_ok=False, seq=0))
        hops.append(hop(served_ok=True, seq=0))
        hops.append(hop(served_ok=True, seq=0))
        return hops[:count]

    def refuses(self, reason, paths, env=None, hops=None, uids=None):
        with self.assertRaises(le.Failed) as caught:
            le.check_pull(paths, env or envelope(), hops if hops is not None
                          else self.default_hops(), uids or self.uids)
        self.assertEqual(caught.exception.reason, reason, caught.exception.detail)


class TheGreenPathTests(_PullCase):

    def test_a_completed_pull_with_four_refused_controls_passes(self):
        result = le.check_pull(self.write(*self.default_set()), envelope(),
                               self.default_hops(), self.uids)
        self.assertEqual(result["expected_chunks"], 1)
        self.assertEqual(result["reassembled_sha256"], OUTPUT_SHA)
        self.assertEqual(result["served_to_uid"], SIDECAR_UID)
        self.assertEqual(result["output_read_frames_served"], 5)
        self.assertEqual(result["served_seqs"], [0])
        self.assertEqual(result["negatives_refused_by_name"], [
            "digest_mismatch", "length_mismatch", "refused:stream_binding_mismatch",
            "refused:stream_unknown"])

    def test_a_multi_chunk_pull_requires_every_seq_in_order(self):
        """The live ladder's output is 322 bytes and takes ONE read, so the striding path cannot be
        reached there. It is reached here, because `check_pull`'s ordering rule is the only thing
        that would catch a supervisor serving `seq 2` twice and never serving `seq 1`."""
        documents = self.default_set()
        documents[0] = pull_document("positive", "ok", reads=3, expected_chunks=3)
        hops = [hop(served_ok=True, seq=0), hop(served_ok=True, seq=1), hop(served_ok=True, seq=2),
                hop(served_ok=False, seq=0), hop(served_ok=False, seq=0),
                hop(served_ok=True, seq=0), hop(served_ok=True, seq=0)]
        result = le.check_pull(self.write(*documents), envelope(), hops, self.uids)
        self.assertEqual(result["served_seqs"], [0, 1, 2])


class TheProvenanceOfTheGateTests(_PullCase):
    """The pull's expected length and digest must be the SIGNED ones.

    This is the property the whole §4.10(f) design turns on. §4.10(e) carries `output_bytes` and
    `output_sha256` as TRANSPORT-ONLY echoes, and a pull that compared its reassembly against those
    would be a check a compromised sidecar supplies both sides of. `pull_output`'s API refuses to
    take either as a parameter; these tests are the other end of the same rule — the verifier
    refusing to believe a driver that gated against anything but the verified envelope.
    """

    def test_a_pull_that_gated_against_another_digest_is_refused(self):
        documents = self.default_set()
        documents[0]["signed"]["output_sha256"] = "0" * 64
        self.refuses("pull_digest_provenance", self.write(*documents))

    def test_a_pull_that_gated_against_another_length_is_refused(self):
        documents = self.default_set()
        documents[0]["signed"]["output_bytes"] = len(OUTPUT) + 1
        self.refuses("pull_length_provenance", self.write(*documents))

    def test_a_pull_that_presented_another_turns_identity_is_refused(self):
        documents = self.default_set()
        documents[0]["signed"]["receipt_id"] = "rcpt-other"
        self.refuses("pull_identity_provenance", self.write(*documents))

    def test_bytes_that_do_not_hash_to_the_signed_digest_are_refused(self):
        documents = self.default_set()
        documents[0]["reassembled_sha256"] = hashlib.sha256(b"other").hexdigest()
        self.refuses("pull_reassembly", self.write(*documents))

    def test_a_reassembly_of_the_wrong_length_is_refused(self):
        documents = self.default_set()
        documents[0]["reassembled_bytes"] = len(OUTPUT) - 1
        self.refuses("pull_reassembly_length", self.write(*documents))


class TheHopLogPairingTests(_PullCase):
    """The half the driver cannot write.

    The driver's transcript is written by the process under test; the hop log is written by the
    SUPERVISOR, and every uid in it came from the kernel via SO_PEERCRED. Without this pairing a
    driver that read the store directly and reported a correct digest would pass, which on this kit
    is not even hypothetical: `/opt/brops-live/store` is world-readable.
    """

    def test_a_pull_with_no_served_read_is_refused(self):
        self.refuses("no_output_read_hops", self.write(*self.default_set()), hops=[])

    def test_reads_served_to_the_broker_are_refused(self):
        hops = [dict(h, peer_uid=BROKER_UID) for h in self.default_hops()]
        self.refuses("output_read_principal", self.write(*self.default_set()), hops=hops)

    def test_a_hop_log_of_other_protocols_does_not_count(self):
        hops = [hop(served_ok=True, seq=0, protocol="brops.governed-turn-open.v1")]
        self.refuses("no_output_read_hops", self.write(*self.default_set()), hops=hops)

    def test_fewer_served_reads_than_the_driver_drove_is_refused(self):
        self.refuses("output_read_count", self.write(*self.default_set()),
                     hops=self.default_hops(4))

    def test_more_served_reads_than_the_driver_drove_is_refused(self):
        """A read the driver never accounts for is a read something else drove."""
        self.refuses("output_read_count", self.write(*self.default_set()),
                     hops=self.default_hops() + [hop(served_ok=True, seq=0)])

    def test_a_supervisor_that_served_no_ok_range_is_refused(self):
        hops = [hop(served_ok=False, seq=0) for _ in range(5)]
        self.refuses("output_read_ranges", self.write(*self.default_set()), hops=hops)

    def test_ranges_served_out_of_order_are_refused(self):
        documents = self.default_set()
        documents[0] = pull_document("positive", "ok", reads=3, expected_chunks=3)
        hops = [hop(served_ok=True, seq=0), hop(served_ok=True, seq=2), hop(served_ok=True, seq=2),
                hop(served_ok=False, seq=0), hop(served_ok=False, seq=0),
                hop(served_ok=True, seq=0), hop(served_ok=True, seq=0)]
        self.refuses("output_read_sequence", self.write(*documents), hops=hops)


class TheShapeOfTheSetTests(_PullCase):

    def test_a_set_with_no_completed_pull_is_refused(self):
        """Four green negatives and nothing that worked proves the egress refuses everything."""
        self.refuses("no_pull_positive", self.write(*self.default_set()[1:]),
                     hops=self.default_hops(4))

    def test_a_set_with_no_failing_control_is_refused(self):
        """The sign-flipped defect, refused by name: a proof with no negative cannot fail."""
        self.refuses("no_pull_negative", self.write(self.default_set()[0]),
                     hops=self.default_hops(1))

    def test_two_completed_pulls_are_refused(self):
        documents = [self.default_set()[0], self.default_set()[0], self.default_set()[1]]
        self.refuses("no_pull_positive", self.write(*documents), hops=self.default_hops(3))

    def test_a_driver_run_that_missed_its_own_expectation_is_refused(self):
        """`ok:false` in the driver's own document means it observed something other than what it
        required. The verifier does not re-litigate that; it refuses the set."""
        documents = self.default_set()
        documents[3] = pull_document("tampered-chunk", "ok", ok=False)
        self.refuses("pull_expectation", self.write(*documents))

    def test_a_document_of_another_protocol_is_refused(self):
        documents = self.default_set()
        documents[0] = dict(documents[0], protocol="brops.something-else.v1")
        self.refuses("not_pull_evidence", self.write(*documents))

    def test_an_absent_document_is_refused(self):
        paths = self.write(*self.default_set())
        os.unlink(paths[0])
        self.refuses("no_pull_evidence", paths)


class TheHopDetailRecorderTests(unittest.TestCase):
    """`HopLogged._read_detail` — what the supervisor writes about a §4.10(f) frame.

    Two properties, and the second is why `bytes_b64` is not in the log: the hop log is evidence
    about WHO was served WHICH range, and a 245760-character field per line would bury it.
    """

    @staticmethod
    def request(seq=0, protocol=OUTPUT_READ_PROTOCOL):
        return {"protocol": protocol, "output_stream_id": TOKEN, "receipt_id": RECEIPT_ID,
                "execution_attempt_id": ATTEMPT_ID, "seq": seq}

    @staticmethod
    def served(seq=0, eof=True):
        return {"protocol": OUTPUT_READ_RESULT_PROTOCOL, "ok": True,
                "output_stream_id": TOKEN, "seq": seq, "bytes_b64": "AAAA", "eof": eof,
                "error": None}

    def test_a_served_range_records_its_seq_and_never_its_bytes(self):
        detail = rls.HopLogged._read_detail(self.request(3), self.served(3))
        self.assertEqual(detail["seq"], 3)
        self.assertEqual(detail["requested_seq"], 3)
        self.assertIs(detail["ok"], True)
        self.assertEqual(detail["chunk_bytes_b64_len"], 4)
        self.assertNotIn("bytes_b64", detail)
        self.assertIsNone(detail["refusal_reason"])

    def test_the_logged_seq_is_the_one_SERVED_not_the_one_asked_for(self):
        """`seq` follows the REPLY; `requested_seq` follows the request.

        Mutation testing found this gap: the first fixture used the same number for both, so a
        mutant that logged the requested seq instead of the served one survived. In a healthy run
        the supervisor echoes, and that is exactly why the distinction has to be pinned — the log
        exists to record what was SERVED, and a divergence between the two is precisely the thing
        it would be read to detect.
        """
        detail = rls.HopLogged._read_detail(self.request(4), self.served(2))
        self.assertEqual(detail["requested_seq"], 4)
        self.assertEqual(detail["seq"], 2)

    def test_a_refusal_records_its_published_reason(self):
        refused = {"protocol": OUTPUT_READ_RESULT_PROTOCOL, "ok": False,
                   "output_stream_id": TOKEN, "seq": 0, "bytes_b64": None, "eof": None,
                   "error": {"reason": "stream_unknown"}}
        detail = rls.HopLogged._read_detail(self.request(), refused)
        self.assertEqual(detail["refusal_reason"], "stream_unknown")
        self.assertIs(detail["ok"], False)
        self.assertIsNone(detail["chunk_bytes_b64_len"])

    def test_no_other_protocol_gains_output_read_fields(self):
        """§4.10(a0)/(a)(b)(c)/(d) answer with `{status, reason}` and have no `seq`. Adding empty
        §4.10(f) keys to their records would make the log's own shape a lie about what was asked."""
        detail = rls.HopLogged._read_detail(
            self.request(protocol="brops.governed-turn-open.v1"),
            {"status": "accepted", "reason": None})
        self.assertEqual(detail, {})

    def test_a_non_mapping_frame_records_nothing_rather_than_raising(self):
        """The hop logger runs after a reply has already been produced. A crash here would lose the
        evidence for a frame that was genuinely served."""
        self.assertEqual(rls.HopLogged._read_detail(None, self.served()), {})
        self.assertEqual(rls.HopLogged._read_detail(self.request(), None), {})


class TheVerifierIsNotOptionalTests(_PullCase):
    """`--pull-evidence` is optional; what it may NEVER do is turn a broken pull green.

    The negative ladder run passes none, because a refused turn mints no capability. That path is
    the reason the argument is optional at all, and it is also the shape a future edit could abuse
    to make the pull unreported — so the contract is pinned here: no documents means `check_pull`
    is not consulted, and any documents at all means every rule above applies.
    """

    def test_an_empty_set_never_reaches_the_checker(self):
        # `main` guards on `if args.pull_evidence`; called directly with nothing, the checker
        # itself must still refuse rather than return a hollow green.
        self.refuses("no_pull_positive", [], hops=[])


if __name__ == "__main__":
    unittest.main()
