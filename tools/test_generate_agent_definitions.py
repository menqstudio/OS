#!/usr/bin/env python3
"""Tests for generate_agent_definitions.py.

Run: python -m unittest test_generate_agent_definitions   (from tools/)

The generator had no test and `--check` ran nowhere: `START_HERE.md` listed it as a manual
pre-PR step, and the only automated comparison was the three tier files' `tools:` lines against
`ai.rs`. So 259 role definitions could drift from the registries with every gate green. This
file is the automated half; it is named on a CI line so it is also the invocation.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import generate_agent_definitions as gen  # noqa: E402


def run_check() -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = gen.main(["--check"])
    return code, out.getvalue()


def frontmatter(text: str) -> dict[str, str]:
    """The `key: value` lines between the two `---` fences, values left as written."""
    lines = text.splitlines()
    assert lines[0] == "---", lines[0]
    end = lines.index("---", 1)
    return dict(line.split(": ", 1) for line in lines[1:end])


class TheCommittedDefinitions(unittest.TestCase):
    """`.claude/agents/` is generated output. It must be what the generator produces today."""

    def test_the_committed_files_match_the_registries(self):
        code, out = run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("GREEN", out)

    def test_the_verdict_counts_what_is_on_disk(self):
        wanted = gen.build()
        on_disk = {p.stem for p in gen.OUT_DIR.glob("*.md")}
        self.assertEqual(on_disk, set(wanted))


class TheCheckGoesRed(unittest.TestCase):
    """`--check` against a scratch output directory, one kind of drift at a time."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = pathlib.Path(tmp.name)
        for name, text in gen.build().items():
            (self.out / f"{name}.md").write_text(text, encoding="utf-8")
        patcher = mock.patch.object(gen, "OUT_DIR", self.out)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_faithful_copy_is_green(self):
        code, out = run_check()
        self.assertEqual(code, 0, out)

    def test_a_missing_definition_is_red(self):
        (self.out / "runner.md").unlink()
        code, out = run_check()
        self.assertEqual(code, 1)
        self.assertIn("runner: missing", out)

    def test_a_hand_edited_definition_is_red(self):
        path = self.out / "builder.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "tools: Read, Edit, Write, Grep, Glob, Bash", "tools: *"), encoding="utf-8")
        code, out = run_check()
        self.assertEqual(code, 1)
        self.assertIn("builder: drifted from the registry", out)

    def test_a_definition_the_registry_no_longer_has_is_red(self):
        (self.out / "ghost--role.md").write_text("---\nname: ghost--role\n---\n", encoding="utf-8")
        code, out = run_check()
        self.assertEqual(code, 1)
        self.assertIn("ghost--role: no longer in the registry", out)

    def test_an_absent_output_directory_is_red_not_empty_green(self):
        with mock.patch.object(gen, "OUT_DIR", self.out / "nowhere"):
            code, out = run_check()
        self.assertEqual(code, 1)
        self.assertIn("missing", out)


