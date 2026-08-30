#!/usr/bin/env python3
"""Self-tests for tools/check_produced_artifact.py — including the GREEN case.

The GREEN case is the load-bearing one. This gate is RED against the real repository by
design and will be for a while, so without a fixture that satisfies all five conditions it
would be a function that can only refuse, and a function that can only refuse measures
nothing. `test_all_five_conditions_met_is_green` builds a synthetic tree meeting every
condition and asserts exit 0; every other test starts from that same tree and breaks exactly
one thing, so each of the five is established independently rather than by cascade.

Run: python -m unittest test_check_produced_artifact   (from tools/)
"""
from __future__ import annotations

import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import check_produced_artifact as gate  # noqa: E402


def _write(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class ProducedArtifactGateTest(unittest.TestCase):
    """Each test mutates ONE thing in a tree that is otherwise fully satisfying."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="produced-artifact-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.build()

    # ---------------------------------------------------------------- fixture

    def build(self) -> None:
        root = self.root
        _write(root / "config" / "produced-artifact-contract.json", {
            "contract_version": 1,
            "store_root": "var/produced-agents",
            "producer_command": "cargo test -p brops-core --test produced_artifact_proof",
            "manifest_filename": "manifest.json",
            "artifact_schema": "contracts/produced-agent-artifact.schema.json",
            "manifest_keys": {"artifact_id": "artifact_id", "flow": "flow", "grant": "grant"},
            "flow_steps_key": "steps",
            "grant_axis_keys": ["capabilities", "paths", "domains"],
            "grant_writer_key": "written_by",
            "runs_path": "var/produced-runs.jsonl",
            "run_keys": {"run_id": "run_id", "artifact_id": "artifact_id", "invoked_by": "invoked_by"},
            "run_invoked_by": "run_due",
            "receipts_path": "var/produced-receipts.jsonl",
            "receipt_keys": {"run_id": "run_id", "enforcement_regime": "enforcement_regime"},
        })
        _write(root / "contracts" / "produced-agent-artifact.schema.json", {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["schema", "artifact_id", "flow", "grant"],
            "properties": {
                "schema": {"type": "integer"},
                "artifact_id": {"type": "string"},
                "flow": {"type": "string"},
                "grant": {"type": "string"},
            },
        })
        # Condition 4 re-grounds itself in the tree before believing a run row that cites run_due.
        _write(root / "apps" / "desktop" / "src-tauri" / "core" / "src" / "repo.rs",
               "pub fn run_due(conn: &Connection, now_ms: i64) -> CoreResult<Vec<AutomationRun>> {}\n")
        _write(root / "var" / "produced-agents" / "agt-1" / "manifest.json", {
            "schema": 1,
            "artifact_id": "agt-1",
            "flow": "flow.json",
            "grant": "grant.json",
        })
        _write(root / "var" / "produced-agents" / "agt-1" / "flow.json", {
            "steps": [{"id": "classify"}, {"id": "notify"}],
        })
        _write(root / "var" / "produced-agents" / "agt-1" / "grant.json", {
            "capabilities": ["READ_LOCAL", "SEND_COMMUNICATION"],
            "paths": [],
            "domains": ["hooks.slack.com"],
            "written_by": "brops-core::agents::grant_writer",
        })
        _write(root / "var" / "produced-runs.jsonl",
               json.dumps({"run_id": "run-1", "artifact_id": "agt-1", "invoked_by": "run_due"}) + "\n")
        _write(root / "var" / "produced-receipts.jsonl",
               json.dumps({"run_id": "run-1", "enforcement_regime": "governed"}) + "\n")

    # ------------------------------------------------------------- utilities

    def conditions(self) -> dict[int, gate.Condition]:
        return {c.number: c for c in gate.evaluate(self.root)}

    def assert_only_failure(self, number: int) -> gate.Condition:
        """The named condition fails and every EARLIER one still passes.

        Later conditions are allowed to cascade — a broken artifact genuinely leaves nothing
        for a run to have invoked — but an earlier one going red means the test broke
        something other than what it meant to.
        """
        found = self.conditions()
        self.assertFalse(found[number].ok, f"condition {number} should fail: {found[number].detail}")
        for earlier in range(1, number):
            self.assertTrue(found[earlier].ok,
                            f"condition {earlier} broke too: {found[earlier].detail}")
        return found[number]

    def contract(self):
        return json.loads((self.root / gate.CONTRACT).read_text())

    def put_contract(self, doc) -> None:
        _write(self.root / gate.CONTRACT, doc)

    def manifest(self):
        return json.loads((self.root / "var/produced-agents/agt-1/manifest.json").read_text())

    def put_manifest(self, doc) -> None:
        _write(self.root / "var/produced-agents/agt-1/manifest.json", doc)

    # -------------------------------------------------------------- the GREEN case

    def test_all_five_conditions_met_is_green(self):
        found = self.conditions()
        for n in range(1, 6):
            self.assertTrue(found[n].ok, f"condition {n} failed on the satisfying fixture: "
                                         f"{found[n].detail}")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = gate.main(["--root", str(self.root)])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertIn("GREEN:", out.getvalue())

    def test_the_real_repository_is_red_and_says_why_in_five_lines(self):
        repo = pathlib.Path(__file__).resolve().parents[1]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = gate.main(["--root", str(repo)])
        self.assertEqual(rc, 1, "the production half does not exist; this gate must be RED")
        text = err.getvalue()
        self.assertIn("RED BY DESIGN", text)
        self.assertIn("When does a customer see something?", text)
        for n in range(1, 6):
            self.assertIn(f"  {n}. MISSING", text)

    # ------------------------------------------------------------- condition 1

    def test_c1_undeclared_store_root(self):
        doc = self.contract()
        doc["store_root"] = None
        self.put_contract(doc)
        self.assertIn("declares no `store_root`", self.assert_only_failure(1).detail)

    def test_c1_store_declared_but_never_produced(self):
        shutil.rmtree(self.root / "var" / "produced-agents")
        self.assertIn("does not exist", self.assert_only_failure(1).detail)

    def test_c1_store_is_empty_of_artifacts(self):
        shutil.rmtree(self.root / "var" / "produced-agents" / "agt-1")
        self.assertIn("holds no directory containing", self.assert_only_failure(1).detail)

    def test_c1_refuses_a_verb_argument_row(self):
        self.put_manifest({"action": "notify: invoice overdue"})
        detail = self.assert_only_failure(1).detail
        self.assertIn("verb: argument", detail)

    def test_c1_refuses_a_manifest_that_violates_its_schema(self):
        doc = self.manifest()
        del doc["artifact_id"]
        self.put_manifest(doc)
        self.assertIn("missing required field `artifact_id`", self.assert_only_failure(1).detail)

    def test_c1_refuses_a_declared_type_mismatch(self):
        doc = self.manifest()
        doc["schema"] = "one"
        self.put_manifest(doc)
        self.assertIn("schema declares integer", self.assert_only_failure(1).detail)

    def test_c1_refuses_an_undefined_schema(self):
        doc = self.contract()
        doc["artifact_schema"] = None
        self.put_contract(doc)
        self.assertIn("declares no `artifact_schema`", self.assert_only_failure(1).detail)

    def test_c1_refuses_a_schema_file_that_defines_nothing(self):
        _write(self.root / "contracts" / "produced-agent-artifact.schema.json", {"type": "object"})
        self.assertIn("defines nothing", self.assert_only_failure(1).detail)

    def test_c1_refuses_a_store_committed_to_git(self):
        """Evidence must be PRODUCED, not COMMITTED — the one control that stops this gate
        being satisfiable by checking a fixture in."""
        if shutil.which("git") is None:
            self.skipTest("git unavailable")
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
               "PATH": "/usr/bin:/bin", "HOME": str(self.root)}
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, env=env)
        subprocess.run(["git", "-C", str(self.root), "add", "var/produced-agents"],
                       check=True, env=env)
        self.assertIn("tracked in git", self.assert_only_failure(1).detail)

    # ------------------------------------------------------------- condition 2

    def test_c2_a_single_step_is_not_a_flow(self):
        _write(self.root / "var/produced-agents/agt-1/flow.json", {"steps": [{"id": "only"}]})
        self.assertIn("requires more than one", self.assert_only_failure(2).detail)

    def test_c2_no_flow_at_all(self):
        doc = self.manifest()
        doc["flow"] = ""
        self.put_manifest(doc)
        self.assertIn("declares no flow", self.assert_only_failure(2).detail)

    def test_c2_flow_reference_escaping_the_artifact_is_refused(self):
        """The escaping target must EXIST and be otherwise VALID, or this test passes for the
        wrong reason. The first version of it pointed at `../../../etc/passwd`, which resolves
        inside a temp tree to a path that does not exist -- so it went red on "no such file"
        whether or not the containment guard was there. The mutation sweep caught it: deleting
        `candidate.relative_to(base.resolve())` left the test GREEN. Here the outside file is a
        perfectly good two-step flow, so without the guard condition 2 would PASS.
        """
        _write(self.root / "outside" / "flow.json", {"steps": [{"id": "a"}, {"id": "b"}]})
        doc = self.manifest()
        doc["flow"] = "../../../outside/flow.json"
        self.put_manifest(doc)
        self.assertIn("not a file inside the artifact", self.assert_only_failure(2).detail)

    def test_c2_undeclared_steps_key(self):
        doc = self.contract()
        doc["flow_steps_key"] = None
        self.put_contract(doc)
        self.assertIn("declares no `flow_steps_key`", self.assert_only_failure(2).detail)

    # ------------------------------------------------------------- condition 3

    def test_c3_absent_grant_is_a_refusal_not_unrestricted(self):
        doc = self.manifest()
        doc["grant"] = ""
        self.put_manifest(doc)
        detail = self.assert_only_failure(3).detail
        self.assertIn("never `unrestricted`", detail)

    def test_c3_a_grant_that_lives_in_a_prompt_is_prose(self):
        doc = self.manifest()
        doc["grant"] = "prompts/grant.md"
        self.put_manifest(doc)
        self.assertIn("prompt or a document", self.assert_only_failure(3).detail)

    def test_c3_a_grant_written_by_a_prompt_is_refused(self):
        _write(self.root / "var/produced-agents/agt-1/grant.json", {
            "capabilities": ["READ_LOCAL"], "written_by": "prompts/build-agent.md"})
        self.assertIn("condition 3's exact exclusion", self.assert_only_failure(3).detail)

    def test_c3_a_grant_empty_on_every_axis_grants_nothing(self):
        _write(self.root / "var/produced-agents/agt-1/grant.json", {
            "capabilities": [], "paths": [], "domains": [],
            "written_by": "brops-core::agents::grant_writer"})
        self.assertIn("empty on every declared axis", self.assert_only_failure(3).detail)

    def test_c3_a_grant_with_no_writer_cannot_claim_the_runtime_wrote_it(self):
        _write(self.root / "var/produced-agents/agt-1/grant.json", {"capabilities": ["READ_LOCAL"]})
        self.assertIn("does not say what wrote it", self.assert_only_failure(3).detail)

    def test_c3_undeclared_writer_key(self):
        doc = self.contract()
        doc["grant_writer_key"] = None
        self.put_contract(doc)
        self.assertIn("declares no `grant_writer_key`", self.assert_only_failure(3).detail)

    # ------------------------------------------------------------- condition 4

    def test_c4_no_run_row(self):
        _write(self.root / "var" / "produced-runs.jsonl", "")
        self.assertIn("none of them is `run_due`", self.assert_only_failure(4).detail)

    def test_c4_a_run_nobody_scheduled_does_not_count(self):
        _write(self.root / "var" / "produced-runs.jsonl", json.dumps(
            {"run_id": "run-1", "artifact_id": "agt-1", "invoked_by": "manual"}) + "\n")
        self.assertIn("none of them is `run_due`", self.assert_only_failure(4).detail)

    def test_c4_a_run_of_some_other_artifact_does_not_count(self):
        _write(self.root / "var" / "produced-runs.jsonl", json.dumps(
            {"run_id": "run-1", "artifact_id": "agt-other", "invoked_by": "run_due"}) + "\n")
        self.assertIn("none of them is `run_due`", self.assert_only_failure(4).detail)

    def test_c4_refuses_evidence_citing_a_function_that_does_not_exist(self):
        (self.root / "apps/desktop/src-tauri/core/src/repo.rs").unlink()
        self.assertIn("no `fn run_due` is defined", self.assert_only_failure(4).detail)

    def test_c4_refuses_a_committed_run_log(self):
        if shutil.which("git") is None:
            self.skipTest("git unavailable")
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
               "PATH": "/usr/bin:/bin", "HOME": str(self.root)}
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, env=env)
        subprocess.run(["git", "-C", str(self.root), "add", "var/produced-runs.jsonl"],
                       check=True, env=env)
        self.assertIn("tracked in git", self.assert_only_failure(4).detail)

    # ------------------------------------------------------------- condition 5

    def test_c5_a_receipt_without_enforcement_regime(self):
        _write(self.root / "var" / "produced-receipts.jsonl",
               json.dumps({"run_id": "run-1", "outcome": "ok"}) + "\n")
        self.assertIn("none carries a non-empty", self.assert_only_failure(5).detail)

    def test_c5_an_empty_enforcement_regime_is_not_a_regime(self):
        _write(self.root / "var" / "produced-receipts.jsonl",
               json.dumps({"run_id": "run-1", "enforcement_regime": "   "}) + "\n")
        self.assertIn("none carries a non-empty", self.assert_only_failure(5).detail)

    def test_c5_a_receipt_for_a_different_run(self):
        _write(self.root / "var" / "produced-receipts.jsonl",
               json.dumps({"run_id": "run-9", "enforcement_regime": "governed"}) + "\n")
        self.assertIn("no receipt for run `run-1`", self.assert_only_failure(5).detail)

    def test_c5_no_receipt_store(self):
        (self.root / "var" / "produced-receipts.jsonl").unlink()
        self.assertIn("the run produced no receipt", self.assert_only_failure(5).detail)

    # ------------------------------------------------------------- the contract itself

    def test_an_unreadable_contract_fails_all_five(self):
        (self.root / gate.CONTRACT).write_text("{ not json", encoding="utf-8")
        found = self.conditions()
        for n in range(1, 6):
            self.assertFalse(found[n].ok)
            self.assertIn("not readable JSON", found[n].detail)


if __name__ == "__main__":
    unittest.main()
