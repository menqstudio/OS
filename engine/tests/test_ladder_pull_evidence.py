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

One prerequisite lives outside `engine/`, and it is named rather than assumed:
`ladder_evidence` imports the bridge's §4.6 frame parser, so the module calls
`_prerequisites.require(BRIDGE_TURN_RESULT)` before importing it. That SKIPS by name only off a CI
runner (a deployed box copies `engine/` alone) and FAILS on one. Everything else is stdlib plus
repo modules imported at module scope, with no `try`/`except` and no `skipIf`, so a missing one is
a hard error rather than a green run with a quiet skip. ``BROPS_TEST_MISSING_PREREQUISITES`` is not
consulted here: that declaration is the Rust `provision` crate's, set for one Windows job in
`.github/workflows/ci.yml`, and no Python suite reads it.
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
             os.path.join(os.path.dirname(ENGINE_ROOT), "bridge"), TESTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from _prerequisites import BRIDGE_TURN_RESULT, require  # noqa: E402

# Stated before the import it would otherwise break on: `ladder_evidence` imports the bridge's
# §4.6 frame parser at module scope, so on a tree that holds engine/ alone this module used to
# fail to LOAD ("No module named 'governed_turn_result_bridge'"). It skips by name there now, and
# under CI `require` FAILS rather than skipping.
require(BRIDGE_TURN_RESULT)

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
    to make the pull unreported — so the contract is pinned here, in both halves: `main` does not
    consult `check_pull` when no document is given and does when any is, and the checker itself
    refuses an empty set rather than passing it.
    """

    def test_the_checker_itself_refuses_an_empty_set(self):
        # `main` guards on `if args.pull_evidence`; called directly with nothing, the checker
        # itself must still refuse rather than return a hollow green.
        self.refuses("no_pull_positive", [], hops=[])

    def _run_main(self, pull_evidence):
        """Drive the real `main` with every OTHER check stood in for, so the one decision left
        is whether it consults `check_pull`. Returns (exit code, the calls it made, the bundle)."""
        from unittest import mock

        calls = []
        ledger = {"execution_attempt_id": ATTEMPT_ID, "staged_handles": {}}
        pulled = {"expected_chunks": 1, "served_to_uid": SIDECAR_UID,
                  "negatives_refused_by_name": ["refused"]}
        bundle_dir = os.path.join(self.tmp.name, "bundle-%d" % len(pull_evidence))
        argv = ["ladder_evidence.py", "--live-root", self.tmp.name, "--submit", "s", "--document", "d",
                "--reply", "r", "--hop-log", os.path.join(self.tmp.name, "absent.log"),
                "--uids", "u", "--bundle", bundle_dir]
        for path in pull_evidence:
            argv += ["--pull-evidence", path]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(le, "read_json", lambda path, reason: {}), \
                mock.patch.object(le, "check_frame",
                                  lambda reply: {"envelope_jcs_b64": ""}), \
                mock.patch.object(le, "check_envelope", lambda receipt, root: envelope()), \
                mock.patch.object(le, "check_request_binding", lambda env, document: None), \
                mock.patch.object(le, "check_ledger", lambda root, document, handle: ledger), \
                mock.patch.object(le, "check_containment", lambda root, attempt, uids: {}), \
                mock.patch.object(le, "check_output", lambda env, root, report: {}), \
                mock.patch.object(le, "check_hops", lambda hops, uids: {}), \
                mock.patch.object(le, "check_pull",
                                  lambda *args: calls.append(args[0]) or pulled), \
                mock.patch("builtins.print"):
            code = le.main()
        with open(os.path.join(bundle_dir, "ladder-evidence.json"), encoding="utf-8") as fh:
            return code, calls, json.load(fh)

    def test_main_does_not_consult_the_checker_when_no_document_is_given(self):
        code, calls, bundle = self._run_main([])
        self.assertEqual(code, 0, bundle["verdict"])
        self.assertEqual(calls, [])
        self.assertIsNone(bundle["output_pull"])

    def test_main_consults_the_checker_as_soon_as_one_document_is_given(self):
        code, calls, bundle = self._run_main(["one.json"])
        self.assertEqual(code, 0, bundle["verdict"])
        self.assertEqual(calls, [["one.json"]])
        self.assertEqual(bundle["output_pull"]["served_to_uid"], SIDECAR_UID)


# ---------------------------------------------------------------------------
# The OTHER checks. `check_pull` was the only verdict function with a unit test, while the tool's
# header said "the failing branch is exercised on every run": the kit's one negative fails in
# `check_frame`, the first check, so every later check's failing branch ran nowhere. One broken
# input and one NAMED reason each, with the passing input beside it so that a refuse-everything
# arm cannot satisfy any of them.
# ---------------------------------------------------------------------------

import base64  # noqa: E402
import sqlite3  # noqa: E402
from unittest import mock  # noqa: E402

import live_crypto as lc  # noqa: E402
from isolated_signer import ENVELOPE_ARTIFACT_TYPE  # noqa: E402

SIGNER_KEY_ID = "isolated-signer-key"
SUP_ATTEST_KEY_ID = "supervisor-attestation-key"
ROOT_KEY_ID = "root-key"
RECORDER_UID = 5005
NOW_MS = 1_800_000_000_000


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class _LiveRoot(unittest.TestCase):
    """A kit-shaped `--live-root`, built with real Ed25519 keys: the anchor, the root-signed
    manifest carrying BOTH kit keys with the receipt-envelope protocol (as `provision_keys`
    writes it), `config.json`, the store, the report directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        for sub in ("tcb", "store", "report", "supervisor-state"):
            os.mkdir(os.path.join(self.root, sub))
        self.root_key = lc.gen_private()
        self.signer_key = lc.gen_private()
        self.attest_key = lc.gen_private()
        self.keys = [self.key_entry(SIGNER_KEY_ID, self.signer_key),
                     self.key_entry(SUP_ATTEST_KEY_ID, self.attest_key)]
        self.write_json("config.json", {"trust": {"signer_key_id": SIGNER_KEY_ID}})
        self.write_json(os.path.join("tcb", "root-anchor.json"),
                        {"root_key_id": ROOT_KEY_ID, "public_key_hex": lc.pub_hex(self.root_key)})
        self.write_manifest()

    @staticmethod
    def key_entry(key_id, key, **overrides):
        return dict({"key_id": key_id, "public_key_hex": lc.pub_hex(key),
                     "trust_class": "production", "valid_from_ms": 1,
                     "valid_to_ms": 9_999_999_999_999, "key_epoch": 1, "revoked": False,
                     "allowed_protocols": [ENVELOPE_ARTIFACT_TYPE]}, **overrides)

    def write_json(self, name, document):
        with open(os.path.join(self.root, name), "w", encoding="utf-8") as fh:
            json.dump(document, fh)

    def write_manifest(self, *, root_key_id=ROOT_KEY_ID, signed_by=None):
        body = json.dumps({"manifest_epoch": 1, "root_key_id": root_key_id, "keys": self.keys},
                          separators=(",", ":")).encode("utf-8")
        with open(os.path.join(self.root, "manifest.json"), "wb") as fh:
            fh.write(body)
        with open(os.path.join(self.root, "manifest.sig"), "w", encoding="ascii") as fh:
            fh.write(lc.sign_b64std(signed_by or self.root_key, body))

    def refused(self, reason, call, *args, **kwargs):
        with self.assertRaises(le.Failed) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.reason, reason, caught.exception.detail)

    def signed_receipt(self, *, key=None, key_id=SIGNER_KEY_ID, **echo_overrides):
        body = {"artifact_type": ENVELOPE_ARTIFACT_TYPE, "key_id": key_id,
                "output_sha256": OUTPUT_SHA, "output_bytes": len(OUTPUT), "run_id": "run-1",
                "execution_attempt_id": ATTEMPT_ID}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        receipt = {"envelope_jcs_b64": b64u(raw),
                   "signature_b64": lc.sign_b64url(key or self.signer_key, raw),
                   "output_sha256": OUTPUT_SHA, "output_bytes": len(OUTPUT), "run_id": "run-1",
                   "execution_attempt_id": ATTEMPT_ID}
        receipt.update(echo_overrides)
        return receipt


