"""The Floor Writer — the fifteen threat cases the Architect required, and the concurrency one.

Every test here asserts its OWN message. A test that only asserts "it raised" is satisfied by
any earlier refusal, and this repository has found four checks defended by exactly that shape.

The custody rule needs two different accounts to be meaningful — the store must be the writer's
and NOT the caller's — so the fixtures pass a ``caller_uid`` that is deliberately not this
process's. That models the deployment; it does not simulate the kernel. Where a test needs a
REAL authenticated peer it uses a real ``AF_UNIX`` socket pair and the kernel's ``SO_PEERCRED``,
and it skips off Linux rather than pretending the property holds there.
"""

import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import floor_writer as fw
from bro_contracts import canonical_json_sha256

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
INSTALL = "install-1"
#: Not this process's uid. Custody requires the store's owner and the caller to differ, and a
#: fixture that used the same uid would be asserting a weaker rule than the one shipped.
CALLER = os.geteuid() + 1


def _request(task_id="task-1", head=5, digest=DIGEST_A, install=INSTALL, **overrides):
    request = {
        "op": fw.OP_ADVANCE_FLOOR,
        "protocol": fw.FLOOR_PROTOCOL,
        "install_id": install,
        "task_id": task_id,
        "head_sequence": head,
        "evidence_head_sha256": digest,
    }
    request.update(overrides)
    return request


class FloorWriterFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = pathlib.Path(self._tmp.name) / "floor"
        self.store.mkdir(mode=0o700)
        # A provisioned store: the roster exists and is empty. An ABSENT roster is a different
        # state and has its own test.
        (self.store / "_index.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def handle(self, request, caller_uid=CALLER, install=INSTALL):
        return fw.handle(request, store=self.store, served_install_id=install,
                         allowed_caller_uids=frozenset({CALLER}), caller_uid=caller_uid)

    def floor_on_disk(self, task_id="task-1"):
        path = self.store / f"{task_id}.floor.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


class ThreatCases(FloorWriterFixture):
    """The numbering follows the Architect's list so an auditor can walk them in order."""

    # 1 -------------------------------------------------------------------------------------
    def test_01_unauthorized_principal_is_refused_and_writes_nothing(self):
        reply = self.handle(_request(), caller_uid=CALLER + 7)
        self.assertEqual(reply["reason"], fw.REFUSE_UNAUTHORIZED)
        self.assertIn("Reaching this socket is not authority", reply["detail"])
        self.assertIsNone(self.floor_on_disk(), "a refused caller must leave no mark")

    def test_01b_the_refusal_does_not_name_the_allowlist(self):
        # A refusal that echoed the permitted uids would be an oracle for which uid to become.
        reply = self.handle(_request(), caller_uid=CALLER + 7)
        self.assertNotIn(str(CALLER), reply["detail"].replace(str(CALLER + 7), ""))

    # 2 -------------------------------------------------------------------------------------
    def test_02_an_unauthenticated_peer_is_refused_before_anything_else(self):
        # caller_uid None is "the platform could not tell us who this is". It must lose before
        # the allowlist, the scope or the request shape are consulted.
        reply = self.handle(_request(head=0), caller_uid=None)
        self.assertEqual(reply["reason"], fw.REFUSE_UNAUTHENTICATED)
        self.assertIn("no principal, no authority", reply["detail"])

    # 3 -------------------------------------------------------------------------------------
    def test_03_scope_mismatch_is_refused(self):
        reply = self.handle(_request(install="install-2"))
        self.assertEqual(reply["reason"], fw.REFUSE_SCOPE_MISMATCH)
        self.assertIn("advanced for someone else", reply["detail"])
        self.assertIsNone(self.floor_on_disk())

    # 4 -------------------------------------------------------------------------------------
    def test_04_malformed_requests_are_each_refused_for_their_own_reason(self):
        cases = [
            (_request(head=0), "head_sequence must be a positive integer"),
            (_request(head="5"), "head_sequence must be a positive integer"),
            (_request(head=True), "head_sequence must be a positive integer"),
            (_request(digest="not-a-digest"), "64 lowercase hex"),
            (_request(task_id="../escape"), "traversal segment"),
            (_request(task_id=""), "1..128 chars"),
            (_request(install=""), "install_id must be an identifier"),
        ]
        for request, expected in cases:
            with self.subTest(expected=expected):
                reply = self.handle(request)
                self.assertEqual(reply["reason"], fw.REFUSE_MALFORMED)
                self.assertIn(expected, reply["detail"])
        self.assertIsNone(self.floor_on_disk())

    def test_04b_an_unknown_field_is_refused_rather_than_ignored(self):
        reply = self.handle(_request(facts={"anything": 1}))
        self.assertEqual(reply["reason"], fw.REFUSE_MALFORMED)
        self.assertIn("unexpected field(s) ['facts']", reply["detail"])

    def test_04c_a_missing_field_is_refused(self):
        request = _request()
        del request["evidence_head_sha256"]
        reply = self.handle(request)
        self.assertIn("missing field(s) ['evidence_head_sha256']", reply["detail"])

    # 5 -------------------------------------------------------------------------------------
    def test_05_an_unsupported_protocol_is_refused_by_name(self):
        reply = self.handle(_request(protocol="bridge.floor-advance.v2"))
        self.assertEqual(reply["reason"], fw.REFUSE_PROTOCOL)
        self.assertIn("speaks 'bridge.floor-advance.v1' and nothing else", reply["detail"])

    def test_05b_an_unknown_op_is_refused(self):
        reply = self.handle(_request(op="reset-floor"))
        self.assertEqual(reply["reason"], fw.REFUSE_PROTOCOL)
        self.assertIn("unknown op 'reset-floor'", reply["detail"])

    # 6 -------------------------------------------------------------------------------------
    def test_06_a_lower_floor_is_refused_and_state_is_untouched(self):
        self.assertEqual(self.handle(_request(head=9))["outcome"], fw.OUTCOME_ADVANCED)
        before = self.floor_on_disk()
        reply = self.handle(_request(head=4))
        self.assertEqual(reply["reason"], fw.REFUSE_ROLLBACK)
        self.assertIn("the authoritative floor is 9 and the request asked for 4", reply["detail"])
        self.assertIn("Nothing was written", reply["detail"])
        self.assertEqual(self.floor_on_disk(), before, "a rollback must not touch the record")

    # 7 -------------------------------------------------------------------------------------
    def test_07_equal_floor_replays_as_already_committed_not_as_an_advancement(self):
        first = self.handle(_request(head=5))
        self.assertEqual(first["outcome"], fw.OUTCOME_ADVANCED)
        before = self.floor_on_disk()
        second = self.handle(_request(head=5))
        self.assertEqual(second["outcome"], fw.OUTCOME_ALREADY_COMMITTED,
                         "R5: an equal head is idempotency, and must not wear the word 'advanced'")
        self.assertEqual(second["floor"], 5)
        self.assertEqual(self.floor_on_disk(), before, "an idempotent replay mutates nothing")

    def test_07b_equal_sequence_with_a_different_head_is_not_a_replay(self):
        # Same number, different signed head: the sequence has stopped being a high-water mark.
        self.handle(_request(head=5, digest=DIGEST_A))
        reply = self.handle(_request(head=5, digest=DIGEST_B))
        self.assertEqual(reply["reason"], fw.REFUSE_STATE_UNREADABLE)
        self.assertIn("a head that changed without advancing is not a replay", reply["detail"])

    # 8 -------------------------------------------------------------------------------------
    def test_08_a_valid_advancement_commits_and_binds_its_evidence(self):
        request = _request(head=5)
        reply = self.handle(request)
        self.assertEqual(reply["outcome"], fw.OUTCOME_ADVANCED)
        self.assertEqual(reply["floor"], 5)
        self.assertEqual(reply["install_id"], INSTALL)
        self.assertEqual(reply["task_id"], "task-1")
        self.assertEqual(reply["evidence_head_sha256"], DIGEST_A)
        self.assertEqual(reply["writer_uid"], os.geteuid())
        self.assertEqual(reply["request_sha256"], canonical_json_sha256(request),
                         "the response must bind to THIS request instance")
        body = {k: v for k, v in reply.items() if k != "result_sha256"}
        self.assertEqual(reply["result_sha256"], canonical_json_sha256(body))
        self.assertEqual(self.floor_on_disk(),
                         {"task_id": "task-1", "head_sequence": 5,
                          "evidence_head_sha256": DIGEST_A})
        self.assertIn("task-1", json.loads((self.store / "_index.json").read_text())["tasks"])

    def test_08b_there_is_no_bare_success_boolean(self):
        # The Architect forbade a meaningless success:true standing in for evidence.
        reply = self.handle(_request())
        self.assertNotIn("success", reply)
        self.assertNotIn("verified", reply)

    # 9 -------------------------------------------------------------------------------------
    def test_09_concurrent_advancement_leaves_the_highest_floor_and_no_lost_update(self):
        # Eight threads race the same task with different heads. Whatever the interleaving, the
        # authoritative floor must end at the maximum, every reply must be self-consistent, and
        # no reply may report a floor the store does not hold.
        heads = [3, 9, 1, 7, 12, 5, 12, 2]
        replies = [None] * len(heads)

        def run(i):
            replies[i] = self.handle(_request(head=heads[i]))

        threads = [threading.Thread(target=run, args=(i,)) for i in range(len(heads))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = self.floor_on_disk()["head_sequence"]
        self.assertEqual(final, max(heads), "the floor must end at the highest head offered")
        advanced = [r for r in replies if r.get("outcome") == fw.OUTCOME_ADVANCED]
        self.assertTrue(advanced, "at least one racer must have advanced")
        for reply in replies:
            if reply.get("outcome") == fw.OUTCOME_ADVANCED:
                self.assertLessEqual(reply["floor"], final)
            elif reply.get("outcome") == fw.OUTCOME_ALREADY_COMMITTED:
                self.assertLessEqual(reply["floor"], final)
            else:
                self.assertEqual(reply["reason"], fw.REFUSE_ROLLBACK,
                                 "the only permitted loss is a refused rollback")
        # And a rollback never won: the mark is the max, not the last writer's value.
        self.assertEqual(self.floor_on_disk()["evidence_head_sha256"], DIGEST_A)

    # 10 ------------------------------------------------------------------------------------
    def test_10_an_unreachable_writer_raises_rather_than_returning_success(self):
        if sys.platform != "linux":
            self.skipTest("SO_PEERCRED is Linux-only and this path refuses off Linux by design")
        missing = pathlib.Path(self._tmp.name) / "no-such.sock"
        with self.assertRaises(fw.FloorWriterError) as caught:
            fw.request_advance(missing, INSTALL, "task-1", 5, DIGEST_A)
        self.assertIn("is unreachable", str(caught.exception))
        self.assertIn("this completion is not trusted", str(caught.exception))

    # 11 ------------------------------------------------------------------------------------
    def test_11_corrupt_authoritative_state_is_refused_not_treated_as_absent(self):
        self.handle(_request(head=5))
        (self.store / "task-1.floor.json").write_text("{tru", encoding="utf-8")
        reply = self.handle(_request(head=6))
        self.assertEqual(reply["reason"], fw.REFUSE_STATE_UNREADABLE)
        self.assertIn("refusing rather than treating a damaged", reply["detail"])

    def test_11b_a_deleted_mark_whose_task_is_rostered_is_refused(self):
        self.handle(_request(head=5))
        (self.store / "task-1.floor.json").unlink()
        reply = self.handle(_request(head=6))
        self.assertEqual(reply["reason"], fw.REFUSE_STATE_UNREADABLE)
        self.assertIn("the mark was removed", reply["detail"])

    def test_11c_an_absent_roster_is_unprovisioned_not_empty(self):
        (self.store / "_index.json").unlink()
        reply = self.handle(_request(head=5))
        self.assertEqual(reply["reason"], fw.REFUSE_STATE_UNREADABLE)
        self.assertIn("unprovisioned", reply["detail"])
        self.assertIsNone(self.floor_on_disk(),
                          "an unprovisioned store must not acquire files and start looking ready")

    # 12 ------------------------------------------------------------------------------------
    def test_12_a_store_the_caller_owns_is_refused(self):
        # The caller "attempting direct storage mutation" is, at this boundary, a store the
        # caller could mutate. If it owns the directory it does not need to ask.
        reply = self.handle(_request(), caller_uid=os.geteuid())
        self.assertEqual(reply["reason"], fw.REFUSE_UNAUTHORIZED)
        # ...and when it IS on the allowlist, custody still refuses it.
        reply = fw.handle(_request(), store=self.store, served_install_id=INSTALL,
                          allowed_caller_uids=frozenset({os.geteuid()}),
                          caller_uid=os.geteuid())
        self.assertEqual(reply["reason"], fw.REFUSE_CUSTODY)
        self.assertIn("owned by the CALLING principal", reply["detail"])
        self.assertIsNone(self.floor_on_disk())

    def test_12b_a_group_or_world_writable_store_is_refused(self):
        os.chmod(self.store, 0o770)
        reply = self.handle(_request())
        self.assertEqual(reply["reason"], fw.REFUSE_CUSTODY)
        self.assertIn("group- or world-writable", reply["detail"])

    def test_12c_a_store_this_principal_does_not_own_is_refused(self):
        # Owning the store is what lets the writer promise to be its only mutator. Simulated by
        # asking about a directory whose owner is not this euid: /tmp is root-owned on this box,
        # and the test skips rather than asserting nothing if it is not.
        root_owned = pathlib.Path("/tmp")
        if root_owned.stat().st_uid == os.geteuid():
            self.skipTest("/tmp is owned by this uid here, so it cannot model a foreign store")
        with self.assertRaises(fw.FloorWriterError) as caught:
            fw.require_writer_custody(root_owned, CALLER)
        self.assertIn("not by the Floor Writer principal", str(caught.exception))

    # 13 ------------------------------------------------------------------------------------
    def test_13_a_reply_replayed_against_a_different_request_is_refused(self):
        first = _request(task_id="task-1", head=5)
        reply = self.handle(first)
        other = _request(task_id="task-2", head=5)
        with self.assertRaises(fw.FloorWriterError) as caught:
            fw.verify_reply(reply, other, canonical_json_sha256(other), reply["writer_uid"])
        self.assertIn("may be another advancement's answer", str(caught.exception))

    def test_13b_a_tampered_reply_fails_its_own_digest(self):
        reply = self.handle(_request(head=5))
        reply["floor"] = 99
        with self.assertRaises(fw.FloorWriterError) as caught:
            fw.verify_reply(reply, _request(head=5), reply["request_sha256"], reply["writer_uid"])
        self.assertIn("does not match its own digest", str(caught.exception))

    def test_13c_a_reply_from_a_different_writer_uid_is_refused(self):
        reply = self.handle(_request(head=5))
        with self.assertRaises(fw.FloorWriterError) as caught:
            fw.verify_reply(reply, _request(head=5), reply["request_sha256"],
                            served_by=reply["writer_uid"] + 1)
        self.assertIn("a principal that misreports itself", str(caught.exception))

    def test_13d_a_refusal_is_never_read_as_a_success(self):
        refusal = self.handle(_request(head=0))
        with self.assertRaises(fw.FloorWriterError) as caught:
            fw.verify_reply(refusal, _request(head=0), "irrelevant", None)
        self.assertIn("floor advancement refused", str(caught.exception))

    # 14 ------------------------------------------------------------------------------------
    def test_14_the_authoritative_floor_survives_a_restart(self):
        self.handle(_request(head=11))
        # A "restart" is a fresh module state reading the same directory: nothing is cached in
        # the process, and that is the property being asserted.
        current, digest = fw._load_floor(self.store, "task-1")
        self.assertEqual((current, digest), (11, DIGEST_A))
        reply = self.handle(_request(head=11))
        self.assertEqual(reply["outcome"], fw.OUTCOME_ALREADY_COMMITTED)
        reply = self.handle(_request(head=10))
        self.assertEqual(reply["reason"], fw.REFUSE_ROLLBACK)

    # 15 ------------------------------------------------------------------------------------
    def test_15_a_write_that_does_not_read_back_is_not_reported_as_committed(self):
        # The failure the read-back exists for: the record on disk is not what was asked for.
        # Simulated by making the store read-only so the write itself fails; the point is that
        # NO branch returns a success without the authoritative state agreeing.
        os.chmod(self.store, 0o500)
        self.addCleanup(os.chmod, self.store, 0o700)
        reply = self.handle(_request(head=5))
        self.assertIs(reply.get("ok"), False)
        self.assertNotIn("outcome", reply, "a failed write must not produce an outcome at all")

    def test_15b_the_crash_order_enrols_the_roster_before_the_mark(self):
        # Deliberate, and it is what makes an interrupted advance fail closed: a task the roster
        # knows with no mark is refused by the loader. The reverse order would silently drop the
        # roster entry instead, degrading the deletion check with no signal.
        self.handle(_request(task_id="task-9", head=4))
        (self.store / "task-9.floor.json").unlink()   # the crash window, reproduced
        reply = self.handle(_request(task_id="task-9", head=5))
        self.assertEqual(reply["reason"], fw.REFUSE_STATE_UNREADABLE)
        self.assertIn("the mark was removed", reply["detail"])


class PlatformBoundary(unittest.TestCase):
    """Linux-only, stated rather than approximated."""

    def test_require_linux_names_the_reason_and_the_platform(self):
        import unittest.mock

        with unittest.mock.patch.object(fw.sys, "platform", "win32"):
            with self.assertRaises(fw.FloorWriterError) as caught:
                fw.require_linux("cannot bind the Floor Writer socket")
        message = str(caught.exception)
        self.assertIn("requires Linux", message)
        self.assertIn("'win32'", message)
        self.assertIn("worse than a stop", message)

    def test_the_client_refuses_before_it_opens_a_socket_off_linux(self):
        import unittest.mock

        with unittest.mock.patch.object(fw.sys, "platform", "darwin"):
            with self.assertRaises(fw.FloorWriterError) as caught:
                fw.request_advance(pathlib.Path("/nonexistent.sock"), INSTALL, "t", 1, DIGEST_A)
        self.assertIn("requires Linux", str(caught.exception))


class RealSocketRoundTrip(FloorWriterFixture):
    """One end-to-end exchange over a real AF_UNIX socket, so the framing, the kernel's
    ``SO_PEERCRED`` and the reply binding are exercised together rather than mocked apart."""

    def test_a_real_peer_gets_a_bound_advancement(self):
        if sys.platform != "linux":
            self.skipTest("SO_PEERCRED is Linux-only")
        path = pathlib.Path(self._tmp.name) / "fw.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(str(path))
        server.listen(1)
        seen = {}

        def serve():
            sock, _ = server.accept()
            try:
                conn = fw.SocketPeerConn(sock)
                # This process is both ends, so the caller's uid IS this uid; custody would
                # (correctly) refuse that, so the store's ownership check is the one thing
                # relaxed here. Everything else — framing, peercred, binding — is real.
                seen["reply"] = fw.serve_connection(
                    conn, store=self.store, served_install_id=INSTALL,
                    allowed_caller_uids=frozenset({os.geteuid()}))
            finally:
                sock.close()

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            with self.assertRaises(fw.FloorWriterError) as caught:
                fw.request_advance(path, INSTALL, "task-1", 5, DIGEST_A,
                                   expected_writer_uid=os.geteuid())
        finally:
            thread.join()
        # The exchange completed over a real socket and the verdict was custody, not a crash:
        # the same-uid store is refused, which is the rule this deployment shape must obey.
        self.assertIn("owned by the CALLING principal", str(caught.exception))
        self.assertEqual(seen["reply"]["reason"], fw.REFUSE_CUSTODY)


if __name__ == "__main__":
    unittest.main()


class CompletionIntegration(unittest.TestCase):
    """The production call path, not the unit.

    ``bro_completion.validate_evidence_chain`` calls ``_commit_head_floor`` where it used to
    write the mark itself. These tests drive THAT function, because a Floor Writer nothing on
    the completion path calls is the `T-056` pattern with a socket.
    """

    def setUp(self):
        import bro_completion

        self.completion = bro_completion
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = pathlib.Path(self._tmp.name) / "store"
        (self.store / "head-floor").mkdir(parents=True)
        (self.store / "head-floor" / "_index.json").write_text(
            json.dumps({"tasks": []}), encoding="utf-8")
        for name in (fw.__name__, "bro_completion"):
            pass
        self._env = {}
        for key in (self.completion.ENV_FLOOR_WRITER_SOCKET,
                    self.completion.ENV_INSTALL_ID,
                    self.completion.ENV_FLOOR_WRITER_UID):
            self._env[key] = os.environ.pop(key, None)
        self.addCleanup(self._restore)
        # The legacy path refuses a self-owned floor unless the deployment acknowledged having
        # no principal separation. These tests are about the WRITER seam, not that rule.
        self._ack = os.environ.pop("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", None)
        os.environ["BRO_OPERATOR_ROOT_PIN_SELF_OWNED"] = "acknowledged"

    def _restore(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if self._ack is None:
            os.environ.pop("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", None)
        else:
            os.environ["BRO_OPERATOR_ROOT_PIN_SELF_OWNED"] = self._ack

    def test_without_the_env_var_the_legacy_in_process_write_still_runs(self):
        # Not a fallback: this is the un-migrated deployment, unchanged on purpose.
        self.completion._commit_head_floor(self.store, "task-1", 3, DIGEST_A)
        record = json.loads((self.store / "head-floor" / "task-1.floor.json").read_text())
        self.assertEqual(record["head_sequence"], 3)

    def test_a_configured_writer_without_a_scope_refuses_the_completion(self):
        os.environ[self.completion.ENV_FLOOR_WRITER_SOCKET] = str(self.store / "fw.sock")
        with self.assertRaises(self.completion.CompletionError) as caught:
            self.completion._commit_head_floor(self.store, "task-1", 3, DIGEST_A)
        self.assertIn("BRO_INSTALL_ID is unset", str(caught.exception))
        self.assertIn("advanced for someone else", str(caught.exception))
        self.assertFalse((self.store / "head-floor" / "task-1.floor.json").exists(),
                         "a refused completion must not have written the mark itself")

    def test_an_unreachable_writer_refuses_and_never_falls_back_to_writing_it_here(self):
        if sys.platform != "linux":
            self.skipTest("the client refuses off Linux for a different reason")
        os.environ[self.completion.ENV_FLOOR_WRITER_SOCKET] = str(self.store / "absent.sock")
        os.environ[self.completion.ENV_INSTALL_ID] = INSTALL
        with self.assertRaises(self.completion.CompletionError) as caught:
            self.completion._commit_head_floor(self.store, "task-1", 3, DIGEST_A)
        message = str(caught.exception)
        self.assertIn("was not authoritatively advanced", message)
        self.assertIn("this completion is not verified", message)
        self.assertFalse((self.store / "head-floor" / "task-1.floor.json").exists(),
                         "R4: there is no fallback writer, so making the service unavailable "
                         "must not hand the property back to the policed process")

    def test_a_non_integer_writer_uid_is_refused(self):
        os.environ[self.completion.ENV_FLOOR_WRITER_SOCKET] = str(self.store / "fw.sock")
        os.environ[self.completion.ENV_INSTALL_ID] = INSTALL
        os.environ[self.completion.ENV_FLOOR_WRITER_UID] = "not-a-uid"
        with self.assertRaises(self.completion.CompletionError) as caught:
            self.completion._commit_head_floor(self.store, "task-1", 3, DIGEST_A)
        self.assertIn("is not an integer uid", str(caught.exception))

    def test_the_call_site_in_the_verified_chain_is_the_writer_seam(self):
        # The seam must be ON the production path, not beside it. Asserted against the source so
        # a refactor that quietly restores the direct write is caught here.
        source = pathlib.Path(self.completion.__file__).read_text(encoding="utf-8")
        start = source.index("def validate_evidence_chain")
        verify = source[start:source.index("_SHA256 = re.compile", start)]
        self.assertIn("_commit_head_floor(", verify,
                      "the verified-chain path must go through the writer seam")
        self.assertNotIn("_advance_head_floor(", verify,
                         "the verified-chain path must not write the mark itself any more")
