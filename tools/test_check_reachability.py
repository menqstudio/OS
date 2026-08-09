"""The reachability gate must FAIL when it should.

A gate nobody can make fail is the same defect it exists to catch: something that reads as
protection while doing nothing. The audit history in this repository has two of those already —
a production guard whose operands were provably equal, and five security functions with zero
callers — so this gate gets the treatment it imposes. Every test below breaks the thing the gate
checks and requires RED, and the ones that matter most are the near-misses: a command mentioned
only in a comment, a command referenced only by its own tests, a command named by a constant
precisely so that it is never called, and a policy flag whose only "reader" is a docstring
example. Each of those is a way something dead can look alive.

Run: `cd tools && python -m unittest test_check_reachability`
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_reachability as gate  # noqa: E402


LIB_RS_TEMPLATE = """
pub fn run() {{
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
{entries}
        ])
        .run(tauri::generate_context!())
        .expect("boom");
}}
"""


class GateTestCase(unittest.TestCase):
    """Builds a minimal but REAL repository shape in a temp dir, then perturbs one thing."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="brops-reachgate-")).resolve()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

        # The ungated allowlist belongs to check_capabilities and describes the REAL repo;
        # in a synthetic root it would be noise, so hold it empty and test the grant rules
        # on their own terms.
        self.original_ungated = gate.intentionally_ungated
        gate.intentionally_ungated = lambda: set()
        self.addCleanup(self._restore)

        for sub in (
            "apps/desktop/src-tauri/src",
            "apps/desktop/src-tauri/capabilities",
            "apps/desktop/src/services",
            "apps/desktop/src/features",
            "config",
            "docs",
            "engine/runtime",
            "engine/tests",
        ):
            (self.tmp / sub).mkdir(parents=True, exist_ok=True)

        self.write_commands(["list_things", "delete_thing"])
        self.write_grants({"list_things": "allow", "delete_thing": "deny"})
        self.write_frontend("export const api = { list: () => invoke('list_things') };")
        self.declare(
            tauri_commands={
                "delete_thing": {
                    "reason": "capability-denied",
                    "note": (
                        "Denied to the window in capabilities/default.json; having no caller "
                        "is the enforced state rather than an oversight."
                    ),
                }
            }
        )

    def _restore(self):
        gate.intentionally_ungated = self.original_ungated

    # -- fixture writers -----------------------------------------------------------------

    def write_commands(self, names, registered=None):
        registered = names if registered is None else registered
        body = "\n".join(
            "#[tauri::command]\npub fn %s() -> Result<(), String> { Ok(()) }" % n for n in names
        )
        (self.tmp / "apps/desktop/src-tauri/src/commands.rs").write_text(body, encoding="utf-8")
        entries = "\n".join(f"            commands::{n}," for n in registered)
        (self.tmp / "apps/desktop/src-tauri/src/lib.rs").write_text(
            LIB_RS_TEMPLATE.format(entries=entries), encoding="utf-8"
        )

    def write_grants(self, grants):
        permissions = ["core:default"] + [
            f"{kind}-{name.replace('_', '-')}" for name, kind in grants.items()
        ]
        (self.tmp / "apps/desktop/src-tauri/capabilities/default.json").write_text(
            json.dumps({"identifier": "default", "permissions": permissions}), encoding="utf-8"
        )

    def write_frontend(self, text, name="services/desktop.ts"):
        path = self.tmp / "apps/desktop/src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_engine(self, text, name="runtime/thing.py"):
        path = self.tmp / "engine" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def declare(self, tauri_commands=None, engine_symbols=None, tools_gates=None):
        (self.tmp / "config/reachability-declarations.json").write_text(
            json.dumps(
                {
                    "tauri_commands": tauri_commands or {},
                    "engine_symbols": engine_symbols or {},
                    "tools_gates": tools_gates or {},
                }
            ),
            encoding="utf-8",
        )

    def write_gate(self, name="check_thing.py"):
        path = self.tmp / "tools" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("print('gate')\n", encoding="utf-8")
        return f"tools/{name}"

    def write_workflow(self, text, name="ci.yml"):
        path = self.tmp / ".github/workflows" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def problems(self):
        found, _ = gate.check(self.tmp)
        return found

    def assertRed(self, needle):
        found = self.problems()
        self.assertTrue(any(needle in p for p in found), f"expected {needle!r} in {found}")

    def assertGreen(self):
        self.assertEqual(self.problems(), [])


class BaselineTests(GateTestCase):
    def test_the_baseline_fixture_is_green(self):
        """If the happy path were not green, every red below would be meaningless."""
        self.assertGreen()


