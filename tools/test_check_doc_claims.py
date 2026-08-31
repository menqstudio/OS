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
import subprocess
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


class AgentWorktreeDoesNotMakeCitationsAmbiguous(unittest.TestCase):
    """A subtree-relative citation resolves by UNIQUE suffix match, and the Agent tool checks a
    whole second copy of the repository out under `.claude/worktrees/<id>/`. On 2026-08-30 that
    copy made five citations in AUDIT_LEDGER.md, SECURITY.md and ARCHITECTURE.md ambiguous, so
    this gate went RED on a clean tree while CI, which has no worktree, was green — a verdict
    that depended on the machine rather than the code."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="doc-claims-worktree-"))

    def _root_citing(self, subtree_path: str) -> pathlib.Path:
        root = build(self.tmp, doc=f"See `{subtree_path}` for the wiring.\n")
        real = root / "apps" / "desktop" / "src-tauri" / subtree_path
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text("// the real one\n", encoding="utf-8")
        return root

    def test_a_unique_suffix_match_still_resolves(self):
        """The positive control. Without it the test below could pass on a gate that
        resolves nothing at all."""
        root = self._root_citing("broker/src/main.rs")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_a_copy_under_claude_worktrees_does_not_make_it_ambiguous(self):
        """Mutant: drop the `/.claude/worktrees/` exclusion ⇒ red, with the citation reported
        as a file that does not exist — which is exactly what it did before this line."""
        root = self._root_citing("broker/src/main.rs")
        copy = root / ".claude" / "worktrees" / "agent-abc" / "apps" / "desktop" / "src-tauri" / "broker" / "src"
        copy.mkdir(parents=True, exist_ok=True)
        (copy / "main.rs").write_text("// the agent's copy\n", encoding="utf-8")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_a_root_that_IS_a_worktree_still_resolves_its_own_citations(self):
        """The direction the first two tests missed, and the one that actually bit.

        The exclusion above was matched on the ABSOLUTE path. When the checkout being
        graded is itself an agent worktree -- `root` ends in `.claude/worktrees/<id>` --
        every candidate contained `/.claude/worktrees/`, so the exclusion swallowed the
        real file too and the citation was reported as one that does not exist. Measured
        2026-08-30: GREEN from /home/gevorg/os, RED with five findings from a worktree of
        the same commit. A gate whose verdict depends on where the tree is checked out is
        the exact failure the exclusion was added to prevent.

        Mutant: match the exclusions on `q.as_posix()` again => this goes red and names
        `broker/src/main.rs` as a file that does not exist.
        """
        nested = self.tmp / ".claude" / "worktrees" / "agent-abc"
        nested.mkdir(parents=True, exist_ok=True)
        root = build(nested, doc="See `broker/src/main.rs` for the wiring.\n")
        real = root / "apps" / "desktop" / "src-tauri" / "broker" / "src"
        real.mkdir(parents=True, exist_ok=True)
        (real / "main.rs").write_text("// the real one\n", encoding="utf-8")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_a_second_REAL_copy_is_still_ambiguous(self):
        """The exclusion must not become a blanket amnesty: two genuine files that both end in
        the cited suffix are still an ambiguous citation, and still red."""
        root = self._root_citing("broker/src/main.rs")
        other = root / "vendor" / "broker" / "src"
        other.mkdir(parents=True, exist_ok=True)
        (other / "main.rs").write_text("// a second real one\n", encoding="utf-8")
        code, out = run(root)
        self.assertEqual(code, 1, out)


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


def build_git(tmp: pathlib.Path, *, doc: str, state: object = None,
              with_origin_main: bool = True) -> tuple[pathlib.Path, str, str, str]:
    """A root that is a REAL git repository, so the ancestry half can be exercised.

    Returns `(root, base_sha, branch_sha, tree_sha)`. `origin/main` points at
    `base`, and `branch` is one commit past it — the exact shape of a pull
    request whose branch commits a squash merge is about to erase.
    """
    root = build(tmp, doc=doc)
    def g(*args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, check=True).stdout.strip()
    g("init", "--quiet")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "T")
    g("add", "-A")
    g("commit", "--quiet", "-m", "base")
    base = g("rev-parse", "HEAD")
    tree = g("rev-parse", "HEAD^{tree}")
    if with_origin_main:
        g("update-ref", "refs/remotes/origin/main", base)
    g("commit", "--quiet", "--allow-empty", "-m", "a branch commit a squash erases")
    branch = g("rev-parse", "HEAD")
    if state is not None:
        (root / "config" / "current_state.json").write_text(
            json.dumps(state), encoding="utf-8")
    return root, base, branch, tree


class TheAncestryOfACommit(unittest.TestCase):
    """Six merges turned `main` RED on a hash that was fine where it was written.

    `git cat-file -e` asks "does this object exist HERE", and on a pull-request
    branch a branch commit exists perfectly well. It stops existing when the
    squash merge erases the branch — after the merge, where no pull request can
    show it. These tests are about the rule that catches the seventh BEFORE.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="doc-claims-anc-"))

    def test_a_branch_commit_is_red_even_though_it_resolves(self):
        """Mutant: drop the ancestry check ⇒ green, which is exactly the state
        the gate was in for six consecutive merges."""
        root, _base, branch, _tree = build_git(self.tmp, doc="head `PLACEHOLDER`\n")
        (root / "DOC.md").write_text(f"head `{branch}`\n", encoding="utf-8")
        # the OLD rule passes on this very hash — that is what made it invisible
        self.assertEqual(
            subprocess.run(["git", "-C", str(root), "cat-file", "-e", branch]).returncode, 0)
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("NOT an ancestor", out)
        self.assertIn(branch, out)

    def test_the_merge_base_is_green(self):
        """So the refusal above is not a check that cannot pass. The merge base
        survives the squash, which is why the handoff names it."""
        root, base, _branch, _tree = build_git(self.tmp, doc="head `PLACEHOLDER`\n")
        (root / "DOC.md").write_text(f"head `{base}`\n", encoding="utf-8")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_a_tree_hash_is_skipped_and_not_judged_for_ancestry(self):
        """`AUDIT_LEDGER.md` names the TREE of each audited head. `merge-base`
        takes commits; a tree failing an ancestry test would be a true RED about
        the wrong thing."""
        root, _base, _branch, tree = build_git(self.tmp, doc="x\n")
        (root / "DOC.md").write_text(f"tree `{tree}`\n", encoding="utf-8")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_an_anchored_open_pr_head_is_exempt_by_POSITION(self):
        """The one commit a canonical document may name that is not on `main`:
        the head of an open PR, anchored in the mirror where
        `check_repo_state.py` compares it with live GitHub. Exempt because of
        the FIELD it sits in, never because of how the hash looks."""
        root, _base, branch, _tree = build_git(
            self.tmp, doc="x\n",
            state={"prs": [{"number": 112, "head": "PLACEHOLDER"}]})
        (root / "config" / "current_state.json").write_text(
            json.dumps({"prs": [{"number": 112, "head": branch}]}), encoding="utf-8")
        (root / "DOC.md").write_text(f"the open PR is at `{branch}`\n", encoding="utf-8")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_an_unanchored_hash_is_still_red_when_a_mirror_exists(self):
        """The exemption must not become a hole: a mirror that anchors SOMETHING
        does not bless every hash in the document."""
        root, _base, branch, _tree = build_git(
            self.tmp, doc="x\n", state={"prs": [{"number": 112, "head": "0" * 40}]})
        (root / "DOC.md").write_text(f"head `{branch}`\n", encoding="utf-8")
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("NOT an ancestor", out)

    def test_no_resolvable_main_says_so_instead_of_judging_the_hash(self):
        """"I could not check" and "it is fine" are different answers, and so are
        "I could not check" and "your hash is dead". Fail closed, with the real
        problem named."""
        root, _base, branch, _tree = build_git(
            self.tmp, doc="x\n", with_origin_main=False)
        subprocess.run(["git", "-C", str(root), "branch", "-m", "not-main"],
                       capture_output=True, check=False)
        (root / "DOC.md").write_text(f"head `{branch}`\n", encoding="utf-8")
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("could not resolve", out)
        self.assertNotIn("NOT an ancestor", out)


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

    def test_a_bare_sha_in_the_canonical_json_is_red(self):
        """The blind spot, measured 2026-08-30.

        `config/current_state.json` is in the read manifest and this gate has always
        read it — but every commit id in it is plain text inside a JSON string, and the
        pattern required BACKTICKS. `38d5d71504ba68b70b015b958cb09109c80e595a` sat in
        `design_gate.candidate_head_note` for six months naming a branch head a squash
        merge had erased, invisible to a gate that was reading the very file it was
        written in. Closing it moved the sha count on the real tree from 36 to 42.
        """
        root = build(self.tmp, doc=json.dumps({"note": "head abc1234def"}),
                     docname="state.json")
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("abc1234def", out)

    def test_a_bare_sha_in_PROSE_is_still_ignored(self):
        """Deliberately narrower than the JSON case, and this is the arm that says so.

        In prose a bare hex word is as likely to be an example, a digest or an id, and
        the backtick is the author saying 'this is a commit'. In the machine mirror
        there is no such convention to lean on, which is why the rule is `.json` only.
        """
        root = build(self.tmp, doc="the digest abc1234def appears in the payload.\n")
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_a_run_id_in_the_canonical_json_is_not_a_commit(self):
        """An 11-digit GitHub run id is hex-shaped and is a NUMBER.

        The old rule exempted only 7-digit numbers; widening the pattern to bare words
        made `33307104106` -- a real run id in the real mirror -- match. A hex word with
        no letter in it and fewer than 40 characters is not a commit.
        """
        root = build(self.tmp, doc=json.dumps({"run_id": 33307104106}), docname="state.json")
        code, out = run(root)
        self.assertEqual(code, 0, out)

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
        """The documents against the record — the half that is true on every machine.

        Deliberately NOT the machine half. Asking a GitHub runner whether
        `config/toolchain.json` describes it is asking about the wrong box, and this test
        went red in CI for exactly that reason on its first run: it is the same confusion,
        one level up, as the defect this whole file is about. The record-versus-machine
        comparison is covered by the synthetic tests above, which supply the machine.
        """
        code, out = run(ROOT, env_ci=True)
        self.assertEqual(code, 0, out)


class EntryPointRunsEverything(unittest.TestCase):
    def test_unittest_main_is_the_last_statement(self):
        source = pathlib.Path(__file__).read_text(encoding="utf-8").splitlines()
        classes = [i for i, ln in enumerate(source) if ln.startswith("class ")]
        guard = [i for i, ln in enumerate(source) if ln.startswith('if __name__')]
        self.assertEqual(len(guard), 1)
        self.assertGreater(guard[0], max(classes))


if __name__ == "__main__":
    unittest.main()
