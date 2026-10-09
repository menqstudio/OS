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

import check_action_pins
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

    def test_tauri_action_is_no_longer_exempt_from_the_pin_rule(self):
        # This test used to assert the OPPOSITE: tauri-action was the one declared exception
        # (audit F-15), so `tauri-apps/tauri-action@v0` was accepted. That exception is gone —
        # release.yml pins the SHA `@v0` resolved to — and the carve-out is deleted rather than
        # left standing. The step holds the Tauri signing key, four Apple secrets and a
        # contents:write token, so a mutable tag there must now be RED like any other.
        root = _tree({"release.yml": _job("tauri-apps/tauri-action@v0")})
        self.assertTrue(
            any("not pinned to a 40-hex commit SHA" in p for p in check(root)), check(root)
        )

    def test_no_action_is_exempt_from_the_pin_rule(self):
        self.assertEqual(
            check_action_pins.FLOATING_ALLOWED, {},
            "an entry here is a standing permission for a mutable tag — adding one must be a "
            "deliberate, reviewed act, not a way to make this gate go quiet",
        )

    def test_a_declared_exception_would_still_be_honoured(self):
        # The mechanism still works — it simply has no members. Proven by declaring one for the
        # length of this test, so removing the last entry did not silently delete the feature.
        root = _tree({"ci.yml": _job("some-org/some-action@v3")})
        self.assertTrue(any("not pinned" in p for p in check(root)), check(root))
        original = dict(check_action_pins.FLOATING_ALLOWED)
        check_action_pins.FLOATING_ALLOWED["some-org/some-action"] = "test exception"
        try:
            self.assertEqual(check(root), [])
        finally:
            check_action_pins.FLOATING_ALLOWED.clear()
            check_action_pins.FLOATING_ALLOWED.update(original)

    def test_the_real_repository_pins_tauri_action_to_a_sha(self):
        # The gate is a rule; this is the fact. Reads the ACTUAL release.yml, so reintroducing
        # `@v0` on the signing step fails here even if someone re-adds the carve-out above.
        repo = pathlib.Path(__file__).resolve().parents[1]
        text = (repo / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        uses = [l.strip() for l in text.splitlines() if "tauri-apps/tauri-action@" in l]
        self.assertEqual(len(uses), 1, uses)
        self.assertRegex(
            uses[0],
            r"uses: tauri-apps/tauri-action@[0-9a-f]{40} # v\d",
            "the release signing step must resolve an immutable commit, with the version in a "
            "trailing comment so the pin stays reviewable",
        )

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

    # ---- workflows rendered by MenQ Standard (T-171) ----

    OTHER_CHECKOUT = "11d5960a326750d5838078e36cf38b85af677262"

    def _with_standard_workflow(self, body: str, recorded: str | None = None) -> pathlib.Path:
        import hashlib
        import json
        root = _tree({
            "ci.yml": _job(f"actions/checkout@{CHECKOUT} # v4.2.2"),
            "menq-standard-update.yml": body,
        })
        digest = recorded or hashlib.sha256(body.encode("utf-8")).hexdigest()
        (root / ".menq-standard.json").write_text(json.dumps({"workflows": {
            ".github/workflows/menq-standard-update.yml": {"sha256": digest}}}), encoding="utf-8")
        return root

    def test_a_workflow_matching_the_standards_pin_keeps_the_standards_versions(self):
        root = self._with_standard_workflow(_job(f"actions/checkout@{self.OTHER_CHECKOUT}"))
        self.assertEqual(check(root), [])

    def test_the_same_workflow_without_a_pin_file_is_red(self):
        root = self._with_standard_workflow(_job(f"actions/checkout@{self.OTHER_CHECKOUT}"))
        (root / ".menq-standard.json").unlink()
        problems = "\n".join(check(root))
        self.assertIn("no trailing", problems)
        self.assertIn("pinned inconsistently", problems)

    def test_a_workflow_edited_after_rendering_loses_the_exemption(self):
        root = self._with_standard_workflow(
            _job(f"actions/checkout@{self.OTHER_CHECKOUT}"), recorded="0" * 64)
        self.assertIn("pinned inconsistently", "\n".join(check(root)))

    def test_a_floating_tag_in_a_standard_workflow_is_still_red(self):
        root = self._with_standard_workflow(_job("actions/checkout@v4"))
        self.assertIn("not pinned to a 40-hex", "\n".join(check(root)))

    def test_a_cross_claimed_commit_in_a_standard_workflow_is_still_red(self):
        root = self._with_standard_workflow(_job(f"actions/setup-node@{CHECKOUT}"))
        self.assertIn("MORE THAN ONE action", "\n".join(check(root)))

    def test_a_crlf_checkout_of_a_standard_workflow_keeps_the_exemption(self):
        import hashlib
        body = _job(f"actions/checkout@{self.OTHER_CHECKOUT}")
        root = self._with_standard_workflow(body, recorded=hashlib.sha256(body.encode()).hexdigest())
        path = root / ".github" / "workflows" / "menq-standard-update.yml"
        path.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(check(root), [])

    def test_a_malformed_pin_file_exempts_nothing(self):
        for text in ("{", "[]", '{"workflows": []}', '{"workflows": {".github/workflows/menq-standard-update.yml": "x"}}'):
            with self.subTest(pin=text):
                root = self._with_standard_workflow(_job(f"actions/checkout@{self.OTHER_CHECKOUT}"))
                (root / ".menq-standard.json").write_text(text, encoding="utf-8")
                self.assertIn("pinned inconsistently", "\n".join(check(root)))

    def test_the_real_repository_is_green(self):
        self.assertEqual(check(pathlib.Path(__file__).resolve().parents[1]), [])


if __name__ == "__main__":
    unittest.main()