class TauriCommandTests(GateTestCase):
    def test_an_unreachable_undeclared_command_fails(self):
        self.write_commands(["list_things", "delete_thing", "orphan_command"])
        self.write_grants(
            {"list_things": "allow", "delete_thing": "deny", "orphan_command": "allow"}
        )
        self.assertRed("`orphan_command` is registered")

    def test_a_declared_unreachable_command_passes(self):
        self.write_commands(["list_things", "delete_thing", "orphan_command"])
        self.write_grants(
            {"list_things": "allow", "delete_thing": "deny", "orphan_command": "allow"}
        )
        self.declare(
            tauri_commands={
                "delete_thing": {
                    "reason": "capability-denied",
                    "note": "Denied to the window; no caller is the enforced state, not a gap.",
                },
                "orphan_command": {
                    "reason": "superseded",
                    "note": (
                        "Superseded by list_things, which is narrower and validates its input "
                        "server-side; kept registered as residual surface."
                    ),
                },
            }
        )
        self.assertGreen()

    # -- the near-misses: ways dead code looks alive --------------------------------------

    def test_a_mention_in_a_line_comment_is_not_a_call(self):
        self.write_frontend(
            "// TODO: wire up 'delete_thing' one day\n"
            "export const api = { list: () => invoke('list_things') };"
        )
        self.declare()
        self.assertRed("`delete_thing` is registered")

    def test_a_mention_in_a_block_comment_is_not_a_call(self):
        self.write_frontend(
            "/* the delete path calls ('delete_thing') eventually */\n"
            "export const api = { list: () => invoke('list_things') };"
        )
        self.declare()
        self.assertRed("`delete_thing` is registered")

    def test_a_constant_naming_a_command_is_not_a_call(self):
        """`const DENIED_DECIDE_COMMAND = 'decide_approval'` exists in order NEVER to be
        invoked. Counting it as a caller would hide the exact command the wall denies."""
        self.write_frontend(
            "export const DENIED = 'delete_thing';\n"
            "export const api = { list: () => invoke('list_things') };"
        )
        self.declare()
        self.assertRed("`delete_thing` is registered")

    def test_a_command_called_only_from_tests_is_not_reached(self):
        """This is exactly how a dead symbol reads as green."""
        self.write_frontend(
            "it('deletes', () => invoke('delete_thing'));", "features/Thing.test.tsx"
        )
        self.declare()
        found = self.problems()
        self.assertTrue(any("`delete_thing` is registered" in p for p in found), found)
        self.assertTrue(any("ONLY from tests" in p for p in found), found)

    def test_a_real_production_call_is_reached(self):
        self.write_frontend(
            "export const api = {\n"
            "  list: () => invoke('list_things'),\n"
            "  del: (id) => invoke('delete_thing', { id }),\n"
            "};"
        )
        self.declare()
        self.assertGreen()

    # -- the declarations file must stay honest --------------------------------------------

    def test_a_placeholder_note_is_refused(self):
        self.declare(
            tauri_commands={"delete_thing": {"reason": "superseded", "note": "unreachable"}}
        )
        self.assertRed("is not a reason")

    def test_a_short_note_is_refused(self):
        self.declare(
            tauri_commands={"delete_thing": {"reason": "superseded", "note": "not used yet"}}
        )
        self.assertRed("characters of real prose")

    def test_an_invented_reason_category_is_refused(self):
        self.declare(
            tauri_commands={
                "delete_thing": {
                    "reason": "because-i-said-so",
                    "note": "A long enough note that nonetheless claims a category nobody defined.",
                }
            }
        )
        self.assertRed("is not one of")

    def test_claiming_capability_denied_while_the_grant_is_allow_fails(self):
        """The declared reason must be the REAL one — otherwise the file is decoration."""
        self.write_grants({"list_things": "allow", "delete_thing": "allow"})
        self.assertRed("claims reason 'capability-denied'")

    def test_not_yet_wired_must_name_an_existing_tracking_file(self):
        self.declare(
            tauri_commands={
                "delete_thing": {
                    "reason": "not-yet-wired",
                    "tracked_by": "docs/NOT_A_REAL_FILE.md",
                    "note": "An honest open gap, but pointed at a document that does not exist.",
                }
            }
        )
        self.assertRed("must name a file that exists")

    def test_not_yet_wired_with_a_real_tracking_file_passes(self):
        (self.tmp / "docs/REACHABILITY_GATE.md").write_text("tracked", encoding="utf-8")
        self.declare(
            tauri_commands={
                "delete_thing": {
                    "reason": "not-yet-wired",
                    "tracked_by": "docs/REACHABILITY_GATE.md §Declared exceptions",
                    "note": (
                        "An OPEN gap declared rather than dressed up: no surface invokes it and "
                        "the grant has not been withdrawn."
                    ),
                }
            }
        )
        self.assertGreen()

    def test_a_declaration_that_is_now_called_is_stale_and_fails(self):
        """An exception must not outlive the condition it described."""
        self.write_frontend(
            "export const api = {\n"
            "  list: () => invoke('list_things'),\n"
            "  del: (id) => invoke('delete_thing', { id }),\n"
            "};"
        )
        self.assertRed("declared unreachable but IS now invoked")

    def test_a_declaration_for_an_unregistered_command_is_stale_and_fails(self):
        self.declare(
            tauri_commands={
                "gone_command": {
                    "reason": "superseded",
                    "note": "A command that no longer exists anywhere in generate_handler!.",
                }
            }
        )
        self.assertRed("no longer registered")


