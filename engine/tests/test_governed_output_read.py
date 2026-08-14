"""Offline tests for the §4.10(f) supervisor hop — ``brops.governed-turn-output-read.v1``.

No socket, no key material, no network, no real clock: an in-memory SQLite carrying the
CANONICAL ``supervisor_ledger.sql``, an in-memory store stand-in, and injected clocks.

What this file is organized around:

  * **Every one of the five closed refusal reasons is produced BY NAME from a frame a
    hostile peer could actually send**, through the real front door (`dispatch` /
    `handle_connection`) and not only through the handler. ``ClosedSetReachabilityTests``
    is the roll call, and it fails if a reason becomes unproducible.
  * **The verdict ORDER is observable and is tested as such.** §4.10(f) locks
    absent → expired → binding → range, so an expired stream presented with the WRONG
    receipt answers ``stream_expired``. Reordering those two lines changes what a caller
    learns, and one test exists purely to notice that.
  * **The arithmetic is in a test, not in a comment.** The literal maximum reply is
    constructed and its byte count asserted (245940 against a 262144 cap), the largest legal
    request is constructed and asserted (421 bytes), and the §2.4 regression is restated for
    the egress direction: a 262144-byte chunk would encode to 349528 and could not fit.
  * **The write-bound defect §4.10(f) exposed has a test that would have caught it.** The
    supervisor front door wrote every reply at the broker's 8192-byte bound while the
    sidecar's READ bound was 262144. Every sidecar reply before this one was a few hundred
    bytes, so nothing in the suite could tell. ``FrameBoundTests`` drives a maximum-size
    chunk reply all the way through ``handle_connection`` and asserts it arrives as a
    §4.10(f) frame rather than as ``reply exceeded frame bound``.
  * **Two paths raise instead of refusing, and they are MARKED.** A store that cannot return
    a live stream's artifact, and an artifact whose length disagrees with the row, are
    reachable only from a faulty store or tampered durable state — never from a frame. They
    are proved by forcing exactly those states rather than left as prose.
  * ``NothingGovernedIsMintedTests`` records what this piece does NOT decide.

No prerequisite here is optional. Everything is stdlib plus repo modules, imported at module
scope with no ``try``/``except`` and no ``skipIf``, so a missing prerequisite is an
unmissable hard error rather than a green run with a quiet skip. (There is no
``BROPS_TEST_MISSING_PREREQUISITES`` declaration anywhere in this tree, so nothing is
declared in it and nothing here may be softened.)
"""

import base64
import hashlib
import json
import pathlib
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import brops_protocol as bp  # noqa: E402
import governed_output_read as gor  # noqa: E402
import governed_output_stream as gos  # noqa: E402
import governed_supervisor_ledger as gsl  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
from governed_supervisor import SupervisorError  # noqa: E402

BROKER_UID = 4001
SIDECAR_UID = 4004
NOW = 1_700_000_000_000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class Store(dict):
    """The content-addressed store, reduced to the one operation §4.10(f) needs.

    ``read`` re-derives the digest and refuses a mismatch, which is exactly what the real
    ``brops_evidence_store.EvidenceStore.read`` does — the property the handler relies on
    when it says it never serves a byte it has not just re-hashed.
    """

    def publish(self, data: bytes) -> str:
        handle = hashlib.sha256(data).hexdigest()
        self[handle] = data
        return handle

    def read(self, handle: str) -> bytes:
        if handle not in self:
            raise KeyError("evidence handle not in store: %s" % handle)
        data = self[handle]
        if hashlib.sha256(data).hexdigest() != handle:
            raise ValueError("store corruption at %s" % handle)
        return data


def ledger() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    gsl.apply_schema(conn)
    return conn


def accept(conn, attempt, *, install_id="inst-1", nonce, receipt_id, handle,
           now_ms=NOW) -> None:
    gsl.accept_prepare(conn, gsl.NewAcceptance(
        install_id=install_id, request_nonce=nonce, challenge_handle=handle,
        run_id="run-1", task_id="task-1", workspace_id="ws-1",
        execution_attempt_id=attempt, challenge_accepted_at_ms=now_ms,
        challenge_registry_handle="d" * 64, challenge_registry_hash="e" * 64,
        challenge_registry_epoch=7, challenge_registry_root_key_id="root-1",
        lease_payload_bytes=b"{}", lease_id="lease-1",
        lease_issued_at_ms=now_ms, lease_expires_at_ms=now_ms + 210_000,
        receipt_id=receipt_id, supervisor_id="sup-1", requested_at_ms=now_ms - 10,
        request_sha256="f" * 64, system_handle="1" * 64, history_handle="2" * 64,
        generation_config_handle="3" * 64,
    ), now_ms)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


#: A sentinel, because ``None`` is one of the malformed FRAMES this file has to send and
#: cannot double as "use the default request".
_DEFAULT = object()


