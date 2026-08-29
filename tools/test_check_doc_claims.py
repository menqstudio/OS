"""Tests for the canonical-claims gate.

This gate had NO tests at all. It shipped in `T-045`, ran in exactly one place — CI — and
its fourth check was structurally unable to pass there: it compared the documents against
whatever machine it happened to run on, and in CI that machine is a GitHub runner. It named
four canonical files as making an untrue claim about `node` while all four were correct
about the box they describe. A gate whose only home is the one place it cannot be right is
worse than no gate, because its RED teaches everyone to scroll past it.

So the version claim gets one source of record, `config/toolchain.json`, and the checking
splits in two: documents against the record everywhere, record against the machine only
where a development machine is what is running.

Every test names the mutation that turns it red. `unittest.main()` is the last statement
(ninth audit `I-05`).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_doc_claims as m


def build(tmp: pathlib.Path, *, doc: str = "", toolchain: object = ...,
          docname: str = "DOC.md") -> pathlib.Path:
    """A root the gate can run over: a read manifest naming one document, and a record.

    `toolchain=None` means the record is deliberately absent."""
    root = tmp / "root"
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / docname).write_text(doc, encoding="utf-8")
    (root / "config" / "canonical-read-manifest.json").write_text(
        json.dumps({"paths": [docname]}), encoding="utf-8")
    if toolchain is ...:
        toolchain = {"versions": {"cargo": "1.97.1", "node": "20.20.2", "npm": "10.8.2"}}
    if toolchain is not None:
        (root / "config" / "toolchain.json").write_text(
            json.dumps(toolchain), encoding="utf-8")
    return root


def run(root: pathlib.Path, env_ci: bool = True) -> tuple[int, str]:
    """The gate, with its stdout captured. CI by default, because the machine half is not
    what most of these tests are about and a developer's real toolchain must not decide
    whether they pass."""
    before = os.environ.get("GITHUB_ACTIONS")
    os.environ["GITHUB_ACTIONS"] = "true" if env_ci else "false"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = m.main(root)
    finally:
        if before is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = before
    return code, buf.getvalue()


class VersionClaims(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="doc-claims-"))

    def test_a_claim_matching_the_record_is_green(self):
        """The positive control: without it every RED below could be a gate that never
        says yes."""
        root = build(self.tmp, doc="Toolchain: cargo 1.97.1, node 20.20.2, npm 10.8.2.\n")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_a_claim_disagreeing_with_the_record_is_red(self):
        """Mutant: drop check 4 ⇒ green. This is the defect the gate was written for —
        `cargo 1.96` in five documents on a box running 1.97.1."""
        root = build(self.tmp, doc="Toolchain: cargo 1.96.0.\n")
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("claims cargo 1.96", out)

    def test_the_ci_runners_own_toolchain_does_not_decide_the_verdict(self):
        """THE REGRESSION, as a test. The document is right about the development box and
        the machine running the gate has something else entirely. That must be GREEN — it
        was RED for every CI run this gate ever had.

        Mutant: compare the documents against installed_versions() again ⇒ red."""
        root = build(self.tmp, doc="node 20.20.2 is what this box has.\n")
        real = m.installed_versions
        m.installed_versions = lambda: {"node": "22.23.2", "cargo": "9.9.9", "npm": "99.0.0"}
        try:
            code, out = run(root)
        finally:
            m.installed_versions = real
        self.assertEqual(code, 0, out)

    def test_the_record_disagreeing_with_the_machine_is_red_off_ci(self):
        """Mutant: drop the record-vs-machine comparison ⇒ green, and the record can then
        drift from the box forever, which is the same defect one level up."""
        root = build(self.tmp, doc="cargo 1.97.1\n")
        real = m.installed_versions
        m.installed_versions = lambda: {"cargo": "1.98.0"}
        try:
            code, out = run(root, env_ci=False)
        finally:
            m.installed_versions = real
        self.assertEqual(code, 1)
        self.assertIn("records cargo 1.97.1; this machine has 1.98.0", out)

    def test_the_same_disagreement_is_skipped_with_a_reason_in_ci(self):
        """Mutant: run the machine comparison in CI too ⇒ red, and the gate is back where
        it started. The SKIP has to be said out loud: "I could not check" and "it is fine"
        are different answers."""
        root = build(self.tmp, doc="cargo 1.97.1\n")
        real = m.installed_versions
        m.installed_versions = lambda: {"cargo": "1.98.0"}
        try:
            code, out = run(root, env_ci=True)
        finally:
            m.installed_versions = real
        self.assertEqual(code, 0, out)
        self.assertIn("SKIPPED", out)
        self.assertIn("different machine", out)

    def test_a_missing_record_is_red(self):
        """Mutant: return an empty dict instead of a problem ⇒ green, and deleting the file
        becomes the cheap way to pass every version claim at once."""
        root = build(self.tmp, doc="cargo 1.96.0\n", toolchain=None)
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("unreadable", out)

    def test_a_record_with_no_versions_object_is_red(self):
        root = build(self.tmp, doc="cargo 1.97.1\n", toolchain={"purpose": "nothing here"})
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("carries no `versions` object", out)

    def test_a_record_version_that_is_not_a_version_is_red(self):
        """A record that says `latest` checks nothing and reads as if it did."""
        root = build(self.tmp, doc="cargo 1.97.1\n",
                     toolchain={"versions": {"cargo": "latest"}})
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("is not an x.y.z version", out)

    def test_a_claim_naming_fewer_parts_than_the_record_is_green(self):
        """`cargo 1.97` against a recorded `1.97.1` is the same version said shorter.
        Mutant: require equality ⇒ red, and documents are forced to a patch number."""
        root = build(self.tmp, doc="cargo 1.97 is what runs here.\n")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_sharing_only_the_major_is_not_a_match(self):
        """Mutant: restore `claimed.startswith(actual.split(".")[0])` ⇒ green.

        That clause made the whole check a formality: against a recorded `1.97.1`, EVERY
        claim beginning `1` passed, `cargo 1.96` included — the exact string the gate was
        written to catch. It only ever fired on node, where 20 and 22 differ in the major."""
        root = build(self.tmp, doc="cargo 1.9 and nothing else.\n")
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("claims cargo 1.9;", out)

    def test_a_quotation_is_exempt_BY_NAME_and_not_by_a_rule(self):
        """The two "*(The documents said cargo 1.96 ...)*" asides are records of a
        correction and must survive. They are exempt as (file, tool, version) triples, so
        the identical sentence in any other file is still a claim.

        Mutant: exempt anything following the word "said" ⇒ this goes green, and every
        stale number in the repository is one sentence away from being exempt."""
        root = build(self.tmp, doc="*(The documents said cargo 1.96.)*\n")
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("claims cargo 1.96", out)
        self.assertIn(("CLAUDE.md", "cargo", "1.96"), m.QUOTED_STALE_VERSIONS)

    def test_a_tool_the_record_does_not_name_is_not_checked(self):
        """Deliberate, and pinned so nobody later defends it as a guarantee: the record is
        the closed list. A claim about something it does not name passes."""
        root = build(self.tmp, doc="python3 3.9.0\n")
        code, out = run(root)
        self.assertEqual(code, 0, out)


class TheOtherThreeChecks(unittest.TestCase):
    """Checks 1-3 had no tests either. One each, so a deletion cannot pass unseen."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="doc-claims-other-"))

    def test_a_referenced_path_that_does_not_exist_is_red(self):
        """Mutant: drop check 1 ⇒ green. `A-06` twice: a citation to a file nobody filed."""
        root = build(self.tmp, doc="See [the report](docs/no-such-file.md).\n")
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("no-such-file.md", out)

    def test_a_sha_that_resolves_to_nothing_is_red(self):
        """Mutant: drop check 2 ⇒ green. A head that has gone stale, invented or rebased
        away reads exactly like one that has not."""
        root = build(self.tmp, doc="settled at `abc1234def`.\n")
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("abc1234def", out)

    def test_a_ticket_id_in_no_board_is_red(self):
        """Mutant: drop check 3 ⇒ green. A `T-nnn` in prose and on no board points at
        nothing, and reads as if the work were tracked."""
        root = build(self.tmp, doc="carried by `T-981`.\n")
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("T-981", out)

    def test_a_document_named_in_the_manifest_and_absent_is_red(self):
        root = build(self.tmp, doc="fine\n")
        (root / "DOC.md").unlink()
        code, out = run(root)
        self.assertEqual(code, 1)
        self.assertIn("in the read manifest and not on disk", out)


class TheRealRepository(unittest.TestCase):
    def test_the_real_canon_makes_no_untrue_claim(self):
        code, _ = run(ROOT, env_ci=False)
        self.assertEqual(code, 0)


class EntryPointRunsEverything(unittest.TestCase):
    def test_unittest_main_is_the_last_statement(self):
        source = pathlib.Path(__file__).read_text(encoding="utf-8").splitlines()
        classes = [i for i, ln in enumerate(source) if ln.startswith("class ")]
        guard = [i for i, ln in enumerate(source) if ln.startswith('if __name__')]
        self.assertEqual(len(guard), 1)
        self.assertGreater(guard[0], max(classes))


if __name__ == "__main__":
    unittest.main()
