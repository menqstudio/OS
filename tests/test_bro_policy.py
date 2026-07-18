import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import os

from bro_authorization import classify_tool_action
from bro_policy import (
    CANONICAL_CONDUCTOR_ID,
    CONDUCTOR_ROLE,
    UNKNOWN_ROLE,
    State,
    authorize_classified_action,
    current_state,
    is_conductor,
)


def bundle(agent_id="agent-1"):
    return SimpleNamespace(
        agent={"agent_id": agent_id},
        task={
            "scope": ["runtime/"],
            "prohibited_scope": ["runtime/secret/"],
            "repository": {
                "full_name": "menqstudio/Bro",
                "branch": "bro-execution-control-plane-v2",
            },
        },
    )


class PolicyTests(unittest.TestCase):
    def classified(self, tool, value):
        return classify_tool_action(tool, value, ROOT)

    def test_review_denies_canonical_write(self):
        classification = self.classified("Write", {"file_path": "runtime/x.py"})
        self.assertFalse(authorize_classified_action(State("review", "bro", "s"), classification, {})[0])

    def test_review_allows_canonical_read(self):
        classification = self.classified("Read", {"file_path": "README.md"})
        self.assertTrue(authorize_classified_action(State("review", "bro", "s"), classification, {})[0])

    def test_bro_cannot_mutate(self):
        classification = self.classified("Write", {"file_path": "runtime/x.py"})
        ok, reason = authorize_classified_action(State("work", "bro", "s"), classification, {})
        self.assertFalse(ok)
        self.assertIn("delegate", reason)

    def test_push_cannot_enter_downstream_policy(self):
        classification = self.classified("Bash", {"command": "git push origin HEAD:bro-execution-control-plane-v2"})
        ok, reason = authorize_classified_action(State("release", "push-executor", "s", "agent-1"), classification, {})
        self.assertFalse(ok)
        self.assertIn("Release Grant V3", reason)

    @patch("bro_policy._grant_bindings_ok", return_value=(True, "bound"))
    @patch("bro_policy.enforce_scope")
    @patch("bro_policy.load_mode_grant_from_env")
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_specialist_mutation_uses_canonical_targets(self, load_bundle, load_mode, enforce, binding):
        load_bundle.return_value = bundle()
        load_mode.return_value = {"mode": "work"}
        classification = self.classified("Write", {"file_path": "runtime/x.py"})
        ok, reason = authorize_classified_action(State("work", "specialist", "s", "agent-1"), classification, {})
        self.assertTrue(ok, reason)
        enforce.assert_called_once_with(ROOT, ["runtime/x.py"], ["runtime/"], ["runtime/secret/"])
        binding.assert_called_once()

    @patch("bro_policy.load_contract_bundle_from_env", side_effect=Exception("must not load"))
    def test_review_read_needs_no_contract(self, load_bundle):
        classification = self.classified("Read", {"file_path": "README.md"})
        ok, _ = authorize_classified_action(State("review", "bro", "s"), classification, {})
        self.assertTrue(ok)
        load_bundle.assert_not_called()