class Fixture:
    """One accepted, completed turn with a real stream row over real bytes."""

    def __init__(self, output: bytes = b"hello governed world", *, attempt="attempt-1",
                 receipt_id="rcpt-1", install_id="inst-1", now_ms=NOW):
        self.conn = ledger()
        self.store = Store()
        self.handle = self.store.publish(output)
        self.output = output
        self.attempt = attempt
        self.receipt_id = receipt_id
        accept(self.conn, attempt, install_id=install_id, nonce="nonce-1",
               receipt_id=receipt_id, handle="c" * 64, now_ms=now_ms)
        _outcome, self.row = gos.mint_stream(self.conn, gos.NewStream(
            install_id=install_id, receipt_id=receipt_id, execution_attempt_id=attempt,
            output_handle=self.handle, output_bytes=len(output)), now_ms)
        self.token = self.row["output_stream_id"]
        self.service = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                             read_output=self.store.read)

    def request(self, seq=0, **overrides):
        req = {
            "protocol": gor.OUTPUT_READ_PROTOCOL,
            "output_stream_id": self.token,
            "receipt_id": self.receipt_id,
            "execution_attempt_id": self.attempt,
            "seq": seq,
        }
        req.update(overrides)
        return req

    def call(self, request=_DEFAULT, *, peer_uid=SIDECAR_UID, now_ms=NOW):
        """The HANDLER, not the service.

        ``OutputReadService.handle`` routes on the ``protocol`` const and raises for anything
        else, so shape cases that violate the const would never reach the handler through it.
        The front door already routes the same way, so the const check that matters lives at
        the layer that owns the shape and is exercised here; the service's own routing has its
        own test."""
        return gor.handle_output_read(
            self.request() if request is _DEFAULT else request,
            peer_uid=peer_uid, allowed_sidecar_uid=SIDECAR_UID, conn=self.conn,
            now_ms=now_ms, read_output=self.store.read)

    def reason(self, request=_DEFAULT, **kw):
        reply = self.call(request, **kw)
        self.assertish(reply)
        return reply["error"]["reason"]

    @staticmethod
    def assertish(reply):
        assert reply["ok"] is False, reply


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------


class ServeTests(unittest.TestCase):
    def test_a_small_output_is_one_chunk_and_eof(self):
        f = Fixture(b"hello")
        reply = f.call()
        self.assertEqual(reply["protocol"], gor.OUTPUT_READ_RESULT_PROTOCOL)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["output_stream_id"], f.token)
        self.assertEqual(reply["seq"], 0)
        self.assertEqual(base64.urlsafe_b64decode(reply["bytes_b64"] + "==="), b"hello")
        self.assertTrue(reply["eof"])
        self.assertIsNone(reply["error"])

    def test_the_reply_carries_exactly_the_design_field_set_on_both_arms(self):
        f = Fixture()
        self.assertEqual(set(f.call()), set(gor.OUTPUT_READ_REPLY_FIELDS))
        self.assertEqual(set(f.call(f.request(seq=99))), set(gor.OUTPUT_READ_REPLY_FIELDS))

    def test_a_multi_chunk_output_reassembles_to_exactly_the_stored_bytes(self):
        payload = bytes(range(256)) * 2000  # 512000 bytes -> 3 chunks
        f = Fixture(payload)
        self.assertEqual(gor.n_chunks(len(payload)), 3)
        got = b""
        for seq in range(3):
            reply = f.call(f.request(seq=seq))
            self.assertTrue(reply["ok"])
            self.assertEqual(reply["eof"], seq == 2)
            got += base64.urlsafe_b64decode(reply["bytes_b64"] + "===")
        self.assertEqual(got, payload)
        self.assertEqual(hashlib.sha256(got).hexdigest(), f.handle)

    def test_a_re_read_of_the_same_seq_returns_byte_identical_bytes(self):
        """§4.10(f): "Reads are **idempotent**: the same ``seq`` always returns the exact same
        byte range … a lost reply is safely retried (no ``next_seq`` consume)." Unlike the
        §4.10(b) ingress there is no cursor at all, which is what makes that true."""
        f = Fixture(bytes(range(256)) * 2000)
        first = f.call(f.request(seq=1))
        for _ in range(4):
            self.assertEqual(f.call(f.request(seq=1)), first)

    def test_the_chunk_boundary_is_exact_at_184320(self):
        f = Fixture(b"z" * gor.OUTPUT_CHUNK_BYTES)
        self.assertEqual(gor.n_chunks(gor.OUTPUT_CHUNK_BYTES), 1)
        reply = f.call()
        self.assertTrue(reply["eof"])
        self.assertEqual(len(reply["bytes_b64"]), gor.MAX_OUTPUT_CHUNK_B64_LEN)
        self.assertEqual(f.reason(f.request(seq=1)), gor.REFUSE_SEQ_OUT_OF_RANGE)

    def test_one_byte_past_the_boundary_becomes_two_chunks(self):
        f = Fixture(b"z" * (gor.OUTPUT_CHUNK_BYTES + 1))
        self.assertFalse(f.call(f.request(seq=0))["eof"])
        tail = f.call(f.request(seq=1))
        self.assertTrue(tail["eof"])
        self.assertEqual(base64.urlsafe_b64decode(tail["bytes_b64"] + "==="), b"z")
        self.assertEqual(f.reason(f.request(seq=2)), gor.REFUSE_SEQ_OUT_OF_RANGE)

    def test_a_zero_byte_output_has_exactly_one_legal_read(self):
        """§4.10(f) zero-byte contract, LOCKED: ``seq == 0`` returns ``ok:true,
        bytes_b64:"", eof:true``; any ``seq > 0`` is ``seq_out_of_range``."""
        f = Fixture(b"")
        reply = f.call()
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["bytes_b64"], "")
        self.assertTrue(reply["eof"])
        self.assertEqual(f.reason(f.request(seq=1)), gor.REFUSE_SEQ_OUT_OF_RANGE)
        # …and the desktop's own assertion holds over the empty reassembly.
        self.assertEqual(hashlib.sha256(b"").hexdigest(), f.handle)

    def test_the_maximum_output_is_46_chunks_ending_at_94208_bytes(self):
        """§4.10(f)'s worked example: ``ceil(8388608 / 184320) = 46``, ``seq`` 0..45, last
        chunk 94208 bytes. Asserted arithmetically rather than by materializing 8 MiB."""
        self.assertEqual(gor.MAX_OUTPUT_CHUNKS, 46)
        self.assertEqual(gor.last_seq(8_388_608), 45)
        start, end = gor.chunk_range(45)
        self.assertEqual(start, 45 * 184_320)
        self.assertEqual(min(end, 8_388_608) - start, 94_208)


