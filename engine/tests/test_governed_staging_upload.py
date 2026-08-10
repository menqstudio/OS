"""Offline tests for the staging upload — rev-30 §4.10(a), §4.10(b), §4.10(c) + §2.4.

No socket, no key material, no OS trust chain. The ledger is a real SQLite file created
from the canonical shared DDL, the ``session_dir`` and every ``<seq>.chunk`` is a real file
on a real filesystem, and the store is a real content-addressed dict whose handle IS the
digest of the bytes it was given. Everything a stranger needs to run this is in the
standard library.

The tests are organized as the design's own obligations:

  * every reason in the three CLOSED refusal sets is REACHABLE, by name, from a request a
    hostile sidecar could actually send — 29 of them;
  * the rules that make an upload mean something are proved against the DATABASE with raw
    SQL, bypassing every Python guard, and each is proved in ISOLATION so that one trigger
    passing does not stand in for another;
  * the deterministic chunk length and the two independent size caps are tested AT their
    boundaries, on both sides;
  * §2.4's crash/corruption reconciliation is driven by actually deleting and rewriting the
    durable files, not by mocking a failure;
  * nothing here creates an acceptance row, an ``execution_attempt_id``, or a lease.
"""

import base64
import hashlib
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_staging_ledger as gsl  # noqa: E402
import governed_staging_upload as gsu  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
from brops_protocol import encode_frame  # noqa: E402
from governed_supervisor import SupervisorError  # noqa: E402

SIDECAR_UID = 4101
BROKER_UID = 4102

NOW = 1_700_000_100_000
EXPIRES = NOW + 30_000

CHUNK = gsu.MAX_STAGING_CHUNK_BYTES          # 184320

SYSTEM_BYTES = b"you are a governed assistant.\n" * 7
HISTORY_BYTES = bytes((i * 7 + 11) % 251 for i in range(CHUNK + 4096))
GENCFG_BYTES = b'{"max_tokens":512,"temperature":0.2}'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class _Store:
    """A real content-addressed store: the handle IS the digest of the bytes written."""

    def __init__(self):
        self.blobs = {}

    def publish(self, data: bytes) -> str:
        handle = sha(data)
        self.blobs.setdefault(handle, data)
        return handle