class RegistrationAndCapabilityTests(GateTestCase):
    def test_a_command_defined_but_never_registered_fails(self):
        self.write_commands(
            ["list_things", "delete_thing", "never_registered"],
            registered=["list_things", "delete_thing"],
        )
        self.assertRed("but is NOT in generate_handler!")

    def test_a_grant_for_a_command_that_does_not_exist_fails(self):
        self.write_grants(
            {"list_things": "allow", "delete_thing": "deny", "ghost_command": "allow"}
        )
        self.assertRed("no such command is registered")

    def test_a_registered_command_with_no_grant_fails(self):
        self.write_grants({"list_things": "allow"})
        self.assertRed("has no allow-*/deny-* entry")


class EngineSymbolTests(GateTestCase):
    def declare_symbol(self, **overrides):
        entry = {
            "kind": "function",
            "defined_in": "engine/runtime/thing.py",
            "expectation": "must_have_caller",
        }
        entry.update(overrides)
        self.declare(
            tauri_commands={
                "delete_thing": {
                    "reason": "capability-denied",
                    "note": "Denied to the window; no caller is the enforced state, not a gap.",
                }
            },
            engine_symbols={"assert_something": entry},
        )

    def test_zero_callers_fails(self):
        self.write_engine("def assert_something(root):\n    raise RuntimeError('nope')\n")
        self.declare_symbol()
        self.assertRed("ZERO callers")

    def test_a_caller_only_in_its_own_module_is_not_a_caller(self):
        self.write_engine(
            "def assert_something(root):\n    raise RuntimeError('nope')\n\n"
            "def helper():\n    return assert_something('.')\n"
        )
        self.declare_symbol()
        self.assertRed("ZERO callers")

    def test_a_caller_only_in_its_own_tests_is_not_a_caller(self):
        """`assert_no_bytecode_shadow` looked green from exactly this shape."""
        self.write_engine("def assert_something(root):\n    raise RuntimeError('nope')\n")
        self.write_engine(
            "from thing import assert_something\n\n"
            "def test_it():\n    assert_something('.')\n",
            "tests/test_thing.py",
        )
        self.declare_symbol()
        found = self.problems()
        self.assertTrue(any("ZERO callers" in p for p in found), found)
        self.assertTrue(any("referenced ONLY by tests" in p for p in found), found)

    def test_a_prose_mention_in_another_module_is_not_a_caller(self):
        self.write_engine("def assert_something(root):\n    raise RuntimeError('nope')\n")
        self.write_engine(
            '"""This module relies on assert_something for its guarantees."""\n'
            "# see assert_something(root) in thing.py\n",
            "runtime/other.py",
        )
        self.declare_symbol()
        self.assertRed("ZERO callers")

    def test_a_real_caller_in_another_module_passes(self):
        self.write_engine("def assert_something(root):\n    raise RuntimeError('nope')\n")
        self.write_engine(
            "from thing import assert_something\n\n"
            "def wall_startup(root):\n    assert_something(root)\n",
            "runtime/other.py",
        )
        self.declare_symbol()
        self.assertGreen()

    def test_declared_unreachable_needs_a_written_reason(self):
        self.write_engine("def assert_something(root):\n    raise RuntimeError('nope')\n")
        self.declare_symbol(expectation="declared_unreachable", reason="dead code",
                            residual_item="O-9")
        self.assertRed("characters saying why")

    def test_declared_unreachable_needs_a_residual_item_or_tracking_file(self):
        self.write_engine("def assert_something(root):\n    raise RuntimeError('nope')\n")
        self.declare_symbol(
            expectation="declared_unreachable",
            reason=(
                "It has no caller and the reason is written out here at length, but nothing "
                "says where the open item is tracked."
            ),
        )
        self.assertRed("must name the residual item")

    def test_declared_unreachable_with_a_residual_item_passes(self):
        self.write_engine("def assert_something(root):\n    raise RuntimeError('nope')\n")
        self.declare_symbol(
            expectation="declared_unreachable",
            residual_item="O-1",
            reason=(
                "Residual item O-1: the function exists and raises correctly, and nothing on "
                "the wall's startup path has ever called it."
            ),
        )
        self.assertGreen()

    def test_declared_unreachable_that_gained_a_caller_fails(self):
        """The direction of improvement still has to be recorded, not silently absorbed."""
        self.write_engine("def assert_something(root):\n    raise RuntimeError('nope')\n")
        self.write_engine(
            "from thing import assert_something\n\n"
            "def wall_startup(root):\n    assert_something(root)\n",
            "runtime/other.py",
        )
        self.declare_symbol(
            expectation="declared_unreachable",
            residual_item="O-1",
            reason=(
                "Residual item O-1: the function exists and raises correctly, and nothing on "
                "the wall's startup path has ever called it."
            ),
        )
        self.assertRed("declared unreachable but now HAS a caller")

    def test_a_declaration_that_drifted_off_the_code_fails(self):
        self.write_engine("def something_else(root):\n    return None\n")
        self.declare_symbol()
        self.assertRed("has rotted away from the code")

    def test_a_missing_defining_module_fails(self):
        self.declare_symbol(defined_in="engine/runtime/nowhere.py")
        self.assertRed("does not exist")