# ---------------------------------------------------------------------------
# The verdict ladder
# ---------------------------------------------------------------------------


class VerdictOrderTests(unittest.TestCase):
    def test_an_absent_token_is_stream_unknown(self):
        f = Fixture()
        self.assertEqual(f.reason(f.request(output_stream_id="Q" * 43)),
                         gor.REFUSE_STREAM_UNKNOWN)

    def test_a_swept_stream_is_stream_unknown_not_stream_expired(self):
        f = Fixture()
        gos.sweep_streams(f.conn, f.row["retained_until_ms"] + 1)
        self.assertEqual(f.reason(now_ms=f.row["retained_until_ms"] + 1),
                         gor.REFUSE_STREAM_UNKNOWN)

    def test_the_expiry_boundary_is_inclusive_at_the_instant(self):
        f = Fixture()
        expires = f.row["expires_at_ms"]
        self.assertTrue(f.call(now_ms=expires)["ok"])
        self.assertEqual(f.reason(now_ms=expires + 1), gor.REFUSE_STREAM_EXPIRED)

    def test_a_logically_expired_but_unswept_row_is_expired_not_unknown(self):
        """§4.10(f)'s delayed-sweep test: the verdict is SYNCHRONOUS on the row's own
        timestamps and never depends on whether the async sweep has run."""
        f = Fixture()
        way_past = f.row["retained_until_ms"] + 10_000_000
        self.assertEqual(f.reason(now_ms=way_past), gor.REFUSE_STREAM_EXPIRED)
        gos.sweep_streams(f.conn, way_past)
        self.assertEqual(f.reason(now_ms=way_past), gor.REFUSE_STREAM_UNKNOWN)

    def test_a_valid_token_with_the_wrong_receipt_is_caught_server_side(self):
        """§4.10(f) P1-3: "a *valid* token from a different receipt/attempt is caught
        **server-side** … not merely by the desktop's final digest"."""
        f = Fixture()
        self.assertEqual(f.reason(f.request(receipt_id="rcpt-other")),
                         gor.REFUSE_STREAM_BINDING_MISMATCH)

    def test_a_valid_token_with_the_wrong_attempt_is_caught_server_side(self):
        f = Fixture()
        self.assertEqual(f.reason(f.request(execution_attempt_id="attempt-other")),
                         gor.REFUSE_STREAM_BINDING_MISMATCH)

    def test_another_turns_live_token_cannot_be_redeemed_against_this_turns_ids(self):
        """The cross-turn case, built out of two real streams rather than a mutated id."""
        f = Fixture(b"turn one")
        accept(f.conn, "attempt-2", nonce="nonce-2", receipt_id="rcpt-2", handle="9" * 64)
        other_handle = f.store.publish(b"turn two")
        _o, other = gos.mint_stream(f.conn, gos.NewStream(
            install_id="inst-1", receipt_id="rcpt-2", execution_attempt_id="attempt-2",
            output_handle=other_handle, output_bytes=8), NOW)
        self.assertEqual(
            f.reason(f.request(output_stream_id=other["output_stream_id"])),
            gor.REFUSE_STREAM_BINDING_MISMATCH)

    def test_expiry_is_decided_BEFORE_the_binding_compare(self):
        """The order §4.10(f) locks, and it is observable: an expired token presented with the
        wrong receipt answers ``stream_expired``. Swapping the two lines would tell an
        unauthorized holder that the token it has is otherwise valid."""
        f = Fixture()
        self.assertEqual(
            f.reason(f.request(receipt_id="rcpt-other"), now_ms=f.row["expires_at_ms"] + 1),
            gor.REFUSE_STREAM_EXPIRED)

    def test_binding_is_decided_BEFORE_the_range_check(self):
        """Same reasoning one step later: a caller that cannot prove the binding learns
        nothing about how long the output is."""
        f = Fixture(b"tiny")
        self.assertEqual(
            f.reason(f.request(seq=99, receipt_id="rcpt-other")),
            gor.REFUSE_STREAM_BINDING_MISMATCH)

    def test_seq_out_of_range_is_the_last_verdict(self):
        f = Fixture(b"tiny")
        self.assertEqual(f.reason(f.request(seq=1)), gor.REFUSE_SEQ_OUT_OF_RANGE)
        self.assertEqual(f.reason(f.request(seq=10 ** 20)), gor.REFUSE_SEQ_OUT_OF_RANGE)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class ShapeTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def test_the_request_field_set_is_exhaustive(self):
        self.assertEqual(set(self.f.request()), set(gor.OUTPUT_READ_REQUEST_FIELDS))

    def test_an_unknown_field_is_malformed(self):
        self.assertEqual(self.f.reason(self.f.request(length=99)), gor.REFUSE_MALFORMED)

    def test_a_caller_may_not_choose_the_chunk_size_or_an_offset(self):
        """The stride is fixed by the protocol. A request that could name its own range would
        let the sidecar decide how much of the output one round trip returns."""
        for smuggled in ("offset", "length", "chunk_bytes", "max_bytes", "eof"):
            self.assertEqual(self.f.reason(self.f.request(**{smuggled: 1})),
                             gor.REFUSE_MALFORMED)

    def test_each_missing_field_is_malformed(self):
        for field in gor.OUTPUT_READ_REQUEST_FIELDS:
            req = self.f.request()
            del req[field]
            self.assertEqual(self.f.reason(req), gor.REFUSE_MALFORMED, field)

    def test_the_wrong_protocol_const_is_malformed(self):
        self.assertEqual(
            self.f.reason(self.f.request(protocol="brops.governed-turn-result.v1")),
            gor.REFUSE_MALFORMED)

    def test_a_token_of_the_wrong_length_is_malformed_not_stream_unknown(self):
        """A value that could not be a capability never becomes a question about the table."""
        for bad in ("Q" * 42, "Q" * 44, "Q"):
            self.assertEqual(self.f.reason(self.f.request(output_stream_id=bad)),
                             gor.REFUSE_MALFORMED, bad)

    def test_a_non_string_id_is_malformed(self):
        for field in ("output_stream_id", "receipt_id", "execution_attempt_id"):
            self.assertEqual(self.f.reason(self.f.request(**{field: 7})),
                             gor.REFUSE_MALFORMED, field)
            self.assertEqual(self.f.reason(self.f.request(**{field: ""})),
                             gor.REFUSE_MALFORMED, field)

    def test_an_over_long_identity_is_malformed(self):
        self.assertEqual(self.f.reason(self.f.request(receipt_id="r" * 129)),
                         gor.REFUSE_MALFORMED)

    def test_a_non_integer_seq_is_malformed(self):
        for bad in ("0", 0.0, None, True, [0]):
            self.assertEqual(self.f.reason(self.f.request(seq=bad)),
                             gor.REFUSE_MALFORMED, repr(bad))

    def test_a_negative_seq_is_malformed_not_out_of_range(self):
        """§4.10(f) types the field ``<int ≥0>``. ``seq_out_of_range`` is reserved for a value
        that could have been a seq for some stream and is not one for this one."""
        self.assertEqual(self.f.reason(self.f.request(seq=-1)), gor.REFUSE_MALFORMED)

    def test_a_frame_that_is_not_an_object_is_malformed(self):
        for bad in ([], "x", 7, None):
            self.assertEqual(self.f.reason(bad), gor.REFUSE_MALFORMED, repr(bad))

    def test_a_malformed_request_echoes_nothing(self):
        """§4.10(f) makes the two echoes ``<same or null>``. A frame that failed the shape
        check named nothing usable, so it gets nulls rather than a partially-parsed echo."""
        reply = self.f.call(self.f.request(length=1))
        self.assertIsNone(reply["output_stream_id"])
        self.assertIsNone(reply["seq"])

    def test_a_refusal_never_discloses_the_rows_real_binding(self):
        reply = self.f.call(self.f.request(receipt_id="rcpt-other"))
        self.assertEqual(reply["output_stream_id"], self.f.token)
        self.assertEqual(json.dumps(reply).count("rcpt-1"), 0)

    def test_a_denied_peer_gets_the_least_informative_published_literal(self):
        """§4.10(f)'s closed set has no ``peer_denied`` — the §4.10(b)/(c) situation exactly —
        so a stranger learns that its frame was not accepted and nothing about the stream."""
        self.assertEqual(self.f.reason(peer_uid=BROKER_UID), gor.REFUSE_MALFORMED)
        self.assertEqual(self.f.reason(peer_uid=None), gor.REFUSE_MALFORMED)

    def test_a_denied_peer_never_reaches_the_database(self):
        f = Fixture()

        class Poisoned:
            def execute(self, *a, **k):
                raise AssertionError("a denied peer reached a query")

        reply = f.service.handle(f.request(), peer_uid=BROKER_UID, conn=Poisoned(),
                                 clock_ms=lambda: NOW)
        self.assertEqual(reply["error"]["reason"], gor.REFUSE_MALFORMED)

    def test_a_reason_outside_the_closed_set_cannot_be_built(self):
        with self.assertRaises(SupervisorError):
            gor.output_read_refused("peer_denied")
        with self.assertRaises(SupervisorError):
            gor.output_read_refused("oversize")