class _Case(unittest.TestCase):
    """One durable ledger on a REAL file and one REAL staging root per test.

    The staging row is created through ``governed_staging_ledger.open_staging`` — the same
    CAS §4.10(a0) drives — rather than by replaying a signed challenge. What §4.10(a)(b)(c)
    need from the turn is exactly the three committed digests and the ``UPLOADING`` state;
    how the supervisor came to believe them is §4.10(a0)'s tested concern, and re-proving it
    here would test the challenge machinery a third time instead of this one.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.conn = gsl.open_ledger(str(self.base / "sup.db"))
        self.staging_root = self.base / "staging"
        self.store = _Store()
        self.clock = NOW
        self.turn = self.new_turn()

    def _cleanup(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.tmp.cleanup()
        except OSError:
            # Windows keeps a handle on a just-closed SQLite file for a moment; the temp
            # dir is the OS's problem, not the test's verdict.
            pass

    # ---- fixtures --------------------------------------------------------------
    def new_turn(self, *, nonce="nonce-1", handle=None, expires=EXPIRES, now=None,
                 install="inst-1", system=None, history=None, gencfg=None):
        handle = handle or sha(nonce.encode("utf-8") + b"|challenge")
        row = gsl.NewStaging(
            install_id=install,
            request_nonce=nonce,
            challenge_handle=handle,
            run_id="run-1",
            task_id="task-1",
            workspace_id="ws-1",
            system_sha256=sha(system if system is not None else SYSTEM_BYTES),
            history_sha256=sha(history if history is not None else HISTORY_BYTES),
            generation_config_sha256=sha(gencfg if gencfg is not None else GENCFG_BYTES),
            challenge_expires_at_ms=expires,
        )
        gsl.open_staging(self.conn, row, NOW if now is None else now)
        return row

    def service(self, *, publish=None, mint=None, sidecar_uid=SIDECAR_UID):
        return gsu.StagingService(
            allowed_sidecar_uid=sidecar_uid,
            staging_root=str(self.staging_root),
            publish_artifact=publish or self.store.publish,
            **({"mint_id": mint} if mint is not None else {}),
        )

    def call(self, request, *, peer_uid=SIDECAR_UID, **service_kwargs):
        return self.service(**service_kwargs).handle(
            request, peer_uid=peer_uid, conn=self.conn, clock_ms=lambda: self.clock
        )

    # ---- request builders ------------------------------------------------------
    def open_request(self, artifact="system", *, data=None, turn=None, **overrides):
        turn = turn or self.turn
        data = SYSTEM_BYTES if data is None else data
        body = {
            "protocol": gsu.STAGING_OPEN_PROTOCOL,
            "install_id": turn.install_id,
            "challenge_handle": turn.challenge_handle,
            "request_nonce": turn.request_nonce,
            "artifact": artifact,
            "declared_len": len(data),
            "declared_sha256": sha(data),
        }
        body.update(overrides)
        return body

    def chunk_request(self, session_id, seq, data, **overrides):
        body = {
            "protocol": gsu.STAGING_CHUNK_PROTOCOL,
            "staging_session_id": session_id,
            "seq": seq,
            "bytes_b64": b64(data),
        }
        body.update(overrides)
        return body

    def final_request(self, session_id, seq, **overrides):
        body = {
            "protocol": gsu.STAGING_FINAL_PROTOCOL,
            "staging_session_id": session_id,
            "seq": seq,
        }
        body.update(overrides)
        return body

    # ---- flows -----------------------------------------------------------------
    def open_session(self, artifact="system", data=None, **kwargs):
        reply = self.call(self.open_request(artifact, data=data, **kwargs))
        self.assertEqual(reply["status"], "opened", reply)
        return reply["staging_session_id"]

    def send_all_chunks(self, session_id, data):
        offset, seq = 0, 0
        while offset < len(data):
            n = min(CHUNK, len(data) - offset)
            reply = self.call(self.chunk_request(session_id, seq, data[offset:offset + n]))
            self.assertEqual(reply["status"], "ack", reply)
            offset += n
            seq += 1
        return seq

    def upload(self, artifact, data, **kwargs):
        session_id = self.open_session(artifact, data, **kwargs)
        seq = self.send_all_chunks(session_id, data)
        return session_id, self.call(self.final_request(session_id, seq))

    # ---- introspection ---------------------------------------------------------
    def session_row(self, session_id):
        return gsl.load_session(self.conn, session_id)

    def turn_row(self, turn=None):
        turn = turn or self.turn
        return gsl.load_staging(self.conn, turn.install_id, turn.request_nonce)

    def session_dir(self, session_id):
        return pathlib.Path(self.session_row(session_id)["session_dir"])


# ---------------------------------------------------------------------------
# The happy path, and what it does and does NOT create
# ---------------------------------------------------------------------------


class UploadPublishesTheDeclaredInputsTests(_Case):
    def test_three_artifacts_publish_and_the_turn_reaches_inputs_ready(self):
        for artifact, data in (("system", SYSTEM_BYTES),
                               ("history", HISTORY_BYTES),
                               ("generation_config", GENCFG_BYTES)):
            _sid, reply = self.upload(artifact, data)
            self.assertEqual(reply["protocol"], gsu.STAGING_FINAL_RESULT_PROTOCOL)
            self.assertEqual(reply["status"], "published")
            self.assertEqual(reply["artifact"], artifact)
            self.assertEqual(reply["handle"], sha(data))

        # `inputs_ready` is true only on the LAST one — it is a statement about the turn.
        turn = self.turn_row()
        self.assertEqual(turn["state"], gsl.INPUTS_READY)
        self.assertEqual(turn["system_handle"], sha(SYSTEM_BYTES))
        self.assertEqual(turn["history_handle"], sha(HISTORY_BYTES))
        self.assertEqual(turn["generation_config_handle"], sha(GENCFG_BYTES))
        for data in (SYSTEM_BYTES, HISTORY_BYTES, GENCFG_BYTES):
            self.assertEqual(self.store.blobs[sha(data)], data)

    def test_inputs_ready_is_false_until_the_third_artifact(self):
        _sid, first = self.upload("system", SYSTEM_BYTES)
        self.assertFalse(first["inputs_ready"])
        _sid, second = self.upload("generation_config", GENCFG_BYTES)
        self.assertFalse(second["inputs_ready"])
        self.assertEqual(self.turn_row()["state"], gsl.UPLOADING)
        _sid, third = self.upload("history", HISTORY_BYTES)
        self.assertTrue(third["inputs_ready"])
        self.assertEqual(self.turn_row()["state"], gsl.INPUTS_READY)

    def test_a_multi_chunk_artifact_is_reassembled_byte_exactly(self):
        session_id, reply = self.upload("history", HISTORY_BYTES)
        self.assertEqual(self.session_row(session_id)["next_seq"], 2)
        self.assertEqual(self.store.blobs[reply["handle"]], HISTORY_BYTES)

    def test_a_zero_byte_artifact_sends_no_chunk_and_publishes_the_empty_bytes(self):
        """§4.10(b), LOCKED: `declared_len == 0` sends NO chunk message at all and goes
        straight to final with `seq == next_seq == 0`."""
        turn = self.new_turn(nonce="nonce-empty", gencfg=b"")
        session_id = self.open_session("generation_config", b"", turn=turn)
        reply = self.call(self.final_request(session_id, 0))
        self.assertEqual(reply["status"], "published")
        self.assertEqual(reply["handle"], sha(b""))
        self.assertEqual(self.store.blobs[sha(b"")], b"")
        self.assertEqual(self.session_row(session_id)["next_seq"], 0)

    def test_the_chunk_files_are_immutable_and_named_by_seq(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.send_all_chunks(session_id, HISTORY_BYTES)
        names = sorted(p.name for p in self.session_dir(session_id).iterdir())
        self.assertEqual(names, ["0.chunk", "1.chunk"])
        self.assertEqual(
            (self.session_dir(session_id) / "0.chunk").read_bytes(), HISTORY_BYTES[:CHUNK])

    def test_no_temp_files_survive_a_completed_upload(self):
        session_id, _reply = self.upload("history", HISTORY_BYTES)
        leftovers = [p.name for p in self.session_dir(session_id).iterdir()
                     if p.name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])


class NothingGovernedIsMintedTests(_Case):
    def test_a_completed_upload_creates_no_acceptance_row(self):
        for artifact, data in (("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
                               ("generation_config", GENCFG_BYTES)):
            self.upload(artifact, data)
        for table in ("governed_turn_acceptance", "governed_turn_completion",
                      "governed_turn_outbox"):
            with self.subTest(table=table):
                rows = self.conn.execute("SELECT COUNT(*) AS n FROM %s" % table).fetchone()
                self.assertEqual(rows["n"], 0)

    def test_neither_staging_table_has_an_execution_attempt_id_column(self):
        for table in ("governed_turn_staging_session", "governed_turn_staging_chunk"):
            with self.subTest(table=table):
                columns = {r["name"] for r in
                           self.conn.execute("PRAGMA table_info(%s)" % table)}
                self.assertNotIn("execution_attempt_id", columns)
                self.assertNotIn("lease_id", columns)
                self.assertNotIn("receipt_id", columns)

    def test_a_request_carrying_a_supervisor_minted_id_is_refused_malformed(self):
        """The P1-5 door, on all three protocols: a requester naming the identity its own
        execution would later be judged under is refused before any side effect."""
        session_id = self.open_session("system", SYSTEM_BYTES)
        for extra in ("execution_attempt_id", "lease_id", "receipt_id"):
            with self.subTest(field=extra):
                self.assertEqual(
                    self.call(self.open_request(**{extra: "x"}))["reason"], "malformed")
                self.assertEqual(
                    self.call(self.chunk_request(session_id, 0, b"", **{extra: "x"}))["reason"],
                    "malformed")
                self.assertEqual(
                    self.call(self.final_request(session_id, 0, **{extra: "x"}))["reason"],
                    "malformed")

    def test_the_staging_row_never_leaves_the_pre_accept_lifecycle(self):
        """INPUTS_READY is the furthest an upload can move a turn. There is no edge out of
        it in the §2.4 domain, so no amount of staging traffic can produce an execution
        right — §4.10(d), which consumes this state, is tested in its own file and only
        ever READS it."""
        for artifact, data in (("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
                               ("generation_config", GENCFG_BYTES)):
            self.upload(artifact, data)
        self.assertIn(self.turn_row()["state"], gsl.ALL_STAGING_STATES)
        self.assertEqual(self.turn_row()["state"], gsl.INPUTS_READY)


# ---------------------------------------------------------------------------
# §4.10(a) — every reason in the closed set, reachable by name
# ---------------------------------------------------------------------------


class StagingOpenRefusalsTests(_Case):
    def refuse(self, request, **kwargs):
        reply = self.call(request, **kwargs)
        self.assertEqual(reply["protocol"], gsu.STAGING_OPEN_RESULT_PROTOCOL)
        self.assertEqual(reply["status"], "refused", reply)
        return reply["reason"]

    def test_peer_denied_for_a_non_sidecar_peer(self):
        self.assertEqual(self.refuse(self.open_request(), peer_uid=BROKER_UID), "peer_denied")

    def test_peer_denied_when_the_supervisor_has_no_sidecar_principal(self):
        reply = gss.dispatch(
            self.open_request(), None, None, None, lambda: self.clock,
            conn=self.conn, staging_service=None, peer_uid=SIDECAR_UID)
        self.assertEqual(reply["reason"], "peer_denied")

    def test_no_staging_row_when_the_turn_was_never_opened(self):
        self.assertEqual(
            self.refuse(self.open_request(request_nonce="never-opened")), "no_staging_row")

    def test_no_staging_row_when_the_challenge_handle_belongs_to_another_turn(self):
        other = self.new_turn(nonce="nonce-2")
        self.assertEqual(
            self.refuse(self.open_request(challenge_handle=other.challenge_handle)),
            "no_staging_row")

    def test_no_staging_row_when_the_turn_has_already_reached_inputs_ready(self):
        for artifact, data in (("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
                               ("generation_config", GENCFG_BYTES)):
            self.upload(artifact, data)
        turn = self.new_turn(nonce="nonce-later")
        del turn  # only to prove the refusal is about STATE, not about a missing row
        self.assertEqual(self.refuse(self.open_request(artifact="system")), "no_staging_row")

    def test_artifact_invalid_for_policy_bundle(self):
        """§2.4 policy authority: the challenge has no `policy_bundle_sha256`, so there is
        nothing to bind a sidecar-supplied policy against and it may not traverse the
        sidecar at all."""
        self.assertEqual(
            self.refuse(self.open_request(artifact="policy_bundle")), "artifact_invalid")

    def test_artifact_invalid_for_output_and_for_an_unknown_name(self):
        for artifact in ("output", "containment_evidence", "", "SYSTEM"):
            with self.subTest(artifact=artifact):
                self.assertEqual(
                    self.refuse(self.open_request(artifact=artifact)), "artifact_invalid")

    def test_digest_mismatch_when_declared_sha256_is_not_the_committed_digest(self):
        self.assertEqual(
            self.refuse(self.open_request(declared_sha256=sha(b"other bytes"))),
            "digest_mismatch")

    def test_digest_mismatch_when_the_right_digest_is_declared_for_the_wrong_artifact(self):
        self.assertEqual(
            self.refuse(self.open_request(artifact="history",
                                          declared_sha256=sha(SYSTEM_BYTES))),
            "digest_mismatch")

    def test_oversize_above_each_artifact_ceiling(self):
        """`oversize` sits BEHIND `digest_mismatch` in §4.10(a)'s order, so reaching it takes
        a request that declares the challenge's real digest and then lies about the length —
        which is exactly the request worth refusing: the ceiling is what stops an 8 MiB
        reservation for a `generation_config` the challenge capped at 64 KiB."""
        for artifact, digest in (("system", self.turn.system_sha256),
                                 ("history", self.turn.history_sha256),
                                 ("generation_config", self.turn.generation_config_sha256)):
            with self.subTest(artifact=artifact):
                self.assertEqual(
                    self.refuse(self.open_request(
                        artifact=artifact, declared_sha256=digest,
                        declared_len=gsu.ARTIFACT_CEILINGS[artifact] + 1)),
                    "oversize")

    def test_oversize_boundary_the_exact_ceiling_is_admitted(self):
        """Strictly `>`, not `>=`: a declaration AT the ceiling opens, one byte over does
        not. Tested on both sides of the same boundary."""
        self.assertEqual(
            self.call(self.open_request(
                artifact="generation_config",
                declared_len=gsu.ARTIFACT_CEILINGS["generation_config"],
                declared_sha256=self.turn.generation_config_sha256))["status"],
            "opened")
        self.assertEqual(
            self.refuse(self.open_request(
                artifact="history", declared_sha256=self.turn.history_sha256,
                declared_len=gsu.ARTIFACT_CEILINGS["history"] + 1)),
            "oversize")

    def test_retry_conflict_on_a_reopen_declaring_a_different_length(self):
        self.open_session("system", SYSTEM_BYTES)
        self.assertEqual(
            self.refuse(self.open_request(declared_len=len(SYSTEM_BYTES) - 1)),
            "retry_conflict")

    def test_retry_conflict_on_a_reopen_declaring_a_different_digest(self):
        """Reached through raw SQL, because §4.10(a)'s own `digest_mismatch` gate stands in
        front of it on the wire. The ledger conflict is a SECOND, independent rule: it holds
        for any writer, including one that never consults the turn."""
        self.open_session("system", SYSTEM_BYTES)
        with self.assertRaises(gsl.Conflict):
            gsl.open_session(self.conn, gsl.NewSession(
                staging_session_id="s2", challenge_handle=self.turn.challenge_handle,
                artifact="system", declared_len=len(SYSTEM_BYTES),
                declared_sha256=sha(b"different"), session_dir=str(self.base / "s2")))

    def test_quota_sessions_on_the_seventh_concurrent_session(self):
        """Reachable because an EXPIRED turn occupies zero MAX_CONCURRENT_GOVERNED_TURNS
        quota (§2.4 live-count rule) while its SESSIONS remain until the sweep — so three
        turns can hold sessions at once even though only two may be live."""
        turns = [self.turn]
        turns.append(self.new_turn(nonce="nonce-2"))
        self.clock = EXPIRES + 1
        turns.append(self.new_turn(nonce="nonce-3", expires=self.clock + 30_000,
                                   now=self.clock))
        opened = 0
        for turn in turns:
            for artifact, data in (("system", SYSTEM_BYTES),
                                   ("generation_config", GENCFG_BYTES),
                                   ("history", HISTORY_BYTES)):
                reply = self.call(self.open_request(artifact, data=data, turn=turn))
                if reply["status"] == "opened":
                    opened += 1
                    continue
                self.assertEqual(reply["reason"], "quota_sessions")
                self.assertEqual(opened, gsl.MAX_STAGING_SESSIONS_PER_INSTALL)
                return
        self.fail("the seventh session was not refused")

    def test_quota_bytes_when_the_declared_reservation_exceeds_the_install_cap(self):
        """Charged on `declared_len` at OPEN, so the cap binds before a byte arrives."""
        big = b"h" * 16
        turns = [self.turn, self.new_turn(nonce="nonce-2")]
        self.clock = EXPIRES + 1
        turns.append(self.new_turn(nonce="nonce-3", expires=self.clock + 30_000,
                                   now=self.clock))
        for turn in turns[:2]:
            reply = self.call(self.open_request(
                "history", data=big, turn=turn,
                declared_len=gsu.ARTIFACT_CEILINGS["history"],
                declared_sha256=turn.history_sha256))
            self.assertEqual(reply["status"], "opened", reply)
        reply = self.call(self.open_request(
            "history", data=big, turn=turns[2],
            declared_len=gsu.ARTIFACT_CEILINGS["history"],
            declared_sha256=turns[2].history_sha256))
        self.assertEqual(reply["reason"], "quota_bytes")

    def test_session_corrupt_on_a_reopen_of_a_corrupted_session(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        (self.session_dir(session_id) / "0.chunk").unlink()
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))  # detects it
        self.assertEqual(
            self.refuse(self.open_request("history", data=HISTORY_BYTES)), "session_corrupt")

    def test_malformed_on_an_unknown_field(self):
        self.assertEqual(self.refuse(self.open_request(extra="x")), "malformed")

    def test_malformed_on_a_missing_field(self):
        body = self.open_request()
        body.pop("request_nonce")
        self.assertEqual(self.refuse(body), "malformed")

    def test_malformed_on_wrong_types(self):
        for field, value in (("install_id", 7), ("request_nonce", None),
                             ("challenge_handle", "not-hex"), ("declared_len", "12"),
                             ("declared_sha256", "A" * 64), ("artifact", 3),
                             ("declared_len", -1), ("declared_len", True),
                             ("install_id", "x" * 129)):
            with self.subTest(field=field, value=value):
                self.assertEqual(self.refuse(self.open_request(**{field: value})), "malformed")

    def test_malformed_on_a_non_object_request(self):
        """Called on the handler directly: `StagingService` routes on `protocol`, so a body
        that is not an object never reaches it through the service. The handler is still the
        thing that has to fail closed, because it is also the unit other code will call."""
        for body in ([], "open", 7, None, [{"protocol": gsu.STAGING_OPEN_PROTOCOL}]):
            with self.subTest(body=body):
                reply = gsu.handle_staging_open(
                    body, peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
                    conn=self.conn, staging_root=str(self.staging_root))
                self.assertEqual(reply["reason"], "malformed")

    def test_the_control_frame_bound_is_a_consequence_of_the_exhaustive_shape(self):
        """§4.10(a) fixes the control frame at 4 KiB, and the SHAPE is what delivers it: every
        field is a ≤128-char id, a 64-hex digest, a closed-set artifact name or a bounded
        int, so the largest request that can pass validation is a few hundred bytes. There is
        deliberately no separate handler-level frame check for this protocol — mutation
        testing showed one could never fire — so the bound is asserted here instead."""
        largest = {
            "protocol": gsu.STAGING_OPEN_PROTOCOL,
            "install_id": "i" * 128,
            "challenge_handle": "d" * 64,
            "request_nonce": "n" * 128,
            "artifact": max(gsl.STAGING_ARTIFACTS, key=len),
            "declared_len": 8388608,
            "declared_sha256": "e" * 64,
        }
        self.assertLess(len(encode_frame(largest)[4:]),
                        gsu.MAX_STAGING_CONTROL_FRAME_BYTES)
        largest_final = {"protocol": gsu.STAGING_FINAL_PROTOCOL,
                         "staging_session_id": "s" * 128, "seq": 45}
        self.assertLess(len(encode_frame(largest_final)[4:]),
                        gsu.MAX_STAGING_CONTROL_FRAME_BYTES)

    def test_malformed_on_an_over_length_id(self):
        """A legal-sized frame with maximum-length ids gets a real verdict; anything longer
        is out of shape. `malformed` is the right word because §4.10(a)'s closed set contains
        no size reason, and inventing one would put a string on the wire that the §4.10(h)
        routing table (**NOT IMPLEMENTED**) cannot map."""
        self.assertEqual(
            self.refuse(self.open_request(install_id="i" * 128, request_nonce="n" * 128)),
            "no_staging_row")
        self.assertEqual(self.refuse(self.open_request(install_id="i" * 129)), "malformed")
        self.assertEqual(self.refuse(self.open_request(install_id="i" * 5000)), "malformed")

    def test_the_closed_reason_set_is_exactly_the_one_the_design_enumerates(self):
        self.assertEqual(
            sorted(gsu.STAGING_OPEN_REFUSAL_REASONS),
            sorted(["peer_denied", "no_staging_row", "artifact_invalid", "digest_mismatch",
                    "oversize", "retry_conflict", "quota_sessions", "quota_bytes",
                    "session_corrupt", "malformed"]))


# ---------------------------------------------------------------------------
# §4.10(b) — every reason in the closed set, reachable by name
# ---------------------------------------------------------------------------


class ChunkRefusalsTests(_Case):
    def setUp(self):
        super().setUp()
        self.session_id = self.open_session("history", HISTORY_BYTES)

    def refuse(self, request, **kwargs):
        reply = self.call(request, **kwargs)
        self.assertEqual(reply["protocol"], gsu.STAGING_CHUNK_RESULT_PROTOCOL)
        self.assertEqual(reply["status"], "refused", reply)
        self.assertIsInstance(reply["next_seq"], int)
        return reply["reason"]

    def test_session_unknown_for_an_id_that_was_never_minted(self):
        self.assertEqual(
            self.refuse(self.chunk_request("no-such-session", 0, b"x")), "session_unknown")

    def test_seq_mismatch_on_a_true_gap(self):
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, 1, HISTORY_BYTES[:CHUNK])),
            "seq_mismatch")

    def test_retry_conflict_when_an_accepted_seq_is_resent_with_different_bytes(self):
        self.call(self.chunk_request(self.session_id, 0, HISTORY_BYTES[:CHUNK]))
        mutated = bytearray(HISTORY_BYTES[:CHUNK])
        mutated[0] ^= 0xFF
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, 0, bytes(mutated))),
            "retry_conflict")

    def test_retry_conflict_when_a_different_chunk_is_already_durable_at_this_seq(self):
        """§2.4 recovery rule (a) from the other side: a crash left a `<seq>.chunk` with no
        DB row, and the re-send does not match it. The durable file wins; it is never
        overwritten."""
        directory = self.session_dir(self.session_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "0.chunk").write_bytes(b"someone else's bytes")
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, 0, HISTORY_BYTES[:CHUNK])),
            "retry_conflict")

    def test_oversize_chunk_one_byte_over_the_decoded_cap(self):
        """184321 decoded bytes still produce a frame that FITS — so this can only be caught
        by the decoded cap, checked independently (§2.4 P1-4)."""
        payload = b"z" * (CHUNK + 1)
        self.assertLessEqual(len(encode_frame(self.chunk_request(self.session_id, 0, payload))),
                             gsu.MAX_STAGING_CHUNK_FRAME_BYTES)
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, 0, payload)), "oversize_chunk")

    def test_oversize_frame_on_a_256_kib_decoded_chunk(self):
        """A 256 KiB decoded chunk base64url-encodes to 349528 bytes and must be refused on
        the FRAME cap, before the payload is decoded at all."""
        payload = b"z" * (256 * 1024)
        self.assertGreater(len(b64(payload)), gsu.MAX_STAGING_CHUNK_FRAME_BYTES)
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, 0, payload)), "oversize_frame")

    def test_over_declared_when_the_chunk_would_pass_declared_len(self):
        turn = self.new_turn(nonce="nonce-small", system=b"tiny")
        session_id = self.open_session("system", b"tiny", turn=turn)
        self.assertEqual(
            self.refuse(self.chunk_request(session_id, 0, b"far too many bytes")),
            "over_declared")

    def test_nondeterministic_chunk_on_a_short_chunk_that_still_fits(self):
        """The Track E amplification vector: a sender trying to turn one artifact into many
        tiny messages is refused on its FIRST one."""
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, 0, b"x")),
            "nondeterministic_chunk")

    def test_nondeterministic_chunk_on_a_final_remainder_sent_early(self):
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, 0, HISTORY_BYTES[:CHUNK - 1])),
            "nondeterministic_chunk")

    def test_too_many_chunks_at_and_above_the_cardinality_cap(self):
        for seq in (gsl.MAX_STAGING_CHUNKS, gsl.MAX_STAGING_CHUNKS + 1, 10_000):
            with self.subTest(seq=seq):
                self.assertEqual(
                    self.refuse(self.chunk_request(self.session_id, seq, b"x")),
                    "too_many_chunks")

    def test_the_cardinality_boundary_45_is_a_seq_mismatch_not_too_many_chunks(self):
        """`seq == 45` is the LAST legal sequence, so at the cap boundary the verdict has to
        be about the cursor, not the cap."""
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, gsl.MAX_STAGING_CHUNKS - 1, b"x")),
            "seq_mismatch")

    def test_session_corrupt_after_a_durable_chunk_disappears(self):
        self.call(self.chunk_request(self.session_id, 0, HISTORY_BYTES[:CHUNK]))
        (self.session_dir(self.session_id) / "0.chunk").unlink()
        self.assertEqual(
            self.refuse(self.chunk_request(self.session_id, 0, HISTORY_BYTES[:CHUNK])),
            "session_corrupt")

    def test_malformed_on_shape_violations(self):
        base = self.chunk_request(self.session_id, 0, b"x")
        cases = [dict(base, extra="y")]
        for field, value in (("seq", "0"), ("seq", -1), ("seq", True), ("seq", 1.0),
                             ("bytes_b64", 7), ("bytes_b64", "not base64!!"),
                             ("bytes_b64", "=="), ("staging_session_id", ""),
                             ("staging_session_id", "s" * 129),
                             ("staging_session_id", 7)):
            cases.append(dict(base, **{field: value}))
        cases.append({k: v for k, v in base.items() if k != "seq"})
        for body in cases:
            with self.subTest(body=sorted((k, repr(v)) for k, v in body.items())):
                self.assertEqual(self.refuse(body), "malformed")

    def test_malformed_on_a_foreign_protocol_const(self):
        """Routed by the handler itself, not by the service: `StagingService` dispatches on
        `protocol`, so a foreign const reaching a handler at all is only possible when the
        handler is called directly — and it must still refuse rather than proceed."""
        reply = gsu.handle_staging_chunk(
            dict(self.chunk_request(self.session_id, 0, b"x"), protocol="brops.other.v1"),
            peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID, conn=self.conn)
        self.assertEqual(reply["reason"], "malformed")

    def test_the_ack_arm_is_a_discriminated_union(self):
        reply = self.call(self.chunk_request(self.session_id, 0, HISTORY_BYTES[:CHUNK]))
        self.assertEqual(reply["status"], "ack")
        self.assertIsNone(reply["reason"])
        self.assertEqual(reply["next_seq"], 1)

    def test_the_closed_reason_set_is_exactly_the_one_the_design_enumerates(self):
        self.assertEqual(
            sorted(gsu.STAGING_CHUNK_REFUSAL_REASONS),
            sorted(["session_unknown", "seq_mismatch", "retry_conflict", "oversize_chunk",
                    "oversize_frame", "over_declared", "nondeterministic_chunk",
                    "too_many_chunks", "session_corrupt", "malformed"]))


# ---------------------------------------------------------------------------
# §4.10(c) — every reason in the closed set, reachable by name
# ---------------------------------------------------------------------------


class FinalRefusalsTests(_Case):
    def refuse(self, request, **kwargs):
        reply = self.call(request, **kwargs)
        self.assertEqual(reply["protocol"], gsu.STAGING_FINAL_RESULT_PROTOCOL)
        self.assertEqual(reply["status"], "refused", reply)
        return reply["reason"]

    def test_session_unknown_for_an_id_that_was_never_minted(self):
        self.assertEqual(self.refuse(self.final_request("nope", 0)), "session_unknown")

    def test_seq_mismatch_when_the_named_cursor_is_not_the_durable_one(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        for seq in (0, 2, 46):
            with self.subTest(seq=seq):
                self.assertEqual(self.refuse(self.final_request(session_id, seq)),
                                 "seq_mismatch")

    def test_len_mismatch_when_the_sender_finals_before_the_declared_bytes_arrive(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        self.assertEqual(self.refuse(self.final_request(session_id, 1)), "len_mismatch")

    def test_sha_mismatch_when_the_uploaded_bytes_are_not_the_declared_bytes(self):
        """The sender declared the digest the challenge committed to — it had to, or the
        open would have been `digest_mismatch` — and then sent DIFFERENT bytes of the same
        length. Only re-hashing from byte zero catches it."""
        forged = bytearray(SYSTEM_BYTES)
        forged[3] ^= 0x20
        session_id = self.open_session("system", SYSTEM_BYTES)
        self.call(self.chunk_request(session_id, 0, bytes(forged)))
        self.assertEqual(self.refuse(self.final_request(session_id, 1)), "sha_mismatch")

    def test_handle_not_challenge_when_the_store_returns_a_different_handle(self):
        """The store re-derives a handle from the bytes it actually wrote. If that disagrees
        with the digest computed here, the supervisor is not looking at the artifact it
        assembled — refuse rather than bind a handle nothing resolves to."""
        session_id = self.open_session("system", SYSTEM_BYTES)
        self.send_all_chunks(session_id, SYSTEM_BYTES)
        self.assertEqual(
            self.refuse(self.final_request(session_id, 1), publish=lambda data: "9" * 64),
            "handle_not_challenge")

    def test_handle_not_challenge_when_the_store_returns_a_non_handle(self):
        session_id = self.open_session("system", SYSTEM_BYTES)
        self.send_all_chunks(session_id, SYSTEM_BYTES)
        self.assertEqual(
            self.refuse(self.final_request(session_id, 1), publish=lambda data: None),
            "handle_not_challenge")

    def test_handle_not_challenge_when_the_turn_no_longer_commits_to_the_digest(self):
        """Defence in depth: the equality §4.10(a) checked at OPEN is re-checked against
        durable state at the moment of publication. Reached by rebuilding the turn's row —
        the immutable-binding trigger refuses to EDIT the committed digest, which is itself
        the point."""
        session_id = self.open_session("system", SYSTEM_BYTES)
        self.send_all_chunks(session_id, SYSTEM_BYTES)
        # The committed digest cannot be edited through any legal path — the immutable
        # binding trigger forbids it, and that trigger has to be DROPPED to stage this at
        # all. Which is the honest statement of this refusal's reachability: it is
        # defence-in-depth against durable state that has already been tampered with, not a
        # verdict any sidecar frame can produce on its own.
        self.conn.execute("DROP TRIGGER trg_governed_turn_staging_immutable_binding")
        self.conn.execute(
            "UPDATE governed_turn_staging SET system_sha256 = ? WHERE challenge_handle = ?",
            (sha(b"a different system prompt"), self.turn.challenge_handle))
        self.assertEqual(self.refuse(self.final_request(session_id, 1)),
                         "handle_not_challenge")

    def test_publish_divergent_when_the_store_refuses_the_publish(self):
        def divergent(data):
            raise RuntimeError("content-address collision: stored bytes differ")

        session_id = self.open_session("system", SYSTEM_BYTES)
        self.send_all_chunks(session_id, SYSTEM_BYTES)
        self.assertEqual(
            self.refuse(self.final_request(session_id, 1), publish=divergent),
            "publish_divergent")

    def test_retry_conflict_when_a_published_session_is_finaled_at_a_different_cursor(self):
        session_id, reply = self.upload("system", SYSTEM_BYTES)
        self.assertEqual(reply["status"], "published")
        self.assertEqual(self.refuse(self.final_request(session_id, 0)), "retry_conflict")

    def test_session_corrupt_when_a_chunk_file_vanished_before_the_final(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.send_all_chunks(session_id, HISTORY_BYTES)
        (self.session_dir(session_id) / "1.chunk").unlink()
        self.assertEqual(self.refuse(self.final_request(session_id, 2)), "session_corrupt")

    def test_session_corrupt_when_a_chunk_file_no_longer_hashes_to_its_record(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.send_all_chunks(session_id, HISTORY_BYTES)
        path = self.session_dir(session_id) / "1.chunk"
        rotted = bytearray(path.read_bytes())
        rotted[0] ^= 0xFF
        path.write_bytes(bytes(rotted))
        self.assertEqual(self.refuse(self.final_request(session_id, 2)), "session_corrupt")
        self.assertEqual(self.session_row(session_id)["state"], gsl.SESSION_CORRUPT)

    def test_malformed_on_shape_violations(self):
        session_id = self.open_session("system", SYSTEM_BYTES)
        base = self.final_request(session_id, 1)
        for body in (dict(base, extra="x"),
                     dict(base, seq="1"),
                     dict(base, seq=-1),
                     dict(base, seq=True),
                     dict(base, staging_session_id=""),
                     {"protocol": gsu.STAGING_FINAL_PROTOCOL, "seq": 0}):
            with self.subTest(body=sorted((k, repr(v)) for k, v in body.items())):
                self.assertEqual(self.refuse(body), "malformed")

    def test_malformed_on_a_foreign_protocol_const(self):
        session_id = self.open_session("system", SYSTEM_BYTES)
        reply = gsu.handle_staging_final(
            dict(self.final_request(session_id, 1), protocol="brops.other.v1"),
            peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID, conn=self.conn,
            publish_artifact=self.store.publish, clock_ms=lambda: self.clock)
        self.assertEqual(reply["reason"], "malformed")

    def test_peer_denied_is_answered_inside_the_closed_set(self):
        """§4.10(b)/(c) publish no `peer_denied`, so a message from a principal that may not
        send it is answered `malformed` rather than with a reason outside the set. The front
        door refuses such a peer before a handler is ever reached."""
        session_id = self.open_session("system", SYSTEM_BYTES)
        self.assertEqual(self.refuse(self.final_request(session_id, 1), peer_uid=BROKER_UID),
                         "malformed")
        reply = self.call(self.chunk_request(session_id, 0, b"x"), peer_uid=BROKER_UID)
        self.assertEqual(reply["reason"], "malformed")

    def test_the_closed_reason_set_is_exactly_the_one_the_design_enumerates(self):
        self.assertEqual(
            sorted(gsu.STAGING_FINAL_REFUSAL_REASONS),
            sorted(["session_unknown", "seq_mismatch", "len_mismatch", "sha_mismatch",
                    "handle_not_challenge", "publish_divergent", "retry_conflict",
                    "session_corrupt", "malformed"]))


# ---------------------------------------------------------------------------
# Idempotency — a lost reply is always safe to retry (P1-6)
# ---------------------------------------------------------------------------


class IdempotencyTests(_Case):
    def test_an_identical_reopen_returns_the_same_session_and_the_current_cursor(self):
        first = self.call(self.open_request("history", data=HISTORY_BYTES))
        session_id = first["staging_session_id"]
        self.assertEqual(first["next_seq"], 0)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))

        second = self.call(self.open_request("history", data=HISTORY_BYTES))
        self.assertEqual(second["staging_session_id"], session_id)
        self.assertEqual(second["next_seq"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM governed_turn_staging_session").fetchone()["n"], 1)

    def test_a_reopen_never_creates_a_second_session_directory(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        for _ in range(3):
            self.call(self.open_request("history", data=HISTORY_BYTES))
        self.assertEqual(sorted(p.name for p in self.staging_root.iterdir()), [session_id])

    def test_a_replayed_chunk_acks_without_re_appending(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        before = self.session_row(session_id)
        for _ in range(3):
            reply = self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
            self.assertEqual(reply["status"], "ack")
            self.assertEqual(reply["next_seq"], 1)
        after = self.session_row(session_id)
        self.assertEqual(after["next_seq"], before["next_seq"])
        self.assertEqual(after["byte_count"], before["byte_count"])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM governed_turn_staging_chunk").fetchone()["n"], 1)

    def test_an_identical_final_retry_re_returns_the_same_reply(self):
        session_id, first = self.upload("system", SYSTEM_BYTES)
        cursor = self.session_row(session_id)["next_seq"]
        for _ in range(3):
            self.assertEqual(self.call(self.final_request(session_id, cursor)), first)
        self.assertEqual(len(self.store.blobs), 1)

    def test_the_published_handle_is_recorded_once_and_never_rewritten(self):
        session_id, _reply = self.upload("system", SYSTEM_BYTES)
        row = self.session_row(session_id)
        self.assertEqual(row["state"], gsl.ARTIFACT_READY)
        self.assertEqual(row["published_handle"], sha(SYSTEM_BYTES))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.conn.execute(
                "UPDATE governed_turn_staging_session SET published_handle = ?"
                " WHERE staging_session_id = ?", ("9" * 64, session_id))
        self.assertIn("binding is immutable", str(ctx.exception))



# ---------------------------------------------------------------------------
# §2.4 crash / corruption reconciliation, driven against real files
# ---------------------------------------------------------------------------


class CrashRecoveryTests(_Case):
    def test_rule_a_a_durable_chunk_with_no_db_row_is_adopted_by_an_identical_retry(self):
        """Crash between the dir fsync (step 6) and the DB commit (step 11): the file is
        there, the cursor is not. The byte-identical retry ADOPTS it — same file, no
        rewrite — and only then does the cursor move."""
        session_id = self.open_session("history", HISTORY_BYTES)
        directory = self.session_dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "0.chunk").write_bytes(HISTORY_BYTES[:CHUNK])
        inode_before = (directory / "0.chunk").stat().st_size

        reply = self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        self.assertEqual(reply["status"], "ack")
        self.assertEqual(reply["next_seq"], 1)
        self.assertEqual((directory / "0.chunk").stat().st_size, inode_before)
        self.assertEqual(self.session_row(session_id)["byte_count"], CHUNK)

        # …and the adopted chunk assembles into the real artifact.
        self.call(self.chunk_request(session_id, 1, HISTORY_BYTES[CHUNK:]))
        self.assertEqual(
            self.call(self.final_request(session_id, 2))["handle"], sha(HISTORY_BYTES))

    def test_rule_b_a_lost_chunk_file_makes_the_session_terminally_corrupt(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        (self.session_dir(session_id) / "0.chunk").unlink()
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        self.assertEqual(self.session_row(session_id)["state"], gsl.SESSION_CORRUPT)

    def test_rule_c_both_present_and_matching_is_an_idempotent_ack(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        reply = self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        self.assertEqual((reply["status"], reply["next_seq"]), ("ack", 1))

    def test_the_session_corrupt_contract_closes_every_later_message(self):
        """§2.4 P1-4, LOCKED: once corrupt, EVERY later open / chunk / final for the session
        (or its `(challenge_handle, artifact)`) returns `session_corrupt`, and the supervisor
        never finalizes, publishes or advances the turn."""
        session_id = self.open_session("history", HISTORY_BYTES)
        self.send_all_chunks(session_id, HISTORY_BYTES)
        (self.session_dir(session_id) / "0.chunk").unlink()
        self.call(self.final_request(session_id, 2))     # detects it

        self.assertEqual(self.session_row(session_id)["state"], gsl.SESSION_CORRUPT)
        self.assertEqual(
            self.call(self.open_request("history", data=HISTORY_BYTES))["reason"],
            "session_corrupt")
        self.assertEqual(
            self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))["reason"],
            "session_corrupt")
        self.assertEqual(
            self.call(self.final_request(session_id, 2))["reason"], "session_corrupt")
        # …including a chunk AT the cursor, which without the explicit corrupt gate would
        # be answered `seq_mismatch` — a refusal, but the wrong one, and one that invites a
        # retry the session can never satisfy.
        self.assertEqual(
            self.call(self.chunk_request(session_id, 2, b"x"))["reason"], "session_corrupt")
        self.assertEqual(self.store.blobs, {})
        self.assertIsNone(self.turn_row()["history_handle"])
        self.assertEqual(self.turn_row()["state"], gsl.UPLOADING)

    def test_a_corrupt_session_never_publishes_even_if_its_files_come_back(self):
        """§2.4, LOCKED: a `SESSION_CORRUPT` artifact can never contribute to an accepted
        turn. Restoring the byte-identical chunk file afterwards must NOT resurrect it —
        recovery is operator-sweep only, and a session that repaired itself would be a
        session whose ACKed prefix nobody can vouch for."""
        session_id = self.open_session("history", HISTORY_BYTES)
        self.send_all_chunks(session_id, HISTORY_BYTES)
        path = self.session_dir(session_id) / "1.chunk"
        saved = path.read_bytes()
        path.unlink()
        self.assertEqual(self.call(self.final_request(session_id, 2))["reason"],
                         "session_corrupt")

        path.write_bytes(saved)      # every byte back exactly where it was
        self.assertEqual(self.call(self.final_request(session_id, 2))["reason"],
                         "session_corrupt")
        self.assertEqual(self.store.blobs, {})
        self.assertIsNone(self.turn_row()["history_handle"])

    def test_a_published_session_accepts_no_further_chunks(self):
        """An ARTIFACT_READY session's cursor is final. Without the explicit gate a chunk at
        the cursor would be judged on its LENGTH (`over_declared`), which reads as "send a
        smaller one" — an invitation to append to a published artifact."""
        session_id, _reply = self.upload("system", SYSTEM_BYTES)
        cursor = self.session_row(session_id)["next_seq"]
        self.assertEqual(
            self.call(self.chunk_request(session_id, cursor, b"more"))["reason"],
            "seq_mismatch")
        self.assertEqual(self.session_row(session_id)["next_seq"], cursor)

    def test_a_corrupt_session_is_never_silently_re_created(self):
        session_id = self.open_session("history", HISTORY_BYTES)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        (self.session_dir(session_id) / "0.chunk").unlink()
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        self.call(self.open_request("history", data=HISTORY_BYTES))
        rows = self.conn.execute(
            "SELECT staging_session_id, state FROM governed_turn_staging_session").fetchall()
        self.assertEqual([(r["staging_session_id"], r["state"]) for r in rows],
                         [(session_id, gsl.SESSION_CORRUPT)])

    def test_the_sweep_may_remove_a_corrupt_session_without_touching_the_turn(self):
        """§2.4: recovery is operator-swept, and the sweep does NOT consume the challenge
        nonce — so the desktop can re-issue against the still-valid signed challenge. The
        sweep itself is a later ordered piece and is NOT IMPLEMENTED; what is proved here is
        that the DDL leaves the door open for it."""
        session_id = self.open_session("history", HISTORY_BYTES)
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))
        (self.session_dir(session_id) / "0.chunk").unlink()
        self.call(self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK]))

        self.conn.execute("DELETE FROM governed_turn_staging_session"
                          " WHERE staging_session_id = ?", (session_id,))
        self.conn.commit()
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM governed_turn_staging_chunk").fetchone()["n"], 0)
        self.assertEqual(self.turn_row()["state"], gsl.UPLOADING)
        # A fresh session against the SAME challenge is then possible again.
        self.assertEqual(
            self.call(self.open_request("history", data=HISTORY_BYTES))["status"], "opened")


