"""Tests for tools/check_capabilities.py — the T-010 capability-inventory CI gate."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_capabilities as cc  # noqa: E402


def _lib_rs(cmds: list[str], ungated: list[str] | None = None) -> str:
    """A synthetic generate_handler!. `cmds` are gated `commands::` entries; `ungated`
    are module-scoped commands deliberately outside the wall. By default the fixture
    registers exactly the checker's INTENTIONALLY_UNGATED set (module-scoped) so the
    allowlist is satisfied — mirroring the real lib.rs, where those commands ARE
    registered but not declared in the manifest/policy."""
    if ungated is None:
        ungated = sorted(cc.INTENTIONALLY_UNGATED)
    lines = [f"            commands::{c}," for c in cmds]
    lines += [f"            governance::{c}," for c in ungated]
    inner = "\n".join(lines)
    return (
        "pub fn run() {\n"
        "    tauri::Builder::default()\n"
        "        .invoke_handler(tauri::generate_handler![\n"
        f"{inner}\n"
        "        ])\n"
        "}\n"
    )


def _build_rs(cmds: list[str]) -> str:
    inner = "\n".join(f'        "{c}",' for c in cmds)
    return (
        "fn main() {\n"
        "    let commands = [\n"
        f"{inner}\n"
        "    ];\n"
        "    tauri_build::try_build(Default::default()).unwrap();\n"
        "}\n"
    )


# Commands the fixture treats as execution/spend tier, so the T-052 X rules are exercised.
X_TIER = {"write_file", "set_integration_status"}


def _tier(cmd: str) -> str:
    if cmd in ("decide_approval", "reject_approval"):
        return "A"
    if cmd.startswith("delete_"):
        return "L2"
    if cmd in X_TIER:
        return "X"
    return "R"


def _policy(grants: dict[str, str], protection: dict[str, str] | None = None) -> str:
    protection = protection or {}
    commands = {}
    for c, g in grants.items():
        spec = {"tier": _tier(c), "grant": g}
        if _tier(c) == "L2":
            spec["protection"] = protection.get(c, "none")
        elif _tier(c) == "X" and g == "allow":
            # T-052: every tier-X allow must DECLARE a protection. The fixture default is
            # the honest one, 'none'; a test that wants otherwise passes it explicitly.
            spec["protection"] = protection.get(c, "none")
        commands[c] = spec
    return json.dumps({"window": "main", "commands": commands}, indent=2)


# The minimal authority layer a `native-confirm` claim is checked against. It carries the
# real symbol names, so a rename in repo.rs makes these tests wrong in the direction that
# is noticed rather than silently green.
REPO_RS_ENFORCING = """
pub mod approvals {
    pub const INTEGRATION_ENTITY_TYPE: &str = "integration";
    pub const INTEGRATION_STATUS_ACTION_TYPE: &str = "Set integration status";
    pub fn require_and_consume(tx: &Connection) {}
}
pub mod integrations {
    pub fn set_status() {
        super::approvals::require_and_consume(
            tx,
            id,
            super::approvals::INTEGRATION_ENTITY_TYPE,
            super::approvals::INTEGRATION_STATUS_ACTION_TYPE,
        );
    }
}
"""


def _default_cap(grants: dict[str, str]) -> str:
    perms = ["core:default"]
    for c, g in grants.items():
        perms.append(f"{g}-{c.replace('_', '-')}")
    return json.dumps({"identifier": "default", "windows": ["main"], "permissions": perms})


class _Fixture:
    """The synthetic tree every class here builds. A mixin, not a TestCase: a class that
    subclasses a TestCase to borrow its helpers re-runs every test it inherits."""

    def _tmp(self) -> pathlib.Path:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return pathlib.Path(d.name)

    def _write(
        self,
        root: pathlib.Path,
        cmds: list[str],
        grants: dict[str, str],
        protection: dict[str, str] | None = None,
        repo_rs: str | None = None,
    ) -> None:
        base = root / cc.DESKTOP
        (base / "src").mkdir(parents=True, exist_ok=True)
        (base / "capabilities").mkdir(parents=True, exist_ok=True)
        (base / "src" / "lib.rs").write_text(_lib_rs(cmds), encoding="utf-8")
        (base / "build.rs").write_text(_build_rs(cmds), encoding="utf-8")
        (base / "command-policy.json").write_text(_policy(grants, protection), encoding="utf-8")
        (base / "capabilities" / "default.json").write_text(_default_cap(grants), encoding="utf-8")
        (base / "core" / "src").mkdir(parents=True, exist_ok=True)
        (base / "core" / "src" / "repo.rs").write_text(
            repo_rs if repo_rs is not None else REPO_RS_ENFORCING, encoding="utf-8"
        )

    def _consistent(self):
        # delete_memory is an L2 hard-delete: denied by default (no protection mode).
        cmds = ["list_projects", "decide_approval", "reject_approval", "write_file", "delete_memory"]
        grants = {
            "list_projects": "allow",
            "decide_approval": "deny",
            "reject_approval": "allow",
            "write_file": "allow",
            "delete_memory": "deny",
        }
        return cmds, grants

class CheckCapabilitiesTests(_Fixture, unittest.TestCase):
    def test_consistent_is_green(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, grants)
        self.assertEqual(cc.check(root), [])

    def test_command_missing_from_manifest_fails(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        # lib.rs has an extra command the manifest/policy lack.
        base = root / cc.DESKTOP
        self._write(root, cmds, grants)
        (base / "src" / "lib.rs").write_text(_lib_rs(cmds + ["orphan_cmd"]), encoding="utf-8")
        problems = cc.check(root)
        self.assertTrue(any("registered != manifest" in p for p in problems), problems)

    def test_decide_approval_granted_fails(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        grants = dict(grants)
        grants["decide_approval"] = "allow"  # must be denied
        self._write(root, cmds, grants)
        problems = cc.check(root)
        self.assertTrue(any("decide_approval must be DENIED" in p for p in problems), problems)

    def test_policy_grant_mismatch_fails(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        base = root / cc.DESKTOP
        self._write(root, cmds, grants)
        # default.json flips list_projects to deny while policy still says allow.
        flipped = dict(grants)
        flipped["list_projects"] = "deny"
        (base / "capabilities" / "default.json").write_text(_default_cap(flipped), encoding="utf-8")
        problems = cc.check(root)
        self.assertTrue(any("list_projects" in p for p in problems), problems)

    def test_reject_approval_denied_fails(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        grants = dict(grants)
        grants["reject_approval"] = "deny"  # fail-safe path must be granted
        self._write(root, cmds, grants)
        problems = cc.check(root)
        self.assertTrue(any("reject_approval" in p for p in problems), problems)

    def test_l2_allow_without_protection_fails(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        grants = dict(grants)
        grants["delete_memory"] = "allow"  # hard-delete granted with protection "none"
        self._write(root, cmds, grants)
        problems = cc.check(root)
        self.assertTrue(any("delete_memory" in p and "L2" in p for p in problems), problems)

    def test_l2_allow_with_declared_protection_is_green(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        grants = dict(grants)
        grants["delete_memory"] = "allow"
        # A real protection mode makes the grant admissible.
        self._write(root, cmds, grants, protection={"delete_memory": "soft-delete"})
        self.assertEqual(cc.check(root), [])

    def test_new_module_scoped_command_not_allowlisted_fails(self):
        # The blind-spot regression guard: a command registered under a module prefix
        # (not commands::/files::) that is neither declared under the wall nor named in
        # INTENTIONALLY_UNGATED must FAIL — it would otherwise be silently ungated.
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, grants)
        base = root / cc.DESKTOP
        lib = _lib_rs(cmds).replace(
            "        ])", "            secret_mod::sneaky_cmd,\n        ])"
        )
        (base / "src" / "lib.rs").write_text(lib, encoding="utf-8")
        problems = cc.check(root)
        self.assertTrue(any("sneaky_cmd" in p for p in problems), problems)

    def test_stale_allowlist_entry_is_caught(self):
        # If an allowlisted command is NOT registered anywhere in lib.rs, the allowlist
        # has rotted and must be flagged.
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, grants)
        base = root / cc.DESKTOP
        # Register only SOME of the allowlist, dropping the rest -> stale entries remain.
        partial = sorted(cc.INTENTIONALLY_UNGATED)[:-1]
        (base / "src" / "lib.rs").write_text(_lib_rs(cmds, ungated=partial), encoding="utf-8")
        problems = cc.check(root)
        self.assertTrue(any("stale allowlist" in p for p in problems), problems)


class EveryInventoryArm(_Fixture, unittest.TestCase):
    """One fixture per refusal, each tripping ONLY the arm it names and asserting on that
    arm's own message. Six of these arms could be deleted with every test above green: the
    fixtures there never had an invalid tier or grant, and where two arms fired on one
    fixture the assertion matched whichever message happened to carry the command's name.
    """

    def _problems(self, mutate) -> list[str]:
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, grants)
        mutate(root / cc.DESKTOP, cmds, grants)
        return cc.check(root)

    def _only(self, problems: list[str], needle: str) -> None:
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(needle, problems[0])

    def _edit_policy(self, base: pathlib.Path, edit) -> None:
        path = base / "command-policy.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        edit(doc["commands"])
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_an_allowlisted_command_also_declared_under_the_wall_is_a_contradiction(self):
        """Only the manifest names it, so the three-way equality arms see it too -- but
        "pick one" is the message that says what is actually wrong."""
        name = sorted(cc.INTENTIONALLY_UNGATED)[0]

        def mutate(base, cmds, grants):
            (base / "build.rs").write_text(_build_rs(cmds + [name]), encoding="utf-8")

        problems = self._problems(mutate)
        self.assertTrue(any("both allowlisted-ungated and declared under the wall" in p
                            and name in p for p in problems), problems)

    def test_a_command_missing_from_the_policy_alone_is_named_as_that(self):
        """lib.rs, build.rs and default.json all carry it; only the policy does not."""
        def mutate(base, cmds, grants):
            more = cmds + ["list_tasks"]
            (base / "src" / "lib.rs").write_text(_lib_rs(more), encoding="utf-8")
            (base / "build.rs").write_text(_build_rs(more), encoding="utf-8")
            (base / "capabilities" / "default.json").write_text(
                _default_cap({**grants, "list_tasks": "allow"}), encoding="utf-8")

        self._only(self._problems(mutate), "gated-registered != policy: only-in-lib.rs=['list_tasks']")

    def test_a_capability_grant_for_a_command_nothing_registers_is_named_as_that(self):
        def mutate(base, cmds, grants):
            (base / "capabilities" / "default.json").write_text(
                _default_cap({**grants, "ghost_cmd": "allow"}), encoding="utf-8")

        self._only(self._problems(mutate),
                   "capability grants != gated-registered: only-in-caps=['ghost_cmd']")

    def test_a_command_with_no_capability_entry_is_named_twice_over(self):
        """The set arm AND the per-command arm; the second is the one that names the
        policy's own grant, and it was reachable by nothing."""
        def mutate(base, cmds, grants):
            trimmed = {c: g for c, g in grants.items() if c != "list_projects"}
            (base / "capabilities" / "default.json").write_text(
                _default_cap(trimmed), encoding="utf-8")

        problems = self._problems(mutate)
        self.assertIn("list_projects: policy grant 'allow' but no capability entry", problems)
        self.assertTrue(any("missing-from-caps=['list_projects']" in p for p in problems), problems)
        self.assertEqual(len(problems), 2, problems)

    def test_an_invalid_tier_is_red(self):
        def mutate(base, cmds, grants):
            self._edit_policy(base, lambda c: c["list_projects"].update(tier="Z"))

        self._only(self._problems(mutate), "list_projects: invalid tier 'Z'")

    def test_an_invalid_grant_is_red(self):
        def mutate(base, cmds, grants):
            self._edit_policy(base, lambda c: c["list_projects"].update(grant="maybe"))

        self._only(self._problems(mutate), "list_projects: invalid grant 'maybe'")