# ---------------------------------------------------------------------------
# Faults that are NOT peer-reachable, and are marked as such
# ---------------------------------------------------------------------------


class StoreFaultTests(unittest.TestCase):
    """MARKED: neither of these is reachable from a frame a hostile peer can send.

    The handle comes off the row, the row was written by the supervisor from the recorder's
    own evidence chain, and the row is INSERT-ONCE — so both states require a faulty store or
    tampered durable state. They raise rather than refusing because §4.10(f) publishes no
    literal for either, and a verdict outside a closed set is the thing ``_checked`` exists to
    stop.
    """

    def test_a_missing_artifact_for_a_live_stream_is_a_fault(self):
        f = Fixture()
        del f.store[f.handle]
        with self.assertRaises(SupervisorError) as caught:
            f.call()
        self.assertIn("unreadable", str(caught.exception))

    def test_an_artifact_whose_length_disagrees_with_the_row_is_a_fault(self):
        """MARKED TWICE. With the REAL ``EvidenceStore.read`` this branch is unreachable —
        the store refuses a digest mismatch first, so the reply here would be the "unreadable"
        fault above. It is reached only through a ``read_output`` seam that does NOT verify,
        which is a legitimate future implementation (a ranged reader that hashes once per
        turn rather than once per chunk), and it is kept for exactly that seam: without it a
        non-verifying reader would serve a wrong-length range and the failure would surface
        two hops away as the desktop's whole-output digest mismatch."""
        f = Fixture(b"hello")
        unverified = gor.OutputReadService(
            allowed_sidecar_uid=SIDECAR_UID, read_output=lambda h: b"hello but longer")
        with self.assertRaises(SupervisorError) as caught:
            unverified.handle(f.request(), peer_uid=SIDECAR_UID, conn=f.conn,
                              clock_ms=lambda: NOW)
        self.assertIn("stream row records", str(caught.exception))
        # …and with the real digest-checking store the SAME tampering is caught one step
        # earlier, by the store, which is why this is a second wall and not the first.
        f.store[f.handle] = b"hello but longer"
        with self.assertRaises(SupervisorError) as caught:
            f.call()
        self.assertIn("unreadable", str(caught.exception))

    def test_a_read_seam_that_is_not_callable_is_refused_at_construction(self):
        with self.assertRaises(SupervisorError):
            gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID, read_output="nope")
        with self.assertRaises(SupervisorError):
            gor.OutputReadService(allowed_sidecar_uid="4004", read_output=lambda h: b"")

    def test_a_seam_returning_a_non_bytes_is_a_fault(self):
        f = Fixture()
        svc = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                    read_output=lambda h: "not bytes")
        with self.assertRaises(SupervisorError):
            svc.handle(f.request(), peer_uid=SIDECAR_UID, conn=f.conn,
                       clock_ms=lambda: NOW)


