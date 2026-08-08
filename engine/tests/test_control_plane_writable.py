"""O-1, the half a detector cannot reach: a control plane this account can still write into.

`assert_no_bytecode_shadow` catches a `.pyc` that is already there. It cannot catch one planted a
moment later, and it cannot catch one loaded before the process started — CPython imports the
cache during import, before any assertion in the module exists to run. `-B` does not help: it
stops bytecode being WRITTEN, not read.

So the only real defence is that the file cannot be created at all, which is a property of the
filesystem rather than the interpreter. These tests hold the gate that turns that from a hope into
a checked precondition.

WHY THESE TESTS DRIVE A FIXTURE TREE RATHER THAN THE AMBIENT CHECKOUT
--------------------------------------------------------------------
They used to assert directly that the *engine checkout* is writable and therefore refused. That is
true of a developer checkout and of CI, and FALSE of the deployment this gate exists to produce: a
correctly deployed box bind-mounts the tree read-only, so the probe finds nothing, nothing refuses,
and seven assertions that had been passing for the whole life of the file turned RED on the one
machine where the property they describe was actually real. The tests were measuring the
environment, not the code.

The environment is not the subject. Each test below therefore builds the tree whose writability it
wants to talk about, so it returns the same verdict on a read-only Debian box, on CI and on a
developer laptop. Exactly one test still looks at the ambient checkout, and it asserts only a
relationship that holds in BOTH states (`test_the_real_tree_agrees_with_its_own_probe`).

Where a property cannot be real in an environment (POSIX modes on Windows; any mode bit against
root) the test SKIPS and names the reason. It never quietly passes: a green that depended on a
precondition nobody checked is the same defect in a different coat, so
`_make_unwritable` re-verifies, with its own `os.open` and not with the code under test, that the
directory really did stop accepting files — and skips rather than continues if it did not.
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

#: The digest-scoped directories every fixture tree contains, in the order the gate reports them.
#: Two of them, and one nested, because "make the control plane read-only" is a statement about a
#: tree and a fixture with a single directory cannot tell a gate that walks from one that peeks.
FIXTURE_DIGEST_DIRS = ("runtime", "runtime/sub")

#: Writable directories that are NOT in digest scope. Their presence is what makes
#: `test_a_directory_outside_the_digest_scope_is_not_a_finding` mean anything: against a tree with
#: no out-of-scope directories at all, that test passes without the filter existing.
FIXTURE_NOISE_DIRS = ("AUDIT", "AUDIT/tickets", "skills")


def _euid() -> int | None:
    """The effective uid, or None where the concept does not apply (Windows)."""
    geteuid = getattr(os, "geteuid", None)
    return geteuid() if geteuid is not None else None


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

    # ---------------------------------------------------------------- fixtures

    def _tree(self, name: str) -> tuple[pathlib.Path, object]:
        """A miniature engine tree the test owns, plus its manifest.

        Owning the tree is the whole point: its writability is set by this method rather than
        inherited from whatever machine happens to be running the suite.
        """
        root = pathlib.Path(self.temp.name) / name
        for relative in FIXTURE_DIGEST_DIRS:
            (root / relative).mkdir(parents=True, exist_ok=True)
            (root / relative / "mod.py").write_text("x = 1\n", encoding="utf-8")
        for relative in FIXTURE_NOISE_DIRS:
            (root / relative).mkdir(parents=True, exist_ok=True)
            (root / relative / "note.md").write_text("not control plane\n", encoding="utf-8")
        (root / "config").mkdir(exist_ok=True)
        (root / "config" / "protected-control-plane.json").write_text(
            MANIFEST_JSON, encoding="utf-8")
        return root, load_protected_manifest(root)

    def _make_unwritable(self, root: pathlib.Path) -> None:
        """Turn the fixture's digest directories read-only, or SKIP saying why it could not be.

        `chmod 0500` is r-x: the directory can still be listed and descended (the walk needs that)
        but no new name can be created in it — which is precisely the property a read-only bind
        mount gives the deployment, reproduced inside a test that owns the tree.

        Three ways that could be a lie, all of which skip rather than continue:

        * **Windows** — POSIX mode bits do not restrain the owner there at all. `os.chmod` accepts
          the call and changes nothing that matters.
        * **root** — the mode bits are simply not consulted for uid 0. A green here would say
          "unwritable trees pass" while the tree was never unwritable.
        * **anything else** — a filesystem that ignores modes (some mounts, some containers,
          CAP_DAC_OVERRIDE without uid 0). This is caught empirically: after the chmod, try to
          create a file with a plain `os.open`, which is deliberately NOT the function under test,
          so a bug in the probe cannot make its own precondition look satisfied.
        """
        if os.name == "nt":
            self.skipTest("POSIX mode bits do not restrain the owner on Windows, so chmod 0500 "
                          "here would produce a green that proves nothing; the read-only property "
                          "is real on the POSIX deployment and is proven there")
        euid = _euid()
        if euid == 0:
            self.skipTest("running as root (euid 0): root is not subject to the 0500 mode bits, "
                          "so the tree would still accept a .pyc and this test cannot be honest "
                          "here; run the suite as a non-root user to exercise it")
        targets = [root / relative for relative in FIXTURE_DIGEST_DIRS]
        # Deepest first, so a parent turned read-only cannot block chmod'ing its children.
        targets.sort(key=lambda p: len(p.parts), reverse=True)
        for path in targets:
            os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(lambda: [os.chmod(p, 0o700) for p in reversed(targets)])
        for path in targets:
            probe = path / ".precondition-probe"
            try:
                handle = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except OSError:
                continue  # the mode held, which is what this fixture needed
            os.close(handle)
            os.unlink(probe)
            self.skipTest(f"chmod 0500 did not stop this account creating {probe}; the filesystem "
                          f"or capability set here ignores directory mode bits (euid={euid}), so "
                          "an unwritable control plane cannot be simulated on this machine")

    # ------------------------------------------------------- the refusal path

    def test_a_writable_control_plane_is_refused_and_names_the_directories(self) -> None:
        """A writable control plane must refuse, and the refusal must be actionable.

        Driven by a fixture whose writability this test set, not by the ambient checkout: the
        checkout is writable on a laptop and in CI and read-only on a correct deployment, and a
        test that asserts a refusal can only be right in two of those three places.
        """
        root, manifest = self._tree("writable")
        self.assertEqual(control_plane_writable_by_me(root, manifest),
                         sorted(FIXTURE_DIGEST_DIRS),
                         "precondition: the fixture must start writable, or the refusal below "
                         "would be asserting against a tree that is not in the state named")
        with self.assertRaises(ProtectedScopeError) as caught:
            assert_control_plane_not_writable(root, manifest)
        message = str(caught.exception)
        for relative in FIXTURE_DIGEST_DIRS:
            self.assertIn(relative, message,
                          "the refusal must name EVERY place a shadow could be planted; an "
                          "operator fixes the directories the message lists and stops there")
        self.assertIn("stops bytecode being written, not read", message,
                      "it must say why -B is not the answer, or someone will add -B and stop")
        self.assertIn(WRITABLE_CONTROL_PLANE_ENV, message,
                      "a deployment that cannot comply must be told how to say so")

    def test_the_real_tree_agrees_with_its_own_probe(self) -> None:
        """The one assertion left on the ambient checkout, and it holds in EITHER state.

        A fixture can be made to pass while the thing anybody actually runs stays open, so the real
        tree is not left untested — but what is asserted about it is a relationship, not a state:
        the gate refuses exactly when the probe finds something, and when it refuses it names
        everything the probe found. On a developer checkout and in CI that exercises the refusal;
        on a correctly deployed read-only box it exercises the pass. Neither is a failure, because
        neither is a property of this repository's code.
        """
        writable = control_plane_writable_by_me(ENGINE, self.manifest)
        if not writable:
            assert_control_plane_not_writable(ENGINE, self.manifest)  # must not raise
            return
        with self.assertRaises(ProtectedScopeError) as caught:
            assert_control_plane_not_writable(ENGINE, self.manifest)
        message = str(caught.exception)
        for relative in writable:
            self.assertIn(relative, message)

    def test_the_probe_answers_by_creating_a_file_not_by_reading_mode_bits(self) -> None:
        """The question is CPython's: can a file appear here?

        A read-only mount, an ACL, an immutable attribute and a full disk all answer that
        correctly, and none of them is legible from `stat()` alone — which is why this must be a
        real create attempt and why a mode-bit shortcut would be a worse check wearing the same
        name.
        """
        root, manifest = self._tree("probe")
        writable = control_plane_writable_by_me(root, manifest)
        self.assertEqual(writable, sorted(FIXTURE_DIGEST_DIRS))
        # And it cleans up after itself: a probe left behind would itself be an undigested file.
        for relative in FIXTURE_DIGEST_DIRS:
            self.assertFalse((root / relative / ".bro-write-probe").exists(),
                             f"the gate left its own probe behind in {relative}")

    def test_a_directory_outside_the_digest_scope_is_not_a_finding(self) -> None:
        """Only where a shadow would matter. A writable `AUDIT/` is not this gate's business, and
        reporting it would train the reader to skim the list.

        The fixture deliberately CONTAINS writable out-of-scope directories. Asserting their
        absence from a list that never had them (an empty list on a read-only tree, or a tree with
        no such directories) is an assertion that passes whether or not the filter exists.
        """
        root, manifest = self._tree("scope")
        writable = control_plane_writable_by_me(root, manifest)
        for noise in FIXTURE_NOISE_DIRS:
            self.assertTrue((root / noise).is_dir(),
                            "precondition: the out-of-scope directory must exist and be writable, "
                            "or its absence from the findings means nothing")
            self.assertNotIn(noise, writable)
        self.assertEqual(writable, sorted(FIXTURE_DIGEST_DIRS),
                         "and the in-scope directories must still be found, or 'no noise' would "
                         "be satisfied by a gate that reports nothing at all")

    # ------------------------------------------------- the acknowledgement

    def test_the_acknowledgement_must_be_the_exact_token(self) -> None:
        """A deployment may accept the residual risk — by typing it out, not by setting a truthy
        value. `1`, `true` and `yes` are what someone sets to make an error go away; the token is
        what someone sets having read what it means."""
        root, manifest = self._tree("token")
        self.assertTrue(control_plane_writable_by_me(root, manifest),
                        "precondition: without a writable tree there is nothing for a wrong "
                        "acknowledgement to fail to waive, and every subTest below would pass "
                        "for the wrong reason")
        for value in ("1", "true", "yes", "accepted", "ACCEPTED-O1-RESIDUAL-RISK",
                      WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT + " ",
                      " " + WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT,
                      WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT.upper(), ""):
            with self.subTest(value=value):
                os.environ[WRITABLE_CONTROL_PLANE_ENV] = value
                with self.assertRaises(ProtectedScopeError):
                    assert_control_plane_not_writable(root, manifest)

    def test_the_exact_acknowledgement_waives_it(self) -> None:
        """And the waiver must be what changed the answer.

        The refusal is asserted FIRST, on the same tree, in the same test. Without that, this test
        passes on any tree that had nothing to refuse — which is exactly what it did on a
        correctly deployed read-only box, reporting a green for the waiver path while the waiver
        was never consulted.
        """
        root, manifest = self._tree("waiver")
        with self.assertRaises(ProtectedScopeError):
            assert_control_plane_not_writable(root, manifest)
        os.environ[WRITABLE_CONTROL_PLANE_ENV] = WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT
        assert_control_plane_not_writable(root, manifest)  # must not raise

    def test_a_stale_probe_file_does_not_read_as_unwritable(self) -> None:
        """EEXIST means somebody created a file here — i.e. writable.

        Treating it as "cannot write" would let one leftover file from an interrupted run turn
        this gate green, which is precisely the failure it exists to prevent.
        """
        root, manifest = self._tree("stale")
        (root / "runtime" / ".bro-write-probe").write_text("", encoding="utf-8")
        self.assertIn("runtime", control_plane_writable_by_me(root, manifest))

    def test_the_answer_comes_from_an_attempted_create_not_a_permission_lookup(self) -> None:
        """The mechanism IS the property here, so the mechanism is what is asserted.

        `test_the_probe_beats_os_access_where_they_disagree` proves this behaviourally — but only
        on Windows, because Windows is where a permission lookup and a create attempt give
        different answers cheaply. On Linux the two agree for every case a non-root test can
        construct (`access(2)` consults ACLs and read-only mounts; the cases that do diverge are a
        full filesystem, a disk quota or `chattr +i`, none reachable without root). Swapping the
        create probe for `os.access` therefore passes the entire behavioural suite on Linux, which
        is where CI runs it — so on the platform that gates merges, the sentence this gate's
        docstring is built on was checked by nothing.

        This closes that portably by asserting the syscall: the verdict must come from an
        `O_CREAT|O_EXCL` open of a probe name in each digest directory. That is white-box, and
        deliberately so — "it tries to create a file rather than asking what the mode bits say" is
        not an implementation detail of this function, it is the entire reason the function is
        trusted over the one-liner someone will eventually propose to replace it.
        """
        import unittest.mock
        root, manifest = self._tree("mechanism")
        attempts: list[tuple[str, int]] = []
        real_open = os.open

        def recording_open(path, flags, *args, **kwargs):
            attempts.append((str(path), flags))
            return real_open(path, flags, *args, **kwargs)

        with unittest.mock.patch("bro_protected.os.open", recording_open):
            writable = control_plane_writable_by_me(root, manifest)
        self.assertEqual(writable, sorted(FIXTURE_DIGEST_DIRS))
        for relative in FIXTURE_DIGEST_DIRS:
            expected = str(root / relative / ".bro-write-probe")
            matching = [flags for path, flags in attempts if path == expected]
            self.assertTrue(matching,
                            f"no create was attempted in {relative}; the verdict came from "
                            "somewhere other than asking the filesystem to make a file, which is "
                            "the one question CPython's import machinery also asks")
            for flags in matching:
                self.assertTrue(flags & os.O_CREAT, "the probe must actually create")
                self.assertTrue(flags & os.O_EXCL,
                                "without O_EXCL the probe would truncate whatever it found and "
                                "could not tell a leftover file from a fresh one")

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
        root, manifest = self._tree("acl")
        self.assertEqual(control_plane_writable_by_me(root, manifest),
                         sorted(FIXTURE_DIGEST_DIRS))

        user = os.environ.get("USERNAME", "")
        targets = [root / relative for relative in FIXTURE_DIGEST_DIRS]
        for target in targets:
            denied = subprocess.run(["icacls", str(target), "/deny", f"{user}:(WD,AD)"],
                                    capture_output=True, text=True)
            if denied.returncode != 0:
                self.skipTest(f"could not apply a deny ACE here: {denied.stdout}{denied.stderr}")
            self.addCleanup(lambda t=target: subprocess.run(
                ["icacls", str(t), "/remove:d", user], capture_output=True))
        for target in targets:
            self.assertTrue(os.access(target, os.W_OK),
                            "os.access is expected to be WRONG here — that is the whole point")
        self.assertEqual(control_plane_writable_by_me(root, manifest), [],
                         "the create probe must see what os.access cannot")
        assert_control_plane_not_writable(root, manifest)  # must not raise

    # --------------------------------------------------------- the pass path

    def test_an_unwritable_tree_passes(self) -> None:
        """The condition the deployment must reach: no digest directory accepts a new file."""
        root, manifest = self._tree("readonly")
        self.assertEqual(control_plane_writable_by_me(root, manifest),
                         sorted(FIXTURE_DIGEST_DIRS))
        self._make_unwritable(root)          # skips, with a reason, where this cannot be honest
        self.assertEqual(control_plane_writable_by_me(root, manifest), [])
        assert_control_plane_not_writable(root, manifest)  # must not raise

    def test_making_a_tree_unwritable_is_what_flips_the_gate(self) -> None:
        """One tree, one property changed, both verdicts observed.

        The strongest form of this gate's claim, and the one neither environment could make on its
        own: the SAME directories refuse while they accept files and pass once they do not. A
        writable-tree test and a read-only-tree test in different fixtures can both be green while
        the gate ignores writability entirely and refuses (or passes) for some unrelated reason.
        """
        root, manifest = self._tree("flip")
        with self.assertRaises(ProtectedScopeError) as caught:
            assert_control_plane_not_writable(root, manifest)
        self.assertIn("runtime", str(caught.exception))
        self._make_unwritable(root)
        assert_control_plane_not_writable(root, manifest)  # the same call, now silent

    def test_one_writable_directory_is_enough_to_refuse(self) -> None:
        """A control plane is not "mostly" read-only.

        The deployment mistake this catches is a partial one: the bind mount covers `runtime/` and
        misses a nested package, or a later `mkdir` lands outside it. The gate must refuse on the
        single remaining hole and name it, because one writable directory under a digest root is a
        complete `.pyc` shadow — an all-but-one tree buys nothing.
        """
        root, manifest = self._tree("partial")
        self._make_unwritable(root)
        self.assertEqual(control_plane_writable_by_me(root, manifest), [])
        hole = root / "runtime" / "sub"
        os.chmod(hole, 0o700)
        self.assertEqual(control_plane_writable_by_me(root, manifest), ["runtime/sub"])
        with self.assertRaises(ProtectedScopeError) as caught:
            assert_control_plane_not_writable(root, manifest)
        self.assertIn("runtime/sub", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
