"""Tests for tools/check_contracts_single_source.py — the cross-half contract drift gate.

Offline and stdlib-only: each test synthesises a whole fake repository (contracts/ + index +
engine/schemas/ + registry) in a temp dir, so nothing here depends on the real tree.

Every test is a mutation of a GREEN tree. A gate whose RED path is never exercised is a gate that
reports the state of its own optimism, which is precisely the ninth audit's `I-12` next door.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_contracts_single_source as cs  # noqa: E402

CROSS = ["execution-lease", "verifier-receipt"]
INTERNAL = ["agent-profile", "skill-receipt"]


def _schema(version: int = 1, envelope: bool = False) -> dict:
    if envelope:
        return {"type": "object", "required": ["payload", "signature"],
                "properties": {"payload": {"properties": {"schema": {"const": version}}}}}
    return {"type": "object", "required": ["schema"], "properties": {"schema": {"const": version}}}


class AgentWorktreeIsNotAStray(unittest.TestCase):
    """The Agent tool checks a subagent's isolated copy of this repository out under
    `.claude/worktrees/<id>/`. On 2026-08-30 that copy made this gate report nine strays — all
    five `contracts/` schemas and all four `bridge/contracts/` ones — on a tree whose real
    content was untouched. RED locally, green in CI: a verdict about the machine."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="contracts-worktree-"))

    def test_a_schema_inside_an_agent_worktree_is_not_a_stray(self):
        """Mutant: drop "worktrees" from _SKIP_DIRS ⇒ red, reporting the copy as a stray."""
        root = self.tmp / "root"
        copy = root / ".claude" / "worktrees" / "agent-abc" / "contracts"
        copy.mkdir(parents=True)
        (copy / "execution-lease.schema.json").write_text("{}", encoding="utf-8")
        self.assertEqual(cs.stray_schema_files(root), [])

    def test_a_real_stray_elsewhere_is_still_reported(self):
        """The exclusion must not become a blanket amnesty."""
        root = self.tmp / "root2"
        stray = root / "vendor"
        stray.mkdir(parents=True)
        (stray / "execution-lease.schema.json").write_text("{}", encoding="utf-8")
        self.assertEqual([p.as_posix() for p in cs.stray_schema_files(root)],
                         ["vendor/execution-lease.schema.json"])