class TheFrontmatter(unittest.TestCase):
    """Every generated header must be YAML a loader can read.

    `builder.md` was not: its description went out as a PLAIN scalar opening "Full working
    capability: reads, ..." and PyYAML refuses that at line 3, column 37.
    """

    def setUp(self):
        self.files = gen.build()

    def test_every_description_is_a_quoted_scalar_that_round_trips(self):
        for name, text in self.files.items():
            with self.subTest(name=name):
                fields = frontmatter(text)
                self.assertEqual(list(fields), ["name", "description", "tools"])
                description = json.loads(fields["description"])
                self.assertIsInstance(description, str)
                self.assertTrue(description.strip())

    def test_the_plain_scalars_carry_nothing_yaml_would_reread(self):
        """`name` and `tools` stay unquoted -- `ai.rs` and the vitest guard read the `tools:`
        line as written -- so they must hold no `: ` and no ` #`."""
        for name, text in self.files.items():
            fields = frontmatter(text)
            for key in ("name", "tools"):
                with self.subTest(name=name, key=key):
                    self.assertNotRegex(fields[key], r": | #|^[\[{\"'&*!|>%@`]")

    def test_pyyaml_agrees_when_it_is_installed(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed; the stdlib checks above are the gate")
        for name, text in self.files.items():
            with self.subTest(name=name):
                block = text.split("---\n")[1]
                loaded = yaml.safe_load(block)
                self.assertEqual(loaded["name"], name)
                self.assertEqual(loaded["description"],
                                 json.loads(frontmatter(text)["description"]))

    def test_the_description_keeps_the_roles_own_spelling(self):
        """`role.lower()` produced "needs a sre lead" in the text an agent is PICKED by."""
        text = self.files["sre-reliability--sre-lead"]
        self.assertIn("calls for the SRE Lead.", json.loads(frontmatter(text)["description"]))
        for name, body in self.files.items():
            self.assertNotIn("needs a ", frontmatter(body)["description"], name)


class WhatTheTextClaims(unittest.TestCase):
    """The generated prose may not claim more than the tool list delivers."""

    def setUp(self):
        self.files = gen.build()

    def test_no_definition_says_a_bash_holder_cannot_edit(self):
        """The runner tier said "but cannot edit" over `Read, Grep, Glob, Bash`. A shell
        writes any file and the root wall does not refuse it in advance."""
        for name, text in self.files.items():
            if "Bash" in frontmatter(text)["tools"]:
                with self.subTest(name=name):
                    self.assertNotIn("cannot edit", text)
                    self.assertNotIn("cannot change anything", text)

    def test_every_role_without_the_edit_tools_is_told_what_bash_can_do(self):
        without = [name for name, text in self.files.items()
                   if frontmatter(text)["tools"] == gen.TOOLS_NO_EDIT and "--" in name]
        self.assertGreater(len(without), 50, "the designated verifiers are gone from the registry")
        for name in without:
            with self.subTest(name=name):
                self.assertIn(gen.NO_EDIT_NOTE, self.files[name])
        self.assertIn("holds no Edit or Write tool. Bash can still write",
                      self.files["runner"])

    def test_a_builder_is_not_given_the_no_edit_note(self):
        self.assertNotIn(gen.NO_EDIT_NOTE, self.files["sre-reliability--sre-lead"])
        self.assertNotIn(gen.NO_EDIT_NOTE, self.files["builder"])

    def test_the_reader_tier_holds_no_shell(self):
        """It is the one tier that may say "cannot change anything", and only while this holds."""
        self.assertEqual(frontmatter(self.files["reader"])["tools"], "Read, Grep, Glob")

    def test_the_read_order_is_the_manifest_not_a_second_list(self):
        """CLAUDE.md: the manifest "is the read order and the only one". All 262 files named
        two documents of their own instead."""
        self.assertTrue((ROOT / "config" / "canonical-read-manifest.json").is_file())
        for name, text in self.files.items():
            with self.subTest(name=name):
                self.assertIn("`config/canonical-read-manifest.json`", text)
                self.assertNotIn("START_HERE.md", text)


class TheEngineIsTheAuthority(unittest.TestCase):
    """`authority_for` re-derives what `bro_authority.resolve_role_authority` enforces. Two
    derivations of one rule are held together here, for every role the generator writes."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "engine" / "runtime"))
        try:
            import bro_authority
            import bro_identity
        finally:
            sys.path.pop(0)
        cls.engine_authority = bro_authority
        cls.engine_identity = bro_identity
        cls.packs, cls.policy = gen.load()

    def test_every_generated_role_carries_the_engines_record(self):
        checked = 0
        for pack in self.packs:
            for role in pack["roles"]:
                with self.subTest(pack=pack["id"], role=role):
                    record, _ = gen.authority_for(self.policy, pack, role)
                    engine = self.engine_authority.resolve_role_authority(pack["id"], role)
                    self.assertEqual(
                        (bool(record.get("can_build")), bool(record.get("can_verify")),
                         bool(record.get("can_release")), tuple(record.get("allowed_modes", [])),
                         record.get("risk_ceiling")),
                        (engine.can_build, engine.can_verify, engine.can_release,
                         engine.allowed_modes, engine.risk_ceiling))
                    checked += 1
        self.assertEqual(checked, 259)

    def test_only_a_role_that_may_build_gets_the_edit_tools(self):
        for pack in self.packs:
            for role in pack["roles"]:
                engine = self.engine_authority.resolve_role_authority(pack["id"], role)
                record, _ = gen.authority_for(self.policy, pack, role)
                with self.subTest(pack=pack["id"], role=role):
                    self.assertEqual(gen.tools_for(record) == gen.TOOLS_BUILD, engine.can_build)

    def test_the_identities_with_no_definition_are_exactly_the_mandatory_flow_role(self):
        """The known gap, pinned by name so it is neither forgotten nor quietly widened.

        The engine registers 311 identities; the generator writes the 259 DECLARED roles. The
        52 it does not write are one `Automation & Flow Engineer` per pack. If this ever
        differs, either a pack role lost its definition or the gap was closed -- and then the
        generator's docstring, and every count that says 262, is what needs changing.
        """
        generated = {(pack["id"], role) for pack in self.packs for role in pack["roles"]}
        registered = set(self.engine_identity.all_agent_identities().values())
        missing = registered - generated
        self.assertEqual(generated - registered, set())
        self.assertEqual({role for _, role in missing}, {"Automation & Flow Engineer"})
        self.assertEqual(len(missing), len(self.packs))
        self.assertEqual(len(registered), 311)
        self.assertEqual(len(gen.build()), 259 + len(gen.TIERS))


if __name__ == "__main__":
    unittest.main()
