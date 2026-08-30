"""Self-tests for the T-056 gate.

Written as fixtures rather than against the real tree, because a gate that is
only ever run on a repository where it happens to be GREEN is a gate nobody has
seen refuse anything.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import check_control_invocation as G  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def build(tmp: pathlib.Path, *, controls: dict, files: dict[str, str],
          workflow: str = "", required: list[str] | None = None,
          hooks: str = "") -> pathlib.Path:
    root = tmp / "root"
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "engine" / "tools").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (root / rel).write_text(text, encoding="utf-8")
    (root / "config" / "required-checks.json").write_text(
        json.dumps({"contexts": required or []}), encoding="utf-8")
    (root / ".github" / "workflows" / "ci.yml").write_text(
        workflow or "name: ci\njobs: {}\n", encoding="utf-8")
    if hooks:
        (root / ".claude" / "hooks" / "h.py").write_text(hooks, encoding="utf-8")
    (root / "config" / "control-invocation.json").write_text(
        json.dumps({"controls": controls}), encoding="utf-8")
    return root


def run(root: pathlib.Path) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = G.main(root)
    return code, buf.getvalue()


WF_REQ = """
name: ci
jobs:
  gate:
    name: The required job
    steps:
      - run: python tools/check_a.py
"""


class ThePopulationIsDerived(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="t056-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_control_on_disk_with_no_entry_is_red(self):
        """Mutant: swap the glob for a list ⇒ green. A gate holding a list can
        omit itself; this is the arm that says so."""
        root = build(self.tmp, controls={}, files={"tools/check_a.py": "x = 1\n"})
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("check_a.py", out)
        self.assertIn("no entry", out)

    def test_an_entry_whose_file_is_gone_is_red(self):
        root = build(self.tmp,
                     controls={"tools/check_ghost.py": {"kind": "check", "blocks": "nothing",
                                                        "why": "x" * 50}},
                     files={})
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("outlived its file", out)

    def test_this_very_gate_is_in_the_real_population(self):
        """Derived, not listed — so it cannot leave itself out."""
        self.assertIn("tools/check_control_invocation.py", G.population(ROOT))


class AConsequenceMustBeOneTheTreeDelivers(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="t056-c-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_blocks_merge_without_a_required_context_is_red(self):
        """Running in CI is not blocking a merge. Two controls in the real tree
        sit exactly here."""
        root = build(self.tmp,
                     controls={"tools/check_a.py": {"kind": "check", "blocks": "merge"}},
                     files={"tools/check_a.py": "x = 1\n"},
                     workflow=WF_REQ, required=[])
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("Running in CI is not blocking a merge", out)

    def test_blocks_merge_with_a_required_context_is_green(self):
        """So the refusal above is not a check that cannot pass."""
        root = build(self.tmp,
                     controls={"tools/check_a.py": {"kind": "check", "blocks": "merge"}},
                     files={"tools/check_a.py": "x = 1\n"},
                     workflow=WF_REQ, required=["The required job"])
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_understating_a_consequence_is_red_too(self):
        root = build(self.tmp,
                     controls={"tools/check_a.py": {"kind": "check", "blocks": "nothing",
                                                    "why": "y" * 50}},
                     files={"tools/check_a.py": "x = 1\n"},
                     workflow=WF_REQ, required=["The required job"])
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("Understating a consequence", out)

    def test_blocks_session_needs_a_hook_that_names_it(self):
        root = build(self.tmp,
                     controls={"tools/check_a.py": {"kind": "check", "blocks": "session"}},
                     files={"tools/check_a.py": "x = 1\n"})
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("names it", out)
        root2 = build(pathlib.Path(tempfile.mkdtemp(prefix="t056-h-")),
                      controls={"tools/check_a.py": {"kind": "check", "blocks": "session"}},
                      files={"tools/check_a.py": "x = 1\n"},
                      hooks="run check_a.py\n")
        self.assertEqual(run(root2)[0], 0)


class TheFailClosedClaimMustBeHonoured(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="t056-f-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_fail_closed_check_that_blocks_nothing_needs_the_sentence(self):
        """`bro_deploy_preflight.py` is the worked example: it calls itself
        fail-closed, nothing invokes it, and being named in a runbook three
        times is a suggestion."""
        root = build(self.tmp,
                     controls={"tools/check_a.py": {"kind": "check", "blocks": "nothing",
                                                    "why": "z" * 50}},
                     files={"tools/check_a.py": '"""A fail-closed gate."""\n'})
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("unenforced_reason", out)

    def test_with_the_sentence_and_a_real_tracker_it_is_green(self):
        root = build(self.tmp,
                     controls={"tools/check_a.py": {
                         "kind": "check", "blocks": "nothing", "why": "z" * 50,
                         "unenforced_reason": "w" * 50, "tracked_by": "TASKS.md"}},
                     files={"tools/check_a.py": '"""A fail-closed gate."""\n',
                            "TASKS.md": "board\n"})
        code, out = run(root)
        self.assertEqual(code, 0, out)

    def test_a_tracker_that_does_not_exist_is_red(self):
        root = build(self.tmp,
                     controls={"tools/check_a.py": {
                         "kind": "check", "blocks": "nothing", "why": "z" * 50,
                         "unenforced_reason": "w" * 50, "tracked_by": "docs/NOPE.md"}},
                     files={"tools/check_a.py": '"""A fail-closed gate."""\n'})
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("does not exist", out)

    def test_a_TOOL_may_block_nothing_without_the_sentence(self):
        """`broctl.py` is a tool, not a check — the Owner's ruling. A tool that
        calls itself fail-closed is describing its own behaviour, not claiming a
        consequence."""
        root = build(self.tmp,
                     controls={"tools/check_a.py": {"kind": "tool", "blocks": "nothing",
                                                    "why": "it does something" + "." * 40}},
                     files={"tools/check_a.py": '"""A fail-closed tool."""\n'})
        self.assertEqual(run(root)[0], 0)

    def test_a_placeholder_reason_is_refused(self):
        root = build(self.tmp,
                     controls={"tools/check_a.py": {"kind": "tool", "blocks": "nothing",
                                                    "why": "n/a"}},
                     files={"tools/check_a.py": "x = 1\n"})
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("not a reason", out)

    def test_blocks_nothing_always_needs_a_why(self):
        root = build(self.tmp,
                     controls={"tools/check_a.py": {"kind": "tool", "blocks": "nothing"}},
                     files={"tools/check_a.py": "x = 1\n"})
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("`why`", out)


class ReadingTheWorkflowsIsNotOptional(unittest.TestCase):
    """The first version imported PyYAML and returned `[]` when that failed —
    which is what happened on the CI runner. The gate then derived no jobs,
    concluded nothing blocks a merge, and went RED on every control while
    passing on the machine that wrote it."""

    def test_the_parser_finds_the_real_workflows_jobs(self):
        jobs = G._yaml_jobs(ROOT)
        self.assertGreater(len(jobs), 20, "the text parser must read the real workflows")
        names = {n for n, _ in jobs}
        self.assertIn("Coordination · docs consistency gate", names)

    def test_the_parser_needs_no_pyyaml(self):
        """Import it under a name PyYAML cannot be reached through, and assert
        the module never asks for it."""
        src = (ROOT / "tools" / "check_control_invocation.py").read_text(encoding="utf-8")
        self.assertNotIn("import yaml", src)

    def test_workflows_that_parse_to_nothing_is_a_READING_failure_not_a_verdict(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="t056-p-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        root = build(tmp,
                     controls={"tools/check_a.py": {"kind": "check", "blocks": "merge"}},
                     files={"tools/check_a.py": "x = 1\n"})
        (root / ".github" / "workflows" / "ci.yml").write_text(
            "name: ci\njobs:\n  gate:\n    name: A job\n", encoding="utf-8")
        _real = G._yaml_jobs
        G._yaml_jobs = lambda _r: []   # the parser reads nothing, as it did on CI
        self.addCleanup(setattr, G, "_yaml_jobs", _real)
        code, out = run(root)
        self.assertEqual(code, 1, out)
        self.assertIn("READING failure", out)
        self.assertNotIn("Running in CI is not blocking a merge", out)


class TheRealTreePasses(unittest.TestCase):
    def test_the_repository_itself_is_green(self):
        code, out = run(ROOT)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