class TheManifestCheckCanFailTests(_LiveRoot):

    def resolve(self, key_id=SIGNER_KEY_ID, now_ms=NOW_MS):
        return le.check_manifest(self.root, key_id, now_ms=now_ms)

    def test_the_signers_key_resolves(self):
        self.assertEqual(self.resolve(), lc.pub_hex(self.signer_key))

    def test_the_supervisors_attestation_key_is_not_the_receipt_signer(self):
        """The finding. That key is IN the root-signed manifest, live, `production`, and carries
        the receipt-envelope protocol, so every other rule here passes it."""
        self.refused("key_not_the_signer", self.resolve, SUP_ATTEST_KEY_ID)

    def test_a_config_with_no_signer_pin_refuses_rather_than_accepting_any_key(self):
        self.write_json("config.json", {"trust": {}})
        self.refused("no_signer_pin", self.resolve)

    def test_a_manifest_not_signed_by_the_anchor_is_refused(self):
        self.write_manifest(signed_by=lc.gen_private())
        self.refused("manifest_unsigned", self.resolve)

    def test_a_manifest_naming_another_root_is_refused(self):
        self.write_manifest(root_key_id="some-other-root")
        self.refused("manifest_root_mismatch", self.resolve)

    def test_each_key_rule_is_refused_by_its_own_name(self):
        for reason, override in (
            ("key_revoked", {"revoked": True}),
            ("key_not_production", {"trust_class": "development"}),
            ("key_protocol_denied", {"allowed_protocols": ["something.else.v1"]}),
            ("key_not_valid_now", {"valid_to_ms": NOW_MS - 1}),
            ("key_not_valid_now", {"valid_from_ms": NOW_MS + 1}),
            ("key_not_valid_now", {"valid_to_ms": None}),
        ):
            with self.subTest(reason=reason, override=override):
                self.keys[0] = self.key_entry(SIGNER_KEY_ID, self.signer_key, **override)
                self.write_manifest()
                self.refused(reason, self.resolve)

    def test_a_pinned_key_the_manifest_does_not_carry_is_unknown(self):
        self.keys = self.keys[1:]
        self.write_manifest()
        self.refused("key_unknown", self.resolve)


