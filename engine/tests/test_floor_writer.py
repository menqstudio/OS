"""Floor Writer FW-1 — §7's acceptance criteria and negative matrix.

Every negative is refused **by name**, from the closed enum in §4.2, and each has a positive
control beside it so a refuse-everything arm cannot satisfy it. The numbering follows §7 so an
auditor can walk the list in order.

Three classes of test, and the difference is stated rather than blurred, because conflating them
is what made the first attempt's peer tests green and meaningless:

* the protocol and state negatives drive ``handle`` directly with an authenticated uid supplied
  as a PARAMETER. They test the rule, not the kernel, and they are not evidence about either;
* ``RunnerStartup`` runs the real entry point as a PROCESS and asks a service manager's question:
  what exit code, what message, and — the one that matters — was a socket left behind;
* the cross-principal boundary is **not in this file and cannot be**. A uid passed as an argument
  is not ``SO_PEERCRED``, and a mode is not an ``EACCES``. Those live in
  ``engine/ci/floor_writer_boundary_proof.sh``, which provisions as root under FOUR real accounts
  and measures the three per-op properties over a real AF_UNIX socket, and in
  ``engine/tests/test_floor_writer_durability.py``, which reads the commit's syscall order out of
  the kernel and kills a writing process twelve times.

The previous attempt's same-uid round trip is exactly why the split is written down: it was green
and the deployment it claimed to model could not connect at all.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import floor_writer as fw

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
INSTALL = "install-1"
LINUX_ONLY = "the Floor Writer authenticates with SO_PEERCRED, which requires Linux (FW-2 is Windows)"
_LINUX = sys.platform == "linux"

#: A uid that is not this process's. The rule under test is per-op admission, and a fixture using
#: this process's own uid would be asserting a weaker rule than the one shipped.
CALLER = (os.geteuid() + 1) if _LINUX else 0
OTHER = (os.geteuid() + 2) if _LINUX else 0


def _advance(task_id="task-1", head=5, digest=DIGEST_A, **overrides):
    request = {"op": fw.OP_ADVANCE, "protocol": fw.FLOOR_PROTOCOL, "task_id": task_id,
               "head_sequence": head, "evidence_head_sha256": digest}
    request.update(overrides)
    return request


def _encode(document):
    """The encoder the transport actually uses -- measuring anything else measures a guess."""
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _get(task_id="task-1", **overrides):
    request = {"op": fw.OP_GET, "protocol": fw.FLOOR_PROTOCOL, "task_id": task_id}
    request.update(overrides)
    return request


@unittest.skipUnless(_LINUX, LINUX_ONLY)
class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = pathlib.Path(self._tmp.name)
        self.marks_root = root / "marks"
        (self.marks_root / INSTALL).mkdir(parents=True, mode=0o700)
        self.config_path = root / "fw-config.json"
        self.config_path.write_text(json.dumps({
            "install_id": INSTALL, "marks_root": str(self.marks_root),
            "socket_path": str(root / "fw.sock"), "generation": 7,
            "peers": {fw.OP_GET: [CALLER], fw.OP_ADVANCE: [CALLER]}}), encoding="utf-8")
        self.config = fw.load_service_config(
            {fw.ENV_SERVICE_CONFIG: str(self.config_path)})
        # Provisioning writes the first authoritative document. §4.2: a floor is not
        # client-bootstrappable, so the tests do not bootstrap one either.
        fw.commit_state(self.config, {"install_id": INSTALL, "generation": 7,
                                      "roster": [], "floors": {}})

    def ask(self, request, peer_uid=CALLER):
        return fw.handle(request, config=self.config, peer_uid=peer_uid)

    def document(self):
        return json.loads((self.config.marks_dir / fw.STATE_FILE).read_text(encoding="utf-8"))


class Negatives(ServiceFixture):
    """§7's numbered list."""

    # 2 -------------------------------------------------------------------------------------
    def test_02_a_lower_head_is_stale_floor_and_writes_nothing(self):
        self.assertEqual(self.ask(_advance(head=9))["outcome"], fw.OUTCOME_ADVANCED)
        before = self.document()
        reply = self.ask(_advance(head=4))
        self.assertEqual(reply["reason"], "stale_floor")
        self.assertNotIn("outcome", reply, "§4.2: a refusal carries no result field at all")
        self.assertEqual(self.document(), before, "a refused rollback must not touch the state")

    def test_02b_a_lying_client_cannot_lower_the_floor_with_its_own_get(self):
        # §7 negative 2, driven with a deliberately-lying client: floor.get's answer is a
        # courtesy, and ignoring it changes nothing, because advance re-checks the store.
        self.ask(_advance(head=9))
        got = self.ask(_get())
        self.assertEqual(got["head_sequence"], 9)
        reply = self.ask(_advance(head=2))   # the client pretends it read 1
        self.assertEqual(reply["reason"], "stale_floor")

    # 3 -------------------------------------------------------------------------------------
    def test_03_same_sequence_with_a_different_head_is_head_digest_changed(self):
        self.ask(_advance(head=5, digest=DIGEST_A))
        reply = self.ask(_advance(head=5, digest=DIGEST_B))
        self.assertEqual(reply["reason"], "head_digest_changed")

    # 4 -------------------------------------------------------------------------------------
    def test_04_advancing_twice_with_the_same_head_is_idempotent_and_writes_once(self):
        # Required because validate_evidence_chain is called TWICE per completion.
        first = self.ask(_advance(head=5))
        self.assertEqual(first["outcome"], fw.OUTCOME_ADVANCED)
        before = self.document()
        second = self.ask(_advance(head=5))
        self.assertEqual(second["outcome"], fw.OUTCOME_IDEMPOTENT)
        self.assertEqual(self.document(), before, "an idempotent replay commits nothing")

    # 5 -------------------------------------------------------------------------------------
    def test_05_a_request_carrying_install_id_is_malformed_not_ignored(self):
        reply = self.ask(_advance(install_id=INSTALL))
        self.assertEqual(reply["reason"], "malformed")
        self.assertIn("install_id", reply["detail"])
        self.assertIn("the scope is the service's own", reply["detail"])
        # ...and the positive control: the same request without the field succeeds.
        self.assertEqual(self.ask(_advance())["outcome"], fw.OUTCOME_ADVANCED)

    # 6 -------------------------------------------------------------------------------------
    def test_06_per_op_admission_is_not_the_union_of_the_lists(self):
        # A peer admitted for get only must not be able to advance, and vice versa. §1.8.
        root = pathlib.Path(self._tmp.name)
        split = root / "split.json"
        split.write_text(json.dumps({
            "install_id": INSTALL, "marks_root": str(self.marks_root),
            "socket_path": str(root / "fw.sock"), "generation": 7,
            "peers": {fw.OP_GET: [CALLER], fw.OP_ADVANCE: [OTHER]}}), encoding="utf-8")
        config = fw.load_service_config({fw.ENV_SERVICE_CONFIG: str(split)})
        denied = fw.handle(_advance(), config=config, peer_uid=CALLER)
        self.assertEqual(denied["reason"], "peer_denied")
        self.assertIn("admission to one op is not admission to another", denied["detail"])
        allowed = fw.handle(_get(), config=config, peer_uid=CALLER)
        self.assertTrue(allowed["ok"], "the same peer IS admitted to the op it is listed for")

    def test_06b_scope_pin_is_out_of_scope_for_fw1_and_says_so(self):
        reply = self.ask({"op": fw.OP_SCOPE_PIN, "protocol": fw.FLOOR_PROTOCOL})
        self.assertEqual(reply["reason"], "unknown_op")
        self.assertIn("FW-3", reply["detail"])

    # 7 -------------------------------------------------------------------------------------
    def test_07_an_unlisted_peer_is_denied_and_the_refusal_is_not_an_oracle(self):
        reply = self.ask(_advance(), peer_uid=OTHER)
        self.assertEqual(reply["reason"], "peer_denied")
        self.assertNotIn(str(CALLER), reply["detail"].replace(str(OTHER), ""))
        self.assertIsNone(self.document()["floors"].get("task-1"))

    def test_07b_an_unauthenticated_peer_is_denied(self):
        self.assertEqual(self.ask(_advance(), peer_uid=None)["reason"], "peer_denied")
        # bool is an int subclass; a stray True must never pass for uid 1.
        self.assertEqual(self.ask(_advance(), peer_uid=True)["reason"], "peer_denied")

    # 8 -------------------------------------------------------------------------------------
    def test_08_malformed_shapes_are_each_refused_for_their_own_reason(self):
        for request, expected in [
            (_advance(head=0), "positive integer"),
            (_advance(head="5"), "positive integer"),
            (_advance(head=True), "positive integer"),
            (_advance(digest="nope"), "64 lowercase hex"),
            (_advance(task_id="../escape"), "traversal segment"),
            ({"op": fw.OP_ADVANCE, "protocol": "brops.floor-writer.v2", "task_id": "t",
              "head_sequence": 1, "evidence_head_sha256": DIGEST_A}, "speaks"),
        ]:
            with self.subTest(expected=expected):
                reply = self.ask(request)
                self.assertEqual(reply["reason"], "malformed")
                self.assertIn(expected, reply["detail"])

    def test_08b_a_missing_field_is_refused(self):
        request = _advance()
        del request["evidence_head_sha256"]
        self.assertIn("missing field(s) ['evidence_head_sha256']", self.ask(request)["detail"])

    # 10 ------------------------------------------------------------------------------------
    def test_10_concurrent_advances_leave_the_maximum_and_keep_every_task_rostered(self):
        heads = [3, 9, 1, 7, 12, 5, 12, 2]
        replies = [None] * len(heads)

        def run(i):
            replies[i] = self.ask(_advance(task_id="task-1", head=heads[i]))

        threads = [threading.Thread(target=run, args=(i,)) for i in range(len(heads))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        document = self.document()
        self.assertEqual(document["floors"]["task-1"]["head_sequence"], max(heads))
        for reply in replies:
            if reply.get("ok"):
                self.assertLessEqual(reply["head_sequence"], max(heads))
            else:
                self.assertEqual(reply["reason"], "stale_floor",
                                 "the only permitted loss is a refused rollback")
        # ...and a second task joins the roster without displacing the first.
        self.ask(_advance(task_id="task-2", head=1))
        self.assertEqual(sorted(self.document()["roster"]), ["task-1", "task-2"])

    # 11 ------------------------------------------------------------------------------------
    def test_11_a_crash_before_the_rename_leaves_the_old_document_intact(self):
        self.ask(_advance(head=5))
        before = self.document()
        # The crash window, reproduced: a temp file exists and the rename never happened.
        temporary = self.config.marks_dir / f".{fw.STATE_FILE}.tmp"
        temporary.write_text('{"install_id":"install-1","roster":["task-1","ghost"],'
                             '"floors":{},"generation":7}', encoding="utf-8")
        self.assertEqual(self.document(), before,
                         "an unrenamed temp file is not the authoritative document")
        reply = self.ask(_advance(head=6))
        self.assertEqual(reply["outcome"], fw.OUTCOME_ADVANCED)
        self.assertEqual(sorted(self.document()["roster"]), ["task-1"],
                         "the abandoned temp file contributed nothing to the roster")

    def test_11b_roster_and_floor_move_in_one_commit_so_no_half_state_exists(self):
        # The B5 property, asserted on the state rather than on the code: after any advance the
        # roster names exactly the tasks that have floors. There is no ordering between them to
        # be interrupted, because there is one document and one rename.
        for task, head in (("t1", 3), ("t2", 4), ("t1", 9)):
            self.ask(_advance(task_id=task, head=head))
            document = self.document()
            self.assertEqual(sorted(document["roster"]), sorted(document["floors"]),
                             "roster membership and floor state must never disagree")

    def test_11c_a_rostered_task_whose_floor_is_gone_is_mark_removed(self):
        # The roster is still an independent semantic fact: if the two halves are made to
        # disagree by hand, the service refuses rather than healing.
        self.ask(_advance(task_id="t1", head=3))
        document = self.document()
        document["floors"] = {}
        fw.commit_state(self.config, document)
        reply = self.ask(_advance(task_id="t1", head=4))
        self.assertEqual(reply["reason"], "mark_removed")
        self.assertIn("the roster names", reply["detail"])

    def test_11d_a_corrupt_document_refuses_and_is_never_rebuilt_from_the_directory(self):
        self.ask(_advance(head=5))
        (self.config.marks_dir / fw.STATE_FILE).write_text("{tru", encoding="utf-8")
        reply = self.ask(_advance(head=6))
        self.assertEqual(reply["reason"], "mark_corrupt")
        self.assertTrue(fw.NEVER_HEAL_FROM_DIRECTORY)
        # The module holds no rebuild path at all, which is the Architect's standing constraint:
        # healing from the filesystem would make the explicit roster stop being the authority the
        # moment it disagreed with what files exist.
        source = (ROOT / "runtime" / "floor_writer.py").read_text(encoding="utf-8")
        self.assertNotIn("def rebuild", source)
        self.assertNotIn("def repair", source)

    def test_11e_an_absent_document_is_unprovisioned_not_empty(self):
        (self.config.marks_dir / fw.STATE_FILE).unlink()
        reply = self.ask(_advance(head=5))
        self.assertEqual(reply["reason"], "floor_absent")
        self.assertIn("unprovisioned", reply["detail"])

    def test_11f_a_document_naming_another_install_is_refused(self):
        document = self.document()
        document["install_id"] = "install-2"
        (self.config.marks_dir / fw.STATE_FILE).write_text(
            json.dumps(document), encoding="utf-8")
        reply = self.ask(_advance(head=5))
        self.assertEqual(reply["reason"], "mark_corrupt")
        self.assertIn("different install", reply["detail"])

    # 12 ------------------------------------------------------------------------------------
    def test_11g_a_store_from_another_provisioning_is_refused(self):
        # §1.10. The generation is minted into BOTH the config and the store. A config
        # re-provisioned over a store that was not would serve `generation: 8` while answering
        # from generation 7's floors — "visibly new" reporting over silently old state, which is
        # the confusion the number exists to remove.
        self.ask(_advance(head=5))
        document = self.document()
        document["generation"] = 6
        (self.config.marks_dir / fw.STATE_FILE).write_text(json.dumps(document), encoding="utf-8")
        reply = self.ask(_get())
        self.assertEqual(reply["reason"], "mark_corrupt")
        self.assertIn("different provisionings", reply["detail"])
        # The positive control: the same document at the configured generation is served.
        document["generation"] = 7
        (self.config.marks_dir / fw.STATE_FILE).write_text(json.dumps(document), encoding="utf-8")
        self.assertEqual(self.ask(_get())["head_sequence"], 5)

    def test_12_a_config_the_service_cannot_use_refuses_to_start(self):
        root = pathlib.Path(self._tmp.name)
        for name, document, expected in [
            ("no-install", {"marks_root": "/x", "socket_path": "/x/s", "generation": 1,
                            "peers": {fw.OP_GET: [1], fw.OP_ADVANCE: [1]}}, "install_id"),
            ("no-socket", {"install_id": INSTALL, "marks_root": "/x", "generation": 1,
                           "peers": {fw.OP_GET: [1], fw.OP_ADVANCE: [1]}}, "socket_path"),
            ("no-generation", {"install_id": INSTALL, "marks_root": "/x", "socket_path": "/x/s",
                               "peers": {fw.OP_GET: [1], fw.OP_ADVANCE: [1]}}, "generation"),
            ("no-peers", {"install_id": INSTALL, "marks_root": "/x", "socket_path": "/x/s",
                          "generation": 1}, "peer allowlist"),
            ("empty-op", {"install_id": INSTALL, "marks_root": "/x", "socket_path": "/x/s",
                          "generation": 1, "peers": {fw.OP_GET: [], fw.OP_ADVANCE: [1]}},
             "no peers"),
            ("bool-uid", {"install_id": INSTALL, "marks_root": "/x", "socket_path": "/x/s",
                          "generation": 1, "peers": {fw.OP_GET: [True], fw.OP_ADVANCE: [1]}},
             "as a peer uid"),
            ("missing-op", {"install_id": INSTALL, "marks_root": "/x", "socket_path": "/x/s",
                            "generation": 1, "peers": {fw.OP_GET: [1]}}, "which FW-1 serves"),
        ]:
            with self.subTest(case=name):
                path = root / f"{name}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(fw.FloorWriterError) as caught:
                    fw.load_service_config({fw.ENV_SERVICE_CONFIG: str(path)})
                self.assertEqual(caught.exception.reason, "scope_unavailable")
                self.assertIn(expected, caught.exception.detail)

    def test_12b_an_absent_config_variable_refuses(self):
        with self.assertRaises(fw.FloorWriterError) as caught:
            fw.load_service_config({})
        self.assertIn("is unset", caught.exception.detail)

    # The positive control for the whole file: the ordinary path works.
    def test_00_the_ordinary_advance_succeeds_and_carries_the_generation(self):
        reply = self.ask(_advance(head=5))
        self.assertEqual(reply["outcome"], fw.OUTCOME_ADVANCED)
        self.assertEqual(reply["head_sequence"], 5)
        self.assertEqual(reply["evidence_head_sha256"], DIGEST_A)
        self.assertEqual(reply["generation"], 7)
        self.assertNotIn("install_id", reply, "the scope is never on this wire, in either direction")
        self.assertEqual(self.document()["floors"]["task-1"],
                         {"head_sequence": 5, "evidence_head_sha256": DIGEST_A})
        self.assertEqual(self.document()["roster"], ["task-1"])


@unittest.skipUnless(_LINUX, LINUX_ONLY)
class FramingBoundary(ServiceFixture):
    """§7 negative 8: the cap tested on BOTH sides of the number."""

    def test_the_cap_is_one_number_and_a_frame_at_exactly_the_cap_is_accepted(self):
        self.assertEqual(fw.MAX_FLOOR_FRAME_BYTES, 4096)
        payload = b"x" * fw.MAX_FLOOR_FRAME_BYTES
        self.assertEqual(len(payload), fw.MAX_FLOOR_FRAME_BYTES)
        # The refusal is strictly greater-than, so the boundary value itself is legal.
        over = fw.MAX_FLOOR_FRAME_BYTES + 1
        self.assertGreater(over, fw.MAX_FLOOR_FRAME_BYTES)

    def test_an_oversize_task_id_cannot_reach_the_store(self):
        reply = self.ask(_advance(task_id="x" * 129))
        self.assertEqual(reply["reason"], "malformed")

    def test_the_cap_is_confirmed_through_the_real_encoder(self):
        """§1.7 defers this arithmetic to FW-1 rather than asserting it in the design.

        The design predicts the largest legal request lands "well under 512 bytes". This measures
        it through the encoder that actually puts bytes on the wire, so the claim cannot survive a
        change to the request shape that breaks it.
        """
        largest = _advance(task_id="t" * 128, head=2 ** 63 - 1, digest="f" * 64)
        self.assertTrue(self.ask(dict(largest, task_id="t" * 128))["ok"],
                        "the largest frame measured must be one the validator actually accepts")
        size = len(_encode(largest))
        self.assertLess(size, 512, "the design's predicted bound")
        self.assertLessEqual(size * 8, fw.MAX_FLOOR_FRAME_BYTES,
                             "§1.7 wants roughly eight-fold headroom, not a cap that merely fits")

    def test_no_reply_the_service_can_produce_exceeds_the_cap(self):
        """A caller must not be able to turn its own refusal into a dropped connection.

        The request is bounded by the frame the service will read, but a refusal quotes the
        request back, so an unbounded quote would let a 4KB `op` produce a reply the writer cannot
        send -- and `_write_frame` raises rather than truncating, which the caller would see as a
        closed socket instead of a named refusal. `_refusal` caps the detail at 512 bytes; nothing
        tested that until now.
        """
        room = fw.MAX_FLOOR_FRAME_BYTES - 200
        for name, request in [
            ("a 4KB op", {"op": "z" * room, "protocol": fw.FLOOR_PROTOCOL}),
            ("a 4KB field name", {"op": fw.OP_GET, "protocol": fw.FLOOR_PROTOCOL,
                                  "task_id": "t", "q" * room: 1}),
            ("a 4KB task_id", _advance(task_id="t" * room)),
            ("a 4KB digest", _advance(digest="f" * room)),
        ]:
            with self.subTest(case=name):
                self.assertLessEqual(len(_encode(request)), fw.MAX_FLOOR_FRAME_BYTES,
                                     "the fixture must be a request the service would READ")
                reply = self.ask(request)
                self.assertFalse(reply["ok"])
                self.assertLessEqual(
                    len(_encode(reply)), fw.MAX_FLOOR_FRAME_BYTES,
                    "the refusal must fit the frame it has to be sent in")


@unittest.skipUnless(_LINUX, LINUX_ONLY)
class RunnerStartup(unittest.TestCase):
    """``run_floor_writer.py`` as a PROCESS: every bad start is a refusal, and none of them binds.

    These drive the real entry point through ``subprocess`` rather than calling ``start()`` in
    this interpreter, because the property under test is what a service manager observes: an exit
    code, a message on stderr, and — the one that matters — **no socket**. A service that refused
    its configuration and left an endpoint behind would be advertising a promise it cannot keep,
    and only a process can be asked whether it did that.

    There is deliberately no positive control that reaches ``serve_forever`` here: that path never
    returns, and it is proved instead by ``engine/ci/floor_writer_boundary_proof.sh``, which
    starts this same runner under a real service account and gets answers out of it.
    """

    RUNNER = str(ROOT / "runtime" / "run_floor_writer.py")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        self.marks_root = self.root / "marks"
        (self.marks_root / INSTALL).mkdir(parents=True, mode=0o700)
        self.socket_dir = self.root / "run"
        self.socket_dir.mkdir(mode=0o750)
        self.socket_path = self.socket_dir / "fw.sock"

    def config(self, **overrides):
        document = {"install_id": INSTALL, "marks_root": str(self.marks_root),
                    "socket_path": str(self.socket_path), "generation": 4,
                    "peers": {fw.OP_GET: [CALLER], fw.OP_ADVANCE: [CALLER]}}
        document.update(overrides)
        for key in [k for k, v in document.items() if v is None]:
            del document[key]
        path = self.root / "fw-config.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def start(self, config_path=None):
        """Run the entry point to completion. It must always complete: there is no exit 0 path."""
        environment = {k: v for k, v in os.environ.items() if k != fw.ENV_SERVICE_CONFIG}
        if config_path is not None:
            environment[fw.ENV_SERVICE_CONFIG] = str(config_path)
        result = subprocess.run([sys.executable, self.RUNNER], env=environment,
                                capture_output=True, text=True, timeout=60)
        self.assertFalse(self.socket_path.exists(),
                         "a refusing service left an endpoint behind; a socket that exists is a "
                         "promise, and this start made none it could keep")
        return result

    def test_a_bare_start_with_no_config_variable_refuses(self):
        result = self.start()
        self.assertEqual(result.returncode, 2)
        self.assertIn(fw.ENV_SERVICE_CONFIG, result.stderr)

    def test_a_config_variable_naming_nothing_refuses(self):
        result = self.start(self.root / "absent.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read", result.stderr)

    def test_a_malformed_config_refuses(self):
        path = self.root / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        result = self.start(path)
        self.assertEqual(result.returncode, 2)

    def test_a_config_without_a_per_op_allowlist_refuses(self):
        result = self.start(self.config(peers=None))
        self.assertEqual(result.returncode, 2)
        self.assertIn("per-op peer allowlist", result.stderr)

    def test_a_config_without_a_generation_refuses(self):
        result = self.start(self.config(generation=None))
        self.assertEqual(result.returncode, 2)
        self.assertIn("generation", result.stderr)

    def test_a_marks_store_that_does_not_exist_is_a_custody_refusal(self):
        result = self.start(self.config(marks_root=str(self.root / "absent")))
        self.assertEqual(result.returncode, 4)

    def test_a_group_writable_marks_store_is_a_custody_refusal(self):
        (self.marks_root / INSTALL).chmod(0o770)
        result = self.start(self.config())
        self.assertEqual(result.returncode, 4)
        self.assertIn("group- or world-writable", result.stderr)

    def test_a_group_writable_socket_directory_is_a_custody_refusal(self):
        self.socket_dir.chmod(0o770)
        result = self.start(self.config())
        self.assertEqual(result.returncode, 4)
        self.assertIn("socket directory", result.stderr)

    def test_a_store_with_no_authoritative_document_refuses_rather_than_starting_empty(self):
        # Custody is fine and the config is fine; the store was never provisioned. §4.2: a floor
        # is not client-bootstrappable, and it is not service-bootstrappable at start either.
        result = self.start(self.config())
        self.assertEqual(result.returncode, 2)
        self.assertIn("unprovisioned", result.stderr)


class PlatformBoundary(unittest.TestCase):
    """FW-2 is Windows and is not built; this stops rather than approximating."""

    def test_require_linux_names_the_platform_and_the_slice(self):
        import unittest.mock

        with unittest.mock.patch.object(fw.sys, "platform", "win32"):
            with self.assertRaises(fw.FloorWriterError) as caught:
                fw.require_linux("cannot bind the Floor Writer socket")
        self.assertIn("requires Linux", caught.exception.detail)
        self.assertIn("FW-2", caught.exception.detail)
        self.assertEqual(caught.exception.reason, "scope_unavailable")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