# ---------------------------------------------------------------------------
# Frame arithmetic — done first, and in a test
# ---------------------------------------------------------------------------


class FrameFitTests(unittest.TestCase):
    def test_the_chunk_encodes_to_exactly_245760_characters(self):
        self.assertEqual(gor.OUTPUT_CHUNK_BYTES, 184_320)
        self.assertEqual(gor.OUTPUT_CHUNK_BYTES % 3, 0)  # so the encoding has no padding
        self.assertEqual(gor.MAX_OUTPUT_CHUNK_B64_LEN, 245_760)
        self.assertEqual(len(b64(b"\xff" * gor.OUTPUT_CHUNK_BYTES)),
                         gor.MAX_OUTPUT_CHUNK_B64_LEN)

    def _max_reply(self):
        """The literal maximum: a FULL chunk, a two-digit ``seq``, and ``eof:false`` — the
        longer of the two boolean spellings, which is why the maximum is not the last chunk."""
        return gor.output_read_ok("Q" * 43, 44, b"\xff" * gor.OUTPUT_CHUNK_BYTES, eof=False)

    def test_the_literal_maximum_reply_frame_fits(self):
        body = json.dumps(self._max_reply(), separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(body), 245_940)
        self.assertLessEqual(len(body), bp.MAX_FRAME_BYTES)
        self.assertEqual(bp.MAX_FRAME_BYTES - len(body), 16_204)

    def test_the_maximum_reply_survives_the_real_transport_encoder(self):
        self.assertEqual(len(bp.encode_frame(self._max_reply())), 245_940 + 4)

    def test_a_256_KiB_chunk_could_not_have_fitted(self):
        """The §2.4 regression, restated for the egress direction: a 262144-byte decoded chunk
        encodes to ``4·⌈262144/3⌉ = 349528`` and overflows before the envelope is even added.
        This is why the chunk stride is a constant of the protocol and not a caller's choice."""
        self.assertEqual(4 * ((262_144 + 2) // 3), 349_528)
        self.assertGreater(349_528, bp.MAX_FRAME_BYTES)

    def test_the_only_size_check_that_can_fire_is_on_the_chunk(self):
        """A frame check on a legal reply could never fire (245940 < 262144), so none exists.
        The bound that DOES hold the arithmetic up is the chunk stride, and it is checked."""
        with self.assertRaises(SupervisorError) as caught:
            gor.output_read_ok("Q" * 43, 0, b"\x00" * (gor.OUTPUT_CHUNK_BYTES + 1), eof=True)
        self.assertIn("frame arithmetic depends on this bound", str(caught.exception))
        gor.output_read_ok("Q" * 43, 0, b"\x00" * gor.OUTPUT_CHUNK_BYTES, eof=True)

    def test_the_largest_legal_request_is_421_bytes(self):
        """And therefore no request-side frame cap exists: §4.10(f) declares the request frame
        at ``MAX_FRAME_BYTES``, which IS the transport read bound, so a cap-table entry could
        never be consulted. The shape check refuses everything a bigger frame could carry."""
        biggest = {
            "protocol": gor.OUTPUT_READ_PROTOCOL,
            "output_stream_id": "Q" * 43,
            "receipt_id": "r" * 128,
            "execution_attempt_id": "a" * 128,
            "seq": 45,
        }
        body = json.dumps(biggest, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(body), 421)
        self.assertEqual(gor.MAX_OUTPUT_READ_FRAME_BYTES, bp.MAX_FRAME_BYTES)
        self.assertEqual(gss.MAX_SIDECAR_FRAME_BYTES, gor.MAX_OUTPUT_READ_FRAME_BYTES)
        self.assertIsNone(gss.frame_cap_refusal(gor.OUTPUT_READ_PROTOCOL,
                                                bp.MAX_FRAME_BYTES))


# ---------------------------------------------------------------------------
# The front door, including the write bound §4.10(f) exposed
# ---------------------------------------------------------------------------


class FakeConn:
    def __init__(self, peer_uid, inbound: bytes = b""):
        self.peer_uid = peer_uid
        self._in = inbound
        self.out = b""

    def recv_exactly(self, n: int) -> bytes:
        chunk = self._in[:n]
        self._in = self._in[n:]
        return chunk

    def send_all(self, data: bytes) -> None:
        self.out += data

    def close(self) -> None:
        pass

    def decoded_reply(self):
        length = int.from_bytes(self.out[:4], "big")
        return json.loads(self.out[4:4 + length].decode("utf-8"))


def framed(obj) -> bytes:
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return len(body).to_bytes(4, "big") + body


def front_door(f, request, *, peer_uid=SIDECAR_UID, service=True, now_ms=NOW):
    conn = FakeConn(peer_uid, framed(request))
    reply = gss.handle_connection(
        conn, BROKER_UID, _config(), lambda m, s: True, lambda p: "0" * 64,
        lambda: now_ms, ledger_conn=f.conn,
        output_read_service=f.service if service else None,
    )
    return conn, reply


def _config():
    from governed_supervisor import SupervisorConfig
    return SupervisorConfig(
        launcher_executable_sha256="0" * 64, executor_executable_sha256="1" * 64,
        id_fn=lambda: "id", supervisor_id="sup-1", executor_id="exec-1",
        builder_id="build-1", policy_id="pol-1", policy_version="1",
        policy_bundle_handle="2" * 64, challenge_registry_handle="d" * 64,
        challenge_registry_hash="e" * 64, challenge_registry_epoch=7,
        challenge_registry_root_key_id="root-1",
    )


class FrameBoundTests(unittest.TestCase):
    """The defect §4.10(f) surfaced, with the test that would have caught it.

    Until §4.10(f) every sidecar reply was a few hundred bytes, so nothing in the suite could
    tell that the front door's WRITE bound had stayed at the broker's 8192 while its READ
    bound was widened to 262144 for the sidecar. A maximum-size chunk reply is 245940 bytes:
    under the old writer it degraded to a minimal error frame that is not a §4.10(f) frame at
    all, and the pull could never have completed.
    """

    def test_a_maximum_size_chunk_reply_reaches_the_peer_intact(self):
        payload = b"\xa5" * (gor.OUTPUT_CHUNK_BYTES * 2)
        f = Fixture(payload)
        conn, reply = front_door(f, f.request(seq=0))
        self.assertTrue(reply["ok"])
        self.assertFalse(reply["eof"])
        wire = conn.decoded_reply()
        self.assertEqual(wire["protocol"], gor.OUTPUT_READ_RESULT_PROTOCOL)
        self.assertEqual(len(wire["bytes_b64"]), gor.MAX_OUTPUT_CHUNK_B64_LEN)
        self.assertEqual(base64.urlsafe_b64decode(wire["bytes_b64"] + "==="),
                         payload[:gor.OUTPUT_CHUNK_BYTES])
        self.assertGreater(len(conn.out), 8192)

    def test_the_broker_write_bound_is_unchanged(self):
        """Widening the sidecar's writer must not widen the broker's. An `op` frame reply is
        still framed at 8192, so nothing about the §5 surface moved."""
        self.assertEqual(gss.MAX_FRAME_BYTES, 8192)
        conn = FakeConn(BROKER_UID, framed({"op": "launch-gate", "extra": "x" * 20}))
        gss.handle_connection(conn, BROKER_UID, _config(), lambda m, s: True,
                              lambda p: "0" * 64, lambda: NOW, ledger_conn=ledger())
        self.assertLessEqual(len(conn.out), 8192 + 4)

    def test_an_over_bound_reply_still_degrades_rather_than_killing_the_process(self):
        """The belt behind the braces (audit F-11): a reply that will not frame must not
        escape ``handle_connection``. Driven directly, since no legal reply can trip it."""
        conn = FakeConn(SIDECAR_UID)
        gss._try_write(conn, {"ok": True, "x": "y" * 300_000}, gss.MAX_SIDECAR_FRAME_BYTES)
        self.assertEqual(conn.decoded_reply(),
                         {"ok": False, "error": "reply exceeded frame bound"})


class FrontDoorTests(unittest.TestCase):
    def test_the_sidecar_may_send_this_protocol_and_the_broker_gets_nothing_from_it(self):
        """The sidecar's grant widens by exactly one name. The broker is not refused at the
        transport — an `op`-speaking principal may reach `dispatch` — but the handler's own
        peer check answers it with the least informative published literal, so the §4.10(f)
        surface is sidecar-only in effect as well as in the allowlist."""
        f = Fixture()
        self.assertIn(gor.OUTPUT_READ_PROTOCOL, gss.SIDECAR_PROTOCOLS)
        self.assertEqual(len(gss.SIDECAR_PROTOCOLS), 6)
        _conn, reply = front_door(f, f.request())
        self.assertTrue(reply["ok"])
        _conn, denied = front_door(f, f.request(), peer_uid=BROKER_UID)
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"]["reason"], gor.REFUSE_MALFORMED)
        self.assertIsNone(denied["bytes_b64"])

    def test_a_sidecar_frame_of_an_unlisted_protocol_never_reaches_dispatch(self):
        f = Fixture()
        conn = FakeConn(SIDECAR_UID, framed({"protocol": "brops.not-a-governed-protocol.v1"}))
        reply = gss.handle_connection(
            conn, BROKER_UID, _config(), lambda m, s: True, lambda p: "0" * 64,
            lambda: NOW, ledger_conn=f.conn, output_read_service=f.service)
        self.assertEqual(reply, {"ok": False, "error": "peer not authorized"})

    def test_an_unconfigured_supervisor_serves_no_read_at_all(self):
        """The fail-closed switch, matching §4.10(a0)/(a)(b)(c)/(d): a supervisor that has not
        been told who the sidecar is, or how to reach the store, answers nobody."""
        f = Fixture()
        reply = gss.dispatch(f.request(), _config(), lambda m, s: True,
                             lambda p: "0" * 64, lambda: NOW, conn=f.conn,
                             output_read_service=None, peer_uid=SIDECAR_UID)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["reason"], gor.REFUSE_MALFORMED)

    def test_the_service_refuses_a_frame_of_another_protocol(self):
        f = Fixture()
        with self.assertRaises(SupervisorError):
            f.service.handle({"protocol": "brops.governed-turn-open.v1"},
                             peer_uid=SIDECAR_UID, conn=f.conn, clock_ms=lambda: NOW)


class ClosedSetReachabilityTests(unittest.TestCase):
    """Every member of the closed set, produced BY NAME through the real front door.

    Four of the five come from a frame a hostile sidecar can send with no help at all. The
    fifth — ``stream_expired`` — needs the supervisor's own clock to have moved past the row's
    expiry, which is a fact about time rather than a state a peer arranges; it is driven by
    the injected clock and named here so the distinction is on the record.
    """

    def test_all_five_reasons_are_reachable_and_none_is_a_stub(self):
        produced = set()
        f = Fixture(b"tiny")

        _c, r = front_door(f, f.request(length=1))
        produced.add(r["error"]["reason"])                       # malformed

        _c, r = front_door(f, f.request(output_stream_id="Q" * 43))
        produced.add(r["error"]["reason"])                       # stream_unknown

        _c, r = front_door(f, f.request(receipt_id="rcpt-other"))
        produced.add(r["error"]["reason"])                       # stream_binding_mismatch

        _c, r = front_door(f, f.request(seq=7))
        produced.add(r["error"]["reason"])                       # seq_out_of_range

        _c, r = front_door(f, f.request(), now_ms=f.row["expires_at_ms"] + 1)
        produced.add(r["error"]["reason"])                       # stream_expired

        self.assertEqual(produced, set(gor.OUTPUT_READ_REFUSAL_REASONS))
        self.assertEqual(len(gor.OUTPUT_READ_REFUSAL_REASONS), 5)

    def test_the_set_is_a_subset_of_the_closed_governed_union_by_design(self):
        """§4.10(h) (**NOT IMPLEMENTED** — a later ordered piece) names "a
        ``brops.governed-turn-output-read-result.v1`` ``refused``" as a
        GENUINE governed verdict, relayed verbatim — not one of the internal refusals its
        diagnostic carrier exists for. So unlike §4.10(a0)/(a)/(b)/(c)/(d), whose sets overlap
        ``GOVERNED_REFUSAL_REASONS`` only by accident of spelling, this containment is
        intended. Nothing here may lean on the stronger "disjoint namespace" reading."""
        import governed_turn_result as gtr
        self.assertTrue(set(gor.OUTPUT_READ_REFUSAL_REASONS)
                        <= set(gtr.GOVERNED_REFUSAL_REASONS))

    def test_the_discriminator_is_what_separates_a_read_refusal_from_a_verdict(self):
        f = Fixture()
        refusal = f.call(f.request(seq=99))
        self.assertEqual(refusal["protocol"], gor.OUTPUT_READ_RESULT_PROTOCOL)
        self.assertNotEqual(refusal["protocol"], "brops.governed-turn-result.v1")
        import governed_turn_result as gtr
        with self.assertRaises(SupervisorError):
            gtr.validate_turn_result(refusal)


# ---------------------------------------------------------------------------
# The mint is wired to a real production path
# ---------------------------------------------------------------------------


class CompletionMintTests(unittest.TestCase):
    """§4.10(f): "The row is durably committed BEFORE the §4.10(e) result summary is
    returned", and "a completing turn's stream is ALWAYS created".

    ``complete-run`` is the §5 v2 op that records what a run produced, so it is where the
    egress is owed. These tests drive the real ``dispatch`` op rather than calling
    ``mint_stream`` directly, because "the mint has a production caller" is exactly the claim
    the deleted Rust ladder could not make.
    """

    def _turn(self):
        conn = ledger()
        store = Store()
        output = b"the model said this"
        handle = store.publish(output)
        accept(conn, "attempt-1", nonce="nonce-1", receipt_id="rcpt-1", handle="c" * 64)
        gsl.mark_lease_ready(conn, "attempt-1", lease_handle="7" * 64, now_ms=NOW)
        gsl.gate_and_start(conn, "attempt-1", NOW)
        gsl.mark_executing(conn, "attempt-1", process_group_id="pg", cgroup_id="cg",
                           execution_started_marker="m", now_ms=NOW)
        return conn, store, handle, output

    def _complete(self, conn, store, handle, *, service):
        # A REAL chain, by the recorder's own rule (audit A-02, 2026-08-14). This fixture used to
        # carry `final_event_hash: "d" * 64` and an event with no `previous_event_hash` and no
        # `sequence` — a chain no recorder would write, which passed because nothing verified the
        # link. That is the finding, standing in a test: the fork detector's discriminator was a
        # value a fixture could invent.
        def _canon(obj):
            return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

        payload = {"output_sha256": handle}
        event = {
            "event_type": "output-captured",
            "payload": payload,
            "payload_sha256": hashlib.sha256(_canon(payload)).hexdigest(),
            "previous_event_hash": None,
            "sequence": 1,
        }
        chain = {
            "protocol": "brops.run-evidence-chain.v1",
            "final_event_hash": hashlib.sha256(_canon(event)).hexdigest(),
            "event_count": 1, "last_sequence": 1,
            "head_sequence": 1,
            "events": [event],
        }
        return gss.dispatch(
            {"op": "complete-run", "execution_attempt_id": "attempt-1",
             "produced": {"output_handle": handle,
                          "containment_evidence_handle": "b" * 64,
                          "completed_at_ms": NOW}},
            _config(), lambda m, s: True, lambda p: "0" * 64, lambda: NOW,
            conn=conn, publish_artifact=store.publish,
            read_run_evidence=lambda a: json.dumps(chain).encode(),
            output_read_service=service, peer_uid=BROKER_UID)

    def test_completing_a_run_mints_its_output_stream(self):
        conn, store, handle, output = self._turn()
        svc = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                    read_output=store.read)
        reply = self._complete(conn, store, handle, service=svc)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["output_stream"], gos.CREATED)
        row = gos.load_stream_for_attempt(conn, "attempt-1")
        self.assertIsNotNone(row)
        self.assertEqual(row["output_handle"], handle)
        self.assertEqual(row["output_bytes"], len(output))
        self.assertEqual(row["receipt_id"], "rcpt-1")

    def test_output_bytes_is_MEASURED_from_the_store_never_reported(self):
        """``produced`` carries no length and admits no extra key (audit F-01), so the only
        possible source is the bytes the handle addresses — which the store re-hashes."""
        conn, store, handle, output = self._turn()
        svc = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                    read_output=store.read)
        self._complete(conn, store, handle, service=svc)
        self.assertEqual(gos.load_stream_for_attempt(conn, "attempt-1")["output_bytes"],
                         len(output))
        self.assertNotIn("output_bytes", gsl.COMPLETION_FIELDS)

    def test_a_retried_completion_re_reads_the_same_token(self):
        conn, store, handle, _out = self._turn()
        svc = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                    read_output=store.read)
        first = self._complete(conn, store, handle, service=svc)
        token = gos.load_stream_for_attempt(conn, "attempt-1")["output_stream_id"]
        again = self._complete(conn, store, handle, service=svc)
        self.assertEqual(first["output_stream"], gos.CREATED)
        self.assertEqual(again["output_stream"], gos.IDEMPOTENT)
        self.assertEqual(gos.load_stream_for_attempt(conn, "attempt-1")["output_stream_id"],
                         token)

    def test_an_unconfigured_supervisor_mints_nothing_and_SAYS_so(self):
        """The pairing that keeps "always created" true: a supervisor with no
        ``output_read_service`` mints no stream AND serves no read, so there is no state in
        which rows exist that nothing can read, or reads are served against rows nothing
        created. The reply names it rather than being silent about it."""
        conn, store, handle, _out = self._turn()
        reply = self._complete(conn, store, handle, service=None)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["output_stream"], "unconfigured")
        self.assertIsNone(gos.load_stream_for_attempt(conn, "attempt-1"))

    def test_an_over_ceiling_output_refuses_the_completion_on_ONE_bound(self):
        """The §4.10(f) ceiling is enforced in exactly one place — ``mint_stream``'s
        validation, backed by the DDL CHECK — and ``measure_output`` deliberately does not
        repeat it. A second check there could only change the wording of a refusal, never its
        outcome, which is the class this repository deletes rather than ships."""
        conn, store, handle, _out = self._turn()
        oversized = bytes(8_388_609)
        svc = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                    read_output=lambda h: oversized)
        reply = self._complete(conn, store, handle, service=svc)
        self.assertFalse(reply["ok"])
        self.assertIsNone(gos.load_stream_for_attempt(conn, "attempt-1"))

    def test_an_unreadable_output_refuses_the_completion_rather_than_faking_a_stream(self):
        conn, store, handle, _out = self._turn()
        svc = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                    read_output=store.read)
        del store[handle]
        reply = self._complete(conn, store, handle, service=svc)
        self.assertFalse(reply["ok"])
        self.assertIsNone(gos.load_stream_for_attempt(conn, "attempt-1"))

    def test_a_completed_turns_stream_serves_the_exact_bytes_the_recorder_captured(self):
        """The end of the chain this piece owns: complete-run mints, the read serves, and the
        reassembled bytes content-address to the handle the terminal record names."""
        conn, store, handle, output = self._turn()
        svc = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                    read_output=store.read)
        self._complete(conn, store, handle, service=svc)
        row = gos.load_stream_for_attempt(conn, "attempt-1")
        reply = svc.handle({"protocol": gor.OUTPUT_READ_PROTOCOL,
                            "output_stream_id": row["output_stream_id"],
                            "receipt_id": "rcpt-1",
                            "execution_attempt_id": "attempt-1", "seq": 0},
                           peer_uid=SIDECAR_UID, conn=conn, clock_ms=lambda: NOW)
        got = base64.urlsafe_b64decode(reply["bytes_b64"] + "===")
        self.assertEqual(got, output)
        self.assertEqual(hashlib.sha256(got).hexdigest(), handle)


