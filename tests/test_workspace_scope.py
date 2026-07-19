import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from _operator_pin import use_operator_pin
from broctl import build_registry, generate_key, sign_payload
from bro_workspace import (
    Workspace,
    WorkspaceError,
    authorize_path,
    authorize_targets,
    git_config_path,
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

    def test_bare_directory_pattern_protects_its_contents(self):
        # A prohibited bare directory (no wildcard) must also match everything beneath
        # it, mirroring bro_security.path_allowed — otherwise `.git` listed without
        # `/**` would silently under-block `.git/config`.
        self.assertTrue(matches_pattern(".git", ".git"))
        self.assertTrue(matches_pattern(".git/config", ".git"))
        self.assertTrue(matches_pattern("runtime/bro_policy.py", "runtime"))
        self.assertFalse(matches_pattern("gitignore", ".git"))       # not a child
        self.assertFalse(matches_pattern("runtimex/a.py", "runtime"))


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


class GitConfigResolutionTests(WorkspaceFixture):
    """The architecture requires builders to run in isolated worktrees, where
    `.git` is a file rather than a directory. Resolving the config only for a
    plain checkout would break the enforcement path in the exact layout the
    design mandates."""

    def test_plain_checkout_config(self):
        self.assertEqual(git_config_path(self.workspace_root),
                         self.workspace_root / ".git" / "config")

    def make_worktree(self, *, commondir: bool) -> pathlib.Path:
        main_git = self.tmp / "main" / ".git"
        (main_git / "worktrees" / "wt").mkdir(parents=True)
        (main_git / "config").write_text(
            '[remote "origin"]\n\turl = git@github.com:menqstudio/Bro.git\n',
            encoding="utf-8")
        linked = self.tmp / "linked"
        linked.mkdir()
        gitdir = main_git / "worktrees" / "wt"
        (linked / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        if commondir:
            (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        else:
            (gitdir / "config").write_text(
                '[remote "origin"]\n\turl = git@github.com:menqstudio/Bro.git\n',
                encoding="utf-8")
        return linked

    def test_worktree_resolves_through_commondir(self):
        linked = self.make_worktree(commondir=True)
        self.assertEqual(real(git_config_path(linked)),
                         real(self.tmp / "main" / ".git" / "config"))

    def test_worktree_without_commondir_uses_gitdir(self):
        linked = self.make_worktree(commondir=False)
        self.assertTrue(git_config_path(linked).is_file())

    def test_worktree_remote_verifies(self):
        linked = self.make_worktree(commondir=True)
        verify_repository_binding(self.workspace(root=real(linked)))

    def test_missing_git_denied(self):
        bare = self.tmp / "nogit"
        bare.mkdir()
        with self.assertRaises(WorkspaceError):
            git_config_path(bare)

    def test_unparsable_git_link_denied(self):
        broken = self.tmp / "broken"
        broken.mkdir()
        (broken / ".git").write_text("not a gitdir line\n", encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            git_config_path(broken)


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


_OMIT = object()


class BindingLoadTests(WorkspaceFixture):
    """load_workspace trusts ONLY an operator-signed binding (H-1) with an
    enforced expiry (M-8). The fixture stands in for the offline operator: it
    generates a test operator-root key, writes a registry signed by that key
    into a scratch repository root, and exports the same key as the external
    CI pin, so verify_artifact's Ed25519 verification runs for real against
    the pinned trust anchor. Negative fixtures are signed too (except the
    signature-gate tests themselves), so each one still fails on its own
    specific property rather than at the signature gate."""

    def setUp(self):
        super().setUp()
        self.now = int(time.time())
        self.repo_root = self.tmp / "repo"
        (self.repo_root / "config").mkdir(parents=True)
        self.operator = generate_key("operator-root", "op", False)
        (self.repo_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry([self.operator], self.now, 100_000)),
            encoding="utf-8")
        use_operator_pin(self, self.operator["public_key"])
        # The raw env pin is honoured only under the CI flag; the fixture is CI.
        ci = patch.dict(os.environ, {"BRO_ENV": "ci"})
        ci.start()
        self.addCleanup(ci.stop)

    def binding(self, *, signed=True, key=None, **overrides) -> pathlib.Path:
        key = key or self.operator
        values = dict(
            schema=1,
            artifact_type="workspace-binding",
            key_id=key["key_id"],
            workspace_id="bro-primary",
            repository="menqstudio/Bro",
            root=str(self.workspace_root),
            control_plane_digest=DIGEST,
            allowed_paths=["**"],
            prohibited_paths=list(PROHIBITED),
            allowed_remotes=["origin"],
            allowed_remote_repository="menqstudio/Bro",
            expires_at_epoch=self.now + 3600,
            active=True,
        )
        values.update(overrides)
        payload = {k: v for k, v in values.items() if v is not _OMIT}
        document = sign_payload(key["private_key"], payload) if signed else payload
        path = self.tmp / "binding.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def load(self, path: pathlib.Path):
        with patch.dict(os.environ, {"BRO_WORKSPACE_BINDING": str(path)}):
            return load_workspace(self.repo_root)

    def test_valid_binding_loads(self):
        workspace = self.load(self.binding())
        self.assertEqual(workspace.workspace_id, "bro-primary")
        self.assertEqual(workspace.allowed_remote_repository, "menqstudio/bro")
        self.assertEqual(workspace.expires_at_epoch, self.now + 3600)

    def test_missing_binding_denied(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(WorkspaceError, "missing BRO_WORKSPACE_BINDING"):
                load_workspace(self.repo_root)

    def test_unsigned_binding_denied(self):
        # Unsigned BY DESIGN (H-1): the raw Phase A payload — the exact document an
        # agent could write itself and point the env var at — must die at the
        # signature gate before any field is trusted.
        with self.assertRaisesRegex(WorkspaceError, "not operator-signed"):
            self.load(self.binding(signed=False))

    def test_forged_signature_denied(self):
        # Signed, but by a key the operator never pinned: an attacker minting
        # their own "operator" key must not pass the registry-anchored verify.
        intruder = generate_key("operator-root", "intruder", False)
        with self.assertRaisesRegex(WorkspaceError, "not operator-signed"):
            self.load(self.binding(key=intruder))

    def test_inactive_binding_denied(self):
        # Signed so the failure is the active gate, not the signature gate.
        with self.assertRaisesRegex(WorkspaceError, "not active"):
            self.load(self.binding(active=False))

    def test_binding_without_digest_denied(self):
        with self.assertRaisesRegex(WorkspaceError, "control_plane_digest"):
            self.load(self.binding(control_plane_digest="short"))

    def test_expired_binding_denied(self):
        # M-8: operator-signed but past its stamped lifetime — still refused.
        with self.assertRaisesRegex(WorkspaceError, "expired"):
            self.load(self.binding(expires_at_epoch=self.now - 10))

    def test_binding_without_expiry_denied(self):
        # M-8: a signed binding with no enforced lifetime would be live forever.
        with self.assertRaisesRegex(WorkspaceError, "expires_at_epoch"):
            self.load(self.binding(expires_at_epoch=_OMIT))

    def test_relative_binding_path_denied(self):
        with patch.dict(os.environ, {"BRO_WORKSPACE_BINDING": "binding.json"}):
            with self.assertRaisesRegex(WorkspaceError, "absolute"):
                load_workspace(self.repo_root)

    def test_binding_inside_repository_denied(self):
        inside = self.repo_root / "bro-test-binding.json"
        inside.write_text(json.dumps({"schema": 1}), encoding="utf-8")
        with patch.dict(os.environ, {"BRO_WORKSPACE_BINDING": str(inside)}):
            with self.assertRaisesRegex(WorkspaceError, "outside the repository"):
                load_workspace(self.repo_root)


if __name__ == "__main__":
    unittest.main()
