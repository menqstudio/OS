"""Tests for tools/check_capabilities.py — the T-010 capability-inventory CI gate."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_capabilities as cc  # noqa: E402


def _lib_rs(cmds: list[str]) -> str:
    inner = "\n".join(f"            commands::{c}," for c in cmds)
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


def _tier(cmd: str) -> str:
    if cmd in ("decide_approval", "reject_approval"):
        return "A"
    if cmd.startswith("delete_"):
        return "L2"
    return "R"


def _policy(grants: dict[str, str], protection: dict[str, str] | None = None) -> str:
    protection = protection or {}
    commands = {}
    for c, g in grants.items():
        spec = {"tier": _tier(c), "grant": g}
        if _tier(c) == "L2":
            spec["protection"] = protection.get(c, "none")
        commands[c] = spec
    return json.dumps({"window": "main", "commands": commands}, indent=2)


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
    ) -> None:
        base = root / cc.DESKTOP
        (base / "src").mkdir(parents=True, exist_ok=True)
        (base / "capabilities").mkdir(parents=True, exist_ok=True)
        (base / "src" / "lib.rs").write_text(_lib_rs(cmds), encoding="utf-8")
        (base / "build.rs").write_text(_build_rs(cmds), encoding="utf-8")
        (base / "command-policy.json").write_text(_policy(grants, protection), encoding="utf-8")
        (base / "capabilities" / "default.json").write_text(_default_cap(grants), encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
