"""Self-tests for the GitHub Action pin gate.

A gate is only worth its GREEN if it is proven to go RED. These drive `check()` against
synthetic workflow trees, including a faithful reconstruction of the audit's **F-46** defect
(setup-node pinned to setup-python's commit), so the gate is shown to catch the thing it was
written for rather than merely to pass on today's tree.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from check_action_pins import check

NODE = "39370e3970a6d050c480ffad4ff0ed4d3fdee5af"
PYTHON = "0b93645e9fea7318ecaed2b359559ac225c90a2b"
CHECKOUT = "11bd71901bbe5b1630ceea73d27597364c9af683"


def _tree(root_workflows: dict[str, str], subtree: dict[str, str] | None = None) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp())
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    for name, body in root_workflows.items():
        (wf / name).write_text(body, encoding="utf-8")
    for name, body in (subtree or {}).items():
        p = root / "engine" / ".github" / "workflows" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def _job(*steps: str) -> str:
    return "jobs:\n  build:\n    steps:\n" + "".join(f"      - uses: {s}\n" for s in steps)


class ActionPinGateTests(unittest.TestCase):
    def test_a_consistent_tree_passes(self):
        root = _tree({
            "ci.yml": _job(f"actions/checkout@{CHECKOUT} # v4.2.2",
                           f"actions/setup-node@{NODE} # v4.1.0"),
            "release.yml": _job(f"actions/setup-node@{NODE} # v4.1.0"),
        })
        self.assertEqual(check(root), [])

    def test_F46_one_commit_claimed_by_two_actions_is_red(self):
        # The exact defect: release.yml pins setup-node to setup-PYTHON's commit.
        root = _tree({
            "ci.yml": _job(f"actions/setup-python@{PYTHON} # v5.3.0"),
            "release.yml": _job(f"actions/setup-node@{PYTHON} # v5.3.0"),
        })
        problems = check(root)
        self.assertTrue(any("MORE THAN ONE action" in p for p in problems), problems)
        self.assertTrue(any("F-46" in p for p in problems), problems)

    def test_the_same_action_pinned_two_ways_is_red(self):
        root = _tree({
            "ci.yml": _job(f"actions/setup-node@{NODE} # v4.1.0"),
            "release.yml": _job(f"actions/setup-node@{CHECKOUT} # v4.2.2"),
        })
        self.assertTrue(
            any("pinned inconsistently" in p for p in check(root)), check(root)
        )

    def test_an_undeclared_floating_tag_is_red(self):
        root = _tree({"ci.yml": _job("actions/setup-node@v4")})
        self.assertTrue(
            any("not pinned to a 40-hex commit SHA" in p for p in check(root)), check(root)
        )

    def test_the_declared_floating_exception_is_allowed(self):
        # tauri-action is the ONE declared exception (audit F-15, owner-gated).
        root = _tree({"release.yml": _job("tauri-apps/tauri-action@v0")})
        self.assertEqual(check(root), [])

    def test_a_sha_with_no_version_comment_is_red(self):
        root = _tree({"ci.yml": _job(f"actions/setup-node@{NODE}")})
        self.assertTrue(
            any("no trailing" in p for p in check(root)), check(root)
        )

    def test_an_empty_tree_is_red_not_vacuously_green(self):
        # A gate that verified nothing must never print GREEN (audit F-16/F-19 class).
        root = _tree({"ci.yml": "jobs:\n  build:\n    steps:\n      - run: echo hi\n"})
        self.assertTrue(any("verified nothing" in p for p in check(root)), check(root))

    def test_local_and_container_actions_are_not_pins(self):
        root = _tree({
            "ci.yml": _job("./.github/actions/local", "docker://alpine:3",
                           f"actions/setup-node@{NODE} # v4.1.0"),
        })
        self.assertEqual(check(root), [])

    def test_the_inert_subtree_may_hold_its_own_versions(self):
        # GitHub never dispatches engine/.github (audit F-22) and that copy carries its own pin
        # history, so a DIFFERENT version there is not a failure...
        root = _tree(
            {"ci.yml": _job(f"actions/setup-node@{NODE} # v4.1.0")},
            {"verify.yml": _job(f"actions/setup-node@{CHECKOUT} # v4")},
        )
        self.assertEqual(check(root), [])

    def test_but_a_cross_claimed_commit_in_the_inert_subtree_is_still_red(self):
        # ...while rule 4 is a fact about git, not about versions, so it still applies there.
        root = _tree(
            {"ci.yml": _job(f"actions/setup-python@{PYTHON} # v5.3.0")},
            {"verify.yml": _job(f"actions/setup-node@{PYTHON} # v5.3.0")},
        )
        self.assertTrue(any("MORE THAN ONE action" in p for p in check(root)), check(root))

    def test_the_real_repository_is_green(self):
        self.assertEqual(check(pathlib.Path(__file__).resolve().parents[1]), [])


if __name__ == "__main__":
    unittest.main()