class TheEnvelopeCheckCanFailTests(_LiveRoot):

    def test_an_envelope_signed_by_the_isolated_signer_verifies(self):
        envelope_ = le.check_envelope(self.signed_receipt(), self.root)
        self.assertEqual(envelope_["output_sha256"], OUTPUT_SHA)

    def test_an_envelope_signed_by_the_SUPERVISOR_is_refused(self):
        """A correctly signed envelope, under a real manifest key, naming that key honestly."""
        receipt = self.signed_receipt(key=self.attest_key, key_id=SUP_ATTEST_KEY_ID)
        self.refused("key_not_the_signer", le.check_envelope, receipt, self.root)

    def test_a_signature_by_another_key_under_the_signers_name_is_invalid(self):
        receipt = self.signed_receipt(key=self.attest_key)
        self.refused("signature_invalid", le.check_envelope, receipt, self.root)

    def test_a_receipt_with_no_envelope_is_refused(self):
        self.refused("no_envelope", le.check_envelope, {"signature_b64": "x"}, self.root)

    def test_a_signed_payload_that_is_not_an_envelope_is_refused(self):
        raw = json.dumps({"artifact_type": "not.an.envelope"}).encode("utf-8")
        receipt = {"envelope_jcs_b64": b64u(raw),
                   "signature_b64": lc.sign_b64url(self.signer_key, raw)}
        self.refused("not_an_envelope", le.check_envelope, receipt, self.root)

    def test_every_transport_echo_must_equal_the_verified_envelope(self):
        for field, value in (("output_sha256", "0" * 64), ("run_id", "run-2"),
                             ("execution_attempt_id", "attempt-9"), ("output_bytes", 1)):
            with self.subTest(field=field):
                receipt = self.signed_receipt(**{field: value})
                self.refused("echo_mismatch", le.check_envelope, receipt, self.root)


class TheFrameCheckCanFailTests(unittest.TestCase):

    def refused(self, reason, reply):
        with self.assertRaises(le.Failed) as caught:
            le.check_frame(reply)
        self.assertEqual(caught.exception.reason, reason, caught.exception.detail)

    def frame(self, **overrides):
        return dict({"protocol": le.gtb.BRIDGE_TURN_RESULT_PROTOCOL, "ok": True,
                     "output_stream_id": TOKEN, "receipt": {"run_id": "run-1"}}, **overrides)

    def test_shapes_that_are_not_a_governed_frame(self):
        self.refused("not_a_frame", ["not", "a", "dict"])
        self.refused("no_governed_frame", {"protocol": "bridge.op.v1", "error": "transport"})
        self.refused("invalid_frame", self.frame())   # the REAL §4.6 validator refuses a stub

    def test_the_arms_behind_the_validator(self):
        """The §4.6 validator has its own tests; it is stubbed here so the three arms that sit
        BEHIND it can be reached with a small frame."""
        with mock.patch.object(le.gtb, "validate_bridge_turn_result", lambda frame: frame):
            self.assertEqual(le.check_frame(self.frame()), {"run_id": "run-1"})
            self.refused("governed_refusal",
                         self.frame(ok=False, error={"reason": "hash_mismatch"}))
            self.refused("no_output_stream", self.frame(output_stream_id=None))
            self.refused("no_receipt", self.frame(receipt=None))


class TheRequestBindingCheckCanFailTests(unittest.TestCase):

    PAYLOAD = {"workspace_id": "ws-1", "install_id": "install-1",
               "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
               "system_sha256": "a" * 64, "history_sha256": "b" * 64,
               "generation_config_sha256": "c" * 64, "requested_at_ms": 1_735_689_600_000,
               "task_id": "task-1"}

    def envelope(self, **overrides):
        payload = {k: v for k, v in self.PAYLOAD.items() if k != "task_id"}
        return dict({"request_sha256": le.recompute_request_sha256(payload),
                     "request_nonce": self.PAYLOAD["request_nonce"], "task_id": "task-1"},
                    **overrides)

    def refused(self, reason, **overrides):
        with self.assertRaises(le.Failed) as caught:
            le.check_request_binding(self.envelope(**overrides), {"payload": self.PAYLOAD})
        self.assertEqual(caught.exception.reason, reason, caught.exception.detail)

    def test_the_turns_own_envelope_binds(self):
        le.check_request_binding(self.envelope(), {"payload": self.PAYLOAD})

    def test_each_binding_is_refused_by_its_own_name(self):
        self.refused("request_binding", request_sha256="0" * 64)
        self.refused("nonce_binding", request_nonce="another-nonce")
        self.refused("task_binding", task_id="task-2")