# ---------------------------------------------------------------------------
# The deterministic chunk length and the two size caps
# ---------------------------------------------------------------------------


class DeterministicChunkingTests(_Case):
    def test_expected_chunk_len_is_full_until_the_remainder(self):
        self.assertEqual(gsu.expected_chunk_len(3 * CHUNK, 0), CHUNK)
        self.assertEqual(gsu.expected_chunk_len(3 * CHUNK, CHUNK), CHUNK)
        self.assertEqual(gsu.expected_chunk_len(3 * CHUNK + 5, 3 * CHUNK), 5)
        self.assertEqual(gsu.expected_chunk_len(0, 0), 0)

    def test_the_chunk_count_is_a_function_of_the_declaration(self):
        self.assertEqual(gsu.n_chunks(0), 0)
        self.assertEqual(gsu.n_chunks(1), 1)
        self.assertEqual(gsu.n_chunks(CHUNK), 1)
        self.assertEqual(gsu.n_chunks(CHUNK + 1), 2)
        self.assertEqual(gsu.n_chunks(gsu.ARTIFACT_CEILINGS["history"]),
                         gsl.MAX_STAGING_CHUNKS)

    def test_the_worst_case_artifact_fits_the_cardinality_cap_with_room_to_spare(self):
        """46 = ceil(8 MiB / 184320) is the cap, and the 8 MiB history ceiling is what
        produces it. The two are NOT the same number: 46 full chunks hold 8478720 bytes, so
        the cap has 90112 bytes of slack above the largest artifact the design permits. The
        cap therefore binds only because the CEILING binds first — worth stating, because a
        future ceiling raised past 8478720 would need 47 and the `next_seq <= 46` CHECK
        would (correctly, fail-closed) start refusing legal uploads."""
        self.assertEqual(gsu.n_chunks(8388608), 46)
        self.assertEqual(gsu.n_chunks(46 * CHUNK), 46)
        self.assertEqual(gsu.n_chunks(46 * CHUNK + 1), 47)
        self.assertEqual(46 * CHUNK - gsu.ARTIFACT_CEILINGS["history"], 90112)

    def test_the_per_turn_and_per_install_file_counts_are_the_derived_ones(self):
        per_turn = sum(gsu.n_chunks(c) for c in gsu.ARTIFACT_CEILINGS.values())
        self.assertEqual(per_turn, gsl.MAX_STAGING_FILES_PER_TURN)
        self.assertEqual(per_turn * gsl.MAX_CONCURRENT_GOVERNED_TURNS,
                         gsl.MAX_STAGING_FILES_PER_INSTALL)
        self.assertEqual(gsu.MAX_TURN_UPLOAD_BYTES * gsl.MAX_CONCURRENT_GOVERNED_TURNS,
                         17_432_576)
        self.assertLessEqual(gsu.MAX_TURN_UPLOAD_BYTES * gsl.MAX_CONCURRENT_GOVERNED_TURNS,
                             gsl.MAX_STAGING_BYTES_PER_INSTALL)

    def test_the_frame_sizing_proof(self):
        """§2.4 P1-4: a 184320-byte chunk encodes to 245760 base64url bytes; plus the JSON
        envelope it stays under 262144 with headroom. A 262144-byte chunk does not."""
        self.assertEqual(len(b64(b"z" * CHUNK)), 4 * ((CHUNK + 2) // 3))
        self.assertEqual(len(b64(b"z" * CHUNK)), 245760)
        # The WORST case the design bounds: a 128-char session id and a two-digit seq.
        # `encode_frame` returns the u32 length prefix + the body, and every cap in §2.4 is
        # stated "body-only" — so the prefix comes off before the comparison.
        worst = encode_frame(self.chunk_request("s" * 128, 45, b"z" * CHUNK))[4:]
        self.assertEqual(len(worst), 245982)
        self.assertLess(len(worst), gsu.MAX_STAGING_CHUNK_FRAME_BYTES)
        # §2.4 P1-4 states the worst-case frame as "≤ 245963 (≥ 16 KiB headroom)". The real
        # compact envelope is 222 bytes, not the "~203" the design estimates, so the true
        # worst case is 245982 and the headroom is 16162 bytes = 15.78 KiB. The design's
        # CONCLUSION holds with room to spare; only its two intermediate numbers are a
        # little optimistic, and this test records the measured ones rather than the quoted.
        self.assertEqual(gsu.MAX_STAGING_CHUNK_FRAME_BYTES - len(worst), 16162)
        self.assertGreater(len(b64(b"z" * 262144)), gsu.MAX_STAGING_CHUNK_FRAME_BYTES)

    def test_an_exact_max_chunk_is_accepted(self):
        data = bytes((i * 13) % 256 for i in range(CHUNK)) * 1
        turn = self.new_turn(nonce="nonce-exact", history=data)
        session_id = self.open_session("history", data, turn=turn)
        reply = self.call(self.chunk_request(session_id, 0, data))
        self.assertEqual((reply["status"], reply["next_seq"]), ("ack", 1))
        self.assertEqual(self.call(self.final_request(session_id, 1))["handle"], sha(data))

    def test_a_full_46_chunk_history_uploads_and_publishes(self):
        """The worst case the design bounds, driven end to end: 45 full chunks and one
        remainder, every file immutable, the digest recomputed from byte zero."""
        data = bytes((i * 31 + 7) % 256 for i in range(gsu.ARTIFACT_CEILINGS["history"]))
        turn = self.new_turn(nonce="nonce-max", history=data)
        session_id = self.open_session("history", data, turn=turn)
        self.assertEqual(self.send_all_chunks(session_id, data), 46)
        row = self.session_row(session_id)
        self.assertEqual((row["next_seq"], row["byte_count"]), (46, len(data)))
        self.assertEqual(
            self.call(self.final_request(session_id, 46))["handle"], sha(data))
        self.assertEqual(len(list(self.session_dir(session_id).iterdir())), 46)


# ---------------------------------------------------------------------------
# What the DATABASE forbids — raw SQL, every Python guard bypassed
# ---------------------------------------------------------------------------


class SessionDdlTests(_Case):
    """Each rule proved SEPARATELY, because together they mask each other.

    That is not a stylistic preference: three of §4.10(a0)'s checks turned out to be masked
    by other checks and only showed up under isolation. A trigger that never fires because
    another one fires first is indistinguishable from a trigger that is not there.
    """

    def bare(self):
        """A fresh in-memory DB from the canonical DDL, so triggers can be dropped one at a
        time without disturbing the real ledger."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.executescript(
            (ROOT / "runtime" / "supervisor_ledger.sql").read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO governed_turn_staging (install_id, request_nonce, challenge_handle,"
            " run_id, task_id, workspace_id, system_sha256, history_sha256,"
            " generation_config_sha256, state, challenge_expires_at_ms, created_at_ms,"
            " updated_at_ms) VALUES ('i','n',?,'r','t','w',?,?,?,'VERIFYING',1,1,1)",
            ("d" * 64, "a" * 64, "b" * 64, "c" * 64))
        conn.execute("UPDATE governed_turn_staging SET state = 'UPLOADING'")
        return conn

    def insert_session(self, conn, **overrides):
        row = {"staging_session_id": "s1", "challenge_handle": "d" * 64,
               "artifact": "system", "declared_len": 3 * CHUNK,
               "declared_sha256": "e" * 64, "next_seq": 0, "byte_count": 0,
               "session_dir": "/tmp/s1", "state": "UPLOADING", "published_handle": None}
        row.update(overrides)
        conn.execute(
            "INSERT INTO governed_turn_staging_session (staging_session_id, challenge_handle,"
            " artifact, declared_len, declared_sha256, next_seq, byte_count, session_dir,"
            " state, published_handle) VALUES (?,?,?,?,?,?,?,?,?,?)",
            tuple(row[k] for k in ("staging_session_id", "challenge_handle", "artifact",
                                   "declared_len", "declared_sha256", "next_seq",
                                   "byte_count", "session_dir", "state",
                                   "published_handle")))

    # ---- creation ----------------------------------------------------------
    def test_a_session_may_only_be_created_empty_and_uploading(self):
        for field, value in (("state", "ARTIFACT_READY"), ("state", "SESSION_CORRUPT"),
                             ("next_seq", 1), ("byte_count", 1),
                             ("published_handle", "f" * 64)):
            with self.subTest(field=field, value=value):
                conn = self.bare()
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_session(conn, **{field: value})
                self.assertIn("must be created empty and UPLOADING", str(ctx.exception))

    def test_the_artifact_domain_is_closed_by_a_check_constraint(self):
        conn = self.bare()
        for artifact in ("policy_bundle", "output", "System"):
            with self.subTest(artifact=artifact):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_session(conn, staging_session_id="s-" + artifact,
                                        artifact=artifact)
                self.assertIn("CHECK constraint failed", str(ctx.exception))

    def test_a_session_cannot_name_a_challenge_the_supervisor_never_opened(self):
        conn = self.bare()
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_session(conn, challenge_handle="9" * 64)
        self.assertIn("FOREIGN KEY", str(ctx.exception).upper())

    def test_declared_len_and_the_cursor_are_bounded_by_check_constraints(self):
        """Proved with the insert trigger DROPPED. With it in place a non-zero `next_seq` is
        refused for being non-empty and the CHECK is never consulted — so the test would
        pass even if the bound were deleted."""
        for field, value in (("declared_len", -1), ("declared_len", 8388609),
                             ("next_seq", -1), ("next_seq", 47)):
            with self.subTest(field=field, value=value):
                conn = self.bare()
                conn.execute("DROP TRIGGER trg_governed_turn_staging_session_insert_state")
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_session(conn, **{field: value})
                self.assertIn("CHECK", str(ctx.exception))

    def test_byte_count_may_never_exceed_declared_len(self):
        conn = self.bare()
        conn.execute("DROP TRIGGER trg_governed_turn_staging_session_insert_state")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_session(conn, declared_len=10, byte_count=11)
        self.assertIn("CHECK", str(ctx.exception))

    def test_one_session_per_challenge_and_artifact(self):
        conn = self.bare()
        self.insert_session(conn)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_session(conn, staging_session_id="s2")
        self.assertIn("UNIQUE", str(ctx.exception).upper())

    # ---- lifecycle ---------------------------------------------------------
    def test_the_legal_session_edges_are_permitted(self):
        for target in ("ARTIFACT_READY", "SESSION_CORRUPT"):
            with self.subTest(target=target):
                conn = self.bare()
                self.insert_session(conn)
                conn.execute("UPDATE governed_turn_staging_session SET state = ?", (target,))
                self.assertEqual(
                    conn.execute("SELECT state FROM governed_turn_staging_session"
                                 ).fetchone()["state"], target)

    def test_neither_terminal_session_state_has_a_way_back_out(self):
        for terminal in ("ARTIFACT_READY", "SESSION_CORRUPT"):
            for target in ("UPLOADING", "ARTIFACT_READY", "SESSION_CORRUPT"):
                if target == terminal:
                    continue
                with self.subTest(terminal=terminal, target=target):
                    conn = self.bare()
                    self.insert_session(conn)
                    conn.execute("UPDATE governed_turn_staging_session SET state = ?",
                                 (terminal,))
                    with self.assertRaises(sqlite3.IntegrityError) as ctx:
                        conn.execute("UPDATE governed_turn_staging_session SET state = ?",
                                     (target,))
                    self.assertIn("illegal staging session state transition",
                                  str(ctx.exception))

    def test_the_session_state_domain_holds_with_the_triggers_dropped(self):
        conn = self.bare()
        conn.execute("DROP TRIGGER trg_governed_turn_staging_session_insert_state")
        conn.execute("DROP TRIGGER trg_governed_turn_staging_session_transition")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_session(conn, state="FINISHED")
        self.assertIn("CHECK constraint failed", str(ctx.exception))

    # ---- the cursor rule ---------------------------------------------------
    def advance(self, conn, next_seq, byte_count):
        conn.execute(
            "UPDATE governed_turn_staging_session SET next_seq = ?, byte_count = ?",
            (next_seq, byte_count))

    def record(self, conn, seq, length):
        conn.execute(
            "INSERT INTO governed_turn_staging_chunk (staging_session_id, seq,"
            " chunk_sha256, chunk_len) VALUES ('s1',?,?,?)", (seq, "a" * 64, length))

    def test_the_cursor_advances_by_exactly_one_recorded_chunk(self):
        conn = self.bare()
        self.insert_session(conn)
        self.record(conn, 0, CHUNK)
        self.advance(conn, 1, CHUNK)
        row = conn.execute("SELECT * FROM governed_turn_staging_session").fetchone()
        self.assertEqual((row["next_seq"], row["byte_count"]), (1, CHUNK))

    def test_the_cursor_may_not_advance_without_a_recorded_chunk(self):
        conn = self.bare()
        self.insert_session(conn)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.advance(conn, 1, CHUNK)
        self.assertIn("advance by exactly one recorded chunk", str(ctx.exception))

    def test_the_cursor_may_not_skip_a_seq(self):
        conn = self.bare()
        self.insert_session(conn)
        self.record(conn, 0, CHUNK)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.advance(conn, 2, 2 * CHUNK)
        self.assertIn("advance by exactly one recorded chunk", str(ctx.exception))

    def test_the_byte_count_may_not_disagree_with_the_recorded_chunk(self):
        conn = self.bare()
        self.insert_session(conn)
        self.record(conn, 0, CHUNK)
        for wrong in (0, CHUNK - 1, CHUNK + 1):
            with self.subTest(byte_count=wrong):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.advance(conn, 1, wrong)
                self.assertIn("advance by exactly one recorded chunk", str(ctx.exception))

    def test_the_cursor_may_not_skip_a_seq_even_with_the_right_byte_count(self):
        """Isolates the `next_seq = OLD.next_seq + 1` half of the cursor rule. The skip test
        above supplies a byte count that is ALSO wrong, so it would still fail with the seq
        step deleted — mutation testing found exactly that. Here the byte count is the
        correct one for the recorded chunk, so only the seq step can refuse."""
        conn = self.bare()
        self.insert_session(conn)
        self.record(conn, 0, CHUNK)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.advance(conn, 2, CHUNK)
        self.assertIn("advance by exactly one recorded chunk", str(ctx.exception))

    def test_the_cursor_may_not_rewind(self):
        conn = self.bare()
        self.insert_session(conn)
        self.record(conn, 0, CHUNK)
        self.advance(conn, 1, CHUNK)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.advance(conn, 0, 0)
        self.assertIn("advance by exactly one recorded chunk", str(ctx.exception))

    def test_byte_count_is_provably_the_sum_of_the_recorded_chunks(self):
        conn = self.bare()
        self.insert_session(conn)
        for seq, length in ((0, CHUNK), (1, CHUNK), (2, 17)):
            self.record(conn, seq, length)
            self.advance(conn, seq + 1,
                         conn.execute("SELECT byte_count AS b FROM"
                                      " governed_turn_staging_session").fetchone()["b"] + length)
        row = conn.execute("SELECT * FROM governed_turn_staging_session").fetchone()
        total = conn.execute("SELECT SUM(chunk_len) AS s, COUNT(*) AS c"
                             " FROM governed_turn_staging_chunk").fetchone()
        self.assertEqual(row["byte_count"], total["s"])
        self.assertEqual(row["next_seq"], total["c"])

    # ---- chunk rows --------------------------------------------------------
    def test_a_chunk_may_only_be_recorded_at_the_cursor(self):
        conn = self.bare()
        self.insert_session(conn)
        for seq in (1, 2, 45):
            with self.subTest(seq=seq):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.record(conn, seq, CHUNK)
                self.assertIn("must be recorded at the current cursor", str(ctx.exception))

    def test_a_chunk_for_an_unknown_session_is_refused_by_the_gapless_trigger(self):
        conn = self.bare()
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.record(conn, 0, CHUNK)
        self.assertIn("must be recorded at the current cursor", str(ctx.exception))

    def test_a_recorded_chunk_can_never_be_updated(self):
        conn = self.bare()
        self.insert_session(conn)
        self.record(conn, 0, CHUNK)
        for column, value in (("chunk_len", 1), ("chunk_sha256", "f" * 64), ("seq", 4)):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute("UPDATE governed_turn_staging_chunk SET %s = ?" % column,
                                 (value,))
                self.assertIn("recorded staging chunks are immutable", str(ctx.exception))

    def test_a_second_chunk_at_a_recorded_seq_is_refused_by_the_primary_key(self):
        conn = self.bare()
        conn.execute("DROP TRIGGER trg_governed_turn_staging_chunk_gapless")
        self.insert_session(conn)
        self.record(conn, 0, CHUNK)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.record(conn, 0, CHUNK)
        self.assertIn("UNIQUE", str(ctx.exception).upper())

    def test_a_zero_length_or_oversize_chunk_row_is_refused_by_a_check(self):
        conn = self.bare()
        self.insert_session(conn)
        for length in (0, -1, CHUNK + 1):
            with self.subTest(length=length):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.record(conn, 0, length)
                self.assertIn("CHECK", str(ctx.exception))

    def test_a_chunk_seq_above_45_is_refused_by_a_check(self):
        conn = self.bare()
        conn.execute("DROP TRIGGER trg_governed_turn_staging_chunk_gapless")
        self.insert_session(conn)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.record(conn, 46, CHUNK)
        self.assertIn("CHECK", str(ctx.exception))

    # ---- immutable session binding ----------------------------------------
    def test_the_session_binding_is_immutable_in_the_database(self):
        conn = self.bare()
        self.insert_session(conn)
        for column, value in (("staging_session_id", "s9"), ("challenge_handle", "d" * 64 + ""),
                              ("artifact", "history"), ("declared_len", 5),
                              ("declared_sha256", "9" * 64), ("session_dir", "/tmp/other")):
            if column == "challenge_handle":
                value = "1" * 64
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute("UPDATE governed_turn_staging_session SET %s = ?" % column,
                                 (value,))
                self.assertIn("binding is immutable", str(ctx.exception))

    def test_a_published_handle_is_write_once(self):
        conn = self.bare()
        self.insert_session(conn)
        conn.execute("UPDATE governed_turn_staging_session SET published_handle = ?",
                     ("a" * 64,))
        for value in ("b" * 64, None):
            with self.subTest(value=value):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute(
                        "UPDATE governed_turn_staging_session SET published_handle = ?",
                        (value,))
                self.assertIn("binding is immutable", str(ctx.exception))

    # ---- the turn's published input handles --------------------------------
    def test_a_published_input_handle_must_be_the_challenge_committed_digest(self):
        conn = self.bare()
        for column, digest in (("system_handle", "a" * 64), ("history_handle", "b" * 64),
                               ("generation_config_handle", "c" * 64)):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute("UPDATE governed_turn_staging SET %s = ?" % column,
                                 ("9" * 64,))
                self.assertIn("must be the challenge-committed digest", str(ctx.exception))
                conn.execute("UPDATE governed_turn_staging SET %s = ?" % column, (digest,))

    def test_a_published_input_handle_is_write_once(self):
        conn = self.bare()
        conn.execute("UPDATE governed_turn_staging SET system_handle = system_sha256")
        for value in (None, "9" * 64):
            with self.subTest(value=value):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute("UPDATE governed_turn_staging SET system_handle = ?",
                                 (value,))
                self.assertIn("must be the challenge-committed digest", str(ctx.exception))

    def test_inputs_ready_is_unreachable_until_all_three_handles_are_published(self):
        conn = self.bare()
        for column in ("system_handle", "history_handle"):
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                conn.execute("UPDATE governed_turn_staging SET state = 'INPUTS_READY'")
            self.assertIn("requires all three published input handles", str(ctx.exception))
            conn.execute("UPDATE governed_turn_staging SET %s = %s"
                         % (column, column.replace("_handle", "_sha256")))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE governed_turn_staging SET state = 'INPUTS_READY'")
        conn.execute("UPDATE governed_turn_staging SET generation_config_handle"
                     " = generation_config_sha256")
        conn.execute("UPDATE governed_turn_staging SET state = 'INPUTS_READY'")
        self.assertEqual(
            conn.execute("SELECT state FROM governed_turn_staging").fetchone()["state"],
            "INPUTS_READY")

    def test_an_inputs_ready_row_provably_carries_the_challenge_digests(self):
        """The property §4.10(d) reads off this state: it holds because of the two triggers
        together, not because anything asserted it."""
        for artifact, data in (("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
                               ("generation_config", GENCFG_BYTES)):
            self.upload(artifact, data)
        row = self.turn_row()
        self.assertEqual(row["state"], gsl.INPUTS_READY)
        for artifact in gsl.STAGING_ARTIFACTS:
            self.assertEqual(row[gsl.ARTIFACT_HANDLE_COLUMN[artifact]],
                             row[gsl.ARTIFACT_DIGEST_COLUMN[artifact]])


# ---------------------------------------------------------------------------
# The front door
# ---------------------------------------------------------------------------


class LedgerContractTests(_Case):
    """The ledger's own guards, exercised where the protocol layer cannot mask them.

    Each of these was a mutation-test SURVIVOR: the handler checks the same thing first, so
    deleting the ledger's guard changed no wire verdict. They still have to hold, because
    the ledger is also the unit a future caller will use without going through a wire
    message at all — the §2.4 sweep, a recovery pass, or the §4.10(d) gate.
    """

    def test_record_chunk_re_checks_the_cursor_inside_its_own_transaction(self):
        """Steps 1-6 of §2.4 run outside any lock, so the cursor can move under them. The
        re-check inside `BEGIN IMMEDIATE` is what stops two senders both believing they
        filled the same seq — and it must raise the typed `Conflict`, not fall through to
        the DDL and surface as a raw integrity error."""
        session_id = self.open_session("history", HISTORY_BYTES)
        digest, length = sha(HISTORY_BYTES[:CHUNK]), CHUNK
        gsl.record_chunk(self.conn, session_id, 0, digest, length)
        with self.assertRaises(gsl.Conflict):
            gsl.record_chunk(self.conn, session_id, 0, digest, length)
        self.assertEqual(self.session_row(session_id)["next_seq"], 1)
        self.assertEqual(self.session_row(session_id)["byte_count"], CHUNK)

    def test_record_chunk_never_lets_a_raw_integrity_error_escape(self):
        """If the cursor check and the DDL ever disagree, the result must still be a typed
        ledger error the front door knows how to answer — a `sqlite3.IntegrityError` is
        caught by nothing above this layer and would escape the connection handler."""
        session_id = self.open_session("history", HISTORY_BYTES)
        self.conn.execute("DROP TRIGGER trg_governed_turn_staging_session_cursor")
        gsl.record_chunk(self.conn, session_id, 0, sha(HISTORY_BYTES[:CHUNK]), CHUNK)
        self.conn.execute(
            "UPDATE governed_turn_staging_session SET next_seq = 0 WHERE staging_session_id = ?",
            (session_id,))
        with self.assertRaises(gsl.LedgerError) as ctx:
            gsl.record_chunk(self.conn, session_id, 0, sha(b"other"), 5)
        self.assertNotIsInstance(ctx.exception, gsl.Conflict)
        self.assertIsInstance(ctx.exception, gsl.Corrupt)

    def test_finalize_session_refuses_a_session_that_is_not_uploading(self):
        session_id, _reply = self.upload("system", SYSTEM_BYTES)
        self.assertEqual(self.session_row(session_id)["state"], gsl.ARTIFACT_READY)
        with self.assertRaises(gsl.IllegalTransition):
            gsl.finalize_session(self.conn, session_id, sha(SYSTEM_BYTES), NOW)

    def test_a_session_state_outside_the_closed_domain_is_refused_not_interpreted(self):
        """A stored state the supervisor cannot interpret must not be treated as the one it
        happens to resemble. Reached by building the table WITHOUT its CHECK — the CHECK is
        what makes this unreachable in a real ledger, and that is the point of proving the
        code-side guard separately."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute(
            "CREATE TABLE governed_turn_staging_session ("
            " staging_session_id TEXT PRIMARY KEY, challenge_handle TEXT, artifact TEXT,"
            " declared_len INTEGER, declared_sha256 TEXT, next_seq INTEGER,"
            " byte_count INTEGER, session_dir TEXT, state TEXT, published_handle TEXT)")
        conn.execute(
            "INSERT INTO governed_turn_staging_session VALUES"
            " ('s1',?, 'system', 0, ?, 0, 0, '/tmp/s1', 'FINISHED', NULL)",
            ("d" * 64, "e" * 64))
        with self.assertRaises(gsl.Corrupt):
            gsl.load_session(conn, "s1")
        with self.assertRaises(gsl.Corrupt):
            gsl.load_session_for_artifact(conn, "d" * 64, "system")


class _Conn:
    """A framed connection stand-in: one request in, one reply out.

    ``raw`` lets a test send bytes that are NOT the compact serialization of ``body`` —
    which is the only way to show that the front door's frame cap is about what arrived on
    the wire and not about what the decoder made of it.
    """

    def __init__(self, peer_uid, body, raw=None):
        self.peer_uid = peer_uid
        payload = raw if raw is not None else json.dumps(
            body, separators=(",", ":")).encode("utf-8")
        self._inbox = len(payload).to_bytes(4, "big") + payload
        self.sent = bytearray()

    def recv_exactly(self, n):
        head, self._inbox = self._inbox[:n], self._inbox[n:]
        return head

    def send_all(self, data):
        self.sent.extend(data)

    def close(self):
        pass

    def reply(self):
        return json.loads(bytes(self.sent[4:]).decode("utf-8"))


class FrontDoorTests(_Case):
    def serve(self, body, *, peer_uid=SIDECAR_UID, staging_service=True):
        conn = _Conn(peer_uid, body)
        return gss.handle_connection(
            conn, BROKER_UID, None, None, None, lambda: self.clock,
            ledger_conn=self.conn,
            staging_service=self.service() if staging_service else None,
        )

    def test_the_sidecar_may_send_all_three_staging_protocols(self):
        opened = self.serve(self.open_request())
        self.assertEqual(opened["status"], "opened")
        session_id = opened["staging_session_id"]
        ack = self.serve(self.chunk_request(session_id, 0, SYSTEM_BYTES))
        self.assertEqual(ack["status"], "ack")
        published = self.serve(self.final_request(session_id, 1))
        self.assertEqual(published["status"], "published")

    def test_the_broker_sending_a_staging_protocol_is_not_authorized(self):
        self.assertEqual(
            self.serve(self.open_request(), peer_uid=BROKER_UID)["reason"], "peer_denied")

    def test_the_sidecar_may_still_not_send_an_op(self):
        self.assertEqual(
            self.serve({"op": "accept-open", "challenge_doc": {}}),
            {"ok": False, "error": "peer not authorized"})

    def test_without_a_staging_service_the_sidecar_is_not_admitted(self):
        self.assertEqual(
            self.serve(self.open_request(), staging_service=False),
            {"ok": False, "error": "peer not authorized"})

    def test_a_split_sidecar_principal_is_refused_outright(self):
        """Two services naming different sidecar uids would mean one principal may open
        turns and another may upload their inputs — a shape §2.6 does not describe."""
        import governed_turn_open as gto
        conn = _Conn(SIDECAR_UID, self.open_request())
        reply = gss.handle_connection(
            conn, BROKER_UID, None, None, None, lambda: self.clock,
            ledger_conn=self.conn,
            staging_service=self.service(),
            open_service=gto.OpenService(
                config=gto.OpenConfig(supervisor_id="s", registry_root_key_id="r",
                                      registry_root_public_key="k"),
                allowed_sidecar_uid=SIDECAR_UID + 1,
                publish_document=lambda b: "",
                resolve_registry_document=lambda: None,
                verify_root_sig=lambda *a: False,
                verify_challenge_sig=lambda *a: False,
            ),
        )
        self.assertIn("principal split", reply["error"])

    def test_a_chunk_frame_larger_than_the_broker_bound_is_still_read(self):
        """The broker's 8 KiB read bound cannot be the sidecar's: a legal chunk frame is
        240 KiB of base64url by design."""
        session_id = self.serve(
            self.open_request("history", data=HISTORY_BYTES))["staging_session_id"]
        body = self.chunk_request(session_id, 0, HISTORY_BYTES[:CHUNK])
        self.assertGreater(len(encode_frame(body)), gss.MAX_FRAME_BYTES)
        self.assertEqual(self.serve(body)["status"], "ack")

    def test_an_over_cap_control_frame_is_refused_at_the_door(self):
        """The transport had to read up to the CHUNK cap to reach a chunk at all, so a
        200 KiB `staging-open` would otherwise sail in on the chunk protocol's allowance.
        The tighter per-protocol caps are re-imposed on the bytes that actually arrived."""
        fat_open = self.open_request(install_id="i" * 100_000)
        self.assertGreater(len(encode_frame(fat_open)),
                           gsu.MAX_STAGING_CONTROL_FRAME_BYTES)
        self.assertLess(len(encode_frame(fat_open)), gsu.MAX_SIDECAR_FRAME_BYTES)
        self.assertEqual(self.serve(fat_open)["reason"], "malformed")

        fat_final = self.final_request("s" * 100_000, 0)
        self.assertEqual(self.serve(fat_final)["reason"], "malformed")

        # A full-size CHUNK frame on the same socket is not over ITS cap and gets a real
        # verdict — so the narrowing is per-protocol and not a blanket 4 KiB door.
        self.assertEqual(
            self.serve(self.chunk_request("s" * 43, 0, b"z" * CHUNK))["reason"],
            "session_unknown")

    def test_the_a0_open_frame_bound_survives_the_widening(self):
        """§4.10(a0) fixes its frame at 8 KiB. The sidecar's transport read is now 256 KiB
        for the chunk's sake, so that bound has to be re-applied per protocol or it would
        have been silently repealed."""
        import governed_turn_open as gto
        self.assertEqual(gsu.SIDECAR_FRAME_CAPS[gto.OPEN_PROTOCOL],
                         gto.MAX_OPEN_FRAME_BYTES)
        over = {"protocol": gto.OPEN_PROTOCOL, "install_id": "i", "request_nonce": "n",
                "challenge_doc_b64": "A" * 20_000}
        self.assertGreater(len(encode_frame(over)), gto.MAX_OPEN_FRAME_BYTES)
        reply = gsu.frame_cap_refusal(gto.OPEN_PROTOCOL, len(encode_frame(over)))
        self.assertEqual(reply["protocol"], gto.OPEN_RESULT_PROTOCOL)
        self.assertEqual(reply["reason"], "malformed")

    def test_a_frame_within_its_protocols_cap_is_not_refused(self):
        for protocol, cap in gsu.SIDECAR_FRAME_CAPS.items():
            with self.subTest(protocol=protocol):
                self.assertIsNone(gsu.frame_cap_refusal(protocol, cap))
                self.assertIsNotNone(gsu.frame_cap_refusal(protocol, cap + 1))
        self.assertIsNone(gsu.frame_cap_refusal("brops.unknown.v1", 10 ** 9))

    def test_a_frame_over_the_sidecar_read_bound_is_refused_by_the_transport(self):
        body = self.chunk_request("s" * 43, 0, b"z" * (300 * 1024))
        conn = _Conn(SIDECAR_UID, body)
        reply = gss.handle_connection(
            conn, BROKER_UID, None, None, None, lambda: self.clock,
            ledger_conn=self.conn, staging_service=self.service())
        self.assertFalse(reply["ok"])
        self.assertIn("exceeds bound", reply["error"])

    def test_the_frame_cap_is_about_the_bytes_that_arrived_not_the_decoded_shape(self):
        """A frame padded with 8 KiB of JSON whitespace decodes to a perfectly legal
        `staging-final` — every field in shape, every length inside its bound. Only a check
        on the RAW frame can refuse it, and refusing it is the point: the 4 KiB control
        bound is a transport budget, and a decoder that discards padding does not spend it.
        """
        session_id = self.open_session("system", SYSTEM_BYTES)
        self.send_all_chunks(session_id, SYSTEM_BYTES)
        body = self.final_request(session_id, 1)
        padded = json.dumps(body, indent=8192).encode("utf-8")
        self.assertGreater(len(padded), gsu.MAX_STAGING_CONTROL_FRAME_BYTES)
        self.assertEqual(json.loads(padded), body)      # decodes to the SAME legal request

        conn = _Conn(SIDECAR_UID, None, raw=padded)
        reply = gss.handle_connection(
            conn, BROKER_UID, None, None, None, lambda: self.clock,
            ledger_conn=self.conn, staging_service=self.service())
        self.assertEqual(reply["status"], "refused")
        self.assertEqual(reply["reason"], "malformed")
        # …and the compact form of the same request is served normally.
        self.assertEqual(self.serve(body)["status"], "published")

    def test_the_sidecar_protocol_set_is_exactly_six_names(self):
        """The sidecar's whole grant, written out. It was four names while staging was the
        end of the road, five when §4.10(d) added the execute/finalize trigger, and six since
        §4.10(f) added the output read — the only one of the six that carries anything OUT.
        This test is the reason widening the door has to be a deliberate edit."""
        self.assertEqual(
            sorted(gss.SIDECAR_PROTOCOLS),
            sorted(["brops.governed-turn-open.v1", "brops.governed-staging-open.v1",
                    "brops.governed-staging-chunk.v1", "brops.governed-staging-final.v1",
                    "brops.governed-evidence-request.v1",
                    "brops.governed-turn-output-read.v1"]))


# ---------------------------------------------------------------------------
# Supervisor-side faults are faults, never refusals
# ---------------------------------------------------------------------------


class StagingCustodyTests(_Case):
    """§2.4: the staging root and every `session_dir` are supervisor-only — "the
    sidecar/executor have no read" — which is STRICTER than the evidence store's own policy
    of a shared signer group. The difference is one parameter on one shared implementation,
    and it has to be exercised on every platform or it is a rule only Linux CI can see."""

    def test_the_owner_only_policy_forbids_group_as_well_as_other(self):
        import stat as _stat

        import brops_evidence_store as store
        self.assertEqual(store.posix_forbidden_mode(True), _stat.S_IRWXO)
        self.assertEqual(store.posix_forbidden_mode(False),
                         _stat.S_IRWXO | _stat.S_IRWXG)
        # The store keeps the looser policy; staging must not inherit it.
        self.assertNotEqual(store.posix_forbidden_mode(False),
                            store.posix_forbidden_mode(True))
        for bit in (_stat.S_IRGRP, _stat.S_IWGRP, _stat.S_IXGRP):
            self.assertTrue(store.posix_forbidden_mode(False) & bit)
            self.assertFalse(store.posix_forbidden_mode(True) & bit)

    def test_staging_directories_are_created_under_the_owner_only_policy(self):
        import brops_evidence_store as store
        seen = []
        original = store.harden_private_dir

        def spy(directory, *, allow_group=True):
            seen.append(allow_group)
            return original(directory, allow_group=allow_group)

        store.harden_private_dir = spy
        gsu.harden_private_dir = spy
        self.addCleanup(setattr, store, "harden_private_dir", original)
        self.addCleanup(setattr, gsu, "harden_private_dir", original)

        self.upload("system", SYSTEM_BYTES)
        self.assertTrue(seen)
        self.assertTrue(all(flag is False for flag in seen), seen)


class SupervisorFaultTests(_Case):
    def test_an_off_contract_refusal_reason_is_a_hard_error(self):
        for builder in (gsu.staging_open_refused, gsu.final_refused):
            with self.subTest(builder=builder.__name__):
                with self.assertRaises(SupervisorError):
                    builder("looks_plausible")
        with self.assertRaises(SupervisorError):
            gsu.chunk_refused("looks_plausible", 0)

    def test_a_reason_from_the_wrong_protocols_set_is_refused(self):
        with self.assertRaises(SupervisorError):
            gsu.staging_open_refused("oversize_chunk")
        with self.assertRaises(SupervisorError):
            gsu.chunk_refused("digest_mismatch", 0)
        with self.assertRaises(SupervisorError):
            gsu.final_refused("quota_bytes")

    def test_a_missing_ledger_connection_is_a_fault_not_a_refusal(self):
        for handler, request in (
            (gsu.handle_staging_open, self.open_request()),
            (gsu.handle_staging_chunk, self.chunk_request("s", 0, b"x")),
        ):
            with self.subTest(handler=handler.__name__):
                with self.assertRaises(SupervisorError):
                    handler(request, peer_uid=SIDECAR_UID,
                            allowed_sidecar_uid=SIDECAR_UID, conn=None,
                            **({"staging_root": self.staging_root}
                               if handler is gsu.handle_staging_open else {}))

    def test_a_session_id_that_is_not_base64url_is_a_supervisor_fault(self):
        """A session id NAMES A DIRECTORY. A minter that produced `../../etc` would place
        `session_dir` anywhere the supervisor can write, so this is refused as a fault
        rather than answered as if a peer had asked for it."""
        for bad in ("../escape", "a/b", "with space", "", "n" * 129, "nul\x00"):
            with self.subTest(bad=bad):
                with self.assertRaises(SupervisorError):
                    self.call(self.open_request(), mint=lambda: bad)

    def test_a_non_int_clock_is_a_fault_not_a_refusal(self):
        session_id = self.open_session("system", SYSTEM_BYTES)
        self.send_all_chunks(session_id, SYSTEM_BYTES)
        with self.assertRaises(SupervisorError):
            gsu.handle_staging_final(
                self.final_request(session_id, 1), peer_uid=SIDECAR_UID,
                allowed_sidecar_uid=SIDECAR_UID, conn=self.conn,
                publish_artifact=self.store.publish, clock_ms=lambda: "now")

    def test_a_service_without_a_publish_seam_is_refused_at_construction(self):
        with self.assertRaises(SupervisorError):
            gsu.StagingService(allowed_sidecar_uid=SIDECAR_UID,
                               staging_root=str(self.staging_root), publish_artifact=None)
        with self.assertRaises(SupervisorError):
            gsu.StagingService(allowed_sidecar_uid=True,
                               staging_root=str(self.staging_root),
                               publish_artifact=self.store.publish)

    def test_a_non_staging_protocol_reaching_the_service_is_a_fault(self):
        with self.assertRaises(SupervisorError):
            self.call({"protocol": "brops.governed-turn-open.v1"})


if __name__ == "__main__":
    unittest.main()
