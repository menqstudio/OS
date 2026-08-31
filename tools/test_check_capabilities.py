"""Tests for tools/check_capabilities.py — the T-010 capability-inventory CI gate."""
from __future__ import annotations

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


class CheckCapabilitiesTests(unittest.TestCase):
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