class TheOutputCheckCanFailTests(_LiveRoot):

    def setUp(self):
        super().setUp()
        self.report = os.path.join(self.root, "report", "ladder-%s.out" % ATTEMPT_ID)
        self.put(os.path.join(self.root, "store", OUTPUT_SHA), OUTPUT)
        self.put(self.report, OUTPUT)

    @staticmethod
    def put(path, data):
        with open(path, "wb") as fh:
            fh.write(data)

    def test_a_stored_blob_identical_to_the_capture_passes(self):
        result = le.check_output(envelope(), self.root, self.report)
        self.assertEqual(result["output_bytes"], len(OUTPUT))
        self.assertIs(result["recorder_report_matches_store"], True)

    def test_an_ABSENT_capture_is_a_refusal_and_not_a_skipped_comparison(self):
        """The finding: removing the report used to turn the byte-identity check OFF."""
        os.unlink(self.report)
        self.refused("no_capture", le.check_output, envelope(), self.root, self.report)
        self.refused("no_capture", le.check_output, envelope(), self.root, None)

    def test_a_capture_that_differs_from_the_store_is_refused(self):
        self.put(self.report, OUTPUT + b"x")
        self.refused("capture_divergence", le.check_output, envelope(), self.root, self.report)

    def test_the_store_arms(self):
        self.refused("output_length", le.check_output,
                     envelope(output_bytes=len(OUTPUT) + 1), self.root, self.report)
        self.put(os.path.join(self.root, "store", OUTPUT_SHA), b"not those bytes")
        self.refused("store_corruption", le.check_output, envelope(), self.root, self.report)
        os.unlink(os.path.join(self.root, "store", OUTPUT_SHA))
        self.refused("output_unresolvable", le.check_output, envelope(), self.root, self.report)


class TheLedgerCheckCanFailTests(_LiveRoot):

    DOCUMENT = {"payload": {"install_id": "install-1", "request_nonce": "nonce-1"}}
    HANDLE = "d" * 64

    def build(self, *, staging="INPUTS_READY", acceptance="COMPLETED", accepted_system="s" * 64,
              with_staging=True, with_acceptance=True):
        path = os.path.join(self.root, "supervisor-state", "supervisor-ledger.db")
        if os.path.exists(path):
            os.unlink(path)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE governed_turn_staging (install_id, request_nonce, state, "
                     "system_handle, history_handle, generation_config_handle)")
        conn.execute("CREATE TABLE governed_turn_acceptance (challenge_handle, state, "
                     "execution_attempt_id, receipt_id, lease_id, request_sha256, system_handle, "
                     "history_handle, generation_config_handle)")
        if with_staging:
            conn.execute("INSERT INTO governed_turn_staging VALUES (?,?,?,?,?,?)",
                         ("install-1", "nonce-1", staging, "s" * 64, "h" * 64, "g" * 64))
        if with_acceptance:
            conn.execute("INSERT INTO governed_turn_acceptance VALUES (?,?,?,?,?,?,?,?,?)",
                         (self.HANDLE, acceptance, ATTEMPT_ID, RECEIPT_ID, "lease-1", "r" * 64,
                          accepted_system, "h" * 64, "g" * 64))
        conn.commit()
        conn.close()

    def check(self):
        return le.check_ledger(self.root, self.DOCUMENT, self.HANDLE)

    def test_a_completed_turn_is_read_back(self):
        self.build()
        result = self.check()
        self.assertEqual(result["acceptance_state"], "COMPLETED")
        self.assertEqual(result["execution_attempt_id"], ATTEMPT_ID)

    def test_each_ledger_arm_is_refused_by_its_own_name(self):
        self.refused("no_ledger", self.check)
        for reason, kwargs in (
            ("no_staging_row", {"with_staging": False}),
            ("staging_state", {"staging": "UPLOADING"}),
            ("no_acceptance_row", {"with_acceptance": False}),
            ("acceptance_state", {"acceptance": "EXECUTING"}),
            ("handle_divergence", {"accepted_system": "x" * 64}),
        ):
            with self.subTest(reason=reason):
                self.build(**kwargs)
                self.refused(reason, self.check)


class TheHopCheckCanFailTests(unittest.TestCase):

    UIDS = {"sidecar": SIDECAR_UID, "desktop_broker": BROKER_UID}

    def refused(self, reason, hops, uids=None):
        with self.assertRaises(le.Failed) as caught:
            le.check_hops(hops, self.UIDS if uids is None else uids)
        self.assertEqual(caught.exception.reason, reason, caught.exception.detail)

    def test_hops_served_to_the_sidecar_pass(self):
        result = le.check_hops([hop(served_ok=True, seq=0)], self.UIDS)
        self.assertEqual(result["sidecar_frames_served"], 1)

    def test_each_hop_arm_is_refused_by_its_own_name(self):
        self.refused("no_uids", [hop(served_ok=True, seq=0)], {"sidecar": SIDECAR_UID})
        self.refused("principal_collapse", [hop(served_ok=True, seq=0)],
                     {"sidecar": SIDECAR_UID, "desktop_broker": SIDECAR_UID})
        self.refused("no_hops_recorded", [])
        self.refused("no_hops_recorded", [{"hop_log_unavailable": "ENOENT"}])
        self.refused("hop_principal", [hop(served_ok=True, seq=0, peer_uid=BROKER_UID)])