class PolicyFlagTests(GateTestCase):
    def declare_flag(self, **overrides):
        entry = {
            "kind": "policy_flag",
            "defined_in": None,
            "expectation": "must_have_caller",
            "residual_item": "O-3",
        }
        entry.update(overrides)
        self.declare(
            tauri_commands={
                "delete_thing": {
                    "reason": "capability-denied",
                    "note": "Denied to the window; no caller is the enforced state, not a gap.",
                }
            },
            engine_symbols={"require_the_token": entry},
        )

    def test_a_docstring_example_is_not_a_read(self):
        """Caught for real while building this gate: the flag's own docstring writes
        `"require_conductor_session_token": true` as an example, and a bare-literal match
        counted that prose as a reader."""
        self.write_engine(
            'def check(root):\n'
            '    """Policy may set `"require_the_token": true` to make it mandatory."""\n'
            "    return False\n",
            "runtime/policy.py",
        )
        self.declare_flag()
        self.assertRed("ZERO callers")

    def test_a_real_read_of_the_literal_passes(self):
        self.write_engine(
            "def check(document):\n"
            '    return bool(document.get("require_the_token", False))\n',
            "runtime/policy.py",
        )
        self.declare_flag()
        self.assertGreen()

    def test_a_read_through_an_undeclared_constant_is_not_seen(self):
        """The honest failure mode: the gate says so rather than pretending it followed it."""
        self.write_engine(
            'POLICY_KEY = "require_the_token"\n\n'
            "def check(document):\n"
            "    return bool(document[POLICY_KEY])\n",
            "runtime/policy.py",
        )
        self.declare_flag()
        self.assertRed("ZERO callers")

    def test_a_read_through_a_declared_and_verified_constant_passes(self):
        self.write_engine(
            'POLICY_KEY = "require_the_token"\n\n'
            "def check(document):\n"
            "    return bool(document[POLICY_KEY])\n",
            "runtime/policy.py",
        )
        self.declare_flag(
            read_via={"constant": "POLICY_KEY", "bound_in": "engine/runtime/policy.py"}
        )
        self.assertGreen()

    def test_a_declared_indirection_that_is_not_real_fails(self):
        """A read_via nobody verified would let the gate follow a dead pointer and count
        references to something unrelated as reads of the flag."""
        self.write_engine(
            'POLICY_KEY = "some_other_flag"\n\n'
            "def check(document):\n"
            "    return bool(document[POLICY_KEY])\n",
            "runtime/policy.py",
        )
        self.declare_flag(
            read_via={"constant": "POLICY_KEY", "bound_in": "engine/runtime/policy.py"}
        )
        self.assertRed("does not bind POLICY_KEY")

    def test_read_via_on_a_function_symbol_is_refused(self):
        self.write_engine("def require_the_token():\n    return True\n", "runtime/policy.py")
        self.declare_flag(
            kind="function",
            defined_in="engine/runtime/policy.py",
            read_via={"constant": "POLICY_KEY", "bound_in": "engine/runtime/policy.py"},
        )
        self.assertRed("only meaningful for a policy_flag")


