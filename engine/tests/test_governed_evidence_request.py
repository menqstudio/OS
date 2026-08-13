"""Offline tests for the execute/finalize trigger — rev-30 §4.10(d)
(+ §2.4, and §4.10(h) which is NOT IMPLEMENTED).

No socket, no key material, no OS trust chain. The ledger is a real SQLite file created
from the canonical shared DDL, every `<seq>.chunk` is a real file on a real filesystem, and
the three artifacts are uploaded through the real §4.10(a)(b)(c) handlers — so a turn only
reaches `INPUTS_READY` here the way it reaches it in production. Everything a stranger
needs to run this is in the standard library.

The tests are organized as the design's own obligations:

  * every reason in the CLOSED five-literal set is REACHABLE, by name, from a request a
    hostile sidecar could actually send — with the ONE exception marked in
    `SessionCorruptIsNotSidecarReachableTests`, which says plainly that `session_corrupt`
    requires already-tampered durable state and shows exactly what has to be broken;
  * the property the gate READS — "all three declared inputs were published and each is the
    digest the signature committed to" — is proved against the DATABASE with raw SQL,
    bypassing every Python guard, and each of the five relied-on triggers is proved in
    ISOLATION so that one passing does not stand in for another;
  * nothing here creates an acceptance row, an `execution_attempt_id`, a lease, or writes a
    single byte to any table: the whole gate is SELECTs, and that is asserted rather than
    assumed;
  * the §4.10(f) output pull landed on 2026-08-10 (the SUPERVISOR hop; the desktop hop is
    still unbuilt) and is not this gate's business either way. The §5
    continuation is a test double throughout. §5 acceptance DOES have a production supplier
    (`governed_acceptance.AcceptanceDriver`, and `test_governed_acceptance.py` drives it
    through this very gate); it is doubled HERE on purpose, because this file's subject is
    the gate and a test that ran the real ladder could not tell a gate failure from an
    acceptance failure. What is asserted about the seam is the CONTRACT it is held to — it
    must answer in §4.10(e)'s
    `brops.governed-turn-result.v1` union, this module cannot impersonate it, and it
    cannot impersonate this module.
"""

import hashlib
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_evidence_request as ger  # noqa: E402
import governed_staging_ledger as gsl  # noqa: E402
import governed_staging_upload as gsu  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
import governed_turn_result as gtr  # noqa: E402
from governed_supervisor import SupervisorError  # noqa: E402

SIDECAR_UID = 4101
BROKER_UID = 4102

NOW = 1_700_000_100_000
EXPIRES = NOW + 30_000

CHUNK = gsu.MAX_STAGING_CHUNK_BYTES          # 184320

SYSTEM_BYTES = b"you are a governed assistant.\n" * 7
HISTORY_BYTES = bytes((i * 7 + 11) % 251 for i in range(CHUNK + 4096))
GENCFG_BYTES = b'{"max_tokens":512,"temperature":0.2}'

