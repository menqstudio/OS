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

    def write_rust(self, text, name="core/src/governed_output_stream.rs"):
        path = self.tmp / "apps/desktop/src-tauri" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def declare(self, tauri_commands=None, engine_symbols=None, tools_gates=None,
                rust_symbols=None):
        (self.tmp / "config/reachability-declarations.json").write_text(
            json.dumps(
                {
                    "tauri_commands": tauri_commands or {},
                    "engine_symbols": engine_symbols or {},
                    "rust_symbols": rust_symbols or {},
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


class RustSymbolTests(GateTestCase):
    """The same defect in the language the security core is written in.

    `rustc` warns about an uncalled PRIVATE item and says nothing about a `pub fn` in a library
    crate. That is the exact shape `governed_output_stream::{mint,resolve,sweep}` had: public,
    documented, nine passing unit tests, zero production callers, and a clean build. Every test
    below breaks one thing and requires RED, and the two that matter most are the near-misses --
    a "caller" that is only a `#[cfg(test)] mod`, and an unrelated function of the SAME NAME in
    another module (this repository really does have `ai.rs`'s own `resolve()` alongside
    `governed_output_stream::resolve`).
    """

    DEFINED = "apps/desktop/src-tauri/core/src/governed_output_stream.rs"
    LADDER = (
        "pub fn create_schema(conn: &Connection) -> Result<()> { Ok(()) }\n"
        'pub fn resolve(conn: &Connection, id: &str) -> Result<String> { Ok(String::new()) }\n'
    )

    def declare_rust(self, **overrides):
        entry = {
            "kind": "function",
            "module": "governed_output_stream",
            "defined_in": self.DEFINED,
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
            rust_symbols={"resolve": entry},
        )

    def test_zero_callers_fails(self):
        self.write_rust(self.LADDER)
        self.declare_rust()
        self.assertRed("ZERO callers")

    def test_a_caller_only_in_its_own_module_is_not_a_caller(self):
        """Including a FULLY QUALIFIED self-call, which is the only shape by which a definer can
        match the caller pattern at all -- and therefore the reason `defined_in` is excluded
        outright instead of being left to the pattern. A module calling itself is one of the
        ways dead code reads as live."""
        self.write_rust(
            self.LADDER
            + "pub fn helper(c: &Connection) -> Result<String> {\n"
            + '    crate::governed_output_stream::resolve(c, "x")\n'
            + "}\n"
        )
        self.declare_rust()
        self.assertRed("ZERO callers")

    def test_a_caller_only_in_a_cfg_test_module_is_not_a_caller(self):
        """The governed_output_stream shape exactly: the only callers are its own unit tests."""
        self.write_rust(self.LADDER, "core/src/other.rs")
        self.write_rust(
            "use brops_core::other::resolve;\n"
            "#[cfg(test)]\n"
            "mod tests {\n"
            "    use super::*;\n"
            "    #[test]\n"
            '    fn it_resolves() { assert!(resolve(&c, "x").is_ok()); }\n'
            "}\n",
            "broker/src/main.rs",
        )
        self.declare_rust(defined_in="apps/desktop/src-tauri/core/src/other.rs", module="other")
        found = self.problems()
        self.assertTrue(any("ZERO callers" in p for p in found), found)
        self.assertTrue(any("referenced ONLY from tests" in p for p in found), found)

    def test_a_brace_in_a_string_does_not_end_the_test_module_early(self):
        """A SQL/format literal containing a brace must not close `mod tests` early and expose
        the rest of the file as production code -- that turns a test-only caller green."""
        self.write_rust(self.LADDER, "core/src/other.rs")
        self.write_rust(
            "use brops_core::other::resolve;\n"
            "#[cfg(test)]\n"
            "mod tests {\n"
            '    fn sql() -> &\'static str { "SELECT json_object(\'{a}\') }" }\n'
            "    #[test]\n"
            '    fn it_resolves() { resolve(&c, "x"); }\n'
            "}\n",
            "broker/src/main.rs",
        )
        self.declare_rust(defined_in="apps/desktop/src-tauri/core/src/other.rs", module="other")
        self.assertRed("ZERO callers")

    def test_an_unrelated_function_of_the_same_name_is_not_a_caller(self):
        """`ai.rs` defines its own `resolve()`. A bare-name scan would call that a caller of
        `governed_output_stream::resolve` -- a false green produced by the gate that exists to
        prevent false greens."""
        self.write_rust(self.LADDER)
        self.write_rust(
            "fn resolve() -> Result<Provider, String> { Ok(Provider::None) }\n"
            "pub fn status() { let _ = resolve(); }\n",
            "src/ai.rs",
        )
        self.declare_rust()
        self.assertRed("ZERO callers")

    def test_a_mention_in_a_comment_is_not_a_caller(self):
        self.write_rust(self.LADDER)
        self.write_rust(
            "// the pull loop will call governed_output_stream::resolve(conn, id) one day\n"
            "/* governed_output_stream::resolve(conn, id) */\n",
            "broker/src/main.rs",
        )
        self.declare_rust()
        self.assertRed("ZERO callers")

    def test_a_qualified_call_in_another_module_passes(self):
        self.write_rust(self.LADDER)
        self.write_rust(
            "pub fn serve(c: &Connection, id: &str) {\n"
            "    let _ = brops_core::governed_output_stream::resolve(c, id);\n"
            "}\n",
            "broker/src/main.rs",
        )
        self.declare_rust()
        self.assertGreen()

    def test_a_bare_call_in_a_file_that_imports_it_passes(self):
        self.write_rust(self.LADDER)
        self.write_rust(
            "use brops_core::governed_output_stream::{resolve, sweep};\n"
            "pub fn serve(c: &Connection, id: &str) { let _ = resolve(c, id); }\n",
            "broker/src/main.rs",
        )
        self.declare_rust()
        self.assertGreen()

    def test_a_declaration_with_no_module_is_refused(self):
        """Without the module there is no way to tell one `resolve` from another, so the gate
        refuses the declaration rather than fall back to scanning for a bare name."""
        self.write_rust(self.LADDER)
        self.declare_rust(module=None)
        self.assertRed("`module` is required")

    def test_a_module_that_does_not_match_the_file_is_refused(self):
        self.write_rust(self.LADDER)
        self.declare_rust(module="governed_turn")
        self.assertRed("does not match defined_in")

    def test_a_declaration_that_drifted_off_the_code_fails(self):
        self.write_rust("pub fn create_schema() {}\n")
        self.declare_rust()
        self.assertRed("declares no `fn resolve`")

    def test_a_missing_defining_file_fails(self):
        self.declare_rust(
            defined_in="apps/desktop/src-tauri/core/src/nowhere.rs", module="nowhere"
        )
        self.assertRed("does not exist")

    def test_a_doc_comment_naming_the_fn_is_not_a_definition(self):
        """`fn resolve` has to be DECLARED, not merely mentioned -- otherwise a module doc that
        names the symbol keeps a rotted declaration alive."""
        self.write_rust("//! resolve() lives here.\npub fn create_schema() {}\n")
        self.declare_rust()
        self.assertRed("declares no `fn resolve`")

    def test_declared_unreachable_needs_a_written_reason(self):
        self.write_rust(self.LADDER)
        self.declare_rust(
            expectation="declared_unreachable", reason="dead code", residual_item="R-1"
        )
        self.assertRed("characters saying why")

    def test_declared_unreachable_needs_a_residual_item_or_tracking_file(self):
        self.write_rust(self.LADDER)
        self.declare_rust(
            expectation="declared_unreachable",
            reason=("It has no caller and the reason is written out at length here, but "
                    "nothing says where the open item is tracked."),
        )
        self.assertRed("must name the residual item")

    def test_declared_unreachable_with_a_tracking_file_passes(self):
        self.write_rust(self.LADDER)
        (self.tmp / "docs/OPEN.md").write_text("open\n", encoding="utf-8")
        self.declare_rust(
            expectation="declared_unreachable",
            tracked_by="docs/OPEN.md",
            reason=("The rev-30 output-pull ladder, implemented ahead of the transport that "
                    "would use it; nothing pulls yet, so it is unreached by design."),
        )
        self.assertGreen()

    def test_declared_unreachable_that_gained_a_caller_fails(self):
        """The exception must not outlive the condition it described."""
        self.write_rust(self.LADDER)
        self.write_rust(
            "pub fn serve(c: &Connection, id: &str) {\n"
            "    let _ = brops_core::governed_output_stream::resolve(c, id);\n"
            "}\n",
            "broker/src/main.rs",
        )
        (self.tmp / "docs/OPEN.md").write_text("open\n", encoding="utf-8")
        self.declare_rust(
            expectation="declared_unreachable",
            tracked_by="docs/OPEN.md",
            reason=("The rev-30 output-pull ladder, implemented ahead of the transport that "
                    "would use it; nothing pulls yet, so it is unreached by design."),
        )
        self.assertRed("declared unreachable but now HAS a caller")

    def test_an_integration_test_file_is_never_a_production_caller(self):
        self.write_rust(self.LADDER)
        self.write_rust(
            "use brops_core::governed_output_stream::resolve;\n"
            "#[test]\n"
            'fn it_resolves() { let _ = resolve(&c, "x"); }\n',
            "core/tests/streams.rs",
        )
        self.declare_rust()
        self.assertRed("ZERO callers")


class ShippedRustLadderTests(unittest.TestCase):
    """The REAL repository, not a fixture: what became of the ladder this section was built
    for.

    Until 2026-08-10 this asserted that `governed_output_stream::{mint,resolve,sweep}` were
    DECLARED and still uncalled. They are neither now: rev-30 §4.10(f) was actually built, as
    SUPERVISOR state in the engine, and the Rust ladder — whose table diverged from the design
    it cited — was deleted rather than left as a second answer. Its own declaration had said
    "wiring a caller is a rewrite, not a hookup", and that turned out to be the finding.

    The assertion is inverted rather than removed, because the deletion is the thing worth
    protecting: re-adding a `pub fn` under that module without a caller must not read as
    normal, and re-adding the entry without the file must turn the gate RED on its own
    (`defined_in` has to exist). The gate's MECHANICS are still exercised in full by the
    fixture tests above, which build their own synthetic ladder.
    """

    def test_the_output_stream_ladder_is_gone_and_no_declaration_outlived_it(self):
        problems, summary = gate.check(ROOT)
        self.assertEqual(problems, [])
        self.assertFalse(
            (ROOT / "apps/desktop/src-tauri/core/src/governed_output_stream.rs").exists(),
            "the divergent §4.10(f) ladder is back; it must not be, see the rust_symbols "
            "note in config/reachability-declarations.json")
        for name in ("mint", "resolve", "sweep"):
            self.assertIsNone(
                summary["rust"].get(name),
                f"{name} is declared under rust_symbols but the file it described is gone")

    def test_the_section_holds_only_symbols_whose_file_exists_and_never_the_deleted_ladder(self):
        """This asserted an EMPTY section until 2026-08-10, and that assertion had a shelf life.

        The section was kept after the divergent ladder was deleted so that the next symbol
        would have somewhere to go — and later the same day one did: §4.10(f)'s desktop hop
        landed built, tested and genuinely uncallable, because §4.6's frame (the only thing that
        carries `output_stream_id` across the sidecar boundary) does not exist yet. Declaring
        those symbols is exactly what the section is for; asserting the section stays empty
        turned the arrival of a correct declaration into a red gate.

        So the assertion is narrowed to the two things that were actually worth protecting:
        the deleted ladder's names must never come back, and no entry may name a file that is
        not there. The second is the mechanism that made the deletion safe — the gate refuses a
        `defined_in` that does not exist, so a declaration cannot outlive its code.
        """
        declared = json.loads(
            (ROOT / "config/reachability-declarations.json").read_text(encoding="utf-8"))
        self.assertIn("rust_symbols", declared)
        entries = {k: v for k, v in declared["rust_symbols"].items() if not k.startswith("$")}
        for name in ("mint", "resolve", "sweep"):
            self.assertNotIn(
                name, entries,
                f"{name} is declared again; the ladder it belonged to was deleted, and a "
                "declaration without its code is what this section must never carry")
        for name, entry in entries.items():
            where = entry.get("defined_in")
            self.assertIsNotNone(where, f"{name} declares no defined_in")
            self.assertTrue(
                (ROOT / where).exists(),
                f"{name} declares {where}, which does not exist — the declaration outlived "
                "its code, which is the failure this section was emptied over")


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