class TheHandlerListIsReadInFull(_Fixture, unittest.TestCase):
    def test_a_command_registered_with_no_module_prefix_is_seen(self):
        """`use commands::greet;` then a bare `greet,` in the list. The old pattern needed
        at least one `mod::`, so this command was registered, ungated, and invisible."""
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, grants)
        lib = _lib_rs(cmds).replace("        ])", "            greet,\n        ])")
        (root / cc.LIB_RS).write_text(lib, encoding="utf-8")
        self.assertIn("greet", cc.registered_commands(root))
        problems = cc.check(root)
        self.assertTrue(any("only-in-lib.rs=['greet']" in p for p in problems), problems)

    def test_an_entry_that_is_not_a_command_path_is_refused_not_skipped(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, grants)
        lib = _lib_rs(cmds).replace(
            "        ])", "            #[cfg(windows)] commands::only_here,\n        ])")
        (root / cc.LIB_RS).write_text(lib, encoding="utf-8")
        with self.assertRaises(SystemExit) as raised:
            cc.registered_commands(root)
        self.assertIn("cannot", str(raised.exception))


class OneCapabilitySource(_Fixture, unittest.TestCase):
    """Tauri enables every file under `capabilities/`; the gate read `default.json` alone."""

    def _root(self) -> pathlib.Path:
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, grants)
        return root

    def test_a_second_capability_file_is_red(self):
        """The hole: `extra.json` granting `allow-decide-approval` left the gate GREEN."""
        root = self._root()
        extra = root / cc.CAPABILITIES_DIR / "extra.json"
        extra.write_text(json.dumps({"identifier": "extra", "windows": ["main"],
                                     "permissions": ["allow-decide-approval"]}), encoding="utf-8")
        problems = cc.check(root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("capabilities/extra.json", problems[0])
        self.assertIn("does not read", problems[0])

    def test_a_capability_file_in_a_subdirectory_or_another_format_is_red(self):
        root = self._root()
        nested = root / cc.CAPABILITIES_DIR / "desktop"
        nested.mkdir()
        (nested / "more.toml").write_text('identifier = "more"\n', encoding="utf-8")
        self.assertTrue(any("capabilities/desktop/more.toml" in p for p in cc.check(root)))

    def test_a_config_that_names_its_own_capability_list_is_red(self):
        root = self._root()
        for name in ("tauri.conf.json", "tauri.linux.conf.json"):
            with self.subTest(conf=name):
                conf = root / cc.DESKTOP / name
                conf.write_text(json.dumps(
                    {"app": {"security": {"capabilities": ["default"]}}}), encoding="utf-8")
                problems = cc.check(root)
                conf.unlink()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(f"{name} sets app.security.capabilities", problems[0])

    def test_a_config_with_no_capability_list_is_green(self):
        root = self._root()
        (root / cc.DESKTOP / "tauri.conf.json").write_text(
            json.dumps({"app": {"security": {"csp": "default-src 'self'"}}}), encoding="utf-8")
        self.assertEqual(cc.check(root), [])

    def test_this_repository_has_exactly_one_capability_source(self):
        repo = pathlib.Path(__file__).resolve().parents[1]
        self.assertEqual(cc.capability_source_problems(repo), [])


class TheExitCode(_Fixture, unittest.TestCase):
    """CI reads `main()`'s return value, and every test above reads `check()`. Turning
    `if problems:` into `if False:` left the whole module green."""

    def _main(self, root: pathlib.Path) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cc.main(["--root", str(root)])
        return code, out.getvalue(), err.getvalue()

    def test_a_consistent_tree_exits_zero_and_says_green(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, grants)
        code, out, _ = self._main(root)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("GREEN:"), out)

    def test_an_inconsistent_tree_exits_one_and_names_the_problem(self):
        root = self._tmp()
        cmds, grants = self._consistent()
        self._write(root, cmds, {**grants, "decide_approval": "allow"})
        code, out, err = self._main(root)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("decide_approval must be DENIED", err)


