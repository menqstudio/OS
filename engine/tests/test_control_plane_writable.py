"""O-1, the half a detector cannot reach: a control plane this account can still write into.

`assert_no_bytecode_shadow` catches a `.pyc` that is already there. It cannot catch one planted a
moment later, and it cannot catch one loaded before the process started — CPython imports the
cache during import, before any assertion in the module exists to run. `-B` does not help: it
stops bytecode being WRITTEN, not read.

So the only real defence is that the file cannot be created at all, which is a property of the
filesystem rather than the interpreter. These tests hold the gate that turns that from a hope into
a checked precondition.
"""
import os
import pathlib
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))

from bro_protected import (  # noqa: E402
    WRITABLE_CONTROL_PLANE_ENV,
    WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT,
    ProtectedScopeError,
    assert_control_plane_not_writable,
    control_plane_writable_by_me,
    load_protected_manifest,
)

ENGINE = pathlib.Path(__file__).resolve().parents[1]

#: The smallest manifest that puts `runtime/` in digest scope — the same keys the shipped
#: `config/protected-control-plane.json` uses, so a fixture cannot drift into testing a shape
#: production does not have.
MANIFEST_JSON = ('{"schema": 1, "protected_roots": ["runtime/**"], '
                 '"digest_roots": ["runtime/**"], "unprotected_exceptions": []}')


class ControlPlaneWritabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_protected_manifest(ENGINE)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.previous = os.environ.pop(WRITABLE_CONTROL_PLANE_ENV, None)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        os.environ.pop(WRITABLE_CONTROL_PLANE_ENV, None)
        if self.previous is not None:
            os.environ[WRITABLE_CONTROL_PLANE_ENV] = self.previous

    def test_a_writable_control_plane_is_refused_and_names_the_directories(self) -> None:
        """A developer checkout is writable, which is exactly the state that must refuse.

        Asserting on the real tree rather than a fixture is deliberate: a fixture could be made to
        pass while the thing anybody actually runs stays open.
        """
        with self.assertRaises(ProtectedScopeError) as caught:
            assert_control_plane_not_writable(ENGINE, self.manifest)
        message = str(caught.exception)
        self.assertIn("runtime", message, "the refusal must name where a shadow could be planted")
        self.assertIn("stops bytecode being written, not read", message,
                      "it must say why -B is not the answer, or someone will add -B and stop")

    def test_the_probe_answers_by_creating_a_file_not_by_reading_mode_bits(self) -> None:
        """The question is CPython's: can a file appear here?

        A read-only mount, an ACL, an immutable attribute and a full disk all answer that
        correctly, and none of them is legible from `stat()` alone — which is why this must be a
        real create attempt and why a mode-bit shortcut would be a worse check wearing the same
        name.
        """
        writable = control_plane_writable_by_me(ENGINE, self.manifest)
        self.assertIn("runtime", writable)
        # And it cleans up after itself: a probe left behind would itself be an undigested file.
        self.assertFalse((ENGINE / "runtime" / ".bro-write-probe").exists())

    def test_a_directory_outside_the_digest_scope_is_not_a_finding(self) -> None:
        """Only where a shadow would matter. A writable `AUDIT/` is not this gate's business, and
        reporting it would train the reader to skim the list."""
        writable = control_plane_writable_by_me(ENGINE, self.manifest)
        for noise in ("AUDIT", "AUDIT/tickets", "skills"):
            self.assertNotIn(noise, writable)

    def test_the_acknowledgement_must_be_the_exact_token(self) -> None:
        """A deployment may accept the residual risk — by typing it out, not by setting a truthy
        value. `1`, `true` and `yes` are what someone sets to make an error go away; the token is
        what someone sets having read what it means."""
        for value in ("1", "true", "yes", "accepted", "ACCEPTED-O1-RESIDUAL-RISK"):
            with self.subTest(value=value):
                os.environ[WRITABLE_CONTROL_PLANE_ENV] = value
                with self.assertRaises(ProtectedScopeError):
                    assert_control_plane_not_writable(ENGINE, self.manifest)

    def test_the_exact_acknowledgement_waives_it(self) -> None:
        os.environ[WRITABLE_CONTROL_PLANE_ENV] = WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT
        assert_control_plane_not_writable(ENGINE, self.manifest)  # must not raise

    def test_a_stale_probe_file_does_not_read_as_unwritable(self) -> None:
        """EEXIST means somebody created a file here — i.e. writable.

        Treating it as "cannot write" would let one leftover file from an interrupted run turn
        this gate green, which is precisely the failure it exists to prevent.
        """
        root = pathlib.Path(self.temp.name) / "stale"
        (root / "runtime").mkdir(parents=True)
        (root / "runtime" / "mod.py").write_text("x = 1", encoding="utf-8")
        (root / "config").mkdir()
        (root / "config" / "protected-control-plane.json").write_text(
            MANIFEST_JSON, encoding="utf-8")
        (root / "runtime" / ".bro-write-probe").write_text("", encoding="utf-8")
        manifest = load_protected_manifest(root)
        self.assertIn("runtime", control_plane_writable_by_me(root, manifest))

    @unittest.skipUnless(os.name == "nt", "the divergence proven here is Windows ACLs vs os.access")
    def test_the_probe_beats_os_access_where_they_disagree(self) -> None:
        """Why this must be a real create attempt and not a permission lookup.

        On Windows `os.access(dir, W_OK)` ignores ACLs: it answers True for a directory whose ACL
        denies file creation outright. A gate built on `os.access` would therefore report a
        genuinely protected control plane as writable — refusing a correct deployment — and,
        worse, the reverse shape exists too. Only an attempted create asks the question CPython's
        import machinery asks.
        """
        import subprocess
        root = pathlib.Path(self.temp.name) / "acl"
        (root / "runtime").mkdir(parents=True)
        (root / "runtime" / "mod.py").write_text("x = 1", encoding="utf-8")
        (root / "config").mkdir()
        (root / "config" / "protected-control-plane.json").write_text(
            MANIFEST_JSON, encoding="utf-8")
        manifest = load_protected_manifest(root)
        self.assertIn("runtime", control_plane_writable_by_me(root, manifest))

        target = root / "runtime"
        user = os.environ.get("USERNAME", "")
        denied = subprocess.run(["icacls", str(target), "/deny", f"{user}:(WD,AD)"],
                                capture_output=True, text=True)
        if denied.returncode != 0:
            self.skipTest(f"could not apply a deny ACE here: {denied.stdout}{denied.stderr}")
        self.addCleanup(lambda: subprocess.run(["icacls", str(target), "/remove:d", user],
                                               capture_output=True))
        self.assertTrue(os.access(target, os.W_OK),
                        "os.access is expected to be WRONG here — that is the whole point")
        self.assertEqual(control_plane_writable_by_me(root, manifest), [],
                         "the create probe must see what os.access cannot")
        assert_control_plane_not_writable(root, manifest)  # must not raise

    @unittest.skipIf(os.name == "nt",
                     "POSIX mode bits do not restrain the owner on Windows; the Debian deployment "
                     "is where this property is real, and it is proven there rather than faked here")
    def test_an_unwritable_tree_passes(self) -> None:
        """The condition the deployment must reach: no digest directory accepts a new file."""
        root = pathlib.Path(self.temp.name) / "engine"
        (root / "runtime").mkdir(parents=True)
        (root / "runtime" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        (root / "config").mkdir()
        (root / "config" / "protected-control-plane.json").write_text(
            MANIFEST_JSON, encoding="utf-8")
        manifest = load_protected_manifest(root)
        self.assertTrue(control_plane_writable_by_me(root, manifest))
        for path in (root / "runtime", root):
            os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(lambda: [os.chmod(p, 0o700) for p in (root, root / "runtime")])
        self.assertEqual(control_plane_writable_by_me(root, manifest), [])
        assert_control_plane_not_writable(root, manifest)  # must not raise


if __name__ == "__main__":
    unittest.main()