# ---------------------------------------------------------------------------
# What this piece does NOT decide
# ---------------------------------------------------------------------------


class NothingGovernedIsMintedTests(unittest.TestCase):
    def test_the_module_reads_no_clock_and_holds_no_entropy(self):
        src = (ROOT / "runtime" / "governed_output_read.py").read_text(encoding="utf-8")
        for forbidden in ("import time", "time.time", "import secrets", "import random",
                          "uuid", "datetime"):
            self.assertNotIn(forbidden, src, forbidden)

    def test_the_module_signs_nothing_and_verifies_no_signature(self):
        src = (ROOT / "runtime" / "governed_output_read.py").read_text(encoding="utf-8")
        for forbidden in ("ed25519", "verify_sig(", "sign_attestation", "bro_signature",
                          "envelope_jcs_b64\"", "signature_b64\""):
            self.assertNotIn(forbidden, src, forbidden)

    def test_no_gate_moved(self):
        src = (ROOT / "runtime" / "governed_output_read.py").read_text(encoding="utf-8")
        for forbidden in ("trusted_verified", "governed_verification_unconfigured",
                          "connect_broker", "UpstreamBlockedExecutor"):
            self.assertNotIn(forbidden, src, forbidden)

    def test_this_hop_is_not_an_authority_over_the_bytes(self):
        """§4.6/§7.1: the desktop's authority is the SIGNED envelope's ``output_sha256`` /
        ``output_bytes``, applied to the reassembled bytes. A tampered chunk is caught there,
        not here — so the honest statement is that this hop can serve wrong bytes and the
        whole-output digest is what refuses them.

        Demonstrated rather than asserted: the store is made to return bytes that do not match
        the handle, and what stops them is the STORE's own digest check, never this module."""
        f = Fixture(b"real output")
        tampered = Store()
        tampered[f.handle] = b"forged!!!!!"
        svc = gor.OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                    read_output=tampered.read)
        with self.assertRaises(SupervisorError):
            svc.handle(f.request(), peer_uid=SIDECAR_UID, conn=f.conn,
                       clock_ms=lambda: NOW)

    def test_the_reply_carries_no_receipt_no_signature_and_no_trust_state(self):
        f = Fixture()
        keys = set(f.call()) | set(f.call(f.request(seq=99)))
        for absent in ("receipt", "envelope_jcs_b64", "signature_b64", "trust_state",
                       "receipt_id", "execution_attempt_id", "status"):
            self.assertNotIn(absent, keys, absent)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