class TheContainmentCheckCanFailTests(_LiveRoot):

    UIDS = {"recorder": RECORDER_UID}

    def report(self, **overrides):
        document = dict({"protocol": "brops.containment-evidence.v1", "launcher_exit": 0,
                         "launcher_gate": "passed", "invoker_uid": RECORDER_UID}, **overrides)
        self.write_json(os.path.join("report", "ladder-%s.out.containment.json" % ATTEMPT_ID),
                        document)

    def check(self, uids=None):
        return le.check_containment(self.root, ATTEMPT_ID, self.UIDS if uids is None else uids)

    def test_a_report_from_the_recorder_principal_passes(self):
        self.report()
        self.assertEqual(self.check()["invoker_uid"], RECORDER_UID)

    def test_a_report_whose_invoker_is_not_the_recorder_is_refused(self):
        """The header promised this check and no code performed it."""
        for invoker in (SIDECAR_UID, 0, True, None, str(RECORDER_UID)):
            with self.subTest(invoker=invoker):
                self.report(invoker_uid=invoker)
                self.refused("invoker_principal", self.check)

    def test_each_containment_arm_is_refused_by_its_own_name(self):
        self.refused("no_containment", self.check)
        self.report(protocol="something.else")
        self.refused("not_containment", self.check)
        self.report(launcher_exit=3)
        self.refused("launcher_refused", self.check)
        self.report(launcher_gate="refused")
        self.refused("launcher_gate", self.check)
        self.report()
        self.refused("no_uids", self.check, {})


# ---------------------------------------------------------------------------
# The kit runners' custody loaders, their shared store, and the ladder service graph.
# `load_allowed_peer_uid`, `load_tcb_json`, `Store`, `FileArtifactStore` and
# `build_ladder_services` were exercised by the root-only CI kit and by no test: the only test
# import of `run_ladder_supervisor` was `HopLogged._read_detail`.
# ---------------------------------------------------------------------------

import ipc_policy  # noqa: E402
import kit_store  # noqa: E402
import run_signer  # noqa: E402
import run_supervisor  # noqa: E402,F401 — imported so a runner that no longer imports is a RED here


class _AsRoot:
    """`fstat` that reports the file's REAL mode under a chosen owner.

    A test process cannot create a root-owned file, and on a root CI runner it cannot create
    one that is not. The owner is therefore stated, and everything else `fstat` returns --
    the type and the permission bits the rule also reads -- is the file's own.
    """

    def __init__(self, uid: int = 0):
        self.uid = uid
        self._real = os.fstat

    def __call__(self, fd):
        real = self._real(fd)
        fields = list(real)
        fields[4] = self.uid          # st_uid
        return os.stat_result(fields)


@unittest.skipUnless(os.name == "posix",
                     "the rule reads POSIX owner and mode bits; a Windows st_mode has neither, and "
                     "the services this loader guards only ever run on Linux")
