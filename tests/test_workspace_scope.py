import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_workspace import (
    Workspace,
    WorkspaceError,
    authorize_path,
    authorize_targets,
    load_workspace,
    matches_pattern,
    normalize_remote,
    verify_repository_binding,
)

DIGEST = "a" * 64

PROHIBITED = (
    ".git/config",
    ".git/credentials",
    "**/.env",
    "**/*secret*",
    "**/*credential*",
    "**/*private-key*",
)


def real(value) -> pathlib.Path:
    return pathlib.Path(os.path.realpath(str(value)))


class WorkspaceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = real(tempfile.mkdtemp(prefix="bro-ws-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.workspace_root = self.tmp / "workspace"
        (self.workspace_root / "src").mkdir(parents=True)
        (self.workspace_root / ".git").mkdir()
        (self.workspace_root / "src" / "app.py").write_text("x", encoding="utf-8")
        (self.workspace_root / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/menqstudio/Bro.git\n',
            encoding="utf-8")
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        (self.outside / "loot.txt").write_text("secrets", encoding="utf-8")

    def workspace(self, **overrides) -> Workspace:
        values = dict(
            workspace_id="bro-primary",
            repository="menqstudio/bro",
            root=self.workspace_root,
            allowed_paths=("**",),
            prohibited_paths=PROHIBITED,
            allowed_remotes=("origin",),
            allowed_remote_repository="menqstudio/bro",
            control_plane_digest=DIGEST,
        )
        values.update(overrides)
        return Workspace(**values)


class PatternTests(unittest.TestCase):
    def test_double_star_matches_everything(self):
        self.assertTrue(matches_pattern("a/b/c.py", "**"))

    def test_root_pattern_matches_nested(self):
        self.assertTrue(matches_pattern("runtime/bro_policy.py", "runtime/**"))
        self.assertTrue(matches_pattern("runtime/a/b.py", "runtime/**"))

    def test_root_pattern_does_not_match_sibling(self):
        self.assertFalse(matches_pattern("runtimex/a.py", "runtime/**"))

    def test_leading_globstar_matches_at_root_and_nested(self):
        self.assertTrue(matches_pattern(".env", "**/.env"))
        self.assertTrue(matches_pattern("a/b/.env", "**/.env"))

    def test_git_config_dot_is_not_stripped(self):
        self.assertTrue(matches_pattern(".git/config", ".git/config"))
        self.assertFalse(matches_pattern("git/config", ".git/config"))


class RemoteTests(unittest.TestCase):
    def test_https_form(self):
        self.assertEqual(
            normalize_remote("https://github.com/menqstudio/Bro.git"), "menqstudio/bro")

    def test_scp_form(self):
        self.assertEqual(
            normalize_remote("git@github.com:menqstudio/Bro.git"), "menqstudio/bro")

    def test_ssh_url_form(self):
        self.assertEqual(
            normalize_remote("ssh://git@github.com/menqstudio/Bro"), "menqstudio/bro")

    def test_other_host_denied(self):
        with self.assertRaises(WorkspaceError):
            normalize_remote("https://gitlab.com/menqstudio/Bro.git")

    def test_lookalike_repo_is_not_equal(self):
        self.assertNotEqual(
            normalize_remote("https://github.com/evil/menqstudio-Bro.git"),
            "menqstudio/bro")


class ScopeTests(WorkspaceFixture):
    def test_inside_workspace_allowed(self):
        resolved = authorize_path(self.workspace(), "src/app.py")
        self.assertEqual(resolved, self.workspace_root / "src" / "app.py")

    def test_workspace_root_itself_allowed(self):
        self.assertEqual(authorize_path(self.workspace(), "."), self.workspace_root)

    def test_outside_absolute_path_denied(self):
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), str(self.outside / "loot.txt"))

    def test_parent_traversal_denied(self):
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), "../outside/loot.txt")

    def test_deep_traversal_denied(self):
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), "src/../../outside/loot.txt")

    def test_prohibited_git_config_denied(self):
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), ".git/config")

    def test_prohibited_env_denied(self):
        (self.workspace_root / "src" / ".env").write_text("k=v", encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), "src/.env")

    def test_prohibited_secret_name_denied(self):
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), "src/my-secret-notes.txt")

    def test_not_in_allowed_paths_denied(self):
        workspace = self.workspace(allowed_paths=("src/**",))
        with self.assertRaises(WorkspaceError):
            authorize_path(workspace, "docs/readme.md")

    def test_empty_target_denied(self):
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), "   ")

    def test_alternate_data_stream_denied(self):
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), "src/app.py:hidden")

    def test_device_path_denied(self):
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), r"\\.\PhysicalDrive0")

    def test_authorize_targets_denies_whole_batch(self):
        with self.assertRaises(WorkspaceError):
            authorize_targets(self.workspace(),
                              ("src/app.py", str(self.outside / "loot.txt")))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_symlink_escape_denied(self):
        link = self.workspace_root / "escape"
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        with self.assertRaises(WorkspaceError):
            authorize_path(self.workspace(), "escape/loot.txt")


