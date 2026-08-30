"""Tests for tools/check_audit_actor.py -- the T-052 audit-actor attribution gate.

Each test builds a throwaway tree with the three search roots the gate walks, so nothing
here depends on the state of the real `repo.rs`. Every rule the gate enforces has a test
that goes RED when the rule is removed, and the GREEN cases exist so a gate that refused
everything would fail too.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_audit_actor as ca  # noqa: E402


def _tree(files: dict[str, str]) -> pathlib.Path:
    """Materialise `{relative path: rust source}` under a temp root, always creating all
    three search roots so a missing-root problem never masks the rule under test."""
    root = pathlib.Path(tempfile.mkdtemp())
    for sub in ca.SEARCH_ROOTS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


CORE = "apps/desktop/src-tauri/core/src"
CMDS = "apps/desktop/src-tauri/src"

DERIVED = f'''
pub fn create(conn: &Connection, actor: audit::Actor<'_>) {{
    super::audit::record(tx, "project.created", actor, "project", &id)?;
}}
'''


class GreenCases(unittest.TestCase):
    def test_a_derived_actor_variable_is_accepted(self):
        root = _tree({f"{CORE}/repo.rs": DERIVED})
        problems, _, calls = ca.check(root)
        self.assertEqual(problems, [])
        self.assertEqual(calls, 1)

    def test_an_actor_constructor_is_accepted(self):
        src = ('fn f() { audit::record(tx, "x.y", audit::Actor::local_operator(), "t", id)?; }\n')
        problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": src}))
        self.assertEqual(problems, [])

    def test_the_message_role_author_shape_is_accepted(self):
        # The shape the six already-correct call sites used at repo.rs:1196/1266.
        src = ('fn f() { audit::record(tx, "message.posted", '
               'Actor::from_message(&input.role, &input.author), "conversation", &id)?; }\n')
        problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": src}))
        self.assertEqual(problems, [])

    def test_a_genuinely_system_originated_literal_actor_is_accepted(self):
        # repo.rs:1944/2049 passed ("system", "system") and were right to.
        for who in sorted(ca.SYSTEM_LITERALS):
            with self.subTest(who=who):
                src = f'fn f() {{ audit::record(tx, "x.y", "system", "{who}", "t", id)?; }}\n'
                problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": src}))
                self.assertEqual(problems, [], f"{who} must be accepted as a system actor")

    def test_a_paren_inside_a_string_does_not_truncate_the_call(self):
        src = ('fn f() { audit::record(tx, "x)y", audit::Actor::scheduler(), "t", id)?; }\n')
        problems, _, calls = ca.check(_tree({f"{CORE}/repo.rs": src}))
        self.assertEqual(problems, [])
        self.assertEqual(calls, 1)


class RedCases(unittest.TestCase):
    def test_a_hardcoded_user_gev_actor_is_refused_and_named_with_its_line(self):
        src = "// line one\n" + 'fn f() { audit::record(tx, "x.y", "user", "gev", "t", id)?; }\n'
        problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": src}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(f"{CORE}/repo.rs:2:", problems[0])
        self.assertIn('"user"', problems[0])
        self.assertIn("gev", problems[0])

    def test_a_hardcoded_user_kind_is_refused_even_with_a_derived_id(self):
        # The HALF-fixed shape at repo.rs:654/744 -- real actor id, hardcoded kind.
        src = 'fn f() { audit::record(tx, "approval.requested", "user", requested_by, "a", &id)?; }\n'
        problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": src}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('hardcodes the actor kind "user"', problems[0])

    def test_a_hand_built_actor_struct_with_a_hardcoded_user_kind_is_refused(self):
        src = ('fn f() { audit::record(tx, "x.y", '
               'Actor { kind: "user", id: whoever }, "t", id)?; }\n')
        problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": src}))
        self.assertTrue(any("half-fixed" in p for p in problems), problems)

    def test_an_actor_literal_naming_a_person_is_refused_anywhere_in_the_file(self):
        src = 'const WHO: Actor = Actor { kind: "user", id: "gev" };\n' + DERIVED
        problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": src}))
        self.assertTrue(any("names a person" in p for p in problems), problems)

    def test_a_literal_actor_id_that_is_not_a_system_component_is_refused(self):
        src = 'fn f() { audit::record(tx, "x.y", "system", "gev", "t", id)?; }\n'
        problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": src}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("hardcodes the actor id", problems[0])

    def test_the_command_layer_is_searched_too_not_only_the_repo(self):
        src = 'fn f() { repo::audit::record(&c, "x.y", "user", "gev", "t", id)?; }\n'
        problems, _, _ = ca.check(_tree({f"{CORE}/repo.rs": DERIVED, f"{CMDS}/commands.rs": src}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(f"{CMDS}/commands.rs", problems[0])


class GateCannotPassVacuously(unittest.TestCase):
    def test_a_tree_with_no_audit_record_call_at_all_is_RED(self):
        # Without this, deleting every call site -- or the gate losing its search roots --
        # would report GREEN, which is the failure mode CLAUDE.md calls a green test that
        # is not a passing check.
        problems, _, calls = ca.check(_tree({f"{CORE}/repo.rs": "fn f() {}\n"}))
        self.assertEqual(calls, 0)
        self.assertTrue(any("vacuously" in p for p in problems), problems)

    def test_a_missing_search_root_is_RED(self):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / CORE).mkdir(parents=True)
        (root / CORE / "repo.rs").write_text(DERIVED, encoding="utf-8")
        problems, _, _ = ca.check(root)
        self.assertTrue(any("does not exist" in p for p in problems), problems)


class RealTree(unittest.TestCase):
    def test_the_gate_is_green_on_this_repository_and_reads_real_call_sites(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        problems, files, calls = ca.check(root)
        self.assertEqual(problems, [], problems)
        # A number, not a shrug: if the call sites vanish the gate must not stay green.
        self.assertGreaterEqual(calls, 40, "the gate found almost no audit::record calls")
        self.assertGreaterEqual(files, 10)


if __name__ == "__main__":
    unittest.main()
