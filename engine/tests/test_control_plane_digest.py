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

from bro_protected import (
    MIN_SECURITY_INDEPENDENCE,
    ProtectedManifest,
    ProtectedScopeError,
    authorize_protected_scope,
    compute_control_plane_digest,
    is_digest_member,
    is_protected,
    load_protected_manifest,
    verify_control_plane_digest,
)

MANIFEST = ProtectedManifest(
    protected_roots=("runtime/**", "config/**", "tools/registry.json",
                     ".claude/**", ".git/**", "**/*secret*"),
    digest_roots=("runtime/**", "config/**", "tools/registry.json", ".claude/**"),
    unprotected_exceptions=(),
)

STANDARD_AUTHORITY = {"task_class": "standard-builder"}

SECURITY_AUTHORITY = {
    "task_class": "security-maintenance",
    "owner_approval": True,
    "protected_scope": ["runtime/bro_policy.py"],
    "verification": {"independence_level": MIN_SECURITY_INDEPENDENCE},
}


def real(value) -> pathlib.Path:
    return pathlib.Path(os.path.realpath(str(value)))


class DigestFixture(unittest.TestCase):
    def setUp(self):
        self.root = real(tempfile.mkdtemp(prefix="bro-cp-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.write("runtime/bro_policy.py", "policy")
        self.write("runtime/bro_hook.py", "hook")
        self.write("config/protected-control-plane.json", "{}")
        self.write("tools/registry.json", "{}")
        self.write("tools/other.py", "not protected")
        self.write("src/app.py", "product code")
        self.write("docs/readme.md", "docs")

    def write(self, relative: str, content: str) -> pathlib.Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def digest(self) -> str:
        return compute_control_plane_digest(self.root, MANIFEST)


class MembershipTests(unittest.TestCase):
    def test_new_runtime_file_is_protected_by_default(self):
        self.assertTrue(is_protected(MANIFEST, "runtime/brand_new_module.py"))

    def test_nested_runtime_file_is_protected(self):
        self.assertTrue(is_protected(MANIFEST, "runtime/deep/nested/thing.py"))

    def test_product_path_is_not_protected(self):
        self.assertFalse(is_protected(MANIFEST, "src/app.py"))

    def test_git_is_protected_but_not_a_digest_member(self):
        self.assertTrue(is_protected(MANIFEST, ".git/config"))
        self.assertFalse(is_digest_member(MANIFEST, ".git/config"))

    def test_pycache_bytecode_is_not_a_digest_member(self):
        self.assertFalse(is_digest_member(MANIFEST, "runtime/__pycache__/bro_policy.cpython-313.pyc"))
        self.assertFalse(is_digest_member(MANIFEST, "runtime/bro_policy.pyc"))
        self.assertTrue(is_digest_member(MANIFEST, "runtime/bro_policy.py"))

    def test_exception_removes_protection(self):
        manifest = ProtectedManifest(
            protected_roots=("runtime/**",),
            digest_roots=("runtime/**",),
            unprotected_exceptions=("runtime/product/**",))
        self.assertFalse(is_protected(manifest, "runtime/product/thing.py"))
        self.assertTrue(is_protected(manifest, "runtime/bro_policy.py"))


class DigestTests(DigestFixture):
    def test_unchanged_tree_gives_same_digest(self):
        self.assertEqual(self.digest(), self.digest())

    def test_bytecode_compilation_does_not_change_digest(self):
        # Cold-cache regression: writing runtime/__pycache__/*.pyc after a binding was
        # issued must not flip the control-plane digest (availability bug fix).
        before = self.digest()
        self.write("runtime/__pycache__/bro_policy.cpython-313.pyc", "compiled bytecode blob")
        self.write("runtime/bro_policy.pyc", "stray pyc")
        self.assertEqual(before, self.digest())

    def test_digest_is_sha256_hex(self):
        value = self.digest()
        self.assertEqual(len(value), 64)
        int(value, 16)

    def test_protected_content_change_changes_digest(self):
        before = self.digest()
        self.write("runtime/bro_policy.py", "policy tampered")
        self.assertNotEqual(before, self.digest())

    def test_new_protected_file_changes_digest(self):
        before = self.digest()
        self.write("runtime/bro_backdoor.py", "surprise")
        self.assertNotEqual(before, self.digest())

    def test_protected_deletion_changes_digest(self):
        before = self.digest()
        (self.root / "runtime" / "bro_hook.py").unlink()
        self.assertNotEqual(before, self.digest())

    def test_protected_rename_changes_digest(self):
        before = self.digest()
        os.rename(self.root / "runtime" / "bro_hook.py",
                  self.root / "runtime" / "bro_hook_renamed.py")
        self.assertNotEqual(before, self.digest())

    def test_unprotected_change_keeps_digest(self):
        before = self.digest()
        self.write("src/app.py", "totally different product code")
        self.write("docs/readme.md", "rewritten")
        self.write("tools/other.py", "changed")
        self.assertEqual(before, self.digest())

    def test_manifest_change_changes_digest(self):
        before = self.digest()
        self.write("config/protected-control-plane.json", '{"schema": 1}')
        self.assertNotEqual(before, self.digest())

    def test_separator_style_does_not_affect_membership(self):
        self.assertTrue(is_digest_member(MANIFEST, "runtime/bro_policy.py"))
        self.assertTrue(is_protected(MANIFEST, "runtime\\bro_policy.py"))

    def test_unreadable_protected_file_fails_closed(self):
        def exploding_read(self_path, *args, **kwargs):
            raise OSError("permission denied")

        with patch.object(pathlib.Path, "read_bytes", exploding_read):
            with self.assertRaises(ProtectedScopeError):
                self.digest()

    def test_git_objects_are_not_walked_into_digest(self):
        self.write(".git/objects/ab/cdef", "binary blob")
        before = self.digest()
        self.write(".git/objects/ab/999999", "another blob")
        self.assertEqual(before, self.digest())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_symlink_under_digest_root_denied(self):
        link = self.root / "runtime" / "linked.py"
        try:
            link.symlink_to(self.root / "src" / "app.py")
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        with self.assertRaises(ProtectedScopeError):
            self.digest()


class DigestBindingTests(DigestFixture):
    def test_matching_digest_verifies(self):
        current = self.digest()
        self.assertEqual(verify_control_plane_digest(self.root, MANIFEST, current), current)

    def test_stale_digest_denied(self):
        bound = self.digest()
        self.write("runtime/bro_policy.py", "changed after authority was issued")
        with self.assertRaises(ProtectedScopeError) as caught:
            verify_control_plane_digest(self.root, MANIFEST, bound)
        self.assertIn("control plane changed after session authority was issued",
                      str(caught.exception))

    def test_malformed_bound_digest_denied(self):
        with self.assertRaises(ProtectedScopeError):
            verify_control_plane_digest(self.root, MANIFEST, "nope")

    def test_repository_edit_cannot_refresh_binding(self):
        bound = self.digest()
        self.write("config/protected-control-plane.json",
                   json.dumps({"schema": 1, "protected_roots": ["nothing/**"],
                               "digest_roots": ["nothing/**"],
                               "unprotected_exceptions": []}))
        with self.assertRaises(ProtectedScopeError):
            verify_control_plane_digest(self.root, MANIFEST, bound)


class ScopeAuthorityTests(unittest.TestCase):
    def test_standard_task_denied_on_protected_path(self):
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, STANDARD_AUTHORITY, ["runtime/bro_policy.py"])

    def test_standard_task_denied_on_new_runtime_file(self):
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, STANDARD_AUTHORITY, ["runtime/new.py"])

    def test_standard_task_allowed_outside_protected_roots(self):
        self.assertEqual(
            authorize_protected_scope(MANIFEST, STANDARD_AUTHORITY,
                                      ["src/app.py", "docs/readme.md"]), [])

    def test_security_task_exact_path_allowed(self):
        self.assertEqual(
            authorize_protected_scope(MANIFEST, SECURITY_AUTHORITY, ["runtime/bro_policy.py"]),
            ["runtime/bro_policy.py"])

    def test_security_task_sibling_path_denied(self):
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, SECURITY_AUTHORITY, ["runtime/bro_security.py"])

    def test_security_scope_may_not_be_a_pattern(self):
        authority = dict(SECURITY_AUTHORITY, protected_scope=["runtime/**"])
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, authority, ["runtime/bro_policy.py"])

    def test_missing_task_class_denied(self):
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, {}, ["runtime/bro_policy.py"])

    def test_unknown_task_class_denied(self):
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, {"task_class": "superuser"},
                                      ["runtime/bro_policy.py"])

    def test_missing_owner_approval_denied(self):
        authority = {k: v for k, v in SECURITY_AUTHORITY.items() if k != "owner_approval"}
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, authority, ["runtime/bro_policy.py"])

    def test_independence_below_l4_denied(self):
        authority = dict(SECURITY_AUTHORITY, verification={"independence_level": 3})
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, authority, ["runtime/bro_policy.py"])

    def test_missing_protected_scope_denied(self):
        authority = {k: v for k, v in SECURITY_AUTHORITY.items() if k != "protected_scope"}
        with self.assertRaises(ProtectedScopeError):
            authorize_protected_scope(MANIFEST, authority, ["runtime/bro_policy.py"])


class ManifestLoadTests(unittest.TestCase):
    def test_canonical_manifest_loads(self):
        manifest = load_protected_manifest(ROOT)
        self.assertIn("runtime/**", manifest.protected_roots)
        self.assertIn(".git/**", manifest.protected_roots)
        self.assertNotIn(".git/**", manifest.digest_roots)
        self.assertEqual(manifest.unprotected_exceptions, ())

    def test_canonical_manifest_protects_every_runtime_module(self):
        manifest = load_protected_manifest(ROOT)
        modules = sorted(p.name for p in (ROOT / "runtime").glob("*.py"))
        self.assertTrue(modules)
        for name in modules:
            self.assertTrue(is_protected(manifest, f"runtime/{name}"), name)


if __name__ == "__main__":
    unittest.main()