ARTIFACTS = (("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
             ("generation_config", GENCFG_BYTES))

#: The tables §4.10(d) must not touch, and the tables it must not change.
GOVERNED_TABLES = ("governed_turn_acceptance", "governed_turn_completion",
                   "governed_turn_outbox", "governed_evidence_head_floor")
STAGING_TABLES = ("governed_turn_staging", "governed_turn_staging_session",
                  "governed_turn_staging_chunk")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Store:
    """A real content-addressed store: the handle IS the digest of the bytes written."""

    def __init__(self):
        self.blobs = {}

    def publish(self, data: bytes) -> str:
        handle = sha(data)
        self.blobs.setdefault(handle, data)
        return handle


#: What the §5 continuation answers with. The real supplier lives in
#: `governed_acceptance` and is exercised in `test_governed_acceptance.py`; here it is a
#: double, and §4.10(d) says
#: that once an acceptance row exists "the acceptance/signer verdict is
#: `brops.governed-turn-result.v1`". So the double answers a REAL §4.10(e) frame, BUILT by
#: that module rather than written out here: this file is still not the place a §4.10(e)
#: shape is defined, it is a place one is used.
#:
#: `lease_not_ready` is chosen deliberately. It is a `GOVERNED_REFUSAL_REASONS` member that
#: §4.5 pins to the execute trigger itself — "the execute trigger (§4.10(d)) arrives before
#: the row reaches `LEASE_READY`" — so the double answers the one governed verdict this
#: hop's own timing can produce, and it is a REFUSAL, the arm most easily confused with
#: §4.10(d)'s own.
CONTINUATION_REPLY = gtr.turn_result_refused("lease_not_ready")


class _Continuation:
    """The §5 acceptance continuation, as a double.

    The real §5 supplier is `governed_acceptance.AcceptanceDriver`; what the gate hands off
    to is stubbed here so this file can fail for gate reasons only. It records the
    ``GatedTurn`` it was given (that object is the entire product of §4.10(d)) and returns
    the §4.10(e) verdict above.
    """

    _DEFAULT = CONTINUATION_REPLY

    def __init__(self, reply=_DEFAULT):
        self.calls = []
        self.reply = reply

    def __call__(self, gated):
        self.calls.append(gated)
        return self.reply


class _Case(unittest.TestCase):
    """One durable ledger on a REAL file, one REAL staging root, one real store per test.

    A turn is walked to `INPUTS_READY` through the real §4.10(a0)-created row and the real
    §4.10(a)(b)(c) handlers rather than by writing the state directly. That matters here
    more than it did in the staging tests: the whole claim of §4.10(d) is that
    `INPUTS_READY` means something, so a test that manufactured the state would be assuming
    what it is supposed to check.
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
        self.continuation = _Continuation()

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
    def new_turn(self, *, nonce="nonce-1", handle=None, install="inst-1", expires=EXPIRES):
        handle = handle or sha(nonce.encode("utf-8") + install.encode("utf-8") + b"|ch")
        row = gsl.NewStaging(
            install_id=install,
            request_nonce=nonce,
            challenge_handle=handle,
            run_id="run-1",
            task_id="task-1",
            workspace_id="ws-1",
            system_sha256=sha(SYSTEM_BYTES),
            history_sha256=sha(HISTORY_BYTES),
            generation_config_sha256=sha(GENCFG_BYTES),
            challenge_expires_at_ms=expires,
        )
        gsl.open_staging(self.conn, row, NOW)
        return row

    def staging_service(self):
        return gsu.StagingService(
            allowed_sidecar_uid=SIDECAR_UID,
            staging_root=str(self.staging_root),
            publish_artifact=self.store.publish,
        )

    def upload(self, artifact, data, turn=None):
        """Drive one artifact through the real §4.10(a)(b)(c) handlers."""
        turn = turn or self.turn
        service = self.staging_service()

        def call(body):
            return service.handle(body, peer_uid=SIDECAR_UID, conn=self.conn,
                                  clock_ms=lambda: self.clock)

        opened = call({
            "protocol": gsu.STAGING_OPEN_PROTOCOL,
            "install_id": turn.install_id,
            "challenge_handle": turn.challenge_handle,
            "request_nonce": turn.request_nonce,
            "artifact": artifact,
            "declared_len": len(data),
            "declared_sha256": sha(data),
        })
        self.assertEqual(opened["status"], "opened", opened)
        session_id = opened["staging_session_id"]

        offset, seq = 0, 0
        while offset < len(data):
            n = min(CHUNK, len(data) - offset)
            import base64
            ack = call({
                "protocol": gsu.STAGING_CHUNK_PROTOCOL,
                "staging_session_id": session_id,
                "seq": seq,
                "bytes_b64": base64.urlsafe_b64encode(
                    data[offset:offset + n]).decode("ascii").rstrip("="),
            })
            self.assertEqual(ack["status"], "ack", ack)
            offset += n
            seq += 1

        published = call({"protocol": gsu.STAGING_FINAL_PROTOCOL,
                          "staging_session_id": session_id, "seq": seq})
        self.assertEqual(published["status"], "published", published)
        return session_id

    def make_ready(self, turn=None):
        """Walk a turn all the way to `INPUTS_READY` the way production does."""
        turn = turn or self.turn
        for artifact, data in ARTIFACTS:
            self.upload(artifact, data, turn=turn)
        self.assertEqual(self.turn_row(turn)["state"], gsl.INPUTS_READY)
        return turn

    # ---- the message under test ------------------------------------------------
    def request(self, *, turn=None, **overrides):
        turn = turn or self.turn
        body = {
            "protocol": ger.EVIDENCE_REQUEST_PROTOCOL,
            "install_id": turn.install_id,
            "challenge_handle": turn.challenge_handle,
            "request_nonce": turn.request_nonce,
        }
        body.update(overrides)
        return body

    def service(self, *, sidecar_uid=SIDECAR_UID, continuation=None):
        return ger.EvidenceRequestService(
            allowed_sidecar_uid=sidecar_uid,
            drive_acceptance=continuation or self.continuation,
        )

    def call(self, request, *, peer_uid=SIDECAR_UID, **service_kwargs):
        return self.service(**service_kwargs).handle(
            request, peer_uid=peer_uid, conn=self.conn)

    # ---- introspection ---------------------------------------------------------
    def turn_row(self, turn=None):
        turn = turn or self.turn
        return gsl.load_staging(self.conn, turn.install_id, turn.request_nonce)

    def snapshot(self):
        """Every row of every governed + staging table, as comparable JSON."""
        out = {}
        for table in GOVERNED_TABLES + STAGING_TABLES:
            rows = self.conn.execute("SELECT * FROM %s" % table).fetchall()
            out[table] = [
                {k: (v.hex() if isinstance(v, bytes) else v) for k, v in dict(r).items()}
                for r in rows
            ]
        return json.dumps(out, sort_keys=True)


# ---------------------------------------------------------------------------
# The happy path, and exactly what it produces
# ---------------------------------------------------------------------------


class GateAdmitsAReadyTurnTests(_Case):
    def test_a_ready_turn_reaches_the_acceptance_continuation(self):
        self.make_ready()
        reply = self.call(self.request())
        self.assertEqual(reply, CONTINUATION_REPLY)
        self.assertEqual(len(self.continuation.calls), 1)

    def test_the_gated_turn_is_read_off_the_row_not_off_the_request(self):
        """The request carries three identifiers and nothing else; everything §5 receives
        was written when the supervisor verified the SIGNATURE, not when the sidecar sent
        this message."""
        self.make_ready()
        gated, reason = ger.gate_evidence_request(
            self.request(), peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
            conn=self.conn)
        self.assertIsNone(reason)
        row = self.turn_row()
        self.assertEqual(gated.install_id, row["install_id"])
        self.assertEqual(gated.request_nonce, row["request_nonce"])
        self.assertEqual(gated.challenge_handle, row["challenge_handle"])
        self.assertEqual(gated.run_id, row["run_id"])
        self.assertEqual(gated.task_id, row["task_id"])
        self.assertEqual(gated.workspace_id, row["workspace_id"])
        self.assertEqual(gated.challenge_expires_at_ms, row["challenge_expires_at_ms"])
        # `run_id`/`task_id`/`workspace_id` are NOT fields of the request at all, so the
        # only place they can have come from is the durable row.
        self.assertNotIn("run_id", self.request())
        self.assertNotIn("task_id", self.request())
        self.assertNotIn("workspace_id", self.request())

    def test_the_three_handles_are_the_bytes_that_were_actually_published(self):
        """The gate reads handles; this proves the handles resolve, in the real store, to
        the exact artifacts uploaded — which is what §5 will go on to re-read."""
        self.make_ready()
        gated, _ = ger.gate_evidence_request(
            self.request(), peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
            conn=self.conn)
        for handle, data in ((gated.system_handle, SYSTEM_BYTES),
                             (gated.history_handle, HISTORY_BYTES),
                             (gated.generation_config_handle, GENCFG_BYTES)):
            self.assertEqual(self.store.blobs[handle], data)

    def test_the_gate_is_idempotent_and_stateless(self):
        """§4.10(d) writes nothing, so asking twice is asking twice — not a replay. A
        one-shot sidecar subprocess whose reply was lost has to be able to retry."""
        self.make_ready()
        before = self.snapshot()
        first = self.call(self.request())
        second = self.call(self.request())
        self.assertEqual(first, second)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.continuation.calls), 2)
        self.assertEqual(self.continuation.calls[0], self.continuation.calls[1])


# ---------------------------------------------------------------------------
# Nothing governed is minted
# ---------------------------------------------------------------------------


class NothingGovernedIsMintedTests(_Case):
    def test_a_passing_gate_creates_no_acceptance_row(self):
        self.make_ready()
        self.call(self.request())
        for table in GOVERNED_TABLES:
            with self.subTest(table=table):
                self.assertEqual(
                    self.conn.execute("SELECT COUNT(*) AS n FROM %s" % table)
                    .fetchone()["n"], 0)

    def test_the_gate_changes_no_row_of_any_table_on_any_outcome(self):
        """Pass AND refuse. The gate is SELECTs; if a future edit slipped a write in, the
        byte-comparison of every row of every governed and staging table catches it."""
        self.make_ready()
        second = self.new_turn(nonce="nonce-2")          # opened, never uploaded
        before = self.snapshot()
        outcomes = [
            self.call(self.request()),                                   # pass
            self.call(self.request(turn=second)),                        # no_inputs_ready
            self.call(self.request(request_nonce="nope")),               # retry_conflict
            self.call(self.request(), peer_uid=BROKER_UID),              # peer_denied
            self.call(self.request(extra="x")),                          # malformed
        ]
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(outcomes), 5)

    def test_the_gated_turn_carries_no_supervisor_minted_identity(self):
        """§4.10(d) "carries no `execution_attempt_id` (the supervisor reserves it, §5) and
        grants no authority by itself"."""
        self.make_ready()
        gated, _ = ger.gate_evidence_request(
            self.request(), peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
            conn=self.conn)
        fields = set(vars(gated))
        for forbidden in ("execution_attempt_id", "lease_id", "lease_handle", "receipt_id",
                          "challenge_accepted_at_ms", "now_ms", "state"):
            self.assertNotIn(forbidden, fields)

    def test_a_request_carrying_a_supervisor_minted_id_is_refused_malformed(self):
        """The P1-5 door: a requester naming the identity its own execution would later be
        judged under is refused before any side effect."""
        self.make_ready()
        for extra in ("execution_attempt_id", "lease_id", "receipt_id"):
            with self.subTest(field=extra):
                reply = self.call(self.request(**{extra: "x"}))
                self.assertEqual(reply["reason"], "malformed")
        self.assertEqual(self.continuation.calls, [])

    def test_the_gate_has_no_clock_seam_and_imports_no_clock(self):
        """The single admission clock read belongs to §4.10(a0) and the single acceptance
        clock read to §5 step 2. A third here would be a time the turn was judged against
        that no artifact records — so there is no clock to pass in and none to reach for.
        Checked structurally, on the module's real signatures and namespace, because a
        grep over the source would also match the prose explaining the rule."""
        import inspect
        for name in ("time", "datetime", "clock_ms"):
            self.assertFalse(hasattr(ger, name), name)
        for func in (ger.gate_evidence_request, ger.handle_evidence_request,
                     ger.EvidenceRequestService.handle):
            with self.subTest(func=func.__name__):
                params = inspect.signature(func).parameters
                self.assertNotIn("clock_ms", params)
                self.assertNotIn("now_ms", params)

    def test_the_gate_issues_only_select_statements(self):
        """A SELECT-only module, observed rather than asserted: every statement SQLite
        actually executes during a pass AND every refusal is captured through the
        connection's own trace callback. The snapshot test above proves no row changed;
        this proves no write was even attempted, and the two fail for different reasons."""
        self.make_ready()
        seen = []
        self.conn.set_trace_callback(seen.append)
        self.addCleanup(self.conn.set_trace_callback, None)
        second = self.new_turn(nonce="nonce-2")
        seen.clear()
        self.call(self.request())                                   # pass
        self.call(self.request(turn=second))                        # no_inputs_ready
        self.call(self.request(request_nonce="nope"))               # retry_conflict
        self.call(self.request(), peer_uid=BROKER_UID)              # peer_denied
        self.call(self.request(extra="x"))                          # malformed
        self.assertTrue(seen)
        for statement in seen:
            self.assertTrue(statement.lstrip().upper().startswith("SELECT"), statement)


# ---------------------------------------------------------------------------
# §4.10(d) — every reason in the closed set, reachable by name
# ---------------------------------------------------------------------------


class RefusalsAreReachableTests(_Case):
    def refuse(self, request, **kwargs):
        reply = self.call(request, **kwargs)
        self.assertEqual(reply["protocol"], ger.EVIDENCE_REQUEST_RESULT_PROTOCOL)
        self.assertEqual(reply["status"], "refused", reply)
        self.assertEqual(set(reply), {"protocol", "status", "reason"})
        self.assertEqual(self.continuation.calls, [])
        return reply["reason"]

    # ---- peer_denied -----------------------------------------------------------
    def test_peer_denied_for_the_broker_uid(self):
        self.make_ready()
        self.assertEqual(self.refuse(self.request(), peer_uid=BROKER_UID), "peer_denied")

    def test_peer_denied_for_an_unauthenticated_peer(self):
        self.make_ready()
        for peer in (None, "4101", True, 4101.0):
            with self.subTest(peer=peer):
                self.assertEqual(self.refuse(self.request(), peer_uid=peer), "peer_denied")

    def test_peer_denied_when_no_sidecar_principal_is_configured(self):
        """`peer_is_sidecar(uid, None)` is fail-closed: a supervisor that has not been told
        who the sidecar is serves no sidecar."""
        self.make_ready()
        gated, reason = ger.gate_evidence_request(
            self.request(), peer_uid=SIDECAR_UID, allowed_sidecar_uid=None, conn=self.conn)
        self.assertIsNone(gated)
        self.assertEqual(reason, "peer_denied")

    def test_the_peer_check_runs_before_the_shape_check(self):
        """A stranger's frame is never parsed on its behalf: a request that is BOTH from
        the wrong peer and malformed answers `peer_denied`, not `malformed`."""
        self.assertEqual(
            self.refuse({"protocol": ger.EVIDENCE_REQUEST_PROTOCOL, "junk": 1},
                        peer_uid=BROKER_UID),
            "peer_denied")

    # ---- malformed -------------------------------------------------------------
    def test_malformed_on_an_unexpected_field(self):
        self.assertEqual(self.refuse(self.request(extra=1)), "malformed")

    def test_malformed_on_each_missing_field(self):
        for field in ("install_id", "challenge_handle", "request_nonce"):
            with self.subTest(field=field):
                body = self.request()
                del body[field]
                self.assertEqual(self.refuse(body), "malformed")

    def test_malformed_on_a_non_object_request(self):
        for body in ([], "x", 7, None):
            with self.subTest(body=body):
                gated, reason = ger.gate_evidence_request(
                    body, peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
                    conn=self.conn)
                self.assertIsNone(gated)
                self.assertEqual(reason, "malformed")

    def test_malformed_on_a_wrong_protocol_const(self):
        """Two layers, two answers, and the difference is deliberate. The FRONT DOOR routes
        by protocol, so a frame with another const never reaches this service at all — and
        `EvidenceRequestService.handle` treats one that somehow did as a supervisor FAULT
        (see `SupervisorFaultTests`), because it means the router misrouted. The gate
        itself, which any caller may drive directly, answers `malformed`: a message
        declaring itself to be something else is not this message."""
        for other in ("brops.evidence-request.v1", "brops.governed-turn-open.v1", "", 7):
            with self.subTest(other=other):
                gated, reason = ger.gate_evidence_request(
                    self.request(protocol=other), peer_uid=SIDECAR_UID,
                    allowed_sidecar_uid=SIDECAR_UID, conn=self.conn)
                self.assertIsNone(gated)
                self.assertEqual(reason, "malformed")

    def test_malformed_on_an_id_that_is_not_a_bounded_string(self):
        for field in ("install_id", "request_nonce"):
            for bad in ("", "x" * 129, 7, None, True, ["x"]):
                with self.subTest(field=field, bad=bad):
                    self.assertEqual(self.refuse(self.request(**{field: bad})), "malformed")

    def test_malformed_on_a_challenge_handle_that_is_not_lowercase_64_hex(self):
        good = self.turn.challenge_handle
        for bad in (good.upper(), good[:63], good + "a", "z" * 64, 7, None, True):
            with self.subTest(bad=bad):
                self.assertEqual(self.refuse(self.request(challenge_handle=bad)),
                                 "malformed")

    # ---- no_inputs_ready -------------------------------------------------------
    def test_no_inputs_ready_when_no_staging_row_exists_at_all(self):
        gated, reason = ger.gate_evidence_request(
            {"protocol": ger.EVIDENCE_REQUEST_PROTOCOL, "install_id": "ghost",
             "request_nonce": "ghost", "challenge_handle": "f" * 64},
            peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID, conn=self.conn)
        self.assertIsNone(gated)
        self.assertEqual(reason, "no_inputs_ready")

    def test_no_inputs_ready_while_the_row_is_still_uploading(self):
        self.assertEqual(self.turn_row()["state"], gsl.UPLOADING)
        self.assertEqual(self.refuse(self.request()), "no_inputs_ready")

    def test_no_inputs_ready_after_two_of_three_artifacts(self):
        """The reason `INPUTS_READY` is the gate and not "some inputs are in"."""
        self.upload("system", SYSTEM_BYTES)
        self.upload("history", HISTORY_BYTES)
        self.assertEqual(self.refuse(self.request()), "no_inputs_ready")
        self.upload("generation_config", GENCFG_BYTES)
        self.assertEqual(self.call(self.request())["protocol"],
                         gtr.GOVERNED_TURN_RESULT_PROTOCOL)

    # ---- retry_conflict --------------------------------------------------------
    def test_retry_conflict_when_the_nonce_names_a_different_challenge(self):
        """§5: "a retry that presents a nonce/challenge pairing different from the stored
        row is a conflict and is refused" — stated one step earlier."""
        self.make_ready()
        self.assertEqual(self.refuse(self.request(challenge_handle="a" * 64)),
                         "retry_conflict")

    def test_retry_conflict_when_the_challenge_is_open_under_another_nonce(self):
        """The mirror image: the handle exists, but under an `(install_id, request_nonce)`
        this request does not name. Answering `no_inputs_ready` there would report a clean
        absence where the truth is that two turns are claiming one challenge."""
        self.make_ready()
        self.assertEqual(self.refuse(self.request(request_nonce="other-nonce")),
                         "retry_conflict")

    def test_retry_conflict_when_the_challenge_belongs_to_another_install(self):
        self.make_ready()
        self.assertEqual(self.refuse(self.request(install_id="other-install")),
                         "retry_conflict")

    def test_a_genuinely_absent_triple_is_no_inputs_ready_not_retry_conflict(self):
        """The two verdicts are told apart by whether the CHALLENGE is known, so this pins
        the boundary: same shape, unknown handle, and the answer changes."""
        self.assertEqual(self.refuse(self.request(request_nonce="other-nonce",
                                                  challenge_handle="b" * 64)),
                         "no_inputs_ready")


# ---------------------------------------------------------------------------
# session_corrupt — reachable, but NOT from a sidecar frame. Marked, not hidden.
# ---------------------------------------------------------------------------


class SessionCorruptIsNotSidecarReachableTests(_Case):
    """**The honest exception.** Four of the five §4.10(d) reasons are reachable from a
    frame a hostile sidecar could send. `session_corrupt` is not, and this class says so
    rather than dressing a filesystem edit up as an attack.

    §2.4 recovery rule (b) is the ONLY producer of `SESSION_CORRUPT`: a session whose DB
    row exists but whose durable `<seq>.chunk` is missing, unreadable, or does not re-hash.
    The staging root is `0700` supervisor-only and the sidecar has no read, let alone write
    — so reaching this state requires a crash, a faulty store, or an operator/attacker with
    the supervisor's own filesystem access. The test therefore deletes a chunk file, which
    is exactly what it is: an act by something that is already inside.

    It is still worth a test. Once that state exists, a compromised sidecar CAN send the
    §4.10(d) trigger against it, and what it must hear is the specific terminal verdict
    (§2.4: recovery is operator-sweep only) rather than the "not yet" of `no_inputs_ready`.
    """

    def corrupt_session(self, artifact, data, turn=None):
        """Drive a session into `SESSION_CORRUPT` the ONLY way anything can: §2.4 recovery
        rule (b). Open it, send its chunks, then destroy the durable `<seq>.chunk` the
        supervisor is about to re-read from byte zero, and let the real §4.10(c) handler
        discover the divergence. Nothing here writes the state directly."""
        import base64
        turn = turn or self.turn
        service = self.staging_service()

        def call(body):
            return service.handle(body, peer_uid=SIDECAR_UID, conn=self.conn,
                                  clock_ms=lambda: self.clock)

        opened = call({
            "protocol": gsu.STAGING_OPEN_PROTOCOL, "install_id": turn.install_id,
            "challenge_handle": turn.challenge_handle,
            "request_nonce": turn.request_nonce, "artifact": artifact,
            "declared_len": len(data), "declared_sha256": sha(data)})
        session_id = opened["staging_session_id"]

        offset, seq = 0, 0
        while offset < len(data):
            n = min(CHUNK, len(data) - offset)
            call({"protocol": gsu.STAGING_CHUNK_PROTOCOL,
                  "staging_session_id": session_id, "seq": seq,
                  "bytes_b64": base64.urlsafe_b64encode(
                      data[offset:offset + n]).decode("ascii").rstrip("=")})
            offset += n
            seq += 1

        session = gsl.load_session(self.conn, session_id)
        (pathlib.Path(session["session_dir"]) / "0.chunk").unlink()

        final = call({"protocol": gsu.STAGING_FINAL_PROTOCOL,
                      "staging_session_id": session_id, "seq": seq})
        self.assertEqual(final["reason"], "session_corrupt", final)
        self.assertEqual(gsl.load_session(self.conn, session_id)["state"],
                         gsl.SESSION_CORRUPT)
        return session_id

    def test_session_corrupt_when_an_upload_session_is_terminally_corrupt(self):
        """The other two artifacts publish normally; the turn is stuck because one session
        can never finish. What the trigger must hear is the permanent verdict, not "not
        yet" — §2.4 makes recovery operator-sweep only, so retrying is pointless."""
        self.corrupt_session("system", SYSTEM_BYTES)
        self.upload("history", HISTORY_BYTES)
        self.upload("generation_config", GENCFG_BYTES)
        self.assertNotEqual(self.turn_row()["state"], gsl.INPUTS_READY)
        self.assertEqual(self.call(self.request())["reason"], "session_corrupt")
        self.assertEqual(self.continuation.calls, [])

    def test_session_corrupt_outranks_no_inputs_ready_for_the_same_row(self):
        """Both diagnoses describe a row that is not `INPUTS_READY`. The boundary between
        them is whether the turn CAN still get there, and this pins it: the same turn, the
        same state, one session corrupted, and the verdict changes."""
        second = self.new_turn(nonce="nonce-2")
        self.assertEqual(self.call(self.request(turn=second))["reason"], "no_inputs_ready")
        self.corrupt_session("system", SYSTEM_BYTES, turn=second)
        self.assertEqual(self.call(self.request(turn=second))["reason"], "session_corrupt")

    def test_session_corrupt_is_found_whichever_artifact_rotted(self):
        """The lookup walks all three artifacts. A version that only looked at one would
        pass every test that happened to corrupt that one, so each is corrupted in its own
        fresh turn here."""
        for i, (artifact, data) in enumerate(ARTIFACTS):
            with self.subTest(artifact=artifact):
                # A fresh install each time: MAX_CONCURRENT_GOVERNED_TURNS is 2.
                turn = self.new_turn(nonce="nonce-corrupt-%d" % i,
                                     install="inst-corrupt-%d" % i)
                self.corrupt_session(artifact, data, turn=turn)
                self.assertEqual(self.call(self.request(turn=turn))["reason"],
                                 "session_corrupt")

    def test_a_not_ready_turn_is_not_tainted_by_another_turn_s_corruption(self):
        """The sharpest form of the keying question, and the one mutation testing found
        missing. The sibling test below uses a READY turn, which never reaches the
        corrupt-session lookup at all — so a lookup that ignored its `challenge_handle`
        argument passed it. Here BOTH turns reach the lookup: one is merely still uploading
        and must hear "not yet", the other is corrupt and must hear the terminal verdict."""
        healthy = self.new_turn(nonce="nonce-healthy", install="inst-healthy")
        self.upload("system", SYSTEM_BYTES, turn=healthy)
        self.assertEqual(self.turn_row(healthy)["state"], gsl.UPLOADING)

        rotten = self.new_turn(nonce="nonce-rotten", install="inst-rotten")
        self.corrupt_session("system", SYSTEM_BYTES, turn=rotten)
        self.assertEqual(self.turn_row(rotten)["state"], gsl.UPLOADING)

        self.assertEqual(self.call(self.request(turn=healthy))["reason"], "no_inputs_ready")
        self.assertEqual(self.call(self.request(turn=rotten))["reason"], "session_corrupt")

    def test_a_corrupt_session_on_ANOTHER_turn_does_not_taint_this_one(self):
        """The corrupt-session lookup is keyed on the turn's own `challenge_handle`. A
        check that ignored the key would refuse every turn on the install once one session
        anywhere went bad."""
        other = self.new_turn(nonce="nonce-2")
        self.corrupt_session("system", SYSTEM_BYTES, turn=other)

        self.make_ready()
        self.assertEqual(self.call(self.request()), CONTINUATION_REPLY)
        self.assertEqual(self.call(self.request(turn=other))["reason"], "session_corrupt")

    def test_a_ready_turn_can_never_have_a_corrupt_session(self):
        """Why the corrupt-session diagnosis is made ONLY on the not-ready branch, and is
        not a check hiding on a path it could never fire from: `ARTIFACT_READY` is terminal
        in the DDL, so a session that published cannot rot afterwards."""
        self.make_ready()
        for artifact, _ in ARTIFACTS:
            session = gsl.load_session_for_artifact(
                self.conn, self.turn.challenge_handle, artifact)
            self.assertEqual(session["state"], gsl.ARTIFACT_READY)
            with self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(
                    "UPDATE governed_turn_staging_session SET state = 'SESSION_CORRUPT'"
                    " WHERE staging_session_id = ?", (session["staging_session_id"],))


# ---------------------------------------------------------------------------
# The property the gate READS, proved against the database
# ---------------------------------------------------------------------------


class InputsReadyIsAPropertyNotAClaimTests(_Case):
    """§4.10(d) reads `INPUTS_READY` as "every declared input exists in the store and
    re-hashes to the challenge's committed digest". That reading is only worth anything if
    the state cannot be declared by a writer that published nothing, so each of the five
    triggers the gate relies on is proved HERE, in isolation, with raw SQL that bypasses
    every Python guard — and none of them stands in for another."""

    def other_row(self, **overrides):
        cols = dict(
            install_id="inst-9", request_nonce="nonce-9", challenge_handle="c" * 64,
            run_id="r", task_id="t", workspace_id="w",
            system_sha256=sha(SYSTEM_BYTES), history_sha256=sha(HISTORY_BYTES),
            generation_config_sha256=sha(GENCFG_BYTES),
            system_handle=None, history_handle=None, generation_config_handle=None,
            state="VERIFYING", challenge_expires_at_ms=EXPIRES,
            created_at_ms=NOW, updated_at_ms=NOW,
        )
        cols.update(overrides)
        self.conn.execute(
            "INSERT INTO governed_turn_staging (%s) VALUES (%s)"
            % (", ".join(cols), ", ".join("?" * len(cols))),
            tuple(cols.values()))

    # ---- 1. a row is born VERIFYING --------------------------------------------
    def test_a_row_cannot_be_inserted_already_inputs_ready(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.other_row(state="INPUTS_READY",
                           system_handle=None, history_handle=None,
                           generation_config_handle=None)
        self.assertIsNone(gsl.load_staging(self.conn, "inst-9", "nonce-9"))

    # ---- 2. a row is born with NO published handles -----------------------------
    def test_a_row_cannot_be_inserted_carrying_published_handles(self):
        """The hole this closes, and why it is not covered by the trigger above.
        `VERIFYING` says nothing about the three handle columns, and pre-set handles that
        already EQUAL the committed digests pass the binding trigger on every later UPDATE
        — so without this a row could walk VERIFYING -> UPLOADING -> INPUTS_READY having
        published nothing at all, and §4.10(d) would read it as proof of upload."""
        for column in ("system_handle", "history_handle", "generation_config_handle"):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.other_row(**{column: sha(SYSTEM_BYTES)})
                self.assertIsNone(gsl.load_staging(self.conn, "inst-9", "nonce-9"))

    def test_the_gate_never_sees_the_row_that_hole_would_have_produced(self):
        """End to end: the exact forgery the trigger refuses, attempted, then the gate
        asked about it. Nothing is admitted because nothing was created."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.other_row(system_handle=sha(SYSTEM_BYTES),
                           history_handle=sha(HISTORY_BYTES),
                           generation_config_handle=sha(GENCFG_BYTES))
        reply = self.call({"protocol": ger.EVIDENCE_REQUEST_PROTOCOL,
                           "install_id": "inst-9", "request_nonce": "nonce-9",
                           "challenge_handle": "c" * 64})
        self.assertEqual(reply["reason"], "no_inputs_ready")
        self.assertEqual(self.continuation.calls, [])

    # ---- 3. the transition matrix -----------------------------------------------
    def test_uploading_cannot_skip_straight_to_inputs_ready_from_verifying(self):
        self.other_row()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE governed_turn_staging SET state = 'INPUTS_READY'"
                " WHERE install_id = 'inst-9'")

    def test_inputs_ready_cannot_be_walked_backwards(self):
        self.make_ready()
        for target in ("UPLOADING", "VERIFYING"):
            with self.subTest(target=target):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(
                        "UPDATE governed_turn_staging SET state = ?"
                        " WHERE challenge_handle = ?",
                        (target, self.turn.challenge_handle))

    # ---- 4. a published handle IS the committed digest --------------------------
    def test_a_handle_that_is_not_the_committed_digest_cannot_be_recorded(self):
        for column, digest in (("system_handle", "system_sha256"),
                               ("history_handle", "history_sha256"),
                               ("generation_config_handle", "generation_config_sha256")):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(
                        "UPDATE governed_turn_staging SET %s = ? WHERE challenge_handle = ?"
                        % column, ("d" * 64, self.turn.challenge_handle))
                row = gsl.load_staging_by_handle(self.conn, self.turn.challenge_handle)
                self.assertIsNone(row[column])
                self.assertIsNotNone(row[digest])

    def test_a_published_handle_is_write_once(self):
        self.make_ready()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE governed_turn_staging SET system_handle = ?"
                " WHERE challenge_handle = ?",
                (sha(GENCFG_BYTES), self.turn.challenge_handle))

    # ---- 5. INPUTS_READY requires all three -------------------------------------
    def test_inputs_ready_is_unreachable_while_any_handle_is_null(self):
        self.upload("system", SYSTEM_BYTES)
        self.upload("history", HISTORY_BYTES)
        row = self.turn_row()
        self.assertIsNone(row["generation_config_handle"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE governed_turn_staging SET state = 'INPUTS_READY'"
                " WHERE challenge_handle = ?", (self.turn.challenge_handle,))
        self.assertEqual(self.refuse_reason(), "no_inputs_ready")

    def refuse_reason(self):
        return self.call(self.request())["reason"]

    # ---- what the DDL genuinely cannot promise ----------------------------------
    def test_the_gate_does_not_and_cannot_prove_the_bytes_are_still_in_the_store(self):
        """Stated rather than hidden. The DDL binds the handle to the committed digest; it
        cannot know whether the content-addressed object still exists. §5/§6 re-read the
        bytes before anything is signed, and §4.10(d) publishes no reason literal for their
        absence — so inventing one here would put a verdict outside a closed set."""
        self.make_ready()
        self.store.blobs.clear()
        self.assertEqual(self.call(self.request())["protocol"],
                         gtr.GOVERNED_TURN_RESULT_PROTOCOL)


# ---------------------------------------------------------------------------
# The two halves of the §4.10(d) union cannot be confused
# ---------------------------------------------------------------------------


class ReplyNamespaceTests(_Case):
    #: §4.5's closed governed enum. It used to be re-typed here from the design, because
    #: the tree had no such constant; §4.10(e) now defines it ONCE
    #: (`governed_turn_result.GOVERNED_REFUSAL_REASONS`) and §4.5's relay literal-embed
    #: rule forbids a second copy, so this is the import rather than the copy.
    GOVERNED_REFUSAL_REASONS = gtr.GOVERNED_REFUSAL_REASONS

    def test_the_two_reason_sets_are_NOT_disjoint_by_value(self):
        """§4.10(h) (NOT IMPLEMENTED) calls the internal codes "a **disjoint** namespace from
        GOVERNED_REFUSAL_REASONS". Taken as a claim about the STRINGS that is false, and
        this test pins exactly how false: `malformed` and `retry_conflict` appear in both.
        The claim holds about the NAMESPACE — see the next test — and a reader who took it
        as a claim about values would wrongly conclude that seeing `retry_conflict` on the
        wire identifies which authority produced it."""
        overlap = set(ger.EVIDENCE_REQUEST_REFUSAL_REASONS) & set(
            self.GOVERNED_REFUSAL_REASONS)
        self.assertEqual(overlap, {"malformed", "retry_conflict"})

    def test_the_discriminator_is_what_separates_them(self):
        """So the separation has to be structural, and it is: a §4.10(d) pre-acceptance
        refusal carries its OWN protocol const, which is neither §4.10(e)'s name nor the
        frozen Wave 3b-1 one, and §4.10(h) (NOT IMPLEMENTED) classifies by that top-level
        key. The `retry_conflict` pair is the worked example: the SAME string under the two
        consts is two different verdicts from two different authorities."""
        reply = ger.evidence_request_refused("retry_conflict")
        verdict = gtr.turn_result_refused("retry_conflict")
        self.assertEqual(reply["reason"], verdict["reason"])
        self.assertEqual(reply["protocol"], "brops.governed-evidence-request-result.v1")
        for other in (gtr.GOVERNED_TURN_RESULT_PROTOCOL, "brops.governed-result.v1",
                      "brops.evidence-request.v1", "brops.governed-sign-result.v1"):
            self.assertNotEqual(reply["protocol"], other)

    def test_a_refusal_can_never_satisfy_the_signed_predicate(self):
        """§4.10(e): its `signed` arm REQUIRES `envelope_jcs_b64` + `signature_b64` +
        `output_stream_id`. A pre-acceptance refusal has exactly three keys - none of them
        those - so it cannot be mistaken for a verdict even by a reader that ignored the
        discriminator. The three names are read from §4.10(e)'s own field set rather than
        re-typed, so a future widening of that set is seen here."""
        for reason in ger.EVIDENCE_REQUEST_REFUSAL_REASONS:
            reply = ger.evidence_request_refused(reason)
            self.assertEqual(set(reply), {"protocol", "status", "reason"})
            for required in ("envelope_jcs_b64", "signature_b64", "output_stream_id"):
                self.assertIn(required, gtr.SIGNED_FIELDS)
                self.assertNotIn(required, reply)

    def test_the_request_protocol_is_not_the_wave_3b1_evidence_request(self):
        """§4.10(d) "replaces the mis-named use of the v1 `brops.evidence-request.v1` const
        on the governed path". §2.2 P0-1 freezes that v1 name with its shipped shape, so
        the governed message has to be a NEW name — this asserts they are two."""
        v1_source = (ROOT / "tools" / "brops_supervisor_service.py").read_text("utf-8")
        self.assertIn('EVIDENCE_REQUEST_PROTOCOL = "brops.evidence-request.v1"', v1_source)
        self.assertEqual(ger.EVIDENCE_REQUEST_PROTOCOL,
                         "brops.governed-evidence-request.v1")
        self.assertNotIn(ger.EVIDENCE_REQUEST_PROTOCOL, v1_source)

    def test_the_diagnostic_stage_is_the_one_the_routing_table_names(self):
        """§4.10(h)'s routing table keys this protocol's refusals on stage
        `evidence-request` (§4.10(h) itself is **NOT IMPLEMENTED** — a later ordered
        piece)."""
        self.assertEqual(ger.DIAGNOSTIC_STAGE, "evidence-request")


# ---------------------------------------------------------------------------
# The front door
# ---------------------------------------------------------------------------


class _Conn:
    """A framed connection stand-in: one request in, one reply out.

    `raw` lets a test send bytes that are NOT the compact serialization of `body` — the
    only way to show that the front door's frame cap is about what ARRIVED on the wire and
    not about what the decoder made of it.
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


class FrontDoorTests(_Case):
    def serve(self, body, *, peer_uid=SIDECAR_UID, service=True, raw=None, **kwargs):
        conn = _Conn(peer_uid, body, raw=raw)
        return gss.handle_connection(
            conn, BROKER_UID, None, None, None, lambda: self.clock,
            ledger_conn=self.conn,
            evidence_request_service=self.service() if service else None,
            **kwargs)

    def test_the_sidecar_may_send_the_evidence_request(self):
        self.make_ready()
        self.assertEqual(self.serve(self.request()), CONTINUATION_REPLY)

    def test_the_broker_sending_an_evidence_request_is_not_authorized(self):
        self.make_ready()
        self.assertEqual(self.serve(self.request(), peer_uid=BROKER_UID)["reason"],
                         "peer_denied")

    def test_without_the_service_the_sidecar_is_not_admitted_at_the_door(self):
        """No configured service means no configured sidecar principal, so the connection
        is refused before a frame is read — the same shape §4.10(a0)/(a)(b)(c) have."""
        self.make_ready()
        self.assertEqual(self.serve(self.request(), service=False),
                         {"ok": False, "error": "peer not authorized"})

    def test_without_the_service_but_with_another_sidecar_service_it_is_peer_denied(self):
        """A supervisor that serves staging but was never told what happens when a turn is
        admitted to execute must refuse the trigger — not fall through to an op, and not
        invent a verdict in a vocabulary that is not this protocol's."""
        self.make_ready()
        conn = _Conn(SIDECAR_UID, self.request())
        reply = gss.handle_connection(
            conn, BROKER_UID, None, None, None, lambda: self.clock,
            ledger_conn=self.conn, staging_service=self.staging_service())
        self.assertEqual(reply["protocol"], ger.EVIDENCE_REQUEST_RESULT_PROTOCOL)
        self.assertEqual(reply["reason"], "peer_denied")

    def test_the_sidecar_may_still_not_send_an_op(self):
        self.assertEqual(self.serve({"op": "accept-open", "challenge_doc": {}}),
                         {"ok": False, "error": "peer not authorized"})

    def test_a_split_sidecar_principal_is_refused_outright(self):
        """Three services now name the sidecar. Two of them naming DIFFERENT uids would
        mean one principal may upload a turn's inputs and another may trigger its
        execution — a shape §2.6 does not describe."""
        conn = _Conn(SIDECAR_UID, self.request())
        reply = gss.handle_connection(
            conn, BROKER_UID, None, None, None, lambda: self.clock,
            ledger_conn=self.conn,
            staging_service=self.staging_service(),
            evidence_request_service=self.service(sidecar_uid=SIDECAR_UID + 1))
        self.assertIn("principal split", reply["error"])

    def test_a_sidecar_uid_equal_to_the_broker_uid_is_the_collapse(self):
        conn = _Conn(SIDECAR_UID, self.request())
        reply = gss.handle_connection(
            conn, BROKER_UID, None, None, None, lambda: self.clock,
            ledger_conn=self.conn,
            evidence_request_service=self.service(sidecar_uid=BROKER_UID))
        self.assertIn("principal collapse", reply["error"])

    def test_an_over_cap_frame_is_refused_on_the_bytes_that_arrived(self):
        """A legal §4.10(d) request is a few hundred bytes, so the shape check alone would
        never see a 4 KiB one — but whitespace a decoder discards is invisible to it. The
        door sees the wire."""
        self.make_ready()
        body = self.request()
        compact = json.dumps(body, separators=(",", ":")).encode("utf-8")
        padded = b"{" + b" " * 5000 + compact[1:]
        self.assertGreater(len(padded), ger.MAX_EVIDENCE_REQUEST_FRAME_BYTES)
        self.assertEqual(json.loads(padded), body)      # decodes to the SAME legal request

        reply = self.serve(None, raw=padded)
        self.assertEqual(reply["protocol"], ger.EVIDENCE_REQUEST_RESULT_PROTOCOL)
        self.assertEqual(reply["reason"], "malformed")
        self.assertEqual(self.continuation.calls, [])
        # ...and the compact form of the same request is served normally.
        self.assertEqual(self.serve(body), CONTINUATION_REPLY)

    def test_the_frame_cap_boundary(self):
        """`<=` is admitted, `+1` is refused — checked on the composed front-door table so
        the boundary is the one the door actually applies."""
        cap = ger.MAX_EVIDENCE_REQUEST_FRAME_BYTES
        self.assertIsNone(gss.frame_cap_refusal(ger.EVIDENCE_REQUEST_PROTOCOL, cap))
        self.assertEqual(
            gss.frame_cap_refusal(ger.EVIDENCE_REQUEST_PROTOCOL, cap + 1)["reason"],
            "malformed")

    def test_the_composed_frame_cap_table_still_answers_for_staging(self):
        """The door consults two per-protocol tables in sequence; neither may swallow the
        other's protocols."""
        self.assertEqual(
            gss.frame_cap_refusal(gsu.STAGING_OPEN_PROTOCOL,
                                  gsu.MAX_STAGING_CONTROL_FRAME_BYTES + 1)["protocol"],
            gsu.STAGING_OPEN_RESULT_PROTOCOL)
        self.assertEqual(
            gss.frame_cap_refusal(gsu.STAGING_CHUNK_PROTOCOL,
                                  gsu.MAX_STAGING_CHUNK_FRAME_BYTES + 1)["reason"],
            "oversize_frame")
        self.assertIsNone(gss.frame_cap_refusal("brops.not-a-sidecar-protocol", 10 ** 9))

    def test_the_shape_alone_bounds_a_legal_request_far_under_the_frame_cap(self):
        """Why there is NO handler-level frame check, only the door's.

        Every field is either the fixed protocol const, a <=128-char id or a 64-hex digest,
        so the LARGEST legal request serializes to 426 bytes against a 4096-byte cap - 3670
        bytes of headroom, 9.6x. A frame check inside the handler could therefore never
        fire: the shape check refuses first, always, with the same verdict. Step 2 shipped
        exactly such a check on §4.10(a)/(c), mutation testing showed deleting it changed
        no test, and it was deleted rather than kept. This records the arithmetic that makes
        the same decision here, and the door's check - which sees the RAW bytes, including
        padding the decoder discards - is what actually bounds the frame."""
        from brops_protocol import encode_frame
        widest = {
            "protocol": ger.EVIDENCE_REQUEST_PROTOCOL,
            "install_id": "i" * 128,
            "challenge_handle": "a" * 64,
            "request_nonce": "n" * 128,
        }
        body = json.dumps(widest, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(body), 426)
        self.assertLess(len(body), ger.MAX_EVIDENCE_REQUEST_FRAME_BYTES)
        self.assertEqual(len(encode_frame(widest)), 430)      # + the 4-byte length prefix
        # ...and one character more in any id is refused by the SHAPE, not by a size cap.
        for field in ("install_id", "request_nonce"):
            with self.subTest(field=field):
                over = dict(widest, **{field: "x" * 129})
                self.assertLess(len(json.dumps(over, separators=(",", ":"))),
                                ger.MAX_EVIDENCE_REQUEST_FRAME_BYTES)
                self.assertEqual(self.serve(over)["reason"], "malformed")

    def test_the_evidence_request_is_in_the_sidecar_protocol_set(self):
        # Six since 2026-08-10: §4.10(f)'s output read joined the grant. The count is pinned
        # in three test files on purpose — widening the sidecar's door has to be a deliberate
        # edit in every place that claims to know how wide it is.
        self.assertIn(ger.EVIDENCE_REQUEST_PROTOCOL, gss.SIDECAR_PROTOCOLS)
        self.assertEqual(len(gss.SIDECAR_PROTOCOLS), 6)


# ---------------------------------------------------------------------------
# Supervisor-side faults are faults, never refusals
# ---------------------------------------------------------------------------


class SupervisorFaultTests(_Case):
    def test_an_off_contract_refusal_reason_is_a_hard_error(self):
        for bad in ("looks_plausible", "no_staging_row", "quota_turns", "sig_invalid",
                    "not_completed", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(SupervisorError):
                    ger.evidence_request_refused(bad)

    def test_a_missing_ledger_connection_is_a_fault_not_a_refusal(self):
        with self.assertRaises(SupervisorError):
            ger.handle_evidence_request(
                self.request(), peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
                conn=None, drive_acceptance=self.continuation)

    def test_a_denied_peer_never_reaches_the_missing_connection(self):
        """Order matters: the peer check is first, so a stranger gets a refusal rather than
        a supervisor-fault error that leaks how this supervisor is configured."""
        reply = ger.handle_evidence_request(
            self.request(), peer_uid=BROKER_UID, allowed_sidecar_uid=SIDECAR_UID,
            conn=None, drive_acceptance=self.continuation)
        self.assertEqual(reply["reason"], "peer_denied")

    def test_a_ledger_row_the_supervisor_cannot_interpret_is_a_fault(self):
        """A `state` outside the closed domain is not a clean absence, and answering
        `no_inputs_ready` would report one. Reaching it means defeating BOTH the table
        CHECK and the transition trigger, which is the point: this is a corrupt/tampered
        ledger, not something a peer can send — so it is marked, like `session_corrupt`."""
        self.conn.execute("DROP TRIGGER trg_governed_turn_staging_transition")
        self.conn.execute("PRAGMA ignore_check_constraints = ON")
        self.conn.execute(
            "UPDATE governed_turn_staging SET state = 'WHATEVER' WHERE challenge_handle = ?",
            (self.turn.challenge_handle,))
        self.conn.commit()
        self.assertEqual(
            self.conn.execute("SELECT state FROM governed_turn_staging").fetchone()["state"],
            "WHATEVER")
        with self.assertRaises(SupervisorError):
            self.call(self.request())
        self.assertEqual(self.continuation.calls, [])

    def test_a_service_without_a_continuation_is_refused_at_construction(self):
        with self.assertRaises(SupervisorError):
            ger.EvidenceRequestService(allowed_sidecar_uid=SIDECAR_UID,
                                       drive_acceptance=None)
        with self.assertRaises(SupervisorError):
            ger.EvidenceRequestService(allowed_sidecar_uid=True,
                                       drive_acceptance=self.continuation)
        with self.assertRaises(SupervisorError):
            ger.EvidenceRequestService(allowed_sidecar_uid="4101",
                                       drive_acceptance=self.continuation)

    def test_a_non_callable_continuation_is_a_fault_before_anything_is_read(self):
        with self.assertRaises(SupervisorError):
            ger.handle_evidence_request(
                self.request(), peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
                conn=self.conn, drive_acceptance="not callable")

    def test_a_continuation_that_returns_a_non_object_is_a_fault(self):
        self.make_ready()
        for bad in (None, "signed", 7, ["x"]):
            with self.subTest(bad=bad):
                with self.assertRaises(SupervisorError):
                    self.call(self.request(), continuation=_Continuation(reply=bad))

    def test_a_continuation_answering_in_the_pre_acceptance_namespace_is_a_fault(self):
        """Once §5 has been entered the verdict belongs to the §4.10(e) union. (§4.10(h) is
        NOT IMPLEMENTED — a later ordered piece.) A continuation replying
        `brops.governed-evidence-request-result.v1` would collapse the two halves of
        §4.10(d)'s reply union into one, and the §4.10(h) classifier — which reads the
        top-level `protocol` — could no longer tell an internal refusal from a governed
        verdict.

        The MESSAGE is asserted, not only the exception type. A pre-acceptance frame is
        also not a §4.10(e) frame, so the general shape check below would raise too - and a
        test that accepted either would let this specific guard be deleted unnoticed."""
        self.make_ready()
        impostor = _Continuation(reply=ger.evidence_request_refused("retry_conflict"))
        with self.assertRaisesRegex(SupervisorError, "pre-acceptance namespace"):
            self.call(self.request(), continuation=impostor)
        self.assertEqual(len(impostor.calls), 1)      # it WAS reached; the reply is refused

    def test_a_continuation_that_answers_outside_the_result_union_is_a_fault(self):
        """§4.10(d): once a row exists "the acceptance/signer verdict is
        `brops.governed-turn-result.v1`". Anything else is a supervisor-side fault - it is
        not a verdict this gate may pass on, and there is no §4.10(d) reason for it because
        no peer asked for it. Until §4.10(e) existed the reply was relayed unexamined."""
        self.make_ready()
        for bad in ({"protocol": "test.continuation-reached.v1"},
                    {"protocol": "brops.governed-result.v1", "status": "signed",
                     "output": "hi", "receipt": {}},
                    dict(gtr.turn_result_refused("hash_mismatch"), extra=1),
                    {"protocol": gtr.GOVERNED_TURN_RESULT_PROTOCOL, "status": "signed"}):
            with self.subTest(bad=bad):
                double = _Continuation(reply=bad)
                with self.assertRaisesRegex(
                        SupervisorError, "not a brops.governed-turn-result.v1 frame"):
                    self.call(self.request(), continuation=double)
                self.assertEqual(len(double.calls), 1)

    def test_a_signed_verdict_is_relayed_verbatim(self):
        """§4.5's relay rule: a genuine governed verdict is "relayed verbatim". §4.10(d)
        checks its SHAPE and changes nothing - it verifies no signature and rewrites no
        field, because the desktop's authority is the signed envelope inside, not this
        hop."""
        self.make_ready()
        verdict = gtr.turn_result_signed(
            receipt_id="rcpt-1", output_stream_id="A" * 43, output_bytes=11,
            output_sha256="c" * 64, envelope_jcs_b64="AAAA", signature_b64="A" * 86,
            key_id="signer-1", attestation_evidence_jcs_b64="BBBB",
            attestation_signature_b64="A" * 86, supervisor_attestation_key_id="sup-1",
            containment_evidence_b64=None, run_id="run-1",
            execution_attempt_id="attempt-1", lease_id="lease-1")
        relayed = self.call(self.request(), continuation=_Continuation(reply=verdict))
        self.assertEqual(relayed, verdict)
        self.assertIsNot(relayed, verdict)

    def test_a_non_evidence_request_protocol_reaching_the_service_is_a_fault(self):
        for protocol in (gsu.STAGING_OPEN_PROTOCOL, "brops.governed-turn-open.v1", None):
            with self.subTest(protocol=protocol):
                with self.assertRaises(SupervisorError):
                    self.call({"protocol": protocol})


if __name__ == "__main__":
    unittest.main()
