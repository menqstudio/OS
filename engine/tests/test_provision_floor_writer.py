"""B6 — the Floor Writer's provisioning path, refusal by refusal.

Everything here runs WITHOUT root, by resolving principals through injected lookups. That is
deliberate and it is also the limit of this file: it proves the DECISIONS provisioning makes, not
the ownership it sets. The ownership is proved where it can only be proved — by real accounts over
a real kernel boundary, in ``engine/ci/floor_writer_boundary_proof.sh``, which runs the actual
``apply()`` as root and then attacks the result from the caller principal.

Two things are kept apart on purpose, because conflating them is what made the first attempt's
peer tests green and meaningless:

* a refusal computed from resolved facts is testable here and is tested here;
* a mode, an owner and an ``EACCES`` are properties of a filesystem and a kernel, and no amount of
  mocking in this file is evidence about them.
"""

import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import floor_writer as fw
import provision_floor_writer as pfw

LINUX_ONLY = "provisioning is Linux-only in FW-1; Windows is FW-2 and is not built"
_LINUX = sys.platform == "linux"

SERVICE_UID = 4400
CALLER_UID = 4401
OTHER_UID = 4402

#: The lookup table the tests inject in place of /etc/passwd, so the decisions under test are the
#: module's and not the box's.
_USERS = {"fw-svc": (SERVICE_UID, SERVICE_UID), "fw-caller": (CALLER_UID, CALLER_UID),
          "fw-other": (OTHER_UID, OTHER_UID), "root": (0, 0)}


def _resolve_user(name):
    if name in _USERS:
        return _USERS[name]
    raise pfw.ProvisionError(pfw.EXIT_CONFIG, f"no such user {name!r}")


class _Args:
    def __init__(self, **kw):
        self.install_id = kw.get("install_id", "install-1")
        self.service_user = kw.get("service_user", "fw-svc")
        self.caller_group = kw.get("caller_group", "fw-group")
        self.marks_root = kw.get("marks_root", "/var/lib/brops-floor/marks")
        self.socket_path = kw.get("socket_path", "/run/brops-floor/fw.sock")
        self.config = kw.get("config", "/etc/brops/floor-writer.json")
        self.peer = kw.get("peer", ["floor.get=fw-caller", "floor.advance=fw-caller"])
        self.reprovision = kw.get("reprovision", False)