class RepositoryBindingTests(WorkspaceFixture):
    def test_matching_remote_accepted(self):
        verify_repository_binding(self.workspace())

    def test_wrong_repository_denied(self):
        (self.workspace_root / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/menqstudio/BroPS.git\n',
            encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            verify_repository_binding(self.workspace())

    def test_missing_remote_denied(self):
        (self.workspace_root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            verify_repository_binding(self.workspace())


class BindingLoadTests(WorkspaceFixture):
    def binding(self, **overrides) -> pathlib.Path:
        values = dict(
            schema=1,
            workspace_id="bro-primary",
            repository="menqstudio/Bro",
            root=str(self.workspace_root),
            control_plane_digest=DIGEST,
            allowed_paths=["**"],
            prohibited_paths=list(PROHIBITED),
            allowed_remotes=["origin"],
            allowed_remote_repository="menqstudio/Bro",
            active=True,
        )
        values.update(overrides)
        path = self.tmp / "binding.json"
        path.write_text(json.dumps(values), encoding="utf-8")
        return path

    def test_valid_binding_loads(self):
        with patch.dict(os.environ, {"BRO_WORKSPACE_BINDING": str(self.binding())}):
            workspace = load_workspace(ROOT)
        self.assertEqual(workspace.workspace_id, "bro-primary")
        self.assertEqual(workspace.allowed_remote_repository, "menqstudio/bro")

    def test_missing_binding_denied(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(WorkspaceError):
                load_workspace(ROOT)

    def test_inactive_binding_denied(self):
        path = self.binding(active=False)
        with patch.dict(os.environ, {"BRO_WORKSPACE_BINDING": str(path)}):
            with self.assertRaises(WorkspaceError):
                load_workspace(ROOT)

    def test_binding_without_digest_denied(self):
        path = self.binding(control_plane_digest="short")
        with patch.dict(os.environ, {"BRO_WORKSPACE_BINDING": str(path)}):
            with self.assertRaises(WorkspaceError):
                load_workspace(ROOT)

    def test_relative_binding_path_denied(self):
        with patch.dict(os.environ, {"BRO_WORKSPACE_BINDING": "binding.json"}):
            with self.assertRaises(WorkspaceError):
                load_workspace(ROOT)

    def test_binding_inside_repository_denied(self):
        inside = ROOT / "bro-test-binding.json"
        inside.write_text(json.dumps({"schema": 1}), encoding="utf-8")
        self.addCleanup(inside.unlink)
        with patch.dict(os.environ, {"BRO_WORKSPACE_BINDING": str(inside)}):
            with self.assertRaises(WorkspaceError):
                load_workspace(ROOT)


if __name__ == "__main__":
    unittest.main()