class TheRootOwnedLoaderCanRefuseTests(unittest.TestCase):
    """`ipc_policy.read_root_owned_json` -- the ONE custody rule both callers now share."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "supervisor.ipc-policy.json")

    def write(self, document, mode=0o644, raw=None):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(raw if raw is not None else json.dumps(document))
        os.chmod(self.path, mode)

    def policy(self, **overrides):
        return dict({"protocol": "brops.ipc-policy.v1", "service": "supervisor",
                     "allowed_peer_uids": [BROKER_UID]}, **overrides)

    def load(self, owner=0):
        with mock.patch.object(ipc_policy.os, "fstat", _AsRoot(owner)):
            return ipc_policy.load_allowed_peer_uid(self.path, "supervisor")

    def refused(self, needle, owner=0):
        with self.assertRaises(ipc_policy.IpcPolicyError) as caught:
            self.load(owner)
        self.assertIn(needle, str(caught.exception))
        self.assertTrue(str(caught.exception).startswith("supervisor: "), str(caught.exception))

    def test_a_root_owned_policy_naming_one_peer_is_loaded(self):
        self.write(self.policy())
        self.assertEqual(self.load(), BROKER_UID)

    def test_custody_is_refused_by_name(self):
        self.write(self.policy())
        self.refused("is owned by uid 5004, not root", owner=5004)
        self.write(self.policy(), mode=0o664)
        self.refused("group/other-writable")
        self.write(self.policy(), mode=0o646)
        self.refused("group/other-writable")
        os.unlink(self.path)
        self.refused("cannot open the IPC policy")
        os.mkdir(self.path)
        self.refused("is not a regular file")

    def test_a_symlinked_policy_is_not_followed(self):
        target = os.path.join(self.tmp.name, "elsewhere.json")
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(self.policy(), fh)
        os.symlink(target, self.path)
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("no O_NOFOLLOW on this platform")
        self.refused("cannot open the IPC policy")

    def test_the_document_is_refused_by_name(self):
        self.write(None, raw="{not json")
        self.refused("is malformed")
        self.write(["a", "list"])
        self.refused("not a brops.ipc-policy.v1 document")
        self.write(self.policy(protocol="something.else"))
        self.refused("not a brops.ipc-policy.v1 document")
        self.write(self.policy(service="isolated-signer"))
        self.refused("a policy issued for a different service")
        for peers in ([BROKER_UID, SIDECAR_UID], [], [True], [-1], ["5001"], None):
            with self.subTest(peers=peers):
                self.write(self.policy(allowed_peer_uids=peers))
                self.refused("exactly one non-negative allowed_peer_uids entry")

    def test_the_ladder_supervisor_uses_the_same_rule_and_its_own_error(self):
        """`load_tcb_json` was a second copy that let `OSError` and `JSONDecodeError` escape
        raw. It is the shared rule now, and every refusal is a `LadderError`."""
        def load(owner=0):
            with mock.patch.object(ipc_policy.os, "fstat", _AsRoot(owner)):
                return rls.load_tcb_json(self.path)

        self.write({"registry": 1})
        self.assertEqual(load(), {"registry": 1})
        for prepare, needle, owner in (
            (lambda: None, "not root", 5004),
            (lambda: os.chmod(self.path, 0o664), "group/other-writable", 0),
            (lambda: self.write(None, raw="{not json"), "is malformed", 0),
            (lambda: os.unlink(self.path), "cannot open", 0),
        ):
            with self.subTest(needle=needle):
                prepare()
                with self.assertRaises(rls.LadderError) as caught:
                    load(owner)
                self.assertIn(needle, str(caught.exception))


class TheKitDecodesBase64StrictlyTests(unittest.TestCase):
    """`live_crypto` verified signatures through the lenient stdlib decode, which skips any
    character outside the alphabet."""

    def test_only_the_canonical_spelling_of_a_signature_verifies(self):
        key = lc.gen_private()
        message = b"the exact bytes"
        good = lc.sign_b64url(key, message)
        public = lc.load_public_hex(lc.pub_hex(key))
        self.assertTrue(lc.verify_b64url(public, message, good))
        for name, spelling in (("padded", good + "=="), ("newline", good[:9] + "\n" + good[9:]),
                               ("junk", good[:9] + "!" + good[9:]), ("space", good + " ")):
            with self.subTest(spelling=name):
                self.assertFalse(lc.verify_b64url(public, message, spelling))

    def test_the_verifier_names_a_malformed_wire_field(self):
        self.assertEqual(le.unb64u(b64u(b"abc")), b"abc")
        with self.assertRaises(le.Failed) as caught:
            le.unb64u(b64u(b"abc") + "=")
        self.assertEqual(caught.exception.reason, "not_base64url")


class TheSharedStoreTests(unittest.TestCase):
    """`kit_store` -- the file-backed store three runners each had a copy of."""

    class Boom(Exception):
        pass

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def test_publish_then_read_round_trips_and_is_idempotent(self):
        handle = kit_store.publish_blob(self.dir, OUTPUT)
        self.assertEqual(handle, OUTPUT_SHA)
        self.assertEqual(kit_store.publish_blob(self.dir, OUTPUT), handle)
        self.assertEqual(sorted(os.listdir(self.dir)), [handle], "no temp file may survive")
        self.assertEqual(kit_store.read_blob(self.dir, handle, error=self.Boom), OUTPUT)

    def test_read_refuses_what_is_not_a_handle_before_touching_the_filesystem(self):
        for bad in ("../" + "a" * 61, "A" * 64, "a" * 63, None, 7, "a" * 64 + "\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.Boom):
                    kit_store.read_blob(self.dir, bad, error=self.Boom)

    def test_read_refuses_a_blob_that_is_not_its_own_name(self):
        with open(os.path.join(self.dir, OUTPUT_SHA), "wb") as fh:
            fh.write(b"other bytes")
        with self.assertRaises(self.Boom) as caught:
            kit_store.read_blob(self.dir, OUTPUT_SHA, error=self.Boom)
        self.assertIn("store corruption", str(caught.exception))

    def test_read_refuses_an_oversize_blob_without_reading_it_whole(self):
        kit_store.publish_blob(self.dir, OUTPUT)
        with self.assertRaises(self.Boom) as caught:
            kit_store.read_blob(self.dir, OUTPUT_SHA, error=self.Boom, max_bytes=len(OUTPUT) - 1)
        self.assertIn("exceeds", str(caught.exception))
        self.assertEqual(kit_store.read_blob(self.dir, OUTPUT_SHA, error=self.Boom,
                                             max_bytes=len(OUTPUT)), OUTPUT)

    def test_an_absent_blob_is_the_callers_to_classify(self):
        with self.assertRaises(FileNotFoundError):
            kit_store.read_blob(self.dir, OUTPUT_SHA, error=self.Boom)

    def test_evidence_is_the_bytes_or_nothing(self):
        with open(os.path.join(self.dir, "attempt-1.evidence.json"), "wb") as fh:
            fh.write(b"0123456789")
        self.assertEqual(kit_store.read_run_evidence(self.dir, "attempt-1"), b"0123456789")
        self.assertIsNone(kit_store.read_run_evidence(self.dir, "attempt-1", max_bytes=9))
        for attempt in ("attempt-2", "", None, 7, "../attempt-1", "attempt-1/..", "a b"):
            with self.subTest(attempt=attempt):
                self.assertIsNone(kit_store.read_run_evidence(self.dir, attempt))

    def test_the_ladder_store_and_the_live_signer_store_are_this_store(self):
        store = rls.Store(self.dir)
        handle = store.publish(OUTPUT)
        self.assertEqual(store.read(handle), OUTPUT)
        with self.assertRaises(rls.LadderError):
            store.read("not-a-handle")
        signer_store = run_signer.FileArtifactStore(self.dir)
        self.assertEqual(signer_store.read_verified(handle), OUTPUT)
        self.assertIsNone(signer_store.read_verified("0" * 64), "absent is None for the signer")
        self.assertIsNone(signer_store.read_verified("not-a-handle"))

    def test_the_live_signer_no_longer_reads_a_blob_of_any_size(self):
        """The drift between the two copies: the ladder capped a blob, the live signer read
        whatever was on disk into memory before hashing it."""
        handle = kit_store.publish_blob(self.dir, OUTPUT)
        with mock.patch.object(kit_store, "MAX_BLOB_BYTES", len(OUTPUT) - 1), \
                mock.patch.object(kit_store.read_blob, "__kwdefaults__",
                                  {"max_bytes": len(OUTPUT) - 1}):
            with self.assertRaises(run_signer.SignerError) as caught:
                run_signer.FileArtifactStore(self.dir).read_verified(handle)
        self.assertIn("exceeds", str(caught.exception))


class TheRecorderTimeoutCannotHangOrLeakTests(unittest.TestCase):
    """The recorder is spawned through `sudo`, which runs as root: the supervisor uid may not
    signal it. The timeout path called `child.kill()` unguarded and then waited with no bound."""

    PINS = {"system": "a" * 64, "history": "b" * 64, "generation_config": "c" * 64}

    def executor(self, hops):
        return rls.RecorderExecutor(
            execution_config={"report_dir": "/nonexistent/report",
                              "evidence_state_dir": "/nonexistent/state",
                              "recorder_store_dir": "/nonexistent/store",
                              "launcher_path": "/l", "executor_path": "/e", "lease_file": "/x",
                              "cgroup_arg": "cg"},
            recorder_command=["/usr/bin/sudo", "-n", "-u", "brops-recorder", "/bin/recorder"],
            clock_ms=lambda: NOW_MS, staged_pins=self.PINS,
            hop_log=lambda protocol, peer, detail: hops.append((protocol, detail)))

    def request(self):
        return rls.gac.ExecutionRequest(
            execution_attempt_id=ATTEMPT_ID, run_id="run-1", task_id="task-1",
            workspace_id="ws-1", install_id="install-1", lease_id="lease-1",
            lease_issued_at_ms=NOW_MS, lease_expires_at_ms=NOW_MS + 210_000,
            system_handle=self.PINS["system"], history_handle=self.PINS["history"],
            generation_config_handle=self.PINS["generation_config"],
            launcher_executable_sha256="1" * 64, executor_executable_sha256="2" * 64)

    def run_with(self, child):
        hops = []
        with mock.patch.object(rls.subprocess, "Popen", lambda *a, **k: child):
            with self.assertRaises(rls.LadderError) as caught:
                self.executor(hops).run(self.request(), lambda started: None)
        return str(caught.exception), hops

    def test_a_child_this_uid_may_not_signal_is_a_ladder_error_that_says_so(self):
        timeout = rls.subprocess.TimeoutExpired("sudo", 1)

        class Unkillable:
            pid = 4242
            waits = []

            def communicate(self, timeout=None):
                Unkillable.waits.append(timeout)
                raise rls.subprocess.TimeoutExpired("sudo", timeout)

            def kill(self):
                raise PermissionError(1, "Operation not permitted")

        message, hops = self.run_with(Unkillable())
        self.assertIn("could NOT be terminated", message)
        self.assertIn("4242", message)
        self.assertEqual(Unkillable.waits, [rls.EXECUTION_WAIT_S],
                         "a process that could not be killed must not be waited on again")
        self.assertIn("execution.unstoppable", [protocol for protocol, _ in hops])
        del timeout

    def test_a_kill_that_lands_but_is_not_reaped_does_not_wait_forever(self):
        class Lingering:
            pid = 4243
            waits = []

            def communicate(self, timeout=None):
                Lingering.waits.append(timeout)
                raise rls.subprocess.TimeoutExpired("sudo", timeout)

            def kill(self):
                return None

        message, _hops = self.run_with(Lingering())
        self.assertIn("may still be running", message)
        self.assertEqual(Lingering.waits, [rls.EXECUTION_WAIT_S, rls.KILL_REAP_S])
        self.assertNotIn(None, Lingering.waits, "every wait on this child must be bounded")

    def test_a_child_that_is_killed_and_reaped_is_the_plain_timeout(self):
        class Killable:
            pid = 4244
            calls = 0

            def communicate(self, timeout=None):
                Killable.calls += 1
                if Killable.calls == 1:
                    raise rls.subprocess.TimeoutExpired("sudo", timeout)
                return b"", None

            def kill(self):
                return None

        message, hops = self.run_with(Killable())
        self.assertNotIn("could NOT", message)
        self.assertIn("exceeded", message)
        self.assertNotIn("execution.unstoppable", [protocol for protocol, _ in hops])


class TheLadderServiceGraphIsBuildableTests(unittest.TestCase):
    """`build_ladder_services` advertises a seam -- "the same construction driven directly, no
    AF_UNIX, no root" -- that nothing called. This calls it, with the execution and the signer
    injected, and puts one frame through a service it built."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        for sub in ("store", "staging", "keys", "state"):
            os.mkdir(os.path.join(root, sub))
        attest, challenge = lc.gen_private(), lc.gen_private()
        with open(os.path.join(root, "keys", "attest.priv"), "wb") as fh:
            fh.write(lc.priv_raw(attest))
        with open(os.path.join(root, "keys", "challenge.pub.hex"), "w", encoding="ascii") as fh:
            fh.write(lc.pub_hex(challenge))
        self.cfg = {
            "store_dir": os.path.join(root, "store"),
            "trust": {"supervisor_attestation_key_id": SUP_ATTEST_KEY_ID},
            "keys": {"supervisor_attest_priv": os.path.join(root, "keys", "attest.priv"),
                     "challenge_pub_hex": os.path.join(root, "keys", "challenge.pub.hex")},
            "execution": {"evidence_state_dir": os.path.join(root, "state")},
            "supervisor": {
                "launcher_executable_sha256": "1" * 64, "executor_executable_sha256": "2" * 64,
                "supervisor_id": "sup-1", "executor_id": "exec-1", "builder_id": "builder-1",
                "policy_id": "policy-1", "policy_version": "v1",
                "policy_bundle_handle": "3" * 64, "challenge_registry_handle": "4" * 64,
                "challenge_registry_hash": "5" * 64, "challenge_registry_epoch": 1,
                "challenge_registry_root_key_id": ROOT_KEY_ID,
                "ledger_db": os.path.join(root, "state", "supervisor-ledger.db"),
            },
        }
        self.ladder = {
            "registry": {"document_path": os.path.join(root, "registry.json"),
                         "root_public_key_b64url": b64u(lc.pub_raw(lc.gen_private())),
                         "epoch_floor": 0},
            "execution_allowlist": ["6" * 64],
            "staging_root": os.path.join(root, "staging"),
            "signer_socket": os.path.join(root, "signer.sock"),
            "recorder_command": ["sudo", "-n", "-u", "brops-recorder", "/bin/true"],
        }
        self.hops = []

    def build(self, **overrides):
        kwargs = dict(allowed_sidecar_uid=SIDECAR_UID, execution=rls.gac.RefusingExecutor(),
                      sign_result=lambda request: {"refused": True},
                      clock_ms=lambda: NOW_MS,
                      hop=lambda protocol, peer_uid, detail: self.hops.append(
                          (protocol, peer_uid)))
        kwargs.update(overrides)
        services = rls.build_ladder_services(self.cfg, self.ladder, **kwargs)
        self.addCleanup(services.ledger_conn.close)
        return services

    def test_the_graph_builds_with_injected_execution_and_signer(self):
        services = self.build()
        self.assertIsInstance(services.driver, rls.gac.AcceptanceDriver)
        self.assertEqual(services.supervisor_attestation_key_id, SUP_ATTEST_KEY_ID)
        self.assertEqual(services.store.read(services.publish_artifact(OUTPUT)), OUTPUT)
        self.assertIsNone(services.read_run_evidence("no-such-attempt"))

    def test_a_frame_put_through_a_built_service_is_answered_and_its_hop_recorded(self):
        services = self.build()
        reply = services.open_service.handle(
            {"protocol": rls.gto.OPEN_PROTOCOL}, peer_uid=SIDECAR_UID,
            conn=services.ledger_conn, clock_ms=services.clock_ms)
        self.assertEqual(reply.get("status"), "refused", reply)
        self.assertEqual(self.hops, [(rls.gto.OPEN_PROTOCOL, SIDECAR_UID)])
        # ...and to the wrong principal it is denied by name, which is the wiring that matters.
        denied = services.open_service.handle(
            {"protocol": rls.gto.OPEN_PROTOCOL}, peer_uid=BROKER_UID,
            conn=services.ledger_conn, clock_ms=services.clock_ms)
        self.assertEqual(denied.get("reason"), "peer_denied", denied)

    def test_a_deployment_that_could_never_execute_refuses_to_build(self):
        self.ladder["execution_allowlist"] = []
        with self.assertRaises(rls.LadderError) as caught:
            self.build()
        self.assertIn("allowlist is empty", str(caught.exception))

    def test_an_unprovisioned_staging_root_refuses_to_build(self):
        self.ladder["staging_root"] = os.path.join(self.tmp.name, "absent")
        with self.assertRaises(rls.LadderError) as caught:
            self.build()
        self.assertIn("staging root is not provisioned", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