class RoleDefaultTests(unittest.TestCase):
    """A privileged default means forgetting to configure an identity grants one."""

    def classified(self, tool, value):
        return classify_tool_action(tool, value, ROOT)

    def test_unset_role_is_unauthenticated(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(current_state({}).role, UNKNOWN_ROLE)

    def test_blank_role_is_unauthenticated(self):
        with patch.dict(os.environ, {"BRO_ROLE": "   "}):
            self.assertEqual(current_state({}).role, UNKNOWN_ROLE)

    def test_unset_role_cannot_mutate(self):
        classification = self.classified("Write", {"file_path": "runtime/x.py"})
        ok, reason = authorize_classified_action(
            State("work", UNKNOWN_ROLE, "s"), classification, {})
        self.assertFalse(ok)
        self.assertIn("unauthenticated", reason)

    def test_unset_role_does_not_inherit_conductor_exemption(self):
        self.assertFalse(is_conductor(State("work", UNKNOWN_ROLE, "s", "")))

    def test_conductor_needs_the_canonical_identity(self):
        self.assertTrue(is_conductor(State("work", CONDUCTOR_ROLE, "s", CANONICAL_CONDUCTOR_ID)))

    def test_role_name_alone_is_not_the_conductor(self):
        """There is exactly one Bro; claiming the role name is not being it."""
        self.assertFalse(is_conductor(State("work", CONDUCTOR_ROLE, "s", "agt-p01-r01")))
        self.assertFalse(is_conductor(State("work", CONDUCTOR_ROLE, "s", "")))

    def test_canonical_id_without_the_role_is_not_the_conductor(self):
        self.assertFalse(is_conductor(State("work", "specialist", "s", CANONICAL_CONDUCTOR_ID)))


class DelegationTests(unittest.TestCase):
    """The contract requires Bro to delegate; leaving delegation unregistered made
    it classify UNKNOWN, so the control plane forbade the one thing Bro must do."""

    def classified(self, tool, value=None):
        return classify_tool_action(tool, value or {}, ROOT)

    def conductor(self, mode="work"):
        return State(mode, CONDUCTOR_ROLE, "s", CANONICAL_CONDUCTOR_ID)

    def test_delegation_is_registered(self):
        for tool in ("Task", "Agent", "Skill", "TodoWrite"):
            classification = self.classified(tool)
            self.assertFalse(classification.unknown, tool)
            self.assertTrue(classification.orchestration, tool)

    def test_delegation_is_not_mutation(self):
        self.assertFalse(self.classified("Task").mutating)

    def test_conductor_may_delegate_in_work(self):
        ok, reason = authorize_classified_action(self.conductor(), self.classified("Task"), {})
        self.assertTrue(ok, reason)
        self.assertIn("supervisor issues the lease", reason)

    def test_review_denies_delegation(self):
        ok, reason = authorize_classified_action(
            self.conductor("review"), self.classified("Task"), {})
        self.assertFalse(ok)
        self.assertIn("findings only", reason)

    def test_specialist_may_not_delegate(self):
        ok, reason = authorize_classified_action(
            State("work", "specialist", "s", "agt-p01-r01"), self.classified("Task"), {})
        self.assertFalse(ok)
        self.assertIn("only the canonical conductor", reason)

    def test_unauthenticated_may_not_delegate(self):
        ok, _ = authorize_classified_action(
            State("work", UNKNOWN_ROLE, "s", ""), self.classified("Task"), {})
        self.assertFalse(ok)

    def test_role_name_alone_may_not_delegate(self):
        ok, _ = authorize_classified_action(
            State("work", CONDUCTOR_ROLE, "s", "agt-p01-r01"), self.classified("Task"), {})
        self.assertFalse(ok)

    def test_delegation_still_cannot_write(self):
        """Delegating must not become a mutation bypass."""
        ok, reason = authorize_classified_action(
            self.conductor(), self.classified("Write", {"file_path": "runtime/x.py"}), {})
        self.assertFalse(ok)
        self.assertIn("delegate", reason)

    def test_unknown_tool_still_denies(self):
        self.assertTrue(self.classified("SomeInventedTool").unknown)


class ConductorBootstrapReadTests(unittest.TestCase):
    """The conductor must read the repository to bootstrap and orchestrate. In
    work/release mode every action used to require a full task-contract bundle,
    including read-only ones, so the canonical conductor could not read at all:
    the fail-closed wall closed on Bro itself. The bootstrap exemption is
    conductor-only, read-only, and cannot reach mutation or any non-read
    capability."""

    def classified(self, tool, value=None):
        return classify_tool_action(tool, value or {}, ROOT)

    def conductor(self, mode="work"):
        return State(mode, CONDUCTOR_ROLE, "s", CANONICAL_CONDUCTOR_ID)

    @patch("bro_policy.load_contract_bundle_from_env", side_effect=Exception("must not load"))
    def test_conductor_may_read_local_without_a_contract(self, load_bundle):
        classification = self.classified("Read", {"file_path": "README.md"})
        ok, reason = authorize_classified_action(self.conductor(), classification, {})
        self.assertTrue(ok, reason)
        self.assertIn("bootstrap", reason)
        load_bundle.assert_not_called()

    def test_bootstrap_is_read_only_and_cannot_mutate(self):
        classification = self.classified("Write", {"file_path": "runtime/x.py"})
        ok, reason = authorize_classified_action(self.conductor(), classification, {})
        self.assertFalse(ok)
        self.assertIn("delegate", reason)

    def test_bootstrap_does_not_extend_to_delegation(self):
        """Orchestration keeps its own conductor path and message; the read-only
        exemption must not swallow it."""
        ok, reason = authorize_classified_action(self.conductor(), self.classified("Task"), {})
        self.assertTrue(ok, reason)
        self.assertIn("supervisor issues the lease", reason)

    def test_bootstrap_requires_the_canonical_identity(self):
        """Role string alone is not the conductor: a bro-role session without the
        canonical id gets no read exemption and falls through to the contract gate."""
        classification = self.classified("Read", {"file_path": "README.md"})
        ok, reason = authorize_classified_action(
            State("work", CONDUCTOR_ROLE, "s", "agt-p01-r01"), classification, {})
        self.assertFalse(ok)
        self.assertIn("task/agent/skill gate", reason)

    def test_specialist_read_still_needs_a_contract(self):
        classification = self.classified("Read", {"file_path": "README.md"})
        ok, reason = authorize_classified_action(
            State("work", "specialist", "s", "agt-p01-r01"), classification, {})
        self.assertFalse(ok)
        self.assertIn("task/agent/skill gate", reason)

    def test_shell_command_substitution_is_denied_at_classification(self):
        """$() command substitution can smuggle a mutation behind a read-only exe,
        so it is rejected when the command is classified and never reaches the
        bootstrap exemption or the mutating-gated scope check."""
        from bro_security import SecurityError
        with self.assertRaises(SecurityError):
            self.classified("Bash", {"command": "cat $(rm -rf runtime/bro_policy.py)"})

    def test_bootstrap_excludes_bash_reads(self):
        """Even a benign shell read is outside the bootstrap allowlist
        (Read/Glob/Grep only), so the conductor's Bash falls through to the full
        contract gate rather than the read-only exemption."""
        classification = self.classified("Bash", {"command": "cat README.md"})
        self.assertEqual(classification.capabilities, ("READ_LOCAL",))
        ok, reason = authorize_classified_action(self.conductor(), classification, {})
        self.assertFalse(ok)
        self.assertNotIn("bootstrap", reason)
        self.assertIn("task/agent/skill gate", reason)

    def test_bootstrap_allows_glob_and_grep(self):
        for tool, tool_input in (("Glob", {"pattern": "**/*.py"}), ("Grep", {"pattern": "def "})):
            with patch("bro_policy.load_contract_bundle_from_env", side_effect=Exception("must not load")):
                ok, reason = authorize_classified_action(
                    self.conductor(), self.classified(tool, tool_input), {})
                self.assertTrue(ok, f"{tool}: {reason}")


class ReceiptFreshnessTests(unittest.TestCase):
    """L1 literacy and L8 thirty-minute reread: the audit's missing freshness coverage."""

    def _write_receipt(self, session_id, *, age=0, tree=None):
        import json
        import time

        import bro_policy
        receipt = {
            "schema": 1,
            "session_id": session_id,
            "read_at_epoch": int(time.time()) - age,
            "tree_identity": bro_policy.tree_identity() if tree is None else tree,
        }
        path = bro_policy.receipt_path(session_id)
        path.write_text(json.dumps(receipt), encoding="utf-8")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return session_id

    def test_literacy_allows_fresh_receipt(self):
        import bro_policy
        ok, reason = bro_policy.receipt_fresh(self._write_receipt("olts-fresh", age=0))
        self.assertTrue(ok, reason)

    def test_literacy_denies_missing_receipt(self):
        import bro_policy
        ok, reason = bro_policy.receipt_fresh("olts-no-such-session-xyz")
        self.assertFalse(ok)
        self.assertIn("missing", reason)

    def test_reread_allows_within_interval(self):
        import bro_policy
        ok, reason = bro_policy.receipt_fresh(self._write_receipt("olts-recent", age=100))
        self.assertTrue(ok, reason)

    def test_reread_blocks_when_stale(self):
        import bro_policy
        ok, reason = bro_policy.receipt_fresh(self._write_receipt("olts-stale", age=100000))
        self.assertFalse(ok)
        self.assertIn("stale", reason)

    def test_tree_change_after_receipt_is_denied(self):
        import bro_policy
        ok, reason = bro_policy.receipt_fresh(self._write_receipt("olts-treechg", age=0, tree="0" * 64))
        self.assertFalse(ok)
        self.assertIn("tree changed", reason)


if __name__ == "__main__":
    unittest.main()