class HonestyTests(unittest.TestCase):
    """A gate that overstates its coverage is the same lie one level up."""

    def test_the_output_always_states_the_limits(self):
        for phrase in (
            "static text scan",
            "dynamic dispatch",
            "ONE level deep",
            "test-only callers",
        ):
            self.assertIn(phrase, gate.LIMITS)

    def test_the_docstring_states_what_it_cannot_detect(self):
        self.assertIn("CANNOT DETECT", gate.__doc__)
        self.assertIn("not a call graph", gate.__doc__)

    def test_the_ungated_allowlist_is_imported_not_copied(self):
        """Two lists of the same commands in two gates is itself a drift defect."""
        import check_capabilities

        self.assertEqual(gate.intentionally_ungated(), set(check_capabilities.INTENTIONALLY_UNGATED))


if __name__ == "__main__":
    unittest.main()


class ToolsGateReachabilityTests(GateTestCase):
    """Section 5: a gate no workflow runs is the uncalled-command defect one level up.

    This section was ADDED to this gate rather than given its own module. A second
    implementation would have duplicated the declarations file, the reason-quality rules
    and the declaration-rot rule that already live here -- which is the "do not build what
    already exists" rule broken while implementing it.
    """

    REASON = (
        "This is a per-session tool whose caller is a Claude Code hook, not a CI job; running "
        "it on a runner could only pass vacuously, and a check that cannot fail reads as "
        "coverage while providing none."
    )
    # setUp's fixture declares delete_thing; re-state it whenever a test rewrites the
    # declarations file, or the tools_gates assertions would be reading a Tauri failure.
    BASELINE = {
        "delete_thing": {
            "reason": "capability-denied",
            "note": ("Denied to the window in capabilities/default.json; having no caller "
                     "is the enforced state rather than an oversight."),
        }
    }

    def declare_gates(self, tools_gates):
        self.declare(tauri_commands=self.BASELINE, tools_gates=tools_gates)

    def test_a_gate_no_workflow_runs_is_red(self):
        self.write_gate()
        self.write_workflow("jobs:\n  x:\n    steps:\n      - run: echo hi\n")
        self.assertRed("is executed by NO workflow")

    def test_a_gate_a_workflow_runs_is_green(self):
        self.write_gate()
        self.write_workflow("jobs:\n  x:\n    steps:\n      - run: python tools/check_thing.py\n")
        self.assertGreen()

    def test_running_only_the_self_tests_does_not_count_as_reached(self):
        """A checker proven correct and never pointed at the repository is still nothing."""
        self.write_gate()
        self.write_workflow(
            "jobs:\n  x:\n    steps:\n      - run: python -m unittest test_check_thing\n")
        self.assertRed("is executed by NO workflow")

    def test_a_written_reason_declares_an_un_run_gate(self):
        gate_path = self.write_gate()
        self.write_workflow("jobs:\n  x:\n    steps:\n      - run: echo hi\n")
        self.declare_gates({gate_path: {"reason": self.REASON}})
        self.assertGreen()

    def test_a_placeholder_reason_is_refused(self):
        gate_path = self.write_gate()
        self.write_workflow("jobs:\n  x:\n    steps:\n      - run: echo hi\n")
        self.declare_gates({gate_path: {"reason": "not used"}})
        self.assertRed("saying why nothing runs it")

    def test_a_declaration_that_outlived_its_condition_is_refused(self):
        gate_path = self.write_gate()
        self.write_workflow("jobs:\n  x:\n    steps:\n      - run: python tools/check_thing.py\n")
        self.declare_gates({gate_path: {"reason": self.REASON}})
        self.assertRed("IS \nexecuted".replace("\n", ""))

    def test_a_declaration_for_a_gate_that_does_not_exist_is_refused(self):
        self.write_workflow("jobs:\n  x:\n    steps:\n      - run: echo hi\n")
        self.declare_gates({"tools/check_ghost.py": {"reason": self.REASON}})
        self.assertRed("which does not exist")

    def test_comment_keys_in_the_declaration_are_not_treated_as_gates(self):
        self.write_workflow("jobs:\n  x:\n    steps:\n      - run: echo hi\n")
        self.declare_gates({"$comment": ["notes about this section"]})
        self.assertGreen()

    def test_the_real_repository_runs_every_gate_it_ships(self):
        problems, summary = gate.check(ROOT)
        self.assertEqual([p for p in problems if "workflow" in p], [])
        self.assertGreater(summary["gates"], 10)