class TierXProtectionRules(unittest.TestCase):
    """T-052. X is the execution/spend tier; `set_integration_auth_ref`,
    `set_integration_status` and `set_automation_enabled` were all `{"tier": "X",
    "grant": "allow"}` with nothing else, and the file had no way to say so."""

    def _tmp(self) -> pathlib.Path:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return pathlib.Path(d.name)

    def _base(self):
        cmds = ["list_projects", "decide_approval", "reject_approval", "write_file",
                "set_integration_status", "delete_memory"]
        grants = {
            "list_projects": "allow", "decide_approval": "deny", "reject_approval": "allow",
            "write_file": "allow", "set_integration_status": "allow", "delete_memory": "deny",
        }
        return cmds, grants

    def _write(self, root, cmds, grants, protection=None, repo_rs=None):
        helper = CheckCapabilitiesTests()
        helper._write(root, cmds, grants, protection, repo_rs)

    def test_a_tier_x_allow_declaring_protection_none_is_green(self):
        root = self._tmp()
        cmds, grants = self._base()
        self._write(root, cmds, grants)
        self.assertEqual(cc.check(root), [])

    def test_a_tier_x_allow_with_no_declared_protection_is_red(self):
        root = self._tmp()
        cmds, grants = self._base()
        self._write(root, cmds, grants)
        policy_path = root / cc.POLICY
        doc = json.loads(policy_path.read_text(encoding="utf-8"))
        del doc["commands"]["write_file"]["protection"]
        policy_path.write_text(json.dumps(doc), encoding="utf-8")
        problems = cc.check(root)
        self.assertTrue(any("must declare a 'protection'" in p for p in problems), problems)

    def test_native_confirm_backed_by_the_enforcing_constants_is_green(self):
        root = self._tmp()
        cmds, grants = self._base()
        self._write(root, cmds, grants, protection={"set_integration_status": "native-confirm"})
        self.assertEqual(cc.check(root), [])

    def test_native_confirm_without_the_enforcing_constants_is_red(self):
        # The policy claims a gate; the authority layer never passes the tuple. This is the
        # rule that stops a JSON file awarding itself a protection it does not have.
        root = self._tmp()
        cmds, grants = self._base()
        self._write(root, cmds, grants,
                    protection={"set_integration_status": "native-confirm"},
                    repo_rs="pub fn nothing() { approvals::require_and_consume(tx); }\n")
        problems = cc.check(root)
        self.assertTrue(any("never passes" in p for p in problems), problems)

    def test_losing_the_shared_verify_and_consume_helper_is_red(self):
        root = self._tmp()
        cmds, grants = self._base()
        self._write(root, cmds, grants, repo_rs="pub fn nothing() {}\n")
        problems = cc.check(root)
        self.assertTrue(
            any("require_and_consume" in p for p in problems), problems)

    def test_a_command_claiming_native_confirm_that_the_gate_cannot_check_is_red(self):
        root = self._tmp()
        cmds, grants = self._base()
        self._write(root, cmds, grants)
        policy_path = root / cc.POLICY
        doc = json.loads(policy_path.read_text(encoding="utf-8"))
        doc["commands"]["write_file"]["protection"] = "native-confirm"
        policy_path.write_text(json.dumps(doc), encoding="utf-8")
        problems = cc.check(root)
        self.assertTrue(
            any("NATIVE_CONFIRM_ENFORCEMENT names no enforcing constants" in p
                for p in problems), problems)

    def test_a_missing_authority_layer_is_red_and_never_a_silent_pass(self):
        root = self._tmp()
        cmds, grants = self._base()
        self._write(root, cmds, grants, protection={"set_integration_status": "native-confirm"})
        (root / cc.REPO_RS).unlink()
        problems = cc.check(root)
        self.assertTrue(any("is missing" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