class ContractsSingleSourceTests(unittest.TestCase):
    def _tree(self) -> pathlib.Path:
        """A repository in which the gate is GREEN. Every test breaks exactly one thing about it."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = pathlib.Path(d.name)
        (root / "contracts").mkdir(parents=True)
        (root / "engine" / "schemas").mkdir(parents=True)

        entries = []
        for cid in CROSS:
            body = json.dumps(_schema(), indent=2) + "\n"
            for home in ("contracts", "engine/schemas"):
                (root / home / f"{cid}.schema.json").write_text(body, encoding="utf-8")
            entries.append({"id": cid, "file": f"{cid}.schema.json", "version": 1,
                            "version_pointer": "/properties/schema/const"})
        for cid in INTERNAL:
            (root / "engine" / "schemas" / f"{cid}.schema.json").write_text(
                json.dumps(_schema(), indent=2) + "\n", encoding="utf-8")

        (root / "contracts" / "index.json").write_text(json.dumps({
            "schema": 1, "source_of_record": "contracts/", "vendored_copy": "engine/schemas/",
            "contracts": entries, "engine_internal": {"ids": INTERNAL},
        }, indent=2), encoding="utf-8")
        (root / "engine" / "schemas" / "registry.json").write_text(json.dumps({
            "schema": 1,
            "schemas": [{"id": c, "path": f"schemas/{c}.schema.json"} for c in CROSS + INTERNAL],
        }), encoding="utf-8")
        return root

    # --- the tree the mutations start from -----------------------------------
    def test_a_consistent_tree_is_green(self):
        self.assertEqual(cs.check(self._tree()), [])

    # --- 1. source present ---------------------------------------------------
    def test_a_missing_source_is_red(self):
        root = self._tree()
        (root / "contracts" / "execution-lease.schema.json").unlink()
        problems = cs.check(root)
        self.assertTrue(any("SOURCE of record is not there" in p for p in problems), problems)

    # --- 2. byte-identical ---------------------------------------------------
    def test_drift_between_source_and_copy_is_red(self):
        # The whole point of the gate. Editing the engine's copy alone is the failure mode that
        # made "one definition both halves are held to" untrue while looking tidy on disk.
        root = self._tree()
        p = root / "engine" / "schemas" / "execution-lease.schema.json"
        p.write_text(p.read_text(encoding="utf-8").replace("object", "object "), encoding="utf-8")
        problems = cs.check(root)
        self.assertTrue(any("DRIFTED" in p_ and "execution-lease" in p_ for p_ in problems), problems)

    def test_whitespace_only_drift_is_still_drift(self):
        # A byte comparison, not a JSON one, and deliberately: a reformat of one copy is how two
        # files start looking different enough that nobody diffs them again.
        root = self._tree()
        p = root / "contracts" / "verifier-receipt.schema.json"
        p.write_text(json.dumps(_schema()), encoding="utf-8")   # same JSON, different bytes
        self.assertTrue(any("DRIFTED" in x for x in cs.check(root)))

    def test_a_missing_engine_copy_is_red(self):
        root = self._tree()
        (root / "engine" / "schemas" / "verifier-receipt.schema.json").unlink()
        problems = cs.check(root)
        self.assertTrue(any("the engine loads by that path" in p for p in problems), problems)

    # --- 3. the engine really loads it ---------------------------------------
    def test_a_contract_the_registry_does_not_list_is_red(self):
        root = self._tree()
        reg = root / "engine" / "schemas" / "registry.json"
        doc = json.loads(reg.read_text(encoding="utf-8"))
        doc["schemas"] = [s for s in doc["schemas"] if s["id"] != "verifier-receipt"]
        reg.write_text(json.dumps(doc), encoding="utf-8")
        self.assertTrue(any("does not load it" in p for p in cs.check(root)))

    # --- 4. versioning -------------------------------------------------------
    def test_a_version_bump_in_the_schema_alone_is_red(self):
        root = self._tree()
        body = json.dumps(_schema(version=2), indent=2) + "\n"
        for home in ("contracts", "engine/schemas"):
            (root / home / "execution-lease.schema.json").write_text(body, encoding="utf-8")
        problems = cs.check(root)
        self.assertTrue(any("index says version 1 but the schema says 2" in p for p in problems), problems)

    def test_a_version_pointer_that_resolves_to_nothing_is_red(self):
        root = self._tree()
        idx = root / "contracts" / "index.json"
        doc = json.loads(idx.read_text(encoding="utf-8"))
        doc["contracts"][0]["version_pointer"] = "/properties/nope/const"
        idx.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        self.assertTrue(any("resolves to nothing" in p for p in cs.check(root)))

    def test_an_envelope_schema_is_versioned_through_its_payload(self):
        # mode-grant is signed, so its version is at payload.schema and NOT at the top level.
        # The pointer has to be able to say that, or the real index cannot describe the real tree.
        root = self._tree()
        body = json.dumps(_schema(envelope=True), indent=2) + "\n"
        for home in ("contracts", "engine/schemas"):
            (root / home / "mode-grant.schema.json").write_text(body, encoding="utf-8")
        idx = root / "contracts" / "index.json"
        doc = json.loads(idx.read_text(encoding="utf-8"))
        doc["contracts"].append({"id": "mode-grant", "file": "mode-grant.schema.json", "version": 1,
                                 "version_pointer": "/properties/payload/properties/schema/const"})
        idx.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        reg = root / "engine" / "schemas" / "registry.json"
        rdoc = json.loads(reg.read_text(encoding="utf-8"))
        rdoc["schemas"].append({"id": "mode-grant", "path": "schemas/mode-grant.schema.json"})
        reg.write_text(json.dumps(rdoc), encoding="utf-8")
        self.assertEqual(cs.check(root), [])

    # --- 5. the split is exhaustive ------------------------------------------
    def test_a_new_unclassified_engine_schema_is_red(self):
        # The property that keeps this gate from decaying: a schema added to the engine is a
        # decision about whether the desktop reads it, and the default must be "say so", not
        # "nothing happens".
        root = self._tree()
        (root / "engine" / "schemas" / "brand-new.schema.json").write_text(
            json.dumps(_schema()), encoding="utf-8")
        problems = cs.check(root)
        self.assertTrue(any("brand-new" in p and "neither list" in p for p in problems), problems)

    def test_classifying_a_schema_twice_is_red(self):
        root = self._tree()
        idx = root / "contracts" / "index.json"
        doc = json.loads(idx.read_text(encoding="utf-8"))
        doc["engine_internal"]["ids"].append("execution-lease")
        idx.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        self.assertTrue(any("classified twice" in p for p in cs.check(root)))

    def test_an_index_naming_a_schema_the_engine_does_not_have_is_red(self):
        root = self._tree()
        idx = root / "contracts" / "index.json"
        doc = json.loads(idx.read_text(encoding="utf-8"))
        doc["engine_internal"]["ids"].append("ghost")
        idx.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        self.assertTrue(any("ghost" in p and "does not have" in p for p in cs.check(root)))

    # --- 6. no third copy ----------------------------------------------------
    def test_a_stray_copy_anywhere_else_is_red(self):
        root = self._tree()
        stray = root / "apps" / "desktop" / "src"
        stray.mkdir(parents=True)
        (stray / "execution-lease.schema.json").write_text(json.dumps(_schema()), encoding="utf-8")
        problems = cs.check(root)
        self.assertTrue(any("stray schema" in p for p in problems), problems)

    def test_the_declared_wire_protocol_homes_are_not_strays(self):
        # M3 of the dedupe plan: bridge/ and engine/contracts/ are protocols between two named
        # processes and stay where they are. A gate that reported them would be asking for the
        # wrong fix.
        root = self._tree()
        for home in ("bridge/contracts", "engine/contracts"):
            d = root / home
            d.mkdir(parents=True, exist_ok=True)
            (d / "task-request.schema.json").write_text(json.dumps(_schema()), encoding="utf-8")
        self.assertEqual(cs.check(root), [])

    def test_build_output_is_not_walked(self):
        # node_modules and target/ carry thousands of unrelated *.schema.json; walking them would
        # make the gate both slow and permanently red.
        root = self._tree()
        for noise in ("node_modules/pkg", "apps/desktop/dist/assets", "target/debug"):
            d = root / noise
            d.mkdir(parents=True, exist_ok=True)
            (d / "some.schema.json").write_text("{}", encoding="utf-8")
        self.assertEqual(cs.check(root), [])

    # --- the gate's own preconditions ----------------------------------------
    def test_a_missing_index_raises(self):
        root = self._tree()
        (root / "contracts" / "index.json").unlink()
        with self.assertRaises(SystemExit):
            cs.check(root)

    def test_an_empty_index_raises(self):
        root = self._tree()
        (root / "contracts" / "index.json").write_text(
            json.dumps({"schema": 1, "contracts": []}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            cs.check(root)


if __name__ == "__main__":
    unittest.main()