class PlanFixture(unittest.TestCase):
    """Every principal lookup injected; the reachable set is the caller and the service."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = pathlib.Path(self._tmp.name) / "floor-writer.json"
        patches = [
            unittest.mock.patch.object(pfw, "resolve_user", _resolve_user),
            unittest.mock.patch.object(pfw, "resolve_group", lambda name: (4400, ["fw-caller"])),
            unittest.mock.patch.object(pfw, "group_members",
                                       lambda gid, members: {SERVICE_UID, CALLER_UID}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def plan(self, **kw):
        kw.setdefault("config", str(self.config_path))
        return pfw.build_plan(_Args(**kw))


class Preconditions(unittest.TestCase):
    def test_a_non_root_provisioner_refuses_rather_than_owning_everything_itself(self):
        with self.assertRaises(pfw.ProvisionError) as caught:
            pfw.require_root(euid=1000)
        self.assertEqual(caught.exception.code, pfw.EXIT_CONFIG)
        self.assertIn("uid 1000", caught.exception.detail)
        pfw.require_root(euid=0)   # the positive control: root is accepted

    def test_provisioning_stops_off_linux_rather_than_approximating(self):
        with unittest.mock.patch.object(pfw.sys, "platform", "win32"):
            with self.assertRaises(pfw.ProvisionError) as caught:
                pfw.require_linux()
        self.assertEqual(caught.exception.code, pfw.EXIT_PLATFORM)
        self.assertIn("FW-2", caught.exception.detail)


class ImportsWhereItDoesNotRun(unittest.TestCase):
    """A Linux-only module must still IMPORT on Windows, or its tests fail instead of skipping.

    `provision_floor_writer` needs `pwd` and `grp`, which do not exist off POSIX. A bare
    `import pwd` at the top would make this whole test module fail to LOAD on the Windows engine
    job — and a suite that cannot load reads as broken rather than as an unbuilt platform. That
    exact confusion has already cost this repository one red job.

    Measured by importing the module in a child interpreter with both databases blocked, rather
    than by patching an attribute: the failure being guarded against happens at import time, and
    an attribute patch happens after it.
    """

    def test_the_module_imports_with_no_posix_principal_database(self):
        program = (
            "import sys, importlib\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "class Blocker:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name in ('grp', 'pwd'):\n"
            "            raise ImportError(name)\n"
            "        return None\n"
            "sys.meta_path.insert(0, Blocker())\n"
            "for n in ('grp', 'pwd'):\n"
            "    sys.modules.pop(n, None)\n"
            "m = importlib.import_module('provision_floor_writer')\n"
            "assert m.grp is None and m.pwd is None\n"
            "try:\n"
            "    m.resolve_user('root')\n"
            "    raise SystemExit('resolve_user did not refuse')\n"
            "except m.ProvisionError as exc:\n"
            "    assert exc.code == m.EXIT_PLATFORM, exc.code\n"
            "print('ok')\n"
        )
        import subprocess
        result = subprocess.run([sys.executable, "-c", program, str(ROOT / "runtime")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-600:])
        self.assertIn("ok", result.stdout)


class Generation(unittest.TestCase):
    """§1.10, the half that did not exist: the number is MINTED, not written by hand."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pathlib.Path(self._tmp.name) / "floor-writer.json"

    def test_the_first_provisioning_mints_one(self):
        self.assertEqual(pfw.mint_generation(self.path), 1)

    def test_a_reprovisioning_mints_strictly_above_the_previous(self):
        self.path.write_text(json.dumps({"generation": 7}), encoding="utf-8")
        self.assertEqual(pfw.mint_generation(self.path), 8)

    def test_an_unreadable_existing_config_refuses_rather_than_minting_one_over_a_live_store(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(pfw.ProvisionError) as caught:
            pfw.mint_generation(self.path)
        self.assertIn("unknown", caught.exception.detail)

    def test_an_existing_config_without_a_generation_refuses(self):
        self.path.write_text(json.dumps({"install_id": "x"}), encoding="utf-8")
        with self.assertRaises(pfw.ProvisionError):
            pfw.mint_generation(self.path)


class PeerAllowlist(PlanFixture):
    """§1.8 and §1.2, decided at provisioning where they can still be fixed."""

    def test_the_ordinary_plan_is_built(self):
        plan = self.plan()
        self.assertEqual(plan.generation, 1)
        self.assertEqual(plan.peers[fw.OP_ADVANCE], frozenset({CALLER_UID}))
        self.assertEqual(plan.marks_dir.name, "install-1")

    def test_the_service_must_not_be_its_own_caller(self):
        with self.assertRaises(pfw.ProvisionError) as caught:
            self.plan(peer=["floor.get=fw-svc", "floor.advance=fw-svc"])
        self.assertIn("A-01 restored", caught.exception.detail)

    def test_root_is_not_admitted_on_the_wire(self):
        with self.assertRaises(pfw.ProvisionError) as caught:
            self.plan(peer=["floor.get=root", "floor.advance=root"])
        self.assertIn("root can rewrite the store directly", caught.exception.detail)

    def test_an_op_with_no_peers_refuses_because_a_union_is_not_a_per_op_list(self):
        with self.assertRaises(pfw.ProvisionError) as caught:
            self.plan(peer=["floor.get=fw-caller"])
        self.assertIn("floor.advance", caught.exception.detail)

    def test_scope_pin_is_fw3_and_cannot_be_provisioned_here(self):
        with self.assertRaises(pfw.ProvisionError) as caught:
            self.plan(peer=["floor.get=fw-caller", "floor.advance=fw-caller",
                            "scope.pin=fw-caller"])
        self.assertIn("FW-3", caught.exception.detail)

    def test_a_peer_that_cannot_traverse_to_the_endpoint_is_a_misconfiguration(self):
        # fw-other is on the allowlist and not in the caller group: the filesystem would refuse it
        # before the allowlist ever ran, and a service nobody can reach is not a posture.
        with self.assertRaises(pfw.ProvisionError) as caught:
            self.plan(peer=["floor.get=fw-caller", "floor.advance=fw-other"])
        self.assertIn(str(OTHER_UID), caught.exception.detail)
        self.assertIn("cannot traverse", caught.exception.detail)

    def test_the_floor_writer_must_not_be_root(self):
        with self.assertRaises(pfw.ProvisionError) as caught:
            self.plan(service_user="root", peer=["floor.get=fw-caller",
                                                 "floor.advance=fw-caller"])
        self.assertIn("must not run as root", caught.exception.detail)

    def test_an_install_id_carrying_a_separator_cannot_address_another_store(self):
        with self.assertRaises(pfw.ProvisionError) as caught:
            self.plan(install_id="../other")
        self.assertIn("directory name", caught.exception.detail)

    def test_an_unknown_service_account_is_a_refusal_and_never_a_create(self):
        with self.assertRaises(pfw.ProvisionError):
            self.plan(service_user="fw-nobody")


@unittest.skipUnless(_LINUX, LINUX_ONLY)
class ParentCustody(unittest.TestCase):
    """Provisioning asks the SERVICE's custody question, with root as the required owner (C2).

    The rule itself — ownership, mode, and the unswappable ancestry — is one function in
    `floor_writer` and is tested there, from both sides, in `CustodyContract`. What is tested here
    is the only thing this module contributes: **who** must own the directory, and that a refusal
    arrives as `EXIT_CUSTODY` rather than as a `FloorWriterError` nobody here would catch.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)

    def test_a_parent_this_uid_owns_is_refused_because_provisioning_requires_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root: the temp directory would satisfy the check")
        with self.assertRaises(pfw.ProvisionError) as caught:
            pfw.require_root_owned_parent(self.root, "the marks root's parent")
        self.assertEqual(caught.exception.code, pfw.EXIT_CUSTODY)
        self.assertIn("not uid 0", caught.exception.detail)

    def test_a_root_owned_unwritable_parent_is_accepted(self):
        # The positive control, on a directory the box really has: /usr is root-owned and 0755,
        # and its ancestry is / at 0755. Without this arm the test above would pass on a function
        # that refused everything.
        pfw.require_root_owned_parent(pathlib.Path("/usr"), "a control")

    def test_a_missing_parent_is_a_refusal_not_a_create(self):
        with self.assertRaises(pfw.ProvisionError) as caught:
            pfw.require_root_owned_parent(self.root / "absent", "the marks root's parent")
        self.assertEqual(caught.exception.code, pfw.EXIT_CUSTODY)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
